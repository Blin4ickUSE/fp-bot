"""
Основной бот Telegram
"""
import asyncio
import logging
import os
import sys
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, CallbackQuery
from aiogram.enums import ParseMode

# Добавляем путь к backend
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../'))

from backend.database import database
from backend.core import core, abuse_detected
from backend.core.blacklist_updater import start_blacklist_updater
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
SUPPORT_BOT_TOKEN = os.getenv('SUPPORT_BOT_TOKEN', '')
WEB_APP_URL = os.getenv('MINIAPP_URL', 'https://your-domain.com/miniapp')

# Валидация токенов
if not BOT_TOKEN:
    logger.error("❌ TELEGRAM_BOT_TOKEN не указан в .env!")
    sys.exit(1)

if BOT_TOKEN == SUPPORT_BOT_TOKEN:
    logger.error("❌ КРИТИЧЕСКАЯ ОШИБКА: TELEGRAM_BOT_TOKEN совпадает с SUPPORT_BOT_TOKEN!")
    logger.error("   Это вызовет ошибку 'Conflict: terminated by other getUpdates request'")
    logger.error("   Создайте ОТДЕЛЬНОГО бота в @BotFather для службы поддержки!")
    sys.exit(1)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def extract_referral_id(text: str) -> int:
    """Извлечь referral ID из команды /start
    
    Поддерживаемые форматы:
    - /start ref123456789
    - /start ref=123456789
    """
    # Пробуем формат ref123456789 (без =)
    match = re.search(r'ref(\d+)', text)
    if match:
        return int(match.group(1))
    # Пробуем формат ref=123456789 (с =)
    match = re.search(r'ref=(\d+)', text)
    return int(match.group(1)) if match else None

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    """Обработчик команды /start"""
    telegram_id = message.from_user.id
    
    # Проверка черного списка
    if core.check_blacklist(telegram_id):
        await message.answer("❌ Ваш аккаунт заблокирован.")
        return
    
    # Извлекаем referral ID
    referral_id = None
    if message.text and 'ref' in message.text:
        referral_id = extract_referral_id(message.text)
    
    # Нельзя быть своим собственным рефералом
    if referral_id == telegram_id:
        referral_id = None
    
    # Получаем или создаем пользователя
    user = database.get_user_by_telegram_id(telegram_id)
    if not user:
        # Создаем нового пользователя
        username = message.from_user.username
        full_name = message.from_user.full_name
        
        # Проверяем referral и рейт-лимит
        referred_by = None
        if referral_id:
            ref_user = database.get_user_by_telegram_id(referral_id)
            if ref_user:
                # Проверяем рейт-лимит: не более 25 рефералов в минуту
                if database.check_referral_rate_limit(referral_id, limit=25, window_seconds=60):
                    referred_by = ref_user['id']
                    logger.info(f"Referral accepted: user {telegram_id} referred by {referral_id}")
                else:
                    logger.warning(f"Referral rate limit exceeded for referrer {referral_id}")
        
        user_id = database.create_user(telegram_id, username, full_name, referred_by)
        user = database.get_user_by_id(user_id)
    else:
        # Пользователь уже существует - попробуем установить реферера, если его нет
        if referral_id and user.get('referred_by') is None:
            ref_user = database.get_user_by_telegram_id(referral_id)
            if ref_user:
                # Проверяем рейт-лимит
                if database.check_referral_rate_limit(referral_id, limit=25, window_seconds=60):
                    if database.set_referrer_for_user(user['id'], ref_user['id']):
                        logger.info(f"Referral set for existing user {telegram_id} -> {referral_id}")
                        # Обновляем данные пользователя
                        user = database.get_user_by_telegram_id(telegram_id)
                else:
                    logger.warning(f"Referral rate limit exceeded for referrer {referral_id}")
    
    # Проверяем статус бана
    ban_status = abuse_detected.check_user_ban_status(user['id'])
    if ban_status.get('banned'):
        await message.answer(
            "❌ Ваш аккаунт заблокирован.\n\n"
            "Если вы считаете, что это ошибка, свяжитесь со службой поддержки.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="Служба поддержки", url="https://t.me/vpn12help_bot")
            ]])
        )
        return
    
    # Формируем сообщение
    text = (
        "*👋 Добро пожаловать!*\n\n"
        "Это *12VPN* — лучший сервис для обхода блокировок и защиты данных. "
        "Просто запусти мини-приложение кнопкой ниже!\n\n"
        "*🎁 Дарим 24 часа бесплатно!*\n"
        "*🇷🇺 Оплата по СБП и картам.*\n"
        "*⚡️ Высокая скорость и стабильная работа*\n"
        "*🤝 Служба поддержки поможет с любым вопросом или решит проблему.*"
    )
    
    # Кнопка Mini App
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="📱 Открыть приложение",
            web_app=WebAppInfo(url=WEB_APP_URL)
        )
    ]])
    
    await message.answer(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)


