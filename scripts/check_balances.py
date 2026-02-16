import os
import sys
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds

# Ensure we can import from parent directory if run directly
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

def check_balance():
    load_dotenv()
    print("--- Polymarket Balance Check ---")
    
    api_key = os.getenv("POLYMARKET_API_KEY")
    api_secret = os.getenv("POLYMARKET_API_SECRET")
    passphrase = os.getenv("POLYMARKET_PASSPHRASE")
    
    if not api_key:
        print("❌ Error: Missing API keys.")
        return

    try:
        creds = ApiCreds(api_key=api_key, api_secret=api_secret, api_passphrase=passphrase)
        
        # Initialize Client without Private Key (using L2 Auth)
        client = ClobClient("https://clob.polymarket.com", key=None, chain_id=137, creds=creds)
        print("Client initialized with API Credentials.")
        
        # 1. Check Auth (Get API Keys)
        try:
            keys = client.get_api_keys()
            print(f"✅ Auth Successful. Found {len(keys)} keys.")
        except Exception as e:
            print(f"❌ Auth Failed: {e}")
            print("To trade, you might need the Private Key to Sign Level 1 headers.")
            return

        # 2. Check USDC Balance (requires asset info or user address)
        # Without PK, we don't know the address unless we derive it from keys? No.
        # But we can ask the user or just try to place a dummy order check?
        
        # Ideally, we read the address from config if available.
        # Or, we just try to get collateral balance if the client supports it "me" style.
        # py-clob-client doesn't have "get_my_balance".
        
        print("Note: To check balance, we need the Wallet Address.")
        # We can try to infer it from the user's previous generate script output if we saved it?
        # No, we didn't save the address to .env.
        
        # But for TRADING, does send_order work without PK?
        # Let's try to fetch open orders (requires Auth).
        orders = client.get_orders()
        print(f"Open Orders: {len(orders)}")
        
        print("✅ L2 API Access Confirmed.")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    check_balance()
