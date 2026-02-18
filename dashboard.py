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

# --- Basic Auth ---
DASH_USER = os.getenv("DASHBOARD_USER", "admin")
DASH_PASS = os.getenv("DASHBOARD_PASS", "polyarb2026")

def check_auth(username, password):
    return username == DASH_USER and password == DASH_PASS

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
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
    logger.info(f"Starting dashboard on port {port}")
    logger.info(f"Login: {DASH_USER} / {'*' * len(DASH_PASS)}")
    app.run(host="0.0.0.0", port=port, debug=False)
