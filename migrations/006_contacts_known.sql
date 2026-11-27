-- Промежуточный режим 2ГИС: ключ без контактов.
-- contacts_known = false — телефон, сайт и соцсети карта не отдала, заведение идёт в «Проверить вручную».
-- contacts_from — откуда взяты контакты, если не из своей карты (например, 'osm' для записи 2ГИС).
ALTER TABLE places ADD COLUMN contacts_known boolean NOT NULL DEFAULT true;
ALTER TABLE places ADD COLUMN contacts_from text NOT NULL DEFAULT '';
