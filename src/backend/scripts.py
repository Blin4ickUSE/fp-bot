"""
Движок скриптов: определяет, какое сообщение отправить покупателю
и какой следующий шаг выполнить на основании его ответа.

Каждый скрипт — это конечный автомат (state machine).
Состояние хранится в Order.script_state (JSON).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .database import ScriptType

EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]{1,128}@[a-zA-Z0-9-]{1,128}\.[a-zA-Z]{1,128}$")


@dataclass
class ScriptResponse:
    """Результат обработки шага скрипта."""
    message_ru: str
    message_en: str
    finished: bool = False
    new_state: dict | None = None


def _override(custom_text: dict, key: str, default_ru: str, default_en: str) -> tuple[str, str]:
    """Подставляет кастомный текст из custom_text[key] или дефолт."""
    if not custom_text or not isinstance(custom_text.get(key), dict):
        return default_ru, default_en
    block = custom_text[key]
    return (
        (block.get("ru") or default_ru).strip() or default_ru,
        (block.get("en") or default_en).strip() or default_en,
    )


# ---------------------------------------------------------------------------
# Базовый класс
# ---------------------------------------------------------------------------

class BaseScript:
    """Базовый скрипт. Переопределяйте process()."""

    script_type: ScriptType = ScriptType.NONE

    def start(self, custom_text: dict | None = None) -> ScriptResponse:
        """Первое сообщение скрипта (после покупки)."""
        raise NotImplementedError

    def process(self, state: dict, user_message: str, custom_text: dict | None = None) -> ScriptResponse:
        """Обработать сообщение покупателя. custom_text — переопределение текстов из настроек лота."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Spotify (ключи для кастомного текста: start, wait_email_error, wait_password, wait_confirm_prompt, confirm_ok, confirm_retry)
# ---------------------------------------------------------------------------

SPOTIFY_DEFAULTS = {
    "start": {
        "ru": "🧡 Для выполнения заказа, отправьте вашу почту, привязанную к Spotify 🍂",
        "en": "🧡 To place an order, please send us your email address linked to Spotify 🍂",
    },
    "wait_email_error": {
        "ru": "❓️ Кажется, это не почта…\n\nЧтобы я смог выполнить заказ, мне понадобится твоя почта, на которую зарегистрирован Spotify в таком формате: example@example.com",
        "en": "❓️ It seems this isn't an email address…\n\nTo complete the order, I'll need your email address, which Spotify is registered to, in this format: example@example.com",
    },
    "wait_password": {
        "ru": "🥮 Отлично. Мне так же понадобится пароль от твоего аккаунта Spotify, чтобы я смог приобрести на него подписку",
        "en": "🥮 Great. I'll also need your Spotify account password so I can purchase a subscription.",
    },
    "wait_confirm_prompt": {
        "ru": "🍁 Перед тем, как я начну выполнение заказа, проверь данные:\n\nПочта: {email}\nПароль: {password}\n\n🍂 Если данные верны, напиши +; Если данные неверны, напиши -",
        "en": "🍁 Before I start fulfilling your order, please check the details:\n\nEmail: {email}\nPassword: {password}\n\n🍂 If the data is correct, write +; If the data is incorrect, write -",
    },
    "confirm_ok": {
        "ru": "🧡 Я передал данные продавцу!\n\nВ ближайшее время он выполнит Ваш заказ (от 10 минут до 10 часов) и уведомит Вас.\n\nЕсли вы вдруг указали неверные данные — не переживайте. Когда продавец приступит к вашему заказу, он вернёт деньги.",
        "en": "🧡 I've sent the information to the seller!\n\nThey will process your order shortly (10 minutes to 10 hours) and notify you.\n\nIf you entered incorrect information — don't worry. Once the seller processes your order, they will refund your money.",
    },
    "confirm_retry": {
        "ru": "🍂 Напишите + если данные верны, или - если нет.",
        "en": "🍂 Write + if the data is correct, or - if not.",
    },
}


