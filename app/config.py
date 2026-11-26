"""Настройки из переменных окружения. Значения читаются один раз при старте."""
from __future__ import annotations

import hashlib
import os

VERSION = "1.0.0"
REPO_URL = "https://github.com/8hwbn2nfvy-dotcom/klienty"
# Внешние сервисы (Overpass, Nominatim, сайты заведений) видят этот User-Agent.
USER_AGENT = f"KlientyAgent/{VERSION} (+{REPO_URL})"


def _env(name: str, default: str = "") -> str:
    # На iPad при вставке часто прилетают пробелы и невидимые символы по краям.
    return (os.environ.get(name) or default).strip().strip("​﻿\"'").strip()


DATABASE_URL = _env("DATABASE_URL")
PASSWORD_HASH = _env("PASSWORD_HASH")
OVERPASS_URL = _env("OVERPASS_URL", "https://overpass-api.de/api/interpreter")
NOMINATIM_URL = _env("NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")

# Подпись cookie входа. Если отдельный секрет не задан, он выводится из хэша пароля:
# смена пароля сразу закрывает все старые входы.
SESSION_SECRET = (_env("SESSION_SECRET") or hashlib.sha256(
    ("klienty-session|" + PASSWORD_HASH).encode()).hexdigest()).encode()
