"""Разбор контактов из тегов OpenStreetMap: телефоны, сайт, соцсети, мессенджеры, онлайн-запись.

Ссылка на VK или Instagram в теге website — это не сайт, а соцсеть: такие адреса уходят в каналы.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

# kind: social / messenger / booking. label — как показать владельцу.
_CHANNEL_TAGS: dict[str, tuple[str, str, str]] = {
    # тег: (kind, label, шаблон ссылки для короткого имени)
    "contact:vk": ("social", "VK", "https://vk.com/{}"),
    "vk": ("social", "VK", "https://vk.com/{}"),
    "contact:ok": ("social", "Одноклассники", "https://ok.ru/{}"),
    "contact:odnoklassniki": ("social", "Одноклассники", "https://ok.ru/{}"),
    "contact:instagram": ("social", "Instagram", "https://instagram.com/{}"),
    "instagram": ("social", "Instagram", "https://instagram.com/{}"),
    "contact:facebook": ("social", "Facebook", "https://facebook.com/{}"),
    "facebook": ("social", "Facebook", "https://facebook.com/{}"),
    "contact:youtube": ("social", "YouTube", "https://youtube.com/{}"),
    "contact:tiktok": ("social", "TikTok", "https://tiktok.com/@{}"),
    "contact:telegram": ("messenger", "Telegram", "https://t.me/{}"),
    "telegram": ("messenger", "Telegram", "https://t.me/{}"),
    "contact:whatsapp": ("messenger", "WhatsApp", "https://wa.me/{}"),
    "whatsapp": ("messenger", "WhatsApp", "https://wa.me/{}"),
    "contact:viber": ("messenger", "Viber", ""),
    "viber": ("messenger", "Viber", ""),
    "contact:max": ("messenger", "MAX", ""),
    "booking": ("booking", "Онлайн-запись", ""),
    "website:booking": ("booking", "Онлайн-запись", ""),
    "contact:booking": ("booking", "Онлайн-запись", ""),
    "reservation:website": ("booking", "Онлайн-запись", ""),
}

# Домены, которые в теге website означают соцсеть, мессенджер или сервис записи, а не свой сайт.
_DOMAIN_CHANNELS: list[tuple[str, str, str]] = [
    ("vk.com", "social", "VK"), ("vk.ru", "social", "VK"), ("ok.ru", "social", "Одноклассники"),
    ("instagram.com", "social", "Instagram"), ("facebook.com", "social", "Facebook"),
    ("youtube.com", "social", "YouTube"), ("tiktok.com", "social", "TikTok"), ("dzen.ru", "social", "Дзен"),
    ("t.me", "messenger", "Telegram"), ("telegram.me", "messenger", "Telegram"),
    ("wa.me", "messenger", "WhatsApp"), ("whatsapp.com", "messenger", "WhatsApp"),
    ("taplink.cc", "social", "Taplink"), ("taplink.ws", "social", "Taplink"),
    ("dikidi.net", "booking", "Онлайн-запись"), ("dikidi.ru", "booking", "Онлайн-запись"),
    ("yclients.com", "booking", "Онлайн-запись"), ("n.yclients.com", "booking", "Онлайн-запись"),
    ("sonline.su", "booking", "Онлайн-запись"),
]
# Каталоги и карты: это не сайт заведения и не канал связи.
_CATALOG_DOMAINS = ("2gis.ru", "2gis.com", "yandex.ru", "yandex.com", "google.com", "avito.ru",
                    "zoon.ru", "flamp.ru", "yell.ru", "goo.gl")


def _split(value: str) -> list[str]:
    return [v.strip() for v in re.split(r"[;,]\s*(?=\S)", value or "") if v.strip()]


def _host(url: str) -> str:
    if "://" not in url:
        url = "http://" + url
    try:
        return (urlsplit(url).hostname or "").lower().removeprefix("www.").removeprefix("m.")
    except ValueError:
        return ""


def _matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def _as_url(value: str, template: str) -> str:
    v = value.strip()
    if v.startswith(("http://", "https://")):
        return v
    if re.match(r"^[\w.-]+\.[a-z]{2,}(/|$)", v, re.I):
        return "https://" + v
    if template:
        return template.format(v.lstrip("@").lstrip("+"))
    return ""


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits[0] in "78":
        return f"+7 {digits[1:4]} {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"
    return value.strip()


def parse(tags: dict[str, str]) -> tuple[list[str], str, list[dict]]:
    """Возвращает (телефоны, свой сайт или "", каналы)."""
    phones: list[str] = []
    for key in ("phone", "contact:phone", "contact:mobile", "mobile", "phone:mobile"):
        for p in _split(tags.get(key, "")):
            n = normalize_phone(p)
            if n not in phones:
                phones.append(n)

    channels: list[dict] = []

    def add(kind: str, label: str, value: str, url: str) -> None:
        if not any(c["label"] == label and c["value"] == value for c in channels):
            channels.append({"kind": kind, "label": label, "value": value, "url": url})

    for key, (kind, label, template) in _CHANNEL_TAGS.items():
        for v in _split(tags.get(key, "")):
            add(kind, label, v, _as_url(v, template))

    website = ""
    for key in ("website", "contact:website", "url"):
        for v in _split(tags.get(key, "")):
            host = _host(v)
            if not host:
                continue
            hit = next(((k, l) for d, k, l in _DOMAIN_CHANNELS if _matches(host, d)), None)
            if hit:
                add(hit[0], hit[1], v, _as_url(v, ""))
            elif any(_matches(host, d) for d in _CATALOG_DOMAINS):
                continue
            elif not website:
                website = v if v.startswith(("http://", "https://")) else "http://" + v

    for key in ("email", "contact:email"):
        for v in _split(tags.get(key, "")):
            add("email", "Почта", v, "mailto:" + v)
    return phones, website, channels


def channel_kinds(channels: list[dict]) -> list[str]:
    """Разные каналы связи кроме телефона и почты: соцсети, мессенджеры, запись (по названию)."""
    out: list[str] = []
    for c in channels:
        if c["kind"] in ("social", "messenger", "booking") and c["label"] not in out:
            out.append(c["label"])
    return out
