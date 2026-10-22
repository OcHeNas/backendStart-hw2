from threading import RLock

from app.domain import Conflict, Crypto, NotFound


class MemoryUsers:
    def __init__(self) -> None:
        self._lock = RLock()
        self._users: dict[str, str] = {}

    def add(self, username: str, password_hash: str) -> None:
        with self._lock:
            if username in self._users:
                raise Conflict("Username already exists")
            self._users[username] = password_hash

    def get_hash(self, username: str) -> str | None:
        with self._lock:
            return self._users.get(username)


class MemoryCryptos:
    def __init__(self) -> None:
        self._lock = RLock()
        self._cryptos: dict[str, Crypto] = {}

    def all(self) -> tuple[Crypto, ...]:
        with self._lock:
            return tuple(self._cryptos[k] for k in sorted(self._cryptos))

    def get(self, symbol: str) -> Crypto:
        with self._lock:
            if symbol not in self._cryptos:
                raise NotFound("Cryptocurrency is not tracked")
            return self._cryptos[symbol]

    def add(self, crypto: Crypto) -> None:
        with self._lock:
            if crypto.coin.symbol in self._cryptos:
                raise Conflict("Cryptocurrency already exists")
            self._cryptos[crypto.coin.symbol] = crypto

    def replace_many(self, cryptos: tuple[Crypto, ...]) -> None:
        with self._lock:
            if any(c.coin.symbol not in self._cryptos for c in cryptos):
                raise NotFound("Cryptocurrency is not tracked")
            self._cryptos.update({c.coin.symbol: c for c in cryptos})

    def delete(self, symbol: str) -> None:
        with self._lock:
            self.get(symbol)
            del self._cryptos[symbol]
