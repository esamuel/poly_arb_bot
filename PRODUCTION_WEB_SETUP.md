# Production Web Setup (Domain + HTTPS)

This setup exposes your dashboard securely at:

- `https://your-domain.com`

## 1) DNS (required first)

In your domain provider DNS panel, create an `A` record:

- Host: your subdomain (for example `bot`)
- Value: your droplet public IP
- TTL: default

Example:

- `bot.yourdomain.com -> 104.131.125.103`

## 2) Configure `.env` on the server

Edit `/opt/poly_arb_bot/.env` and set:

- `DOMAIN=bot.yourdomain.com`
- `TLS_EMAIL=you@yourdomain.com`
- strong `DASHBOARD_PASS` value

## 3) Deploy production stack

On server:

```bash
cd /opt/poly_arb_bot
bash deploy_production.sh
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

- `https://bot.yourdomain.com`

## 5) Update later

```bash
cd /opt/poly_arb_bot
docker compose -f docker-compose.prod.yml up -d --build
```

## 6) Security notes

- Keep only `22`, `80`, `443` open externally.
- Rotate credentials if they were ever shared in chat or screenshots.
- Use a strong dashboard password.
