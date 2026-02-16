
from web3 import Web3
from eth_abi import encode

# Constants form Gnosis Conditional Tokens
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

def verify():
    # Market Data
    # Question: Will Trump deport less than 250,000?
    question_id = "0xa69729ae3d9838ec5754e0f74bf57dedd5ddbecd9e31b15a04f48f081168ba00"
    condition_id_api = "0xaf9d0e448129a9f657f851d49495ba4742055d80e0ef1166ba0ee81d4d594214"
    
    # Token ID from API (first outcome, "Yes"?)
    # "101676997363687199724245607342877036148401850938023978421879460310389391082353"
    target_token_id_int = 101676997363687199724245607342877036148401850938023978421879460310389391082353
    target_token_id_hex = hex(target_token_id_int)
    
    # Collateral Candidates
    USDC_BRIDGED = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    USDC_NATIVE = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
    
    # Index Sets for Binary Market with 2 outcomes
    # Outcome 0 (Yes): IndexSet = 1 (binary 01)
    # Outcome 1 (No): IndexSet = 2 (binary 10)
    
    parent_collection_id = bytes([0]*32)
    condition_id = bytes.fromhex(condition_id_api[2:])
    
    print(f"Target Token ID: {target_token_id_hex}")
    
    # Check Outcome 0 (Yes)
    index_set = 1 
    collection_id = get_collection_id(parent_collection_id, condition_id, index_set)
    
    # 1. Try Bridged
    pos_id_bridged = get_position_id(USDC_BRIDGED, collection_id)
    print(f"Calc ID (Bridged, Yes): {pos_id_bridged.hex()}")
    
    if int(pos_id_bridged.hex(), 16) == target_token_id_int:
        print("MATCH FOUND: Market uses BRIDGED USDC (USDC.e) for 'Yes'")
        return

    # 2. Try Native
    pos_id_native = get_position_id(USDC_NATIVE, collection_id)
    print(f"Calc ID (Native, Yes): {pos_id_native.hex()}")

    if int(pos_id_native.hex(), 16) == target_token_id_int:
        print("MATCH FOUND: Market uses NATIVE USDC (USDC) for 'Yes'")
        return
        
    print("No match for Outcome 'Yes' (IndexSet 1). Checking 'No' (IndexSet 2)...")
    
    # Check Outcome 1 (No) just in case
    index_set = 2
    collection_id = get_collection_id(parent_collection_id, condition_id, index_set)
    
    pos_id_bridged = get_position_id(USDC_BRIDGED, collection_id)
    print(f"Calc ID (Bridged, No): {pos_id_bridged.hex()}")
    if int(pos_id_bridged.hex(), 16) == target_token_id_int:
        print("MATCH FOUND: Market uses BRIDGED USDC (USDC.e) for 'No'")
        return

    pos_id_native = get_position_id(USDC_NATIVE, collection_id)
    print(f"Calc ID (Native, No): {pos_id_native.hex()}")
    if int(pos_id_native.hex(), 16) == target_token_id_int:
        print("MATCH FOUND: Market uses NATIVE USDC (USDC) for 'No'")
        return
        
    print("NO MATCH FOUND. Calculation assumption might be wrong or Parent Collection ID is not 0 checking Split?")

if __name__ == "__main__":
    verify()
