"""Концерты и сетлисты с thejammers.org.

Сайт на Next.js: список концертов (/archive) отрендерен в HTML, а на странице
концерта (/events/<id>) треки и состав лежат в RSC-потоке — кусках
`self.__next_f.push([1,"…"])`, из которых собирается JSON. Оттуда берём
исполнителя, название, занятость мест (готов ли трек) и состав — кто на каком
месте, чтобы искать видео по музыканту.

Сырой JSON треков сохраняется в concerts.raw_json, так что разбор можно
перегнать без повторной выкачки: `concerts --reparse`.

setlist_overrides.json: для концерта, у которого на доске сайта лежат все
предложения, а не то, что сыграли, — список «Исполнитель — Название» по порядку.
Остаются только эти треки, в этом порядке; применяется при каждой загрузке.
"""

import difflib
import html
import json
import re
import time
import urllib.request
from datetime import datetime, timezone

from . import config
from .text import norm_key

BASE = "https://thejammers.org"
ARCHIVE_URL = BASE + "/archive"
USER_AGENT = "tg-chat-videos/0.1 (+https://github.com/bodomic)"
PAUSE = 0.5  # секунд между запросами к сайту

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Вёрстка архива с ноября 2026 (до этого строки были <a><div>дата</div><h2>…</h2><p>…</p></a>):
# <li data-archive-row="true"> — одна строка на концерт, внутри десктопная и мобильная версии.
#   <span>13 Dec</span><span>2026 · Sun</span>                         дата
#   <a data-archive-row-title="true" href="/events/ID">Название</a>   название; у концерта без
#                                                                      своего названия — «The Jammers · 13 December 2026»
#   <span data-archive-row-meta="true">Music Hall · 19:00</span>       площадка · время
#   <span>24 songs</span>                                              число треков
# Предстоящие концерты лежат в <section data-archive-upcoming="true">: на их страницах доска
# с предложениями, а не сыгранный сетлист, так что их не качаем (известные концерты потом
# не перекачиваются, снимок «до концерта» остался бы навсегда).
ARCHIVE_UPCOMING = re.compile(r'<section[^>]*data-archive-upcoming="true".*?</section>', re.DOTALL)
ARCHIVE_ROW = re.compile(r'<li [^>]*data-archive-row="true"[^>]*>(?P<row>.*?)</li>', re.DOTALL)
# Год в блоке даты бывает только у предстоящих; у архивных — один день недели («Sun»).
ARCHIVE_DATE = re.compile(r"<span[^>]*>(?P<dm>\d{1,2} [A-Za-z]+)</span><span[^>]*>(?:(?P<year>\d{4}) · )?(?P<wd>[A-Za-z]{3})</span>")
TITLE_DATE = re.compile(r"\d{1,2} [A-Za-z]+ (?P<year>\d{4})")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
ARCHIVE_TITLE = re.compile(
    r'<a [^>]*data-archive-row-title="true"[^>]*href="/events/(?P<id>[a-z0-9]+)"[^>]*>(?P<title>[^<]*)</a>'
    r'<span[^>]*data-archive-row-meta="true"[^>]*>(?P<meta>[^<]*)</span>'
)
ARCHIVE_SONGS = re.compile(r">(?P<n>\d+) songs?<")
TIME_ONLY = re.compile(r"\d{1,2}:\d{2}")
RSC_CHUNK = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')
RSC_LINE = re.compile(r"^[0-9a-f]+:(?=[\[{])")


