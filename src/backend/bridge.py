"""
FunPay Bridge — связывает FunPayAPI (события, чаты, заказы)
с нашей базой данных, скриптами и Telegram-ботом.
"""
from __future__ import annotations

import json
import logging
import re
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

# URL чата FunPay (node = chat_id)
FUNPAY_CHAT_URL_TEMPLATE = "https://funpay.com/chat/?node={chat_id}"

from bs4 import BeautifulSoup

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

        # Синхронизация существующих заказов при старте
        self._sync_existing_orders()

        # Предзагрузка лотов в кэш (в фоне)
        threading.Thread(target=self._preload_funpay_lots, daemon=True, name="PreloadLots").start()

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
        script_type, lot_config_id = self._match_script_type(order_shortcut)

        # Язык покупателя — из FunPay API (страница чата), иначе по описанию заказа
        buyer_lang = self._get_buyer_lang_from_funpay_api(order_shortcut.chat_id)
        if not buyer_lang:
            buyer_lang = self._detect_buyer_language(order_shortcut)

        # Получаем название товара
        item_name = getattr(order_shortcut, 'description', None) or \
                   getattr(order_shortcut, 'short_description', None) or \
                   getattr(order_shortcut, 'full_description', None) or "Unknown"

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
                item_name=item_name,
                price=order_shortcut.price,
                currency=str(order_shortcut.currency),
                status=OrderStatus.WAITING_DATA if script_type != ScriptType.NONE else OrderStatus.DATA_COLLECTED,
                script_type=script_type,
                lot_config_id=lot_config_id,
                buyer_lang=buyer_lang,
            )
            session.add(db_order)
            session.commit()

        # Уведомление в Telegram
        self.notify_telegram(
            f"🆕 Новый заказ #{order_shortcut.id}\n"
            f"Покупатель: {order_shortcut.buyer_username}\n"
            f"Товар: {item_name}\n"
            f"Цена: {order_shortcut.price} {order_shortcut.currency}\n"
            f"Скрипт: {script_type.value}"
        )

        # Если есть скрипт — запускаем его
        if script_type != ScriptType.NONE:
            script = get_script(script_type)
            if script:
                custom_text = {}
                if lot_config_id:
                    with get_session() as session:
                        lot_config = session.query(LotConfig).filter(LotConfig.id == lot_config_id).first()
                        if lot_config:
                            custom_text = lot_config.get_script_custom_text() or {}
                response = script.start(custom_text=custom_text)
                msg = response.message_ru if buyer_lang == "ru" else response.message_en
                if (msg or "").strip():
                    self._send_fp_message(str(order_shortcut.chat_id), msg)
                    logger.info(f"Скрипт start: отправлено сообщение в чат {order_shortcut.chat_id}")
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

                    # Уведомление о подтверждении не отправляем (п.7)

                    # Отправляем напоминание об отзыве
                    settings = session.query(AutomationSettings).first()
                    if settings and settings.review_reminder:
                        self._schedule_review_reminder(db_order, settings)

            elif order_shortcut.status == OrderStatuses.REFUNDED:
                db_order.status = OrderStatus.REFUNDED
                session.commit()
                # Уведомление о возврате не отправляем (п.7)

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
            if message.type == MessageTypes.ORDER_CONFIRMED:
                self._handle_order_confirmed_message(message)
            elif message.type in (MessageTypes.NEW_FEEDBACK, MessageTypes.FEEDBACK_CHANGED):
                self._handle_review_message(message)
            return

        # Ищем активный заказ от этого покупателя, ожидающий данных
        chat_id = str(message.chat_id)
        author_id = getattr(message, "author_id", None) or getattr(message, "interlocutor_id", None)
        with get_session() as session:
            db_order = session.query(Order).filter(
                Order.chat_id == chat_id,
                Order.status == OrderStatus.WAITING_DATA,
            ).order_by(Order.created_at.desc()).first()
            if not db_order and author_id:
                db_order = session.query(Order).filter(
                    Order.buyer_id == int(author_id),
                    Order.status == OrderStatus.WAITING_DATA,
                ).order_by(Order.created_at.desc()).first()

            if not db_order:
                # Нет активного скрипта — уведомляем о новом сообщении и предлагаем перейти в чат
                if not message.type or message.type == MessageTypes.NON_SYSTEM:
                    author = getattr(message, 'author_name', None) or getattr(message, 'chat_name', None) or "Покупатель"
                    link = FUNPAY_CHAT_URL_TEMPLATE.format(chat_id=chat_id)
                    self.notify_telegram(
                        f"💬 Вам написали на FunPay!\n\n"
                        f"От: {author}\n\n"
                        f"Перейти в чат: {link}"
                    )
                return

            script = get_script(db_order.script_type)
            if not script:
                return

            state = db_order.get_script_state()
            if state.get("step") == "done":
                # Скрипт завершён, но заказ ещё в сборе данных — не отправляем «Вам написали»
                return

            custom_text = {}
            if getattr(db_order, "lot_config_id", None):
                lot_config = session.query(LotConfig).filter(LotConfig.id == db_order.lot_config_id).first()
                if lot_config:
                    custom_text = lot_config.get_script_custom_text() or {}

            response = script.process(state, message.text or "", custom_text=custom_text)

            # Язык покупателя не меняем по тексту — он задаётся через FunPay API при создании заказа
            # Отправляем ответ на языке покупателя (если пусто — используем другой язык)
            msg = response.message_ru if db_order.buyer_lang == "ru" else response.message_en
            if not (msg or "").strip():
                msg = response.message_en if db_order.buyer_lang == "ru" else response.message_ru
            if (msg or "").strip():
                self._send_fp_message(chat_id, msg)
                logger.info(f"Скрипт ответ: отправлено в чат {chat_id}, шаг {state.get('step')}")

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

    def _get_my_rating(self) -> Optional[float]:
        """Получает текущий рейтинг продавца (из страницы профиля). Возвращает None при ошибке."""
        try:
            if not self.account:
                return None
            user = self.account.get_user(self.account.id)
            if not getattr(user, "html", None):
                return None
            from bs4 import BeautifulSoup
            parser = BeautifulSoup(user.html, "lxml")
            rating_el = parser.find("div", class_="rating-stars")
            if rating_el:
                stars = rating_el.find_all("i", class_="fas")
                if stars:
                    return float(len(stars))
            return None
        except Exception as e:
            logger.debug(f"Не удалось получить рейтинг: {e}")
            return None

    def _handle_review_message(self, message):
        """Уведомление об отзыве только если изменился общий рейтинг."""
        def _check_rating_changed():
            try:
                rating_before = self._get_my_rating()
                time.sleep(3)
                rating_after = self._get_my_rating()
                if rating_before is not None and rating_after is not None and rating_before != rating_after:
                    order_match = re.search(r"#([A-Z0-9]{8})", message.text or "")
                    order_id = order_match.group(1) if order_match else "?"
                    self.notify_telegram(
                        f"⭐ Изменился рейтинг! Был {rating_before}, стал {rating_after}\n"
                        f"Заказ #{order_id}"
                    )
            except Exception as e:
                logger.debug(f"Проверка рейтинга после отзыва: {e}")

        threading.Thread(target=_check_rating_changed, daemon=True, name="ReviewRatingCheck").start()

    def _handle_order_confirmed_message(self, message):
        """Обработка системного сообщения о подтверждении заказа."""
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
                # Напоминание об отзыве планируется только в _on_order_status_changed (CLOSED), не здесь,
                # чтобы не отправлять его дважды.

    # ------------------------------------------------------------------
    # Синхронизация существующих заказов
    # ------------------------------------------------------------------

    def _sync_existing_orders(self):
        """Синхронизирует существующие заказы из FunPay при старте."""
        try:
            logger.info("Синхронизация существующих заказов...")
            # Получаем активные заказы (paid = ожидающие выполнения)
            _, orders, _, _ = self.account.get_sales(
                include_paid=True,
                include_closed=False,
                include_refunded=False
            )
            
            synced = 0
            with get_session() as session:
                for order_shortcut in orders:
                    existing = session.query(Order).filter(
                        Order.funpay_order_id == order_shortcut.id
                    ).first()
                    if existing:
                        continue  # Уже есть в БД
                    
                    script_type, lot_config_id = self._match_script_type(order_shortcut)
                    buyer_lang = self._detect_buyer_language(order_shortcut)

                    if order_shortcut.status == OrderStatuses.PAID:
                        status = OrderStatus.WAITING_DATA if script_type != ScriptType.NONE else OrderStatus.DATA_COLLECTED
                    elif order_shortcut.status == OrderStatuses.CLOSED:
                        status = OrderStatus.CONFIRMED
                    elif order_shortcut.status == OrderStatuses.REFUNDED:
                        status = OrderStatus.REFUNDED
                    else:
                        status = OrderStatus.WAITING_DATA
                    
                    db_order = Order(
                        funpay_order_id=order_shortcut.id,
                        buyer_username=order_shortcut.buyer_username,
                        buyer_id=order_shortcut.buyer_id,
                        chat_id=str(order_shortcut.chat_id),
                        item_name=getattr(order_shortcut, 'description', None) or \
                              getattr(order_shortcut, 'short_description', None) or \
                              getattr(order_shortcut, 'full_description', None) or "Unknown",
                        price=order_shortcut.price,
                        currency=str(order_shortcut.currency),
                        status=status,
                        script_type=script_type,
                        lot_config_id=lot_config_id,
                        buyer_lang=buyer_lang,
                    )
                    session.add(db_order)
                    synced += 1
                
                session.commit()
            
            if synced > 0:
                logger.info(f"Синхронизировано {synced} существующих заказов.")
            else:
                logger.info("Новых заказов для синхронизации не найдено.")
        except Exception as e:
            logger.error(f"Ошибка синхронизации заказов: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def _match_script_type(self, order_shortcut) -> tuple[ScriptType, Optional[int]]:
        """Определяет тип скрипта по заказу: ключевые слова или паттерн в описании. Возвращает (script_type, lot_config_id)."""
        description = getattr(order_shortcut, 'description', None) or \
                     getattr(order_shortcut, 'short_description', None) or \
                     getattr(order_shortcut, 'full_description', None) or ""
        desc_lower = description.lower()

        with get_session() as session:
            configs = session.query(LotConfig).all()

            # 1) Совпадение по ключевым словам (приоритет)
            for config in configs:
                keywords = config.get_script_keywords()
                if keywords and any(kw in desc_lower for kw in keywords):
                    return config.script_type, config.id

            # 2) Точное совпадение по lot_id
            if hasattr(order_shortcut, 'lot_id') and order_shortcut.lot_id:
                for config in configs:
                    if config.lot_id and config.lot_id == order_shortcut.lot_id:
                        return config.script_type, config.id

            # 3) Паттерн в названии (обратная совместимость)
            for config in configs:
                if config.lot_name_pattern and config.lot_name_pattern.lower() in desc_lower:
                    return config.script_type, config.id

            return ScriptType.NONE, None

    def _get_buyer_lang_from_funpay_api(self, chat_id) -> Optional[str]:
        """Получает язык из FunPay API: запрашивает страницу чата и берёт locale из data-app-data."""
        try:
            if not self.account or not chat_id:
                return None
            chat = self.account.get_chat(int(chat_id), with_history=False)
            if not getattr(chat, "html_response", None):
                return None
            parser = BeautifulSoup(chat.html_response, "lxml")
            body = parser.find("body")
            if not body:
                return None
            app_data_str = body.get("data-app-data")
            if not app_data_str:
                return None
            app_data = json.loads(app_data_str)
            locale = app_data.get("locale")
            if locale in ("ru", "en", "uk"):
                return locale
            return None
        except Exception as e:
            logger.debug(f"Не удалось получить locale чата {chat_id} из FunPay API: {e}")
            return None

    def _detect_buyer_language(self, order_shortcut) -> str:
        """Определяет язык покупателя по описанию заказа (кириллица → ru, иначе en). Используется, если API не вернул locale."""
        desc = getattr(order_shortcut, 'description', None) or \
               getattr(order_shortcut, 'short_description', None) or \
               getattr(order_shortcut, 'full_description', None) or ""
        if desc:
            cyrillic_count = sum(1 for c in desc if '\u0400' <= c <= '\u04ff')
            if cyrillic_count > len(desc) * 0.2:
                return "ru"
            if cyrillic_count == 0 and len(desc) > 2:
                return "en"
        return "ru"

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
        """Планирует отправку напоминания об отзыве (задержка в секундах)."""
        delay_seconds = getattr(settings, 'review_delay_seconds', None) or 3

        def _send_reminder():
            time.sleep(delay_seconds)
            # Проверяем, что заказ всё ещё подтверждён (не возвращён)
            with get_session() as session:
                check_order = session.query(Order).filter(
                    Order.id == db_order.id
                ).first()
                if check_order and check_order.status == OrderStatus.CONFIRMED:
                    lang = check_order.buyer_lang or "ru"
                    msg_ru = (settings.review_message_ru or "").strip() or STATUS_MESSAGES.get("review_reminder", {}).get("ru", "")
                    msg_en = (settings.review_message_en or "").strip() or STATUS_MESSAGES.get("review_reminder", {}).get("en", "")
                    msg = msg_ru if lang == "ru" else msg_en
                    if msg:
                        self._send_fp_message(check_order.chat_id, msg)
                    logger.info(f"Напоминание об отзыве отправлено для #{check_order.funpay_order_id}")
                else:
                    logger.info(f"Напоминание об отзыве отменено для #{db_order.funpay_order_id} (заказ изменён)")

        t = threading.Thread(target=_send_reminder, daemon=True,
                             name=f"ReviewReminder-{db_order.funpay_order_id}")
        t.start()
    
    def _preload_funpay_lots(self):
        """Предзагрузка лотов FunPay в кэш."""
        try:
            import time as time_module
            from . import routes
            
            logger.info("Предзагрузка лотов FunPay...")
            account = self.account
            all_lots = []
            
            if hasattr(account, 'categories') and account.categories:
                for category in account.categories:
                    try:
                        subcategories = category.get_subcategories() if hasattr(category, 'get_subcategories') else []
                        for subcategory in subcategories:
                            try:
                                lots = account.get_my_subcategory_lots(subcategory.id)
                                for lot in lots:
                                    all_lots.append({
                                        "id": lot.id,
                                        "name": lot.description or f"Лот #{lot.id}",
                                        "subcategory_id": subcategory.id,
                                        "subcategory_name": subcategory.name or "",
                                        "category_name": category.name or "",
                                        "price": lot.price,
                                        "currency": str(lot.currency),
                                        "amount": lot.amount,
                                        "server": lot.server,
                                        "side": lot.side,
                                    })
                            except Exception as e:
                                logger.warning(f"Не удалось получить лоты для подкатегории {subcategory.id}: {e}")
                                continue
                    except Exception as e:
                        logger.warning(f"Ошибка при обработке категории: {e}")
                        continue
            
            sorted_lots = sorted(all_lots, key=lambda x: x.get("name", ""))
            routes._funpay_lots_cache = sorted_lots
            routes._funpay_lots_cache_time = time_module.time()
            logger.info(f"Предзагружено {len(sorted_lots)} лотов FunPay")
        except Exception as e:
            logger.error(f"Ошибка предзагрузки лотов: {e}", exc_info=True)

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

                # Вечный онлайн + обновление баланса
                if settings and settings.eternal_online and (now - last_online_time > ONLINE_INTERVAL):
                    try:
                        self.account.get()
                        last_online_time = now
                        logger.debug(f"Вечный онлайн: аккаунт обновлён. Баланс: {self.account.total_balance or 0} {self.account.currency}")
                    except Exception as e:
                        logger.error(f"Ошибка вечного онлайна: {e}")

                # Автоподнятие лотов только в тех категориях/подкатегориях, где есть наши лоты
                if settings and settings.auto_bump and (now - last_bump_time > BUMP_INTERVAL):
                    try:
                        categories = self.account.categories
                        for cat in categories:
                            try:
                                subcats = cat.get_subcategories() if hasattr(cat, 'get_subcategories') else []
                                subcats_with_lots = []
                                for sub in subcats:
                                    try:
                                        lots = self.account.get_my_subcategory_lots(sub.id)
                                        if lots:
                                            subcats_with_lots.append(sub)
                                    except Exception:
                                        continue
                                if subcats_with_lots:
                                    self.account.raise_lots(cat.id, subcategories=subcats_with_lots)
                                    logger.info(f"Лоты категории {cat.name} подняты ({len(subcats_with_lots)} подкатегорий с лотами).")
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
