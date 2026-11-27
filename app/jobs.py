"""Задача поиска: найти заведения → проверить сайты → посчитать оценку → отдать N лучших.

Состояние задачи хранится только в таблице jobs. Если сервер перезапустился посреди работы,
при старте незавершённые задачи помечаются ошибкой, а на странице появляется кнопка «Повторить».
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app import catalog, merge, scoring, sitecheck
from app.db import Jsonb, connect, fetch_all, fetch_one
from app.sources import get as get_source
from app.sources.base import FoundPlace, SourceError

log = logging.getLogger("klienty.jobs")
SITE_RECHECK_HOURS = 24
PARALLEL_SITES = 6        # разные домены проверяются параллельно; один домен — 1 запрос/с
MAX_RADAR_POINTS = 200
CANCEL_POLL_SECONDS = 1.5
CANCELLED_MESSAGE = "Поиск отменён. В список ничего не добавлено."
RESTART_ERROR = "Сервер перезапустился, пока шёл поиск (на бесплатном Render так бывает). Нажми «Повторить»."
_tasks: set[asyncio.Task] = set()  # только чтобы задача не была собрана сборщиком мусора


class JobBusy(RuntimeError):
    def __init__(self, job_id: int):
        super().__init__("Поиск уже идёт.")
        self.job_id = job_id


def mark_interrupted() -> int:
    """Вызывается при старте сервера: всё, что «шло», на самом деле оборвалось."""
    with connect() as c:
        # если перед перезапуском успели нажать «Отменить», это отмена, а не ошибка
        return c.execute("""UPDATE jobs SET updated_at = now(), finished_at = now(),
                                status = CASE WHEN cancel_requested THEN 'cancelled' ELSE 'error' END,
                                error = CASE WHEN cancel_requested THEN '' ELSE %s END,
                                message = CASE WHEN cancel_requested THEN %s ELSE message END
                            WHERE status IN ('queued', 'running')""", (RESTART_ERROR, CANCELLED_MESSAGE)).rowcount


def get(job_id: int) -> dict | None:
    return fetch_one("SELECT * FROM jobs WHERE id = %s", (job_id,))


def latest() -> dict | None:
    return fetch_one("SELECT * FROM jobs ORDER BY id DESC LIMIT 1")


def create(niche_ids: list[str], city_ids: list[str], amount: int, sources: list[str],
           categories: list[str]) -> int:
    """Записывает задачу в базу (синхронно). Запуск — launch(), из цикла событий сервера."""
    running = fetch_one("SELECT id FROM jobs WHERE status IN ('queued', 'running') ORDER BY id DESC LIMIT 1")
    if running:
        raise JobBusy(running["id"])
    row = fetch_one("""INSERT INTO jobs(niches, cities, amount, sources, categories)
                       VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                    (niche_ids, city_ids, amount, sources, categories))
    return row["id"]


def request_cancel(job_id: int) -> bool:
    """Просит идущий поиск остановиться. False — поиск уже закончился, отменять нечего."""
    with connect() as c:
        n = c.execute("""UPDATE jobs SET cancel_requested = true, updated_at = now()
                         WHERE id = %s AND status IN ('queued', 'running')""", (job_id,)).rowcount
    return n == 1


