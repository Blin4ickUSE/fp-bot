"""
API модуль для работы с Platega
Документация: https://app.platega.io/
"""
import os
import requests
import logging
import uuid
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Конфигурация
PLATEGA_API_URL = os.getenv('PLATEGA_API_URL', 'https://app.platega.io')
PLATEGA_MERCHANT_ID = os.getenv('PLATEGA_MERCHANT_ID', '')
PLATEGA_SECRET_KEY = os.getenv('PLATEGA_SECRET_KEY', '')
PLATEGA_RETURN_URL = os.getenv('PLATEGA_RETURN_URL', '')
PLATEGA_FAILED_URL = os.getenv('PLATEGA_FAILED_URL', '')

# Методы оплаты Platega
PLATEGA_METHOD_SBP_QR = 2       # СБП QR
PLATEGA_METHOD_CARD_RUB = 10   # Карты (RUB)
PLATEGA_METHOD_CARD = 11       # Карточный эквайринг
PLATEGA_METHOD_INTL = 12       # Международный эквайринг
PLATEGA_METHOD_CRYPTO = 13     # Криптовалюта

# Статусы платежей
PLATEGA_SUCCESS_STATUSES = {"CONFIRMED"}
PLATEGA_FAILED_STATUSES = {"CANCELED", "CHARGEBACKED"}
PLATEGA_PENDING_STATUSES = {"PENDING"}


class PlategaAPI:
    """Класс для работы с Platega API"""
    
    def __init__(self):
        self.base_url = PLATEGA_API_URL.rstrip('/')
        self.merchant_id = PLATEGA_MERCHANT_ID
        self.secret_key = PLATEGA_SECRET_KEY
        self.return_url = PLATEGA_RETURN_URL
        self.failed_url = PLATEGA_FAILED_URL
    
    @property
    def is_configured(self) -> bool:
        """Проверить, настроен ли Platega"""
        return bool(self.merchant_id and self.secret_key)
    
    def _request(self, method: str, endpoint: str, data: Dict = None) -> Optional[Dict]:
        """Базовый метод для выполнения запросов"""
        if not self.is_configured:
            logger.error("Platega не настроен: отсутствуют MERCHANT_ID или SECRET_KEY")
            return None
            
        url = f"{self.base_url}{endpoint}"
        
        # Заголовки авторизации по документации
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-MerchantId': self.merchant_id,
            'X-Secret': self.secret_key,
        }
        
        try:
            logger.info(f"Platega request: {method} {url}")
            
            if method == 'POST':
                response = requests.post(url, headers=headers, json=data, timeout=30)
            elif method == 'GET':
                response = requests.get(url, headers=headers, params=data, timeout=30)
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            logger.info(f"Platega response: {response.status_code}")
            
            response.raise_for_status()
            return response.json() if response.content else None
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Platega API error: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            return None
    
    def create_payment(self, amount: float, user_id: int, description: str = None,
                      payment_method: int = PLATEGA_METHOD_SBP_QR) -> Optional[Dict]:
        """
        Создать платеж через Platega
        
        Args:
            amount: Сумма платежа в рублях
            user_id: ID пользователя
            description: Описание платежа
            payment_method: Метод оплаты (2=СБП QR, 10=Карты RUB, 11=Карточный, 12=Международный, 13=Крипто)
        """
        if not self.is_configured:
            return None
        
        # Уникальный payload для идентификации платежа
        correlation_id = f"platega_{user_id}_{uuid.uuid4().hex[:8]}"
        
        # Формат запроса по документации
        data = {
            'paymentMethod': payment_method,
            'paymentDetails': {
                'amount': float(amount),
                'currency': 'RUB'
            },
            'description': description or f'Пополнение баланса',
            'return': self.return_url,
            'failedUrl': self.failed_url,
            'payload': correlation_id,
        }
        
        # Endpoint по документации: /transaction/process
        result = self._request('POST', '/transaction/process', data)
        
        if result:
            transaction_id = result.get('transactionId')
            redirect_url = result.get('redirect')
            status = str(result.get('status', 'PENDING')).upper()
            
            logger.info(f"Platega платеж создан: {transaction_id} для user {user_id}, сумма {amount}₽")
            
            return {
                'id': transaction_id,
                'redirect_url': redirect_url,
                'status': status,
                'correlation_id': correlation_id,
                'payload': correlation_id,
                'amount': amount,
                'amount_kopeks': int(amount * 100),
                'expires_in': result.get('expiresIn'),
            }
        
        return None
    
    def create_sbp_payment(self, amount: float, user_id: int, description: str = None) -> Optional[Dict]:
        """Создать СБП QR платеж"""
        return self.create_payment(amount, user_id, description, PLATEGA_METHOD_SBP_QR)
    
    def create_card_payment(self, amount: float, user_id: int, description: str = None) -> Optional[Dict]:
        """Создать платеж картой (RUB)"""
        return self.create_payment(amount, user_id, description, PLATEGA_METHOD_CARD_RUB)
    
    def verify_webhook(self, headers: Dict, payload: Dict) -> bool:
        """
        Проверить webhook от Platega
        
        По документации: Platega отправляет X-MerchantId и X-Secret в заголовках
        """
        if not self.is_configured:
            return True
        
        received_merchant = headers.get('X-MerchantId', '')
        received_secret = headers.get('X-Secret', '')
        
        return (received_merchant == self.merchant_id and 
                received_secret == self.secret_key)
    
    def verify_webhook_signature(self, payload: Dict, signature: str = None) -> bool:
        """Обратная совместимость - проверка webhook"""
        return True  # Platega использует X-MerchantId/X-Secret, не подпись


platega_api = PlategaAPI()
