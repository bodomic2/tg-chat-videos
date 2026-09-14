-- Сырые посты: источник правды, заполняется fetch'ем.
CREATE TABLE IF NOT EXISTS messages (
  msg_id       INTEGER PRIMARY KEY,
  date_utc     TEXT NOT NULL,          -- ISO8601, UTC
  text         TEXT NOT NULL,
  entities     TEXT,                   -- JSON: [{"type","offset","length"}] в UTF-16 единицах
  link         TEXT,
  header       TEXT,                   -- выделенная первая строка, как есть
  body         TEXT,                   -- остальной текст поста
  lang         TEXT,                   -- ru | en | mixed | ''
  parse_status TEXT NOT NULL DEFAULT 'new',  -- ok | maybe | other | empty
  parse_note   TEXT,
  fetched_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_status ON messages(parse_status);

-- Уникальная песня: пара (исполнитель, название) по нормализованным ключам.
CREATE TABLE IF NOT EXISTS tracks (
  id         INTEGER PRIMARY KEY,
  artist_raw TEXT NOT NULL,
  artist_key TEXT NOT NULL,
  title_raw  TEXT NOT NULL,
  title_key  TEXT NOT NULL,
  UNIQUE(artist_key, title_key)
);
CREATE INDEX IF NOT EXISTS idx_tracks_artist ON tracks(artist_key);

-- Исполнение: по строке на пост. Повтор песни = ещё одна строка здесь.
CREATE TABLE IF NOT EXISTS appearances (
  track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
  msg_id   INTEGER NOT NULL REFERENCES messages(msg_id) ON DELETE CASCADE,
  date_utc TEXT NOT NULL,
  notes    TEXT,
  confidence TEXT NOT NULL DEFAULT 'ok',   -- ok = по шаблону, maybe = похоже на песню
  PRIMARY KEY (track_id, msg_id)
);
CREATE INDEX IF NOT EXISTS idx_appearances_date ON appearances(date_utc);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
