
import os
import requests
from web3 import Web3

# Constants
USDC_BRIDGED = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
USDC_NATIVE = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
CTF = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"

def get_collection_id(parent_collection_id, condition_id, index_set):
    return Web3.solidity_keccak(
        ['bytes32', 'bytes32', 'uint256'],
        [parent_collection_id, condition_id, index_set]
    )

def get_position_id(collateral_token, collection_id):
    return Web3.solidity_keccak(
        ['address', 'bytes32'],
        [collateral_token, collection_id]
    )

def check_all():
    print("Fetching active markets...")
    url = "https://gamma-api.polymarket.com/markets?limit=5&active=true&closed=false"
    resp = requests.get(url).json()
    
    parent_collection_id = bytes([0]*32)
    
    for m in resp:
        print(f"\n--- Market: {m.get('question')} ---")
        condition_id_hex = m.get('conditionId')
        # Gamma API returns token IDs in clobTokenIds
        # format: ["id_yes", "id_no"]
        clob_ids = json.loads(m.get("clobTokenIds")) if isinstance(m.get("clobTokenIds"), str) else m.get("clobTokenIds")
        
        target_id_yes = int(clob_ids[0])
        print(f"Target ID (Yes): {hex(target_id_yes)}")
        
        condition_id = bytes.fromhex(condition_id_hex[2:])
        
        # Calculate Yes (IndexSet 1)
        col_id = get_collection_id(parent_collection_id, condition_id, 1)
        
        # 1. Bridged
        calc_bridged = int(get_position_id(USDC_BRIDGED, col_id).hex(), 16)
        if calc_bridged == target_id_yes:
            print("✅ MATCH: BRIDGED USDC")
            continue
            
        # 2. Native
        calc_native = int(get_position_id(USDC_NATIVE, col_id).hex(), 16)
        if calc_native == target_id_yes:
            print("✅ MATCH: NATIVE USDC")
            continue
            
        print("❌ NO MATCH (Complex Market?)")

import json
if __name__ == "__main__":
    check_all()
