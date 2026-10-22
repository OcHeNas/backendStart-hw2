import re
from threading import RLock

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
    def __init__(self, repository: CryptoRepository, provider: PriceProvider) -> None:
        self.repository = repository
        self.provider = provider
        self._mutations = RLock()

    def add(self, symbol: str) -> Crypto:
        symbol = normalize_symbol(symbol)
        with self._mutations:
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
        with self._mutations:
            crypto = self.get(symbol)
            price = self.provider.prices([crypto.coin.coin_id])[crypto.coin.coin_id]
            crypto = crypto.append(price, utcnow())
            self.repository.replace_many((crypto,))
            return crypto

    def refresh_all(self) -> int:
        with self._mutations:
            cryptos = self.repository.all()
            if not cryptos:
                return 0
            prices = self.provider.prices([c.coin.coin_id for c in cryptos])
            now = utcnow()
            # Commit only after every quote has been fetched and validated.
            self.repository.replace_many(
                tuple(c.append(prices[c.coin.coin_id], now) for c in cryptos)
            )
            return len(cryptos)

    def delete(self, symbol: str) -> None:
        with self._mutations:
            self.repository.delete(normalize_symbol(symbol))
