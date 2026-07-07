"""NseClient — the ONE hardened gateway to NSE (PLAN Section 4.2).

NSE blocks naive scrapers. This client centralizes the workarounds so no other
module ever calls NSE directly:
  * browser-like headers,
  * a warm-up request to nseindia.com to obtain session cookies,
  * polite rate limiting between requests,
  * retry with exponential backoff,
  * a simple on-disk cache for immutable archive files (dated bhavcopies).

If NSE endpoints change, this is the single file to fix.
"""

from __future__ import annotations

import time
from pathlib import Path

import requests

from analyzer.config import Config, get_config
from analyzer.logging_setup import get_logger

log = get_logger(__name__)


class NseClient:
    def __init__(self, cfg: Config | None = None) -> None:
        self.cfg = cfg or get_config()
        ing = self.cfg.ingestion
        self.base_url = ing.nse_base_url
        self.archives_url = ing.nse_archives_url
        self.timeout = ing.request_timeout_sec
        self.rate_limit = ing.rate_limit_sec
        self.max_retries = ing.max_retries
        self.backoff_base = ing.backoff_base_sec
        self.cache_dir = self.cfg.cache_path
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": ing.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
            }
        )
        self._warmed = False
        self._last_request_ts = 0.0

    # --- session management ---------------------------------------------------
    def _warm_up(self) -> None:
        """Hit the homepage once to obtain the cookies NSE requires for data URLs."""
        if self._warmed:
            return
        try:
            self._session.get(self.base_url, timeout=self.timeout)
            self._warmed = True
            log.debug("nse_warmup_ok")
        except requests.RequestException as exc:
            log.warning("nse_warmup_failed", error=str(exc))

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request_ts
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)
        self._last_request_ts = time.time()

    # --- core request with retry ---------------------------------------------
    def get(self, url: str, referer: str | None = None, **kwargs) -> requests.Response:
        """GET with warm-up, throttle, and exponential-backoff retry."""
        self._warm_up()
        headers = dict(kwargs.pop("headers", {}))
        if referer:
            headers["Referer"] = referer
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                resp = self._session.get(url, timeout=self.timeout, headers=headers, **kwargs)
                if resp.status_code == 200:
                    return resp
                # NSE sometimes 401/403s a cold session — re-warm and retry.
                if resp.status_code in (401, 403):
                    self._warmed = False
                    self._warm_up()
                log.warning("nse_http_status", url=url, status=resp.status_code, attempt=attempt)
            except requests.RequestException as exc:
                last_exc = exc
                log.warning("nse_request_error", url=url, attempt=attempt, error=str(exc))
            time.sleep(self.backoff_base ** attempt)
        raise RuntimeError(f"NSE GET failed after {self.max_retries} attempts: {url}") from last_exc

    def get_json(self, url: str, referer: str | None = None, **kwargs) -> dict:
        return self.get(url, referer=referer, **kwargs).json()

    # --- cached archive download ---------------------------------------------
    def download(self, url: str, dest_name: str, referer: str | None = None,
                 use_cache: bool = True) -> Path:
        """Download a (typically immutable, dated) file to the cache dir.

        Dated archive files never change, so a cache hit is authoritative and
        skips the network entirely.
        """
        dest = self.cache_dir / dest_name
        if use_cache and dest.exists() and dest.stat().st_size > 0:
            log.debug("cache_hit", file=dest_name)
            return dest
        resp = self.get(url, referer=referer)
        dest.write_bytes(resp.content)
        log.debug("downloaded", file=dest_name, bytes=len(resp.content))
        return dest