# ========== Обработчики callback для запросов на вывод ==========

# Состояния для ожидания причины отказа
withdrawal_reject_states = {}

@dp.callback_query(F.data.startswith('withdraw_approve_'))
async def handle_withdraw_approve(callback: CallbackQuery):
    """Обработка одобрения запроса на вывод"""
    try:
        transaction_id = int(callback.data.split('_')[-1])
        
        # Отправляем запрос на подтверждение
        confirm_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text='✅ Да, выполнить', callback_data=f'withdraw_confirm_{transaction_id}'),
                InlineKeyboardButton(text='❌ Отмена', callback_data=f'withdraw_cancel_{transaction_id}')
            ]
        ])
        
        await callback.message.edit_reply_markup(reply_markup=confirm_keyboard)
        await callback.answer('Подтвердите выполнение вывода')
    except Exception as e:
        logger.error(f"Error handling withdraw approve: {e}")
        await callback.answer('Ошибка обработки', show_alert=True)


@dp.callback_query(F.data.startswith('withdraw_confirm_'))
async def handle_withdraw_confirm(callback: CallbackQuery):
    """Подтверждение вывода - отправляем пользователю уведомление об успехе"""
    try:
        transaction_id = int(callback.data.split('_')[-1])
        
        conn = database.get_db_connection()
        cursor = conn.cursor()
        
        # Получаем информацию о транзакции
        cursor.execute("""
            SELECT t.*, u.telegram_id, u.username
            FROM transactions t
            JOIN users u ON t.user_id = u.id
            WHERE t.id = ?
        """, (transaction_id,))
        
        transaction = cursor.fetchone()
        if not transaction:
            await callback.answer('Транзакция не найдена', show_alert=True)
            return
        
        # Обновляем статус транзакции
        cursor.execute("""
            UPDATE transactions SET status = 'Success' WHERE id = ?
        """, (transaction_id,))
        
        conn.commit()
        conn.close()
        
        # Отправляем уведомление пользователю
        amount = abs(float(transaction['amount']))
        core.send_notification_to_user(
            transaction['telegram_id'],
            f"✅ <b>Вывод средств выполнен!</b>\n\n"
            f"💵 Сумма: {amount}₽\n"
            f"💳 Метод: {transaction['payment_method']}\n\n"
            f"Деньги отправлены. Спасибо за использование 12VPN!"
        )
        
        # Удаляем сообщение с запросом
        await callback.message.delete()
        await callback.answer('Вывод успешно выполнен!', show_alert=True)
        
    except Exception as e:
        logger.error(f"Error confirming withdrawal: {e}")
        await callback.answer('Ошибка обработки', show_alert=True)


@dp.callback_query(F.data.startswith('withdraw_reject_'))
async def handle_withdraw_reject(callback: CallbackQuery):
    """Обработка отказа в выводе"""
    try:
        transaction_id = int(callback.data.split('_')[-1])
        
        # Запрашиваем причину отказа
        reason_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='Без причины', callback_data=f'withdraw_reject_confirm_{transaction_id}_none')],
            [InlineKeyboardButton(text='Подозрительная активность', callback_data=f'withdraw_reject_confirm_{transaction_id}_suspicious')],
            [InlineKeyboardButton(text='Неверные реквизиты', callback_data=f'withdraw_reject_confirm_{transaction_id}_invalid')],
            [InlineKeyboardButton(text='❌ Отмена', callback_data=f'withdraw_cancel_{transaction_id}')]
        ])
        
        await callback.message.edit_reply_markup(reply_markup=reason_keyboard)
        await callback.answer('Выберите причину отказа')
    except Exception as e:
        logger.error(f"Error handling withdraw reject: {e}")
        await callback.answer('Ошибка обработки', show_alert=True)


