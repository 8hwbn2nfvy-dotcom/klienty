"""OpenStreetMap: город через Nominatim, заведения через Overpass API.

Правила сервисов: не чаще 1 запроса в секунду, ответы кэшируются, одинаковый запрос
к Overpass — не чаще раза в сутки (кэш в таблице source_fetches, сами записи — в places).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx

from app import config, contacts
from app.catalog import City, Niche
from app.db import Jsonb, connect, fetch_all, fetch_one
from app.ratelimit import limiter
from app.sources.base import FoundPlace, SearchResult, Source, SourceError

log = logging.getLogger("klienty.osm")
REFRESH_HOURS = 24
_AREA_OFFSET = {"relation": 3_600_000_000, "way": 2_400_000_000}


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(headers={"User-Agent": config.USER_AGENT, "Accept-Language": "ru"},
                             timeout=httpx.Timeout(90.0, connect=15.0))


async def geocode(city: City) -> dict:
    """Область города в OSM: {area_id, lat, lon, name}. Результат хранится в geo_cache бессрочно."""
    row = fetch_one("SELECT result FROM geo_cache WHERE query = %s", (city.query,))
    if row:
        return row["result"]
    await limiter.wait("nominatim")
    try:
        async with _client() as cl:
            r = await cl.get(config.NOMINATIM_URL, params={
                "q": city.query, "format": "jsonv2", "limit": 5, "countrycodes": "ru"})
    except httpx.HTTPError as e:
        raise SourceError(f"Nominatim (поиск города) не отвечает: {e.__class__.__name__}. Попробуй позже.") from e
    if r.status_code != 200:
        raise SourceError(f"Nominatim (поиск города) ответил кодом {r.status_code}. Попробуй позже.")
    hit = next((h for h in r.json() if h.get("osm_type") in _AREA_OFFSET
                and h.get("addresstype") in ("city", "town", "village", "municipality", "county")), None)
    hit = hit or next((h for h in r.json() if h.get("osm_type") in _AREA_OFFSET), None)
    if not hit:
        raise SourceError(f"Nominatim не нашёл границы города «{city.title}». Проверь строку query в app/catalog.py.")
    result = {"area_id": _AREA_OFFSET[hit["osm_type"]] + int(hit["osm_id"]),
              "lat": float(hit["lat"]), "lon": float(hit["lon"]), "name": hit.get("display_name", "")}
    with connect() as c:
        c.execute("""INSERT INTO geo_cache(query, result) VALUES (%s, %s)
                     ON CONFLICT (query) DO UPDATE SET result = EXCLUDED.result, fetched_at = now()""",
                  (city.query, Jsonb(result)))
    return result


def build_query(niche: Niche, area_id: int) -> str:
    parts = "\n".join(f"  nwr{f}(area.a);" for f in niche.osm_filters)
    # meta — чтобы знать, когда запись правили последний раз
    return f"[out:json][timeout:90];\narea(id:{area_id})->.a;\n(\n{parts}\n);\nout center meta;"


_CLOSED_HOURS = re.compile(r"^\s*(closed|off)\s*$", re.I)
_DATE = re.compile(r"(\d{4})-(\d{2})(?:-(\d{2}))?")


def _parse_date(value: str) -> datetime | None:
    m = _DATE.search(value or "")
    if not m:
        return None
    try:
        return datetime(int(m[1]), int(m[2]), int(m[3] or 1), tzinfo=timezone.utc)
    except ValueError:
        return None


def is_closed(tags: dict[str, str]) -> bool:
    """Заведение отмечено на карте как закрытое."""
    if _CLOSED_HOURS.match(tags.get("opening_hours", "")):
        return True
    if any(tags.get(k) for k in ("end_date", "disused", "abandoned")):
        return True
    return bool(re.search(r"\bзакрыт", tags.get("name", "") + " " + tags.get("note", ""), re.I))


def updated_at(el: dict) -> datetime | None:
    """Последняя правка записи или последняя отметка «проверено на месте» — что новее."""
    tags = el.get("tags") or {}
    dates = [_parse_date(el.get("timestamp", ""))]
    dates += [_parse_date(tags.get(k, "")) for k in ("check_date", "survey:date", "check_date:opening_hours")]
    dates = [d for d in dates if d]
    return max(dates) if dates else None


def normalize(el: dict) -> FoundPlace | None:
    tags = el.get("tags") or {}
    name = (tags.get("name") or tags.get("brand") or "").strip()
    if not name:
        return None  # без названия владельцу некого искать
    if is_closed(tags):
        return None  # на карте отмечено закрытым
    lat = el.get("lat", (el.get("center") or {}).get("lat"))
    lon = el.get("lon", (el.get("center") or {}).get("lon"))
    phones, website, channels = contacts.parse(tags)
    return FoundPlace(source="osm", ext_type=el["type"], ext_id=int(el["id"]), name=name,
                      street=tags.get("addr:street", ""), housenumber=tags.get("addr:housenumber", ""),
                      lat=lat, lon=lon, phones=phones, website=website, channels=channels,
                      updated_at=updated_at(el))


async def _overpass(query: str) -> tuple[list[dict], datetime | None]:
    """Пробует серверы Overpass по очереди. Возвращает (объекты, дата данных сервера).

    Ответ сервера, чьи данные старше OVERPASS_MAX_LAG_DAYS, откладывается про запас:
    агент спрашивает следующий сервер и берёт самые свежие данные из полученных.
    Ошибка — только если не ответил ни один."""
    problems: list[str] = []
    stale: tuple[list[dict], datetime | None] | None = None
    async with _client() as cl:
        for url in config.OVERPASS_URLS:
            host = urlsplit(url).hostname or url
            await limiter.wait("overpass:" + host)
            try:
                r = await cl.post(url, data={"data": query})
            except httpx.TimeoutException:
                problems.append(f"{host}: не ответил вовремя")
                continue
            except httpx.HTTPError as e:
                problems.append(f"{host}: {e.__class__.__name__}")
                continue
            if r.status_code != 200:
                problems.append(f"{host}: код {r.status_code}" + (" (просит подождать)" if r.status_code == 429 else ""))
                continue
            try:
                data = r.json()
            except ValueError:
                problems.append(f"{host}: непонятный ответ (не JSON)")
                continue
            base = _parse_base(data)
            got = (data.get("elements", []), base)
            lag = (datetime.now(timezone.utc) - base).days if base else None
            log.info("overpass %s answered, data at %s", host, base)
            if lag is not None and lag > config.OVERPASS_MAX_LAG_DAYS:
                problems.append(f"{host}: данные устарели ({lag} дн.)")
                if stale is None or (stale[1] and base and base > stale[1]):
                    stale = got
                continue
            return got
    if stale is not None:
        return stale  # свежее никто не дал — лучше старые данные, чем ничего; дата видна на странице
    log.warning("overpass failed on all servers: %s", "; ".join(problems))
    raise SourceError("Ни один сервер Overpass (поиск по карте OSM) не ответил: " + "; ".join(problems)
                      + ". Попробуй через пару минут.")


def _parse_base(data: dict) -> datetime | None:
    raw = (data.get("osm3s") or {}).get("timestamp_osm_base", "")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")) if raw else None
    except ValueError:
        return None


class OsmSource(Source):
    id = "osm"
    title = "OpenStreetMap"
    available = True
    default_on = True
    note = "Работает"
    attribution = "© OpenStreetMap contributors"

    def object_url(self, ext_type: str, ext_id: int) -> str:
        return f"https://www.openstreetmap.org/{ext_type}/{ext_id}"

    async def search(self, niche: Niche, city: City) -> SearchResult:
        geo = await geocode(city)
        center = (geo["lat"], geo["lon"])
        fresh = fetch_one("""SELECT place_ids FROM source_fetches WHERE source = 'osm' AND niche = %s AND city = %s
                             AND fetched_at > now() - make_interval(hours => %s)""", (niche.id, city.id, REFRESH_HOURS))
        if fresh is not None:
            rows = fetch_all("SELECT * FROM places WHERE id = ANY(%s)", (fresh["place_ids"],))
            return SearchResult([_from_row(r) for r in rows], center, from_cache=True)

        elements, data_at = await _overpass(build_query(niche, geo["area_id"]))
        places = [p for p in (normalize(el) for el in elements) if p]
        return SearchResult(places, center, from_cache=False, data_at=data_at)


def _from_row(r: dict) -> FoundPlace:
    return FoundPlace(source=r["source"], ext_type=r["ext_type"], ext_id=r["ext_id"], name=r["name"],
                      street=r["street"], housenumber=r["housenumber"], lat=r["lat"], lon=r["lon"],
                      phones=list(r["phones"]), website=r["website"], channels=list(r["channels"]),
                      updated_at=r.get("source_updated_at"))
