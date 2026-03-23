#!/usr/bin/env python3
"""
4-Hour Paper-Test Telegram Report
Runs inside the polybot Docker container (via docker exec).
Queries the dashboard API at localhost:8080, formats a concise report,
and sends it to Telegram.
"""
import os
import sys
import json
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

# ── Path bootstrap ────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[1]
for p in (str(REPO_ROOT.parent), str(REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

load_dotenv(REPO_ROOT / ".env")

# ── Config ────────────────────────────────────────────────────────────────────
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "http://localhost:8080")
DASHBOARD_USER = os.getenv("DASHBOARD_USER", "admin")
DASHBOARD_PASS = os.getenv("DASHBOARD_PASS", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

PAPER_BALANCE_START = float(os.getenv("PAPER_BALANCE", "500"))
PAPER_TEST_START = os.getenv("PAPER_TEST_START", "2026-03-15")


# ── Helpers ───────────────────────────────────────────────────────────────────
def _get(path: str) -> dict:
    url = f"{DASHBOARD_URL}{path}"
    auth = (DASHBOARD_USER, DASHBOARD_PASS) if DASHBOARD_PASS else None
    resp = requests.get(url, auth=auth, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _elapsed_days() -> float:
    try:
        start = datetime.strptime(PAPER_TEST_START, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return (now - start).total_seconds() / 86400
    except Exception:
        return 0.0


def _pnl_arrow(v: float) -> str:
    return "📈" if v > 0 else ("📉" if v < 0 else "➡️")


def _sign(v: float) -> str:
    return f"+${v:.2f}" if v >= 0 else f"-${abs(v):.2f}"


# ── Report builder ────────────────────────────────────────────────────────────
def build_report(state: dict, positions: list) -> str:
    now_str = datetime.now(timezone.utc).strftime("%a %d %b %Y  %H:%M UTC")
    elapsed = _elapsed_days()

    mode = state.get("mode", "PAPER").upper()
    bot_status = state.get("status", "?").upper()
    wallet = float(state.get("wallet_balance") or PAPER_BALANCE_START)
    realized = float(state.get("realized_pnl") or 0.0)
    unrealized = float(state.get("unrealized_pnl_estimate") or 0.0)
    total_pnl = realized + unrealized
    trades = int(state.get("trades_executed") or 0)
    opps_found = int(state.get("opportunities_found") or 0)
    pairs = int(state.get("pairs_monitored") or 0)
    if pairs == 0:
        pairs = len(state.get("sessions") or [])

    # ROI vs starting $500
    roi_pct = (total_pnl / PAPER_BALANCE_START) * 100 if PAPER_BALANCE_START else 0.0

    lines = [
        f"<b>🤖 PolyArb Paper-Test Report</b>",
        f"<i>{now_str}</i>",
        f"<i>Day {elapsed:.1f} / 14  |  Mode: {mode}  |  Status: {bot_status}</i>",
        "",
        "─── 💰 BALANCE ───",
        f"Paper Balance:  <b>${wallet:.2f}</b>   (start: ${PAPER_BALANCE_START:.0f})",
        f"Realized PnL:   {_pnl_arrow(realized)} <b>{_sign(realized)}</b>",
        f"Unrealized PnL: {_pnl_arrow(unrealized)} {_sign(unrealized)}",
        f"Total PnL:      {_pnl_arrow(total_pnl)} <b>{_sign(total_pnl)}</b>  ({roi_pct:+.2f}%)",
        "",
        "─── 📊 ACTIVITY ───",
        f"Trades executed:  {trades}",
        f"Opportunities:    {opps_found}",
        f"Pairs monitored:  {pairs}",
    ]

    # Recent trades from state (each row is one CLOB order leg, not a closed round-trip)
    recent_trades = state.get("recent_trades") or []
    if recent_trades:
        lines.append("")
        lines.append("─── 🔄 RECENT ORDER LEGS ───")
        lines.append(
            "<i>(Last legs logged — token id suffix; notional + limit price. "
            "Per-leg P&amp;L is not stored; use Realized/Unrealized above.)</i>"
        )
        for i, t in enumerate(recent_trades[-8:], 1):
            # bot_controller stores: time, side, price, size, token (not token_id)
            tok = str(
                t.get("token")
                or t.get("token_id")
                or t.get("market")
                or "?"
            )
            side = str(t.get("side") or "?").upper()
            price = float(t.get("price") or t.get("fill_price") or 0.0)
            size = float(t.get("size") or 0.0)
            clock = str(t.get("time") or "")
            prefix = f"{i}. [{clock}] " if clock else f"{i}. "
            lines.append(
                f"{prefix}{side} {tok}  ${size:.2f} @ {price:.4f}"
            )

    # Open positions
    if positions:
        lines.append("")
        lines.append(f"─── 📂 OPEN POSITIONS ({len(positions)}) ───")
        for pos in positions[:10]:
            tid_short = pos.get("token_short") or f"...{str(pos.get('token_id','?'))[-8:]}"
            shares = float(pos.get("shares") or 0)
            avg_e = float(pos.get("avg_entry") or 0)
            mid = float(pos.get("last_mid") or 0)
            upnl = float(pos.get("unrealized_pnl") or 0)
            lines.append(
                f"• {tid_short}  {shares:.1f}sh @ {avg_e:.3f}→{mid:.3f}  {_pnl_arrow(upnl)}{_sign(upnl)}"
            )
        if len(positions) > 10:
            lines.append(f"  ... +{len(positions)-10} more")
    else:
        lines.append("")
        lines.append("📂 No open positions.")

    lines.append("")
    lines.append("─────────────────────────────")
    lines.append(f"<i>Next report in 4h  •  app.orbitarb.com</i>")

    return "\n".join(lines)


# ── Telegram sender ───────────────────────────────────────────────────────────
def send_telegram(message: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
        timeout=20,
    )
    resp.raise_for_status()


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> int:
    try:
        state = _get("/api/state")
    except Exception as e:
        print(f"[paper_test_report] ERROR fetching /api/state: {e}", file=sys.stderr)
        state = {}

    try:
        positions = _get("/api/positions")
        if not isinstance(positions, list):
            positions = []
    except Exception as e:
        print(f"[paper_test_report] WARNING fetching /api/positions: {e}", file=sys.stderr)
        positions = []

    report = build_report(state, positions)
    send_telegram(report)
    print("Paper-test report sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
