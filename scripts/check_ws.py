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
    # Fetch Top Market Token
    try:
        url = "https://gamma-api.polymarket.com/markets?limit=1&active=true&closed=false&order=volumeNum24hr"
        resp = requests.get(url).json()
        token = json.loads(resp[0]["clobTokenIds"])[0]
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
