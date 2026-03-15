import requests
import json
import os
from poly_arb_bot.config import PROXY_ADDRESS

address = PROXY_ADDRESS
url = "https://data-api.polymarket.com/positions"
resp = requests.get(url, params={"user": address, "sizeThreshold": "0"}, timeout=15)
positions = resp.json()

print(json.dumps(positions[:2], indent=2))
