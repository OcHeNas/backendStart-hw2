from decimal import Decimal

import httpx
import pytest

from app.coingecko import CoinGecko
from app.config import Settings
from app.domain import InvalidInput, ProviderError

COINS = [{"id": "bitcoin", "symbol": "btc", "name": "Bitcoin"}]


def adapter(handler):
    client = httpx.Client(base_url="https://test/api/v3/", transport=httpx.MockTransport(handler))
    return CoinGecko(Settings(), client)


def test_mapping_cache_and_exact_prices():
    paths = []

    def handle(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/coins/list"):
            return httpx.Response(200, json=COINS)
        assert request.url.params["ids"] == "bitcoin"
        assert request.url.params["vs_currencies"] == "usd"
        return httpx.Response(200, text='{"bitcoin":{"usd":0.123456789123456789}}')

    with_provider = adapter(handle)
    assert with_provider.resolve("BTC").coin_id == "bitcoin"
    with_provider.resolve("BTC")
    assert with_provider.prices(["bitcoin"])["bitcoin"] == Decimal("0.123456789123456789")
    assert paths.count("/api/v3/coins/list") == 1
    with_provider.close()


def test_symbol_collision_search_ranking():
    def handle(request):
        if request.url.path.endswith("/coins/list"):
            return httpx.Response(
                200, json=COINS + [{"id": "other", "symbol": "btc", "name": "Other"}]
            )
        assert request.url.path.endswith("/search")
        return httpx.Response(
            200,
            json={
                "coins": [
                    {"id": "other", "symbol": "BTC", "name": "Other", "market_cap_rank": None},
                    {**COINS[0], "market_cap_rank": 1},
                ]
            },
        )

    provider = adapter(handle)
    assert provider.resolve("BTC").coin_id == "bitcoin"


def test_unknown_negative_cache_and_new_search_coin():
    paths = []

    def handle(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/coins/list"):
            return httpx.Response(200, json=[])
        return httpx.Response(
            200, json={"coins": COINS if request.url.params["query"] == "BTC" else []}
        )

    provider = adapter(handle)
    assert provider.resolve("BTC").name == "Bitcoin"
    for _ in range(2):
        with pytest.raises(InvalidInput):
            provider.resolve("NOTREAL")
    assert paths.count("/api/v3/search") == 2


@pytest.mark.parametrize(
    "body",
    [
        "{}",
        '{"bitcoin":{"usd":null}}',
        '{"bitcoin":{"usd":true}}',
        '{"bitcoin":{"usd":-1}}',
        '{"bitcoin":{"usd":"1"}}',
        '{"bitcoin":{"usd":NaN}}',
        "broken",
        "[]",
    ],
)
def test_invalid_price(body):
    provider = adapter(lambda _: httpx.Response(200, text=body))
    with pytest.raises(ProviderError):
        provider.prices(["bitcoin"])


@pytest.mark.parametrize("status", [401, 429, 500])
def test_http_failure(status):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(status, headers={"Retry-After": "60"})

    provider = adapter(handle)
    with pytest.raises(ProviderError):
        provider.prices(["bitcoin"])
    assert len(calls) == (2 if status == 500 else 1)
    if status == 429:
        with pytest.raises(ProviderError):
            provider.prices(["bitcoin"])
        assert len(calls) == 1


def test_timeout_retry():
    calls = []

    def handle(request):
        calls.append(request)
        raise httpx.ReadTimeout("timeout", request=request)

    with pytest.raises(ProviderError):
        adapter(handle).prices(["bitcoin"])
    assert len(calls) == 2


def test_retry_recovery():
    calls = []

    def handle(request):
        calls.append(request)
        return (
            httpx.Response(503)
            if len(calls) == 1
            else httpx.Response(200, json={"bitcoin": {"usd": 1}})
        )

    assert adapter(handle).prices(["bitcoin"]) == {"bitcoin": Decimal(1)}


def test_cache_expiry():
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=COINS)

    provider = adapter(handle)
    provider.resolve("BTC")
    provider._expires = 0
    provider._resolved.clear()
    provider.resolve("BTC")
    assert len(calls) == 2


def test_batching_and_missing_quote():
    sizes = []

    def handle(request):
        ids = request.url.params["ids"].split(",")
        sizes.append(len(ids))
        return httpx.Response(200, json={i: {"usd": 1} for i in ids})

    provider = adapter(handle)
    assert len(provider.prices([str(i) for i in range(401)])) == 401
    assert sizes == [200, 200, 1]


@pytest.mark.parametrize("body", [{}, [1], [{"id": 1, "symbol": "btc", "name": "Bitcoin"}]])
def test_invalid_coin_metadata(body):
    with pytest.raises(ProviderError):
        adapter(lambda _: httpx.Response(200, json=body)).resolve("BTC")


def test_live_catalog_empty_symbols_do_not_break_other_coins():
    provider = adapter(
        lambda _: httpx.Response(
            200, json=COINS + [{"id": "unlisted-symbol", "symbol": "", "name": "No ticker"}]
        )
    )
    assert provider.resolve("BTC").coin_id == "bitcoin"
