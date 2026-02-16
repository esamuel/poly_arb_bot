import requests
import json

def debug_market_ids():
    print("--- Debugging Valid Market IDs ---")
    
    # 1. Fetch 'Trump deport' markets
    # Use Gamma Query
    url = "https://gamma-api.polymarket.com/markets"
    params = {
        "limit": 10,
        "active": "true",
        "closed": "false",
        # "slug": "will-trump-deport-less-than-250k" # Hard to guess slug
    }
    
    resp = requests.get(url, params=params)
    data = resp.json()
    
    found_trump = False
    
    for m in data:
        q = m.get("question", "")
        if "Trump" in q and "deport" in q:
            found_trump = True
            print(f"\nQuestion: {q}")
            print(f"Condition ID: {m.get('conditionId')}")
            
            # Helper to parse clob token ids
            tokens = m.get("clobTokenIds")
            if isinstance(tokens, str):
                tokens = json.loads(tokens)
            
            print(f"Token IDs: {tokens}")
            
            if tokens and len(tokens) >= 2:
                # Check specifics for each token
                t1 = tokens[0]
                t2 = tokens[1]
                print(f"  Token 1 (YES/NO?): {t1}")
                print(f"  Token 2 (YES/NO?): {t2}")

                # Check Collateral from Market
                collat = m.get("collateralToken")
                print(f"  Collateral: {collat}")
                
                # Check Rewards/Liquidity
                rewards = m.get("rewards", {})
                print(f"  Rewards: {rewards}")

    if not found_trump:
        print("\n❌ Could not find 'Trump deport' markets in active list.")

if __name__ == "__main__":
    debug_market_ids()
