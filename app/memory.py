from threading import RLock

from app.domain import Conflict, Crypto, NotFound, User


class MemoryUsers:
    def __init__(self) -> None:
        self._lock = RLock()
        self._users: dict[str, User] = {}

    def add(self, username: str, password_hash: str) -> User:
        with self._lock:
            if username in self._users:
                raise Conflict("Username already exists")
            user = User(username, password_hash)
            self._users[username] = user
            return user

    def get(self, username: str) -> User | None:
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

    def replace_many(self, expected: tuple[Crypto, ...], cryptos: tuple[Crypto, ...]) -> None:
        if len(expected) != len(cryptos):
            raise ValueError("Snapshot and update sizes differ")
        if len({c.coin.symbol for c in expected}) != len(expected):
            raise ValueError("Duplicate symbols in update")
        with self._lock:
            for before, after in zip(expected, cryptos, strict=True):
                if (
                    after.coin != before.coin
                    or after.record_id != before.record_id
                    or after.version != before.version + 1
                ):
                    raise ValueError("Invalid update version or identity")
                current = self._cryptos.get(before.coin.symbol)
                if current is None:
                    raise NotFound("Cryptocurrency is not tracked")
                if (current.record_id, current.version) != (before.record_id, before.version):
                    raise Conflict("Cryptocurrency changed during update; retry the request")
            self._cryptos.update({c.coin.symbol: c for c in cryptos})

    def delete(self, symbol: str) -> None:
        with self._lock:
            self.get(symbol)
            del self._cryptos[symbol]
