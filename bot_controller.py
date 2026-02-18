"""
Bot Controller - Manages the arbitrage bot lifecycle with shared state
for the web dashboard to read/control.
"""
import logging
import threading
import time
import json
import csv
import os
import re
import numpy as np
import requests as _requests
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from collections import deque
from pathlib import Path

from poly_arb_bot.config import (
    LOG_LEVEL, EXECUTION_MODE, MIN_PROFIT_THRESHOLD, 
    MAX_POSITION_SIZE, POLYMARKET_API_KEY, PRIVATE_KEY, OPENAI_API_KEY
)
from poly_arb_bot.adapters.polymarket import PolymarketAdapter
from poly_arb_bot.engine.math import MarketMath
from poly_arb_bot.engine.execution import ExecutionEngine
from poly_arb_bot.engine.dependency import DependencyDetector

logger = logging.getLogger(__name__)

# --- Constants ---
POLYMARKET_FEE_RATE = 0.01
SLIPPAGE_BUFFER = 0.005
TRADE_COOLDOWN_SECONDS = int(os.getenv("TRADE_COOLDOWN_SECONDS", "15"))
MAX_PAIRS_TO_ANALYZE = 15
MAX_MARKETS_TO_FETCH = 1000
ENTRY_BAND = 0.01
MAX_SPREAD_PCT = 0.35
MIN_EXEC_PRICE = 0.01
MAX_EXEC_PRICE = 0.99
MAX_LIVE_ORDERS = 12
STALE_ORDER_TIMEOUT_SECONDS = 90
CASH_RESERVE_RATIO = float(os.getenv("CASH_RESERVE_RATIO", "0.30"))
MAX_CAPITAL_PER_TRADE_RATIO = float(os.getenv("MAX_CAPITAL_PER_TRADE_RATIO", "0.15"))

# --- Quick-Flip Take-Profit / Stop-Loss ---
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "0.03"))   # Exit when +3% above entry
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "0.08"))       # Cut loss at -8% below entry
FLIP_CHECK_INTERVAL = int(os.getenv("FLIP_CHECK_SECONDS", "10"))  # Check exits every 10s

# --- Position Recycler Settings (fast turnover) ---
RECYCLE_ENABLED = os.getenv("RECYCLE_ENABLED", "1").strip().lower() in ("1", "true", "yes")
RECYCLE_INTERVAL_SECONDS = int(os.getenv("RECYCLE_INTERVAL_MINUTES", "60")) * 60  # every 60 min
RECYCLE_MIN_HOLD_SECONDS = int(os.getenv("RECYCLE_MIN_HOLD_MINUTES", "30")) * 60  # 30 min minimum hold
RECYCLE_MAX_HOLD_SECONDS = int(os.getenv("RECYCLE_MAX_HOLD_HOURS", "4")) * 3600   # 4h force sell
RECYCLE_MIN_CASH_RESERVE = float(os.getenv("RECYCLE_MIN_CASH", "10.0"))

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
OPPORTUNITY_LOG_FILE = os.path.join(PROJECT_DIR, "opportunities.csv")
DATA_DIR = os.path.join(PROJECT_DIR, "data")
RUNTIME_STATE_FILE = os.path.join(DATA_DIR, "runtime_state.json")


def convert_outcomes_to_vectors(outcome_tuples: List[Tuple[str, str]]) -> np.array:
    vectors = []
    for pair in outcome_tuples:
        vec = []
        if pair[0].upper() == "YES": vec.extend([1, 0])
        else: vec.extend([0, 1])
        if pair[1].upper() == "YES": vec.extend([1, 0])
        else: vec.extend([0, 1])
        vectors.append(vec)
    return np.array(vectors)


class MonitoringSession:
    def __init__(self, markets: List[Dict], valid_outcomes: np.array):
        self.markets = markets
        self.valid_outcomes = valid_outcomes
        self.token_map = {}
        self.prices = np.zeros(len(markets) * 2)
        self.token_lookup = {}
        self.prices_initialized = set()
        self.last_trade_time = 0
        self.best_bids = {}
        self.best_asks = {}
        
        for i, m in enumerate(markets):
            tokens = m.get("clobTokenIds", [])
            outcomes = m.get("outcomes", ["No", "Yes"])
            if isinstance(outcomes, str):
                try: outcomes = json.loads(outcomes)
                except: outcomes = ["No", "Yes"]
            if len(tokens) < 2: continue

            yes_idx, no_idx = -1, -1
            for idx, label in enumerate(outcomes):
                if "Yes" in str(label) or "YES" in str(label): yes_idx = idx
                elif "No" in str(label) or "NO" in str(label): no_idx = idx
            if yes_idx == -1: yes_idx = 1
            if no_idx == -1: no_idx = 0

            idx_yes = i * 2 + 0
            idx_no = i * 2 + 1
            self.token_map[tokens[yes_idx]] = idx_yes
            self.token_map[tokens[no_idx]] = idx_no
            self.token_lookup[idx_yes] = tokens[yes_idx]
            self.token_lookup[idx_no] = tokens[no_idx]

            try:
                op = m.get("outcomePrices", ["0.5", "0.5"])
                if isinstance(op, str): op = json.loads(op)
                self.prices[idx_yes] = float(op[yes_idx]) if len(op) > yes_idx else 0.5
                self.prices[idx_no] = float(op[no_idx]) if len(op) > no_idx else 0.5
            except Exception:
                self.prices[idx_yes] = 0.5
                self.prices[idx_no] = 0.5

    def update_price(self, token_id, new_price, best_bid=None, best_ask=None):
        if token_id in self.token_map:
            idx = self.token_map[token_id]
            self.prices[idx] = new_price
            self.prices_initialized.add(idx)
            if best_bid is not None: self.best_bids[token_id] = best_bid
            if best_ask is not None: self.best_asks[token_id] = best_ask
            return True
        return False

    def has_valid_prices(self):
        return np.all(self.prices > 0.001)

    def can_trade(self):
        return (time.time() - self.last_trade_time) > TRADE_COOLDOWN_SECONDS

    def mark_traded(self):
        self.last_trade_time = time.time()

    def run_analysis(self):
        if not self.has_valid_prices(): return 0.0, None
        mu_star = MarketMath.frank_wolfe_projection(self.prices, self.valid_outcomes)
        profit = MarketMath.calculate_profit(self.prices, mu_star)
        return profit, mu_star

    def to_dict(self):
        return {
            "markets": [m.get("question", "?")[:80] for m in self.markets],
            "prices": self.prices.tolist(),
            "num_tokens": len(self.token_map),
            "last_trade": datetime.fromtimestamp(self.last_trade_time).isoformat() if self.last_trade_time > 0 else "Never",
        }


