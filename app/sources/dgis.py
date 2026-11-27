"""2ГИС: поиск организаций через Places API (catalog.api.2gis.com).

Город → регион 2ГИС через Regions API (кэш в geo_cache бессрочно), заведения — /3.0/items
по тексту ниши в этом регионе, постранично. Каждый успешный запрос тратит лимит ключа
(демо-ключ — 1000 запросов на 30 дней), поэтому одинаковый запрос — не чаще раза в сутки
(кэш в source_fetches) и не больше DGIS_MAX_RESULTS заведений на пару «ниша + город».

Контакты (items.contact_groups) 2ГИС открывает только за отдельную плату. Пока их нет,
работает промежуточный режим: записи приходят с contacts_known = False, контакты для них
задача поиска берёт из OpenStreetMap (app/merge.py), а кого там нет — идут в категорию
«Проверить вручную» со ссылкой на карточку 2ГИС. Сайт из названия («700shin.ru, шиномонтаж»)
берётся сразу.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

import httpx

from app import config, contacts
from app.catalog import CITIES, City, Niche
from app.db import Jsonb, connect, fetch_all, fetch_one
from app.ratelimit import limiter
from app.sources.base import FoundPlace, SearchResult, Source, SourceError

log = logging.getLogger("klienty.2gis")
REFRESH_HOURS = 24
FIELDS = "items.point,items.address,items.contact_groups,items.dates,items.rubrics"

# тип контакта 2ГИС → (вид канала, подпись) как в app/contacts.py
_CHANNELS = {
    "vkontakte": ("social", "VK"), "odnoklassniki": ("social", "Одноклассники"),
    "instagram": ("social", "Instagram"), "facebook": ("social", "Facebook"),
    "youtube": ("social", "YouTube"), "twitter": ("social", "Twitter"), "tiktok": ("social", "TikTok"),
    "telegram": ("messenger", "Telegram"), "whatsapp": ("messenger", "WhatsApp"),
    "viber": ("messenger", "Viber"), "max": ("messenger", "MAX"),
    "email": ("email", "Почта"),
}


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(headers={"User-Agent": config.USER_AGENT, "Accept-Language": "ru"},
                             timeout=httpx.Timeout(30.0, connect=15.0))


def _count_request() -> None:
    """Учёт запросов к 2ГИС по дням: страница «Карты» показывает, сколько потрачено за 30 дней."""
    with connect() as c:
        c.execute("""INSERT INTO api_usage(source, day, requests) VALUES ('2gis', current_date, 1)
                     ON CONFLICT (source, day) DO UPDATE SET requests = api_usage.requests + 1""")


def used_last_30_days() -> int:
    row = fetch_one("""SELECT COALESCE(sum(requests), 0) AS n FROM api_usage
                       WHERE source = '2gis' AND day > current_date - 30""")
    return int(row["n"]) if row else 0


async def _get(path: str, params: dict) -> dict:
    """Один запрос к 2ГИС. Возвращает result; «ничего не найдено» — пустой result."""
    await limiter.wait("2gis")
    try:
        async with _client() as cl:
            r = await cl.get(config.DGIS_URL + path, params={**params, "key": config.DGIS_API_KEY})
    except httpx.TimeoutException as e:
        raise SourceError("2ГИС не ответил вовремя. Попробуй через пару минут.") from e
    except httpx.HTTPError as e:
        raise SourceError(f"2ГИС недоступен: {e.__class__.__name__}. Попробуй через пару минут.") from e
    try:
        data = r.json()
    except ValueError as e:
        raise SourceError(f"2ГИС вернул непонятный ответ (код {r.status_code}).") from e
    meta = data.get("meta") or {}
    code = meta.get("code", r.status_code)
    if code == 200:
        _count_request()
        return data.get("result") or {}
    if code == 404:  # у 2ГИС это «ничего не найдено», не ошибка
        return {}
    err = meta.get("error") or {}
    msg = err.get("message") or err.get("type") or f"код {code}"
    if code in (401, 403):
        raise SourceError(f"2ГИС не принял ключ: {msg}. Проверь DGIS_API_KEY в Render; демо-ключ живёт 30 дней.")
    if code == 429:
        raise SourceError("2ГИС: лимит запросов исчерпан (у демо-ключа — 1000 на 30 дней).")
    raise SourceError(f"2ГИС ответил ошибкой: {msg}.")


async def region_id(city: City) -> int:
    key = "2gis:" + city.query
    row = fetch_one("SELECT result FROM geo_cache WHERE query = %s", (key,))
    if row:
        return int(row["result"]["region_id"])
    res = await _get("/2.0/region/search", {"q": city.title})
    items = res.get("items") or []
    if not items:
        raise SourceError(f"2ГИС не знает город «{city.title}». Проверь название в app/catalog.py.")
    rid = int(items[0]["id"])
    with connect() as c:
        c.execute("""INSERT INTO geo_cache(query, result) VALUES (%s, %s)
                     ON CONFLICT (query) DO UPDATE SET result = EXCLUDED.result, fetched_at = now()""",
                  (key, Jsonb({"region_id": rid, "name": items[0].get("name", "")})))
    return rid


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


_DOMAIN_IN_NAME = re.compile(r"\b((?:\d+\s)?[a-z0-9][a-z0-9-]*\.(?:ru|рф|com|net|org|su|pro|online|site|store|shop|info|biz))\b", re.I)


def site_from_name(name: str) -> str:
    """«700shin.ru, шиномонтажная мастерская» → http://700shin.ru"""
    m = _DOMAIN_IN_NAME.search(name or "")
    return "http://" + re.sub(r"\s+", "", m.group(1)).lower() if m else ""  # «700 shin.ru» → 700shin.ru


