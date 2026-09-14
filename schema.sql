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
  fetched_at      TEXT,
  concert_id      TEXT REFERENCES concerts(id) ON DELETE SET NULL,  -- по окну дат, ставит match
  hidden          INTEGER NOT NULL DEFAULT 0  -- 1 = руками помечено «не с концерта»
);
CREATE INDEX IF NOT EXISTS idx_videos_date ON videos(date_utc);
CREATE INDEX IF NOT EXISTS idx_videos_group ON videos(grouped_id);
CREATE INDEX IF NOT EXISTS idx_videos_concert ON videos(concert_id);

-- Привязка видео к песне сетлиста. manual — поставлено руками, match её не трогает.
CREATE TABLE IF NOT EXISTS matches (
  msg_id     INTEGER NOT NULL REFERENCES videos(msg_id) ON DELETE CASCADE,
  track_id   TEXT NOT NULL REFERENCES setlist(id) ON DELETE CASCADE,
  confidence TEXT NOT NULL,           -- ok | maybe | manual
  source     TEXT,                    -- caption | album | reply | manual
  PRIMARY KEY (msg_id, track_id)
);
CREATE INDEX IF NOT EXISTS idx_matches_track ON matches(track_id);
