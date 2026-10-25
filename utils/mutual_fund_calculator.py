"""
Mutual-fund portfolio calculations for folio-level holding statements.

The request payload is folio-level:

    Scheme
       ├── Folio 1
       ├── Folio 2
       └── ...

Therefore calculations are maintained at both levels:

1. Folio level
2. Scheme level

Transaction columns supported:

    Purchase
    Switch In
    Div Reinv
    Redemption
    Switch Out
    Div Pay

Definitions used for the supplied request:

    gross_invested
        = Purchase + Switch In + Div Reinv

    cost_basis
        = gross_invested - Redemption - Switch Out

    current_value
        = current units × live/current NAV

    gain_loss
        = current_value - cost_basis

    absolute_return_pct
        = gain_loss / gross_invested × 100

XIRR:

    XIRR from the request is preserved at folio level.
    A scheme-level XIRR is NOT fabricated by averaging folio XIRRs.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import pandas as pd

from utils.json_utils import sanitize_for_json


# ============================================================
# SAFE HELPERS
# ============================================================

def _safe_float(
    value: Any,
) -> float | None:

    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except (
        TypeError,
        ValueError,
    ):
        pass

    try:
        value = float(value)

        if not math.isfinite(value):
            return None

        return value

    except (
        TypeError,
        ValueError,
    ):
        return None


def _safe_pct(
    numerator: Any,
    denominator: Any,
) -> float | None:

    numerator = _safe_float(
        numerator
    )

    denominator = _safe_float(
        denominator
    )

    if (
        numerator is None
        or denominator is None
        or denominator == 0
    ):
        return None

    return round(
        numerator
        / denominator
        * 100,
        4,
    )


def _clean_text(
    value: Any,
) -> str | None:

    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except (
        TypeError,
        ValueError,
    ):
        pass

    text = str(value).strip()

    if not text:
        return None

    if text.lower() in {
        "nan",
        "none",
        "nat",
    }:
        return None

    return text


# ============================================================
# TRANSACTION HELPERS
# ============================================================

def _column_sum(
    row: dict[str, Any],
    column_names: list[str],
) -> float | None:
    """
    Return the value for the first matching column.

    These request fields represent one transaction category
    per row, so there should normally be exactly one matching
    name.
    """

    for column in column_names:

        if column in row:

            value = _safe_float(
                row.get(column)
            )

            if value is None:
                return 0.0

            return value

    return None


def _derive_transaction_values(
    row: dict[str, Any],
) -> dict[str, float | None]:
    """
    Derive investment/cost values from the request's transaction fields.
    """

    purchase = _column_sum(
        row,
        [
            "Purchase",
            "purchase",
        ],
    )

    switch_in = _column_sum(
        row,
        [
            "Switch In",
            "switch in",
        ],
    )

    div_reinv = _column_sum(
        row,
        [
            "Div Reinv",
            "div reinv",
        ],
    )

    redemption = _column_sum(
        row,
        [
            "Redemption",
            "redemption",
        ],
    )

    switch_out = _column_sum(
        row,
        [
            "Switch Out",
            "switch out",
        ],
    )

    div_pay = _column_sum(
        row,
        [
            "Div Pay",
            "div pay",
        ],
    )

    transaction_columns_present = any(
        column in row
        for column in [
            "Purchase",
            "purchase",
            "Switch In",
            "switch in",
            "Div Reinv",
            "div reinv",
            "Redemption",
            "redemption",
            "Switch Out",
            "switch out",
            "Div Pay",
            "div pay",
        ]
    )

    if not transaction_columns_present:

        return {
            "gross_invested": None,
            "cost_basis": None,
            "purchase": None,
            "switch_in": None,
            "div_reinv": None,
            "redemption": None,
            "switch_out": None,
            "div_pay": None,
        }

    purchase_value = (
        purchase or 0.0
    )

    switch_in_value = (
        switch_in or 0.0
    )

    div_reinv_value = (
        div_reinv or 0.0
    )

    redemption_value = (
        redemption or 0.0
    )

    switch_out_value = (
        switch_out or 0.0
    )

    gross_invested = (
        purchase_value
        + switch_in_value
        + div_reinv_value
    )

    cost_basis = (
        gross_invested
        - redemption_value
        - switch_out_value
    )

    return {
        "gross_invested": round(
            gross_invested,
            2,
        ),
        "cost_basis": round(
            cost_basis,
            2,
        ),
        "purchase": round(
            purchase_value,
            2,
        ),
        "switch_in": round(
            switch_in_value,
            2,
        ),
        "div_reinv": round(
            div_reinv_value,
            2,
        ),
        "redemption": round(
            redemption_value,
            2,
        ),
        "switch_out": round(
            switch_out_value,
            2,
        ),
        "div_pay": round(
            div_pay or 0.0,
            2,
        ),
    }


# ============================================================
# NAV PERFORMANCE
# ============================================================

def compute_nav_performance(
    nav_records: list[dict],
    reference_date: datetime | None = None,
) -> dict[str, Any]:
    """
    Compute NAV performance from records:

        {
            "date": "YYYY-MM-DD",
            "nav": 123.45
        }
    """

    if not nav_records:

        return {
            "latest_nav": None,
            "nav_date": None,
            "return_1m_pct": None,
            "return_3m_pct": None,
            "return_6m_pct": None,
            "return_1y_pct": None,
            "cagr_3y_pct": None,
            "cagr_5y_pct": None,
            "unavailable_metrics": [
                "All – no NAV history available."
            ],
        }

    parsed: list[
        tuple[datetime, float]
    ] = []

    for record in nav_records:

        try:

            date_value = datetime.fromisoformat(
                str(
                    record["date"]
                )
            )

            nav_value = float(
                record["nav"]
            )

            if (
                math.isfinite(
                    nav_value
                )
                and nav_value > 0
            ):
                parsed.append(
                    (
                        date_value,
                        nav_value,
                    )
                )

        except (
            KeyError,
            TypeError,
            ValueError,
        ):
            continue

    if not parsed:

        return {
            "latest_nav": None,
            "nav_date": None,
            "return_1m_pct": None,
            "return_3m_pct": None,
            "return_6m_pct": None,
            "return_1y_pct": None,
            "cagr_3y_pct": None,
            "cagr_5y_pct": None,
            "unavailable_metrics": [
                (
                    "All – NAV records "
                    "could not be parsed."
                )
            ],
        }

    parsed.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    latest_date, latest_nav = (
        parsed[0]
    )

    calculation_date = (
        reference_date
        or latest_date
    )

    def _nav_at(
        days_ago: int,
    ) -> float | None:

        target = (
            calculation_date
            - pd.Timedelta(
                days=days_ago
            )
        )

        eligible = [
            item
            for item in parsed
            if item[0] <= target
        ]

        if not eligible:
            return None

        closest = min(
            eligible,
            key=lambda item: abs(
                (
                    item[0]
                    - target
                ).days
            ),
        )

        return closest[1]

    def _period_return(
        days_ago: int,
    ) -> float | None:

        old_nav = _nav_at(
            days_ago
        )

        if (
            old_nav is None
            or old_nav == 0
        ):
            return None

        return round(
            (
                latest_nav
                - old_nav
            )
            / old_nav
            * 100,
            4,
        )

    def _cagr(
        years: int,
    ) -> float | None:

        old_nav = _nav_at(
            years * 365
        )

        if (
            old_nav is None
            or old_nav <= 0
        ):
            return None

        ratio = (
            latest_nav
            / old_nav
        )

        if ratio <= 0:
            return None

        return round(
            (
                ratio ** (
                    1 / years
                )
                - 1
            )
            * 100,
            4,
        )

    r1m = _period_return(
        30
    )
    r3m = _period_return(
        90
    )
    r6m = _period_return(
        180
    )
    r1y = _period_return(
        365
    )

    c3y = _cagr(3)
    c5y = _cagr(5)

    unavailable = []

    if r1m is None:
        unavailable.append(
            "return_1m_pct – insufficient history."
        )

    if r3m is None:
        unavailable.append(
            "return_3m_pct – insufficient history."
        )

    if r6m is None:
        unavailable.append(
            "return_6m_pct – insufficient history."
        )

    if r1y is None:
        unavailable.append(
            "return_1y_pct – insufficient history."
        )

    if c3y is None:
        unavailable.append(
            "cagr_3y_pct – insufficient 3-year history."
        )

    if c5y is None:
        unavailable.append(
            "cagr_5y_pct – insufficient 5-year history."
        )

    return sanitize_for_json(
        {
            "latest_nav": latest_nav,
            "nav_date": latest_date.strftime(
                "%Y-%m-%d"
            ),
            "return_1m_pct": r1m,
            "return_3m_pct": r3m,
            "return_6m_pct": r6m,
            "return_1y_pct": r1y,
            "cagr_3y_pct": c3y,
            "cagr_5y_pct": c5y,
            "unavailable_metrics": unavailable,
        }
    )


# ============================================================
# FOLIO METRICS
# ============================================================

def compute_mf_holding_metrics(
    row: dict[str, Any],
    current_nav: float | None,
) -> dict[str, Any]:
    """
    Calculate one folio.

    Live NAV from mfnav is authoritative.

    Example:

        units = 16,755.076
        live NAV = 20.75

        current value =
            16,755.076 × 20.75
    """

    units = _safe_float(
        row.get("units")
    )

    supplied_nav = _safe_float(
        row.get("current_nav")
    )

    live_nav = _safe_float(
        current_nav
    )

    nav_used = (
        live_nav
        if live_nav is not None
        else supplied_nav
    )

    supplied_current_value = (
        _safe_float(
            row.get(
                "current_value"
            )
        )
    )

    supplied_gain_loss = (
        _safe_float(
            row.get(
                "gain_loss"
            )
        )
    )

    supplied_abs_return = (
        _safe_float(
            row.get(
                "absolute_return_pct"
            )
        )
    )

    xirr = _safe_float(
        row.get("xirr_pct")
    )

    transactions = (
        _derive_transaction_values(
            row
        )
    )

    gross_invested = transactions[
        "gross_invested"
    ]

    cost_basis = transactions[
        "cost_basis"
    ]

    # Fallback if the request provides a normalized invested_value.
    if gross_invested is None:

        explicit_invested = (
            _safe_float(
                row.get(
                    "invested_value"
                )
            )
        )

        gross_invested = (
            explicit_invested
        )

        cost_basis = (
            explicit_invested
        )

    # If transaction data is unavailable but current value + gain/loss
    # exist, infer the statement's cost basis.
    if (
        cost_basis is None
        and supplied_current_value is not None
        and supplied_gain_loss is not None
    ):

        cost_basis = round(
            supplied_current_value
            - supplied_gain_loss,
            2,
        )

    # --------------------------------------------------------
    # Current value
    # --------------------------------------------------------

    if (
        live_nav is not None
        and units is not None
    ):

        current_value = round(
            units
            * live_nav,
            2,
        )

    elif (
        nav_used is not None
        and units is not None
    ):

        current_value = round(
            units
            * nav_used,
            2,
        )

    else:

        current_value = supplied_current_value

    # --------------------------------------------------------
    # Gain/loss
    # --------------------------------------------------------

    if (
        current_value is not None
        and cost_basis is not None
    ):

        gain_loss = round(
            current_value
            - cost_basis,
            2,
        )

    else:

        gain_loss = (
            supplied_gain_loss
        )

    # --------------------------------------------------------
    # Absolute return
    # --------------------------------------------------------

    if (
        gain_loss is not None
        and gross_invested is not None
        and gross_invested != 0
    ):

        absolute_return = (
            _safe_pct(
                gain_loss,
                gross_invested,
            )
        )

    else:

        absolute_return = (
            supplied_abs_return
        )

    return sanitize_for_json(
        {
            "units": units,

            "current_nav": nav_used,

            "nav_source": (
                "mfnav"
                if live_nav is not None
                else (
                    "request"
                    if supplied_nav is not None
                    else None
                )
            ),

            "current_value": (
                current_value
            ),

            "gross_invested": (
                gross_invested
            ),

            "invested_value": (
                gross_invested
            ),

            "cost_basis": (
                cost_basis
            ),

            "gain_loss": (
                gain_loss
            ),

            "absolute_return_pct": (
                absolute_return
            ),

            "xirr_pct": xirr,

            "purchase": transactions[
                "purchase"
            ],

            "switch_in": transactions[
                "switch_in"
            ],

            "div_reinv": transactions[
                "div_reinv"
            ],

            "redemption": transactions[
                "redemption"
            ],

            "switch_out": transactions[
                "switch_out"
            ],

            "div_pay": transactions[
                "div_pay"
            ],
        }
    )


# ============================================================
# SCHEME HELPERS
# ============================================================

def _scheme_key(
    row: dict[str, Any],
) -> str:

    scheme_code = _clean_text(
        row.get(
            "scheme_code"
        )
    )

    if scheme_code:
        return (
            "code:"
            + scheme_code
        )

    scheme_name = _clean_text(
        row.get(
            "scheme_name"
        )
    )

    if scheme_name:
        normalized = (
            " ".join(
                scheme_name
                .casefold()
                .split()
            )
        )

        return (
            "name:"
            + normalized
        )

    return "unknown"


def _first_nonempty(
    rows: list[dict[str, Any]],
    key: str,
) -> Any:

    for row in rows:

        value = _clean_text(
            row.get(key)
        )

        if value is not None:
            return value

    return None


def _folio_number(
    value: Any,
) -> str | None:

    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except (
        TypeError,
        ValueError,
    ):
        pass

    # Numeric value supplied by the frontend.
    if isinstance(value, float):

        if (
            math.isfinite(value)
            and value.is_integer()
        ):
            return str(
                int(value)
            )

    text = str(
        value
    ).strip()

    if not text:
        return None

    if text.lower() in {
        "nan",
        "none",
    }:
        return None

    # Frontends may provide scientific notation as text.
    if "e" in text.lower():

        try:

            number = float(
                text
            )

            if (
                math.isfinite(
                    number
                )
                and number.is_integer()
            ):

                return str(
                    int(number)
                )

        except ValueError:
            pass

    return text


# ============================================================
# SCHEME AGGREGATION
# ============================================================

def _aggregate_scheme(
    rows: list[dict[str, Any]],
    folio_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Combine multiple folios of one scheme.
    """

    first_row = rows[0]

    total_units = sum(
        (
            _safe_float(
                folio.get(
                    "units"
                )
            )
            or 0.0
        )
        for folio in folio_records
    )

    total_current_value = sum(
        (
            _safe_float(
                folio.get(
                    "current_value"
                )
            )
            or 0.0
        )
        for folio in folio_records
    )

    total_gross_invested = sum(
        (
            _safe_float(
                folio.get(
                    "gross_invested"
                )
            )
            or 0.0
        )
        for folio in folio_records
    )

    total_cost_basis = sum(
        (
            _safe_float(
                folio.get(
                    "cost_basis"
                )
            )
            or 0.0
        )
        for folio in folio_records
    )

    total_gain_loss = round(
        total_current_value
        - total_cost_basis,
        2,
    )

    total_absolute_return = (
        _safe_pct(
            total_gain_loss,
            total_gross_invested,
        )
    )

    xirr_values = [
        _safe_float(
            folio.get(
                "xirr_pct"
            )
        )
        for folio in folio_records
        if _safe_float(
            folio.get(
                "xirr_pct"
            )
        ) is not None
    ]

    xirr_note = None

    if xirr_values:

        xirr_note = (
            "XIRR is supplied at folio level. "
            "A scheme-level XIRR is not calculated "
            "because averaging individual XIRRs would "
            "not produce a mathematically valid portfolio XIRR."
        )

    return sanitize_for_json(
        {
            "scheme_name": _clean_text(
                first_row.get(
                    "scheme_name"
                )
            ),

            "scheme_code": _clean_text(
                first_row.get(
                    "scheme_code"
                )
            ),

            "isin": _first_nonempty(
                rows,
                "isin",
            ),

            "fund_house": _first_nonempty(
                rows,
                "fund_house",
            ),

            "category": _first_nonempty(
                rows,
                "category",
            ),

            "sub_category": _first_nonempty(
                rows,
                "sub_category",
            ),

            "plan_type": _first_nonempty(
                rows,
                "plan_type",
            ),

            "option_type": _first_nonempty(
                rows,
                "option_type",
            ),

            "folio_count": len(
                folio_records
            ),

            "units": round(
                total_units,
                6,
            ),

            "current_nav": (
                folio_records[0].get(
                    "current_nav"
                )
                if folio_records
                else None
            ),

            "nav_source": (
                folio_records[0].get(
                    "nav_source"
                )
                if folio_records
                else None
            ),

            "current_value": round(
                total_current_value,
                2,
            ),

            "gross_invested": round(
                total_gross_invested,
                2,
            ),

            "invested_value": round(
                total_gross_invested,
                2,
            ),

            "cost_basis": round(
                total_cost_basis,
                2,
            ),

            "gain_loss": (
                total_gain_loss
            ),

            "absolute_return_pct": (
                total_absolute_return
            ),

            "xirr_pct": None,

            "xirr_note": xirr_note,

            "folios": folio_records,
        }
    )


