from web3 import Web3

W3 = Web3(Web3.HTTPProvider("https://polygon-bor.publicnode.com"))
PROXY = Web3.to_checksum_address("0xc383AaA749043c0ba96ECf58ce23c6D1Dd203adA")

# Try various owner/signer methods
ABI = [
    {"inputs":[],"name":"owner","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"getOwner","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"signer","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"}
]

def check_owner():
    contract = W3.eth.contract(address=PROXY, abi=ABI)
    for method in ["owner", "getOwner", "signer"]:
        try:
            res = getattr(contract.functions, method)().call()
            print(f"{method}: {res}")
        except Exception as e:
            print(f"{method} error: {e}")

if __name__ == "__main__":
    check_owner()
