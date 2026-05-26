"""Shared pytest fixtures and helpers."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from bs4 import BeautifulSoup

from yle_dl_plex.areena import USER_AGENT


@pytest.fixture
def http_client() -> Iterator[httpx.Client]:
    """A real httpx.Client matching production headers/options.

    Combine with `respx_mock` in tests that need mocked responses —
    respx intercepts at the transport layer, so no client wiring is
    required here.
    """
    with httpx.Client(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=30.0,
    ) as client:
        yield client


def soup_of(html: str) -> BeautifulSoup:
    """Parse `html` with the same parser used in production (areena.py)."""
    return BeautifulSoup(html, "lxml")
