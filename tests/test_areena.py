"""Tests for `yle_dl_plex.areena` pure functions."""

from __future__ import annotations

import pytest

from tests.conftest import soup_of
from yle_dl_plex.areena import (
    SeriesMetadata,
    _extract_hero_background,
    _extract_jsonld_tvseries,
    _extract_logo,
    _extract_og_meta,
    _jsonld_first,
    _jsonld_nth,
    _walk_objects,
    build_series_metadata,
    extract_program_id,
    resize_yle_image,
)

# --------------------------------------------------------------------------- #
# extract_program_id                                                          #
# --------------------------------------------------------------------------- #


class TestExtractProgramId:
    def test_full_url(self) -> None:
        assert extract_program_id("https://areena.yle.fi/1-62248394") == "1-62248394"

    def test_trailing_slash(self) -> None:
        assert extract_program_id("https://areena.yle.fi/1-62248394/") == "1-62248394"

    def test_bare_id_path(self) -> None:
        assert extract_program_id("/1-62248394") == "1-62248394"

    def test_empty_path(self) -> None:
        assert extract_program_id("https://areena.yle.fi") == ""

    def test_deeper_path(self) -> None:
        assert extract_program_id("https://areena.yle.fi/podcastit/1-99") == "1-99"


# --------------------------------------------------------------------------- #
# resize_yle_image                                                            #
# --------------------------------------------------------------------------- #


class TestResizeYleImage:
    def test_images_cdn_host_rewrites_width(self) -> None:
        url = "https://images.cdn.yle.fi/image/upload/w_640,ar_16:9/v123/abc.jpg"
        assert resize_yle_image(url, 1920) == (
            "https://images.cdn.yle.fi/image/upload/w_1920,ar_16:9/v123/abc.jpg"
        )

    def test_img_cdn_host_unchanged(self) -> None:
        url = "https://img.img-cdn.yle.fi/foo/w_640,ar_16:9/bar.jpg"
        assert resize_yle_image(url, 1920) == url

    def test_no_width_token_unchanged(self) -> None:
        url = "https://images.cdn.yle.fi/image/upload/ar_16:9/v123/abc.jpg"
        assert resize_yle_image(url, 1920) == url


# --------------------------------------------------------------------------- #
# _walk_objects                                                               #
# --------------------------------------------------------------------------- #


class TestWalkObjects:
    def test_yields_nested_dicts(self) -> None:
        node = {"a": 1, "b": {"c": 2, "d": [{"e": 3}, {"f": 4}]}}
        results = list(_walk_objects(node))
        assert {"a": 1, "b": {"c": 2, "d": [{"e": 3}, {"f": 4}]}} in results
        assert {"c": 2, "d": [{"e": 3}, {"f": 4}]} in results
        assert {"e": 3} in results
        assert {"f": 4} in results

    def test_scalar_yields_nothing(self) -> None:
        assert list(_walk_objects(42)) == []
        assert list(_walk_objects("hello")) == []
        assert list(_walk_objects(None)) == []

    def test_empty_collections(self) -> None:
        assert list(_walk_objects([])) == []
        assert list(_walk_objects({})) == [{}]


# --------------------------------------------------------------------------- #
# _jsonld_first / _jsonld_nth                                                 #
# --------------------------------------------------------------------------- #


class TestJsonldFirst:
    def test_list_returns_first(self) -> None:
        assert _jsonld_first(["a", "b"]) == "a"

    def test_empty_list_returns_empty(self) -> None:
        assert _jsonld_first([]) == ""

    def test_scalar_returned_as_str(self) -> None:
        assert _jsonld_first("hello") == "hello"
        assert _jsonld_first(42) == "42"

    def test_none_returns_empty(self) -> None:
        assert _jsonld_first(None) == ""


