"""Deterministic mutual-fund/SIP projection calculations.

All rates are annual percentage assumptions (e.g. 10 means 10%).
Monthly contribution timing is end-of-month. Projections are estimates,
not guarantees. This module has no database or file-persistence code.
"""
from __future__ import annotations

from datetime import date
from math import isfinite
from typing import Any

from schema.portfolio import MutualFundGoalRequest, MutualFundProjectionRequest, ProjectionType


def _monthly_rate(return_pct: float) -> float:
    if not isfinite(float(return_pct)) or return_pct <= -100:
        raise ValueError("expected_return_pct must be finite and greater than -100")
    return float(return_pct) / 100.0 / 12.0


def _growth_factor(rate: float, months: int) -> float:
    if months < 0:
        raise ValueError("duration_months cannot be negative")
    return (1.0 + rate) ** months


def _annuity_factor(rate: float, months: int) -> float:
    if months <= 0:
        raise ValueError("duration_months must be greater than zero")
    if abs(rate) < 1e-12:
        return float(months)
    return ((1.0 + rate) ** months - 1.0) / rate


def calculate_future_value(
    current_investment: float,
    monthly_sip: float,
    duration_months: int,
    return_pct: float,
) -> float:
    if current_investment < 0 or monthly_sip < 0:
        raise ValueError("Investment and SIP values cannot be negative")
    rate = _monthly_rate(return_pct)
    growth = _growth_factor(rate, duration_months)
    return current_investment * growth + monthly_sip * _annuity_factor(rate, duration_months)


def calculate_required_sip_total(
    target: float, current_investment: float, duration_months: int, return_pct: float
) -> float:
    """Total monthly SIP required if no other recurring SIP is already counted."""
    if target <= 0 or current_investment < 0:
        raise ValueError("target must be positive and current investment non-negative")
    rate = _monthly_rate(return_pct)
    corpus_future_value = current_investment * _growth_factor(rate, duration_months)
    factor = _annuity_factor(rate, duration_months)
    return max(0.0, (target - corpus_future_value) / factor)


def calculate_required_sip(
    target: float,
    current_investment: float,
    existing_monthly_sip: float,
    duration_months: int,
    return_pct: float,
) -> float:
    """Return the additional monthly SIP needed beyond existing SIPs."""
    if existing_monthly_sip < 0:
        raise ValueError("existing_monthly_sip cannot be negative")
    required_total = calculate_required_sip_total(
        target, current_investment, duration_months, return_pct
    )
    return max(0.0, required_total - existing_monthly_sip)


def calculate_time_to_target(
    target: float, current_investment: float, monthly_sip: float, return_pct: float
) -> int | None:
    if target <= 0 or current_investment < 0 or monthly_sip < 0:
        raise ValueError("Invalid target, current investment, or SIP amount")
    if target <= current_investment:
        return 0
    if current_investment == 0 and monthly_sip == 0:
        return None
    rate = _monthly_rate(return_pct)
    value = current_investment
    for month in range(1, 1201):
        value = value * (1.0 + rate) + monthly_sip
        if value >= target:
            return month
    return None


def calculate_lumpsum_growth(current_investment: float, duration_months: int, return_pct: float) -> float:
    return calculate_future_value(current_investment, 0.0, duration_months, return_pct)


def build_growth_series(
    current_investment: float, monthly_sip: float, duration_months: int, return_pct: float
) -> list[dict[str, Any]]:
    if duration_months > 1200:
        raise ValueError("duration_months cannot exceed 1200 (100 years)")
    rate = _monthly_rate(return_pct)
    value = float(current_investment)
    series = [{"month": 0, "value": round(value, 2)}]
    for month in range(1, duration_months + 1):
        value = value * (1.0 + rate) + monthly_sip
        series.append({"month": month, "value": round(value, 2)})
    return series