def history(limit: int = 100) -> list[dict]:
    return fetch_all("SELECT * FROM jobs ORDER BY id DESC LIMIT %s", (limit,))


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
                                   phones, website, channels, source_updated_at, contacts_known)
                VALUES (%s, %s, %s, ARRAY[%s], %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source, ext_type, ext_id) DO UPDATE SET
                    niches = (SELECT array_agg(DISTINCT x) FROM unnest(places.niches || EXCLUDED.niches) x),
                    city = EXCLUDED.city, name = EXCLUDED.name, street = EXCLUDED.street,
                    housenumber = EXCLUDED.housenumber, lat = EXCLUDED.lat, lon = EXCLUDED.lon,
                    phones = EXCLUDED.phones, channels = EXCLUDED.channels,
                    source_updated_at = COALESCE(EXCLUDED.source_updated_at, places.source_updated_at),
                    contacts_known = EXCLUDED.contacts_known, contacts_from = '',
                    -- сайт, вписанный владельцем, важнее карты; сменился сайт → старая проверка не про него
                    site_check = CASE WHEN places.website_manual <> '' OR places.website = EXCLUDED.website
                                      THEN places.site_check END,
                    site_checked_at = CASE WHEN places.website_manual <> '' OR places.website = EXCLUDED.website
                                           THEN places.site_checked_at END,
                    website = CASE WHEN places.website_manual <> '' THEN places.website_manual ELSE EXCLUDED.website END,
                    updated_at = now()
                RETURNING id""",
                (p.source, p.ext_type, p.ext_id, niche_id, city_id, p.name, p.street, p.housenumber, p.lat, p.lon,
                 p.phones, p.website, Jsonb(p.channels), p.updated_at, p.contacts_known)).fetchone()
            ids.append(row["id"])
    return ids


def _save_fetch(source: str, niche_id: str, city_id: str, ids: list[int]) -> None:
    with connect() as c:
        c.execute("""INSERT INTO source_fetches(source, niche, city, place_ids) VALUES (%s, %s, %s, %s)
                     ON CONFLICT (source, niche, city) DO UPDATE SET place_ids = EXCLUDED.place_ids, fetched_at = now()""",
                  (source, niche_id, city_id, ids))


class _Finishing:
    """После начала записи итогов отмена уже не прерывает задачу: иначе список и статус разойдутся."""
    flag = False


async def run(job_id: int) -> None:
    """Запускает поиск и следит за кнопкой «Отменить»: флаг cancel_requested проверяется в базе."""
    finishing = _Finishing()
    work = asyncio.create_task(_work(job_id, finishing))
    try:
        while not work.done():
            await asyncio.wait({work}, timeout=CANCEL_POLL_SECONDS)
            if work.done() or finishing.flag:
                continue
            row = await asyncio.to_thread(fetch_one, "SELECT cancel_requested FROM jobs WHERE id = %s", (job_id,))
            if row and row["cancel_requested"]:
                work.cancel()
                try:
                    await work
                except asyncio.CancelledError:
                    pass  # ожидаемо: мы сами остановили поиск
                await asyncio.to_thread(_update, job_id, status="cancelled", stage="done",
                                        message=CANCELLED_MESSAGE, finished_at=_now())
                return
    except Exception:  # следилка не должна ронять поиск; ошибка уйдёт в лог, поиск доработает
        log.exception("cancel watcher for job %s failed", job_id)
        await work


async def _work(job_id: int, finishing: _Finishing) -> None:
    db = asyncio.to_thread
    try:
        job = await db(get, job_id)
        niches = [catalog.niche(n) for n in job["niches"]]
        cities = [catalog.city(c) for c in job["cities"]]
        if not all(niches) or not all(cities) or not niches or not cities:
            raise SourceError("Ниша или город больше не существуют в справочнике. Выбери заново.")
        await db(_update, job_id, status="running", stage="search")

        # 1. Ищу заведения: каждая карта × каждая ниша × каждый город
        ids: list[int] = []
        points: list[list[float]] = []
        cached: list[str] = []
        center: tuple[float, float] | None = None
        data_dates: list = []
        notes: list[str] = []
        helper_ids: list[int] = []  # записи OSM, нужные только как источник контактов для 2ГИС
        plan = list(job["sources"])
        if "2gis" in plan and "osm" not in plan:
            plan.append("osm")
        for source_id in plan:
            helper = source_id not in job["sources"]
            src = get_source(source_id)
            if not src or not src.available:
                raise SourceError(f"Источник «{source_id}» недоступен.")
            for city in cities:
                for niche in niches:
                    res = await src.search(niche, city)
                    got = await db(_upsert_places, res.places, niche.id, city.id)
                    if res.data_at:
                        data_dates.append(res.data_at)
                    if res.note and not helper:
                        notes.append(res.note)
                    if res.from_cache:
                        cached.append(f"{niche.title} · {city.title}")
                    else:
                        await db(_save_fetch, source_id, niche.id, city.id, got)
                    if helper:
                        helper_ids += got
                        continue
                    for place_id, p in zip(got, res.places):  # got идёт в том же порядке, что res.places
                        if place_id in ids:
                            continue  # то же заведение под другой нишей — вторую точку не ставим
                        ids.append(place_id)
                        if p.lat is not None and len(points) < MAX_RADAR_POINTS:
                            points.append([p.lat, p.lon])
                    # Один город — центр радара в центре города; несколько — радар сам берёт середину точек.
                    if len(cities) == 1 and res.center:
                        center = res.center
                    await db(_update, job_id, found=len(ids), points=points,
                             center=list(center) if center else None,
                             map_data_at=min(data_dates) if data_dates else None)
        if not ids:
            what = ", ".join(n.title for n in niches)
            where = ", ".join(c.title for c in cities)
            await db(_update, job_id, status="done", stage="done", finished_at=_now(),
                     message=f"На карте не нашлось ни одного заведения ({what}; {where}). Ничего не изменилось.")
            return

        # Одно заведение из двух карт — одна запись (контакты берутся из 2ГИС)
        if "2gis" in job["sources"] and (len(job["sources"]) > 1 or helper_ids):
            merged = await db(_merge_duplicates, ids + helper_ids)
            ids = [i for i in ids if i not in merged]

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

        # 4. N лучших среди новых — только в тех категориях, что выбраны для поиска
        finishing.flag = True
        cats = list(job["categories"])
        scored = [c for c in cats if c in scoring.SCORED]
        # сначала те, кого ещё не показывали; не хватает — добавляются показанные раньше, но не тронутые
        best = await db(fetch_all, """SELECT id, shown_at FROM places WHERE id = ANY(%s) AND category = ANY(%s)
                                      AND status = 'new' ORDER BY (shown_at IS NOT NULL), score DESC, name LIMIT %s""",
                        (ids, scored, job["amount"])) if scored else []
        manual = []
        if "manual" in cats:
            # без оценки сравнивать не с чем: отдельная квота того же размера, свежие записи 2ГИС первыми
            manual = await db(fetch_all, """SELECT id, shown_at FROM places WHERE id = ANY(%s) AND category = 'manual'
                                            AND status = 'new'
                                            ORDER BY (shown_at IS NOT NULL), source_updated_at DESC NULLS LAST, name
                                            LIMIT %s""", (ids, job["amount"]))
        best = list(best) + list(manual)
        best_ids = [r["id"] for r in best]
        fresh = sum(1 for r in best if r["shown_at"] is None)
        if best_ids:
            await db(_mark_shown, best_ids)
        rows = await db(fetch_all, "SELECT id, category, status, site_check FROM places WHERE id = ANY(%s)", (ids,))
        msg = f"Найдено на карте: {len(ids)}. В выдаче: {len(best_ids)}"
        msg += (f" (с оценкой — {len(best_ids) - len(manual)}, проверить вручную — {len(manual)})." if manual else ".")
        why = explain_left_out(rows, set(best_ids), cats, job["amount"])
        if why:
            msg += " " + why
        if not best_ids:
            msg += " Новых подходящих нет: все уже в работе или пропущены. Ничего не изменилось."
        elif fresh == 0:
            msg += " Все они уже были в списке раньше — новых не появилось."
        else:
            msg += f" Новых в списке: {fresh}."
        if notes:
            msg += " " + " ".join(notes)
        if cached:
            msg += f" Из сохранённого поиска за последние сутки (карту заново не спрашивали): {', '.join(cached)}."
        await db(_update, job_id, status="done", stage="done", result_ids=best_ids, message=msg, finished_at=_now())
    except SourceError as e:
        await asyncio.to_thread(_update, job_id, status="error", error=str(e), finished_at=_now())
    except Exception as e:  # всё неожиданное — тоже на страницу, не молча
        log.exception("job %s failed", job_id)
        await asyncio.to_thread(_update, job_id, status="error", finished_at=_now(),
                                error=f"Внутренняя ошибка: {e.__class__.__name__}: {e}"[:500])


PIPELINE_STATUSES = ("work", "contacted", "no_answer", "agreed", "done", "refused")


def explain_left_out(rows: list[dict], best: set[int], cats: list[str], amount: int) -> str:
    """Почему найденные не попали в выдачу — одной фразой с числами и подсказкой, что включить."""
    counts: dict[str, int] = {}

    def add(reason: str) -> None:
        counts[reason] = counts.get(reason, 0) + 1

    for r in rows:
        if r["id"] in best:
            continue
        check = r.get("site_check") or {}
        if r["status"] in PIPELINE_STATUSES:
            add("уже в работе")
        elif r["status"] == "skipped":
            add("пропущены тобой")
        elif r["category"] is None:
            add("сайт защищён от проверки (скорее всего крупный)" if check.get("protected") else "сайт в порядке")
        elif r["category"] not in cats:
            add(f"«{scoring.CATEGORIES.get(r['category'], r['category'])}» — не выбрано в «Что ищу»")
        else:
            add(f"не вошли в количество ({amount})")
    if not counts:
        return ""
    parts = [f"{n} — {reason}" for reason, n in sorted(counts.items(), key=lambda x: -x[1])]
    text = "Не попали в выдачу: " + "; ".join(parts) + "."
    hidden = [c for c in scoring.CATEGORIES if c not in cats and any(f"«{scoring.CATEGORIES[c]}»" in p for p in parts)]
    if hidden:
        text += " Чтобы их видеть, включи в «Что ищу»: " + ", ".join(f"«{scoring.CATEGORIES[c]}»" for c in hidden) + "."
    return text


def _cat_titles(cats: list[str]) -> str:
    return ", ".join(scoring.CATEGORIES.get(c, c).lower() for c in cats)


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def _merge_duplicates(ids: list[int]) -> set[int]:
    """Склеивает записи OSM с записями 2ГИС того же заведения. Возвращает id склеенных записей OSM."""
    rows = fetch_all("""SELECT id, source, city, name, lat, lon, phones, website, website_manual, channels,
                               contacts_known FROM places WHERE id = ANY(%s)""", (ids,))
    osm = [r for r in rows if r["source"] == "osm"]
    dgis = {r["id"]: r for r in rows if r["source"] == "2gis"}
    pairs = merge.find_pairs(osm, list(dgis.values()))
    by_id = {r["id"]: r for r in osm}
    with connect() as c:
        # пересчёт с нуля: если в 2ГИС заведение пропало, запись OSM снова видна
        c.execute("UPDATE places SET merged_into = NULL WHERE id = ANY(%s)", ([r["id"] for r in osm],))
        for osm_id, dgis_id in pairs.items():
            c.execute("UPDATE places SET merged_into = %s WHERE id = %s", (dgis_id, osm_id))
            d, o = dgis[dgis_id], by_id[osm_id]
            if not d["contacts_known"]:
                # 2ГИС не отдал контакты — берём их из OSM; сайт из названия 2ГИС важнее пустого
                website = d["website_manual"] or o["website"] or d["website"]
                c.execute("""UPDATE places SET phones = %s, website = %s, channels = %s, contacts_known = true,
                                 contacts_from = 'osm',
                                 site_check = CASE WHEN website = %s THEN site_check END,
                                 site_checked_at = CASE WHEN website = %s THEN site_checked_at END
                             WHERE id = %s""",
                          (o["phones"], website, Jsonb(o["channels"]), website, website, dgis_id))
    return set(pairs)


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
