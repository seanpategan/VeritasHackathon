import json

import pytest

from app.rules import engine
from app.rules.engine import Inputs

CORN_IA = Inputs(crop="corn", official_name="Corn", subtype=None, year=2025, state_abbr="IA", state_name="Iowa")
WHEAT_WA = Inputs(crop="wheat", official_name="Winter Wheat", subtype="Winter wheat", year=2025, state_abbr="WA", state_name="Washington")


def test_identical_inputs_identical_output_and_order():
    a = engine.generate(CORN_IA)
    b = engine.generate(CORN_IA)
    assert json.dumps(a, sort_keys=False) == json.dumps(b, sort_keys=False)
    assert a["recommendation_ids"] == b["recommendation_ids"]


def test_category_order_is_fixed():
    out = engine.generate(CORN_IA)
    cats = [g["category"] for g in out["groups"]]
    assert cats == ["soil_health", "water_efficiency", "rotation_cover_crops"]
    ids = out["recommendation_ids"]
    assert ids.index("SH-01-soil-test") < ids.index("SH-02-reduce-tillage") < ids.index("WE-01-soil-moisture-monitoring")


def test_stable_order_within_category():
    out = engine.generate(CORN_IA)
    for g in out["groups"]:
        orders = [r["id"] for r in g["recommendations"]]
        rules = {r["id"]: r for r in engine.load_ruleset()["rules"]}
        assert orders == sorted(orders, key=lambda i: (rules[i]["display_order"], i))


def test_unsupported_crop_raises():
    with pytest.raises(engine.UnsupportedCrop):
        engine.generate(Inputs(crop="soybeans", official_name="Soybeans", subtype=None, year=2025))


def test_missing_prerequisites_are_conditional_not_asserted():
    out = engine.generate(CORN_IA)
    recs = {r["id"]: r for g in out["groups"] for r in g["recommendations"]}
    irr = recs["WE-01-soil-moisture-monitoring"]
    assert irr["conditional"] is True
    assert irr["conditional_prefix"].startswith("If this area is irrigated")
    assert "The area is irrigated" in irr["unverified_prerequisites"]
    # supporting observations contain only verified facts, never the missing prerequisite
    for obs in irr["supporting_observations"]:
        assert "irrigated" not in obs.lower()


def test_geographic_scope_rule_requires_known_state():
    ia_ids = engine.generate(CORN_IA)["recommendation_ids"]
    wa_ids = engine.generate(WHEAT_WA)["recommendation_ids"]
    unknown = engine.generate(Inputs(crop="corn", official_name="Corn", subtype=None, year=2025))["recommendation_ids"]
    assert "RC-02-mccc-selector" in ia_ids
    assert "RC-02-mccc-selector" not in wa_ids
    assert "RC-02-mccc-selector" not in unknown


def test_dataset_year_flows_into_observations():
    out = engine.generate(Inputs(crop="wheat", official_name="Spring Wheat", subtype="Spring wheat", year=2031))
    assert out["dataset_year"] == 2031
    for g in out["groups"]:
        for r in g["recommendations"]:
            assert "2031 USDA Cropland Data Layer" in r["supporting_observations"][0]
            assert "Spring Wheat" in r["supporting_observations"][0]


def test_case_studies_filtered_by_crop_and_no_case_note():
    corn = engine.generate(CORN_IA)
    for g in corn["groups"]:
        for r in g["recommendations"]:
            for cs in r["case_studies"]:
                assert "corn" in cs["crops"]
            if not r["case_studies"]:
                assert r["case_study_note"] == "No verified case study included for this recommendation."
    wheat = engine.generate(WHEAT_WA)
    tillage = next(r for g in wheat["groups"] for r in g["recommendations"] if r["id"] == "SH-02-reduce-tillage")
    assert "cs-upton-il" not in [c["id"] for c in tillage["case_studies"]]  # corn-only profile
    assert "cs-emmons-ok" in [c["id"] for c in tillage["case_studies"]]


def test_source_and_case_study_lookup():
    assert engine.get_source("psu-no-till-soil")["publisher"].startswith("Penn State")
    assert engine.get_case_study("cs-brandt-oh")["source_url"].startswith("https://www.sare.org/")
    with pytest.raises(KeyError):
        engine.get_source("does-not-exist")


def test_cost_effort_levels_are_qualitative():
    allowed = {"Low", "Moderate", "High", "Depends on field conditions", "Requires local assessment"}
    for rule in engine.load_ruleset()["rules"]:
        assert rule["cost_effort"]["level"] in allowed
