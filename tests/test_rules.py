from datetime import date

from app import contacts, scoring


def test_vk_in_website_is_a_channel_not_a_site():
    phones, website, channels = contacts.parse({
        "website": "https://vk.com/shina", "contact:telegram": "@shina", "phone": "8 (8442) 12-34-56; +79001112233"})
    assert website == ""
    assert [c["label"] for c in channels] == ["Telegram", "VK"] or {c["label"] for c in channels} == {"VK", "Telegram"}
    assert phones == ["+7 844 212-34-56", "+7 900 111-22-33"]


def test_catalog_links_are_ignored_and_bare_domain_gets_scheme():
    _, website, channels = contacts.parse({"website": "2gis.ru/volgograd/firm/1", "url": "shina34.ru"})
    assert website == "http://shina34.ru" and channels == []


def test_categories():
    site = {"website": "", "phones": ["1"], "channels": [
        {"kind": "social", "label": "VK", "value": "x", "url": ""},
        {"kind": "messenger", "label": "Telegram", "value": "x", "url": ""}]}
    assert scoring.score(site)[0] == "site"
    assert scoring.score({"website": "", "phones": ["1"], "channels": []})[0] == "card"
    old = {"website": "http://a", "site_check": {"opened": True, "https": False, "viewport": False,
                                                 "footer_year": date.today().year - 10, "text_len": 100,
                                                 "internal_links": 0, "broken_links": 0}}
    cat, total, parts = scoring.score(old)
    assert cat == "upgrade" and total == sum(p["points"] for p in parts)
    fine = {"website": "http://a", "site_check": {"opened": True, "https": True, "viewport": True,
                                                  "footer_year": date.today().year, "text_len": 5000,
                                                  "internal_links": 5, "broken_links": 0}}
    assert scoring.score(fine)[0] is None


def test_site_down_is_not_no_site():
    cat, _, parts = scoring.score({"website": "http://a", "site_check": {"opened": False, "error": "не ответил за 10 секунд"}})
    assert cat == "upgrade"
    assert "не открывается" in parts[1]["label"]


def test_score_clamped():
    p = {"website": "", "phones": [], "channels": []}
    assert 0 <= scoring.score(p)[1] <= 100
