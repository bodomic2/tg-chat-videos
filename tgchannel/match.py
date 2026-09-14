"""Привязка видео к концерту и песне из его сетлиста.

Концерт — по дате: видео относится к последнему концерту, который был не позже
него (окно [дата концерта, дата следующего)). Песня — по тексту: подпись видео,
подписи соседей по альбому, текст сообщения, на которое видео отвечает.

Сравнение нечёткое, по токенам: «Disturbed- Down With a Sickness» должно
находить «Down with the Sickness». Название ищется как окно токенов в тексте
с порогом схожести; исполнитель — по значимым токенам. Исходы:

  ok     — совпали название и исполнитель, либо одно достаточно длинное название;
  maybe  — только исполнитель, и у него в этом сетлисте ровно одна песня;
  (нет)  — видео остаётся в подвале концерта.

Видео с концерта выкладывают в первые день-два, дальше в окне идёт шум: джемы,
анонсы, чужие клипы. Поэтому maybe засчитывается только в первые NEAR_DAYS дней
(иначе анонс «Кис-Кис в субботу» привяжется к прошлому концерту), а в подвал
попадают только неподписанные видео этих же дней. ok по названию — в любой день.

Ручные привязки (confidence = manual) при перепрогоне не трогаются.
"""

import difflib
import re
import unicodedata

from .text import QUOTES

TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
PARENS = re.compile(r"\s*[(\[][^()\[\]]*[)\]]")
STOPWORDS = {
    "a", "an", "the", "of", "and", "or", "in", "on", "at", "to", "for", "by", "with",
    "feat", "ft", "vs", "cover", "version", "live", "remix", "this", "that", "it", "is",
    "и", "в", "на", "с", "из", "не", "по", "у", "о", "от", "за", "для",
}
TITLE_RATIO = 0.82     # схожесть окна текста с названием
ARTIST_RATIO = 0.85
MIN_TITLE_ALONE = 2    # токенов в названии, чтобы верить ему без исполнителя
MIN_TITLE_ALONE_LEN = 6  # или символов, если токен один
NEAR_DAYS = 7          # дней после концерта, пока видео ещё «с концерта»
# «10 - Ghost (…)» — номер песни в сетлисте перед названием
NUMBERED = re.compile(r"^\s*#?(\d{1,2})\s*[.)\-–—:]\s*(\S.*)")


def normalize(text):
    text = unicodedata.normalize("NFKC", text or "").translate(QUOTES)
    return text.casefold().replace("ё", "е")


def tokens(text):
    return TOKEN.findall(normalize(text))


def key_tokens(text):
    """Значимые токены: без стоп-слов и однобуквенных, кроме случая, когда иначе пусто."""
    toks = tokens(text)
    keep = [t for t in toks if t not in STOPWORDS and len(t) > 1]
    return keep or toks


def strip_parens(title):
    """«Rollin' (Air raid vehicle)» → «Rollin'» — в подписях скобки не пишут."""
    return PARENS.sub("", title).strip() or title


def window_ratio(needle, haystack):
    """Лучшая схожесть needle (список токенов) с окном той же длины в haystack."""
    n = len(needle)
    if not n or len(haystack) < n:
        return 0.0
    target = " ".join(needle)
    best = 0.0
    for i in range(len(haystack) - n + 1):
        ratio = difflib.SequenceMatcher(None, target, " ".join(haystack[i:i + n])).ratio()
        if ratio > best:
            best = ratio
            if best == 1.0:
                break
    return best


def match_title(title, text_key):
    return window_ratio(key_tokens(strip_parens(title)), text_key) >= TITLE_RATIO


def match_artist_strong(artist, text_key):
    """Имя целиком (нечётко) или однословный исполнитель — этого хватает и без названия."""
    art = key_tokens(artist)
    if not art:
        return False
    if len(art) == 1:
        return art[0] in set(text_key)
    return window_ratio(art, text_key) >= ARTIST_RATIO


def match_artist_weak(artist, text_key):
    """Любой заметный токен имени — годится только как подтверждение к найденному названию."""
    text_set = set(text_key)
    return any(len(t) > 3 and t in text_set for t in key_tokens(artist))


def title_stands_alone(title):
    toks = key_tokens(strip_parens(title))
    return len(toks) >= MIN_TITLE_ALONE or (toks and len(toks[0]) >= MIN_TITLE_ALONE_LEN)


def match_by_number(text, tracks):
    """Подпись с номером сетлиста: трек на этой позиции, если название совпало."""
    m = NUMBERED.match(text)
    if not m:
        return None
    position, rest = int(m.group(1)), m.group(2)
    for track in tracks:
        if track["position"] == position and match_title(track["title"], key_tokens(rest)):
            return track
    return None