class SpotifyScript(BaseScript):
    script_type = ScriptType.SPOTIFY

    def start(self, custom_text: dict | None = None) -> ScriptResponse:
        ru, en = _override(custom_text or {}, "start", SPOTIFY_DEFAULTS["start"]["ru"], SPOTIFY_DEFAULTS["start"]["en"])
        return ScriptResponse(message_ru=ru, message_en=en, new_state={"step": "wait_email", "data": {}})

    def process(self, state: dict, user_message: str, custom_text: dict | None = None) -> ScriptResponse:
        custom_text = custom_text or {}
        step = state.get("step", "wait_email")
        data = state.get("data", {})

        if step == "wait_email":
            msg = user_message.strip()
            if not EMAIL_RE.match(msg):
                ru, en = _override(custom_text, "wait_email_error", SPOTIFY_DEFAULTS["wait_email_error"]["ru"], SPOTIFY_DEFAULTS["wait_email_error"]["en"])
                return ScriptResponse(message_ru=ru, message_en=en, new_state=state)
            data["email"] = msg
            ru, en = _override(custom_text, "wait_password", SPOTIFY_DEFAULTS["wait_password"]["ru"], SPOTIFY_DEFAULTS["wait_password"]["en"])
            return ScriptResponse(message_ru=ru, message_en=en, new_state={"step": "wait_password", "data": data})

        if step == "wait_password":
            data["password"] = user_message.strip()
            t = SPOTIFY_DEFAULTS["wait_confirm_prompt"]
            ru = (custom_text.get("wait_confirm_prompt") or {}).get("ru") or t["ru"]
            en = (custom_text.get("wait_confirm_prompt") or {}).get("en") or t["en"]
            ru = ru.replace("{email}", data["email"]).replace("{password}", data["password"])
            en = en.replace("{email}", data["email"]).replace("{password}", data["password"])
            return ScriptResponse(message_ru=ru, message_en=en, new_state={"step": "wait_confirm", "data": data})

        if step == "wait_confirm":
            msg = user_message.strip()
            if msg == "+":
                ru, en = _override(custom_text, "confirm_ok", SPOTIFY_DEFAULTS["confirm_ok"]["ru"], SPOTIFY_DEFAULTS["confirm_ok"]["en"])
                return ScriptResponse(message_ru=ru, message_en=en, finished=True, new_state={"step": "done", "data": data})
            if msg == "-":
                return self.start(custom_text=custom_text)
            ru, en = _override(custom_text, "confirm_retry", SPOTIFY_DEFAULTS["confirm_retry"]["ru"], SPOTIFY_DEFAULTS["confirm_retry"]["en"])
            return ScriptResponse(message_ru=ru, message_en=en, new_state=state)

        ru = (custom_text.get("wait") or {}).get("ru") or "⏳ Ожидайте, продавец скоро приступит к заказу."
        en = (custom_text.get("wait") or {}).get("en") or "⏳ Please wait, the seller will process your order soon."
        return ScriptResponse(message_ru=ru, message_en=en, new_state=state)


