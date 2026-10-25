from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException

from providers.llm import LLMProvider
from providers.market_data import MarketDataProvider
from providers.mutual_funds import MutualFundProvider, normalize_scheme_code
from providers.news import NewsProvider
from schema.portfolio import (
    CurrencyCode,
    MutualFundAnalysisRequest,
    MutualFundPortfolioRequest,
    MutualFundTransactionRequest,
    StockAnalysisRequest,
    StatelessMonitoringRequest,
)
from schema.monitoring import MonitoringCheckRequest
from utils.ai_context import build_portfolio_context, build_projection_context
from utils.auth_guard import get_current_manager
from utils.currency import infer_purchase_currency, normalize_currency
from utils.mutual_fund_calculator import calculate_mutual_fund_portfolio
from utils.mutual_fund_context import build_mutual_fund_context
from utils.mutual_fund_projection import calculate_goal_projection, calculate_projection
from utils.portfolio_calculator import calculate_stock_portfolio
from utils.sip_calculator import calculate_sip_analysis


router = APIRouter(prefix="/api/portfolio", tags=["Portfolio"])
market_provider = MarketDataProvider()
news_provider = NewsProvider()
llm_provider = LLMProvider()
mutual_fund_provider = MutualFundProvider()
NAV_STALE_AFTER_DAYS = 10


def _stock_payload(request: StockAnalysisRequest) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in request.holdings]


@router.post("/analyze")
async def analyze_portfolio(
    request: StockAnalysisRequest,
    current_manager: dict = Depends(get_current_manager),
):
    """Analyze stock holdings supplied directly by the frontend; do not persist them."""
    holdings = _stock_payload(request)
    symbols = sorted({h["symbol"].strip().upper() for h in holdings})
    market_data = await market_provider.get_batch_quotes(symbols)
    warnings: list[str] = []
    purchase_currencies = []

    for holding in holdings:
        currency = normalize_currency(holding.get("currency"))
        if currency is None:
            quote = market_data.get(holding["symbol"].strip().upper(), {})
            currency, _ = infer_purchase_currency(holding, market_exchange=quote.get("exchange"))
        purchase_currencies.append(currency)

    reporting_currency = normalize_currency(request.reporting_currency)

    known_purchase_currencies = {
        currency
        for currency in purchase_currencies
        if currency is not None
    }

    market_currencies = [
        normalize_currency(
            market_data.get(
                holding["symbol"].strip().upper(), {}
            ).get("currency")
        )
        for holding in holdings
    ]

    # Automatically choose a reporting currency only when every holding's
    # purchase and market currencies match and are known.
    currencies_match = (
        len(holdings) > 0
        and all(
            purchase_currency is not None
            and market_currency is not None
            and purchase_currency == market_currency
            for purchase_currency, market_currency
            in zip(purchase_currencies, market_currencies)
        )
    )

    common_currencies = (
        set(purchase_currencies) | set(market_currencies)
    ) - {None}

    if reporting_currency is None:
        if currencies_match and len(common_currencies) == 1:
            reporting_currency = next(iter(common_currencies))
        else:
            warnings.append(
                "A reporting currency is required when holdings use different "
                "currencies or currency metadata is missing."
            )

    exchange_rates: dict[tuple[str, str], float | None] = {}
    if reporting_currency:
        pairs = set()
        for purchase_currency, holding in zip(purchase_currencies, holdings):
            market_currency = normalize_currency(
                market_data.get(holding["symbol"].strip().upper(), {}).get("currency")
            )
            if purchase_currency:
                pairs.add((purchase_currency, reporting_currency))
            if market_currency:
                pairs.add((market_currency, reporting_currency))
        for base, quote in sorted(pairs):
            if base == quote:
                exchange_rates[(base, quote)] = 1.0
            else:
                exchange_rates[(base, quote)] = await market_provider.get_exchange_rate(base, quote)

    portfolio = calculate_stock_portfolio(
        holdings, market_data, reporting_currency, exchange_rates, warnings
    )
    news_data = await news_provider.get_news_for_symbols(symbols, limit=3)
    primary_symbol = symbols[0]
    context = build_portfolio_context(
        client_id=holdings[0]["client_id"],
        portfolio_metrics=portfolio,
        market_data=market_data,
        news_data=news_data,
        requested_symbol=primary_symbol,
        analysis_question=request.analysis_question
    )
    explanation = await llm_provider.generate_explanation(context)
    return {
        "success": True,
        "data": {
            "client_id": holdings[0]["client_id"],
            "symbol": primary_symbol,
            "portfolio": portfolio,
            "warnings": portfolio.get("warnings", []),
            "currency": {
                "reporting_currency": reporting_currency,
                "purchase_currencies": sorted(known_purchase_currencies),
                "market_currencies": sorted({
                    currency
                    for quote in market_data.values()
                    for currency in [normalize_currency(quote.get("currency"))]
                    if currency
                }),
            },
            "market_data": market_data,
            "news": news_data,
            "analysis": explanation,
            "persisted": False,
        },
    }


