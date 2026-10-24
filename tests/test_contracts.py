import pytest

from app.config import Settings
from app.schemas import (
    CryptoEnvelope,
    CryptoListResponse,
    CryptoResponse,
    EmptyResponse,
    HistoryResponse,
    ScheduleResponse,
    StatsResponse,
    TriggerResponse,
)


def test_wire_response_models(authorized):
    response = authorized.post("/crypto", json={"symbol": "BTC"})
    CryptoEnvelope.model_validate_json(response.text)
    for path, model in [
        ("/crypto", CryptoListResponse),
        ("/crypto/BTC", CryptoResponse),
        ("/crypto/BTC/history", HistoryResponse),
        ("/crypto/BTC/stats", StatsResponse),
        ("/schedule", ScheduleResponse),
    ]:
        model.model_validate_json(authorized.get(path).text)
    TriggerResponse.model_validate_json(authorized.post("/schedule/trigger").text)
    EmptyResponse.model_validate_json(authorized.delete("/crypto/BTC").text)


def test_openapi(client):
    schema = client.get("/openapi.json").json()
    assert (
        schema["components"]["schemas"]["CryptoResponse"]["properties"]["current_price"]["type"]
        == "number"
    )
    assert schema["paths"]["/crypto"]["get"]["security"] == [{"HTTPBearer": []}]
    assert "422" not in schema["paths"]["/auth/register"]["post"]["responses"]
    assert "400" in schema["paths"]["/auth/register"]["post"]["responses"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"jwt_secret": "short"},
        {"jwt_ttl": 0},
        {"cache_ttl": 0},
        {"http_timeout": -1},
        {"coingecko_key_header": "bad"},
    ],
)
def test_invalid_settings(kwargs):
    with pytest.raises(ValueError):
        Settings(**kwargs)


def test_password_salts():
    import secrets

    from app.security import hash_password, verify_password

    password = secrets.token_urlsafe(20)
    first, second = hash_password(password), hash_password(password)
    assert first != second
    assert verify_password(password, first) and verify_password(password, second)
