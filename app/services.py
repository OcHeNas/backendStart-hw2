import re
from collections.abc import Iterator
from contextlib import contextmanager
from threading import BoundedSemaphore

from app.domain import (
    Conflict,
    Crypto,
    CryptoRepository,
    InvalidInput,
    Price,
    PriceProvider,
    utcnow,
)


def normalize_symbol(symbol: str) -> str:
    symbol = symbol.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,31}", symbol):
        raise InvalidInput("Invalid cryptocurrency symbol")
    return symbol


class CryptoService:
    def __init__(
        self, repository: CryptoRepository, provider: PriceProvider, max_inflight: int = 4
    ) -> None:
        if max_inflight < 1:
            raise ValueError("max_inflight must be positive")
        self.repository = repository
        self.provider = provider
        self._slots = BoundedSemaphore(max_inflight)

    @contextmanager
    def _admit(self) -> Iterator[None]:
        if not self._slots.acquire(blocking=False):
            raise Conflict("Too many price operations; retry later")
        try:
            yield
        finally:
            self._slots.release()

    def add(self, symbol: str) -> Crypto:
        symbol = normalize_symbol(symbol)
        with self._admit():
            if any(c.coin.symbol == symbol for c in self.repository.all()):
                raise Conflict("Cryptocurrency already exists")
            coin = self.provider.resolve(symbol)
            price = self.provider.prices([coin.coin_id])[coin.coin_id]
            crypto = Crypto(coin, (Price(price, utcnow()),))
            self.repository.add(crypto)
            return crypto

    def get(self, symbol: str) -> Crypto:
        return self.repository.get(normalize_symbol(symbol))

    def refresh(self, symbol: str) -> Crypto:
        with self._admit():
            before = self.get(symbol)
            price = self.provider.prices([before.coin.coin_id])[before.coin.coin_id]
            after = before.append(price, utcnow())
            self.repository.replace_many((before,), (after,))
            return after

    def refresh_all(self) -> int:
        with self._admit():
            before = self.repository.all()
            if not before:
                return 0
            prices = self.provider.prices([c.coin.coin_id for c in before])
            now = utcnow()
            after = tuple(c.append(prices[c.coin.coin_id], now) for c in before)
            self.repository.replace_many(before, after)
            return len(before)

    def delete(self, symbol: str) -> None:
        self.repository.delete(normalize_symbol(symbol))
