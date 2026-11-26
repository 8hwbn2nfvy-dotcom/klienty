"""Источники заведений (карты). Каждый — адаптер с одинаковым интерфейсом, см. base.py."""
from __future__ import annotations

from app.sources.base import Source
from app.sources.dgis import DgisSource
from app.sources.osm import OsmSource
from app.sources.yandex import YandexSource

SOURCES: list[Source] = [OsmSource(), DgisSource(), YandexSource()]


def get(source_id: str) -> Source | None:
    return next((s for s in SOURCES if s.id == source_id), None)
