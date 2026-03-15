
import os
import time
from web3 import Web3
from dotenv import load_dotenv
from security_guard import enforce_fund_movement_guard

load_dotenv()

EOA = "0xBF42b359EE1aA090342e75D60052177118b0f777"
USDC_NATIVE = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
EXCHANGE_NEG = "0xC5d563A36AE78145C45a50134d48A1215220f80a" 

# Standard ERC20 Approve ABI
ABI = [{"constant":False,"inputs":[{"name":"_spender","type":"address"},{"name":"_value","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"payable":False,"stateMutability":"nonpayable","type":"function"}]

w3 = Web3(Web3.HTTPProvider("https://polygon-bor.publicnode.com"))
pkey = os.getenv("PRIVATE_KEY")

def approve():
    enforce_fund_movement_guard("Approve NegRisk exchange allowance")
    print(f"Approving Exchange {EXCHANGE_NEG} for Native USDC...")
    
    contract = w3.eth.contract(address=Web3.to_checksum_address(USDC_NATIVE), abi=ABI)
    
    # Build Tx
    nonce = w3.eth.get_transaction_count(EOA)
    tx = contract.functions.approve(
        Web3.to_checksum_address(EXCHANGE_NEG),
        2**256 - 1 # Max Uint
    ).build_transaction({
        'chainId': 137,
        'gas': 100000,
        'maxFeePerGas': w3.to_wei('50', 'gwei'),
        'maxPriorityFeePerGas': w3.to_wei('30', 'gwei'),
        'nonce': nonce,
    })
    
    # Sign
    signed_tx = w3.eth.account.sign_transaction(tx, private_key=pkey)
    
    # Send
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    print(f"Transaction Sent! Hash: {tx_hash.hex()}")
    
    # Wait
    print("Waiting for confirmation...")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    print(f"Confirmed! Status: {receipt['status']}")

if __name__ == "__main__":
    approve()
