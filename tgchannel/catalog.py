"""Генерация каталога: out/CATALOG.md и out/catalog.html.

Три раздела и они не смешиваются:
  * каталог — только посты по шаблону (жирная строка «Исполнитель - Название»);
  * похоже на песню — разобралось, но шаблон не соблюдён, нужен глаз;
  * прочие посты — заметки, ссылки, анонсы.

Наружу идут только метаданные — исполнитель, название, примечания, даты и ссылки.
Тексты постов остаются в базе.
"""

import html
import json
from datetime import datetime, timezone

from . import config, db
from .parse import norm_key

CYR = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"


def sort_key(name):
    """Латиница и цифры сначала, кириллица потом; ключ тот же, что при группировке."""
    key = norm_key(name or "").lstrip("\"'([«").strip()
    bucket = 1 if key and key[0] in CYR else 0
    return (bucket, key, name or "")


def collect(conn, include_maybe=False):
    """Каталог: [{artist, tracks: [{title, notes, plays: [...]}]}].

    Берутся только песни, подтверждённые хотя бы одним постом по шаблону.
    include_maybe добавляет к ним даты из «похожих» постов про ту же песню.
    """
    confidences = ("ok", "maybe") if include_maybe else ("ok",)
    placeholders = ",".join("?" * len(confidences))
    rows = conn.execute(
        "SELECT t.artist_raw, t.artist_key, t.title_raw, t.title_key, "
        "       a.msg_id, a.date_utc, a.notes, a.confidence, m.link "
        "FROM tracks t "
        "JOIN appearances a ON a.track_id = t.id "
        "JOIN messages m ON m.msg_id = a.msg_id "
        f"WHERE a.confidence IN ({placeholders}) "
        "  AND t.id IN (SELECT track_id FROM appearances WHERE confidence = 'ok') "
        "ORDER BY t.artist_key, t.title_key, a.date_utc, a.msg_id",
        confidences,
    ).fetchall()

    artists = {}
    for row in rows:
        artist = artists.setdefault(
            row["artist_key"], {"artist": row["artist_raw"], "tracks": {}}
        )
        track = artist["tracks"].setdefault(
            row["title_key"], {"title": row["title_raw"], "notes": [], "plays": []}
        )
        track["plays"].append(
            {
                "date": row["date_utc"][:10],
                "link": row["link"],
                "maybe": row["confidence"] != "ok",
            }
        )
        if row["notes"] and row["notes"] not in track["notes"]:
            track["notes"].append(row["notes"])

    result = []
    for artist in artists.values():
        tracks = []
        for track in artist["tracks"].values():
            tracks.append(
                {
                    "title": track["title"],
                    "notes": "; ".join(track["notes"]),
                    "count": len(track["plays"]),
                    "last": max(p["date"] for p in track["plays"]),
                    "plays": track["plays"],
                }
            )
        tracks.sort(key=lambda t: sort_key(t["title"]))
        result.append(
            {
                "artist": artist["artist"],
                "tracks": tracks,
                "count": sum(t["count"] for t in tracks),
                "last": max(t["last"] for t in tracks),
            }
        )
    result.sort(key=lambda a: sort_key(a["artist"]))
    return result


def flat_songs(conn, include_maybe=False):
    """Плоский список распознанных песен — по строке на песню, а не по исполнителю."""
    songs = []
    for artist in collect(conn, include_maybe=include_maybe):
        for track in artist["tracks"]:
            songs.append(
                {
                    "artist": artist["artist"],
                    "title": track["title"],
                    "notes": track["notes"],
                    "count": track["count"],
                    "dates": [p["date"] for p in track["plays"]],
                    "links": [p["link"] for p in track["plays"]],
                }
            )
    return songs


def render_text(songs, with_dates=True):
    """По строке на песню: «Исполнитель - Название (примечания) — даты ×N»."""
    lines = []
    for song in songs:
        line = f"{song['artist']} - {song['title']}"
        if song["notes"]:
            line += f" ({song['notes']})"
        if with_dates:
            line += " — " + ", ".join(song["dates"])
            if song["count"] > 1:
                line += f" ×{song['count']}"
        lines.append(line)
    return "\n".join(lines)


