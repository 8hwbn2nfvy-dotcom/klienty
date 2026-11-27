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
OVERPASS_MAX_LAG_DAYS = 7
# 2ГИС: ключ из Менеджера Платформы (platform.2gis.ru). Пусто — 2ГИС нельзя включить.
DGIS_API_KEY = _env("DGIS_API_KEY")
DGIS_URL = _env("DGIS_URL", "https://catalog.api.2gis.com")
DGIS_PAGE_SIZE = 50   # больше 2ГИС не отдаёт за один запрос
DGIS_MAX_PAGES = 10   # не больше 500 заведений на пару «ниша + город»: бережём лимит запросов
PASSWORD_HASH = _env("PASSWORD_HASH")
# Серверы Overpass по порядку: если первый не отвечает или его данные старше
# OVERPASS_MAX_LAG_DAYS, агент пробует следующий. maps.mail.ru первым: с Render
# overpass-api.de не подключается, а kumi.systems часто отвечает 504.
# Своё значение — адреса через запятую.
OVERPASS_URLS = [u.strip() for u in _env(
    "OVERPASS_URL",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter,"
    "https://overpass.private.coffee/api/interpreter,"
    "https://overpass-api.de/api/interpreter,"
    "https://overpass.kumi.systems/api/interpreter",
).split(",") if u.strip()]
NOMINATIM_URL = _env("NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")

# Подпись cookie входа. Если отдельный секрет не задан, он выводится из хэша пароля:
# смена пароля сразу закрывает все старые входы.
SESSION_SECRET = (_env("SESSION_SECRET") or hashlib.sha256(
    ("klienty-session|" + PASSWORD_HASH).encode()).hexdigest()).encode()
