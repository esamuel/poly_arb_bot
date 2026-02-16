import os
import json
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, BalanceAllowanceParams, AssetType
from dotenv import load_dotenv

load_dotenv()

def diagnostic():
    host = "https://clob.polymarket.com"
    key = os.getenv("PRIVATE_KEY")
    creds = ApiCreds(
        api_key=os.getenv("POLYMARKET_API_KEY"),
        api_secret=os.getenv("POLYMARKET_API_SECRET"),
        api_passphrase=os.getenv("POLYMARKET_PASSPHRASE")
    )
    
    client = ClobClient(host, key=key, chain_id=137, creds=creds, signature_type=0)
    
    print(f"--- EOA Diagnostic for {client.get_address()} ---")
    
    try:
        # Check signature_type 0 (EOA)
        print("\nChecking CLOB API (Sig Type 0)...")
        resp = client.get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=0))
        print(json.dumps(resp, indent=2))
        
        # Also check signature_type 2 just in case the account is still "Proxy-flavor"
        print("\nChecking CLOB API (Sig Type 2)...")
        resp2 = client.get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=2))
        print(json.dumps(resp2, indent=2))

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    diagnostic()
