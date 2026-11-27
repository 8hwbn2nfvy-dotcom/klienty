"""Поддельные Nominatim, Overpass и сайты заведений для тестов (без интернета)."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

fake = FastAPI()
CALLS = {"overpass": 0, "nominatim": 0, "stale_mirror": 0}
RECENT = (datetime.now(timezone.utc) - timedelta(days=200)).strftime("%Y-%m-%dT%H:%M:%SZ")
BASE = os.environ.get("FAKE_BASE", "http://127.0.0.1:0")  # подменяется в conftest


@fake.get("/nominatim")
def nominatim(q: str):
    CALLS["nominatim"] += 1
    return [{"osm_type": "relation", "osm_id": 3374767, "lat": "48.70", "lon": "44.51",
             "addresstype": "city", "display_name": q}]


def elements() -> list[dict]:
    return [
        # сайта нет, VK + Telegram + запись → «создание сайта»
        {"type": "node", "id": 1, "lat": 48.71, "lon": 44.52, "timestamp": RECENT, "tags": {
            "name": "Шиномонтаж Колесо", "shop": "tyres", "phone": "+7 (8442) 11-22-33",
            "website": "https://vk.com/koleso34", "contact:telegram": "koleso34", "addr:street": "улица Мира",
            "addr:housenumber": "5", "booking": "https://dikidi.net/123"}},
        # только телефон → «создание визитки»
        # запись не правили с 2016 года → «старая запись»
        {"type": "node", "id": 2, "lat": 48.69, "lon": 44.48, "timestamp": "2016-04-02T10:00:00Z", "tags": {
            "name": "Шины у Ашота", "shop": "tyres", "phone": "89001234567"}},
        # старый сайт → «доработка»
        {"type": "way", "id": 3, "center": {"lat": 48.75, "lon": 44.55}, "timestamp": "2015-01-01T00:00:00Z", "tags": {
            "check_date": RECENT[:10],
            "name": "Автошина", "shop": "tyres", "website": f"{BASE}/old", "phone": "+7 900 000-00-00"}},
        # хороший сайт → не подходит
        {"type": "node", "id": 4, "lat": 48.72, "lon": 44.40, "timestamp": RECENT, "tags": {
            "name": "Шинный центр Про", "shop": "tyres", "website": f"{BASE}/good"}},
        # сайт не открывается → «доработка», статус «не открывается»
        {"type": "node", "id": 5, "lat": 48.60, "lon": 44.60, "timestamp": RECENT, "tags": {
            "name": "Резина 24", "shop": "tyres", "website": f"{BASE}/down"}},
        # без названия — пропускается
        {"type": "node", "id": 6, "lat": 48.6, "lon": 44.6, "tags": {"shop": "tyres"}},
        # отмечено на карте закрытым — пропускается
        {"type": "node", "id": 7, "lat": 48.6, "lon": 44.6, "timestamp": RECENT,
         "tags": {"shop": "tyres", "name": "Шины Закрыто", "opening_hours": "closed"}},
    ]


@fake.post("/overpass")
async def overpass(request: Request):
    CALLS["overpass"] += 1
    form = await request.form()
    assert "area(id:3603374767)" in form["data"] and "out center meta" in form["data"]
    if '"car_wash"' in form["data"]:
        await asyncio.sleep(8)  # медленный запрос — для проверки отмены
    return JSONResponse({"osm3s": {"timestamp_osm_base": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
                         "elements": elements()})


@fake.post("/stale-overpass")
async def stale_overpass():
    """Сервер-зеркало с данными месячной давности: агент должен пойти к следующему."""
    CALLS["stale_mirror"] += 1
    old = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return JSONResponse({"osm3s": {"timestamp_osm_base": old}, "elements": []})


OLD = """<html><head><title>Автошина</title></head><body><table><tr><td>Шиномонтаж. Звоните!</td></tr></table>
<a href="/broken">Цены</a><footer>© 2014 Автошина</footer></body></html>"""
GOOD = """<html><head><meta name="viewport" content="width=device-width"></head><body>
<nav><a href="/good/prices">Цены</a><a href="/good/contacts">Контакты</a></nav><main>""" + ("Текст о шинах. " * 80) + \
    """</main><footer>© 2019–2026 Шинный центр Про</footer></body></html>"""


@fake.get("/old")
def old():
    return HTMLResponse(OLD)


@fake.get("/good")
def good():
    return HTMLResponse(GOOD)


@fake.get("/good/{page}")
def good_page(page: str):
    return HTMLResponse("<html><body>ok</body></html>")


@fake.get("/down")
def down():
    return HTMLResponse("oops", status_code=502)


# ---------- поддельный 2ГИС ----------
DGIS_ITEMS = [
    # то же заведение, что «Шины у Ашота» в OSM: тот же телефон, рядом — должно склеиться
    {"id": "70000001000000001_abc", "name": "Шины у Ашота, шиномонтаж", "type": "branch",
     "address_name": "Тулака, 3", "point": {"lat": 48.6905, "lon": 44.4805},
     "dates": {"updated_at": RECENT},
     "contact_groups": [{"contacts": [
         {"type": "phone", "value": "+79001234567", "text": "+7 900 123-45-67"},
         {"type": "whatsapp", "value": "79001234567", "url": "https://wa.me/79001234567", "text": "WhatsApp"}]}]},
    # есть в OSM как «Шиномонтаж Колесо» рядом — при ключе без контактов возьмёт контакты из OSM
    {"id": "70000001000000003", "name": "Шиномонтаж Колесо, шиномонтажная мастерская", "type": "branch",
     "point": {"lat": 48.7101, "lon": 44.5201}, "dates": {"updated_at": RECENT},
     "contact_groups": [{"contacts": [{"type": "phone", "value": "+78442112233"}]}]},
    # нет ни в OSM, ни контактов → «проверить вручную» при ключе без контактов
    {"id": "70000001000000005", "name": "Резина Плюс, шинный центр", "type": "branch",
     "point": {"lat": 48.90, "lon": 44.70}, "dates": {"updated_at": RECENT},
     "contact_groups": [{"contacts": [{"type": "phone", "value": "+78442999999"}]}]},
    # новое заведение: только VK в поле «сайт» и Telegram → «создание сайта»
    {"id": "70000001000000002", "name": "Колесо 34", "type": "branch",
     "address": {"components": [{"type": "street_number", "street": "Ленина", "number": "10"}]},
     "point": {"lat": 48.73, "lon": 44.50}, "dates": {"updated_at": RECENT},
     "contact_groups": [{"contacts": [
         {"type": "phone", "value": "+78442000000"},
         {"type": "website", "value": "https://vk.com/koleso34v", "text": "vk.com/koleso34v"},
         {"type": "telegram", "value": "koleso34", "url": "https://t.me/koleso34"}]}]},
]


@fake.get("/2gis/2.0/region/search")
def dgis_region(q: str, key: str):
    CALLS["2gis"] = CALLS.get("2gis", 0) + 1
    if key == "bad":
        return {"meta": {"code": 403, "error": {"type": "keyIsNotActive", "message": "Ключ не активен"}}}
    return {"meta": {"code": 200}, "result": {"items": [{"id": "33", "name": q, "type": "region"}], "total": 1}}


@fake.get("/2gis/3.0/items")
def dgis_items(q: str, region_id: int, key: str, page: int = 1, page_size: int = 20, fields: str = ""):
    CALLS["2gis"] = CALLS.get("2gis", 0) + 1
    if key == "bad":
        return {"meta": {"code": 403, "error": {"type": "keyIsNotActive", "message": "Ключ не активен"}}}
    if page_size > 10:  # как у демо-ключа
        return {"meta": {"code": 400, "error": {"type": "paramBadValue",
                                                "message": "Length of parameter 'page_size' should be from 1 to 10"}}}
    if page > 5:  # как у демо-ключа
        return {"meta": {"code": 400, "error": {"type": "paramBadValue",
                                                "message": "Length of parameter 'page' should be from 1 to 5"}}}
    if page > 1:
        return {"meta": {"code": 404, "error": {"type": "itemNotFound", "message": "Results not found"}}}
    items = [dict(i) for i in DGIS_ITEMS]
    if key == "nocontacts":
        for i in items:
            i.pop("contact_groups", None)
    return {"meta": {"code": 200}, "result": {"items": items[:page_size], "total": len(items)}}
