import secrets
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.domain import Coin, InvalidInput, ProviderError


class FakeProvider:
    def __init__(self):
        self.value = Decimal("45000.123456789123456789")
        self.fail = False
        self.calls = 0
        self.closed = False

    def resolve(self, symbol):
        if symbol not in ("BTC", "ETH"):
            raise InvalidInput("Unknown cryptocurrency symbol")
        return Coin(
            symbol,
            {"BTC": "bitcoin", "ETH": "ethereum"}[symbol],
            {"BTC": "Bitcoin", "ETH": "Ethereum"}[symbol],
        )

    def prices(self, ids):
        self.calls += 1
        if self.fail:
            raise ProviderError("Provider unavailable")
        return dict.fromkeys(ids, self.value)

    def close(self):
        self.closed = True


@pytest.fixture
def provider():
    return FakeProvider()


@pytest.fixture
def client(provider):
    app = create_app(provider=provider, start_scheduler=False)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def credentials():
    return {"username": "alice", "password": secrets.token_urlsafe(20)}


@pytest.fixture
def authorized(client, credentials):
    token = client.post("/auth/register", json=credentials).json()["token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client
