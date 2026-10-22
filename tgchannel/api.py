"""Машиночитаемая сводка архива для thejammers.org: GET /api/summary.json.

Тот сайт по ней решает, у каких гигов и песен рисовать «▶», поэтому форма
ответа зафиксирована (version 1): менять её несовместимо нельзя — только
добавлять version 2 рядом. Идентификаторы и так их: concerts.id и setlist.id
приехали с thejammers.org и стоят в наших же ссылках /concert/<id>#t<id>.

Что попадает в счётчики:
  * привязки ok и manual — да;
  * привязки maybe (на сайте с «?») — нигде, «▶» там должен вести к настоящему
    видео этой песни, а не к похожему;
  * видео из подвала — в счётчик гига и в общий итог, но не в tracks: песня
    у них не определена (как и на странице концерта);
  * скрытые руками видео («не с концерта») — нигде.
"""

from datetime import datetime, timezone

VERSION = 1
CERTAIN = ("ok", "manual")

# Видео, уверенно привязанные к песне: (msg_id, track_id, concert_id).
CERTAIN_SQL = """
SELECT m.msg_id, m.track_id, s.concert_id
FROM matches m
JOIN videos v ON v.msg_id = m.msg_id
JOIN setlist s ON s.id = m.track_id
WHERE m.confidence IN ('ok', 'manual') AND v.hidden = 0
"""

# Видео из подвала концерта: те же, что показывает страница концерта.
BASEMENT_SQL = """
SELECT v.concert_id, v.msg_id
FROM videos v
JOIN concerts c ON c.id = v.concert_id
WHERE v.hidden = 0
  AND julianday(v.date_utc) - julianday(c.date) < ?
  AND v.msg_id NOT IN (SELECT msg_id FROM matches)
"""

MUSICIANS_SQL = """
SELECT l.username, count(DISTINCT m.msg_id) AS videos
FROM lineup l
JOIN matches m ON m.track_id = l.track_id
JOIN videos v ON v.msg_id = m.msg_id
WHERE m.confidence IN ('ok', 'manual') AND v.hidden = 0 AND l.username IS NOT NULL
GROUP BY l.username
HAVING videos > 0
"""

# Когда архив последний раз менялся: докачка видео и перезагрузка концертов.
UPDATED_SQL = """
SELECT max(ts) FROM (
  SELECT max(fetched_at) AS ts FROM videos
  UNION ALL
  SELECT max(fetched_at) FROM concerts
)
"""


def _utc_z(value):
    """«2026-10-21T15:00:00+00:00» → «2026-10-21T15:00:00Z»."""
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        moment = datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def summary(conn, near_days):
    """Сводка целиком. near_days — окно подвала, то же, что на странице концерта."""
    gig_videos = {}   # concert_id -> {msg_id}
    track_videos = {}  # concert_id -> {track_id: {msg_id}}

    for row in conn.execute(CERTAIN_SQL):
        gig_videos.setdefault(row["concert_id"], set()).add(row["msg_id"])
        tracks = track_videos.setdefault(row["concert_id"], {})
        tracks.setdefault(row["track_id"], set()).add(row["msg_id"])

    for row in conn.execute(BASEMENT_SQL, (near_days,)):
        gig_videos.setdefault(row["concert_id"], set()).add(row["msg_id"])

    gigs = [
        {
            "id": concert_id,
            "videos": len(videos),
            "tracks": [
                {"id": track_id, "videos": len(msg_ids)}
                for track_id, msg_ids in sorted(track_videos.get(concert_id, {}).items())
            ],
        }
        for concert_id, videos in sorted(gig_videos.items())
        if videos
    ]
    musicians = [
        {"telegram": row["username"], "videos": row["videos"]}
        for row in conn.execute(MUSICIANS_SQL)
    ]
    songs = sum(len(tracks) for tracks in track_videos.values())
    videos_total = len(set().union(*gig_videos.values())) if gig_videos else 0

    return {
        "version": VERSION,
        "updatedAt": _utc_z(conn.execute(UPDATED_SQL).fetchone()[0]),
        "totals": {"gigs": len(gigs), "songs": songs, "videos": videos_total},
        "gigs": gigs,
        "musicians": musicians,
    }
