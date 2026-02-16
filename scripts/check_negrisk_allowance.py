
import os
import requests
from web3 import Web3
from dotenv import load_dotenv

load_dotenv()

EOA = "0xBF42b359EE1aA090342e75D60052177118b0f777"
USDC_NATIVE = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"

# Exchange Addresses
EXCHANGE_STD = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
EXCHANGE_NEG = "0xC5d563A36AE78145C45a50134d48A1215220f80a" 

ABI = [{"constant":True,"inputs":[{"name":"_owner","type":"address"},{"name":"_spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"type":"function"}]

w3 = Web3(Web3.HTTPProvider("https://polygon-bor.publicnode.com"))

def check():
    # 1. Check a market to see if it is Neg Risk
    print("--- Market Check ---")
    try:
        url = "https://gamma-api.polymarket.com/markets?limit=1&active=true&closed=false"
        resp = requests.get(url).json()
        if resp:
            m = resp[0]
            print(f"Market: {m.get('question')}")
            print(f"Neg Risk: {m.get('neg_risk')}")
            print(f"Neg Risk Market ID: {m.get('neg_risk_market_id')}")
    except Exception as e:
        print(f"Market fetch failed: {e}")

    # 2. Check Allowance for Neg Risk Exchange
    print("\n--- Allowance Check (Native USDC) ---")
    ctr = w3.eth.contract(address=Web3.to_checksum_address(USDC_NATIVE), abi=ABI)
    
    allow_std = ctr.functions.allowance(Web3.to_checksum_address(EOA), Web3.to_checksum_address(EXCHANGE_STD)).call()
    print(f"EOA -> Standard Exchange ({EXCHANGE_STD[:6]}...): {allow_std}")

    allow_neg = ctr.functions.allowance(Web3.to_checksum_address(EOA), Web3.to_checksum_address(EXCHANGE_NEG)).call()
    print(f"EOA -> Neg Risk Exchange ({EXCHANGE_NEG[:6]}...): {allow_neg}")

if __name__ == "__main__":
    check()