# Дефолты для скриптов «логин + пароль» (Discord, ChatGPT, Netflix, Claude) — те же ключи, что у Spotify
def _login_password_defaults(name_ru: str, name_en: str) -> dict:
    return {
        "start": {
            "ru": f"🧡 Для выполнения заказа отправьте почту, привязанную к {name_ru} 🍂",
            "en": f"🧡 To complete your order, please send the email linked to your {name_en} account 🍂",
        },
        "wait_email_error": {
            "ru": f"❓️ Кажется, это не почта. Нужна почта в формате example@example.com, на которую зарегистрирован {name_ru}.",
            "en": f"❓️ This doesn't look like an email. Please send the email registered to your {name_en} account in format: example@example.com",
        },
        "wait_password": {
            "ru": f"🥮 Отлично. Теперь отправьте пароль от аккаунта {name_ru}.",
            "en": f"🥮 Great. Now please send your {name_en} account password.",
        },
        "wait_confirm_prompt": {
            "ru": "🍁 Проверьте данные:\n\nПочта: {email}\nПароль: {password}\n\nЕсли верно — напишите +, если нет — -",
            "en": "🍁 Check the details:\n\nEmail: {email}\nPassword: {password}\n\nIf correct — write +, if not — -",
        },
        "confirm_ok": {
            "ru": "🧡 Данные переданы продавцу. Заказ будет выполнен в ближайшее время (10 мин – 10 ч). При ошибке в данных — вернём деньги.",
            "en": "🧡 Data sent to the seller. Your order will be processed shortly (10 min – 10 h). If data was wrong, we'll refund.",
        },
        "confirm_retry": {
            "ru": "🍂 Напишите + если данные верны, или - если нет.",
            "en": "🍂 Write + if the data is correct, or - if not.",
        },
    }

DISCORD_DEFAULTS = _login_password_defaults("Discord", "Discord")
CHATGPT_DEFAULTS = _login_password_defaults("ChatGPT", "ChatGPT")
NETFLIX_DEFAULTS = _login_password_defaults("Netflix", "Netflix")
CLAUDE_DEFAULTS = _login_password_defaults("Claude", "Claude")


def _process_login_password(state: dict, user_message: str, custom_text: dict, defaults: dict) -> ScriptResponse:
    """Общая логика шагов wait_email → wait_password → wait_confirm для скриптов логин+пароль."""
    step = state.get("step", "wait_email")
    data = state.get("data", {})

    if step == "wait_email":
        msg = user_message.strip()
        if not EMAIL_RE.match(msg):
            ru, en = _override(custom_text, "wait_email_error", defaults["wait_email_error"]["ru"], defaults["wait_email_error"]["en"])
            return ScriptResponse(message_ru=ru, message_en=en, new_state=state)
        data["email"] = msg
        ru, en = _override(custom_text, "wait_password", defaults["wait_password"]["ru"], defaults["wait_password"]["en"])
        return ScriptResponse(message_ru=ru, message_en=en, new_state={"step": "wait_password", "data": data})

    if step == "wait_password":
        data["password"] = user_message.strip()
        t = defaults["wait_confirm_prompt"]
        ru = (custom_text.get("wait_confirm_prompt") or {}).get("ru") or t["ru"]
        en = (custom_text.get("wait_confirm_prompt") or {}).get("en") or t["en"]
        ru = ru.replace("{email}", data["email"]).replace("{password}", data["password"])
        en = en.replace("{email}", data["email"]).replace("{password}", data["password"])
        return ScriptResponse(message_ru=ru, message_en=en, new_state={"step": "wait_confirm", "data": data})

    if step == "wait_confirm":
        msg = user_message.strip()
        if msg == "+":
            ru, en = _override(custom_text, "confirm_ok", defaults["confirm_ok"]["ru"], defaults["confirm_ok"]["en"])
            return ScriptResponse(message_ru=ru, message_en=en, finished=True, new_state={"step": "done", "data": data})
        if msg == "-":
            ru, en = _override(custom_text, "start", defaults["start"]["ru"], defaults["start"]["en"])
            return ScriptResponse(message_ru=ru, message_en=en, new_state={"step": "wait_email", "data": {}})
        ru, en = _override(custom_text, "confirm_retry", defaults["confirm_retry"]["ru"], defaults["confirm_retry"]["en"])
        return ScriptResponse(message_ru=ru, message_en=en, new_state=state)

    ru = (custom_text.get("wait") or {}).get("ru") or "⏳ Ожидайте, продавец скоро приступит к заказу."
    en = (custom_text.get("wait") or {}).get("en") or "⏳ Please wait, the seller will process your order soon."
    return ScriptResponse(message_ru=ru, message_en=en, new_state=state)


# ---------------------------------------------------------------------------
# Discord Nitro (логин + пароль, тексты как у Spotify)
# ---------------------------------------------------------------------------

