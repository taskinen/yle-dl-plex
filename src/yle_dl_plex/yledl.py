"""In-process wrapper around the `yledl` Python API.

We use the upstream Python package rather than shelling out to its CLI. The
public surface in `yledl.__all__` is enough to drive a download, but
constructing the downloader requires three helpers that live in submodules
(`yledl.http.HttpClient`, `yledl.titleformatter.TitleFormatter`,
`yledl.geolocation.AreenaGeoLocation`) — the upstream CLI entry point
(`yledl/yledl.py:main`) uses these same imports, so we accept the same
internal-API surface yle-dl itself depends on.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from yledl import RD_FAILED, RD_INCOMPLETE, RD_SUCCESS, IOContext, StreamFilters, YleDlDownloader
from yledl.geolocation import AreenaGeoLocation
from yledl.http import HttpClient
from yledl.titleformatter import TitleFormatter

# Mirrors the Bash OUTPUT_TEMPLATE — yle-dl interpolates these tokens.
OUTPUT_TEMPLATE = "${series}/${season}/${series} - ${episode_or_date} - ${title}"


@dataclass(frozen=True, slots=True)
class Episode:
    """Subset of the yle-dl metadata schema (docs/metadata.md upstream) we use."""

    filename: str
    title: str
    description: str
    thumbnail: str
    duration_seconds: int
    publish_timestamp: str
    webpage: str
    program_id: str

    @classmethod
    def from_metadata(cls, item: dict[str, Any]) -> Episode:
        return cls(
            filename=item.get("filename", ""),
            title=item.get("title", ""),
            description=item.get("description", ""),
            thumbnail=item.get("thumbnail", ""),
            duration_seconds=int(item.get("duration_seconds") or 0),
            publish_timestamp=item.get("publish_timestamp", ""),
            webpage=item.get("webpage", ""),
            program_id=item.get("program_id", ""),
        )


@dataclass(frozen=True, slots=True)
class _Wiring:
    downloader: YleDlDownloader
    io: IOContext
    filters: StreamFilters


def _build_wiring(destdir: Path, preferred_format: str = "mkv") -> _Wiring:
    # `preferred_format` and `resume` are left at None/False by IOContext
    # but the yle-dl CLI always sets them (defaults: 'mkv', True). Without
    # `preferred_format`, `Downloader.file_extension()` crashes during a
    # real download. With `resume=True`, re-runs skip already-downloaded
    # files instead of refusing to overwrite.
    io = IOContext(
        destdir=str(destdir),
        create_dirs=True,
        preferred_format=preferred_format,
        resume=True,
    )
    httpclient = HttpClient(io)
    title_formatter = TitleFormatter(OUTPUT_TEMPLATE)
    geolocation = AreenaGeoLocation(httpclient)
    downloader = YleDlDownloader(geolocation, title_formatter, httpclient)
    filters = StreamFilters()
    return _Wiring(downloader=downloader, io=io, filters=filters)


def fetch_episode_metadata(url: str, destdir: Path, preferred_format: str = "mkv") -> list[Episode]:
    """Return one Episode per stream detected at `url`.

    Mirrors `yle-dl --showmetadata` but skips the JSON-on-stdout round trip.
    """
    w = _build_wiring(destdir, preferred_format=preferred_format)
    raw = w.downloader.get_metadata(url, w.io, latest_only=False)
    return [Episode.from_metadata(item) for item in raw]


class DownloadFailed(RuntimeError):
    """yle-dl returned RD_FAILED."""


def download_clips(url: str, destdir: Path, preferred_format: str = "mkv") -> int:
    """Download every clip discovered at `url`. Returns the yle-dl exit code.

    Raises DownloadFailed when the result is RD_FAILED. RD_INCOMPLETE is
    returned as-is so the caller can warn instead of aborting.
    """
    w = _build_wiring(destdir, preferred_format=preferred_format)
    code: int = int(w.downloader.download_clips(url, w.io, w.filters))
    if code == RD_FAILED:
        raise DownloadFailed(f"yle-dl reported a failure downloading {url!r}")
    return code


__all__ = [
    "OUTPUT_TEMPLATE",
    "RD_INCOMPLETE",
    "RD_SUCCESS",
    "DownloadFailed",
    "Episode",
    "download_clips",
    "fetch_episode_metadata",
]
