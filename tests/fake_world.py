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
