"""Shared fixtures. All external services are mocked here; mock data never reaches the real UI."""
from __future__ import annotations

import pytest

from app import create_app
from app.config import TestConfig
from app.services import usda
from app.services.usda import DatasetInfo

FAKE_DS = DatasetInfo(
    year=2025, raster_id=40, raster_name="2025_10m_cdls", resolution_m=10,
    checked_at="2026-11-14T00:00:00Z", status="live", status_note="test",
)

FAKE_REGION = {
    "available": True,
    "geometry": {"type": "Polygon", "coordinates": [[[-93.0, 42.0], [-93.0, 42.01], [-92.99, 42.01], [-93.0, 42.0]]]},
    "clipped": False,
    "mapped_area": {"hectares": 10.0, "acres": 24.7},
    "pixel_count": 1000,
    "window_km": 5.1,
    "notes": ["test"],
}


@pytest.fixture
def app(tmp_path):
    class Cfg(TestConfig):
        CACHE_DIR = str(tmp_path / "cache")
        RATELIMIT_AI = "3 per minute"
        RATELIMIT_LOOKUP = "100 per minute"

    application = create_app(Cfg)
    yield application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def fake_usda(monkeypatch):
    """Mock the USDA + Census services. Returns a dict to control the identified class code."""
    state = {"code": 1, "loc": {"state": "Iowa", "state_abbr": "IA", "county": "Story County", "source": "test"}}
    monkeypatch.setattr(usda, "get_dataset", lambda timeout=15.0: FAKE_DS)
    monkeypatch.setattr(usda, "identify", lambda lon, lat, ds, timeout=20.0: state["code"])
    monkeypatch.setattr(usda, "region_at", lambda lon, lat, code, ds, cache: FAKE_REGION)
    monkeypatch.setattr(usda, "class_name", lambda code: {5: "Soybeans", 111: "Open Water"}.get(code))
    from app.services import geocoding

    monkeypatch.setattr(geocoding, "approximate_location", lambda lon, lat, timeout=6.0: state["loc"])
    return state


def select(client, lat=42.05, lon=-93.55):
    resp = client.post("/api/crop-at", json={"lat": lat, "lon": lon})
    return resp
