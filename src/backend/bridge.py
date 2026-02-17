"""
FunPay Bridge — связывает FunPayAPI (события, чаты, заказы)
с нашей базой данных, скриптами и Telegram-ботом.
"""
from __future__ import annotations

import logging
import threading
import time
import datetime
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..bot.telegram_bot import TelegramNotifier

import FunPayAPI
from FunPayAPI.account import Account
from FunPayAPI.updater.runner import Runner
from FunPayAPI.updater import events as fp_events
from FunPayAPI.common.enums import MessageTypes, OrderStatuses, EventTypes

from .config import FUNPAY_GOLDEN_KEY, FUNPAY_USER_AGENT
from .database import (
    get_session, Order, OrderStatus, ScriptType, LotConfig,
    AutomationSettings, StatsSnapshot,
)
from .scripts import get_script, STATUS_MESSAGES

logger = logging.getLogger("backend.bridge")


class FunPayBridge:
    """
    Мост между FunPayAPI и нашим бэкендом.
    Запускается в отдельных потоках:
    - runner.loop()    — обработка очереди запросов
    - runner.listen()  — прослушивание событий
    - _background_tasks() — вечный онлайн, автоподнятие и т.д.
    """

    def __init__(self):
        self.account: Optional[Account] = None
        self.runner: Optional[Runner] = None
        self.telegram: Optional[TelegramNotifier] = None
        self.is_running: bool = False
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []

    # ------------------------------------------------------------------
    # Инициализация
    # ------------------------------------------------------------------

    def init_account(self) -> Account:
        """Инициализирует аккаунт FunPay."""
        logger.info("Инициализация аккаунта FunPay...")
        self.account = Account(
            golden_key=FUNPAY_GOLDEN_KEY,
            user_agent=FUNPAY_USER_AGENT,
        )
        self.account.get()
        logger.info(f"Авторизован как: {self.account.username} (ID: {self.account.id})")
        return self.account

    def start(self):
        """Запуск всех потоков."""
        if self.is_running:
            return
        self.is_running = True
        self._stop_event.clear()

        # Создаём Runner
        self.runner = Runner(self.account, disable_message_requests=False,
                             disabled_order_requests=False)

        # Поток runner.loop() — обработка очереди запросов
        t_loop = threading.Thread(target=self.runner.loop, daemon=True, name="RunnerLoop")
        t_loop.start()
        self._threads.append(t_loop)

        # Поток прослушивания событий
        t_listen = threading.Thread(target=self._event_listener, daemon=True, name="EventListener")
        t_listen.start()
        self._threads.append(t_listen)

        # Фоновые задачи (вечный онлайн, автоподнятие)
        t_bg = threading.Thread(target=self._background_tasks, daemon=True, name="BackgroundTasks")
        t_bg.start()
        self._threads.append(t_bg)

        logger.info("FunPay Bridge запущен.")

    def stop(self):
        self.is_running = False
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Прослушивание событий
    # ------------------------------------------------------------------

    def _event_listener(self):
        """Слушает события от FunPay Runner."""
        logger.info("Event listener запущен.")
        for event in self.runner.listen(requests_delay=6.0, ignore_exceptions=True):
            if self._stop_event.is_set():
                break
            try:
                self._handle_event(event)
            except Exception as e:
                logger.error(f"Ошибка обработки события: {e}", exc_info=True)

    def _handle_event(self, event):
        """Обрабатывает одно событие."""

        # Новый заказ
        if isinstance(event, fp_events.NewOrderEvent):
            self._on_new_order(event)

        # Статус заказа изменился
        elif isinstance(event, fp_events.OrderStatusChangedEvent):
            self._on_order_status_changed(event)

        # Новое сообщение
        elif isinstance(event, fp_events.NewMessageEvent):
            self._on_new_message(event)

    # ------------------------------------------------------------------
    # Обработка нового заказа
    # ------------------------------------------------------------------

    def _on_new_order(self, event: fp_events.NewOrderEvent):
        order_shortcut = event.order
        logger.info(f"Новый заказ: #{order_shortcut.id} от {order_shortcut.buyer_username}")

        # Определяем тип скрипта на основе конфигурации лотов
        script_type = self._match_script_type(order_shortcut.description or "")

        # Определяем язык покупателя
        buyer_lang = self._detect_buyer_language(order_shortcut)

        # Создаём запись в БД
        with get_session() as session:
            existing = session.query(Order).filter(
                Order.funpay_order_id == order_shortcut.id
            ).first()
            if existing:
                return  # Уже обработан

            db_order = Order(
                funpay_order_id=order_shortcut.id,
                buyer_username=order_shortcut.buyer_username,
                buyer_id=order_shortcut.buyer_id,
                chat_id=str(order_shortcut.chat_id),
                item_name=order_shortcut.description or "Unknown",
                price=order_shortcut.price,
                currency=str(order_shortcut.currency),
                status=OrderStatus.WAITING_DATA if script_type != ScriptType.NONE else OrderStatus.DATA_COLLECTED,
                script_type=script_type,
                buyer_lang=buyer_lang,
            )
            session.add(db_order)
            session.commit()

        # Уведомление в Telegram
        self.notify_telegram(
            f"🆕 Новый заказ #{order_shortcut.id}\n"
            f"Покупатель: {order_shortcut.buyer_username}\n"
            f"Товар: {order_shortcut.description}\n"
            f"Цена: {order_shortcut.price} {order_shortcut.currency}\n"
            f"Скрипт: {script_type.value}"
        )

        # Если есть скрипт — запускаем его
        if script_type != ScriptType.NONE:
            script = get_script(script_type)
            if script:
                response = script.start()
                msg = response.message_ru if buyer_lang == "ru" else response.message_en
                self._send_fp_message(str(order_shortcut.chat_id), msg)
                # Обновляем состояние скрипта
                with get_session() as session:
                    db_order = session.query(Order).filter(
                        Order.funpay_order_id == order_shortcut.id
                    ).first()
                    if db_order and response.new_state:
                        db_order.set_script_state(response.new_state)
                        session.commit()

    # ------------------------------------------------------------------
    # Обработка изменения статуса заказа
    # ------------------------------------------------------------------

    def _on_order_status_changed(self, event: fp_events.OrderStatusChangedEvent):
        order_shortcut = event.order
        logger.info(f"Статус заказа #{order_shortcut.id} изменён: {order_shortcut.status}")

        with get_session() as session:
            db_order = session.query(Order).filter(
                Order.funpay_order_id == order_shortcut.id
            ).first()
            if not db_order:
                return

            # Если FunPay показывает статус CLOSED — покупатель подтвердил
            if order_shortcut.status == OrderStatuses.CLOSED:
                if db_order.status not in (OrderStatus.REFUNDED,):
                    db_order.status = OrderStatus.CONFIRMED
                    session.commit()

                    # Уведомление в Telegram
                    self.notify_telegram(
                        f"✅ Заказ #{order_shortcut.id} подтверждён покупателем!"
                    )

                    # Отправляем напоминание об отзыве
                    settings = session.query(AutomationSettings).first()
                    if settings and settings.review_reminder:
                        self._schedule_review_reminder(db_order, settings)

            elif order_shortcut.status == OrderStatuses.REFUNDED:
                db_order.status = OrderStatus.REFUNDED
                session.commit()
                self.notify_telegram(
                    f"💸 Возврат по заказу #{order_shortcut.id}"
                )

            # Если заказ открыт повторно (спор)
            elif order_shortcut.status == OrderStatuses.PAID:
                if db_order.status == OrderStatus.CONFIRMED:
                    db_order.status = OrderStatus.DISPUTE
                    session.commit()
                    self.notify_telegram(
                        f"⚠️ Заказ #{order_shortcut.id} открыт повторно (возможно спор)!\n"
                        f"Покупатель: {order_shortcut.buyer_username}"
                    )

    # ------------------------------------------------------------------
    # Обработка нового сообщения
    # ------------------------------------------------------------------

    def _on_new_message(self, event: fp_events.NewMessageEvent):
        message = event.message

        # Пропускаем системные сообщения и свои сообщения
        if message.author_id == self.account.id:
            return
        if message.by_bot:
            return
        if message.type and message.type != MessageTypes.NON_SYSTEM:
            # Обрабатываем системное сообщение "покупатель подтвердил"
            if message.type == MessageTypes.ORDER_CONFIRMED:
                self._handle_order_confirmed_message(message)
            return

        # Ищем активный заказ от этого покупателя, ожидающий данных
        chat_id = str(message.chat_id)
        with get_session() as session:
            db_order = session.query(Order).filter(
                Order.chat_id == chat_id,
                Order.status == OrderStatus.WAITING_DATA,
            ).order_by(Order.created_at.desc()).first()

            if not db_order:
                return  # Нет активного скрипта для этого чата

            script = get_script(db_order.script_type)
            if not script:
                return

            state = db_order.get_script_state()
            if state.get("step") == "done":
                return  # Скрипт уже завершён

            response = script.process(state, message.text or "")

            # Отправляем ответ
            msg = response.message_ru if db_order.buyer_lang == "ru" else response.message_en
            self._send_fp_message(chat_id, msg)

            # Обновляем состояние
            if response.new_state:
                db_order.set_script_state(response.new_state)

            if response.finished:
                db_order.status = OrderStatus.DATA_COLLECTED
                # Сохраняем собранные данные
                data = response.new_state.get("data", {}) if response.new_state else {}
                db_order.set_collected_data(data)
                session.commit()

                # Уведомление в Telegram
                data_text = "\n".join(f"  {k}: {v}" for k, v in data.items())
                self.notify_telegram(
                    f"📥 Данные собраны для заказа #{db_order.funpay_order_id}\n"
                    f"Покупатель: {db_order.buyer_username}\n"
                    f"Товар: {db_order.item_name}\n"
                    f"Данные:\n{data_text}"
                )
            else:
                session.commit()

    def _handle_order_confirmed_message(self, message):
        """Обработка системного сообщения о подтверждении заказа."""
        # Ищем ID заказа в тексте сообщения
        import re
        if not message.text:
            return
        match = re.search(r"#([A-Z0-9]{8})", message.text)
        if not match:
            return
        order_id = match.group(1)

        with get_session() as session:
            db_order = session.query(Order).filter(
                Order.funpay_order_id == order_id
            ).first()
            if db_order and db_order.status not in (OrderStatus.REFUNDED,):
                db_order.status = OrderStatus.CONFIRMED
                session.commit()

                settings = session.query(AutomationSettings).first()
                if settings and settings.review_reminder:
                    self._schedule_review_reminder(db_order, settings)

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def _match_script_type(self, description: str) -> ScriptType:
        """Определяет тип скрипта по описанию заказа, сверяя с конфигурацией лотов."""
        with get_session() as session:
            configs = session.query(LotConfig).all()
            desc_lower = description.lower()
            for config in configs:
                if config.lot_name_pattern.lower() in desc_lower:
                    return config.script_type
        return ScriptType.NONE

    def _detect_buyer_language(self, order_shortcut) -> str:
        """Определяет язык покупателя.
        Используем описание заказа или профиль.
        """
        # Простая эвристика: если в описании есть кириллица — ru, иначе en
        desc = order_shortcut.description or ""
        cyrillic_count = sum(1 for c in desc if '\u0400' <= c <= '\u04ff')
        if cyrillic_count > len(desc) * 0.3:
            return "ru"
        # Попробуем определить по locale аккаунта (если доступно через чат)
        return "ru"  # По умолчанию

    def _send_fp_message(self, chat_id: str, text: str):
        """Отправляет сообщение через FunPay."""
        try:
            self.account.send_message(
                chat_id=chat_id,
                text=text,
                add_to_ignore_list=True,
                update_last_saved_message=True,
            )
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения в чат {chat_id}: {e}")

    def send_status_message(self, chat_id: str, status_key: str, lang: str = "ru"):
        """Отправить сообщение о статусе заказа покупателю."""
        messages = STATUS_MESSAGES.get(status_key, {})
        msg = messages.get(lang, messages.get("ru", ""))
        if msg:
            self._send_fp_message(chat_id, msg)

    def do_refund(self, funpay_order_id: str):
        """Выполнить возврат средств через FunPay."""
        try:
            self.account.refund(funpay_order_id)
            logger.info(f"Возврат по заказу {funpay_order_id} выполнен.")
        except Exception as e:
            logger.error(f"Ошибка возврата по заказу {funpay_order_id}: {e}")
            raise

    def notify_telegram(self, text: str):
        """Отправить уведомление в Telegram."""
        if self.telegram:
            try:
                self.telegram.send_notification(text)
            except Exception as e:
                logger.error(f"Ошибка отправки в Telegram: {e}")

    def _schedule_review_reminder(self, db_order: Order, settings: AutomationSettings):
        """Планирует отправку напоминания об отзыве."""
        delay_minutes = settings.review_delay_minutes or 1440

        def _send_reminder():
            time.sleep(delay_minutes * 60)
            lang = db_order.buyer_lang or "ru"
            self.send_status_message(db_order.chat_id, "review_reminder", lang)
            logger.info(f"Напоминание об отзыве отправлено для #{db_order.funpay_order_id}")

        t = threading.Thread(target=_send_reminder, daemon=True,
                             name=f"ReviewReminder-{db_order.funpay_order_id}")
        t.start()

    # ------------------------------------------------------------------
    # Фоновые задачи
    # ------------------------------------------------------------------

    def _background_tasks(self):
        """Фоновые задачи: вечный онлайн, автоподнятие, снимки статистики."""
        last_online_time = 0
        last_bump_time = 0
        last_stats_time = 0
        ONLINE_INTERVAL = 60 * 4       # каждые 4 минуты обновляем аккаунт
        BUMP_INTERVAL = 60 * 60 * 4    # каждые 4 часа автоподнятие
        STATS_INTERVAL = 60 * 60       # каждый час снимок статистики

        while not self._stop_event.is_set():
            try:
                now = time.time()

                with get_session() as session:
                    settings = session.query(AutomationSettings).first()

                # Вечный онлайн
                if settings and settings.eternal_online and (now - last_online_time > ONLINE_INTERVAL):
                    try:
                        self.account.get()
                        last_online_time = now
                        logger.debug("Вечный онлайн: аккаунт обновлён.")
                    except Exception as e:
                        logger.error(f"Ошибка вечного онлайна: {e}")

                # Автоподнятие лотов
                if settings and settings.auto_bump and (now - last_bump_time > BUMP_INTERVAL):
                    try:
                        categories = self.account.get_categories()
                        for cat in categories:
                            try:
                                self.account.raise_lots(cat.id)
                                logger.info(f"Лоты категории {cat.name} подняты.")
                            except Exception as e:
                                logger.warning(f"Не удалось поднять {cat.name}: {e}")
                        last_bump_time = now
                    except Exception as e:
                        logger.error(f"Ошибка автоподнятия: {e}")

                # Снимок статистики
                if now - last_stats_time > STATS_INTERVAL:
                    try:
                        self._save_stats_snapshot()
                        last_stats_time = now
                    except Exception as e:
                        logger.error(f"Ошибка снимка статистики: {e}")

            except Exception as e:
                logger.error(f"Ошибка в фоновых задачах: {e}", exc_info=True)

            self._stop_event.wait(30)  # Проверяем каждые 30 секунд

    def _save_stats_snapshot(self):
        """Сохраняет снимок статистики."""
        with get_session() as session:
            total = session.query(Order).count()
            active = session.query(Order).filter(
                Order.status.in_([OrderStatus.WAITING_DATA, OrderStatus.DATA_COLLECTED, OrderStatus.IN_PROGRESS])
            ).count()

            balance_rub = 0.0
            balance_usd = 0.0
            balance_eur = 0.0
            if self.account and self.account.total_balance:
                # Примерно — точный баланс по валютам можно получить через get_balance
                balance_rub = float(self.account.total_balance)

            snapshot = StatsSnapshot(
                total_orders=total,
                active_orders=active,
                balance_rub=balance_rub,
                balance_usd=balance_usd,
                balance_eur=balance_eur,
            )
            session.add(snapshot)
            session.commit()