def maybe_songs(conn):
    """Посты, разобранные как песня, но не по шаблону. Каталог их не включает."""
    rows = conn.execute(
        "SELECT t.artist_raw, t.title_raw, a.msg_id, a.date_utc, a.notes, m.link, "
        "       m.parse_note, "
        "       EXISTS(SELECT 1 FROM appearances o WHERE o.track_id = t.id "
        "              AND o.confidence = 'ok') AS known "
        "FROM tracks t "
        "JOIN appearances a ON a.track_id = t.id "
        "JOIN messages m ON m.msg_id = a.msg_id "
        "WHERE a.confidence = 'maybe' "
        "ORDER BY known, t.artist_key, a.date_utc"
    ).fetchall()
    return [
        {
            "artist": r["artist_raw"],
            "title": r["title_raw"],
            "notes": r["notes"] or "",
            "date": r["date_utc"][:10],
            "link": r["link"],
            "known": bool(r["known"]),
            "note": r["parse_note"] or "",
        }
        for r in rows
    ]


def other_posts(conn, limit=1000):
    """Всё остальное: заметки, ссылки, анонсы. Только дата, ссылка и начало строки."""
    rows = conn.execute(
        "SELECT msg_id, date_utc, header, text, link, parse_note FROM messages "
        "WHERE parse_status NOT IN ('ok','maybe') ORDER BY date_utc DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "date": r["date_utc"][:10],
            "link": r["link"],
            "note": r["parse_note"] or "",
            "excerpt": " ".join((r["header"] or r["text"]).split())[:90],
        }
        for r in rows
    ]


def render_markdown(catalog, maybes, others, meta, stats):
    lines = [f"# {meta.get('channel_title', 'Канал')} — каталог песен", ""]
    lines.append(
        f"По шаблону: {stats['catalog_posts']} постов · "
        f"исполнителей: {stats['artists']} · песен: {stats['tracks']} · "
        f"исполнений: {stats['appearances']}"
    )
    lines.append(
        f"Похоже на песню: {stats['maybe_posts']} · "
        f"прочих постов: {stats['other_posts']} · "
        f"всего в базе: {stats['messages']}"
    )
    lines.append(f"Сгенерировано: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC")
    lines.append("")
    lines.append("## Каталог")
    lines.append("")

    for artist in catalog:
        lines.append(f"### {artist['artist']}")
        lines.append("")
        for track in artist["tracks"]:
            title = track["title"]
            if track["notes"]:
                title += f" ({track['notes']})"
            dates = ", ".join(
                f"[{p['date']}{'?' if p['maybe'] else ''}]({p['link']})"
                for p in track["plays"]
            )
            repeat = f" **×{track['count']}**" if track["count"] > 1 else ""
            lines.append(f"- {title} — {dates}{repeat}")
        lines.append("")

    lines.append(f"## Похоже на песню, но не по шаблону ({len(maybes)})")
    lines.append("")
    lines.append("Разобралось как «исполнитель - название», но шаблон не соблюдён.")
    lines.append("В каталог не попало — проверьте глазами.")
    lines.append("")
    for item in maybes:
        mark = " `уже в каталоге`" if item["known"] else ""
        lines.append(
            f"- [{item['date']}]({item['link']}) **{item['artist']}** — {item['title']}"
            f"{mark} · _{item['note']}_"
        )
    lines.append("")

    lines.append(f"## Прочие посты ({len(others)})")
    lines.append("")
    for item in others:
        lines.append(f"- [{item['date']}]({item['link']}) — {item['excerpt']}")
    lines.append("")
    return "\n".join(lines)


