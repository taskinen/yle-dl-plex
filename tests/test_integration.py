"""Integration tests for the main CLI orchestration."""

from unittest.mock import patch

import pytest
import respx
from httpx import Response

from yle_dl_plex.cli import main
from yle_dl_plex.yledl import RD_SUCCESS, Episode


@pytest.fixture
def mock_yledl():
    with (
        patch("yle_dl_plex.yledl.fetch_episode_metadata") as mock_fetch,
        patch("yle_dl_plex.yledl.download_clips") as mock_download,
    ):
        mock_fetch.return_value = [
            Episode(
                filename="Show/Season 01/Show - S01E01 - Title.mkv",
                title="Show - S01E01 - Title",
                description="Episode description",
                thumbnail="https://example.com/thumb.jpg",
                duration_seconds=1800,
                publish_timestamp="2024-01-01T12:00:00Z",
                webpage="https://areena.yle.fi/1-123",
                program_id="1-123",
            )
        ]
        mock_download.return_value = RD_SUCCESS
        yield mock_fetch, mock_download


@respx.mock
def test_main_orchestration(tmp_path, mock_yledl):
    mock_fetch, mock_download = mock_yledl
    destdir = tmp_path / "output"

    # Mock Areena page
    respx.get("https://areena.yle.fi/1-123").mock(
        return_value=Response(
            200,
            text="""
        <html>
            <head>
                <script type="application/ld+json">
                {
                    "@type": "TVSeries",
                    "name": "Show",
                    "description": "Series description",
                    "image": ["https://example.com/poster.jpg", "https://example.com/background.jpg"]
                }
                </script>
            </head>
            <body></body>
        </html>
    """,
        )
    )

    # Mock images
    respx.get("https://example.com/thumb.jpg").mock(return_value=Response(200, content=b"thumb"))
    respx.get("https://example.com/poster.jpg").mock(return_value=Response(200, content=b"poster"))
    respx.get("https://example.com/background.jpg").mock(
        return_value=Response(200, content=b"background")
    )

    # We need to create a dummy video file because Stage 4 checks for it
    video_path = destdir / "Show/Season 01/Show - S01E01 - Title.mkv"
    video_path.parent.mkdir(parents=True)
    video_path.write_text("dummy video")

    args = ["--destdir", str(destdir), "https://areena.yle.fi/1-123"]
    assert main(args) == 0

    # Verify calls
    mock_fetch.assert_called_once()
    mock_download.assert_called_once()

    # Verify files created
    assert (destdir / "Show/tvshow.nfo").exists()
    assert (destdir / "Show/poster.jpg").exists()
    assert (destdir / "Show/background.jpg").exists()
    assert (destdir / "Show/Season 01/Show - S01E01 - Title.nfo").exists()
    assert (destdir / "Show/Season 01/Show - S01E01 - Title.jpg").exists()


@respx.mock
def test_main_metadata_only(tmp_path, mock_yledl):
    mock_fetch, mock_download = mock_yledl
    destdir = tmp_path / "output"

    # Mock Areena page
    respx.get("https://areena.yle.fi/1-123").mock(return_value=Response(200, text="<html></html>"))
    # Mock thumbnail for Stage 4
    respx.get("https://example.com/thumb.jpg").mock(return_value=Response(200, content=b"thumb"))

    args = ["--destdir", str(destdir), "--metadata-only", "https://areena.yle.fi/1-123"]
    assert main(args) == 0

    mock_fetch.assert_called_once()
    mock_download.assert_not_called()
