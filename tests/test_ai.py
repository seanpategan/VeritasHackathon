import json

import pytest

from app.routes import ai as ai_route
from app.services import ai_provider, turnstile
from tests.conftest import select

IDS = ["SH-01-soil-test", "WE-01-soil-moisture-monitoring"]


def good_output(ids=IDS, **override):
    data = {
        "overview": "These suggestions are general practices worth investigating for a mapped corn area.",
        "explanations": [
            {"recommendation_id": i, "plain_language": "This suggestion asks whether a check is useful here.",
             "tradeoffs": "It takes some time and effort, with possible long-term benefits.",
             "uncertainty": "Field conditions were not observed, so suitability is unknown."} for i in ids
        ],
        "reported_practices_review": "No practices were reported, so this audit stays general for this crop.",
        "additional_considerations": [
            {"title": "Consider field drainage", "category": "soil_health",
             "detail": "Drainage can affect planting timing and soil structure in many corn areas.",
             "why_relevant": "The area was classified as corn in a region where drainage is common."},
        ],
        "questions_for_adviser": ["Which cover crop species tend to suit this county?"],
        "verify_summary": ["Check existing practices with a local adviser."],
    }
    data.update(override)
    return json.dumps(data)


def test_validate_accepts_good_output_and_restores_order():
    out = ai_provider.validate_output(good_output(list(reversed(IDS))), IDS)
    assert [e.recommendation_id for e in out.explanations] == IDS


@pytest.mark.parametrize("bad", [
    "not json",
    json.dumps({"overview": "x" * 20}),
    good_output(IDS + ["XX-99-invented"]),
    good_output(IDS[:1]),
    good_output(IDS + IDS[:1]),
    good_output(overview="See https://example.com for details about this area."),
    good_output(overview="Cover crops will increase yields on this land for sure."),
    good_output(overview="Expect roughly 15% more organic matter after three years."),
    good_output(overview="This could save $40 per acre in the first season alone."),
    good_output(overview="Apply 120 lbs of nitrogen per acre before planting corn."),
    good_output(overview="This field has poor drainage and needs tile installed soon."),
    good_output(additional_considerations=[{"title": "Weed control", "category": "other",
        "detail": "Spray atrazine before planting to control weeds early in the season.", "why_relevant": "Corn area."}]),
    good_output(additional_considerations=[{"title": "Cover crops", "category": "rotation_cover_crops",
        "detail": "Research shows cover crops help in nearly every system nationwide.", "why_relevant": "Corn area."}]),
    good_output(additional_considerations=[{"title": "Something", "category": "made_up_category",
        "detail": "A detail that is long enough to pass length checks.", "why_relevant": "Corn area here."}]),
    good_output(additional_considerations=[{"title": "Item number", "category": "other",
        "detail": "A detail that is long enough to pass length checks.", "why_relevant": "Corn area here."}] * 6),
    good_output(questions_for_adviser=["See www.example.org for the right cover crop mix?"]),
    good_output(reported_practices_review="Irrigate 1.5 inches every week during tasseling."),
])
def test_validate_rejects_invalid_or_unsupported(bad):
    with pytest.raises(ai_provider.AIOutputRejected):
        ai_provider.validate_output(bad, IDS)


def test_schema_enumerates_only_existing_ids():
    schema = ai_provider.output_schema(IDS)
    enum = schema["properties"]["explanations"]["items"]["properties"]["recommendation_id"]["enum"]
    assert enum == IDS and schema["additionalProperties"] is False
    cats = schema["properties"]["additional_considerations"]["items"]["properties"]["category"]["enum"]
    assert cats == ai_provider.CATEGORIES


def test_audit_extras_parsed():
    out = ai_provider.validate_output(good_output(), IDS)
    assert out.additional_considerations[0].category == "soil_health"
    assert out.questions_for_adviser and out.reported_practices_review


class FakeProvider:
    calls = 0

    def __init__(self, fail=False):
        self.fail = fail

    def explain(self, user_text, rec_ids):
        FakeProvider.calls += 1
        assert "selection" in user_text and "approved_source_excerpts" in user_text
        assert "lat" not in json.loads(user_text.split("<context>\n")[1].split("\n</context>")[0])["selection"]
        if self.fail:
            raise ai_provider.AIUnavailable("ai_failed", "AI explanation unavailable (test).")
        return ai_provider.AIResult(ai_provider.validate_output(good_output(rec_ids), rec_ids), "fake-model", 1)


