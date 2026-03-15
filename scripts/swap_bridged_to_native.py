from web3 import Web3
import os
import time
from dotenv import load_dotenv
from security_guard import enforce_fund_movement_guard

load_dotenv()

PRIVATE_KEY = os.getenv("PRIVATE_KEY")
RPC_URL = "https://polygon-bor.publicnode.com"

# Token Addresses
NATIVE_USDC = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
BRIDGED_USDC = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
ROUTER_ADDRESS = "0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45" # Uniswap V3

ERC20_ABI = [
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
    {"constant": False, "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"}
]

ROUTER_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"internalType": "address", "name": "tokenIn", "type": "address"},
                    {"internalType": "address", "name": "tokenOut", "type": "address"},
                    {"internalType": "uint24", "name": "fee", "type": "uint24"},
                    {"internalType": "address", "name": "recipient", "type": "address"},
                    {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                    {"internalType": "uint256", "name": "amountOutMinimum", "type": "uint256"},
                    {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"}
                ],
                "internalType": "struct IV3SwapRouter.ExactInputSingleParams",
                "name": "params",
                "type": "tuple"
            }
        ],
        "name": "exactInputSingle",
        "outputs": [{"internalType": "uint256", "name": "amountOut", "type": "uint256"}],
        "stateMutability": "payable",
        "type": "function"
    }
]

def swap_back():
    enforce_fund_movement_guard("Swap Bridged USDC -> Native USDC")
    print("--- Swapping Bridged USDC to Native USDC ---")
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    account = w3.eth.account.from_key(PRIVATE_KEY)
    my_address = account.address
    print(f"Address: {my_address}")

    # 1. Check Bridged Balance
    bridged_contract = w3.eth.contract(address=BRIDGED_USDC, abi=ERC20_ABI)
    balance_wei = bridged_contract.functions.balanceOf(my_address).call()
    balance = balance_wei / 10**6
    print(f"Bridged USDC Balance: {balance:.2f}")

    amount_to_swap = 5.0 # Swap 5 USDC
    amount_wei = int(amount_to_swap * 10**6)

    if balance < amount_to_swap:
        print("❌ Not enough Bridged USDC.")
        return

    # 2. Approve Router (Bridged) - Already Sent
    # print("Approving Uniswap Router (Bridged)...")
    # approve_tx = bridged_contract.functions.approve(ROUTER_ADDRESS, amount_wei).build_transaction({
    #     'from': my_address,
    #     'nonce': w3.eth.get_transaction_count(my_address),
    #     'gas': 100000,
    #     'gasPrice': w3.eth.gas_price
    # })
    # signed_approve = w3.eth.account.sign_transaction(approve_tx, PRIVATE_KEY)
    # tx_hash = w3.eth.send_raw_transaction(signed_approve.raw_transaction)
    # print(f"Approve Tx: {tx_hash.hex()}")
    # time.sleep(5) 

    # 3. Swap
    print("Swapping...")
    router_contract = w3.eth.contract(address=ROUTER_ADDRESS, abi=ROUTER_ABI)
    
    params = (
        BRIDGED_USDC,
        NATIVE_USDC,
        500, # Fee tier 0.05% (Standard)
        my_address,
        amount_wei,
        0, 
        0
    )
    
    # Nonce might comprise pending txs?
    nonce = w3.eth.get_transaction_count(my_address) # default includes pending? No. 'pending'?
    
    swap_tx = router_contract.functions.exactInputSingle(params).build_transaction({
        'from': my_address,
        'nonce': nonce,
        'gas': 400000, # More gas
        'gasPrice': int(w3.eth.gas_price * 1.5) # Aggressive Gas
    })
    
    signed_swap = w3.eth.account.sign_transaction(swap_tx, PRIVATE_KEY)
    swap_hash = w3.eth.send_raw_transaction(signed_swap.raw_transaction)
    print(f"✅ Swap Transaction Sent! Hash: {swap_hash.hex()}")
    print("Swapped 5.0 Bridged -> Native.")

if __name__ == "__main__":
    swap_back()
