import os
from dotenv import load_dotenv

load_dotenv()

def _clean_env(value: str | None) -> str | None:
    """Normalize env values and strip inline comments."""
    if value is None:
        return None
    return value.split("#", 1)[0].strip()

def _get_float_env(name: str, default: str) -> float:
    raw = _clean_env(os.getenv(name, default))
    try:
        return float(raw if raw not in (None, "") else default)
    except (TypeError, ValueError):
        return float(default)

def _get_int_env(name: str, default: str) -> int:
    raw = _clean_env(os.getenv(name, default))
    try:
        return int(raw if raw not in (None, "") else default)
    except (TypeError, ValueError):
        return int(default)

# API Keys
POLYMARKET_API_KEY = _clean_env(os.getenv("POLYMARKET_API_KEY"))
POLYMARKET_API_SECRET = _clean_env(os.getenv("POLYMARKET_API_SECRET"))
POLYMARKET_PASSPHRASE = _clean_env(os.getenv("POLYMARKET_PASSPHRASE"))
PRIVATE_KEY = _clean_env(os.getenv("PRIVATE_KEY"))
OPENAI_API_KEY = _clean_env(os.getenv("OPENAI_API_KEY"))
PROXY_ADDRESS = _clean_env(os.getenv("PROXY_ADDRESS"))

# API Endpoints
POLYMARKET_CLOB_API_URL = "https://clob.polymarket.com"
POLYMARKET_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

# Bot Configuration
EXECUTION_MODE = (_clean_env(os.getenv("EXECUTION_MODE", "PAPER")) or "PAPER").upper()  # PAPER or LIVE
MIN_PROFIT_THRESHOLD = _get_float_env("MIN_PROFIT_THRESHOLD", "0.05")  # $0.05
MAX_POSITION_SIZE = _get_float_env("MAX_POSITION_SIZE", "3.0")  # $3 per leg (conservative paper mode)
MAX_DAYS_TO_RESOLUTION = _get_int_env("MAX_DAYS_TO_RESOLUTION", "14")  # Short-term markets only

# Logging
LOG_LEVEL = (_clean_env(os.getenv("LOG_LEVEL", "INFO")) or "INFO").upper()

# Telegram Notifications
TELEGRAM_BOT_TOKEN = _clean_env(os.getenv("TELEGRAM_BOT_TOKEN"))
TELEGRAM_CHAT_ID = _clean_env(os.getenv("TELEGRAM_CHAT_ID"))

# Security
ALLOW_FUND_MOVEMENTS = (_clean_env(os.getenv("ALLOW_FUND_MOVEMENTS", "0")) or "0").lower() in ("1", "true", "yes", "on")
DASHBOARD_ALLOW_INSECURE_DEFAULTS = (_clean_env(os.getenv("DASHBOARD_ALLOW_INSECURE_DEFAULTS", "0")) or "0").lower() in ("1", "true", "yes", "on")

# Validate critical config on import
def validate_config():
    """Validate config on import, fail-fast on invalid execution mode."""
    import logging
    _logger = logging.getLogger("config")
    
    if not PRIVATE_KEY:
        _logger.warning("PRIVATE_KEY not set. Live trading will be disabled.")
    if not POLYMARKET_API_KEY:
        _logger.warning("POLYMARKET_API_KEY not set. Order execution will fail.")
    if not OPENAI_API_KEY:
        _logger.warning("OPENAI_API_KEY not set. LLM dependency detection disabled.")
    if EXECUTION_MODE not in ("PAPER", "LIVE"):
        msg = f"Invalid EXECUTION_MODE: '{EXECUTION_MODE}'. Must be PAPER or LIVE."
        _logger.error(msg)
        raise ValueError(msg)
    if ALLOW_FUND_MOVEMENTS:
        _logger.warning("ALLOW_FUND_MOVEMENTS=1. Fund transfer/swap scripts are unlocked.")
    if DASHBOARD_ALLOW_INSECURE_DEFAULTS:
        _logger.warning("DASHBOARD_ALLOW_INSECURE_DEFAULTS=1. Dashboard security protections are bypassed.")

validate_config()
