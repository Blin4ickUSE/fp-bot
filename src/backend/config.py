"""
Конфигурация проекта. Загрузка из .env файла.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH)

# FunPay
FUNPAY_GOLDEN_KEY: str = os.getenv("FUNPAY_GOLDEN_KEY", "")
FUNPAY_USER_AGENT: str = os.getenv("FUNPAY_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# Telegram
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ADMIN_ID: int = int(os.getenv("TELEGRAM_ADMIN_ID", "0"))
WEBAPP_URL: str = os.getenv("WEBAPP_URL", "")  # URL мини-приложения (напр. https://yourapp.com)

# Backend
API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
API_PORT: int = int(os.getenv("API_PORT", "8080"))
API_SECRET: str = os.getenv("API_SECRET", "change-me-to-random-secret-key")

# Database
DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'fpbot.db'}")

# Paths
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
