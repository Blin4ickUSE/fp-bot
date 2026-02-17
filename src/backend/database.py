"""
Модели базы данных и утилиты для работы с ней (SQLAlchemy + SQLite).
"""
from __future__ import annotations

import datetime
import json
from contextlib import contextmanager
from enum import Enum as PyEnum

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Text,
    DateTime, Boolean, Enum, ForeignKey, Index
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship

from .config import DATABASE_URL

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
    TELEGRAM_PREMIUM_1M = "telegram_premium_1m"
    TELEGRAM_PREMIUM_LONG = "telegram_premium_long"     # 3/6/12 мес
    TELEGRAM_STARS = "telegram_stars"


# ---------- Models ----------

class LotConfig(Base):
    """Конфигурация лота: какой скрипт привязан к какому лоту FunPay."""
    __tablename__ = "lot_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # ID лота на FunPay (если указан, используется точное совпадение)
    lot_id = Column(Integer, nullable=True, unique=True, index=True,
                    comment="ID лота на FunPay (для точного совпадения)")
    # Название лота (для отображения)
    lot_name = Column(String(512), nullable=True,
                      comment="Название лота для отображения")
    # Паттерн для сопоставления лота (часть названия, используется если lot_id не указан)
    lot_name_pattern = Column(String(512), nullable=True,
                              comment="Подстрока в названии лота для сопоставления")
    script_type = Column(Enum(ScriptType), default=ScriptType.NONE, nullable=False)
    # Кастомный текст скрипта (JSON, переопределяет дефолтный)
    script_custom_text = Column(Text, nullable=True,
                                comment="Кастомный текст скрипта (JSON: {step_id: {ru: ..., en: ...}})")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

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
    review_delay_minutes = Column(Integer, default=1440)
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

    def to_dict(self) -> dict:
        return {
            "eternal_online": self.eternal_online,
            "auto_bump": self.auto_bump,
            "auto_confirm": self.auto_confirm,
            "auto_confirm_time": self.auto_confirm_time,
            "auto_confirm_max_orders": self.auto_confirm_max_orders,
            "review_reminder": self.review_reminder,
            "review_delay_minutes": self.review_delay_minutes,
            "review_message_ru": self.review_message_ru,
            "review_message_en": self.review_message_en,
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
    """Создать все таблицы."""
    Base.metadata.create_all(bind=engine)
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
