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
        if job["status"] in ("done", "error"):
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
    assert s["settings"]["niche"] == "tyres" and s["settings"]["city"] == "volgograd" and s["settings"]["amount"] == 10
    assert client.put("/api/settings", json={"amount": 10}).json()["changed"] == []
    assert client.put("/api/settings", json={"amount": 5}).json()["changed"] == ["amount"]
    assert client.put("/api/settings", json={"amount": 7}).status_code == 400
    r = client.put("/api/settings", json={"sources": {"osm": True, "2gis": True}})
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
    jid = fetch_one("INSERT INTO jobs(niche, city, amount, sources, status) VALUES ('tyres','volgograd',10,'{osm}','running') RETURNING id")["id"]
    from app import jobs
    assert jobs.mark_interrupted() == 1
    job = client.get(f"/api/jobs/{jid}").json()["job"]
    assert job["status"] == "error" and "Повторить" in job["error"]
    new = client.post(f"/api/jobs/{jid}/retry").json()["job_id"]
    assert wait_job(client, new)["status"] == "done"


def test_migrations_are_recorded(client):
    from app.db import fetch_all
    names = [r["name"] for r in fetch_all("SELECT name FROM schema_migrations")]
    assert names == ["001_init.sql"]
    from app.migrate import migrate
    assert migrate() == []
