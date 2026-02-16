import os
import requests
import json
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, BalanceAllowanceParams, AssetType
from dotenv import load_dotenv

load_dotenv()

def diagnostic():
    host = "https://clob.polymarket.com"
    key = os.getenv("PRIVATE_KEY")
    proxy = os.getenv("PROXY_ADDRESS")
    
    creds = ApiCreds(
        api_key=os.getenv("POLYMARKET_API_KEY"),
        api_secret=os.getenv("POLYMARKET_API_SECRET"),
        api_passphrase=os.getenv("POLYMARKET_PASSPHRASE")
    )
    
    print(f"--- Proxy Diagnostic for {proxy} ---")
    
    # Initialize Client with Proxy
    client = ClobClient(host, key=key, chain_id=137, creds=creds, funder=proxy, signature_type=2)
    
    try:
        # Check Balance & Allowance via API
        print("\nChecking CLOB API for Balance & Allowance...")
        resp = client.get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=2))
        print(json.dumps(resp, indent=2))
        
        # Check specific collateral required for active markets
        print("\nSearching for Active Markets using Bridged USDC (USDC.e)...")
        gamma_url = "https://gamma-api.polymarket.com/markets?limit=500&active=true&closed=false"
        m_resp = requests.get(gamma_url).json()
        found = 0
        for m in m_resp:
            col = m.get('collateralToken', '').lower()
            if "2791" in col: # 0x2791... is USDC.e
                print(f"✅ Market: {m['question'][:60]}... (ID: {m['id']})")
                print(f"   Tokens: {m.get('clobTokenIds')}")
                found += 1
                if found >= 5: break
        
        if found == 0:
            print("❌ No active Bridged USDC markets found in the last 500 markets.")

    except Exception as e:
        print(f"Diagnostic Error: {e}")

if __name__ == "__main__":
    diagnostic()
