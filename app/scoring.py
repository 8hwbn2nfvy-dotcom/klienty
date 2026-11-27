"""Категория и оценка «купит ли сайт» (0–100). Все пороги и баллы — константы ниже.

Пороги стартовые: проверить на первых 10 реальных записях и подправить 🟡.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.contacts import channel_kinds

CATEGORIES = {"site": "Создание сайта", "card": "Создание визитки", "upgrade": "Доработка",
              "manual": "Проверить вручную"}
SCORED = ("site", "card", "upgrade")  # «Проверить вручную» без оценки: данных для неё нет

# --- пороги ---
MIN_CHANNELS_FOR_SITE = 2     # сайта нет, но каналов связи столько или больше → «создание сайта»
OLD_FOOTER_YEARS = 3          # год в подвале старше стольких лет → признак старого сайта
SHORT_PAGE_CHARS = 600        # меньше стольких символов текста на главной → «очень короткая»
MIN_OLD_SIGNS_FOR_UPGRADE = 1 # столько признаков старого сайта достаточно для «доработки»
STALE_RECORD_YEARS = 3        # запись на карте не правили и не проверяли столько лет → «проверь, работает ли»

# --- баллы ---
BASE = {"site": 55, "card": 40, "upgrade": 35}
PER_EXTRA_CHANNEL = 6         # за каждый канал сверх порога
MAX_CHANNEL_BONUS = 18
HAS_BOOKING = 8               # есть онлайн-запись → бизнес уже ищет клиентов онлайн
HAS_PHONE = 5
HAS_ADDRESS = 4
NO_CONTACTS_AT_ALL = -25      # не с кем связаться
STALE_RECORD = -15            # данные на карте старые: заведение могло закрыться или сменить телефон
SITE_SIGNS = {
    "down": ("сайт не открывается", 35),
    "no_https": ("нет https", 10),
    "no_viewport": ("нет мобильной версии (meta viewport)", 15),
    "old_year": ("год в подвале старше {years} лет", 12),
    "short": ("очень короткая главная", 8),
    "one_page": ("одна страница", 6),
    "broken": ("битые ссылки", 10),
}


def site_signs(check: dict | None) -> list[tuple[str, str, int]]:
    """Признаки старой визитки: [(код, подпись, баллы)]."""
    if not check:
        return []
    if check.get("protected"):
        return []  # сайт работает и защищён от роботов — признаков старой визитки не видно
    if not check.get("opened"):
        label, pts = SITE_SIGNS["down"]
        return [("down", f"{label} ({check.get('error') or 'ошибка'})", pts)]
    out = []

    def add(code: str, **fmt) -> None:
        label, pts = SITE_SIGNS[code]
        out.append((code, label.format(**fmt), pts))

    if check.get("https") is False:
        add("no_https")
    if check.get("viewport") is False:
        add("no_viewport")
    year = check.get("footer_year")
    if year and year < date.today().year - OLD_FOOTER_YEARS:
        out.append(("old_year", f"год в подвале {year}", SITE_SIGNS["old_year"][1]))
    if not check.get("js_app"):
        if check.get("text_len") is not None and check["text_len"] < SHORT_PAGE_CHARS:
            add("short")
        if check.get("internal_links") == 0:
            add("one_page")
    if check.get("broken_links"):
        add("broken")
    return out


def is_stale(place: dict) -> bool:
    """Запись на карте давно не обновлялась. Нет даты — тоже считаем старой: проверить не по чему."""
    d = place.get("source_updated_at")
    return d is None or d < datetime.now(timezone.utc) - timedelta(days=365 * STALE_RECORD_YEARS)


def score(place: dict) -> tuple[str | None, int, list[dict]]:
    """Возвращает (категория или None, оценка 0–100, разбивка [{label, points}])."""
    if place.get("contacts_known") is False and not place.get("website"):
        return "manual", 0, [{"label": "карта не отдала контакты — открой карточку в 2ГИС: есть ли сайт, телефон, соцсети",
                              "points": 0}]
    parts: list[dict] = []
    kinds = channel_kinds(place.get("channels") or [])
    phones = place.get("phones") or []
    has_booking = any(c["kind"] == "booking" for c in place.get("channels") or [])

    if place.get("website"):
        signs = site_signs(place.get("site_check"))
        if place.get("site_check") is None:
            return None, 0, [{"label": "сайт ещё не проверен", "points": 0}]
        if (place.get("site_check") or {}).get("protected"):
            return None, 0, [{"label": "сайт защищён от автоматической проверки — скорее всего крупный современный сайт",
                              "points": 0}]
        if len(signs) < MIN_OLD_SIGNS_FOR_UPGRADE:
            return None, 0, [{"label": "сайт в порядке: признаков старой визитки нет", "points": 0}]
        category = "upgrade"
        parts.append({"label": "есть сайт, нужна доработка", "points": BASE["upgrade"]})
        parts += [{"label": label, "points": pts} for _, label, pts in signs]
    elif len(kinds) >= MIN_CHANNELS_FOR_SITE:
        category = "site"
        parts.append({"label": f"сайта нет, каналов связи: {len(kinds)} ({', '.join(kinds)})", "points": BASE["site"]})
        extra = min((len(kinds) - MIN_CHANNELS_FOR_SITE) * PER_EXTRA_CHANNEL, MAX_CHANNEL_BONUS)
        if extra:
            parts.append({"label": "много каналов связи", "points": extra})
    else:
        category = "card"
        label = "сайта нет, " + (f"есть {kinds[0]}" if kinds else "только телефон" if phones else "контактов нет")
        parts.append({"label": label, "points": BASE["card"]})

    if has_booking:
        parts.append({"label": "есть онлайн-запись", "points": HAS_BOOKING})
    if phones:
        parts.append({"label": "есть телефон", "points": HAS_PHONE})
    elif not kinds and category != "upgrade":  # у кого есть сайт, с тем связаться можно
        parts.append({"label": "нет ни телефона, ни соцсетей", "points": NO_CONTACTS_AT_ALL})
    if place.get("street"):
        parts.append({"label": "указан адрес", "points": HAS_ADDRESS})
    if is_stale(place):
        d = place.get("source_updated_at")
        when = f"с {d.year} года" if d else "давно (дата неизвестна)"
        parts.append({"label": f"запись на карте не обновлялась {when} — проверь, работает ли", "points": STALE_RECORD})

    total = max(0, min(100, sum(p["points"] for p in parts)))
    return category, total, parts
