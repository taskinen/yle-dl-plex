"""Tests for `yle_dl_plex.areena.fetch_series_page` using respx."""

from __future__ import annotations

import logging

import httpx
import pytest
import respx

from yle_dl_plex.areena import fetch_series_page


@respx.mock
def test_fetch_series_page_success(http_client: httpx.Client) -> None:
    series_id = "1-62248394"
    expected_url = f"https://areena.yle.fi/{series_id}"
    respx.get(expected_url).mock(
        return_value=httpx.Response(200, text="<html><body>hello</body></html>")
    )

    soup = fetch_series_page(http_client, series_id)

    assert soup is not None
    assert soup.body is not None
    assert soup.body.get_text() == "hello"


@respx.mock
def test_fetch_series_page_404_returns_none_and_warns(
    http_client: httpx.Client,
    caplog: pytest.LogCaptureFixture,
) -> None:
    series_id = "1-not-found"
    respx.get(f"https://areena.yle.fi/{series_id}").mock(return_value=httpx.Response(404))

    with caplog.at_level(logging.WARNING, logger="yle_dl_plex"):
        result = fetch_series_page(http_client, series_id)

    assert result is None
    assert any("Could not fetch series page" in rec.message for rec in caplog.records)


@respx.mock
def test_fetch_series_page_connection_error_returns_none(
    http_client: httpx.Client,
    caplog: pytest.LogCaptureFixture,
) -> None:
    series_id = "1-network-error"
    respx.get(f"https://areena.yle.fi/{series_id}").mock(
        side_effect=httpx.ConnectError("connection refused")
    )

    with caplog.at_level(logging.WARNING, logger="yle_dl_plex"):
        result = fetch_series_page(http_client, series_id)

    assert result is None


@respx.mock
def test_fetch_series_page_requests_correct_url(http_client: httpx.Client) -> None:
    series_id = "1-12345"
    route = respx.get(f"https://areena.yle.fi/{series_id}").mock(
        return_value=httpx.Response(200, text="<html></html>")
    )

    fetch_series_page(http_client, series_id)

    assert route.called
    assert route.call_count == 1
