from typing import Any

from services.market_data import TwelveDataClient


class MarketDataProvider:
    def __init__(self):
        self.client = TwelveDataClient()

    async def get_quote(self, symbol: str) -> dict[str, Any]:
        normalized = symbol.strip().upper()
        try:
            data = await self.client.get_price(normalized)
            price = float(data["price"])
            if price <= 0:
                raise ValueError("Provider returned a non-positive price")
            return {
                "available": True,
                "symbol": normalized,
                "price": price,
                "currency": data.get("currency"),
                "exchange": data.get("exchange"),
                "change": data.get("change"),
                "percent_change": data.get("percent_change"),
                "previous_close": data.get("previous_close"),
                "source": "twelve_data",
            }
        except Exception:
            # Keep provider errors generic; never leak query strings or credentials.
            return {
                "available": False,
                "symbol": normalized,
                "price": None,
                "currency": None,
                "exchange": None,
                "change": None,
                "percent_change": None,
                "previous_close": None,
                "source": "twelve_data",
                "error": "Market quote unavailable.",
            }

    async def get_batch_quotes(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        results = {}
        for symbol in symbols:
            normalized = symbol.strip().upper()
            results[normalized] = await self.get_quote(normalized)
        return results

    async def get_exchange_rate(self, base: str, quote: str) -> float | None:
        if base.upper() == quote.upper():
            return 1.0
        try:
            result = await self.client.get_exchange_rate(base.upper(), quote.upper())
            rate = float(result)
            return rate if rate > 0 else None
        except Exception:
            return None

    async def get_time_series(self, symbol: str, interval: str = "1day", outputsize: int = 30):
        return await self.client.get_time_series(
            symbol=symbol.strip().upper(), interval=interval, outputsize=outputsize
        )
