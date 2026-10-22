from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from typing import Protocol


def utcnow() -> datetime:
    return datetime.now(UTC)


class ServiceError(Exception):
    """An expected application failure, translated by the HTTP adapter."""


class InvalidInput(ServiceError):
    pass


class Conflict(ServiceError):
    pass


class NotFound(ServiceError):
    pass


class Unauthorized(ServiceError):
    pass


class ProviderError(ServiceError):
    pass


@dataclass(frozen=True)
class Coin:
    symbol: str
    coin_id: str
    name: str


@dataclass(frozen=True)
class Price:
    price: Decimal
    timestamp: datetime


@dataclass(frozen=True)
class Crypto:
    coin: Coin
    history: tuple[Price, ...]

    def append(self, price: Decimal, timestamp: datetime) -> "Crypto":
        return replace(self, history=(*self.history, Price(price, timestamp))[-100:])

    @property
    def latest(self) -> Price:
        return self.history[-1]

    def stats(self) -> dict[str, Decimal | int | None]:
        values = [p.price for p in self.history]
        # Stored quotes are never rounded; calculations use 50 significant digits.
        with localcontext() as ctx:
            ctx.prec = 50
            change = values[-1] - values[0]
            percent = change / values[0] * 100 if values[0] else None
            return dict(
                min_price=min(values),
                max_price=max(values),
                avg_price=sum(values) / len(values),
                price_change=change,
                price_change_percent=percent,
                records_count=len(values),
            )


class CryptoRepository(Protocol):
    def all(self) -> tuple[Crypto, ...]: ...
    def get(self, symbol: str) -> Crypto: ...
    def add(self, crypto: Crypto) -> None: ...
    def replace_many(self, cryptos: tuple[Crypto, ...]) -> None: ...
    def delete(self, symbol: str) -> None: ...


class UserRepository(Protocol):
    def add(self, username: str, password_hash: str) -> None: ...
    def get_hash(self, username: str) -> str | None: ...


class PriceProvider(Protocol):
    def resolve(self, symbol: str) -> Coin: ...
    def prices(self, coin_ids: list[str]) -> dict[str, Decimal]: ...
    def close(self) -> None: ...
