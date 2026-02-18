#!/usr/bin/env python3
"""Transfer USDC from EOA wallet to Proxy wallet address"""
import os
import sys
from web3 import Web3
from eth_account import Account

# Add project to path
sys.path.insert(0, '/app/poly_arb_bot')
from poly_arb_bot.config import PRIVATE_KEY, PROXY_ADDRESS

def main():
    # Connect to Polygon
    w3 = Web3(Web3.HTTPProvider("https://polygon-rpc.com"))
    
    if not w3.is_connected():
        print("Failed to connect to Polygon RPC")
        return
    
    eoa_account = Account.from_key(PRIVATE_KEY)
    print(f"EOA Address: {eoa_account.address}")
    print(f"Proxy Address: {PROXY_ADDRESS}")
    
    # USDC contract on Polygon (bridged USDC)
    usdc_address = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    usdc_abi = [
        {
            "constant": False,
            "inputs": [
                {"name": "_to", "type": "address"},
                {"name": "_value", "type": "uint256"}
            ],
            "name": "transfer",
            "outputs": [{"name": "", "type": "bool"}],
            "type": "function"
        },
        {
            "constant": True,
            "inputs": [{"name": "_owner", "type": "address"}],
            "name": "balanceOf",
            "outputs": [{"name": "balance", "type": "uint256"}],
            "type": "function"
        }
    ]
    
    usdc = w3.eth.contract(address=usdc_address, abi=usdc_abi)
    
    # Check balances
    eoa_balance = usdc.functions.balanceOf(eoa_account.address).call()
    proxy_balance = usdc.functions.balanceOf(PROXY_ADDRESS).call()
    
    print(f"\nCurrent Balances:")
    print(f"  EOA: ${eoa_balance / 1e6:.6f} USDC")
    print(f"  Proxy: ${proxy_balance / 1e6:.6f} USDC")
    
    if eoa_balance == 0:
        print("\nNo USDC to transfer from EOA wallet")
        return
    
    # Build transfer transaction
    print(f"\nTransferring ${eoa_balance / 1e6:.6f} USDC from EOA to Proxy...")
    
    try:
        # Get current gas price and nonce
        gas_price = w3.eth.gas_price
        nonce = w3.eth.get_transaction_count(eoa_account.address, 'pending')
        
        print(f"Gas price: {gas_price / 1e9:.2f} Gwei")
        print(f"Nonce: {nonce}")
        
        # Build transaction
        transfer_tx = usdc.functions.transfer(
            PROXY_ADDRESS,
            eoa_balance
        ).build_transaction({
            'from': eoa_account.address,
            'gas': 100000,
            'gasPrice': gas_price,
            'nonce': nonce,
            'chainId': 137
        })
        
        # Sign transaction
        signed_tx = w3.eth.account.sign_transaction(transfer_tx, PRIVATE_KEY)
        
        # Send transaction
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        print(f"\nTransaction sent: {tx_hash.hex()}")
        print("Waiting for confirmation...")
        
        # Wait for receipt (timeout 2 minutes)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        
        if receipt['status'] == 1:
            print(f"✅ Transaction successful!")
            print(f"   Block: {receipt['blockNumber']}")
            print(f"   Gas used: {receipt['gasUsed']}")
            
            # Check new balances
            new_eoa_balance = usdc.functions.balanceOf(eoa_account.address).call()
            new_proxy_balance = usdc.functions.balanceOf(PROXY_ADDRESS).call()
            
            print(f"\nNew Balances:")
            print(f"  EOA: ${new_eoa_balance / 1e6:.6f} USDC")
            print(f"  Proxy: ${new_proxy_balance / 1e6:.6f} USDC")
        else:
            print(f"❌ Transaction failed!")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
