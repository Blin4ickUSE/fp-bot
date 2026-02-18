"""
Простое файловое хранилище: топик (chat_id, thread_id) <-> telegram_id пользователя.
Позволяет при перезапуске бота сохранять связь топиков с пользователями.
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

# В Docker: /app/data; локально: корень_проекта/data
_ProjectRoot = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_STORAGE_PATH = os.path.join(_ProjectRoot, "data", "support_bot_topics.json")


def _ensure_dir():
    path = os.path.dirname(DEFAULT_STORAGE_PATH)
    if path and not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def _key(chat_id: int, thread_id: int) -> str:
    return f"{chat_id}_{thread_id}"


def load_topic_to_user(storage_path: str = DEFAULT_STORAGE_PATH) -> dict:
    """Загрузить маппинг topic_key -> telegram_id."""
    _ensure_dir()
    if not os.path.isfile(storage_path):
        return {}
    try:
        with open(storage_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Failed to load support_bot storage: %s", e)
        return {}


def save_topic_to_user(mapping: dict, storage_path: str = DEFAULT_STORAGE_PATH) -> None:
    """Сохранить маппинг topic_key -> telegram_id."""
    _ensure_dir()
    try:
        with open(storage_path, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("Failed to save support_bot storage: %s", e)


def load_user_to_topic(storage_path: str = None) -> dict:
    """Загрузить маппинг telegram_id -> {"chat_id": int, "thread_id": int} (последний топик пользователя)."""
    if storage_path is None:
        storage_path = DEFAULT_STORAGE_PATH.replace(".json", "_user_to_topic.json")
    _ensure_dir()
    if not os.path.isfile(storage_path):
        return {}
    try:
        with open(storage_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {int(k): v for k, v in data.items()}
    except Exception as e:
        logger.warning("Failed to load support_bot user_to_topic: %s", e)
        return {}


def save_user_to_topic(mapping: dict, storage_path: str = None) -> None:
    """Сохранить маппинг user -> topic."""
    if storage_path is None:
        storage_path = DEFAULT_STORAGE_PATH.replace(".json", "_user_to_topic.json")
    _ensure_dir()
    try:
        with open(storage_path, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in mapping.items()}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("Failed to save support_bot user_to_topic: %s", e)
