#!/bin/bash
###############################################################################
# Digital Ocean Deployment Script for Poly Arb Bot
#
# USAGE:
#   1. Create a Digital Ocean Droplet (Ubuntu 24.04, $6/month basic is enough)
#   2. SSH into the droplet:  ssh root@YOUR_DROPLET_IP
#   3. Copy this script there and run it:  bash deploy.sh
#
# PREREQUISITES:
#   - A Digital Ocean Droplet with Ubuntu 22.04 or 24.04
#   - Your .env file with all API keys ready
###############################################################################

set -e

echo "================================================"
echo "  Poly Arb Bot - Digital Ocean Deployment"
echo "================================================"

# 1. Update system
echo "[1/6] Updating system..."
apt-get update && apt-get upgrade -y

# 2. Install Docker
echo "[2/6] Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
    echo "Docker installed."
else
    echo "Docker already installed."
fi

# 3. Install Docker Compose
echo "[3/6] Installing Docker Compose..."
if ! command -v docker-compose &> /dev/null; then
    apt-get install -y docker-compose-plugin
    # Also install standalone docker-compose
    curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64" \
        -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
    echo "Docker Compose installed."
else
    echo "Docker Compose already installed."
fi

# 4. Setup project directory
echo "[4/6] Setting up project..."
PROJECT_DIR="/opt/poly_arb_bot"
mkdir -p "$PROJECT_DIR"

# Check if files are already here (user may have scp'd them)
if [ ! -f "$PROJECT_DIR/docker-compose.yml" ]; then
    echo ""
    echo "=============================================="
    echo "  IMPORTANT: Copy your project files now!"
    echo "=============================================="
    echo ""
    echo "From your MacBook, run this command:"
    echo ""
    echo "  scp -r /Users/samueleskenasy/poly_arb_bot/* root@\$(curl -s ifconfig.me):$PROJECT_DIR/"
    echo ""
    echo "Then run this script again."
    echo ""
    exit 1
fi

# 5. Configure firewall
echo "[5/6] Configuring firewall..."
ufw allow 22/tcp      # SSH
ufw allow 8080/tcp    # Dashboard
ufw --force enable
echo "Firewall configured (SSH + Dashboard port 8080)."

# 6. Build and start
echo "[6/6] Building and starting bot..."
cd "$PROJECT_DIR"

# Build the Docker image
docker-compose build

# Start in background
docker-compose up -d

echo ""
echo "================================================"
echo "  DEPLOYMENT COMPLETE!"
echo "================================================"
echo ""
echo "  Dashboard: http://$(curl -s ifconfig.me):8080"
echo "  Login:     admin / polyarb2026"
echo ""
echo "  Useful commands:"
echo "    View logs:     docker-compose logs -f"
echo "    Stop bot:      docker-compose down"
echo "    Restart:       docker-compose restart"
echo "    Update:        docker-compose build && docker-compose up -d"
echo ""
echo "  IMPORTANT: Change DASHBOARD_PASS in .env!"
echo "================================================"
