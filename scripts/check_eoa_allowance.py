
import os
from web3 import Web3
from dotenv import load_dotenv

load_dotenv()

EOA = "0xBF42b359EE1aA090342e75D60052177118b0f777"
USDC_NATIVE = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
SPENDER = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E" # CTF Exchange / Clob

ABI = [{"constant":True,"inputs":[{"name":"_owner","type":"address"},{"name":"_spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"type":"function"}]

w3 = Web3(Web3.HTTPProvider("https://polygon-bor.publicnode.com"))

def check():
    ctr = w3.eth.contract(address=Web3.to_checksum_address(USDC_NATIVE), abi=ABI)
    allow = ctr.functions.allowance(Web3.to_checksum_address(EOA), Web3.to_checksum_address(SPENDER)).call()
    print(f"Native USDC Allowance for EOA -> Spender: {allow}")

if __name__ == "__main__":
    check()
