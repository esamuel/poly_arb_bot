
import os
import time
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, BalanceAllowanceParams, AssetType
from security_guard import enforce_fund_movement_guard

load_dotenv()

USDC_NATIVE = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"

def fix_native_allowance():
    enforce_fund_movement_guard("Fix native allowance v2")
    host = "https://clob.polymarket.com"
    key = os.getenv("PRIVATE_KEY")
    creds = ApiCreds(
        api_key=os.getenv("POLYMARKET_API_KEY"),
        api_secret=os.getenv("POLYMARKET_API_SECRET"),
        api_passphrase=os.getenv("POLYMARKET_PASSPHRASE")
    )
    proxy_address = os.getenv("PROXY_ADDRESS")
    
    print(f"--- Fixing Native USDC Allowance for Proxy: {proxy_address} ---")
    
    # Initialize with Proxy funder
    client = ClobClient(host, key=key, chain_id=137, creds=creds, funder=proxy_address, signature_type=2)
    
    try:
        # Check current state with explicit TOKEN ID
        print(f"Checking allowance for Token: {USDC_NATIVE}")
        params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=2, token_id=USDC_NATIVE)
        before = client.get_balance_allowance(params)
        print(f"Allowance before: {before.get('allowances')}")
        
        # Update allowance
        print("\nSending allowance update request (Native USDC)...")
        resp = client.update_balance_allowance(params)
        print(f"Response: {resp}")
        
        # Verify
        print("Waiting 5 seconds...")
        time.sleep(5)
        after = client.get_balance_allowance(params)
        print(f"Allowance after: {after.get('allowances')}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    fix_native_allowance()
