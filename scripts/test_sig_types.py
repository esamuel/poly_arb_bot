import os
import json
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, BalanceAllowanceParams, AssetType
from dotenv import load_dotenv

load_dotenv()

def try_sig_types():
    host = "https://clob.polymarket.com"
    key = os.getenv("PRIVATE_KEY")
    creds = ApiCreds(
        api_key=os.getenv("POLYMARKET_API_KEY"),
        api_secret=os.getenv("POLYMARKET_API_SECRET"),
        api_passphrase=os.getenv("POLYMARKET_PASSPHRASE")
    )
    
    print("--- Sig Type Diagnostic ---")
    for sig_type in [0, 1, 2]:
        try:
            print(f"\nChecking Sig Type {sig_type}...")
            client = ClobClient(host, key=key, chain_id=137, creds=creds, signature_type=sig_type)
            resp = client.get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=sig_type))
            print(f"Balance: {resp.get('balance')}")
            # print(json.dumps(resp, indent=2))
        except Exception as e:
            print(f"Error for {sig_type}: {e}")

if __name__ == "__main__":
    try_sig_types()
