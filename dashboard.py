"""
Web Dashboard for the Polymarket Arbitrage Bot.
Provides real-time monitoring, controls, and configuration.
"""
import os
import sys
import logging
from functools import wraps
from flask import Flask, render_template, jsonify, request, Response

# Ensure project root is in path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from poly_arb_bot.bot_controller import BotController
from poly_arb_bot.adapters.polymarket import PolymarketAdapter

# Setup logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Flask App ---
app = Flask(__name__, template_folder=os.path.join(current_dir, "templates"))
app.secret_key = os.getenv("FLASK_SECRET", "poly-arb-bot-secret-change-me")

# Singleton bot controller
bot = BotController()

# Shared adapter for portfolio queries (reuses the same keys/proxy config)
_portfolio_adapter = None

def _get_portfolio_adapter():
    global _portfolio_adapter
    if _portfolio_adapter is None:
        _portfolio_adapter = PolymarketAdapter()
    return _portfolio_adapter

# --- Basic Auth ---
DASH_USER = os.getenv("DASHBOARD_USER", "admin")
DASH_PASS = os.getenv("DASHBOARD_PASS", "polyarb2026")
# Set DASHBOARD_AUTH_DISABLED=1 for local dev (skips login prompt)
AUTH_DISABLED = os.getenv("DASHBOARD_AUTH_DISABLED", "0").strip().lower() in ("1", "true", "yes")
ALLOW_INSECURE_DASHBOARD = os.getenv("DASHBOARD_ALLOW_INSECURE_DEFAULTS", "0").strip().lower() in ("1", "true", "yes")


def validate_dashboard_security():
    insecure_default_creds = (DASH_USER == "admin" and DASH_PASS == "polyarb2026")
    if insecure_default_creds and not ALLOW_INSECURE_DASHBOARD:
        raise RuntimeError(
            "Refusing to start dashboard with default credentials. "
            "Set DASHBOARD_USER and DASHBOARD_PASS in .env "
            "(or set DASHBOARD_ALLOW_INSECURE_DEFAULTS=1 to bypass)."
        )
    if AUTH_DISABLED and not ALLOW_INSECURE_DASHBOARD:
        raise RuntimeError(
            "Refusing to start dashboard with DASHBOARD_AUTH_DISABLED=1. "
            "Set DASHBOARD_AUTH_DISABLED=0 "
            "(or set DASHBOARD_ALLOW_INSECURE_DEFAULTS=1 to bypass)."
        )


validate_dashboard_security()

def check_auth(username, password):
    return username == DASH_USER and password == DASH_PASS

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if AUTH_DISABLED:
            return f(*args, **kwargs)
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return Response(
                'Login required.\n', 401,
                {'WWW-Authenticate': 'Basic realm="Poly Arb Bot"'}
            )
        return f(*args, **kwargs)
    return decorated

# --- Routes ---

@app.route("/")
@requires_auth
def index():
    return render_template("dashboard.html")

@app.route("/api/state")
@requires_auth
def api_state():
    return jsonify(bot.get_state())

@app.route("/api/start", methods=["POST"])
@requires_auth
def api_start():
    result = bot.start()
    return jsonify(result)

@app.route("/api/stop", methods=["POST"])
@requires_auth
def api_stop():
    result = bot.stop()
    return jsonify(result)

@app.route("/api/settings", methods=["POST"])
@requires_auth
def api_settings():
    data = request.get_json() or {}
    result = bot.update_settings(data)
    return jsonify(result)

@app.route("/api/positions")
@requires_auth
def api_positions():
    return jsonify(bot.get_positions())

@app.route("/api/portfolio")
@requires_auth
def api_portfolio():
    """Live portfolio data fetched directly from Polymarket (same as polymarket.com)."""
    try:
        adapter = _get_portfolio_adapter()
        return jsonify(adapter.get_portfolio_summary())
    except Exception as e:
        logger.error(f"Portfolio fetch error: {e}", exc_info=True)
        return jsonify({"error": str(e), "positions": [], "cash_balance": 0}), 500

@app.route("/api/close_position", methods=["POST"])
@requires_auth
def api_close_position():
    data = request.get_json() or {}
    token_id = data.get("token_id", "")
    result = bot.close_position(token_id)
    return jsonify(result)

@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "bot": bot.state["status"],
        "role": bot.state.get("role", "primary"),
        "uptime": bot.state.get("uptime", 0),
    })


if __name__ == "__main__":
    port = int(os.getenv("DASHBOARD_PORT", "8080"))
    validate_dashboard_security()
    logger.info(f"Starting dashboard on port {port}")
    logger.info(f"Login: {DASH_USER} / {'*' * len(DASH_PASS)}")
    app.run(host="0.0.0.0", port=port, debug=False)
