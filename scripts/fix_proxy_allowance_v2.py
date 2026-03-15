import os
import json
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, BalanceAllowanceParams, AssetType
from dotenv import load_dotenv
from security_guard import enforce_fund_movement_guard

load_dotenv()

def fix_proxy_allowance():
    enforce_fund_movement_guard("Fix proxy allowance v2")
    host = "https://clob.polymarket.com"
    key = os.getenv("PRIVATE_KEY")
    creds = ApiCreds(
        api_key=os.getenv("POLYMARKET_API_KEY"),
        api_secret=os.getenv("POLYMARKET_API_SECRET"),
        api_passphrase=os.getenv("POLYMARKET_PASSPHRASE")
    )
    proxy_address = os.getenv("PROXY_ADDRESS")
    
    print(f"--- Fixing Allowance for Proxy: {proxy_address} ---")
    
    # Initialize with Proxy funder
    client = ClobClient(host, key=key, chain_id=137, creds=creds, funder=proxy_address, signature_type=2)
    
    try:
        # Check current state
        params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=2)
        before = client.get_balance_allowance(params)
        print(f"Allowance before: {before.get('allowances')}")
        
        # Update allowance
        print("\nSending allowance update request...")
        # Note: update_balance_allowance internally signs a message that the CLOB uses to verify the owner's intent
        resp = client.update_balance_allowance(params)
        print(f"Response: {resp}")
        
        # Verify
        import time
        print("Waiting 5 seconds for update...")
        time.sleep(5)
        after = client.get_balance_allowance(params)
        print(f"Allowance after: {after.get('allowances')}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    fix_proxy_allowance()
