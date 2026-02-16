import os
import json
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds
from dotenv import load_dotenv

load_dotenv()

def check_creds():
    host = "https://clob.polymarket.com"
    key = os.getenv("PRIVATE_KEY")
    creds = ApiCreds(
        api_key=os.getenv("POLYMARKET_API_KEY"),
        api_secret=os.getenv("POLYMARKET_API_SECRET"),
        api_passphrase=os.getenv("POLYMARKET_PASSPHRASE")
    )
    
    # Initialize Client without funder (EOA mode)
    client = ClobClient(host, key=key, chain_id=137, creds=creds, signature_type=0)
    
    print(f"Signer Address: {client.get_address()}")
    
    try:
        print("\nChecking Account Info...")
        # Get address linked to these API keys
        resp = client.get_api_keys()
        print(f"API Key Response: {json.dumps(resp, indent=2)}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_creds()
