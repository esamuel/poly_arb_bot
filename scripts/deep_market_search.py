import requests
import json

def deep_market_search():
    bridged_token = "0x2791bca1f2de4661ed88a30c99a7a9449aa84174"
    print(f"Searching for markets using Bridged USDC ({bridged_token})...")
    
    offset = 0
    limit = 100
    found_any = False
    
    while offset < 2000:
        url = f"https://gamma-api.polymarket.com/markets?limit={limit}&offset={offset}&active=true&closed=false"
        try:
            resp = requests.get(url)
            markets = resp.json()
            if not markets:
                break
            
            for m in markets:
                col = m.get('collateralToken', '').lower()
                if col == bridged_token:
                    print(f"✅ FOUND: {m['question']} (ID: {m['id']})")
                    found_any = True
            
            offset += limit
            print(f"Checked {offset} markets...")
        except Exception as e:
            print(f"Error: {e}")
            break
            
    if not found_any:
        print("\n❌ NO active markets found using Bridged USDC in the top 2000.")

if __name__ == "__main__":
    deep_market_search()
