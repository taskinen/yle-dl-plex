# yle-dl-plex

Downloads a Yle Areena TV series with `yle-dl` and writes Plex-compatible
local metadata (Kodi/XBMC-style NFO + artwork) so a Plex library configured
with the **Plex TV Series (NFO)** or **Personal Media Shows** agent picks
the series up offline.

> **Plex caveat.** The default *Plex TV Series* agent ignores `.nfo` files.
> The library must use an NFO-capable agent for this output to be visible.

This file documents design decisions for the Python implementation. **Keep
it in sync with the code** — if you change a module's responsibility, the
fallback chain, the output layout, or a dependency contract, update the
corresponding section here.

Documentation about how Plex expects the metadata to be saved can be found
from the Plex website at the following pages:

* https://support.plex.tv/articles/using-nfo-metadata-files-with-plex/
* https://support.plex.tv/articles/200220717-local-media-assets-tv-shows/

## Output layout

```
<destdir>/<series>/
  tvshow.nfo
  poster.jpg
  background.jpg
  clearlogo.png                       (optional — only if a logo is on the page)
  <season>/
    season.nfo                          (optional — not currently written)
    <series> - <SxxExx|date> - <title>.mkv     (or .mp4 / .m4a / .webm)
    <series> - <SxxExx|date> - <title>.nfo
    <series> - <SxxExx|date> - <title>.jpg
```

The directory + filename structure comes from the `yle-dl` output template
`${series}/${season}/${series} - ${episode_or_date} - ${title}`, which lives
in `yle_dl_plex.yledl.OUTPUT_TEMPLATE` and is passed to `TitleFormatter`.

