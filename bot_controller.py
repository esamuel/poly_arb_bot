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
import math
import numpy as np
import requests as _requests
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from collections import deque
from pathlib import Path

from poly_arb_bot.config import (
    EXECUTION_MODE, MIN_PROFIT_THRESHOLD, 
    MAX_POSITION_SIZE, POLYMARKET_API_KEY, PRIVATE_KEY, OPENAI_API_KEY
)
from poly_arb_bot.adapters.polymarket import PolymarketAdapter
from poly_arb_bot.engine.math import MarketMath
from poly_arb_bot.engine.execution import ExecutionEngine
from poly_arb_bot.engine.dependency import DependencyDetector

logger = logging.getLogger(__name__)

# Polymarket CLOB is long-only. All positions are non-negative.
# "size" fields in orders represent USDC cost for BUY,
# and number of shares for SELL.

# --- Constants ---
POLYMARKET_FEE_RATE = 0.01
SLIPPAGE_BUFFER = 0.005
# Round-trip cost floor.  An opportunity MUST exceed 2× (fee + slippage)
# to have any chance of being profitable.  Previously set to 0.001 which
# guaranteed losses after the 2% round-trip cost.
MIN_EFFECTIVE_EDGE = max(2 * (POLYMARKET_FEE_RATE + SLIPPAGE_BUFFER), 0.035)
TRADE_COOLDOWN_SECONDS = int(os.getenv("TRADE_COOLDOWN_SECONDS", "10"))
MAX_PAIRS_TO_ANALYZE = 15
MAX_MARKETS_TO_FETCH = 1000
ENTRY_BAND = 0.01
MAX_SPREAD_PCT = 0.15
MIN_EXEC_PRICE = 0.01
MAX_EXEC_PRICE = 0.99
MAX_LIVE_ORDERS = 12
STALE_ORDER_TIMEOUT_SECONDS = 60  # cancel unfilled orders after 60s
STALE_CHECK_INTERVAL = 30.0
CASH_RESERVE_RATIO = float(os.getenv("CASH_RESERVE_RATIO", "0.40"))  # keep 40% liquid
MAX_CAPITAL_PER_TRADE_RATIO = float(os.getenv("MAX_CAPITAL_PER_TRADE_RATIO", "0.10"))  # max 10% per trade
MAX_OPPORTUNITY_LOG_BYTES = 10 * 1024 * 1024  # 10 MB
PREFER_SPORTS_TECH = os.getenv("PREFER_SPORTS_TECH", "1").strip().lower() in ("1", "true", "yes")
MIN_SPORTS_TECH_PAIRS = int(os.getenv("MIN_SPORTS_TECH_PAIRS", "8"))
MAX_POLITICS_PAIRS = int(os.getenv("MAX_POLITICS_PAIRS", "2"))

# --- ABSOLUTE CAPITAL FLOOR ---
# Never allow wallet to drop below this amount.  Trades that would breach
# this floor are blocked.  Set via env or defaults to $5.
MIN_WALLET_FLOOR = float(os.getenv("MIN_WALLET_FLOOR", "5.0"))

# --- Quick-Flip Take-Profit / Stop-Loss ---
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "0.02"))   # Exit at +2% (fast exit)
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "0.05"))       # Cut loss at -5%
FLIP_CHECK_INTERVAL = int(os.getenv("FLIP_CHECK_SECONDS", "10"))  # Check exits every 10s
FILL_CONFIRM_WINDOW_SECONDS = int(os.getenv("FILL_CONFIRM_WINDOW_SECONDS", "15"))
FILL_CONFIRM_POLL_SECONDS = float(os.getenv("FILL_CONFIRM_POLL_SECONDS", "2"))

# --- Position Recycler Settings (fast turnover for paper testing) ---
RECYCLE_ENABLED = os.getenv("RECYCLE_ENABLED", "1").strip().lower() in ("1", "true", "yes")
# Support both MINUTES and legacy HOURS env vars
_recycle_interval_min = os.getenv("RECYCLE_INTERVAL_MINUTES")
_recycle_min_hold_min = os.getenv("RECYCLE_MIN_HOLD_MINUTES")
_recycle_max_hold_min = os.getenv("RECYCLE_MAX_HOLD_MINUTES")
if _recycle_interval_min:
    RECYCLE_INTERVAL_SECONDS = int(_recycle_interval_min) * 60
else:
    RECYCLE_INTERVAL_SECONDS = int(os.getenv("RECYCLE_INTERVAL_HOURS", "1")) * 3600
if _recycle_min_hold_min:
    RECYCLE_MIN_HOLD_SECONDS = int(_recycle_min_hold_min) * 60
else:
    RECYCLE_MIN_HOLD_SECONDS = int(float(os.getenv("RECYCLE_MIN_HOLD_HOURS", "0.5")) * 3600)
if _recycle_max_hold_min:
    RECYCLE_MAX_HOLD_SECONDS = int(_recycle_max_hold_min) * 60
else:
    RECYCLE_MAX_HOLD_SECONDS = int(os.getenv("RECYCLE_MAX_HOLD_HOURS", "1")) * 3600
RECYCLE_MIN_CASH_RESERVE = float(os.getenv("RECYCLE_MIN_CASH", str(MIN_WALLET_FLOOR)))

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
OPPORTUNITY_LOG_FILE = os.path.join(PROJECT_DIR, "opportunities.csv")
DATA_DIR = os.path.join(PROJECT_DIR, "data")
RUNTIME_STATE_FILE = os.path.join(DATA_DIR, "runtime_state.json")

# ---------- Category keyword sets ----------
CRYPTO_KEYWORDS = {
    "bitcoin","btc","ethereum","eth","crypto","cryptocurrency","solana","sol",
    "bnb","xrp","ripple","cardano","ada","doge","dogecoin","usdc","usdt",
    "defi","nft","blockchain","altcoin","polygon","matic","avax","avalanche",
    "chainlink","link","uniswap","aave","dai","litecoin","ltc","binance",
    "stablecoin","token","coin","coins","tokens","wallet","satoshi",
}

SPORTS_KEYWORDS = {
    # Leagues / governing bodies
    "nfl","nba","mlb","nhl","mls","ufc","pga","ncaa","fifa","uefa","atp","wta",
    # Events
    "super","bowl","championship","playoff","playoffs","finals","stanley","cup",
    "worldcup","world","series","open","classic","grand","prix","olympics",
    # Actions / outcomes
    "win","wins","beat","defeat","score","scores","scored","title","trophy",
    "draft","trade","transfer","contract","roster","suspended","injured",
    # Sport names
    "football","basketball","baseball","soccer","tennis","golf","boxing","mma",
    "wrestling","hockey","cricket","rugby","racing","f1","formula",
    # Generic sports terms
    "game","games","match","matches","season","tournament","league","team","teams",
    "player","players","coach","quarterback","touchdown","homerun","goal",
}

