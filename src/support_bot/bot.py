"""
Бот поддержки 12VPN.
- Принимает сообщения от пользователей в личку.
- Создаёт новую тему в группе-форуме с информацией о пользователе и текстом сообщения.
- Любое сообщение, отправленное в эту тему оператором, пересылается пользователю.
"""
import asyncio
import logging
import os
import sys

# Корень проекта в path для импортов
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.enums import ParseMode

from src.support_bot.storage import (
    load_topic_to_user,
    save_topic_to_user,
    load_user_to_topic,
    save_user_to_topic,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("SUPPORT_BOT_TOKEN", "")
SUPPORT_FORUM_GROUP_ID = os.getenv("SUPPORT_FORUM_GROUP_ID", "")  # ID группы с включёнными топиками (форум)

if not BOT_TOKEN:
    logger.error("SUPPORT_BOT_TOKEN не задан в .env")
    sys.exit(1)

if not SUPPORT_FORUM_GROUP_ID:
    logger.error("SUPPORT_FORUM_GROUP_ID не задан. Укажите ID группы-форума для топиков поддержки.")
    sys.exit(1)

try:
    FORUM_CHAT_ID = int(SUPPORT_FORUM_GROUP_ID)
except ValueError:
    # Может быть @username
    FORUM_CHAT_ID = SUPPORT_FORUM_GROUP_ID.strip()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Маппинги в памяти, при старте подгружаем из файла
TOPIC_TO_USER: dict[str, int] = {}
USER_TO_TOPIC: dict[int, dict] = {}


def _topic_key(chat_id: int, thread_id: int) -> str:
    return f"{chat_id}_{thread_id}"


def _load_storage():
    global TOPIC_TO_USER, USER_TO_TOPIC
    TOPIC_TO_USER = load_topic_to_user()
    USER_TO_TOPIC = load_user_to_topic()
    logger.info("Loaded %s topic->user, %s user->topic mappings", len(TOPIC_TO_USER), len(USER_TO_TOPIC))


def _save_mappings():
    save_topic_to_user(TOPIC_TO_USER)
    save_user_to_topic(USER_TO_TOPIC)


def _user_info(user: types.User) -> str:
    name = (user.full_name or "").strip() or "(без имени)"
    username = f"@{user.username}" if user.username else "—"
    return f"ID: {user.id} | {name} | {username}"


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Это бот поддержки 12VPN.\n\n"
        "Напишите сюда ваше сообщение — мы создадим обращение и ответим в этой переписке."
    )


@dp.message(F.chat.type == "private", F.text)
async def on_private_message(message: types.Message):
    """Пользователь пишет в личку — создаём топик (или дополняем существующий) и постим сообщение."""
    user = message.from_user
    if not user:
        return
    text = (message.text or "").strip()
    if not text:
        await message.answer("Отправьте текстовое сообщение.")
        return

    try:
        # Проверяем, есть ли у пользователя уже открытый топик — тогда пишем в него
        chat_id = FORUM_CHAT_ID
        thread_id = None
        if user.id in USER_TO_TOPIC:
            info = USER_TO_TOPIC[user.id]
            if isinstance(info, dict) and "chat_id" in info and "thread_id" in info:
                thread_id = info["thread_id"]
                chat_id = info["chat_id"]

        if thread_id is None:
            # Создаём новую тему
            topic_name = f"User: {user.full_name or user.id} ({user.id})"
            if len(topic_name) > 128:
                topic_name = topic_name[:125] + "..."
            topic = await bot.create_forum_topic(
                chat_id=chat_id,
                name=topic_name,
            )
            thread_id = topic.message_thread_id
            # Первое сообщение в топике — инфо о пользователе + текст
            header = (
                f"🆕 Обращение от пользователя\n"
                f"{_user_info(user)}\n\n"
                f"Сообщение:\n{text}"
            )
            TOPIC_TO_USER[_topic_key(chat_id, thread_id)] = user.id
            USER_TO_TOPIC[user.id] = {"chat_id": chat_id, "thread_id": thread_id}
            _save_mappings()
        else:
            # Дополняем существующий топик
            header = f"📩 Новое сообщение от пользователя:\n\n{text}"

        await bot.send_message(
            chat_id=chat_id,
            text=header,
            message_thread_id=thread_id,
        )
        await message.answer("✅ Ваше сообщение передано в поддержку. Ожидайте ответа здесь.")
    except Exception as e:
        logger.exception("Failed to create topic or send to forum: %s", e)
        await message.answer(
            "Не удалось создать обращение. Попробуйте позже или напишите в основной бот 12VPN."
        )


