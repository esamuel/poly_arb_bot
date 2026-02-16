from py_clob_client.client import ClobClient, ApiCreds, OrderArgs
from py_clob_client.order_builder.constants import BUY
import requests
import os
from dotenv import load_dotenv

load_dotenv()

def test_random_market():
    print("--- Testing Random Active Market ---")
    
    # 1. Fetch Top Market
    url = "https://gamma-api.polymarket.com/markets?limit=1&active=true&closed=false&order=volumeNum24hr"
    resp = requests.get(url)
    m = resp.json()[0]
    
    q = m['question']
    tokens = m['clobTokenIds']
    if isinstance(tokens, str): import json; tokens = json.loads(tokens)
    target_token = tokens[1] # YES
    
    print(f"Market: {q}")
    print(f"Token: {target_token}")
    
    # 2. Setup Client
    host = "https://clob.polymarket.com"
    key = os.getenv("PRIVATE_KEY")
    creds = ApiCreds(
        api_key=os.getenv("POLYMARKET_API_KEY"),
        api_secret=os.getenv("POLYMARKET_API_SECRET"),
        api_passphrase=os.getenv("POLYMARKET_PASSPHRASE")
    )
    client = ClobClient(host, key=key, chain_id=137, creds=creds)
    
    # 3. Place Order ($1.0 at very low price to not fill)
    price = 0.05 # 5 cents
    size_usd = 1.0
    shares = size_usd / price
    
    print(f"Attempting BUY {shares} shares @ {price} ($1.0)")
    
    try:
        order_args = OrderArgs(
            price=price,
            size=shares,
            side=BUY,
            token_id=target_token
        )
        resp = client.create_and_post_order(order_args)
        print(f"✅ Success! Response: {resp}")
        
        # Cancel immediately if possible? Or just leave it (it's 5 cents).
        # client.cancel_order(resp['orderID'])
        
    except Exception as e:
        print(f"❌ Failed: {e}")

if __name__ == "__main__":
    test_random_market()
