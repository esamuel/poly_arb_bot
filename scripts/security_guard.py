import os
import sys
from dotenv import load_dotenv


def _is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def _extract_unlock_code_from_argv() -> str | None:
    prefix = "--unlock-code="
    argv = sys.argv[1:]
    for i, arg in enumerate(argv):
        if arg.startswith(prefix):
            return arg[len(prefix):].strip()
        if arg == "--unlock-code" and i + 1 < len(argv):
            return argv[i + 1].strip()
    return None


def enforce_fund_movement_guard(action_name: str) -> None:
    """
    Block fund-moving scripts unless explicitly unlocked by env vars.

    Required:
      - ALLOW_FUND_MOVEMENTS=1

    Optional second factor:
      - FUND_MOVEMENT_UNLOCK_CODE=<secret>
      - pass via --unlock-code=<secret>
    """
    load_dotenv()

    if not _is_truthy(os.getenv("ALLOW_FUND_MOVEMENTS")):
        raise SystemExit(
            f"BLOCKED: {action_name} is disabled.\n"
            "Set ALLOW_FUND_MOVEMENTS=1 in .env to run this script."
        )

    expected_code = (os.getenv("FUND_MOVEMENT_UNLOCK_CODE") or "").strip()
    if expected_code:
        provided_code = _extract_unlock_code_from_argv() or ""
        if provided_code != expected_code:
            raise SystemExit(
                f"BLOCKED: {action_name} requires unlock code.\n"
                "Run with --unlock-code=<your code>."
            )