def _parse_nav_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _nav_is_stale(nav_date: Any) -> bool | None:
    parsed = _parse_nav_date(nav_date)
    if parsed is None:
        return None
    return (date.today() - parsed).days > NAV_STALE_AFTER_DAYS


async def _prepare_mf_holdings(
    request: MutualFundAnalysisRequest,
) -> tuple[list[dict[str, Any]], dict[str, float], list[dict[str, Any]], list[str]]:
    """Resolve schemes and obtain latest published NAVs without storing holdings."""
    rows: list[dict[str, Any]] = []
    live_navs: dict[str, float] = {}
    nav_status: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen_status: set[str] = set()

    for holding in request.holdings:
        row = holding.model_dump(mode="json")
        requested_name = row.get("scheme_name")
        row["_requested_scheme_name"] = requested_name
        raw_code = normalize_scheme_code(row.get("scheme_code"))
        if raw_code:
            row["scheme_code"] = raw_code

        try:
            resolved = await mutual_fund_provider.resolve_scheme(
                requested_name or "",
                scheme_code=raw_code,
            )
        except Exception:
            resolved = {"resolved": False, "available": False, "error": "Scheme resolution failed."}

        nav_entry: dict[str, Any] = {
            "requested_scheme_name": requested_name,
            "scheme_code": raw_code,
            "scheme_name": requested_name,
            "resolved": bool(resolved.get("resolved")),
            "nav": None,
            "nav_date": None,
            "nav_source": "unavailable",
            "status": "unavailable",
            "error": resolved.get("error") or resolved.get("reason"),
        }

        if resolved.get("resolved"):
            code = normalize_scheme_code(resolved.get("scheme_code")) or raw_code
            if code:
                row["scheme_code"] = code
                nav_entry["scheme_code"] = code
            canonical_name = resolved.get("scheme_name")
            if canonical_name:
                row["scheme_name"] = str(canonical_name)
                nav_entry["scheme_name"] = str(canonical_name)
            nav_entry["resolved"] = True

            if code:
                try:
                    current = await mutual_fund_provider.get_current_nav(code)
                except Exception:
                    current = {"available": False, "error": "Latest NAV retrieval failed."}
                if current.get("available") and current.get("nav") is not None:
                    nav = float(current["nav"])
                    nav_date = current.get("nav_date")
                    stale = _nav_is_stale(nav_date)
                    nav_entry.update({
                        "nav": nav,
                        "nav_date": nav_date,
                        "nav_source": "mfnav.in",
                        "status": "stale" if stale is True else "fresh" if stale is False else "freshness_unknown",
                        "error": None,
                    })
                    live_navs[code] = nav
                    row["current_nav"] = nav
                    if row.get("units") is not None:
                        row["current_value"] = round(float(row["units"]) * nav, 2)
                    if stale is True:
                        warnings.append(f"Latest available NAV for {row['scheme_name']} is older than {NAV_STALE_AFTER_DAYS} days.")
                else:
                    nav_entry["error"] = current.get("error") or "Latest NAV unavailable."
                    warnings.append(f"Latest NAV unavailable for {row['scheme_name']}; supplied valuation data will be identified as frontend-provided.")

        # If MFNav cannot resolve/fetch a NAV, retain the supplied statement values as
        # statement data; never label them as live provider data.
        if nav_entry["nav"] is None:
            if row.get("current_nav") is not None:
                nav_entry["nav"] = float(row["current_nav"])
                nav_entry["nav_source"] = "frontend_supplied"
                nav_entry["status"] = "frontend_supplied"
                if row.get("current_value") is None and row.get("units") is not None:
                    row["current_value"] = round(float(row["units"]) * float(row["current_nav"]), 2)
            elif row.get("current_value") is not None:
                nav_entry["nav_source"] = "frontend_current_value"
                nav_entry["status"] = "frontend_supplied"
            else:
                warnings.append(f"No usable NAV or current value is available for {requested_name}.")

        rows.append(row)
        status_key = str(nav_entry.get("scheme_code") or nav_entry.get("scheme_name") or requested_name)
        if status_key not in seen_status:
            nav_status.append(nav_entry)
            seen_status.add(status_key)

    return rows, live_navs, nav_status, sorted(set(warnings))


