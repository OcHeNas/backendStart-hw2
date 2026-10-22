import json
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal

import jwt
import pytest

from app.domain import utcnow

PROTECTED = [
    ("GET", "/crypto"),
    ("POST", "/crypto"),
    ("GET", "/crypto/BTC"),
    ("PUT", "/crypto/BTC/refresh"),
    ("GET", "/crypto/BTC/history"),
    ("GET", "/crypto/BTC/stats"),
    ("DELETE", "/crypto/BTC"),
    ("GET", "/schedule"),
    ("PUT", "/schedule"),
    ("POST", "/schedule/trigger"),
]


@pytest.mark.parametrize("method,path", PROTECTED)
def test_protected(client, method, path):
    response = client.request(method, path)
    assert response.status_code == 401
    assert set(response.json()) == {"error"}
    assert response.headers["www-authenticate"] == "Bearer"


def test_register_login(client, credentials):
    response = client.post("/auth/register", json=credentials)
    assert response.status_code == 201
    token = response.json()["token"]
    assert len(token.split(".")) == 3
    encoded = client.app.state.auth.users.get_hash(credentials["username"])
    assert encoded.startswith("scrypt$") and credentials["password"] not in encoded
    assert client.post("/auth/register", json=credentials).status_code == 409
    assert client.post("/auth/login", json=credentials).status_code == 200
    wrong = {**credentials, "password": secrets.token_urlsafe(20)}
    assert client.post("/auth/login", json=wrong).status_code == 401
    assert (
        client.post("/auth/login", json={**credentials, "username": "missing"}).status_code == 401
    )


@pytest.mark.parametrize(
    "body",
    [
        {},
        [],
        {"username": "a"},
        {"username": "", "password": "x"},
        {"username": " a", "password": "x"},
        {"username": "a", "password": ""},
        {"username": 12, "password": "x"},
        {"username": "a", "password": 12},
        {"username": "a", "password": "x", "extra": 1},
    ],
)
@pytest.mark.parametrize("path", ["/auth/register", "/auth/login"])
def test_invalid_credentials(client, body, path):
    response = client.post(path, json=body)
    assert response.status_code == 400
    assert set(response.json()) == {"error"}


def test_bad_json(client):
    response = client.post(
        "/auth/register", content="{", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400
    assert set(response.json()) == {"error"}


@pytest.mark.parametrize(
    "kind", ["expired", "wrong_key", "none", "missing_exp", "unknown_user", "malformed"]
)
def test_invalid_jwt(authorized, kind):
    auth = authorized.app.state.auth
    claims = {
        "sub": "alice",
        "iat": utcnow(),
        "exp": utcnow() + timedelta(hours=1),
        "iss": "cryptoserver",
        "aud": "cryptoserver",
    }
    if kind == "expired":
        claims["exp"] = utcnow() - timedelta(seconds=5)
    if kind == "missing_exp":
        del claims["exp"]
    if kind == "unknown_user":
        claims["sub"] = "missing"
    key = secrets.token_urlsafe(48) if kind == "wrong_key" else auth.secret
    token = jwt.encode(
        claims, "" if kind == "none" else key, algorithm="none" if kind == "none" else "HS256"
    )
    if kind == "malformed":
        token = "broken"
    response = authorized.get("/crypto", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_crud_and_decimal(authorized, provider):
    client = authorized
    assert client.get("/crypto").json() == {"cryptos": []}
    response = client.post("/crypto", json={"symbol": "btc"})
    assert response.status_code == 201
    data = json.loads(response.text, parse_float=Decimal)["crypto"]
    assert data["symbol"] == "BTC" and data["name"] == "Bitcoin"
    assert data["current_price"] == provider.value
    assert data["last_updated"].endswith("Z")
    assert client.post("/crypto", json={"symbol": "BTC"}).status_code == 409
    assert client.get("/crypto/btc").status_code == 200
    assert len(client.get("/crypto").json()["cryptos"]) == 1
    original = provider.value
    provider.value += Decimal("1000")
    assert client.put("/crypto/BTC/refresh").status_code == 200
    stats = json.loads(client.get("/crypto/BTC/stats").text, parse_float=Decimal)["stats"]
    assert stats["records_count"] == 2
    assert stats["min_price"] == original
    assert stats["max_price"] == provider.value
    assert stats["avg_price"] == original + Decimal("500")
    assert stats["price_change"] == 1000
    history = client.get("/crypto/BTC/history").json()["history"]
    assert len(history) == 2 and history[0]["timestamp"] <= history[1]["timestamp"]
    assert client.delete("/crypto/btc").json() == {}
    assert client.get("/crypto/BTC").status_code == 404
    assert client.post("/crypto", json={"symbol": "BTC"}).status_code == 201
    assert len(client.get("/crypto/BTC/history").json()["history"]) == 1


@pytest.mark.parametrize("method,path", PROTECTED[2:7])
def test_missing_crypto(authorized, method, path):
    response = authorized.request(method, path)
    assert response.status_code == 404
    assert set(response.json()) == {"error"}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"symbol": ""},
        {"symbol": "???"},
        {"symbol": 1},
        {"symbol": "NO_SUCH_COIN"},
        {"symbol": "BTC", "name": "x"},
    ],
)
def test_invalid_coin(authorized, body):
    assert authorized.post("/crypto", json=body).status_code == 400


