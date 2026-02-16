
import os
from py_clob_client.client import ClobClient
from dotenv import load_dotenv
import json

load_dotenv()

def inspect_tokens():
    host = "https://clob.polymarket.com"
    key = os.getenv("PRIVATE_KEY")
    client = ClobClient(host, key=key, chain_id=137)
    
    # Get the specific market
    condition_id = "0xaf9d0e448129a9f657f851d49495ba4742055d80e0ef1166ba0ee81d4d594214"
    print(f"Fetching Market {condition_id}...")
    
    try:
        resp = client.get_market(condition_id)
        print(json.dumps(resp, indent=2))
        
        if "tokens" in resp:
            print("\n--- Token Details ---")
            for t in resp["tokens"]:
                print(json.dumps(t, indent=2))
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    inspect_tokens()
