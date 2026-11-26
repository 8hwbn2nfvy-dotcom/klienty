"""Общий интерфейс источника. Новый источник: класс-наследник + строка в SOURCES."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.catalog import City, Niche


@dataclass
class FoundPlace:
    """Нормализованная запись: то, что агент берёт из карты. Сырой ответ не хранится."""
    source: str
    ext_type: str
    ext_id: int
    name: str
    street: str = ""
    housenumber: str = ""
    lat: float | None = None
    lon: float | None = None
    phones: list[str] = field(default_factory=list)
    website: str = ""
    channels: list[dict] = field(default_factory=list)  # [{kind, label, value, url}]


@dataclass
class SearchResult:
    places: list[FoundPlace]
    center: tuple[float, float] | None
    from_cache: bool


class SourceError(RuntimeError):
    """Понятная ошибка источника: текст показывается владельцу как есть."""


class Source:
    id = ""
    title = ""
    available = False   # можно ли включить
    default_on = False
    note = ""           # подпись в окне «Карты»
    attribution = ""

    async def search(self, niche: Niche, city: City) -> SearchResult:
        raise SourceError(f"Источник «{self.title}» ещё не подключён.")

    def object_url(self, ext_type: str, ext_id: int) -> str:
        return ""
