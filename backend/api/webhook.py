"""
Модуль для обработки webhook'ов от платежных систем
"""
import os
import logging
import asyncio
from typing import Dict, Any, Optional
from flask import Flask, request, jsonify
from backend.api import platega
from backend.database import database
from backend.core import core

logger = logging.getLogger(__name__)

app = Flask(__name__)

def notify_admin_about_deposit(user: Dict, amount: float, method: str, provider: str):
    """Уведомить администратора только о успешном пополнении баланса"""
    username = user.get('username', 'N/A')
    telegram_id = user.get('telegram_id', 'N/A')
    
    message = (
        f"💰 <b>Пополнение баланса</b>\n\n"
        f"👤 Пользователь: @{username}\n"
        f"🆔 Telegram ID: {telegram_id}\n"
        f"💵 Сумма: {amount}₽\n"
        f"💳 Способ: {method}\n"
        f"🏦 Провайдер: {provider}"
    )
    
    core.send_notification_to_admin(message)

@app.route('/platega', methods=['POST'])
def platega_webhook():
    """Обработка webhook от Platega (по документации API)"""
    try:
        data = request.json
        
        logger.info(f"Platega webhook: {data}")
        
        # Проверяем авторизацию по документации: X-MerchantId и X-Secret в заголовках
        received_merchant = request.headers.get('X-MerchantId', '')
        received_secret = request.headers.get('X-Secret', '')
        
        if platega.platega_api.is_configured:
            if (received_merchant != platega.platega_api.merchant_id or 
                received_secret != platega.platega_api.secret_key):
                logger.error("Platega webhook: неверные X-MerchantId или X-Secret")
                return jsonify({'error': 'Unauthorized'}), 401
        
        status = str(data.get('status', '')).upper()
        transaction_id = data.get('id')  # По документации: поле "id"
        payload = data.get('payload', '')
        # По документации: amount приходит в рублях (float), не в копейках!
        amount = float(data.get('amount', 0))
        
        if status == 'CONFIRMED':
            # Извлекаем user_id из payload (формат: platega_{user_id}_{hash})
            user_id = None
            if payload:
                # Убираем возможный префикс platega:
                clean_payload = payload.replace('platega:', '') if payload.startswith('platega:') else payload
                parts = clean_payload.split('_')
                if len(parts) >= 2 and parts[0] == 'platega':
                    try:
                        user_id = int(parts[1])
                    except ValueError:
                        pass
            
            if not user_id:
                logger.error(f"Platega webhook: не удалось извлечь user_id из payload {payload}")
                return jsonify({'status': 'ok'}), 200
            
            # Проверяем, не был ли уже обработан этот платеж
            conn = database.get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM transactions WHERE payment_id = ? AND payment_provider = 'Platega'",
                (transaction_id,)
            )
            existing = cursor.fetchone()
            conn.close()
            
            if existing:
                logger.info(f"Platega платеж {transaction_id} уже обработан")
                return jsonify({'status': 'ok'}), 200
            
            # Определяем метод оплаты из данных (по документации)
            payment_method = data.get('paymentMethod', 0)
            # 2=СБП QR, 10=Карты RUB, 11=Карточный, 12=Международный, 13=Крипто
            if payment_method == 2:
                method_name = 'СБП'
            elif payment_method in (10, 11, 12):
                method_name = 'Карта'
            elif payment_method == 13:
                method_name = 'Крипто'
            else:
                method_name = 'Platega'
            
            # Проверяем авто-скидки на пополнение
            bonus_amount = 0
            bonus_name = None
            try:
                conn = database.get_db_connection()
                cursor = conn.cursor()
                
                # Проверяем скидки по сумме пополнения
                cursor.execute("""
                    SELECT * FROM auto_discounts 
                    WHERE is_active = 1 AND condition_type = 'payment_amount'
                    ORDER BY CAST(condition_value AS REAL) DESC
                """)
                discounts = cursor.fetchall()
                
                for discount in discounts:
                    try:
                        min_amount = float(discount['condition_value'])
                        if amount >= min_amount:
                            if discount['discount_type'] == 'percent':
                                bonus_amount = round(amount * float(discount['discount_value']) / 100, 2)
                            else:
                                bonus_amount = float(discount['discount_value'])
                            bonus_name = discount['name']
                            break
                    except (ValueError, TypeError):
                        continue
                
                # Проверяем скидки по методу оплаты
                if bonus_amount == 0:
                    cursor.execute("""
                        SELECT * FROM auto_discounts 
                        WHERE is_active = 1 AND condition_type = 'payment_method'
                          AND LOWER(condition_value) = LOWER(?)
                    """, (method_name,))
                    method_discount = cursor.fetchone()
                    if method_discount:
                        if method_discount['discount_type'] == 'percent':
                            bonus_amount = round(amount * float(method_discount['discount_value']) / 100, 2)
                        else:
                            bonus_amount = float(method_discount['discount_value'])
                        bonus_name = method_discount['name']
                
                conn.close()
            except Exception as e:
                logger.error(f"Error checking auto-discounts for Platega: {e}")
            
            # Обновляем баланс (с бонусом если есть)
            total_amount = amount + bonus_amount
            database.update_user_balance(user_id, total_amount)
            
            # Создаем транзакцию
            conn = database.get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO transactions (user_id, type, amount, status, payment_method, payment_provider, payment_id)
                VALUES (?, 'deposit', ?, 'Success', ?, 'Platega', ?)
            """, (user_id, total_amount, method_name, transaction_id))
            
            # Если был бонус, создаем отдельную транзакцию для него
            if bonus_amount > 0:
                cursor.execute("""
                    INSERT INTO transactions (user_id, type, amount, status, description)
                    VALUES (?, 'bonus', ?, 'Success', ?)
                """, (user_id, bonus_amount, f"Бонус: {bonus_name}"))
            
            conn.commit()
            conn.close()
            
            # Уведомление пользователю
            user = database.get_user_by_id(user_id)
            if user:
                if bonus_amount > 0:
                    msg = f"✅ Баланс пополнен на {amount}₽ + бонус {bonus_amount}₽ через Platega ({method_name})"
                else:
                    msg = f"✅ Баланс пополнен на {amount}₽ через Platega ({method_name})"
                core.send_notification_to_user(user['telegram_id'], msg)
                
                # Уведомление администратору о пополнении
                notify_admin_about_deposit(user, amount, method_name, 'Platega')
            
            logger.info(f"Platega платеж {transaction_id} успешно обработан: {amount}₽ для user {user_id}")
        
        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        logger.error(f"Platega webhook error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Проверка здоровья сервиса"""
    return jsonify({
        'status': 'ok',
        'platega_configured': platega.platega_api.is_configured
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('WEBHOOK_PORT', 5000)))
