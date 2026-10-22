import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient

from app.api import create_app

pytestmark = pytest.mark.schedule


def test_defaults_and_trigger(authorized):
    schedule = authorized.get("/schedule").json()
    assert schedule["enabled"] is True and schedule["interval_seconds"] == 30
    assert schedule["last_update"] is None and schedule["next_update"].endswith("Z")
    assert authorized.post("/schedule/trigger").json()["updated_count"] == 0
    for symbol in ("BTC", "ETH"):
        assert authorized.post("/crypto", json={"symbol": symbol}).status_code == 201
    assert authorized.put("/schedule", json={"enabled": False, "interval_seconds": 60}).json() == {
        "enabled": False,
        "interval_seconds": 60,
    }
    assert authorized.get("/schedule").json()["next_update"] is None
    result = authorized.post("/schedule/trigger").json()
    assert result["updated_count"] == 2
    assert authorized.get("/schedule").json()["last_update"] == result["timestamp"]
    for symbol in ("BTC", "ETH"):
        assert len(authorized.get(f"/crypto/{symbol}/history").json()["history"]) == 2


@pytest.mark.parametrize("interval", [9, 3601, 10.5, "30", True, None])
def test_invalid_interval(authorized, interval):
    before = authorized.get("/schedule").json()
    response = authorized.put("/schedule", json={"enabled": True, "interval_seconds": interval})
    assert response.status_code == 400
    assert authorized.get("/schedule").json() == before


@pytest.mark.parametrize("enabled", [1, "true", None])
def test_invalid_enabled(authorized, enabled):
    assert (
        authorized.put("/schedule", json={"enabled": enabled, "interval_seconds": 30}).status_code
        == 400
    )


@pytest.mark.parametrize("interval", [10, 3600])
def test_interval_boundaries(authorized, interval):
    assert (
        authorized.put(
            "/schedule", json={"enabled": True, "interval_seconds": interval}
        ).status_code
        == 200
    )


def test_failed_trigger_is_atomic(authorized, provider):
    for symbol in ("BTC", "ETH"):
        authorized.post("/crypto", json={"symbol": symbol})
    provider.fail = True
    response = authorized.post("/schedule/trigger")
    assert response.status_code == 500
    assert authorized.get("/schedule").json()["last_update"] is None
    for symbol in ("BTC", "ETH"):
        assert len(authorized.get(f"/crypto/{symbol}/history").json()["history"]) == 1
    provider.fail = False
    assert authorized.post("/schedule/trigger").json()["updated_count"] == 2


def test_concurrent_triggers(authorized):
    authorized.post("/crypto", json={"symbol": "BTC"})
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: authorized.post("/schedule/trigger"), range(4)))
    assert all(r.json()["updated_count"] == 1 for r in responses)
    assert len(authorized.get("/crypto/BTC/history").json()["history"]) == 5


def test_real_thread_reconfigure_disable_shutdown(provider, credentials):
    app = create_app(provider=provider)
    with TestClient(app) as client:
        token = client.post("/auth/register", json=credentials).json()["token"]
        client.headers["Authorization"] = f"Bearer {token}"
        client.post("/crypto", json={"symbol": "BTC"})
        client.put("/schedule", json={"enabled": True, "interval_seconds": 10})
        deadline = time.monotonic() + 13
        while time.monotonic() < deadline:
            if len(client.get("/crypto/BTC/history").json()["history"]) >= 2:
                break
            time.sleep(0.05)
        else:
            pytest.fail("Real scheduler did not update within 13 seconds")
        assert client.get("/schedule").json()["last_update"] is not None
        client.put("/schedule", json={"enabled": False, "interval_seconds": 10})
        calls = provider.calls
        # A disabled worker ignores even an elapsed deadline.
        scheduler = app.state.scheduler
        with scheduler._condition:
            scheduler._deadline = time.monotonic() - 1
            scheduler._condition.notify_all()
        time.sleep(0.15)
        assert provider.calls == calls
    assert not scheduler._thread.is_alive()
    assert provider.closed


def test_worker_recovers_from_error(provider):
    app = create_app(provider=provider)
    service = app.state.service
    service.add("BTC")
    provider.fail = True
    scheduler = app.state.scheduler
    completed = Event()
    original = service.refresh_all

    def refresh():
        try:
            return original()
        finally:
            completed.set()

    service.refresh_all = refresh
    with TestClient(app):
        with scheduler._condition:
            scheduler._deadline = time.monotonic() - 1
            scheduler._condition.notify_all()
        assert completed.wait(2)
        assert len(service.get("BTC").history) == 1
        assert scheduler._thread.is_alive()
        provider.fail = False
        assert scheduler.trigger()["updated_count"] == 1
        assert len(service.get("BTC").history) == 2
