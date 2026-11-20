"""parse_archive against a trimmed copy of the thejammers.org archive page (layout of 2026-11)."""
from pathlib import Path

import pytest

from tgchannel import jammers

PAGE = (Path(__file__).parent / "fixtures" / "archive_2026-11.html").read_text(encoding="utf-8")


def test_upcoming_concert_is_not_listed():
    ids = [c["id"] for c in jammers.parse_archive(PAGE)]
    assert "cmw7y9a21000aw701yfy07ulk" not in ids  # 13 Dec 2026, "Open": a board of proposals, not a setlist
    assert len(ids) == 6


def test_generated_title_loses_its_date_and_year_comes_from_it():
    c = jammers.parse_archive(PAGE)[0]
    assert (c["date"], c["time"], c["venue"], c["title"], c["track_count"]) == (
        "2026-11-15", "18:00", "Music Hall", "The Jammers", 22)


def test_custom_title_year_is_inferred_from_neighbours_and_weekday():
    c = next(c for c in jammers.parse_archive(PAGE) if c["title"] == "The Jammers Hot June")
    assert (c["date"], c["time"], c["track_count"]) == ("2026-06-28", "19:00", 25)


def test_old_rows_keep_their_year_and_venue():
    c = jammers.parse_archive(PAGE)[-1]
    assert (c["date"], c["venue"]) == ("2023-03-25", "Sinatra Karaoke Club")
    assert [x["date"] for x in jammers.parse_archive(PAGE)] == sorted((x["date"] for x in jammers.parse_archive(PAGE)), reverse=True)


def test_unparseable_row_is_an_error_not_a_silent_skip():
    broken = PAGE.replace('data-archive-row-meta="true"', 'data-renamed="true"')
    with pytest.raises(ValueError):
        jammers.parse_archive(broken)


def test_weekday_mismatch_is_an_error():
    # 15 November 2026 is a Sunday; claiming a Monday must not slip through
    broken = PAGE.replace(">Sun</span>", ">Mon</span>", 1)
    with pytest.raises(ValueError):
        jammers.parse_archive(broken)
