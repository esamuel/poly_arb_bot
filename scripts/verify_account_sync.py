#!/usr/bin/env python3
"""
Verify Polymarket account data matches polymarket.com.

Fetches:
- Cash balance (CLOB API)
- Positions (Data API - same as polymarket.com)
- Open orders (CLOB API)

Compare the output with polymarket.com — they should match.
Minor timing differences (e.g. pending fills) can cause slight variance.
"""
import os
import sys

# Project root
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

os.chdir(project_root)


def main():
    from poly_arb_bot.adapters.polymarket import PolymarketAdapter

    print("=" * 60)
    print("Polymarket Account Verification")
    print("Compare with polymarket.com — data should match")
    print("=" * 60)

    adapter = PolymarketAdapter()

    # 1. Cash balance (CLOB)
    try:
        bal = adapter.get_balance_allowance()
        cash_raw = bal.get("balance", "0")
        cash_usd = float(cash_raw) / 1e6
        print(f"\n[1] CASH BALANCE (USDC)")
        print(f"    ${cash_usd:,.2f}")
    except Exception as e:
        print(f"\n[1] CASH BALANCE — Error: {e}")

    # 2. Positions (Data API — same as polymarket.com)
    try:
        pos_list = adapter.get_portfolio_positions()
        print(f"\n[2] POSITIONS ({len(pos_list)} total)")
        if not pos_list:
            print("    No open positions")
        else:
            total_val = 0
            for p in pos_list:
                size = float(p.get("size", 0))
                if size < 0.001:
                    continue
                title = (p.get("title", "?") or "?")[:50]
                outcome = p.get("outcome", "?")
                cur_val = float(p.get("currentValue", 0))
                total_val += cur_val
                print(f"    • {outcome}: {title}...")
                print(f"      Size: {size:.2f} | Value: ${cur_val:.2f}")
            print(f"    ---")
            print(f"    Total positions value: ${total_val:,.2f}")
    except Exception as e:
        print(f"\n[2] POSITIONS — Error: {e}")

    # 3. Open orders (CLOB)
    try:
        orders = adapter.get_open_orders()
        print(f"\n[3] OPEN ORDERS ({len(orders)} total)")
        if not orders:
            print("    No open orders")
        else:
            for o in orders:
                side = o.get("side", o.get("order_side", "?"))
                price = o.get("price", o.get("limit_price", o.get("limitPrice", "?")))
                size = o.get("size", o.get("remaining_size", o.get("remainingSize", "?")))
                token_short = (o.get("asset_id", o.get("token_id", "?")) or "?")[-8:]
                print(f"    • {side} @ ${price} × {size} (...{token_short})")
    except Exception as e:
        print(f"\n[3] OPEN ORDERS — Error: {e}")

    # 4. Portfolio summary (combined)
    try:
        summary = adapter.get_portfolio_summary()
        print(f"\n[4] PORTFOLIO SUMMARY (same as polymarket.com)")
        print(f"    Cash:        ${summary.get('cash_balance', 0):,.2f}")
        print(f"    Positions:   ${summary.get('total_current_value', 0):,.2f}")
        print(f"    Portfolio:   ${summary.get('portfolio_value', 0):,.2f}")
        print(f"    Unrealized:  ${summary.get('total_unrealized_pnl', 0):,.2f}")
        print(f"    Realized:    ${summary.get('total_realized_pnl', 0):,.2f}")
    except Exception as e:
        print(f"\n[4] PORTFOLIO SUMMARY — Error: {e}")

    print("\n" + "=" * 60)
    print("Compare the numbers above with polymarket.com")
    print("If they match, your account is in sync.")
    print("=" * 60)


if __name__ == "__main__":
    main()
