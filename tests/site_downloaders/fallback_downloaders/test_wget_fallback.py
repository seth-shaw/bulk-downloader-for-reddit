#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from warcio.warcwriter import WARCWriter

from bdfr.exceptions import NotADownloadableLinkError, SiteDownloaderError
from bdfr.resource import Resource
from bdfr.site_downloaders.fallback_downloaders.wget_fallback import WgetFallback


def test_can_handle_link_valid_urls():
    assert WgetFallback.can_handle_link("https://www.google.com/")
    assert WgetFallback.can_handle_link("www.example.com/test")
    assert WgetFallback.can_handle_link("http://example.org")


def test_can_handle_link_invalid_urls():
    assert not WgetFallback.can_handle_link("://bad")
    assert not WgetFallback.can_handle_link("")


def test_find_resources_raises_if_wget_missing(monkeypatch):
    test_submission = MagicMock()
    test_submission.url = "https://www.example.com/"
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError()))

    downloader = WgetFallback(test_submission)
    with pytest.raises(SiteDownloaderError, match="wget executable not found"):
        downloader.find_resources()[0].download()


def test_find_resources_raises_if_wget_fails(monkeypatch):
    test_submission = MagicMock()
    test_submission.url = "https://www.example.com/"

    class DummyResult:
        returncode = 8
        stderr = "HTTP request returned error code 404"
        stdout = ""

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: DummyResult())
    downloader = WgetFallback(test_submission)

    resources = downloader.find_resources()
    with pytest.raises(
        SiteDownloaderError,
        match=r"Wget could not capture URL.*exit code 8 \(server issued error response\): HTTP request returned error code 404",
    ):
        resources[0].download()


def test_find_resources_logs_wget_command_and_stderr(monkeypatch, caplog):
    test_submission = MagicMock()
    test_submission.url = "https://www.example.com/"

    class DummyResult:
        returncode = 8
        stderr = "HTTP request returned error code 404"
        stdout = ""

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: DummyResult())
    downloader = WgetFallback(test_submission)

    resources = downloader.find_resources()
    caplog.set_level(logging.DEBUG)
    with pytest.raises(SiteDownloaderError):
        resources[0].download()

    assert "Wget failed command:" in caplog.text
    assert "wget --warc-file" in caplog.text
    assert "--quiet" not in caplog.text
    assert "Wget stderr: HTTP request returned error code 404" in caplog.text


def test_find_resources_accepts_warc_with_target_url_on_nonzero_exit(monkeypatch, tmp_path, caplog):
    test_submission = MagicMock()
    test_submission.url = "https://www.example.com/"
    temp_dir = tmp_path / "wget_temp"
    temp_dir.mkdir()
    warc_path = temp_dir / "capture.warc"
    warc_stream = BytesIO()
    writer = WARCWriter(warc_stream, gzip=False)
    writer.write_record(
        writer.create_warc_record("https://www.example.com/", "resource", payload=BytesIO(b"captured content"))
    )
    warc_content = warc_stream.getvalue()
    warc_path.write_bytes(warc_content)

    class DummyResult:
        returncode = 8
        stderr = "HTTP request returned error code 404"
        stdout = ""

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: DummyResult())

    class DummyTemporaryDirectory:
        def __enter__(self_inner):
            return str(temp_dir)

        def __exit__(self_inner, exc_type, exc_val, exc_tb):
            return False

    monkeypatch.setattr(tempfile, "TemporaryDirectory", lambda: DummyTemporaryDirectory())

    downloader = WgetFallback(test_submission)
    caplog.set_level(logging.WARNING)
    resources = downloader.find_resources()
    resources[0].download()

    assert resources[0].content == warc_content
    assert "contains the target URL; accepting capture" in caplog.text


def test_warc_contains_url_rejects_unparseable_header_bytes(tmp_path):
    warc_path = tmp_path / "capture.warc"
    warc_path.write_bytes(b"WARC-Target-URI: https://www.example.com/")

    assert not WgetFallback._warc_contains_url(warc_path, "https://www.example.com/")


def test_find_resources_returns_warc_bytes(monkeypatch, tmp_path):
    test_submission = MagicMock()
    test_submission.url = "https://www.example.com/"
    temp_dir = tmp_path / "wget_temp"
    temp_dir.mkdir()
    warc_path = temp_dir / "capture.warc.gz"
    warc_path.write_bytes(b"sample warc content")

    class DummyResult:
        returncode = 0
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: DummyResult())

    class DummyTemporaryDirectory:
        def __enter__(self_inner):
            return str(temp_dir)

        def __exit__(self_inner, exc_type, exc_val, exc_tb):
            return False

    monkeypatch.setattr(tempfile, "TemporaryDirectory", lambda: DummyTemporaryDirectory())

    downloader = WgetFallback(test_submission)
    resources = downloader.find_resources()
    assert len(resources) == 1
    resource = resources[0]
    assert isinstance(resource, Resource)
    resource.download()
    assert resource.content == b"sample warc content"
    assert resource.extension == ".warc.gz"
