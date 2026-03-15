import logging
from typing import Dict, Any, List
import poly_arb_bot.config as cfg
from poly_arb_bot.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
import json
import os
import requests
from datetime import datetime


MAX_DAILY_LOSS = 10.0  # Circuit Breaker limit ($)
MAX_DAILY_TRADES = 500  # Maximum trades per day
STATS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "daily_stats.json")

logger = logging.getLogger(__name__)


class ExecutionEngine:
    def __init__(self, adapter):
        self.adapter = adapter
        self.daily_pnl = 0.0
        self.daily_trade_count = 0
        self.last_reset = datetime.now().date()
        self._load_stats()

    def _load_stats(self):
        try:
            if os.path.exists(STATS_FILE):
                with open(STATS_FILE, "r") as f:
                    data = json.load(f)
                    saved_date = datetime.strptime(data.get("date", ""), "%Y-%m-%d").date()
                    if saved_date == datetime.now().date():
                        self.daily_pnl = data.get("pnl", 0.0)
                        self.daily_trade_count = data.get("trade_count", 0)
                    else:
                        self.daily_pnl = 0.0
                        self.daily_trade_count = 0
        except Exception as e:
            logger.warning(f"Could not load stats: {e}")
            self.daily_pnl = 0.0
            self.daily_trade_count = 0

    def _save_stats(self):
        try:
            with open(STATS_FILE, "w") as f:
                json.dump({
                    "date": datetime.now().date().strftime("%Y-%m-%d"),
                    "pnl": self.daily_pnl,
                    "trade_count": self.daily_trade_count
                }, f)
        except Exception as e:
            logger.warning(f"Could not save stats: {e}")

    def send_telegram_alert(self, message: str):
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            return
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            logger.error(f"Telegram Error: {e}")

    def check_safety(self) -> bool:
        """Check all safety limits before trading."""
        # Check daily reset
        today = datetime.now().date()
        if today != self.last_reset:
            logger.info(f"New day detected. Resetting daily stats (prev PnL: ${self.daily_pnl:.2f}).")
            self.daily_pnl = 0.0
            self.daily_trade_count = 0
            self.last_reset = today
            self._save_stats()
        
        # Check PnL Limit
        if self.daily_pnl <= -MAX_DAILY_LOSS:
            msg = f"SAFETY STOP: Daily Loss Limit Reached (${self.daily_pnl:.2f}). Trading Halted."
            logger.error(msg)
            self.send_telegram_alert(f"<b>{msg}</b>")
            return False
        
        # Check trade count limit
        if self.daily_trade_count >= MAX_DAILY_TRADES:
            msg = f"SAFETY STOP: Daily Trade Count Limit Reached ({self.daily_trade_count}). Trading Halted."
            logger.error(msg)
            self.send_telegram_alert(f"<b>{msg}</b>")
            return False
        
        return True

    def record_trade_result(self, profit_loss: float):
        self.daily_pnl += profit_loss
        self.daily_trade_count += 1
        self._save_stats()
        logger.info(f"Trade recorded. Daily PnL: ${self.daily_pnl:.2f} | Trades today: {self.daily_trade_count}")

    def execute_arbitrage(self, orders: List[Dict[str, Any]]):
        """
        Execute a batch of orders for an arbitrage opportunity.
        Each order dict should have:
        - token_id: CLOB token ID
        - side: 'BUY' or 'SELL'
        - price: limit price per share (0-1)
        - size: dollar amount to spend (USDC)
        """
        if not orders:
            logger.info("No orders to execute.")
            return []

        total_value = sum(o.get('size', 0) for o in orders)
        logger.info(f"Preparing to execute {len(orders)} orders. Total Value: ${total_value:.2f}")

        # --- PAPER MODE ---
        if cfg.EXECUTION_MODE != "LIVE":
            logger.info(f"[PAPER MODE] Simulated execution of {len(orders)} orders:")
            simulated_results = []
            for o in orders:
                shares = o['size'] / o['price'] if o['price'] > 0 else 0
                logger.info(f"  [PAPER] {o['side']} ${o['size']:.2f} ({shares:.1f} shares) of ...{o['token_id'][-8:]} @ {o['price']:.4f}")
                simulated_results.append({"order": o, "response": {"status": "paper"}, "filled": False, "ok": True})
            
            # Send telegram alert even in paper mode
            msg = "<b>[PAPER] Arb Signal</b>\n"
            for o in orders:
                msg += f"{o['side']} ${o['size']:.2f} @ {o['price']:.4f}\n"
            self.send_telegram_alert(msg)
            return simulated_results

        # --- LIVE EXECUTION ---
        if not self.check_safety():
            return []

        logger.info("LIVE EXECUTION STARTING...")

        successful_orders = 0
        failed_orders = 0
        execution_results = []

        for order in orders:
            try:
                resp = self.adapter.place_limit_order(
                    token_id=order['token_id'],
                    side=order['side'],
                    price=order['price'],
                    size=order['size']
                )
                if resp:
                    successful_orders += 1
                    logger.info(f"Order Placed: {resp}")
                    status = str(resp.get("status", "")).lower() if isinstance(resp, dict) else ""
                    taking = str(resp.get("takingAmount", "")).strip() if isinstance(resp, dict) else ""
                    making = str(resp.get("makingAmount", "")).strip() if isinstance(resp, dict) else ""
                    # Treat only immediate matches (or explicit non-zero fill amounts) as filled.
                    try:
                        taking_val = float(taking) if taking else 0.0
                        making_val = float(making) if making else 0.0
                    except ValueError:
                        taking_val = making_val = 0.0
                    filled = (status == "matched") or (taking_val > 0 and making_val > 0)
                    # Capture order_id for possible unwind cancellation
                    order_id = resp.get("orderID") or resp.get("order_id") or resp.get("id") if isinstance(resp, dict) else None
                    execution_results.append({
                        "order": order, "response": resp,
                        "filled": filled, "ok": True,
                        "order_id": order_id,
                    })
                    self.send_telegram_alert(
                        f"<b>Order Placed!</b>\n"
                        f"Token: ...{order['token_id'][-8:]}\n"
                        f"Side: {order['side']}\n"
                        f"Size: ${order['size']:.2f}\n"
                        f"Price: {order['price']:.4f}"
                    )
                else:
                    failed_orders += 1
                    logger.error(f"Order Failed for ...{order['token_id'][-8:]}")
                    execution_results.append({
                        "order": order, "response": None,
                        "filled": False, "ok": False, "order_id": None,
                    })
                    self.send_telegram_alert(
                        f"<b>Order Failed!</b>\n"
                        f"Token: ...{order['token_id'][-8:]}\n"
                        f"Reason: Null response from exchange"
                    )

            except Exception as e:
                failed_orders += 1
                logger.error(f"Execution Error: {e}", exc_info=True)
                execution_results.append({
                    "order": order, "response": {"error": str(e)},
                    "filled": False, "ok": False, "order_id": None,
                })
                self.send_telegram_alert(f"<b>Execution Error:</b> {str(e)[:200]}")

        # Track trade count (even partial fills count)
        if successful_orders > 0:
            self.daily_trade_count += 1
            self._save_stats()

        logger.info(f"Batch Complete. Successful: {successful_orders}, Failed: {failed_orders}")

        # --- PARTIAL EXECUTION AUTO-UNWIND ---
        # If this was a multi-leg batch and some legs failed, cancel any unfilled
        # orders that already landed on the exchange to avoid unhedged exposure.
        if failed_orders > 0 and successful_orders > 0 and len(orders) >= 2:
            logger.warning(
                f"PARTIAL EXECUTION: {successful_orders}/{len(orders)} orders succeeded. "
                f"Attempting to cancel unfilled legs to reduce unhedged exposure."
            )
            cancelled_count = 0
            for r in execution_results:
                # Cancel orders that were placed on exchange but NOT filled
                if r.get("ok") and not r.get("filled") and r.get("order_id"):
                    try:
                        cancel_resp = self.adapter.cancel_order(r["order_id"])
                        if cancel_resp:
                            cancelled_count += 1
                            logger.info(
                                f"Unwind: cancelled unfilled order {r['order_id'][:16]}... "
                                f"(...{r['order']['token_id'][-8:]} {r['order']['side']})"
                            )
                    except Exception as ce:
                        logger.warning(f"Unwind cancel failed for {r.get('order_id', '?')[:16]}: {ce}")

            alert_msg = (
                f"<b>⚠️ PARTIAL EXECUTION — AUTO-UNWIND</b>\n"
                f"{successful_orders}/{len(orders)} legs filled.\n"
                f"Cancelled {cancelled_count} unfilled leg(s) to reduce exposure.\n"
                f"Please verify open positions on the dashboard."
            )
            self.send_telegram_alert(alert_msg)
        elif failed_orders > 0 and successful_orders == 0:
            # Complete failure — nothing to unwind
            logger.warning(f"ALL {failed_orders} orders failed. No unhedged exposure.")

        return execution_results