@pytest.fixture
def ts_ok(monkeypatch):
    monkeypatch.setattr(turnstile, "verify", lambda token, secret, ip=None, timeout=6.0: (True, "ok"))


def _token(client):
    return select(client).get_json()["selection_token"]


def test_explain_success_and_cache(client, fake_usda, ts_ok, monkeypatch):
    FakeProvider.calls = 0
    monkeypatch.setattr(ai_route, "get_provider", lambda: FakeProvider())
    tok = _token(client)
    r = client.post("/api/audit", json={"selection_token": tok, "turnstile_token": "t"})
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    recs = client.post("/api/recommendations", json={"selection_token": tok}).get_json()
    assert [e["recommendation_id"] for e in d["explanation"]["explanations"]] == recs["recommendation_ids"]
    assert d["dataset_year"] == 2025 and d["cached"] is False
    r2 = client.post("/api/audit", json={"selection_token": tok, "turnstile_token": "t"})
    assert r2.get_json()["cached"] is True and FakeProvider.calls == 1
    assert "NOT from FieldWise's verified" in d["disclaimer"]
    assert d["explanation"]["additional_considerations"] and d["explanation"]["questions_for_adviser"]


def test_explain_provider_failure_keeps_recommendations(client, fake_usda, ts_ok, monkeypatch):
    monkeypatch.setattr(ai_route, "get_provider", lambda: FakeProvider(fail=True))
    tok = _token(client)
    r = client.post("/api/audit", json={"selection_token": tok, "turnstile_token": "t"})
    assert r.status_code == 503 and r.get_json()["error"]["code"] == "ai_failed"
    assert client.post("/api/recommendations", json={"selection_token": tok}).status_code == 200


def test_turnstile_failure_blocks_ai(client, fake_usda, monkeypatch):
    monkeypatch.setattr(turnstile, "verify", lambda token, secret, ip=None, timeout=6.0: (False, "turnstile_failed"))
    monkeypatch.setattr(ai_route, "get_provider", lambda: pytest.fail("provider must not be called"))
    r = client.post("/api/audit", json={"selection_token": _token(client), "turnstile_token": "bad"})
    assert r.status_code == 403 and r.get_json()["error"]["code"] == "turnstile_failed"


def test_disabled_ai(client, app, fake_usda):
    app.config["AI_ENABLED"] = False
    r = client.post("/api/audit", json={"selection_token": _token(client), "turnstile_token": "t"})
    assert r.status_code == 503 and r.get_json()["error"]["code"] == "ai_disabled"
    assert client.get("/api/ai/status").get_json()["available"] is False


def test_missing_api_key(client, app, fake_usda):
    app.config["ANTHROPIC_API_KEY"] = ""
    r = client.post("/api/audit", json={"selection_token": _token(client), "turnstile_token": "t"})
    assert r.get_json()["error"]["code"] == "ai_not_configured"


def test_ai_rate_limit(client, fake_usda, ts_ok, monkeypatch):
    monkeypatch.setattr(ai_route, "get_provider", lambda: FakeProvider())
    tok = _token(client)
    codes = [client.post("/api/audit", json={"selection_token": tok, "turnstile_token": "t"}).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3] == 429
    r = client.post("/api/audit", json={"selection_token": tok, "turnstile_token": "t"})
    assert r.get_json()["error"]["code"] == "rate_limited"


class FakeResp:
    def __init__(self, data, status=200):
        self.data, self.status = data, status

    def raise_for_status(self):
        if self.status >= 400:
            import requests

            raise requests.HTTPError("x")

    def json(self):
        return self.data


def test_turnstile_server_verification(monkeypatch):
    import requests

    sent = {}

    def post(url, data, timeout):
        sent.update(data)
        return FakeResp({"success": data["response"] == "good"})

    monkeypatch.setattr(requests, "post", post)
    assert turnstile.verify("good", "secret", "1.2.3.4") == (True, "ok")
    assert sent["secret"] == "secret" and sent["remoteip"] == "1.2.3.4"
    assert turnstile.verify("bad", "secret") == (False, "turnstile_failed")
    assert turnstile.verify("", "secret") == (False, "turnstile_missing")
    assert turnstile.verify("good", "") == (False, "turnstile_not_configured")

    def down(*a, **k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(requests, "post", down)
    assert turnstile.verify("good", "secret") == (False, "turnstile_unavailable")