class TestJsonldNth:
    def test_list_index(self) -> None:
        assert _jsonld_nth(["a", "b", "c"], 1) == "b"

    def test_out_of_range_returns_empty(self) -> None:
        assert _jsonld_nth(["a"], 5) == ""

    def test_scalar_returns_empty(self) -> None:
        assert _jsonld_nth("hello", 0) == ""

    def test_none_returns_empty(self) -> None:
        assert _jsonld_nth(None, 0) == ""


# --------------------------------------------------------------------------- #
# _extract_jsonld_tvseries                                                    #
# --------------------------------------------------------------------------- #


class TestExtractJsonldTVSeries:
    def test_top_level_tvseries(self) -> None:
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type": "TVSeries", "name": "My Show"}
        </script>
        </head></html>
        """
        result = _extract_jsonld_tvseries(soup_of(html))
        assert result is not None
        assert result["name"] == "My Show"

    def test_nested_in_graph(self) -> None:
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@graph": [
          {"@type": "WebPage"},
          {"@type": "TVSeries", "name": "Nested Show"}
        ]}
        </script>
        </head></html>
        """
        result = _extract_jsonld_tvseries(soup_of(html))
        assert result is not None
        assert result["name"] == "Nested Show"

    def test_multiple_script_blocks_finds_in_second(self) -> None:
        html = """
        <html><head>
        <script type="application/ld+json">{"@type": "WebPage"}</script>
        <script type="application/ld+json">{"@type": "TVSeries", "name": "Second"}</script>
        </head></html>
        """
        result = _extract_jsonld_tvseries(soup_of(html))
        assert result is not None
        assert result["name"] == "Second"

    def test_malformed_json_is_skipped(self) -> None:
        html = """
        <html><head>
        <script type="application/ld+json">{not valid json</script>
        <script type="application/ld+json">{"@type": "TVSeries", "name": "After Malformed"}</script>
        </head></html>
        """
        result = _extract_jsonld_tvseries(soup_of(html))
        assert result is not None
        assert result["name"] == "After Malformed"

    def test_no_tvseries_returns_none(self) -> None:
        html = """
        <html><head>
        <script type="application/ld+json">{"@type": "WebPage"}</script>
        </head></html>
        """
        assert _extract_jsonld_tvseries(soup_of(html)) is None

    def test_no_ldjson_returns_none(self) -> None:
        assert _extract_jsonld_tvseries(soup_of("<html></html>")) is None


# --------------------------------------------------------------------------- #
# _extract_og_meta                                                            #
# --------------------------------------------------------------------------- #


class TestExtractOgMeta:
    def test_present(self) -> None:
        html = '<html><head><meta property="og:title" content="Hello"></head></html>'
        assert _extract_og_meta(soup_of(html), "og:title") == "Hello"

    def test_missing(self) -> None:
        assert _extract_og_meta(soup_of("<html></html>"), "og:title") == ""

    def test_empty_content(self) -> None:
        html = '<html><head><meta property="og:title" content=""></head></html>'
        assert _extract_og_meta(soup_of(html), "og:title") == ""


# --------------------------------------------------------------------------- #
# _extract_hero_background                                                    #
# --------------------------------------------------------------------------- #


