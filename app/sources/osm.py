"""OpenStreetMap: город через Nominatim, заведения через Overpass API.

Правила сервисов: не чаще 1 запроса в секунду, ответы кэшируются, одинаковый запрос
к Overpass — не чаще раза в сутки (кэш в таблице source_fetches, сами записи — в places).
"""
from __future__ import annotations

import httpx

from app import config, contacts
from app.catalog import City, Niche
from app.db import Jsonb, connect, fetch_all, fetch_one
from app.ratelimit import limiter
from app.sources.base import FoundPlace, SearchResult, Source, SourceError

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
    return f"[out:json][timeout:90];\narea(id:{area_id})->.a;\n(\n{parts}\n);\nout center tags;"


def normalize(el: dict) -> FoundPlace | None:
    tags = el.get("tags") or {}
    name = (tags.get("name") or tags.get("brand") or "").strip()
    if not name:
        return None  # без названия владельцу некого искать
    lat = el.get("lat", (el.get("center") or {}).get("lat"))
    lon = el.get("lon", (el.get("center") or {}).get("lon"))
    phones, website, channels = contacts.parse(tags)
    return FoundPlace(source="osm", ext_type=el["type"], ext_id=int(el["id"]), name=name,
                      street=tags.get("addr:street", ""), housenumber=tags.get("addr:housenumber", ""),
                      lat=lat, lon=lon, phones=phones, website=website, channels=channels)


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

        await limiter.wait("overpass")
        try:
            async with _client() as cl:
                r = await cl.post(config.OVERPASS_URL, data={"data": build_query(niche, geo["area_id"])})
        except httpx.HTTPError as e:
            raise SourceError(f"Overpass (поиск по карте OSM) не отвечает: {e.__class__.__name__}. Попробуй через пару минут.") from e
        if r.status_code == 429:
            raise SourceError("Overpass просит подождать (слишком много запросов). Повтори через 1–2 минуты.")
        if r.status_code != 200:
            raise SourceError(f"Overpass ответил кодом {r.status_code}. Сервер карты перегружен, повтори позже.")
        try:
            elements = r.json().get("elements", [])
        except ValueError as e:
            raise SourceError("Overpass вернул непонятный ответ (не JSON). Повтори позже.") from e
        places = [p for p in (normalize(el) for el in elements) if p]
        return SearchResult(places, center, from_cache=False)


def _from_row(r: dict) -> FoundPlace:
    return FoundPlace(source=r["source"], ext_type=r["ext_type"], ext_id=r["ext_id"], name=r["name"],
                      street=r["street"], housenumber=r["housenumber"], lat=r["lat"], lon=r["lon"],
                      phones=list(r["phones"]), website=r["website"], channels=list(r["channels"]))
