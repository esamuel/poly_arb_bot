import requests
import json

def check_token(token_id):
    url = f"https://gamma-api.polymarket.com/markets?clob_token_id={token_id}"
    resp = requests.get(url)
    data = resp.json()
    if data:
        m = data[0]
        question = m.get('question')
        collateral = m.get('collateralToken')
        print(f"Token: {token_id}")
        print(f"Question: {question}")
        print(f"Collateral: {collateral}")
        
        if collateral == "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359":
            print("🚨 Market requires NATIVE USDC (0x3c49...)")
        elif collateral == "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174":
            print("✅ Market requires BRIDGED USDC (0x2791...)")
        else:
            print("Unknown Collateral Token.")
    else:
        print(f"Token {token_id} not found.")

if __name__ == "__main__":
    # Check the two tokens from the failed trades
    tokens = [
        "30442780799048074404860985387051749017905070253466005720364298335239299761065",
        "13244681086321087932946246027856416106585284024824496763706748621681543444582"
    ]
    for tid in tokens:
        check_token(tid)
