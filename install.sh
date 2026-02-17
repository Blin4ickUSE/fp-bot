#!/usr/bin/env bash
# ============================================================
#  FunPay Manager — Установка на Ubuntu 22.04
#  Устанавливает Docker, получает SSL-сертификат,
#  собирает и запускает всё на порту 21000.
#
#  Запуск:
#    chmod +x install.sh
#    sudo ./install.sh
# ============================================================

set -euo pipefail

# ─── Цвета ───────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log()   { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
err()   { echo -e "${RED}[✗]${NC} $*"; }
header(){ echo -e "\n${CYAN}${BOLD}═══ $* ═══${NC}\n"; }

# ─── Проверки ────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    err "Запустите скрипт от root: sudo ./install.sh"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

header "FunPay Manager — Установка"

# ─── 1. Ввод данных ─────────────────────────────────────────
echo -e "${BOLD}Введите данные для настройки:${NC}\n"

read -rp "Домен (например, fp.example.com): " DOMAIN
if [[ -z "$DOMAIN" ]]; then
    err "Домен обязателен!"
    exit 1
fi

read -rp "Email для SSL-сертификата (Let's Encrypt): " SSL_EMAIL
if [[ -z "$SSL_EMAIL" ]]; then
    err "Email обязателен для Let's Encrypt!"
    exit 1
fi

read -rp "FunPay Golden Key: " FUNPAY_GOLDEN_KEY
read -rp "Telegram Bot Token: " TELEGRAM_BOT_TOKEN
read -rp "Telegram Admin ID (ваш числовой ID): " TELEGRAM_ADMIN_ID

# Генерируем секрет API
API_SECRET=$(openssl rand -hex 32)

echo ""
log "Домен: $DOMAIN"
log "Email: $SSL_EMAIL"
log "API Secret: ${API_SECRET:0:8}..."
echo ""

# ─── 2. Обновление системы ──────────────────────────────────
header "Обновление системы"

apt-get update -y
apt-get upgrade -y
log "Система обновлена."

# ─── 3. Установка Docker ────────────────────────────────────
header "Установка Docker"

if command -v docker &>/dev/null; then
    log "Docker уже установлен: $(docker --version)"
else
    apt-get install -y ca-certificates curl gnupg lsb-release

    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
        gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
      https://download.docker.com/linux/ubuntu \
      $(lsb_release -cs) stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null

    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    systemctl enable docker
    systemctl start docker
    log "Docker установлен: $(docker --version)"
fi

# Проверка docker compose
if docker compose version &>/dev/null; then
    log "Docker Compose: $(docker compose version --short)"
else
    err "Docker Compose plugin не найден!"
    exit 1
fi

# ─── 4. Открытие порта в файрволе ───────────────────────────
header "Настройка файрвола"

if command -v ufw &>/dev/null; then
    ufw allow 21000/tcp comment "FunPay Manager HTTPS" 2>/dev/null || true
    ufw allow 21080/tcp comment "FunPay Manager HTTP redirect" 2>/dev/null || true
    # Порт 80 нужен для certbot
    ufw allow 80/tcp comment "Certbot HTTP challenge" 2>/dev/null || true
    log "Порты 21000, 21080, 80 открыты в UFW."
else
    warn "UFW не найден, пропускаем настройку файрвола."
    warn "Убедитесь, что порты 21000 и 80 открыты!"
fi

# ─── 5. SSL-сертификат (Let's Encrypt) ──────────────────────
header "Получение SSL-сертификата"

apt-get install -y certbot

if [[ -d "/etc/letsencrypt/live/$DOMAIN" ]]; then
    log "Сертификат для $DOMAIN уже существует."
else
    log "Получаем сертификат для $DOMAIN..."

    # Останавливаем всё что слушает 80-й порт
    systemctl stop nginx 2>/dev/null || true
    systemctl stop apache2 2>/dev/null || true

    certbot certonly \
        --standalone \
        --non-interactive \
        --agree-tos \
        --email "$SSL_EMAIL" \
        -d "$DOMAIN" \
        --preferred-challenges http

    if [[ $? -eq 0 ]]; then
        log "SSL-сертификат получен!"
    else
        err "Не удалось получить сертификат!"
        err "Убедитесь, что домен $DOMAIN указывает на этот сервер"
        err "и порт 80 доступен из интернета."
        exit 1
    fi
