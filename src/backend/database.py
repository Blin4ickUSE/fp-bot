"""
Модели базы данных и утилиты для работы с ней (SQLAlchemy + SQLite).
"""
from __future__ import annotations

import datetime
import json
import logging
from contextlib import contextmanager
from enum import Enum as PyEnum

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Text,
    DateTime, Boolean, Enum, ForeignKey, Index, inspect, text
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship

from .config import DATABASE_URL

logger = logging.getLogger("backend.database")

engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


# ---------- Enums ----------

class OrderStatus(PyEnum):
    WAITING_DATA = "waiting_data"       # скрипт собирает данные
    DATA_COLLECTED = "data_collected"    # данные собраны, ожидает продавца
    IN_PROGRESS = "in_progress"         # продавец выполняет
    COMPLETED = "completed"             # выполнен
    REFUNDED = "refunded"               # возврат
    CONFIRMED = "confirmed"             # подтверждён покупателем
    DISPUTE = "dispute"                 # спор (заказ переоткрыт)


class ScriptType(PyEnum):
    NONE = "none"
    SPOTIFY = "spotify"
    DISCORD_NITRO = "discord_nitro"
    CHATGPT = "chatgpt"
    NETFLIX = "netflix"
    CLAUDE = "claude"
    TELEGRAM_PREMIUM_1M = "telegram_premium_1m"
    TELEGRAM_PREMIUM_LONG = "telegram_premium_long"     # 3/6/12 мес
    TELEGRAM_STARS = "telegram_stars"


# ---------- Models ----------

class LotConfig(Base):
    """Конфигурация скрипта: ключевые слова в заказе/описании → тип скрипта."""
    __tablename__ = "lot_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # Ключевые слова (JSON-массив строк): если любое есть в описании заказа — срабатывает этот скрипт
    script_keywords = Column(Text, nullable=True,
                             comment="JSON array of keywords for matching order description")
    # Устаревшие поля (для обратной совместимости)
    lot_id = Column(Integer, nullable=True, index=True)
    lot_name = Column(String(512), nullable=True)
    lot_name_pattern = Column(String(512), nullable=True)
    script_type = Column(Enum(ScriptType), default=ScriptType.NONE, nullable=False)
    script_custom_text = Column(Text, nullable=True,
                                comment="Кастомный текст скрипта (JSON: {step_id: {ru: ..., en: ...}})")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    def get_script_keywords(self) -> list:
        """Список ключевых слов для сопоставления."""
        if not self.script_keywords:
            return []
        try:
            data = json.loads(self.script_keywords)
            return [str(k).strip().lower() for k in (data if isinstance(data, list) else []) if k]
        except json.JSONDecodeError:
            return []

    def set_script_keywords(self, keywords: list):
        """Установить ключевые слова."""
        self.script_keywords = json.dumps(keywords, ensure_ascii=False) if keywords else None

    def get_script_custom_text(self) -> dict:
        """Получить кастомный текст скрипта."""
        if not self.script_custom_text:
            return {}
        try:
            return json.loads(self.script_custom_text)
        except json.JSONDecodeError:
            return {}

    def set_script_custom_text(self, text: dict):
        """Установить кастомный текст скрипта."""
        self.script_custom_text = json.dumps(text, ensure_ascii=False) if text else None

    def __repr__(self):
        kw = self.get_script_keywords()
        if kw:
            return f"<LotConfig keywords={kw} → {self.script_type.value}>"
        if self.lot_id:
            return f"<LotConfig lot_id={self.lot_id} → {self.script_type.value}>"
        return f"<LotConfig pattern={self.lot_name_pattern} → {self.script_type.value}>"


