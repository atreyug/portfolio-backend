"""
Utility: SIP (Systematic Investment Plan) calculations.

A SIP is a transaction-level investment method into a mutual fund.
This module handles:
  - SIP metrics from transaction-level data (Level 2 analysis)
  - Graceful degradation when only a holding statement is available

XIRR is computed using actual dated cash flows via scipy.optimize.
We fall back to None + explanation when scipy is unavailable or
when the cash flows are degenerate.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

import pandas as pd

from utils.json_utils import sanitize_for_json


# ---------------------------------------------------------------------------
# XIRR – cash flow based IRR
# ---------------------------------------------------------------------------

def _xirr(
    cash_flows: list[float],
    dates: list[date],
    guess: float = 0.1,
) -> float | None:
    """
    Compute XIRR from a list of cash flows and dates.

    Negative cash flows = investments out.
    Positive cash flows = redemptions / current value.

    Returns annualised IRR as a fraction (e.g. 0.12 for 12%),
    or None if it cannot be computed.
    """
    if len(cash_flows) != len(dates) or len(cash_flows) < 2:
        return None

    # Validate: must have at least one positive and one negative flow
    has_pos = any(cf > 0 for cf in cash_flows)
    has_neg = any(cf < 0 for cf in cash_flows)
    if not (has_pos and has_neg):
        return None

    try:
        from scipy.optimize import brentq  # type: ignore
    except ImportError:
        return None

    base_date = min(dates)
    years = [
        (d - base_date).days / 365.0
        for d in dates
    ]

    def _npv(rate: float) -> float:
        total = 0.0
        for cf, y in zip(cash_flows, years):
            try:
                total += cf / ((1 + rate) ** y)
            except (OverflowError, ZeroDivisionError):
                return float("inf")
        return total

    try:
        result = brentq(_npv, -0.999, 100.0, xtol=1e-8, maxiter=1000)
        if not math.isfinite(result):
            return None
        return result
    except (ValueError, RuntimeError):
        return None


# ---------------------------------------------------------------------------
# Transaction-level SIP analysis
# ---------------------------------------------------------------------------

def calculate_sip_analysis(
    transactions_df: pd.DataFrame,
    current_nav: float | None,
    nav_date: str | None = None,
) -> dict[str, Any]:
    """
    Compute full SIP analysis from a transaction-level DataFrame.

    Expected columns (after parsing + aliasing):
      transaction_date, transaction_type, amount, nav, units

    Returns:
      {
        "sip_analysis_available": True,
        "scheme_name": ...,
        "total_invested": ...,
        "total_units": ...,
        "current_nav": ...,
        "current_value": ...,
        "gain_loss": ...,
        "absolute_return_pct": ...,
        "xirr_pct": ...,
        "avg_acquisition_nav": ...,
        "sip_installment_count": ...,
        "transaction_summary": [...],
        ...
      }
    """
    if transactions_df.empty:
        return {
            "sip_analysis_available": False,
            "reason": "No transaction records provided.",
        }

    required = ["transaction_date", "transaction_type", "amount", "nav", "units"]
    missing = [c for c in required if c not in transactions_df.columns]
    if missing:
        return {
            "sip_analysis_available": False,
            "reason": (
                f"Transaction data is missing required columns: {missing}. "
                "Cannot perform full SIP analysis."
            ),
        }

    df = transactions_df.copy()

    # Parse transaction_date
    df["_date"] = pd.to_datetime(df["transaction_date"], errors="coerce", dayfirst=True)
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df["nav"] = pd.to_numeric(df["nav"], errors="coerce")
    df["units"] = pd.to_numeric(df["units"], errors="coerce")
    df["transaction_type"] = df["transaction_type"].astype(str).str.strip().str.upper()

    # Drop rows with no parseable date
    df = df.dropna(subset=["_date"])

    if df.empty:
        return {
            "sip_analysis_available": False,
            "reason": "No parseable transaction dates found.",
        }

    # Sort chronologically
    df = df.sort_values("_date")

    # Classify transaction types
    purchase_types = {"SIP", "PURCHASE", "BUY", "SWITCH IN", "SWITCHIN", "NFO"}
    redemption_types = {"REDEMPTION", "SELL", "REDEEM", "SWITCH OUT", "SWITCHOUT"}

    def _is_purchase(txn_type: str) -> bool:
        return any(pt in txn_type for pt in purchase_types)

    def _is_redemption(txn_type: str) -> bool:
        return any(rt in txn_type for rt in redemption_types)

    sip_rows = df[df["transaction_type"].apply(
        lambda t: t == "SIP"
    )]
    purchase_rows = df[df["transaction_type"].apply(_is_purchase)]
    redemption_rows = df[df["transaction_type"].apply(_is_redemption)]

    # Totals
    total_invested = float(purchase_rows["amount"].fillna(0).sum())
    total_redeemed = float(redemption_rows["amount"].fillna(0).sum())
    total_units_purchased = float(purchase_rows["units"].fillna(0).sum())
    total_units_redeemed = float(redemption_rows["units"].fillna(0).sum())
    net_units = total_units_purchased - total_units_redeemed

    sip_count = len(sip_rows)
    total_purchase_count = len(purchase_rows)

    # Current value
    current_value: float | None = None
    if current_nav is not None and net_units > 0:
        current_value = round(net_units * current_nav, 2)

    # Gain/loss
    gain_loss: float | None = None
    abs_return: float | None = None
    if current_value is not None and total_invested > 0:
        gain_loss = round(current_value - (total_invested - total_redeemed), 2)
        net_cost = total_invested - total_redeemed
        if net_cost > 0:
            abs_return = round(gain_loss / net_cost * 100, 4)

    # Average acquisition NAV
    avg_nav: float | None = None
    if net_units > 0 and (total_invested - total_redeemed) > 0:
        avg_nav = round((total_invested - total_redeemed) / net_units, 4)

    # XIRR cash flows
    xirr_pct: float | None = None
    cf_list: list[float] = []
    date_list: list[date] = []

    for _, row in purchase_rows.iterrows():
        amt = row.get("amount")
        dt = row.get("_date")
        if pd.notna(amt) and pd.notna(dt):
            cf_list.append(-abs(float(amt)))  # outflow is negative
            date_list.append(pd.Timestamp(dt).date())

    for _, row in redemption_rows.iterrows():
        amt = row.get("amount")
        dt = row.get("_date")
        if pd.notna(amt) and pd.notna(dt):
            cf_list.append(abs(float(amt)))  # inflow
            date_list.append(pd.Timestamp(dt).date())

    # Terminal value as final inflow
    if current_value and current_value > 0:
        # Value the terminal cash flow on the NAV valuation date when supplied,
        # not automatically today if the latest published NAV is older.
        valuation_dt = pd.to_datetime(nav_date, errors="coerce") if nav_date else pd.NaT
        terminal_date = (
            valuation_dt.date()
            if not pd.isna(valuation_dt)
            else datetime.today().date()
        )
        cf_list.append(current_value)
        date_list.append(terminal_date)

    if cf_list and date_list:
        raw_xirr = _xirr(cf_list, date_list)
        if raw_xirr is not None:
            xirr_pct = round(raw_xirr * 100, 4)

    # Investment duration
    first_date = df["_date"].min()
    last_date = df["_date"].max()
    duration_days = (last_date - first_date).days if pd.notna(first_date) and pd.notna(last_date) else None

    # SIP regularity (approximate)
    sip_consistency: str | None = None
    if len(sip_rows) >= 3:
        sip_dates = sorted(sip_rows["_date"].dropna().tolist())
        gaps = [(sip_dates[i + 1] - sip_dates[i]).days for i in range(len(sip_dates) - 1)]
        avg_gap = sum(gaps) / len(gaps)
        max_gap = max(gaps)
        if max_gap <= avg_gap * 1.5:
            sip_consistency = "Regular"
        else:
            sip_consistency = "Irregular (some gaps detected)"

    # Transaction summary
    txn_summary = []
    for _, row in df.iterrows():
        txn_summary.append({
            "date": row["_date"].strftime("%Y-%m-%d") if pd.notna(row["_date"]) else None,
            "type": str(row.get("transaction_type", "")),
            "amount": float(row["amount"]) if pd.notna(row.get("amount")) else None,
            "nav": float(row["nav"]) if pd.notna(row.get("nav")) else None,
            "units": float(row["units"]) if pd.notna(row.get("units")) else None,
        })

    return sanitize_for_json({
        "sip_analysis_available": True,
        "total_invested": round(total_invested, 2),
        "total_redeemed": round(total_redeemed, 2),
        "total_units_purchased": round(total_units_purchased, 6),
        "total_units_redeemed": round(total_units_redeemed, 6),
        "net_units": round(net_units, 6),
        "current_nav": current_nav,
        "nav_date": nav_date,
        "current_value": current_value,
        "gain_loss": gain_loss,
        "absolute_return_pct": abs_return,
        "xirr_pct": xirr_pct,
        "xirr_note": None if xirr_pct is not None else "XIRR could not be computed (scipy not installed or degenerate cash flows).",
        "avg_acquisition_nav": avg_nav,
        "sip_installment_count": sip_count,
        "total_purchase_transactions": total_purchase_count,
        "sip_consistency": sip_consistency,
        "investment_duration_days": duration_days,
        "first_transaction_date": first_date.strftime("%Y-%m-%d") if pd.notna(first_date) else None,
        "last_transaction_date": last_date.strftime("%Y-%m-%d") if pd.notna(last_date) else None,
        "transaction_summary": txn_summary,
    })


def no_transaction_data_response() -> dict[str, Any]:
    """
    Return the standard 'no SIP transaction data' response.
    Used when transaction-level data is not supplied.
    """
    return {
        "sip_analysis_available": False,
        "reason": "Transaction-level data was not provided. "
                  "Only holding statement analysis is available.",
    }
