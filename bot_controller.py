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
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from collections import deque

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
TRADE_COOLDOWN_SECONDS = 60
MAX_PAIRS_TO_ANALYZE = 15
MAX_MARKETS_TO_FETCH = 1000
ENTRY_BAND = 0.01
MAX_SPREAD_PCT = 0.35
MIN_EXEC_PRICE = 0.01
MAX_EXEC_PRICE = 0.99

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
OPPORTUNITY_LOG_FILE = os.path.join(PROJECT_DIR, "opportunities.csv")


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
            "wallet_balance": None,
            "position_value_estimate": 0.0,
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

    def _log(self, level: str, message: str):
        """Add log entry to recent logs and standard logger."""
        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "level": level,
            "msg": message
        }
        self.recent_logs.append(entry)
        getattr(logger, level.lower(), logger.info)(message)

    def start(self):
        with self._lock:
            if self.state["status"] == "running":
                return {"ok": False, "msg": "Bot is already running"}
            
            self._stop_event.clear()
            self.state["status"] = "starting"
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            return {"ok": True, "msg": "Bot starting..."}

    def stop(self):
        with self._lock:
            if self.state["status"] == "stopped":
                return {"ok": False, "msg": "Bot is already stopped"}
            
            self._stop_event.set()
            self.state["status"] = "stopped"
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
                perms = adapter.get_balance_allowance()
                cash = float(perms.get("balance", "0")) / 1e6
                self.state["wallet_balance"] = cash
                self._log("INFO", f"Wallet balance: ${cash:.2f}")

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
                            self._execute_orders(exec_engine, orders, session)
                except Exception as e:
                    self._log("ERROR", f"WS handler error: {e}")

            adapter.add_callback(on_price_update)

            # Main loop
            poll_counter = 0
            REST_POLL_INTERVAL = 4

            while not self._stop_event.is_set():
                time.sleep(30)
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
                                    self._execute_orders(exec_engine, orders, session)
                    
                    self.sessions_info = [s.to_dict() for s in sessions]
                    # Update balance periodically
                    if self.state["mode"] == "LIVE":
                        try:
                            perms = adapter.get_balance_allowance()
                            self.state["wallet_balance"] = float(perms.get("balance", "0")) / 1e6
                            self._recompute_equity()
                        except: pass

            self._log("INFO", "Bot stopped cleanly.")
            self.state["status"] = "stopped"

        except Exception as e:
            self._log("ERROR", f"Bot crashed: {e}")
            self.state["status"] = "error"
            self.state["last_error"] = str(e)

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
                orders.append({"token_id": tid, "side": "BUY", "price": round(ep, 4), "size": leg})
            elif fair < price * (1 - ENTRY_BAND) and price >= MIN_EXEC_PRICE:
                ep = session.best_bids.get(tid, price)
                if ep <= 0: ep = price
                if ep < MIN_EXEC_PRICE or ep > MAX_EXEC_PRICE:
                    continue
                orders.append({"token_id": tid, "side": "SELL", "price": round(ep, 4), "size": leg})
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

        # Tight books with non-extreme pricing can execute with smaller theoretical edges.
        if avg_spread <= 0.04 and 0.05 <= avg_mid <= 0.95:
            return min(configured, 0.0015)
        if avg_spread <= 0.08 and 0.03 <= avg_mid <= 0.97:
            return min(configured, 0.0030)
        if avg_spread <= 0.14 and 0.02 <= avg_mid <= 0.98:
            return min(configured, 0.0060)
        return configured

    def _execute_orders(self, exec_engine, orders, session):
        self.state["trades_executed"] += 1
        for o in orders:
            self.recent_trades.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "side": o["side"],
                "price": o["price"],
                "size": o["size"],
                "token": f"...{o['token_id'][-8:]}",
            })
        
        # Override execution mode from dashboard state
        original_mode = EXECUTION_MODE
        import poly_arb_bot.config as cfg
        cfg.EXECUTION_MODE = self.state["mode"]
        
        exec_engine.execute_arbitrage(orders)
        if self.state.get("mode") == "LIVE":
            for o in orders:
                self._apply_filled_order(o)
        session.mark_traded()
        
        cfg.EXECUTION_MODE = original_mode
        self.state["daily_pnl"] = exec_engine.daily_pnl
        self._recompute_equity()

    def _apply_filled_order(self, order: Dict[str, float]):
        """Update internal position book assuming order was filled."""
        token_id = order["token_id"]
        price = float(order["price"])
        size = float(order["size"])
        if price <= 0:
            return
        shares = size / price
        side = order["side"].upper()
        signed = shares if side == "BUY" else -shares
        if token_id not in self.position_book:
            self.position_book[token_id] = {"shares": 0.0, "last_mid": price}
        self.position_book[token_id]["shares"] += signed
        # prune dust
        if abs(self.position_book[token_id]["shares"]) < 1e-8:
            del self.position_book[token_id]

    def _update_mark_price(self, token_id: str, mid: float):
        if token_id in self.position_book and mid > 0:
            self.position_book[token_id]["last_mid"] = mid

    def _recompute_equity(self):
        pos_val = 0.0
        open_count = 0
        for token_id, p in self.position_book.items():
            shares = float(p.get("shares", 0.0))
            mid = float(p.get("last_mid", 0.0))
            if abs(shares) < 1e-8:
                continue
            open_count += 1
            pos_val += shares * mid
        self.state["position_value_estimate"] = pos_val
        self.state["open_positions_count"] = open_count
        cash = self.state.get("wallet_balance")
        self.state["net_equity_estimate"] = (cash + pos_val) if cash is not None else None

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