fi

# ─── 6. Автообновление сертификата ──────────────────────────
header "Настройка автообновления SSL"

CRON_JOB="0 3 * * * certbot renew --quiet --deploy-hook 'docker restart fpbot-nginx' >> /var/log/certbot-renew.log 2>&1"
(crontab -l 2>/dev/null | grep -v "certbot renew" ; echo "$CRON_JOB") | crontab -
log "Cron-задача для обновления SSL настроена (03:00 ежедневно)."

# ─── 7. Создание .env ───────────────────────────────────────
header "Создание конфигурации (.env)"

ENV_FILE="$SCRIPT_DIR/.env"

cat > "$ENV_FILE" <<EOF
# ============================================================
# FunPay Manager — Auto-generated config
# Created: $(date -Iseconds)
# ============================================================

# Domain
DOMAIN=$DOMAIN

# FunPay
FUNPAY_GOLDEN_KEY=$FUNPAY_GOLDEN_KEY
FUNPAY_USER_AGENT=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36

# Telegram
TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN
TELEGRAM_ADMIN_ID=$TELEGRAM_ADMIN_ID
WEBAPP_URL=https://$DOMAIN:21000

# Backend
API_HOST=0.0.0.0
API_PORT=8080
API_SECRET=$API_SECRET

# Database
DATABASE_URL=sqlite:////app/data/fpbot.db
EOF

chmod 600 "$ENV_FILE"
log ".env создан (chmod 600)."

# ─── 8. Сборка и запуск Docker ──────────────────────────────
header "Сборка Docker-образов"

docker compose build --no-cache
log "Образы собраны."

header "Запуск контейнеров"

docker compose up -d
log "Контейнеры запущены."

# ─── 9. Ждём готовности ─────────────────────────────────────
header "Проверка здоровья"

echo -n "Ожидание запуска backend"
for i in $(seq 1 30); do
    if docker compose exec -T backend python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/health')" &>/dev/null; then
        echo ""
        log "Backend готов!"
        break
    fi
    echo -n "."
    sleep 2
done

echo -n "Проверка nginx"
for i in $(seq 1 15); do
    if curl -sk "https://localhost:21000" &>/dev/null; then
        echo ""
        log "Nginx готов!"
        break
    fi
    echo -n "."
    sleep 2
done

# ─── 10. Итог ───────────────────────────────────────────────
header "Установка завершена!"

echo -e "${BOLD}Ваш FunPay Manager доступен по адресу:${NC}"
echo ""
echo -e "  ${GREEN}${BOLD}https://$DOMAIN:21000${NC}"
echo ""
echo -e "${BOLD}Telegram Mini App URL:${NC}"
echo -e "  ${CYAN}https://$DOMAIN:21000${NC}"
echo ""
echo -e "${BOLD}Полезные команды:${NC}"
echo -e "  ${CYAN}docker compose logs -f${NC}          — логи всех сервисов"
echo -e "  ${CYAN}docker compose logs -f backend${NC}  — логи бэкенда"
echo -e "  ${CYAN}docker compose logs -f nginx${NC}    — логи nginx"
echo -e "  ${CYAN}docker compose restart${NC}          — перезапуск"
echo -e "  ${CYAN}docker compose down${NC}             — остановка"
echo -e "  ${CYAN}docker compose up -d --build${NC}    — пересборка и запуск"
echo ""
echo -e "${BOLD}Файлы:${NC}"
echo -e "  ${CYAN}$SCRIPT_DIR/.env${NC}          — конфигурация"
echo -e "  ${CYAN}/app/data/fpbot.db${NC}        — база данных (в Docker volume)"
echo -e "  ${CYAN}/app/data/fpbot.log${NC}       — логи бота"
echo ""
echo -e "${YELLOW}Не забудьте:${NC}"
echo -e "  1. Настроить Telegram бота (@BotFather): установите Mini App URL = ${CYAN}https://$DOMAIN:21000${NC}"
echo -e "  2. Написать боту /start для проверки"
echo -e "  3. Проверить, что FunPay Golden Key актуален"
echo ""
log "Готово! 🦊"
