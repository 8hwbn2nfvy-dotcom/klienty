"""Вход: один пользователь, пароль сверяется с хэшем из PASSWORD_HASH.

Сессия — подписанная cookie на 30 дней. Защита от перебора: 5 ошибок за 5 минут с одного адреса → пауза.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time

from fastapi import HTTPException, Request

from app import config
from app.passwords import clean, looks_valid, verify_password

COOKIE = "klienty_session"
TTL = 60 * 60 * 24 * 30
_failures: dict[str, list[float]] = {}


def configured() -> bool:
    return looks_valid(config.PASSWORD_HASH)


def _sign(payload: str) -> str:
    return hmac.new(config.SESSION_SECRET, payload.encode(), hashlib.sha256).hexdigest()


def make_token() -> str:
    payload = f"owner|{int(time.time()) + TTL}"
    return base64.urlsafe_b64encode(f"{payload}|{_sign(payload)}".encode()).decode()


def token_ok(token: str | None) -> bool:
    if not token or not configured():
        return False
    try:
        user, exp, sig = base64.urlsafe_b64decode(token.encode()).decode().split("|")
    except Exception:  # мусор в cookie = не вошёл
        return False
    return hmac.compare_digest(sig, _sign(f"{user}|{exp}")) and int(exp) > time.time()


def is_logged_in(request: Request) -> bool:
    return token_ok(request.cookies.get(COOKIE))


def require(request: Request) -> None:
    if not is_logged_in(request):
        raise HTTPException(401, "Нужно войти заново.")


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def check_password(password: str, ip: str) -> None:
    if not configured():
        raise HTTPException(503, "Пароль ещё не задан: в Render нет переменной PASSWORD_HASH или она с ошибкой.")
    now = time.time()
    recent = [t for t in _failures.get(ip, []) if t > now - 300]
    if len(recent) >= 5:
        raise HTTPException(429, "Слишком много неверных попыток. Подожди 5 минут.")
    if not verify_password(clean(password), config.PASSWORD_HASH):
        _failures[ip] = recent + [now]
        raise HTTPException(401, "Неверный пароль.")
    _failures.pop(ip, None)
