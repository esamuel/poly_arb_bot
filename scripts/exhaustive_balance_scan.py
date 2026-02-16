import os
import json
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, BalanceAllowanceParams, AssetType
from dotenv import load_dotenv

load_dotenv()

def check_all():
    host = "https://clob.polymarket.com"
    key = os.getenv("PRIVATE_KEY")
    creds = ApiCreds(
        api_key=os.getenv("POLYMARKET_API_KEY"),
        api_secret=os.getenv("POLYMARKET_API_SECRET"),
        api_passphrase=os.getenv("POLYMARKET_PASSPHRASE")
    )
    
    # Init client
    client = ClobClient(host, key=key, chain_id=137, creds=creds)
    
    print(f"Checking for {client.get_address()}")
    
    for sig_type in [0, 1, 2]:
        print(f"\n--- SIGNATURE TYPE {sig_type} ---")
        for asset in [AssetType.COLLATERAL, AssetType.CONDITIONAL]:
            try:
                params = BalanceAllowanceParams(asset_type=asset, signature_type=sig_type)
                resp = client.get_balance_allowance(params)
                balance = resp.get("balance", "0")
                if float(balance) > 0:
                    print(f"✅ FOUND BALANCE! Asset: {asset} | Balance: {balance}")
                else:
                    print(f"Asset: {asset} | Balance: 0")
            except Exception as e:
                print(f"Error for {asset}: {e}")

if __name__ == "__main__":
    check_all()
