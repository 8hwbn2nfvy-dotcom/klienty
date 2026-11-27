"""Склейка: одно заведение, найденное в двух картах, остаётся одной записью.

Запись OpenStreetMap склеивается с записью 2ГИС, если у них общий телефон и они ближе
PHONE_MATCH_METERS, или одинаковое название (без слов вроде «шиномонтаж») и они ближе
NAME_MATCH_METERS. Склеенная запись OSM получает merged_into = id записи 2ГИС и больше
не попадает в список: контакты 2ГИС свежее.
"""
from __future__ import annotations

import math
import re

PHONE_MATCH_METERS = 3000
NAME_MATCH_METERS = 300
_GENERIC = re.compile(r"\b(шиномонтаж\w*|автосервис\w*|автомойк\w*|парикмахерск\w*|салон\w*|красоты|"
                      r"стоматолог\w*|клиник\w*|центр|сервис|ооо|ип|шинн\w*|шины)\b", re.I)


def _phones(p: dict) -> set[str]:
    return {re.sub(r"\D", "", x)[-10:] for x in p.get("phones") or [] if len(re.sub(r"\D", "", x)) >= 10}


def _name(p: dict) -> str:
    """Название для сравнения: у 2ГИС после запятой идёт вид деятельности («Шина34, шинный центр»),
    общие слова («шиномонтаж», «ООО») убираются, если после этого что-то остаётся."""
    raw = (p.get("name") or "").lower().replace("ё", "е")
    if p.get("source") == "2gis":
        raw = raw.split(",")[0]
    short = re.sub(r"[^\w]+", "", _GENERIC.sub(" ", raw))
    return short or re.sub(r"[^\w]+", "", raw)


def _meters(a: dict, b: dict) -> float:
    if None in (a.get("lat"), a.get("lon"), b.get("lat"), b.get("lon")):
        return math.inf
    k = math.cos(math.radians(a["lat"]))
    return math.hypot((a["lat"] - b["lat"]) * 111_320, (a["lon"] - b["lon"]) * 111_320 * k)


def find_pairs(osm: list[dict], dgis: list[dict]) -> dict[int, int]:
    """{id записи OSM: id записи 2ГИС} для одинаковых заведений."""
    pairs: dict[int, int] = {}
    for o in osm:
        best = None
        for d in dgis:
            if o.get("city") != d.get("city"):
                continue
            dist = _meters(o, d)
            same_phone = bool(_phones(o) & _phones(d)) and dist <= PHONE_MATCH_METERS
            same_name = _name(o) and _name(o) == _name(d) and dist <= NAME_MATCH_METERS
            if (same_phone or same_name) and (best is None or dist < best[0]):
                best = (dist, d["id"])
        if best:
            pairs[o["id"]] = best[1]
    return pairs
