"""Проверка сайта заведения: только признаки, содержимое не сохраняется.

Читается не больше MAX_BYTES главной страницы; из неё берутся признаки, сам текст выбрасывается.
К одному домену — не чаще одного запроса в секунду (app/ratelimit.py).
"""
from __future__ import annotations

import re
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx

from app import config
from app.ratelimit import limiter

TIMEOUT = 10.0
MAX_BYTES = 2_000_000
MAX_LINKS_TO_TEST = 3
_SKIP_EXT = re.compile(r"\.(jpe?g|png|gif|webp|svg|pdf|docx?|xlsx?|zip|rar|mp4|mp3)$", re.I)


class _Scan(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.viewport = False
        self.links: list[str] = []
        self.text_len = 0
        self.texts: list[str] = []
        self.in_footer = 0
        self.footer_text: list[str] = []
        self._skip = 0
        self.spa_root = False
        self.scripts = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta" and (a.get("name") or "").lower() == "viewport":
            self.viewport = True
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])
        elif tag in ("script", "style", "noscript", "template"):
            self._skip += 1
            if tag == "script":
                self.scripts += 1
        elif tag == "footer":
            self.in_footer += 1
        if tag == "div" and a.get("id") in ("root", "app", "__next", "__nuxt"):
            self.spa_root = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "template") and self._skip:
            self._skip -= 1
        elif tag == "footer" and self.in_footer:
            self.in_footer -= 1

    def handle_data(self, data):
        if self._skip:
            return
        s = data.strip()
        if not s:
            return
        self.text_len += len(s)
        self.texts.append(s)
        if self.in_footer:
            self.footer_text.append(s)


def _years(text: str) -> list[int]:
    this_year = date.today().year
    return [int(y) for y in re.findall(r"(?<!\d)(19[89]\d|20\d\d)(?!\d)", text) if 1990 <= int(y) <= this_year]


def footer_year(scan: _Scan) -> int | None:
    """Последний год из подвала: <footer>, а если его нет — из конца страницы рядом со знаком ©."""
    text = " ".join(scan.footer_text)
    if not text:
        tail = " ".join(scan.texts)[-1500:]
        m = re.findall(r"(?:©|&copy;|\(c\)|copyright)[^\n]{0,40}", tail, re.I)
        text = " ".join(m)
    ys = _years(text)
    return max(ys) if ys else None


def _internal_links(base: str, hrefs: list[str]) -> list[str]:
    host = urlsplit(base).hostname
    seen: list[str] = []
    for h in hrefs:
        if h.startswith(("#", "mailto:", "tel:", "javascript:", "whatsapp:", "viber:")):
            continue
        u = urljoin(base, h).split("#")[0]
        p = urlsplit(u)
        if p.scheme not in ("http", "https") or p.hostname != host or _SKIP_EXT.search(p.path):
            continue
        if p.path.rstrip("/") == urlsplit(base).path.rstrip("/") and not p.query:
            continue
        if u not in seen:
            seen.append(u)
    return seen


async def _get(cl: httpx.AsyncClient, url: str) -> tuple[httpx.Response, bytes]:
    await limiter.wait("site:" + (urlsplit(url).hostname or url))
    async with cl.stream("GET", url) as r:
        body = b""
        if "html" in r.headers.get("content-type", "html"):
            async for chunk in r.aiter_bytes():
                body += chunk
                if len(body) >= MAX_BYTES:
                    break
        return r, body


async def check(url: str) -> dict:
    """Возвращает признаки сайта. Ошибка сети — это статус «не открывается», а не «сайта нет»."""
    result: dict = {"url": url, "opened": False, "status_code": None, "final_url": None, "error": "",
                    "https": None, "viewport": None, "footer_year": None, "text_len": None,
                    "internal_links": None, "broken_links": None, "tested_links": 0, "js_app": False}
    async with httpx.AsyncClient(headers={"User-Agent": config.USER_AGENT}, follow_redirects=True,
                                 timeout=TIMEOUT, max_redirects=8, verify=True) as cl:
        try:
            r, body = await _get(cl, url)
        except httpx.ConnectError as e:
            if "CERTIFICATE" in str(e).upper() or "SSL" in str(e).upper():
                result["error"] = "ошибка сертификата https"
            else:
                result["error"] = "не удалось подключиться"
            return result
        except httpx.TimeoutException:
            result["error"] = "не ответил за 10 секунд"
            return result
        except httpx.TooManyRedirects:
            result["error"] = "бесконечная переадресация"
            return result
        except (httpx.HTTPError, ValueError) as e:
            result["error"] = f"ошибка: {e.__class__.__name__}"
            return result
        result["status_code"] = r.status_code
        result["final_url"] = str(r.url)
        result["https"] = r.url.scheme == "https"
        if r.status_code >= 400:
            result["error"] = f"сервер ответил кодом {r.status_code}"
            return result
        result["opened"] = True
        scan = _Scan()
        try:
            scan.feed(body.decode(r.encoding or "utf-8", errors="replace"))
        except Exception:  # кривой HTML: берём то, что успели разобрать
            pass
        result["viewport"] = scan.viewport
        result["footer_year"] = footer_year(scan)
        result["text_len"] = scan.text_len
        result["js_app"] = scan.spa_root and scan.text_len < 300
        links = _internal_links(str(r.url), scan.links)
        result["internal_links"] = len(links)
        broken = 0
        for link in links[:MAX_LINKS_TO_TEST]:
            try:
                lr, _ = await _get(cl, link)
                bad = lr.status_code >= 400
            except (httpx.HTTPError, ValueError):
                bad = True
            broken += bad
            result["tested_links"] += 1
        result["broken_links"] = broken
        del body, scan  # содержимое чужого сайта дальше не живёт
    return result