AI_TECH_KEYWORDS = {
    # AI companies & models
    "ai","openai","anthropic","gpt","claude","gemini","llm","llms","chatgpt",
    "deepmind","mistral","grok","perplexity","copilot","sora",
    # AI concepts
    "artificial","intelligence","machine","learning","neural","benchmark","agi",
    "superintelligence","reasoning","multimodal","inference","training","parameter",
    # Big Tech / leaders
    "nvidia","apple","google","amazon","meta","microsoft","tesla","spacex",
    "altman","musk","bezos","zuckerberg","pichai","nadella","huang",
    # Tech events
    "release","launch","version","update","regulation","antitrust","acquisition",
    "merger","ipo","funding","valuation","startup",
    # Other tech
    "quantum","computing","robotics","autonomous","self-driving","semiconductor",
    "chip","chips","cloud","cybersecurity","hack","breach",
}

POLITICS_KEYWORDS = {
    "election","elections","elect","vote","voting","ballot","poll","polls",
    "prime","minister","president","parliament","congress","senate","government",
    "coalition","party","candidate","incumbent","campaign","mayor","governor",
    "hungary","hungarian","orban","magyar","toroczkai",
}


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
                except (json.JSONDecodeError, ValueError): outcomes = ["No", "Yes"]
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
        self._position_book_lock = threading.Lock()
        self._csv_lock = threading.Lock()
        self._last_metrics_refresh = 0.0
        self._last_stale_check = 0.0
        
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
            "effective_threshold": max(MIN_PROFIT_THRESHOLD + POLYMARKET_FEE_RATE + SLIPPAGE_BUFFER, MIN_EFFECTIVE_EDGE),
        }
        
        # Recent activity logs (ring buffer)
        self.recent_logs: deque = deque(maxlen=200)
        self.recent_opportunities: deque = deque(maxlen=50)
        self.recent_trades: deque = deque(maxlen=50)
        self.sessions_info: List[Dict] = []
        self.position_book: Dict[str, Dict[str, float]] = {}
        self.exec_engine = None  # Set in run(); used by exit/recycler to record realized P&L

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

    def _log(self, level: str, message: str, **kwargs):
        """Add log entry to recent logs and standard logger."""
        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "level": level,
            "msg": message
        }
        self.recent_logs.append(entry)
        getattr(logger, level.lower(), logger.info)(message, **kwargs)

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

            # Sanity check: if net equity is deeply negative, the position book is
            # corrupt (e.g. phantom SHORTs from the hydration sign bug). Wipe it so
            # the reconciler can re-hydrate clean state from the exchange on startup.
            try:
                net_eq = float(self.state.get("net_equity_estimate") or 0.0)
            except (TypeError, ValueError):
                net_eq = 0.0
            if net_eq < -1.0:
                logger.warning(
                    f"STARTUP: net_equity_estimate=${net_eq:.2f} is deeply negative — "
                    f"position book is likely corrupt. Wiping {len(self.position_book)} "
                    f"phantom position(s) and forcing re-hydration from exchange."
                )
                self.position_book = {}
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
        try:
        # Prefer Data API (adapter.get_portfolio_positions) as it matches the UI
            pos_list = adapter.get_portfolio_positions()
            
            if not pos_list:
                # Fallback to ClobClient if Data API fails or returns nothing
                client = getattr(adapter, "client", None)
                if client:
                    for method_name in ("get_positions", "get_open_positions", "get_user_positions"):
                        method = getattr(client, method_name, None)
                        if callable(method):
                            raw = method()
                            if raw:
                                if isinstance(raw, dict):
                                    pos_list = raw.get("positions") or raw.get("data") or raw.get("items") or []
                                elif isinstance(raw, list):
                                    pos_list = raw
                                break

            if not pos_list:
                return

            restored = 0
            for p in pos_list:
                if not isinstance(p, dict):
                    continue
                    
                # Data API fields vs CLOB fields mapping
                # asset (Data API) is the decimal tokenId. asset_id/token_id (CLOB) are typically hex.
                token_id = str(p.get("asset") or p.get("asset_id") or p.get("token_id") or p.get("conditionId") or p.get("id") or "")
                if not token_id:
                    continue
                    
                qty = p.get("size", p.get("amount", p.get("quantity", p.get("shares", 0.0))))
                try:
                    shares = float(qty)
                except Exception:
                    continue
                    
                # In Polymarket CLOB, all positions are LONG (you hold tokens, never negative).
                # "outcome" is the token label (Yes/No), NOT the trade direction — never use it
                # to infer short. Only explicit "side"/"direction" fields indicate direction.
                side = str(p.get("side") or p.get("direction") or "").upper()
                if side in ("SELL", "SHORT"):
                    shares = -abs(shares)
                else:
                    shares = abs(shares)
                    
                if abs(shares) < 1e-8:
                    continue
                    
                mark = p.get("mark_price", p.get("mid_price", p.get("avg_entry_price", p.get("curPrice", 0.5))))
                try:
                    last_mid = float(mark)
                except Exception:
                    last_mid = 0.5
                    
                entry_raw = p.get("avg_entry_price", p.get("entry_price", p.get("avgPrice", last_mid)))
                try:
                    avg_entry = float(entry_raw)
                except Exception:
                    avg_entry = last_mid
                    
                self.position_book[token_id] = {
                    "shares": shares,
                    "last_mid": last_mid,
                    "avg_entry": avg_entry,
                    "question": p.get("title", p.get("question", "Imported Position")),
                }
                restored += 1

            if restored > 0:
                self._recompute_equity()
                self._save_runtime_state()
                self._log("INFO", f"Hydrated {restored} positions from Polymarket API.")
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

        # Sanity cap: reserved should not exceed 2× balance (API may return raw units)
        balance = self.state.get("wallet_balance") or 0.0
        if balance > 0 and reserved > balance * 2:
            logger.warning(f"Reserve estimate ${reserved:.2f} > 2× balance ${balance:.2f}; capping.")
            reserved = balance * 2
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

    def _refresh_account_metrics_cached(self, adapter, min_interval: float = 5.0):
        """Rate-limit account metric refreshes to avoid API overuse."""
        now = time.time()
        if now - self._last_metrics_refresh < min_interval:
            return
        self._refresh_account_metrics(adapter)
        self._last_metrics_refresh = now

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
            self.state["effective_threshold"] = max(
                self.state["min_profit_threshold"] + POLYMARKET_FEE_RATE + SLIPPAGE_BUFFER,
                MIN_EFFECTIVE_EDGE,
            )
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
        """Close a position by placing a sell/buy order using actual exchange balance.
        If token not in position_book, fetches balance from exchange (supports portfolio Close button)."""
        if not token_id:
            return {"ok": False, "msg": "No token_id provided"}

        try:
            from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
            adapter = PolymarketAdapter()
            params = BalanceAllowanceParams(
                asset_type=AssetType.CONDITIONAL,
                token_id=token_id,
                signature_type=adapter.signature_type
            )
            adapter.client.update_balance_allowance(params)
            bal = adapter.client.get_balance_allowance(params)
            actual_shares = int(bal.get("balance", "0")) / 1e6
        except Exception as e:
            self._log("ERROR", f"Failed to fetch balance for ...{token_id[-8:]}: {e}")
            return {"ok": False, "msg": str(e)}

        if actual_shares < 1:
            # Not in book and no exchange balance — try reconciling first
            if token_id not in self.position_book:
                self._runtime_reconcile_positions(adapter)
                if token_id in self.position_book:
                    pos = self.position_book[token_id]
                    actual_shares = float(pos.get("shares", 0.0))
            if actual_shares < 1:
                return {"ok": False, "msg": f"Position not found or too small (...{token_id[-8:]})"}

        pos = self.position_book.get(token_id, {})
        mid = float(pos.get("last_mid", 0.0))
        if mid <= 0:
            book = adapter.get_best_bid_ask(token_id)
            mid = book.get("mid", 0.05)
        shares = actual_shares

        if abs(shares) < 1:
            return {"ok": False, "msg": f"Position too small to close ({shares:.2f} shares)"}

        try:
            if shares > 0:
                # Long position -> SELL to close (re-fetch balance for freshness)
                adapter.client.update_balance_allowance(params)
                bal = adapter.client.get_balance_allowance(params)
                actual_shares = int(bal.get("balance", "0")) / 1e6
                if actual_shares < 1:
                    return {"ok": False, "msg": f"No shares found on exchange (book says {shares:.0f}, exchange says {actual_shares:.0f})"}

                sell_price = self._compute_exit_price(adapter, token_id, mid, "SELL")
                num_shares = round(actual_shares - 1, 0)  # keep 1 share buffer
                self._log("INFO", f"CLOSING LONG: SELL {num_shares:.0f} of {actual_shares:.0f} actual shares of ...{token_id[-8:]} @ ${sell_price}")
                resp = adapter.place_close_order(token_id, "SELL", sell_price, num_shares)
            else:
                # Short position -> BUY to close
                buy_price = self._compute_exit_price(adapter, token_id, mid, "BUY")
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
            self.state["status"] = "starting"
            
            adapter = PolymarketAdapter()
            exec_engine = ExecutionEngine(adapter)
            self.exec_engine = exec_engine  # Store so _check_exit_signals / _run_position_recycler can record P&L
            self.state["daily_pnl"] = float(exec_engine.daily_pnl)
            self.state["realized_pnl"] = float(exec_engine.daily_pnl)
            dep_detector = DependencyDetector()

            # Connect WS
            adapter.connect_ws()
            time.sleep(2)

            # Check initial balance & positions
            if self.state["mode"] == "LIVE":
                self._refresh_account_metrics_cached(adapter)
                self._hydrate_positions_from_exchange(adapter)
                self._recompute_equity()

            self.state["status"] = "scanning"
            self._log("INFO", "Bot services active. Initializing market monitoring...")

            sessions = []
            all_token_ids = []
            
            # Monitoring loop state
            last_pair_scan = 0
            PAIR_SCAN_INTERVAL = 300  # Scan for new pairs every 5 mins
            poll_counter = 0
            last_recycle_time = time.time()
            last_flip_check = time.time()

            # Defined up here so sessions can refer to it
            def on_price_update(data):
                nonlocal sessions
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
                        if profit <= cur_threshold or not session.can_trade(): continue

                        # SAFETY CHECK: $5 cash floor
                        cash = self.state.get("wallet_balance", 0.0)
                        if self.state["mode"] == "LIVE" and cash < MIN_WALLET_FLOOR:
                            self._log("WARNING", f"Trade blocked: Cash balance ${cash:.2f} is below safety floor ${MIN_WALLET_FLOOR}.")
                            continue

                        self._log("INFO", f"TRADE SIGNAL (WS): Profit ${profit:.4f}")
                        orders = self._build_orders(session, mu_star)
                        if orders:
                            self._execute_orders(exec_engine, orders, session, adapter)
                except Exception as e:
                    self._log("ERROR", f"WS handler error: {e}")

            adapter.add_callback(on_price_update)

            # --- Main Loop ---
            while not self._stop_event.is_set():
                time.sleep(1)
                poll_counter += 1

                # A. Scan for pairs if needed (e.g. initial start or periodically)
                seconds_since_last_scan = time.time() - last_pair_scan
                if (not sessions and seconds_since_last_scan > 60) or (seconds_since_last_scan > PAIR_SCAN_INTERVAL):
                    pair_count_before = len(sessions)
                    self.state["status"] = "scanning"
                    markets = adapter.get_markets(limit=MAX_MARKETS_TO_FETCH)
                    if markets:
                        all_pairs = self._find_related_pairs(markets, dep_detector)
                        if all_pairs:
                            sessions = []
                            all_token_ids = []
                            for pm, vo in all_pairs:
                                s = MonitoringSession(pm, vo)
                                sessions.append(s)
                                all_token_ids.extend(list(s.token_map.keys()))
                            
                            adapter.subscribe(all_token_ids)
                            # Pre-fill prices
                            for s in sessions:
                                for tid in s.token_map:
                                    book = adapter.get_best_bid_ask(tid)
                                    if book["mid"] > 0:
                                        s.update_price(tid, book["mid"], book["bid"], book["ask"])
                            
                            self.state["pairs_monitored"] = len(sessions)
                            self.state["tokens_subscribed"] = len(all_token_ids)
                            self.sessions_info = [s.to_dict() for s in sessions]
                            self._log("INFO", f"Scanning complete: Monitoring {len(sessions)} pairs.")
                        else:
                            if pair_count_before == 0:
                                self._log("INFO", "No dependent pairs found in initial scan. Will keep searching (cooldown active)...")

                    last_pair_scan = time.time()
                    self.state["status"] = "running" if sessions else "scanning"

                # B. WebSocket health
                if not adapter.is_ws_connected():
                    self._log("WARNING", "WebSocket offline. Reconnecting...")
                    adapter.reconnect_ws()
                    if adapter.is_ws_connected() and all_token_ids:
                        adapter.subscribe(all_token_ids)

                # C. Exit signals (TP/SL)
                if self.state["mode"] == "LIVE" and (time.time() - last_flip_check) >= FLIP_CHECK_INTERVAL:
                    try:
                        self._check_exit_signals(adapter)
                        last_flip_check = time.time()
                    except Exception as e:
                        self._log("WARNING", f"Exit check error: {e}")

                # D. Cancel stale orders
                if poll_counter % 30 == 0 and self.state["mode"] == "LIVE":
                    self._cancel_stale_orders(adapter)

                # E. Position recycler
                if self.state["mode"] == "LIVE":
                    cash = self.state.get("wallet_balance", 0.0)
                    time_since_recycle = time.time() - last_recycle_time
                    # Recycler runs every interval, OR every 5 mins if cash is critically low
                    rc_interval = min(RECYCLE_INTERVAL_SECONDS, 300) if cash < MIN_WALLET_FLOOR else RECYCLE_INTERVAL_SECONDS
                    if time_since_recycle >= rc_interval:
                        try:
                            self._run_position_recycler(adapter)
                            last_recycle_time = time.time()
                        except Exception as e:
                            self._log("WARNING", f"Recycler error: {e}")

                # F. Periodic REST poll & balance refresh
                if poll_counter % 30 == 0:
                    for session in sessions:
                        for token_id in session.token_map:
                            book = adapter.get_best_bid_ask(token_id)
                            if book["mid"] > 0:
                                session.update_price(token_id, book["mid"], book["bid"], book["ask"])
                                self._update_mark_price(token_id, book["mid"])
                        
                        # Background trade check (REST-based)
                        profit, mu_star = session.run_analysis()
                        if profit and profit > self._adaptive_threshold(session) and session.can_trade():
                            # Re-check floor
                            if self.state["mode"] != "LIVE" or self.state["wallet_balance"] >= MIN_WALLET_FLOOR:
                                orders = self._build_orders(session, mu_star)
                                if orders:
                                    self._execute_orders(exec_engine, orders, session, adapter)
                    
                    if self.state["mode"] == "LIVE":
                        self._refresh_account_metrics_cached(adapter)
                    self.sessions_info = [s.to_dict() for s in sessions]

                # G. Runtime reconciliation (every ~10 min)
                if poll_counter % 600 == 0 and self.state["mode"] == "LIVE":
                    try:
                        self._runtime_reconcile_positions(adapter)
                    except Exception as e:
                        self._log("WARNING", f"Runtime reconciliation error: {e}")

            self.state["status"] = "stopped"
            self._log("INFO", "Bot loop ended.")

        except Exception as e:
            self._log("ERROR", f"Bot crashed: {e}", exc_info=True)
            self.state["status"] = "error"
            self.state["last_error"] = str(e)
            self._save_runtime_state()

    def _find_related_pairs(self, markets, dep_detector):
        """Find related pairs DIVERSIFIED across different topics.
        
        Scoring now incorporates:
        - Structural similarity (stem matching, ladder keywords)
        - Liquidity (avg volume × tighter spread = higher score)
        - Time preference (shorter resolution horizon = higher score)
        """
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
                # --- Crypto exclusion: skip any pair where either question is crypto-related ---
                q1_words = set(q1.split())
                q2_words = set(q2.split())
                if (q1_words & CRYPTO_KEYWORDS) or (q2_words & CRYPTO_KEYWORDS):
                    continue
                overlap = (set(q1.split()) & set(q2.split())) - stop
                if len(overlap) >= 2:
                    topic_key = tuple(sorted(overlap))
                    stem1 = re.sub(r"\b(20\d{2}|\$?\d[\d,\.]*[bkmt]?|between|less|more|than|at|least|over|under)\b", " ", q1)
                    stem2 = re.sub(r"\b(20\d{2}|\$?\d[\d,\.]*[bkmt]?|between|less|more|than|at|least|over|under)\b", " ", q2)
                    stem1 = " ".join(stem1.split())
                    stem2 = " ".join(stem2.split())
                    same_stem = 1 if stem1[:80] == stem2[:80] else 0
                    ladder_like = 1 if (("between" in q1 or "less than" in q1 or "more than" in q1) and ("between" in q2 or "less than" in q2 or "more than" in q2)) else 0

                    # --- Structural score ---
                    structural = (len(overlap) * 10) + (same_stem * 40) + (ladder_like * 25)

                    # --- Liquidity score  (NEW) ---
                    vol1 = float(m1.get("_volume_24h", 0))
                    vol2 = float(m2.get("_volume_24h", 0))
                    avg_vol = (vol1 + vol2) / 2.0
                    spr1 = float(m1.get("_spread_pct", 1.0))
                    spr2 = float(m2.get("_spread_pct", 1.0))
                    avg_spread = (spr1 + spr2) / 2.0
                    # More volume + tighter spread = better.  log scale to dampen outliers.
                    import math
                    liquidity_score = math.log1p(avg_vol) * 5 * max(1.0 - avg_spread, 0.1)

                    # --- Horizon score (NEW): prefer sooner-resolving markets ---
                    d1 = m1.get("_days_to_end")
                    d2 = m2.get("_days_to_end")
                    if d1 is not None and d2 is not None:
                        avg_days = (d1 + d2) / 2.0
                        horizon_score = max(30 - avg_days, 0) * 0.5  # up to +15 for same-day
                    else:
                        horizon_score = 0

                    # --- Category boost: heavily reward Sports and AI/Tech pairs ---
                    category_boost = 0
                    if overlap & SPORTS_KEYWORDS:
                        category_boost += 80
                    if overlap & AI_TECH_KEYWORDS:
                        category_boost += 60

                    execution_score = structural + liquidity_score + horizon_score + category_boost
                    all_candidates.append((m1, m2, len(overlap), topic_key, execution_score))

        self._log("INFO", f"Found {len(all_candidates)} total candidate pairs.")

        # Step 2: Group by topic and pick best pairs from DIFFERENT topics
        from collections import defaultdict
        topic_groups = defaultdict(list)
        for m1, m2, score, topic, exec_score in all_candidates:
            short_topic = tuple(sorted(topic)[:3])
            topic_groups[short_topic].append((m1, m2, score, topic, exec_score))

        MAX_PER_TOPIC = 2
        diversified = []
        for topic, pairs in sorted(topic_groups.items(), key=lambda x: -max(p[4] for p in x[1])):
            pairs.sort(key=lambda x: x[4], reverse=True)
            for p in pairs[:MAX_PER_TOPIC]:
                diversified.append(p)
            if len(diversified) >= MAX_PAIRS_TO_ANALYZE * 2:
                break

        # Step 2b: Category rebalance to avoid politics concentration
        def _pair_category(m1, m2):
            words = set(m1["question"].lower().split()) | set(m2["question"].lower().split())
            if (words & SPORTS_KEYWORDS) or (words & AI_TECH_KEYWORDS):
                return "preferred"  # SPORTS or AI/TECH
            if words & POLITICS_KEYWORDS:
                return "politics"
            return "other"

        if PREFER_SPORTS_TECH:
            preferred_pairs = []
            politics_pairs = []
            other_pairs = []
            for pair in diversified:
                m1, m2, _, _, _ = pair
                cat = _pair_category(m1, m2)
                if cat == "preferred":
                    preferred_pairs.append(pair)
                elif cat == "politics":
                    politics_pairs.append(pair)
                else:
                    other_pairs.append(pair)

            selected = []
            preferred_target = min(len(preferred_pairs), min(MIN_SPORTS_TECH_PAIRS, MAX_PAIRS_TO_ANALYZE))
            selected.extend(preferred_pairs[:preferred_target])

            politics_cap = max(0, MAX_POLITICS_PAIRS)
            remaining_slots = MAX_PAIRS_TO_ANALYZE - len(selected)
            selected.extend(politics_pairs[:min(politics_cap, remaining_slots)])

            remaining_slots = MAX_PAIRS_TO_ANALYZE - len(selected)
            selected.extend(other_pairs[:remaining_slots])

            remaining_slots = MAX_PAIRS_TO_ANALYZE - len(selected)
            if remaining_slots > 0:
                selected.extend(preferred_pairs[preferred_target:preferred_target + remaining_slots])

            remaining_slots = MAX_PAIRS_TO_ANALYZE - len(selected)
            if remaining_slots > 0:
                selected.extend(politics_pairs[min(politics_cap, len(politics_pairs)):min(politics_cap, len(politics_pairs)) + remaining_slots])

            diversified = selected[:MAX_PAIRS_TO_ANALYZE]
            self._log(
                "INFO",
                f"Category rebalance: preferred={len(preferred_pairs)}, politics={len(politics_pairs)}, "
                f"other={len(other_pairs)}, selected={len(diversified)}"
            )
        else:
            diversified = diversified[:MAX_PAIRS_TO_ANALYZE]
        
        topics_found = set()
        for _, _, _, topic, _ in diversified:
            topics_found.add(tuple(sorted(topic)[:3]))
        self._log("INFO", f"Selected {len(diversified)} pairs across {len(topics_found)} different topics.")

        # Step 3: LLM analysis (cached — see engine/dependency.py)
        found = []
        for m1, m2, score, topic, exec_score in diversified:
            if self._stop_event.is_set(): break
            cats = []
            combined_q = set(m1['question'].lower().split()) | set(m2['question'].lower().split())
            if combined_q & SPORTS_KEYWORDS: cats.append("SPORTS")
            if combined_q & AI_TECH_KEYWORDS: cats.append("AI/TECH")
            if not cats: cats.append("OTHER")
            self._log("INFO", f"LLM analyzing [{'+'.join(cats)}](score={exec_score:.1f}): '{m1['question'][:50]}' vs '{m2['question'][:50]}'")
            result = dep_detector.analyze_market_pair(m1, m2)
            if result and len(result) < 4:
                self._log("INFO", f"Dependency found! ({len(result)} valid combos)")
                matrix = convert_outcomes_to_vectors(result)
                found.append(([m1, m2], matrix))

        # Log LLM cache efficiency
        stats = dep_detector.get_cache_stats()
        total = stats['hits'] + stats['misses']
        if total > 0:
            self._log("INFO", f"LLM cache: {stats['hits']}/{total} hits ({stats['hits']*100//max(total,1)}% saved)")
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
                # Only SELL tokens we actually hold — Polymarket has no true short-selling.
                pos = self.position_book.get(tid, {})
                if pos.get("shares", 0) <= 0:
                    continue
                ep = session.best_bids.get(tid, price)
                if ep <= 0: ep = price
                if ep < MIN_EXEC_PRICE or ep > MAX_EXEC_PRICE:
                    continue
                orders.append({
                    "token_id": tid, "side": "SELL", "price": round(ep, 4),
                    "size": leg, "fair_value": round(fair, 4),
                })

        # Avoid single-leg directional bets from a multi-leg arb detector.
        if len(orders) < 2:
            return []

        # Conservative gate: recompute divergence with executable prices
        # (buy at ask, sell at bid) and skip if edge vanishes after costs.
        exec_prices = np.array(session.prices, dtype=float).copy()
        for o in orders:
            idx = session.token_map.get(o["token_id"])
            if idx is not None:
                exec_prices[idx] = float(o["price"])

        exec_profit = MarketMath.calculate_profit(exec_prices, mu_star)
        threshold = self._adaptive_threshold(session)
        if exec_profit <= threshold:
            self._log(
                "INFO",
                f"Skip signal: executable edge {exec_profit:.5f} <= threshold {threshold:.5f}",
            )
            return []

        # Optional dollar sanity check for BUY capital deployment.
        buy_notional = sum(float(o["size"]) for o in orders if o["side"] == "BUY")
        if buy_notional > 0:
            est_dollar = MarketMath.estimate_dollar_profit(
                exec_prices, mu_star, buy_notional, fee_rate=POLYMARKET_FEE_RATE
            )
            if est_dollar <= 0:
                self._log(
                    "INFO",
                    f"Skip signal: estimated net dollar profit <= 0 (est=${est_dollar:.4f})",
                )
                return []

        return orders

    def _adaptive_threshold(self, session) -> float:
        """
        Dynamic execution threshold:
        - Never go below MIN_EFFECTIVE_EDGE (covers round-trip fees + slippage).
        - Keep user's configured threshold as the upper bound.
        - Allow lower threshold on tighter books to increase executable flow,
          but ONLY down to the fee-breakeven floor.
        """
        configured = float(self.state["effective_threshold"])
        # Absolute floor: must cover 2× (fee + slippage) to break even
        floor = MIN_EFFECTIVE_EDGE
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
            return max(configured, floor)
        avg_spread = sum(spreads) / len(spreads)
        avg_mid = sum(mids) / len(mids) if mids else 0.5

        # Tight books can be traded at lower theoretical edge,
        # but still must clear the fee floor.
        if avg_spread <= 0.05 and 0.03 <= avg_mid <= 0.97:
            return max(min(configured, floor * 1.0), floor)
        if avg_spread <= 0.10 and 0.02 <= avg_mid <= 0.98:
            return max(min(configured, floor * 1.2), floor)
        if avg_spread <= 0.18 and 0.01 <= avg_mid <= 0.99:
            return max(min(configured, floor * 1.5), floor)
        return max(configured, floor)

    def _execute_orders(self, exec_engine, orders, session, adapter):
        if not self._trade_lock.acquire(blocking=False):
            return
        try:
            self._execute_orders_inner(exec_engine, orders, session, adapter)
        finally:
            self._trade_lock.release()

    def _get_token_share_balance(self, adapter, token_id: str) -> float:
        """Read authoritative exchange share balance for one conditional token."""
        try:
            from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
            params = BalanceAllowanceParams(
                asset_type=AssetType.CONDITIONAL,
                token_id=token_id,
                signature_type=adapter.signature_type
            )
            bal = adapter.client.get_balance_allowance(params)
            return int(bal.get("balance", "0")) / 1e6
        except Exception:
            return 0.0

    def _confirm_recent_fills(self, adapter, exec_results, pre_balances: Dict[str, float]):
        """
        Confirm fills by polling real exchange balances shortly after order placement.
        This captures delayed/partial matches that are not marked as immediate fills.
        """
        if not exec_results or not pre_balances:
            return

        poll_every = max(FILL_CONFIRM_POLL_SECONDS, 0.5)
        deadline = time.time() + max(FILL_CONFIRM_WINDOW_SECONDS, 1)
        tokens = list(pre_balances.keys())
        latest = dict(pre_balances)

        while time.time() < deadline:
            for tid in tokens:
                latest[tid] = self._get_token_share_balance(adapter, tid)
            time.sleep(poll_every)

        # Net share movement by token after execution window
        net_delta = {tid: latest.get(tid, 0.0) - pre_balances.get(tid, 0.0) for tid in tokens}

        # Reserve already-accounted immediate fills so we don't double count.
        reserved_buy = {}
        reserved_sell = {}
        for r in exec_results:
            if not r.get("filled"):
                continue
            o = r.get("order", {})
            tid = o.get("token_id")
            side = str(o.get("side", "")).upper()
            price = float(o.get("price", 0) or 0)
            size = float(o.get("size", 0) or 0)
            if not tid or price <= 0:
                continue

            # Unit convention:
            # BUY  -> size is USDC cost, convert to shares.
            # SELL -> size is already shares.
            if side == "BUY":
                shares = size / price
            elif side == "SELL":
                shares = size
            else:
                continue

            if side == "BUY":
                reserved_buy[tid] = reserved_buy.get(tid, 0.0) + shares
            elif side == "SELL":
                reserved_sell[tid] = reserved_sell.get(tid, 0.0) + shares

        remaining = {}
        for tid, delta in net_delta.items():
            buy_rem = max(delta, 0.0) - reserved_buy.get(tid, 0.0)
            sell_rem = max(-delta, 0.0) - reserved_sell.get(tid, 0.0)
            remaining[(tid, "BUY")] = max(buy_rem, 0.0)
            remaining[(tid, "SELL")] = max(sell_rem, 0.0)

        confirmed = 0
        for r in exec_results:
            if not r.get("ok") or r.get("filled"):
                continue
            o = r.get("order", {})
            tid = o.get("token_id")
            side = str(o.get("side", "")).upper()
            price = float(o.get("price", 0) or 0)
            size = float(o.get("size", 0) or 0)
            if not tid or side not in ("BUY", "SELL") or price <= 0 or size <= 0:
                continue

            if side == "BUY":
                expected_shares = size / price
            else:
                expected_shares = size

            key = (tid, side)
            avail = remaining.get(key, 0.0)
            matched_shares = min(expected_shares, avail)
            if matched_shares < 0.1:
                continue

            remaining[key] = max(avail - matched_shares, 0.0)
            matched_order = dict(o)
            matched_order["size"] = round(matched_shares * price, 4) if side == "BUY" else round(matched_shares, 4)
            with self._position_book_lock:
                self._apply_filled_order(matched_order)
            r["filled"] = True
            r["confirmed_by_balance"] = True
            r["filled_shares"] = round(matched_shares, 4)
            confirmed += 1

        if confirmed > 0:
            self._log("INFO", f"Post-trade confirm: {confirmed} delayed fill(s) reconciled from exchange balances.")

    def _execute_orders_inner(self, exec_engine, orders, session, adapter):
        total_buy_cost = sum(o["size"] for o in orders if o["side"] == "BUY")

        # ── CAPITAL FLOOR CHECK (LIVE only; PAPER mode uses simulated balance) ──
        if self.state.get("mode") == "LIVE":
            balance = self.state.get("wallet_balance") or 0.0
            if balance - total_buy_cost < MIN_WALLET_FLOOR:
                self._log("WARNING",
                    f"🛑 CAPITAL FLOOR: ${balance:.2f} - ${total_buy_cost:.2f} trade "
                    f"= ${balance - total_buy_cost:.2f} (floor=${MIN_WALLET_FLOOR:.2f}). BLOCKED."
                )
                return

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

            # Re-check floor with fresh balance
            if balance - total_buy_cost < MIN_WALLET_FLOOR:
                self._log("WARNING",
                    f"🛑 CAPITAL FLOOR (refreshed): ${balance:.2f} bal "
                    f"- ${total_buy_cost:.2f} = ${balance - total_buy_cost:.2f}. BLOCKED."
                )
                return

            min_reserve = max(min(equity * CASH_RESERVE_RATIO, balance * 0.40), MIN_WALLET_FLOOR)
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

        pre_balances = {}
        if self.state.get("mode") == "LIVE":
            try:
                token_ids = sorted({str(o.get("token_id", "")) for o in orders if o.get("token_id")})
                pre_balances = {tid: self._get_token_share_balance(adapter, tid) for tid in token_ids}
            except Exception:
                pre_balances = {}

        exec_results = []
        try:
            exec_results = exec_engine.execute_arbitrage(orders, mode=self.state["mode"])
        finally:
            session.mark_traded()

        if self.state.get("mode") == "LIVE":
            for r in exec_results:
                if r.get("filled"):
                    with self._position_book_lock:
                        self._apply_filled_order(r["order"])
            t = threading.Thread(
                target=self._confirm_recent_fills,
                args=(adapter, exec_results, pre_balances),
                daemon=True,
            )
            t.start()
        self.state["daily_pnl"] = exec_engine.daily_pnl
        self.state["realized_pnl"] = float(exec_engine.daily_pnl)
        if self.state.get("mode") == "LIVE":
            self._refresh_account_metrics_cached(adapter)
        self._recompute_equity()
        self._save_runtime_state()

    def _apply_filled_order(self, order: Dict[str, float]):
        # NOTE: Polymarket CLOB is long-only. All conditional token
        # positions are non-negative. Short-selling is not supported.
        """Update internal long-only position book assuming order was filled."""
        token_id = order["token_id"]
        price = float(order["price"])
        size = float(order["size"])
        if price <= 0:
            return
        delta = size / price
        side = str(order["side"]).upper()
        if side not in ("BUY", "SELL"):
            return
        if token_id not in self.position_book and side == "SELL":
            self._log("INFO", f"Ignoring SELL fill for unknown long-only token ...{token_id[-8:]}")
            return

        if token_id not in self.position_book:
            fair = float(order.get("fair_value", 0))
            tp = fair if fair > price else min(price * (1 + TAKE_PROFIT_PCT), 0.99)
            sl = max(price * (1 - STOP_LOSS_PCT), 0.01)
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

        if side == "BUY":
            total_shares = prev_shares + delta
            new_avg = (
                ((prev_shares * prev_avg) + (delta * price)) / max(total_shares, 1e-12)
                if total_shares > 0 else price
            )
            new_shares = total_shares
        else:
            new_shares = max(prev_shares - delta, 0.0)
            new_avg = prev_avg

        pos["shares"] = new_shares
        pos["last_mid"] = price
        pos["avg_entry"] = new_avg

        # Prune dust
        if pos["shares"] < 1e-8:
            del self.position_book[token_id]

    def _update_mark_price(self, token_id: str, mid: float):
        if token_id in self.position_book and mid > 0:
            self.position_book[token_id]["last_mid"] = mid

    def _compute_exit_price(self, adapter: PolymarketAdapter, token_id: str, mid: float, side: str) -> float:
        """
        Dynamic close pricing using live top-of-book when available.
        Falls back to a small adaptive concession from mid.
        """
        tick = 0.01
        side_u = side.upper()
        bid = ask = 0.0
        try:
            book = adapter.get_best_bid_ask(token_id)
            bid = float(book.get("bid", 0.0) or 0.0)
            ask = float(book.get("ask", 0.0) or 0.0)
        except Exception:
            pass

        spread = max(ask - bid, 0.0) if ask > 0 and bid > 0 else 0.0
        concession = max(tick, min(spread * 0.25, 0.03))

        if side_u == "SELL":
            if bid > 0:
                px = max(bid, mid - concession)
            else:
                px = max(mid - concession, MIN_EXEC_PRICE)
        else:
            if ask > 0 and ask < 0.999:
                px = min(ask, mid + concession)
            else:
                px = min(mid + concession, MAX_EXEC_PRICE)

        return round(min(max(px, MIN_EXEC_PRICE), MAX_EXEC_PRICE), 2)

    def _check_exit_signals(self, adapter):
        # NOTE: Polymarket CLOB is long-only. All conditional token
        # positions are non-negative. Short-selling is not supported.
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

            reason = None

            if target and mid >= target:
                reason = "TAKE-PROFIT"
            elif stop and mid <= stop:
                reason = "STOP-LOSS"

            if not reason:
                continue

            pnl_per = (mid - avg_entry)
            pnl_pct = (pnl_per / max(avg_entry, 0.001)) * 100
            age_min = (time.time() - float(p.get("opened_at", time.time()))) / 60

            try:
                params = BalanceAllowanceParams(
                    asset_type=AssetType.CONDITIONAL,
                    token_id=token_id,
                    signature_type=adapter.signature_type
                )
                adapter.client.update_balance_allowance(params)
                bal = adapter.client.get_balance_allowance(params)
                actual = int(bal.get("balance", "0")) / 1e6
                if actual < 1:
                    self.position_book.pop(token_id, None)
                    continue

                num = math.floor(actual)
                if actual > 2:
                    num = max(math.floor(actual - 1), 1)
                if num < 1:
                    self._log("INFO", f"SKIP EXIT: only {actual:.2f} shares on exchange for ...{token_id[-8:]}, removing from book")
                    self.position_book.pop(token_id, None)
                    continue

                sell_price = self._compute_exit_price(adapter, token_id, mid, "SELL")
                self._log("INFO",
                    f"{reason}: SELL {num:.0f} shares ...{token_id[-8:]} "
                    f"@ ${sell_price} (entry ${avg_entry:.3f}, PnL {pnl_pct:+.1f}%, held {age_min:.0f}min)"
                )
                resp = adapter.place_close_order(token_id, "SELL", sell_price, num)

                if resp:
                    exits_triggered += 1
                    # Record realized P&L from the actual exit price (not mid estimate).
                    realized_pnl = (sell_price - avg_entry) * num
                    engine = self.exec_engine
                    if engine is not None:
                        engine.record_trade_result(realized_pnl)
                        self.state["daily_pnl"] = engine.daily_pnl
                        self.state["realized_pnl"] = float(engine.daily_pnl)
                    # Remove from position book immediately so the next 10s tick
                    # doesn't re-trigger the same exit order before the reconciler runs.
                    self.position_book.pop(token_id, None)
                    self._recompute_equity()
            except Exception as e:
                self._log("WARNING", f"Exit order failed for ...{token_id[-8:]}: {e}")

        if exits_triggered > 0:
            self._log("INFO", f"Quick-flip: {exits_triggered} exit(s) triggered")
            self._refresh_account_metrics_cached(adapter)
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
        now = time.time()
        if now - self._last_stale_check < STALE_CHECK_INTERVAL:
            return
        self._last_stale_check = now
        try:
            orders = adapter.get_open_orders()
            if not orders:
                return

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
                    elif isinstance(created_raw, str) and re.fullmatch(r"\d+(\.\d+)?", created_raw.strip()):
                        created_ts = float(created_raw.strip())
                    else:
                        created_dt = datetime.fromisoformat(str(created_raw).replace("Z", "+00:00"))
                        created_ts = created_dt.timestamp()

                    # API timestamps may arrive in milliseconds.
                    if created_ts > 1e12:
                        created_ts /= 1000.0

                    age_seconds = now - created_ts

                    # Ignore invalid timestamps rather than mass-canceling.
                    if age_seconds < 0 or age_seconds > 86400 * 30:
                        continue

                    if age_seconds > STALE_ORDER_TIMEOUT_SECONDS:
                        order_id = o.get("id") or o.get("orderID") or o.get("order_id")
                        if order_id:
                            self._log("INFO", f"Cancelling stale order (age={int(age_seconds)}s): {order_id[:16]}...")
                            adapter.cancel_order(order_id)
                            cancelled_count += 1
                except Exception:
                    continue
            
            if cancelled_count > 0:
                self._log("INFO", f"Cancelled {cancelled_count} stale orders.")
                # Refresh metrics after cancellations
                self._refresh_account_metrics_cached(adapter)
        except Exception as e:
            self._log("WARNING", f"Stale order cleanup failed: {e}")

    # ------------------------------------------------------------------
    # Runtime reconciliation: continuous sync against Polymarket Data API
    # ------------------------------------------------------------------

    def _runtime_reconcile_positions(self, adapter):
        """
        Full reconciliation against Polymarket Data API (runs every ~10 min in LIVE mode).

        - Positions on exchange but NOT in internal book → added (prevents missing fills)
        - Positions in internal book but NOT on exchange (or < 1 share) → removed (prevents phantoms)
        - Positions in both → update shares and last_mid from authoritative exchange data

        This is the same logic used at startup (_hydrate_positions_from_exchange) but
        runs continuously so the book stays accurate even after reconnects or crashes.
        """
        if self.state.get("mode") != "LIVE":
            return
        try:
            pos_list = adapter.get_portfolio_positions()
        except Exception as e:
            self._log("WARNING", f"Runtime reconcile: failed to fetch exchange positions: {e}")
            return

        if pos_list is None:
            return

        # Build a set of exchange token IDs for quick lookup
        exchange_tokens: dict = {}
        for p in pos_list:
            if not isinstance(p, dict):
                continue
            token_id = str(p.get("asset") or p.get("asset_id") or p.get("token_id") or "")
            if not token_id:
                continue
            try:
                shares = float(p.get("size", p.get("amount", p.get("shares", 0.0))))
            except Exception:
                shares = 0.0
            try:
                cur_price = float(p.get("curPrice", p.get("avg_entry_price", 0.5)))
            except Exception:
                cur_price = 0.5
            try:
                avg_price = float(p.get("avgPrice", p.get("avg_entry_price", cur_price)))
            except Exception:
                avg_price = cur_price
            exchange_tokens[token_id] = {
                "shares": shares,
                "last_mid": cur_price,
                "avg_entry": avg_price,
                "question": p.get("title", p.get("question", "")),
            }

        added = removed = updated = 0

        # 1. Remove book entries that are no longer on exchange (or < 1 share)
        for token_id in list(self.position_book.keys()):
            if token_id not in exchange_tokens or exchange_tokens[token_id]["shares"] < 1:
                book_shares = self.position_book[token_id].get("shares", 0)
                self._log(
                    "INFO",
                    f"RECONCILE: Removing ...{token_id[-8:]} from book "
                    f"(book={book_shares:.1f}, exchange="
                    f"{exchange_tokens.get(token_id, {}).get('shares', 0):.1f})"
                )
                del self.position_book[token_id]
                removed += 1

        # 2. Update existing entries and add missing ones from exchange
        for token_id, ex in exchange_tokens.items():
            if ex["shares"] < 1:
                continue  # ignore dust
            if token_id in self.position_book:
                # Update mark price and shares from authoritative source
                self.position_book[token_id]["last_mid"] = ex["last_mid"]
                self.position_book[token_id]["shares"] = ex["shares"]
                updated += 1
            else:
                # Position exists on exchange but not in our book — add it
                self._log(
                    "INFO",
                    f"RECONCILE: Adding missing position ...{token_id[-8:]} "
                    f"({ex['shares']:.1f} shares @ {ex['last_mid']:.4f})"
                )
                avg = ex["avg_entry"]
                tp = min(avg * (1 + TAKE_PROFIT_PCT), 0.99)
                sl = max(avg * (1 - STOP_LOSS_PCT), 0.01)
                self.position_book[token_id] = {
                    "shares": ex["shares"],
                    "last_mid": ex["last_mid"],
                    "avg_entry": avg,
                    "opened_at": time.time(),
                    "question": ex["question"],
                    "target_exit": round(tp, 4),
                    "stop_exit": round(sl, 4),
                }
                added += 1

        if added + removed + updated > 0:
            self._log(
                "INFO",
                f"RECONCILE complete: +{added} added, -{removed} removed, ~{updated} updated "
                f"({len(self.position_book)} positions total)"
            )
            self._recompute_equity()
            self._save_runtime_state()


    def _reconcile_position_book(self, adapter):
        """@deprecated: use _runtime_reconcile_positions() as single source of truth."""
        self._runtime_reconcile_positions(adapter)

    def _run_position_recycler(self, adapter):
        # NOTE: Polymarket CLOB is long-only. All conditional token
        # positions are non-negative. Short-selling is not supported.
        """
        Automatic position recycling logic. Called periodically from the main loop.

        Two-phase approach:
          Phase 0 — RECONCILE book vs exchange (remove phantoms)
          Phase 1 — SELL longs (requires shares on exchange, NOT cash)
        """
        if self.state.get("mode") != "LIVE":
            return
        if not RECYCLE_ENABLED:
            return

        # Phase 0: Reconcile before any trading decisions
        self._runtime_reconcile_positions(adapter)

        if not self.position_book:
            return

        from py_clob_client.clob_types import BalanceAllowanceParams, AssetType

        now = time.time()
        cash = self.state.get("wallet_balance") or 0.0
        longs = []

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
        if not longs:
            return

        longs.sort(key=lambda c: (-c["pnl"], -c["market_value"]))

        def _should_recycle(c):
            if c["is_expired"]:
                return True
            if c["is_profitable"] and c["is_mature"]:
                return True
            if cash < RECYCLE_MIN_CASH_RESERVE and c["is_profitable"]:
                return True
            return False

        longs_to_sell = [c for c in longs if _should_recycle(c)]
        if not longs_to_sell:
            return

        if cash < RECYCLE_MIN_CASH_RESERVE:
            self._log("INFO", f"RECYCLER: Cash low (${cash:.2f} < ${RECYCLE_MIN_CASH_RESERVE}). Selling longs first to free capital.")

        self._log("INFO", f"RECYCLER: {len(longs_to_sell)} long positions queued for recycle")

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
                    signature_type=adapter.signature_type
                )
                adapter.client.update_balance_allowance(params)
                bal = adapter.client.get_balance_allowance(params)
                actual = int(bal.get("balance", "0")) / 1e6

                if actual < 1:
                    self._log("INFO", f"RECYCLER: ...{token_id[-8:]} has 0 shares on exchange, removing from book")
                    self.position_book.pop(token_id, None)
                    continue

                sell_price = self._compute_exit_price(adapter, token_id, mid, "SELL")
                num_shares = math.floor(actual)
                if actual > 2:
                    num_shares = max(math.floor(actual - 1), 1)
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
                    _ae = self.position_book.get(token_id, {}).get("avg_entry")
                    avg_entry = _ae if _ae is not None else sell_price
                    realized_pnl = (sell_price - avg_entry) * num_shares
                    engine = self.exec_engine
                    if engine is not None:
                        engine.record_trade_result(realized_pnl)
                        self.state["daily_pnl"] = engine.daily_pnl
                        self.state["realized_pnl"] = float(engine.daily_pnl)
                    self.position_book.pop(token_id, None)

            except Exception as e:
                self._log("WARNING", f"RECYCLER: Failed to sell ...{token_id[-8:]}: {e}")

        # Refresh balance after sells so we have cash available for buy-backs
        if longs_to_sell:
            self._refresh_account_metrics_cached(adapter)
            cash = self.state.get("wallet_balance") or 0.0

        self._refresh_account_metrics_cached(adapter)
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
            with self._csv_lock:
                if os.path.exists(OPPORTUNITY_LOG_FILE):
                    if os.path.getsize(OPPORTUNITY_LOG_FILE) > MAX_OPPORTUNITY_LOG_BYTES:
                        os.replace(OPPORTUNITY_LOG_FILE, OPPORTUNITY_LOG_FILE + ".bak")
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
        except Exception: pass
