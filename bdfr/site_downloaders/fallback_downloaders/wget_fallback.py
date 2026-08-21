#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import shlex
import shutil
import subprocess
import tempfile
import time
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
        res = Resource(self.post, self.post.url, download_function, ".warc.gz")
        return [res]

    _WGET_EXIT_CODE_REASON = {
        1: "generic error",
        2: "parse error",
        3: "file I/O error",
        4: "network failure",
        5: "SSL verification failure",
        6: "username/password authentication failure",
        7: "protocol errors",
        8: "server issued error response",
    }

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
                    "--page-requisites",
                    "--span-hosts",
                    "--trust-server-names",
                    "--max-redirect=20",
                    "--tries=2",
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

                # Look for any WARC-like files that wget may have produced. Some
                # builds or configurations may write slightly different names
                # (e.g. compression suffixes). Prefer the most-recent warc file.
                warc_candidates = sorted(Path(temp_dir).glob("*.warc*"), key=lambda p: p.stat().st_mtime, reverse=True)
                selected_warc = warc_candidates[0] if warc_candidates else warc_path

                if completed.returncode != 0:
                    stderr_text = completed.stderr.strip() if completed.stderr else ""
                    reason = self._WGET_EXIT_CODE_REASON.get(completed.returncode, "unknown error")
                    command_text = " ".join(shlex.quote(str(arg)) for arg in command)
                    logger.debug("Wget failed command: %s", command_text)
                    logger.debug("Wget stderr: %s", stderr_text or "<empty>")
                    # If wget returned non-zero but produced a WARC that contains
                    # the target URL, accept the capture as successful.
                    if selected_warc.exists() and self._warc_contains_url(
                        selected_warc, self._normalize_url(self.post.url)
                    ):
                        logger.warning(
                            "Wget exited with code %s (%s), but the WARC file %s contains the target URL; accepting capture",
                            completed.returncode,
                            reason,
                            str(selected_warc),
                        )
                    else:
                        raise SiteDownloaderError(
                            f"Wget could not capture URL {self.post.url}: exit code {completed.returncode} ({reason})"
                            + (f": {stderr_text}" if stderr_text else "")
                        )

                if not selected_warc.exists():
                    raise SiteDownloaderError("Wget did not produce a WARC file")

                with selected_warc.open("rb") as file:
                    return file.read()

        return download

    @staticmethod
    def _normalize_url(url: str) -> str:
        if url.startswith(("http://", "https://")):
            return url
        return "https://" + url

    @staticmethod
    def _warc_contains_url(warc_path: Path, url: str) -> bool:
        try:
            from warcio.archiveiterator import ArchiveIterator

            logger.debug("Using warcio to inspect WARC %s for %s", warc_path, url)
            with warc_path.open("rb") as file:
                for record in ArchiveIterator(file):
                    target = record.rec_headers.get_header("WARC-Target-URI")
                    if target == url or target == f"<{url}>":
                        logger.debug("WARC %s: found target via warcio: %s", warc_path, target)
                        return True
        except Exception:
            logger.exception("warcio-based WARC scanning failed for %s", warc_path)
            return False

        logger.debug("WARC %s: target not found via warcio", warc_path)
        return False

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
