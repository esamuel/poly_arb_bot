
from web3 import Web3
from dotenv import load_dotenv
import os

load_dotenv()

# Conditional Tokens Contract (Same for both usually)
CTF = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"

ABI = [{"constant":True,"inputs":[{"name":"conditionId","type":"bytes32"}],"name":"getOutcomeSlotCount","outputs":[{"name":"","type":"uint256"}],"type":"function"}]

w3 = Web3(Web3.HTTPProvider("https://polygon-bor.publicnode.com"))

def check():
    condition_id_hex = "0xaf9d0e448129a9f657f851d49495ba4742055d80e0ef1166ba0ee81d4d594214"
    ctr = w3.eth.contract(address=CTF, abi=ABI)
    
    # Check if condition exists
    try:
        slots = ctr.functions.getOutcomeSlotCount(condition_id_hex).call()
        print(f"Outcome Slot Count: {slots}")
    except Exception as e:
        print(f"Error checking condition: {e}")

if __name__ == "__main__":
    check()
