-- 2ГИС: учёт запросов (у демо-ключа лимит 1000) и склейка одного заведения из двух карт.

CREATE TABLE api_usage (
    source   text NOT NULL,
    day      date NOT NULL,
    requests integer NOT NULL DEFAULT 0,
    PRIMARY KEY (source, day)
);

-- Если то же заведение нашлось в двух картах, запись OSM указывает на запись 2ГИС
-- и в список и выдачу не попадает: контакты 2ГИС свежее.
ALTER TABLE places ADD COLUMN merged_into bigint REFERENCES places(id) ON DELETE SET NULL;
CREATE INDEX places_merged_idx ON places (merged_into);
