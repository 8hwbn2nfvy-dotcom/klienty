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
    offer: dict[str, str]  # что предложить: по категории (site / card / upgrade / manual)
    dgis_query: str = ""   # текст поиска в 2ГИС; пусто — название ниши маленькими буквами
    group: str = ""        # группа в окне «Ниша»

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
    "manual": "Карта не отдала контакты. Открой карточку в 2ГИС: нет сайта — предложи сайт (если есть соцсети) или визитку; сайт старый — доработку.",
    "upgrade": "Обновить сайт: мобильная версия, https, свежие цены и контакты, кнопка записи. Текущий сайт выглядит устаревшим или работает с ошибками.",
}

def _offer(site: str, card: str, upgrade: str = "") -> dict[str, str]:
    """Что предложить: текст для «создания сайта», «визитки» и (по желанию) «доработки»."""
    return {**_DEFAULT_OFFER, "site": site, "card": card, **({"upgrade": upgrade} if upgrade else {})}


# Предложения по группам ниш: что клиенту нужно на сайте в первую очередь.
_AUTO = _offer(
    "Сайт автосервиса: услуги и цены, онлайн-запись на время, фото работ, отзывы, карта проезда.",
    "Визитка: список работ и цены, кнопка «позвонить», часы работы, как проехать.")
_BEAUTY = _offer(
    "Сайт с онлайн-записью к мастеру, прайсом, портфолио работ и отзывами. Сейчас запись идёт только через соцсети.",
    "Визитка: прайс, фото работ, кнопки «записаться» в мессенджер и «позвонить», адрес.")
_HEALTH = _offer(
    "Сайт с услугами и ценами, врачами или мастерами, онлайн-записью и отзывами.",
    "Визитка: услуги, цены, часы работы, кнопка записи по телефону.")
_EDU = _offer(
    "Сайт с направлениями, расписанием, ценами абонементов и записью на пробное занятие.",
    "Визитка: направления, расписание, цена, кнопка «записаться на пробное».")
_SERVICE = _offer(
    "Сайт с услугами и ценами, сроками работы, примерами, кнопкой «оставить заявку».",
    "Визитка: прайс, сроки, адрес и часы работы, кнопка «позвонить».")
_HOME = _offer(
    "Сайт с портфолио работ, калькулятором стоимости, заявкой на замер и отзывами.",
    "Визитка: примеры работ, цены «от», кнопка «вызвать замерщика».")
_FOOD = _offer(
    "Сайт с меню или каталогом, ценами, заказом на дом или к празднику, отзывами.",
    "Визитка: меню и цены, адрес, часы работы, кнопка заказа в мессенджер.")

# Группы — порядок плиток в окне «Ниша».
GROUPS = ["Авто", "Красота", "Здоровье и уход", "Обучение и досуг", "Бытовые услуги", "Дом и ремонт", "Еда и цветы"]