def test_failure_preserves_data(authorized, provider):
    authorized.post("/crypto", json={"symbol": "BTC"})
    before = authorized.get("/crypto/BTC/history").json()
    provider.fail = True
    assert authorized.put("/crypto/BTC/refresh").status_code == 500
    assert authorized.post("/crypto", json={"symbol": "ETH"}).status_code == 500
    assert authorized.get("/crypto/BTC/history").json() == before
    assert len(authorized.get("/crypto").json()["cryptos"]) == 1


def test_history_bound_and_stats(authorized, provider):
    provider.value = Decimal(0)
    authorized.post("/crypto", json={"symbol": "BTC"})
    stats = authorized.get("/crypto/BTC/stats").json()["stats"]
    assert stats["price_change_percent"] is None
    for value in range(1, 106):
        provider.value = Decimal(value)
        assert authorized.put("/crypto/BTC/refresh").status_code == 200
    history = authorized.get("/crypto/BTC/history").json()["history"]
    assert len(history) == 100
    assert history[0]["price"] == 6 and history[-1]["price"] == 105
    stats = authorized.get("/crypto/BTC/stats").json()["stats"]
    assert stats == dict(
        min_price=6,
        max_price=105,
        avg_price=55.5,
        price_change=99,
        price_change_percent=1650,
        records_count=100,
    )


def test_concurrent_add_refresh_delete(authorized):
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(
            pool.map(lambda _: authorized.post("/crypto", json={"symbol": "BTC"}), range(8))
        )
    assert sorted(r.status_code for r in responses) == [201] + [409] * 7
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: authorized.put("/crypto/BTC/refresh"), range(20)))
    assert all(r.status_code == 200 for r in responses)
    assert len(authorized.get("/crypto/BTC/history").json()["history"]) == 21
    with ThreadPoolExecutor(max_workers=2) as pool:
        refresh = pool.submit(authorized.put, "/crypto/BTC/refresh")
        delete = pool.submit(authorized.delete, "/crypto/BTC")
        assert refresh.result().status_code in (200, 404)
        assert delete.result().status_code == 200
    assert authorized.get("/crypto/BTC").status_code == 404


def test_concurrent_register(client, credentials):
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(
            pool.map(lambda _: client.post("/auth/register", json=credentials), range(4))
        )
    assert sorted(r.status_code for r in responses) == [201, 409, 409, 409]


def test_shared_tracking_and_http_errors(authorized, credentials):
    authorized.post("/crypto", json={"symbol": "BTC"})
    token = authorized.post("/auth/register", json={**credentials, "username": "bob"}).json()[
        "token"
    ]
    assert (
        authorized.get("/crypto/BTC", headers={"Authorization": f"Bearer {token}"}).status_code
        == 200
    )
    assert authorized.get("/missing").json() == {"error": "Not Found"}
    assert authorized.patch("/crypto").status_code == 405
    assert authorized.get("/health").json() == {"status": "ok"}
