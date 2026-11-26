"""2ГИС — заглушка. Подключим позже, через официальный API."""
from app.sources.base import Source


class DgisSource(Source):
    id = "2gis"
    title = "2ГИС"
    note = "Скоро"
