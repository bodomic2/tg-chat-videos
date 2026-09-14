"""Веб-каталог: поиск по исполнителю/песне/дате, страницы концертов, подвал и правка.

Правка без авторизации, намеренно: любой из чата может привязать неопознанное
видео к песне сетлиста, скрыть постороннее или сбросить ошибочную привязку.
Ручные привязки хранятся в matches с confidence = manual и переживают `match`.

Запуск: python -m tgchannel serve [--host 0.0.0.0] [--port 8080]
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, abort, g, redirect, render_template, request, url_for

from . import db
from .match import NEAR_DAYS, rematch_video
from .text import norm_key

LOCAL_TZ = ZoneInfo("Asia/Nicosia")  # чат кипрский: даты постов показываем по местному времени
CAPTION_LEN = 60

app = Flask(__name__)


def conn():
    if "conn" not in g:
        g.conn = db.connect()
    return g.conn


@app.teardown_appcontext
def _close(_exc):
    c = g.pop("conn", None)
    if c is not None:
        c.close()


# --- представление -----------------------------------------------------------

def local_date(date_utc):
    return datetime.fromisoformat(date_utc).astimezone(LOCAL_TZ)


def short_date(value):
    """«2025-10-31» или ISO с временем → «31.10.25»."""
    if len(value) == 10:
        return datetime.fromisoformat(value).strftime("%d.%m.%y")
    return local_date(value).strftime("%d.%m.%y")


def caption_line(caption):
    line = next((ln.strip() for ln in (caption or "").splitlines() if ln.strip()), "")
    return line if len(line) <= CAPTION_LEN else line[:CAPTION_LEN - 1] + "…"


def video_view(row, concert_date, index=None):
    """Словарь для шаблона: ссылка, подпись и метка вида «31.10.25 <= 02.11.25 - 1»."""
    posted = short_date(row["date_utc"])
    if index is not None:
        label = f"{short_date(concert_date)} <= {posted} - {index}"
    else:
        label = caption_line(row["caption"]) or f"видео {posted}"
    return {
        "msg_id": row["msg_id"],
        "link": row["link"],
        "posted": posted,
        "label": label,
        "caption": row["caption"],
        "confidence": row["confidence"] if "confidence" in row.keys() else None,
        "duration": row["duration"],
    }


app.jinja_env.filters["short_date"] = short_date


# --- выборки -----------------------------------------------------------------

MATCHED_SQL = """
SELECT s.id AS track_id, s.position, s.artist, s.title, s.artist_key, s.title_key,
       c.id AS concert_id, c.date AS concert_date, c.title AS concert_title,
       v.msg_id, v.date_utc, v.caption, v.link, v.duration, m.confidence
