import requests
import websocket
import json
import threading
import logging
import time
import re
import os
from typing import List, Dict, Any
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
        self.proxy_address = PROXY_ADDRESS
        proxy_flag = str(os.getenv("USE_PROXY_MODE", "0")).strip().lower()
        self.use_proxy_mode = bool(self.proxy_address and proxy_flag in ("1", "true", "yes", "on"))
        self.signature_type = 2 if self.use_proxy_mode else 0
        
        # Configure WARP proxy for geo-restriction bypass
        self.warp_proxy = os.getenv("WARP_PROXY", "")
        if self.warp_proxy:
            # Monkey-patch the request function to use a proxied client
            try:
                import httpx
                from httpx_socks import SyncProxyTransport
                from py_clob_client.http_helpers import helpers as clob_helpers
                
                # Create proxied client
                _proxied_client = httpx.Client(
                    http2=True,
                    transport=SyncProxyTransport.from_url(self.warp_proxy)
                )
                
                # Save original request function
                _original_request = clob_helpers.request
                
                # Create wrapper that uses proxied client
                def proxied_request(endpoint, method, headers=None, data=None):
                    try:
                        headers = clob_helpers.overloadHeaders(method, headers)
                        if isinstance(data, str):
                            resp = _proxied_client.request(
                                method=method,
                                url=endpoint,
                                headers=headers,
                                content=data.encode("utf-8"),
                            )
                        else:
                            resp = _proxied_client.request(
                                method=method,
                                url=endpoint,
                                headers=headers,
                                json=data,
                            )
                        
                        if resp.status_code != 200:
                            from py_clob_client.exceptions import PolyApiException
                            raise PolyApiException(resp)
                        
                        try:
                            return resp.json()
                        except ValueError:
                            return resp.text
                    except httpx.RequestError:
                        from py_clob_client.exceptions import PolyApiException
                        raise PolyApiException(error_msg="Request exception!")
                
                # Replace HTTP functions in helpers module
                clob_helpers.request = proxied_request
                _proxied_post = lambda endpoint, headers=None, data=None: proxied_request(endpoint, "POST", headers, data)
                _proxied_get = lambda endpoint, headers=None, data=None: proxied_request(endpoint, "GET", headers, data)
                _proxied_delete = lambda endpoint, headers=None, data=None: proxied_request(endpoint, "DELETE", headers, data)
                _proxied_put = lambda endpoint, headers=None, data=None: proxied_request(endpoint, "PUT", headers, data)
                clob_helpers.post = _proxied_post
                clob_helpers.get = _proxied_get
                clob_helpers.delete = _proxied_delete
                clob_helpers.put = _proxied_put
                
                # CRITICAL: client.py imported post/get/delete directly,
                # so we must also patch them in the client module's namespace
                from py_clob_client import client as clob_client_module
                clob_client_module.post = _proxied_post
                clob_client_module.get = _proxied_get
                clob_client_module.delete = _proxied_delete
                logger.info(f"✓ Patched py_clob_client HTTP functions (helpers + client) with SOCKS proxy: {self.warp_proxy}")
            except Exception as e:
                logger.error(f"✗ Failed to patch py_clob_client: {e}")
                raise
        
        self.ws = None
        self.ws_thread = None
        self.callbacks = [] 
        self._ws_connected = False
        self._ws_lock = threading.Lock()
        self._reconnect_count = 0
        self._max_reconnect_delay = 60  # Max seconds between reconnect attempts
        
        # Initialize ClobClient for Order execution (httpx already patched globally above)
        self.client = None
        if self.private_key and self.api_key:
            try:
                creds = ApiCreds(
                    api_key=self.api_key, 
                    api_secret=self.api_secret, 
                    api_passphrase=self.passphrase
                )
                client_kwargs = {
                    "host": self.clob_url,
                    "key": self.private_key,
                    "chain_id": 137,
                    "creds": creds,
                }
                if self.use_proxy_mode:
                    client_kwargs["funder"] = self.proxy_address
                    client_kwargs["signature_type"] = 2
                self.client = ClobClient(**client_kwargs)
                mode = "Proxy Mode (signature_type=2)" if self.signature_type == 2 else "EOA Mode (signature_type=0)"
                proxy_status = f" via {self.warp_proxy}" if self.warp_proxy else ""
                logger.info(f"ClobClient initialized for trading ({mode}){proxy_status}.")
            except Exception as e:
                logger.error(f"Failed to init ClobClient: {e}")

    # --- LIVE PORTFOLIO (Data API) ---

    def get_portfolio_positions(self) -> List[Dict[str, Any]]:
        """Fetch actual positions from Polymarket Data API (the same data shown on polymarket.com)."""
        address = self.proxy_address or ""
        if not address:
            logger.warning("No PROXY_ADDRESS configured; cannot fetch portfolio.")
            return []
        url = "https://data-api.polymarket.com/positions"
        try:
            resp = requests.get(url, params={"user": address, "sizeThreshold": "0"}, timeout=15)
            resp.raise_for_status()
            positions = resp.json()
            if not isinstance(positions, list):
                return []
            return positions
        except Exception as e:
            logger.error(f"Error fetching portfolio from data API: {e}")
            return []

    def get_portfolio_summary(self) -> Dict[str, Any]:
        """Build a portfolio summary identical to what polymarket.com shows."""
        positions = self.get_portfolio_positions()
        balance_info = self.get_balance_allowance()
        cash = float(balance_info.get("balance", "0")) / 1e6 if balance_info else 0.0

        total_invested = 0.0
        total_current = 0.0
        total_pnl = 0.0
        total_realized = 0.0
        formatted = []

        for p in positions:
            size = float(p.get("size", 0))
            if size < 0.001:
                continue
            avg_price = float(p.get("avgPrice", 0))
            cur_price = float(p.get("curPrice", 0))
            initial_value = float(p.get("initialValue", 0))
            current_value = float(p.get("currentValue", 0))
            cash_pnl = float(p.get("cashPnl", 0))
            realized_pnl = float(p.get("realizedPnl", 0))
            pct_pnl = float(p.get("percentPnl", 0))

            total_invested += initial_value
            total_current += current_value
            total_pnl += cash_pnl
            total_realized += realized_pnl

            token_id = str(p.get("asset_id") or p.get("asset") or p.get("token_id") or "")
            formatted.append({
                "token_id": token_id,
                "title": p.get("title", "Unknown"),
                "outcome": p.get("outcome", "?"),
                "slug": p.get("slug", ""),
                "icon": p.get("icon", ""),
                "size": round(size, 2),
                "avg_price": round(avg_price, 4),
                "cur_price": round(cur_price, 4),
                "initial_value": round(initial_value, 2),
                "current_value": round(current_value, 2),
                "cash_pnl": round(cash_pnl, 4),
                "realized_pnl": round(realized_pnl, 4),
                "percent_pnl": round(pct_pnl, 2),
                "redeemable": p.get("redeemable", False),
                "end_date": p.get("endDate", ""),
            })

        formatted.sort(key=lambda x: abs(x["current_value"]), reverse=True)

        return {
            "cash_balance": round(cash, 2),
            "total_invested": round(total_invested, 2),
            "total_current_value": round(total_current, 2),
            "total_unrealized_pnl": round(total_pnl, 4),
            "total_realized_pnl": round(total_realized, 4),
            "portfolio_value": round(cash + total_current, 2),
            "num_positions": len(formatted),
            "positions": formatted,
        }

    # --- MARKET DATA ---

    # Minimum 24h volume (USD) to consider a market tradeable.
    MIN_VOLUME_24H = float(os.getenv("MIN_VOLUME_24H", "100"))
    # Maximum bid-ask spread % to consider a market liquid enough.
    MAX_SPREAD_FILTER = float(os.getenv("MAX_SPREAD_FILTER", "0.50"))

    def get_markets(self, limit: int = 200) -> List[Dict[str, Any]]:
        """Fetch active markets via Gamma API with robust filtering.
        
        Improvements (2026-02-18):
        - Volume filter: skip markets with < $100/day volume (illiquid, orders won't fill)
        - Spread filter: skip markets with bid-ask spread > 50% of mid (fee-eaters)
        - Capture volume & spread metadata for downstream opportunity scoring
        """
        gamma_url = "https://gamma-api.polymarket.com/markets"
        params = {"limit": limit, "active": "true", "closed": "false"}
        try:
            response = requests.get(gamma_url, params=params, timeout=15)
            response.raise_for_status()
            raw_markets = response.json()
            
            cleaned_markets = []
            skipped_volume = 0
            skipped_spread = 0
            current_year = datetime.now().year
            now_utc = datetime.utcnow()
            
            for m in raw_markets:
                # Ensure market has CLOB tokens
                t_ids = m.get("clobTokenIds")
                if isinstance(t_ids, str):
                    try: t_ids = json.loads(t_ids)
                    except (json.JSONDecodeError, ValueError): continue

                if not t_ids or not isinstance(t_ids, list) or len(t_ids) < 2:
                    continue
                m["clobTokenIds"] = t_ids

                # Parse outcomes properly
                outcomes = m.get("outcomes")
                if isinstance(outcomes, str):
                    try: outcomes = json.loads(outcomes)
                    except (json.JSONDecodeError, ValueError): outcomes = ["No", "Yes"]
                    m["outcomes"] = outcomes

                # Parse outcomePrices properly
                op = m.get("outcomePrices")
                if isinstance(op, str):
                    try: op = json.loads(op)
                    except (json.JSONDecodeError, ValueError): op = None
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
                end_raw = (
                    m.get("endDate")
                    or m.get("end_date_iso")
                    or m.get("endDateIso")
                    or m.get("end_date")
                    or ""
                )
                days_to_end = None
                if end_raw:
                    try:
                        end_dt = datetime.fromisoformat(str(end_raw).replace("Z", "+00:00")).replace(tzinfo=None)
                        days_to_end = (end_dt - now_utc).days
                        if days_to_end < 0:
                            continue
                        if days_to_end > MAX_DAYS_TO_RESOLUTION:
                            continue
                    except Exception:
                        continue
                
                # Must have valid question
                if not m.get("question"):
                    continue
                question = str(m.get("question", ""))
                # Exclude markets explicitly tied to past calendar years
                years_in_question = [int(y) for y in re.findall(r"\b(20\d{2})\b", question)]
                if years_in_question and max(years_in_question) < current_year:
                    continue

                # Must have some price activity or liquidity
                best_bid = float(m.get("bestBid", 0) or 0)
                best_ask = float(m.get("bestAsk", 0) or 0)
                if best_bid == 0 and best_ask == 0:
                    continue

                # --- NEW: Volume filter ---
                vol_raw = m.get("volume24hr") or m.get("volume") or m.get("volumeNum") or 0
                try:
                    volume_24h = float(vol_raw)
                except (TypeError, ValueError):
                    volume_24h = 0.0
                if volume_24h < self.MIN_VOLUME_24H:
                    skipped_volume += 1
                    continue
                m["_volume_24h"] = volume_24h  # attach for downstream scoring

                # --- NEW: Spread filter ---
                if best_bid > 0 and best_ask > 0 and best_ask > best_bid:
                    mid = (best_bid + best_ask) / 2.0
                    spread_pct = (best_ask - best_bid) / max(mid, 0.001)
                    if spread_pct > self.MAX_SPREAD_FILTER:
                        skipped_spread += 1
                        continue
                    m["_spread_pct"] = round(spread_pct, 4)
                else:
                    m["_spread_pct"] = 1.0  # unknown spread, keep but flag

                # Attach days-to-resolution for shorter-horizon preference
                m["_days_to_end"] = days_to_end
                
                cleaned_markets.append(m)
            
            logger.info(
                f"Fetched {len(cleaned_markets)} tradeable markets "
                f"(from {len(raw_markets)} raw, horizon <= {MAX_DAYS_TO_RESOLUTION}d, "
                f"skipped: {skipped_volume} low-vol, {skipped_spread} wide-spread)."
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
                except Exception: pass
            
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
        """Run WebSocket with ping/pong keepalive and proxy support."""
        try:
            # Configure SOCKS proxy for WebSocket if WARP is enabled
            ws_kwargs = {"ping_interval": 30, "ping_timeout": 10}
            if self.warp_proxy and "socks5://" in self.warp_proxy:
                proxy_parts = self.warp_proxy.replace("socks5://", "").split(":")
                if len(proxy_parts) == 2:
                    ws_kwargs["proxy_type"] = "socks5"
                    ws_kwargs["http_proxy_host"] = proxy_parts[0]
                    ws_kwargs["http_proxy_port"] = int(proxy_parts[1])
            self.ws.run_forever(**ws_kwargs)
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

    def get_best_bid_ask(self, token_id: str) -> Dict[str, float]:
        """Returns {'bid': float, 'ask': float, 'mid': float} for the given token."""
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
            params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=self.signature_type)
            return self.client.get_balance_allowance(params)
        except Exception as e:
            logger.error(f"Error checking balance: {e}")
            return {}

    def update_permissions(self):
        """Enable trading by granting allowance."""
        if not self.client: return None
        try:
            from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
            logger.info(f"Enabling trading permissions (signature_type={self.signature_type})...")
            params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=self.signature_type)
            resp = self.client.update_balance_allowance(params)
            logger.info(f"Permission Update Sent: {resp}")
            return resp
        except Exception as e:
            logger.error(f"Failed to update permissions: {e}")
            return None

    def get_open_orders(self):
        """Fetch current orders from CLOB (best effort)."""
        if not self.client:
            return []
        try:
            orders = self.client.get_orders()
            if isinstance(orders, dict):
                return orders.get("orders") or orders.get("data") or orders.get("items") or []
            if isinstance(orders, list):
                return orders
            return []
        except Exception as e:
            logger.error(f"Error fetching open orders: {e}")
            return []

    def cancel_order(self, order_id: str):
        """Cancel an open order by ID."""
        if not self.client:
            logger.warning("Cannot cancel order: ClobClient not initialized.")
            return None
        try:
            resp = self.client.cancel(order_id)
            logger.info(f"Cancelled order {order_id[:16]}...: {resp}")
            return resp
        except Exception as e:
            logger.error(f"Error cancelling order {order_id[:16]}...: {e}")
            return None

    # --- EXECUTION METHODS ---

    def place_close_order(self, token_id: str, side: str, price: float, num_shares: float):
        """
        Place an order to close a position (size is in SHARES, not USD).
        Used by the close_position feature and the recycler.
        """
        if not self.client:
            logger.error("Cannot place order: ClobClient not initialized.")
            return None
        order_side = BUY if side.upper() == 'BUY' else SELL
        try:
            price = round(price, 2)
            if price <= 0:
                logger.error(f"Invalid price {price}. Must be > 0.")
                return None
            if price >= 1.0:
                price = 0.99
            size_shares = round(num_shares, 2)
            if size_shares < 0.1:
                logger.warning(f"Order too small: {size_shares} shares. Skipping.")
                return None
            order_args = OrderArgs(
                price=price,
                size=size_shares,
                side=order_side,
                token_id=token_id
            )
            logger.info(f"Close Order: {side} {size_shares:.2f} shares of ...{token_id[-8:]} @ ${price}")
            resp = self.client.create_and_post_order(order_args)
            logger.info(f"Close Order Response: {resp}")
            return resp
        except Exception as e:
            logger.error(f"Close Order Failed: {e}", exc_info=True)
            return None

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
