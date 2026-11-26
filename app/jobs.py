"""Задача поиска: найти заведения → проверить сайты → посчитать оценку → отдать N лучших.

Состояние задачи хранится только в таблице jobs. Если сервер перезапустился посреди работы,
при старте незавершённые задачи помечаются ошибкой, а на странице появляется кнопка «Повторить».
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app import catalog, scoring, sitecheck
from app.db import Jsonb, connect, fetch_all, fetch_one
from app.sources import get as get_source
from app.sources.base import FoundPlace, SourceError

log = logging.getLogger("klienty.jobs")
SITE_RECHECK_HOURS = 24
PARALLEL_SITES = 6        # разные домены проверяются параллельно; один домен — 1 запрос/с
MAX_RADAR_POINTS = 200
RESTART_ERROR = "Сервер перезапустился, пока шёл поиск (на бесплатном Render так бывает). Нажми «Повторить»."
_tasks: set[asyncio.Task] = set()  # только чтобы задача не была собрана сборщиком мусора


class JobBusy(RuntimeError):
    def __init__(self, job_id: int):
        super().__init__("Поиск уже идёт.")
        self.job_id = job_id


def mark_interrupted() -> int:
    """Вызывается при старте сервера: всё, что «шло», на самом деле оборвалось."""
    with connect() as c:
        return c.execute("""UPDATE jobs SET status = 'error', error = %s, updated_at = now(), finished_at = now()
                            WHERE status IN ('queued', 'running')""", (RESTART_ERROR,)).rowcount


def get(job_id: int) -> dict | None:
    return fetch_one("SELECT * FROM jobs WHERE id = %s", (job_id,))


def latest() -> dict | None:
    return fetch_one("SELECT * FROM jobs ORDER BY id DESC LIMIT 1")


def create(niche_id: str, city_id: str, amount: int, sources: list[str]) -> int:
    """Записывает задачу в базу (синхронно). Запуск — launch(), из цикла событий сервера."""
    running = fetch_one("SELECT id FROM jobs WHERE status IN ('queued', 'running') ORDER BY id DESC LIMIT 1")
    if running:
        raise JobBusy(running["id"])
    row = fetch_one("""INSERT INTO jobs(niche, city, amount, sources) VALUES (%s, %s, %s, %s) RETURNING id""",
                    (niche_id, city_id, amount, sources))
    return row["id"]


def launch(job_id: int) -> None:
    task = asyncio.create_task(run(job_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def _update(job_id: int, **fields: Any) -> None:
    sets = ", ".join(f"{k} = %s" for k in fields)
    vals = [Jsonb(v) if k in ("points", "center") else v for k, v in fields.items()]
    with connect() as c:
        c.execute(f"UPDATE jobs SET {sets}, updated_at = now() WHERE id = %s", (*vals, job_id))


def _upsert_places(found: list[FoundPlace], niche_id: str, city_id: str) -> list[int]:
    ids: list[int] = []
    with connect() as c:
        for p in found:
            row = c.execute("""
                INSERT INTO places(source, ext_type, ext_id, niches, city, name, street, housenumber, lat, lon,
                                   phones, website, channels)
                VALUES (%s, %s, %s, ARRAY[%s], %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source, ext_type, ext_id) DO UPDATE SET
                    niches = (SELECT array_agg(DISTINCT x) FROM unnest(places.niches || EXCLUDED.niches) x),
                    city = EXCLUDED.city, name = EXCLUDED.name, street = EXCLUDED.street,
                    housenumber = EXCLUDED.housenumber, lat = EXCLUDED.lat, lon = EXCLUDED.lon,
                    phones = EXCLUDED.phones, channels = EXCLUDED.channels,
                    -- сайт сменился → старая проверка больше не про него
                    site_check = CASE WHEN places.website = EXCLUDED.website THEN places.site_check END,
                    site_checked_at = CASE WHEN places.website = EXCLUDED.website THEN places.site_checked_at END,
                    website = EXCLUDED.website, updated_at = now()
                RETURNING id""",
                (p.source, p.ext_type, p.ext_id, niche_id, city_id, p.name, p.street, p.housenumber, p.lat, p.lon,
                 p.phones, p.website, Jsonb(p.channels))).fetchone()
            ids.append(row["id"])
    return ids


def _save_fetch(source: str, niche_id: str, city_id: str, ids: list[int]) -> None:
    with connect() as c:
        c.execute("""INSERT INTO source_fetches(source, niche, city, place_ids) VALUES (%s, %s, %s, %s)
                     ON CONFLICT (source, niche, city) DO UPDATE SET place_ids = EXCLUDED.place_ids, fetched_at = now()""",
                  (source, niche_id, city_id, ids))


async def run(job_id: int) -> None:
    db = asyncio.to_thread
    try:
        job = await db(get, job_id)
        niche, city = catalog.niche(job["niche"]), catalog.city(job["city"])
        if not niche or not city:
            raise SourceError("Ниша или город больше не существуют в справочнике. Выбери заново.")
        await db(_update, job_id, status="running", stage="search")

        # 1. Ищу заведения
        ids: list[int] = []
        points: list[list[float]] = []
        cached_sources: list[str] = []
        for source_id in job["sources"]:
            src = get_source(source_id)
            if not src or not src.available:
                raise SourceError(f"Источник «{source_id}» недоступен.")
            res = await src.search(niche, city)
            got = await db(_upsert_places, res.places, niche.id, city.id)
            if res.from_cache:
                cached_sources.append(src.title)
            else:
                await db(_save_fetch, source_id, niche.id, city.id, got)
            ids += [i for i in got if i not in ids]
            points += [[p.lat, p.lon] for p in res.places if p.lat is not None][:MAX_RADAR_POINTS - len(points)]
            await db(_update, job_id, found=len(ids), points=points,
                     center=list(res.center) if res.center else None)
        if not ids:
            await db(_update, job_id, status="done", stage="done", finished_at=_now(),
                     message=f"На карте не нашлось ни одного заведения «{niche.title}» в городе {city.title}. "
                             "Ничего не изменилось.")
            return

        # 2. Проверяю сайты
        await db(_update, job_id, stage="check")
        to_check = await db(fetch_all, """SELECT id, website FROM places WHERE id = ANY(%s) AND website <> ''
            AND (site_checked_at IS NULL OR site_checked_at < now() - make_interval(hours => %s))""",
                            (ids, SITE_RECHECK_HOURS))
        await db(_update, job_id, to_check=len(to_check))
        sem = asyncio.Semaphore(PARALLEL_SITES)
        done = 0

        async def one(row: dict) -> None:
            nonlocal done
            async with sem:
                res = await sitecheck.check(row["website"])
            await db(_save_check, row["id"], res)
            done += 1
            await db(_update, job_id, checked=done)

        await asyncio.gather(*(one(r) for r in to_check))

        # 3. Считаю оценку
        await db(_update, job_id, stage="score")
        rows = await db(fetch_all, "SELECT * FROM places WHERE id = ANY(%s)", (ids,))
        await db(_save_scores, rows)
        await db(_update, job_id, scored=len(rows))

        # 4. N лучших среди новых
        best = await db(fetch_all, """SELECT id, shown_at FROM places WHERE id = ANY(%s) AND category IS NOT NULL
                                      AND status = 'new' ORDER BY score DESC, name LIMIT %s""", (ids, job["amount"]))
        best_ids = [r["id"] for r in best]
        fresh = sum(1 for r in best if r["shown_at"] is None)
        if best_ids:
            await db(_mark_shown, best_ids)
        suitable = (await db(fetch_one, "SELECT count(*) AS n FROM places WHERE id = ANY(%s) AND category IS NOT NULL",
                             (ids,)))["n"]
        msg = f"Найдено на карте: {len(ids)}. Подходят: {suitable}. Лучших в выдаче: {len(best_ids)}."
        if not best_ids:
            msg += " Новых подходящих нет: все уже в работе или пропущены. Ничего не изменилось."
        elif fresh == 0:
            msg += " Все они уже были в списке раньше — новых не появилось."
        else:
            msg += f" Новых в списке: {fresh}."
        if cached_sources:
            msg += f" Карта ({', '.join(cached_sources)}) взята из сохранённого поиска за последние сутки."
        await db(_update, job_id, status="done", stage="done", result_ids=best_ids, message=msg, finished_at=_now())
    except SourceError as e:
        await asyncio.to_thread(_update, job_id, status="error", error=str(e), finished_at=_now())
    except Exception as e:  # всё неожиданное — тоже на страницу, не молча
        log.exception("job %s failed", job_id)
        await asyncio.to_thread(_update, job_id, status="error", finished_at=_now(),
                                error=f"Внутренняя ошибка: {e.__class__.__name__}: {e}"[:500])


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def _save_check(place_id: int, res: dict) -> None:
    with connect() as c:
        c.execute("UPDATE places SET site_check = %s, site_checked_at = now() WHERE id = %s", (Jsonb(res), place_id))


def _save_scores(rows: list[dict]) -> None:
    with connect() as c:
        for r in rows:
            category, total, parts = scoring.score(r)
            r["category"] = category
            c.execute("UPDATE places SET category = %s, score = %s, score_parts = %s WHERE id = %s",
                      (category, total, Jsonb(parts), r["id"]))


def _mark_shown(ids: list[int]) -> None:
    with connect() as c:
        c.execute("UPDATE places SET shown_at = COALESCE(shown_at, now()) WHERE id = ANY(%s)", (ids,))
