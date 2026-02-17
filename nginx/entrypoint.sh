#!/bin/sh
set -e

DOMAIN="${DOMAIN:-localhost}"

echo "[fpbot-nginx] Generating config for domain: ${DOMAIN}"

sed "s/__DOMAIN__/${DOMAIN}/g" \
    /etc/nginx/nginx.conf.template \
    > /etc/nginx/conf.d/default.conf

echo "[fpbot-nginx] Config written to /etc/nginx/conf.d/default.conf"
echo "[fpbot-nginx] Starting nginx on port 21000 (SSL)..."

exec nginx -g 'daemon off;'
