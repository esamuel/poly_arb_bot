import os
import json
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds
from dotenv import load_dotenv

load_dotenv()

def check_collateral():
    host = "https://clob.polymarket.com"
    creds = ApiCreds(
        api_key=os.getenv("POLYMARKET_API_KEY"),
        api_secret=os.getenv("POLYMARKET_API_SECRET"),
        api_passphrase=os.getenv("POLYMARKET_PASSPHRASE")
    )
    client = ClobClient(host, chain_id=137, creds=creds)
    
    try:
        print("\nChecking CLOB Collateral...")
        # There isn't a direct get_collateral but we can check the collateral address from a market
        # Or look at the balance details if possible
        # Actually, let's just check the balance for every possible asset type
        from py_clob_client.clob_types import AssetType, BalanceAllowanceParams
        
        for asset in [AssetType.COLLATERAL, AssetType.CONDITIONAL]:
            print(f"\nAsset: {asset}")
            resp = client.get_balance_allowance(BalanceAllowanceParams(asset_type=asset, signature_type=0))
            print(json.dumps(resp, indent=2))
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_collateral()
