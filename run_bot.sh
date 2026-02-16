#!/bin/bash
# Polymarket Arbitrage Bot - Runner
cd "$(dirname "$0")/.."
/opt/anaconda3/bin/python -m poly_arb_bot.main
