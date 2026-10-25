"""
Provider: Mutual Funds (mfnav.in)

Same public interface as before:
    search_funds / get_fund_details / get_current_nav / get_nav_history / resolve_scheme

Fixes:
  * scheme_code normalised to a clean integer string ("120503.0" -> "120503")
  * ISIN matching checks both `isin` and `isin_reinvest`
  * NAV history requests a bounded date window (default ~5y) and reports
    `latest_date` / `is_stale`
  * name resolution: tries several query shapes (statement names rarely equal
    AMFI names), token-based scoring, hard plan/option constraints, and prefers
    ACTIVE schemes over dormant duplicates
  * get_current_nav uses /api/funds/{code} (1 small call, not the whole history)
"""

from __future__ import annotations

import asyncio
import math
import re
from datetime import date, datetime, timedelta
from typing import Any

from services.mfnav import MFNavClient

STALE_AFTER_DAYS = 10          # NAV older than this => scheme likely dormant
HISTORY_DAYS = 5 * 365 + 45    # enough for 5Y CAGR
MIN_NAME_SCORE = 50.0          # 0-100 token similarity needed to consider a match
CLOSE_SCORE_BAND = 10.0        # candidates within this band of the best are contenders
MIN_MARGIN = 3.0               # winner must beat runner-up by this to be unambiguous


# ============================================================================
# HELPERS
# ============================================================================

def normalize_scheme_code(value: Any) -> str | None:
    """'120503', 120503, 120503.0, '120503.0', ' 120503 ' -> '120503'; junk -> None."""
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "nat", "null"}:
        return None
    try:
        number = int(float(text))
    except (ValueError, OverflowError):
        return None
    return str(number) if number > 0 else None


_STOP = {"the", "of", "and", "a", "plan", "option", "scheme"}


def _tokens(text: Any) -> set[str]:
    text = str(text or "").lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    out = set()
    for tok in text.split():
        if tok in _STOP:
            continue
        out.add("idcw" if tok == "dividend" else tok)
    return out


def _plan_of(text: Any) -> str:
    toks = _tokens(text)
    return "direct" if "direct" in toks else "regular" if "regular" in toks else ""


def _option_of(text: Any) -> str:
    toks = _tokens(text)
    return "idcw" if "idcw" in toks else "growth" if "growth" in toks else ""


def _clean_value(value: Any) -> Any:
    if value is None:
        return None
    if str(value).strip().lower() in {"", "none", "nan", "null"}:
        return None
    return value


def _is_active(latest_date: Any) -> bool:
    try:
        d = date.fromisoformat(str(latest_date)[:10])
    except ValueError:
        return False
    return (date.today() - d).days <= STALE_AFTER_DAYS


