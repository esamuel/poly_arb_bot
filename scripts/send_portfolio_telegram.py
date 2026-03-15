#!/usr/bin/env python3
import os
import sys
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv


def _bootstrap_paths() -> Path:
    """
    Ensure imports work whether script is run from repo root, parent, or cron.
    """
    repo_root = Path(__file__).resolve().parents[1]
    parent_dir = repo_root.parent
    for p in (str(parent_dir), str(repo_root)):
        if p not in sys.path:
            sys.path.insert(0, p)
    return repo_root


REPO_ROOT = _bootstrap_paths()
load_dotenv(REPO_ROOT / ".env")

from poly_arb_bot.adapters.polymarket import PolymarketAdapter  # noqa: E402


def build_message(summary: dict) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cash = float(summary.get("cash_balance", 0.0) or 0.0)
    portfolio_value = float(summary.get("portfolio_value", 0.0) or 0.0)
    positions_value = float(summary.get("total_current_value", 0.0) or 0.0)
    invested = float(summary.get("total_invested", 0.0) or 0.0)
    unrealized = float(summary.get("total_unrealized_pnl", 0.0) or 0.0)
    realized = float(summary.get("total_realized_pnl", 0.0) or 0.0)
    num_positions = int(summary.get("num_positions", 0) or 0)
    positions = summary.get("positions", []) or []

    lines = [
        f"<b>Polymarket Portfolio Update</b>",
        f"<i>{now}</i>",
        "",
        f"Cash balance: <b>${cash:.2f}</b>",
        f"Portfolio value: <b>${portfolio_value:.2f}</b>",
        f"Open positions value: ${positions_value:.2f}",
        f"Total invested: ${invested:.2f}",
        f"Unrealized PnL: ${unrealized:.4f}",
        f"Realized PnL: ${realized:.4f}",
        f"Positions count: {num_positions}",
    ]

    if positions:
        lines.append("")
        lines.append("<b>Top positions</b>")
        for p in positions[:5]:
            title = (p.get("title") or "Unknown")[:60]
            outcome = p.get("outcome") or "?"
            current_value = float(p.get("current_value", 0.0) or 0.0)
            pnl = float(p.get("cash_pnl", 0.0) or 0.0)
            lines.append(f"- {title} | {outcome} | ${current_value:.2f} | pnl ${pnl:.4f}")

    return "\n".join(lines)


def send_telegram(message: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID in .env")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    resp = requests.post(url, json=payload, timeout=15)
    resp.raise_for_status()


def main() -> int:
    adapter = PolymarketAdapter()
    summary = adapter.get_portfolio_summary()
    message = build_message(summary)
    print(message.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", ""))
    send_telegram(message)
    print("\nTelegram: sent successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