def _mf_response(selected: pd.DataFrame, live_navs: dict[str, float]) -> dict[str, Any]:
    return calculate_mutual_fund_portfolio(selected, current_navs=live_navs)


def _scheme_group_key(row: dict[str, Any]) -> str:
    code = normalize_scheme_code(row.get("scheme_code"))
    if code:
        return f"code:{code}"
    name = str(row.get("scheme_name") or "").strip().casefold()
    return f"name:{' '.join(name.split())}"


def _build_goal_holdings(
    rows: list[dict[str, Any]],
    live_navs: dict[str, float],
    goal_expected_return_pct: float,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_scheme_group_key(row), []).append(row)

    result: list[dict[str, Any]] = []
    for key, folios in grouped.items():
        code = normalize_scheme_code(folios[0].get("scheme_code"))
        nav = live_navs.get(code) if code else None
        current_values: list[float | None] = []
        sip_values: list[float | None] = []
        rates: set[float] = set()
        for folio in folios:
            units = folio.get("units")
            value = folio.get("current_value")
            if nav is not None and units is not None:
                value = float(units) * nav
            current_values.append(float(value) if value is not None else None)
            sip = folio.get("monthly_sip_amount")
            sip_values.append(float(sip) if sip is not None else None)
            if folio.get("expected_return_pct") is not None:
                rates.add(float(folio["expected_return_pct"]))

        current_value = round(sum(current_values), 2) if current_values and all(v is not None for v in current_values) else None
        monthly_sip = round(sum(sip_values), 2) if sip_values and all(v is not None for v in sip_values) else None
        scheme_rate = next(iter(rates)) if len(rates) == 1 else goal_expected_return_pct
        result.append({
            "scheme_code": code,
            "scheme_name": folios[0].get("scheme_name") or "Unknown scheme",
            "current_value": current_value,
            "monthly_sip_amount": monthly_sip,
            "expected_return_pct": scheme_rate,
            "data_complete": current_value is not None and monthly_sip is not None,
        })
    return result


