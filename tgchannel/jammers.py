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
