import json
import re
from pathlib import Path

from app.rules import engine
from app.services import usda

DATA = Path(__file__).resolve().parent.parent / "app" / "data"


def test_rule_fields_and_references():
    rs = engine.load_ruleset()
    sources = engine.load_sources()
    cases = engine.load_case_studies()
    required = {"id", "version", "category", "display_order", "crops", "geographic_scope", "prerequisites", "trigger",
                "content", "cost_effort", "source_ids", "case_study_ids", "limitations", "verify_before_acting"}
    ids = set()
    for rule in rs["rules"]:
        assert required <= set(rule), rule["id"]
        assert rule["id"] not in ids
        ids.add(rule["id"])
        assert rule["category"] in rs["category_order"]
        assert rule["source_ids"], f"{rule['id']} must cite at least one source"
        for sid in rule["source_ids"]:
            assert sid in sources
        for cid in rule["case_study_ids"]:
            assert cid in cases
        for crop in rule["crops"]:
            assert crop in rule["content"]["general_context"]


def test_sources_and_cases_have_https_urls_and_dates():
    for s in engine.load_sources().values():
        assert s["url"].startswith("https://") and "placeholder" not in s["url"]
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", s["verified_on"])
        for k in ("title", "publisher", "supported_claim", "scope"):
            assert s[k]
    for c in engine.load_case_studies().values():
        assert c["source_url"].startswith("https://") and "placeholder" not in c["source_url"]
        for k in ("name", "practices", "region", "summary", "applicability_limits"):
            assert c[k]


def test_rule_text_avoids_prohibited_language():
    text = json.dumps(engine.load_ruleset()).lower()
    for phrase in ["will increase yield", "this field has", "you are overwatering", "will be profitable", "lbs/acre", "lb/ac"]:
        assert phrase not in text


def test_manifest_required_fields():
    m = usda.MANIFEST
    for k in ("dataset_title", "official_source_url", "integration", "geographic_coverage", "categories",
              "known_limitations", "fallback", "last_verified"):
        assert k in m
    assert m["integration"]["service_endpoint"].startswith("https://")
    assert m["last_verified"]["checked_at"]


def test_bookmarks_are_verified_records():
    bm = json.loads((DATA / "bookmarks.json").read_text())["bookmarks"]
    assert len(bm) >= 3
    for b in bm:
        assert usda.in_conus(b["lon"], b["lat"])
        assert b["expected_code"] in usda.CROP_CODES
        assert b["verified_year"] and b["verified_at"]