class DiscordNitroScript(BaseScript):
    script_type = ScriptType.DISCORD_NITRO

    def start(self, custom_text: dict | None = None) -> ScriptResponse:
        ru, en = _override(custom_text or {}, "start", DISCORD_DEFAULTS["start"]["ru"], DISCORD_DEFAULTS["start"]["en"])
        return ScriptResponse(message_ru=ru, message_en=en, new_state={"step": "wait_email", "data": {}})

    def process(self, state: dict, user_message: str, custom_text: dict | None = None) -> ScriptResponse:
        return _process_login_password(state, user_message, custom_text or {}, DISCORD_DEFAULTS)


# ---------------------------------------------------------------------------
# ChatGPT (логин + пароль, тексты как у Spotify)
# ---------------------------------------------------------------------------

class ChatGPTScript(BaseScript):
    script_type = ScriptType.CHATGPT

    def start(self, custom_text: dict | None = None) -> ScriptResponse:
        ru, en = _override(custom_text or {}, "start", CHATGPT_DEFAULTS["start"]["ru"], CHATGPT_DEFAULTS["start"]["en"])
        return ScriptResponse(message_ru=ru, message_en=en, new_state={"step": "wait_email", "data": {}})

    def process(self, state: dict, user_message: str, custom_text: dict | None = None) -> ScriptResponse:
        return _process_login_password(state, user_message, custom_text or {}, CHATGPT_DEFAULTS)


# ---------------------------------------------------------------------------
# Netflix (логин + пароль)
# ---------------------------------------------------------------------------

class NetflixScript(BaseScript):
    script_type = ScriptType.NETFLIX

    def start(self, custom_text: dict | None = None) -> ScriptResponse:
        ru, en = _override(custom_text or {}, "start", NETFLIX_DEFAULTS["start"]["ru"], NETFLIX_DEFAULTS["start"]["en"])
        return ScriptResponse(message_ru=ru, message_en=en, new_state={"step": "wait_email", "data": {}})

    def process(self, state: dict, user_message: str, custom_text: dict | None = None) -> ScriptResponse:
        return _process_login_password(state, user_message, custom_text or {}, NETFLIX_DEFAULTS)


# ---------------------------------------------------------------------------
# Claude (логин + пароль)
# ---------------------------------------------------------------------------

class ClaudeScript(BaseScript):
    script_type = ScriptType.CLAUDE

    def start(self, custom_text: dict | None = None) -> ScriptResponse:
        ru, en = _override(custom_text or {}, "start", CLAUDE_DEFAULTS["start"]["ru"], CLAUDE_DEFAULTS["start"]["en"])
        return ScriptResponse(message_ru=ru, message_en=en, new_state={"step": "wait_email", "data": {}})

    def process(self, state: dict, user_message: str, custom_text: dict | None = None) -> ScriptResponse:
        return _process_login_password(state, user_message, custom_text or {}, CLAUDE_DEFAULTS)


# ---------------------------------------------------------------------------
# Telegram Premium (1 мес) — нужен логин+пароль+облачный пароль
# ---------------------------------------------------------------------------

