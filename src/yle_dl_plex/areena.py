"""Areena series-page metadata extraction.

Pulls a series' title/plot/poster/background from the Areena HTML page. We
prefer the embedded JSON-LD `TVSeries` node (single line, structured) and
fall back to `og:*` meta tags. We pick a separate hero image for the
background because the 4K `ar_16:9` rendition served via
`<link rel="preload" as="image">` omits the title/logo overlay that the
JSON-LD `image[0]` includes — a much better `background.jpg`.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Iterator
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup, Tag

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) yle-dl-plex/1.0"

# Yle CDN URL patterns:
#   images.cdn.yle.fi  — supports on-the-fly resize via `w_<n>` in the path
#   img.img-cdn.yle.fi — preload hero images; multiple sizes already advertised
#                        in srcset, so we only pick the widest there
_IMAGES_CDN_HOST = "images.cdn.yle.fi"
# Match a single hero image URL anywhere inside an attribute value. Stop at
# whitespace or quote chars — these never appear inside a CDN URL. We do NOT
# stop at "," because Yle's URLs legitimately contain commas (`w_640,ar_16:9`).
_HERO_URL_PATTERN = re.compile(r"https://img\.img-cdn\.yle\.fi/[^\s\"'<>]*?ar_16:9[^\s\"'<>]*")
_WIDTH_TOKEN = re.compile(r"w_(\d+)")
# Logo: a `<link rel=preload as=image>` whose URL uses the `crop_limit,w_<n>`
# transformation chain. JSON-LD poster URLs share the `crop_limit` family but
# carry an extra `h_<n>` token; we'd reject those with the `/<id>` anchor at
# the end of the pattern, but the preload-link scope keeps them out anyway.
_LOGO_URL_PATTERN = re.compile(r"https://img\.img-cdn\.yle\.fi/crop_limit,w_\d+/[\w-]+")
# Strip the transformation segment to request the original untransformed
# asset — that's the full-resolution transparent PNG.
_LOGO_TRANSFORM = re.compile(r"/crop_limit,w_\d+/")
# Episode pages serve the hero as a decorative *blurred* backdrop
# (`crop_fill,ar_16:9,…,blur_60`). The image ID is identical to the sharp
# rendition on the series page — the CDN's transformation chain just has
# one extra `blur_<n>` token. Stripping it yields a sharp image (verified
# on `img.img-cdn.yle.fi`: same path, smaller file with blur, larger
# without).
_BLUR_TOKEN = re.compile(r",blur_\d+")

log = logging.getLogger("yle_dl_plex")


@dataclass(frozen=True, slots=True)
class SeriesMetadata:
    series_id: str
    title: str
    plot: str
    poster_url: str
    background_url: str
    image_url: str  # fallback for <thumb> in tvshow.nfo
    logo_url: str  # transparent PNG wordmark for clearlogo.png; "" if not found


def extract_program_id(url: str) -> str:
    """Pull a Yle program ID (e.g. "1-62248394") from any Areena URL."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    return path.rsplit("/", 1)[-1] if path else ""


def fetch_series_page(client: httpx.Client, series_id: str) -> BeautifulSoup | None:
    """Fetch the Areena series page; return parsed soup or None on failure."""
    url = f"https://areena.yle.fi/{series_id}"
    try:
        response = client.get(url)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("Could not fetch series page %s: %s", url, exc)
        return None
    return BeautifulSoup(response.text, "lxml")


