import logging
import time
import json
import csv
import os
import numpy as np
import sys
from typing import Dict, List, Tuple
from datetime import datetime

# Ensure project root is in path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from poly_arb_bot.config import LOG_LEVEL, EXECUTION_MODE, MIN_PROFIT_THRESHOLD, MAX_POSITION_SIZE
from poly_arb_bot.adapters.polymarket import PolymarketAdapter
from poly_arb_bot.engine.math import MarketMath
from poly_arb_bot.engine.execution import ExecutionEngine
from poly_arb_bot.engine.dependency import DependencyDetector

# Setup logging
logging.basicConfig(level=LOG_LEVEL, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Constants ---
# Fee and slippage estimation
POLYMARKET_FEE_RATE = 0.02       # Polymarket ~2% fee on winnings
SLIPPAGE_BUFFER = 0.01           # 1% slippage buffer
# We need at least 3.5% edge to cover round-trip fees and slippage
MIN_EFFECTIVE_EDGE = 0.035
EFFECTIVE_MIN_PROFIT = max(MIN_PROFIT_THRESHOLD, MIN_EFFECTIVE_EDGE)
TRADE_COOLDOWN_SECONDS = 60      # Minimum seconds between trades on the same pair
OPPORTUNITY_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "opportunities.csv")
MAX_PAIRS_TO_ANALYZE = 10        # Analyze up to 10 candidate pairs
MAX_MARKETS_TO_FETCH = 1000      # Fetch more markets for wider search


def convert_outcomes_to_vectors(outcome_tuples: List[Tuple[str, str]]) -> np.array:
    """
    Convert logical outcomes [("YES", "NO"), ...] into one-hot vectors.
    Mapped to: [A_YES, A_NO, B_YES, B_NO]
    """
    vectors = []
    for pair in outcome_tuples:
        vec = []
        # Market A
        if pair[0].upper() == "YES":
            vec.extend([1, 0])
        else:
            vec.extend([0, 1])
            
        # Market B
        if pair[1].upper() == "YES":
            vec.extend([1, 0])
        else:
            vec.extend([0, 1])
            
        vectors.append(vec)
        
    return np.array(vectors)


def log_opportunity(profit: float, prices: np.ndarray, mu_star: np.ndarray, markets: List[Dict]):
    """Log detected opportunity to CSV for analysis."""
    try:
        file_exists = os.path.exists(OPPORTUNITY_LOG_FILE)
        with open(OPPORTUNITY_LOG_FILE, "a", newline="") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["timestamp", "profit", "prices", "mu_star", "market_a", "market_b"])
            writer.writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                f"{profit:.5f}",
                np.array2string(prices, precision=4, separator=', '),
                np.array2string(mu_star, precision=4, separator=', '),
                markets[0].get("question", "?")[:80] if len(markets) > 0 else "",
                markets[1].get("question", "?")[:80] if len(markets) > 1 else "",
            ])
    except Exception as e:
        logger.warning(f"Failed to log opportunity: {e}")