class TelegramPremium1MScript(BaseScript):
    script_type = ScriptType.TELEGRAM_PREMIUM_1M

    def start(self, custom_text: dict | None = None) -> ScriptResponse:
        return ScriptResponse(
            message_ru=(
                "💎 Для выполнения заказа, отправьте номер телефона, "
                "привязанный к вашему Telegram-аккаунту (в формате +7XXXXXXXXXX)"
            ),
            message_en=(
                "💎 To fulfill your order, please send the phone number "
                "linked to your Telegram account (format: +7XXXXXXXXXX)"
            ),
            new_state={"step": "wait_phone", "data": {}}
        )

    def process(self, state: dict, user_message: str, custom_text: dict | None = None) -> ScriptResponse:
        step = state.get("step", "wait_phone")
        data = state.get("data", {})

        if step == "wait_phone":
            msg = user_message.strip()
            if not re.match(r"^\+?\d{7,15}$", msg.replace(" ", "").replace("-", "")):
                return ScriptResponse(
                    message_ru="❓ Неверный формат номера. Отправьте номер в формате +7XXXXXXXXXX",
                    message_en="❓ Invalid phone format. Please send in format +7XXXXXXXXXX",
                    new_state=state
                )
            data["phone"] = msg
            return ScriptResponse(
                message_ru="🔑 Теперь отправьте пароль от вашего Telegram-аккаунта (пароль для входа)",
                message_en="🔑 Now send your Telegram account password (login password)",
                new_state={"step": "wait_password", "data": data}
            )

        if step == "wait_password":
            data["password"] = user_message.strip()
            return ScriptResponse(
                message_ru=(
                    "☁️ Установлен ли у вас облачный пароль (Two-Step Verification) в Telegram?\n\n"
                    "Если да — отправьте его. Если нет — напишите: нет"
                ),
                message_en=(
                    "☁️ Do you have a cloud password (Two-Step Verification) in Telegram?\n\n"
                    "If yes — send it. If no — write: no"
                ),
                new_state={"step": "wait_cloud_password", "data": data}
            )

        if step == "wait_cloud_password":
            msg = user_message.strip().lower()
            if msg not in ("нет", "no"):
                data["cloud_password"] = user_message.strip()
            return ScriptResponse(
                message_ru=(
                    f"📋 Проверьте данные:\n\n"
                    f"Телефон: {data['phone']}\n"
                    f"Пароль: {data['password']}\n"
                    f"Облачный пароль: {data.get('cloud_password', 'нет')}\n\n"
                    f"Если верно — напишите +, если нет — напишите -"
                ),
                message_en=(
                    f"📋 Check the details:\n\n"
                    f"Phone: {data['phone']}\n"
                    f"Password: {data['password']}\n"
                    f"Cloud password: {data.get('cloud_password', 'no')}\n\n"
                    f"If correct — write +, if not — write -"
                ),
                new_state={"step": "wait_confirm", "data": data}
            )

        if step == "wait_confirm":
            msg = user_message.strip()
            if msg == "+":
                return ScriptResponse(
                    message_ru=(
                        "🧡 Я передал данные продавцу!\n\n"
                        "В ближайшее время он выполнит Ваш заказ (от 10 минут до 12 часов) "
                        "и уведомит Вас.\n\n"
                        "Если вы вдруг указали неверные данные — не переживайте. "
                        "Когда продавец приступит к вашему заказу, он вернёт деньги."
                    ),
                    message_en=(
                        "🧡 I've sent the information to the seller!\n\n"
                        "They will process your order shortly (10 minutes to 12 hours) "
                        "and notify you.\n\n"
                        "If you entered incorrect information — don't worry. "
                        "Once the seller processes your order, they will refund your money."
                    ),
                    finished=True,
                    new_state={"step": "done", "data": data}
                )
            elif msg == "-":
                return self.start()
            else:
                return ScriptResponse(
                    message_ru="Напишите + если данные верны, или - если нет.",
                    message_en="Write + if the data is correct, or - if not.",
                    new_state=state
                )

        return ScriptResponse(
            message_ru="⏳ Ожидайте, продавец скоро приступит к заказу.",
            message_en="⏳ Please wait, the seller will process your order soon.",
            new_state=state
        )


# ---------------------------------------------------------------------------
# Telegram Premium 3/6/12 мес, Telegram Stars — нужен только username
# ---------------------------------------------------------------------------

