import os
from dotenv import load_dotenv

load_dotenv()

# API Keys
POLYMARKET_API_KEY = os.getenv("POLYMARKET_API_KEY")
POLYMARKET_API_SECRET = os.getenv("POLYMARKET_API_SECRET")
POLYMARKET_PASSPHRASE = os.getenv("POLYMARKET_PASSPHRASE")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PROXY_ADDRESS = os.getenv("PROXY_ADDRESS")

# API Endpoints
POLYMARKET_CLOB_API_URL = "https://clob.polymarket.com"
POLYMARKET_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

# Bot Configuration
EXECUTION_MODE = os.getenv("EXECUTION_MODE", "PAPER")  # PAPER or LIVE
MIN_PROFIT_THRESHOLD = float(os.getenv("MIN_PROFIT_THRESHOLD", "0.05"))  # $0.05
MAX_POSITION_SIZE = float(os.getenv("MAX_POSITION_SIZE", "100.0"))  # $100 per leg
MAX_DAYS_TO_RESOLUTION = int(os.getenv("MAX_DAYS_TO_RESOLUTION", "120"))  # Prefer near-term markets

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Telegram Notifications
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Validate critical config on import
def validate_config():
    """Log warnings for missing config at startup."""
    import logging
    _logger = logging.getLogger("config")
    
    if not PRIVATE_KEY:
        _logger.warning("PRIVATE_KEY not set. Live trading will be disabled.")
    if not POLYMARKET_API_KEY:
        _logger.warning("POLYMARKET_API_KEY not set. Order execution will fail.")
    if not OPENAI_API_KEY:
        _logger.warning("OPENAI_API_KEY not set. LLM dependency detection disabled.")
    if EXECUTION_MODE not in ("PAPER", "LIVE"):
        _logger.error(f"Invalid EXECUTION_MODE: '{EXECUTION_MODE}'. Must be PAPER or LIVE.")

validate_config()
