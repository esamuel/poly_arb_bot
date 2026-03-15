# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python 3.12 arbitrage bot for [Polymarket](https://polymarket.com) prediction markets. Detects logically-dependent binary-outcome market pairs, computes fair prices via Bregman divergence / Frank–Wolfe projection, and places limit orders when mispricing exceeds the fee floor.

**Stack:** Python 3.12, Flask, Docker, `py-clob-client` (Polymarket CLOB SDK), OpenAI GPT-4o-mini

---

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run tests (only engine/math is covered)
pytest tests/

# Run a single test
pytest tests/test_math.py::TestMarketMath::test_frank_wolfe_simple_arbitrage

# Start dashboard (Paper mode — set EXECUTION_MODE=PAPER in .env first)
python dashboard.py       # Web UI at http://localhost:8080

# Start CLI mode (legacy)
python main.py

# Docker (local dev)
docker compose up -d --build
docker logs poly_arb_bot -f
docker compose down

# Docker (production with Caddy/HTTPS)
docker compose -f docker-compose.prod.yml up -d --build

# Quick operational one-liners
python -c "from adapters.polymarket import PolymarketAdapter; a = PolymarketAdapter(); print(a.get_portfolio_summary())"
python -c "from adapters.polymarket import PolymarketAdapter; a = PolymarketAdapter(); [a.cancel_order(o['id']) for o in a.get_open_orders()]"
```

There is no linting or formatter configured in this project.

**Tests:** Run `./run_tests.sh` to execute tests in Docker (avoids numpy segfault on some local Anaconda setups). If numpy imports segfault locally, use Docker or a fresh venv with `pip install numpy`.

---

## Architecture

### Entry Points
- **`dashboard.py`** — Flask web app; creates a `BotController` singleton and exposes REST endpoints (`/start`, `/stop`, `/state`, `/positions`, `/settings`). Preferred entry point.
- **`main.py`** — Legacy CLI entry; runs the bot without a dashboard.
- **`config.py`** — Loads and validates all env vars from `.env`. All configuration lives here.

### Core Classes

**`bot_controller.BotController`** (~1550 lines, the main loop)
- Singleton managing the full bot lifecycle (`state`: stopped → starting → scanning → running → stopping)
- `start()` / `stop()` run the loop in a background thread
- `_find_related_pairs()` — fetches up to 1000 markets from Gamma API, scores pairs by keyword overlap + liquidity, then calls `DependencyDetector` (up to 15 LLM calls per restart, minus cache hits) to get valid outcome vectors
- `_run()` — main loop: WS price updates every 1s, REST fallback every 2s, quick-flip exits every 10s, stale order cancel every 90s, recycler every 60min
- `_build_orders()` / `_execute_orders()` — converts Frank–Wolfe output (`mu_star`) into BUY/SELL limit orders
- `_reconcile_position_book()` — syncs internal `position_book` dict against actual exchange positions before every recycler run
- `_save_runtime_state()` / `_load_runtime_state()` — persists position book + wallet snapshot to `data/runtime_state.json`

**`bot_controller.MonitoringSession`** — tracks live price state for one market pair
- `update_price(token_id, price, bid, ask)` — called from WebSocket callbacks
- `run_analysis()` → calls `MarketMath.frank_wolfe_projection()` and returns `(profit, mu_star)`
- `can_trade()` — enforces per-pair cooldown

**`adapters.polymarket.PolymarketAdapter`** (~650 lines)
- Wraps `py-clob-client` (`ClobClient`) for order signing + CLOB API
- Uses Gamma API (`https://gamma-api.polymarket.com`) for market discovery
- Uses Polymarket Data API for portfolio positions
- WebSocket (`connect_ws()`) subscribes to real-time price feeds; auto-reconnects with exponential backoff
- SOCKS proxy support (`httpx-socks`) patches py-clob-client globally — required to bypass geographic IP blocks from cloud/VPS IPs
- Signing mode: GNOSIS Safe proxy (`signature_type=2`) via `PROXY_ADDRESS` env var

**`engine.math.MarketMath`** (pure, stateless)
- `frank_wolfe_projection(current_prices, valid_outcomes)` → `mu_star` (numpy array)
- `bregman_divergence(p, q)` → scalar profit estimate
- `estimate_dollar_profit(current_prices, mu_star, position_size, fee_rate=0.02)` → dollar P&L after fees

**`engine.dependency.DependencyDetector`**
- `analyze_market_pair(market_a, market_b)` → list of valid outcome tuples e.g. `[("YES","YES"), ("NO","NO")]`; empty list = independent markets
- Cache key = SHA256 of sorted question strings; results in `data/dep_cache/` with 7-day TTL
- Uses `gpt-4o-mini` with `temperature=0.1`, JSON mode

**`engine.execution.ExecutionEngine`**
- `execute_arbitrage(orders)` → places orders via adapter; skips in PAPER mode
- `check_safety()` — circuit breakers: `MAX_DAILY_LOSS=$10`, `MAX_DAILY_TRADES=500`
- `send_telegram_alert(message)` — sends to Telegram if `TELEGRAM_BOT_TOKEN` is set

### Data Flow

```
Gamma API → market list → pair scoring → DependencyDetector (LLM + cache)
                                              ↓
                                    MonitoringSession (valid_outcomes matrix)
                                              ↓
WebSocket price feed → update_price() → run_analysis() → frank_wolfe_projection()
                                              ↓
                                    profit > MIN_EFFECTIVE_EDGE (3.5%)
                                              ↓
                                    ExecutionEngine.execute_arbitrage()
                                              ↓
                                    position_book → recycler / quick-flip exits
```

### Key Configuration Constants (hardcoded in `bot_controller.py`)
- `MIN_EFFECTIVE_EDGE = 0.035` — 3.5% floor; overrides `MIN_PROFIT_THRESHOLD` from env
- `FEE_RATE = 0.01`, `SLIPPAGE_BUFFER = 0.005` — baked into profit estimates
- `TAKE_PROFIT_PCT = 0.03`, `STOP_LOSS_PCT = 0.08` — quick-flip thresholds
- `STALE_ORDER_TIMEOUT = 90` seconds

---

## Environment Variables

Required in `.env`:

| Variable | Purpose |
|----------|---------|
| `PRIVATE_KEY` | Ethereum wallet private key |
| `POLYMARKET_API_KEY/SECRET/PASSPHRASE` | CLOB API auth |
| `OPENAI_API_KEY` | LLM dependency detection |
| `PROXY_ADDRESS` | Polymarket GNOSIS Safe proxy address |
| `EXECUTION_MODE` | `PAPER` (safe) or `LIVE` (real money) |

Optional: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `SOCKS_PROXY_URL`

---

## Key Gotchas

- **Geographic restriction** — Polymarket blocks cloud/VPS IPs. The SOCKS proxy patches `py-clob-client` HTTP sessions globally; touch `PolymarketAdapter.__init__` carefully.
- **Never run two instances** on the same account — open orders conflict.
- **Token IDs vs Condition IDs** — Polymarket uses decimal Token IDs (e.g. `p.get("asset")`) for CLOB orders, NOT hex Condition IDs. Mixing these causes 400 errors.
- **Position book** — `position_book` in memory can drift from exchange reality. `_reconcile_position_book()` must be called before acting on the book.
- **LLM hallucination risk** — GPT may mark independent markets as dependent, creating false arbitrage signals. Tune prompts in `engine/dependency.py` carefully.
- **`EXECUTION_MODE`** must be `PAPER` for safe local testing; `LIVE` spends real USDC on Polygon.
