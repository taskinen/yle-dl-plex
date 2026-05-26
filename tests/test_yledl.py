"""Tests for `yle_dl_plex.yledl.Episode` boundary conversion."""

from __future__ import annotations

from yle_dl_plex.yledl import Episode


def test_from_metadata_full() -> None:
    item = {
        "filename": "/library/My Show/Season 01/My Show - S01E02 - The Pilot.mkv",
        "title": "My Show - S01E02 - The Pilot",
        "description": "Plot text.",
        "thumbnail": "https://images.cdn.yle.fi/thumb.jpg",
        "duration_seconds": 2700,
        "publish_timestamp": "2025-01-15T18:00:00+02:00",
        "webpage": "https://areena.yle.fi/1-62248394",
        "program_id": "1-62248394",
    }
    ep = Episode.from_metadata(item)
    assert ep == Episode(
        filename="/library/My Show/Season 01/My Show - S01E02 - The Pilot.mkv",
        title="My Show - S01E02 - The Pilot",
        description="Plot text.",
        thumbnail="https://images.cdn.yle.fi/thumb.jpg",
        duration_seconds=2700,
        publish_timestamp="2025-01-15T18:00:00+02:00",
        webpage="https://areena.yle.fi/1-62248394",
        program_id="1-62248394",
    )


def test_from_metadata_missing_fields_default_to_empty() -> None:
    ep = Episode.from_metadata({})
    assert ep == Episode(
        filename="",
        title="",
        description="",
        thumbnail="",
        duration_seconds=0,
        publish_timestamp="",
        webpage="",
        program_id="",
    )


def test_from_metadata_none_duration_coerces_to_zero() -> None:
    ep = Episode.from_metadata({"duration_seconds": None})
    assert ep.duration_seconds == 0


def test_from_metadata_string_duration_coerced_to_int() -> None:
    # yle-dl emits the duration as an int, but be defensive about it
    # — int() handles string digits just in case.
    ep = Episode.from_metadata({"duration_seconds": "1800"})
    assert ep.duration_seconds == 1800