class BotController:
    """Singleton controller for the arbitrage bot with shared state."""

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        
        self._trade_lock = threading.Lock()
        
        # Shared state for the dashboard
        self.state = {
            "status": "stopped",        # stopped, starting, running, error
            "mode": EXECUTION_MODE,
            "started_at": None,
            "uptime": 0,
            "pairs_monitored": 0,
            "tokens_subscribed": 0,
            "opportunities_found": 0,
            "raw_opportunities": 0,
            "tradable_opportunities": 0,
            "trades_executed": 0,
            "daily_pnl": 0.0,
            "realized_pnl": 0.0,
            "wallet_balance": None,
            "reserved_in_live_orders_estimate": 0.0,
            "live_orders_count": 0,
            "position_value_estimate": 0.0,
            "unrealized_pnl_estimate": 0.0,
            "net_equity_estimate": None,
            "open_positions_count": 0,
            "last_error": None,
            "min_profit_threshold": MIN_PROFIT_THRESHOLD,
            "max_position_size": MAX_POSITION_SIZE,
            "effective_threshold": MIN_PROFIT_THRESHOLD + POLYMARKET_FEE_RATE + SLIPPAGE_BUFFER,
        }
        
        # Recent activity logs (ring buffer)
        self.recent_logs: deque = deque(maxlen=200)
        self.recent_opportunities: deque = deque(maxlen=50)
        self.recent_trades: deque = deque(maxlen=50)
        self.sessions_info: List[Dict] = []
        self.position_book: Dict[str, Dict[str, float]] = {}
        
        # Config validation
        self.state["config_ok"] = bool(POLYMARKET_API_KEY and PRIVATE_KEY)
        self.state["llm_ok"] = bool(OPENAI_API_KEY)
        self._load_runtime_state()
        
        # Failover role
        self._role = os.getenv("BOT_ROLE", "primary").strip().lower()
        self._primary_health_url = os.getenv("PRIMARY_HEALTH_URL", "").strip()
        self._failover_running = False
        self.state["role"] = self._role
        
        # Auto-start or standby watchdog
        auto_start = os.getenv("AUTO_START", "0").strip().lower() in ("1", "true", "yes")
        if self._role == "standby" and self._primary_health_url:
            logger.info(f"STANDBY mode - watching primary at {self._primary_health_url}")
            self._failover_thread = threading.Thread(target=self._failover_watchdog, daemon=True)
            self._failover_thread.start()
        elif auto_start:
            logger.info("AUTO_START enabled - bot will start automatically in 3s")
            threading.Timer(3.0, self._auto_start).start()

    def _auto_start(self):
        """Auto-start the bot after a short delay to let services initialize."""
        logger.info("Auto-starting bot...")
        result = self.start()
        logger.info(f"Auto-start result: {result}")

    def _check_primary_alive(self) -> bool:
        """Check if the primary node is alive via its health endpoint."""
        try:
            resp = _requests.get(self._primary_health_url, timeout=5)
            data = resp.json()
            return resp.status_code == 200 and data.get("bot") == "running"
        except Exception:
            return False

    def _failover_watchdog(self):
        """Standby watchdog: monitor primary, take over if it goes down."""
        FAIL_THRESHOLD = 3          # consecutive failures before takeover
        CHECK_INTERVAL = 30         # seconds between health checks
        RECOVERY_CHECK = 60         # seconds between checks once we're active
        consecutive_fails = 0
        
        logger.info(f"Failover watchdog started (threshold={FAIL_THRESHOLD} fails, interval={CHECK_INTERVAL}s)")
        time.sleep(10)  # initial delay to let everything settle
        
        while True:
            primary_alive = self._check_primary_alive()
            bot_running = self.state["status"] == "running"
            
            if primary_alive:
                consecutive_fails = 0
                if bot_running and self._failover_running:
                    logger.info("PRIMARY is back online - stopping standby trading")
                    self.stop()
                    self._failover_running = False
                    self._log("INFO", "Primary recovered - standby stopped trading")
                time.sleep(CHECK_INTERVAL)
            else:
                consecutive_fails += 1
                logger.warning(f"Primary health check failed ({consecutive_fails}/{FAIL_THRESHOLD})")
                
                if consecutive_fails >= FAIL_THRESHOLD and not bot_running:
                    logger.info("PRIMARY DOWN - STANDBY TAKING OVER")
                    self._log("WARN", "Primary appears down - standby taking over!")
                    self._failover_running = True
                    self.start()
                
                time.sleep(CHECK_INTERVAL if not bot_running else RECOVERY_CHECK)

    def _log(self, level: str, message: str):
        """Add log entry to recent logs and standard logger."""
        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "level": level,
            "msg": message
        }
        self.recent_logs.append(entry)
        getattr(logger, level.lower(), logger.info)(message)

    def _load_runtime_state(self):
        """Restore persisted wallet/position state across restarts."""
        try:
            path = Path(RUNTIME_STATE_FILE)
            if not path.exists():
                return
            data = json.loads(path.read_text())
            wb = data.get("wallet_balance")
            self.state["wallet_balance"] = float(wb) if wb is not None else None
            self.state["reserved_in_live_orders_estimate"] = float(data.get("reserved_in_live_orders_estimate", 0.0))
            self.state["live_orders_count"] = int(data.get("live_orders_count", 0))

            raw_pos = data.get("position_book", {})
            restored: Dict[str, Dict[str, float]] = {}
            for token_id, p in raw_pos.items():
                shares = float(p.get("shares", 0.0))
                last_mid = float(p.get("last_mid", 0.0))
                avg_entry = float(p.get("avg_entry", last_mid))
                if abs(shares) < 1e-8:
                    continue
                restored[str(token_id)] = {
                    "shares": shares,
                    "last_mid": last_mid,
                    "avg_entry": avg_entry,
                    "opened_at": float(p.get("opened_at", time.time())),
                }
            self.position_book = restored
            self._recompute_equity()
            logger.info(
                "Restored runtime state: %d positions, wallet=%s",
                len(self.position_book),
                self.state.get("wallet_balance"),
            )
        except Exception as e:
            logger.warning(f"Failed to load runtime state: {e}")

    def _save_runtime_state(self):
        """Persist runtime wallet/position state to disk."""
        try:
            Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
            payload = {
                "saved_at": datetime.utcnow().isoformat(),
                "wallet_balance": self.state.get("wallet_balance"),
                "reserved_in_live_orders_estimate": self.state.get("reserved_in_live_orders_estimate", 0.0),
                "live_orders_count": self.state.get("live_orders_count", 0),
                "position_book": self.position_book,
                "position_value_estimate": self.state.get("position_value_estimate", 0.0),
                "unrealized_pnl_estimate": self.state.get("unrealized_pnl_estimate", 0.0),
                "realized_pnl": self.state.get("realized_pnl", 0.0),
                "net_equity_estimate": self.state.get("net_equity_estimate"),
                "open_positions_count": self.state.get("open_positions_count", 0),
            }
            tmp = Path(RUNTIME_STATE_FILE + ".tmp")
            tmp.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=True))
            tmp.replace(Path(RUNTIME_STATE_FILE))
        except Exception as e:
            logger.warning(f"Failed to save runtime state: {e}")

    def _hydrate_positions_from_exchange(self, adapter):
        """
        Best-effort bootstrap from exchange positions on startup.
        This is optional and only runs if the adapter client exposes a positions API.
        """
        if self.state.get("mode") != "LIVE":
            return
        if self.position_book:
            return
        client = getattr(adapter, "client", None)
        if client is None:
            return
        try:
            raw = None
            for method_name in ("get_positions", "get_open_positions", "get_user_positions"):
                method = getattr(client, method_name, None)
                if callable(method):
                    raw = method()
                    if raw:
                        break
            if not raw:
                return

            if isinstance(raw, dict):
                pos_list = raw.get("positions") or raw.get("data") or raw.get("items") or []
            elif isinstance(raw, list):
                pos_list = raw
            else:
                return

            restored = 0
            for p in pos_list:
                if not isinstance(p, dict):
                    continue
                token_id = str(p.get("asset_id") or p.get("token_id") or p.get("id") or "")
                if not token_id:
                    continue
                qty = p.get("size", p.get("amount", p.get("quantity", p.get("shares", 0.0))))
                try:
                    shares = float(qty)
                except Exception:
                    continue
                side = str(p.get("side") or p.get("direction") or "").upper()
                if side in ("SELL", "SHORT"):
                    shares = -abs(shares)
                if abs(shares) < 1e-8:
                    continue
                mark = p.get("mark_price", p.get("mid_price", p.get("avg_entry_price", p.get("price", 0.5))))
                try:
                    last_mid = float(mark)
                except Exception:
                    last_mid = 0.5
                entry_raw = p.get("avg_entry_price", p.get("entry_price", last_mid))
                try:
                    avg_entry = float(entry_raw)
                except Exception:
                    avg_entry = last_mid
                self.position_book[token_id] = {
                    "shares": shares,
                    "last_mid": last_mid,
                    "avg_entry": avg_entry,
                }
                restored += 1

            if restored > 0:
                self._recompute_equity()
                self._save_runtime_state()
                self._log("INFO", f"Hydrated {restored} positions from exchange API.")
        except Exception as e:
            self._log("WARNING", f"Position hydration skipped: {e}")

    def start(self):
        with self._lock:
            if self.state["status"] == "running":
                return {"ok": False, "msg": "Bot is already running"}
            
            self._stop_event.clear()
            self.state["status"] = "starting"
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            return {"ok": True, "msg": "Bot starting..."}

    def _estimate_live_order_reserve(self, adapter) -> tuple[float, int]:
        """
        Estimate reserved collateral from currently-open orders.
        Best effort: sums BUY order notionals from non-terminal statuses.
        """
        orders = adapter.get_open_orders() if adapter else []
        if not orders:
            return 0.0, 0

        terminal = {"matched", "filled", "cancelled", "canceled", "rejected", "failed", "expired", "executed"}
        reserved = 0.0
        live_count = 0

        for o in orders:
            if not isinstance(o, dict):
                continue
            status = str(o.get("status") or o.get("state") or "").strip().lower()
            if status and status in terminal:
                continue

            side = str(o.get("side") or o.get("order_side") or "").strip().upper()
            if side == "SELL":
                # SELL orders reserve inventory shares, not collateral cash.
                continue

            price_raw = (
                o.get("price")
                or o.get("limit_price")
                or o.get("limitPrice")
                or o.get("avg_price")
                or o.get("avgPrice")
                or 0
            )
            try:
                price = float(price_raw)
            except Exception:
                price = 0.0

            # Prefer explicit remaining quantity when present.
            qty_raw = (
                o.get("remaining_size")
                or o.get("remainingSize")
                or o.get("size")
                or o.get("quantity")
                or o.get("amount")
                or o.get("original_size")
                or 0
            )
            try:
                qty = float(qty_raw)
            except Exception:
                qty = 0.0

            if price > 0 and qty > 0:
                reserved += price * qty
                live_count += 1

        return max(reserved, 0.0), live_count

    def _refresh_account_metrics(self, adapter):
        """Refresh wallet balance and reserved collateral estimates."""
        if self.state.get("mode") != "LIVE":
            return
        try:
            perms = adapter.get_balance_allowance()
            self.state["wallet_balance"] = float(perms.get("balance", "0")) / 1e6
        except Exception as e:
            self._log("WARNING", f"Balance refresh failed: {e}")

        try:
            reserved, live_count = self._estimate_live_order_reserve(adapter)
            self.state["reserved_in_live_orders_estimate"] = reserved
            self.state["live_orders_count"] = live_count
        except Exception as e:
            self._log("WARNING", f"Live order reserve estimate failed: {e}")

        self._recompute_equity()
        self._save_runtime_state()

    def stop(self):
        with self._lock:
            if self.state["status"] == "stopped":
                return {"ok": False, "msg": "Bot is already stopped"}
            
            self._stop_event.set()
            self.state["status"] = "stopped"
            self._save_runtime_state()
            self._log("INFO", "Bot stop requested.")
            return {"ok": True, "msg": "Bot stopping..."}

    def update_settings(self, settings: Dict):
        """Update bot settings dynamically."""
        if "min_profit_threshold" in settings:
            self.state["min_profit_threshold"] = float(settings["min_profit_threshold"])
            self.state["effective_threshold"] = self.state["min_profit_threshold"] + POLYMARKET_FEE_RATE + SLIPPAGE_BUFFER
        if "max_position_size" in settings:
            self.state["max_position_size"] = float(settings["max_position_size"])
        if "mode" in settings and settings["mode"] in ("PAPER", "LIVE"):
            self.state["mode"] = settings["mode"]
        self._log("INFO", f"Settings updated: {settings}")
        return {"ok": True}

    def get_positions(self) -> List[Dict]:
        """Return current position book as a list for the dashboard."""
        positions = []
        for token_id, p in self.position_book.items():
            shares = float(p.get("shares", 0.0))
            mid = float(p.get("last_mid", 0.0))
            avg_entry = float(p.get("avg_entry", mid))
            if abs(shares) < 1e-8:
                continue
            market_value = shares * mid
            cost_basis = shares * avg_entry
            unrealized = market_value - cost_basis
            positions.append({
                "token_id": token_id,
                "token_short": f"...{token_id[-8:]}",
                "shares": round(shares, 4),
                "avg_entry": round(avg_entry, 4),
                "last_mid": round(mid, 4),
                "market_value": round(market_value, 2),
                "cost_basis": round(cost_basis, 2),
                "unrealized_pnl": round(unrealized, 2),
                "side": "LONG" if shares > 0 else "SHORT",
            })
        return sorted(positions, key=lambda x: abs(x["market_value"]), reverse=True)

    def close_position(self, token_id: str) -> Dict:
        """Close a position by placing a sell/buy order using actual exchange balance."""
        if not token_id or token_id not in self.position_book:
            return {"ok": False, "msg": f"Position not found for token ...{token_id[-8:] if token_id else '?'}"}

        pos = self.position_book[token_id]
        shares = float(pos.get("shares", 0.0))
        mid = float(pos.get("last_mid", 0.0))

        if abs(shares) < 1:
            return {"ok": False, "msg": f"Position too small to close ({shares:.2f} shares)"}

        try:
            from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
            adapter = PolymarketAdapter()

            if shares > 0:
                # Long position -> SELL to close
                # Check actual token balance on exchange (not our internal book)
                params = BalanceAllowanceParams(
                    asset_type=AssetType.CONDITIONAL,
                    token_id=token_id,
                    signature_type=2
                )
                adapter.client.update_balance_allowance(params)
                bal = adapter.client.get_balance_allowance(params)
                actual_shares = int(bal.get("balance", "0")) / 1e6

                if actual_shares < 1:
                    return {"ok": False, "msg": f"No shares found on exchange (book says {shares:.0f}, exchange says {actual_shares:.0f})"}

                sell_price = round(max(mid - 0.01, 0.01), 2)
                num_shares = round(actual_shares - 1, 0)  # keep 1 share buffer
                self._log("INFO", f"CLOSING LONG: SELL {num_shares:.0f} of {actual_shares:.0f} actual shares of ...{token_id[-8:]} @ ${sell_price}")
                resp = adapter.place_close_order(token_id, "SELL", sell_price, num_shares)
            else:
                # Short position -> BUY to close
                buy_price = round(min(mid + 0.01, 0.99), 2)
                num_shares = round(abs(shares), 2)
                self._log("INFO", f"CLOSING SHORT: BUY {num_shares:.0f} shares of ...{token_id[-8:]} @ ${buy_price}")
                resp = adapter.place_close_order(token_id, "BUY", buy_price, num_shares)

            if resp:
                self._log("INFO", f"Close order placed: {resp}")
                return {"ok": True, "msg": f"Close order placed for ...{token_id[-8:]}", "response": str(resp)}
            else:
                return {"ok": False, "msg": "Order failed - check logs"}

        except Exception as e:
            self._log("ERROR", f"Failed to close position: {e}")
            return {"ok": False, "msg": str(e)}

    def get_state(self) -> Dict:
        """Return current state for dashboard."""
        if self.state["started_at"]:
            self.state["uptime"] = int(time.time() - self.state["started_at"])
        self._recompute_equity()
        return {
            **self.state,
            "recent_logs": list(self.recent_logs)[-50:],
            "recent_opportunities": list(self.recent_opportunities)[-20:],
            "recent_trades": list(self.recent_trades)[-20:],
            "sessions": self.sessions_info,
        }

    # --- Bot Main Loop (runs in thread) ---

    def _run(self):
        try:
            self._log("INFO", f"Bot starting in {self.state['mode']} mode...")
            self.state["started_at"] = time.time()
            
            adapter = PolymarketAdapter()
            exec_engine = ExecutionEngine(adapter)
            self.state["daily_pnl"] = float(exec_engine.daily_pnl)
            self.state["realized_pnl"] = float(exec_engine.daily_pnl)
            dep_detector = DependencyDetector()

            # Connect WS
            adapter.connect_ws()
            time.sleep(2)

            # Fetch markets
            self._log("INFO", "Fetching markets...")
            markets = adapter.get_markets(limit=MAX_MARKETS_TO_FETCH)
            if not markets:
                self._log("ERROR", "No markets fetched. Check network.")
                self.state["status"] = "error"
                self.state["last_error"] = "No markets fetched"
                return
            self._log("INFO", f"Fetched {len(markets)} active markets.")

            # Check balance
            if self.state["mode"] == "LIVE":
                self._refresh_account_metrics(adapter)
                self._log("INFO", f"Wallet balance: ${self.state.get('wallet_balance', 0.0):.2f}")
                self._hydrate_positions_from_exchange(adapter)

            # Find pairs
            self._log("INFO", "Analyzing market pairs with LLM...")
            all_pairs = self._find_related_pairs(markets, dep_detector)
            if not all_pairs:
                self._log("ERROR", "No dependent market pairs found.")
                self.state["status"] = "error"
                self.state["last_error"] = "No dependent pairs found"
                return

            self.state["pairs_monitored"] = len(all_pairs)
            self._log("INFO", f"Found {len(all_pairs)} dependent market pairs.")

            # Create sessions
            sessions = []
            all_token_ids = []
            for pair_markets, valid_outcomes in all_pairs:
                session = MonitoringSession(pair_markets, valid_outcomes)
                sessions.append(session)
                all_token_ids.extend(list(session.token_map.keys()))
            
            self.state["tokens_subscribed"] = len(all_token_ids)
            self.sessions_info = [s.to_dict() for s in sessions]

            # Subscribe
            adapter.subscribe(all_token_ids)

            # Initial REST fetch
            self._log("INFO", "Fetching initial order books...")
            for session in sessions:
                for token_id in session.token_map:
                    book = adapter.get_midmarket_price(token_id)
                    if book["mid"] > 0:
                        session.update_price(token_id, book["mid"], book["bid"], book["ask"])
                profit, mu_star = session.run_analysis()
                if profit and profit > 0.001:
                    self._record_opportunity(profit, session)

            self.sessions_info = [s.to_dict() for s in sessions]
            self.state["status"] = "running"
            self._log("INFO", "Bot is LIVE and monitoring.")

            # WS callback
            effective_threshold = self.state["effective_threshold"]
            
            def on_price_update(data):
                try:
                    if not isinstance(data, dict): return
                    token_id = data.get("asset_id")
                    if not token_id: return
                    bids = data.get("bids", [])
                    asks = data.get("asks", [])
                    if not bids and not asks: return

                    best_bid = max((float(b['price']) for b in bids), default=0.0) if bids else 0.0
                    best_ask = min((float(a['price']) for a in asks if float(a['price']) < 0.999), default=0.0) if asks else 0.0

                    if best_bid > 0 and best_ask > 0: mid = (best_bid + best_ask) / 2
                    elif best_bid > 0: mid = best_bid
                    elif best_ask > 0: mid = best_ask
                    else: return

                    for session in sessions:
                        if not session.update_price(token_id, mid, best_bid, best_ask): continue
                        self._update_mark_price(token_id, mid)
                        profit, mu_star = session.run_analysis()
                        if profit is None or profit <= 0.0001: continue

                        self._record_opportunity(profit, session)

                        cur_threshold = self._adaptive_threshold(session)
                        if profit <= cur_threshold: continue
                        self.state["tradable_opportunities"] += 1
                        if not session.can_trade(): continue

                        self._log("INFO", f"TRADE SIGNAL (WS): Profit ${profit:.4f}")
                        orders = self._build_orders(session, mu_star)
                        if orders:
                            self._execute_orders(exec_engine, orders, session, adapter)
                except Exception as e:
                    self._log("ERROR", f"WS handler error: {e}")

            adapter.add_callback(on_price_update)

            # Main loop
            poll_counter = 0
            last_recycle_time = time.time()
            last_flip_check = time.time()
            REST_POLL_INTERVAL = 2

            while not self._stop_event.is_set():
                time.sleep(1)
                if self._stop_event.is_set(): break
                poll_counter += 1

                # WS health
                if not adapter.is_ws_connected():
                    self._log("WARNING", "WebSocket disconnected! Reconnecting...")
                    adapter.reconnect_ws()
                    time.sleep(2)
                    if adapter.is_ws_connected():
                        adapter.subscribe(all_token_ids)
                        self._log("INFO", "Reconnected.")

                # Quick-flip exit check (take-profit / stop-loss)
                if self.state["mode"] == "LIVE" and (time.time() - last_flip_check) >= FLIP_CHECK_INTERVAL:
                    try:
                        self._check_exit_signals(adapter)
                        last_flip_check = time.time()
                    except Exception as e:
                        self._log("WARNING", f"Exit check error: {e}")

                # Cancel stale live orders
                if poll_counter % REST_POLL_INTERVAL == 0 and self.state["mode"] == "LIVE":
                    self._cancel_stale_orders(adapter)

                # Position recycler (runs on interval; runs more often when cash is low, but not every second)
                if self.state["mode"] == "LIVE":
                    cash = self.state.get("wallet_balance") or 0.0
                    time_since_recycle = time.time() - last_recycle_time
                    low_cash_interval = 300  # 5 min when cash is low (not every second)
                    interval = low_cash_interval if cash < RECYCLE_MIN_CASH_RESERVE else RECYCLE_INTERVAL_SECONDS
                    if time_since_recycle >= interval:
                        try:
                            self._run_position_recycler(adapter)
                            last_recycle_time = time.time()
                        except Exception as e:
                            self._log("WARNING", f"Recycler error: {e}")
                
                # REST poll
                if poll_counter % REST_POLL_INTERVAL == 0:
                    for session in sessions:
                        for token_id in session.token_map:
                            book = adapter.get_midmarket_price(token_id)
                            if book["mid"] > 0:
                                session.update_price(token_id, book["mid"], book["bid"], book["ask"])
                                self._update_mark_price(token_id, book["mid"])
                        profit, mu_star = session.run_analysis()
                        if profit and profit > 0.001:
                            self._record_opportunity(profit, session)
                            cur_threshold = self._adaptive_threshold(session)
                            if profit > cur_threshold and session.can_trade():
                                self.state["tradable_opportunities"] += 1
                                self._log("INFO", f"TRADE SIGNAL (REST): Profit ${profit:.4f}")
                                orders = self._build_orders(session, mu_star)
                                if orders:
                                    self._execute_orders(exec_engine, orders, session, adapter)
                    
                    self.sessions_info = [s.to_dict() for s in sessions]
                    # Update balance periodically
                    if self.state["mode"] == "LIVE":
                        self._refresh_account_metrics(adapter)

            self._log("INFO", "Bot stopped cleanly.")
            self.state["status"] = "stopped"
            self._save_runtime_state()

        except Exception as e:
            self._log("ERROR", f"Bot crashed: {e}")
            self.state["status"] = "error"
            self.state["last_error"] = str(e)
            self._save_runtime_state()

    def _find_related_pairs(self, markets, dep_detector):
        """Find related pairs DIVERSIFIED across different topics."""
        stop = {"will","the","be","in","price","of","to","above","below","a","by","on","at",
                "for","is","it","or","and","this","that","with","from","an","are","was","were",
                "has","have","do","does","before","after","than","more","less","?","how","many",
                "much","what","which","when","where","who","its","their","his","her","they"}

        # Step 1: Find ALL candidate pairs
        all_candidates = []
        for i in range(len(markets)):
            for j in range(i + 1, len(markets)):
                m1, m2 = markets[i], markets[j]
                t1 = m1.get('clobTokenIds', [])
                t2 = m2.get('clobTokenIds', [])
                if not isinstance(t1, list) or len(t1) < 2: continue
                if not isinstance(t2, list) or len(t2) < 2: continue
                q1, q2 = m1['question'].lower(), m2['question'].lower()
                overlap = (set(q1.split()) & set(q2.split())) - stop
                if len(overlap) >= 2:
                    # Create a "topic key" from shared words to detect same-topic pairs
                    topic_key = tuple(sorted(overlap))
                    # execution-first structural score:
                    # prefer same-stem ladder markets (between/less/more style ranges)
                    stem1 = re.sub(r"\b(20\d{2}|\$?\d[\d,\.]*[bkmt]?|between|less|more|than|at|least|over|under)\b", " ", q1)
                    stem2 = re.sub(r"\b(20\d{2}|\$?\d[\d,\.]*[bkmt]?|between|less|more|than|at|least|over|under)\b", " ", q2)
                    stem1 = " ".join(stem1.split())
                    stem2 = " ".join(stem2.split())
                    same_stem = 1 if stem1[:80] == stem2[:80] else 0
                    ladder_like = 1 if (("between" in q1 or "less than" in q1 or "more than" in q1) and ("between" in q2 or "less than" in q2 or "more than" in q2)) else 0
                    execution_score = (len(overlap) * 10) + (same_stem * 40) + (ladder_like * 25)
                    all_candidates.append((m1, m2, len(overlap), topic_key, execution_score))

        self._log("INFO", f"Found {len(all_candidates)} total candidate pairs.")

        # Step 2: Group by topic and pick best pairs from DIFFERENT topics
        from collections import defaultdict
        topic_groups = defaultdict(list)
        for m1, m2, score, topic, exec_score in all_candidates:
            # Use top-3 shared words as topic fingerprint
            short_topic = tuple(sorted(topic)[:3])
            topic_groups[short_topic].append((m1, m2, score, topic, exec_score))

        # Sort each topic group by score, pick top 2 per topic
        MAX_PER_TOPIC = 2
        diversified = []
        for topic, pairs in sorted(topic_groups.items(), key=lambda x: -max(p[4] for p in x[1])):
            pairs.sort(key=lambda x: x[4], reverse=True)
            for p in pairs[:MAX_PER_TOPIC]:
                diversified.append(p)
            if len(diversified) >= MAX_PAIRS_TO_ANALYZE * 2:
                break

        # Take top N overall
        diversified = diversified[:MAX_PAIRS_TO_ANALYZE]
        
        topics_found = set()
        for _, _, _, topic, _ in diversified:
            topics_found.add(tuple(sorted(topic)[:3]))
        self._log("INFO", f"Selected {len(diversified)} pairs across {len(topics_found)} different topics.")

        # Step 3: LLM analysis
        found = []
        for m1, m2, score, topic, exec_score in diversified:
            if self._stop_event.is_set(): break
            self._log("INFO", f"LLM analyzing(score={exec_score}): '{m1['question'][:50]}' vs '{m2['question'][:50]}'")
            result = dep_detector.analyze_market_pair(m1, m2)
            if result and len(result) < 4:
                self._log("INFO", f"Dependency found! ({len(result)} valid combos)")
                matrix = convert_outcomes_to_vectors(result)
                found.append(([m1, m2], matrix))
        return found

    def _build_orders(self, session, mu_star):
        orders = []
        pos_size = self.state["max_position_size"]
        for i, price in enumerate(session.prices):
            fair = mu_star[i]
            tid = session.token_lookup.get(i)
            if not tid: continue

            bid = session.best_bids.get(tid, 0.0)
            ask = session.best_asks.get(tid, 0.0)
            mid = (bid + ask) / 2 if bid > 0 and ask > 0 else price
            if mid <= 0:
                continue
            if bid > 0 and ask > 0 and ask > bid:
                spread_pct = (ask - bid) / max(mid, 0.01)
                if spread_pct > MAX_SPREAD_PCT:
                    continue

            leg = min(pos_size / max(len(session.markets), 1), pos_size)
            if fair > price * (1 + ENTRY_BAND) and price >= MIN_EXEC_PRICE:
                ep = session.best_asks.get(tid, price)
                if ep <= 0: ep = price
                if ep < MIN_EXEC_PRICE or ep > MAX_EXEC_PRICE:
                    continue
                orders.append({
                    "token_id": tid, "side": "BUY", "price": round(ep, 4),
                    "size": leg, "fair_value": round(fair, 4),
                })
            elif fair < price * (1 - ENTRY_BAND) and price >= MIN_EXEC_PRICE:
                ep = session.best_bids.get(tid, price)
                if ep <= 0: ep = price
                if ep < MIN_EXEC_PRICE or ep > MAX_EXEC_PRICE:
                    continue
                orders.append({
                    "token_id": tid, "side": "SELL", "price": round(ep, 4),
                    "size": leg, "fair_value": round(fair, 4),
                })
        return orders

    def _adaptive_threshold(self, session) -> float:
        """
        Dynamic execution threshold:
        - Keep user's configured threshold as the upper bound.
        - Allow lower threshold on tighter books to increase executable flow.
        """
        configured = float(self.state["effective_threshold"])
        spreads = []
        mids = []
        for tid in session.token_map.keys():
            bid = session.best_bids.get(tid, 0.0)
            ask = session.best_asks.get(tid, 0.0)
            if bid > 0 and ask > bid and ask < 0.999:
                mid = (bid + ask) / 2.0
                if mid > 0:
                    spreads.append((ask - bid) / max(mid, 0.01))
                    mids.append(mid)
        if not spreads:
            return configured
        avg_spread = sum(spreads) / len(spreads)
        avg_mid = sum(mids) / len(mids) if mids else 0.5

        # Tight books can be traded at lower theoretical edge.
        # This keeps a dynamic floor but avoids missing sub-cent opportunities
        # that were historically executable on liquid pairs.
        if avg_spread <= 0.05 and 0.03 <= avg_mid <= 0.97:
            return min(configured, 0.0008)
        if avg_spread <= 0.10 and 0.02 <= avg_mid <= 0.98:
            return min(configured, 0.0015)
        if avg_spread <= 0.18 and 0.01 <= avg_mid <= 0.99:
            return min(configured, 0.0030)
        return configured

    def _execute_orders(self, exec_engine, orders, session, adapter):
        if not self._trade_lock.acquire(blocking=False):
            return
        try:
            self._execute_orders_inner(exec_engine, orders, session, adapter)
        finally:
            self._trade_lock.release()

    def _execute_orders_inner(self, exec_engine, orders, session, adapter):
        if self.state.get("mode") == "LIVE":
            current_live = self.state.get("live_orders_count", 0)
            if current_live >= MAX_LIVE_ORDERS:
                self._log("WARNING", f"Live order limit reached ({current_live}/{MAX_LIVE_ORDERS}). Skipping.")
                return

            # Refresh balance right before trading to get latest
            self._refresh_account_metrics(adapter)
            balance = self.state.get("wallet_balance") or 0.0
            equity = self.state.get("net_equity_estimate") or balance
            reserved = self.state.get("reserved_in_live_orders_estimate", 0.0)

            min_reserve = max(min(equity * CASH_RESERVE_RATIO, balance * 0.40), 2.0)
            available = balance - reserved - min_reserve
            if available <= 0:
                self._log("WARNING",
                    f"Cash reserve: ${balance:.2f} bal - ${reserved:.2f} rsv "
                    f"- ${min_reserve:.2f} floor = ${available:.2f}. Skipping."
                )
                return

            max_per_trade = max(equity * MAX_CAPITAL_PER_TRADE_RATIO, 1.0)
            cap = min(available, max_per_trade)

            total_buy_cost = sum(o["size"] for o in orders if o["side"] == "BUY")
            if total_buy_cost > cap and total_buy_cost > 0:
                scale = cap / total_buy_cost
                self._log("INFO", f"Scaling orders to {scale:.0%} (cap ${cap:.2f}, requested ${total_buy_cost:.2f})")
                for o in orders:
                    if o["side"] == "BUY":
                        o["size"] = round(o["size"] * scale, 2)

        self.state["trades_executed"] += 1
        for o in orders:
            self.recent_trades.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "side": o["side"],
                "price": o["price"],
                "size": o["size"],
                "token": f"...{o['token_id'][-8:]}",
            })

        original_mode = EXECUTION_MODE
        import poly_arb_bot.config as cfg
        cfg.EXECUTION_MODE = self.state["mode"]

        exec_results = exec_engine.execute_arbitrage(orders)
        if self.state.get("mode") == "LIVE":
            for r in exec_results:
                if r.get("filled"):
                    self._apply_filled_order(r["order"])
        session.mark_traded()

        cfg.EXECUTION_MODE = original_mode
        self.state["daily_pnl"] = exec_engine.daily_pnl
        self.state["realized_pnl"] = float(exec_engine.daily_pnl)
        if self.state.get("mode") == "LIVE":
            self._refresh_account_metrics(adapter)
        self._recompute_equity()
        self._save_runtime_state()

    def _apply_filled_order(self, order: Dict[str, float]):
        """Update internal position book assuming order was filled."""
        token_id = order["token_id"]
        price = float(order["price"])
        size = float(order["size"])
        if price <= 0:
            return
        delta = size / price
        side = str(order["side"]).upper()
        signed_delta = delta if side == "BUY" else -delta
        if token_id not in self.position_book:
            fair = float(order.get("fair_value", 0))
            if side == "BUY":
                # Take-profit: use fair value if available, otherwise % above entry
                tp = fair if fair > price else min(price * (1 + TAKE_PROFIT_PCT), 0.99)
                sl = max(price * (1 - STOP_LOSS_PCT), 0.01)
            else:
                tp = fair if 0 < fair < price else max(price * (1 - TAKE_PROFIT_PCT), 0.01)
                sl = min(price * (1 + STOP_LOSS_PCT), 0.99)
            self.position_book[token_id] = {
                "shares": 0.0,
                "last_mid": price,
                "avg_entry": price,
                "opened_at": time.time(),
                "target_exit": round(tp, 4),
                "stop_exit": round(sl, 4),
            }

        pos = self.position_book[token_id]
        prev_shares = float(pos.get("shares", 0.0))
        prev_avg = float(pos.get("avg_entry", price))
        new_shares = prev_shares + signed_delta

        # Update average entry only when increasing exposure in same direction
        # or when opening a fresh position after crossing through zero.
        if abs(prev_shares) < 1e-8:
            new_avg = price
        elif (prev_shares > 0 and signed_delta > 0) or (prev_shares < 0 and signed_delta < 0):
            total_abs = abs(prev_shares) + abs(signed_delta)
            new_avg = ((abs(prev_shares) * prev_avg) + (abs(signed_delta) * price)) / max(total_abs, 1e-12)
        elif (prev_shares > 0 > new_shares) or (prev_shares < 0 < new_shares):
            # Position crossed zero; remainder is a fresh position at current fill.
            new_avg = price
        else:
            # Reducing existing exposure keeps prior avg entry.
            new_avg = prev_avg

        pos["shares"] = new_shares
        pos["last_mid"] = price
        pos["avg_entry"] = new_avg

        # Prune dust
        if abs(pos["shares"]) < 1e-8:
            del self.position_book[token_id]

    def _update_mark_price(self, token_id: str, mid: float):
        if token_id in self.position_book and mid > 0:
            self.position_book[token_id]["last_mid"] = mid

    def _check_exit_signals(self, adapter):
        """
        Quick-flip exit logic: close positions that hit take-profit or stop-loss.
        Called periodically from the main loop.
        """
        if self.state.get("mode") != "LIVE":
            return
        if not self.position_book:
            return

        from py_clob_client.clob_types import BalanceAllowanceParams, AssetType

        exits_triggered = 0
        for token_id, p in list(self.position_book.items()):
            shares = float(p.get("shares", 0.0))
            mid = float(p.get("last_mid", 0.0))
            avg_entry = float(p.get("avg_entry", mid))
            target = p.get("target_exit")
            stop = p.get("stop_exit")

            if abs(shares) < 1 or mid <= 0:
                continue
            if target is None and stop is None:
                continue

            is_long = shares > 0
            reason = None

            if is_long:
                if target and mid >= target:
                    reason = "TAKE-PROFIT"
                elif stop and mid <= stop:
                    reason = "STOP-LOSS"
            else:
                if target and mid <= target:
                    reason = "TAKE-PROFIT"
                elif stop and mid >= stop:
                    reason = "STOP-LOSS"

            if not reason:
                continue

            pnl_per = (mid - avg_entry) if is_long else (avg_entry - mid)
            pnl_pct = (pnl_per / max(avg_entry, 0.001)) * 100
            age_min = (time.time() - float(p.get("opened_at", time.time()))) / 60

            try:
                if is_long:
                    params = BalanceAllowanceParams(
                        asset_type=AssetType.CONDITIONAL,
                        token_id=token_id,
                        signature_type=2
                    )
                    adapter.client.update_balance_allowance(params)
                    bal = adapter.client.get_balance_allowance(params)
                    actual = int(bal.get("balance", "0")) / 1e6
                    if actual < 1:
                        self.position_book.pop(token_id, None)
                        continue
                    sell_price = round(max(mid - 0.01, 0.01), 2)
                    if sell_price >= 1.0:
                        sell_price = 0.99
                    num = round(actual - 1, 0)
                    if num < 1:
                        self.position_book.pop(token_id, None)
                        continue
                    self._log("INFO",
                        f"{reason}: SELL {num:.0f} shares ...{token_id[-8:]} "
                        f"@ ${sell_price} (entry ${avg_entry:.3f}, PnL {pnl_pct:+.1f}%, held {age_min:.0f}min)"
                    )
                    resp = adapter.place_close_order(token_id, "SELL", sell_price, num)
                else:
                    cash = self.state.get("wallet_balance") or 0.0
                    buy_price = round(min(mid + 0.01, 0.99), 2)
                    num = round(abs(shares), 2)
                    cost = buy_price * num
                    if cash < cost + 2.0:
                        continue
                    self._log("INFO",
                        f"{reason}: BUY-BACK {num:.0f} shares ...{token_id[-8:]} "
                        f"@ ${buy_price} (entry ${avg_entry:.3f}, PnL {pnl_pct:+.1f}%, held {age_min:.0f}min)"
                    )
                    resp = adapter.place_close_order(token_id, "BUY", buy_price, num)

                if resp:
                    exits_triggered += 1
            except Exception as e:
                self._log("WARNING", f"Exit order failed for ...{token_id[-8:]}: {e}")

        if exits_triggered > 0:
            self._log("INFO", f"Quick-flip: {exits_triggered} exit(s) triggered")
            self._refresh_account_metrics(adapter)
            self._save_runtime_state()

    def _recompute_equity(self):
        pos_val = 0.0
        unrealized = 0.0
        open_count = 0
        for token_id, p in self.position_book.items():
            shares = float(p.get("shares", 0.0))
            mid = float(p.get("last_mid", 0.0))
            avg_entry = float(p.get("avg_entry", mid))
            if abs(shares) < 1e-8:
                continue
            open_count += 1
            pos_val += shares * mid
            unrealized += shares * (mid - avg_entry)
        self.state["position_value_estimate"] = pos_val
        self.state["unrealized_pnl_estimate"] = unrealized
        self.state["open_positions_count"] = open_count
        cash = self.state.get("wallet_balance")
        self.state["net_equity_estimate"] = (cash + pos_val) if cash is not None else None

    def _cancel_stale_orders(self, adapter):
        """Cancel orders that have been live too long without filling."""
        try:
            orders = adapter.get_open_orders()
            if not orders:
                return
            
            now = time.time()
            cancelled_count = 0
            
            for o in orders:
                if not isinstance(o, dict):
                    continue
                
                # Check if order is in non-terminal state
                status = str(o.get("status") or o.get("state") or "").strip().lower()
                terminal = {"matched", "filled", "cancelled", "canceled", "rejected", "failed", "expired", "executed"}
                if status in terminal:
                    continue
                
                # Parse order creation time
                created_raw = o.get("created_at") or o.get("createdAt") or o.get("timestamp") or ""
                if not created_raw:
                    continue
                
                try:
                    # Try parsing ISO timestamp
                    if isinstance(created_raw, (int, float)):
                        created_ts = float(created_raw)
                    else:
                        created_dt = datetime.fromisoformat(str(created_raw).replace("Z", "+00:00"))
                        created_ts = created_dt.timestamp()
                    
                    age_seconds = now - created_ts
                    
                    if age_seconds > STALE_ORDER_TIMEOUT_SECONDS:
                        order_id = o.get("id") or o.get("orderID") or o.get("order_id")
                        if order_id:
                            self._log("INFO", f"Cancelling stale order (age={int(age_seconds)}s): {order_id[:16]}...")
                            adapter.cancel_order(order_id)
                            cancelled_count += 1
                except Exception as e:
                    continue
            
            if cancelled_count > 0:
                self._log("INFO", f"Cancelled {cancelled_count} stale orders.")
                # Refresh metrics after cancellations
                self._refresh_account_metrics(adapter)
        except Exception as e:
            self._log("WARNING", f"Stale order cleanup failed: {e}")

    # ------------------------------------------------------------------
    # Position Recycler: auto-sell positions to free cash for new trades
    # ------------------------------------------------------------------

    def _run_position_recycler(self, adapter):
        """
        Automatic position recycling logic. Called periodically from the main loop.

        Two-phase approach to avoid the $0 deadlock:
          Phase 1 — SELL longs (requires shares on exchange, NOT cash)
          Phase 2 — BUY-BACK shorts (requires cash freed from Phase 1)
        """
        if self.state.get("mode") != "LIVE":
            return
        if not RECYCLE_ENABLED:
            return
        if not self.position_book:
            return

        from py_clob_client.clob_types import BalanceAllowanceParams, AssetType

        now = time.time()
        cash = self.state.get("wallet_balance") or 0.0
        longs = []
        shorts = []

        for token_id, p in list(self.position_book.items()):
            shares = float(p.get("shares", 0.0))
            mid = float(p.get("last_mid", 0.0))
            avg_entry = float(p.get("avg_entry", mid))
            opened_at = float(p.get("opened_at", now))
            age = now - opened_at

            if abs(shares) < 1 or mid <= 0:
                continue

            pnl_per_share = mid - avg_entry if shares > 0 else avg_entry - mid
            total_pnl = pnl_per_share * abs(shares)
            market_value = abs(shares) * mid

            entry = {
                "token_id": token_id,
                "shares": shares,
                "mid": mid,
                "avg_entry": avg_entry,
                "age": age,
                "pnl": total_pnl,
                "market_value": market_value,
                "is_profitable": total_pnl > 0,
                "is_expired": age > RECYCLE_MAX_HOLD_SECONDS,
                "is_mature": age > RECYCLE_MIN_HOLD_SECONDS,
            }
            if shares > 0:
                longs.append(entry)
            else:
                shorts.append(entry)

        if not longs and not shorts:
            return

        longs.sort(key=lambda c: (-c["pnl"], -c["market_value"]))
        shorts.sort(key=lambda c: (-c["pnl"], -c["market_value"]))

        def _should_recycle(c):
            if cash < RECYCLE_MIN_CASH_RESERVE:
                return True
            if c["is_expired"]:
                return True
            if c["is_profitable"] and c["is_mature"]:
                return True
            return False

        longs_to_sell = [c for c in longs if _should_recycle(c)]
        shorts_to_buy = [c for c in shorts if _should_recycle(c)]

        total = len(longs_to_sell) + len(shorts_to_buy)
        if total == 0:
            return

        if cash < RECYCLE_MIN_CASH_RESERVE:
            self._log("INFO", f"RECYCLER: Cash low (${cash:.2f} < ${RECYCLE_MIN_CASH_RESERVE}). Selling longs first to free capital.")

        self._log("INFO", f"RECYCLER: {len(longs_to_sell)} longs to sell, {len(shorts_to_buy)} shorts to buy-back")

        # --- Phase 1: Sell longs (no cash required, only shares) ---
        for c in longs_to_sell:
            token_id = c["token_id"]
            mid = c["mid"]
            pnl = c["pnl"]
            age_hours = c["age"] / 3600
            reason = "expired" if c["is_expired"] else ("profitable" if c["is_profitable"] else "low cash")

            try:
                params = BalanceAllowanceParams(
                    asset_type=AssetType.CONDITIONAL,
                    token_id=token_id,
                    signature_type=2
                )
                adapter.client.update_balance_allowance(params)
                bal = adapter.client.get_balance_allowance(params)
                actual = int(bal.get("balance", "0")) / 1e6

                if actual < 1:
                    self._log("INFO", f"RECYCLER: ...{token_id[-8:]} has 0 shares on exchange, removing from book")
                    self.position_book.pop(token_id, None)
                    continue

                sell_price = round(max(mid - 0.01, 0.01), 2)
                if sell_price >= 1.0:
                    sell_price = 0.99
                num_shares = round(actual - 1, 0)
                if num_shares < 1:
                    self._log("INFO", f"RECYCLER: ...{token_id[-8:]} only {actual:.0f} share on exchange, removing from book")
                    self.position_book.pop(token_id, None)
                    continue

                self._log("INFO",
                    f"RECYCLER SELL: {num_shares:.0f} shares of ...{token_id[-8:]} "
                    f"@ ${sell_price} (PnL: ${pnl:+.2f}, held {age_hours:.1f}h, reason: {reason})"
                )
                resp = adapter.place_close_order(token_id, "SELL", sell_price, num_shares)
                if resp:
                    self._log("INFO", f"RECYCLER: Sell order placed: {resp.get('orderID', '?')[:16]}...")

            except Exception as e:
                self._log("WARNING", f"RECYCLER: Failed to sell ...{token_id[-8:]}: {e}")

        # Refresh balance after sells so we have cash available for buy-backs
        if longs_to_sell:
            self._refresh_account_metrics(adapter)
            cash = self.state.get("wallet_balance") or 0.0

        # --- Phase 2: Buy-back shorts (requires cash freed from Phase 1) ---
        for c in shorts_to_buy:
            token_id = c["token_id"]
            mid = c["mid"]
            pnl = c["pnl"]
            age_hours = c["age"] / 3600
            reason = "expired" if c["is_expired"] else ("profitable" if c["is_profitable"] else "low cash")

            buy_price = round(min(mid + 0.01, 0.99), 2)
            num_shares = round(abs(c["shares"]), 2)
            cost_estimate = buy_price * num_shares

            if cash < 2.0:
                self._log("INFO",
                    f"RECYCLER: Skipping short buy-back ...{token_id[-8:]} "
                    f"(need ~${cost_estimate:.2f}, have ${cash:.2f}). Waiting for long sells to settle."
                )
                continue

            try:
                self._log("INFO",
                    f"RECYCLER BUY-BACK: {num_shares:.0f} shares of ...{token_id[-8:]} "
                    f"@ ${buy_price} (PnL: ${pnl:+.2f}, held {age_hours:.1f}h, reason: {reason})"
                )
                resp = adapter.place_close_order(token_id, "BUY", buy_price, num_shares)
                if resp:
                    self._log("INFO", f"RECYCLER: Buy-back order placed: {resp.get('orderID', '?')[:16]}...")
                    cash -= cost_estimate
            except Exception as e:
                self._log("WARNING", f"RECYCLER: Failed to buy-back ...{token_id[-8:]}: {e}")

        self._refresh_account_metrics(adapter)
        self._save_runtime_state()

    def _record_opportunity(self, profit, session):
        self.state["opportunities_found"] += 1
        self.state["raw_opportunities"] += 1
        self.recent_opportunities.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "profit": round(profit, 5),
            "markets": [m.get("question", "?")[:50] for m in session.markets],
            "prices": session.prices.round(4).tolist(),
        })
        # Also log to CSV
        try:
            exists = os.path.exists(OPPORTUNITY_LOG_FILE)
            with open(OPPORTUNITY_LOG_FILE, "a", newline="") as f:
                w = csv.writer(f)
                if not exists:
                    w.writerow(["timestamp","profit","prices","market_a","market_b"])
                w.writerow([
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    f"{profit:.5f}",
                    np.array2string(session.prices, precision=4, separator=', '),
                    session.markets[0].get("question","?")[:80] if len(session.markets)>0 else "",
                    session.markets[1].get("question","?")[:80] if len(session.markets)>1 else "",
                ])
        except: pass
