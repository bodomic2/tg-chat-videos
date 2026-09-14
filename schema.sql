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

-- Концерты с thejammers.org/archive. raw_json — треки как отдал сайт, для пересборки.
CREATE TABLE IF NOT EXISTS concerts (
  id          TEXT PRIMARY KEY,      -- id события на сайте
  date        TEXT NOT NULL,         -- YYYY-MM-DD
  time        TEXT,
  title       TEXT NOT NULL,
  venue       TEXT,
  url         TEXT NOT NULL,
  track_count INTEGER,
  raw_json    TEXT NOT NULL,
  fetched_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_concerts_date ON concerts(date);

-- Сетлист: по строке на трек концерта, в порядке сайта.
CREATE TABLE IF NOT EXISTS setlist (
  id         TEXT PRIMARY KEY,       -- id трека на сайте
  concert_id TEXT NOT NULL REFERENCES concerts(id) ON DELETE CASCADE,
  position   INTEGER NOT NULL,
  artist     TEXT NOT NULL,
  title      TEXT NOT NULL,
  artist_key TEXT NOT NULL,
  title_key  TEXT NOT NULL,
  state      TEXT,
  ready      INTEGER NOT NULL DEFAULT 0,  -- 1 = все обязательные места заняты
  comment    TEXT
);
CREATE INDEX IF NOT EXISTS idx_setlist_concert ON setlist(concert_id, position);
CREATE INDEX IF NOT EXISTS idx_setlist_keys ON setlist(artist_key, title_key);

-- Сообщения чата с видео: источник правды, заполняется fetch'ем.
CREATE TABLE IF NOT EXISTS videos (
  msg_id          INTEGER PRIMARY KEY,
  date_utc        TEXT NOT NULL,      -- ISO8601, UTC
  caption         TEXT NOT NULL DEFAULT '',
  link            TEXT NOT NULL,
  grouped_id      INTEGER,            -- альбом: несколько видео с одной подписью
  reply_to_msg_id INTEGER,
  reply_text      TEXT,               -- текст сообщения, на которое отвечает видео
  duration        INTEGER,            -- секунд
  fetched_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_videos_date ON videos(date_utc);
CREATE INDEX IF NOT EXISTS idx_videos_group ON videos(grouped_id);
