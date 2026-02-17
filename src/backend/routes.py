"""
FastAPI маршруты для мини-приложения.
Предоставляет API для управления заказами, лотами, автоматизацией.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import datetime
import logging
import time
from typing import Optional
from urllib.parse import unquote, parse_qs

from fastapi import FastAPI, HTTPException, Depends, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .config import API_SECRET, TELEGRAM_BOT_TOKEN
from .database import (
    get_session, Order, OrderStatus, ScriptType,
    LotConfig, AutomationSettings, StatsSnapshot,
)

logger = logging.getLogger("backend.routes")

app = FastAPI(title="FunPay Manager API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Telegram Mini App auth — проверка initData
# ---------------------------------------------------------------------------

def validate_telegram_init_data(init_data: str) -> dict | None:
    """Проверяет initData из Telegram Mini App.
    Возвращает данные пользователя или None, если невалидно.
    """
    if not TELEGRAM_BOT_TOKEN:
        # В dev-режиме без токена пропускаем проверку
        return {"id": 0, "first_name": "dev"}

    try:
        parsed = parse_qs(init_data)
        received_hash = parsed.get("hash", [None])[0]
        if not received_hash:
            return None
        data_check_arr = []
        for key in sorted(parsed.keys()):
            if key == "hash":
                continue
            data_check_arr.append(f"{key}={unquote(parsed[key][0])}")
        data_check_string = "\n".join(data_check_arr)
        secret_key = hmac.new(b"WebAppData", TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256).digest()
        computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if computed_hash == received_hash:
            user_data = json.loads(unquote(parsed.get("user", ["{}"])[0]))
            return user_data
        return None
    except Exception:
        return None


async def get_current_user(request: Request) -> dict:
    """Проверка авторизации через заголовок X-Init-Data."""
    init_data = request.headers.get("X-Init-Data", "")
    # Для локальной разработки/тестирования разрешаем X-Api-Key
    api_key = request.headers.get("X-Api-Key", "")
    if api_key and api_key == API_SECRET:
        return {"id": 0, "first_name": "admin"}
    if init_data:
        user = validate_telegram_init_data(init_data)
        if user:
            return user
    # В dev-режиме без токена пропускаем (для тестирования)
    if not TELEGRAM_BOT_TOKEN:
        return {"id": 0, "first_name": "dev"}
    # Если есть токен, но нет initData — это ошибка авторизации
    # Но для удобства разработки разрешаем доступ с предупреждением
    logger.warning(f"Unauthorized access attempt from {request.client.host} (no initData)")
    raise HTTPException(status_code=401, detail="Unauthorized: Telegram WebApp initData required")


# ---------------------------------------------------------------------------
# Ссылка на FunPay bridge (заполняется в main.py)
# ---------------------------------------------------------------------------

_funpay_bridge = None

def set_funpay_bridge(bridge):
    global _funpay_bridge
    _funpay_bridge = bridge


# ---------------------------------------------------------------------------
# Pydantic схемы
# ---------------------------------------------------------------------------

class OrderActionRequest(BaseModel):
    action: str  # "start", "complete", "refund"


class LotConfigCreate(BaseModel):
    lot_id: Optional[int] = None  # ID лота на FunPay
    lot_name: Optional[str] = None  # Название лота
    lot_name_pattern: Optional[str] = None  # Паттерн (если lot_id не указан)
    script_type: str


class LotConfigUpdate(BaseModel):
    lot_id: Optional[int] = None
    lot_name: Optional[str] = None
    lot_name_pattern: Optional[str] = None
    script_type: Optional[str] = None
    script_custom_text: Optional[dict] = None  # Кастомный текст скрипта


class AutomationSettingsUpdate(BaseModel):
    eternal_online: Optional[bool] = None
    auto_bump: Optional[bool] = None
    auto_confirm: Optional[bool] = None
    auto_confirm_time: Optional[str] = None
    auto_confirm_max_orders: Optional[int] = None
    review_reminder: Optional[bool] = None
    review_delay_minutes: Optional[int] = None
    review_message_ru: Optional[str] = None
    review_message_en: Optional[str] = None


# ---------------------------------------------------------------------------
# Маршруты — Заказы
# ---------------------------------------------------------------------------

@app.get("/api/orders")
async def get_orders(
    status: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    """Получить список заказов с опциональной фильтрацией по статусу."""
    with get_session() as session:
        q = session.query(Order)
        if status:
            try:
                st = OrderStatus(status)
                q = q.filter(Order.status == st)
            except ValueError:
                pass
        orders = q.order_by(Order.created_at.desc()).all()
        return [o.to_dict() for o in orders]


@app.get("/api/orders/{order_id}")
async def get_order(order_id: int, user: dict = Depends(get_current_user)):
    """Получить детали заказа."""
    with get_session() as session:
        order = session.query(Order).filter(Order.id == order_id).first()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        return order.to_dict()


@app.post("/api/orders/{order_id}/action")
async def order_action(
    order_id: int,
    body: OrderActionRequest,
    user: dict = Depends(get_current_user),
):
    """
    Выполнить действие над заказом:
    - start — начать выполнение
    - complete — выполнен
    - refund — возврат
    """
    with get_session() as session:
        order = session.query(Order).filter(Order.id == order_id).first()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        action = body.action

        if action == "start":
            order.status = OrderStatus.IN_PROGRESS
            session.commit()
            # Отправить сообщение покупателю
            if _funpay_bridge:
                _funpay_bridge.send_status_message(order.chat_id, "order_started", order.buyer_lang)
                _funpay_bridge.notify_telegram(
                    f"▶️ Начато выполнение заказа #{order.funpay_order_id}\n"
                    f"Покупатель: {order.buyer_username}\n"
                    f"Товар: {order.item_name}"
                )
            return {"ok": True, "order": order.to_dict()}

        elif action == "complete":
            order.status = OrderStatus.COMPLETED
            session.commit()
            if _funpay_bridge:
                _funpay_bridge.send_status_message(order.chat_id, "order_completed", order.buyer_lang)
                _funpay_bridge.notify_telegram(
                    f"✅ Заказ #{order.funpay_order_id} выполнен!\n"
                    f"Покупатель: {order.buyer_username}"
                )
            return {"ok": True, "order": order.to_dict()}

        elif action == "refund":
            order.status = OrderStatus.REFUNDED
            session.commit()
            if _funpay_bridge:
                _funpay_bridge.send_status_message(order.chat_id, "order_cancelled", order.buyer_lang)
                # Выполнить возврат через FunPay API
                try:
                    _funpay_bridge.do_refund(order.funpay_order_id)
                except Exception as e:
                    logger.error(f"Ошибка при возврате {order.funpay_order_id}: {e}")
                _funpay_bridge.notify_telegram(
                    f"❌ Возврат по заказу #{order.funpay_order_id}\n"
                    f"Покупатель: {order.buyer_username}"
                )
            return {"ok": True, "order": order.to_dict()}

        else:
            raise HTTPException(status_code=400, detail=f"Unknown action: {action}")


# ---------------------------------------------------------------------------
# Маршруты — Конфигурация лотов
# ---------------------------------------------------------------------------

@app.get("/api/funpay-lots")
async def get_funpay_lots(user: dict = Depends(get_current_user)):
    """Получить список всех лотов пользователя с FunPay."""
    if not _funpay_bridge or not _funpay_bridge.account:
        return []  # Возвращаем пустой массив вместо ошибки
    
    try:
        account = _funpay_bridge.account
        all_lots = []
        
        # Проверяем, что categories доступны
        if not hasattr(account, 'categories') or not account.categories:
            logger.warning("Категории не загружены")
            return []
        
        # Проходим по всем категориям и подкатегориям
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
                logger.warning(f"Ошибка при обработке категории {category.name if hasattr(category, 'name') else 'unknown'}: {e}")
                continue
        
        return sorted(all_lots, key=lambda x: x.get("name", ""))
    except Exception as e:
        logger.error(f"Ошибка получения лотов FunPay: {e}", exc_info=True)
        return []  # Возвращаем пустой массив вместо ошибки


@app.get("/api/lots")
async def get_lot_configs(user: dict = Depends(get_current_user)):
    """Получить список конфигураций лотов (привязок)."""
    with get_session() as session:
        configs = session.query(LotConfig).all()
        return [
            {
                "id": c.id,
                "lot_id": c.lot_id,
                "lot_name": c.lot_name,
                "lot_name_pattern": c.lot_name_pattern,
                "script_type": c.script_type.value,
                "script_custom_text": c.get_script_custom_text(),
            }
            for c in configs
        ]


@app.post("/api/lots")
async def create_lot_config(body: LotConfigCreate, user: dict = Depends(get_current_user)):
    with get_session() as session:
        # Проверка: должен быть указан либо lot_id, либо lot_name_pattern
        if not body.lot_id and not body.lot_name_pattern:
            raise HTTPException(status_code=400, detail="Укажите либо ID лота, либо паттерн названия")
        
        # Проверка на дубликаты
        if body.lot_id:
            existing = session.query(LotConfig).filter(LotConfig.lot_id == body.lot_id).first()
            if existing:
                raise HTTPException(status_code=400, detail=f"Лот с ID {body.lot_id} уже настроен")
        elif body.lot_name_pattern:
            existing = session.query(LotConfig).filter(LotConfig.lot_name_pattern == body.lot_name_pattern).first()
            if existing:
                raise HTTPException(status_code=400, detail=f"Паттерн '{body.lot_name_pattern}' уже используется")
        
        try:
            st = ScriptType(body.script_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown script type: {body.script_type}")
        
        config = LotConfig(
            lot_id=body.lot_id,
            lot_name=body.lot_name,
            lot_name_pattern=body.lot_name_pattern,
            script_type=st
        )
        session.add(config)
        session.commit()
        return {
            "id": config.id,
            "lot_id": config.lot_id,
            "lot_name": config.lot_name,
            "lot_name_pattern": config.lot_name_pattern,
            "script_type": config.script_type.value,
        }


@app.put("/api/lots/{lot_id}")
async def update_lot_config(lot_id: int, body: LotConfigUpdate, user: dict = Depends(get_current_user)):
    with get_session() as session:
        config = session.query(LotConfig).filter(LotConfig.id == lot_id).first()
        if not config:
            raise HTTPException(status_code=404, detail="Lot config not found")
        
        if body.lot_id is not None:
            config.lot_id = body.lot_id
        if body.lot_name is not None:
            config.lot_name = body.lot_name
        if body.lot_name_pattern is not None:
            config.lot_name_pattern = body.lot_name_pattern
        if body.script_type is not None:
            try:
                config.script_type = ScriptType(body.script_type)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Unknown script type: {body.script_type}")
        if body.script_custom_text is not None:
            config.set_script_custom_text(body.script_custom_text)
        
        session.commit()
        return {
            "id": config.id,
            "lot_id": config.lot_id,
            "lot_name": config.lot_name,
            "lot_name_pattern": config.lot_name_pattern,
            "script_type": config.script_type.value,
            "script_custom_text": config.get_script_custom_text(),
        }


@app.delete("/api/lots/{lot_id}")
async def delete_lot_config(lot_id: int, user: dict = Depends(get_current_user)):
    with get_session() as session:
        config = session.query(LotConfig).filter(LotConfig.id == lot_id).first()
        if not config:
            raise HTTPException(status_code=404, detail="Lot config not found")
        session.delete(config)
        session.commit()
        return {"ok": True}


# ---------------------------------------------------------------------------
# Маршруты — Автоматизация
# ---------------------------------------------------------------------------

@app.get("/api/automation")
async def get_automation(user: dict = Depends(get_current_user)):
    with get_session() as session:
        settings = session.query(AutomationSettings).first()
        if not settings:
            settings = AutomationSettings(id=1)
            session.add(settings)
            session.commit()
        return settings.to_dict()


@app.put("/api/automation")
async def update_automation(body: AutomationSettingsUpdate, user: dict = Depends(get_current_user)):
    with get_session() as session:
        settings = session.query(AutomationSettings).first()
        if not settings:
            settings = AutomationSettings(id=1)
            session.add(settings)
        for field, value in body.dict(exclude_unset=True).items():
            if value is not None:
                setattr(settings, field, value)
        session.commit()
        return settings.to_dict()


# ---------------------------------------------------------------------------
# Маршруты — Статистика
# ---------------------------------------------------------------------------

@app.get("/api/stats")
async def get_stats(user: dict = Depends(get_current_user)):
    """Общая статистика для дашборда."""
    with get_session() as session:
        total_orders = session.query(Order).count()
        active_orders = session.query(Order).filter(
            Order.status.in_([OrderStatus.WAITING_DATA, OrderStatus.DATA_COLLECTED, OrderStatus.IN_PROGRESS])
        ).count()
        completed_orders = session.query(Order).filter(Order.status == OrderStatus.COMPLETED).count()
        confirmed_orders = session.query(Order).filter(Order.status == OrderStatus.CONFIRMED).count()

        # Баланс и статус бота берём из FunPay bridge
        balance = "—"
        bot_status = "OFFLINE"
        if _funpay_bridge and _funpay_bridge.account:
            acc = _funpay_bridge.account
            # Обновляем баланс, если прошло больше 5 минут с последнего обновления
            if acc.last_update and (time.time() - acc.last_update) > 300:
                try:
                    acc.get()
                except Exception as e:
                    logger.warning(f"Не удалось обновить баланс: {e}")
            if acc.total_balance is not None:
                balance = f"{acc.total_balance:,} {acc.currency}".replace(",", " ")
            bot_status = "ONLINE" if _funpay_bridge.is_running else "OFFLINE"

        return {
            "balance": balance,
            "total_orders": total_orders,
            "active_orders": active_orders,
            "completed_orders": completed_orders,
            "confirmed_orders": confirmed_orders,
            "bot_status": bot_status,
        }


@app.get("/api/stats/chart")
async def get_chart_data(
    hours: int = Query(default=24, ge=1, le=168),
    user: dict = Depends(get_current_user),
):
    """Данные для графика заказов по часам."""
    with get_session() as session:
        since = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
        orders = session.query(Order).filter(Order.created_at >= since).all()

        # Группируем по часам
        buckets: dict[str, int] = {}
        for o in orders:
            if o.created_at:
                key = o.created_at.strftime("%H:00")
                buckets[key] = buckets.get(key, 0) + 1

        data = []
        for h in range(24):
            key = f"{h:02d}:00"
            data.append({"time": key, "orders": buckets.get(key, 0)})
        return data


# ---------------------------------------------------------------------------
# Маршруты — Типы скриптов (для UI)
# ---------------------------------------------------------------------------

@app.get("/api/script-types")
async def get_script_types(user: dict = Depends(get_current_user)):
    return [
        {"value": st.value, "label": st.value.replace("_", " ").title()}
        for st in ScriptType
    ]


# ---------------------------------------------------------------------------
# Здоровье
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    return {"status": "ok"}
