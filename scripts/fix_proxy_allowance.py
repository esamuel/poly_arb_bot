import os
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, BalanceAllowanceParams, AssetType
from dotenv import load_dotenv
from security_guard import enforce_fund_movement_guard

load_dotenv()

def fix_proxy_allowance():
    enforce_fund_movement_guard("Fix proxy allowance")
    host = "https://clob.polymarket.com"
    key = os.getenv("PRIVATE_KEY")
    proxy = os.getenv("PROXY_ADDRESS")
    
    creds = ApiCreds(
        api_key=os.getenv("POLYMARKET_API_KEY"),
        api_secret=os.getenv("POLYMARKET_API_SECRET"),
        api_passphrase=os.getenv("POLYMARKET_PASSPHRASE")
    )
    
    # Initialize with Proxy
    client = ClobClient(host, key=key, chain_id=137, creds=creds, funder=proxy, signature_type=2)
    
    print(f"🔄 Attempting Proxy Allowance for {proxy}...")
    
    try:
        # Grant allowance for Collateral (USDC)
        # signature_type=2 matches Gnosis Safe
        params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=2)
        resp = client.update_balance_allowance(params)
        print(f"Allowance Update Response: {resp}")
        
        print("✅ Proxy Allowance request sent. Wait 10-20 seconds for blockchain confirmation.")
    except Exception as e:
        print(f"❌ Error updating proxy allowance: {e}")

if __name__ == "__main__":
    fix_proxy_allowance()