def _extract_scheme_fields(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalise scheme metadata (search rows and /api/funds/{code} share these keys)."""

    def _get(*keys: str) -> Any:
        for key in keys:
            value = _clean_value(raw.get(key))
            if value is not None:
                return value
        return None

    return {
        "scheme_code": normalize_scheme_code(_get("scheme_code", "schemeCode")),
        "scheme_name": _get("scheme_name", "schemeName", "name"),
        "fund_house": _get("fund_house", "fundHouse", "amc", "amcName"),
        "isin": _get("isin", "isinDiv", "isinGrowth"),
        "isin_reinvest": _get("isin_reinvest"),
        "plan_type": _get("plan_type", "planType", "plan"),
        "option_type": _get("option_type", "optionType", "option"),
        "category": _get("category", "schemeCategory"),
        "sub_category": _get("sub_category", "subCategory", "schemeSubCategory"),
        # only present on /api/funds/{code}
        "latest_nav": _get("latest_nav"),
        "latest_nav_date": _get("latest_nav_date"),
        "daily_metrics": raw.get("daily_metrics"),
    }


def _name_queries(name: str) -> list[str]:
    """Progressively looser search strings for a statement scheme name."""
    full = " ".join(str(name).split())
    core = re.sub(
        r"(?i)\b(direct|regular|plan|option|growth|idcw|dividend)\b", " ", full
    )
    core = " ".join(re.sub(r"[-\u2013\u2014()/,]+", " ", core).split())
    first3 = " ".join(core.split()[:3])
    queries: list[str] = []
    for q in (full, core, first3):
        if len(q) >= 2 and q not in queries:
            queries.append(q)
    return queries


# ============================================================================
# PROVIDER
# ============================================================================

class MutualFundProvider:
    """High-level mutual-fund provider backed by mfnav.in. Never raises."""

    def __init__(self, client: MFNavClient | None = None) -> None:
        self.client = client or MFNavClient()

    # ------------------------------------------------------------------ search

    async def search_funds(self, query: str, page_size: int = 50) -> dict[str, Any]:
        raw = await self.client.search_funds(query=query, page=1, page_size=page_size)
        if raw.get("available") is False:
            return raw
        results = raw.get("results", raw.get("data", []))
        if not isinstance(results, list):
            results = []
        return {
            "available": True,
            "results": results,
            "count": len(results),
            "total": raw.get("total", len(results)),
        }

    # ------------------------------------------------------------ fund details

    async def get_fund_details(self, scheme_code: int | str) -> dict[str, Any]:
        return await self.client.get_fund_details(scheme_code)

    # ------------------------------------------------------------- current NAV

    async def get_current_nav(self, scheme_code: int | str) -> dict[str, Any]:
        details = await self.get_fund_details(scheme_code)
        if details.get("available") is False:
            return details
        try:
            nav = float(details["latest_nav"])
        except (KeyError, TypeError, ValueError):
            return {"available": False, "error": "Latest NAV missing or unparseable."}
        if not math.isfinite(nav) or nav <= 0:
            return {"available": False, "error": "Latest NAV is not a valid positive number."}
        return {
            "available": True,
            "scheme_code": str(scheme_code),
            "nav": nav,
            "nav_date": details.get("latest_nav_date"),
        }

    # -------------------------------------------------------------- NAV history

    async def get_nav_history(
        self,
        scheme_code: int | str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """
        Normalised history, newest first:
            {"available": True, "records": [{"date": "YYYY-MM-DD", "nav": 12.3}, ...],
             "count": n, "latest_date": "...", "is_stale": bool}
        Defaults to the last ~5 years (enough for 1M/3M/6M/1Y/3Y/5Y metrics).
        """
        if not start_date and not end_date:
            start_date = (date.today() - timedelta(days=HISTORY_DAYS)).isoformat()

        raw = await self.client.get_nav_history(scheme_code, start_date, end_date)
        if raw.get("available") is False:
            return raw

        rows = raw.get("data", [])
        if not isinstance(rows, list):
            return {"available": False, "error": "Unexpected NAV history response."}

        parsed: dict[str, float] = {}
        for rec in rows:
            if not isinstance(rec, dict):
                continue
            d = self._parse_nav_date(rec.get("nav_date", rec.get("date")))
            try:
                nav = float(rec.get("nav"))
            except (TypeError, ValueError):
                continue
            if d is not None and nav > 0:
                parsed[d.strftime("%Y-%m-%d")] = nav

        records = [
            {"date": k, "nav": parsed[k]} for k in sorted(parsed, reverse=True)
        ]
        latest = records[0]["date"] if records else None

        return {
            "available": True,
            "scheme_code": str(scheme_code),
            "records": records,
            "count": len(records),
            "latest_date": latest,
            "is_stale": (not _is_active(latest)) if latest else True,
        }

    @staticmethod
    def _parse_nav_date(raw_date: Any) -> datetime | None:
        if raw_date is None:
            return None
        if isinstance(raw_date, datetime):
            return raw_date
        value = str(raw_date).strip()
        for parser in (
            datetime.fromisoformat,
            lambda v: datetime.strptime(v, "%d-%m-%Y"),
        ):
            try:
                return parser(value)
            except ValueError:
                continue
        return None

    # ------------------------------------------------------------------ resolve

    @staticmethod
    def _unavailable(res: dict[str, Any]) -> dict[str, Any]:
        return {
            "resolved": False,
            "available": False,
            "error": res.get("error", "mfnav unavailable"),
        }

    async def resolve_scheme(
        self,
        scheme_name: str,
        isin: str | None = None,
        scheme_code: str | int | None = None,
        plan_type: str | None = None,
        option_type: str | None = None,
        fund_house: str | None = None,
    ) -> dict[str, Any]:
        """
        Resolve one scheme. Priority: scheme_code -> ISIN -> name.
        A failed lookup on a higher-priority key falls through to the next one
        (unless mfnav itself is down).
        """

        # 1. scheme code ---------------------------------------------------
        code = normalize_scheme_code(scheme_code)
        if code:
            details = await self.get_fund_details(code)
            if details.get("available") is not False:
                return {"resolved": True, **_extract_scheme_fields(details)}
            if details.get("status") not in (404, 422):
                return self._unavailable(details)

        # 2. ISIN -----------------------------------------------------------
        if isin and str(isin).strip():
            isin_value = str(isin).strip().upper()
            res = await self.search_funds(isin_value, page_size=20)
            if res.get("available") is False:
                return self._unavailable(res)

            matches = [
                c
                for c in res["results"]
                if isin_value
                in (
                    str(c.get("isin") or "").upper(),
                    str(c.get("isin_reinvest") or "").upper(),
                )
            ]
            if len(matches) == 1:
                return {"resolved": True, **_extract_scheme_fields(matches[0])}
            if len(matches) > 1:
                return {
                    "resolved": False,
                    "reason": "Multiple schemes matched the given ISIN.",
                    "candidates": [_extract_scheme_fields(m) for m in matches],
                }

        # 3. name ------------------------------------------------------------
        if not scheme_name or not scheme_name.strip():
            return {
                "resolved": False,
                "reason": "No scheme identifier was provided.",
                "candidates": [],
            }
        return await self._resolve_by_name(
            scheme_name, plan_type, option_type, fund_house
        )

    async def _resolve_by_name(
        self,
        scheme_name: str,
        plan_type: str | None,
        option_type: str | None,
        fund_house: str | None,
    ) -> dict[str, Any]:

        # gather candidates: first query shape that returns anything wins
        pool: dict[str, dict[str, Any]] = {}
        for q in _name_queries(scheme_name):
            res = await self.search_funds(q, page_size=500)
            if res.get("available") is False:
                if not pool:
                    return self._unavailable(res)
                break
            for c in res["results"]:
                code = normalize_scheme_code(c.get("scheme_code"))
                if code:
                    pool.setdefault(code, c)
            if pool:
                break

        if not pool:
            return {
                "resolved": False,
                "reason": f"No schemes found matching '{scheme_name}'.",
                "candidates": [],
            }

        q_tokens = _tokens(scheme_name)
        plan = _plan_of(plan_type) or _plan_of(scheme_name)
        option = _option_of(option_type) or _option_of(scheme_name)
        house_tokens = _tokens(fund_house)

        def score(c: dict[str, Any]) -> float:
            c_tokens = _tokens(c.get("scheme_name"))
            if not q_tokens or not c_tokens:
                return 0.0
            s = 100.0 * len(q_tokens & c_tokens) / len(q_tokens | c_tokens)
            c_plan = _plan_of(c.get("plan_type")) or _plan_of(c.get("scheme_name"))
            c_opt = _option_of(c.get("option_type")) or _option_of(c.get("scheme_name"))
            if plan and c_plan and plan != c_plan:
                return -1.0
            if option and c_opt and option != c_opt:
                return -1.0
            if house_tokens and house_tokens <= _tokens(c.get("fund_house")):
                s += 5.0
            return s

        scored = sorted(
            ((score(c), c) for c in pool.values()), key=lambda t: t[0], reverse=True
        )
        scored = [(s, c) for s, c in scored if s >= MIN_NAME_SCORE]

        if not scored:
            return {
                "resolved": False,
                "reason": f"No strong match found for '{scheme_name}'.",
                "candidates": [
                    _extract_scheme_fields(c) for c in list(pool.values())[:10]
                ],
            }

        best = scored[0][0]
        contenders = [(s, c) for s, c in scored if s >= best - CLOSE_SCORE_BAND][:6]

        # single contender: done (route flags it if its NAV turns out stale)
        if len(contenders) == 1:
            return {"resolved": True, **_extract_scheme_fields(contenders[0][1])}

        # several contenders: prefer ACTIVE schemes over dormant duplicates
        details = await asyncio.gather(
            *[self.get_fund_details(c["scheme_code"]) for _, c in contenders]
        )
        enriched: list[tuple[float, dict[str, Any], bool]] = []
        for (s, c), d in zip(contenders, details):
            if d.get("available") is not False:
                enriched.append((s, d, _is_active(d.get("latest_nav_date"))))
            else:
                enriched.append((s, c, False))

        active = [e for e in enriched if e[2]]
        ranked = sorted(active or enriched, key=lambda e: e[0], reverse=True)

        if len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= MIN_MARGIN:
            result = {"resolved": True, **_extract_scheme_fields(ranked[0][1])}
            if not active:
                result["warnings"] = [
                    "All matching schemes have stale NAVs; the scheme may be dormant."
                ]
            return result

        return {
            "resolved": False,
            "reason": (
                f"Multiple active schemes matched '{scheme_name}'. "
                "Provide scheme_code or ISIN to identify the exact scheme."
            ),
            "candidates": [_extract_scheme_fields(e[1]) for e in ranked[:15]],
        }