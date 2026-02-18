"""
REST API сервер для мини-приложения и панели
"""
import os
import logging
import hmac
import hashlib
from datetime import datetime, timedelta
from urllib.parse import parse_qs, unquote
from flask import Flask, request, jsonify
from flask_cors import CORS
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../'))

from backend.database import database
from backend.core import core, abuse_detected
from backend.api import remnawave, platega

app = Flask(__name__)

# CORS для miniapp и панели
CORS(
    app,
    resources={r"/api/*": {"origins": "*"}},
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def format_datetime_msk(dt: datetime = None) -> str:
    """Форматировать datetime в ISO формат без миллисекунд (для МСК)"""
    if dt is None:
        dt = datetime.now()
    return dt.strftime('%Y-%m-%dT%H:%M:%S')

# Секретный ключ для аутентификации панели (legacy)
PANEL_SECRET = os.getenv('PANEL_SECRET', 'change_this_secret')
BOT_TOKEN = os.getenv('BOT_TOKEN', '')

def verify_telegram_webapp_data(init_data: str) -> dict | None:
    """
    Проверяет подлинность данных Telegram WebApp.
    Возвращает данные пользователя если валидно, иначе None.
    """
    if not init_data or not BOT_TOKEN:
        return None
    
    try:
        parsed = parse_qs(init_data)
        
        # Получаем hash из данных
        received_hash = parsed.get('hash', [''])[0]
        if not received_hash:
            return None
        
        # Создаём строку для проверки (все параметры кроме hash, отсортированные)
        data_check_arr = []
        for key, value in parsed.items():
            if key != 'hash':
                data_check_arr.append(f"{key}={value[0]}")
        data_check_arr.sort()
        data_check_string = '\n'.join(data_check_arr)
        
        # Создаём секретный ключ из токена бота
        secret_key = hmac.new(
            b'WebAppData',
            BOT_TOKEN.encode(),
            hashlib.sha256
        ).digest()
        
        # Вычисляем hash
        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        # Проверяем hash
        if not hmac.compare_digest(calculated_hash, received_hash):
            return None
        
        # Парсим данные пользователя
        import json
        user_data_str = parsed.get('user', [''])[0]
        if user_data_str:
            user_data = json.loads(unquote(user_data_str))
            return user_data
        
        return None
    except Exception as e:
        logger.error(f"Error verifying Telegram WebApp data: {e}")
        return None

def get_telegram_user_from_request() -> dict | None:
    """
    Получает и проверяет Telegram пользователя из запроса.
    Проверяет X-Telegram-Init-Data заголовок.
    """
    init_data = request.headers.get('X-Telegram-Init-Data', '')
    if init_data:
        return verify_telegram_webapp_data(init_data)
    return None

def require_telegram_auth(allow_user_id: bool = False):
    """
    Декоратор для проверки Telegram аутентификации.
    Если allow_user_id=True, также проверяет что user_id в запросе совпадает с authenticated user.
    """
    def decorator(f):
        def wrapper(*args, **kwargs):
            tg_user = get_telegram_user_from_request()
            
            # Если initData не валидный, проверяем fallback через telegram_id
            # Это менее безопасно, но сохраняет обратную совместимость
            if not tg_user:
                # В production здесь должен быть return jsonify({'error': 'Unauthorized'}), 401
                # Но для совместимости оставляем fallback
                pass
            
            # Добавляем user данные в kwargs для использования в функции
            kwargs['_tg_user'] = tg_user
            return f(*args, **kwargs)
        wrapper.__name__ = f.__name__
        return wrapper
    return decorator

def require_auth(f):
    """
    Декоратор для проверки аутентификации.
    Поддерживает:
    1. Legacy: Bearer {PANEL_SECRET}
    2. Новая система: Bearer {session_token}
    """
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({'error': 'Unauthorized'}), 401
        
        # Извлекаем токен
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Invalid authorization format'}), 401
        
        token = auth_header[7:]  # Убираем "Bearer "
        
        # Проверяем legacy PANEL_SECRET
        if token == PANEL_SECRET:
            return f(*args, **kwargs)
        
        # Проверяем сессию
        session = database.verify_panel_session(token)
        if session:
            return f(*args, **kwargs)
        
        return jsonify({'error': 'Unauthorized'}), 401
    wrapper.__name__ = f.__name__
    return wrapper

# ========== Шифрование ссылки для Happ ==========

@app.route('/api/encrypt-link', methods=['POST'])
def encrypt_link_for_happ():
    """Проксирует запрос на шифрование ссылки через crypto.happ.su"""
    import requests as req
    
    data = request.get_json()
    url = data.get('url') if data else None
    
    if not url:
        return jsonify({'error': 'URL is required'}), 400
    
    try:
        response = req.post(
            'https://crypto.happ.su/api.php',
            json={'url': url},
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        
        if response.ok:
            result = response.json()
            if result and result.get('encrypted_link'):
                return jsonify({'encrypted_link': result['encrypted_link']})
        
        logger.error(f"Happ encryption API failed: {response.status_code} - {response.text}")
        return jsonify({'error': 'Encryption failed'}), 500
    except Exception as e:
        logger.error(f"Happ encryption API error: {e}")
        return jsonify({'error': str(e)}), 500

# ========== Редирект для открытия Happ ==========

@app.route('/api/redirect')
def redirect_to_happ():
    """Страница редиректа для открытия приложения Happ"""
    from flask import Response
    
    url = request.args.get('url', '')
    
    html = f'''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Открываем Happ...</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #fff;
        }}
        @media (prefers-color-scheme: light) {{
            body {{
                background: linear-gradient(135deg, #f5f5f7 0%, #e5e7eb 100%);
                color: #1d1d1f;
            }}
            .spinner {{
                border-color: rgba(0,0,0,0.1);
                border-top-color: #3b82f6;
            }}
            .error {{
                background: rgba(0,0,0,0.05);
            }}
            .btn {{
                background: #3b82f6;
                color: #fff;
            }}
        }}
        .container {{ text-align: center; padding: 2rem; }}
        .spinner {{
            width: 48px;
            height: 48px;
            border: 4px solid rgba(255,255,255,0.2);
            border-top-color: #fff;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 1.5rem;
        }}
        @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
        h1 {{ font-size: 1.25rem; font-weight: 500; margin-bottom: 0.5rem; }}
        p {{ font-size: 0.875rem; opacity: 0.7; }}
        .error {{
            display: none;
            margin-top: 1.5rem;
            padding: 1rem;
            background: rgba(255,255,255,0.1);
            border-radius: 8px;
        }}
        .error.show {{ display: block; }}
        .btn {{
            display: inline-block;
            margin-top: 1rem;
            padding: 0.75rem 1.5rem;
            background: #fff;
            color: #1a1a2e;
            text-decoration: none;
            border-radius: 8px;
            font-weight: 500;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="spinner" id="spinner"></div>
        <h1 id="title">Открываем приложение...</h1>
        <p id="subtitle">Пожалуйста, подождите</p>
        <div class="error" id="errorBlock">
            <p>Если приложение не открылось, нажмите кнопку:</p>
            <a class="btn" id="manualBtn" href="#">Открыть приложение</a>
        </div>
    </div>

    <script>
        (function() {{
            var url = "{url}";
            
            if (!url) {{
                document.getElementById('title').textContent = 'URL не указан';
                document.getElementById('subtitle').textContent = '';
                document.getElementById('spinner').style.display = 'none';
                return;
            }}
            
            var manualBtn = document.getElementById('manualBtn');
            manualBtn.href = url;
            
            // Открываем URL напрямую
            window.location.href = url;
            
            // Показываем кнопку через 2 секунды если редирект не сработал
            setTimeout(function() {{
                document.getElementById('errorBlock').classList.add('show');
            }}, 2000);
        }})();
    </script>
</body>
</html>'''
    
    return Response(html, mimetype='text/html')

# ========== API для мини-приложения ==========

@app.route('/api/user/info', methods=['GET'])
def get_user_info():
    """Получить информацию о пользователе"""
    telegram_id = request.args.get('telegram_id', type=int)
    username = request.args.get('username', '')
    first_name = request.args.get('first_name', '')  # Имя пользователя из Telegram
    ref = request.args.get('ref', type=int)  # Telegram ID реферера
    
    if not telegram_id:
        return jsonify({'error': 'telegram_id required'}), 400
    
    # Нельзя быть своим собственным рефералом
    if ref == telegram_id:
        ref = None
    
    user = database.get_user_by_telegram_id(telegram_id)
    is_new_user = False
    
    # Автоматически создаем пользователя если его нет
    if not user:
        is_new_user = True
        
        # Обрабатываем реферала
        referred_by = None
        referrer = None
        if ref:
            # Проверяем, существует ли реферер
            referrer = database.get_user_by_telegram_id(ref)
            if referrer:
                # Проверяем рейт-лимит (25 рефералов в минуту)
                if database.check_referral_rate_limit(ref, limit=25, window_seconds=60):
                    referred_by = referrer['id']
                    logger.info(f"Referral accepted: user {telegram_id} referred by {ref}")
                else:
                    logger.warning(f"Referral rate limit exceeded for referrer {ref}")
        
        # Создаем пользователя с full_name = first_name
        user_id = database.create_user(
            telegram_id, 
            username or f'user_{telegram_id}',
            full_name=first_name or None,
            referred_by=referred_by
        )
        user = database.get_user_by_id(user_id)
        if not user:
            return jsonify({'error': 'Failed to create user'}), 500
        
        # Уведомляем реферера о новом реферале
        if referred_by and referrer:
            try:
                new_user_name = first_name or username or f"user_{telegram_id}"
                msg = (
                    f"🎉 <b>Новый реферал!</b>\n\n"
                    f"Пользователь <b>{new_user_name}</b> присоединился по вашей ссылке.\n"
                    f"Вы получите 50₽ за его первую покупку!"
                )
                core.send_notification_to_user(referrer['telegram_id'], msg)
                logger.info(f"Notified referrer {ref} about new referral {telegram_id}")
            except Exception as e:
                logger.error(f"Failed to notify referrer about new referral: {e}")
    else:
        # Пользователь уже существует - попробуем установить реферера, если его нет
        if ref and user.get('referred_by') is None:
            referrer = database.get_user_by_telegram_id(ref)
            if referrer:
                # Проверяем рейт-лимит
                if database.check_referral_rate_limit(ref, limit=25, window_seconds=60):
                    if database.set_referrer_for_user(user['id'], referrer['id']):
                        logger.info(f"Referral set for existing user {telegram_id} -> {ref}")
                        # Обновляем user для получения актуальных данных
                        user = database.get_user_by_telegram_id(telegram_id)
                else:
                    logger.warning(f"Referral rate limit exceeded for referrer {ref}")
        
        # Обновляем first_name если он изменился (всегда актуальное имя из Telegram)
        if first_name and first_name != user.get('full_name'):
            database.update_user_full_name(telegram_id, first_name)
            user = database.get_user_by_telegram_id(telegram_id)
    
    # Проверка бана (включая черный список)
    ban_status = abuse_detected.check_user_ban_status(user['id'], telegram_id)
    if ban_status.get('banned'):
        return jsonify({
            'banned': True,
            'reason': ban_status.get('reason', 'Аккаунт заблокирован'),
            'blacklisted': ban_status.get('blacklisted', False)
        }), 403
    
    stats = core.get_referral_stats(user['id'])
    
    # Получаем дату последнего вывода на карту
    last_card_withdrawal = None
    try:
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT created_at FROM transactions 
            WHERE user_id = ? AND type = 'withdrawal_request' AND payment_method = 'Карта'
            ORDER BY created_at DESC LIMIT 1
        """, (user['id'],))
        last_row = cursor.fetchone()
        if last_row:
            last_card_withdrawal = last_row['created_at']
        conn.close()
    except Exception as e:
        logger.error(f"Error getting last card withdrawal: {e}")

    return jsonify({
        'id': user['id'],
        'telegram_id': user['telegram_id'],
        'username': user.get('username'),
        'full_name': user.get('full_name'),  # First name из Telegram
        'balance': user.get('balance', 0),
        'status': user.get('status', 'Trial'),
        'referral_code': user.get('referral_code'),
        'partner_balance': stats.get('partner_balance', 0),  # Доступно для вывода
        'referrals_count': stats.get('referrals_count', 0),
        'referral_earned': stats.get('total_earned', 0),  # Всего заработано
        'referral_rate': stats.get('rate', 20),
        'is_new_user': is_new_user,
        'trial_used': user.get('trial_used', 0),  # Был ли использован пробный период
        'last_card_withdrawal': last_card_withdrawal,  # Дата последнего вывода на карту
    })

@app.route('/api/payment/create', methods=['POST'])
def create_payment():
    """Создать платеж"""
    data = request.json
    user_id = data.get('user_id')
    amount = data.get('amount')
    method = data.get('method')  # 'platega_card', 'platega_sbp'
    
    if not user_id or not amount or not method:
        return jsonify({'error': 'Missing required fields'}), 400
    
    user = database.get_user_by_id(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    return_url = f"{os.getenv('MINIAPP_URL', '')}/success"
    
    try:
        if method == 'platega_card':
            # Банковская карта через Platega
            payment = platega.platega_api.create_card_payment(amount, user_id)
            if payment:
                return jsonify({
                    'payment_id': payment.get('id'),
                    'payment_url': payment.get('redirect_url'),
                    'status': payment.get('status', 'pending')
                })
        
        elif method == 'platega_sbp':
            # СБП через Platega
            payment = platega.platega_api.create_sbp_payment(amount, user_id)
            if payment:
                return jsonify({
                    'payment_id': payment.get('id'),
                    'payment_url': payment.get('redirect_url'),
                    'status': payment.get('status', 'pending')
                })
        
        else:
            return jsonify({'error': f'Unknown payment method: {method}'}), 400
        
    except Exception as e:
        logger.error(f"Payment creation error for method {method}: {e}")
    
    return jsonify({'error': 'Payment creation failed'}), 500

@app.route('/api/promocode/apply', methods=['POST'])
def apply_promocode():
    """Применить промокод"""
    data = request.json
    user_id = data.get('user_id')
    code = data.get('code')
    
    if not user_id or not code:
        return jsonify({'error': 'Missing required fields'}), 400
    
    result = core.apply_promocode(user_id, code)
    return jsonify(result)

@app.route('/api/user/devices', methods=['GET'])
def get_user_devices():
    """Получить список устройств пользователя"""
    telegram_id = request.args.get('telegram_id', type=int)
    if not telegram_id:
        return jsonify({'error': 'telegram_id required'}), 400
    
    user = database.get_user_by_telegram_id(telegram_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    # Синхронизируем traffic_used из Remnawave
    try:
        rw_users = remnawave.remnawave_api.get_user_by_telegram_id(telegram_id)
        if rw_users:
            conn_sync = database.get_db_connection()
            cursor_sync = conn_sync.cursor()
            for rw_user in rw_users:
                rw_uuid = rw_user.uuid if hasattr(rw_user, 'uuid') else rw_user.get('uuid')
                # Получаем used_traffic_bytes из user_traffic
                traffic_used = 0
                if hasattr(rw_user, 'user_traffic') and rw_user.user_traffic:
                    traffic_used = rw_user.user_traffic.used_traffic_bytes
                elif hasattr(rw_user, 'used_traffic_bytes'):
                    traffic_used = rw_user.used_traffic_bytes
                
                if rw_uuid and traffic_used > 0:
                    cursor_sync.execute("""
                        UPDATE vpn_keys SET traffic_used = ? WHERE key_uuid = ?
                    """, (traffic_used, rw_uuid))
            conn_sync.commit()
            conn_sync.close()
    except Exception as e:
        logger.warning(f"Failed to sync traffic from Remnawave: {e}")
    
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT id, key_config, key_uuid, status as key_status, expiry_date,
                   traffic_used, traffic_limit, plan_type, created_at
            FROM vpn_keys
            WHERE user_id = ? AND key_uuid IS NOT NULL AND status != 'Deleted'
            ORDER BY created_at DESC
        """, (user['id'],))
        
        rows = cursor.fetchall()
        devices = []
        for row in rows:
            from datetime import datetime
            created_at = row['created_at']
            if created_at:
                try:
                    if isinstance(created_at, str):
                        dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    else:
                        dt = created_at
                    added_formatted = dt.strftime('%d.%m.%Y')
                except:
                    added_formatted = str(created_at)[:10]
            else:
                added_formatted = datetime.now().strftime('%d.%m.%Y')
            
            # Рассчитываем оставшееся время с точностью до минуты
            days_left = None
            hours_left = None
            is_expired = False
            expiry_date_str = None
            if row['expiry_date']:
                try:
                    if isinstance(row['expiry_date'], str):
                        expiry_dt = datetime.fromisoformat(row['expiry_date'].replace('Z', '+00:00'))
                    else:
                        expiry_dt = row['expiry_date']
                    
                    # Убираем timezone info для корректного сравнения
                    if expiry_dt.tzinfo:
                        expiry_dt = expiry_dt.replace(tzinfo=None)
                    
                    now = datetime.now()
                    diff = expiry_dt - now
                    total_seconds = diff.total_seconds()
                    
                    if total_seconds <= 0:
                        is_expired = True
                        days_left = 0
                        hours_left = 0
                    else:
                        # Округляем вверх - если осталось хотя бы 1 секунда, это ещё не истекло
                        import math
                        total_hours = total_seconds / 3600
                        days_left = int(total_hours / 24)
                        hours_left = int(math.ceil(total_hours % 24))
                        # Если меньше 1 дня, но есть часы - показываем 0 дней
                        if days_left == 0 and hours_left > 0:
                            days_left = 0  # Покажем часы
                    
                    expiry_date_str = format_datetime_msk(expiry_dt)
                except Exception as e:
                    logger.error(f"Error parsing expiry_date: {e}")
            
            # Короткий UUID для отображения (первые 8 символов)
            short_uuid = row['key_uuid'][:8] if row['key_uuid'] else None
            
            # Определяем тип устройства
            device_name = 'VPN подписка'
            
            # Получаем plan_type безопасно
            plan_type = 'vpn'
            try:
                if 'plan_type' in row.keys():
                    plan_type = row['plan_type'] or 'vpn'
            except:
                plan_type = 'vpn'
            
            devices.append({
                'id': row['id'],
                'name': device_name,
                'type': 'universal',
                'added': added_formatted,
                'key_config': row['key_config'],
                'key_uuid': row['key_uuid'],
                'short_uuid': short_uuid,
                'key_status': row['key_status'],
                'days_left': days_left,
                'hours_left': hours_left,
                'is_expired': is_expired,
                'expiry_date': expiry_date_str,
                'traffic_used': row['traffic_used'],
                'traffic_limit': row['traffic_limit'],
                'plan_type': plan_type
            })
        
        return jsonify(devices)
    finally:
        conn.close()

@app.route('/api/user/history', methods=['GET'])
def get_user_history():
    """Получить историю транзакций пользователя"""
    telegram_id = request.args.get('telegram_id', type=int)
    if not telegram_id:
        return jsonify({'error': 'telegram_id required'}), 400
    
    user = database.get_user_by_telegram_id(telegram_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT id, type, amount, description, created_at, status, payment_method
            FROM transactions
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT 100
        """, (user['id'],))
        
        rows = cursor.fetchall()
        history = []
        for row in rows:
            # Маппинг типов транзакций
            type_map = {
                'deposit': 'deposit',
                'withdrawal': 'withdrawal',
                'subscription': 'sub_off',
                'device_purchase': 'buy_dev',
                'trial': 'trial'
            }
            
            title_map = {
                'deposit': f'Пополнение баланса ({row["payment_method"] or ""})',
                'withdrawal': 'Вывод средств',
                'subscription': 'Списание за подписку',
                'device_purchase': 'Покупка устройства',
                'trial': 'Активация пробного периода'
            }
            
            trans_type = type_map.get(row['type'], row['type'])
            title = row['description'] or title_map.get(row['type'], row['type'])
            
            # Форматирование даты
            from datetime import datetime
            date_str = row['created_at']
            if date_str:
                try:
                    if isinstance(date_str, str):
                        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    else:
                        dt = date_str
                    # Месяцы на русском
                    months = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
                    month_idx = dt.month - 1
                    date_formatted = f"{dt.day} {months[month_idx]} {dt.year}"
                except:
                    date_formatted = str(date_str)[:10]
            else:
                date_formatted = datetime.now().strftime('%d %b %Y')
            
            history.append({
                'id': row['id'],
                'type': trans_type,
                'title': title,
                'amount': float(row['amount']),
                'date': date_formatted
            })
        
        return jsonify(history)
    finally:
        conn.close()

@app.route('/api/user/payment-methods', methods=['GET'])
def get_user_payment_methods():
    """Получить сохраненные способы оплаты пользователя"""
    telegram_id = request.args.get('telegram_id', type=int)
    if not telegram_id:
        return jsonify({'error': 'telegram_id required'}), 400
    
    user = database.get_user_by_telegram_id(telegram_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    conn = database.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT id, payment_provider, payment_method_id, payment_method_type, 
                   card_last4, card_brand, created_at
            FROM saved_payment_methods
            WHERE user_id = ? AND is_active = 1
            ORDER BY created_at DESC
        """, (user['id'],))
        rows = cursor.fetchall()
        methods = []
        for row in rows:
            methods.append({
                'id': row['id'],
                'provider': row['payment_provider'],
                'payment_method_id': row['payment_method_id'],
                'type': row['payment_method_type'],
                'card_last4': row['card_last4'],
                'card_brand': row['card_brand'],
                'created_at': row['created_at']
            })
        return jsonify(methods)
    finally:
        conn.close()

@app.route('/api/user/payment-methods/<int:method_id>', methods=['DELETE'])
def delete_payment_method(method_id: int):
    """Удалить сохраненный способ оплаты"""
    telegram_id = request.args.get('telegram_id', type=int)
    if not telegram_id:
        return jsonify({'error': 'telegram_id required'}), 400
    
    user = database.get_user_by_telegram_id(telegram_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    conn = database.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE saved_payment_methods
            SET is_active = 0
            WHERE id = ? AND user_id = ?
        """, (method_id, user['id']))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()

@app.route('/api/user/devices/<int:device_id>', methods=['DELETE'])
def delete_user_device(device_id: int):
    """Удалить устройство пользователя и ключ из Remnawave"""
    telegram_id = request.args.get('telegram_id', type=int)
    if not telegram_id:
        return jsonify({'error': 'telegram_id required'}), 400
    
    user = database.get_user_by_telegram_id(telegram_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    conn = database.get_db_connection()
    cursor = conn.cursor()
    try:
        # Проверяем, что устройство принадлежит пользователю
        cursor.execute("""
            SELECT id, key_uuid FROM vpn_keys
            WHERE id = ? AND user_id = ?
        """, (device_id, user['id']))
        device = cursor.fetchone()
        
        if not device:
            return jsonify({'error': 'Device not found'}), 404
        
        key_uuid = device['key_uuid']
        
        # Удаляем из Remnawave если есть UUID
        if key_uuid:
            try:
                remnawave.remnawave_api.delete_user_sync(key_uuid)
                logger.info(f"Deleted key {key_uuid} from Remnawave")
            except Exception as e:
                logger.error(f"Failed to delete key {key_uuid} from Remnawave: {e}")
        
        # Удаляем устройство/ключ (теперь это одна запись)
        cursor.execute("DELETE FROM vpn_keys WHERE id = ?", (device_id,))
        
        conn.commit()
        logger.info(f"Device {device_id} deleted for user {telegram_id}")
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        logger.error(f"Error deleting device {device_id}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/subscription/extend', methods=['POST'])
def extend_subscription():
    """Продлить существующую подписку (не создавать новый ключ)"""
    data = request.json
    user_id = data.get('user_id')
    key_id = data.get('key_id')  # ID существующего ключа для продления
    days = data.get('days')
    price = data.get('price', 0)
    
    if not user_id or not key_id or not days:
        return jsonify({'error': 'Missing required fields'}), 400
    
    user = database.get_user_by_id(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    # Получаем существующий ключ
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT id, key_uuid, expiry_date, plan_type, traffic_limit, status
            FROM vpn_keys WHERE id = ? AND user_id = ?
        """, (key_id, user_id))
        key_row = cursor.fetchone()
        
        if not key_row:
            return jsonify({'error': 'Key not found'}), 404
        
        key_uuid = key_row['key_uuid']
        current_expiry = key_row['expiry_date']
        plan_type = key_row['plan_type'] or 'vpn'
        
        # Списываем баланс
        if price > 0:
            deducted = database.update_user_balance(user_id, -price, ensure_non_negative=True)
            if not deducted:
                return jsonify({'error': 'Insufficient balance'}), 400
        
        # Рассчитываем новую дату истечения
        from datetime import datetime, timedelta
        
        # Если ключ истёк, продлеваем от текущей даты
        # Если активен - добавляем к существующей дате
        if current_expiry:
            try:
                expiry_dt = datetime.fromisoformat(current_expiry.replace('Z', '+00:00').replace('+00:00', ''))
            except:
                expiry_dt = datetime.now()
            
            if expiry_dt < datetime.now():
                # Ключ истёк - продлеваем от сейчас
                new_expiry = datetime.now() + timedelta(days=days)
            else:
                # Ключ ещё активен - добавляем дни
                new_expiry = expiry_dt + timedelta(days=days)
        else:
            new_expiry = datetime.now() + timedelta(days=days)
        
        new_expiry_str = new_expiry.isoformat()
        
        # Обновляем ключ в Remnawave
        if key_uuid:
            try:
                remnawave.remnawave_api.update_user_sync(
                    uuid=key_uuid,
                    expire_at=new_expiry,
                    status=remnawave.UserStatus.ACTIVE
                )
            except Exception as e:
                logger.error(f"Failed to update key in Remnawave: {e}")
                # Возвращаем баланс если не удалось обновить
                if price > 0:
                    database.update_user_balance(user_id, price)
                return jsonify({'error': 'Failed to extend subscription in VPN system'}), 500
        
        # Обновляем ключ в БД
        cursor.execute("""
            UPDATE vpn_keys SET 
                status = 'Active',
                expiry_date = ?
            WHERE id = ?
        """, (new_expiry_str, key_id))
        conn.commit()
        
        # Создаем транзакцию
        description = f"Продление подписки ({days} дней)"
        cursor.execute("""
            INSERT INTO transactions (user_id, type, amount, status, description, payment_method)
            VALUES (?, 'subscription_extend', ?, 'Success', ?, 'Balance')
        """, (user_id, -price, description))
        conn.commit()
        
        # Начисляем доход рефереру
        if price > 0:
            referral_result = database.credit_referral_income(user_id, price, f"Доход от продления подписки ({description})")
            if referral_result:
                logger.info(f"Credited {referral_result['income']}₽ to referrer for extension")
                try:
                    referrer_telegram_id = referral_result['referrer_telegram_id']
                    income = referral_result['income']
                    msg = (
                        f"💰 <b>Реферальный доход!</b>\n\n"
                        f"Ваш реферал совершил первую покупку.\n"
                        f"Ваше вознаграждение: <b>{income:.0f}₽</b>\n\n"
                        f"Доступно для вывода: проверьте в разделе «Рефералы»"
                    )
                    core.send_notification_to_user(referrer_telegram_id, msg)
                except Exception as e:
                    logger.error(f"Failed to notify referrer: {e}")
        
        return jsonify({
            'success': True,
            'key_id': key_id,
            'new_expiry': new_expiry_str
        })
        
    except Exception as e:
        logger.error(f"Error extending subscription: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/subscription/create', methods=['POST'])
def create_subscription():
    """Создать подписку"""
    data = request.json
    user_id = data.get('user_id')
    days = data.get('days')
    plan_type = data.get('type', 'vpn')  # Только 'vpn'
    use_auto_pay = data.get('use_auto_pay', False)  # Использовать автоплатеж
    payment_method_id = data.get('payment_method_id')  # ID сохраненного способа оплаты
    is_trial = data.get('is_trial', False)  # Пробный период
    
    if not user_id or not days:
        return jsonify({'error': 'Missing required fields'}), 400
    
    user = database.get_user_by_id(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    # Проверка пробного периода
    if is_trial:
        if user.get('trial_used', 0) == 1:
            return jsonify({'error': 'Пробный период уже использован'}), 400
        # Триальные настройки
        days = 1
        price = 0
    else:
        # VPN подписка - используем фиксированные цены из планов
        price = data.get('price', days * 3.3)
    
    # Автоплатеж отключен (yookassa удален)
    
    # Для пробного периода не списываем баланс
    if not is_trial:
        deducted = database.update_user_balance(user_id, -price, ensure_non_negative=True)
        if not deducted:
            return jsonify({'error': 'Insufficient balance'}), 400
    
    # Создаем подписку
    logger.info(f"Creating subscription for user_id={user_id}, telegram_id={user['telegram_id']}, days={days}, is_trial={is_trial}")
    if is_trial:
        # Пробный период - 10 ГБ трафика
        traffic_limit_bytes = int(10 * (1024 ** 3))
        result = core.create_user_and_subscription(
            user['telegram_id'], user.get('username', ''), days,
            traffic_limit=traffic_limit_bytes,
            plan_type='vpn'
        )
    else:
        # Обычный VPN - безлимитный трафик (0 = unlimited)
        result = core.create_user_and_subscription(
            user['telegram_id'], user.get('username', ''), days,
            traffic_limit=0,
            plan_type='vpn'
        )
    
    logger.info(f"Subscription creation result: {result is not None}, result={result}")
    
    if result:
        conn = database.get_db_connection()
        cursor = conn.cursor()
        
        if is_trial:
            # Помечаем пробный период как использованный
            cursor.execute("UPDATE users SET trial_used = 1 WHERE id = ?", (user_id,))
            description = "Активация пробного периода (1 день)"
            trans_type = 'trial'
        else:
            description = f"VPN подписка ({days} дней)"
            trans_type = 'subscription'
        
        # Создаем транзакцию
        cursor.execute("""
            INSERT INTO transactions (user_id, type, amount, status, description, payment_method)
            VALUES (?, ?, ?, 'Success', ?, 'Balance')
        """, (user_id, trans_type, -price, description))
        conn.commit()
        conn.close()
        
        # Начисляем доход рефереру (если есть) - только для платных подписок
        if not is_trial and price > 0:
            referral_result = database.credit_referral_income(user_id, price, f"Доход от покупки подписки ({description})")
            if referral_result:
                logger.info(f"Credited {referral_result['income']}₽ to referrer {referral_result['referrer_telegram_id']}")
                # Уведомляем реферера о доходе
                try:
                    referrer_telegram_id = referral_result['referrer_telegram_id']
                    income = referral_result['income']
                    msg = (
                        f"💰 <b>Реферальный доход!</b>\n\n"
                        f"Ваш реферал совершил первую покупку.\n"
                        f"Ваше вознаграждение: <b>{income:.0f}₽</b>\n\n"
                        f"Доступно для вывода: проверьте в разделе «Рефералы»"
                    )
                    core.send_notification_to_user(referrer_telegram_id, msg)
                except Exception as e:
                    logger.error(f"Failed to notify referrer: {e}")
        
        return jsonify({'success': True, 'subscription': result})
    
    # Откат баланса, если создание не удалось (только для не-триала)
    if not is_trial:
        database.update_user_balance(user_id, price)
    return jsonify({'error': 'Failed to create subscription'}), 500

# ========== API для панели ==========

@app.route('/api/panel/users', methods=['GET'])
@require_auth
def get_users():
    """Получить список пользователей с информацией о черном списке"""
    limit = request.args.get('limit', 100, type=int)
    offset = request.args.get('offset', 0, type=int)
    raw_users = database.get_all_users(limit, offset)
    
    # Получаем telegram_id всех пользователей из черного списка
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT telegram_id FROM blacklist")
    blacklisted_ids = set(row['telegram_id'] for row in cursor.fetchall())
    conn.close()
    
    # Добавляем статус черного списка к каждому пользователю
    for user in raw_users:
        user['in_blacklist'] = user.get('telegram_id') in blacklisted_ids
    
    return jsonify(raw_users)

@app.route('/api/panel/promocodes', methods=['GET'])
@require_auth
def get_promocodes():
    """Получить список промокодов"""
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM promocodes ORDER BY id DESC")
    promos = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(promos)

@app.route('/api/panel/promocodes', methods=['POST'])
@require_auth
def create_promocode():
    """Создать промокод"""
    data = request.json
    conn = database.get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO promocodes (code, type, value, uses_limit, expires_at, is_active, target_type)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data.get('code', '').upper(),
            data.get('type'),
            str(data.get('value')),
            data.get('uses_limit'),
            data.get('expires_at'),
            1 if data.get('is_active', 1) else 0,
            data.get('target_type', 'all'),  # all, vpn
        ),
    )

    conn.commit()
    promo_id = cursor.lastrowid

    cursor.execute("SELECT * FROM promocodes WHERE id = ?", (promo_id,))
    promo = dict(cursor.fetchone())

    conn.close()

    return jsonify({'id': promo_id, 'success': True, 'promocode': promo})


@app.route('/api/panel/promocodes/<int:promo_id>', methods=['PUT'])
@require_auth
def update_promocode(promo_id: int):
    """Обновить промокод"""
    data = request.json or {}
    conn = database.get_db_connection()
    cursor = conn.cursor()

    # Собираем поля для обновления динамически
    fields = []
    values = []

    mapping = {
        'code': 'code',
        'type': 'type',
        'value': 'value',
        'uses_limit': 'uses_limit',
        'expires_at': 'expires_at',
        'is_active': 'is_active',
        'target_type': 'target_type',  # all, vpn
    }

    for key, column in mapping.items():
        if key in data:
            val = data[key]
            if key == 'code' and isinstance(val, str):
                val = val.upper()
            if key == 'is_active':
                val = 1 if val else 0
            fields.append(f"{column} = ?")
            values.append(val)

    if not fields:
        conn.close()
        return jsonify({'success': False, 'error': 'Nothing to update'}), 400

    values.append(promo_id)

    cursor.execute(
        f"UPDATE promocodes SET {', '.join(fields)} WHERE id = ?",
        tuple(values),
    )
    conn.commit()

    cursor.execute("SELECT * FROM promocodes WHERE id = ?", (promo_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return jsonify({'success': False, 'error': 'Promocode not found'}), 404

    return jsonify({'success': True, 'promocode': dict(row)})

@app.route('/api/panel/mailing', methods=['POST'])
@require_auth
def send_mailing():
    """Отправить рассылку с поддержкой HTML/Markdown форматирования"""
    data = request.json
    message = data.get('message')
    target_users = data.get('target_users', 'all')  # 'all' or list/int user_ids
    button_type = data.get('button_type')
    button_value = data.get('button_value')
    image_url = data.get('image_url')
    parse_mode = data.get('parse_mode', 'HTML')  # HTML или Markdown

    if not message:
        return jsonify({'success': False, 'error': 'Message is required'}), 400

    conn = database.get_db_connection()
    cursor = conn.cursor()

    try:
        # Определяем список получателей
        user_rows = []
        if target_users == 'all':
            cursor.execute("SELECT id, telegram_id FROM users WHERE is_banned = 0 OR is_banned IS NULL")
            user_rows = cursor.fetchall()
        elif target_users == 'active':
            # Пользователи с активными подписками
            cursor.execute("""
                SELECT DISTINCT u.id, u.telegram_id FROM users u
                JOIN vpn_keys vk ON u.id = vk.user_id
                WHERE (u.is_banned = 0 OR u.is_banned IS NULL)
                  AND vk.status = 'Active' AND vk.expiry_date > datetime('now')
            """)
            user_rows = cursor.fetchall()
        elif target_users == 'expired':
            # Пользователи с истёкшими подписками
            cursor.execute("""
                SELECT DISTINCT u.id, u.telegram_id FROM users u
                JOIN vpn_keys vk ON u.id = vk.user_id
                WHERE (u.is_banned = 0 OR u.is_banned IS NULL)
                  AND (vk.status = 'Expired' OR vk.expiry_date < datetime('now'))
            """)
            user_rows = cursor.fetchall()
        elif target_users == 'no_subscription':
            # Пользователи без подписок
            cursor.execute("""
                SELECT u.id, u.telegram_id FROM users u
                WHERE (u.is_banned = 0 OR u.is_banned IS NULL)
                  AND u.id NOT IN (SELECT DISTINCT user_id FROM vpn_keys)
            """)
            user_rows = cursor.fetchall()
        elif isinstance(target_users, list):
            placeholders = ",".join("?" for _ in target_users)
            cursor.execute(
                f"SELECT id, telegram_id FROM users WHERE id IN ({placeholders}) AND (is_banned = 0 OR is_banned IS NULL)",
                tuple(target_users),
            )
            user_rows = cursor.fetchall()

        # Формируем кнопки если есть
        reply_markup = None
        miniapp_url = os.getenv('MINIAPP_URL', 'https://your-domain.com/miniapp')
        
        if button_type and button_value:
            if button_type == 'external_link' or button_type == 'url':
                # Внешняя ссылка: значение может быть "Текст|URL" или просто URL
                if '|' in button_value:
                    btn_text, btn_url = button_value.split('|', 1)
                else:
                    btn_text = 'Перейти'
                    btn_url = button_value
                reply_markup = {
                    'inline_keyboard': [[{'text': btn_text, 'url': btn_url}]]
                }
            elif button_type == 'open_miniapp' or button_type == 'webapp':
                # Открытие мини-приложения
                btn_text = button_value if button_value else 'Открыть приложение'
                reply_markup = {
                    'inline_keyboard': [[{'text': btn_text, 'web_app': {'url': miniapp_url}}]]
                }
            elif button_type == 'activate_promo':
                # Кнопка с промокодом - добавляет промокод в deep link
                promo_url = f"https://t.me/{os.getenv('BOT_USERNAME', 'your_bot')}?start=promo_{button_value}"
                reply_markup = {
                    'inline_keyboard': [[{'text': f'🎁 Активировать промокод {button_value}', 'url': promo_url}]]
                }
            elif button_type == 'add_balance':
                # Кнопка пополнения баланса - открывает мини-приложение на странице пополнения
                balance_url = f"{miniapp_url}?view=topup&amount={button_value}"
                reply_markup = {
                    'inline_keyboard': [[{'text': f'💰 Пополнить на {button_value}₽', 'web_app': {'url': balance_url}}]]
                }

        sent = 0
        errors = 0
        for row in user_rows:
            telegram_id = row['telegram_id']
            try:
                if image_url:
                    # Отправка с изображением
                    success = core.send_photo_to_user(telegram_id, image_url, message, parse_mode, reply_markup)
                else:
                    # Обычная рассылка
                    success = core.send_formatted_notification(telegram_id, message, parse_mode, reply_markup)
                
                if success:
                    sent += 1
                else:
                    errors += 1
            except Exception as e:
                logger.error(f"Error sending mailing to {telegram_id}: {e}")
                errors += 1

        # Сохраняем запись о рассылке
        cursor.execute(
            """
            INSERT INTO mailings (title, message_text, target_users, sent_count, status, sent_at, button_type, button_value, image_url)
            VALUES (?, ?, ?, ?, 'Completed', CURRENT_TIMESTAMP, ?, ?, ?)
            """,
            (data.get('title', ''), message, str(target_users), sent, button_type, button_value, image_url),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({'success': True, 'sent': sent, 'errors': errors})

@app.route('/api/panel/mailing/stats', methods=['GET'])
@require_auth
def get_mailing_stats():
    """Получить статистику рассылок"""
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Общее количество отправленных сообщений
        cursor.execute("SELECT COALESCE(SUM(sent_count), 0) AS total FROM mailings WHERE status = 'Completed'")
        total_sent = cursor.fetchone()['total'] or 0
        
        # Доставляемость - считаем по реальным данным
        cursor.execute("""
            SELECT COALESCE(SUM(sent_count), 0) as total_sent, 
                   COALESCE(SUM(CASE WHEN status = 'Completed' THEN sent_count ELSE 0 END), 0) as delivered
            FROM mailings
        """)
        delivery_row = cursor.fetchone()
        total_sent_for_rate = delivery_row['total_sent'] or 0
        delivered_count = delivery_row['delivered'] or 0
        # Если все успешно отправлены - 100%
        delivered_rate = (delivered_count / total_sent_for_rate * 100) if total_sent_for_rate > 0 else 100
        
        # Переходы (пока нет трекинга, возвращаем 0)
        clicks = 0
        
        # Последняя кампания
        cursor.execute("""
            SELECT title, sent_at FROM mailings 
            WHERE status = 'Completed' 
            ORDER BY sent_at DESC LIMIT 1
        """)
        last_campaign_row = cursor.fetchone()
        last_campaign = last_campaign_row['title'] if last_campaign_row else None
        last_campaign_date = last_campaign_row['sent_at'] if last_campaign_row else None
        
        return jsonify({
            'totalSent': total_sent,
            'delivered': delivered_rate,
            'clicks': clicks,
            'lastCampaign': last_campaign,
            'lastCampaignDate': last_campaign_date
        })
    finally:
        conn.close()

@app.route('/api/panel/mailing/history', methods=['GET'])
@require_auth
def get_mailing_history():
    """Получить историю рассылок"""
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT id, title, message_text, sent_count, status, sent_at, created_at
            FROM mailings
            ORDER BY created_at DESC
            LIMIT 50
        """)
        rows = cursor.fetchall()
        history = []
        for row in rows:
            from datetime import datetime
            date_str = row['sent_at'] or row['created_at']
            if date_str:
                try:
                    if isinstance(date_str, str):
                        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    else:
                        dt = date_str
                    date_formatted = dt.strftime('%d.%m.%y')
                except:
                    date_formatted = str(date_str)[:10]
            else:
                date_formatted = ''
            
            history.append({
                'id': row['id'],
                'title': row['title'] or row['message_text'][:50] if row['message_text'] else 'Без названия',
                'sent_count': row['sent_count'] or 0,
                'status': row['status'],
                'date': date_formatted
            })
        
        return jsonify(history)
    finally:
        conn.close()


@app.route('/api/panel/transactions', methods=['GET'])
@require_auth
def get_transactions():
    """Получить список транзакций - только успешные пополнения и выводы, без действий администратора"""
    limit = request.args.get('limit', 100, type=int)
    offset = request.args.get('offset', 0, type=int)
    
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Показываем только успешные пополнения (deposit) и выводы (withdrawal_request)
        # Исключаем действия администратора (admin_deposit, admin_withdraw) и другие типы
        cursor.execute("""
            SELECT 
                t.id,
                t.user_id,
                u.username,
                t.type,
                t.amount,
                t.status,
                t.payment_method,
                t.payment_provider,
                t.payment_id,
                t.hash,
                t.created_at
            FROM transactions t
            LEFT JOIN users u ON t.user_id = u.id
            WHERE t.type IN ('deposit', 'withdrawal_request')
              AND t.status = 'Success'
              AND t.payment_method != 'Admin'
            ORDER BY t.created_at DESC
            LIMIT ? OFFSET ?
        """, (limit, offset))
        
        rows = cursor.fetchall()
        transactions = []
        for row in rows:
            username = row['username'] or f"user_{row['user_id']}"
            transactions.append({
                'id': row['id'],
                'user_id': row['user_id'],
                'user': f"@{username}" if username and not username.startswith('@') else username,
                'amount': float(row['amount']),
                'type': row['type'],
                'status': row['status'] or 'Pending',
                'payment_method': row['payment_method'] or 'Unknown',
                'payment_provider': row['payment_provider'] or '',
                'payment_id': row['payment_id'] or '',
                'hash': row['hash'] or row['payment_id'] or '',
                'created_at': row['created_at']
            })
        
        return jsonify(transactions)
    finally:
        conn.close()

@app.route('/api/panel/transactions/<int:transaction_id>/refund', methods=['POST'])
@require_auth
def refund_transaction(transaction_id: int):
    """Сделать возврат по транзакции"""
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Получаем транзакцию
        cursor.execute("""
            SELECT t.*, u.telegram_id, u.username
            FROM transactions t
            LEFT JOIN users u ON t.user_id = u.id
            WHERE t.id = ?
        """, (transaction_id,))
        
        transaction = cursor.fetchone()
        if not transaction:
            return jsonify({'success': False, 'error': 'Транзакция не найдена'}), 404
        
        if transaction['type'] != 'deposit':
            return jsonify({'success': False, 'error': 'Возврат возможен только для пополнений'}), 400
        
        if transaction['status'] == 'Refunded':
            return jsonify({'success': False, 'error': 'Транзакция уже была возвращена'}), 400
        
        amount = float(transaction['amount'])
        user_id = transaction['user_id']
        payment_id = transaction['payment_id']
        payment_provider = transaction['payment_provider']
        
        # Возврат через API отключен для yookassa (удален)
        refund_result = None
        
        # Списываем сумму с баланса пользователя
        user = database.get_user_by_id(user_id)
        if user:
            current_balance = user.get('balance', 0)
            new_balance = max(0, current_balance - amount)  # Не уходим в минус
            
            cursor.execute("""
                UPDATE users SET balance = ? WHERE id = ?
            """, (new_balance, user_id))
        
        # Помечаем транзакцию как возвращенную
        cursor.execute("""
            UPDATE transactions 
            SET status = 'Refunded', refunded_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (transaction_id,))
        
        # Создаем транзакцию возврата
        cursor.execute("""
            INSERT INTO transactions (user_id, type, amount, status, payment_method, payment_provider, description)
            VALUES (?, 'refund', ?, 'Success', ?, ?, ?)
        """, (user_id, -amount, transaction['payment_method'], payment_provider, f'Возврат по транзакции #{transaction_id}'))
        
        conn.commit()
        
        # Уведомляем пользователя
        if transaction['telegram_id']:
            core.send_notification_to_user(
                transaction['telegram_id'],
                f"💸 Возврат средств: {amount}₽ по транзакции #{transaction_id}"
            )
        
        logger.info(f"Возврат по транзакции #{transaction_id}: {amount}₽ для user {user_id}")
        
        return jsonify({
            'success': True, 
            'message': f'Возврат {amount}₽ выполнен успешно',
            'refund_id': refund_result.get('id') if refund_result else None
        })
        
    except Exception as e:
        logger.error(f"Error refunding transaction {transaction_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/panel/users/<int:user_id>/subscriptions', methods=['GET'])
@require_auth
def get_user_subscriptions(user_id: int):
    """Получить все подписки (ключи) пользователя с синхронизацией трафика из Remnawave"""
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Получаем telegram_id пользователя для запроса к Remnawave
        cursor.execute("SELECT telegram_id FROM users WHERE id = ?", (user_id,))
        user_row = cursor.fetchone()
        telegram_id = user_row['telegram_id'] if user_row else None
        
        cursor.execute("""
            SELECT vk.id, vk.key_uuid, vk.status, vk.expiry_date, 
                   vk.traffic_used, vk.traffic_limit, vk.created_at,
                   'vpn' as type
            FROM vpn_keys vk
            WHERE vk.user_id = ?
            ORDER BY vk.created_at DESC
        """, (user_id,))
        
        rows = cursor.fetchall()
        
        # Получаем трафик из Remnawave
        remnawave_traffic = {}
        if telegram_id:
            try:
                rw_users = remnawave.remnawave_api.get_user_by_telegram_id(telegram_id)
                for rw_user in rw_users:
                    if hasattr(rw_user, 'uuid'):
                        traffic_used = 0
                        if hasattr(rw_user, 'user_traffic') and rw_user.user_traffic:
                            traffic_used = rw_user.user_traffic.used_traffic_bytes
                        elif hasattr(rw_user, 'used_traffic_bytes'):
                            traffic_used = rw_user.used_traffic_bytes
                        remnawave_traffic[rw_user.uuid] = traffic_used
            except Exception as e:
                logger.warning(f"Failed to sync traffic from Remnawave: {e}")
        
        subscriptions = []
        
        for row in rows:
            days_left = 0
            hours_left = 0
            is_expired = False
            if row['expiry_date']:
                try:
                    if isinstance(row['expiry_date'], str):
                        expiry_dt = datetime.fromisoformat(row['expiry_date'].replace('Z', '+00:00'))
                    else:
                        expiry_dt = row['expiry_date']
                    
                    if expiry_dt.tzinfo:
                        expiry_dt = expiry_dt.replace(tzinfo=None)
                    
                    diff = expiry_dt - datetime.now()
                    total_seconds = diff.total_seconds()
                    
                    if total_seconds <= 0:
                        is_expired = True
                        days_left = 0
                        hours_left = 0
                    else:
                        import math
                        total_hours = total_seconds / 3600
                        days_left = int(total_hours / 24)
                        hours_left = int(math.ceil(total_hours % 24))
                except:
                    is_expired = True
            
            # Получаем актуальный трафик из Remnawave
            traffic_used = float(row['traffic_used'] or 0)
            key_uuid = row['key_uuid']
            if key_uuid and key_uuid in remnawave_traffic:
                traffic_used = float(remnawave_traffic[key_uuid])
                # Обновляем в БД
                try:
                    cursor.execute("UPDATE vpn_keys SET traffic_used = ? WHERE key_uuid = ?", 
                                 (traffic_used, key_uuid))
                except:
                    pass
            
            subscriptions.append({
                'id': row['id'],
                'key_uuid': row['key_uuid'],
                'short_uuid': row['key_uuid'][:8] if row['key_uuid'] else None,
                'status': row['status'],
                'expiry_date': row['expiry_date'],
                'days_left': days_left if days_left is not None else 0,
                'traffic_used': traffic_used,
                'traffic_limit': float(row['traffic_limit'] or 0),
                'type': row['type']
            })
        
        # Commit обновлений трафика
        try:
            conn.commit()
        except:
            pass
        
        return jsonify(subscriptions)
    finally:
        conn.close()


@app.route('/api/panel/users/<int:user_id>/unban', methods=['POST'])
@require_auth
def unban_user(user_id: int):
    """Разбанить пользователя (снять is_banned и удалить из черного списка)"""
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Проверяем существование пользователя
        cursor.execute("SELECT id, telegram_id, username, is_banned FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()
        
        if not user:
            return jsonify({'success': False, 'error': 'Пользователь не найден'}), 404
        
        telegram_id = user['telegram_id']
        
        # Проверяем, в черном списке ли пользователь
        cursor.execute("SELECT 1 FROM blacklist WHERE telegram_id = ?", (telegram_id,))
        in_blacklist = cursor.fetchone() is not None
        
        # Если не забанен И не в черном списке - ошибка
        if not user['is_banned'] and not in_blacklist:
            return jsonify({'success': False, 'error': 'Пользователь не заблокирован'}), 400
        
        # Разбаниваем пользователя (снимаем is_banned)
        cursor.execute("UPDATE users SET is_banned = 0, ban_reason = NULL WHERE id = ?", (user_id,))
        
        # Удаляем из черного списка
        if in_blacklist:
            cursor.execute("DELETE FROM blacklist WHERE telegram_id = ?", (telegram_id,))
            logger.info(f"User {user_id} (telegram_id={telegram_id}) removed from blacklist")
        
        conn.commit()
        
        # Уведомляем пользователя
        if telegram_id:
            core.send_notification_to_user(
                telegram_id,
                "✅ Ваш аккаунт разблокирован! Вы снова можете пользоваться сервисом."
            )
        
        logger.info(f"User {user_id} unbanned successfully")
        
        return jsonify({
            'success': True,
            'message': f'Пользователь @{user["username"] or user_id} разблокирован',
            'was_blacklisted': in_blacklist
        })
        
    except Exception as e:
        logger.error(f"Error unbanning user {user_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/panel/keys', methods=['GET'])
@require_auth
def get_keys():
    """Получить список ключей VPN с синхронизацией трафика из Remnawave"""
    limit = request.args.get('limit', 100, type=int)
    offset = request.args.get('offset', 0, type=int)
    
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT 
                vk.id,
                vk.user_id,
                u.username,
                u.telegram_id,
                vk.key_uuid,
                vk.key_config,
                vk.status,
                vk.expiry_date,
                vk.traffic_used,
                vk.traffic_limit,
                vk.devices_limit,
                vk.server_location,
                vk.created_at
            FROM vpn_keys vk
            LEFT JOIN users u ON vk.user_id = u.id
            ORDER BY vk.created_at DESC
            LIMIT ? OFFSET ?
        """, (limit, offset))
        
        rows = cursor.fetchall()
        keys = []
        
        # Собираем все telegram_id для batch запроса к Remnawave
        telegram_ids = set()
        for row in rows:
            if row['telegram_id']:
                telegram_ids.add(row['telegram_id'])
        
        # Получаем трафик из Remnawave для всех ключей
        remnawave_traffic = {}
        try:
            for telegram_id in telegram_ids:
                rw_users = remnawave.remnawave_api.get_user_by_telegram_id(telegram_id)
                for rw_user in rw_users:
                    if hasattr(rw_user, 'uuid'):
                        traffic_used = 0
                        if hasattr(rw_user, 'user_traffic') and rw_user.user_traffic:
                            traffic_used = rw_user.user_traffic.used_traffic_bytes
                        elif hasattr(rw_user, 'used_traffic_bytes'):
                            traffic_used = rw_user.used_traffic_bytes
                        remnawave_traffic[rw_user.uuid] = traffic_used
        except Exception as e:
            logger.warning(f"Failed to sync traffic from Remnawave for panel keys: {e}")
        
        for row in rows:
            username = row['username'] or f"user_{row['user_id']}"
            key_display = row['key_config'] or row['key_uuid'] or f"key_{row['id']}"
            if len(key_display) > 50:
                key_display = key_display[:47] + '...'
            
            # Вычисляем оставшиеся дни
            expiry_days = 0
            if row['expiry_date']:
                try:
                    from datetime import datetime
                    if isinstance(row['expiry_date'], str):
                        expiry = datetime.fromisoformat(row['expiry_date'].replace('Z', '+00:00'))
                    else:
                        expiry = row['expiry_date']
                    now = datetime.now()
                    if expiry.tzinfo:
                        from datetime import timezone
                        now = datetime.now(timezone.utc)
                    diff = expiry - now
                    expiry_days = max(0, int(diff.total_seconds() / 86400))
                except:
                    expiry_days = 0
            
            # Получаем актуальный трафик из Remnawave если доступен
            traffic_used = float(row['traffic_used'] or 0)
            key_uuid = row['key_uuid']
            if key_uuid and key_uuid in remnawave_traffic:
                traffic_used = float(remnawave_traffic[key_uuid])
                # Обновляем в БД для консистентности
                try:
                    cursor.execute("UPDATE vpn_keys SET traffic_used = ? WHERE key_uuid = ?", 
                                 (traffic_used, key_uuid))
                except:
                    pass
            
            keys.append({
                'id': row['id'],
                'key_config': row['key_config'],
                'key_uuid': row['key_uuid'],
                'key': key_display,
                'user_id': row['user_id'],
                'username': f"@{username}" if username and not username.startswith('@') else username,
                'status': row['status'] or 'Active',
                'expiry_date': row['expiry_date'],
                'expiry': expiry_days,
                'traffic_used': traffic_used,
                'traffic_limit': float(row['traffic_limit'] or 0),
                'devices_used': 0,  # TODO: подсчитать из devices
                'devices_limit': row['devices_limit'] or 1,
                'server_location': row['server_location'] or 'Unknown'
            })
        
        # Commit любых обновлений трафика
        try:
            conn.commit()
        except:
            pass
        
        return jsonify(keys)
    finally:
        conn.close()


@app.route('/api/panel/keys', methods=['POST'])
@require_auth
def create_key():
    """Создать ключ VPN для пользователя через Remnawave"""
    data = request.json
    
    user_id = data.get('user_id')
    days = data.get('days', 30)
    traffic_gb = data.get('traffic', 100)  # В ГБ
    devices = data.get('devices', 5)
    is_trial = data.get('is_trial', False)
    plan_type = data.get('plan_type', 'vpn')
    # Если сквады не указаны явно, используем балансировщик для выбора оптимального сквада
    squad_uuids = data.get('squads')
    if squad_uuids is None or len(squad_uuids) == 0:
        # Сначала пробуем балансировщик - выбираем сквад с наименьшей нагрузкой
        best_squad = database.get_best_squad_for_subscription(plan_type)
        if best_squad:
            squad_uuids = [best_squad['squad_uuid']]
            logger.info(f"Balancer selected squad {best_squad['squad_name']} for {plan_type} (users: {best_squad['current_users']})")
        else:
            # Fallback на сквады из настроек
            squad_uuids = database.get_default_squads(plan_type)
            logger.info(f"Using default squads for {plan_type}: {squad_uuids}")
    
    if not user_id:
        return jsonify({'error': 'user_id обязателен'}), 400
    
    # Получаем пользователя
    user = database.get_user_by_id(user_id)
    if not user:
        return jsonify({'error': 'Пользователь не найден'}), 404
    
    telegram_id = user.get('telegram_id')
    raw_username = user.get('username') or f"user_{telegram_id}"
    
    # Санитизация username для Remnawave (только буквы, цифры, _ и -)
    import re
    username = re.sub(r'[^a-zA-Z0-9_-]', '', raw_username)
    if not username:
        username = f"user_{telegram_id}"
    if username[0] in '_-':
        username = f"u{username}"
    
    # Триальные настройки
    if is_trial:
        days = 1
        traffic_gb = 5
        devices = 1
    
    traffic_bytes = int(traffic_gb * (1024 ** 3))  # Конвертация в байты
    
    try:
        from backend.api import remnawave
        
        # Создаем или получаем пользователя в Remnawave
        remnawave_user = None
        existing_users = remnawave.remnawave_api.get_user_by_telegram_id(telegram_id)
        
        if existing_users and len(existing_users) > 0:
            # Пользователь уже существует - обновляем подписку
            remnawave_user = existing_users[0]
            expire_at = datetime.now() + timedelta(days=days)
            
            # Обновляем пользователя
            logger.info(f"Updating Remnawave user {remnawave_user.uuid} with squads: {squad_uuids}")
            updated_user = remnawave.remnawave_api.update_user_sync(
                uuid=remnawave_user.uuid,
                expire_at=expire_at,
                traffic_limit_bytes=traffic_bytes,
                hwid_device_limit=devices,
                active_internal_squads=squad_uuids if squad_uuids else None
            )
            remnawave_user = updated_user
        else:
            # Создаём нового пользователя в Remnawave с санитизированным username
            logger.info(f"Creating Remnawave user {username} with squads: {squad_uuids}")
            try:
                remnawave_user = remnawave.remnawave_api.create_user_with_params(
                    telegram_id=telegram_id,
                    username=username,
                    days=days,
                    traffic_limit_bytes=traffic_bytes,
                    hwid_device_limit=devices,
                    active_internal_squads=squad_uuids if squad_uuids else None
                )
            except Exception as create_error:
                error_msg = str(create_error).lower()
                # Если username уже существует - добавляем telegram_id для уникальности
                if 'already exists' in error_msg or 'a019' in error_msg:
                    unique_username = f"{username}_{telegram_id}"
                    logger.info(f"Username {username} already exists, trying {unique_username}")
                    remnawave_user = remnawave.remnawave_api.create_user_with_params(
                        telegram_id=telegram_id,
                        username=unique_username,
                        days=days,
                        traffic_limit_bytes=traffic_bytes,
                        hwid_device_limit=devices,
                        active_internal_squads=squad_uuids if squad_uuids else None
                    )
                else:
                    raise create_error
        
        if not remnawave_user:
            return jsonify({'error': 'Не удалось создать пользователя в Remnawave'}), 500
        
        # Сохраняем или обновляем ключ в БД
        conn = database.get_db_connection()
        cursor = conn.cursor()
        
        expiry_date = format_datetime_msk(datetime.now() + timedelta(days=days))
        key_uuid = remnawave_user.uuid if hasattr(remnawave_user, 'uuid') else remnawave_user.get('uuid')
        subscription_url = remnawave_user.subscription_url if hasattr(remnawave_user, 'subscription_url') else remnawave_user.get('subscription_url', '')
        
        # Проверяем существует ли уже ключ для этого пользователя
        cursor.execute("SELECT id FROM vpn_keys WHERE user_id = ? AND key_uuid = ?", (user_id, key_uuid))
        existing_key = cursor.fetchone()
        
        if existing_key:
            # Обновляем существующий ключ
            cursor.execute("""
                UPDATE vpn_keys
                SET status = 'Active', expiry_date = ?, traffic_limit = ?, devices_limit = ?, 
                    key_config = ?
                WHERE id = ?
            """, (expiry_date, traffic_bytes, devices, subscription_url, existing_key['id']))
            key_id = existing_key['id']
        else:
            # Создаем новый ключ
            cursor.execute("""
                INSERT INTO vpn_keys (user_id, key_uuid, key_config, status, expiry_date, 
                                    devices_limit, traffic_limit, plan_type)
                VALUES (?, ?, ?, 'Active', ?, ?, ?, ?)
            """, (user_id, key_uuid, subscription_url, expiry_date, devices, traffic_bytes, plan_type))
            key_id = cursor.lastrowid
        
        conn.commit()
        conn.close()
        
        # Уведомление админу удалено - оставляем только для пополнений и запросов на вывод
        
        # Отправляем ключ пользователю с кнопкой открытия приложения
        core.send_key_created_notification(telegram_id, days, traffic_gb, devices)
        
        return jsonify({
            'success': True,
            'key_id': key_id,
            'key_uuid': key_uuid,
            'subscription_url': subscription_url,
            'expiry_date': expiry_date
        }), 201
        
    except Exception as e:
        logger.error(f"Ошибка создания ключа: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Ошибка создания ключа: {str(e)}'}), 500


@app.route('/api/panel/keys/<int:key_id>/block', methods=['POST'])
@require_auth
def toggle_key_block(key_id):
    """Заблокировать/разблокировать ключ вручную"""
    data = request.json
    blocked = data.get('blocked', True)
    
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Обновляем статус ключа
        new_status = 'Blocked' if blocked else 'Active'
        cursor.execute("""
            UPDATE vpn_keys 
            SET status = ?, last_used = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (new_status, key_id))
        
        if cursor.rowcount == 0:
            return jsonify({'error': 'Ключ не найден'}), 404
        
        conn.commit()
        
        # Если блокируем, также отключаем в Remnawave через update_user
        cursor.execute("SELECT key_uuid FROM vpn_keys WHERE id = ?", (key_id,))
        row = cursor.fetchone()
        
        if row and row['key_uuid']:
            try:
                from backend.api.remnawave import UserStatus
                
                # Обновляем статус в Remnawave
                status = UserStatus.DISABLED if blocked else UserStatus.ACTIVE
                remnawave.remnawave_api.update_user_sync(
                    uuid=row['key_uuid'],
                    status=status
                )
                logger.info(f"Key {key_id} {'blocked' if blocked else 'unblocked'} in Remnawave")
            except Exception as e:
                logger.error(f"Failed to update key status in Remnawave: {e}")
        
        return jsonify({
            'success': True,
            'key_id': key_id,
            'status': new_status,
            'blocked': blocked
        })
    except Exception as e:
        logger.error(f"Error toggling key block: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/panel/keys/<int:key_id>', methods=['DELETE'])
@require_auth
def delete_key(key_id: int):
    """Удалить ключ из панели и Remnawave"""
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Получаем информацию о ключе
        cursor.execute("SELECT key_uuid, user_id FROM vpn_keys WHERE id = ?", (key_id,))
        row = cursor.fetchone()
        
        if not row:
            return jsonify({'error': 'Ключ не найден'}), 404
        
        key_uuid = row['key_uuid']
        user_id = row['user_id']
        
        # Удаляем из Remnawave
        if key_uuid:
            try:
                remnawave.remnawave_api.delete_user_sync(key_uuid)
                logger.info(f"Deleted key {key_uuid} from Remnawave")
            except Exception as e:
                logger.error(f"Failed to delete key {key_uuid} from Remnawave: {e}")
        
        # Удаляем ключ/устройство (теперь одна запись)
        cursor.execute("DELETE FROM vpn_keys WHERE id = ?", (key_id,))
        
        conn.commit()
        
        # Уведомляем пользователя
        cursor.execute("SELECT telegram_id FROM users WHERE id = ?", (user_id,))
        user_row = cursor.fetchone()
        if user_row:
            core.send_notification_to_user(
                user_row['telegram_id'],
                "🗑 Ваша VPN подписка была удалена администратором."
            )
        
        logger.info(f"Key {key_id} deleted from panel")
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error deleting key {key_id}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/panel/keys/<int:key_id>', methods=['PUT'])
@require_auth
def update_key(key_id: int):
    """Обновить параметры ключа"""
    data = request.json
    
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Получаем информацию о ключе
        cursor.execute("SELECT key_uuid, expiry_date, traffic_limit, devices_limit FROM vpn_keys WHERE id = ?", (key_id,))
        row = cursor.fetchone()
        
        if not row:
            return jsonify({'error': 'Ключ не найден'}), 404
        
        key_uuid = row['key_uuid']
        
        # Новые значения
        new_expiry_days = data.get('expiry_days')
        new_traffic_gb = data.get('traffic_gb')
        new_devices = data.get('devices_limit')
        
        # Обновляем в БД
        updates = []
        values = []
        
        if new_expiry_days is not None:
            new_expiry_date = format_datetime_msk(datetime.now() + timedelta(days=int(new_expiry_days)))
            updates.append("expiry_date = ?")
            values.append(new_expiry_date)
        
        if new_traffic_gb is not None:
            traffic_bytes = int(float(new_traffic_gb) * (1024 ** 3))
            updates.append("traffic_limit = ?")
            values.append(traffic_bytes)
        
        if new_devices is not None:
            updates.append("devices_limit = ?")
            values.append(int(new_devices))
        
        if updates:
            values.append(key_id)
            cursor.execute(f"UPDATE vpn_keys SET {', '.join(updates)} WHERE id = ?", tuple(values))
            conn.commit()
        
        # Обновляем в Remnawave
        if key_uuid:
            try:
                update_params = {'uuid': key_uuid}
                
                if new_expiry_days is not None:
                    update_params['expire_at'] = datetime.now() + timedelta(days=int(new_expiry_days))
                
                if new_traffic_gb is not None:
                    update_params['traffic_limit_bytes'] = int(float(new_traffic_gb) * (1024 ** 3))
                
                if new_devices is not None:
                    update_params['hwid_device_limit'] = int(new_devices)
                
                remnawave.remnawave_api.update_user_sync(**update_params)
                logger.info(f"Updated key {key_uuid} in Remnawave")
            except Exception as e:
                logger.error(f"Failed to update key {key_uuid} in Remnawave: {e}")
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error updating key {key_id}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/user/referrals', methods=['GET'])
def get_user_referrals():
    """Получить список рефералов пользователя"""
    telegram_id = request.args.get('telegram_id', type=int)
    if not telegram_id:
        return jsonify({'error': 'telegram_id required'}), 400

    user = database.get_user_by_telegram_id(telegram_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    conn = database.get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT id, username, full_name, registration_date
            FROM users
            WHERE referred_by = ?
            ORDER BY registration_date DESC
            """,
            (user["id"],),
        )
        referrals_rows = cursor.fetchall()

        # Загружаем ставки
        rate = user.get("partner_rate", 20) / 100

        referrals = []
        for r in referrals_rows:
            ref_id = r["id"]
            
            # Сумма покупок реферала (подписки, а не депозиты)
            cursor.execute(
                """
                SELECT COALESCE(SUM(ABS(amount)), 0) as total
                FROM transactions
                WHERE user_id = ? AND type IN ('subscription', 'trial')
                """,
                (ref_id,),
            )
            spent_row = cursor.fetchone()
            total_spent = float(spent_row["total"] or 0)
            
            # Мой реальный доход от этого реферала (из транзакций referral_income)
            cursor.execute(
                """
                SELECT COALESCE(SUM(amount), 0) as total
                FROM transactions
                WHERE user_id = ? AND type = 'referral_income' 
                AND description LIKE ?
                """,
                (user["id"], f"%реферала%{r['username'] or ref_id}%"),
            )
            income_row = cursor.fetchone()
            my_profit = float(income_row["total"] or 0)
            
            # Если нет записанного дохода, рассчитываем потенциальный
            if my_profit == 0 and total_spent > 0:
                my_profit = total_spent * rate
            
            # История транзакций реферала (последние 5)
            cursor.execute(
                """
                SELECT type, amount, created_at, description
                FROM transactions
                WHERE user_id = ? AND type IN ('subscription', 'trial')
                ORDER BY created_at DESC
                LIMIT 5
                """,
                (ref_id,),
            )
            history_rows = cursor.fetchall()
            history = []
            for h in history_rows:
                amount = abs(float(h["amount"] or 0))
                trans_type = h["type"]
                description = h["description"] or ""
                
                # Формируем понятное описание
                if trans_type == 'subscription':
                    title = f"Покупка подписки: {round(amount, 2)}₽"
                elif trans_type == 'trial':
                    title = "Активация пробного периода"
                else:
                    title = description or f"Транзакция: {round(amount, 2)}₽"
                
                # Вычисляем доход реферера
                referrer_income = round(amount * rate, 2)
                
                history.append({
                    "type": trans_type,
                    "title": title,
                    "amount": round(amount, 2),
                    "income": referrer_income,
                    "date": h["created_at"] or "",
                })

            referrals.append(
                {
                    "id": ref_id,
                    "name": r["full_name"] or r["username"] or f"id{ref_id}",
                    "date": r["registration_date"] or "",
                    "spent": round(total_spent, 2),
                    "myProfit": round(my_profit, 2),
                    "history": history,
                }
            )

        return jsonify(referrals)
    finally:
        conn.close()


@app.route('/api/user/referral-history', methods=['GET'])
def get_referral_income_history():
    """Получить историю реферального дохода пользователя"""
    telegram_id = request.args.get('telegram_id', type=int)
    if not telegram_id:
        return jsonify({'error': 'telegram_id required'}), 400
    
    user = database.get_user_by_telegram_id(telegram_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Получаем все транзакции реферального дохода и вывода
        cursor.execute("""
            SELECT id, type, amount, status, description, created_at
            FROM transactions
            WHERE user_id = ? AND type IN ('referral_income', 'transfer', 'withdrawal_request')
            ORDER BY created_at DESC
            LIMIT 50
        """, (user['id'],))
        
        rows = cursor.fetchall()
        history = []
        
        for row in rows:
            trans_type = row['type']
            amount = round(float(row['amount'] or 0), 2)
            description = row['description'] or ''
            
            if trans_type == 'referral_income':
                title = f'💰 Реферальный доход: +{amount}₽'
                icon = 'income'
            elif trans_type == 'transfer':
                title = f'🔄 Перевод на баланс: {amount}₽'
                icon = 'transfer'
            else:
                title = f'💸 Заявка на вывод: {amount}₽'
                icon = 'withdrawal'
            
            history.append({
                'id': row['id'],
                'type': icon,
                'title': title,
                'amount': amount,
                'status': row['status'],
                'description': description,
                'date': row['created_at']
            })
        
        return jsonify(history)
    finally:
        conn.close()


@app.route('/api/user/withdraw', methods=['POST'])
def request_withdrawal():
    """Запрос на вывод средств из реферального баланса"""
    data = request.json
    telegram_id = data.get('telegram_id')
    amount = data.get('amount', 0)
    method = data.get('method')  # 'balance', 'card', 'crypto'
    
    # Дополнительные данные в зависимости от метода
    phone = data.get('phone', '')
    bank = data.get('bank', '')
    crypto_net = data.get('crypto_net', '')
    crypto_addr = data.get('crypto_addr', '')
    
    logger.info(f"Withdrawal request: telegram_id={telegram_id}, amount={amount}, method={method}")
    
    if not telegram_id or not method:
        logger.error("Missing required fields: telegram_id or method")
        return jsonify({'error': 'Missing required fields'}), 400
    
    try:
        amount = float(amount)
    except (ValueError, TypeError):
        logger.error(f"Invalid amount: {amount}")
        return jsonify({'error': 'Invalid amount'}), 400
        
    if amount <= 0:
        logger.error(f"Amount must be positive: {amount}")
        return jsonify({'error': 'Invalid amount'}), 400
    
    # Минимальный вывод для карты и крипто - 200₽
    if method in ('card', 'crypto') and amount < 200:
        return jsonify({'error': 'Минимальная сумма вывода - 200₽'}), 400
    
    user = database.get_user_by_telegram_id(telegram_id)
    if not user:
        logger.error(f"User not found: {telegram_id}")
        return jsonify({'error': 'User not found'}), 404
    
    partner_balance = user.get('partner_balance', 0)
    logger.info(f"User partner_balance: {partner_balance}, requested: {amount}")
    
    if amount > partner_balance:
        return jsonify({'error': 'Insufficient partner balance'}), 400
    
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    # Проверка лимита для вывода на карту - не чаще 1 раза в 30 дней
    if method == 'card':
        cursor.execute("""
            SELECT created_at FROM transactions 
            WHERE user_id = ? AND type = 'withdrawal_request' AND payment_method = 'Карта' AND status = 'Pending'
            ORDER BY created_at DESC LIMIT 1
        """, (user['id'],))
        last_card_withdrawal = cursor.fetchone()
        
        if last_card_withdrawal:
            from datetime import datetime, timedelta
            last_date_str = last_card_withdrawal['created_at']
            try:
                if isinstance(last_date_str, str):
                    last_date = datetime.fromisoformat(last_date_str.replace('Z', '+00:00'))
                else:
                    last_date = last_date_str
                
                days_since = (datetime.now() - last_date.replace(tzinfo=None)).days
                if days_since < 30:
                    days_left = 30 - days_since
                    return jsonify({'error': f'Вывод на карту доступен не чаще 1 раза в 30 дней. Осталось дней: {days_left}'}), 400
            except Exception as e:
                logger.error(f"Error parsing last withdrawal date: {e}")
    
    try:
        if method == 'balance':
            # Перевод на основной баланс
            cursor.execute("""
                UPDATE users 
                SET balance = balance + ?, partner_balance = partner_balance - ?
                WHERE id = ?
            """, (amount, amount, user['id']))
            
            cursor.execute("""
                INSERT INTO transactions (user_id, type, amount, status, description)
                VALUES (?, 'transfer', ?, 'Success', 'Перевод с реферального баланса на основной')
            """, (user['id'], amount))
            
            conn.commit()
            
            return jsonify({
                'success': True,
                'message': f'Переведено {amount}₽ на основной баланс'
            })
        
        elif method in ('card', 'crypto'):
            # Запрос на вывод - списываем с partner_balance и создаем заявку
            cursor.execute("""
                UPDATE users SET partner_balance = partner_balance - ? WHERE id = ?
            """, (amount, user['id']))
            
            # Создаем заявку на вывод
            if method == 'card':
                description = f'Заявка на вывод {amount}₽ на карту. Банк: {bank}, Телефон: {phone}'
                details = f"🏦 Банк: {bank}\n📱 Телефон: {phone}"
            else:
                description = f'Заявка на вывод {amount}₽ в криптовалюте. Сеть: {crypto_net}, Адрес: {crypto_addr}'
                details = f"🌐 Сеть: {crypto_net}\n📝 Адрес: {crypto_addr}"
            
            cursor.execute("""
                INSERT INTO transactions (user_id, type, amount, status, description, payment_method)
                VALUES (?, 'withdrawal_request', ?, 'Pending', ?, ?)
            """, (user['id'], -amount, description, 'Карта' if method == 'card' else 'Crypto'))
            
            transaction_id = cursor.lastrowid
            conn.commit()
            
            # Отправляем запрос ТОЛЬКО админу с кнопками Принять/Отказать
            username = user.get('username', 'N/A')
            method_name = 'Банковская карта' if method == 'card' else 'Криптовалюта'
            
            core.send_withdrawal_request_to_admin(
                transaction_id=transaction_id,
                user_id=user['id'],
                telegram_id=telegram_id,
                username=username,
                amount=amount,
                method=method_name,
                details=details
            )
            
            return jsonify({
                'success': True,
                'message': f'Заявка на вывод {amount}₽ создана. Ожидайте обработки.'
            })
        
        else:
            return jsonify({'error': f'Unknown withdrawal method: {method}'}), 400
            
    except Exception as e:
        logger.error(f"Error processing withdrawal request: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/panel/stats/charts', methods=['GET'])
@require_auth
def get_stats_charts():
    """Графики для дашборда панели (последние 14 дней)"""
    conn = database.get_db_connection()
    cursor = conn.cursor()
    from datetime import datetime, timedelta

    try:
        # Подготовим даты
        days = []
        today = datetime.utcnow().date()
        for i in range(14):
            days.append(today - timedelta(days=13 - i))

        # Пользователи по дням
        cursor.execute(
            """
            SELECT DATE(registration_date) as d, COUNT(*) as cnt
            FROM users
            GROUP BY DATE(registration_date)
            """
        )
        users_map = {row["d"]: row["cnt"] for row in cursor.fetchall()}
        users_series = [users_map.get(str(d), 0) for d in days]

        # Ключи по дням
        cursor.execute(
            """
            SELECT DATE(created_at) as d, COUNT(*) as cnt
            FROM vpn_keys
            GROUP BY DATE(created_at)
            """
        )
        keys_map = {row["d"]: row["cnt"] for row in cursor.fetchall()}
        keys_series = [keys_map.get(str(d), 0) for d in days]

        return jsonify({
            "users": users_series,
            "keys": keys_series,
            "labels": [d.strftime("%d.%m") for d in days],
        })
    finally:
        conn.close()


@app.route('/api/panel/stats/summary', methods=['GET'])
@require_auth
def get_stats_summary():
    """
    Сводные метрики для дашборда:
    - total_users: всего пользователей
    - active_keys: активных ключей
    - monthly_revenue: сумма депозитов за текущий месяц
    """
    conn = database.get_db_connection()
    cursor = conn.cursor()
    from datetime import datetime

    try:
        # Всего пользователей
        cursor.execute("SELECT COUNT(*) AS cnt FROM users")
        total_users = cursor.fetchone()["cnt"] or 0

        # Активные ключи
        cursor.execute("SELECT COUNT(*) AS cnt FROM vpn_keys WHERE status = 'Active'")
        active_keys = cursor.fetchone()["cnt"] or 0

        # Доход за текущий месяц (по депозитам)
        now = datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        cursor.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS total
            FROM transactions
            WHERE type = 'deposit'
              AND created_at >= ?
              AND status = 'Success'
            """,
            (month_start.isoformat(),),
        )
        monthly_revenue = float(cursor.fetchone()["total"] or 0)

        return jsonify(
            {
                "total_users": total_users,
                "active_keys": active_keys,
                "monthly_revenue": monthly_revenue,
            }
        )
    finally:
        conn.close()

@app.route('/api/panel/finance/stats', methods=['GET'])
@require_auth
def get_finance_stats():
    """Статистика финансов (пополнения, списания, успешные операции)"""
    conn = database.get_db_connection()
    cursor = conn.cursor()
    from datetime import datetime, timedelta
    
    try:
        # Пополнения (все депозиты)
        cursor.execute("""
            SELECT COALESCE(SUM(amount), 0) AS total, COUNT(*) AS cnt
            FROM transactions
            WHERE type = 'deposit' AND status = 'Success'
        """)
        deposits_row = cursor.fetchone()
        deposits_total = float(deposits_row['total'] or 0)
        deposits_count = deposits_row['cnt'] or 0
        
        # Расходы: выводы реферальных средств, возвраты, рефанды
        cursor.execute("""
            SELECT COALESCE(SUM(ABS(amount)), 0) AS total, COUNT(*) AS cnt
            FROM transactions
            WHERE type IN ('referral_withdrawal', 'refund', 'withdrawal', 'admin_withdrawal') 
              AND status = 'Success'
        """)
        withdrawals_row = cursor.fetchone()
        withdrawals_total = float(withdrawals_row['total'] or 0)
        withdrawals_count = withdrawals_row['cnt'] or 0
        
        # Успешные операции
        cursor.execute("""
            SELECT COUNT(*) AS cnt
            FROM transactions
            WHERE status = 'Success'
        """)
        successful_ops = cursor.fetchone()['cnt'] or 0
        
        # Изменение за период (сравнение с предыдущим месяцем)
        now = datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        prev_month_start = (month_start - timedelta(days=1)).replace(day=1)
        
        cursor.execute("""
            SELECT COALESCE(SUM(amount), 0) AS total
            FROM transactions
            WHERE type = 'deposit' AND status = 'Success'
              AND created_at >= ? AND created_at < ?
        """, (prev_month_start.isoformat(), month_start.isoformat()))
        prev_deposits = float(cursor.fetchone()['total'] or 0)
        
        deposits_change = ((deposits_total - prev_deposits) / prev_deposits * 100) if prev_deposits > 0 else 0
        
        return jsonify({
            'deposits': deposits_total,
            'depositsChange': f"+{deposits_change:.1f}%" if deposits_change >= 0 else f"{deposits_change:.1f}%",
            'withdrawals': withdrawals_total,
            'withdrawalsChange': '+2.1%',  # Упрощенно
            'successfulOps': successful_ops
        })
    finally:
        conn.close()

@app.route('/api/panel/statistics/full', methods=['GET'])
@require_auth
def get_full_statistics():
    """Полная статистика для страницы Статистика"""
    conn = database.get_db_connection()
    cursor = conn.cursor()
    from datetime import datetime, timedelta
    
    try:
        # Основные метрики
        cursor.execute("SELECT COUNT(*) AS cnt FROM users")
        total_users = cursor.fetchone()['cnt'] or 0
        
        cursor.execute("SELECT COUNT(*) AS cnt FROM vpn_keys WHERE status = 'Active'")
        active_subscriptions = cursor.fetchone()['cnt'] or 0
        
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        cursor.execute("""
            SELECT COUNT(*) AS cnt FROM transactions
            WHERE type = 'deposit' AND status = 'Success' AND created_at >= ?
        """, (today_start.isoformat(),))
        payments_today = cursor.fetchone()['cnt'] or 0
        
        cursor.execute("SELECT COALESCE(SUM(balance), 0) AS total FROM users")
        clients_balance = float(cursor.fetchone()['total'] or 0)
        
        # Выручка по дням (последние 30 дней)
        revenue_data = []
        revenue_labels = []
        for i in range(30):
            day = (datetime.utcnow() - timedelta(days=29-i)).date()
            day_start = datetime.combine(day, datetime.min.time())
            day_end = day_start + timedelta(days=1)
            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0) AS total
                FROM transactions
                WHERE type = 'deposit' AND status = 'Success'
                  AND created_at >= ? AND created_at < ?
            """, (day_start.isoformat(), day_end.isoformat()))
            revenue_data.append(float(cursor.fetchone()['total'] or 0))
            revenue_labels.append(day.strftime('%d.%m.%Y'))
        
        # Распределение пользователей (на основе состояния их ключей)
        cursor.execute("""
            SELECT COUNT(DISTINCT user_id) AS cnt FROM vpn_keys 
            WHERE status = 'Active' AND expiry_date > datetime('now')
        """)
        active_users = cursor.fetchone()['cnt'] or 0
        
        cursor.execute("SELECT COUNT(*) AS cnt FROM users WHERE trial_used = 0")
        trial_users = cursor.fetchone()['cnt'] or 0
        
        cursor.execute("SELECT COUNT(*) AS cnt FROM users WHERE is_banned = 1")
        banned_users = cursor.fetchone()['cnt'] or 0
        
        cursor.execute("""
            SELECT COUNT(DISTINCT user_id) AS cnt FROM vpn_keys 
            WHERE status = 'Expired' OR (expiry_date IS NOT NULL AND expiry_date < datetime('now'))
        """)
        expired_users = cursor.fetchone()['cnt'] or 0
        
        sleeping_users = max(0, total_users - active_users - trial_users - banned_users - expired_users)
        
        user_dist_data = [
            {'label': 'Активные', 'value': active_users},
            {'label': 'Ушли', 'value': expired_users},
            {'label': 'Trial', 'value': trial_users},
            {'label': 'Бан', 'value': banned_users},
            {'label': 'Спящие', 'value': sleeping_users},
        ]
        
        # Способы оплаты
        cursor.execute("""
            SELECT payment_method, COUNT(*) AS cnt
            FROM transactions
            WHERE type = 'deposit' AND status = 'Success'
            GROUP BY payment_method
        """)
        payment_methods_raw = cursor.fetchall()
        total_payments = sum(row['cnt'] for row in payment_methods_raw) or 1
        payment_methods_data = []
        for row in payment_methods_raw:
            method = row['payment_method'] or 'Other'
            count = row['cnt']
            payment_methods_data.append({
                'label': method,
                'value': int((count / total_payments) * 100)
            })
        
        # Подписки
        cursor.execute("SELECT COUNT(*) AS cnt FROM vpn_keys")
        total_subscriptions = cursor.fetchone()['cnt'] or 0
        cursor.execute("SELECT COUNT(*) AS cnt FROM vpn_keys WHERE status = 'Active' AND expiry_date > datetime('now')")
        paid_subscriptions = cursor.fetchone()['cnt'] or 0
        
        week_start = datetime.utcnow() - timedelta(days=7)
        cursor.execute("""
            SELECT COUNT(*) AS cnt FROM vpn_keys
            WHERE created_at >= ?
        """, (week_start.isoformat(),))
        bought_this_week = cursor.fetchone()['cnt'] or 0
        
        # Конверсия Trial -> Paid (на основе наличия активных подписок)
        cursor.execute("SELECT COUNT(*) AS cnt FROM users WHERE trial_used = 1")
        used_trial = cursor.fetchone()['cnt'] or 0
        cursor.execute("""
            SELECT COUNT(DISTINCT u.id) AS cnt 
            FROM users u
            JOIN vpn_keys vk ON vk.user_id = u.id
            WHERE u.trial_used = 1 AND vk.status = 'Active' AND vk.expiry_date > datetime('now')
        """)
        converted = cursor.fetchone()['cnt'] or 0
        conversion_rate = (converted / used_trial * 100) if used_trial > 0 else 0
        
        # Рефералы
        cursor.execute("SELECT COUNT(*) AS cnt FROM users WHERE referred_by IS NOT NULL")
        total_invited = cursor.fetchone()['cnt'] or 0
        cursor.execute("SELECT COUNT(*) AS cnt FROM users WHERE is_partner = 1")
        partners = cursor.fetchone()['cnt'] or 0
        cursor.execute("SELECT COALESCE(SUM(total_earned), 0) AS total FROM users")
        total_paid = float(cursor.fetchone()['total'] or 0)
        
        # Топ рефералов
        cursor.execute("""
            SELECT u.id, u.username, u.partner_rate,
                   COUNT(r.id) AS referrals_count,
                   COALESCE(SUM(t.amount), 0) AS total_spent
            FROM users u
            LEFT JOIN users r ON r.referred_by = u.id
            LEFT JOIN transactions t ON t.user_id = r.id AND t.type = 'deposit'
            WHERE u.is_partner = 1
            GROUP BY u.id
            ORDER BY total_spent DESC
            LIMIT 10
        """)
        top_referrers_raw = cursor.fetchall()
        top_referrers = []
        for idx, row in enumerate(top_referrers_raw, 1):
            username = row['username'] or f"id{row['id']}"
            rate = row['partner_rate'] or 20
            total_spent = float(row['total_spent'] or 0)
            earned = total_spent * (rate / 100)
            top_referrers.append({
                'id': idx,
                'name': f"@{username}" if not username.startswith('@') else username,
                'count': row['referrals_count'] or 0,
                'earned': earned
            })
        
        # Средняя выручка в день
        avg_daily = sum(revenue_data) / len(revenue_data) if revenue_data else 0
        best_day_value = max(revenue_data) if revenue_data else 0
        best_day_idx = revenue_data.index(best_day_value) if revenue_data else 0
        best_day_date = (datetime.utcnow() - timedelta(days=29-best_day_idx)).strftime('%d %B') if revenue_data else ''
        
        return jsonify({
            'totalUsers': total_users,
            'activeSubscriptions': active_subscriptions,
            'paymentsToday': payments_today,
            'clientsBalance': clients_balance,
            'revenueData': revenue_data,
            'revenueLabels': revenue_labels,
            'userDistData': user_dist_data,
            'paymentMethodsData': payment_methods_data,
            'totalSubscriptions': total_subscriptions,
            'paidSubscriptions': paid_subscriptions,
            'boughtThisWeek': bought_this_week,
            'conversionRate': conversion_rate,
            'totalInvited': total_invited,
            'partners': partners,
            'totalPaid': total_paid,
            'topReferrers': top_referrers,
            'avgDaily': avg_daily,
            'bestDayValue': best_day_value,
            'bestDayDate': best_day_date
        })
    finally:
        conn.close()

@app.route('/api/panel/promocodes/stats', methods=['GET'])
@require_auth
def get_promocodes_stats():
    """Статистика промокодов"""
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT 
                COUNT(*) AS total,
                SUM(uses_count) AS total_uses,
                COUNT(CASE WHEN is_active = 1 THEN 1 END) AS active_count
            FROM promocodes
        """)
        row = cursor.fetchone()
        return jsonify({
            'total': row['total'] or 0,
            'totalUses': row['total_uses'] or 0,
            'activeCount': row['active_count'] or 0
        })
    finally:
        conn.close()

@app.route('/api/tariffs', methods=['GET'])
def get_public_tariffs():
    """Публичный API для получения тарифов (для мини-приложения)"""
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT * FROM tariff_plans
            WHERE is_active = 1
            ORDER BY plan_type, sort_order
        """)
        rows = cursor.fetchall()
        plans = []
        for row in rows:
            plans.append({
                'id': row['id'],
                'plan_type': row['plan_type'],
                'name': row['name'],
                'price': float(row['price']),
                'duration_days': row['duration_days'],
                'is_active': bool(row['is_active']),
                'sort_order': row['sort_order']
            })
        return jsonify(plans)
    finally:
        conn.close()


@app.route('/api/panel/tariffs', methods=['GET'])
@require_auth
def get_tariffs():
    """Получить тарифные планы (для панели)"""
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT * FROM tariff_plans
            WHERE is_active = 1
            ORDER BY plan_type, sort_order
        """)
        rows = cursor.fetchall()
        plans = []
        for row in rows:
            plans.append({
                'id': row['id'],
                'plan_type': row['plan_type'],
                'name': row['name'],
                'price': float(row['price']),
                'duration_days': row['duration_days'],
                'is_active': bool(row['is_active']),
                'sort_order': row['sort_order']
            })
        return jsonify(plans)
    finally:
        conn.close()

@app.route('/api/panel/tariffs', methods=['POST'])
@require_auth
def create_tariff():
    """Создать тарифный план"""
    data = request.json
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO tariff_plans (plan_type, name, price, duration_days, is_active, sort_order)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            data.get('plan_type'),
            data.get('name'),
            data.get('price'),
            data.get('duration_days'),
            1 if data.get('is_active', True) else 0,
            data.get('sort_order', 0)
        ))
        conn.commit()
        plan_id = cursor.lastrowid
        cursor.execute("SELECT * FROM tariff_plans WHERE id = ?", (plan_id,))
        return jsonify({'success': True, 'plan': dict(cursor.fetchone())})
    finally:
        conn.close()

@app.route('/api/panel/tariffs/<int:plan_id>', methods=['PUT'])
@require_auth
def update_tariff(plan_id: int):
    """Обновить тарифный план"""
    data = request.json
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        fields = []
        values = []
        for key in ['plan_type', 'name', 'price', 'duration_days', 'is_active', 'sort_order']:
            if key in data:
                if key == 'is_active':
                    values.append(1 if data[key] else 0)
                else:
                    values.append(data[key])
                fields.append(f"{key} = ?")
        
        if not fields:
            return jsonify({'success': False, 'error': 'Nothing to update'}), 400
        
        values.append(plan_id)
        cursor.execute(f"UPDATE tariff_plans SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", tuple(values))
        conn.commit()
        cursor.execute("SELECT * FROM tariff_plans WHERE id = ?", (plan_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({'success': False, 'error': 'Plan not found'}), 404
        return jsonify({'success': True, 'plan': dict(row)})
    finally:
        conn.close()

@app.route('/api/panel/tariffs/<int:plan_id>', methods=['DELETE'])
@require_auth
def delete_tariff(plan_id: int):
    """Удалить тарифный план"""
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("UPDATE tariff_plans SET is_active = 0 WHERE id = ?", (plan_id,))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


@app.route('/api/panel/auto-discounts', methods=['GET'])
@require_auth
def get_auto_discounts():
    """Получить список авто-скидок"""
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM auto_discounts ORDER BY created_at DESC")
        rows = cursor.fetchall()
        discounts = []
        for row in rows:
            discounts.append({
                'id': row['id'],
                'name': row['name'],
                'condition_type': row['condition_type'],
                'condition_value': row['condition_value'],
                'discount_type': row['discount_type'],
                'discount_value': float(row['discount_value']),
                'is_active': bool(row['is_active'])
            })
        return jsonify(discounts)
    finally:
        conn.close()

@app.route('/api/panel/auto-discounts', methods=['POST'])
@require_auth
def create_auto_discount():
    """Создать правило авто-скидки"""
    data = request.json
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO auto_discounts (name, condition_type, condition_value, discount_type, discount_value, is_active)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            data.get('name'),
            data.get('condition_type'),
            data.get('condition_value'),
            data.get('discount_type'),
            data.get('discount_value'),
            1 if data.get('is_active', True) else 0
        ))
        conn.commit()
        discount_id = cursor.lastrowid
        cursor.execute("SELECT * FROM auto_discounts WHERE id = ?", (discount_id,))
        return jsonify({'success': True, 'discount': dict(cursor.fetchone())})
    finally:
        conn.close()

@app.route('/api/panel/auto-discounts/<int:discount_id>', methods=['PUT'])
@require_auth
def update_auto_discount(discount_id: int):
    """Обновить правило авто-скидки"""
    data = request.json
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        fields = []
        values = []
        for key in ['name', 'condition_type', 'condition_value', 'discount_type', 'discount_value', 'is_active']:
            if key in data:
                if key == 'is_active':
                    values.append(1 if data[key] else 0)
                else:
                    values.append(data[key])
                fields.append(f"{key} = ?")
        if not fields:
            return jsonify({'success': False, 'error': 'Nothing to update'}), 400
        values.append(discount_id)
        cursor.execute(f"UPDATE auto_discounts SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", tuple(values))
        conn.commit()
        cursor.execute("SELECT * FROM auto_discounts WHERE id = ?", (discount_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({'success': False, 'error': 'Discount not found'}), 404
        return jsonify({'success': True, 'discount': dict(row)})
    finally:
        conn.close()

@app.route('/api/panel/auto-discounts/<int:discount_id>', methods=['DELETE'])
@require_auth
def delete_auto_discount(discount_id: int):
    """Удалить правило авто-скидки"""
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("DELETE FROM auto_discounts WHERE id = ?", (discount_id,))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()

@app.route('/api/panel/public-pages', methods=['GET'])
@require_auth
def get_public_pages():
    """Получить публичные страницы"""
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM public_pages")
        rows = cursor.fetchall()
        pages = {}
        for row in rows:
            pages[row['page_type']] = {
                'id': row['id'],
                'content': row['content'],
                'updated_at': row['updated_at']
            }
        return jsonify(pages)
    finally:
        conn.close()

@app.route('/api/panel/public-pages/<page_type>', methods=['PUT'])
@require_auth
def update_public_page(page_type: str):
    """Обновить публичную страницу"""
    data = request.json
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT id FROM public_pages WHERE page_type = ?", (page_type,))
        row = cursor.fetchone()
        if row:
            cursor.execute("""
                UPDATE public_pages SET content = ?, updated_at = CURRENT_TIMESTAMP
                WHERE page_type = ?
            """, (data.get('content', ''), page_type))
        else:
            cursor.execute("""
                INSERT INTO public_pages (page_type, content)
                VALUES (?, ?)
            """, (page_type, data.get('content', '')))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()

@app.route('/api/public-pages', methods=['GET'])
def get_all_public_pages():
    """Получить все публичные страницы (публичный эндпоинт для мини-приложения)"""
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT page_type, content, updated_at FROM public_pages")
        rows = cursor.fetchall()
        pages = {}
        for row in rows:
            pages[row['page_type']] = {
                'content': row['content'],
                'updated_at': row['updated_at']
            }
        return jsonify(pages)
    finally:
        conn.close()


@app.route('/api/public-pages/<page_type>', methods=['GET'])
def get_public_page(page_type: str):
    """Получить публичную страницу (публичный эндпоинт для мини-приложения)"""
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT content FROM public_pages WHERE page_type = ?", (page_type,))
        row = cursor.fetchone()
        if row:
            return jsonify({'content': row['content']})
        return jsonify({'content': ''})
    finally:
        conn.close()

@app.route('/api/panel/settings', methods=['GET'])
@require_auth
def get_settings():
    """Получить настройки системы"""
    import os
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    def mask_token(token: str) -> str:
        """Маскирует токен, показывая только первые и последние 4 символа"""
        if not token or len(token) < 10:
            return token
        return token[:4] + '...' + token[-4:]
    
    try:
        # Настройки из БД
        cursor.execute("SELECT setting_key, setting_value FROM system_settings")
        db_settings = {row['setting_key']: row['setting_value'] for row in cursor.fetchall()}
        
        # Добавляем сквады по умолчанию
        db_settings['default_squads'] = database.get_default_squads()
        
        # Настройки из .env
        env_settings = {
            'MINIAPP_URL': os.getenv('MINIAPP_URL', ''),
            'PANEL_URL': os.getenv('PANEL_URL', ''),
            'API_URL': os.getenv('API_URL', ''),
            'BOT_USERNAME': os.getenv('BOT_USERNAME', 'blnnnbot'),
            'TRIAL_HOURS': os.getenv('TRIAL_HOURS', '24'),
            'MIN_TOPUP_AMOUNT': os.getenv('MIN_TOPUP_AMOUNT', '50'),
            'MAX_TOPUP_AMOUNT': os.getenv('MAX_TOPUP_AMOUNT', '100000'),
            # Токены (частично замаскированные для безопасности)
            'TELEGRAM_BOT_TOKEN': mask_token(os.getenv('TELEGRAM_BOT_TOKEN', '')),
            'SUPPORT_BOT_TOKEN': mask_token(os.getenv('SUPPORT_BOT_TOKEN', '')),
            'TELEGRAM_ADMIN_ID': os.getenv('TELEGRAM_ADMIN_ID', ''),
            'TELEGRAM_SUPPORT_GROUP_ID': os.getenv('TELEGRAM_SUPPORT_GROUP_ID', ''),
            # Remnawave
            'REMWAVE_PANEL_URL': os.getenv('REMWAVE_PANEL_URL', os.getenv('REMWAVE_API_URL', '')),
            'REMWAVE_API_KEY': mask_token(os.getenv('REMWAVE_API_KEY', '')),
        }
        
        return jsonify({**db_settings, **env_settings})
    finally:
        conn.close()

@app.route('/api/panel/settings', methods=['PUT'])
@require_auth
def update_settings():
    """Обновить настройки системы"""
    data = request.json
    import os
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Обновляем настройки в БД
        for key, value in data.items():
            # Сохраняем все настройки в БД
            cursor.execute("""
                INSERT OR REPLACE INTO system_settings (setting_key, setting_value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            """, (key, str(value)))
            
            # Обновляем переменные окружения для настроек "Мой Налог"
            if key == 'NALOG_ENABLED':
                os.environ['NALOG_ENABLED'] = str(value).lower()
            elif key == 'NALOG_INN':
                os.environ['NALOG_INN'] = str(value)
            elif key == 'NALOG_PASSWORD':
                os.environ['NALOG_PASSWORD'] = str(value)
            elif key == 'NALOG_TOKEN_PATH':
                os.environ['NALOG_TOKEN_PATH'] = str(value)
            elif key == 'NALOG_SERVICE_NAME':
                os.environ['NALOG_SERVICE_NAME'] = str(value)
            # Обновляем переменные окружения для основных настроек
            elif key == 'TRIAL_HOURS':
                os.environ['TRIAL_HOURS'] = str(value)
            elif key == 'MIN_TOPUP_AMOUNT':
                os.environ['MIN_TOPUP_AMOUNT'] = str(value)
            elif key == 'MAX_TOPUP_AMOUNT':
                os.environ['MAX_TOPUP_AMOUNT'] = str(value)
        
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error updating settings: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/panel/default-squads', methods=['GET'])
@require_auth
def get_default_squads():
    """Получить список сквадов по умолчанию для подписок"""
    vpn_squads = database.get_default_squads('vpn')
    return jsonify({
        'vpn_squads': vpn_squads
    })

@app.route('/api/panel/default-squads', methods=['PUT'])
@require_auth
def set_default_squads():
    """Установить список сквадов по умолчанию для подписок"""
    data = request.json
    vpn_squads = data.get('vpn_squads', [])
    
    if not isinstance(vpn_squads, list):
        return jsonify({'error': 'squads должен быть массивом UUID'}), 400
    
    success_vpn = database.set_default_squads(vpn_squads, 'vpn')
    
    if success_vpn:
        return jsonify({
            'success': True, 
            'vpn_squads': vpn_squads
        })
    return jsonify({'error': 'Ошибка сохранения настроек'}), 500

@app.route('/api/panel/payment-fees', methods=['GET'])
@require_auth
def get_payment_fees():
    """Получить комиссии платежных систем"""
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM payment_fees")
        rows = cursor.fetchall()
        fees = {}
        for row in rows:
            fees[row['payment_method']] = {
                'fee_percent': float(row['fee_percent']),
                'fee_fixed': float(row['fee_fixed'])
            }
        return jsonify(fees)
    finally:
        conn.close()

@app.route('/api/panel/payment-fees', methods=['PUT'])
@require_auth
def update_payment_fees():
    """Обновить комиссии платежных систем"""
    data = request.json
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        for method, fees in data.items():
            cursor.execute("""
                INSERT OR REPLACE INTO payment_fees (payment_method, fee_percent, fee_fixed, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """, (method, fees.get('fee_percent', 0), fees.get('fee_fixed', 0)))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()

@app.route('/api/panel/payment-settings', methods=['GET'])
@require_auth
def get_payment_settings():
    """Получить настройки платежных систем"""
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM payment_provider_settings")
        rows = cursor.fetchall()
        settings = {}
        for row in rows:
            provider = row['provider']
            if provider not in settings:
                settings[provider] = {}
            settings[provider][row['setting_key']] = row['setting_value']
        
        # Заполняем пустыми значениями если нет в БД
        providers = ['platega']
        for p in providers:
            if p not in settings:
                settings[p] = {'enabled': '0'}
        
        return jsonify(settings)
    finally:
        conn.close()

@app.route('/api/panel/payment-settings/<provider>', methods=['PUT'])
@require_auth
def update_payment_settings(provider: str):
    """Обновить настройки платежной системы"""
    data = request.json
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        for key, value in data.items():
            # Upsert: INSERT OR REPLACE
            cursor.execute("""
                INSERT OR REPLACE INTO payment_provider_settings (provider, setting_key, setting_value, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """, (provider, key, str(value)))
        conn.commit()
        
        # Обновляем переменные окружения в памяти (опционально)
        # Это позволит применить настройки без перезапуска
        if provider == 'platega':
            if 'merchant_id' in data:
                os.environ['PLATEGA_MERCHANT_ID'] = str(data['merchant_id'])
            if 'secret_key' in data:
                os.environ['PLATEGA_SECRET_KEY'] = str(data['secret_key'])
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error updating payment settings for {provider}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/panel/backups/status', methods=['GET'])
@require_auth
def get_backup_status():
    """Получить статус резервного копирования"""
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM backup_settings ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        if row:
            return jsonify({
                'enabled': bool(row['enabled']),
                'interval_hours': row['interval_hours'],
                'last_backup': row['last_backup']
            })
        return jsonify({
            'enabled': False,
            'interval_hours': 12,
            'last_backup': None
        })
    finally:
        conn.close()


@app.route('/api/panel/backups/settings', methods=['PUT'])
@require_auth
def update_backup_settings():
    """Обновить настройки резервного копирования"""
    data = request.json
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT id FROM backup_settings ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        if row:
            cursor.execute("""
                UPDATE backup_settings SET enabled = ?, interval_hours = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (1 if data.get('enabled') else 0, data.get('interval_hours', 12), row['id']))
        else:
            cursor.execute("""
                INSERT INTO backup_settings (enabled, interval_hours)
                VALUES (?, ?)
            """, (1 if data.get('enabled') else 0, data.get('interval_hours', 12)))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


@app.route('/api/panel/backups/create', methods=['POST'])
@require_auth
def create_backup():
    """Создать резервную копию и отправить администратору"""
    import os
    import shutil
    import tempfile
    from datetime import datetime
    
    try:
        # Используем тот же путь что и в database.py
        db_path = os.getenv('DB_PATH', 'data.db')
        
        # Если путь относительный, делаем его абсолютным
        if not os.path.isabs(db_path):
            db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), db_path)
        
        if not os.path.exists(db_path):
            return jsonify({'error': 'Database file not found'}), 404
        
        # Создаем временный файл с копией БД
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f'blinvpn_backup_{timestamp}.db'
        
        with tempfile.TemporaryDirectory() as temp_dir:
            backup_path = os.path.join(temp_dir, backup_name)
            shutil.copy2(db_path, backup_path)
            
            # Создаем zip архив
            zip_path = os.path.join(temp_dir, f'{backup_name}.zip')
            shutil.make_archive(backup_path, 'zip', temp_dir, backup_name)
            
            # Отправляем файл администратору
            admin_id = os.getenv('TELEGRAM_ADMIN_ID')
            bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
            
            if admin_id and bot_token:
                import requests
                with open(f'{backup_path}.zip', 'rb') as f:
                    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
                    response = requests.post(
                        url,
                        data={
                            'chat_id': admin_id,
                            'caption': f'🗄️ Резервная копия БД\n📅 {datetime.now().strftime("%d.%m.%Y %H:%M")}'
                        },
                        files={'document': (f'{backup_name}.zip', f, 'application/zip')},
                        timeout=30
                    )
                    if response.status_code != 200:
                        logger.error(f"Failed to send backup: {response.text}")
                        return jsonify({'error': 'Failed to send backup to admin'}), 500
        
        # Обновляем время последнего бекапа
        conn = database.get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE backup_settings SET last_backup = CURRENT_TIMESTAMP")
            conn.commit()
        finally:
            conn.close()
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Backup creation error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/panel/remnawave/squads', methods=['GET'])
@require_auth
def get_remnawave_squads():
    """Получить список сквадов из Remnawave"""
    try:
        import asyncio
        from backend.api.remnawave import get_remnawave_api, RemnaWaveAPI
        
        async def fetch_squads():
            api = get_remnawave_api()
            async with api as connected_api:
                internal_squads = await connected_api.get_internal_squads()
                return [{'uuid': s.uuid, 'name': s.name, 'members_count': s.members_count} for s in internal_squads]
        
        squads = asyncio.run(fetch_squads())
        # Убираем дубликаты по UUID
        seen_uuids = set()
        unique_squads = []
        for sq in squads:
            if sq['uuid'] not in seen_uuids:
                seen_uuids.add(sq['uuid'])
                unique_squads.append(sq)
        return jsonify(unique_squads)
    except Exception as e:
        logger.error(f"Error fetching Remnawave squads: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/panel/remnawave/sync', methods=['POST'])
@require_auth
def sync_remnawave_keys():
    """Синхронизировать ключи с Remnawave - удалить из БД ключи, которых нет в Remnawave"""
    try:
        result = core.sync_keys_with_remnawave()
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error syncing with Remnawave: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/panel/users/mass-action', methods=['POST'])
@require_auth
def mass_user_action():
    """Массовые действия над пользователями"""
    data = request.get_json()
    action_type = data.get('action')
    value = data.get('value', '')
    notify = data.get('notify', False)
    user_ids = data.get('user_ids', [])  # Если пустой - применить ко всем
    
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Получаем список пользователей
        if user_ids:
            placeholders = ','.join('?' * len(user_ids))
            cursor.execute(f"SELECT id, telegram_id, balance FROM users WHERE id IN ({placeholders})", user_ids)
        else:
            cursor.execute("SELECT id, telegram_id, balance FROM users")
        users = cursor.fetchall()
        
        affected = 0
        notifications = []
        
        for user in users:
            user_id = user['id']
            telegram_id = user['telegram_id']
            
            if action_type == 'MASS_ADD_BALANCE':
                amount = float(value)
                cursor.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, user_id))
                cursor.execute("""
                    INSERT INTO transactions (user_id, amount, type, status, description)
                    VALUES (?, ?, 'deposit', 'Success', 'Начисление от администрации')
                """, (user_id, amount))
                if notify:
                    notifications.append((telegram_id, f"💰 Вам начислено {amount} ₽ на баланс!"))
                affected += 1
                
            elif action_type == 'MASS_ADD_DAYS':
                days = int(value)
                cursor.execute("""
                    UPDATE vpn_keys SET expiry_date = datetime(
                        CASE WHEN expiry_date > datetime('now') THEN expiry_date ELSE datetime('now') END,
                        '+' || ? || ' days'
                    ) WHERE user_id = ?
                """, (days, user_id))
                if notify:
                    notifications.append((telegram_id, f"⏰ Ваша подписка продлена на {days} дней!"))
                affected += 1
                
            elif action_type == 'MASS_BAN':
                cursor.execute("UPDATE users SET is_banned = 1 WHERE id = ?", (user_id,))
                if notify:
                    notifications.append((telegram_id, f"⛔ Ваш аккаунт заблокирован. Причина: {value or 'Не указана'}"))
                affected += 1
                
            elif action_type == 'MASS_UNBAN':
                cursor.execute("UPDATE users SET is_banned = 0 WHERE id = ?", (user_id,))
                if notify:
                    notifications.append((telegram_id, "✅ Ваш аккаунт разблокирован!"))
                affected += 1
                
            elif action_type == 'MASS_RESET_TRIAL':
                cursor.execute("UPDATE users SET trial_used = 0 WHERE id = ?", (user_id,))
                if notify:
                    notifications.append((telegram_id, "🎁 Ваш пробный период сброшен! Вы можете снова воспользоваться триалом."))
                affected += 1
                
            elif action_type == 'MASS_DELETE_KEYS':
                cursor.execute("DELETE FROM vpn_keys WHERE user_id = ?", (user_id,))
                if notify:
                    notifications.append((telegram_id, "🔑 Ваши VPN ключи были удалены."))
                affected += 1
                
            elif action_type == 'MASS_SET_PARTNER':
                rate = int(value) if value else 20
                cursor.execute("UPDATE users SET is_partner = 1, partner_rate = ? WHERE id = ?", (rate, user_id))
                if notify:
                    notifications.append((telegram_id, f"🤝 Вы стали партнером! Ваша комиссия: {rate}%"))
                affected += 1
                
            elif action_type == 'MASS_REMOVE_PARTNER':
                cursor.execute("UPDATE users SET is_partner = 0, partner_rate = 0 WHERE id = ?", (user_id,))
                if notify:
                    notifications.append((telegram_id, "👤 Ваш партнерский статус отменен."))
                affected += 1
        
        conn.commit()
        
        # Отправляем уведомления через бота (асинхронно)
        if notifications:
            from threading import Thread
            def send_notifications():
                import asyncio
                from aiogram import Bot
                bot = Bot(token=os.getenv('TELEGRAM_BOT_TOKEN', ''))
                async def send_all():
                    for tg_id, msg in notifications:
                        try:
                            await bot.send_message(tg_id, msg)
                        except Exception as e:
                            logger.warning(f"Failed to send notification to {tg_id}: {e}")
                    await bot.session.close()
                asyncio.run(send_all())
            Thread(target=send_notifications, daemon=True).start()
        
        return jsonify({'success': True, 'affected': affected})
    except Exception as e:
        conn.rollback()
        logger.error(f"Mass action error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/panel/users/<int:user_id>/action', methods=['POST'])
@require_auth
def single_user_action(user_id):
    """Действия над одним пользователем"""
    data = request.get_json()
    action_type = data.get('action')
    value = data.get('value', '')
    notify = data.get('notify', False)
    
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT telegram_id, balance FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        telegram_id = user['telegram_id']
        notification_msg = None
        
        if action_type == 'ADD_BALANCE':
            amount = float(value)
            cursor.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, user_id))
            cursor.execute("""
                INSERT INTO transactions (user_id, amount, type, status, description)
                VALUES (?, ?, 'deposit', 'Success', 'Начисление от администрации')
            """, (user_id, amount))
            notification_msg = f"💰 Вам начислено {amount} ₽ на баланс!"
            
        elif action_type == 'SUB_BALANCE':
            amount = float(value)
            cursor.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (amount, user_id))
            cursor.execute("""
                INSERT INTO transactions (user_id, amount, type, status, description)
                VALUES (?, ?, 'withdrawal', 'Success', 'Списание администрацией')
            """, (user_id, -amount))
            notification_msg = f"💸 С вашего баланса списано {amount} ₽"
            
        elif action_type == 'EXTEND_SUB':
            days = int(value)
            cursor.execute("""
                UPDATE vpn_keys SET expiry_date = datetime(
                    CASE WHEN expiry_date > datetime('now') THEN expiry_date ELSE datetime('now') END,
                    '+' || ? || ' days'
                ) WHERE user_id = ?
            """, (days, user_id))
            notification_msg = f"⏰ Ваша подписка продлена на {days} дней!"
            
        elif action_type == 'REDUCE_SUB':
            days = int(value)
            cursor.execute("""
                UPDATE vpn_keys SET expiry_date = datetime(expiry_date, '-' || ? || ' days')
                WHERE user_id = ?
            """, (days, user_id))
            notification_msg = f"⏰ Срок вашей подписки уменьшен на {days} дней."
            
        elif action_type == 'SET_TRAFFIC':
            limit_gb = int(value)
            cursor.execute("UPDATE vpn_keys SET traffic_limit = ? WHERE user_id = ?", (limit_gb * 1024 * 1024 * 1024, user_id))
            notification_msg = f"📊 Ваш лимит трафика установлен: {limit_gb} ГБ"
            
        elif action_type == 'SET_DEVICES':
            limit = int(value)
            cursor.execute("UPDATE vpn_keys SET devices_limit = ? WHERE user_id = ?", (limit, user_id))
            notification_msg = f"📱 Ваш лимит устройств: {limit}"
            
        elif action_type == 'BAN':
            cursor.execute("UPDATE users SET is_banned = 1 WHERE id = ?", (user_id,))
            notification_msg = f"⛔ Ваш аккаунт заблокирован. Причина: {value or 'Не указана'}"
            
        elif action_type == 'UNBAN':
            cursor.execute("UPDATE users SET is_banned = 0, ban_reason = NULL WHERE id = ?", (user_id,))
            # Также удаляем из черного списка
            cursor.execute("DELETE FROM blacklist WHERE telegram_id = ?", (telegram_id,))
            notification_msg = "✅ Ваш аккаунт разблокирован!"
            
        elif action_type == 'NOTIFY':
            notification_msg = value
        
        conn.commit()
        
        # Отправляем уведомление
        if notify and notification_msg:
            from threading import Thread
            def send_notification():
                import asyncio
                from aiogram import Bot
                bot = Bot(token=os.getenv('TELEGRAM_BOT_TOKEN', ''))
                async def send():
                    try:
                        await bot.send_message(telegram_id, notification_msg)
                    except Exception as e:
                        logger.warning(f"Failed to send notification: {e}")
                    await bot.session.close()
                asyncio.run(send())
            Thread(target=send_notification, daemon=True).start()
        
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        logger.error(f"User action error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


# ========== Авторизация панели (логин/пароль) ==========

@app.route('/api/panel/auth/login', methods=['POST'])
def panel_login():
    """Авторизация в панели по логину и паролю"""
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    
    admin = database.verify_panel_admin(username, password)
    if not admin:
        return jsonify({'error': 'Invalid credentials'}), 401
    
    session_token = database.create_panel_session(admin['id'])
    if not session_token:
        return jsonify({'error': 'Failed to create session'}), 500
    
    return jsonify({
        'success': True,
        'session_token': session_token,
        'username': admin['username']
    })


@app.route('/api/panel/auth/logout', methods=['POST'])
def panel_logout():
    """Выход из панели"""
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header[7:]
        database.delete_panel_session(token)
    return jsonify({'success': True})


@app.route('/api/panel/auth/check', methods=['GET'])
def panel_auth_check():
    """Проверка авторизации (для клиента)"""
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({'authenticated': False}), 401
    
    token = auth_header[7:]
    
    # Legacy PANEL_SECRET
    if token == PANEL_SECRET:
        return jsonify({'authenticated': True, 'method': 'legacy'})
    
    # Сессия
    session = database.verify_panel_session(token)
    if session:
        return jsonify({
            'authenticated': True, 
            'method': 'session',
            'username': session['username']
        })
    
    return jsonify({'authenticated': False}), 401


@app.route('/api/panel/auth/init', methods=['GET'])
def panel_auth_init():
    """
    Получить информацию об инициализации авторизации.
    При первом запуске создаёт дефолтного админа и возвращает пароль.
    """
    result = database.get_or_create_default_admin()
    
    if result.get('password'):
        # Новый админ создан
        return jsonify({
            'initialized': True,
            'new_admin': True,
            'username': result['username'],
            'password': result['password'],
            'message': 'Сохраните эти данные! Пароль показывается только один раз.'
        })
    elif result.get('exists'):
        return jsonify({
            'initialized': True,
            'new_admin': False,
            'username': result['username']
        })
    else:
        return jsonify({'initialized': False, 'error': 'Failed to initialize admin'}), 500


@app.route('/api/panel/auth/change-password', methods=['POST'])
@require_auth
def panel_change_password():
    """Смена пароля администратора"""
    auth_header = request.headers.get('Authorization')
    token = auth_header[7:] if auth_header and auth_header.startswith('Bearer ') else None
    
    session = database.verify_panel_session(token) if token else None
    if not session:
        return jsonify({'error': 'Session required for password change'}), 403
    
    data = request.json
    new_password = data.get('new_password')
    
    if not new_password or len(new_password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters'}), 400
    
    if database.update_admin_password(session['admin_id'], new_password):
        return jsonify({'success': True})
    return jsonify({'error': 'Failed to update password'}), 500


# ========== Управление сквадами ==========

@app.route('/api/panel/squads', methods=['GET'])
@require_auth
def get_squads():
    """Получить все сквады"""
    squads = database.get_all_squad_configs()
    mapping = database.get_subscription_squad_mapping()
    return jsonify({
        'squads': squads,
        'mapping': mapping
    })


@app.route('/api/panel/squads/sync', methods=['POST'])
@require_auth
def sync_squads():
    """Синхронизировать сквады с Remnawave"""
    try:
        import asyncio
        
        async def do_sync():
            api = remnawave.get_remnawave_api()
            async with api as rw_api:
                rw_squads = await rw_api.get_internal_squads()
                
                synced = []
                for squad in rw_squads:
                    # Определяем тип сквада по имени
                    name_lower = squad.name.lower()
                    if 'wifi' in name_lower or 'vpn' in name_lower:
                        squad_type = 'vpn'
                    elif 'lte' in name_lower or 'whitelist' in name_lower:
                        squad_type = 'vpn'  # Whitelist больше не используется
                    elif 'trial' in name_lower or 'test' in name_lower:
                        squad_type = 'trial'
                    else:
                        squad_type = 'vpn'  # По умолчанию
                    
                    database.upsert_squad_config(
                        squad_uuid=squad.uuid,
                        squad_name=squad.name,
                        squad_type=squad_type,
                        max_users=0,  # Без лимита по умолчанию
                        priority=squad.view_position
                    )
                    synced.append({
                        'uuid': squad.uuid,
                        'name': squad.name,
                        'type': squad_type
                    })
                
                # Синхронизируем счётчики
                database.sync_squad_user_counts()
                
                return synced
        
        synced = asyncio.run(do_sync())
        return jsonify({
            'success': True,
            'synced': synced,
            'count': len(synced)
        })
    except Exception as e:
        logger.error(f"Squad sync error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/panel/squads/<squad_uuid>', methods=['PUT'])
@require_auth
def update_squad(squad_uuid: str):
    """Обновить настройки сквада"""
    data = request.json
    
    squad_name = data.get('squad_name')
    squad_type = data.get('squad_type')
    max_users = data.get('max_users', 0)
    priority = data.get('priority', 0)
    is_active = data.get('is_active', True)
    
    if not squad_name or not squad_type:
        return jsonify({'error': 'squad_name and squad_type required'}), 400
    
    conn = database.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE squad_configs 
            SET squad_name = ?, squad_type = ?, max_users = ?, 
                priority = ?, is_active = ?, updated_at = CURRENT_TIMESTAMP
            WHERE squad_uuid = ?
        """, (squad_name, squad_type, max_users, priority, 1 if is_active else 0, squad_uuid))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/panel/squads/mapping', methods=['PUT'])
@require_auth
def update_squad_mapping():
    """Обновить привязку сквадов к типам подписок"""
    data = request.json
    
    vpn_squads = data.get('vpn', [])
    trial_squads = data.get('trial', [])
    
    success = True
    success = success and database.set_subscription_squads('vpn', vpn_squads)
    success = success and database.set_subscription_squads('trial', trial_squads)
    
    if success:
        return jsonify({'success': True})
    return jsonify({'error': 'Failed to update mapping'}), 500


@app.route('/api/panel/squads/counts', methods=['POST'])
@require_auth
def sync_squad_counts():
    """Синхронизировать счётчики пользователей в сквадах"""
    database.sync_squad_user_counts()
    return jsonify({'success': True})


# ========== Выдача ключа с выбором типа ==========

@app.route('/api/panel/issue-key', methods=['POST'])
@require_auth
def issue_key_with_type():
    """
    Выдать ключ пользователю с указанием типа подписки.
    Автоматически выбирает лучший сквад для балансировки.
    """
    data = request.json
    user_id = data.get('user_id')
    plan_type = data.get('plan_type', 'vpn')  # vpn, whitelist, trial
    days = data.get('days', 30)
    traffic_limit_gb = data.get('traffic_limit_gb', 0)  # 0 = безлимит
    
    if not user_id:
        return jsonify({'error': 'user_id required'}), 400
    
    user = database.get_user_by_id(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    try:
        # Выбираем лучший сквад для этого типа подписки
        best_squad = database.get_best_squad_for_subscription(plan_type)
        squad_uuids = [best_squad['squad_uuid']] if best_squad else None
        
        if not squad_uuids:
            # Используем дефолтные сквады из настроек
            squad_uuids = database.get_default_squads(plan_type)
        
        # Конвертируем трафик в байты
        traffic_limit_bytes = int(traffic_limit_gb * 1024 * 1024 * 1024) if traffic_limit_gb > 0 else 0
        
        # Создаём подписку через core
        result = core.create_user_and_subscription(
            telegram_id=user['telegram_id'],
            username=user.get('username', ''),
            days=days,
            traffic_limit=traffic_limit_bytes,
            plan_type=plan_type,
            squad_uuids=squad_uuids
        )
        
        if result:
            # Обновляем счётчик сквада
            if best_squad:
                database.update_squad_user_count(best_squad['squad_uuid'], 1)
            
            return jsonify({
                'success': True,
                'subscription': result,
                'squad': best_squad['squad_name'] if best_squad else 'default'
            })
        
        return jsonify({'error': 'Failed to create subscription'}), 500
    except Exception as e:
        logger.error(f"Issue key error: {e}")
        return jsonify({'error': str(e)}), 500


# Функция создания автоматического бэкапа
def auto_backup():
    """Создать автоматический бэкап и отправить администратору"""
    import shutil
    import tempfile
    
    try:
        # Проверяем, включены ли бэкапы
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT enabled FROM backup_settings ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        
        if not row or not row['enabled']:
            logger.info("Auto backup skipped - disabled in settings")
            return
        
        db_path = os.path.join(os.path.dirname(__file__), '..', 'database', 'blinvpn.db')
        if not os.path.exists(db_path):
            logger.error("Database file not found for auto backup")
            return
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f'blinvpn_auto_backup_{timestamp}.db'
        
        with tempfile.TemporaryDirectory() as temp_dir:
            backup_path = os.path.join(temp_dir, backup_name)
            shutil.copy2(db_path, backup_path)
            
            # Создаем zip архив
            shutil.make_archive(backup_path, 'zip', temp_dir, backup_name)
            
            # Отправляем администратору
            admin_id = os.getenv('TELEGRAM_ADMIN_ID')
            bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
            
            if admin_id and bot_token:
                import requests
                with open(f'{backup_path}.zip', 'rb') as f:
                    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
                    response = requests.post(
                        url,
                        data={
                            'chat_id': admin_id,
                            'caption': f'🗄️ Автоматический бэкап БД\n📅 {datetime.now().strftime("%d.%m.%Y %H:%M")} МСК'
                        },
                        files={'document': (f'{backup_name}.zip', f, 'application/zip')},
                        timeout=60
                    )
                    if response.status_code == 200:
                        logger.info(f"Auto backup sent successfully")
                    else:
                        logger.error(f"Failed to send auto backup: {response.text}")
        
        # Обновляем время последнего бэкапа
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE backup_settings SET last_backup = CURRENT_TIMESTAMP")
        conn.commit()
        conn.close()
        
    except Exception as e:
        logger.error(f"Auto backup error: {e}")


# ===== TOOLS ENDPOINTS =====

@app.route('/api/panel/export/<data_type>', methods=['GET'])
@require_auth
def export_data(data_type: str):
    """Экспорт данных в JSON"""
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        if data_type == 'users':
            cursor.execute("SELECT * FROM users ORDER BY id")
        elif data_type == 'keys':
            cursor.execute("SELECT * FROM vpn_keys ORDER BY id")
        elif data_type == 'transactions':
            cursor.execute("SELECT * FROM transactions ORDER BY id DESC LIMIT 10000")
        else:
            return jsonify({'error': 'Invalid data type'}), 400
        
        rows = cursor.fetchall()
        data = [dict(row) for row in rows]
        return jsonify({'data': data})
    finally:
        conn.close()

@app.route('/api/panel/diagnostics', methods=['GET'])
@require_auth
def get_diagnostics():
    """Диагностика системы"""
    conn = database.get_db_connection()
    cursor = conn.cursor()
    issues = []
    
    try:
        # Количество пользователей
        cursor.execute("SELECT COUNT(*) FROM users")
        users_count = cursor.fetchone()[0]
        
        # Количество ключей
        cursor.execute("SELECT COUNT(*) FROM vpn_keys")
        keys_count = cursor.fetchone()[0]
        
        # Активные ключи
        cursor.execute("SELECT COUNT(*) FROM vpn_keys WHERE status = 'Active' AND expiry_date > datetime('now')")
        active_keys = cursor.fetchone()[0]
        
        # Истёкшие ключи
        cursor.execute("SELECT COUNT(*) FROM vpn_keys WHERE expiry_date < datetime('now')")
        expired_keys = cursor.fetchone()[0]
        
        # Забаненные пользователи
        cursor.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1")
        banned_users = cursor.fetchone()[0]
        
        # Проверка Remnawave
        remnawave_status = 'OK'
        try:
            rw_squads = remnawave.get_all_squads()
            if not rw_squads:
                remnawave_status = 'Нет сквадов'
                issues.append('Remnawave: нет доступных сквадов')
        except Exception as e:
            remnawave_status = 'Ошибка'
            issues.append(f'Remnawave: {str(e)[:50]}')
        
        # Проверка проблем
        if expired_keys > 100:
            issues.append(f'Много истёкших ключей: {expired_keys}')
        
        cursor.execute("SELECT COUNT(*) FROM users WHERE balance < 0")
        negative_balance = cursor.fetchone()[0]
        if negative_balance > 0:
            issues.append(f'Пользователей с отрицательным балансом: {negative_balance}')
        
        return jsonify({
            'users_count': users_count,
            'keys_count': keys_count,
            'active_keys': active_keys,
            'expired_keys': expired_keys,
            'banned_users': banned_users,
            'remnawave_status': remnawave_status,
            'issues': issues
        })
    finally:
        conn.close()

@app.route('/api/panel/tools/cleanup-expired', methods=['POST'])
@require_auth
def cleanup_expired_keys():
    """Удалить истёкшие ключи старше 30 дней"""
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Получаем ключи для удаления
        cursor.execute("""
            SELECT key_uuid FROM vpn_keys 
            WHERE expiry_date < datetime('now', '-30 days')
        """)
        keys_to_delete = [row[0] for row in cursor.fetchall()]
        
        # Удаляем из Remnawave
        deleted = 0
        for key_uuid in keys_to_delete:
            try:
                remnawave.delete_user(key_uuid)
                deleted += 1
            except:
                pass
        
        # Удаляем из базы
        cursor.execute("""
            DELETE FROM vpn_keys 
            WHERE expiry_date < datetime('now', '-30 days')
        """)
        conn.commit()
        
        return jsonify({'success': True, 'deleted': deleted})
    finally:
        conn.close()

# Запуск планировщика для автоматических бэкапов
def start_backup_scheduler():
    """Запустить планировщик для бэкапов в 02:00 МСК"""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        import pytz
        
        scheduler = BackgroundScheduler()
        moscow_tz = pytz.timezone('Europe/Moscow')
        
        # Бэкап каждый день в 02:00 МСК
        scheduler.add_job(
            auto_backup,
            CronTrigger(hour=2, minute=0, timezone=moscow_tz),
            id='auto_backup',
            name='Daily backup at 02:00 MSK',
            replace_existing=True
        )
        
        scheduler.start()
        logger.info("Backup scheduler started - daily at 02:00 MSK")
        
    except ImportError:
        logger.warning("APScheduler not installed, auto backups disabled. Install with: pip install apscheduler pytz")
    except Exception as e:
        logger.error(f"Failed to start backup scheduler: {e}")


if __name__ == '__main__':
    # Запускаем планировщик бэкапов
    start_backup_scheduler()
    app.run(host='0.0.0.0', port=int(os.getenv('API_PORT', 8000)))

