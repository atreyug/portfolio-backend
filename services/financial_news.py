import httpx
from datetime import datetime, timedelta, timezone

from config.config import settings


class MarketauxClient:

    RECENT_NEWS_DAYS = 7

    def __init__(self):
        self.api_key = settings.MARKETAUX_API_KEY
        self.base_url = "https://api.marketaux.com/v1"

    async def get_news_by_symbol(
        self,
        symbol: str,
        limit: int = 3,
    ) -> dict:

        symbol = symbol.strip().upper()

        if not self.api_key:
            return {
                "data": [],
                "source": "mock",
                "warnings": [
                    "MARKETAUX_API_KEY is not configured."
                ],
            }

        published_after = (
            datetime.now(timezone.utc) - timedelta(days=self.RECENT_NEWS_DAYS)
        ).strftime("%Y-%m-%dT%H:%M")

        params = {
            "symbols": symbol,
            "limit": limit,
            "api_token": self.api_key,
            "language": "en",
            "filter_entities": "true",
            "must_have_entities": "true",
            "published_after": published_after,
        }

        async with httpx.AsyncClient(
            timeout=15.0
        ) as client:

            response = await client.get(
                f"{self.base_url}/news/all",
                params=params,
            )

            response.raise_for_status()

            payload = response.json()
            if not isinstance(payload, dict):
                return {
                    "data": [],
                    "warnings": ["Marketaux returned an empty response."],
                    "source": "marketaux",
                }

            articles = payload.get("data")
            if not isinstance(articles, list):
                payload["data"] = []
                payload.setdefault(
                    "warnings",
                    ["No recent English news found for the supplied symbol(s)."],
                )
            elif not articles:
                payload.setdefault(
                    "warnings",
                    ["No recent English news found for the supplied symbol(s)."],
                )
            return payload

    async def get_news_by_symbols(
        self,
        symbols: list[str],
        limit: int = 3,
    ) -> dict:

        cleaned_symbols = [
            symbol.strip().upper()
            for symbol in symbols
            if symbol and symbol.strip()
        ]

        cleaned_symbols = list(
            dict.fromkeys(cleaned_symbols)
        )

        if not cleaned_symbols:
            return {
                "data": [],
                "warnings": [
                    "No symbols provided."
                ],
            }

        symbols_str = ",".join(
            cleaned_symbols
        )

        return await self.get_news_by_symbol(
            symbols_str,
            limit=limit,
        )
