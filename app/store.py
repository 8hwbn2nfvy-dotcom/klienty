"""Настройки владельца в таблице settings. Каждое изменение возвращает, поменялось ли что-то."""
from __future__ import annotations

from typing import Any

from app import catalog
from app.db import Jsonb, connect, fetch_all
from app.scoring import CATEGORIES
from app.sources import SOURCES

DEFAULTS: dict[str, Any] = {
    "theme": "light",
    "niches": [catalog.DEFAULT_NICHE],
    "cities": [catalog.DEFAULT_CITY],
    "categories": list(CATEGORIES),  # фильтр списка на главной
    "amount": catalog.DEFAULT_AMOUNT,
    "sources": {s.id: s.default_on for s in SOURCES},
}


class BadSetting(ValueError):
    pass


def get_all() -> dict[str, Any]:
    out = dict(DEFAULTS)
    for row in fetch_all("SELECT key, value FROM settings"):
        if row["key"] in DEFAULTS:
            out[row["key"]] = row["value"]
    # Источник, который нельзя включить (заглушка), всегда выключен, что бы ни лежало в базе.
    out["sources"] = {s.id: bool(out["sources"].get(s.id)) and s.available for s in SOURCES}
    return out


def validate(key: str, value: Any) -> Any:
    if key == "theme" and value in ("light", "dark"):
        return value
    if key in ("niches", "cities", "categories"):
        known = {"niches": [n.id for n in catalog.NICHES], "cities": [c.id for c in catalog.CITIES],
                 "categories": list(CATEGORIES)}[key]
        what = {"niches": "нишу", "cities": "город", "categories": "категорию"}[key]
        if not isinstance(value, list) or not value:
            raise BadSetting(f"Выбери хотя бы одну {what}.")
        bad = [v for v in value if v not in known]
        if bad:
            raise BadSetting(f"Неизвестные значения: {', '.join(map(str, bad))}")
        return [k for k in known if k in value]  # порядок как в справочнике, без повторов
    if key == "amount" and value in catalog.AMOUNTS:
        return value
    if key == "sources" and isinstance(value, dict):
        out = {}
        for s in SOURCES:
            want = bool(value.get(s.id))
            if want and not s.available:
                raise BadSetting(f"«{s.title}» пока нельзя включить: подключим позже.")
            out[s.id] = want
        return out
    raise BadSetting(f"Неверное значение для «{key}»: {value!r}")


def update(changes: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Сохраняет изменения. Возвращает (новые настройки, список реально изменённых ключей)."""
    current = get_all()
    changed: list[str] = []
    clean = {k: validate(k, v) for k, v in changes.items() if k in DEFAULTS}
    if len(clean) != len(changes):
        unknown = sorted(set(changes) - set(DEFAULTS))
        raise BadSetting("Неизвестные настройки: " + ", ".join(unknown))
    with connect() as c:
        for k, v in clean.items():
            if current.get(k) == v:
                continue
            c.execute("""INSERT INTO settings(key, value) VALUES (%s, %s)
                         ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()""",
                      (k, Jsonb(v)))
            changed.append(k)
    return get_all(), changed
