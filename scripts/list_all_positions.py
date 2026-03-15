
import os
import json
from poly_arb_bot.adapters.polymarket import PolymarketAdapter

adapter = PolymarketAdapter()
positions = adapter.get_portfolio_positions()

print("\n--- Live Data API Positions ---")
for p in positions:
    size = float(p.get("size", 0))
    if size < 0.001: continue
    print(f"- {p.get('title')}: {p.get('outcome')} | Size: {size} | CurValue: ${p.get('currentValue')}")
