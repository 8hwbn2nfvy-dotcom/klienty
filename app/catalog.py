"""Ниши и города. Чтобы добавить новую, допиши строку в список: подробности в README, раздел 3.

Ниша — набор фильтров Overpass (теги OpenStreetMap). Каждый фильтр — строка вида
["ключ"="значение"]...; агент ищет объекты, у которых совпал хотя бы один фильтр.
Теги проверены по wiki.openstreetmap.org, но точность для каждого города надо смотреть на живых данных 🟡.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Niche:
    id: str
    title: str
    osm_filters: tuple[str, ...]
    offer: dict[str, str]  # что предложить: по категории (site / card / upgrade)
    dgis_query: str = ""   # текст поиска в 2ГИС; пусто — название ниши маленькими буквами

    @property
    def search_text(self) -> str:
        return self.dgis_query or self.title.lower()


@dataclass(frozen=True)
class City:
    id: str
    title: str
    query: str  # строка для Nominatim


_DEFAULT_OFFER = {
    "site": "Сайт на 3–5 страниц: услуги и цены, отзывы, онлайн-запись, карта проезда. Сейчас клиенты находят вас только через соцсети и мессенджеры.",
    "card": "Сайт-визитка на одну страницу: услуги, цены, телефон, кнопка «позвонить», карта. Чтобы вас находили в поиске, а не только по телефону.",
    "upgrade": "Обновить сайт: мобильная версия, https, свежие цены и контакты, кнопка записи. Текущий сайт выглядит устаревшим или работает с ошибками.",
}

NICHES: list[Niche] = [
    Niche("tyres", "Шиномонтаж", (
        '["shop"="tyres"]',
        '["shop"="car_repair"]["service:vehicle:tyres"="yes"]',
        '["shop"="car_repair"]["name"~"шином",i]',
        '["craft"="tyre_fitter"]',
    ), {
        **_DEFAULT_OFFER,
        "site": "Сайт шиномонтажа: цены на сезонную переобувку по радиусам, онлайн-запись на время, хранение шин, карта проезда.",
        "card": "Визитка шиномонтажа: цены по радиусам, телефон с кнопкой «позвонить», часы работы, как проехать.",
    }),
    Niche("car_repair", "Автосервис", ('["shop"="car_repair"]',), _DEFAULT_OFFER),
    Niche("car_wash", "Автомойка", ('["amenity"="car_wash"]',), _DEFAULT_OFFER),
    Niche("hairdresser", "Парикмахерская", ('["shop"="hairdresser"]',), _DEFAULT_OFFER),
    Niche("beauty", "Салон красоты", ('["shop"="beauty"]',), _DEFAULT_OFFER),
    Niche("dentist", "Стоматология", ('["amenity"="dentist"]', '["healthcare"="dentist"]'), _DEFAULT_OFFER),
]

CITIES: list[City] = [
    City("volgograd", "Волгоград", "Волгоград, Россия"),
    City("volzhsky", "Волжский", "Волжский, Волгоградская область, Россия"),
    City("rostov", "Ростов-на-Дону", "Ростов-на-Дону, Россия"),
    City("saratov", "Саратов", "Саратов, Россия"),
    City("astrakhan", "Астрахань", "Астрахань, Россия"),
    City("krasnodar", "Краснодар", "Краснодар, Россия"),
    City("voronezh", "Воронеж", "Воронеж, Россия"),
    City("samara", "Самара", "Самара, Россия"),
]

DEFAULT_NICHE = "tyres"
DEFAULT_CITY = "volgograd"
AMOUNTS = [5, 10, 15, 20, 25, 30, 40, 50]
DEFAULT_AMOUNT = 10


def niche(niche_id: str) -> Niche | None:
    return next((n for n in NICHES if n.id == niche_id), None)


def city(city_id: str) -> City | None:
    return next((c for c in CITIES if c.id == city_id), None)
