"""Разбор поста: первая жирная строка вида «Исполнитель - Название (примечания)».

Три исхода на пост:
  ok    — шаблон: жирная первая строка + разделитель с пробелами. Это и есть каталог.
  maybe — разбирается как песня, но не по шаблону (не жирным или разделитель кривой).
  other — обычный пост: заметка, ссылка, анонс. В каталог не идёт.

Правила намеренно собраны в одном месте: разбор перезапускается по сохранённым
в БД постам, поэтому их можно править и прогонять `parse` заново без выкачки канала.
"""

import json
import re
import unicodedata

# Разделители исполнителя и названия — только с пробелами по бокам.
# Порядок важен: длинные варианты раньше.
SEPARATORS = (" -- ", " — ", " – ", " ‒ ", " ― ", " − ", " - ")
# Односторонний дефис («Artist- Title», «Artist -Title»). Дефис внутри слова
# («что-то», «sing-recording») сюда не попадает — именно он раньше рвал обычный текст.
ONE_SIDED_DASH = re.compile(r"(?<=\S)\s+[-—–−](?=\S)|(?<=\S)[-—–−](?=\s\S)")

NUMBERING = re.compile(r"^\s*\d{1,3}\s*[.)]\s+")
HASHTAGS = re.compile(r"^(?:#\S+\s*)+")
# Ведущий мусор: пробелы, эмодзи, стрелки, маркеры. Буквы, цифры, кавычки и скобки целы.
LEADING_SYMBOLS = re.compile(r"^[^\w(\[\"'«»]+", re.UNICODE)
TRAILING_NOTE = re.compile(r"\s*[(\[]([^()\[\]]*)[)\]]\s*$")

URL = re.compile(r"https?://|www\.", re.IGNORECASE)
# Имя и название обычно начинаются с заглавной, цифры или кавычки — а не с середины фразы.
STARTS_LIKE_NAME = re.compile(r"^[\"'(\[«]?[A-ZА-ЯЁ0-9]", re.UNICODE)

MAX_HEADER_LEN = 100   # длиннее — это предложение, а не заголовок
MAX_ARTIST_LEN = 40
MAX_TITLE_WORDS = 8    # название из десятка слов — уже фраза

QUOTES = str.maketrans({
    "«": '"', "»": '"', "“": '"', "”": '"', "„": '"', "‟": '"',
    "‘": "'", "’": "'", "‚": "'", "`": "'", "´": "'",
})
CYRILLIC = re.compile(r"[а-яёА-ЯЁ]")
LATIN = re.compile(r"[a-zA-Z]")

CATALOG_STATUSES = ("ok",)
SONG_STATUSES = ("ok", "maybe")


def utf16_len(text):
    """Длина в UTF-16 единицах — в них Telegram задаёт смещения энтити."""
    return len(text.encode("utf-16-le")) // 2


def split_first_line(text):
    """(всё до первой непустой строки, сама строка) — без хвоста поста."""
    prefix_len = 0
    for line in text.split("\n"):
        if line.strip():
            return text[:prefix_len], line
        prefix_len += len(line) + 1
    return text, ""


def header_is_bold(text, entities):
    """Покрыта ли первая непустая строка жирным хотя бы на 60%."""
    if not entities:
        return False
    prefix, line = split_first_line(text)
    if not line:
        return False
    start = utf16_len(prefix)
    end = start + utf16_len(line)
    covered = 0
    for ent in entities:
        if ent.get("type") not in ("MessageEntityBold", "MessageEntityUnderline"):
            continue
        lo = max(start, ent.get("offset", 0))
        hi = min(end, ent.get("offset", 0) + ent.get("length", 0))
        if hi > lo:
            covered += hi - lo
    return covered >= 0.6 * (end - start)


def clean_header(line):
    line = line.strip()
    line = HASHTAGS.sub("", line)
    line = LEADING_SYMBOLS.sub("", line)
    line = NUMBERING.sub("", line)
    return line.strip().strip("*_").strip()


def extract_notes(line):
    """Отрезает хвостовые (…) и […] в примечания; возвращает (строка, примечания)."""
    notes = []
    while True:
        match = TRAILING_NOTE.search(line)
        if not match:
            break
        rest = line[: match.start()].strip()
        if not rest:  # скобка — это весь заголовок, а не примечание
            break
        notes.append(match.group(1).strip())
        line = rest
    return line, "; ".join(reversed([n for n in notes if n]))


def split_artist_title(line):
    """(исполнитель, название, надёжно ли) — по первому подходящему разделителю."""
    for sep in SEPARATORS:
        if sep in line:
            artist, title = line.split(sep, 1)
            if artist.strip() and title.strip():
                return artist.strip(), title.strip(), True
    match = ONE_SIDED_DASH.search(line)
    if match:
        artist, title = line[: match.start()], line[match.end():]
        if artist.strip() and title.strip():
            return artist.strip(), title.strip(), False
    return None, None, False


def classify(header, artist, title, bold, confident):
    """('ok' | 'maybe' | 'other', причина) — по шаблону ли разобрался пост.

    Жирная строка сама по себе сильный признак, поэтому к ней применяются только
    грубые проверки. Не жирные проходят строгий фильтр: иначе обычная заметка
    с тире в предложении притворяется песней.
    """
    hard = []
    if URL.search(header):
        hard.append("ссылка в первой строке")
    if len(header) > MAX_HEADER_LEN:
        hard.append("первая строка слишком длинная")
    if len(artist) > MAX_ARTIST_LEN:
        hard.append("слишком длинное имя исполнителя")

    if bold and confident and not hard:
        return "ok", None

    soft = list(hard)
    if not STARTS_LIKE_NAME.match(artist):
        soft.append("исполнитель начинается с середины фразы")
    if not STARTS_LIKE_NAME.match(title):
        soft.append("название начинается с середины фразы")
    if title.count(" ") > MAX_TITLE_WORDS:
        soft.append("название похоже на фразу")
    if ", " in artist:
        soft.append("запятая в имени исполнителя")
    if soft:
        return "other", "; ".join(soft)

    reason = "первая строка не выделена жирным" if not bold else "разделитель без пробелов"
    return "maybe", reason


