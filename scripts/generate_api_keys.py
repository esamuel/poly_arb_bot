import os
import sys
import re
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from web3 import Web3

# Ensure we can import from parent directory if run directly
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

def update_env_file(api_key, api_secret, passphrase):
    env_path = os.path.join(parent_dir, '.env')
    print(f"Updating .env at {env_path}...")
    
    try:
        with open(env_path, 'r') as f:
            content = f.read()
            
        # Helper to replace or append
        def update_line(key, value):
            pattern = f"^{key}=.*"
            replacement = f"{key}={value}"
            nonlocal content
            if re.search(pattern, content, re.MULTILINE):
                content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
            else:
                content += f"\n{key}={value}"

        update_line("POLYMARKET_API_KEY", api_key)
        update_line("POLYMARKET_API_SECRET", api_secret)
        update_line("POLYMARKET_PASSPHRASE", passphrase)
        
        with open(env_path, 'w') as f:
            f.write(content)
            
        print("✅ .env file updated successfully!")
        
    except Exception as e:
        print(f"❌ Failed to update .env: {e}")

def generate_keys():
    load_dotenv()
    print("--- Polymarket API Key Generator ---")
    
    # Check for private key
    pk = input("Private Key: ").strip()
    if not pk.startswith("0x"):
        pk = "0x" + pk
        
    try:
        w3 = Web3(Web3.HTTPProvider("https://polygon-rpc.com"))
        account = w3.eth.account.from_key(pk)
        address = account.address
        print(f"\nDerived Address: {address}")
        
    except Exception as e:
        print(f"Invalid private key: {e}")
        return

    # --- API KEY GENERATION ---
    print("\nConnecting to Polymarket CLOB...")
    try:
        # We need to initialize with a chain_id. 137 is Polygon Mainnet.
        client = ClobClient("https://clob.polymarket.com", key=pk, chain_id=137)
        
        print("Attempting to create or derive API credentials...")
        creds = client.create_or_derive_api_creds()
        
        print("\nSUCCESS! Credentials obtained.")
        
        # Debugging attributes if needed
        # print(f"DEBUG: {dir(creds)}")

        # Robust extraction
        api_key = getattr(creds, 'api_key', getattr(creds, 'key', 'UNKNOWN'))
        secret = getattr(creds, 'api_secret', getattr(creds, 'secret', 'UNKNOWN'))
        passphrase = getattr(creds, 'passphrase', getattr(creds, 'api_passphrase', 'UNKNOWN'))
        
        print(f"API Key: {api_key}")
        print(f"Passphrase: {passphrase}")
        
        if passphrase == 'UNKNOWN':
             print("WARNING: Could not find passphrase in credentials object.")
             print(f"Available attributes: {dir(creds)}")
        
        # Update .env
        update_env_file(api_key, secret, passphrase)
        
    except Exception as e:
        print(f"\n❌ Polymarket API Error: {e}")
        # Inspect exception
        if "400" in str(e):
             print("This might be a Proxy initialization issue.")

if __name__ == "__main__":
    generate_keys()