FROM matches m
JOIN videos v ON v.msg_id = m.msg_id
JOIN setlist s ON s.id = m.track_id
JOIN concerts c ON c.id = s.concert_id
WHERE v.hidden = 0
"""


def matched_tracks(where="", params=()):
    """[{track…, videos: [...]}] — песни, у которых есть хотя бы одно видео."""
    rows = conn().execute(MATCHED_SQL + where + " ORDER BY c.date, s.position, v.msg_id", params).fetchall()
    tracks = {}
    for row in rows:
        track = tracks.setdefault(row["track_id"], {
            "track_id": row["track_id"], "position": row["position"],
            "artist": row["artist"], "title": row["title"],
            "artist_key": row["artist_key"], "title_key": row["title_key"],
            "concert_id": row["concert_id"], "concert_date": row["concert_date"],
            "concert_title": row["concert_title"], "videos": [],
        })
        track["videos"].append(video_view(row, row["concert_date"]))
    return list(tracks.values())


def basement(concert_id, concert_date):
    """Неопознанные видео первых дней после концерта, с нумерацией внутри дня публикации."""
    rows = conn().execute(
        "SELECT v.msg_id, v.date_utc, v.caption, v.link, v.duration FROM videos v "
        "WHERE v.concert_id = ? AND v.hidden = 0 "
        "  AND julianday(v.date_utc) - julianday(?) < ? "
        "  AND v.msg_id NOT IN (SELECT msg_id FROM matches) ORDER BY v.msg_id",
        (concert_id, concert_date, NEAR_DAYS),
    ).fetchall()
    out, counter, last_day = [], 0, None
    for row in rows:
        day = local_date(row["date_utc"]).date()
        counter = counter + 1 if day == last_day else 1
        last_day = day
        out.append(video_view(row, concert_date, index=counter))
    return out


def setlist_of(concert_id):
    return conn().execute(
        "SELECT id, position, artist, title, ready FROM setlist WHERE concert_id = ? ORDER BY position",
        (concert_id,),
    ).fetchall()


# --- страницы ----------------------------------------------------------------

SORTS = {
    "date": lambda t: (t["concert_date"], t["position"]),
    "artist": lambda t: (t["artist_key"], t["title_key"], t["concert_date"]),
    "title": lambda t: (t["title_key"], t["artist_key"], t["concert_date"]),
}


@app.get("/")
def catalog():
    q = request.args.get("q", "").strip()
    sort = request.args.get("sort", "date")
    if sort not in SORTS:
        sort = "date"
    desc = request.args.get("dir", "desc" if sort == "date" else "asc") == "desc"
    tracks = matched_tracks()
    if q:
        needle = norm_key(q)
        tracks = [
            t for t in tracks
            if needle in t["artist_key"] or needle in t["title_key"]
            or needle in t["concert_date"] or needle in short_date(t["concert_date"])
        ]
    tracks.sort(key=SORTS[sort], reverse=desc)
    return render_template("catalog.html", tracks=tracks, q=q, sort=sort, desc=desc,
                           stats=db.counts(conn()))


@app.get("/concerts")
def concerts():
    rows = conn().execute(
        "SELECT c.id, c.date, c.title, c.venue, c.url, c.track_count, "
        "  (SELECT count(*) FROM setlist s WHERE s.concert_id = c.id) AS songs, "
        "  (SELECT count(DISTINCT m.track_id) FROM matches m JOIN setlist s ON s.id = m.track_id "
        "     JOIN videos v ON v.msg_id = m.msg_id WHERE s.concert_id = c.id AND v.hidden = 0) AS songs_with_video, "
        "  (SELECT count(*) FROM videos v WHERE v.concert_id = c.id AND v.hidden = 0 "
        "     AND julianday(v.date_utc) - julianday(c.date) < ? "
        "     AND v.msg_id NOT IN (SELECT msg_id FROM matches)) AS unsorted "
        "FROM concerts c ORDER BY c.date DESC",
        (NEAR_DAYS,),
    ).fetchall()
    return render_template("concerts.html", concerts=rows)


@app.get("/concert/<concert_id>")
def concert(concert_id):
    row = conn().execute("SELECT * FROM concerts WHERE id = ?", (concert_id,)).fetchone()
    if row is None:
        abort(404)
    videos_by_track = {t["track_id"]: t["videos"] for t in matched_tracks("AND c.id = ?", (concert_id,))}
    setlist = [dict(t, videos=videos_by_track.get(t["id"], [])) for t in setlist_of(concert_id)]
    return render_template(
        "concert.html", concert=row, setlist=setlist,
        unsorted=basement(concert_id, row["date"]), near_days=NEAR_DAYS,
    )


@app.post("/video/<int:msg_id>")
def edit_video(msg_id):
    c = conn()
    video = c.execute("SELECT msg_id, concert_id FROM videos WHERE msg_id = ?", (msg_id,)).fetchone()
    if video is None:
        abort(404)
    action = request.form.get("action")
    if action == "match":
        track_id = request.form.get("track_id", "")
        ok = c.execute(
            "SELECT 1 FROM setlist WHERE id = ? AND concert_id = ?", (track_id, video["concert_id"])
        ).fetchone()
        if not ok:
            abort(400)
        c.execute("DELETE FROM matches WHERE msg_id = ?", (msg_id,))
        c.execute(
            "INSERT INTO matches(msg_id, track_id, confidence, source) VALUES(?,?,'manual','manual')",
            (msg_id, track_id),
        )
        c.execute("UPDATE videos SET hidden = 0 WHERE msg_id = ?", (msg_id,))
    elif action == "hide":
        c.execute("DELETE FROM matches WHERE msg_id = ?", (msg_id,))
        c.execute("UPDATE videos SET hidden = 1 WHERE msg_id = ?", (msg_id,))
    elif action == "reset":
        c.execute("UPDATE videos SET hidden = 0 WHERE msg_id = ?", (msg_id,))
        rematch_video(c, msg_id)
    else:
        abort(400)
    c.commit()
    target = request.form.get("next") or url_for("concert", concert_id=video["concert_id"])
    if not target.startswith("/"):
        target = url_for("concert", concert_id=video["concert_id"])
    return redirect(target + f"#v{msg_id}")


def serve(host="127.0.0.1", port=8080, debug=False):
    app.run(host=host, port=port, debug=debug)