**Season-less shows.** When the series has no `Kausi N` season markers (a
date-only show like https://areena.yle.fi/1-63711925), `TitleFormatter`
expands `${season}` to the empty string. The surrounding `/` literals
remain, so the rendered path collapses to a single separator and episodes
land directly in `<destdir>/<series>/` without a `<season>/` subdirectory.
`cli._series_dir()` derives the series directory as the first path
component below `destdir`, which works for both layouts — do **not**
revert to `episode.parent.parent`, which overshoots to `destdir` itself
in the season-less case.

**Specials inside a seasoned show.** Upstream yle-dl only extracts the
season number when an `episode_number` is present
(`yledl/areena_extractors.py:83`). For an unnumbered special inside a
seasoned series, that drops the season → `${season}` collapses → the
video lands in the series root next to `tvshow.nfo` instead of in a
season subdir. We don't try to recover the original season number;
instead, **all such specials are relocated into a `Season 00/`
subdirectory** (Plex/Kodi specials convention), and the NFO carries
`<season>0</season>` with no `<episode>`. The folder name uses the same
`Season NN` shape yle-dl's `TitleFormatter._season()` produces.

Detection runs with no extra HTTP — it reuses the soup already fetched
in Stage 2. `_show_uses_seasons()` returns `True` if *any* of three
signals holds:

1. At least one `Episode.filename` resolves to a subdirectory of the
   series root (the typical series-URL run with one orphan special
   among many numbered episodes).
2. A `Season NN/` directory already exists on disk under the series
   root from a previous run (catches re-runs invoked with a single
   episode URL after that file was deleted).
3. JSON-LD on the fetched page contains a season-structure token
   (`partOfSeason`, `seasonNumber`, `containsSeason`, `numberOfSeasons`).
   Catches cold-start runs of a single-episode URL — the episode page
   alone carries `partOfSeason` even though the metadata batch holds
   only that one episode.

If all three are false the show is season-less by design and
`_corrected_episode_path()` is a no-op — season-less shows must still
place every episode directly in `<series>/`, not in `Season 00/`.
`_relocate_orphan_episode()` runs right after Stage 3 (so
`--skip-metadata` also benefits) and is idempotent on re-runs.

## Module responsibilities

- `cli.py` — argparse, logging setup, 5-stage orchestration, the
  per-episode loop, and the HTTP fetch helper. Single entry point: `main()`.
- `yledl.py` — thin wrapper around the upstream `yledl` Python API. Builds
  the `YleDlDownloader` wiring and exposes `fetch_episode_metadata()` +
  `download_clips()`. Defines the `Episode` dataclass.
- `areena.py` — Areena series-page parsing. JSON-LD walk, `og:*` meta tag
  fallback, hero-image srcset discovery, transparent-PNG logo discovery,
  and the `images.cdn.yle.fi` `w_<n>` resize helper. Exposes
  `SeriesMetadata` and `build_series_metadata()`.
- `nfo.py` — Plex/Kodi NFO writers using `xml.etree.ElementTree` with
  atomic writes (temp file → `os.replace`).

## yle-dl Python API — caveat

`yledl/__init__.py`'s `__all__` exports `YleDlDownloader`, `IOContext`,
`StreamFilters`, `StreamAction`, and the `RD_*` exit codes. Wiring
`YleDlDownloader` also needs three classes that are **not** in `__all__`:

```python
from yledl.http import HttpClient
from yledl.titleformatter import TitleFormatter
from yledl.geolocation import AreenaGeoLocation
```

We accept this internal-API surface because the upstream CLI entry point
(`yledl/yledl.py:main`) uses the exact same imports — any rename would
break upstream's own bin script in the same release. If upstream does
break, the fix is local to `yledl.py`.

`ffmpeg` must be on `PATH` (the downloader shells out to it for muxing).
This is the same constraint as the CLI.

`fetch_episode_metadata()` returns the same dicts that
`yle-dl --showmetadata` would JSON-serialize; the upstream schema is
documented in [docs/metadata.md][yledl-metadata] in the yle-dl repo. We
coerce the dicts to a frozen `Episode` dataclass at the boundary.

**Logging gotcha.** `yledl` attaches its own `StreamHandler` to the
`yledl` logger at import time. Left alone, every yle-dl message is
emitted twice: once raw by yle-dl's handler, and once with our
`[yle-dl-plex]` prefix after propagation to the root logger.
`cli._setup_logging` strips that handler so records flow only through
ours. We also clamp `httpx`/`httpcore`/`urllib3` to `WARNING` unless
`--verbose` — httpx's INFO records (one per request) are too noisy.

**`IOContext` gotcha.** Two fields the yle-dl CLI always populates
default to `None`/`False` when you construct `IOContext` yourself:

- `preferred_format` — `None` by default; the CLI sets `'mkv'` (the
  `--preferformat` default). If you leave it as `None`, the first real
  download crashes in `Downloader.file_extension()` with
  `AttributeError: 'NoneType' object has no attribute 'startswith'`.
- `resume` — `False` by default; the CLI sets `True`. With resume off,
  re-runs refuse to overwrite existing files instead of skipping them.

`yledl._build_wiring` sets both explicitly to match the CLI's behavior.

[yledl-metadata]: https://github.com/aajanki/yle-dl/blob/master/docs/metadata.md

## Series-page fallback chain

Implemented in `areena.build_series_metadata()`:

| field        | preference                                                |
|--------------|-----------------------------------------------------------|
| `title`      | JSON-LD `name` → `og:title` → on-disk directory name      |
| `plot`       | JSON-LD `description` → `og:description` → empty          |
| `background` | Hero 4K `ar_16:9` → JSON-LD `image[0]` → `og:image`       |
| `poster`     | JSON-LD `image[1]` → `background` → `og:image`            |
| `image` (for `<thumb>`) | `poster` → `background` → `og:image`           |
| `logo` (for `clearlogo.png`) | `<link rel=preload>` `crop_limit,w_<n>` URL → empty |

**Hero preference rationale.** Areena's `<link rel="preload" as="image">`
elements advertise a 16:9 hero rendition that **omits the show
title/logo overlay**. JSON-LD `image[0]` is the same scene *with* the
overlay baked in. For Plex's `background.jpg` we much prefer the clean
hero.

**Episode-page blur quirk.** When the user passes an *episode* URL
rather than a series URL, the page serves the hero as a decorative
*blurred* backdrop (`crop_fill,ar_16:9,…,blur_60`). The image ID is the
same as the sharp rendition on the series page — the CDN's
transformation chain just has an extra `blur_<n>` token. The hero
picker (`_extract_hero_background`) strips `,blur_<n>` from each
candidate before comparing widths; the underlying CDN serves a sharp
image when the blur transformation is removed. Verified: sharp 4K is
~1.5 MB, blurred is ~240 KB.

## Image URL resizing

Two CDN hosts appear in series pages:

- `images.cdn.yle.fi` — supports on-the-fly resize via a `w_<n>` segment
  in the path. We rewrite this with `resize_yle_image()` to request
  poster at **1000 px** and background at **1920 px** wide.
- `img.img-cdn.yle.fi` — the preload hero CDN. Multiple widths are
  advertised in the `imagesrcset`/`srcset` attribute and we already pick
  the widest, so we leave the URL alone. The same host serves the
  transparent-PNG show logo via a separate `crop_limit,w_<n>` preload
  link; `_extract_logo()` strips that transformation segment to request
  the original, full-resolution asset (saved as `clearlogo.png`).

## yle-dl version pinning

`yle-dl >= 20250730`. Older versions don't expose the `thumbnail` metadata
field nor emit absolute paths in `filename` from `--showmetadata`. The
Python wrapper still handles relative `filename` values via
`_resolve_path()`, but the absolute-path form (≥ 20250730) is what we test
against.

## CLI surface

Single console-script `yle-dl-plex` (registered in `pyproject.toml` →
`yle_dl_plex.cli:main`). Positional `url`, plus:

| flag | effect |
|------|--------|
| `--destdir DIR` | Output root (default: cwd). Created if missing. |
| `--metadata-only` | Skip video download; only write NFO + artwork. |
| `--skip-metadata` | Download videos only; skip NFO + artwork. |
| `-v, --verbose` | Lift logging to DEBUG and let httpx INFO through. |
| `-h, --help` | argparse-generated help. |

`--metadata-only` and `--skip-metadata` are not mutually exclusive in
argparse, but `--skip-metadata` short-circuits before Stage 4/5, so
passing both is equivalent to `--metadata-only --skip-metadata` →
nothing happens after Stage 3 except a "Skipping…" log line.

## Install + run

```bash
uv sync
uv run yle-dl-plex --destdir /path/to/library https://areena.yle.fi/1-62248394
```

Or for re-running metadata generation only (skip download):

```bash
uv run yle-dl-plex --metadata-only --destdir /path/to/library \
  https://areena.yle.fi/1-62248394
```

## Maintenance

Per the user's global instruction: **keep this file up to date with code
changes**. If you change a module's role, the output layout, the fallback
chain, an image size, or a dependency contract, update the relevant
section here in the same commit.
