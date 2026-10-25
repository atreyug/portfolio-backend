from typing import Any

from services.financial_news import MarketauxClient


class NewsProvider:

    # Your current Marketaux plan allows max 3 articles/request
    MAX_ARTICLES = 3

    def __init__(self):
        self.client = MarketauxClient()

    async def get_news_for_symbol(
        self,
        symbol: str,
        limit: int = 3,
    ) -> dict[str, Any]:

        symbol = symbol.strip().upper()

        limit = min(
            max(1, limit),
            self.MAX_ARTICLES,
        )

        try:
            return await self.client.get_news_by_symbol(
                symbol=symbol,
                limit=limit,
            )

        except Exception as exc:

            return {
                "data": [],
                "warnings": [
                    f"Marketaux unavailable: {str(exc)}"
                ],
                "source": "fallback",
            }

    async def get_news_for_symbols(
        self,
        symbols: list[str],
        limit: int = 3,
    ) -> dict[str, Any]:

        cleaned_symbols = [
            symbol.strip().upper()
            for symbol in symbols
            if symbol and symbol.strip()
        ]

        # Remove duplicates while preserving order
        cleaned_symbols = list(
            dict.fromkeys(cleaned_symbols)
        )

        limit = min(
            max(1, limit),
            self.MAX_ARTICLES,
        )

        if not cleaned_symbols:
            return {
                "data": [],
                "warnings": [
                    "No valid symbols provided."
                ],
                "source": "empty",
            }

        try:
            return await self.client.get_news_by_symbols(
                symbols=cleaned_symbols,
                limit=limit,
            )

        except Exception as exc:

            return {
                "data": [],
                "warnings": [
                    f"Marketaux unavailable: {str(exc)}"
                ],
                "source": "fallback",
            }