-- Несколько ниш и городов в одном поиске.

ALTER TABLE jobs ADD COLUMN niches text[] NOT NULL DEFAULT '{}';
ALTER TABLE jobs ADD COLUMN cities text[] NOT NULL DEFAULT '{}';
UPDATE jobs SET niches = ARRAY[niche], cities = ARRAY[city];
-- старые одиночные поля больше не заполняются
ALTER TABLE jobs ALTER COLUMN niche DROP NOT NULL;
ALTER TABLE jobs ALTER COLUMN city DROP NOT NULL;

-- Настройки: одиночный выбор → список.
INSERT INTO settings(key, value)
SELECT 'niches', jsonb_build_array(value) FROM settings WHERE key = 'niche'
ON CONFLICT (key) DO NOTHING;
INSERT INTO settings(key, value)
SELECT 'cities', jsonb_build_array(value) FROM settings WHERE key = 'city'
ON CONFLICT (key) DO NOTHING;
DELETE FROM settings WHERE key IN ('niche', 'city');
