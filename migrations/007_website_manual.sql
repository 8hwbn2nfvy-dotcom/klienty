-- Адрес сайта, который владелец нашёл и вписал сам («Сайт есть»).
-- Карта его не знает, поэтому новый поиск не должен его затирать.
ALTER TABLE places ADD COLUMN website_manual text NOT NULL DEFAULT '';
