"""Integration smoke tests for the Railway Assistant Bot API."""

import os
import sys

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)


@pytest.fixture(scope="module")
def client():
    """Fast bootstrap (SQLite only) to keep tests fast."""
    import bootstrap
    from database import init_db

    original = bootstrap.run_bootstrap

    def fast_bootstrap(force: bool = False):
        init_db()

    bootstrap.run_bootstrap = fast_bootstrap

    from main import app

    with TestClient(app) as test_client:
        yield test_client

    bootstrap.run_bootstrap = original


def test_root_health(client):
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"


def test_chat_greeting(client):
    response = client.post("/api/chat", json={
        "message": "Hello",
        "session_id": "test-session-1",
        "history": [],
    })
    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "greeting"
    assert "response" in data


def test_add_pnr_watchlist(client):
    response = client.post("/api/pnr-watchlist", json={
        "pnr": "2145678901",
        "session_id": "test-session-watch",
    })
    assert response.status_code == 200
    data = response.json()
    assert data.get("success") is True
    assert data.get("pnr") == "2145678901"


def test_get_pnr_watchlist(client):
    client.post("/api/pnr-watchlist", json={
        "pnr": "2145678901",
        "session_id": "test-session-watch-2",
    })
    response = client.get("/api/pnr-watchlist/test-session-watch-2")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert any(item["pnr"] == "2145678901" for item in data)


def test_live_train_status(client):
    response = client.get("/api/live-train/12301")
    assert response.status_code == 200
    data = response.json()
    assert data["train_no"] == "12301"
    assert "current_station" in data
    assert "status" in data


def test_pnr_status_shape(client):
    response = client.post("/api/chat", json={
        "message": "Check PNR 2145678901",
        "session_id": "test-session-pnr",
        "history": [],
    })
    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "prs"
    assert "pnr_data" in data.get("raw_data", {})
    pnr_data = data["raw_data"]["pnr_data"]
    assert pnr_data["pnr"] == "2145678901"
    assert "booking_status" in pnr_data