@dp.message(F.chat.type == "private", F.photo)
async def on_private_photo(message: types.Message):
    """Фото в личку — тоже создаём/дополняем топик."""
    user = message.from_user
    if not user:
        return
    caption = (message.caption or "").strip()
    thread_id = None
    chat_id = FORUM_CHAT_ID
    if user.id in USER_TO_TOPIC:
        info = USER_TO_TOPIC[user.id]
        if isinstance(info, dict):
            thread_id = info.get("thread_id")
            chat_id = info.get("chat_id", FORUM_CHAT_ID)

    try:
        if thread_id is None:
            topic_name = f"User: {user.full_name or user.id} ({user.id})"
            if len(topic_name) > 128:
                topic_name = topic_name[:125] + "..."
            topic = await bot.create_forum_topic(chat_id=chat_id, name=topic_name)
            thread_id = topic.message_thread_id
            TOPIC_TO_USER[_topic_key(chat_id, thread_id)] = user.id
            USER_TO_TOPIC[user.id] = {"chat_id": chat_id, "thread_id": thread_id}
            _save_mappings()
            header = f"🆕 Обращение от пользователя\n{_user_info(user)}\n\n"
        else:
            header = "📩 Новое сообщение от пользователя:\n\n"
        if caption:
            header += f"Подпись: {caption}\n\n"
        header += "[Фото]"
        await bot.send_photo(
            chat_id=chat_id,
            photo=message.photo[-1].file_id,
            caption=header,
            message_thread_id=thread_id,
        )
        await message.answer("✅ Сообщение передано в поддержку.")
    except Exception as e:
        logger.exception("Failed to send photo to forum: %s", e)
        await message.answer("Не удалось отправить. Попробуйте позже.")


@dp.message(F.chat.type == "private")
async def on_private_other(message: types.Message):
    """Любой другой тип сообщения в личку — просим текст или фото."""
    await message.answer("Пожалуйста, отправьте текст или фото.")


@dp.message(F.chat.id == FORUM_CHAT_ID, F.message_thread_id)
async def on_forum_topic_message(message: types.Message):
    """Сообщение в топике форум-группы — пересылаем пользователю."""
    thread_id = message.message_thread_id
    if thread_id is None:
        return
    key = _topic_key(message.chat.id, thread_id)
    user_telegram_id = TOPIC_TO_USER.get(key)
    if not user_telegram_id:
        return  # Топик не от нашего бота или старый

    # Игнорируем служебные сообщения и команды от бота
    if not message.text and not message.caption:
        if message.photo or message.document or message.video:
            # Пересылаем медиа с подписью
            caption = message.caption or "Ответ поддержки:"
            try:
                if message.photo:
                    await bot.send_photo(
                        user_telegram_id,
                        photo=message.photo[-1].file_id,
                        caption=caption,
                    )
                elif message.document:
                    await bot.send_document(
                        user_telegram_id,
                        document=message.document.file_id,
                        caption=caption,
                    )
                elif message.video:
                    await bot.send_video(
                        user_telegram_id,
                        video=message.video.file_id,
                        caption=caption,
                    )
                else:
                    await bot.send_message(user_telegram_id, caption or "Ответ поддержки.")
            except Exception as e:
                logger.warning("Failed to forward to user %s: %s", user_telegram_id, e)
        return

    text = (message.text or message.caption or "").strip()
    if not text:
        return

    reply_prefix = "💬 Ответ поддержки 12VPN:\n\n"
    try:
        await bot.send_message(
            user_telegram_id,
            reply_prefix + text,
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.warning("Failed to send reply to user %s: %s", user_telegram_id, e)


async def main():
    _load_storage()
    logger.info("Support bot starting (forum group id: %s)", FORUM_CHAT_ID)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
