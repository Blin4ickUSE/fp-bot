# ============================================================
# FunPay Manager — Nginx + Frontend build
# Stage 1: Build React app
# Stage 2: Nginx with built files + custom entrypoint
# ============================================================

# --- Stage 1: Build frontend ---
FROM node:20-alpine AS builder

WORKDIR /build
COPY src/miniapp/package.json src/miniapp/package-lock.json* ./
RUN npm ci --no-audit --no-fund 2>/dev/null || npm install --no-audit --no-fund
COPY src/miniapp/ ./
RUN npm run build

# --- Stage 2: Nginx ---
FROM nginx:1.27-alpine

# Clean default config
RUN rm -f /etc/nginx/conf.d/default.conf

# Copy template
COPY nginx/nginx.conf.template /etc/nginx/nginx.conf.template

# Copy custom entrypoint
COPY nginx/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Copy built frontend
COPY --from=builder /build/dist /usr/share/nginx/html

EXPOSE 21000 21080

ENTRYPOINT ["/entrypoint.sh"]
