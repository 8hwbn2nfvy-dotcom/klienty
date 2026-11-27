"""Общий интерфейс источника. Новый источник: класс-наследник + строка в SOURCES."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

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
    updated_at: datetime | None = None  # когда запись на карте правили или проверяли последний раз
    contacts_known: bool = True  # False — карта не отдала контакты (2ГИС без платного поля)


@dataclass
class SearchResult:
    places: list[FoundPlace]
    center: tuple[float, float] | None
    from_cache: bool
    data_at: datetime | None = None  # на какую дату данные карты у ответившего сервера
    note: str = ""  # что владельцу стоит знать об этом ответе (например, лимит демо-ключа)


class SourceError(RuntimeError):
    """Понятная ошибка источника: текст показывается владельцу как есть."""


class Source:
    id = ""
    title = ""
    available = False   # можно ли включить
    default_on = False
    note = ""           # подпись в окне «Карты»
    unavailable_reason = "подключим позже"
    checkable = False   # есть ли кнопка «Проверить ключ»
    attribution = ""

    async def search(self, niche: Niche, city: City) -> SearchResult:
        raise SourceError(f"Источник «{self.title}» ещё не подключён.")

    def object_url(self, ext_type: str, ext_id: int) -> str:
        return ""

    async def check(self) -> dict:
        """Пробный запрос для кнопки «Проверить ключ»: {ok, message}."""
        return {"ok": False, "message": "Для этой карты проверки нет."}
