"""Tests for `yle_dl_plex.nfo` writers."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import pytest

from yle_dl_plex.areena import SeriesMetadata
from yle_dl_plex.nfo import (
    EpisodeNfo,
    _add_text_child,
    write_episode_nfo,
    write_tvshow_nfo,
)

# --------------------------------------------------------------------------- #
# _add_text_child                                                             #
# --------------------------------------------------------------------------- #


class TestAddTextChild:
    def test_emits_string(self) -> None:
        root = ET.Element("root")
        _add_text_child(root, "tag", "hello")
        assert root.find("tag") is not None
        assert root.find("tag").text == "hello"  # type: ignore[union-attr]

    def test_emits_int(self) -> None:
        root = ET.Element("root")
        _add_text_child(root, "tag", 42)
        assert root.find("tag").text == "42"  # type: ignore[union-attr]

    def test_skips_none(self) -> None:
        root = ET.Element("root")
        _add_text_child(root, "tag", None)
        assert root.find("tag") is None

    def test_skips_empty_string(self) -> None:
        root = ET.Element("root")
        _add_text_child(root, "tag", "")
        assert root.find("tag") is None

    def test_emits_zero(self) -> None:
        # Integer 0 is meaningful (season 0 = specials); must not be skipped.
        root = ET.Element("root")
        _add_text_child(root, "tag", 0)
        assert root.find("tag").text == "0"  # type: ignore[union-attr]


# --------------------------------------------------------------------------- #
# write_episode_nfo                                                           #
# --------------------------------------------------------------------------- #


def _full_episode() -> EpisodeNfo:
    return EpisodeNfo(
        title="Pilot",
        showtitle="My Show",
        season=1,
        episode=2,
        plot="The opening episode.",
        aired="2025-01-15",
        runtime_minutes=45,
        thumb_url="https://example.com/thumb.jpg",
        program_id="1-99",
    )


class TestWriteEpisodeNfo:
    def test_round_trip_full(self, tmp_path: Path) -> None:
        path = tmp_path / "ep.nfo"
        write_episode_nfo(path, _full_episode())

        root = ET.parse(path).getroot()
        assert root.tag == "episodedetails"
        assert root.findtext("title") == "Pilot"
        assert root.findtext("showtitle") == "My Show"
        assert root.findtext("season") == "1"
        assert root.findtext("episode") == "2"
        assert root.findtext("plot") == "The opening episode."
        assert root.findtext("aired") == "2025-01-15"
        assert root.findtext("runtime") == "45"
        assert root.findtext("thumb") == "https://example.com/thumb.jpg"
        assert root.findtext("studio") == "Yle"

        uid = root.find("uniqueid")
        assert uid is not None
        assert uid.get("type") == "yle"
        assert uid.get("default") == "true"
        assert uid.text == "1-99"

    def test_round_trip_sparse(self, tmp_path: Path) -> None:
        path = tmp_path / "ep.nfo"
        write_episode_nfo(
            path,
            EpisodeNfo(
                title="Some Special",
                showtitle="My Show",
                season=None,
                episode=None,
                plot="",
                aired="",
                runtime_minutes=None,
                thumb_url="",
                program_id="",
            ),
        )

        root = ET.parse(path).getroot()
        assert root.findtext("title") == "Some Special"
        assert root.findtext("showtitle") == "My Show"
        # Optional fields all omitted.
        for tag in ("season", "episode", "plot", "aired", "runtime", "thumb", "uniqueid"):
            assert root.find(tag) is None
        # studio is unconditional.
        assert root.findtext("studio") == "Yle"

    def test_season_zero_is_emitted(self, tmp_path: Path) -> None:
        path = tmp_path / "ep.nfo"
        ep = EpisodeNfo(
            title="Special",
            showtitle="My Show",
            season=0,
            episode=None,
            plot="",
            aired="",
            runtime_minutes=None,
            thumb_url="",
            program_id="",
        )
        write_episode_nfo(path, ep)

        root = ET.parse(path).getroot()
        # 0 must be emitted (specials season).
        assert root.findtext("season") == "0"

    def test_uniqueid_omitted_when_program_id_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "ep.nfo"
        ep = EpisodeNfo(
            title="X",
            showtitle="Y",
            season=1,
            episode=1,
            plot="",
            aired="",
            runtime_minutes=None,
            thumb_url="",
            program_id="",
        )
        write_episode_nfo(path, ep)

        root = ET.parse(path).getroot()
        assert root.find("uniqueid") is None


# --------------------------------------------------------------------------- #
# write_tvshow_nfo                                                            #
# --------------------------------------------------------------------------- #


class TestWriteTvshowNfo:
    def test_round_trip_full(self, tmp_path: Path) -> None:
        path = tmp_path / "tvshow.nfo"
        series = SeriesMetadata(
            series_id="1-99",
            title="My Show",
            plot="Some plot.",
            poster_url="https://example.com/poster.jpg",
            background_url="https://example.com/bg.jpg",
            image_url="https://example.com/thumb.jpg",
            logo_url="https://example.com/logo.png",
        )
        write_tvshow_nfo(path, series)

        root = ET.parse(path).getroot()
        assert root.tag == "tvshow"
        assert root.findtext("title") == "My Show"
        assert root.findtext("plot") == "Some plot."
        assert root.findtext("thumb") == "https://example.com/thumb.jpg"
        assert root.findtext("studio") == "Yle"

        uid = root.find("uniqueid")
        assert uid is not None
        assert uid.get("type") == "yle"
        assert uid.get("default") == "true"
        assert uid.text == "1-99"

    def test_uniqueid_omitted_when_series_id_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "tvshow.nfo"
        series = SeriesMetadata(
            series_id="",
            title="My Show",
            plot="",
            poster_url="",
            background_url="",
            image_url="",
            logo_url="",
        )
        write_tvshow_nfo(path, series)

        root = ET.parse(path).getroot()
        assert root.find("uniqueid") is None
        # Even with everything blank, title and studio remain.
        assert root.findtext("title") == "My Show"
        assert root.findtext("studio") == "Yle"


# --------------------------------------------------------------------------- #
# Atomic write behavior                                                       #
# --------------------------------------------------------------------------- #


class TestAtomicWrite:
    def test_pre_existing_destination_is_replaced(self, tmp_path: Path) -> None:
        path = tmp_path / "ep.nfo"
        path.write_text("<old/>", encoding="utf-8")

        write_episode_nfo(path, _full_episode())

        assert ET.parse(path).getroot().tag == "episodedetails"

    def test_no_temp_files_left_on_success(self, tmp_path: Path) -> None:
        path = tmp_path / "ep.nfo"
        write_episode_nfo(path, _full_episode())

        leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".nfo.")]
        assert leftovers == []

    def test_failure_cleans_up_temp_and_preserves_original(self, tmp_path: Path) -> None:
        path = tmp_path / "ep.nfo"
        path.write_text("<old/>", encoding="utf-8")
        original_bytes = path.read_bytes()

        with (
            patch.object(ET.ElementTree, "write", side_effect=RuntimeError("disk full")),
            pytest.raises(RuntimeError, match="disk full"),
        ):
            write_episode_nfo(path, _full_episode())

        # Original is untouched (no partial write).
        assert path.read_bytes() == original_bytes
        # Temp file cleaned up.
        leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".nfo.")]
        assert leftovers == []
