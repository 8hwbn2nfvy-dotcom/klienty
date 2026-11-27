"""Весь путь: вход → настройки → поиск → список → карточка → статусы → перезапуск."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from tests.conftest import PASSWORD


@pytest.fixture()
def client(clean_db, fake_server):
    from app.main import app
    with TestClient(app) as c:
        yield c


def login(c):
    r = c.post("/api/login", json={"password": PASSWORD})
    assert r.status_code == 200, r.text


def wait_job(c, job_id, timeout=40):
    end = time.time() + timeout
    while time.time() < end:
        job = c.get(f"/api/jobs/{job_id}").json()["job"]
        if job["status"] in ("done", "error", "cancelled"):
            return job
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def test_pages_require_login(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert client.get("/api/places").status_code == 401
    assert client.post("/api/login", json={"password": "wrong"}).status_code == 401
    assert client.post("/api/setup/hash", json={"password": "12345678", "password2": "12345678"}).status_code == 403
    login(client)
    for path in ("/", "/niches", "/cities", "/amount", "/sources", "/settings"):
        r = client.get(path)
        assert r.status_code == 200 and 'id="main"' in r.text and "[hidden]" not in r.text
    assert client.get("/static/app.css").text.startswith("/*")
    assert "[hidden] { display: none !important; }" in client.get("/static/app.css").text


def test_health(client):
    h = client.get("/api/health").json()
    assert h["db"] == "ok" and h["password_set"] is True


def test_settings_changed_flag(client):
    login(client)
    s = client.get("/api/settings").json()
    assert s["settings"]["niches"] == ["tyres"] and s["settings"]["cities"] == ["volgograd"] and s["settings"]["amount"] == 10
    assert s["settings"]["categories"] == ["site", "card", "upgrade", "manual"]
    assert client.put("/api/settings", json={"cities": []}).status_code == 400
    assert client.put("/api/settings", json={"cities": ["volgograd", "mars"]}).status_code == 400
    r = client.put("/api/settings", json={"cities": ["rostov", "volgograd", "rostov"]}).json()
    assert r["settings"]["cities"] == ["volgograd", "rostov"] and r["changed"] == ["cities"]
    assert client.put("/api/settings", json={"cities": ["rostov", "volgograd"]}).json()["changed"] == []
    assert client.put("/api/settings", json={"categories": ["card", "site"]}).json()["settings"]["categories"] == ["site", "card"]
    assert client.put("/api/settings", json={"categories": []}).status_code == 400
    assert client.put("/api/settings", json={"amount": 10}).json()["changed"] == []
    assert client.put("/api/settings", json={"amount": 5}).json()["changed"] == ["amount"]
    assert client.put("/api/settings", json={"amount": 7}).status_code == 400
    r = client.put("/api/settings", json={"sources": {"osm": True, "yandex": True}})
    assert r.status_code == 400 and "позже" in r.json()["detail"]
    client.put("/api/settings", json={"sources": {"osm": False}})
    r = client.post("/api/search")
    assert r.status_code == 400 and "Ни одна карта" in r.json()["detail"]


def test_search_flow(client, fake_server):
    login(client)
    before = dict(fake_server.CALLS)
    job_id = client.post("/api/search").json()["job_id"]
    job = wait_job(client, job_id)
    assert job["status"] == "done", job
    assert job["found"] == 5 and job["to_check"] == 3 and job["checked"] == 3
    assert len(job["points"]) == 5 and job["center"] == [48.70, 44.51]

    places = client.get("/api/places").json()["places"]
    by_name = {p["name"]: p for p in places}
    assert by_name["Шиномонтаж Колесо"]["category"] == "site"
    assert by_name["Шины у Ашота"]["category"] == "card"
    assert by_name["Автошина"]["category"] == "upgrade"
    assert by_name["Резина 24"]["category"] == "upgrade"
    # тестовый «хороший» сайт работает по http — единственный признак «нет https»
    good = client.get(f"/api/places/{by_name['Шинный центр Про']['id']}").json()
    assert [p["label"] for p in good["score_parts"]][1:] == ["нет https"]
    assert good["stale"] is False
    ashot = client.get(f"/api/places/{by_name['Шины у Ашота']['id']}").json()
    assert ashot["stale"] is True and "2016" in " ".join(p["label"] for p in ashot["score_parts"])
    assert by_name["Автошина"]["stale"] is False  # правка старая, но check_date свежая
    assert "Шины Закрыто" not in by_name
    kolesо = by_name["Шиномонтаж Колесо"]
    assert kolesо["phone"].startswith("+7") and {l["label"] for l in kolesо["links"]} == {"VK", "Telegram", "Онлайн-запись"}
    assert job["map_data_at"] and fake_server.CALLS["stale_mirror"] >= 1
    assert good["score"] < by_name["Автошина"]["score"]
    assert [p["score"] for p in places] == sorted((p["score"] for p in places), reverse=True)

    card = client.get(f"/api/places/{by_name['Автошина']['id']}").json()
    labels = " | ".join(p["label"] for p in card["score_parts"])
    assert "нет https" in labels and "мобильной" in labels and "2014" in labels and "битые" in labels
    assert card["object_url"] == "https://www.openstreetmap.org/way/3"
    down = client.get(f"/api/places/{by_name['Резина 24']['id']}").json()
    assert down["site_check"]["opened"] is False and "502" in down["site_check"]["error"]

    pid = by_name["Шины у Ашота"]["id"]
    assert client.post(f"/api/places/{pid}/status", json={"status": "work"}).json()["changed"] is True
    assert client.post(f"/api/places/{pid}/status", json={"status": "work"}).json()["changed"] is False
    assert client.post(f"/api/places/{pid}/status", json={"status": "new"}).json()["changed"] is True

    # повтор в те же сутки: Overpass не трогаем, дублей нет, статусы целы
    client.post(f"/api/places/{pid}/status", json={"status": "skipped"})
    job2 = wait_job(client, client.post("/api/search").json()["job_id"])
    assert job2["status"] == "done" and "сохранённого поиска" in job2["message"]
    assert fake_server.CALLS["overpass"] - before["overpass"] == 1
    assert fake_server.CALLS["nominatim"] - before["nominatim"] == 1
    places2 = client.get("/api/places").json()["places"]
    assert len(places2) == len(places)
    assert next(p for p in places2 if p["id"] == pid)["status"] == "skipped"
    assert job2["result_count"] == 4  # пропущенное не попадает в новую выдачу


def test_amount_limits_results(client, fake_server):
    login(client)
    client.put("/api/settings", json={"amount": 5})
    job = wait_job(client, client.post("/api/search").json()["job_id"])
    assert job["result_count"] == 5
    client.put("/api/settings", json={"amount": 10})
    job = wait_job(client, client.post("/api/search").json()["job_id"])
    assert job["result_count"] == 5 and "новых не появилось" in job["message"]


def test_interrupted_jobs_marked_on_restart(client):
    login(client)
    from app.db import fetch_one
    jid = fetch_one("INSERT INTO jobs(niches, cities, amount, sources, status) VALUES ('{tyres}','{volgograd}',10,'{osm}','running') RETURNING id")["id"]
    from app import jobs
    assert jobs.mark_interrupted() == 1
    job = client.get(f"/api/jobs/{jid}").json()["job"]
    assert job["status"] == "error" and "Повторить" in job["error"]
    new = client.post(f"/api/jobs/{jid}/retry").json()["job_id"]
    assert wait_job(client, new)["status"] == "done"


def test_migrations_are_recorded(client):
    from app.db import fetch_all
    names = [r["name"] for r in fetch_all("SELECT name FROM schema_migrations")]
    assert names == ["001_init.sql", "002_multi_niche_city.sql", "003_cancel_history_freshness.sql", "004_refresh_map_cache.sql", "005_2gis.sql", "006_contacts_known.sql"]
    from app.migrate import migrate
    assert migrate() == []


def test_several_cities_and_niches(client, fake_server):
    """Две ниши × два города: каждая пара — свой запрос к карте, N лучших — на всех вместе."""
    login(client)
    before = fake_server.CALLS["overpass"]
    client.put("/api/settings", json={"cities": ["volgograd", "volzhsky"], "niches": ["tyres", "car_repair"], "amount": 5})
    job = wait_job(client, client.post("/api/search").json()["job_id"])
    assert job["status"] == "done", job
    assert fake_server.CALLS["overpass"] - before == 4
    assert job["city_title"] == "Волгоград, Волжский" and job["niche_title"] == "Шиномонтаж, Автосервис"
    assert job["center"] is None and len(job["points"]) == 5
    assert job["result_count"] == 5
    r = client.get("/api/places").json()
    assert r["city"] == "Волгоград, Волжский" and all("city_title" in p for p in r["places"])


def test_categories_limit_the_search(client):
    """«Что ищу» — условие поиска: в выдачу попадают только выбранные категории."""
    login(client)
    client.put("/api/settings", json={"categories": ["site", "card"], "amount": 10})
    job = wait_job(client, client.post("/api/search").json()["job_id"])
    assert job["status"] == "done" and job["categories"] == ["site", "card"]
    assert job["result_count"] == 2
    places = client.get("/api/places").json()["places"]
    assert {p["category"] for p in places} == {"site", "card"}
    # потом добавили «Доработку»: прошлые поиски её не выдавали — в списке её нет, пока не поищешь
    client.put("/api/settings", json={"categories": ["site", "card", "upgrade"]})
    assert len(client.get("/api/places").json()["places"]) == 2
    job = wait_job(client, client.post("/api/search").json()["job_id"])
    assert job["result_count"] == 5


def test_cancel_and_history(client):
    login(client)
    client.put("/api/settings", json={"niches": ["car_wash"]})  # поддельная карта отвечает на мойки 8 секунд
    job_id = client.post("/api/search").json()["job_id"]
    time.sleep(1.5)
    assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 200
    job = wait_job(client, job_id, timeout=15)
    assert job["status"] == "cancelled" and "ничего не добавлено" in job["message"]
    assert client.get("/api/places").json()["places"] == []
    r = client.post(f"/api/jobs/{job_id}/cancel")
    assert r.status_code == 409 and "ничего не изменилось" in r.json()["detail"]
    hist = client.get("/api/jobs").json()["jobs"]
    assert hist[0]["id"] == job_id and hist[0]["status"] == "cancelled"
    assert client.get("/history").status_code == 200


def test_themes(client):
    login(client)
    for t in ("graphite", "sand", "navy", "light"):
        assert client.put("/api/settings", json={"theme": t}).status_code == 200
    assert client.put("/api/settings", json={"theme": "pink"}).status_code == 400


def test_2gis_with_osm_merges_duplicates(client):
    login(client)
    r = client.put("/api/settings", json={"sources": {"osm": True, "2gis": True}})
    assert r.status_code == 200 and r.json()["settings"]["sources"]["2gis"] is True
    job = wait_job(client, client.post("/api/search").json()["job_id"])
    assert job["status"] == "done", job
    places = client.get("/api/places").json()["places"]
    names = [p["name"] for p in places]
    assert "Колесо 34" in names
    assert "Шины у Ашота" not in names and "Шины у Ашота, шиномонтаж" in names  # склеились, осталась запись 2ГИС
    kol = next(p for p in places if p["name"] == "Колесо 34")
    assert kol["category"] == "site" and {l["label"] for l in kol["links"]} == {"VK", "Telegram"}
    card = client.get(f"/api/places/{kol['id']}").json()
    assert card["object_url"] == "https://2gis.ru/firm/70000001000000002" and card["attribution"] == "© 2ГИС"
    assert card["street"] == "Ленина" and card["housenumber"] == "10"
    from app.sources.dgis import used_last_30_days
    assert used_last_30_days() >= 2


def test_2gis_key_problems(client, monkeypatch):
    login(client)
    from app import config
    monkeypatch.setattr(config, "DGIS_API_KEY", "bad")
    r = client.post("/api/sources/2gis/check").json()
    assert r["ok"] is False and "не принял ключ" in r["message"] and "Ключ не активен" in r["message"]
    client.put("/api/settings", json={"sources": {"osm": False, "2gis": True}})
    job = wait_job(client, client.post("/api/search").json()["job_id"])
    assert job["status"] == "error" and "не принял ключ" in job["error"]
    monkeypatch.setattr(config, "DGIS_API_KEY", "")
    r = client.post("/api/sources/2gis/check").json()
    assert r["ok"] is False and "DGIS_API_KEY" in r["message"]
    s = client.get("/api/settings").json()
    assert s["settings"]["sources"]["2gis"] is False  # без ключа включить нельзя
    assert client.put("/api/settings", json={"sources": {"osm": True, "2gis": True}}).status_code == 400


def test_2gis_without_contacts_intermediate_mode(client, monkeypatch):
    """Ключ без контактов: список из 2ГИС, контакты из OSM, остальные — «Проверить вручную»."""
    login(client)
    from app import config
    monkeypatch.setattr(config, "DGIS_API_KEY", "nocontacts")
    r = client.post("/api/sources/2gis/check").json()
    assert r["ok"] is True and "промежуточный режим" in r["message"]
    # включён только 2ГИС — OSM всё равно спрашивается ради контактов
    client.put("/api/settings", json={"sources": {"osm": False, "2gis": True},
                                      "categories": ["site", "card", "upgrade", "manual"]})
    job = wait_job(client, client.post("/api/search").json()["job_id"])
    assert job["status"] == "done", job
    assert "Проверить вручную" in job["message"]
    places = {p["name"]: p for p in client.get("/api/places").json()["places"]}
    # OSM-записи без пары в 2ГИС не показываются: OSM здесь только помощник
    assert "Автошина" not in places and "Резина 24" not in places
    kol = places["Шиномонтаж Колесо, шиномонтажная мастерская"]
    assert kol["category"] == "site" and {l["label"] for l in kol["links"]} >= {"VK", "Telegram"}
    card = client.get(f"/api/places/{kol['id']}").json()
    assert card["contacts_from"] == "osm" and card["contacts_known"] is True
    ashot = places["Шины у Ашота, шиномонтаж"]  # пара в OSM есть по названию рядом
    assert ashot["category"] == "card" and ashot["phone"]
    plus = places["Резина Плюс, шинный центр"]
    assert plus["category"] == "manual" and plus["score"] == 0 and plus["links"] == [] and plus["phone"] == ""
    assert places["Колесо 34"]["category"] == "manual"  # без контактов и без пары в OSM
    # повтор в те же сутки берёт 2ГИС из кэша — «проверить вручную» должно остаться
    job2 = wait_job(client, client.post("/api/search").json()["job_id"])
    assert job2["status"] == "done" and "сохранённого поиска" in job2["message"]
    places2 = {p["name"]: p for p in client.get("/api/places").json()["places"]}
    assert places2["Резина Плюс, шинный центр"]["category"] == "manual"
    assert places2["Шиномонтаж Колесо, шиномонтажная мастерская"]["category"] == "site"


def test_2gis_check_ok(client):
    login(client)
    r = client.post("/api/sources/2gis/check").json()
    assert r["ok"] is True and "контакты отдаются" in r["message"]
