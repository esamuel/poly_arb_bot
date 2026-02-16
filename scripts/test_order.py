from py_clob_client.client import ClobClient, ApiCreds, OrderArgs
from py_clob_client.order_builder.constants import BUY
import os
from dotenv import load_dotenv

load_dotenv() # Force reload

def test_trade():
    print("--- Testing Live Order ---")
    size_usd = 1.0 # Try a tiny trade
    price = 0.5
    shares = size_usd / price
    
    token_id = "13244681086321087932946246027856416106585284024824496763706748621681543444582" # Trump 250-500k (YES?)
    
    print(f"Token: {token_id}")
    print(f"Size: {shares} shares @ {price} = ${size_usd}")
    
    host = "https://clob.polymarket.com"
    key = os.getenv("PRIVATE_KEY")
    creds = ApiCreds(
        api_key=os.getenv("POLYMARKET_API_KEY"),
        api_secret=os.getenv("POLYMARKET_API_SECRET"),
        api_passphrase=os.getenv("POLYMARKET_PASSPHRASE")
    )
    client = ClobClient(host, key=key, chain_id=137, creds=creds)
    
    try:
        order_args = OrderArgs(
            price=price,
            size=shares,
            side=BUY,
            token_id=token_id
        )
        print("Sending Order...")
        resp = client.create_and_post_order(order_args)
        print(f"✅ Success! Response: {resp}")
    except Exception as e:
        print(f"❌ Failed: {e}")

if __name__ == "__main__":
    test_trade()
