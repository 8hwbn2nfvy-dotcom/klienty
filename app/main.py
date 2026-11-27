"""Сайт-агент поиска клиентов: страницы, API, запуск миграций при старте."""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import auth, catalog, config, jobs, store
from app.db import DbNotConfigured, fetch_all, fetch_one, execute
from app.migrate import migrate
from app.passwords import clean, hash_password
from app.scoring import CATEGORIES, is_stale
from app.sources import SOURCES, get as get_source

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("klienty")
ROOT = Path(__file__).resolve().parent.parent
PAGES = {"/": "list", "/history": "history", "/niches": "niches", "/cities": "cities", "/amount": "amount",
         "/sources": "sources", "/settings": "settings"}
TITLES = {"list": "Клиенты", "history": "История", "niches": "Ниша", "cities": "Город", "amount": "Количество",
          "sources": "Карты", "settings": "Настройки", "login": "Вход"}
STATUSES = {"new": "Новое", "work": "В работе", "skipped": "Пропущено"}


class DbState:
    ready = False
    error = ""
    last_try = 0.0


def ensure_db() -> None:
    """Миграции при старте; если база была недоступна — повторная попытка не чаще раза в 10 с."""
    if DbState.ready or time.time() - DbState.last_try < 10:
        if not DbState.ready:
            raise DbNotConfigured(DbState.error)
        return
    DbState.last_try = time.time()
    try:
        applied = migrate()
        n = jobs.mark_interrupted()
        DbState.ready, DbState.error = True, ""
        log.info("migrations applied: %s; interrupted jobs: %s", applied, n)
    except DbNotConfigured as e:
        DbState.error = str(e)
        raise
    except psycopg.Error as e:
        DbState.error = f"База недоступна: {e.__class__.__name__}: {str(e).strip()[:300]}"
        raise DbNotConfigured(DbState.error) from e


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        await asyncio.to_thread(ensure_db)
    except DbNotConfigured as e:
        log.error("DB not ready at startup: %s", e)
    yield