def norm_key(value):
    """Ключ группировки: регистр, кавычки, ё/е, лишние пробелы и хвостовая пунктуация."""
    value = unicodedata.normalize("NFKC", value).translate(QUOTES)
    value = value.casefold().replace("ё", "е")
    value = re.sub(r"\s+", " ", value).strip()
    value = value.strip("\"'.,!?;:-–—… ")
    value = re.sub(r"^the\s+", "", value)
    return re.sub(r"\s+", " ", value).strip()


def detect_lang(text):
    cyr = len(CYRILLIC.findall(text))
    lat = len(LATIN.findall(text))
    total = cyr + lat
    if total < 10:
        return ""
    if cyr > 0.8 * total:
        return "ru"
    if lat > 0.8 * total:
        return "en"
    return "mixed"


def parse_message(text, entities=None):
    """Разбирает текст поста. Всегда возвращает dict со статусом — не бросает."""
    result = {
        "header": None, "body": "", "artist": None, "title": None,
        "notes": "", "lang": "", "status": "empty", "note": None,
    }
    if not text or not text.strip():
        return result

    prefix, raw_header = split_first_line(text)
    body = text[len(prefix) + len(raw_header):].strip("\n")
    result["body"] = body
    result["lang"] = detect_lang(body or text)

    header = clean_header(raw_header)
    if not header:
        result["status"] = "other"
        result["note"] = "первая строка пустая после чистки"
        return result
    result["header"] = header

    bold = header_is_bold(text, entities)
    core, notes = extract_notes(header)
    artist, title, confident = split_artist_title(core)
    if not artist:
        result["status"] = "other"
        result["note"] = "нет разделителя «исполнитель - название»"
        return result

    status, note = classify(header, artist, title, bold, confident)
    result["status"] = status
    result["note"] = note
    if status != "other":
        result["artist"] = artist
        result["title"] = title
        result["notes"] = notes
    return result


def reparse_all(conn, verbose=True):
    """Пересобирает tracks/appearances с нуля по сохранённым постам."""
    conn.execute("DELETE FROM appearances")
    conn.execute("DELETE FROM tracks")

    stats = {}
    rows = conn.execute(
        "SELECT msg_id, date_utc, text, entities FROM messages ORDER BY msg_id"
    ).fetchall()
    for row in rows:
        entities = json.loads(row["entities"]) if row["entities"] else []
        parsed = parse_message(row["text"], entities)
        stats[parsed["status"]] = stats.get(parsed["status"], 0) + 1
        conn.execute(
            "UPDATE messages SET header = ?, body = ?, lang = ?, parse_status = ?, "
            "parse_note = ? WHERE msg_id = ?",
            (parsed["header"], parsed["body"], parsed["lang"], parsed["status"],
             parsed["note"], row["msg_id"]),
        )
        if not parsed["artist"]:
            continue

        artist_key = norm_key(parsed["artist"])
        title_key = norm_key(parsed["title"])
        if not artist_key or not title_key:
            continue
        conn.execute(
            "INSERT INTO tracks(artist_raw, artist_key, title_raw, title_key) "
            "VALUES(?,?,?,?) ON CONFLICT(artist_key, title_key) DO NOTHING",
            (parsed["artist"], artist_key, parsed["title"], title_key),
        )
        track_id = conn.execute(
            "SELECT id FROM tracks WHERE artist_key = ? AND title_key = ?",
            (artist_key, title_key),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO appearances(track_id, msg_id, date_utc, notes, confidence) "
            "VALUES(?,?,?,?,?) ON CONFLICT(track_id, msg_id) DO UPDATE SET "
            "notes = excluded.notes, confidence = excluded.confidence",
            (track_id, row["msg_id"], row["date_utc"], parsed["notes"] or None,
             parsed["status"]),
        )
    conn.commit()
    if verbose:
        titles = {
            "ok": "в каталог", "maybe": "похоже на песню",
            "other": "прочие посты", "empty": "пустые",
        }
        for status in ("ok", "maybe", "other", "empty"):
            if stats.get(status):
                print(f"  {titles[status]:18} {stats[status]}")
    return stats


def dry_run(conn, sample=30, status=None):
    """Печатает разбор нескольких постов, ничего не записывая в БД."""
    sql = "SELECT msg_id, date_utc, text, entities FROM messages"
    params = []
    if status:
        sql += " WHERE parse_status = ?"
        params.append(status)
    sql += " ORDER BY msg_id DESC LIMIT ?"
    params.append(sample)
    rows = conn.execute(sql, params).fetchall()
    if not rows:
        print("Подходящих постов нет — сначала запустите fetch.")
        return
    for row in rows:
        entities = json.loads(row["entities"]) if row["entities"] else []
        parsed = parse_message(row["text"], entities)
        note = f"  ({parsed['note']})" if parsed["note"] else ""
        print(f"\n#{row['msg_id']}  {row['date_utc'][:10]}  [{parsed['status']}]{note}")
        print(f"  заголовок  : {parsed['header']}")
        if parsed["artist"]:
            print(f"  исполнитель: {parsed['artist']}")
            print(f"  название   : {parsed['title']}")
        if parsed["notes"]:
            print(f"  примечания : {parsed['notes']}")