# ============================================================
# COMPLETE PORTFOLIO
# ============================================================

def calculate_mutual_fund_portfolio(
    df: pd.DataFrame,
    current_navs: dict[
        str,
        float | None,
    ] | None = None,
) -> dict[str, Any]:
    """
    Calculate the complete MF portfolio.

    `holdings`
        Scheme-level holdings.

    `folio_holdings`
        Original folio-level holdings.

    This prevents one scheme with multiple folios from appearing as
    multiple funds in concentration/exposure calculations.
    """

    current_navs = (
        current_navs or {}
    )

    if df.empty:

        return {
            "total_value": 0.0,
            "total_invested": None,
            "total_cost_basis": None,
            "total_gain_loss": None,
            "total_absolute_return_pct": None,
            "holding_count": 0,
            "scheme_count": 0,
            "folio_count": 0,
            "holdings": [],
            "folio_holdings": [],
            "top_holdings": [],
            "fund_house_exposure": {},
            "category_exposure": {},
            "concentration": {
                "largest_fund_pct": 0.0,
                "largest_amc_pct": 0.0,
                "largest_category_pct": 0.0,
            },
        }

    grouped: dict[
        str,
        list[
            tuple[
                dict[str, Any],
                dict[str, Any]
            ]
        ]
    ] = {}

    folio_holdings = []

    # --------------------------------------------------------
    # Folio-level calculations
    # --------------------------------------------------------

    for _, series in df.iterrows():

        row = series.to_dict()

        key = _scheme_key(
            row
        )

        scheme_code = _clean_text(
            row.get(
                "scheme_code"
            )
        )

        live_nav = None

        if scheme_code:
            live_nav = current_navs.get(
                scheme_code
            )

        metrics = (
            compute_mf_holding_metrics(
                row,
                live_nav,
            )
        )

        folio_record = sanitize_for_json(
            {
                "scheme_name": _clean_text(
                    row.get(
                        "scheme_name"
                    )
                ),

                "folio_no": _folio_number(
                    row.get(
                        "folio_no"
                    )
                ),

                "investment_date": (
                    str(
                        row.get(
                            "investment_date"
                        )
                    )
                    if row.get(
                        "investment_date"
                    ) is not None
                    and str(
                        row.get(
                            "investment_date"
                        )
                    )
                    not in {
                        "NaT",
                        "nan",
                        "None",
                    }
                    else None
                ),

                **metrics,
            }
        )

        grouped.setdefault(
            key,
            [],
        ).append(
            (
                row,
                folio_record,
            )
        )

        folio_holdings.append(
            folio_record
        )

    # --------------------------------------------------------
    # Scheme-level aggregation
    # --------------------------------------------------------

    holdings = []

    total_value = 0.0
    total_invested = 0.0
    total_cost_basis = 0.0

    have_invested = False
    have_cost_basis = False

    for items in grouped.values():

        rows = [
            item[0]
            for item in items
        ]

        folios = [
            item[1]
            for item in items
        ]

        scheme_holding = (
            _aggregate_scheme(
                rows,
                folios,
            )
        )

        current_value = (
            _safe_float(
                scheme_holding.get(
                    "current_value"
                )
            )
            or 0.0
        )

        gross_invested = (
            _safe_float(
                scheme_holding.get(
                    "gross_invested"
                )
            )
        )

        cost_basis = (
            _safe_float(
                scheme_holding.get(
                    "cost_basis"
                )
            )
        )

        total_value += (
            current_value
        )

        if gross_invested is not None:
            total_invested += (
                gross_invested
            )
            have_invested = True

        if cost_basis is not None:
            total_cost_basis += (
                cost_basis
            )
            have_cost_basis = True

        holdings.append(
            scheme_holding
        )

    # --------------------------------------------------------
    # Weights
    # --------------------------------------------------------

    for holding in holdings:

        current_value = (
            _safe_float(
                holding.get(
                    "current_value"
                )
            )
            or 0.0
        )

        holding[
            "weight_pct"
        ] = (
            round(
                current_value
                / total_value
                * 100,
                4,
            )
            if total_value > 0
            else 0.0
        )

    holdings.sort(
        key=lambda item: (
            _safe_float(
                item.get(
                    "current_value"
                )
            )
            or 0.0
        ),
        reverse=True,
    )

    # --------------------------------------------------------
    # Fund-house exposure
    # --------------------------------------------------------

    house_map: dict[
        str,
        float,
    ] = {}

    for holding in holdings:

        house = (
            _clean_text(
                holding.get(
                    "fund_house"
                )
            )
            or "Unknown"
        )

        house_map[house] = (
            house_map.get(
                house,
                0.0,
            )
            + (
                _safe_float(
                    holding.get(
                        "current_value"
                    )
                )
                or 0.0
            )
        )

    fund_house_exposure = {
        key: {
            "value": round(
                value,
                2,
            ),
            "weight_pct": (
                round(
                    value
                    / total_value
                    * 100,
                    4,
                )
                if total_value > 0
                else 0.0
            ),
        }
        for key, value in sorted(
            house_map.items(),
            key=lambda item: -item[1],
        )
    }

    # --------------------------------------------------------
    # Category exposure
    # --------------------------------------------------------

    category_map: dict[
        str,
        float,
    ] = {}

    for holding in holdings:

        category = (
            _clean_text(
                holding.get(
                    "category"
                )
            )
            or "Unknown"
        )

        category_map[category] = (
            category_map.get(
                category,
                0.0,
            )
            + (
                _safe_float(
                    holding.get(
                        "current_value"
                    )
                )
                or 0.0
            )
        )

    category_exposure = {
        key: {
            "value": round(
                value,
                2,
            ),
            "weight_pct": (
                round(
                    value
                    / total_value
                    * 100,
                    4,
                )
                if total_value > 0
                else 0.0
            ),
        }
        for key, value in sorted(
            category_map.items(),
            key=lambda item: -item[1],
        )
    }

    # --------------------------------------------------------
    # Totals
    # --------------------------------------------------------

    total_invested_value = (
        round(
            total_invested,
            2,
        )
        if have_invested
        else None
    )

    total_cost_basis_value = (
        round(
            total_cost_basis,
            2,
        )
        if have_cost_basis
        else None
    )

    total_gain_loss = None

    if (
        total_cost_basis_value
        is not None
    ):

        total_gain_loss = round(
            total_value
            - total_cost_basis_value,
            2,
        )

    total_absolute_return = (
        _safe_pct(
            total_gain_loss,
            total_invested_value,
        )
    )

    # --------------------------------------------------------
    # Concentration
    # --------------------------------------------------------

    largest_fund_pct = (
        holdings[0].get(
            "weight_pct"
        )
        if holdings
        else 0.0
    )

    largest_amc_pct = max(
        (
            value.get(
                "weight_pct"
            )
            for value
            in fund_house_exposure.values()
        ),
        default=0.0,
    )

    largest_category_pct = max(
        (
            value.get(
                "weight_pct"
            )
            for value
            in category_exposure.values()
        ),
        default=0.0,
    )

    return sanitize_for_json(
        {
            "total_value": round(
                total_value,
                2,
            ),

            "total_invested": (
                total_invested_value
            ),

            "total_cost_basis": (
                total_cost_basis_value
            ),

            "total_gain_loss": (
                total_gain_loss
            ),

            "total_absolute_return_pct": (
                total_absolute_return
            ),

            "holding_count": len(
                holdings
            ),

            "scheme_count": len(
                holdings
            ),

            "folio_count": len(
                folio_holdings
            ),

            "holdings": holdings,

            "folio_holdings": (
                folio_holdings
            ),

            "top_holdings": (
                holdings[:10]
            ),

            "fund_house_exposure": (
                fund_house_exposure
            ),

            "category_exposure": (
                category_exposure
            ),

            "concentration": {
                "largest_fund_pct": round(
                    largest_fund_pct,
                    4,
                ),
                "largest_amc_pct": round(
                    largest_amc_pct,
                    4,
                ),
                "largest_category_pct": round(
                    largest_category_pct,
                    4,
                ),
            },
        }
    )