@dp.callback_query(F.data.startswith('withdraw_reject_confirm_'))
async def handle_withdraw_reject_confirm(callback: CallbackQuery):
    """Подтверждение отказа с причиной"""
    try:
        parts = callback.data.split('_')
        transaction_id = int(parts[3])
        reason_code = parts[4] if len(parts) > 4 else 'none'
        
        reasons = {
            'none': '',
            'suspicious': 'Подозрительная активность',
            'invalid': 'Неверные реквизиты'
        }
        reason = reasons.get(reason_code, '')
        
        conn = database.get_db_connection()
        cursor = conn.cursor()
        
        # Получаем информацию о транзакции
        cursor.execute("""
            SELECT t.*, u.telegram_id, u.username
            FROM transactions t
            JOIN users u ON t.user_id = u.id
            WHERE t.id = ?
        """, (transaction_id,))
        
        transaction = cursor.fetchone()
        if not transaction:
            await callback.answer('Транзакция не найдена', show_alert=True)
            return
        
        amount = abs(float(transaction['amount']))
        user_id = transaction['user_id']
        
        # Возвращаем деньги на реферальный баланс
        cursor.execute("""
            UPDATE users SET partner_balance = partner_balance + ? WHERE id = ?
        """, (amount, user_id))
        
        # Обновляем статус транзакции
        cursor.execute("""
            UPDATE transactions SET status = 'Rejected', description = description || ' | Причина отказа: ' || ? WHERE id = ?
        """, (reason or 'Не указана', transaction_id))
        
        conn.commit()
        conn.close()
        
        # Отправляем уведомление пользователю
        reject_msg = f"❌ <b>Вывод средств отклонён</b>\n\n💵 Сумма: {amount}₽\n"
        if reason:
            reject_msg += f"📝 Причина: {reason}\n"
        reject_msg += "\n💰 Средства возвращены на ваш реферальный баланс."
        
        core.send_notification_to_user(transaction['telegram_id'], reject_msg)
        
        # Удаляем сообщение с запросом
        await callback.message.delete()
        await callback.answer('Вывод отклонён, средства возвращены', show_alert=True)
        
    except Exception as e:
        logger.error(f"Error confirming rejection: {e}")
        await callback.answer('Ошибка обработки', show_alert=True)


@dp.callback_query(F.data.startswith('withdraw_cancel_'))
async def handle_withdraw_cancel(callback: CallbackQuery):
    """Отмена действия - возвращаем исходные кнопки"""
    try:
        transaction_id = int(callback.data.split('_')[-1])
        
        original_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text='✅ Принять', callback_data=f'withdraw_approve_{transaction_id}'),
                InlineKeyboardButton(text='❌ Отказать', callback_data=f'withdraw_reject_{transaction_id}')
            ]
        ])
        
        await callback.message.edit_reply_markup(reply_markup=original_keyboard)
        await callback.answer('Действие отменено')
    except Exception as e:
        logger.error(f"Error canceling: {e}")
        await callback.answer('Ошибка', show_alert=True)


