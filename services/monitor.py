"""Stateless in-memory monitoring for frontend-supplied assets and rules.

This service intentionally contains no database imports or persistence.
A request is evaluated independently; clients keep any alert/transition state.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from providers.market_data import MarketDataProvider
from providers.mutual_funds import MutualFundProvider, normalize_scheme_code
from schema.portfolio import (
    MonitoringAssetType,
    MonitoringRuleType,
    StatelessMonitoringRequest,
)


class MonitoringService:
    def __init__(self) -> None:
        self.market = MarketDataProvider()
        self.mutual_funds = MutualFundProvider()

    async def check_holding(self, holding: dict[str, Any]) -> dict[str, Any]:
        """Backward-compatible quote check for legacy clients; this does not save data."""
        symbol = str(holding.get("symbol") or "").strip().upper()
        if not symbol:
            raise ValueError("symbol is required")
        quote = await self.market.get_quote(symbol)
        current_price = quote.get("price")
        result: dict[str, Any] = {
            "client_id": holding.get("client_id"),
            "symbol": symbol,
            "quantity": holding.get("quantity"),
            "buy_price": holding.get("buy_price"),
            "exchange": holding.get("exchange"),
            "current_price": current_price,
            "market_data": quote,
            "rules_evaluated": False,
            "persisted": False,
            "message": "This compatibility endpoint checks a quote only. Submit assets and rules to /api/monitoring/check for rule evaluation.",
        }
        quantity = holding.get("quantity")
        buy_price = holding.get("buy_price")
        if current_price is not None and quantity is not None and buy_price is not None:
            invested = float(quantity) * float(buy_price)
            value = float(quantity) * float(current_price)
            result.update({
                "current_value": round(value, 2),
                "profit_loss": round(value - invested, 2),
                "return_percentage": round((value - invested) / invested * 100, 4) if invested else None,
            })
        return result

    async def check_stateless(self, request: StatelessMonitoringRequest) -> dict[str, Any]:
        """Evaluate each submitted asset independently and never persist results."""
        results: list[dict[str, Any]] = []
        failures = 0
        for asset in request.assets:
            try:
                if asset.asset_type == MonitoringAssetType.STOCK:
                    result = await self._check_stock_asset(request.client_id, asset)
                else:
                    result = await self._check_mutual_fund_asset(request.client_id, asset)
            except Exception:
                # Do not expose provider exceptions or sensitive request payloads.
                failures += 1
                result = {
                    "client_id": request.client_id,
                    "asset_type": asset.asset_type.value,
                    "symbol": asset.symbol,
                    "scheme_code": asset.scheme_code,
                    "scheme_name": asset.scheme_name,
                    "status": "error",
                    "error": "This asset could not be checked due to a provider or processing error.",
                    "metrics": {},
                    "alerts": [
                        {
                            "rule_id": rule.rule_id,
                            "rule_type": rule.rule_type.value,
                            "threshold": rule.threshold,
                            "triggered": None,
                            "evaluated": False,
                            "reason": "Rule could not be evaluated because required data was unavailable.",
                        }
                        for rule in asset.rules
                    ],
                }
            results.append(result)

        return {
            "client_id": request.client_id,
            "assets": results,
            "checked_assets": len(results),
            "failed_assets": failures,
            "persisted": False,
            "alert_state_persisted": False,
            "note": "No holdings, rules, evaluations, or alerts were stored. Keep deduplication state in the frontend.",
        }

    async def _check_stock_asset(self, client_id: str, asset) -> dict[str, Any]:
        symbol = asset.symbol.strip().upper()
        quote = await self.market.get_quote(symbol)
        price = quote.get("price")
        metrics: dict[str, Any] = {
            "current_price": price,
            "current_value": None,
            "invested_value": None,
            "profit_loss": None,
            "return_percentage": None,
        }
        if price is not None and asset.quantity is not None and asset.buy_price is not None:
            invested = float(asset.quantity) * float(asset.buy_price)
            value = float(asset.quantity) * float(price)
            metrics.update({
                "current_value": round(value, 2),
                "invested_value": round(invested, 2),
                "profit_loss": round(value - invested, 2),
                "return_percentage": round((value - invested) / invested * 100, 4) if invested else None,
            })

        alerts = self._evaluate_rules(asset.rules, metrics, quote)
        return {
            "client_id": client_id,
            "asset_type": asset.asset_type.value,
            "symbol": symbol,
            "status": "available" if price is not None else "data_unavailable",
            "market_data": quote,
            "metrics": metrics,
            "alerts": alerts,
        }

    async def _check_mutual_fund_asset(self, client_id: str, asset) -> dict[str, Any]:
        resolved = await self.mutual_funds.resolve_scheme(
            asset.scheme_name or "",
            scheme_code=asset.scheme_code,
        )
        if not resolved.get("resolved") or not resolved.get("scheme_code"):
            return {
                "client_id": client_id,
                "asset_type": asset.asset_type.value,
                "scheme_code": asset.scheme_code,
                "scheme_name": asset.scheme_name,
                "status": "scheme_unresolved",
                "scheme_resolution": resolved,
                "metrics": {"current_nav": None, "current_value": None, "profit_loss": None, "return_percentage": None},
                "alerts": self._unavailable_alerts(asset.rules, "Scheme could not be resolved."),
            }

        code = normalize_scheme_code(resolved.get("scheme_code"))
        nav_data = await self.mutual_funds.get_current_nav(code)
        nav = nav_data.get("nav") if nav_data.get("available") else None
        metrics: dict[str, Any] = {
            "current_nav": nav,
            "current_value": None,
            "invested_value": asset.invested_value,
            "profit_loss": None,
            "return_percentage": None,
            "nav_change_pct": None,
        }
        if nav is not None and asset.units is not None:
            current_value = float(asset.units) * float(nav)
            metrics["current_value"] = round(current_value, 2)
            if asset.invested_value is not None and float(asset.invested_value) > 0:
                pnl = current_value - float(asset.invested_value)
                metrics["profit_loss"] = round(pnl, 2)
                metrics["return_percentage"] = round(pnl / float(asset.invested_value) * 100, 4)

        if any(rule.rule_type == MonitoringRuleType.NAV_CHANGE_PCT for rule in asset.rules):
            metrics["nav_change_pct"] = await self._get_nav_change_pct(code)

        rule_context = {
            **nav_data,
            "latest_day_change_pct": metrics.get("nav_change_pct"),
        }
        return {
            "client_id": client_id,
            "asset_type": asset.asset_type.value,
            "scheme_code": code,
            "scheme_name": resolved.get("scheme_name") or asset.scheme_name,
            "status": "available" if nav is not None else "data_unavailable",
            "scheme_resolution": {"resolved": True, "warnings": resolved.get("warnings", [])},
            "nav_data": nav_data,
            "metrics": metrics,
            "alerts": self._evaluate_rules(asset.rules, metrics, rule_context),
        }

    async def _get_nav_change_pct(self, scheme_code: str | None) -> float | None:
        """Calculate percentage change from the two latest NAV observations."""
        if not scheme_code:
            return None
        today = date.today()
        start = (today - timedelta(days=14)).isoformat()
        try:
            history = await self.mutual_funds.get_nav_history(
                scheme_code, start_date=start, end_date=today.isoformat()
            )
        except Exception:
            return None
        records = history.get("records") if history.get("available") else None
        if not records or len(records) < 2:
            return None
        try:
            # Provider returns newest-first history.
            latest = float(records[0]["nav"])
            previous = float(records[1]["nav"])
            if previous <= 0:
                return None
            return round((latest / previous - 1.0) * 100.0, 4)
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            return None

    @staticmethod
    def _unavailable_alerts(rules, reason: str) -> list[dict[str, Any]]:
        return [
            {
                "rule_id": rule.rule_id,
                "rule_type": rule.rule_type.value,
                "threshold": rule.threshold,
                "triggered": None,
                "evaluated": False,
                "reason": reason,
            }
            for rule in rules
        ]

    @staticmethod
    def _evaluate_rules(rules, metrics: dict[str, Any], data: dict[str, Any]) -> list[dict[str, Any]]:
        alerts: list[dict[str, Any]] = []
        for rule in rules:
            triggered, reason, evaluated = MonitoringService._rule_result(
                rule.rule_type, float(rule.threshold), metrics, data
            )
            alerts.append({
                "rule_id": rule.rule_id,
                "rule_type": rule.rule_type.value,
                "threshold": rule.threshold,
                "triggered": triggered,
                "evaluated": evaluated,
                "reason": reason,
            })
        return alerts

    @staticmethod
    def _rule_result(
        rule_type: MonitoringRuleType,
        threshold: float,
        metrics: dict[str, Any],
        data: dict[str, Any],
    ) -> tuple[bool | None, str, bool]:
        price = metrics.get("current_price")
        if price is None:
            price = metrics.get("current_nav")

        if rule_type == MonitoringRuleType.PRICE_ABOVE:
            if price is None:
                return None, "Current price/NAV unavailable; rule was not evaluated.", False
            return price >= threshold, "Current price/NAV is at or above the threshold." if price >= threshold else "Current price/NAV is below the threshold.", True

        if rule_type == MonitoringRuleType.PRICE_BELOW:
            if price is None:
                return None, "Current price/NAV unavailable; rule was not evaluated.", False
            return price <= threshold, "Current price/NAV is at or below the threshold." if price <= threshold else "Current price/NAV is above the threshold.", True

        return_pct = metrics.get("return_percentage")
        if rule_type in {MonitoringRuleType.LOSS_PCT_ABOVE, MonitoringRuleType.MF_LOSS_PCT_ABOVE}:
            if return_pct is None:
                return None, "Return percentage unavailable; cost basis and current valuation are required.", False
            triggered = float(return_pct) <= -threshold
            return triggered, "Loss percentage meets the threshold." if triggered else "Loss percentage is below the threshold.", True

        if rule_type == MonitoringRuleType.GAIN_PCT_ABOVE:
            if return_pct is None:
                return None, "Return percentage unavailable; cost basis and current valuation are required.", False
            triggered = float(return_pct) >= threshold
            return triggered, "Gain percentage meets the threshold." if triggered else "Gain percentage is below the threshold.", True

        if rule_type == MonitoringRuleType.NAV_CHANGE_PCT:
            change = metrics.get("nav_change_pct")
            if change is None:
                return None, "NAV change is unavailable because at least two recent NAV observations were not available.", False
            triggered = abs(float(change)) >= threshold
            return triggered, "Absolute NAV change meets the threshold." if triggered else "Absolute NAV change is below the threshold.", True

        return None, "Unsupported rule type; rule was not evaluated.", False
