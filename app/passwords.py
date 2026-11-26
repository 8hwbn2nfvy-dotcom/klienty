"""Пароль: хранится только хэш (scrypt из стандартной библиотеки, с солью)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

N, R, P = 2 ** 14, 8, 1


def clean(s: str) -> str:
    return (s or "").strip().strip("​﻿").strip()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=N, r=R, p=P, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(h).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        kind, salt, h = stored.split("$")
        if kind != "scrypt":
            return False
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=N, r=R, p=P, dklen=32)
        return hmac.compare_digest(got, base64.b64decode(h))
    except (ValueError, TypeError):
        return False


def looks_valid(stored: str) -> bool:
    try:
        kind, salt, h = stored.split("$")
        return kind == "scrypt" and len(base64.b64decode(salt)) == 16 and len(base64.b64decode(h)) == 32
    except (ValueError, TypeError):
        return False