HTML_TEMPLATE = """<meta charset="utf-8">
<title>__TITLE__</title>
<style>
  :root {
    --bg: #fbfaf8; --fg: #1c1b19; --muted: #6b6863; --line: #e3ded6;
    --card: #ffffff; --accent: #9a5b2c; --chip: #f0ebe3;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #171614; --fg: #ece9e4; --muted: #9a958d; --line: #2e2c28;
      --card: #1f1e1b; --accent: #d99a63; --chip: #2a2825;
    }
  }
  * { box-sizing: border-box; }
  body { margin: 0; padding: 2rem 1.25rem 4rem; background: var(--bg); color: var(--fg);
         font: 16px/1.55 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
  .wrap { max-width: 940px; margin: 0 auto; }
  h1 { font-size: 1.6rem; margin: 0 0 .3rem; }
  h2 { font-size: 1.05rem; margin: 2.2rem 0 .2rem; }
  .sub, .hint { color: var(--muted); font-size: .9rem; }
  .sub { margin-bottom: 1.2rem; }
  .hint { margin: 0 0 .7rem; }
  .bar { display: flex; gap: .6rem; flex-wrap: wrap; position: sticky; top: 0;
         background: var(--bg); padding: .75rem 0; border-bottom: 1px solid var(--line);
         margin-bottom: 1rem; z-index: 5; }
  input, select, button { font: inherit; color: var(--fg); background: var(--card);
         border: 1px solid var(--line); border-radius: 8px; padding: .45rem .7rem; }
  input { flex: 1 1 260px; }
  button { cursor: pointer; }
  details { background: var(--card); border: 1px solid var(--line); border-radius: 10px;
            margin-bottom: .55rem; }
  summary { cursor: pointer; padding: .7rem .9rem; font-weight: 600; display: flex;
            gap: .6rem; align-items: baseline; }
  summary::-webkit-details-marker { display: none; }
  summary .meta { color: var(--muted); font-weight: 400; font-size: .85rem; }
  ul { margin: 0; padding: 0 .9rem .8rem 1.9rem; }
  li { margin: .3rem 0; }
  .notes { color: var(--muted); }
  .dates { margin-left: .4rem; font-size: .87rem; }
  .dates a { color: var(--accent); text-decoration: none; margin-right: .45rem;
             white-space: nowrap; }
  .dates a:hover { text-decoration: underline; }
  .rep, .badge { background: var(--chip); border-radius: 6px; padding: 0 .35rem;
                 font-size: .8rem; color: var(--muted); }
  .why { color: var(--muted); font-size: .82rem; }
  .plain { font-size: .9rem; color: var(--muted); }
  .plain a { color: var(--accent); text-decoration: none; margin-right: .4rem; }
  #empty { color: var(--muted); padding: 1rem 0; display: none; }
</style>
<div class="wrap">
  <h1>__TITLE__</h1>
  <div class="sub">__SUB__</div>
  <div class="bar">
    <input id="q" placeholder="поиск по исполнителю или названию" autocomplete="off">
    <select id="sort">
      <option value="alpha">по алфавиту</option>
      <option value="count">по числу исполнений</option>
      <option value="last">по дате последнего поста</option>
    </select>
    <button id="toggle">развернуть всё</button>
  </div>
  <div id="list"></div>
  <div id="empty">Ничего не найдено.</div>

  <h2>Похоже на песню, но не по шаблону</h2>
  <p class="hint">Разобралось как «исполнитель - название», но первая строка не жирная
     или разделитель кривой. В каталог не входит.</p>
  <details id="maybeBox"><summary>Показать <span class="meta" id="maybeCount"></span></summary>
    <ul id="maybeList"></ul>
  </details>

  <h2>Прочие посты</h2>
  <p class="hint">Заметки, ссылки, анонсы — всё, что не описывает песню.</p>
  <details id="otherBox"><summary>Показать <span class="meta" id="otherCount"></span></summary>
    <ul id="otherList"></ul>
  </details>
</div>
<script>
const DATA = __DATA__;
const MAYBE = __MAYBE__;
const OTHER = __OTHER__;
const list = document.getElementById("list");
const empty = document.getElementById("empty");
const q = document.getElementById("q");
const sortSel = document.getElementById("sort");
const esc = s => String(s).replace(/[&<>"]/g, c => (
  {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));

function sorted(items) {
  const mode = sortSel.value;
  const copy = items.slice();
  if (mode === "count") copy.sort((a, b) => b.count - a.count || a.artist.localeCompare(b.artist));
  else if (mode === "last") copy.sort((a, b) => b.last.localeCompare(a.last));
  return copy;
}

function render() {
  const needle = q.value.trim().toLowerCase();
  let shown = 0;
  const parts = [];
  for (const artist of sorted(DATA)) {
    const hitArtist = !needle || artist.artist.toLowerCase().includes(needle);
    const tracks = hitArtist ? artist.tracks
      : artist.tracks.filter(t => t.title.toLowerCase().includes(needle));
    if (!tracks.length) continue;
    shown++;
    const open = needle ? " open" : "";
    const items = tracks.map(t => {
      const notes = t.notes ? ` <span class="notes">(${esc(t.notes)})</span>` : "";
      const rep = t.count > 1 ? ` <span class="rep">×${t.count}</span>` : "";
      const dates = t.plays.map(p =>
        `<a href="${esc(p.link)}" target="_blank" rel="noopener">${p.date}${p.maybe ? "?" : ""}</a>`
      ).join("");
      return `<li>${esc(t.title)}${notes}${rep}<span class="dates">${dates}</span></li>`;
    }).join("");
    parts.push(`<details${open}><summary>${esc(artist.artist)}` +
      `<span class="meta">${artist.tracks.length} песен · ${artist.count} исполнений</span>` +
      `</summary><ul>${items}</ul></details>`);
  }
  list.innerHTML = parts.join("");
  empty.style.display = shown ? "none" : "block";
}

document.getElementById("toggle").onclick = e => {
  const openAll = e.target.textContent === "развернуть всё";
  list.querySelectorAll("details").forEach(d => { d.open = openAll; });
  e.target.textContent = openAll ? "свернуть всё" : "развернуть всё";
};
q.oninput = render;
sortSel.onchange = render;

document.getElementById("maybeCount").textContent = `(${MAYBE.length})`;
document.getElementById("maybeList").innerHTML = MAYBE.map(m =>
  `<li><a href="${esc(m.link)}" target="_blank" rel="noopener">${m.date}</a> ` +
  `<b>${esc(m.artist)}</b> — ${esc(m.title)}` +
  (m.known ? ` <span class="badge">уже в каталоге</span>` : "") +
  ` <span class="why">${esc(m.note)}</span></li>`).join("");

document.getElementById("otherCount").textContent = `(${OTHER.length})`;
document.getElementById("otherList").innerHTML = OTHER.map(o =>
  `<li class="plain"><a href="${esc(o.link)}" target="_blank" rel="noopener">${o.date}</a> ` +
  `${esc(o.excerpt)}</li>`).join("");

render();
</script>
"""