app = FastAPI(title="Klienty", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.exception_handler(DbNotConfigured)
async def _db_missing(_: Request, e: DbNotConfigured):
    return JSONResponse({"detail": str(e)}, status_code=503)


@app.exception_handler(psycopg.Error)
async def _db_error(_: Request, e: psycopg.Error):
    log.exception("db error")
    return JSONResponse({"detail": f"Ошибка базы: {e.__class__.__name__}. Изменения не сохранены."}, status_code=503)


# ---------- страницы ----------

def render_page(page: str, title: str | None = None) -> HTMLResponse:
    shell = (ROOT / "pages" / "shell.html").read_text(encoding="utf-8")
    body = (ROOT / "pages" / f"{page}.html").read_text(encoding="utf-8")
    html = (shell.replace("{{title}}", title or TITLES[page]).replace("{{page}}", page)
            .replace("{{version}}", config.VERSION).replace("{{main}}", body))
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if auth.is_logged_in(request):
        return RedirectResponse("/", status_code=303)
    return render_page("login")


def _page_route(path: str, page: str):
    def handler(request: Request):
        if not auth.is_logged_in(request):
            return RedirectResponse("/login", status_code=303)
        return render_page(page)
    app.add_api_route(path, handler, methods=["GET"], response_class=HTMLResponse, name=f"page_{page}")


for _path, _page in PAGES.items():
    _page_route(_path, _page)


@app.get("/search/{job_id}", response_class=HTMLResponse)
def result_page(job_id: int, request: Request):
    """Итог одного поиска: та же страница списка, она сама видит адрес и показывает только этот поиск."""
    if not auth.is_logged_in(request):
        return RedirectResponse("/login", status_code=303)
    return render_page("list", title=f"Итог поиска №{job_id}")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(ROOT / "static" / "icon.svg", media_type="image/svg+xml")


# ---------- здоровье и вход ----------

@app.get("/api/health")
def health():
    db = "ok"
    try:
        ensure_db()
        fetch_one("SELECT 1 AS ok")
    except Exception as e:  # здоровье отвечает всегда: ошибка базы видна в ответе и на сайте
        db = f"error: {e}"
    return {"ok": True, "version": config.VERSION, "db": db, "password_set": auth.configured()}


@app.get("/api/auth/state")
def auth_state(request: Request):
    return {"configured": auth.configured(), "logged_in": auth.is_logged_in(request),
            "hash_env_present": bool(config.PASSWORD_HASH)}


class SetupBody(BaseModel):
    password: str
    password2: str


@app.post("/api/setup/hash")
def setup_hash(body: SetupBody):
    """Первый запуск: считает хэш пароля, ничего не сохраняет. После установки PASSWORD_HASH — закрыто."""
    if auth.configured():
        raise HTTPException(403, "Пароль уже задан. Чтобы сменить его, удали PASSWORD_HASH в Render и открой /login снова.")
    p1, p2 = clean(body.password), clean(body.password2)
    if len(p1) < 8:
        raise HTTPException(400, "Пароль слишком короткий: нужно хотя бы 8 символов.")
    if p1 != p2:
        raise HTTPException(400, "Пароли не совпадают.")
    return {"name": "PASSWORD_HASH", "value": hash_password(p1)}


class LoginBody(BaseModel):
    password: str


@app.post("/api/login")
def login(body: LoginBody, request: Request, response: Response):
    auth.check_password(body.password, auth.client_ip(request))
    secure = request.url.scheme == "https"
    response.set_cookie(auth.COOKIE, auth.make_token(), max_age=auth.TTL, httponly=True,
                        samesite="lax", secure=secure)
    return {"ok": True}


@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie(auth.COOKIE)
    return {"ok": True}


# ---------- настройки и справочники ----------

def _catalog_payload() -> dict:
    return {
        "niches": [{"id": n.id, "title": n.title} for n in catalog.NICHES],
        "cities": [{"id": c.id, "title": c.title} for c in catalog.CITIES],
        "amounts": catalog.AMOUNTS,
        "sources": [{"id": s.id, "title": s.title, "available": s.available, "note": s.note,
                     "reason": "" if s.available else s.unavailable_reason, "checkable": s.checkable}
                    for s in SOURCES],
        "categories": CATEGORIES,
        "statuses": STATUSES,
    }


@app.get("/api/settings")
def get_settings(request: Request):
    auth.require(request)
    ensure_db()
    return {"settings": store.get_all(), "catalog": _catalog_payload()}


@app.put("/api/settings")
def put_settings(changes: dict, request: Request):
    auth.require(request)
    ensure_db()
    try:
        settings, changed = store.update(changes)
    except store.BadSetting as e:
        raise HTTPException(400, str(e)) from e
    return {"settings": settings, "changed": changed}


# ---------- поиск ----------

def _titles(ids: list[str], lookup) -> str:
    return ", ".join((lookup(i).title if lookup(i) else i) for i in ids if i)


def _job_payload(job: dict | None) -> dict | None:
    if not job:
        return None
    niche_ids = job["niches"] or [job["niche"]]
    city_ids = job["cities"] or [job["city"]]
    return {k: job[k] for k in ("id", "status", "stage", "found", "to_check", "checked", "scored", "points",
                                "center", "message", "error", "amount", "sources", "categories",
                                "cancel_requested")} | {
        "niche_title": _titles(niche_ids, catalog.niche), "city_title": _titles(city_ids, catalog.city),
        "categories_title": ", ".join(CATEGORIES.get(c, c) for c in job["categories"]),
        "map_data_at": job["map_data_at"].isoformat() if job["map_data_at"] else None,
        "result_count": len(job["result_ids"] or []),
        "created_at": job["created_at"].isoformat(),
        "finished_at": job["finished_at"].isoformat() if job["finished_at"] else None}


async def _create_and_launch(niches: list[str], cities: list[str], amount: int, sources: list[str],
                             categories: list[str]):
    try:
        job_id = await asyncio.to_thread(jobs.create, niches, cities, amount, sources, categories)
    except jobs.JobBusy as e:
        return JSONResponse({"detail": "Поиск уже идёт — показываю его.", "job_id": e.job_id}, status_code=409)
    jobs.launch(job_id)
    return {"job_id": job_id}


@app.post("/api/search")
async def start_search(request: Request):
    auth.require(request)
    await asyncio.to_thread(ensure_db)
    s = await asyncio.to_thread(store.get_all)
    enabled = [sid for sid, on in s["sources"].items() if on]
    if not enabled:
        raise HTTPException(400, "Ни одна карта не включена. Открой «Карты» и включи OpenStreetMap.")
    return await _create_and_launch(s["niches"], s["cities"], s["amount"], enabled, s["categories"])


@app.post("/api/jobs/{job_id}/retry")
async def retry_job(job_id: int, request: Request):
    auth.require(request)
    await asyncio.to_thread(ensure_db)
    old = await asyncio.to_thread(jobs.get, job_id)
    if not old:
        raise HTTPException(404, "Такой задачи нет.")
    if old["status"] != "error":
        raise HTTPException(400, "Повторить можно только задачу с ошибкой.")
    return await _create_and_launch(list(old["niches"]) or [old["niche"]], list(old["cities"]) or [old["city"]],
                                    old["amount"], list(old["sources"]), list(old["categories"]))


@app.post("/api/sources/{source_id}/check")
async def check_source(source_id: str, request: Request):
    """Кнопка «Проверить ключ»: один пробный запрос к карте."""
    auth.require(request)
    await asyncio.to_thread(ensure_db)
    src = get_source(source_id)
    if not src or not src.checkable:
        raise HTTPException(404, "Для этой карты проверки нет.")
    return await src.check()


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: int, request: Request):
    auth.require(request)
    ensure_db()
    if not jobs.get(job_id):
        raise HTTPException(404, "Такой задачи нет.")
    if not jobs.request_cancel(job_id):
        return JSONResponse({"detail": "Поиск уже закончился — отменять нечего, ничего не изменилось."}, status_code=409)
    return {"ok": True}


