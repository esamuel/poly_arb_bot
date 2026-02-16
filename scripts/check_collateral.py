
import os
from py_clob_client.client import ClobClient
from dotenv import load_dotenv

load_dotenv()

def check():
    host = "https://clob.polymarket.com"
    key = os.getenv("PRIVATE_KEY")
    client = ClobClient(host, key=key, chain_id=137)
    
    # Get a market
    resp = client.get_markets(next_cursor="")
    if "data" in resp and len(resp["data"]) > 0:
        m = resp["data"][0]
        print(f"Market ID: {m.get('condition_id')}")
        print(f"Question: {m.get('question')}")
        
        # Check tokens
        tokens = m.get("tokens")
        if tokens:
            print(f"Token 0 ID: {tokens[0].get('token_id')}")
            
        # Does the market object have collateral info?
        # Usually checking the asset ID or querying market details
        # Let's inspect the keys
        print("Keys:", m.keys())
        
        # We can also check specific token details if possible
        
    else:
        print("No markets found via CLOB API.")

if __name__ == "__main__":
    check()
