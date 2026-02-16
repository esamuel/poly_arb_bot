import os
import json
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds
from dotenv import load_dotenv

load_dotenv()

def check_books():
    host = "https://clob.polymarket.com"
    creds = ApiCreds(
        api_key=os.getenv("POLYMARKET_API_KEY"),
        api_secret=os.getenv("POLYMARKET_API_SECRET"),
        api_passphrase=os.getenv("POLYMARKET_PASSPHRASE")
    )
    client = ClobClient(host, chain_id=137, creds=creds)
    
    # Trump Vaccination tokens (from logs)
    tokens = [
        "1026040810332675975765691079374092497645068222629749503463777732298950570624",
        "5163198084534825925340645164103135890967398285918641974136616012015321520108"
    ]
    
    for t in tokens:
        try:
            print(f"\nChecking Book for: {t}")
            book = client.get_order_book(t)
            print(f"Bids: {len(book.bids)} | Asks: {len(book.asks)}")
            if book.bids: print(f"Best Bid: {book.bids[0].price}")
            if book.asks: print(f"Best Ask: {book.asks[0].price}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    check_books()
