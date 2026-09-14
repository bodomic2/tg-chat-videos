"""Концерты и сетлисты с thejammers.org.

Сайт на Next.js: список концертов (/archive) отрендерен в HTML, а на странице
концерта (/events/<id>) треки и состав лежат в RSC-потоке — кусках
`self.__next_f.push([1,"…"])`, из которых собирается JSON. Оттуда берём
исполнителя, название, состояние трека и кто на каком месте сидит (telegram-ник).

Сырой JSON треков сохраняется в concerts.raw_json, так что разбор можно
перегнать без повторной выкачки: `concerts --reparse`.
"""

import html
import json
import re
import time
import urllib.request
from datetime import datetime, timezone

from .parse import norm_key

BASE = "https://thejammers.org"
ARCHIVE_URL = BASE + "/archive"
USER_AGENT = "tg-chat-videos/0.1 (+https://github.com/bodomic)"
PAUSE = 0.5  # секунд между запросами к сайту

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# <a href="/events/ID"><div>28 Jun 2026</div><div><h2>Music Hall</h2><p>16:00 · Title</p></div>
# Если площадки нет, в <h2> лежит название, а в <p> только время.
ARCHIVE_ITEM = re.compile(
    r'<a [^>]*href="/events/(?P<id>[a-z0-9]+)"[^>]*>'
    r"<div[^>]*>(?P<date>[^<]+)</div>"
    r"<div[^>]*><h2[^>]*>(?P<h2>[^<]+)</h2><p[^>]*>(?P<p>.*?)</p></div>"
    r".*?<span[^>]*>(?P<tracks>\d+)<!-- -->",
    re.DOTALL,
)
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


def parse_archive(page):
    """Список концертов со страницы архива, в порядке сайта (новые сверху)."""
    concerts = []
    for m in ARCHIVE_ITEM.finditer(page):
        h2, p = _clean(m.group("h2")), _clean(m.group("p"))
        if " · " in p:
            time_, title = p.split(" · ", 1)
            venue = h2
        else:
            time_, title, venue = p, h2, None
        concerts.append({
            "id": m.group("id"),
            "date": parse_date(_clean(m.group("date"))),
            "time": time_.strip() or None,
            "title": title.strip(),
            "venue": venue,
            "url": f"{BASE}/events/{m.group('id')}",
            "track_count": int(m.group("tracks")),
        })
    return concerts


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
    """Одна запись сетлиста + состав из сырого трека сайта."""
    song = track["song"]
    artist = (song.get("artist") or {}).get("name") or ""
    title = song.get("title") or ""
    lineup = []
    for seat in track.get("seats") or []:
        user = seat.get("user") or {}
        slot = seat.get("lineupSlot") or {}
        lineup.append({
            "id": seat["id"],
            "slot": slot.get("key") or "",
            "label": seat.get("label") or slot.get("label") or "",
            "seat_index": seat.get("seatIndex"),
            "username": user.get("telegramUsername"),
            "full_name": user.get("fullName"),
            "status": seat.get("status"),
            "optional": bool(seat.get("isOptional")),
        })
    return {
        "id": track["id"],
        "position": position,
        "artist": artist.strip(),
        "title": title.strip(),
        "artist_key": norm_key(artist),
        "title_key": norm_key(title),
        "state": track.get("state"),
        "ready": int(all(s["status"] != "OPEN" for s in lineup if not s["optional"])),
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


def store_setlist(conn, concert_id, raw_tracks):
    """Пересобирает setlist/lineup концерта из сырого JSON."""
    conn.execute("DELETE FROM setlist WHERE concert_id = ?", (concert_id,))
    for position, raw in enumerate(raw_tracks, 1):
        track = flatten_track(raw, position)
        conn.execute(
            "INSERT INTO setlist(id, concert_id, position, artist, title, artist_key, title_key, "
            "state, ready, comment) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                track["id"], concert_id, position, track["artist"], track["title"],
                track["artist_key"], track["title_key"], track["state"], track["ready"],
                track["comment"],
            ),
        )
        conn.executemany(
            "INSERT INTO lineup(id, track_id, slot, label, seat_index, username, full_name, status) "
            "VALUES(?,?,?,?,?,?,?,?)",
            [
                (s["id"], track["id"], s["slot"], s["label"], s["seat_index"],
                 s["username"], s["full_name"], s["status"])
                for s in track["lineup"]
            ],
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
    """Пересобирает setlist/lineup из сохранённого raw_json без обращения к сайту."""
    rows = conn.execute("SELECT id, raw_json FROM concerts").fetchall()
    for row in rows:
        store_setlist(conn, row["id"], json.loads(row["raw_json"]))
    conn.commit()
    print(f"Пересобрано {len(rows)} концертов.")
