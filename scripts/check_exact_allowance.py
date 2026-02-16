import os
from web3 import Web3
from dotenv import load_dotenv

load_dotenv()

W3 = Web3(Web3.HTTPProvider("https://polygon-bor.publicnode.com"))
PROXY = "0xc383AaA749043c0ba96ECf58ce23c6D1Dd203adA"
USDC_BRIDGED = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
# The one from API
EXCHANGE_API = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
# The one I used
EXCHANGE_OLD = "0x4bFb41d5B3570DeFd21C390604A6896f5b652F93"

ERC20_ABI = [{"constant":True,"inputs":[{"name":"_owner","type":"address"},{"name":"_spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"type":"function"}]

def check():
    p_addr = Web3.to_checksum_address(PROXY)
    b_contract = W3.eth.contract(address=Web3.to_checksum_address(USDC_BRIDGED), abi=ERC20_ABI)
    
    a1 = b_contract.functions.allowance(p_addr, Web3.to_checksum_address(EXCHANGE_API)).call()
    a2 = b_contract.functions.allowance(p_addr, Web3.to_checksum_address(EXCHANGE_OLD)).call()
    
    print(f"Allowance for API Exchange ({EXCHANGE_API}): {a1 / 1e6:.2f}")
    print(f"Allowance for OLD Exchange ({EXCHANGE_OLD}): {a2 / 1e6:.2f}")

if __name__ == "__main__":
    check()
