
import requests
import json
from pprint import pprint

def inspect_market():
    # Fetch a few recent active markets
    url = "https://gamma-api.polymarket.com/markets?limit=5&active=true&closed=false"
    resp = requests.get(url).json()
    
    print(f"Found {len(resp)} markets.")
    for m in resp:
        print(f"\n--- Market: {m.get('question')} ---")
        print(f"ID: {m.get('id')}")
        print(f"Created: {m.get('createdAt')}")
        
        # Check Token metadata
        clob_ids = m.get("clobTokenIds")
        print(f"CLOB Token IDs: {clob_ids}")
        
        # We need to find the Collateral Token for this market.
        # Often it's not in the basic 'markets' endpoint. 
        # We might need to check the implicit collateral or a 'token' endpoint.
        # But 'clobTokenIds' implies it is on the CLOB.
        
        # Let's check if the generic 'collateral' field exists or 'currency'
        # Usually it's in the 'tokens' list or similar.
        if "tokens" in m:
            print("Tokens: ", m["tokens"])
            
if __name__ == "__main__":
    inspect_market()
