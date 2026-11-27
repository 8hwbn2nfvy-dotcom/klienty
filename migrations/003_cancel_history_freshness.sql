-- Отмена поиска, категории как условие поиска, свежесть данных карты.

ALTER TABLE jobs ADD COLUMN categories text[] NOT NULL DEFAULT '{site,card,upgrade}';
ALTER TABLE jobs ADD COLUMN cancel_requested boolean NOT NULL DEFAULT false;
-- на какую дату были данные карты у сервера, который ответил (самая старая из пар «ниша + город»)
ALTER TABLE jobs ADD COLUMN map_data_at timestamptz;

-- когда запись об объекте последний раз правили или проверяли на карте
ALTER TABLE places ADD COLUMN source_updated_at timestamptz;