def match_tracks(text, tracks):
    """[(track, confidence)] для текста среди треков одного концерта."""
    numbered = match_by_number(text, tracks)
    if numbered:
        return [(numbered, "ok")]
    text_key = key_tokens(text)
    if not text_key:
        return []
    found = []
    artist_only = []
    for track in tracks:
        by_title = match_title(track["title"], text_key)
        if by_title and (match_artist_weak(track["artist"], text_key) or title_stands_alone(track["title"])):
            found.append((track, "ok"))
        elif not by_title and match_artist_strong(track["artist"], text_key):
            artist_only.append(track)
    if found:
        return found
    # только исполнитель: годится, если у него в этом сетлисте одна песня
    by_artist = {}
    for track in artist_only:
        by_artist.setdefault(track["artist_key"], []).append(track)
    return [(ts[0], "maybe") for ts in by_artist.values() if len(ts) == 1]


def concert_windows(conn):
    """[(concert_id, date_from, date_to|None)] по возрастанию даты."""
    rows = conn.execute("SELECT id, date FROM concerts ORDER BY date, id").fetchall()
    windows = []
    for i, row in enumerate(rows):
        nxt = rows[i + 1]["date"] if i + 1 < len(rows) else None
        windows.append((row["id"], row["date"], nxt))
    return windows


def assign_concerts(conn):
    """Проставляет videos.concert_id по окну дат."""
    conn.execute("UPDATE videos SET concert_id = NULL")
    for concert_id, date_from, date_to in concert_windows(conn):
        if date_to:
            conn.execute(
                "UPDATE videos SET concert_id = ? WHERE date_utc >= ? AND date_utc < ?",
                (concert_id, date_from, date_to),
            )
        else:
            conn.execute("UPDATE videos SET concert_id = ? WHERE date_utc >= ?", (concert_id, date_from))


def video_texts(conn, video):
    """Тексты, по которым искать песню, в порядке доверия: (источник, текст)."""
    out = []
    if video["caption"].strip():
        out.append(("caption", video["caption"]))
    if video["grouped_id"] is not None:
        for row in conn.execute(
            "SELECT caption FROM videos WHERE grouped_id = ? AND msg_id != ? AND caption != ''",
            (video["grouped_id"], video["msg_id"]),
        ):
            out.append(("album", row["caption"]))
    if (video["reply_text"] or "").strip():
        out.append(("reply", video["reply_text"]))
    return out


VIDEO_SQL = (
    "SELECT v.msg_id, v.concert_id, v.caption, v.grouped_id, v.reply_text, v.hidden, "
    "       julianday(v.date_utc) - julianday(c.date) AS days "
    "FROM videos v JOIN concerts c ON c.id = v.concert_id "
)


def is_near(video):
    return video["days"] < NEAR_DAYS


def match_video(conn, video, tracks):
    """[(track, confidence, source)] для одного видео среди треков его концерта."""
    near = is_near(video)
    for source, text in video_texts(conn, video):
        hits = [(t, conf, source) for t, conf in match_tracks(text, tracks) if conf == "ok" or near]
        if hits:
            return hits
    return []


def setlists_by_concert(conn):
    setlists = {}
    for row in conn.execute("SELECT id, concert_id, position, artist, title, artist_key FROM setlist"):
        setlists.setdefault(row["concert_id"], []).append(row)
    return setlists


def store_hits(conn, msg_id, hits):
    conn.executemany(
        "INSERT OR IGNORE INTO matches(msg_id, track_id, confidence, source) VALUES(?,?,?,?)",
        [(msg_id, track["id"], confidence, source) for track, confidence, source in hits],
    )


def rematch_video(conn, msg_id):
    """Автопривязка одного видео заново (после сброса ручной правки)."""
    conn.execute("DELETE FROM matches WHERE msg_id = ?", (msg_id,))
    video = conn.execute(VIDEO_SQL + "WHERE v.msg_id = ?", (msg_id,)).fetchone()
    if video is None or video["hidden"]:
        return []
    tracks = [r for r in setlists_by_concert(conn).get(video["concert_id"], [])]
    hits = match_video(conn, video, tracks)
    store_hits(conn, msg_id, hits)
    return hits


def run(conn):
    """Пересчитывает автоматические привязки. Ручные и скрытые остаются."""
    assign_concerts(conn)
    conn.execute("DELETE FROM matches WHERE confidence != 'manual'")
    manual = {r["msg_id"] for r in conn.execute("SELECT msg_id FROM matches WHERE confidence = 'manual'")}
    setlists = setlists_by_concert(conn)

    stats = {"videos": 0, "ok": 0, "maybe": 0, "unmatched": 0, "manual": 0, "hidden": 0, "far": 0}
    for video in conn.execute(VIDEO_SQL + "ORDER BY v.msg_id").fetchall():
        stats["videos"] += 1
        if video["msg_id"] in manual:
            stats["manual"] += 1
            continue
        if video["hidden"]:
            stats["hidden"] += 1
            continue
        hits = match_video(conn, video, setlists.get(video["concert_id"], []))
        if not hits:
            stats["unmatched" if is_near(video) else "far"] += 1
            continue
        store_hits(conn, video["msg_id"], hits)
        stats[hits[0][1]] += 1
    conn.commit()
    print(
        f"Видео в окнах концертов: {stats['videos']}; привязано: {stats['ok']} ok, "
        f"{stats['maybe']} maybe, {stats['manual']} вручную; скрыто: {stats['hidden']}; "
        f"в подвале: {stats['unmatched']}; поздних без привязки (не показываем): {stats['far']}."
    )
    return stats
