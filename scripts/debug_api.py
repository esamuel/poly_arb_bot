import requests

def debug_api():
    url = "https://gamma-api.polymarket.com/markets"
    params = {"limit": 1, "active": "true", "closed": "false", "order": "volume"}
    try:
        resp = requests.get(url, params=params)
        print(f"Status: {resp.status_code}")
        print(f"Content: {resp.text[:500]}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    debug_api()
