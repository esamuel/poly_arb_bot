from web3 import Web3
import os
import time
from dotenv import load_dotenv

load_dotenv()

PRIVATE_KEY = os.getenv("PRIVATE_KEY")
RPC_URL = "https://polygon-bor.publicnode.com"

# Token Addresses
NATIVE_USDC = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
BRIDGED_USDC = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

# Uniswap V3 Router (SwapRouter02)
ROUTER_ADDRESS = "0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45"

# ERC20 ABI (Minimal)
ERC20_ABI = [
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
    {"constant": False, "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"}
]

# Router ABI (ExactInputSingle)
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

def swap():
    print("--- Swapping Native USDC to Bridged USDC ---")
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    account = w3.eth.account.from_key(PRIVATE_KEY)
    my_address = account.address
    print(f"Address: {my_address}")

    # 1. Check Balance
    native_contract = w3.eth.contract(address=NATIVE_USDC, abi=ERC20_ABI)
    balance_wei = native_contract.functions.balanceOf(my_address).call()
    balance = balance_wei / 10**6
    print(f"Native USDC Balance: {balance:.2f}")

    if balance < 1.0:
        print("❌ Not enough Native USDC to swap.")
        return

    # 2. Approve Router (Skipping as already sent)
    # print("Approving Uniswap Router...")
    # approve_tx = native_contract.functions.approve(ROUTER_ADDRESS, balance_wei).build_transaction({
    #     'from': my_address,
    #     'nonce': w3.eth.get_transaction_count(my_address),
    #     'gas': 100000,
    #     'gasPrice': w3.eth.gas_price
    # })
    # signed_approve = w3.eth.account.sign_transaction(approve_tx, PRIVATE_KEY)
    # tx_hash = w3.eth.send_raw_transaction(signed_approve.raw_transaction)
    # print(f"Approve Tx: {tx_hash.hex()}")
    # time.sleep(5) # Wait for confirmation

    # 3. Swap
    print("Swapping...")
    router_contract = w3.eth.contract(address=ROUTER_ADDRESS, abi=ROUTER_ABI)
    
    # Pool Fee: 0.05% (500) usually for stable pairs
    params = (
        NATIVE_USDC,
        BRIDGED_USDC,
        500, # Fee tier
        my_address,
        balance_wei,
        0, # Min Amount Out (Slippage unused for simplicity in script, use high tolerance)
        0
    )
    
    swap_tx = router_contract.functions.exactInputSingle(params).build_transaction({
        'from': my_address,
        'nonce': w3.eth.get_transaction_count(my_address),
        'gas': 300000,
        'gasPrice': w3.eth.gas_price
    })
    
    signed_swap = w3.eth.account.sign_transaction(swap_tx, PRIVATE_KEY)
    swap_hash = w3.eth.send_raw_transaction(signed_swap.raw_transaction)
    print(f"✅ Swap Transaction Sent! Hash: {swap_hash.hex()}")
    print("Once confirmed, run the bot!")

if __name__ == "__main__":
    swap()
