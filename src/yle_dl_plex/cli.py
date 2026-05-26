"""Command-line entry point + 5-stage orchestration.

Stages:
  1. Fetch per-episode metadata via the yledl Python API.
  2. Fetch the Areena series HTML page and extract series-level metadata.
  3. Download episode videos (unless --metadata-only).
  4. Write per-episode NFO + thumbnail.
  5. Write tvshow.nfo + poster.jpg + background.jpg.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import tempfile
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from yle_dl_plex import yledl
from yle_dl_plex.areena import (
    USER_AGENT,
    SeriesMetadata,
    build_series_metadata,
    extract_program_id,
    fetch_series_page,
    resize_yle_image,
)
from yle_dl_plex.nfo import EpisodeNfo, write_episode_nfo, write_tvshow_nfo
from yle_dl_plex.yledl import Episode

log = logging.getLogger("yle_dl_plex")

POSTER_WIDTH = 1000
BACKGROUND_WIDTH = 1920
VIDEO_EXTENSIONS = (".mkv", ".mp4", ".m4a", ".webm")
# Plex/Kodi convention: season 0 holds specials. Folder name matches
# yle-dl's TitleFormatter._season() shape ("Season NN").
SPECIALS_SEASON = 0
SPECIALS_DIRNAME = f"Season {SPECIALS_SEASON:02d}"

# Matches the SxxExx token anywhere in the file basename.
_SXXEXX = re.compile(r"S(\d+)E(\d+)")
# Strip leading "SxxExx - " or "YYYY-MM-DD - " from an episode title.
_LEADING_SXXEXX = re.compile(r"^S\d+E\d+ - (.*)$")
_LEADING_DATE = re.compile(r"^\d{4}-\d{2}-\d{2} - (.*)$")
# Tokens that, if present in any JSON-LD blob on the page, mean the show
# is seasoned. Cheap substring check; we don't need to parse the JSON.
_SEASON_INDICATORS_LD = ("partOfSeason", "seasonNumber", "containsSeason", "numberOfSeasons")


# --------------------------------------------------------------------------- #
# Logging                                                                     #
# --------------------------------------------------------------------------- #


class _PrefixFormatter(logging.Formatter):
    """Format every record as `[yle-dl-plex] [LEVEL] message`."""

    def format(self, record: logging.LogRecord) -> str:
        prefix = "[yle-dl-plex]"
        if record.levelno >= logging.ERROR:
            return f"{prefix} ERROR: {record.getMessage()}"
        if record.levelno >= logging.WARNING:
            return f"{prefix} WARNING: {record.getMessage()}"
        return f"{prefix} {record.getMessage()}"


def _setup_logging(verbose: bool) -> None:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_PrefixFormatter())
    root.handlers = [handler]

    # yle-dl attaches its own StreamHandler to the `yledl` logger at import
    # time. Strip it so its records only reach our prefixed handler via
    # propagation — otherwise every yle-dl log line is emitted twice (once
    # raw, once with our prefix).
    yledl_logger = logging.getLogger("yledl")
    yledl_logger.handlers = []
    yledl_logger.propagate = True

    # httpx emits a one-line INFO record for every request — far too noisy
    # for our default INFO level. Drop it to WARNING unless --verbose.
    if not verbose:
        for noisy in ("httpx", "httpcore", "urllib3"):
            logging.getLogger(noisy).setLevel(logging.WARNING)


# --------------------------------------------------------------------------- #
# HTTP                                                                        #
# --------------------------------------------------------------------------- #


def _make_http_client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=30.0,
    )


def fetch_to_file(client: httpx.Client, url: str, dest: Path) -> bool:
    """Download `url` into `dest` atomically. Returns True on success."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        response = client.get(url)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("Failed to download %s: %s", url, exc)
        return False
    if not response.content:
        log.warning("Empty body when downloading %s", url)
        return False
    fd, tmp_name = tempfile.mkstemp(prefix=".dl.", dir=str(dest.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(response.content)
        os.replace(tmp_name, dest)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise
    return True


# --------------------------------------------------------------------------- #
# Path / filename helpers                                                     #
# --------------------------------------------------------------------------- #


def _resolve_path(filename: str, destdir: Path) -> Path:
    """yle-dl emits either absolute or destdir-relative filenames; normalize."""
    path = Path(filename)
    return path if path.is_absolute() else destdir / path


def _series_dir(episode_abs_path: Path, destdir: Path) -> Path:
    # `yle-dl`'s OUTPUT_TEMPLATE always puts `${series}` as the top-level
    # directory under destdir. For shows without season metadata,
    # `${season}` collapses to empty and the season subdirectory is omitted,
    # so `.parent.parent` would overshoot to destdir itself.
    try:
        first_component = episode_abs_path.relative_to(destdir).parts[0]
    except (ValueError, IndexError):
        return episode_abs_path.parent.parent
    return destdir / first_component


def _find_video_file(base: Path) -> Path | None:
    for ext in VIDEO_EXTENSIONS:
        candidate = base.with_suffix(ext)
        if candidate.is_file():
            return candidate
    return None


def _parse_season_episode(basename: str) -> tuple[int | None, int | None]:
    match = _SXXEXX.search(basename)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def _clean_episode_title(raw_title: str, series_title: str) -> str:
    """Strip path prefix and `<series> - SxxExx - ` / date prefix off a title."""
    title = raw_title.rsplit("/", 1)[-1]
    series_prefix = f"{series_title} - "
    if title.startswith(series_prefix):
        title = title[len(series_prefix):]
    for pattern in (_LEADING_SXXEXX, _LEADING_DATE):
        match = pattern.match(title)
        if match:
            return match.group(1)
    return title


def _page_indicates_seasons(soup: BeautifulSoup | None) -> bool:
    # Look for season-structure markers in any JSON-LD blob on the page.
    # On an episode page that's the TVEpisode's partOfSeason/seasonNumber;
    # on a series page it's containsSeason/numberOfSeasons or a TVEpisode
    # listing with partOfSeason. Substring check is enough — these tokens
    # don't appear in season-less shows' JSON-LD.
    if soup is None:
        return False
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        text = script.string or script.get_text() or ""
        if any(token in text for token in _SEASON_INDICATORS_LD):
            return True
    return False


def _show_uses_seasons(
    episodes: list[Episode],
    series_dir: Path,
    destdir: Path,
    soup: BeautifulSoup | None,
) -> bool:
    # Three signals, any one is enough:
    #   1. Sibling episodes already live in a "Season NN" subdir (yle-dl
    #      rendered ${season} for them). Catches the typical series-URL
    #      run where most episodes are numbered and one is a special.
    #   2. A "Season NN" directory already exists on disk under the
    #      series root from a previous run. Catches re-runs invoked with
    #      a single-episode URL after the user deleted that file.
    #   3. JSON-LD on the fetched page mentions a season structure
    #      (partOfSeason, seasonNumber, …). Catches cold-start runs of a
    #      single-episode URL — the episode page's JSON-LD carries
    #      partOfSeason even though our metadata batch holds only one
    #      episode.
    if any(_resolve_path(ep.filename, destdir).parent != series_dir for ep in episodes):
        return True
    if series_dir.is_dir():
        for child in series_dir.iterdir():
            if child.is_dir() and child.name.startswith("Season "):
                return True
    return _page_indicates_seasons(soup)


def _corrected_episode_path(
    ep: Episode, series_dir: Path, destdir: Path, seasoned: bool
) -> Path:
    # Upstream yle-dl drops the season number for specials that lack an
    # episode_number (areena_extractors.py:83). On a seasoned show that
    # collapses ${season} → the special lands directly in the series
    # root. Redirect it into the Plex/Kodi specials folder ("Season 00").
    # Season-less shows are not affected: every episode is in the series
    # root by design, seasoned=False, and this function is a no-op.
    abs_path = _resolve_path(ep.filename, destdir)
    if not seasoned or abs_path.parent != series_dir:
        return abs_path
    return series_dir / SPECIALS_DIRNAME / abs_path.name


def _relocate_orphan_episode(
    ep: Episode, series_dir: Path, destdir: Path, seasoned: bool
) -> None:
    original = _resolve_path(ep.filename, destdir)
    corrected = _corrected_episode_path(ep, series_dir, destdir, seasoned)
    if original == corrected:
        return
    video = _find_video_file(original.with_suffix(""))
    if video is None:
        return
    target_dir = corrected.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / video.name
    if target.exists():
        return
    video.replace(target)
    log.info("Relocated special episode to specials folder: %s", target)


# --------------------------------------------------------------------------- #
# Stage runners                                                               #
# --------------------------------------------------------------------------- #


def _process_episode(
    ep: Episode,
    destdir: Path,
    series_dir: Path,
    series_title: str,
    http: httpx.Client,
    seasoned: bool,
) -> None:
    original = _resolve_path(ep.filename, destdir)
    abs_path = _corrected_episode_path(ep, series_dir, destdir, seasoned)
    base = abs_path.with_suffix("")
    base.parent.mkdir(parents=True, exist_ok=True)

    if _find_video_file(base) is None:
        log.warning("No video file found for %r — writing metadata anyway.", base.name)

    season, episode = _parse_season_episode(base.name)
    if season is None and abs_path != original:
        season = SPECIALS_SEASON
    aired = ep.publish_timestamp[:10] if ep.publish_timestamp else ""
    runtime_minutes: int | None = None
    if ep.duration_seconds > 0:
        runtime_minutes = (ep.duration_seconds + 30) // 60

    program_id = ep.program_id or extract_program_id(ep.webpage)

    write_episode_nfo(
        base.with_suffix(".nfo"),
        EpisodeNfo(
            title=_clean_episode_title(ep.title, series_title),
            showtitle=series_title,
            season=season,
            episode=episode,
            plot=ep.description,
            aired=aired,
            runtime_minutes=runtime_minutes,
            thumb_url=ep.thumbnail,
            program_id=program_id,
        ),
    )

    if ep.thumbnail:
        if not fetch_to_file(http, ep.thumbnail, base.with_suffix(".jpg")):
            log.warning("Failed to download thumbnail for %r.", base.name)
    else:
        log.warning("No thumbnail URL in metadata for %r (older yle-dl?).", base.name)


def _write_series_artwork(
    series_dir: Path,
    series: SeriesMetadata,
    http: httpx.Client,
) -> None:
    if series.poster_url:
        if not fetch_to_file(
            http, resize_yle_image(series.poster_url, POSTER_WIDTH), series_dir / "poster.jpg"
        ):
            log.warning("Failed to download series poster.")
    else:
        log.warning("No poster image found; skipping poster.jpg.")

    if series.background_url:
        if not fetch_to_file(
            http,
            resize_yle_image(series.background_url, BACKGROUND_WIDTH),
            series_dir / "background.jpg",
        ):
            log.warning("Failed to download series background.")
    else:
        log.warning("No background image found; skipping background.jpg.")

    # `series.logo_url` already points at the untransformed asset, so no
    # `resize_yle_image` call here. Absence is info-level, not a warning —
    # not every series carries a clearlogo.
    if series.logo_url:
        if not fetch_to_file(http, series.logo_url, series_dir / "clearlogo.png"):
            log.warning("Failed to download series clearlogo.")
    else:
        log.info("No clearlogo found on the series page; skipping clearlogo.png.")


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="yle-dl-plex",
        description=(
            "Download a Yle Areena TV series with yle-dl and generate "
            "Plex-compatible local metadata (NFO + artwork). In Plex, set the "
            'library agent to "Plex TV Series (NFO)" or "Personal Media '
            'Shows" with NFO support — the default TV agent ignores NFO.'
        ),
    )
    parser.add_argument("url", help="Yle Areena series URL, e.g. https://areena.yle.fi/1-62248394")
    parser.add_argument(
        "--destdir",
        default=".",
        help="Output root directory (default: current directory).",
    )
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="Skip video download; only (re)generate NFO/artwork.",
    )
    parser.add_argument(
        "--skip-metadata",
        action="store_true",
        help="Download videos only; skip NFO/artwork generation.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _setup_logging(args.verbose)

    destdir = Path(args.destdir).expanduser().resolve()
    destdir.mkdir(parents=True, exist_ok=True)

    # Stage 1: episode metadata
    log.info("Fetching episode metadata from yle-dl ...")
    episodes = yledl.fetch_episode_metadata(args.url, destdir)
    if not episodes:
        log.error("No episodes found at %s", args.url)
        return 1
    log.info("Found %d episodes.", len(episodes))

    first_abs = _resolve_path(episodes[0].filename, destdir)
    series_dir = _series_dir(first_abs, destdir)
    series_dir.mkdir(parents=True, exist_ok=True)
    log.info("Series directory: %s", series_dir)

    series_id = extract_program_id(args.url)

    with _make_http_client() as http:
        # Stage 2: series-level metadata
        log.info("Fetching series page for %s ...", series_id)
        soup = fetch_series_page(http, series_id)
        series = build_series_metadata(soup, series_id, fallback_title=series_dir.name)
        log.info("Series title: %s", series.title)
        if series.plot:
            preview = series.plot[:80] + ("..." if len(series.plot) > 80 else "")
            log.info("Series description: %s", preview)
        else:
            log.warning("No series description found (neither JSON-LD nor og:description).")

        # On seasoned shows, yle-dl drops the season for unnumbered
        # specials and they land in the series root rather than a season
        # subdir. We move them into a Plex/Kodi-style "Season 00" folder.
        # On season-less shows every episode is in the series root by
        # design, so we leave them alone.
        seasoned = _show_uses_seasons(episodes, series_dir, destdir, soup)

        # Stage 3: video download
        if args.metadata_only:
            log.info("Skipping download (--metadata-only).")
        else:
            log.info("Downloading episodes with yle-dl ...")
            try:
                code = yledl.download_clips(args.url, destdir)
            except yledl.DownloadFailed as exc:
                log.error("%s", exc)
                return 1
            if code == yledl.RD_INCOMPLETE:
                log.warning("yle-dl reported an incomplete download; continuing anyway.")
            # Move any orphan special into Season 00/ before
            # --skip-metadata short-circuits or Stage 4 runs.
            for episode in episodes:
                _relocate_orphan_episode(episode, series_dir, destdir, seasoned)

        if args.skip_metadata:
            log.info("Skipping metadata generation (--skip-metadata). Done.")
            return 0

        # Stage 4: per-episode NFO + thumbnail
        log.info("Writing per-episode NFO and thumbnails ...")
        for episode in episodes:
            _process_episode(episode, destdir, series_dir, series.title, http, seasoned)

        # Stage 5: series-level NFO + artwork
        log.info("Writing series-level metadata ...")
        _write_series_artwork(series_dir, series, http)
        write_tvshow_nfo(series_dir / "tvshow.nfo", series)

    log.info("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
