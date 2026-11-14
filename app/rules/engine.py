"""Deterministic recommendation engine.

Same validated inputs + same ruleset version -> same recommendations in the same order.
Inputs are limited to: verified crop, subtype, dataset year, and (for geographically scoped
rules only) the state. Nothing about soil, irrigation, fertilizer, rotation, yield, budget or
practices is assumed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
NO_CASE_STUDY = "No verified case study included for this recommendation."
SUPPORTED_CROPS = ("corn", "wheat")


@lru_cache(maxsize=1)
def load_ruleset() -> dict:
    return json.loads((DATA / "recommendation_rules.json").read_text())


@lru_cache(maxsize=1)
def load_sources() -> dict[str, dict]:
    return {s["id"]: s for s in json.loads((DATA / "sources.json").read_text())["sources"]}


@lru_cache(maxsize=1)
def load_case_studies() -> dict[str, dict]:
    return {c["id"]: c for c in json.loads((DATA / "case_studies.json").read_text())["case_studies"]}


@lru_cache(maxsize=1)
def load_questions() -> dict:
    return json.loads((DATA / "context_questions.json").read_text())


def question_index() -> dict[str, dict]:
    return {q["id"]: {"label": q["label"], "options": {o["value"]: o["label"] for o in q["options"]}}
            for q in load_questions()["questions"]}


class InvalidContext(ValueError):
    pass


def normalize_context(raw: dict | None) -> tuple[tuple[str, str], ...]:
    """Validate user-reported answers against the fixed dropdown options. 'unknown' answers are dropped.
    Returns a sorted tuple so identical answers always give identical (hashable) inputs."""
    if not raw:
        return ()
    if not isinstance(raw, dict):
        raise InvalidContext("context must be an object")
    idx = question_index()
    out = []
    for key, value in raw.items():
        if key not in idx:
            raise InvalidContext(f"unknown question: {key}")
        if not isinstance(value, str) or value not in idx[key]["options"]:
            raise InvalidContext(f"invalid answer for {key}")
        if value != "unknown":
            out.append((key, value))
    return tuple(sorted(out))


def describe_context(context: tuple[tuple[str, str], ...]) -> list[dict]:
    idx = question_index()
    order = [q["id"] for q in load_questions()["questions"]]
    items = sorted(context, key=lambda kv: order.index(kv[0]))
    return [{"id": k, "question": idx[k]["label"], "answer": idx[k]["options"][v], "value": v} for k, v in items]


def get_source(source_id: str) -> dict:
    return load_sources()[source_id]


def get_case_study(case_id: str) -> dict:
    return load_case_studies()[case_id]


@dataclass(frozen=True)
class Inputs:
    crop: str                 # "corn" | "wheat"
    official_name: str        # official CDL class name, e.g. "Winter Wheat"
    subtype: str | None
    year: int
    state_abbr: str | None = None
    state_name: str | None = None
    context: tuple[tuple[str, str], ...] = ()   # user-reported, unverified (see normalize_context)


class UnsupportedCrop(ValueError):
    pass


def _geo_applies(scope: dict, inputs: Inputs) -> bool:
    if scope["type"] == "conus":
        return True
    if scope["type"] == "states":
        return inputs.state_abbr is not None and inputs.state_abbr in scope["states"]
    return False


def _observations(rule: dict, inputs: Inputs) -> list[str]:
    """Only known, verified facts."""
    obs = [f"This location was classified as {inputs.official_name} in the {inputs.year} USDA Cropland Data Layer."]
    if rule["geographic_scope"]["type"] == "states" and inputs.state_name:
        obs.append(
            f"The selected point is in {inputs.state_name} (U.S. Census lookup), which is within the rule's scope: "
            f"{rule['geographic_scope']['basis']}"
        )
    return obs


def generate(inputs: Inputs) -> dict:
    if inputs.crop not in SUPPORTED_CROPS:
        raise UnsupportedCrop(f"Unsupported crop: {inputs.crop!r}")
    rs = load_ruleset()
    sources = load_sources()
    cases = load_case_studies()
    cat_index = {c: i for i, c in enumerate(rs["category_order"])}

    answers = dict(inputs.context)
    qidx = question_index()

    selected = []
    not_shown = []
    for rule in rs["rules"]:
        if inputs.crop not in rule["crops"]:
            continue
        if not _geo_applies(rule["geographic_scope"], inputs):
            continue
        missing, reported, excluded_by = [], [], None
        for p in rule["prerequisites"]:
            if p["available"]:
                continue
            ab = p.get("answered_by")
            ans = answers.get(ab["field"]) if ab else None
            if ab and ans in ab["met"]:
                reported.append(f"{qidx[ab['field']]['label']} — {qidx[ab['field']]['options'][ans]}")
            elif ab and ans in ab["not_met"]:
                excluded_by = f"{qidx[ab['field']]['label']} — {qidx[ab['field']]['options'][ans]}"
                break
            elif p.get("blocking_when_unknown", True):
                missing.append(p)
        if excluded_by:
            not_shown.append({"id": rule["id"], "action": rule["content"]["action"],
                              "reason": f"Not shown because you reported: {excluded_by}."})
            continue
        if missing and rule["on_missing_prerequisite"] == "omit":
            continue
        selected.append((rule, missing, reported))

    selected.sort(key=lambda rm: (cat_index[rm[0]["category"]], rm[0]["display_order"], rm[0]["id"]))
    order = {r["id"]: i for i, r in enumerate(rs["rules"])}
    not_shown.sort(key=lambda n: order[n["id"]])

    recs = []
    for rule, missing, reported in selected:
        c = rule["content"]
        case_list = [
            {k: cs[k] for k in ("id", "name", "source_url", "publisher", "region", "summary", "applicability_limits", "crops")}
            for cid in rule["case_study_ids"]
            if (cs := cases[cid]) and inputs.crop in cs["crops"]
        ]
        recs.append({
            "id": rule["id"],
            "ruleset_version": rs["ruleset_version"],
            "category": rule["category"],
            "category_label": rs["category_labels"][rule["category"]],
            "conditional": bool(missing),
            "conditional_prefix": rule.get("conditional_prefix") if missing else None,
            "unverified_prerequisites": [p["description"] for p in missing],
            "action": c["action"],
            "why": c["why"],
            "general_context": c["general_context"][inputs.crop],
            "supporting_observations": _observations(rule, inputs),
            "reported_by_user": reported,
            "case_studies": case_list,
            "case_study_note": None if case_list else NO_CASE_STUDY,
            "cost_effort": rule["cost_effort"],
            "verify_before_acting": rule["verify_before_acting"],
            "limitations": rule["limitations"],
            "sources": [
                {k: sources[sid][k] for k in ("id", "title", "publisher", "url", "verified_on")} for sid in rule["source_ids"]
            ],
        })

    groups = []
    for cat in rs["category_order"]:
        items = [r for r in recs if r["category"] == cat]
        if items:
            groups.append({"category": cat, "label": rs["category_labels"][cat], "recommendations": items})

    warnings = []
    if answers.get("current_crop") == "different":
        warnings.append(
            f"You reported a different crop this season. These suggestions are based on the {inputs.year} USDA "
            f"classification ({inputs.official_name}) and may not fit what is planted now."
        )

    return {
        "ruleset_version": rs["ruleset_version"],
        "dataset_year": inputs.year,
        "crop": inputs.crop,
        "official_name": inputs.official_name,
        "framing": (
            "Practices worth investigating — not diagnoses or prescriptions. "
            + ("FieldWise has not verified anything you reported about soil, management or current conditions."
               if inputs.context else
               "FieldWise has no information about this area's soil, management history or current conditions.")
        ),
        "groups": groups,
        "recommendation_ids": [r["id"] for r in recs],
        "reported_context": describe_context(inputs.context),
        "not_shown": not_shown,
        "warnings": warnings,
    }
