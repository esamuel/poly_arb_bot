import os
import requests
from web3 import Web3
from dotenv import load_dotenv
import json

load_dotenv()

PRIVATE_KEY = os.getenv("PRIVATE_KEY")
W3 = Web3(Web3.HTTPProvider("https://polygon-bor.publicnode.com"))
ADR = "0xBF42b359EE1aA090342e75D60052177118b0f777"

USDC_NATIVE = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
USDC_BRIDGED = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

ERC20_ABI = [{"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"},{"constant":True,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"type":"function"}]

def check():
    print(f"--- Balance Report for {ADR} ---")
    
    # On-chain EOA balances
    for name, addr in [("Native USDC", USDC_NATIVE), ("Bridged USDC", USDC_BRIDGED)]:
        contract = W3.eth.contract(address=Web3.to_checksum_address(addr), abi=ERC20_ABI)
        bal = contract.functions.balanceOf(ADR).call()
        dec = contract.functions.decimals().call()
        print(f"{name}: {bal / (10**dec):.2f}")
    
    # Proxy Balance Check
    PROXY_ADDRESS = os.getenv("PROXY_ADDRESS")
    print(f"\n--- Proxy Balance Check for {PROXY_ADDRESS} ---")
    if PROXY_ADDRESS:
        p_addr = Web3.to_checksum_address(PROXY_ADDRESS)
        # Check Native
        n_contract = W3.eth.contract(address=Web3.to_checksum_address(USDC_NATIVE), abi=ERC20_ABI)
        n_bal = n_contract.functions.balanceOf(p_addr).call()
        print(f"Proxy Native USDC: {n_bal / 1e6:.2f}")
        
        # Check Bridged
        b_contract = W3.eth.contract(address=Web3.to_checksum_address(USDC_BRIDGED), abi=ERC20_ABI)
        b_bal = b_contract.functions.balanceOf(p_addr).call()
        print(f"Proxy Bridged USDC: {b_bal / 1e6:.2f}")
    else:
        print("No PROXY_ADDRESS found in .env")

if __name__ == "__main__":
    check()
