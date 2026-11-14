from app.services import usda
from tests.conftest import select


def test_index_and_static(client):
    r = client.get("/")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "FieldWise" in html and "maplibre-gl@4.7.1" in html
    assert "test-key" not in html and "1x0000000000000000000000000000000AA" not in html  # secrets never rendered
    assert client.get("/static/css/styles.css").status_code == 200
    for js in ("api", "map", "recommendations", "main"):
        assert client.get(f"/static/js/{js}.js").status_code == 200


def test_crop_at_corn_and_year_consistency(client, fake_usda):
    r = select(client)
    assert r.status_code == 200
    d = r.get_json()
    assert d["supported"] is True
    assert d["classification"]["official_name"] == "Corn"
    assert "Mapped crop coverage—not a property boundary." in d["statements"]
    assert "Current planting and field conditions are not verified." in d["statements"]
    recs = client.post("/api/recommendations", json={"selection_token": d["selection_token"]}).get_json()
    assert d["dataset"]["year"] == recs["dataset_year"] == 2025
    assert recs["recommendation_ids"]


def test_wheat_subtype_preserved(client, fake_usda):
    fake_usda["code"] = 23
    d = select(client).get_json()
    assert d["classification"]["subtype"] == "Spring wheat"
    recs = client.post("/api/recommendations", json={"selection_token": d["selection_token"]}).get_json()
    assert recs["crop"] == "wheat" and recs["official_name"] == "Spring Wheat"


def test_unsupported_crop_and_double_crop(client, fake_usda):
    fake_usda["code"] = 5
    d = select(client).get_json()
    assert d["supported"] is False and d["selection_token"] is None and "Soybeans" in d["message"]
    fake_usda["code"] = 225
    d = select(client).get_json()
    assert d["supported"] is False and "double-crop" in d["message"]
    fake_usda["code"] = None
    d = select(client).get_json()
    assert d["supported"] is False and "No classification" in d["message"]


def test_invalid_coordinates(client, fake_usda):
    assert client.post("/api/crop-at", json={"lat": 999, "lon": 0}).status_code == 422
    assert client.post("/api/crop-at", json={"lat": "x", "lon": 0}).status_code == 422
    assert client.post("/api/crop-at", json={"lat": 1}).status_code == 422
    assert client.post("/api/crop-at", json={"lat": 1, "lon": 2, "extra": 3}).status_code == 422
    r = client.post("/api/crop-at", json={"lat": 21.3, "lon": -157.8})  # Hawaii
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "unsupported_geography"


def test_request_size_limit(client):
    r = client.post("/api/crop-at", data="x" * 20000, content_type="application/json")
    assert r.status_code == 413


def test_invalid_tiles(client, fake_usda):
    assert client.get("/api/tiles/corn/2/0/0.png").status_code == 400
    assert client.get("/api/tiles/corn/6/999/0.png").status_code == 400
    assert client.get("/api/tiles/soy/6/0/0.png").status_code == 404
    assert client.get("/api/outlines/10/0/0.json").status_code == 400


def test_usda_failure_returns_clear_error(client, fake_usda, monkeypatch):
    from app.errors import UpstreamError

    def down(*a, **k):
        raise UpstreamError("usda_unavailable", "The USDA Cropland Data Layer service did not respond.")

    monkeypatch.setattr(usda, "identify", down)
    r = select(client)
    assert r.status_code == 502
    assert r.get_json()["error"]["code"] == "usda_unavailable"


def test_census_failure_still_returns_classification(client, fake_usda):
    fake_usda["loc"] = None
    d = select(client).get_json()
    assert d["supported"] is True and d["location"]["county"] is None and d["location"]["note"]
    recs = client.post("/api/recommendations", json={"selection_token": d["selection_token"]}).get_json()
    assert "RC-02-mccc-selector" not in recs["recommendation_ids"]  # state unknown -> geo rule omitted


def test_forged_selection_token_rejected(client):
    r = client.post("/api/recommendations", json={"selection_token": "forged-token-value"})
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "invalid_selection"


def test_search(client):
    d = client.get("/api/search?q=Ames, IA").get_json()
    assert d["results"][0]["label"] == "Ames, IA"
    d = client.get("/api/search?q=50010").get_json()
    assert d["results"][0]["label"] == "ZIP 50010"
    assert client.get("/api/search?q=" + "a" * 100).status_code == 400
    assert client.get("/api/search?q=a").get_json()["results"] == []
    assert client.get("/api/search?q=Honolulu").get_json()["results"] == []  # outside CONUS


def test_json_error_shape_for_unknown_api_route(client):
    r = client.get("/api/nope")
    assert r.status_code == 404 and "error" in r.get_json()


def test_missing_secret_key_falls_back_to_shared_key(tmp_path):
    from app import _shared_fallback_secret

    key_file = tmp_path / "secret_key"
    first = _shared_fallback_secret(key_file)    # first worker creates the key
    second = _shared_fallback_secret(key_file)   # other workers read the same key
    assert first == second and len(first) == 64
