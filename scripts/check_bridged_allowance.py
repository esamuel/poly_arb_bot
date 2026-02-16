
import os
import time
from web3 import Web3
from dotenv import load_dotenv

load_dotenv()

EOA = "0xBF42b359EE1aA090342e75D60052177118b0f777"
USDC_BRIDGED = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
EXCHANGE_NEG = "0xC5d563A36AE78145C45a50134d48A1215220f80a" 

ABI = [{"constant":True,"inputs":[{"name":"_owner","type":"address"},{"name":"_spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"type":"function"},
       {"constant":False,"inputs":[{"name":"_spender","type":"address"},{"name":"_value","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"payable":False,"stateMutability":"nonpayable","type":"function"}]

w3 = Web3(Web3.HTTPProvider("https://polygon-bor.publicnode.com"))
pkey = os.getenv("PRIVATE_KEY")

def check_and_approve():
    print("--- Bridged USDC Allowance Check (Neg Risk) ---")
    
    contract = w3.eth.contract(address=Web3.to_checksum_address(USDC_BRIDGED), abi=ABI)
    
    allow = contract.functions.allowance(
        Web3.to_checksum_address(EOA),
        Web3.to_checksum_address(EXCHANGE_NEG)
    ).call()
    
    print(f"Allowance: {allow}")
    
    if allow == 0:
        print("Approving Exchange...")
        nonce = w3.eth.get_transaction_count(EOA)
        tx = contract.functions.approve(
            Web3.to_checksum_address(EXCHANGE_NEG),
            2**256 - 1
        ).build_transaction({
            'chainId': 137,
            'gas': 100000,
            'maxFeePerGas': w3.to_wei('50', 'gwei'),
            'maxPriorityFeePerGas': w3.to_wei('30', 'gwei'),
            'nonce': nonce,
        })
        signed_tx = w3.eth.account.sign_transaction(tx, private_key=pkey)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        print(f"Tx Sent: {tx_hash.hex()}")
        w3.eth.wait_for_transaction_receipt(tx_hash)
        print("Confirmed.")
    else:
        print("Allowance Good.")

if __name__ == "__main__":
    check_and_approve()