NICHES: list[Niche] = [
    # ---- Авто ----
    Niche("tyres", "Шиномонтаж", (
        '["shop"="tyres"]',
        '["shop"="car_repair"]["service:vehicle:tyres"="yes"]',
        '["shop"="car_repair"]["name"~"шином",i]',
        '["craft"="tyre_fitter"]',
    ), {
        **_DEFAULT_OFFER,
        "site": "Сайт шиномонтажа: цены на сезонную переобувку по радиусам, онлайн-запись на время, хранение шин, карта проезда.",
        "card": "Визитка шиномонтажа: цены по радиусам, телефон с кнопкой «позвонить», часы работы, как проехать.",
    }, group="Авто"),
    Niche("car_repair", "Автосервис", ('["shop"="car_repair"]',), _AUTO, group="Авто"),
    Niche("car_wash", "Автомойка", ('["amenity"="car_wash"]',), _AUTO, group="Авто"),
    Niche("auto_electric", "Автоэлектрик", (
        '["shop"="car_repair"]["service:vehicle:electrical"="yes"]',
        '["shop"="car_repair"]["name"~"электрик",i]',
    ), _AUTO, "автоэлектрик", group="Авто"),
    Niche("body_repair", "Кузовной ремонт", (
        '["shop"="car_repair"]["service:vehicle:body_repair"="yes"]',
        '["shop"="car_repair"]["name"~"кузов|покраск",i]',
    ), _AUTO, "кузовной ремонт", group="Авто"),
    Niche("detailing", "Детейлинг", (
        '["shop"="car_repair"]["name"~"детейл|detail|полировк",i]',
        '["amenity"="car_wash"]["name"~"детейл|detail",i]',
    ), _AUTO, "детейлинг", group="Авто"),
    Niche("auto_glass", "Автостёкла", (
        '["shop"="car_repair"]["name"~"стекл",i]',
        '["shop"="car_parts"]["name"~"стекл",i]',
    ), _AUTO, "автостекла", group="Авто"),
    Niche("driving_school", "Автошкола", ('["amenity"="driving_school"]',), _EDU, "автошкола", group="Авто"),

    # ---- Красота ----
    Niche("hairdresser", "Парикмахерская", ('["shop"="hairdresser"]',), _BEAUTY, group="Красота"),
    Niche("barber", "Барбершоп", (
        '["shop"="hairdresser"]["hairdresser"="barber"]',
        '["shop"="hairdresser"]["name"~"барбер|barber",i]',
    ), _BEAUTY, "барбершоп", group="Красота"),
    Niche("beauty", "Салон красоты", ('["shop"="beauty"]',), _BEAUTY, group="Красота"),
    Niche("nails", "Маникюр", (
        '["shop"="beauty"]["beauty"~"nails"]',
        '["shop"="beauty"]["name"~"ногт|маникюр|nail",i]',
    ), _BEAUTY, "маникюр", group="Красота"),
    Niche("cosmetology", "Косметология", (
        '["shop"="beauty"]["beauty"~"skin_care|cosmetics"]',
        '["name"~"космет",i]["shop"="beauty"]',
        '["amenity"="clinic"]["name"~"космет",i]',
    ), _BEAUTY, "косметология", group="Красота"),
    Niche("tattoo", "Тату-салон", ('["shop"="tattoo"]',), _BEAUTY, "тату-салон", group="Красота"),

    # ---- Здоровье и уход ----
    Niche("dentist", "Стоматология", ('["amenity"="dentist"]', '["healthcare"="dentist"]'), _HEALTH, group="Здоровье и уход"),
    Niche("massage", "Массаж", ('["shop"="massage"]', '["healthcare"="physiotherapist"]["name"~"массаж",i]'),
          _HEALTH, "массаж", group="Здоровье и уход"),
    Niche("vet", "Ветклиника", ('["amenity"="veterinary"]',), _HEALTH, "ветеринарная клиника", group="Здоровье и уход"),
    Niche("grooming", "Груминг", ('["shop"="pet_grooming"]', '["shop"="pet"]["name"~"груминг",i]'),
          _BEAUTY, "груминг", group="Здоровье и уход"),
    Niche("sauna", "Сауна, баня", ('["leisure"="sauna"]', '["amenity"="public_bath"]'),
          _offer("Сайт с залами и фото, ценами по часам, онлайн-бронированием и картой проезда.",
                 "Визитка: фото, цены по часам, кнопка «забронировать по телефону»."), "сауна", group="Здоровье и уход"),

    # ---- Обучение и досуг ----
    Niche("fitness", "Фитнес-клуб", ('["leisure"="fitness_centre"]',), _EDU, "фитнес-клуб", group="Обучение и досуг"),
    Niche("dance", "Школа танцев", ('["leisure"="dance"]', '["amenity"="dancing_school"]'), _EDU, "школа танцев",
          group="Обучение и досуг"),
    Niche("kids_center", "Детский центр", (
        '["amenity"="childcare"]',
        '["amenity"="kindergarten"]["operator:type"="private"]',
        '["name"~"развити",i]["amenity"~"childcare|kindergarten|school"]',
    ), _EDU, "детский развивающий центр", group="Обучение и досуг"),
    Niche("language_school", "Языковые курсы", ('["amenity"="language_school"]',), _EDU,
          "курсы иностранных языков", group="Обучение и досуг"),
    Niche("photo_studio", "Фотостудия", ('["shop"="photo"]', '["craft"="photographer"]', '["shop"="photo_studio"]'),
          _offer("Сайт с портфолио, ценами на съёмку и аренду зала, онлайн-бронированием.",
                 "Визитка: примеры фото, цены, кнопка «забронировать»."), "фотостудия", group="Обучение и досуг"),

    # ---- Бытовые услуги ----
    Niche("shoe_repair", "Ремонт обуви", ('["craft"="shoemaker"]', '["shop"="shoe_repair"]'), _SERVICE,
          "ремонт обуви", group="Бытовые услуги"),
    Niche("tailor", "Ателье", ('["craft"="tailor"]', '["shop"="tailor"]', '["craft"="dressmaker"]'), _SERVICE,
          "ателье", group="Бытовые услуги"),
    Niche("dry_cleaning", "Химчистка", ('["shop"="dry_cleaning"]', '["shop"="laundry"]'), _SERVICE,
          "химчистка", group="Бытовые услуги"),
    Niche("phone_repair", "Ремонт телефонов", (
        '["craft"="electronics_repair"]["electronics_repair"~"phone"]',
        '["shop"="mobile_phone"]["name"~"ремонт",i]',
        '["shop"="electronics_repair"]',
    ), _SERVICE, "ремонт телефонов", group="Бытовые услуги"),
    Niche("appliance_repair", "Ремонт бытовой техники", (
        '["craft"="electronics_repair"]',
        '["shop"="appliance"]["name"~"ремонт",i]',
    ), _SERVICE, "ремонт бытовой техники", group="Бытовые услуги"),

    # ---- Дом и ремонт ----
    Niche("custom_furniture", "Мебель на заказ", (
        '["craft"="carpenter"]',
        '["shop"="furniture"]["name"~"заказ|кухн|шкаф",i]',
    ), _HOME, "мебель на заказ", group="Дом и ремонт"),
    Niche("windows", "Пластиковые окна", (
        '["craft"="window_construction"]',
        '["shop"="windows"]',
        '["name"~"окна|окон",i]["shop"]',
    ), _HOME, "пластиковые окна", group="Дом и ремонт"),
    Niche("ceilings", "Натяжные потолки", ('["name"~"потолк",i]["shop"]', '["name"~"потолк",i]["craft"]'),
          _HOME, "натяжные потолки", group="Дом и ремонт"),

    # ---- Еда и цветы ----
    Niche("bakery", "Пекарня", ('["shop"="bakery"]',), _FOOD, "пекарня", group="Еда и цветы"),
    Niche("confectionery", "Кондитерская, торты", ('["shop"="confectionery"]', '["shop"="pastry"]'), _FOOD,
          "торты на заказ", group="Еда и цветы"),
    Niche("cafe", "Кафе", ('["amenity"="cafe"]',), _FOOD, "кафе", group="Еда и цветы"),
    Niche("florist", "Цветы", ('["shop"="florist"]',),
          _offer("Сайт-каталог букетов с ценами, заказом и доставкой.",
                 "Визитка: фото букетов, цены «от», кнопка заказа в мессенджер, адрес."), "цветы", group="Еда и цветы"),
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