def _build_sip_analysis(
    transactions: list[MutualFundTransactionRequest] | None,
    holdings: list[dict[str, Any]],
    live_navs: dict[str, float],
    nav_status: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not transactions:
        return []

    status_by_code = {str(s.get("scheme_code")): s for s in nav_status if s.get("scheme_code")}
    grouped_holdings: dict[str, list[dict[str, Any]]] = {}
    code_aliases: dict[str, str] = {}
    name_aliases: dict[str, set[str]] = {}
    for row in holdings:
        key = _scheme_group_key(row)
        grouped_holdings.setdefault(key, []).append(row)
        code = normalize_scheme_code(row.get("scheme_code"))
        if code:
            code_aliases[f"code:{code}"] = key
        for name in (row.get("scheme_name"), row.get("_requested_scheme_name")):
            if name:
                alias = f"name:{' '.join(str(name).strip().casefold().split())}"
                name_aliases.setdefault(alias, set()).add(key)

    by_scheme: dict[str, list[dict[str, Any]]] = {key: [] for key in grouped_holdings}
    unmatched = 0
    for transaction in transactions:
        item = transaction.model_dump(mode="json")
        code = normalize_scheme_code(item.get("scheme_code"))
        # If a code was provided, only accept an exact code match. Never use a
        # scheme-name fallback to attach transactions to a different code.
        key = code_aliases.get(f"code:{code}") if code else None
        if code is None and item.get("scheme_name"):
            alias = f"name:{' '.join(str(item['scheme_name']).strip().casefold().split())}"
            matches = name_aliases.get(alias, set())
            key = next(iter(matches)) if len(matches) == 1 else None
        if key is None:
            unmatched += 1
            continue
        by_scheme[key].append(item)

    analyses: list[dict[str, Any]] = []
    for key, txn_rows in by_scheme.items():
        if not txn_rows:
            continue
        row = grouped_holdings[key][0]
        code = normalize_scheme_code(row.get("scheme_code"))
        nav_info = status_by_code.get(str(code), {}) if code else {}
        nav = live_navs.get(code) if code else None
        if nav is None:
            nav = nav_info.get("nav")
        try:
            analysis = calculate_sip_analysis(pd.DataFrame(txn_rows), current_nav=nav, nav_date=nav_info.get("nav_date"))
        except Exception:
            analysis = {"sip_analysis_available": False, "reason": "Transaction data could not be analysed safely."}
        analyses.append({
            "scheme_code": code,
            "scheme_name": row.get("scheme_name"),
            **analysis,
        })

    if unmatched:
        analyses.append({
            "sip_analysis_available": False,
            "reason": f"{unmatched} transaction record(s) could not be matched to a supplied scheme and were not used.",
        })
    return analyses


@router.post("/mutual-fund/analyze")
async def analyze_mutual_fund(
    request: MutualFundAnalysisRequest,
    scheme_name: str | None = None,
    current_manager: dict = Depends(get_current_manager),
):
    """Analyze frontend-supplied mutual-fund holdings without persisting them."""
    rows, live_navs, nav_status, nav_warnings = await _prepare_mf_holdings(request)
    frame = pd.DataFrame(rows)
    selected = frame

    if scheme_name:
        requested = scheme_name.strip().casefold()
        matching = frame.apply(
            lambda row: requested in {
                str(row.get("scheme_name") or "").strip().casefold(),
                str(row.get("_requested_scheme_name") or "").strip().casefold(),
            },
            axis=1,
        )
        selected = frame[matching]
        if selected.empty:
            raise HTTPException(status_code=404, detail=f"{scheme_name} was not found in the supplied holdings")

    portfolio = _mf_response(selected, live_navs)
    selected_holding = portfolio["holdings"][0] if portfolio.get("holdings") else None
    context = build_mutual_fund_context(
        client_id=request.holdings[0].client_id,
        portfolio_metrics=portfolio,
        selected_holding=selected_holding if scheme_name else None,
        fund_details={"scheme_name": scheme_name} if scheme_name else None,
        analysis_question=request.analysis_question,
    )
    explanation = await llm_provider.generate_explanation(context)
    result: dict[str, Any] = {
        "client_id": request.holdings[0].client_id,
        "asset_type": "mutual_fund",
        "portfolio": portfolio,
        "nav_status": nav_status,
        "warnings": nav_warnings,
        "analysis": explanation,
        "persisted": False,
    }

    sip_analysis = _build_sip_analysis(request.transactions, rows, live_navs, nav_status)
    if request.transactions:
        result["sip_analysis"] = sip_analysis

    if request.goal:
        goal_holdings = _build_goal_holdings(rows, live_navs, request.goal.expected_return_pct)
        try:
            result["goal_projection"] = calculate_goal_projection(goal_holdings, request.goal)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        goal_context = build_projection_context(
            projection_type="SCHEME_BASED_GOAL",
            inputs={"goal": request.goal.model_dump(mode="json"), "scheme_holdings": goal_holdings},
            result=result["goal_projection"],
            analysis_question=request.analysis_question,
        )
        result["goal_projection_analysis"] = await llm_provider.generate_explanation(context + "\n\n" + goal_context)

    if request.projection:
        try:
            result["projection"] = calculate_projection(request.projection)
        except (TypeError, ValueError, OverflowError) as exc:
            raise HTTPException(status_code=422, detail=f"Projection could not be calculated: {exc}") from exc
        projection_context = build_projection_context(
            projection_type=request.projection.projection_type.value,
            inputs=request.projection.model_dump(mode="json"),
            result=result["projection"],
            analysis_question=request.projection.analysis_question or request.analysis_question,
        )
        result["projection_analysis"] = await llm_provider.generate_explanation(context + "\n\n" + projection_context)

    if scheme_name:
        result["holding"] = selected_holding
    return {"success": True, "data": result}


@router.post("/mutual-fund/analyze-portfolio")
async def analyze_mutual_fund_portfolio(
    request: MutualFundPortfolioRequest,
    current_manager: dict = Depends(get_current_manager),
):
    """Analyze the full mutual-fund payload from the frontend."""
    return await analyze_mutual_fund(request, current_manager=current_manager)


@router.post("/monitor")
async def monitor_holding(
    request: MonitoringCheckRequest,
    current_manager: dict = Depends(get_current_manager),
):
    """Legacy stock quote check. Rule evaluation is available at /api/monitoring/check."""
    from services.monitor import MonitoringService

    result = await MonitoringService().check_holding(request.model_dump())
    return {"success": True, "data": result}
