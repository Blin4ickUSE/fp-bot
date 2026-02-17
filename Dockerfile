# ============================================================
# FunPay Manager — Backend Dockerfile
# Python 3.11 + FastAPI + FunPayAPI + Telegram Bot
# ============================================================

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all source code
COPY src/ ./src/

# Create data directory for SQLite + logs
RUN mkdir -p /app/data

ENV API_HOST=0.0.0.0
ENV API_PORT=8080
ENV DATABASE_URL=sqlite:////app/data/fpbot.db
ENV PYTHONPATH=/app:/app/src
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8080

VOLUME ["/app/data"]

CMD ["python", "-m", "src.main"]