def normalize(item: dict) -> FoundPlace | None:
    name = (item.get("name") or "").strip()
    if not name:
        return None
    raw_id = str(item.get("id", "")).split("_")[0]
    if not raw_id.isdigit():
        return None
    point = item.get("point") or {}
    addr = item.get("address") or {}
    street = housenumber = ""
    for comp in addr.get("components") or []:
        if comp.get("type") in ("street_number", "number"):
            street, housenumber = comp.get("street", ""), comp.get("number", "")
            break
    if not street and item.get("address_name"):
        street = item["address_name"]

    phones: list[str] = []
    website = ""
    channels: list[dict] = []
    for group in item.get("contact_groups") or []:
        for c in group.get("contacts") or []:
            kind, value = c.get("type", ""), (c.get("value") or c.get("text") or "").strip()
            if not value:
                continue
            if kind == "phone":
                p = contacts.normalize_phone(value)
                if p not in phones:
                    phones.append(p)
            elif kind == "website":
                url = value if value.startswith(("http://", "https://")) else c.get("url") or ("http://" + value)
                # сайт, который на самом деле VK или Taplink, — канал связи, как и в OSM
                _, site, ch = contacts.parse({"website": url})
                channels += [x for x in ch if x not in channels]
                if site and not website:
                    website = site
            elif kind in _CHANNELS:
                ck, label = _CHANNELS[kind]
                url = c.get("url") or (value if value.startswith("http") else "")
                if kind == "email":
                    url = "mailto:" + value
                if not any(x["label"] == label and x["value"] == value for x in channels):
                    channels.append({"kind": ck, "label": label, "value": c.get("text") or value, "url": url})
    dates = item.get("dates") or {}
    known = "contact_groups" in item
    if not known and not website:
        website = site_from_name(name)
    return FoundPlace(source="2gis", ext_type="branch", ext_id=int(raw_id), name=name,
                      street=street, housenumber=housenumber, lat=point.get("lat"), lon=point.get("lon"),
                      phones=phones, website=website, channels=channels,
                      updated_at=_parse_dt(dates.get("updated_at") or dates.get("created_at")),
                      contacts_known=known)


