"""
Service: mfnav.in HTTP client  (docs: https://mfnav.in/api-docs)

No auth. Free tier: 120 requests/min per IP.

Improvements over the original:
  * one shared AsyncClient (connection reuse) instead of one per request
  * concurrency limit + retry/backoff on HTTP 429 and 5xx
  * small in-memory TTL cache (fund details, NAV history, search)
  * /api/nav is paginated (default 250 rows!) -> we request the API maximum
    page size and keep paging until `total` is reached
  * scheme_code is validated as an integer (the API path param is an int)
  * never raises: failures return {"available": False, "status": ..., "error": ...}
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

BASE_URL = "https://mfnav.in"
TIMEOUT = 20.0
MAX_CONCURRENCY = 4
MAX_RETRIES = 3

NAV_PAGE_SIZE = 10_000      # API maximum for /api/nav
SEARCH_PAGE_SIZE_MAX = 500  # API maximum for /api/funds/search

TTL_SEARCH = 3600
TTL_DETAILS = 900
TTL_NAV = 900


def _fail(error: str, status: int | None = None) -> dict[str, Any]:
    return {"available": False, "status": status, "error": error}


class MFNavClient:
    """Low-level HTTP client for mfnav.in."""

    def __init__(
        self,
        base_url: str = BASE_URL,
        timeout: float = TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,  # injectable for tests
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._sem: asyncio.Semaphore | None = None
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _ensure(self) -> tuple[httpx.AsyncClient, asyncio.Semaphore]:
        # Created lazily so module-level instantiation never touches an event loop.
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                transport=self._transport,
                headers={"User-Agent": "portfolio-analyzer/1.0", "Accept": "application/json"},
            )
            self._sem = asyncio.Semaphore(MAX_CONCURRENCY)
        return self._client, self._sem  # type: ignore[return-value]

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        ttl: int = 0,
    ) -> dict[str, Any]:
        key = f"{path}?{sorted((params or {}).items())}"
        hit = self._cache.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]

        client, sem = self._ensure()
        last_error, status = "request failed", None

        for attempt in range(MAX_RETRIES):
            delay = 0.5 * (2 ** attempt)
            try:
                async with sem:
                    resp = await client.get(path, params=params)
            except httpx.TimeoutException:
                last_error = "request timed out"
            except httpx.HTTPError as exc:
                last_error = f"unavailable: {exc}"
            else:
                status = resp.status_code
                if status == 200:
                    try:
                        payload = resp.json()
                    except ValueError:
                        return _fail("mfnav.in returned invalid JSON.", status)
                    if isinstance(payload, list):
                        payload = {"data": payload}
                    payload["available"] = True
                    if ttl:
                        self._cache[key] = (time.monotonic() + ttl, payload)
                    return payload

                if status != 429 and status < 500:
                    # 4xx (404 unknown scheme, 422 bad param): retrying won't help
                    return _fail(f"mfnav.in returned HTTP {status}.", status)

                last_error = f"HTTP {status}"
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = min(float(retry_after), 10.0)
                    except ValueError:
                        pass

            if attempt < MAX_RETRIES - 1:
                log.warning("mfnav %s failed (%s); retrying in %.1fs", path, last_error, delay)
                await asyncio.sleep(delay)

        return _fail(f"mfnav.in {last_error}.", status)

    # ------------------------------------------------------------------
    # endpoints
    # ------------------------------------------------------------------

    async def search_funds(
        self, query: str, page: int = 1, page_size: int = 50
    ) -> dict[str, Any]:
        """GET /api/funds/search?q=  (q must be >= 2 chars; results ordered by scheme_code)."""
        q = (query or "").strip()
        if len(q) < 2:
            return {"available": True, "results": [], "total": 0}

        page_size = max(1, min(int(page_size), SEARCH_PAGE_SIZE_MAX))
        res = await self._get(
            "/api/funds/search",
            {"q": q, "page": page, "page_size": page_size},
            ttl=TTL_SEARCH,
        )
        if res.get("available") is False:
            res.setdefault("results", [])
        return res

    async def get_fund_details(self, scheme_code: int | str) -> dict[str, Any]:
        """
        GET /api/funds/{scheme_code}  (flat object)

        Includes latest_nav, latest_nav_date, latest_day_change_pct and
        daily_metrics (cagr_1y/3y/5y..., abs_return_*; decimal fractions).
        """
        try:
            code = int(scheme_code)
        except (TypeError, ValueError):
            return _fail(f"Invalid scheme_code: {scheme_code!r}", 422)
        return await self._get(f"/api/funds/{code}", ttl=TTL_DETAILS)

    async def get_nav_history(
        self,
        scheme_code: int | str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """
        GET /api/nav/{scheme_code}  -> {"fund_details", "data": [...], "total", ...}

        The endpoint is paginated (default 250 rows). We use the max page size and
        keep paging until every row inside the date window has been collected.
        """
        try:
            code = int(scheme_code)
        except (TypeError, ValueError):
            return _fail(f"Invalid scheme_code: {scheme_code!r}", 422)

        params: dict[str, Any] = {"page_size": NAV_PAGE_SIZE}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        records: list[dict[str, Any]] = []
        first: dict[str, Any] | None = None
        page = 1

        while True:
            resp = await self._get(f"/api/nav/{code}", {**params, "page": page}, ttl=TTL_NAV)
            if resp.get("available") is False:
                return {**resp, "data": []}

            first = first or resp
            batch = resp.get("data") or []
            records.extend(batch)

            total = resp.get("total")
            if not batch or total is None or len(records) >= total:
                break
            page += 1

        return {**first, "data": records, "available": True}

    async def get_latest_nav_date(self) -> dict[str, Any]:
        """GET /api/date/latest"""
        return await self._get("/api/date/latest", ttl=300)

    async def get_categories(self) -> dict[str, Any]:
        """GET /api/categories/"""
        return await self._get("/api/categories/", ttl=TTL_SEARCH)