class Order(Base):
    """Заказ, отслеживаемый ботом."""
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    funpay_order_id = Column(String(32), unique=True, nullable=False, index=True)
    buyer_username = Column(String(128), nullable=False)
    buyer_id = Column(Integer, nullable=False)
    chat_id = Column(String(64), nullable=False)
    item_name = Column(String(512), nullable=False)
    price = Column(Float, default=0.0)
    currency = Column(String(8), default="₽")
    status = Column(Enum(OrderStatus), default=OrderStatus.WAITING_DATA, nullable=False)
    script_type = Column(Enum(ScriptType), default=ScriptType.NONE, nullable=False)
    lot_config_id = Column(Integer, nullable=True, index=True)
    # Текущий шаг скрипта: хранится как JSON {"step": "...", "data": {...}}
    script_state = Column(Text, default="{}")
    # Собранные данные пользователя (JSON)
    collected_data = Column(Text, default="{}")
    # Язык покупателя (ru/en)
    buyer_lang = Column(String(4), default="ru")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    __table_args__ = (
        Index("ix_orders_status", "status"),
    )

    # --- helpers ---
    def get_script_state(self) -> dict:
        try:
            return json.loads(self.script_state or "{}")
        except json.JSONDecodeError:
            return {}

    def set_script_state(self, state: dict):
        self.script_state = json.dumps(state, ensure_ascii=False)

    def get_collected_data(self) -> dict:
        try:
            return json.loads(self.collected_data or "{}")
        except json.JSONDecodeError:
            return {}

    def set_collected_data(self, data: dict):
        self.collected_data = json.dumps(data, ensure_ascii=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "funpay_order_id": self.funpay_order_id,
            "buyer_username": self.buyer_username,
            "buyer_id": self.buyer_id,
            "chat_id": self.chat_id,
            "item_name": self.item_name,
            "price": self.price,
            "currency": self.currency,
            "status": self.status.value,
            "script_type": self.script_type.value,
            "collected_data": self.get_collected_data(),
            "buyer_lang": self.buyer_lang,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class AutomationSettings(Base):
    """Настройки автоматизации (единственная строка в таблице)."""
    __tablename__ = "automation_settings"

    id = Column(Integer, primary_key=True, default=1)
    eternal_online = Column(Boolean, default=True)
    auto_bump = Column(Boolean, default=True)
    auto_confirm = Column(Boolean, default=False)
    auto_confirm_time = Column(String(8), default="12:00")
    auto_confirm_max_orders = Column(Integer, default=5)
    review_reminder = Column(Boolean, default=True)
    review_delay_minutes = Column(Integer, default=1440)  # deprecated, use review_delay_seconds
    review_delay_seconds = Column(Integer, default=3)  # задержка напоминания об отзыве в секундах
    review_message_ru = Column(Text, default=(
        "🫶 Пожалуйста, поставьте нам 5 звезд ⭐️\n\n"
        "Продавец старается выполнять все заказы быстро и качественно, "
        "при этом сохраняя самую низкую цену на рынке.\n\n"
        "Если у вас возникли проблемы, не спешите портить рейтинг продавцу, "
        "обратитесь в чат к продавцу. Чаще всего, если что-то случится, "
        "мы бесплатно восстанавливаем подписку."
    ))
    review_message_en = Column(Text, default=(
        "🫶 Please give us 5 stars ⭐️\n\n"
        "The seller strives to fulfill all orders quickly and efficiently, "
        "while maintaining the lowest prices on the market.\n\n"
        "If you encounter any problems, don't rush to ruin the seller's rating; "
        "contact them via chat. In most cases, if something happens, "
        "we will restore your subscription free of charge."
    ))
    # Авто-подтверждение: тикет в поддержку FunPay (как в плагине AutoTicket)
    auto_ticket_message = Column(Text, default="Пожалуйста, подтвердите заказы: {order_ids}")
    manual_ticket_message = Column(Text, default="Подтвердите заказ: {order_id}")
    auto_ticket_interval_minutes = Column(Integer, default=60)

    def to_dict(self) -> dict:
        return {
            "eternal_online": self.eternal_online,
            "auto_bump": self.auto_bump,
            "auto_confirm": self.auto_confirm,
            "auto_confirm_time": self.auto_confirm_time,
            "auto_confirm_max_orders": self.auto_confirm_max_orders,
            "review_reminder": self.review_reminder,
            "review_delay_minutes": self.review_delay_minutes,
            "review_delay_seconds": getattr(self, "review_delay_seconds", 3),
            "review_message_ru": self.review_message_ru,
            "review_message_en": self.review_message_en,
            "auto_ticket_message": getattr(self, "auto_ticket_message", "Пожалуйста, подтвердите заказы: {order_ids}"),
            "manual_ticket_message": getattr(self, "manual_ticket_message", "Подтвердите заказ: {order_id}"),
            "auto_ticket_interval_minutes": getattr(self, "auto_ticket_interval_minutes", 60),
        }


class StatsSnapshot(Base):
    """Снимок статистики (для графика)."""
    __tablename__ = "stats_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    total_orders = Column(Integer, default=0)
    active_orders = Column(Integer, default=0)
    balance_rub = Column(Float, default=0.0)
    balance_usd = Column(Float, default=0.0)
    balance_eur = Column(Float, default=0.0)


# ---------- Helpers ----------

def init_db():
    """Создать все таблицы и выполнить миграции."""
    Base.metadata.create_all(bind=engine)
    
    # Миграция: добавить новые поля в lot_configs, если их нет
    try:
        inspector = inspect(engine)
        if inspector.has_table('lot_configs'):
            columns = [col['name'] for col in inspector.get_columns('lot_configs')]
            
            with engine.begin() as conn:  # begin() автоматически коммитит
                # Добавляем новые поля, если их нет
                if 'lot_id' not in columns:
                    try:
                        conn.execute(text("ALTER TABLE lot_configs ADD COLUMN lot_id INTEGER"))
                        logger.info("Миграция: добавлено поле lot_id")
                    except Exception as e:
                        logger.warning(f"Не удалось добавить lot_id: {e}")
                
                if 'lot_name' not in columns:
                    try:
                        conn.execute(text("ALTER TABLE lot_configs ADD COLUMN lot_name VARCHAR(512)"))
                        logger.info("Миграция: добавлено поле lot_name")
                    except Exception as e:
                        logger.warning(f"Не удалось добавить lot_name: {e}")
                
                if 'script_custom_text' not in columns:
                    try:
                        conn.execute(text("ALTER TABLE lot_configs ADD COLUMN script_custom_text TEXT"))
                        logger.info("Миграция: добавлено поле script_custom_text")
                    except Exception as e:
                        logger.warning(f"Не удалось добавить script_custom_text: {e}")
                
                if 'updated_at' not in columns:
                    try:
                        conn.execute(text("ALTER TABLE lot_configs ADD COLUMN updated_at DATETIME"))
                        logger.info("Миграция: добавлено поле updated_at")
                    except Exception as e:
                        logger.warning(f"Не удалось добавить updated_at: {e}")

                if 'script_keywords' not in columns:
                    try:
                        conn.execute(text("ALTER TABLE lot_configs ADD COLUMN script_keywords TEXT"))
                        logger.info("Миграция: добавлено поле script_keywords")
                    except Exception as e:
                        logger.warning(f"Не удалось добавить script_keywords: {e}")
        # Миграция: review_delay_seconds в automation_settings
        try:
            inspector = inspect(engine)
            if inspector.has_table('automation_settings'):
                columns = [col['name'] for col in inspector.get_columns('automation_settings')]
                if 'review_delay_seconds' not in columns:
                    with engine.begin() as conn:
                        conn.execute(text("ALTER TABLE automation_settings ADD COLUMN review_delay_seconds INTEGER DEFAULT 3"))
                        logger.info("Миграция: добавлено поле review_delay_seconds")
                for col_name, col_sql in [
                    ("auto_ticket_message", "ALTER TABLE automation_settings ADD COLUMN auto_ticket_message TEXT DEFAULT 'Пожалуйста, подтвердите заказы: {order_ids}'"),
                    ("manual_ticket_message", "ALTER TABLE automation_settings ADD COLUMN manual_ticket_message TEXT DEFAULT 'Подтвердите заказ: {order_id}'"),
                    ("auto_ticket_interval_minutes", "ALTER TABLE automation_settings ADD COLUMN auto_ticket_interval_minutes INTEGER DEFAULT 60"),
                ]:
                    if col_name not in columns:
                        try:
                            with engine.begin() as conn:
                                conn.execute(text(col_sql))
                            logger.info(f"Миграция: добавлено поле automation_settings.{col_name}")
                        except Exception as e:
                            logger.warning(f"Миграция automation_settings.{col_name}: {e}")
        except Exception as e:
            logger.warning(f"Ошибка при проверке миграции automation_settings: {e}")
        if inspector.has_table('orders'):
            ocols = [col['name'] for col in inspector.get_columns('orders')]
            if 'lot_config_id' not in ocols:
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE orders ADD COLUMN lot_config_id INTEGER"))
                    logger.info("Миграция: добавлено поле orders.lot_config_id")
    except Exception as e:
        logger.warning(f"Ошибка при проверке миграций: {e}")

    # Явно убедиться, что script_keywords есть в lot_configs (на случай устаревшей БД)
    try:
        inspector = inspect(engine)
        if inspector.has_table('lot_configs'):
            columns = [c['name'] for c in inspector.get_columns('lot_configs')]
            if 'script_keywords' not in columns:
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE lot_configs ADD COLUMN script_keywords TEXT"))
                logger.info("Миграция: добавлена колонка lot_configs.script_keywords")
    except Exception as e:
        logger.warning(f"Миграция script_keywords: {e}")

    # Миграция: пересоздать lot_configs с nullable lot_name и lot_name_pattern (убрать NOT NULL и UNIQUE).
    # Выполняется при каждом старте, если таблица есть — так схема всегда корректна.
    try:
        inspector = inspect(engine)
        if inspector.has_table('lot_configs'):
            with engine.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE lot_configs_new (
                        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        script_keywords TEXT,
                        lot_id INTEGER,
                        lot_name TEXT,
                        lot_name_pattern TEXT,
                        script_type VARCHAR(32) NOT NULL,
                        script_custom_text TEXT,
                        created_at DATETIME,
                        updated_at DATETIME
                    )
                """))
                conn.execute(text("""
                    INSERT INTO lot_configs_new
                    (id, script_keywords, lot_id, lot_name, lot_name_pattern, script_type, script_custom_text, created_at, updated_at)
                    SELECT id, script_keywords, lot_id,
                           NULLIF(TRIM(COALESCE(lot_name, '')), ''),
                           NULLIF(TRIM(COALESCE(lot_name_pattern, '')), ''),
                           script_type, script_custom_text, created_at, updated_at
                    FROM lot_configs
                """))
                conn.execute(text("DROP TABLE lot_configs"))
                conn.execute(text("ALTER TABLE lot_configs_new RENAME TO lot_configs"))
            logger.info("Миграция: lot_configs пересоздана (lot_name, lot_name_pattern nullable)")
    except Exception as e:
        logger.warning(f"Миграция lot_configs (nullable): {e}")

    # Создать дефолтные настройки автоматизации, если их нет
    with get_session() as session:
        if not session.query(AutomationSettings).first():
            session.add(AutomationSettings(id=1))
            session.commit()


@contextmanager
def get_session() -> Session:
    """Контекстный менеджер для сессии."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
