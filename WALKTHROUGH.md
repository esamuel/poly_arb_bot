# Polymarket Arbitrage Bot - Walkthrough

This guide outlines the steps to configure and run the Polymarket Arbitrage Bot ("ArbBot").

## 1. Prerequisites
- Python 3.10+
- A Polymarket account connected via MetaMask (Polygon Network)
- MATIC in your wallet for gas fees (needed to initialize/sign)
- `pip` installed

## 2. Setup & Installation

### Install Dependencies
Run the following command in your terminal:
```bash
pip install -r requirements.txt
```

## 3. Configuration (API Keys)

To allow the bot to trade, you must generate API keys using your wallet's Private Key. The bot uses these keys to authenticate with the Polymarket CLOB (Central Limit Order Book).

### Generate Keys
1.  Locate your **Polygon Wallet Private Key** (from MetaMask: Account Details -> Show Private Key).
2.  Run the generation script:
    ```bash
    python scripts/generate_api_keys.py
    ```
3.  Enter your Private Key when prompted.
4.  The script will output:
    - `POLYMARKET_API_KEY`
    - `POLYMARKET_API_SECRET`
    - `POLYMARKET_PASSPHRASE`

### Update .env
1.  Open the `.env` file in the root directory.
2.  Paste the generated values into the corresponding fields.
3.  Ensure `EXECUTION_MODE` is set to `PAPER` for initial testing.

## 4. Run the Bot (Paper Mode)

To verify everything is working without risking real funds:
1.  Ensure `EXECUTION_MODE=PAPER` in `.env`.
2.  Run the bot:
    ```bash
    python main.py
    ```
3.  The bot will simulate a trade scenario (mock data) or connect to the WebSocket and log potential opportunities without executing real orders.

## 5. Live Trading (Caution!)

Once confident:
1.  Change `EXECUTION_MODE=LIVE` in `.env`.
2.  Ensure your wallet has sufficient USDC (Polymarket collateral) and MATIC (gas).
3.  Restart the bot.
