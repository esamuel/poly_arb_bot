# Production Web Setup (Domain + HTTPS)

This setup exposes your dashboard securely at:

- `https://app.orbitarb.com`

## 1) DNS (required first)

In your domain provider DNS panel, create an `A` record:

- Host: `app` (for app.orbitarb.com)
- Value: your server's public IP
- TTL: default

Example:

- `app.orbitarb.com -> YOUR_SERVER_IP`

## 2) Configure `.env` on the server

Edit `/opt/poly_arb_bot/.env` (or your project path) and set:

- `DOMAIN=app.orbitarb.com`
- `TLS_EMAIL=samuel.eskenasy@gmail.com`
- strong `DASHBOARD_PASS` value
- `DASHBOARD_AUTH_DISABLED=0` (auth is auto-enabled in production)
- keep `DASHBOARD_ALLOW_INSECURE_DEFAULTS=0` (default; prevents weak auth startup)
- keep `ALLOW_FUND_MOVEMENTS=0` unless you are intentionally running transfer/swap/allowance scripts

## 3) Deploy production stack

On your server (copy the project first, e.g. via git clone or rsync):

```bash
cd /path/to/poly_arb_bot   # e.g. /opt/poly_arb_bot
sudo bash deploy_production.sh
```

This will:

- run app container internally (not public on `:8080`)
- run Caddy reverse proxy on `80/443`
- auto-provision and renew TLS certificate

## 4) Verify

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f caddy
docker compose -f docker-compose.prod.yml logs -f polybot
```

Then open:

- `https://app.orbitarb.com`

Login: `admin` / your `DASHBOARD_PASS` from .env

## 5) Update later

```bash
cd /opt/poly_arb_bot
docker compose -f docker-compose.prod.yml up -d --build
```

## 6) Security notes

- Keep only `22`, `80`, `443` open externally.
- Rotate credentials if they were ever shared in chat or screenshots.
- Use a strong dashboard password.
