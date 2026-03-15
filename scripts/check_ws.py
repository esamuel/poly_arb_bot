import websocket
import json

def on_message(ws, message):
    data = json.loads(message)
    print(f"Update: {data}")
    # Close after 1 message
    ws.close()

import requests

def on_open(ws):
    print("Opened")
    # Fetch one active market token
    try:
        url = "https://gamma-api.polymarket.com/markets?limit=5&active=true&closed=false"
        resp = requests.get(url, timeout=15).json()
        token = None
        for market in resp:
            raw = market.get("clobTokenIds", [])
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except Exception:
                    raw = []
            if isinstance(raw, list) and raw:
                token = raw[0]
                break
        if not token:
            raise RuntimeError("No valid market token found")
        print(f"Subscribing to Top Volume Token: {token}")
        
        msg = {
            "assets_ids": [token],
            "type": "market"
        }
        ws.send(json.dumps(msg))
    except Exception as e:
        print(f"Error fetching token: {e}")
        ws.close()

if __name__ == "__main__":
    ws = websocket.WebSocketApp("wss://ws-subscriptions-clob.polymarket.com/ws/market",
                                on_open=on_open,
                                on_message=on_message)
    ws.run_forever()
