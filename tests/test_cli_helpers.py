"""Tests for pure path/season helpers in `yle_dl_plex.cli`."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import soup_of
from yle_dl_plex.cli import (
    SPECIALS_DIRNAME,
    _clean_episode_title,
    _corrected_episode_path,
    _find_video_file,
    _page_indicates_seasons,
    _parse_season_episode,
    _resolve_path,
    _series_dir,
    _show_uses_seasons,
)
from yle_dl_plex.yledl import Episode

# --------------------------------------------------------------------------- #
# _resolve_path                                                               #
# --------------------------------------------------------------------------- #


class TestResolvePath:
    def test_absolute_returned_as_is(self, tmp_path: Path) -> None:
        abs_path = tmp_path / "show" / "ep.mkv"
        result = _resolve_path(str(abs_path), tmp_path / "other")
        assert result == abs_path

    def test_relative_resolved_under_destdir(self, tmp_path: Path) -> None:
        result = _resolve_path("show/ep.mkv", tmp_path)
        assert result == tmp_path / "show" / "ep.mkv"


# --------------------------------------------------------------------------- #
# _series_dir                                                                 #
# --------------------------------------------------------------------------- #


class TestSeriesDir:
    def test_seasoned_show(self, tmp_path: Path) -> None:
        # Episode at <destdir>/My Show/Season 01/file.mkv → series dir
        # is <destdir>/My Show.
        destdir = tmp_path
        episode = destdir / "My Show" / "Season 01" / "ep.mkv"
        assert _series_dir(episode, destdir) == destdir / "My Show"

    def test_season_less_show_does_not_overshoot(self, tmp_path: Path) -> None:
        # Regression guard for AGENTS.md:46-49: episode at
        # <destdir>/My Show/file.mkv must still return <destdir>/My Show,
        # not destdir itself (which is what .parent.parent would yield).
        destdir = tmp_path
        episode = destdir / "My Show" / "ep.mkv"
        assert _series_dir(episode, destdir) == destdir / "My Show"

    def test_episode_outside_destdir_falls_back(self, tmp_path: Path) -> None:
        # If the episode isn't under destdir at all, the function falls
        # back to parent.parent.
        destdir = tmp_path / "library"
        episode = tmp_path / "elsewhere" / "show" / "ep.mkv"
        assert _series_dir(episode, destdir) == tmp_path / "elsewhere"


# --------------------------------------------------------------------------- #
# _find_video_file                                                            #
# --------------------------------------------------------------------------- #


class TestFindVideoFile:
    def test_picks_mkv_first(self, tmp_path: Path) -> None:
        base = tmp_path / "ep"
        (tmp_path / "ep.mkv").touch()
        (tmp_path / "ep.mp4").touch()
        assert _find_video_file(base) == tmp_path / "ep.mkv"

    def test_picks_mp4_when_no_mkv(self, tmp_path: Path) -> None:
        base = tmp_path / "ep"
        (tmp_path / "ep.mp4").touch()
        assert _find_video_file(base) == tmp_path / "ep.mp4"

    @pytest.mark.parametrize("ext", [".mkv", ".mp4", ".m4a", ".webm"])
    def test_picks_each_extension(self, tmp_path: Path, ext: str) -> None:
        base = tmp_path / "ep"
        (tmp_path / f"ep{ext}").touch()
        assert _find_video_file(base) == tmp_path / f"ep{ext}"

    def test_returns_none_when_absent(self, tmp_path: Path) -> None:
        assert _find_video_file(tmp_path / "missing") is None


# --------------------------------------------------------------------------- #
# _parse_season_episode                                                       #
# --------------------------------------------------------------------------- #


class TestParseSeasonEpisode:
    def test_basic_sxxexx(self) -> None:
        assert _parse_season_episode("Show - S01E02 - Title") == (1, 2)

    def test_multidigit(self) -> None:
        assert _parse_season_episode("Show - S12E34 - Title") == (12, 34)

    def test_no_match_returns_none_pair(self) -> None:
        assert _parse_season_episode("Show - 2025-01-15 - Title") == (None, None)

    def test_empty_string(self) -> None:
        assert _parse_season_episode("") == (None, None)


# --------------------------------------------------------------------------- #
# _clean_episode_title                                                        #
# --------------------------------------------------------------------------- #


class TestCleanEpisodeTitle:
    def test_strips_series_prefix_then_sxxexx(self) -> None:
        assert _clean_episode_title("My Show - S01E02 - The Pilot", "My Show") == "The Pilot"

    def test_strips_series_prefix_then_date(self) -> None:
        assert _clean_episode_title("My Show - 2025-01-15 - The Pilot", "My Show") == "The Pilot"

    def test_strips_path_component(self) -> None:
        assert (
            _clean_episode_title("/abs/path/My Show - S01E02 - The Pilot", "My Show") == "The Pilot"
        )

    def test_passthrough_when_no_match(self) -> None:
        assert _clean_episode_title("Standalone Title", "My Show") == "Standalone Title"

    def test_strips_sxxexx_without_series_prefix(self) -> None:
        # If the title starts with SxxExx directly (no series prefix),
        # strip just that.
        assert _clean_episode_title("S01E02 - The Pilot", "My Show") == "The Pilot"


# --------------------------------------------------------------------------- #
# _page_indicates_seasons                                                     #
# --------------------------------------------------------------------------- #


class TestPageIndicatesSeasons:
    @pytest.mark.parametrize(
        "token",
        ["partOfSeason", "seasonNumber", "containsSeason", "numberOfSeasons"],
    )
    def test_each_token_signals_seasons(self, token: str) -> None:
        html = f"""
        <html><head>
        <script type="application/ld+json">
        {{"@type": "TVEpisode", "{token}": "anything"}}
        </script>
        </head></html>
        """
        assert _page_indicates_seasons(soup_of(html)) is True

    def test_no_season_tokens_returns_false(self) -> None:
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type": "TVSeries", "name": "Season-less Show"}
        </script>
        </head></html>
        """
        assert _page_indicates_seasons(soup_of(html)) is False

    def test_none_soup_returns_false(self) -> None:
        assert _page_indicates_seasons(None) is False


