import requests
import websocket
import json
import threading
import logging
import time
import re
from typing import List, Dict, Any, Optional
from datetime import datetime

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs

BUY = "BUY"
SELL = "SELL"

from poly_arb_bot.config import (
    POLYMARKET_CLOB_API_URL, POLYMARKET_WS_URL,
    POLYMARKET_API_KEY, POLYMARKET_API_SECRET, 
    POLYMARKET_PASSPHRASE, PRIVATE_KEY, PROXY_ADDRESS,
    MAX_DAYS_TO_RESOLUTION
)

logger = logging.getLogger(__name__)


class PolymarketAdapter:
    def __init__(self):
        self.clob_url = POLYMARKET_CLOB_API_URL
        self.ws_url = POLYMARKET_WS_URL
        self.api_key = POLYMARKET_API_KEY
        self.api_secret = POLYMARKET_API_SECRET
        self.passphrase = POLYMARKET_PASSPHRASE
        self.private_key = PRIVATE_KEY
        
        self.ws = None
        self.ws_thread = None
        self.callbacks = [] 
        self._ws_connected = False
        self._ws_lock = threading.Lock()
        self._reconnect_count = 0
        self._max_reconnect_delay = 60  # Max seconds between reconnect attempts
        
        # Initialize ClobClient for Order execution
        self.client = None
        if self.private_key and self.api_key:
            try:
                creds = ApiCreds(
                    api_key=self.api_key, 
                    api_secret=self.api_secret, 
                    api_passphrase=self.passphrase
                )
                self.client = ClobClient(
                    host=self.clob_url, 
                    key=self.private_key, 
                    chain_id=137, 
                    creds=creds
                )
                logger.info("ClobClient initialized for trading (EOA Mode).")
            except Exception as e:
                logger.error(f"Failed to init ClobClient: {e}")

    # --- MARKET DATA ---

    def get_markets(self, limit: int = 200) -> List[Dict[str, Any]]:
        """Fetch active markets via Gamma API with robust filtering."""
        gamma_url = "https://gamma-api.polymarket.com/markets"
        params = {"limit": limit, "active": "true", "closed": "false"}
        try:
            response = requests.get(gamma_url, params=params, timeout=15)
            response.raise_for_status()
            raw_markets = response.json()
            
            cleaned_markets = []
            current_year = datetime.now().year
            now_utc = datetime.utcnow()
            
            for m in raw_markets:
                # Ensure market has CLOB tokens
                t_ids = m.get("clobTokenIds")
                if isinstance(t_ids, str):
                    try: t_ids = json.loads(t_ids)
                    except: continue
                
                if not t_ids or not isinstance(t_ids, list) or len(t_ids) < 2:
                    continue
                m["clobTokenIds"] = t_ids
                
                # Parse outcomes properly
                outcomes = m.get("outcomes")
                if isinstance(outcomes, str):
                    try: outcomes = json.loads(outcomes)
                    except: outcomes = ["No", "Yes"]
                    m["outcomes"] = outcomes

                # Parse outcomePrices properly
                op = m.get("outcomePrices")
                if isinstance(op, str):
                    try: op = json.loads(op)
                    except: op = None
                    m["outcomePrices"] = op

                # Date filter: only markets from recent years (dynamic, not hardcoded)
                created_at = m.get("createdAt", "")
                if created_at:
                    try:
                        created_year = int(created_at[:4])
                        if created_year < current_year - 1:  # Allow current year and last year
                            continue
                    except (ValueError, IndexError):
                        pass  # If we can't parse the date, keep the market

                # Resolution horizon filter:
                # keep only markets expected to resolve within MAX_DAYS_TO_RESOLUTION days.
                # This avoids stale/very long-dated markets and improves capital turnover.
                end_raw = (
                    m.get("endDate")
                    or m.get("end_date_iso")
                    or m.get("endDateIso")
                    or m.get("end_date")
                    or ""
                )
                if end_raw:
                    try:
                        end_dt = datetime.fromisoformat(str(end_raw).replace("Z", "+00:00")).replace(tzinfo=None)
                        days_to_end = (end_dt - now_utc).days
                        # Skip already-ended markets and too-far markets.
                        if days_to_end < 0:
                            continue
                        if days_to_end > MAX_DAYS_TO_RESOLUTION:
                            continue
                    except Exception:
                        # If end date is malformed, skip to stay conservative.
                        continue
                
                # Must have valid question
                if not m.get("question"):
                    continue
                question = str(m.get("question", ""))
                # Exclude markets explicitly tied to past calendar years in the title/question.
                years_in_question = [int(y) for y in re.findall(r"\b(20\d{2})\b", question)]
                if years_in_question and max(years_in_question) < current_year:
                    continue

                # Must have some price activity or liquidity
                best_bid = float(m.get("bestBid", 0) or 0)
                best_ask = float(m.get("bestAsk", 0) or 0)
                if best_bid == 0 and best_ask == 0:
                    continue
                
                cleaned_markets.append(m)
            
            logger.info(
                f"Fetched {len(cleaned_markets)} genuine active markets "
                f"(from {len(raw_markets)} raw, horizon <= {MAX_DAYS_TO_RESOLUTION}d)."
            )
            return cleaned_markets
        except requests.exceptions.Timeout:
            logger.error("Timeout fetching markets from Gamma API")
            return []
        except Exception as e:
            logger.error(f"Error fetching markets: {e}")
            return []

    # --- WEBSOCKET ---

    def connect_ws(self):
        """Connect to WebSocket with error handling."""
        with self._ws_lock:
            if self.ws:
                try:
                    self.ws.close()
                except: pass
            
            self.ws = websocket.WebSocketApp(
                self.ws_url,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
                on_open=self._on_open
            )
            self.ws_thread = threading.Thread(target=self._run_ws, daemon=True)
            self.ws_thread.start()

    def _run_ws(self):
        """Run WebSocket with ping/pong keepalive."""
        try:
            self.ws.run_forever(ping_interval=30, ping_timeout=10)
        except Exception as e:
            logger.error(f"WebSocket run_forever error: {e}")
        finally:
            self._ws_connected = False

    def is_ws_connected(self) -> bool:
        """Check if WebSocket is alive."""
        return (
            self._ws_connected 
            and self.ws is not None 
            and self.ws.sock is not None 
            and self.ws.sock.connected
        )

    def reconnect_ws(self):
        """Reconnect with exponential backoff."""
        self._reconnect_count += 1
        delay = min(2 ** self._reconnect_count, self._max_reconnect_delay)
        logger.info(f"Reconnecting WebSocket (attempt #{self._reconnect_count}, delay={delay}s)...")
        time.sleep(delay)
        self.connect_ws()

    def subscribe(self, asset_ids: List[str]):
        """Subscribe to market book updates for given assets."""
        if not self.is_ws_connected():
            logger.warning("Cannot subscribe: WebSocket not connected.")
            return
        
        # Polymarket WS expects batched subscriptions
        # Send in chunks to avoid message size limits
        chunk_size = 50
        for i in range(0, len(asset_ids), chunk_size):
            chunk = asset_ids[i:i + chunk_size]
            msg = {
                "assets_ids": chunk,
                "type": "market"
            }
            try:
                self.ws.send(json.dumps(msg))
                logger.info(f"Subscribed to {len(chunk)} assets (batch {i // chunk_size + 1})")
            except Exception as e:
                logger.error(f"Subscribe error: {e}")

    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
            # Handle both list and dict response formats
            messages = data if isinstance(data, list) else [data]
            
            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                    
                # Only forward book events with actual data
                event_type = msg.get("event_type")
                if event_type == "book":
                    for callback in self.callbacks:
                        try:
                            callback(msg)
                        except Exception as e:
                            logger.error(f"Callback error: {e}", exc_info=True)
                            
        except json.JSONDecodeError:
            pass  # Ignore non-JSON messages (pong, etc.)
        except Exception as e:
            logger.error(f"WS message handling error: {e}")

    def _on_error(self, ws, error):
        logger.error(f"WebSocket error: {error}")
        self._ws_connected = False

    def _on_close(self, ws, close_status_code, close_msg):
        logger.warning(f"WebSocket closed (code={close_status_code}, msg={close_msg})")
        self._ws_connected = False

    def _on_open(self, ws):
        logger.info("WebSocket connection opened")
        self._ws_connected = True
        self._reconnect_count = 0  # Reset backoff on successful connect
        
    def add_callback(self, callback):
        self.callbacks.append(callback)

    # --- REST BOOK DATA ---

    def get_order_book(self, token_id: str) -> Dict[str, Any]:
        """Fetch the current order book for a token via REST."""
        try:
            url = f"{self.clob_url}/book"
            resp = requests.get(url, params={"token_id": token_id}, timeout=10)
            if resp.status_code == 200:
                return resp.json()
            else:
                return {}
        except Exception as e:
            logger.error(f"Error fetching book for {token_id[-8:]}: {e}")
            return {}

    def get_midmarket_price(self, token_id: str) -> Dict[str, float]:
        """Get best bid, best ask, and midpoint for a token from REST."""
        book = self.get_order_book(token_id)
        bids = book.get("bids", [])
        asks = book.get("asks", [])
        
        # CLOB returns bids worst-to-best and asks worst-to-best
        # Best bid = highest price (last in list), Best ask = lowest price (last in list)
        best_bid = max((float(b["price"]) for b in bids), default=0.0) if bids else 0.0
        best_ask = min((float(a["price"]) for a in asks if float(a["price"]) < 0.999), default=0.0) if asks else 0.0
        
        if best_bid > 0 and best_ask > 0:
            mid = (best_bid + best_ask) / 2
        elif best_bid > 0:
            mid = best_bid
        elif best_ask > 0:
            mid = best_ask
        else:
            mid = 0.0
        
        return {"bid": best_bid, "ask": best_ask, "mid": mid}

    # --- BALANCE & PERMISSIONS ---

    def get_balance_allowance(self) -> Dict[str, Any]:
        """Check balance and allowance via CLOB API."""
        if not self.client:
            logger.warning("Cannot check balance: ClobClient not initialized.")
            return {}
        try:
            from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
            params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=0)
            return self.client.get_balance_allowance(params)
        except Exception as e:
            logger.error(f"Error checking balance: {e}")
            return {}

    def update_permissions(self):
        """Enable trading by granting allowance."""
        if not self.client: return None
        try:
            from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
            logger.info("Enabling trading permissions (EOA Mode)...")
            params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=0)
            resp = self.client.update_balance_allowance(params)
            logger.info(f"Permission Update Sent: {resp}")
            return resp
        except Exception as e:
            logger.error(f"Failed to update permissions: {e}")
            return None

    # --- EXECUTION METHODS ---

    def place_limit_order(self, token_id: str, side: str, price: float, size: float):
        """
        Place a Limit Order.
        Args:
            token_id: The CLOB token ID.
            side: 'BUY' or 'SELL'.
            price: Limit price per share (0 to 1).
            size: Dollar amount to spend (USDC).
        Returns:
            Order response dict or None on failure.
        """
        if not self.client:
            logger.error("Cannot place order: ClobClient not initialized (missing private key or API key).")
            return None
            
        order_side = BUY if side.upper() == 'BUY' else SELL
        
        try:
            # Validate price
            if price <= 0 or price >= 1:
                logger.error(f"Invalid price {price}. Must be between 0 and 1.")
                return None
            
            # Convert dollar size to shares
            # size is in USDC, shares = usdc_amount / price_per_share
            size_shares = round(size / price, 2)
            
            if size_shares < 1:
                logger.warning(f"Order too small: {size_shares} shares. Skipping.")
                return None
            
            # Round price to Polymarket tick size (0.01)
            price = round(price, 2)
            
            order_args = OrderArgs(
                price=price,
                size=size_shares,
                side=order_side,
                token_id=token_id
            )
            
            logger.info(f"Placing Order: {side} {size_shares:.2f} shares of ...{token_id[-8:]} @ ${price}")
            resp = self.client.create_and_post_order(order_args)
            logger.info(f"Order Response: {resp}")
            return resp
            
        except Exception as e:
            logger.error(f"Order Execution Failed: {e}", exc_info=True)
            return None
