"""
Отправка тикетов в поддержку FunPay (support.funpay.com) для авто-подтверждения заказов.
Логика из плагина AutoTicket: SSO по golden_key → PHPSESSID поддержки → CSRF → POST тикета.
"""
from __future__ import annotations

import logging
import time
from typing import List, Tuple

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("backend.support_ticket")

SUPPORT_URL_NEW = "https://support.funpay.com/tickets/new/1"
SUPPORT_URL_CREATE = "https://support.funpay.com/tickets/create/1"
SSO_URL = "https://funpay.com/support/sso?return_to=%2Ftickets%2Fnew"


def _get_support_phpsessid(golden_key: str, user_agent: str, locale: str = "ru") -> str:
    """
    SSO: по golden_key получаем JWT с funpay.com, затем PHPSESSID на support.funpay.com.
    """
    session = requests.Session()
    session.headers.update({
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": f"{locale}-{locale.upper()},{locale};q=0.9,en;q=0.8",
        "referer": "https://funpay.com/",
        "user-agent": user_agent,
    })
    session.cookies.set("golden_key", golden_key, domain="funpay.com")
    if not golden_key or len(golden_key) < 20:
        raise ValueError("Недействительный golden_key")

    # Редирект на SSO
    r = session.get(SSO_URL, allow_redirects=False, timeout=20)
    if r.status_code == 403:
        raise ValueError("Доступ запрещён (403), проверьте golden_key")
    if r.status_code != 302:
        raise ValueError(f"Ожидался редирект 302, получен {r.status_code}")

    location = r.headers.get("Location", "")
    if "jwt=" not in location:
        raise ValueError("JWT не найден в редиректе SSO")
    jwt_token = location.split("jwt=")[1].split("&")[0]
    access_url = f"https://support.funpay.com/access/jwt?jwt={jwt_token}&return_to=%2Ftickets%2Fnew"
    r2 = session.get(access_url, allow_redirects=True, timeout=20)
    if r2.status_code not in (200, 302):
        raise ValueError(f"Ошибка доступа к поддержке: {r2.status_code}")

    for c in session.cookies:
        if c.name == "PHPSESSID" and ("support.funpay.com" in c.domain or ".support.funpay.com" in c.domain):
            logger.info("PHPSESSID поддержки получен через SSO")
            return c.value
    raise ValueError("PHPSESSID поддержки не найден после SSO")


def _get_csrf_token(session: requests.Session, phpsessid: str, user_agent: str, locale: str = "ru") -> str:
    """Загружает страницу создания тикета и извлекает CSRF-токен."""
    session.cookies.set("PHPSESSID", phpsessid, domain="support.funpay.com")
    session.headers.update({
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": f"{locale}-{locale.upper()},{locale};q=0.9",
        "referer": "https://support.funpay.com/tickets/new/1",
        "user-agent": user_agent,
    })
    r = session.get(SUPPORT_URL_NEW, timeout=20)
    r.raise_for_status()
    if r.status_code in (401, 403):
        raise ValueError("Не авторизован на support.funpay.com")
    soup = BeautifulSoup(r.text, "lxml")
    inp = soup.find("input", {"id": "ticket__token"})
    if inp and inp.get("value"):
        return inp["value"]
    attr = soup.find(attrs={"data-csrf-token": True})
    if attr and attr.get("data-csrf-token"):
        return attr["data-csrf-token"]
    for script in soup.find_all("script"):
        if "csrfToken" in str(script):
            part = str(script).split('csrfToken":"')
            if len(part) > 1:
                token = part[1].split('"')[0]
                if token:
                    return token
    raise ValueError("CSRF-токен не найден на странице тикета")


def send_support_ticket(
    golden_key: str,
    user_agent: str,
    username: str,
    order_ids: List[str],
    message_template: str,
    is_manual: bool = False,
    locale: str = "ru",
) -> Tuple[bool, str]:
    """
    Отправляет тикет в поддержку FunPay с просьбой подтвердить заказы.

    :param golden_key: ключ авторизации FunPay
    :param user_agent: User-Agent
    :param username: никнейм продавца (для формы)
    :param order_ids: список ID заказов (без #)
    :param message_template: шаблон сообщения; для авто — должен содержать {order_ids}, для ручного — {order_id}
    :param is_manual: если True, один заказ и подстановка {order_id}
    :param locale: ru/en/uk
    :return: (успех, id тикета или пустая строка)
    """
    if not order_ids:
        return False, ""
    order_id_first = order_ids[0].lstrip("#")

    try:
        phpsessid = _get_support_phpsessid(golden_key, user_agent, locale)
    except Exception as e:
        logger.error("Ошибка получения PHPSESSID поддержки: %s", e)
        return False, ""

    session = requests.Session()
    session.headers.update({
        "accept": "application/json, text/javascript, */*; q=0.01",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "origin": "https://support.funpay.com",
        "referer": "https://support.funpay.com/tickets/new/1",
        "user-agent": user_agent,
        "x-requested-with": "XMLHttpRequest",
        "accept-language": f"{locale}-{locale.upper()},{locale};q=0.9",
        "cookie": f"PHPSESSID={phpsessid}",
    })

    for attempt in range(3):
        try:
            csrf = _get_csrf_token(session, phpsessid, user_agent, locale)
        except Exception as e:
            logger.warning("Попытка %s получения CSRF: %s", attempt + 1, e)
            time.sleep(2)
            continue
        if is_manual:
            message = message_template.format(order_id=f"#{order_id_first}")
        else:
            order_ids_str = ", ".join(f"#{oid.lstrip('#')}" for oid in order_ids)
            message = message_template.format(order_ids=order_ids_str)

        body_html = f'<p dir="auto">{message}</p>'
        payload = {
            "ticket[fields][1]": username,
            "ticket[fields][2]": order_id_first,
            "ticket[fields][3]": "2",
            "ticket[fields][5]": "201",
            "ticket[comment][body_html]": body_html,
            "ticket[comment][attachments]": "",
            "ticket[_token]": csrf,
            "ticket[submit]": "Отправить",
        }

        try:
            r = session.post(SUPPORT_URL_CREATE, data=payload, timeout=20)
            r.raise_for_status()
            if r.status_code in (401, 403):
                logger.warning("Не авторизован при отправке тикета, попытка %s", attempt + 1)
                time.sleep(2)
                continue
            ticket_id = ""
            if r.url and "/tickets/" in r.url:
                ticket_id = r.url.rstrip("/").split("/")[-1]
            logger.info("Тикет в поддержку отправлен для заказов %s, ticket_id=%s", order_ids, ticket_id)
            return True, ticket_id
        except requests.RequestException as e:
            logger.warning("Ошибка POST тикета (попытка %s): %s", attempt + 1, e)
            time.sleep(2)
    return False, ""