class TestExtractHeroBackground:
    def test_picks_widest_of_multiple_widths(self) -> None:
        html = """
        <html><head>
        <link rel="preload" as="image"
              imagesrcset="https://img.img-cdn.yle.fi/img/w_640,ar_16:9/abc 640w,
                           https://img.img-cdn.yle.fi/img/w_1920,ar_16:9/abc 1920w,
                           https://img.img-cdn.yle.fi/img/w_3840,ar_16:9/abc 3840w">
        </head></html>
        """
        result = _extract_hero_background(soup_of(html))
        assert result == "https://img.img-cdn.yle.fi/img/w_3840,ar_16:9/abc"

    def test_strips_blur_token(self) -> None:
        html = """
        <html><head>
        <link rel="preload" as="image"
              href="https://img.img-cdn.yle.fi/img/crop_fill,ar_16:9,w_1920,blur_60/abc">
        </head></html>
        """
        result = _extract_hero_background(soup_of(html))
        assert "blur_" not in result
        assert result == "https://img.img-cdn.yle.fi/img/crop_fill,ar_16:9,w_1920/abc"

    def test_ignores_non_preload_links(self) -> None:
        html = """
        <html><head>
        <link rel="stylesheet" as="image"
              href="https://img.img-cdn.yle.fi/img/w_3840,ar_16:9/abc">
        <link rel="preload" as="font"
              href="https://img.img-cdn.yle.fi/img/w_3840,ar_16:9/abc">
        </head></html>
        """
        assert _extract_hero_background(soup_of(html)) == ""

    def test_no_candidates_returns_empty(self) -> None:
        assert _extract_hero_background(soup_of("<html></html>")) == ""


# --------------------------------------------------------------------------- #
# _extract_logo                                                               #
# --------------------------------------------------------------------------- #


