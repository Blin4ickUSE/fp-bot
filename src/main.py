"""
Главная точка входа. Запускает:
1. FunPay Bridge (слушает события, обрабатывает скрипты)
2. Telegram Bot (уведомления + команды)
3. FastAPI Backend (API для мини-приложения)
"""
import sys
import os
import logging
import threading
import uvicorn

# Добавляем корень проекта и src/ в sys.path
# (корень — для src.*, src/ — для FunPayAPI.*)
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_src = os.path.join(_root, "src")
for _p in (_root, _src):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from src.backend.config import API_HOST, API_PORT, FUNPAY_GOLDEN_KEY, TELEGRAM_BOT_TOKEN, DATA_DIR
from src.backend.database import init_db
from src.backend.bridge import FunPayBridge
from src.backend.routes import app, set_funpay_bridge
from src.bot.telegram_bot import TelegramNotifier

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(DATA_DIR / "fpbot.log"), encoding="utf-8"),
    ]
)
logger = logging.getLogger("main")


def main():
    logger.info("=" * 50)
    logger.info("FunPay Manager — Запуск")
    logger.info("=" * 50)

    # 1) Инициализация БД
    logger.info("Инициализация базы данных...")
    init_db()

    # 2) Инициализация Telegram бота
    telegram = TelegramNotifier()
    if TELEGRAM_BOT_TOKEN:
        logger.info("Инициализация Telegram бота...")
        telegram.init()
        telegram.start()
    else:
        logger.warning("TELEGRAM_BOT_TOKEN не задан — бот не запущен.")

    # 3) Инициализация FunPay Bridge
    bridge = FunPayBridge()
    bridge.telegram = telegram
    set_funpay_bridge(bridge)

    if FUNPAY_GOLDEN_KEY:
        logger.info("Инициализация FunPay...")
        try:
            bridge.init_account()
            bridge.start()
        except Exception as e:
            logger.error(f"Не удалось инициализировать FunPay: {e}", exc_info=True)
            logger.warning("Бот продолжит работу без подключения к FunPay.")
    else:
        logger.warning("FUNPAY_GOLDEN_KEY не задан — FunPay не подключён.")

    # 4) Запуск FastAPI
    logger.info(f"Запуск API на {API_HOST}:{API_PORT}...")
    uvicorn.run(app, host=API_HOST, port=API_PORT, log_level="info")


if __name__ == "__main__":
    main()
