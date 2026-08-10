#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

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

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: DummyResult())
    downloader = WgetFallback(test_submission)

    resources = downloader.find_resources()
    with pytest.raises(SiteDownloaderError, match="Wget could not capture URL"):
        resources[0].download()


def test_find_resources_returns_warc_bytes(monkeypatch, tmp_path):
    test_submission = MagicMock()
    test_submission.url = "https://www.example.com/"
    temp_dir = tmp_path / "wget_temp"
    temp_dir.mkdir()
    warc_path = temp_dir / "capture.warc"
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
    assert resource.extension == ".warc"
