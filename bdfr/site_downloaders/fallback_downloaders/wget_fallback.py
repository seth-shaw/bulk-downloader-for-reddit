#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import subprocess
import tempfile
import urllib.parse
from pathlib import Path
from typing import Optional

from praw.models import Submission

from bdfr.exceptions import NotADownloadableLinkError, SiteDownloaderError
from bdfr.resource import Resource
from bdfr.site_authenticator import SiteAuthenticator
from bdfr.site_downloaders.fallback_downloaders.fallback_downloader import BaseFallbackDownloader

logger = logging.getLogger(__name__)


class WgetFallback(BaseFallbackDownloader):
    def __init__(self, post: Submission):
        super(WgetFallback, self).__init__(post)

    def find_resources(self, authenticator: Optional[SiteAuthenticator] = None) -> list[Resource]:
        if not self.post.url:
            raise SiteDownloaderError("No URL provided for Wget fallback")
        if not WgetFallback.can_handle_link(self.post.url):
            raise NotADownloadableLinkError(f"Wget fallback cannot handle link {self.post.url}")

        download_function = self._download_warc()
        res = Resource(self.post, self.post.url, download_function, ".warc")
        return [res]

    def _download_warc(self):
        def download(_: dict) -> bytes:
            with tempfile.TemporaryDirectory() as temp_dir:
                warc_path = Path(temp_dir) / "capture.warc"
                warc_prefix = Path(temp_dir) / "capture"
                command = [
                    "wget",
                    "--quiet",
                    "--warc-file",
                    str(warc_prefix),
                    "--no-warc-compression",
                    "--page-requisites",
                    "--span-hosts",
                    "--trust-server-names",
                    "--max-redirect=20",
                    "--tries=1",
                    self._normalize_url(self.post.url),
                ]
                try:
                    completed = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                except FileNotFoundError as e:
                    logger.exception(e)
                    raise SiteDownloaderError("wget executable not found")

                if completed.returncode != 0:
                    stderr_text = completed.stderr.strip() if completed.stderr else ""
                    raise SiteDownloaderError(
                        f"Wget could not capture URL {self.post.url}: {completed.returncode} {stderr_text}"
                    )

                if not warc_path.exists():
                    raise SiteDownloaderError("Wget did not produce a WARC file")

                with warc_path.open("rb") as file:
                    return file.read()

        return download

    @staticmethod
    def _normalize_url(url: str) -> str:
        if url.startswith(("http://", "https://")):
            return url
        return "https://" + url

    @staticmethod
    def can_handle_link(url: str) -> bool:
        try:
            original_parsed = urllib.parse.urlsplit(url)
        except Exception:
            return False
        if original_parsed.scheme:
            if original_parsed.scheme not in ("http", "https"):
                return False
            if not original_parsed.hostname:
                return False
            return True

        normalized_url = WgetFallback._normalize_url(url)
        try:
            parsed = urllib.parse.urlsplit(normalized_url)
        except Exception:
            return False
        if parsed.scheme not in ("http", "https"):
            return False
        if not parsed.hostname:
            return False
        return True
