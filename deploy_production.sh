#!/usr/bin/env bash
###############################################################################
# Production deploy script (Domain + HTTPS) for Poly Arb Bot
#
# Usage:
#   1) Copy project to server (example): /opt/poly_arb_bot
#   2) In .env set:
#        DOMAIN=bot.yourdomain.com
#        TLS_EMAIL=you@yourdomain.com
#   3) Run: bash deploy_production.sh
###############################################################################

set -euo pipefail

# Use directory of this script, or /opt/poly_arb_bot if run directly
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$SCRIPT_DIR}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run as root (or with sudo)."
  exit 1
fi

echo "==============================================="
echo " Poly Arb Bot - Production HTTPS Deployment"
echo "==============================================="

echo "[1/6] Updating system packages..."
apt-get update -y
apt-get upgrade -y

echo "[2/6] Installing Docker..."
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
  systemctl enable docker
  systemctl start docker
else
  echo "Docker already installed."
fi

echo "[3/6] Installing Docker Compose plugin..."
if ! docker compose version >/dev/null 2>&1; then
  apt-get install -y docker-compose-plugin
else
  echo "Docker Compose plugin already installed."
fi

echo "[4/6] Validating project files..."
if [[ ! -d "${PROJECT_DIR}" ]]; then
  echo "Missing ${PROJECT_DIR}. Copy project files first."
  exit 1
fi
if [[ ! -f "${PROJECT_DIR}/docker-compose.prod.yml" ]]; then
  echo "Missing docker-compose.prod.yml in ${PROJECT_DIR}."
  exit 1
fi
if [[ ! -f "${PROJECT_DIR}/.env" ]]; then
  echo "Missing .env in ${PROJECT_DIR}."
  exit 1
fi

set +u
source "${PROJECT_DIR}/.env"
set -u

if [[ -z "${DOMAIN:-}" ]]; then
  echo "DOMAIN is missing in .env (example: DOMAIN=bot.yourdomain.com)."
  exit 1
fi
if [[ -z "${TLS_EMAIL:-}" ]]; then
  echo "TLS_EMAIL is missing in .env (example: TLS_EMAIL=you@yourdomain.com)."
  exit 1
fi

echo "[5/6] Configuring firewall for production (22, 80, 443)..."
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "[6/6] Starting production stack..."
cd "${PROJECT_DIR}"
docker compose -f docker-compose.prod.yml up -d --build

echo ""
echo "==============================================="
echo " Deployment complete"
echo "==============================================="
echo " Dashboard URL: https://${DOMAIN}"
echo ""
echo "If HTTPS does not come up within 2-3 minutes:"
echo "  - Ensure DNS A record points DOMAIN to this server IP"
echo "  - Keep ports 80/443 open in cloud firewall"
echo "  - Check logs: docker compose -f docker-compose.prod.yml logs -f caddy"
