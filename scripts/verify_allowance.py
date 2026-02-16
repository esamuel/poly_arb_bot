import os
from web3 import Web3
from dotenv import load_dotenv

load_dotenv()

W3 = Web3(Web3.HTTPProvider("https://polygon-bor.publicnode.com"))
ADR = "0xBF42b359EE1aA090342e75D60052177118b0f777"
USDC_NATIVE = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
EXCHANGE = "0x4bFb41d5B3570DeFd21C390604A6896f5b652F93" # Settlement Exchange

ERC20_ABI = [{"constant":True,"inputs":[{"name":"_owner","type":"address"},{"name":"_spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"type":"function"}]

def check():
    target_exchange = Web3.to_checksum_address(EXCHANGE)
    contract = W3.eth.contract(address=Web3.to_checksum_address(USDC_NATIVE), abi=ERC20_ABI)
    allowance = contract.functions.allowance(ADR, target_exchange).call()
    print(f"Allowance for Exchange {target_exchange}: {allowance / 1e6:.2f} USDC")

if __name__ == "__main__":
    check()