# --------------------------------------------------------------------------- #
# _show_uses_seasons                                                          #
# --------------------------------------------------------------------------- #


def _ep(filename: str) -> Episode:
    """Tiny Episode factory for season-detection tests."""
    return Episode(
        filename=filename,
        title="",
        description="",
        thumbnail="",
        duration_seconds=0,
        publish_timestamp="",
        webpage="",
        program_id="",
    )


class TestShowUsesSeasons:
    def test_signal_1_episode_in_subdir(self, tmp_path: Path) -> None:
        destdir = tmp_path
        series_dir = destdir / "My Show"
        episodes = [_ep(str(series_dir / "Season 01" / "ep.mkv"))]
        assert _show_uses_seasons(episodes, series_dir, destdir, soup=None) is True

    def test_signal_2_existing_season_dir(self, tmp_path: Path) -> None:
        destdir = tmp_path
        series_dir = destdir / "My Show"
        (series_dir / "Season 01").mkdir(parents=True)
        # Episode itself lives in series root → no signal 1.
        episodes = [_ep(str(series_dir / "ep.mkv"))]
        assert _show_uses_seasons(episodes, series_dir, destdir, soup=None) is True

    def test_signal_3_jsonld_only(self, tmp_path: Path) -> None:
        destdir = tmp_path
        series_dir = destdir / "My Show"
        episodes = [_ep(str(series_dir / "ep.mkv"))]
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type": "TVEpisode", "partOfSeason": {"@type": "TVSeason"}}
        </script>
        </head></html>
        """
        assert _show_uses_seasons(episodes, series_dir, destdir, soup=soup_of(html)) is True

    def test_no_signals_returns_false(self, tmp_path: Path) -> None:
        destdir = tmp_path
        series_dir = destdir / "My Show"
        series_dir.mkdir()
        episodes = [_ep(str(series_dir / "ep.mkv"))]
        assert _show_uses_seasons(episodes, series_dir, destdir, soup=None) is False


# --------------------------------------------------------------------------- #
# _corrected_episode_path                                                     #
# --------------------------------------------------------------------------- #


class TestCorrectedEpisodePath:
    def test_seasoned_orphan_in_series_root_redirects_to_specials(self, tmp_path: Path) -> None:
        destdir = tmp_path
        series_dir = destdir / "My Show"
        ep = _ep(str(series_dir / "Special.mkv"))
        result = _corrected_episode_path(ep, series_dir, destdir, seasoned=True)
        assert result == series_dir / SPECIALS_DIRNAME / "Special.mkv"

    def test_seasoned_episode_in_season_subdir_unchanged(self, tmp_path: Path) -> None:
        destdir = tmp_path
        series_dir = destdir / "My Show"
        ep = _ep(str(series_dir / "Season 01" / "ep.mkv"))
        result = _corrected_episode_path(ep, series_dir, destdir, seasoned=True)
        assert result == series_dir / "Season 01" / "ep.mkv"

    def test_season_less_show_is_noop(self, tmp_path: Path) -> None:
        destdir = tmp_path
        series_dir = destdir / "My Show"
        ep = _ep(str(series_dir / "ep.mkv"))
        result = _corrected_episode_path(ep, series_dir, destdir, seasoned=False)
        assert result == series_dir / "ep.mkv"
