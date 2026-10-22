# `GET /api/summary.json` — done and live

Reply to *Task: add `GET /api/summary.json` to video.bodomi.com* (thejammers.org team).
Deployed and verified on **2026-10-22**.

```
https://video.bodomi.com/api/summary.json
```

| | |
|---|---|
| Status / type | `200`, `application/json; charset=utf-8` |
| Auth | none; no cookies, no sessions, no query parameters |
| Language | one response for everyone — the RU/EN switch does not touch it |
| Headers | `Cache-Control: public, max-age=3600`, `ETag`; `If-None-Match` answers `304` |
| Size / speed | 22.7 KB, 20 ms on the server (0.4 s through Cloudflare, cold) |
| On failure | JSON body with HTTP `503`, never a `200` with an HTML page |

Current payload (2026-10-22): `totals` = 37 gigs, 214 songs, 1916 videos; 37 gigs and
287 musicians listed. Shape is exactly version 1 as specified.

## Two things that need your attention

### 1. Cloudflare blocks the default Python `urllib` User-Agent

The site sits behind Cloudflare. A request whose `User-Agent` is `Python-urllib/3.x`
gets **403**. Measured from outside:

| User-Agent | Result |
|---|---|
| `Python-urllib/3.12` | **403** |
| `python-requests/2.31.0` | 200 |
| `thejammers.org/1.0 (+https://thejammers.org)` | 200 |
| `Go-http-client/2.0`, `node-fetch/3.0`, `axios/1.7.2`, `curl/8.5.0` | 200 |
| no User-Agent at all | 200 |

So: send any normal `User-Agent` and you are fine. Only the Python standard library's
default string is blocked — if your fetcher is `urllib.request` without an explicit
header, it will see 403 every time. A name like `thejammers.org/1.0` is ideal: if we
ever need to whitelist or debug, we can find you in the logs.

### 2. `gigs[].videos` counts videos, not songs — your example suggests you meant songs

The field table says *"Videos linked to that gig"* and rule 4 says to include the
unsorted ones, so that is what we return. But the example in the request (`"videos": 17`
for Hot June) equals the **"С видео" column** on our Concerts page, which is the number
of *songs* that have a video. Those are different numbers:

| Gig | `videos` (what we return) | `tracks.length` | "С видео" on our site | your example |
|---|---|---|---|---|
| 28.06.26 Hot June | 21 | 16 | 17 | 17 |
| 27.09.26 | 70 | 12 | 12 | 12 |
| 19.04.26 | 13 | 11 | 11 | 11 |

If you want "▶ 17 videos" to read as *songs with video*, use `gigs[].tracks.length` —
it is already in the response, no change needed on our side. `tracks.length` is one
less than "С видео" for Hot June because one of those matches is an uncertain one,
which rule 3 told us to drop.

The same split applies to `totals.videos`. Three defensible numbers, one field:

| Definition | Value |
|---|---|
| Certain matches + unsorted videos the gig pages show — **what we return**, per rules 3 and 4 | 1916 |
| Certain matches only (no unsorted) | 305 |
| What the Catalog header says ("388 linked videos" — includes uncertain matches, excludes unsorted) | 388 |

We went with the rules as written rather than with the example number. If the banner
should say something else, tell us which of the three you want — it is a one-line
change and we will keep the field name.

## Counting rules we implemented

* **Counted:** matches our matcher is confident about, plus the ones a human fixed by
  hand on the site.
* **Not counted anywhere:** uncertain matches (the ones shown with a `?`), exactly as
  rule 3 asks, and videos a human marked as "not from the gig".
* **Unsorted videos** (`#unsorted` on a gig page): counted in `gigs[].videos` and
  `totals.videos`, never in `tracks` — their song is unknown.
* **IDs** are yours: `concerts.id` and `setlist.id` come from thejammers.org and are the
  same strings we use in `/concert/<id>#t<id>`. Nothing invented, nothing remapped.
* `musicians[].videos` counts distinct videos of songs that musician played in, keyed by
  the telegram username without `@`, the same one `/musician/<nick>` uses.
* `updatedAt` is when the archive last pulled new data. Manual fixes on the site do not
  move it, but they do change the `ETag`, so revalidation still sees them.

## Acceptance checks

All checks from the request were run against the live site and pass:

1. `200`, `version: 1`, totals present; `If-None-Match` → `304`.
2. Totals are consistent with the site (see the discrepancy note above).
3. Every gig id opens a real gig page; counts come from the same data as the pages.
4. Every `tracks[].id` has a matching `id="t<id>"` anchor on its gig page — checked for
   all tracks of the first five gigs, none missing.
5. No zero entries, no uncertain matches, no `@` prefixes, integers only;
   `totals.gigs == gigs.length` and `totals.songs == Σ tracks.length`.

## What stays stable

`/concert/<gigId>`, the `#t<trackId>` anchors, `/musician/<telegram>`, the
`/api/summary.json` path and the version 1 shape. Anything incompatible will appear as
`version: 2` at a new path, with version 1 kept alive.

One caveat about gig pages: for a gig whose board on thejammers.org lists proposals
rather than the played setlist, we pin the real setlist by hand (currently Hot June
2026). Track ids for songs that were only proposed will therefore not appear here.

Questions: Alexey (@bodomic). Source: https://github.com/bodomic2/tg-chat-videos —
the contract lives in `tgchannel/api.py`.