def calculate_projection(request: MutualFundProjectionRequest) -> dict[str, Any]:
    """Backward-compatible single-scenario projection endpoint calculation."""
    current = float(request.current_investment or 0.0)
    monthly_sip = float(request.monthly_sip_amount or 0.0)
    months = request.duration_months
    target = request.target_amount
    annual_return = float(request.expected_return_pct)

    if request.projection_type in {ProjectionType.FUTURE_VALUE, ProjectionType.LUMPSUM_GROWTH}:
        included_sip = monthly_sip if request.projection_type == ProjectionType.FUTURE_VALUE else 0.0
        future = calculate_future_value(current, included_sip, months, annual_return)
        contributions = current + included_sip * months
        return {
            "projection_type": request.projection_type.value,
            "current_investment": round(current, 2),
            "monthly_sip_amount": round(included_sip, 2),
            "duration_months": months,
            "expected_return_pct": annual_return,
            "future_value": round(future, 2),
            "total_contributions": round(contributions, 2),
            "estimated_gain": round(future - contributions, 2),
            "growth_series": build_growth_series(current, included_sip, months, annual_return),
        }

    if request.projection_type == ProjectionType.REQUIRED_SIP:
        required_total = calculate_required_sip_total(target, current, months, annual_return)
        additional = max(0.0, required_total - monthly_sip)
        return {
            "projection_type": request.projection_type.value,
            "target_amount": round(target, 2),
            "current_investment": round(current, 2),
            "existing_monthly_sip": round(monthly_sip, 2),
            "required_total_monthly_sip": round(required_total, 2),
            "additional_monthly_sip_required": round(additional, 2),
            # Retained for compatibility; now explicitly means additional SIP.
            "required_monthly_sip": round(additional, 2),
            "duration_months": months,
            "expected_return_pct": annual_return,
            "growth_series": build_growth_series(current, monthly_sip + additional, months, annual_return),
        }

    duration = calculate_time_to_target(target, current, monthly_sip, annual_return)
    return {
        "projection_type": request.projection_type.value,
        "target_amount": round(target, 2),
        "current_investment": round(current, 2),
        "monthly_sip_amount": round(monthly_sip, 2),
        "expected_return_pct": annual_return,
        "duration_months": duration,
    }


def _months_until(target_date: date) -> int:
    today = date.today()
    months = (target_date.year - today.year) * 12 + target_date.month - today.month
    if target_date.day < today.day:
        months -= 1
    return max(1, months)


