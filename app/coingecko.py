import json
import time
from datetime import UTC, datetime
from decimal import Decimal
from email.utils import parsedate_to_datetime
from threading import RLock
from typing import Any

import httpx

from app.config import Settings
from app.domain import Coin, InvalidInput, ProviderError


class CoinGecko:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        headers = (
            {settings.coingecko_key_header: settings.coingecko_key}
            if settings.coingecko_key
            else {}
        )
        self.client = client or httpx.Client(
            base_url=settings.coingecko_url.rstrip("/") + "/",
            timeout=settings.http_timeout,
            headers=headers,
        )
        self.ttl = settings.cache_ttl
        self._lock = RLock()
        self._mapping: dict[str, list[Coin]] = {}
        self._expires = 0.0
        self._resolved: dict[str, tuple[Coin | None, float]] = {}
        self._cooldown = 0.0

    def _request(self, path: str, params: dict[str, str] | None = None) -> Any:
        if time.monotonic() < self._cooldown:
            raise ProviderError("CoinGecko rate limit; try again later")
        for attempt in range(2):
            try:
                response = self.client.get(path, params=params)
            except httpx.RequestError as exc:
                if attempt == 0:
                    time.sleep(0.2)
                    continue
                raise ProviderError("CoinGecko is unavailable") from exc
            if response.status_code == 429:
                value = response.headers.get("Retry-After", "30")
                try:
                    delay = float(value)
                except ValueError:
                    try:
                        delay = (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
                    except (ValueError, TypeError, OverflowError):
                        delay = 30
                self._cooldown = time.monotonic() + min(max(delay, 1), 3600)
                raise ProviderError("CoinGecko rate limit; try again later")
            if response.status_code >= 500 and attempt == 0:
                time.sleep(0.2)
                continue
            if response.status_code != 200:
                raise ProviderError(f"CoinGecko returned HTTP {response.status_code}")
            try:
                return json.loads(
                    response.content,
                    parse_float=Decimal,
                    parse_constant=lambda value: self._bad_constant(value),
                )
            except (ValueError, UnicodeError) as exc:
                raise ProviderError("Invalid CoinGecko JSON") from exc
        raise ProviderError("CoinGecko is unavailable")

    @staticmethod
    def _bad_constant(value: str) -> None:
        raise ValueError(f"Invalid JSON constant: {value}")

    @staticmethod
    def _coin(row: Any) -> Coin:
        if not isinstance(row, dict) or any(
            not isinstance(row.get(k), str) or not row[k] for k in ("symbol", "id", "name")
        ):
            raise ProviderError("Invalid CoinGecko coin metadata")
        return Coin(row["symbol"].upper(), row["id"], row["name"])

    def resolve(self, symbol: str) -> Coin:
        with self._lock:
            now = time.monotonic()
            cached = self._resolved.get(symbol)
            if cached and cached[1] > now:
                if cached[0] is None:
                    raise InvalidInput("Unknown cryptocurrency symbol")
                return cached[0]
            if now >= self._expires:
                rows = self._request("coins/list")
                if not isinstance(rows, list):
                    raise ProviderError("Invalid CoinGecko coin list")
                mapping: dict[str, list[Coin]] = {}
                for row in rows:
                    # Live catalog includes assets with no ticker. They cannot
                    # be selected through our symbol-based API.
                    if isinstance(row, dict) and row.get("symbol") == "":
                        continue
                    coin = self._coin(row)
                    mapping.setdefault(coin.symbol, []).append(coin)
                self._mapping = mapping
                self._expires = time.monotonic() + self.ttl
            candidates = self._mapping.get(symbol, [])
            if len(candidates) == 1:
                coin = candidates[0]
            else:
                data = self._request("search", {"query": symbol})
                if not isinstance(data, dict) or not isinstance(data.get("coins"), list):
                    raise ProviderError("Invalid CoinGecko search response")
                matches = []
                for row in data["coins"]:
                    if isinstance(row, dict) and row.get("symbol") == "":
                        continue
                    candidate = self._coin(row)
                    if candidate.symbol == symbol:
                        rank = row.get("market_cap_rank")
                        rank = rank if type(rank) is int and rank > 0 else 2**63
                        matches.append((rank, candidate.coin_id, candidate))
                if not matches:
                    self._resolved[symbol] = (None, now + min(self.ttl, 60))
                    raise InvalidInput("Unknown cryptocurrency symbol")
                # Symbol collisions: prefer best market-cap rank, then stable ID.
                coin = min(matches, key=lambda item: item[:2])[2]
            self._resolved[symbol] = (coin, time.monotonic() + self.ttl)
            return coin

    def prices(self, coin_ids: list[str]) -> dict[str, Decimal]:
        with self._lock:
            result = {}
            for offset in range(0, len(coin_ids), 200):
                batch = coin_ids[offset : offset + 200]
                data = self._request(
                    "simple/price",
                    {"ids": ",".join(batch), "vs_currencies": "usd", "precision": "full"},
                )
                if not isinstance(data, dict):
                    raise ProviderError("Invalid CoinGecko price response")
                for coin_id in batch:
                    row = data.get(coin_id)
                    value = row.get("usd") if isinstance(row, dict) else None
                    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
                        raise ProviderError("CoinGecko price is missing or invalid")
                    price = Decimal(value)
                    if not price.is_finite() or price < 0:
                        raise ProviderError("CoinGecko price is invalid")
                    result[coin_id] = price
            return result

    def close(self) -> None:
        self.client.close()