async def subscription_notifications_task():
    """Фоновая задача для уведомлений о подписках (умная корзина)"""
    while True:
        try:
            await asyncio.sleep(3600)  # Проверка каждый час
            
            conn = database.get_db_connection()
            cursor = conn.cursor()
            
            from datetime import datetime, timedelta
            now = datetime.now()
            
            # === 1. Уведомления за 3, 2, 1 день и 3 часа до конца ===
            notification_intervals = [
                (3, 'days', '3 дня'),
                (2, 'days', '2 дня'),
                (1, 'days', '1 день'),
                (3, 'hours', '3 часа')
            ]
            
            for value, unit, text in notification_intervals:
                if unit == 'days':
                    target_time = now + timedelta(days=value)
                    window_start = target_time - timedelta(hours=1)
                    window_end = target_time + timedelta(hours=1)
                else:
                    target_time = now + timedelta(hours=value)
                    window_start = target_time - timedelta(minutes=30)
                    window_end = target_time + timedelta(minutes=30)
                
                cursor.execute("""
                    SELECT vk.id, vk.key_uuid, vk.expiry_date, u.telegram_id
                    FROM vpn_keys vk
                    JOIN users u ON vk.user_id = u.id
                    WHERE vk.status = 'Active'
                      AND datetime(vk.expiry_date) BETWEEN ? AND ?
                """, (window_start.isoformat(), window_end.isoformat()))
                
                for row in cursor.fetchall():
                    key_id = row['id']
                    key_uuid = row['key_uuid']
                    telegram_id = row['telegram_id']
                    short_id = key_uuid[:8] if key_uuid else f"#{key_id}"
                    
                    msg = (
                        f"⚠️ <b>Ваша подписка скоро закончится</b>\n\n"
                        f"Через {text} ваш ключ {short_id} закончится. "
                        f"Чтобы сохранить доступ в свободный интернет, оплатите подписку!"
                    )
                    core.send_notification_to_user(telegram_id, msg)
                    logger.info(f"Sent expiry reminder ({text}) to {telegram_id} for key {key_id}")
            
            # === 2. Уведомление при истечении подписки ===
            cursor.execute("""
                SELECT vk.id, vk.key_uuid, vk.expiry_date, u.telegram_id
                FROM vpn_keys vk
                JOIN users u ON vk.user_id = u.id
                WHERE vk.status = 'Active'
                  AND datetime(vk.expiry_date) < ?
            """, (now.isoformat(),))
            
            for row in cursor.fetchall():
                key_id = row['id']
                telegram_id = row['telegram_id']
                
                # Помечаем как истёкший
                cursor.execute("UPDATE vpn_keys SET status = 'Expired' WHERE id = ?", (key_id,))
                
                msg = (
                    "❌ <b>Ваша подписка закончилась.</b>\n\n"
                    "Вскоре она будет окончательно удалена. "
                    "Чтобы не перенастраивать всё заново, продлите подписку в разделе \"Устройства\""
                )
                core.send_notification_to_user(telegram_id, msg)
                logger.info(f"Subscription expired for key {key_id}, notified user {telegram_id}")
            
            # === 3. Уведомление за сутки перед удалением (9-й день) ===
            nine_days_ago = now - timedelta(days=9)
            cursor.execute("""
                SELECT vk.id, vk.key_uuid, vk.expiry_date, u.telegram_id
                FROM vpn_keys vk
                JOIN users u ON vk.user_id = u.id
                WHERE vk.status = 'Expired'
                  AND datetime(vk.expiry_date) BETWEEN ? AND ?
            """, ((nine_days_ago - timedelta(hours=1)).isoformat(), 
                  (nine_days_ago + timedelta(hours=1)).isoformat()))
            
            for row in cursor.fetchall():
                telegram_id = row['telegram_id']
                
                msg = (
                    "❗️ <b>Ваша подписка будет удалена</b>\n\n"
                    "Через 24 часа ваша подписка будет окончательно удалена. "
                    "Чтобы не потерять доступ, продлите подписку."
                )
                core.send_notification_to_user(telegram_id, msg)
            
            # === 4. Удаление через 10 дней после истечения ===
            ten_days_ago = now - timedelta(days=10)
            cursor.execute("""
                SELECT vk.id, vk.key_uuid, vk.user_id, u.telegram_id
                FROM vpn_keys vk
                JOIN users u ON vk.user_id = u.id
                WHERE vk.status = 'Expired'
                  AND datetime(vk.expiry_date) < ?
            """, (ten_days_ago.isoformat(),))
            
            for row in cursor.fetchall():
                key_id = row['id']
                key_uuid = row['key_uuid']
                user_id = row['user_id']
                
                # Удаляем из Remnawave
                if key_uuid:
                    try:
                        from backend.api import remnawave
                        remnawave.remnawave_api.delete_user_sync(key_uuid)
                        logger.info(f"Deleted key {key_uuid} from Remnawave")
                    except Exception as e:
                        logger.error(f"Failed to delete key {key_uuid} from Remnawave: {e}")
                
                # Удаляем ключ/устройство (теперь одна запись)
                cursor.execute("DELETE FROM vpn_keys WHERE id = ?", (key_id,))
                
                logger.info(f"Auto-deleted expired key {key_id} for user {user_id}")
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Error in subscription_notifications_task: {e}")
            await asyncio.sleep(60)


