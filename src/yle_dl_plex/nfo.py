"""Plex/Kodi NFO writers.

We build the XML with `xml.etree.ElementTree` — proper escaping happens
automatically, so the Bash `xml_escape` hand-rolled helper is gone. Files
are written atomically (temp file + os.replace) to avoid leaving a partial
NFO on disk if the process crashes mid-write.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from yle_dl_plex.areena import SeriesMetadata


@dataclass(frozen=True, slots=True)
class EpisodeNfo:
    title: str
    showtitle: str
    season: int | None
    episode: int | None
    plot: str
    aired: str  # ISO date (YYYY-MM-DD)
    runtime_minutes: int | None
    thumb_url: str
    program_id: str


def _add_text_child(parent: ET.Element, tag: str, text: str | int | None) -> None:
    """Append `<tag>text</tag>` only when `text` is non-empty / non-None.

    Mirrors the Bash conditional emission of optional fields.
    """
    if text is None or text == "":
        return
    elem = ET.SubElement(parent, tag)
    elem.text = str(text)


def _write_tree_atomic(tree: ET.ElementTree, path: Path) -> None:
    """Pretty-print + atomically replace `path`."""
    ET.indent(tree, space="  ")
    fd, tmp_name = tempfile.mkstemp(prefix=".nfo.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            tree.write(handle, encoding="utf-8", xml_declaration=True)
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise


def write_episode_nfo(path: Path, ep: EpisodeNfo) -> None:
    root = ET.Element("episodedetails")
    _add_text_child(root, "title", ep.title)
    _add_text_child(root, "showtitle", ep.showtitle)
    _add_text_child(root, "season", ep.season)
    _add_text_child(root, "episode", ep.episode)
    _add_text_child(root, "plot", ep.plot)
    _add_text_child(root, "aired", ep.aired)
    _add_text_child(root, "runtime", ep.runtime_minutes)
    _add_text_child(root, "thumb", ep.thumb_url)
    _add_text_child(root, "studio", "Yle")
    if ep.program_id:
        uid = ET.SubElement(root, "uniqueid", attrib={"type": "yle", "default": "true"})
        uid.text = ep.program_id
    _write_tree_atomic(ET.ElementTree(root), path)


def write_tvshow_nfo(path: Path, series: SeriesMetadata) -> None:
    root = ET.Element("tvshow")
    _add_text_child(root, "title", series.title)
    _add_text_child(root, "plot", series.plot)
    _add_text_child(root, "thumb", series.image_url)
    _add_text_child(root, "studio", "Yle")
    if series.series_id:
        uid = ET.SubElement(root, "uniqueid", attrib={"type": "yle", "default": "true"})
        uid.text = series.series_id
    _write_tree_atomic(ET.ElementTree(root), path)


__all__ = ["EpisodeNfo", "write_episode_nfo", "write_tvshow_nfo"]
