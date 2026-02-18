"""
Модуль для работы с базой данных SQLite
"""
import sqlite3
import os
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import hashlib

logger = logging.getLogger(__name__)

DB_PATH = os.getenv('DB_PATH', 'data.db')


def get_db_connection():
    """Получить соединение с базой данных"""
    db_dir = os.path.dirname(os.path.abspath(DB_PATH))
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


def init_database():
    """Инициализация базы данных"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Пользователи
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                full_name TEXT,
                balance REAL DEFAULT 0,
                status TEXT DEFAULT 'Trial',
                registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                paid_until TIMESTAMP,
                referral_code TEXT UNIQUE,
                referred_by INTEGER,
                is_partner INTEGER DEFAULT 0,
                partner_rate INTEGER DEFAULT 20,
                partner_balance REAL DEFAULT 0,
                total_earned REAL DEFAULT 0,
                trial_used INTEGER DEFAULT 0,
                banned_keys_count INTEGER DEFAULT 0,
                is_banned INTEGER DEFAULT 0,
                ban_reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (referred_by) REFERENCES users(id)
            )
        """)
        
        # VPN ключи
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS vpn_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                key_uuid TEXT UNIQUE,
                key_config TEXT,
                status TEXT DEFAULT 'Active',
                expiry_date TIMESTAMP,
                traffic_used REAL DEFAULT 0,
                traffic_limit REAL,
                devices_limit INTEGER DEFAULT 1,
                server_location TEXT,
                hwid_hash TEXT,
                last_used TIMESTAMP,
                last_ip TEXT,
                squad_uuid TEXT,
                plan_type TEXT DEFAULT 'vpn',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        
        # Транзакции
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                amount REAL NOT NULL,
                status TEXT DEFAULT 'Pending',
                payment_method TEXT,
                payment_provider TEXT,
                payment_id TEXT,
                description TEXT,
                hash TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        
        # Промокоды
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS promocodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                type TEXT NOT NULL,
                value TEXT NOT NULL,
                uses_count INTEGER DEFAULT 0,
                uses_limit INTEGER,
                expires_at TIMESTAMP,
                is_active INTEGER DEFAULT 1,
                target_type TEXT DEFAULT 'all',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Использование промокодов
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS promocode_uses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                promocode_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (promocode_id) REFERENCES promocodes(id),
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(promocode_id, user_id)
            )
        """)
        
        # Статистика трафика
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS traffic_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vpn_key_id INTEGER,
                user_id INTEGER NOT NULL,
                date DATE NOT NULL,
                traffic_bytes REAL DEFAULT 0,
                unique_hwids INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (vpn_key_id) REFERENCES vpn_keys(id),
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(vpn_key_id, date)
            )
        """)
        
        # Черный список
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS blacklist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Рассылки
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mailings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                message_text TEXT,
                target_users TEXT,
                sent_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'Pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sent_at TIMESTAMP,
                button_type TEXT,
                button_value TEXT,
                image_url TEXT
            )
        """)
        
        # Тарифные планы
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tariff_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_type TEXT NOT NULL,
                name TEXT NOT NULL,
                price REAL NOT NULL,
                duration_days INTEGER NOT NULL,
                is_active INTEGER DEFAULT 1,
                sort_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Настройки whitelist
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS whitelist_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subscription_fee REAL DEFAULT 100.0,
                price_per_gb REAL DEFAULT 15.0,
                min_gb INTEGER DEFAULT 5,
                max_gb INTEGER DEFAULT 500,
                auto_pay_enabled INTEGER DEFAULT 1,
                auto_pay_threshold_mb INTEGER DEFAULT 100,
                pricing_type TEXT DEFAULT 'fixed',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Авто-скидки
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS auto_discounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                condition_type TEXT NOT NULL,
                condition_value TEXT NOT NULL,
                discount_type TEXT NOT NULL,
                discount_value REAL NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Публичные страницы
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS public_pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                page_type TEXT UNIQUE NOT NULL,
                content TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Системные настройки
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                setting_key TEXT UNIQUE NOT NULL,
                setting_value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Комиссии платежных систем
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payment_fees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_method TEXT UNIQUE NOT NULL,
                fee_percent REAL DEFAULT 0.0,
                fee_fixed REAL DEFAULT 0.0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Сохраненные способы оплаты
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS saved_payment_methods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                payment_provider TEXT NOT NULL,
                payment_method_id TEXT NOT NULL,
                payment_method_type TEXT,
                card_last4 TEXT,
                card_brand TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(user_id, payment_provider, payment_method_id)
            )
        """)
        
        # Настройки провайдеров
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payment_provider_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                setting_key TEXT NOT NULL,
                setting_value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(provider, setting_key)
            )
        """)
        
        # Настройки бэкапов
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS backup_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                enabled INTEGER DEFAULT 0,
                interval_hours INTEGER DEFAULT 12,
                last_backup TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Конфигурация сквадов
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS squad_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                squad_uuid TEXT UNIQUE NOT NULL,
                squad_name TEXT NOT NULL,
                squad_type TEXT NOT NULL,
                max_users INTEGER DEFAULT 0,
                current_users INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                priority INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Привязка подписок к сквадам
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS subscription_squad_mapping (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subscription_type TEXT NOT NULL,
                squad_uuid TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(subscription_type, squad_uuid)
            )
        """)
        
        # Администраторы панели
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS panel_admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                last_login TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Сессии панели
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS panel_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER NOT NULL,
                session_token TEXT UNIQUE NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (admin_id) REFERENCES panel_admins(id)
            )
        """)
        
        # Индексы
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_referral_code ON users(referral_code)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_vpn_keys_user_id ON vpn_keys(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_vpn_keys_status ON vpn_keys(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_vpn_keys_key_uuid ON vpn_keys(key_uuid)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user_id ON transactions(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_traffic_stats_date ON traffic_stats(date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_blacklist_telegram_id ON blacklist(telegram_id)")
        
        conn.commit()
        
        # Дефолтные тарифы
        cursor.execute("SELECT COUNT(*) FROM tariff_plans WHERE plan_type = 'vpn'")
        if cursor.fetchone()[0] == 0:
            default_plans = [
                ('vpn', '1 месяц', 99, 30, 1),
                ('vpn', '3 месяца', 249, 90, 2),
                ('vpn', '6 месяцев', 449, 180, 3),
                ('vpn', '1 год', 799, 365, 4),
                ('vpn', '2 года', 1199, 730, 5),
            ]
            cursor.executemany("""
                INSERT INTO tariff_plans (plan_type, name, price, duration_days, sort_order)
                VALUES (?, ?, ?, ?, ?)
            """, default_plans)
        
        # Настройки whitelist
        cursor.execute("SELECT COUNT(*) FROM whitelist_settings")
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
                INSERT INTO whitelist_settings (subscription_fee, price_per_gb, min_gb, max_gb, pricing_type)
                VALUES (299.0, 15.0, 100, 500, 'fixed')
            """)
        
        # Публичные страницы
        for page_type in ['offer', 'privacy']:
            cursor.execute("SELECT COUNT(*) FROM public_pages WHERE page_type = ?", (page_type,))
            if cursor.fetchone()[0] == 0:
                cursor.execute("INSERT INTO public_pages (page_type, content) VALUES (?, '')", (page_type,))
        
        # Комиссии
        for method in ['platega', 'crypto']:
            cursor.execute("SELECT COUNT(*) FROM payment_fees WHERE payment_method = ?", (method,))
            if cursor.fetchone()[0] == 0:
                cursor.execute("INSERT INTO payment_fees (payment_method) VALUES (?)", (method,))
        
        conn.commit()
        logger.info("Database initialized")
        
    except Exception as e:
        logger.error(f"Database init error: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


# ===== ПОЛЬЗОВАТЕЛИ =====

def create_user(telegram_id: int, username: str = None, full_name: str = None, referred_by: int = None) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        referral_code = f"REF{telegram_id}"
        cursor.execute("""
            INSERT INTO users (telegram_id, username, full_name, referral_code, referred_by)
            VALUES (?, ?, ?, ?, ?)
        """, (telegram_id, username, full_name, referral_code, referred_by))
        user_id = cursor.lastrowid
        conn.commit()
        return user_id
    except sqlite3.IntegrityError:
        cursor.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
        row = cursor.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def get_user_by_telegram_id(telegram_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_user_balance(user_id: int, amount: float, ensure_non_negative: bool = False) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute("SELECT balance FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            conn.rollback()
            return False
        new_balance = (row["balance"] or 0) + amount
        if ensure_non_negative and new_balance < 0:
            conn.rollback()
            return False
        cursor.execute("UPDATE users SET balance = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                      (new_balance, user_id))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def update_user_full_name(telegram_id: int, full_name: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE users SET full_name = ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
                      (full_name, telegram_id))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def update_user_username(telegram_id: int, username: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE users SET username = ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
                      (username, telegram_id))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_all_users(limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM users ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


# ===== VPN КЛЮЧИ =====

def get_user_vpn_keys(user_id: int) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM vpn_keys WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_vpn_key_by_uuid(key_uuid: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM vpn_keys WHERE key_uuid = ?", (key_uuid,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_vpn_key_by_id(key_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM vpn_keys WHERE id = ?", (key_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_vpn_key(user_id: int, key_uuid: str, key_config: str = None,
                   plan_type: str = 'vpn', expiry_date: str = None,
                   traffic_limit: float = None, squad_uuid: str = None) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO vpn_keys (user_id, key_uuid, key_config, plan_type, expiry_date, traffic_limit, squad_uuid)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, key_uuid, key_config, plan_type, expiry_date, traffic_limit, squad_uuid))
        key_id = cursor.lastrowid
        conn.commit()
        return key_id
    finally:
        conn.close()


def update_vpn_key(key_id: int, **kwargs) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        allowed = ['status', 'expiry_date', 'traffic_used', 'traffic_limit', 'key_config',
                   'last_used', 'last_ip', 'squad_uuid', 'plan_type', 'hwid_hash', 'devices_limit']
        updates = []
        values = []
        for k, v in kwargs.items():
            if k in allowed:
                updates.append(f"{k} = ?")
                values.append(v)
        if not updates:
            return False
        values.append(key_id)
        cursor.execute(f"UPDATE vpn_keys SET {', '.join(updates)} WHERE id = ?", values)
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def delete_vpn_key(key_id: int) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM vpn_keys WHERE id = ?", (key_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def update_vpn_key_traffic(key_uuid: str, traffic_used: float) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE vpn_keys SET traffic_used = ? WHERE key_uuid = ?", (traffic_used, key_uuid))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def count_user_active_keys(user_id: int, plan_type: str = None) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if plan_type:
            cursor.execute("""
                SELECT COUNT(*) FROM vpn_keys 
                WHERE user_id = ? AND status = 'Active' AND plan_type = ?
            """, (user_id, plan_type))
        else:
            cursor.execute("SELECT COUNT(*) FROM vpn_keys WHERE user_id = ? AND status = 'Active'", (user_id,))
        return cursor.fetchone()[0]
    finally:
        conn.close()


def get_all_vpn_keys(limit: int = 100, offset: int = 0, plan_type: str = None) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if plan_type:
            cursor.execute("""
                SELECT vk.*, u.telegram_id, u.username 
                FROM vpn_keys vk LEFT JOIN users u ON vk.user_id = u.id
                WHERE vk.plan_type = ? ORDER BY vk.id DESC LIMIT ? OFFSET ?
            """, (plan_type, limit, offset))
        else:
            cursor.execute("""
                SELECT vk.*, u.telegram_id, u.username 
                FROM vpn_keys vk LEFT JOIN users u ON vk.user_id = u.id
                ORDER BY vk.id DESC LIMIT ? OFFSET ?
            """, (limit, offset))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


# ===== СИСТЕМНЫЕ НАСТРОЙКИ =====

def hash_hwid(hwid: str) -> str:
    return hashlib.sha256(hwid.encode()).hexdigest()


def get_system_setting(key: str, default: str = None) -> Optional[str]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT setting_value FROM system_settings WHERE setting_key = ?", (key,))
        row = cursor.fetchone()
        return row['setting_value'] if row else default
    finally:
        conn.close()


def set_system_setting(key: str, value: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO system_settings (setting_key, setting_value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        """, (key, value))
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()


def get_default_squads(plan_type: str = 'vpn') -> List[str]:
    import json
    value = get_system_setting(f'default_squads_{plan_type}', '[]')
    try:
        return json.loads(value)
    except:
        return []


def set_default_squads(squad_uuids: List[str], plan_type: str = 'vpn') -> bool:
    import json
    return set_system_setting(f'default_squads_{plan_type}', json.dumps(list(dict.fromkeys(squad_uuids))))


# ===== РЕФЕРАЛЫ =====

def check_referral_rate_limit(referrer_telegram_id: int, limit: int = 25, window_seconds: int = 60) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cutoff = datetime.now() - timedelta(seconds=window_seconds)
        cursor.execute("""
            SELECT COUNT(*) FROM users
            WHERE referred_by = (SELECT id FROM users WHERE telegram_id = ?)
            AND registration_date > ?
        """, (referrer_telegram_id, cutoff.isoformat()))
        return cursor.fetchone()[0] < limit
    finally:
        conn.close()


def set_referrer_for_user(user_id: int, referrer_id: int) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT referred_by FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row or row['referred_by'] is not None:
            return False
        cursor.execute("UPDATE users SET referred_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                      (referrer_id, user_id))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_user_by_referral_code(referral_code: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM users WHERE referral_code = ?", (referral_code,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def credit_referral_income(user_id: int, purchase_amount: float, description: str = None) -> Optional[Dict]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT u.id, u.username, u.referred_by,
                   r.id as referrer_id, r.telegram_id as referrer_telegram_id,
                   r.partner_rate, r.username as referrer_username
            FROM users u LEFT JOIN users r ON u.referred_by = r.id
            WHERE u.id = ?
        """, (user_id,))
        row = cursor.fetchone()
        if not row or not row['referrer_id']:
            return None
        
        referrer_id = row['referrer_id']
        
        # Проверяем, была ли уже начислена реферальная выплата за этого реферала
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM transactions
            WHERE user_id = ? AND type = 'referral_income'
            AND description LIKE ?
        """, (referrer_id, f"%реферала%{row['username'] or user_id}%"))
        
        existing_count = cursor.fetchone()['count']
        if existing_count > 0:
            # Уже начисляли за этого реферала - не начисляем повторно
            return None
        
        # Фиксированная сумма 50 рублей за приглашение
        income = 50.0
        
        cursor.execute("""
            UPDATE users SET partner_balance = partner_balance + ?,
                           total_earned = total_earned + ?,
                           updated_at = CURRENT_TIMESTAMP WHERE id = ?
        """, (income, income, referrer_id))
        
        desc = description or f"Доход от реферала @{row['username'] or user_id}: 50₽ за приглашение"
        cursor.execute("""
            INSERT INTO transactions (user_id, type, amount, status, description)
            VALUES (?, 'referral_income', ?, 'Success', ?)
        """, (referrer_id, income, desc))
        
        conn.commit()
        return {
            'referrer_id': referrer_id,
            'referrer_telegram_id': row['referrer_telegram_id'],
            'income': income,
            'rate': 0,  # Больше не процент
            'purchase_amount': purchase_amount
        }
    except Exception as e:
        logger.error(f"Referral income error: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()


def get_referrer_info(user_id: int) -> Optional[Dict]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT r.id, r.telegram_id, r.username, r.full_name
            FROM users u JOIN users r ON u.referred_by = r.id WHERE u.id = ?
        """, (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ===== СКВАДЫ =====

def get_all_squad_configs() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM squad_configs ORDER BY squad_type, priority DESC")
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_squads_for_subscription(subscription_type: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT sc.* FROM squad_configs sc
            JOIN subscription_squad_mapping ssm ON sc.squad_uuid = ssm.squad_uuid
            WHERE ssm.subscription_type = ? AND ssm.is_active = 1 AND sc.is_active = 1
            ORDER BY sc.priority DESC, sc.current_users ASC
        """, (subscription_type,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_best_squad_for_subscription(subscription_type: str) -> Optional[Dict[str, Any]]:
    squads = get_squads_for_subscription(subscription_type)
    if not squads:
        return None
    available = [s for s in squads if s['max_users'] == 0 or s['current_users'] < s['max_users']]
    if not available:
        available = squads
    return min(available, key=lambda s: s['current_users'])


def update_squad_user_count(squad_uuid: str, delta: int = 1) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE squad_configs SET current_users = MAX(0, current_users + ?),
                                    updated_at = CURRENT_TIMESTAMP WHERE squad_uuid = ?
        """, (delta, squad_uuid))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def upsert_squad_config(squad_uuid: str, squad_name: str, squad_type: str,
                        max_users: int = 0, priority: int = 0) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO squad_configs (squad_uuid, squad_name, squad_type, max_users, priority)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(squad_uuid) DO UPDATE SET
                squad_name = excluded.squad_name, squad_type = excluded.squad_type,
                max_users = excluded.max_users, priority = excluded.priority,
                updated_at = CURRENT_TIMESTAMP
        """, (squad_uuid, squad_name, squad_type, max_users, priority))
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()


def sync_squad_user_counts() -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT squad_uuid, COUNT(*) as cnt FROM vpn_keys 
            WHERE squad_uuid IS NOT NULL AND status = 'Active' GROUP BY squad_uuid
        """)
        counts = {row['squad_uuid']: row['cnt'] for row in cursor.fetchall()}
        
        cursor.execute("SELECT squad_uuid FROM squad_configs")
        for row in cursor.fetchall():
            cursor.execute("UPDATE squad_configs SET current_users = ?, updated_at = CURRENT_TIMESTAMP WHERE squad_uuid = ?",
                          (counts.get(row['squad_uuid'], 0), row['squad_uuid']))
        conn.commit()
    except Exception as e:
        logger.error(f"Sync squad counts error: {e}")
        conn.rollback()
    finally:
        conn.close()


def get_subscription_squad_mapping() -> Dict[str, List[str]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT subscription_type, squad_uuid FROM subscription_squad_mapping WHERE is_active = 1")
        result = {'vpn': [], 'whitelist': [], 'trial': []}
        for row in cursor.fetchall():
            if row['subscription_type'] in result:
                result[row['subscription_type']].append(row['squad_uuid'])
        return result
    finally:
        conn.close()


def set_subscription_squads(subscription_type: str, squad_uuids: List[str]) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM subscription_squad_mapping WHERE subscription_type = ?", (subscription_type,))
        for uuid in squad_uuids:
            cursor.execute("INSERT INTO subscription_squad_mapping (subscription_type, squad_uuid) VALUES (?, ?)",
                          (subscription_type, uuid))
        conn.commit()
        return True
    except:
        conn.rollback()
        return False
    finally:
        conn.close()


# ===== АВТОРИЗАЦИЯ ПАНЕЛИ =====

def create_panel_admin(username: str, password: str) -> Optional[int]:
    import secrets
    salt = secrets.token_hex(16)
    password_hash = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO panel_admins (username, password_hash) VALUES (?, ?)",
                      (username, f"{salt}:{password_hash}"))
        conn.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def verify_panel_admin(username: str, password: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, username, password_hash, is_active FROM panel_admins WHERE username = ? AND is_active = 1",
                      (username,))
        row = cursor.fetchone()
        if not row:
            return None
        
        salt, expected = row['password_hash'].split(':', 1)
        computed = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
        if computed != expected:
            return None
        
        cursor.execute("UPDATE panel_admins SET last_login = CURRENT_TIMESTAMP WHERE id = ?", (row['id'],))
        conn.commit()
        return {'id': row['id'], 'username': row['username']}
    finally:
        conn.close()


def create_panel_session(admin_id: int) -> Optional[str]:
    import secrets
    token = secrets.token_urlsafe(32)
    expires = datetime.now() + timedelta(days=7)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM panel_sessions WHERE admin_id = ?", (admin_id,))
        cursor.execute("INSERT INTO panel_sessions (admin_id, session_token, expires_at) VALUES (?, ?, ?)",
                      (admin_id, token, expires.isoformat()))
        conn.commit()
        return token
    except:
        return None
    finally:
        conn.close()


def verify_panel_session(session_token: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT ps.*, pa.username FROM panel_sessions ps
            JOIN panel_admins pa ON ps.admin_id = pa.id
            WHERE ps.session_token = ? AND ps.expires_at > CURRENT_TIMESTAMP AND pa.is_active = 1
        """, (session_token,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def delete_panel_session(session_token: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM panel_sessions WHERE session_token = ?", (session_token,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_or_create_default_admin() -> Dict[str, str]:
    import secrets
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, username FROM panel_admins WHERE is_active = 1 LIMIT 1")
        row = cursor.fetchone()
        if row:
            return {'username': row['username'], 'password': None, 'exists': True}
        
        username = 'admin'
        password = secrets.token_urlsafe(12)
        admin_id = create_panel_admin(username, password)
        if admin_id:
            return {'username': username, 'password': password, 'exists': False}
        return {'username': None, 'password': None, 'exists': False}
    finally:
        conn.close()


def update_admin_password(admin_id: int, new_password: str) -> bool:
    import secrets
    salt = secrets.token_hex(16)
    password_hash = hashlib.sha256(f"{salt}:{new_password}".encode()).hexdigest()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE panel_admins SET password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                      (f"{salt}:{password_hash}", admin_id))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


# Инициализация при импорте
if __name__ != "__main__":
    init_database()