class MonitoringSession:
    """
    Manages the state of a live monitoring session for a specific pair/group of markets.
    """
    def __init__(self, markets: List[Dict], valid_outcomes: np.array):
        self.markets = markets
        self.valid_outcomes = valid_outcomes
        self.token_map = {}        # token_id -> price_vector_index
        self.prices = np.zeros(len(markets) * 2)  # [A_YES, A_NO, B_YES, B_NO]
        self.token_lookup = {}     # index -> token_id (Reverse map)
        self.prices_initialized = set()  # Track which indices got real WS data
        self.last_trade_time = 0   # Timestamp of last trade execution
        
        # Book data for proper execution pricing
        self.best_bids = {}   # token_id -> best bid price
        self.best_asks = {}   # token_id -> best ask price
        
        for i, m in enumerate(markets):
            # Parse Tokens
            tokens = m.get("clobTokenIds", [])
            outcomes = m.get("outcomes", ["No", "Yes"]) 
            
            if isinstance(outcomes, str):
                try: outcomes = json.loads(outcomes)
                except (json.JSONDecodeError, ValueError): outcomes = ["No", "Yes"]
            
            if len(tokens) < 2: continue

            yes_idx = -1
            no_idx = -1
            for idx, label in enumerate(outcomes):
                if "Yes" in str(label) or "YES" in str(label):
                    yes_idx = idx
                elif "No" in str(label) or "NO" in str(label):
                    no_idx = idx
            
            if yes_idx == -1: yes_idx = 1
            if no_idx == -1: no_idx = 0
            
            # Map Indices
            idx_yes = i * 2 + 0
            idx_no = i * 2 + 1
            
            self.token_map[tokens[yes_idx]] = idx_yes
            self.token_map[tokens[no_idx]] = idx_no
            
            # Save reverse map for execution
            self.token_lookup[idx_yes] = tokens[yes_idx]
            self.token_lookup[idx_no] = tokens[no_idx]
            
            # Initialize Prices from market data (REST snapshot)
            try:
                op = m.get("outcomePrices", ["0.5", "0.5"])
                if isinstance(op, str): op = json.loads(op)
                p_yes = float(op[yes_idx]) if len(op) > yes_idx else 0.5
                p_no = float(op[no_idx]) if len(op) > no_idx else 0.5
                self.prices[idx_yes] = p_yes
                self.prices[idx_no] = p_no
            except Exception:
                self.prices[idx_yes] = 0.5
                self.prices[idx_no] = 0.5
                
        logger.info(f"Initialized Price Map for {len(self.token_map)} tokens.")
        logger.info(f"Initial prices: {self.prices}")

    def update_price(self, token_id: str, new_price: float, best_bid: float = None, best_ask: float = None):
        if token_id in self.token_map:
            idx = self.token_map[token_id]
            self.prices[idx] = new_price
            self.prices_initialized.add(idx)
            
            # Store book data for execution
            if best_bid is not None:
                self.best_bids[token_id] = best_bid
            if best_ask is not None:
                self.best_asks[token_id] = best_ask
            return True
        return False

    def has_valid_prices(self) -> bool:
        """Check if all prices are non-zero (either from REST init or WS)."""
        return np.all(self.prices > 0.001)

    def can_trade(self) -> bool:
        """Check cooldown to prevent duplicate trades."""
        return (time.time() - self.last_trade_time) > TRADE_COOLDOWN_SECONDS

    def mark_traded(self):
        self.last_trade_time = time.time()

    def run_analysis(self):
        # Need all prices to be valid (nonzero)
        if not self.has_valid_prices():
            return 0.0, None
        
        mu_star = MarketMath.frank_wolfe_projection(self.prices, self.valid_outcomes)
        profit = MarketMath.calculate_profit(self.prices, mu_star)
        return profit, mu_star


def find_related_pairs(markets: List[Dict], dep_detector: DependencyDetector) -> List[Tuple[List[Dict], np.array]]:
    """
    Scan markets to find related pairs DIVERSIFIED across different topics.
    Returns a list of (market_pair, valid_outcome_matrix) tuples.
    """
    from collections import defaultdict
    
    logger.info(f"SEARCHING for related markets among {len(markets)} candidates...")
    
    stop_words = {"will", "the", "be", "in", "price", "of", "to", "above", "below", 
                 "a", "by", "on", "at", "for", "is", "it", "or", "and", "this", "that",
                 "with", "from", "an", "are", "was", "were", "has", "have", "do", "does",
                 "before", "after", "than", "more", "less", "?", "how", "many",
                 "much", "what", "which", "when", "where", "who", "its", "their"}

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
            overlap = (set(q1.split()) & set(q2.split())) - stop_words
            
            if len(overlap) >= 2:
                topic_key = tuple(sorted(overlap))
                all_candidates.append((m1, m2, len(overlap), topic_key))

    logger.info(f"Found {len(all_candidates)} total candidate pairs.")

    # Step 2: Group by topic and pick best from DIFFERENT topics
    topic_groups = defaultdict(list)
    for m1, m2, score, topic in all_candidates:
        short_topic = tuple(sorted(topic)[:3])
        topic_groups[short_topic].append((m1, m2, score, topic))

    MAX_PER_TOPIC = 2
    diversified = []
    for topic, pairs in sorted(topic_groups.items(), key=lambda x: -max(p[2] for p in x[1])):
        pairs.sort(key=lambda x: x[2], reverse=True)
        for p in pairs[:MAX_PER_TOPIC]:
            diversified.append(p)
        if len(diversified) >= MAX_PAIRS_TO_ANALYZE * 2:
            break

    diversified = diversified[:MAX_PAIRS_TO_ANALYZE]
    
    topics = set(tuple(sorted(t)[:3]) for _,_,_,t in diversified)
    logger.info(f"Selected {len(diversified)} pairs across {len(topics)} different topics.")

    # Step 3: LLM Analysis
    found_pairs = []
    for m1, m2, score, topic in diversified:
        logger.info(f"Analyzing pair (overlap={score}): '{m1['question'][:60]}' vs '{m2['question'][:60]}'")
        valid_outcomes_tuples = dep_detector.analyze_market_pair(m1, m2)
        
        if valid_outcomes_tuples and len(valid_outcomes_tuples) < 4:
            logger.info(f"DEPENDENCY FOUND! ({len(valid_outcomes_tuples)} valid combos)")
            matrix = convert_outcomes_to_vectors(valid_outcomes_tuples)
            found_pairs.append(([m1, m2], matrix))

    if not found_pairs:
        logger.warning("No dependent pairs found after analyzing all candidates.")

    return found_pairs