class TestExtractLogo:
    def test_strips_crop_limit_transform(self) -> None:
        html = """
        <html><head>
        <link rel="preload" as="image"
              href="https://img.img-cdn.yle.fi/crop_limit,w_400/logo-id-123">
        </head></html>
        """
        result = _extract_logo(soup_of(html))
        assert result == "https://img.img-cdn.yle.fi/logo-id-123"

    def test_returns_empty_when_absent(self) -> None:
        assert _extract_logo(soup_of("<html></html>")) == ""

    def test_not_confused_by_jsonld_poster_urls(self) -> None:
        # JSON-LD `image` URLs share `crop_limit` family but are inside
        # <script>, not preload links. _extract_logo only scans preload
        # links so it must NOT pick these up.
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type": "TVSeries",
         "image": ["https://img.img-cdn.yle.fi/crop_limit,w_640,h_360/poster-id"]}
        </script>
        </head></html>
        """
        assert _extract_logo(soup_of(html)) == ""


# --------------------------------------------------------------------------- #
# build_series_metadata — fallback chain                                      #
# --------------------------------------------------------------------------- #


class TestBuildSeriesMetadata:
    def test_soup_none_uses_fallback_title(self) -> None:
        result = build_series_metadata(None, "1-99", fallback_title="Dirname")
        assert result == SeriesMetadata(
            series_id="1-99",
            title="Dirname",
            plot="",
            poster_url="",
            background_url="",
            image_url="",
            logo_url="",
        )

    def test_title_jsonld_wins(self) -> None:
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type": "TVSeries", "name": "From JSON-LD"}
        </script>
        <meta property="og:title" content="From og">
        </head></html>
        """
        result = build_series_metadata(soup_of(html), "id", fallback_title="dir")
        assert result.title == "From JSON-LD"

    def test_title_og_when_no_jsonld(self) -> None:
        html = '<html><head><meta property="og:title" content="From og"></head></html>'
        result = build_series_metadata(soup_of(html), "id", fallback_title="dir")
        assert result.title == "From og"

    def test_title_fallback_to_dir(self) -> None:
        result = build_series_metadata(soup_of("<html></html>"), "id", fallback_title="dir")
        assert result.title == "dir"

    def test_plot_jsonld_wins_and_is_rstripped(self) -> None:
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type": "TVSeries", "description": "From JSON-LD.   \\n"}
        </script>
        <meta property="og:description" content="From og">
        </head></html>
        """
        result = build_series_metadata(soup_of(html), "id", fallback_title="dir")
        assert result.plot == "From JSON-LD."

    def test_plot_og_fallback(self) -> None:
        html = '<html><head><meta property="og:description" content="From og   "></head></html>'
        result = build_series_metadata(soup_of(html), "id", fallback_title="dir")
        assert result.plot == "From og"

    def test_plot_empty_when_absent(self) -> None:
        result = build_series_metadata(soup_of("<html></html>"), "id", fallback_title="dir")
        assert result.plot == ""

    def test_background_prefers_hero(self) -> None:
        html = """
        <html><head>
        <link rel="preload" as="image"
              href="https://img.img-cdn.yle.fi/img/w_3840,ar_16:9/hero">
        <script type="application/ld+json">
        {"@type": "TVSeries",
         "image": ["https://images.cdn.yle.fi/jsonld-0",
                   "https://images.cdn.yle.fi/jsonld-1"]}
        </script>
        <meta property="og:image" content="https://og.example/og.jpg">
        </head></html>
        """
        result = build_series_metadata(soup_of(html), "id", fallback_title="dir")
        assert result.background_url == "https://img.img-cdn.yle.fi/img/w_3840,ar_16:9/hero"

    def test_background_falls_back_to_jsonld_image0(self) -> None:
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type": "TVSeries",
         "image": ["https://images.cdn.yle.fi/jsonld-0",
                   "https://images.cdn.yle.fi/jsonld-1"]}
        </script>
        <meta property="og:image" content="https://og.example/og.jpg">
        </head></html>
        """
        result = build_series_metadata(soup_of(html), "id", fallback_title="dir")
        assert result.background_url == "https://images.cdn.yle.fi/jsonld-0"

    def test_background_falls_back_to_og_image(self) -> None:
        html = '<html><head><meta property="og:image" content="https://og.example/og.jpg"></head></html>'
        result = build_series_metadata(soup_of(html), "id", fallback_title="dir")
        assert result.background_url == "https://og.example/og.jpg"

    def test_poster_prefers_jsonld_image1(self) -> None:
        html = """
        <html><head>
        <link rel="preload" as="image"
              href="https://img.img-cdn.yle.fi/img/w_3840,ar_16:9/hero">
        <script type="application/ld+json">
        {"@type": "TVSeries",
         "image": ["https://images.cdn.yle.fi/jsonld-0",
                   "https://images.cdn.yle.fi/jsonld-1"]}
        </script>
        </head></html>
        """
        result = build_series_metadata(soup_of(html), "id", fallback_title="dir")
        assert result.poster_url == "https://images.cdn.yle.fi/jsonld-1"

    def test_poster_falls_back_to_background(self) -> None:
        # Only one JSON-LD image present, so image[1] is empty; poster
        # falls back to background.
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type": "TVSeries",
         "image": ["https://images.cdn.yle.fi/only-one"]}
        </script>
        </head></html>
        """
        result = build_series_metadata(soup_of(html), "id", fallback_title="dir")
        assert result.poster_url == "https://images.cdn.yle.fi/only-one"
        assert result.background_url == "https://images.cdn.yle.fi/only-one"

    def test_image_field_prefers_poster(self) -> None:
        html = """
        <html><head>
        <link rel="preload" as="image"
              href="https://img.img-cdn.yle.fi/img/w_3840,ar_16:9/hero">
        <script type="application/ld+json">
        {"@type": "TVSeries",
         "image": ["https://images.cdn.yle.fi/jsonld-0",
                   "https://images.cdn.yle.fi/jsonld-1"]}
        </script>
        </head></html>
        """
        result = build_series_metadata(soup_of(html), "id", fallback_title="dir")
        assert result.image_url == result.poster_url
        assert result.image_url == "https://images.cdn.yle.fi/jsonld-1"

    def test_logo_extracted(self) -> None:
        html = """
        <html><head>
        <link rel="preload" as="image"
              href="https://img.img-cdn.yle.fi/crop_limit,w_400/logo-abc">
        </head></html>
        """
        result = build_series_metadata(soup_of(html), "id", fallback_title="dir")
        assert result.logo_url == "https://img.img-cdn.yle.fi/logo-abc"

    def test_logo_empty_when_absent(self) -> None:
        result = build_series_metadata(soup_of("<html></html>"), "id", fallback_title="dir")
        assert result.logo_url == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
