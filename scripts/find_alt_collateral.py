import requests
import json

def find_alt_collateral():
    print("Searching for markets using collateral OTHER than Native USDC (0x3c49...)...")
    offset = 0
    limit = 100
    NATIVE_USDC = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"
    BRIDGED_USDC = "0x2791bca1f2de4661ed88a30c99a7a9449aa84174"
    
    alt_tokens = {}
    
    while offset < 1000:
        url = f"https://gamma-api.polymarket.com/markets?limit={limit}&offset={offset}&active=true&closed=false"
        try:
            resp = requests.get(url)
            markets = resp.json()
            if not markets: break
                
            for m in markets:
                col = m.get('collateralToken', '').lower()
                if col and col != NATIVE_USDC:
                    if col not in alt_tokens:
                        alt_tokens[col] = []
                    alt_tokens[col].append(m['question'])
            
            offset += limit
        except Exception as e:
            print(f"Error: {e}")
            break
            
    if alt_tokens:
        print(f"\n✅ Found {len(alt_tokens)} alternative collateral tokens!")
        for token, markets in alt_tokens.items():
            print(f"\nToken: {token}")
            if token == BRIDGED_USDC:
                print("   (This is the Bridged USDC you hold!)")
            print(f"   Used by {len(markets)} markets.")
            for q in markets[:3]:
                print(f"   - {q}")
    else:
        print("\n❌ No markets found using alternative collateral. 100% of checked markets are Native USDC.")

if __name__ == "__main__":
    find_alt_collateral()
