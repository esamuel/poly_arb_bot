import requests
import json

def find_bridged_markets():
    print("Searching for ALL active markets using Bridged USDC (USDC.e)...")
    offset = 0
    limit = 100
    found_markets = []
    
    while offset < 1000:
        url = f"https://gamma-api.polymarket.com/markets?limit={limit}&offset={offset}&active=true&closed=false"
        try:
            resp = requests.get(url)
            markets = resp.json()
            if not markets:
                break
                
            for m in markets:
                col = m.get('collateralToken', '').lower()
                # 0x2791... is USDC.e
                if "2791" in col:
                    found_markets.append({
                        "id": m['id'],
                        "question": m['question'],
                        "tokens": m.get('clobTokenIds'),
                        "volume": m.get('volumeNum', 0)
                    })
            
            offset += limit
            print(f"Checked {offset} markets...")
        except Exception as e:
            print(f"Error at offset {offset}: {e}")
            break
            
    if found_markets:
        print(f"\n✅ Found {len(found_markets)} Bridged USDC markets!")
        for fm in found_markets[:10]:
            print(f"- {fm['question']} (Vol: {fm['volume']})")
            print(f"  Tokens: {fm['tokens']}")
    else:
        print("\n❌ No active Bridged USDC markets found in the first 1000 results.")

if __name__ == "__main__":
    find_bridged_markets()