def fetch_url(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8")


def _clean(text):
    return html.unescape(re.sub(r"<!--.*?-->", "", text)).strip()


def parse_date(text):
    """«14 Sept 2025» → «2025-09-14»."""
    day, month, year = text.split()
    return f"{int(year):04d}-{MONTHS[month.lower().rstrip('.')]:02d}-{int(day):02d}"


def _fill_years(rows):
    """Год каждой строки: из блока даты, из сгенерированного названия, иначе — из соседей.

    У архивных строк года нет, только день недели. Концерт без своего названия несёт полную дату в
    названии; у остальных год выбираем среди годов соседних строк (список идёт от новых к старым,
    так что год не может выйти за границы соседей) так, чтобы совпал день недели. Если однозначно
    не вышло — ошибка: неверная дата хуже отсутствующей, концерт записался бы в базу навсегда."""
    for r in rows:
        r["year"] = r["year"] or r["title_year"]
    for i, r in enumerate(rows):
        if r["year"]:
            continue
        above = next((x["year"] for x in reversed(rows[:i]) if x["year"]), None)
        below = next((x["year"] for x in rows[i + 1:] if x["year"]), None)
        known = [y for y in (above, below) if y]
        if not known:
            raise ValueError(f"не определить год концерта {r['id']}: ни у одной строки нет года")
        fits = [y for y in range(min(known), max(known) + 1)
                if WEEKDAYS[datetime(y, r["month"], r["day"]).weekday()] == r["wd"]]
        if len(fits) != 1:
            raise ValueError(f"не определить год концерта {r['id']}: подходят годы {fits} ({r['day']}.{r['month']} {r['wd']})")
        r["year"] = fits[0]
    for r in rows:
        if WEEKDAYS[datetime(r["year"], r["month"], r["day"]).weekday()] != r["wd"]:
            raise ValueError(f"день недели не сходится с датой у концерта {r['id']}: {r['day']}.{r['month']}.{r['year']} {r['wd']}")


def parse_archive(page):
    """Список концертов со страницы архива, в порядке сайта (новые сверху)."""
    rows = []
    for m in ARCHIVE_ROW.finditer(ARCHIVE_UPCOMING.sub("", page)):
        row = m.group("row")
        d, t, s = ARCHIVE_DATE.search(row), ARCHIVE_TITLE.search(row), ARCHIVE_SONGS.search(row)
        if not (d and t and s):
            # Строку, которую не разобрали, нельзя молча пропустить: концерт выпал бы из архива навсегда.
            raise ValueError(f"строка архива не разобралась (вёрстка снова поменялась?): {_clean(row)[:120]!r}")
        day, month = d.group("dm").split()
        title, meta = _clean(t.group("title")), _clean(t.group("meta"))
        # Сгенерированное название «The Jammers · 13 December 2026»: дата в нём лишняя (она в поле date),
        # но из неё берём год.
        title_year = None
        head, sep, tail = title.rpartition(" · ")
        if sep and (td := TITLE_DATE.fullmatch(tail)):
            title, title_year = head, int(td.group("year"))
        venue, sep, time_ = meta.rpartition(" · ")
        if not sep:  # в мете только время (или только площадка)
            venue, time_ = (None, meta) if TIME_ONLY.fullmatch(meta) else (meta or None, "")
        rows.append({
            "id": t.group("id"), "day": int(day), "month": MONTHS[month.lower().rstrip(".")], "wd": d.group("wd"),
            "year": int(d.group("year")) if d.group("year") else None, "title_year": title_year,
            "time": time_.strip() or None, "title": title, "venue": venue, "track_count": int(s.group("n")),
        })
    _fill_years(rows)
    return [{
        "id": r["id"],
        "date": f"{r['year']:04d}-{r['month']:02d}-{r['day']:02d}",
        "time": r["time"],
        "title": r["title"],
        "venue": r["venue"],
        "url": f"{BASE}/events/{r['id']}",
        "track_count": r["track_count"],
    } for r in rows]


def rsc_stream(page):
    """Склеивает куски RSC-потока со страницы в один текст."""
    return "".join(json.loads('"' + c + '"') for c in RSC_CHUNK.findall(page))


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def extract_tracks(page):
    """Список треков (как их отдаёт сайт) из страницы концерта.

    Ищем в RSC-потоке объект с полем tracks, где у элементов есть song —
    это props доски концерта. Порядок треков — trackNumbers из тех же props.
    """
    for line in rsc_stream(page).split("\n"):
        if not RSC_LINE.match(line):
            continue
        try:
            data = json.loads(line.split(":", 1)[1])
        except json.JSONDecodeError:
            continue
        for obj in _walk(data):
            tracks = obj.get("tracks")
            if isinstance(tracks, list) and tracks and isinstance(tracks[0], dict) and "song" in tracks[0]:
                numbers = obj.get("trackNumbers") or {}
                return sorted(tracks, key=lambda t: numbers.get(t["id"], 10**6))
    raise ValueError("на странице не нашлось треков")


def flatten_track(track, position):
    """Одна запись сетлиста + состав из сырого трека сайта.

    ready = все обязательные места заняты (необязательные и закрытые не считаются).
    В состав идут только занятые места с известным пользователем.
    """
    song = track["song"]
    artist = ((song.get("artist") or {}).get("name") or "").strip()
    title = (song.get("title") or "").strip()
    seats = track.get("seats") or []
    required = [s.get("status") for s in seats if not s.get("isOptional") and s.get("status") != "UNAVAILABLE"]
    lineup = []
    for seat in seats:
        user = seat.get("user") or {}
        if seat.get("status") != "CLAIMED" or not user.get("telegramUsername"):
            continue  # без ника музыканта не найти и не сослаться
        slot = seat.get("lineupSlot") or {}
        lineup.append({
            "id": seat["id"],
            "slot": slot.get("key") or "",
            "label": seat.get("label") or slot.get("label") or "",
            "username": user.get("telegramUsername"),
            "full_name": user.get("fullName"),
        })
    return {
        "id": track["id"],
        "position": position,
        "artist": artist,
        "title": title,
        "artist_key": norm_key(artist),
        "title_key": norm_key(title),
        "state": track.get("state"),
        "ready": int(bool(required) and all(st == "CLAIMED" for st in required)),
        "comment": track.get("comment"),
        "lineup": lineup,
    }


def store_concert(conn, concert, raw_tracks, fetched_at):
    conn.execute(
        "INSERT INTO concerts(id, date, time, title, venue, url, track_count, raw_json, fetched_at) "
        "VALUES(?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET date = excluded.date, time = excluded.time, "
        "title = excluded.title, venue = excluded.venue, url = excluded.url, "
        "track_count = excluded.track_count, raw_json = excluded.raw_json, "
        "fetched_at = excluded.fetched_at",
        (
            concert["id"], concert["date"], concert["time"], concert["title"],
            concert["venue"], concert["url"], concert["track_count"],
            json.dumps(raw_tracks, ensure_ascii=False), fetched_at,
        ),
    )
    store_setlist(conn, concert["id"], raw_tracks)


def load_overrides():
    if not config.SETLIST_OVERRIDES.exists():
        return {}
    data = json.loads(config.SETLIST_OVERRIDES.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def apply_override(tracks, wanted, concert_id):
    """Оставляет из tracks только строки wanted («Исполнитель — Название»), в их порядке."""
    by_key = {f"{t['artist_key']} — {t['title_key']}": t for t in tracks}
    kept, used = [], set()
    for line in wanted:
        artist, _, title = line.partition("—")
        key = f"{norm_key(artist)} — {norm_key(title)}"
        track = by_key.get(key)
        if track is None:  # мелкие расхождения: регистр уже снят, остаются опечатки/скобки
            free = [k for k, t in by_key.items() if t["id"] not in used]
            close = difflib.get_close_matches(key, free, n=1, cutoff=0.8)
            track = by_key[close[0]] if close else None
        if track is None or track["id"] in used:
            print(f"  ! {concert_id}: в сетлисте сайта не нашлось «{line.strip()}»")
            continue
        used.add(track["id"])
        kept.append(dict(track, position=len(kept) + 1))
    return kept


def store_setlist(conn, concert_id, raw_tracks):
    """Обновляет сетлист и состав концерта из сырого JSON.

    Треки обновляются по id (он у сайта стабильный), а не удаляются и вставляются
    заново: на setlist ссылаются matches, и DELETE снёс бы ручные привязки.
    Удаляются только треки, которых больше нет (на сайте или в overrides).
    """
    tracks = [flatten_track(raw, pos) for pos, raw in enumerate(raw_tracks, 1)]
    wanted = load_overrides().get(concert_id)
    if wanted:
        tracks = apply_override(tracks, wanted, concert_id)
    conn.executemany(
        "INSERT INTO setlist(id, concert_id, position, artist, title, artist_key, title_key, "
        "state, ready, comment) VALUES(?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET concert_id = excluded.concert_id, "
        "position = excluded.position, artist = excluded.artist, title = excluded.title, "
        "artist_key = excluded.artist_key, title_key = excluded.title_key, "
        "state = excluded.state, ready = excluded.ready, comment = excluded.comment",
        [(t["id"], concert_id, t["position"], t["artist"], t["title"],
          t["artist_key"], t["title_key"], t["state"], t["ready"], t["comment"]) for t in tracks],
    )
    ids = [t["id"] for t in tracks]
    marks = ",".join("?" * len(ids)) or "''"
    conn.execute(f"DELETE FROM setlist WHERE concert_id = ? AND id NOT IN ({marks})", [concert_id, *ids])
    conn.execute(
        "DELETE FROM lineup WHERE track_id IN (SELECT id FROM setlist WHERE concert_id = ?)", (concert_id,)
    )
    conn.executemany(
        "INSERT INTO lineup(id, track_id, slot, label, username, full_name) VALUES(?,?,?,?,?,?)",
        [(m["id"], t["id"], m["slot"], m["label"], m["username"], m["full_name"])
         for t in tracks for m in t["lineup"]],
    )


def run(conn, force=False):
    """Скачивает архив и страницы концертов, которых ещё нет в базе (все — с force)."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    concerts = parse_archive(fetch_url(ARCHIVE_URL))
    if not concerts:
        raise SystemExit("Архив не разобрался: список концертов пуст — сайт поменял вёрстку?")
    known = {r["id"] for r in conn.execute("SELECT id FROM concerts")}
    print(f"На сайте {len(concerts)} концертов, в базе {len(known)}.")

    fetched = 0
    for concert in reversed(concerts):  # от старых к новым
        if concert["id"] in known and not force:
            continue
        page = fetch_url(concert["url"])
        raw_tracks = extract_tracks(page)
        store_concert(conn, concert, raw_tracks, now)
        conn.commit()
        fetched += 1
        print(f"  {concert['date']}  {concert['title']}: {len(raw_tracks)} треков")
        time.sleep(PAUSE)
    print(f"Готово: скачано {fetched} концертов.")
    return fetched


def reparse(conn):
    """Пересобирает setlist из сохранённого raw_json без обращения к сайту."""
    rows = conn.execute("SELECT id, raw_json FROM concerts").fetchall()
    for row in rows:
        store_setlist(conn, row["id"], json.loads(row["raw_json"]))
    conn.commit()
    print(f"Пересобрано {len(rows)} концертов.")