async def auto_renewal_task():
    """Фоновая задача для автоматического продления подписок за 60 минут до истечения"""
    while True:
        try:
            await asyncio.sleep(300)  # Проверка каждые 5 минут
            
            conn = database.get_db_connection()
            cursor = conn.cursor()
            
            from datetime import datetime, timedelta
            now = datetime.now()
            
            # Находим подписки, истекающие через 55-65 минут (окно 10 минут)
            check_window_start = now + timedelta(minutes=55)
            check_window_end = now + timedelta(minutes=65)
            
            cursor.execute("""
                SELECT vk.id, vk.key_uuid, vk.expiry_date, vk.plan_type, vk.traffic_limit,
                       u.id as user_id, u.telegram_id, u.balance, u.username
                FROM vpn_keys vk
                JOIN users u ON vk.user_id = u.id
                WHERE vk.status = 'Active'
                  AND datetime(vk.expiry_date) BETWEEN ? AND ?
            """, (check_window_start.isoformat(), check_window_end.isoformat()))
            
            expiring_keys = cursor.fetchall()
            
            for row in expiring_keys:
                key_id = row['id']
                key_uuid = row['key_uuid']
                user_id = row['user_id']
                telegram_id = row['telegram_id']
                balance = float(row['balance'] or 0)
                plan_type = row['plan_type'] or 'vpn'
                
                # Получаем минимальную цену продления (1 месяц VPN = 99₽)
                renewal_price = 99  # Базовая цена за 1 месяц
                renewal_days = 30
                
                # Проверяем, достаточно ли средств на балансе
                if balance >= renewal_price:
                    try:
                        # Списываем баланс
                        cursor.execute("BEGIN IMMEDIATE")
                        cursor.execute("SELECT balance FROM users WHERE id = ?", (user_id,))
                        current_balance = float(cursor.fetchone()['balance'] or 0)
                        
                        if current_balance >= renewal_price:
                            # Списываем
                            new_balance = current_balance - renewal_price
                            cursor.execute("UPDATE users SET balance = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                         (new_balance, user_id))
                            
                            # Рассчитываем новую дату истечения
                            current_expiry = datetime.fromisoformat(row['expiry_date'].replace('Z', '+00:00').replace('+00:00', ''))
                            new_expiry = current_expiry + timedelta(days=renewal_days)
                            
                            # Обновляем ключ в Remnawave
                            if key_uuid:
                                try:
                                    from backend.api import remnawave
                                    remnawave.remnawave_api.update_user_sync(
                                        uuid=key_uuid,
                                        expire_at=new_expiry
                                    )
                                except Exception as e:
                                    logger.error(f"Failed to update key {key_uuid} in Remnawave: {e}")
                                    cursor.execute("ROLLBACK")
                                    continue
                            
                            # Обновляем ключ в БД
                            cursor.execute("""
                                UPDATE vpn_keys SET expiry_date = ? WHERE id = ?
                            """, (new_expiry.isoformat(), key_id))
                            
                            # Создаем транзакцию
                            cursor.execute("""
                                INSERT INTO transactions (user_id, type, amount, status, description, payment_method)
                                VALUES (?, 'auto_renewal', ?, 'Success', 'Автоматическое продление подписки (30 дней)', 'Balance')
                            """, (user_id, -renewal_price))
                            
                            conn.commit()
                            
                            # Уведомляем пользователя
                            core.send_notification_to_user(
                                telegram_id,
                                f"✅ <b>Подписка автоматически продлена!</b>\n\n"
                                f"💳 Списано с баланса: {renewal_price}₽\n"
                                f"📅 Новая дата окончания: {new_expiry.strftime('%d.%m.%Y')}\n"
                                f"💰 Остаток на балансе: {new_balance:.2f}₽\n\n"
                                f"Если вы не хотите автопродления, уменьшите баланс до 0."
                            )
                            
                            logger.info(f"Auto-renewed subscription for user {user_id} (key {key_id})")
                        else:
                            conn.rollback()
                            
                    except Exception as e:
                        logger.error(f"Error auto-renewing subscription for key {key_id}: {e}")
                        try:
                            conn.rollback()
                        except:
                            pass
                else:
                    # Недостаточно средств - уведомляем пользователя (только один раз)
                    # Проверяем, не отправляли ли уже уведомление
                    cursor.execute("""
                        SELECT COUNT(*) as cnt FROM transactions 
                        WHERE user_id = ? AND type = 'auto_renewal_warning' 
                        AND created_at > datetime('now', '-2 hours')
                    """, (user_id,))
                    
                    if cursor.fetchone()['cnt'] == 0:
                        core.send_notification_to_user(
                            telegram_id,
                            f"⚠️ <b>Подписка истекает через 1 час!</b>\n\n"
                            f"Для автоматического продления на балансе должно быть минимум {renewal_price}₽.\n"
                            f"💰 Ваш баланс: {balance:.2f}₽\n\n"
                            f"Пополните баланс, чтобы не потерять доступ к VPN!"
                        )
                        
                        # Записываем предупреждение чтобы не спамить
                        cursor.execute("""
                            INSERT INTO transactions (user_id, type, amount, status, description)
                            VALUES (?, 'auto_renewal_warning', 0, 'Info', 'Уведомление о недостатке средств для автопродления')
                        """, (user_id,))
                        conn.commit()
            
            conn.close()
            
        except Exception as e:
            logger.error(f"Error in auto_renewal_task: {e}")
            import traceback
            traceback.print_exc()
            await asyncio.sleep(60)


async def weekly_reminder_task():
    """Еженедельное напоминание для неактивных пользователей (в течение полугода)"""
    while True:
        try:
            await asyncio.sleep(86400)  # Проверка раз в день
            
            # Проверяем только по понедельникам
            from datetime import datetime, timedelta
            if datetime.now().weekday() != 0:  # 0 = понедельник
                continue
            
            conn = database.get_db_connection()
            cursor = conn.cursor()
            
            # Находим пользователей у которых были подписки, но нет активных,
            # и последняя подписка была удалена не более 6 месяцев назад
            six_months_ago = datetime.now() - timedelta(days=180)
            
            cursor.execute("""
                SELECT DISTINCT u.telegram_id, u.id
                FROM users u
                WHERE u.id IN (
                    SELECT DISTINCT user_id FROM transactions 
                    WHERE type IN ('subscription', 'trial') 
                    AND created_at > ?
                )
                AND u.id NOT IN (
                    SELECT user_id FROM vpn_keys WHERE status = 'Active'
                )
                AND (u.is_banned = 0 OR u.is_banned IS NULL)
            """, (six_months_ago.isoformat(),))
            
            for row in cursor.fetchall():
                telegram_id = row['telegram_id']
                
                msg = (
                    "❔️ <b>Вы про нас не забыли?</b>\n\n"
                    "А мы про вас нет. Вы приобретали подписку у нас и перестали пользоваться. "
                    "Нам очень жаль, если наш сервис вам не понравился.\n\n"
                    "Напишите нам в поддержку, чтобы мы разобрались с вашей проблемой "
                    "и вы вновь могли пользоваться нашим сервисом!"
                )
                
                core.send_notification_to_user(telegram_id, msg)
            
            conn.close()
            
        except Exception as e:
            logger.error(f"Error in weekly_reminder_task: {e}")
            await asyncio.sleep(3600)


async def auto_refund_expired_withdrawals():
    """Фоновая задача для автовозврата просроченных запросов на вывод (7 дней)"""
    while True:
        try:
            await asyncio.sleep(3600)  # Проверка каждый час
            
            conn = database.get_db_connection()
            cursor = conn.cursor()
            
            # Находим просроченные запросы (старше 7 дней)
            cursor.execute("""
                SELECT t.id, t.user_id, t.amount, u.telegram_id
                FROM transactions t
                JOIN users u ON t.user_id = u.id
                WHERE t.type = 'withdrawal_request' 
                  AND t.status = 'Pending'
                  AND datetime(t.created_at) < datetime('now', '-7 days')
            """)
            
            expired = cursor.fetchall()
            
            for row in expired:
                trans_id = row['id']
                user_id = row['user_id']
                amount = abs(float(row['amount']))
                telegram_id = row['telegram_id']
                
                # Возвращаем деньги на реферальный баланс
                cursor.execute("""
                    UPDATE users SET partner_balance = partner_balance + ? WHERE id = ?
                """, (amount, user_id))
                
                # Обновляем статус транзакции
                cursor.execute("""
                    UPDATE transactions SET status = 'Expired', description = description || ' | Автовозврат через 7 дней'
                    WHERE id = ?
                """, (trans_id,))
                
                # Уведомляем пользователя
                core.send_notification_to_user(
                    telegram_id,
                    f"⏰ <b>Истёк срок обработки заявки на вывод</b>\n\n"
                    f"💵 Сумма: {amount}₽\n\n"
                    f"Заявка не была обработана в течение 7 дней. "
                    f"Средства возвращены на ваш реферальный баланс."
                )
                
                logger.info(f"Auto-refunded withdrawal #{trans_id} for user {user_id}: {amount}₽")
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Error in auto_refund_expired_withdrawals: {e}")
            await asyncio.sleep(60)  # При ошибке ждём минуту


async def main():
    """Запуск бота"""
    # Запускаем обновление черного списка
    start_blacklist_updater()
    
    # Запускаем фоновые задачи
    asyncio.create_task(auto_refund_expired_withdrawals())
    asyncio.create_task(subscription_notifications_task())
    asyncio.create_task(weekly_reminder_task())
    asyncio.create_task(auto_renewal_task())  # Автопродление за 60 минут до истечения
    
    logger.info("Бот запущен...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")