def main():
    logger.info(f"Starting Arbitrage Hunter in {EXECUTION_MODE} mode")
    logger.info(f"Profit threshold: ${MIN_PROFIT_THRESHOLD:.2f} (effective with fees: ${EFFECTIVE_MIN_PROFIT:.2f})")
    logger.info(f"Max position size: ${MAX_POSITION_SIZE:.2f}")
    logger.info(f"Trade cooldown: {TRADE_COOLDOWN_SECONDS}s")
    
    adapter = PolymarketAdapter()
    exec_engine = ExecutionEngine(adapter)
    dep_detector = DependencyDetector()
    
    # Connect WebSocket
    adapter.connect_ws()
    time.sleep(2)
    
    # Fetch more markets for wider search
    markets = adapter.get_markets(limit=MAX_MARKETS_TO_FETCH) 
    if not markets:
        logger.error("No markets fetched. Check network / API.")
        return

    # Check Balance if LIVE
    if EXECUTION_MODE == "LIVE":
        logger.info("Checking MetaMask Wallet Balance...")
        perms = adapter.get_balance_allowance()
        cash = float(perms.get("balance", "0")) / 1e6
        logger.info(f"MetaMask Cash balance: ${cash:.2f}")
        if cash < MAX_POSITION_SIZE:
            logger.warning(f"Balance ${cash:.2f} is less than max position size ${MAX_POSITION_SIZE:.2f}!")

    # Find ALL related pairs (not just one)
    all_pairs = find_related_pairs(markets, dep_detector)
    if not all_pairs:
        logger.error("No valid market pairs found. Exiting.")
        return
    
    logger.info(f"Monitoring {len(all_pairs)} dependent market pairs.")
    
    # Create monitoring sessions for all pairs
    sessions = []
    all_token_ids = []
    for pair_markets, valid_outcomes in all_pairs:
        session = MonitoringSession(pair_markets, valid_outcomes)
        sessions.append(session)
        all_token_ids.extend(list(session.token_map.keys()))
    
    if not all_token_ids:
        logger.error("No tokens to subscribe to.")
        return

    # Subscribe to all tokens
    logger.info(f"Subscribing to {len(all_token_ids)} tokens across {len(sessions)} pairs...")
    adapter.subscribe(all_token_ids)
    
    # --- Initial REST book fetch to get real bid/ask prices ---
    logger.info("Fetching initial order books from REST API...")
    for session in sessions:
        for token_id, idx in session.token_map.items():
            book_data = adapter.get_midmarket_price(token_id)
            if book_data["mid"] > 0:
                session.update_price(token_id, book_data["mid"], book_data["bid"], book_data["ask"])
        
        # Run initial analysis with REST prices
        profit, mu_star = session.run_analysis()
        if profit and profit > 0.001:
            m_names = [m.get("question", "?")[:50] for m in session.markets]
            logger.info(f"Initial analysis: profit={profit:.5f} | {m_names}")
            if profit > MIN_PROFIT_THRESHOLD * 0.5:
                log_opportunity(profit, session.prices, mu_star, session.markets)
    
    logger.info("Initial REST book fetch complete. Now monitoring via WebSocket + periodic REST poll.")
    
    # Live Loop - Price update handler
    def on_price_update(data):
        try:
            # Validate incoming data
            if not isinstance(data, dict):
                return
            
            token_id = data.get("asset_id")
            if not token_id:
                return
            
            bids = data.get("bids", [])
            asks = data.get("asks", [])
            if not bids and not asks:
                return
            
            # Parse book data - CLOB returns worst-to-best ordering
            # Best bid = highest price, Best ask = lowest price (filter out 0.999 placeholder asks)
            best_bid = max((float(b['price']) for b in bids), default=0.0) if bids else 0.0
            best_ask = min((float(a['price']) for a in asks if float(a['price']) < 0.999), default=0.0) if asks else 0.0
            
            # Use midpoint for analysis but store bid/ask for execution
            if best_bid > 0 and best_ask > 0:
                mid_price = (best_bid + best_ask) / 2
            elif best_bid > 0:
                mid_price = best_bid
            elif best_ask > 0:
                mid_price = best_ask
            else:
                return
            
            # Update all sessions that track this token
            for session in sessions:
                updated = session.update_price(token_id, mid_price, best_bid, best_ask)
                
                if not updated:
                    continue
                    
                # Run arbitrage analysis
                profit, mu_star = session.run_analysis()
                
                if profit is None or profit <= 0.0001:
                    continue
                
                logger.info(f"Opportunity detected: Profit={profit:.5f} | Prices={session.prices}")
                
                # Log ALL opportunities for analysis
                if profit > MIN_PROFIT_THRESHOLD * 0.5:
                    log_opportunity(profit, session.prices, mu_star, session.markets)
                
                # Only trade if profit exceeds threshold WITH fees
                if profit <= EFFECTIVE_MIN_PROFIT:
                    continue
                
                # Check cooldown
                if not session.can_trade():
                    logger.info(f"Trade cooldown active. Skipping. (wait {TRADE_COOLDOWN_SECONDS}s)")
                    continue
                
                logger.info(f"TRADE SIGNAL: Profit ${profit:.4f} > threshold ${EFFECTIVE_MIN_PROFIT:.4f}")
                
                # Construct orders - BUY underpriced AND SELL overpriced
                orders = []
                for i, current_price in enumerate(session.prices):
                    fair_value = mu_star[i]
                    tid = session.token_lookup.get(i)
                    if not tid:
                        continue
                    
                    # BUY underpriced tokens (fair value significantly above market)
                    if fair_value > current_price * 1.03 and current_price > 0.02:
                        # Use ASK price for buying (taking liquidity)
                        exec_price = session.best_asks.get(tid, current_price)
                        if exec_price <= 0:
                            exec_price = current_price
                        
                        # Cap position size per leg
                        leg_size = min(MAX_POSITION_SIZE / max(len(session.markets), 1), MAX_POSITION_SIZE)
                        
                        orders.append({
                            "token_id": tid,
                            "side": "BUY",
                            "price": round(exec_price, 4),
                            "size": leg_size
                        })
                    
                    # SELL overpriced tokens (fair value significantly below market)
                    elif fair_value < current_price * 0.97 and current_price > 0.02:
                        # Use BID price for selling (taking liquidity)
                        exec_price = session.best_bids.get(tid, current_price)
                        if exec_price <= 0:
                            exec_price = current_price
                        
                        leg_size = min(MAX_POSITION_SIZE / max(len(session.markets), 1), MAX_POSITION_SIZE)
                        
                        orders.append({
                            "token_id": tid,
                            "side": "SELL",
                            "price": round(exec_price, 4),
                            "size": leg_size
                        })
                
                if orders:
                    logger.info(f"Generated {len(orders)} orders (BUY + SELL legs):")
                    for o in orders:
                        logger.info(f"  -> {o['side']} ${o['size']:.2f} of ...{o['token_id'][-8:]} @ {o['price']}")
                    
                    results = exec_engine.execute_arbitrage(orders)
                    
                    # --- FIX: Record results for circuit breaker ---
                    successful_value = 0.0
                    for r in results:
                        if r.get("ok"):
                            # Estimate profit/loss for this leg. For simplicity, we track volume-weighted PnL
                            # In a real arb, we'd wait for settlement, but for the circuit breaker 
                            # we should at least track that trades happened.
                            successful_value += r['order']['size']
                    
                    # We record a small "cost" for each trade to represent fees/risk until settled
                    # This ensures the daily loss limit can actually trigger.
                    if successful_value > 0:
                        exec_engine.record_trade_result(-successful_value * 0.02) # assume 2% cost/risk out the gate
                    
                    session.mark_traded()

        except Exception as e:
            logger.error(f"Error in price update handler: {e}", exc_info=True)

    adapter.add_callback(on_price_update)
    logger.info("Monitoring & Execution Active.")
    
    poll_counter = 0
    REST_POLL_INTERVAL = 4  # Poll REST every 4 cycles (every ~2 min at 30s sleep)
    
    try:
        while True:
            time.sleep(30)
            poll_counter += 1
            
            # Check WebSocket health
            if not adapter.is_ws_connected():
                logger.warning("WebSocket disconnected! Reconnecting...")
                adapter.reconnect_ws()
                time.sleep(2)
                if adapter.is_ws_connected():
                    adapter.subscribe(all_token_ids)
                    logger.info("Reconnected and resubscribed.")
                else:
                    logger.error("Reconnection failed. Will retry in 30s.")
            
            # Periodic REST poll to catch price changes on low-volume markets
            if poll_counter % REST_POLL_INTERVAL == 0:
                logger.info("Periodic REST book poll...")
                for session in sessions:
                    for token_id, idx in session.token_map.items():
                        book_data = adapter.get_midmarket_price(token_id)
                        if book_data["mid"] > 0:
                            session.update_price(token_id, book_data["mid"], book_data["bid"], book_data["ask"])
                    
                    # Run analysis on refreshed REST data
                    profit, mu_star = session.run_analysis()
                    if profit and profit > 0.001:
                        logger.info(f"REST poll opportunity: profit={profit:.5f} | prices={session.prices}")
                        
                        if profit > MIN_PROFIT_THRESHOLD * 0.5:
                            log_opportunity(profit, session.prices, mu_star, session.markets)
                        
                        if profit > EFFECTIVE_MIN_PROFIT and session.can_trade():
                            logger.info(f"TRADE SIGNAL (REST): Profit ${profit:.4f} > ${EFFECTIVE_MIN_PROFIT:.4f}")
                            orders = []
                            for i, current_price in enumerate(session.prices):
                                fair_value = mu_star[i]
                                tid = session.token_lookup.get(i)
                                if not tid:
                                    continue
                                if fair_value > current_price * 1.03 and current_price > 0.02:
                                    exec_price = session.best_asks.get(tid, current_price)
                                    if exec_price <= 0: exec_price = current_price
                                    leg_size = min(MAX_POSITION_SIZE / max(len(session.markets), 1), MAX_POSITION_SIZE)
                                    orders.append({"token_id": tid, "side": "BUY", "price": round(exec_price, 4), "size": leg_size})
                                elif fair_value < current_price * 0.97 and current_price > 0.02:
                                    exec_price = session.best_bids.get(tid, current_price)
                                    if exec_price <= 0: exec_price = current_price
                                    leg_size = min(MAX_POSITION_SIZE / max(len(session.markets), 1), MAX_POSITION_SIZE)
                                    orders.append({"token_id": tid, "side": "SELL", "price": round(exec_price, 4), "size": leg_size})
                            
                            if orders:
                                logger.info(f"Generated {len(orders)} REST-triggered orders.")
                                results = exec_engine.execute_arbitrage(orders)
                                
                                # --- FIX: Record results for circuit breaker ---
                                if any(r.get("ok") for r in results):
                                    exec_engine.record_trade_result(-0.10) # Nominal risk record
                                    
                                session.mark_traded()
            
    except KeyboardInterrupt:
        logger.info("Stopped by user.")


if __name__ == "__main__":
    main()
