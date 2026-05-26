"""Tests for `yle_dl_plex.cli.fetch_to_file` using respx + tmp_path."""

from __future__ import annotations

from pathlib import Path

import httpx
import respx

from yle_dl_plex.cli import fetch_to_file


@respx.mock
def test_success_writes_bytes(http_client: httpx.Client, tmp_path: Path) -> None:
    dest = tmp_path / "out.jpg"
    payload = b"\xff\xd8\xff\xe0bytes"
    respx.get("https://example.com/img.jpg").mock(return_value=httpx.Response(200, content=payload))

    assert fetch_to_file(http_client, "https://example.com/img.jpg", dest) is True
    assert dest.read_bytes() == payload


@respx.mock
def test_creates_parent_directory(http_client: httpx.Client, tmp_path: Path) -> None:
    dest = tmp_path / "nested" / "dir" / "out.jpg"
    respx.get("https://example.com/img.jpg").mock(return_value=httpx.Response(200, content=b"data"))

    assert fetch_to_file(http_client, "https://example.com/img.jpg", dest) is True
    assert dest.exists()


@respx.mock
def test_empty_body_returns_false(http_client: httpx.Client, tmp_path: Path) -> None:
    dest = tmp_path / "out.jpg"
    respx.get("https://example.com/img.jpg").mock(return_value=httpx.Response(200, content=b""))

    assert fetch_to_file(http_client, "https://example.com/img.jpg", dest) is False
    assert not dest.exists()


@respx.mock
def test_404_returns_false_no_file(http_client: httpx.Client, tmp_path: Path) -> None:
    dest = tmp_path / "out.jpg"
    respx.get("https://example.com/img.jpg").mock(return_value=httpx.Response(404))

    assert fetch_to_file(http_client, "https://example.com/img.jpg", dest) is False
    assert not dest.exists()


@respx.mock
def test_network_error_returns_false_no_file(http_client: httpx.Client, tmp_path: Path) -> None:
    dest = tmp_path / "out.jpg"
    respx.get("https://example.com/img.jpg").mock(side_effect=httpx.ConnectError("nope"))

    assert fetch_to_file(http_client, "https://example.com/img.jpg", dest) is False
    assert not dest.exists()


@respx.mock
def test_replaces_existing_file_atomically(http_client: httpx.Client, tmp_path: Path) -> None:
    dest = tmp_path / "out.jpg"
    dest.write_bytes(b"old contents")
    new_payload = b"new contents"
    respx.get("https://example.com/img.jpg").mock(
        return_value=httpx.Response(200, content=new_payload)
    )

    assert fetch_to_file(http_client, "https://example.com/img.jpg", dest) is True
    assert dest.read_bytes() == new_payload

    # No `.dl.*` temp leftovers in the directory.
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".dl.")]
    assert leftovers == []