class DgisSource(Source):
    id = "2gis"
    title = "2ГИС"
    checkable = True
    attribution = "© 2ГИС"

    @property
    def available(self) -> bool:  # type: ignore[override]
        return bool(config.DGIS_API_KEY)

    @property
    def note(self) -> str:  # type: ignore[override]
        return "Ключ задан" if self.available else "Нужен ключ (DGIS_API_KEY в Render)"

    unavailable_reason = "в Render не задан ключ DGIS_API_KEY, см. README"

    def object_url(self, ext_type: str, ext_id: int) -> str:
        return f"https://2gis.ru/firm/{ext_id}"

    page_size = config.DGIS_PAGE_SIZE

    async def _page(self, niche: Niche, rid: int, page: int) -> dict:
        params = {"q": niche.search_text, "region_id": rid, "type": "branch", "fields": FIELDS, "page": page}
        try:
            return await _get("/3.0/items", {**params, "page_size": self.page_size})
        except SourceError as e:
            # демо-ключ отдаёт не больше 10 за запрос: «Length of parameter 'page_size' should be from 1 to 10»
            if "page_size" not in str(e) or self.page_size <= 10:
                raise
            log.info("2gis: page_size %s refused, switching to 10", self.page_size)
            DgisSource.page_size = 10
            return await _get("/3.0/items", {**params, "page_size": 10})

    async def search(self, niche: Niche, city: City) -> SearchResult:
        fresh = fetch_one("""SELECT place_ids FROM source_fetches WHERE source = '2gis' AND niche = %s AND city = %s
                             AND fetched_at > now() - make_interval(hours => %s)""", (niche.id, city.id, REFRESH_HOURS))
        if fresh is not None:
            from app.sources.osm import _from_row  # одна функция «строка базы → FoundPlace»
            rows = fetch_all("SELECT * FROM places WHERE id = ANY(%s)", (fresh["place_ids"],))
            return SearchResult([_from_row(r) for r in rows], None, from_cache=True)

        rid = await region_id(city)
        places: list[FoundPlace] = []
        total = None
        page = 0
        note = ""
        while len(places) < config.DGIS_MAX_RESULTS:
            page += 1
            try:
                res = await self._page(niche, rid, page)
            except SourceError as e:
                # демо-ключ: «Length of parameter 'page' should be from 1 to 5» — дальше страниц нет
                if "'page'" not in str(e) or page == 1:
                    raise
                note = (f"2ГИС с этим ключом отдаёт не больше {len(places)} заведений на запрос "
                        f"(«{niche.title} · {city.title}»: всего в 2ГИС {total}). Платный ключ снимает ограничение.")
                log.info("2gis: page limit reached at page %s: %s", page, e)
                break
            items = res.get("items") or []
            total = res.get("total", total)
            for it in items:
                p = normalize(it)
                if p:
                    places.append(p)
            if not items or len(items) < self.page_size or (total is not None and page * self.page_size >= total):
                break
        if total and total > len(places):
            log.info("2gis: %s in %s has %s results, took first %s", niche.id, city.id, total, len(places))
        return SearchResult(places, None, from_cache=False, data_at=None, note=note)

    async def check(self) -> dict:
        if not self.available:
            return {"ok": False, "message": "Ключ не задан: добавь DGIS_API_KEY в Render → Environment."}
        city = next((c for c in CITIES if c.id == "volgograd"), CITIES[0])
        from app.catalog import NICHES
        try:
            rid = await region_id(city)
            res = await _get("/3.0/items", {"q": NICHES[0].search_text, "region_id": rid, "type": "branch",
                                            "fields": FIELDS, "page_size": 5})
        except SourceError as e:
            return {"ok": False, "message": str(e)}
        items = res.get("items") or []
        if not items:
            return {"ok": True, "message": f"Ключ работает, но по запросу «{NICHES[0].search_text}» в городе {city.title} "
                                           "ничего не нашлось. Проверить контакты не на чем."}
        with_contacts = sum(1 for it in items if "contact_groups" in it)
        used = used_last_30_days()
        if with_contacts == 0:
            return {"ok": True, "message": f"Ключ работает и находит заведения (в пробном запросе: {len(items)}), но контакты "
                                           "(телефон, сайт, соцсети) не отдаёт — их 2ГИС подключает за отдельную плату. "
                                           "Работает промежуточный режим: контакты берутся из OpenStreetMap, а кого там нет — "
                                           "в группе «Проверить вручную» со ссылкой на 2ГИС. "
                                           f"Запросов к 2ГИС за 30 дней: {used} (у демо-ключа лимит 1000)."}
        sample = normalize(items[0])
        what = []
        if sample and sample.phones:
            what.append("телефон")
        if sample and sample.website:
            what.append("сайт")
        if sample and sample.channels:
            what.append(", ".join(sorted({c['label'] for c in sample.channels})))
        return {"ok": True, "message": f"Ключ работает, контакты отдаются ({with_contacts} из {len(items)} заведений). "
                                       f"Пример: «{items[0].get('name')}» — {', '.join(what) or 'контактов нет'}. "
                                       f"Запросов к 2ГИС за 30 дней: {used} (у демо-ключа лимит 1000)."}
