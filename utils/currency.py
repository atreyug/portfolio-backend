from __future__ import annotations

from typing import Any

from schema.portfolio import CurrencyCode


EXCHANGE_CURRENCY = {
    "NSE": "INR",
    "BSE": "INR",
    "NASDAQ": "USD",
    "NYSE": "USD",
    "AMEX": "USD",
    "NYSEARCA": "USD",
}


def normalize_currency(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, CurrencyCode):
        return value.value
    value = str(value).strip().upper()
    return value if value in {item.value for item in CurrencyCode} else None


def infer_purchase_currency(
    holding: dict[str, Any],
    market_exchange: str | None = None,
) -> tuple[str | None, str | None]:
    """Infer only from an explicit exchange with a known ISO currency."""
    exchange = str(
        holding.get("exchange") or market_exchange or ""
    ).strip().upper()
    currency = EXCHANGE_CURRENCY.get(exchange)
    if currency:
        return currency, f"inferred from exchange {exchange}"
    return None, None


def money(value: float | None, currency: str | None) -> str | None:
    if value is None or currency is None:
        return None
    symbol = {"INR": chr(0x20B9), "USD": "$"}.get(currency, currency + " ")
    return f"{symbol}{value:,.2f}"
