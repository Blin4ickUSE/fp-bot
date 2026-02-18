"""
Telegram-бот для уведомлений и управления.
Использует python-telegram-bot (v20+).
"""
from __future__ import annotations

import logging
import asyncio
import threading
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters,
)

from ..backend.config import TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_ID, WEBAPP_URL
from ..backend.database import get_session, Order, OrderStatus

logger = logging.getLogger("bot.telegram")


class TelegramNotifier:
    """Отправка уведомлений администратору."""

    def __init__(self):
        self.application: Optional[Application] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def init(self):
        """Инициализация бота."""
        if not TELEGRAM_BOT_TOKEN:
            logger.warning("TELEGRAM_BOT_TOKEN не задан, бот не будет работать.")
            return

        self.application = (
            Application.builder()
            .token(TELEGRAM_BOT_TOKEN)
            .build()
        )

        # Команды
        self.application.add_handler(CommandHandler("start", self._cmd_start))
        self.application.add_handler(CommandHandler("orders", self._cmd_orders))
        self.application.add_handler(CommandHandler("stats", self._cmd_stats))
        self.application.add_handler(CommandHandler("help", self._cmd_help))
        self.application.add_handler(CallbackQueryHandler(self._callback_handler))

    def start(self):
        """Запуск бота в отдельном потоке."""
        if not self.application:
            return

        def _run():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._run_bot())

        t = threading.Thread(target=_run, daemon=True, name="TelegramBot")
        t.start()
        logger.info("Telegram-бот запущен.")

    async def _run_bot(self):
        """Запускает polling."""
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling(drop_pending_updates=True)

        # Ожидаем вечно
        stop_event = asyncio.Event()
        await stop_event.wait()

    def send_notification(self, text: str):
        """Отправляет уведомление админу (thread-safe)."""
        if not self.application or not TELEGRAM_ADMIN_ID:
            return

        async def _send():
            try:
                await self.application.bot.send_message(
                    chat_id=TELEGRAM_ADMIN_ID,
                    text=text,
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление: {e}")

        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(_send(), self._loop)
        else:
            # Фоллбэк, если цикл ещё не запущен
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(_send())
                loop.close()
            except Exception as e:
                logger.error(f"Фоллбэк отправки: {e}")

    # ------------------------------------------------------------------
    # Команды
    # ------------------------------------------------------------------

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != TELEGRAM_ADMIN_ID:
            await update.message.reply_text("⛔ Доступ запрещён.")
            return

        keyboard = []
        if WEBAPP_URL:
            keyboard.append([
                InlineKeyboardButton(
                    "📱 Открыть панель управления",
                    web_app=WebAppInfo(url=WEBAPP_URL)
                )
            ])
        keyboard.append([
            InlineKeyboardButton("📦 Заказы", callback_data="orders"),
            InlineKeyboardButton("📊 Статистика", callback_data="stats"),
        ])

        await update.message.reply_text(
            "🦊 <b>FunPay Manager</b>\n\n"
            "Добро пожаловать! Используйте кнопки ниже или команды:\n"
            "/orders — список заказов\n"
            "/stats — статистика\n"
            "/help — помощь",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )

    async def _cmd_orders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != TELEGRAM_ADMIN_ID:
            return

        with get_session() as session:
            active_orders = session.query(Order).filter(
                Order.status.in_([
                    OrderStatus.WAITING_DATA,
                    OrderStatus.DATA_COLLECTED,
                    OrderStatus.IN_PROGRESS,
                ])
            ).order_by(Order.created_at.desc()).limit(20).all()

            if not active_orders:
                await update.message.reply_text("📭 Нет активных заказов.")
                return

            text = "📦 <b>Активные заказы:</b>\n\n"
            for o in active_orders:
                status_emoji = {
                    OrderStatus.WAITING_DATA: "⏳",
                    OrderStatus.DATA_COLLECTED: "📥",
                    OrderStatus.IN_PROGRESS: "🔄",
                }.get(o.status, "❔")
                text += (
                    f"{status_emoji} <b>#{o.funpay_order_id}</b>\n"
                    f"  👤 {o.buyer_username}\n"
                    f"  📦 {o.item_name}\n"
                    f"  💰 {o.price} {o.currency}\n"
                    f"  📋 {o.status.value}\n\n"
                )

        keyboard = []
        if WEBAPP_URL:
            keyboard.append([
                InlineKeyboardButton(
                    "📱 Управление в приложении",
                    web_app=WebAppInfo(url=WEBAPP_URL)
                )
            ])

        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
            parse_mode="HTML",
        )

    async def _cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != TELEGRAM_ADMIN_ID:
            return

        with get_session() as session:
            total = session.query(Order).count()
            active = session.query(Order).filter(
                Order.status.in_([OrderStatus.WAITING_DATA, OrderStatus.DATA_COLLECTED, OrderStatus.IN_PROGRESS])
            ).count()
            completed = session.query(Order).filter(Order.status == OrderStatus.COMPLETED).count()
            confirmed = session.query(Order).filter(Order.status == OrderStatus.CONFIRMED).count()
            refunded = session.query(Order).filter(Order.status == OrderStatus.REFUNDED).count()

        text = (
            "📊 <b>Статистика</b>\n\n"
            f"📦 Всего заказов: <b>{total}</b>\n"
            f"🔄 Активных: <b>{active}</b>\n"
            f"✅ Выполненных: <b>{completed}</b>\n"
            f"☑️ Подтверждённых: <b>{confirmed}</b>\n"
            f"↩️ Возвратов: <b>{refunded}</b>"
        )

        await update.message.reply_text(text, parse_mode="HTML")

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != TELEGRAM_ADMIN_ID:
            return

        await update.message.reply_text(
            "🦊 <b>FunPay Manager — Помощь</b>\n\n"
            "<b>Команды:</b>\n"
            "/start — главное меню\n"
            "/orders — активные заказы\n"
            "/stats — статистика\n"
            "/help — эта справка\n\n"
            "<b>Уведомления:</b>\n"
            "Бот автоматически присылает уведомления о:\n"
            "• Новых заказах\n"
            "• Собранных данных от покупателей\n"
            "• Изменениях статусов\n"
            "• Подтверждениях и возвратах\n\n"
            "<b>Мини-приложение:</b>\n"
            "Для полного управления используйте мини-приложение (кнопка в /start).",
            parse_mode="HTML",
        )

    async def _callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        if query.data == "orders":
            # Вызываем логику /orders
            with get_session() as session:
                active_orders = session.query(Order).filter(
                    Order.status.in_([
                        OrderStatus.WAITING_DATA,
                        OrderStatus.DATA_COLLECTED,
                        OrderStatus.IN_PROGRESS,
                    ])
                ).order_by(Order.created_at.desc()).limit(10).all()

                if not active_orders:
                    await query.edit_message_text("📭 Нет активных заказов.")
                    return

                text = "📦 <b>Активные заказы:</b>\n\n"
                for o in active_orders:
                    status_emoji = {
                        OrderStatus.WAITING_DATA: "⏳",
                        OrderStatus.DATA_COLLECTED: "📥",
                        OrderStatus.IN_PROGRESS: "🔄",
                    }.get(o.status, "❔")
                    text += (
                        f"{status_emoji} <b>#{o.funpay_order_id}</b> — "
                        f"{o.buyer_username} — {o.item_name}\n"
                    )

            await query.edit_message_text(text, parse_mode="HTML")

        elif query.data == "stats":
            with get_session() as session:
                total = session.query(Order).count()
                active = session.query(Order).filter(
                    Order.status.in_([OrderStatus.WAITING_DATA, OrderStatus.DATA_COLLECTED, OrderStatus.IN_PROGRESS])
                ).count()
                completed = session.query(Order).filter(Order.status == OrderStatus.COMPLETED).count()

            await query.edit_message_text(
                f"📊 Всего: {total} | Активных: {active} | Выполненных: {completed}",
                parse_mode="HTML",
            )
