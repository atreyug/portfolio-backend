import httpx
from config.config import settings


class TwelveDataClient:
    def __init__(self):
        self.api_key = settings.TWELVE_DATA_API_KEY
        self.base_url = "https://api.twelvedata.com"

    async def get_price(self, symbol: str) -> dict:
        if not self.api_key:
            raise ValueError("TWELVE_DATA_API_KEY is not configured.")
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/quote",
                params={"symbol": symbol, "apikey": self.api_key},
                timeout=10.0,
            )
            data = resp.json()
            if "price" in data or "close" in data:
                if "price" not in data and "close" in data:
                    data["price"] = data["close"]
                return data
            raise ValueError(data.get("message", "Failed to fetch price"))

    async def get_exchange_rate(self, base: str, quote: str) -> float | None:
        if base == quote:
            return 1.0
        if not self.api_key:
            return None
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/exchange_rate",
                params={
                    "symbol": f"{base}/{quote}",
                    "apikey": self.api_key,
                },
                timeout=10.0,
            )
            data = resp.json()
            try:
                return float(data["rate"])
            except (KeyError, TypeError, ValueError):
                raise ValueError(data.get("message", "Failed to fetch exchange rate"))

    async def get_time_series(self, symbol: str, interval: str = "1day", outputsize: int = 30):
        if not self.api_key:
            return {"values": [], "status": "ok"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/time_series",
                params={
                    "symbol": symbol,
                    "interval": interval,
                    "outputsize": outputsize,
                    "apikey": self.api_key,
                },
                timeout=10.0,
            )
            return resp.json()