class UsernameOnlyScript(BaseScript):
    """Базовый скрипт, запрашивающий только username."""
    script_type = ScriptType.TELEGRAM_PREMIUM_LONG

    def __init__(self, product_name_ru: str = "Telegram Premium", product_name_en: str = "Telegram Premium"):
        self.product_name_ru = product_name_ru
        self.product_name_en = product_name_en

    def start(self, custom_text: dict | None = None) -> ScriptResponse:
        return ScriptResponse(
            message_ru=f"💎 Для выполнения заказа, отправьте ваш username в Telegram (например, @username)",
            message_en=f"💎 To fulfill your order, please send your Telegram username (e.g., @username)",
            new_state={"step": "wait_username", "data": {}}
        )

    def process(self, state: dict, user_message: str, custom_text: dict | None = None) -> ScriptResponse:
        step = state.get("step", "wait_username")
        data = state.get("data", {})

        if step == "wait_username":
            msg = user_message.strip()
            # Принимаем с @ или без
            if msg.startswith("@"):
                msg = msg[1:]
            if not re.match(r"^[a-zA-Z0-9_]{3,32}$", msg):
                return ScriptResponse(
                    message_ru="❓ Неверный формат. Отправьте ваш username (например, @username)",
                    message_en="❓ Invalid format. Send your username (e.g., @username)",
                    new_state=state
                )
            data["username"] = f"@{msg}"
            return ScriptResponse(
                message_ru=(
                    f"📋 Проверьте данные:\n\n"
                    f"Username: {data['username']}\n\n"
                    f"Если верно — напишите +, если нет — напишите -"
                ),
                message_en=(
                    f"📋 Check the details:\n\n"
                    f"Username: {data['username']}\n\n"
                    f"If correct — write +, if not — write -"
                ),
                new_state={"step": "wait_confirm", "data": data}
            )

        if step == "wait_confirm":
            msg = user_message.strip()
            if msg == "+":
                return ScriptResponse(
                    message_ru=(
                        "🧡 Я передал данные продавцу!\n\n"
                        "В ближайшее время он выполнит Ваш заказ (от 10 минут до 12 часов) "
                        "и уведомит Вас.\n\n"
                        "Если вы вдруг указали неверные данные — не переживайте. "
                        "Когда продавец приступит к вашему заказу, он вернёт деньги."
                    ),
                    message_en=(
                        "🧡 I've sent the information to the seller!\n\n"
                        "They will process your order shortly (10 minutes to 12 hours) "
                        "and notify you.\n\n"
                        "If you entered incorrect information — don't worry. "
                        "Once the seller processes your order, they will refund your money."
                    ),
                    finished=True,
                    new_state={"step": "done", "data": data}
                )
            elif msg == "-":
                return self.start()
            else:
                return ScriptResponse(
                    message_ru="Напишите + если данные верны, или - если нет.",
                    message_en="Write + if the data is correct, or - if not.",
                    new_state=state
                )

        return ScriptResponse(
            message_ru="⏳ Ожидайте, продавец скоро приступит к заказу.",
            message_en="⏳ Please wait, the seller will process your order soon.",
            new_state=state
        )


class TelegramStarsScript(UsernameOnlyScript):
    script_type = ScriptType.TELEGRAM_STARS

    def __init__(self):
        super().__init__("Telegram Stars", "Telegram Stars")


class TelegramPremiumLongScript(UsernameOnlyScript):
    script_type = ScriptType.TELEGRAM_PREMIUM_LONG

    def __init__(self):
        super().__init__("Telegram Premium", "Telegram Premium")


# ---------------------------------------------------------------------------
# Реестр скриптов
# ---------------------------------------------------------------------------

SCRIPTS: dict[ScriptType, BaseScript] = {
    ScriptType.SPOTIFY: SpotifyScript(),
    ScriptType.DISCORD_NITRO: DiscordNitroScript(),
    ScriptType.CHATGPT: ChatGPTScript(),
    ScriptType.NETFLIX: NetflixScript(),
    ScriptType.CLAUDE: ClaudeScript(),
    ScriptType.TELEGRAM_PREMIUM_1M: TelegramPremium1MScript(),
    ScriptType.TELEGRAM_PREMIUM_LONG: TelegramPremiumLongScript(),
    ScriptType.TELEGRAM_STARS: TelegramStarsScript(),
}