def render_html(catalog, maybes, others, meta, stats):
    title = meta.get("channel_title") or "Каталог песен"
    sub = (
        f"По шаблону: {stats['catalog_posts']} постов · исполнителей: {stats['artists']} · "
        f"песен: {stats['tracks']} · исполнений: {stats['appearances']} · "
        f"похоже на песню: {stats['maybe_posts']} · прочих: {stats['other_posts']} · "
        f"обновлено {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC"
    )
    return (
        HTML_TEMPLATE
        .replace("__TITLE__", html.escape(title))
        .replace("__SUB__", html.escape(sub))
        .replace("__DATA__", json.dumps(catalog, ensure_ascii=False))
        .replace("__MAYBE__", json.dumps(maybes, ensure_ascii=False))
        .replace("__OTHER__", json.dumps(others, ensure_ascii=False))
    )


def generate(conn, out_dir=None, include_maybe=False):
    out_dir = out_dir or config.OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM meta")}
    stats = db.counts(conn)
    catalog = collect(conn, include_maybe=include_maybe)
    maybes = maybe_songs(conn)
    others = other_posts(conn)

    md_path = out_dir / "CATALOG.md"
    html_path = out_dir / "catalog.html"
    md_path.write_text(
        render_markdown(catalog, maybes, others, meta, stats), encoding="utf-8", newline="\n"
    )
    html_path.write_text(
        render_html(catalog, maybes, others, meta, stats), encoding="utf-8", newline="\n"
    )
    print(f"Каталог: {md_path}")
    print(f"         {html_path}")
    print(
        f"В каталоге: {stats['artists']} исполнителей · {stats['tracks']} песен · "
        f"{stats['appearances']} исполнений"
    )
    print(f"Похоже на песню: {len(maybes)} · прочих постов: {len(others)}")
    return md_path, html_path


def export(conn, fmt="txt", out_path=None, include_maybe=False, with_dates=True):
    """Выгружает распознанные песни списком: txt или json. Без пути — в stdout."""
    songs = flat_songs(conn, include_maybe=include_maybe)
    if fmt == "json":
        text = json.dumps(songs, ensure_ascii=False, indent=2)
    else:
        text = render_text(songs, with_dates=with_dates)
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8", newline="\n")
        print(f"Песен: {len(songs)} → {out_path}")
    else:
        print(text)
    return songs
