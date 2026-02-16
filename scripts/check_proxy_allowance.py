import os
from web3 import Web3
from dotenv import load_dotenv

load_dotenv()

W3 = Web3(Web3.HTTPProvider("https://polygon-bor.publicnode.com"))
PROXY = os.getenv("PROXY_ADDRESS")
USDC_NATIVE = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
USDC_BRIDGED = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
EXCHANGE = "0x4bFb41d5B3570DeFd21C390604A6896f5b652F93"

ERC20_ABI = [{"constant":True,"inputs":[{"name":"_owner","type":"address"},{"name":"_spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"type":"function"}]

def check():
    if not PROXY:
        print("No PROXY_ADDRESS in .env")
        return
        
    p_addr = Web3.to_checksum_address(PROXY)
    e_addr = Web3.to_checksum_address(EXCHANGE)
    
    # Check Native
    n_contract = W3.eth.contract(address=Web3.to_checksum_address(USDC_NATIVE), abi=ERC20_ABI)
    n_allowance = n_contract.functions.allowance(p_addr, e_addr).call()
    print(f"Proxy Native USDC Allowance: {n_allowance / 1e6:.2f}")
    
    # Check Bridged
    b_contract = W3.eth.contract(address=Web3.to_checksum_address(USDC_BRIDGED), abi=ERC20_ABI)
    b_allowance = b_contract.functions.allowance(p_addr, e_addr).call()
    print(f"Proxy Bridged USDC Allowance: {b_allowance / 1e6:.2f}")

if __name__ == "__main__":
    check()
