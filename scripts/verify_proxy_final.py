import os
import json
import requests
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, BalanceAllowanceParams, AssetType
from dotenv import load_dotenv

load_dotenv()

def verify_proxy_final():
    host = "https://clob.polymarket.com"
    key = os.getenv("PRIVATE_KEY")
    creds = ApiCreds(
        api_key=os.getenv("POLYMARKET_API_KEY"),
        api_secret=os.getenv("POLYMARKET_API_SECRET"),
        api_passphrase=os.getenv("POLYMARKET_PASSPHRASE")
    )
    proxy_address = os.getenv("PROXY_ADDRESS")
    
    print(f"--- Final Proxy Verification for {proxy_address} ---")
    
    try:
        # 1. Check CLOB API recognition
        print("\nChecking CLOB API...")
        client = ClobClient(host, key=key, chain_id=137, creds=creds, funder=proxy_address, signature_type=2)
        params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=2)
        resp = client.get_balance_allowance(params)
        print(json.dumps(resp, indent=2))
        
        balance = float(resp.get("balance", "0")) / 1e6
        print(f"\nCLOB Available Balance: ${balance:.2f}")

        # 2. Check for Bridged USDC markets just in case
        print("\nSearching for any active Bridged USDC (USDC.e) markets...")
        gamma_url = "https://gamma-api.polymarket.com/markets?limit=500&active=true&closed=false"
        m_resp = requests.get(gamma_url).json()
        bridged_markets = []
        for m in m_resp:
            col = m.get('collateralToken', '').lower()
            if "2791" in col: # 0x2791 is USDC.e
                bridged_markets.append(m['question'])
        
        if bridged_markets:
            print(f"✅ Found {len(bridged_markets)} Bridged USDC markets.")
            for q in bridged_markets[:3]:
                print(f"   - {q}")
        else:
            print("❌ No active Bridged USDC markets found in top 500.")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    verify_proxy_final()
