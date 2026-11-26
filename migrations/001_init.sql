-- Первая версия таблиц.

-- Настройки владельца: тема, ниша, город, количество, карты. Значение хранится как JSON.
CREATE TABLE settings (
    key        text PRIMARY KEY,
    value      jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Кэш геокодера: город → область OSM. Nominatim дважды об одном и том же не спрашиваем.
CREATE TABLE geo_cache (
    query      text PRIMARY KEY,
    result     jsonb NOT NULL,
    fetched_at timestamptz NOT NULL DEFAULT now()
);

-- Когда последний раз спрашивали карту про пару «ниша + город».
-- Сам ответ не храним: из него получаются нормализованные записи в places.
CREATE TABLE source_fetches (
    source     text NOT NULL,
    niche      text NOT NULL,
    city       text NOT NULL,
    fetched_at timestamptz NOT NULL DEFAULT now(),
    place_ids  bigint[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (source, niche, city)
);

-- Заведения. Одна строка на объект карты; ссылка на объект: source + ext_type + ext_id.
CREATE TABLE places (
    id            bigserial PRIMARY KEY,
    source        text NOT NULL,              -- osm, позже 2gis / yandex
    ext_type      text NOT NULL,              -- node / way / relation
    ext_id        bigint NOT NULL,
    niches        text[] NOT NULL DEFAULT '{}',
    city          text NOT NULL,
    name          text NOT NULL DEFAULT '',
    street        text NOT NULL DEFAULT '',
    housenumber   text NOT NULL DEFAULT '',
    lat           double precision,
    lon           double precision,
    phones        text[] NOT NULL DEFAULT '{}',
    website       text NOT NULL DEFAULT '',
    channels      jsonb NOT NULL DEFAULT '[]',  -- [{kind, label, value, url}]
    site_check    jsonb,                        -- признаки сайта, см. app/sitecheck.py
    site_checked_at timestamptz,
    category      text,                         -- site / card / upgrade / NULL (не подходит)
    score         integer NOT NULL DEFAULT 0,
    score_parts   jsonb NOT NULL DEFAULT '[]',  -- [{label, points}]
    status        text NOT NULL DEFAULT 'new',  -- new / work / skipped
    status_at     timestamptz,
    shown_at      timestamptz,                  -- попало в выдачу поиска
    first_seen    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source, ext_type, ext_id)
);
CREATE INDEX places_city_idx ON places (city);
CREATE INDEX places_niches_idx ON places USING gin (niches);

-- Задачи поиска. Состояние только здесь, не в памяти сервера.
CREATE TABLE jobs (
    id          bigserial PRIMARY KEY,
    niche       text NOT NULL,
    city        text NOT NULL,
    amount      integer NOT NULL,
    sources     text[] NOT NULL,
    status      text NOT NULL DEFAULT 'queued',  -- queued / running / done / error
    stage       text NOT NULL DEFAULT 'search',  -- search / check / score / done
    found       integer NOT NULL DEFAULT 0,
    to_check    integer NOT NULL DEFAULT 0,
    checked     integer NOT NULL DEFAULT 0,
    scored      integer NOT NULL DEFAULT 0,
    points      jsonb NOT NULL DEFAULT '[]',     -- [[lat, lon], ...] для экрана-радара
    center      jsonb,                           -- [lat, lon] центра города
    result_ids  bigint[] NOT NULL DEFAULT '{}',
    message     text NOT NULL DEFAULT '',
    error       text NOT NULL DEFAULT '',
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);
