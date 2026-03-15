
import os
import logging
from poly_arb_bot.adapters.polymarket import PolymarketAdapter
from py_clob_client.clob_types import BalanceAllowanceParams, AssetType

logging.basicConfig(level=logging.INFO)

adapter = PolymarketAdapter()

print("\n--- Balance Check ---")
print(f"Proxy Address: {adapter.proxy_address}")
print(f"Use Proxy Mode: {adapter.use_proxy_mode}")
print(f"Signature Type: {adapter.signature_type}")

# Check EOA balance (signature_type=0)
params_eoa = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=0)
bal_eoa = adapter.client.get_balance_allowance(params_eoa)
print(f"EOA Balance: ${float(bal_eoa.get('balance', '0')) / 1e6:.2f}")

# Check Proxy balance (signature_type=2)
params_proxy = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=2)
bal_proxy = adapter.client.get_balance_allowance(params_proxy)
print(f"Proxy Balance: ${float(bal_proxy.get('balance', '0')) / 1e6:.2f}")

# Check Portfolio summary (uses Proxy by default if configured)
summary = adapter.get_portfolio_summary()
print(f"Portfolio Summary Cash: ${summary.get('cash_balance', 0.0):.2f}")
print(f"Portfolio Total Value: ${summary.get('portfolio_value', 0.0):.2f}")
