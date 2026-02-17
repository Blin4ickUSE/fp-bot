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
    # Если True — скрипт завершён, данные собраны
    finished: bool = False
    # Новое состояние (шаг + промежуточные данные)
    new_state: dict | None = None


# ---------------------------------------------------------------------------
# Базовый класс
# ---------------------------------------------------------------------------

class BaseScript:
    """Базовый скрипт. Переопределяйте process()."""

    script_type: ScriptType = ScriptType.NONE

    def start(self) -> ScriptResponse:
        """Первое сообщение скрипта (после покупки)."""
        raise NotImplementedError

    def process(self, state: dict, user_message: str) -> ScriptResponse:
        """Обработать сообщение покупателя.
        state — текущее состояние из БД.
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Spotify
# ---------------------------------------------------------------------------

class SpotifyScript(BaseScript):
    script_type = ScriptType.SPOTIFY

    def start(self) -> ScriptResponse:
        return ScriptResponse(
            message_ru="🧡 Для выполнения заказа, отправьте вашу почту, привязанную к Spotify 🍂",
            message_en="🧡 To place an order, please send us your email address linked to Spotify 🍂",
            new_state={"step": "wait_email", "data": {}}
        )

    def process(self, state: dict, user_message: str) -> ScriptResponse:
        step = state.get("step", "wait_email")
        data = state.get("data", {})

        if step == "wait_email":
            msg = user_message.strip()
            if not EMAIL_RE.match(msg):
                return ScriptResponse(
                    message_ru=(
                        "❓️ Кажется, это не почта…\n\n"
                        "Чтобы я смог выполнить заказ, мне понадобится твоя почта, "
                        "на которую зарегистрирован Spotify в таком формате: example@example.com"
                    ),
                    message_en=(
                        "❓️ It seems this isn't an email address…\n\n"
                        "To complete the order, I'll need your email address, "
                        "which Spotify is registered to, in this format: example@example.com"
                    ),
                    new_state=state
                )
            data["email"] = msg
            return ScriptResponse(
                message_ru=(
                    "🥮 Отлично. Мне так же понадобится пароль от твоего аккаунта Spotify, "
                    "чтобы я смог приобрести на него подписку"
                ),
                message_en=(
                    "🥮 Great. I'll also need your Spotify account password "
                    "so I can purchase a subscription."
                ),
                new_state={"step": "wait_password", "data": data}
            )

        if step == "wait_password":
            data["password"] = user_message.strip()
            return ScriptResponse(
                message_ru=(
                    f"🍁 Перед тем, как я начну выполнение заказа, проверь данные:\n\n"
                    f"Почта: {data['email']}\n"
                    f"Пароль: {data['password']}\n\n"
                    f"🍂 Если данные верны, напиши +; Если данные неверны, напиши -"
                ),
                message_en=(
                    f"🍁 Before I start fulfilling your order, please check the details:\n\n"
                    f"Email: {data['email']}\n"
                    f"Password: {data['password']}\n\n"
                    f"🍂 If the data is correct, write +; If the data is incorrect, write -"
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
                # Рестарт
                return self.start()
            else:
                return ScriptResponse(
                    message_ru="🍂 Напишите + если данные верны, или - если нет.",
                    message_en="🍂 Write + if the data is correct, or - if not.",
                    new_state=state
                )

        return ScriptResponse(
            message_ru="⏳ Ожидайте, продавец скоро приступит к заказу.",
            message_en="⏳ Please wait, the seller will process your order soon.",
            new_state=state
        )


# ---------------------------------------------------------------------------
# Discord Nitro
# ---------------------------------------------------------------------------

class DiscordNitroScript(BaseScript):
    script_type = ScriptType.DISCORD_NITRO

    def start(self) -> ScriptResponse:
        return ScriptResponse(
            message_ru="🎮 Для выполнения заказа, отправьте вашу почту, привязанную к Discord",
            message_en="🎮 To fulfill your order, please send your email address linked to Discord",
            new_state={"step": "wait_email", "data": {}}
        )

    def process(self, state: dict, user_message: str) -> ScriptResponse:
        step = state.get("step", "wait_email")
        data = state.get("data", {})

        if step == "wait_email":
            msg = user_message.strip()
            if not EMAIL_RE.match(msg):
                return ScriptResponse(
                    message_ru=(
                        "❓️ Кажется, это не почта…\n\n"
                        "Мне понадобится почта вашего Discord-аккаунта в формате: example@example.com"
                    ),
                    message_en=(
                        "❓️ It seems this isn't an email address…\n\n"
                        "I need your Discord account email in this format: example@example.com"
                    ),
                    new_state=state
                )
            data["email"] = msg
            return ScriptResponse(
                message_ru="🔑 Отлично. Теперь отправьте пароль от вашего Discord-аккаунта",
                message_en="🔑 Great. Now please send your Discord account password",
                new_state={"step": "wait_password", "data": data}
            )

        if step == "wait_password":
            data["password"] = user_message.strip()
            return ScriptResponse(
                message_ru=(
                    "🔐 Если на вашем аккаунте включена двухфакторная аутентификация (2FA), "
                    "отправьте код подтверждения.\n\n"
                    "Если 2FA не включена, напишите: нет"
                ),
                message_en=(
                    "🔐 If your account has two-factor authentication (2FA) enabled, "
                    "please send the verification code.\n\n"
                    "If 2FA is not enabled, write: no"
                ),
                new_state={"step": "wait_2fa", "data": data}
            )

        if step == "wait_2fa":
            msg = user_message.strip().lower()
            if msg not in ("нет", "no"):
                data["2fa_code"] = user_message.strip()
            return ScriptResponse(
                message_ru=(
                    f"📋 Проверьте данные:\n\n"
                    f"Почта: {data['email']}\n"
                    f"Пароль: {data['password']}\n"
                    f"2FA: {data.get('2fa_code', 'нет')}\n\n"
                    f"Если верно — напишите +, если нет — напишите -"
                ),
                message_en=(
                    f"📋 Check the details:\n\n"
                    f"Email: {data['email']}\n"
                    f"Password: {data['password']}\n"
                    f"2FA: {data.get('2fa_code', 'no')}\n\n"
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
# ChatGPT
# ---------------------------------------------------------------------------

class ChatGPTScript(BaseScript):
    script_type = ScriptType.CHATGPT

    def start(self) -> ScriptResponse:
        return ScriptResponse(
            message_ru="🤖 Для выполнения заказа, отправьте вашу почту от аккаунта ChatGPT (OpenAI)",
            message_en="🤖 To fulfill your order, please send your ChatGPT (OpenAI) account email",
            new_state={"step": "wait_email", "data": {}}
        )

    def process(self, state: dict, user_message: str) -> ScriptResponse:
        step = state.get("step", "wait_email")
        data = state.get("data", {})

        if step == "wait_email":
            msg = user_message.strip()
            if not EMAIL_RE.match(msg):
                return ScriptResponse(
                    message_ru=(
                        "❓️ Кажется, это не почта…\n\n"
                        "Мне понадобится почта вашего аккаунта OpenAI в формате: example@example.com"
                    ),
                    message_en=(
                        "❓️ It seems this isn't an email address…\n\n"
                        "I need your OpenAI account email in this format: example@example.com"
                    ),
                    new_state=state
                )
            data["email"] = msg
            return ScriptResponse(
                message_ru="🔑 Отлично. Теперь отправьте пароль от вашего аккаунта ChatGPT",
                message_en="🔑 Great. Now please send your ChatGPT account password",
                new_state={"step": "wait_password", "data": data}
            )

        if step == "wait_password":
            data["password"] = user_message.strip()
            return ScriptResponse(
                message_ru=(
                    f"📋 Проверьте данные:\n\n"
                    f"Почта: {data['email']}\n"
                    f"Пароль: {data['password']}\n\n"
                    f"Если верно — напишите +, если нет — напишите -"
                ),
                message_en=(
                    f"📋 Check the details:\n\n"
                    f"Email: {data['email']}\n"
                    f"Password: {data['password']}\n\n"
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
# Telegram Premium (1 мес) — нужен логин+пароль+облачный пароль
# ---------------------------------------------------------------------------

class TelegramPremium1MScript(BaseScript):
    script_type = ScriptType.TELEGRAM_PREMIUM_1M

    def start(self) -> ScriptResponse:
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

    def process(self, state: dict, user_message: str) -> ScriptResponse:
        step = state.get("step", "wait_phone")
        data = state.get("data", {})

        if step == "wait_phone":
            msg = user_message.strip()
            # Простая проверка телефона
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

    def start(self) -> ScriptResponse:
        return ScriptResponse(
            message_ru=f"💎 Для выполнения заказа, отправьте ваш username в Telegram (например, @username)",
            message_en=f"💎 To fulfill your order, please send your Telegram username (e.g., @username)",
            new_state={"step": "wait_username", "data": {}}
        )

    def process(self, state: dict, user_message: str) -> ScriptResponse:
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
    ScriptType.TELEGRAM_PREMIUM_1M: TelegramPremium1MScript(),
    ScriptType.TELEGRAM_PREMIUM_LONG: TelegramPremiumLongScript(),
    ScriptType.TELEGRAM_STARS: TelegramStarsScript(),
}


def get_script(script_type: ScriptType) -> Optional[BaseScript]:
    return SCRIPTS.get(script_type)


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
