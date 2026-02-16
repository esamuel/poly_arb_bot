import os
import sys
import json
from web3 import Web3
from dotenv import load_dotenv

# Load Env
load_dotenv()

PRIVATE_KEY = os.getenv("PRIVATE_KEY")
RPC_URL = "https://polygon-bor.publicnode.com"

# Addresses (Polygon)
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174" # Bridged
USDC_NATIVE_ADDRESS = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359" # Native
CTF_EXCHANGE_ADDRESS = "0x4bFb41d5B3570DeFd21C390604A6896f5b652F93" 

# Minimal ERC20 ABI
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}, {"name": "_spender", "type": "address"}],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
]

def main():
    print("--- Polymarket Helper: Check & Fix Allowance ---")
    
    if not PRIVATE_KEY:
        print("❌ Error: PRIVATE_KEY not found in .env")
        return

    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    if not w3.is_connected():
        print("❌ Error: Could not connect to Polygon RPC")
        return

    # Derive Account
    account = w3.eth.account.from_key(PRIVATE_KEY)
    my_address = account.address
    exchange_address = Web3.to_checksum_address(CTF_EXCHANGE_ADDRESS)
    print(f"🔑 Wallet Address: {my_address}")
    print(f"🏛️  Exchange Address: {exchange_address}")
    
    # 1. Check MATIC (Gas)
    matic_balance = w3.eth.get_balance(my_address)
    matic = w3.from_wei(matic_balance, 'ether')
    print(f"⛽ MATIC Balance: {matic:.4f}")
    
    # 2. Check Bridged USDC Balance
    usdc_contract = w3.eth.contract(address=USDC_ADDRESS, abi=ERC20_ABI)
    usdc_balance_wei = usdc_contract.functions.balanceOf(my_address).call()
    usdc_balance = usdc_balance_wei / 10**6
    print(f"💰 Bridged USDC Balance: ${usdc_balance:.2f} (0x2791...)")

    # 3. Check Native USDC Balance
    usdc_native_contract = w3.eth.contract(address=USDC_NATIVE_ADDRESS, abi=ERC20_ABI)
    usdc_native_wei = usdc_native_contract.functions.balanceOf(my_address).call()
    usdc_native = usdc_native_wei / 10**6
    print(f"💰 Native USDC Balance:  ${usdc_native:.2f} (0x3c49...)")
    
    total_usdc = usdc_balance + usdc_native
    if total_usdc < 5.0:
        print("⚠️  Warning: Low USDC (Bridged+Native) balance. You need ~15 USDC to trade.")

    # 4. Check Allowance (for Bridged - Usually standard)
    allowance_wei = usdc_contract.functions.allowance(my_address, exchange_address).call()
    allowance = allowance_wei / 10**6
    print(f"🔓 Exchange Allowance (Bridged): ${allowance:.2f}")
    
    # Check Allowance for Native too
    allowance_native_wei = usdc_native_contract.functions.allowance(my_address, exchange_address).call()
    allowance_native = allowance_native_wei / 10**6
    print(f"🔓 Exchange Allowance (Native):  ${allowance_native:.2f}")

    # Approve Logic (Handles Both if needed)
    target_contract = None
    if usdc_balance >= 5.0 and allowance < 1000.0:
        target_contract = usdc_contract
        print("Found Bridged USDC. Approving...")
    elif usdc_native >= 5.0 and allowance_native < 1000.0:
        target_contract = usdc_native_contract
        print("Found Native USDC. Approving...")
    
    if target_contract:
        print(f"🔄 Approving Exchange to spend USDC...")
        max_amount = 2**256 - 1
        tx = target_contract.functions.approve(exchange_address, max_amount).build_transaction({
            'from': my_address,
            'nonce': w3.eth.get_transaction_count(my_address),
            'gas': 100000,
            'gasPrice': w3.eth.gas_price
        })
        signed_tx = w3.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        print(f"✅ Approve Transaction Sent! Hash: {tx_hash.hex()}")
        # w3.eth.wait_for_transaction_receipt(tx_hash) # Skip waiting to avoid RPC timeout
        print("✅ Please wait 10s for confirmation.")
    else:
        print("✅ Allowance is sufficient (or balance is 0). You are ready.")

if __name__ == "__main__":
    main()
