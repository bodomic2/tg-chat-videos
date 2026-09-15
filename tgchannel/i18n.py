"""Строки интерфейса: русский по умолчанию, английский по cookie `lang`.

В шаблонах: {{ t('key') }} и {{ t('key', n=5) }} для форм множественного числа.
"""

LANGS = ("ru", "en")
DEFAULT = "ru"

STRINGS = {
    "site": {"ru": "Видео с гигов The Jammers", "en": "The Jammers gig videos"},
    "nav_catalog": {"ru": "Каталог", "en": "Catalog"},
    "nav_concerts": {"ru": "Концерты", "en": "Gigs"},
    "nav_musicians": {"ru": "Музыканты", "en": "Musicians"},
    "footer": {
        "ru": "Видео из чата «Музыканты Кипра», сетлисты с {site}. "
              "Ошиблись с привязкой? Правьте прямо здесь — авторизация не нужна.",
        "en": "Videos from the Cyprus Musicians chat, setlists from {site}. "
              "Wrong match? Fix it right here — no sign-in needed.",
    },
    "stats": {
        "ru": "{concerts} концертов · {songs} песен с видео · {videos} видео привязано",
        "en": "{concerts} gigs · {songs} songs with video · {videos} videos matched",
    },
    "search_placeholder": {
        "ru": "исполнитель, песня, дата (31.10.25) или музыкант",
        "en": "artist, song, date (31.10.25) or musician",
    },
    "search": {"ru": "Искать", "en": "Search"},
    "reset_search": {"ru": "сбросить", "en": "clear"},
    "th_concert": {"ru": "Концерт", "en": "Gig"},
    "th_artist": {"ru": "Исполнитель", "en": "Artist"},
    "th_title": {"ru": "Песня", "en": "Song"},
    "th_videos": {"ru": "Видео", "en": "Videos"},
    "nothing_found": {"ru": "Ничего не нашлось.", "en": "Nothing found."},
    "all_musicians": {"ru": "← все музыканты", "en": "← all musicians"},
    "all_concerts": {"ru": "← все концерты", "en": "← all gigs"},
    "songs_n": {"ru": ("{n} песня", "{n} песни", "{n} песен"), "en": ("{n} song", "{n} songs")},
    "by_query": {"ru": " по запросу", "en": " matching the query"},
    "concerts_h1": {"ru": "Концерты", "en": "Gigs"},
    "th_date": {"ru": "Дата", "en": "Date"},
    "th_songs": {"ru": "Песен", "en": "Songs"},
    "th_with_video": {"ru": "С видео", "en": "With video"},
    "th_unsorted": {"ru": "В подвале", "en": "Unsorted"},
    "setlist_on_site": {"ru": "сетлист на сайте", "en": "setlist on the site"},
    "unsorted_h2": {
        "ru": "Подвал: без подписи или не распознано ({n})",
        "en": "Unsorted: no caption or not recognised ({n})",
    },
    "unsorted_help": {
        "ru": "Видео первых {days} дней после концерта, которые не удалось привязать к песне. "
              "Метка: дата концерта ⇐ дата публикации − номер видео за тот день. Нажмите ⋯, чтобы привязать.",
        "en": "Videos from the first {days} days after the gig that could not be matched to a song. "
              "Label: gig date ⇐ posting date − number of the video that day. Press ⋯ to match.",
    },
    "empty": {"ru": "Пусто.", "en": "Empty."},
    "video_fallback": {"ru": "видео {date}", "en": "video {date}"},
    "badge_maybe": {"ru": "привязано только по исполнителю", "en": "matched by artist only"},
    "badge_manual": {"ru": "привязано вручную", "en": "matched by hand"},
    "edit": {"ru": "исправить", "en": "fix"},
    "btn_match": {"ru": "Это эта песня", "en": "It's this song"},
    "btn_hide": {"ru": "Не с концерта", "en": "Not from the gig"},
    "btn_reset": {"ru": "Сбросить", "en": "Reset"},
    "musicians_h1": {"ru": "Музыканты", "en": "Musicians"},
    "musicians_help": {
        "ru": "{n} человек; «песен» — сколько раз выходил на сцену на гигах, «с видео» — из них с видео в каталоге.",
        "en": "{n} people; “songs” — times on stage at gigs, “with video” — of those, songs with a video in the catalog.",
    },
    "th_nick": {"ru": "Ник", "en": "Nick"},
    "th_name": {"ru": "Имя", "en": "Name"},
}


def plural(lang, forms, n):
    if lang == "ru":
        n10, n100 = n % 10, n % 100
        if n10 == 1 and n100 != 11:
            return forms[0]
        if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
            return forms[1]
        return forms[2]
    return forms[0] if n == 1 else forms[1]


def translator(lang):
    lang = lang if lang in LANGS else DEFAULT

    def t(key, **kw):
        value = STRINGS[key][lang]
        if isinstance(value, tuple):
            value = plural(lang, value, kw.get("n", 0))
        return value.format(**kw) if kw else value

    return t
