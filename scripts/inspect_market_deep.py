
import requests
import json

def inspect_deep():
    # Fetch specific market ID from logs: 517310
    # "Will Trump deport less than 250,000?"
    # Using Gamma API detailed endpoint if possible, or just the list with that ID
    
    url = "https://gamma-api.polymarket.com/markets/517310"
    print(f"Fetching {url}...")
    
    try:
        resp = requests.get(url)
        if resp.status_code == 200:
            data = resp.json()
            print(json.dumps(data, indent=2))
        else:
            print(f"Failed: {resp.status_code}")
            # Try searching list
            url2 = "https://gamma-api.polymarket.com/markets?id=517310"
            resp2 = requests.get(url2)
            print(json.dumps(resp2.json(), indent=2))
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    inspect_deep()