def calculate_goal_projection(
    scheme_holdings: list[dict[str, Any]], goal: MutualFundGoalRequest
) -> dict[str, Any]:
    """Project the supplied current schemes and known SIP contributions.

    `scheme_holdings` must be aggregated per scheme. Unknown monthly SIP
    amounts are not treated as zero unless the goal request explicitly opts in.
    Additional SIP is reported only when the baseline inputs are complete.
    """
    months = goal.duration_months or _months_until(goal.target_date)
    if months > 1200:
        raise ValueError("Goal duration cannot exceed 1200 months")

    projected_schemes: list[dict[str, Any]] = []
    warnings: list[str] = []
    complete = True
    base_total = 0.0
    existing_monthly_sip_total = 0.0
    total_future_contributions = 0.0

    for holding in scheme_holdings:
        name = str(holding.get("scheme_name") or "Unknown scheme")
        code = holding.get("scheme_code")
        current_value = holding.get("current_value")
        monthly_sip = holding.get("monthly_sip_amount")
        assumption = holding.get("expected_return_pct")
        if assumption is None:
            assumption = goal.expected_return_pct
        assumption = float(assumption)
        rate = _monthly_rate(assumption)

        current_value = float(current_value) if current_value is not None else None
        if current_value is None:
            complete = False
            warnings.append(f"Current value is unavailable for {name}.")
        elif current_value < 0:
            raise ValueError(f"Current value cannot be negative for {name}.")

        if monthly_sip is None:
            if goal.assume_unknown_sip_zero:
                monthly_sip = 0.0
                warnings.append(f"Unknown SIP for {name} was explicitly assumed to be ₹0 per month.")
            else:
                complete = False
                warnings.append(f"Monthly SIP amount is unknown for {name}; confirm it or explicitly assume zero.")
        else:
            monthly_sip = float(monthly_sip)
            if monthly_sip < 0:
                raise ValueError(f"Monthly SIP cannot be negative for {name}.")

        corpus_future = None if current_value is None else current_value * _growth_factor(rate, months)
        sip_future = None if monthly_sip is None else monthly_sip * _annuity_factor(rate, months)
        scheme_future = None if corpus_future is None or sip_future is None else corpus_future + sip_future

        if scheme_future is not None:
            base_total += scheme_future
        if monthly_sip is not None:
            existing_monthly_sip_total += monthly_sip
            total_future_contributions += monthly_sip * months
        if current_value is not None:
            total_future_contributions += 0.0  # Current corpus is not a future contribution.

        projected_schemes.append({
            "scheme_code": code,
            "scheme_name": name,
            "current_value": round(current_value, 2) if current_value is not None else None,
            "monthly_sip_amount": round(monthly_sip, 2) if monthly_sip is not None else None,
            "expected_return_pct": assumption,
            "projected_existing_corpus_value": round(corpus_future, 2) if corpus_future is not None else None,
            "projected_existing_sip_value": round(sip_future, 2) if sip_future is not None else None,
            "projected_value": round(scheme_future, 2) if scheme_future is not None else None,
            "future_sip_contributions": round(monthly_sip * months, 2) if monthly_sip is not None else None,
            "estimated_gain": round(scheme_future - current_value - monthly_sip * months, 2) if scheme_future is not None and current_value is not None and monthly_sip is not None else None,
        })

    projected_total = round(base_total, 2) if complete else None
    target_gap = round(float(goal.target_amount) - projected_total, 2) if projected_total is not None else None
    surplus = round(projected_total - float(goal.target_amount), 2) if projected_total is not None else None
    reached = bool(projected_total is not None and projected_total >= float(goal.target_amount)) if complete else None

    additional_rate_pct = goal.additional_sip_return_pct
    if additional_rate_pct is None:
        additional_rate_pct = goal.expected_return_pct
    if complete:
        additional_factor = _annuity_factor(_monthly_rate(additional_rate_pct), months)
        additional_sip = max(0.0, (float(goal.target_amount) - projected_total) / additional_factor)
        required_total_sip = existing_monthly_sip_total + additional_sip
    else:
        additional_sip = None
        required_total_sip = None

    def scenario(rate_pct: float | None) -> dict[str, Any]:
        if rate_pct is None:
            return {"available": False, "reason": "No return assumption supplied for this scenario."}
        if not complete:
            return {"available": False, "reason": "Required holding values and SIP amounts are incomplete."}
        rate = _monthly_rate(rate_pct)
        future_value = 0.0
        for holding in scheme_holdings:
            current_value = float(holding["current_value"])
            monthly_sip = holding.get("monthly_sip_amount")
            if monthly_sip is None and goal.assume_unknown_sip_zero:
                monthly_sip = 0.0
            future_value += current_value * _growth_factor(rate, months)
            future_value += float(monthly_sip) * _annuity_factor(rate, months)
        future_value = round(future_value, 2)
        return {
            "available": True,
            "assumed_annual_return_pct": rate_pct,
            "projected_value": future_value,
            "target_gap": round(float(goal.target_amount) - future_value, 2),
            "target_reached": future_value >= float(goal.target_amount),
        }

    return {
        "projection_type": "SCHEME_BASED_GOAL",
        "target_amount": round(float(goal.target_amount), 2),
        "duration_months": months,
        "target_date": goal.target_date.isoformat() if goal.target_date else None,
        "projected_value": projected_total,
        "projected_surplus": surplus,
        "target_shortfall": max(0.0, target_gap) if target_gap is not None else None,
        "target_gap": target_gap,
        "target_reached": reached,
        "existing_monthly_sip_total": round(existing_monthly_sip_total, 2) if complete else None,
        "required_total_monthly_sip": round(required_total_sip, 2) if required_total_sip is not None else None,
        "additional_monthly_sip_required": round(additional_sip, 2) if additional_sip is not None else None,
        "additional_sip_return_assumption_pct": additional_rate_pct,
        "allocation_status": "not_allocated_to_individual_schemes",
        "projection_complete": complete,
        "assumptions": {
            "base_return_pct": goal.expected_return_pct,
            "scheme_specific_return_overrides_used": True,
            "lower_and_higher_scenarios_use_uniform_portfolio_rates": True,
            "contribution_timing": "end_of_month",
            "unknown_sips_assumed_zero": goal.assume_unknown_sip_zero,
            "returns_are_estimates_not_guarantees": True,
        },
        "scheme_projections": projected_schemes,
        "scenarios": {
            "lower": scenario(goal.lower_return_pct),
            "base": {
                "available": complete,
                "assumed_return_pct": goal.expected_return_pct,
                "projected_value": projected_total,
                "target_gap": target_gap,
                "target_reached": reached,
                "note": "Base scenario uses scheme-specific return assumptions when supplied.",
            },
            "higher": scenario(goal.higher_return_pct),
        },
        "warnings": sorted(set(warnings)),
    }