def _walk_objects(node: Any) -> Iterator[dict[str, Any]]:
    """Yield every dict found anywhere in a nested JSON structure."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk_objects(v)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_objects(item)


def _extract_jsonld_tvseries(soup: BeautifulSoup) -> dict[str, Any] | None:
    """Return the first schema.org TVSeries object in any JSON-LD <script>."""
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        text = script.string or script.get_text()
        if not text:
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        for obj in _walk_objects(data):
            if obj.get("@type") == "TVSeries":
                return obj
    return None


def _jsonld_first(value: Any) -> str:
    """Coerce a JSON-LD field to a single string (taking [0] for arrays)."""
    if isinstance(value, list):
        return str(value[0]) if value else ""
    if value is None:
        return ""
    return str(value)


def _jsonld_nth(value: Any, idx: int) -> str:
    if isinstance(value, list) and idx < len(value):
        return str(value[idx])
    return ""


def _extract_og_meta(soup: BeautifulSoup, prop: str) -> str:
    tag = soup.find("meta", attrs={"property": prop})
    if not isinstance(tag, Tag):
        return ""
    content = tag.get("content", "")
    return str(content) if content else ""


def _extract_hero_background(soup: BeautifulSoup) -> str:
    """Pick the widest 16:9 hero image from any <link rel=preload as=image>.

    We don't try to parse srcset format — Yle's URLs contain commas
    (`w_640,ar_16:9`), and splitting on commas mangles them. Instead we
    grep every URL matching the hero pattern out of the raw attribute
    text and pick the one with the largest `w_<n>`, matching the Bash
    version's whole-page grep approach.
    """
    candidates: list[tuple[int, str]] = []
    for link in soup.find_all("link", attrs={"rel": "preload"}):
        if not isinstance(link, Tag) or link.get("as") != "image":
            continue
        haystack_parts: list[str] = []
        for attr in ("imagesrcset", "srcset", "imagesrc", "href"):
            value = link.get(attr)
            if isinstance(value, str) and value:
                haystack_parts.append(value)
        haystack = " ".join(haystack_parts)
        for url in _HERO_URL_PATTERN.findall(haystack):
            url = _BLUR_TOKEN.sub("", url)
            match = _WIDTH_TOKEN.search(url)
            width = int(match.group(1)) if match else 0
            candidates.append((width, url))
    if not candidates:
        return ""
    return max(candidates, key=lambda pair: pair[0])[1]


def _extract_logo(soup: BeautifulSoup) -> str:
    """Pick the show's transparent PNG logo from any <link rel=preload as=image>.

    Scoped to preload-link tags (same as `_extract_hero_background`) so we
    don't accidentally match the JSON-LD poster URLs that share the
    `crop_limit` family. Strips the `crop_limit,w_<n>/` transformation to
    return the original untransformed asset URL.
    """
    for link in soup.find_all("link", attrs={"rel": "preload"}):
        if not isinstance(link, Tag) or link.get("as") != "image":
            continue
        haystack_parts: list[str] = []
        for attr in ("imagesrcset", "srcset", "imagesrc", "href"):
            value = link.get(attr)
            if isinstance(value, str) and value:
                haystack_parts.append(value)
        haystack = " ".join(haystack_parts)
        for url in _LOGO_URL_PATTERN.findall(haystack):
            return _LOGO_TRANSFORM.sub("/", url)
    return ""


def resize_yle_image(url: str, width: int) -> str:
    """Rewrite an `images.cdn.yle.fi` URL to request a different width.

    Other hosts (notably `img.img-cdn.yle.fi`) are returned unchanged —
    `_extract_hero_background` already picked the largest size available.
    """
    if _IMAGES_CDN_HOST in url:
        return _WIDTH_TOKEN.sub(f"w_{width}", url)
    return url


def build_series_metadata(
    soup: BeautifulSoup | None,
    series_id: str,
    fallback_title: str,
) -> SeriesMetadata:
    """Resolve series-level fields with the fallback chain from the Bash version.

    title:      JSON-LD name -> og:title -> on-disk dir name
    plot:       JSON-LD description -> og:description -> "" (right-stripped)
    background: hero (4K) -> JSON-LD image[0] -> og:image
    poster:     JSON-LD image[1] -> background -> og:image
    image:      poster -> background -> og:image  (fallback for <thumb>)
    logo:      `<link rel=preload>` `crop_limit,w_<n>` URL, stripped to the
                untransformed asset; "" if no logo preload link is present.
    """
    jsonld: dict[str, Any] = {}
    og_title = og_desc = og_image = ""
    if soup is not None:
        jsonld = _extract_jsonld_tvseries(soup) or {}
        og_title = _extract_og_meta(soup, "og:title")
        og_desc = _extract_og_meta(soup, "og:description")
        og_image = _extract_og_meta(soup, "og:image")
        hero = _extract_hero_background(soup)
        logo = _extract_logo(soup)
    else:
        hero = ""
        logo = ""

    title = _jsonld_first(jsonld.get("name")) or og_title or fallback_title
    plot = (_jsonld_first(jsonld.get("description")) or og_desc).rstrip()

    background = hero or _jsonld_nth(jsonld.get("image"), 0) or og_image
    poster = _jsonld_nth(jsonld.get("image"), 1) or background or og_image
    # `image` (used for <thumb>) prefers the poster, then background, then og.
    image = poster or background or og_image

    return SeriesMetadata(
        series_id=series_id,
        title=title,
        plot=plot,
        poster_url=poster,
        background_url=background,
        image_url=image,
        logo_url=logo,
    )


__all__ = [
    "USER_AGENT",
    "SeriesMetadata",
    "build_series_metadata",
    "extract_program_id",
    "fetch_series_page",
    "resize_yle_image",
]