@app.get("/api/jobs")
def job_history(request: Request):
    auth.require(request)
    ensure_db()
    return {"jobs": [_job_payload(j) for j in jobs.history()]}


@app.get("/api/jobs/latest")
def latest_job(request: Request):
    auth.require(request)
    ensure_db()
    return {"job": _job_payload(jobs.latest())}


@app.get("/api/jobs/{job_id}/places")
def job_places(job_id: int, request: Request):
    """Заведения, которые выдал этот поиск: сначала с оценкой по убыванию, потом «проверить вручную»."""
    auth.require(request)
    ensure_db()
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Такого поиска нет.")
    rows = fetch_all("""SELECT * FROM places WHERE id = ANY(%s)
                        ORDER BY (category = 'manual'), score DESC, name""", (list(job["result_ids"] or []),))
    many_cities = len(set(r["city"] for r in rows)) > 1
    return {"job": _job_payload(job),
            "places": [_place_brief(r) | ({"city_title": _titles([r["city"]], catalog.city)} if many_cities else {})
                       for r in rows]}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: int, request: Request):
    auth.require(request)
    ensure_db()
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Такой задачи нет.")
    return {"job": _job_payload(job)}


# ---------- заведения ----------

def _place_brief(r: dict) -> dict:
    # для строки списка: первый телефон и ссылки на соцсети, мессенджеры и запись
    links = [c for c in r["channels"] if c["kind"] in ("social", "messenger", "booking") and c.get("url")]
    return {"id": r["id"], "name": r["name"], "category": r["category"], "score": r["score"],
            "status": r["status"], "street": r["street"], "housenumber": r["housenumber"],
            "phone": (r["phones"] or [""])[0], "links": [{"label": c["label"], "url": c["url"]} for c in links],
            "stale": is_stale(r),
            "source_updated_at": r["source_updated_at"].date().isoformat() if r["source_updated_at"] else None}


@app.get("/api/places")
def list_places(request: Request):
    """Список для выбранных ниш и городов: всё, что хоть раз попадало в выдачу поиска.
    Показываются только выбранные для поиска категории (настройка categories)."""
    auth.require(request)
    ensure_db()
    s = store.get_all()
    rows = fetch_all("""SELECT * FROM places WHERE city = ANY(%s) AND niches && %s AND shown_at IS NOT NULL
                        AND category = ANY(%s) AND merged_into IS NULL ORDER BY score DESC, name""", (s["cities"], s["niches"], s["categories"]))
    many_cities = len(s["cities"]) > 1
    return {"places": [_place_brief(r) | ({"city_title": _titles([r["city"]], catalog.city)} if many_cities else {})
                       for r in rows],
            "niche": _titles(s["niches"], catalog.niche), "city": _titles(s["cities"], catalog.city)}


@app.get("/api/places/{place_id}")
def place_card(place_id: int, request: Request):
    auth.require(request)
    ensure_db()
    r = fetch_one("SELECT * FROM places WHERE id = %s", (place_id,))
    if not r:
        raise HTTPException(404, "Такой записи нет (возможно, её удалили).")
    src = get_source(r["source"])
    c = catalog.city(r["city"])
    niche = next((catalog.niche(n) for n in r["niches"] if catalog.niche(n)), None)
    offer = (niche.offer if niche else {}).get(r["category"] or "", "")
    return {**_place_brief(r), "city_title": c.title if c else r["city"], "phones": r["phones"],
            "website": r["website"], "channels": r["channels"], "site_check": r["site_check"],
            "score_parts": r["score_parts"], "offer": offer,
            "contacts_known": r["contacts_known"], "contacts_from": r["contacts_from"],
            "object_url": src.object_url(r["ext_type"], r["ext_id"]) if src else "",
            "source_title": src.title if src else r["source"], "attribution": src.attribution if src else ""}


class StatusBody(BaseModel):
    status: str


@app.post("/api/places/{place_id}/status")
def set_status(place_id: int, body: StatusBody, request: Request):
    auth.require(request)
    ensure_db()
    if body.status not in STATUSES:
        raise HTTPException(400, "Неизвестный статус.")
    r = fetch_one("SELECT status FROM places WHERE id = %s", (place_id,))
    if not r:
        raise HTTPException(404, "Такой записи нет.")
    if r["status"] == body.status:
        return {"changed": False, "status": body.status}
    n = execute("UPDATE places SET status = %s, status_at = now() WHERE id = %s", (body.status, place_id))
    if n != 1:
        raise HTTPException(500, "Статус не сохранился. Попробуй ещё раз.")
    return {"changed": True, "status": body.status, "previous": r["status"]}
