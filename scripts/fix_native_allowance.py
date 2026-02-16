
import os
import time
from dotenv import load_dotenv

# 1. Import the client module normally
import py_clob_client.client
from py_clob_client.clob_types import ContractConfig

# 2. Save original function (optional, but good practice if needed)
# But we need the original logic to get the object first
import py_clob_client.config
_original_get_config = py_clob_client.config.get_contract_config

USDC_NATIVE = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"

# 3. Define Patch
def patched_get_contract_config(chainID: int, neg_risk: bool = False) -> ContractConfig:
    print(f"⚡ [PATCH] Intercepted config request for Chain {chainID} (NegRisk={neg_risk})")
    config = _original_get_config(chainID, neg_risk)
    
    # Check if we need to replace collateral
    if config.collateral.lower() != USDC_NATIVE.lower():
        print(f"⚡ [PATCH] Replacing Collateral {config.collateral} -> {USDC_NATIVE}")
        config.collateral = USDC_NATIVE
    return config

# 4. EXPLICITLY Patch the function in the 'client' module namespace
print("Applying Monkey Patch to py_clob_client.client.get_contract_config...")
py_clob_client.client.get_contract_config = patched_get_contract_config

# 5. Now we can use ClobClient and it should use the patched function
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, BalanceAllowanceParams, AssetType

load_dotenv()

def fix_native_allowance():
    host = "https://clob.polymarket.com"
    key = os.getenv("PRIVATE_KEY")
    creds = ApiCreds(
        api_key=os.getenv("POLYMARKET_API_KEY"),
        api_secret=os.getenv("POLYMARKET_API_SECRET"),
        api_passphrase=os.getenv("POLYMARKET_PASSPHRASE")
    )
    proxy_address = os.getenv("PROXY_ADDRESS")
    
    print(f"--- Fixing Native USDC Allowance for Proxy: {proxy_address} ---")
    
    # Initialize with Proxy funder + Sig Type 2
    client = ClobClient(host, key=key, chain_id=137, creds=creds, funder=proxy_address, signature_type=2)
    
    try:
        # Check current state (using patched config)
        params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=2)
        # Verify patch is working by checking collateral address
        print(f"Client Collateral Address: {client.get_collateral_address()}")

        before = client.get_balance_allowance(params)
        print(f"Allowance before: {before.get('allowances')}")
        
        # Update allowance
        print("\nSending allowance update request (Native USDC)...")
        resp = client.update_balance_allowance(params)
        print(f"Response: {resp}")
        
        # Verify
        print("Waiting 5 seconds for propagation...")
        time.sleep(5)
        after = client.get_balance_allowance(params)
        print(f"Allowance after: {after.get('allowances')}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    fix_native_allowance()
