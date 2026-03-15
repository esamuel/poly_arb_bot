# Fund Logic Review — Poly Arb Bot

**Review date:** 2025-02-28

## Summary

Reviewed all fund-related logic in `bot_controller.py`, `engine/execution.py`, and `adapters/polymarket.py`. Fixed 3 issues and documented the fund flow.

---

## Fund Flow Overview

### 1. Balance Source
- **API:** `get_balance_allowance()` returns raw USDC (1e6 units)
- **Conversion:** `balance_usd = raw_balance / 1e6`
- **When refreshed:** Before LIVE trades, every 30 polls (~30s), and after recycler runs

### 2. Reserved Collateral
- **Source:** Open BUY orders on the CLOB
- **Formula:** `reserved = sum(price × qty)` for each non-terminal BUY order
- **SELL orders:** Do NOT reserve cash (they reserve shares)
- **Sanity cap:** Reserved is capped at 2× balance if API returns anomalous values

### 3. Available Capital
```
available = balance - reserved - min_reserve
min_reserve = max(min(equity × CASH_RESERVE_RATIO, balance × 0.40), MIN_WALLET_FLOOR)
max_per_trade = max(equity × MAX_CAPITAL_PER_TRADE_RATIO, 1.0)
cap = min(available, max_per_trade)
```

### 4. Capital Floor (MIN_WALLET_FLOOR)
- **Value:** $5 (configurable via `MIN_WALLET_FLOOR` env)
- **Rule:** `balance - total_buy_cost >= MIN_WALLET_FLOOR` before any trade
- **Scope:** LIVE mode only (PAPER mode bypasses)

### 5. Order Sizing
- **Execution engine:** Passes `size` in USD to adapter
- **Adapter:** Converts `shares = size / price` for both BUY and SELL
- **Position book:** Uses shares; `_apply_filled_order` updates shares from fill

### 6. Recycler Cash Logic
- **Phase 1 (SELL longs):** No cash required — uses shares on exchange
- **Phase 2 (BUY-back shorts):** Requires `cash >= cost_estimate + 1.0` (or $2 minimum)
- **Emergency:** When `cash < RECYCLE_MIN_CASH_RESERVE`, recycler runs more frequently (every 5 min)

---

## Fixes Applied

### 1. PAPER Mode Capital Floor (Bug)
**Issue:** Capital floor check ran for PAPER mode with `wallet_balance = 0`, blocking all paper trades.

**Fix:** Run the floor check only in LIVE mode. PAPER mode uses simulated execution and does not require real balance.

### 2. Recycler Short Buy-Back Cash Check
**Issue:** Recycler skipped short buy-back only when `cash < 2.0`, not when `cash < cost_estimate`.

**Fix:** Skip when `cash < max(cost_estimate + 1.0, 2.0)` so we don’t attempt buy-backs without enough cash.

### 3. Duplicate Line
**Issue:** `self.state["last_error"] = str(e)` was set twice in the exception handler.

**Fix:** Removed the duplicate assignment.

### 4. Reserved Estimate Sanity Cap
**Issue:** If the CLOB returns sizes in raw units, the reserve estimate could be inflated.

**Fix:** Cap reserved at 2× balance and log a warning.

---

## Circuit Breakers (Execution Engine)

- **MAX_DAILY_LOSS:** $10 — stops trading for the day
- **MAX_DAILY_TRADES:** 500 — stops trading for the day
- **Partial execution unwind:** If some legs of a multi-leg arb fail, unfilled legs are cancelled

---

## Safety Checklist

- [x] Capital floor enforced before LIVE trades
- [x] Cash reserve (CASH_RESERVE_RATIO) limits exposure
- [x] Max capital per trade (MAX_CAPITAL_PER_TRADE_RATIO)
- [x] Max live orders (MAX_LIVE_ORDERS = 12)
- [x] Stale order cancellation (60s timeout)
- [x] Daily loss/trade limits in execution engine
- [x] PAPER mode does not touch real funds
- [x] Recycler checks exchange balance before selling
- [x] Reconciliation removes phantom positions
