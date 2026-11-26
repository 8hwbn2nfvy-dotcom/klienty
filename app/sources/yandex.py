"""Яндекс Карты — заглушка. Подключим позже, через официальный API."""
from app.sources.base import Source


class YandexSource(Source):
    id = "yandex"
    title = "Яндекс Карты"
    note = "Скоро"
