import math
from typing import Any

import pandas as pd


def safe_float(
    value: Any,
) -> float | None:

    if value is None:
        return None

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

def calculate_portfolio(
    df: pd.DataFrame,
) -> dict[str, Any]:

    total_value = (
        pd.to_numeric(
            df["total_value"],
            errors="coerce",
        )
        .fillna(0)
        .sum()
    )

    total_value = safe_float(
        total_value
    ) or 0.0

    holdings = []

    for _, row in df.iterrows():

        value = safe_float(
            row.get("total_value")
        ) or 0.0

        if total_value > 0:

            weight = (
                value
                / total_value
                * 100
            )

        else:

            weight = 0.0

        quantity = safe_float(
            row.get("quantity")
        )

        current_price = safe_float(
            row.get("current_price")
        )

        gain_loss = safe_float(
            row.get("gain_loss")
        )

        absolute_return = safe_float(
            row.get(
                "absolute_return_pct"
            )
        )

        xirr = safe_float(
            row.get("xirr_pct")
        )

        holdings.append(
            {
                "asset_name": str(
                    row.get(
                        "asset_name",
                        ""
                    )
                ),

                "symbol": (
                    str(row["symbol"])
                    if (
                        "symbol" in row
                        and pd.notna(
                            row["symbol"]
                        )
                    )
                    else None
                ),

                "quantity": quantity,

                "current_price": current_price,

                "current_value": round(
                    value,
                    2,
                ),

                "gain_loss": gain_loss,

                "absolute_return_pct": (
                    absolute_return
                ),

                "xirr_pct": xirr,

                "weight_pct": round(
                    weight,
                    2,
                ),
            }
        )

    holdings.sort(
        key=lambda x: (
            x["current_value"] or 0
        ),
        reverse=True,
    )

    concentration = (
        holdings[0]["weight_pct"]
        if holdings
        else 0
    )

    return {
        "total_value": round(
            total_value,
            2,
        ),

        "holding_count": len(
            holdings
        ),

        "top_holdings": holdings[:10],

        "concentration": concentration,
    }


def calculate_stock_portfolio(
    holdings: list[dict[str, Any]],
    market_quotes: dict[str, dict[str, Any]],
    reporting_currency: str | None,
    exchange_rates: dict[tuple[str, str], float | None],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Calculate stock metrics without mixing currencies."""
    from utils.currency import infer_purchase_currency, money, normalize_currency

    warnings = warnings if warnings is not None else []
    positions = []
    for item in holdings:
        quantity = safe_float(item.get("quantity"))
        buy_price = safe_float(item.get("buy_price"))
        symbol = str(item["symbol"]).strip().upper()
        quote = market_quotes.get(symbol) or {}
        purchase_currency = normalize_currency(item.get("currency"))
        inference_note = None
        if purchase_currency is None:
            purchase_currency, inference_note = infer_purchase_currency(
                item,
                market_exchange=quote.get("exchange"),
            )
        if purchase_currency is None:
            warnings.append(f"{symbol}: purchase currency is missing or could not be inferred reliably.")

        market_currency = normalize_currency(quote.get("currency"))
        current_price = safe_float(quote.get("price"))
        if market_currency is None:
            warnings.append(f"{symbol}: market currency metadata is unavailable.")
        if current_price is None:
            warnings.append(f"{symbol}: current market price is unavailable.")

        invested = quantity * buy_price if quantity is not None and buy_price is not None else None
        current_value_native = (
            quantity * current_price
            if quantity is not None and current_price is not None and market_currency
            else None
        )
        invested_reporting = None
        current_value_reporting = None
        if reporting_currency and purchase_currency:
            purchase_rate = (
                1.0
                if purchase_currency == reporting_currency
                else exchange_rates.get((purchase_currency, reporting_currency))
            )
            if purchase_rate is not None:
                invested_reporting = invested * purchase_rate if invested is not None else None
            else:
                warnings.append(f"{symbol}: exchange rate {purchase_currency}/{reporting_currency} is unavailable.")
        if reporting_currency and market_currency and current_value_native is not None:
            market_rate = (
                1.0
                if market_currency == reporting_currency
                else exchange_rates.get((market_currency, reporting_currency))
            )
            if market_rate is not None:
                current_value_reporting = current_value_native * market_rate
            else:
                warnings.append(f"{symbol}: exchange rate {market_currency}/{reporting_currency} is unavailable.")
        profit_loss = (
            current_value_reporting - invested_reporting
            if current_value_reporting is not None and invested_reporting is not None
            else None
        )
        positions.append({
            **item,
            "symbol": symbol,
            "quantity": quantity,
            "buy_price": buy_price,
            "currency": purchase_currency,
            "purchase_currency": purchase_currency,
            "market_currency": market_currency,
            "currency_inference": inference_note,
            "current_price": current_price,
            "invested": round(invested_reporting, 2) if invested_reporting is not None else None,
            "invested_value": round(invested_reporting, 2) if invested_reporting is not None else None,
            "invested_value_native": round(invested, 2) if invested is not None else None,
            "current_value_native": round(current_value_native, 2) if current_value_native is not None else None,
            "current_value": round(current_value_reporting, 2) if current_value_reporting is not None else None,
            "profit_loss": round(profit_loss, 2) if profit_loss is not None else None,
            "profit_loss_percentage": round(profit_loss / invested_reporting * 100, 4) if profit_loss is not None and invested_reporting else None,
            "formatted_invested": money(invested_reporting, reporting_currency),
            "formatted_current_value": money(current_value_reporting, reporting_currency),
            "formatted_profit_loss": money(profit_loss, reporting_currency),
        })

    all_invested_available = all(p["invested"] is not None for p in positions)
    all_values_available = all(
        p["current_value"] is not None and p["invested"] is not None
        for p in positions
    )
    total_invested = sum(p["invested"] for p in positions) if all_invested_available else None
    current_value = sum(p["current_value"] for p in positions) if all_values_available else None
    profit_loss = current_value - total_invested if current_value is not None and total_invested is not None else None
    for position in positions:
        position["weight"] = (
            round(position["current_value"] / current_value * 100, 4)
            if current_value and position["current_value"] is not None and all_values_available
            else None
        )
    positions.sort(key=lambda p: p["current_value"] or 0, reverse=True)
    return {
        "reporting_currency": reporting_currency,
        "total_invested": round(total_invested, 2) if total_invested is not None else None,
        "current_value": round(current_value, 2) if current_value is not None else None,
        "profit_loss": round(profit_loss, 2) if profit_loss is not None else None,
        "return_percentage": round(profit_loss / total_invested * 100, 4) if profit_loss is not None and total_invested else None,
        "formatted_total_invested": money(total_invested, reporting_currency),
        "formatted_current_value": money(current_value, reporting_currency),
        "formatted_profit_loss": money(profit_loss, reporting_currency),
        "warnings": sorted(set(warnings)),
        "positions": positions,
    }
