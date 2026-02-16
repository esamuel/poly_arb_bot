import os
import json
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, BalanceAllowanceParams, AssetType
from dotenv import load_dotenv

load_dotenv()

def check_proxy_linked():
    host = "https://clob.polymarket.com"
    key = os.getenv("PRIVATE_KEY")
    creds = ApiCreds(
        api_key=os.getenv("POLYMARKET_API_KEY"),
        api_secret=os.getenv("POLYMARKET_API_SECRET"),
        api_passphrase=os.getenv("POLYMARKET_PASSPHRASE")
    )
    proxy = os.getenv("PROXY_ADDRESS")
    
    # Init client WITH funder=proxy
    client = ClobClient(host, key=key, chain_id=137, creds=creds, funder=proxy, signature_type=2)
    
    print(f"Checking CLOB for Funder: {proxy}")
    
    try:
        # Check signature_type 2 (Proxy) for balance
        print("\nChecking CLOB API (Funder=Proxy, Sig Type 2)...")
        resp = client.get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=2))
        print(json.dumps(resp, indent=2))
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_proxy_linked()