def get_script(script_type: ScriptType) -> Optional[BaseScript]:
    return SCRIPTS.get(script_type)


# Ключи сообщений по типам скриптов (для UI редактирования)
_COMMON_LOGIN_KEYS = [
    {"key": "start", "label_ru": "Приветствие (запрос почты)", "label_en": "Greeting (email request)"},
    {"key": "wait_email_error", "label_ru": "Ошибка: не почта", "label_en": "Error: not email"},
    {"key": "wait_password", "label_ru": "Запрос пароля", "label_en": "Password request"},
    {"key": "wait_confirm_prompt", "label_ru": "Проверка данных (+/-)", "label_en": "Check data (+/-)"},
    {"key": "confirm_ok", "label_ru": "Данные приняты", "label_en": "Data accepted"},
    {"key": "confirm_retry", "label_ru": "Повтор: напиши + или -", "label_en": "Retry: write + or -"},
]
SCRIPT_MESSAGE_KEYS: dict[str, list[dict]] = {
    "spotify": _COMMON_LOGIN_KEYS.copy(),
    "discord_nitro": _COMMON_LOGIN_KEYS.copy(),
    "chatgpt": _COMMON_LOGIN_KEYS.copy(),
    "netflix": _COMMON_LOGIN_KEYS.copy(),
    "claude": _COMMON_LOGIN_KEYS.copy(),
    "telegram_premium_1m": [{"key": "start", "label_ru": "Приветствие", "label_en": "Greeting"}],
    "telegram_premium_long": [{"key": "start", "label_ru": "Приветствие (username)", "label_en": "Greeting (username)"}],
    "telegram_stars": [{"key": "start", "label_ru": "Приветствие (username)", "label_en": "Greeting (username)"}],
}


# ---------------------------------------------------------------------------
# Сообщения при изменении статуса (отправляются продавцом через мини-приложение)
# ---------------------------------------------------------------------------

STATUS_MESSAGES = {
    "order_started": {
        "ru": (
            "🥮 Продавец приступил к вашему заказу.\n"
            "Он будет выполнен (или отменен, если данные неверны) "
            "в ближайшее время (не более 20 минут)"
        ),
        "en": (
            "🥮 The seller has started processing your order. "
            "It will be fulfilled (or canceled if the information is incorrect) "
            "shortly (no more than 20 minutes)."
        ),
    },
    "order_completed": {
        "ru": "🦊 ЗАКАЗ ВЫПОЛНЕН! Не забудьте подтвердить заказ и оставить отзыв.",
        "en": "🦊 ORDER COMPLETED! Don't forget to confirm your order and leave a review.",
    },
    "order_cancelled": {
        "ru": (
            "❌️ ЗАКАЗ ОТМЕНЕН! Возможно, вы указали неверные данные "
            "или продавец не может выполнить заказ в данный момент. Простите…"
        ),
        "en": (
            "❌️ ORDER CANCELLED! You may have provided incorrect information "
            "or the seller is unable to fulfill your order at this time. Sorry..."
        ),
    },
    "review_reminder": {
        "ru": (
            "🫶 Пожалуйста, поставьте нам 5 звезд ⭐️\n\n"
            "Продавец старается выполнять все заказы быстро и качественно, "
            "при этом сохраняя самую низкую цену на рынке.\n\n"
            "Если у вас возникли проблемы, не спешите портить рейтинг продавцу, "
            "обратитесь в чат к продавцу. Чаще всего, если что-то случится, "
            "мы бесплатно восстанавливаем подписку."
        ),
        "en": (
            "🫶 Please give us 5 stars ⭐️\n\n"
            "The seller strives to fulfill all orders quickly and efficiently, "
            "while maintaining the lowest prices on the market.\n\n"
            "If you encounter any problems, don't rush to ruin the seller's rating; "
            "contact them via chat. In most cases, if something happens, "
            "we will restore your subscription free of charge."
        ),
    },
}
