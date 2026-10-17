"""The exported JSON Schema and the Pydantic models agree on the cases that matter (audit P2-2).

jsonschema is not a project dependency, so this file carries a small validator for exactly
the keywords schemas/scene_spec.schema.json uses. test_validator_covers_every_keyword fails if
the exported schema ever uses one it does not implement, so nothing is silently skipped.
Cross-field rules that only Pydantic enforces (shot coverage, unique ids, keys inside a shot,
1.2 conflicts) are out of scope here and are not claimed to match.
"""
import copy
import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from apps.api.schemas.scene_spec import SceneSpec

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas/scene_spec.schema.json").read_text())
EX = {n: json.loads((ROOT / f"schemas/examples/{n}.json").read_text())
      for n in ("scene_001", "milestone1_primitives", "m3_framing", "m4_sequence", "m6_character")}

ANNOTATIONS = {"title", "description", "default"}
SUBSCHEMA_LISTS = {"anyOf", "oneOf", "allOf", "prefixItems"}
SUBSCHEMA_ONE = {"items", "if", "then", "else", "additionalProperties"}
SUBSCHEMA_MAPS = {"properties", "$defs"}
CHECKS = {"type", "enum", "const", "required", "minItems", "maxItems", "minLength",
          "maxLength", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
          "pattern", "$ref"}
SUPPORTED = ANNOTATIONS | SUBSCHEMA_LISTS | SUBSCHEMA_ONE | SUBSCHEMA_MAPS | CHECKS


def keywords(schema, found=None) -> set[str]:
    found = set() if found is None else found
    if not isinstance(schema, dict):
        return found
    for k, v in schema.items():
        found.add(k)
        if k in SUBSCHEMA_MAPS:
            for sub in v.values():
                keywords(sub, found)
        elif k in SUBSCHEMA_LISTS:
            for sub in v:
                keywords(sub, found)
        elif k in SUBSCHEMA_ONE and isinstance(v, dict):
            keywords(v, found)
    return found


def _type_ok(inst, t) -> bool:
    if isinstance(t, list):
        return any(_type_ok(inst, x) for x in t)
    return {"object": isinstance(inst, dict), "array": isinstance(inst, list),
            "string": isinstance(inst, str), "boolean": isinstance(inst, bool),
            "null": inst is None,
            "integer": isinstance(inst, int) and not isinstance(inst, bool),
            "number": isinstance(inst, (int, float)) and not isinstance(inst, bool)}[t]


def _same(a, b) -> bool:                 # JSON equality: true is not 1
    return type(a) is type(b) and a == b if isinstance(a, bool) or isinstance(b, bool) else a == b


def valid(inst, s, root=SCHEMA) -> bool:
    if "$ref" in s:
        name = s["$ref"].removeprefix("#/$defs/")
        if not valid(inst, root["$defs"][name], root):
            return False
    if "type" in s and not _type_ok(inst, s["type"]):
        return False
    if "enum" in s and not any(_same(inst, e) for e in s["enum"]):
        return False
    if "const" in s and not _same(inst, s["const"]):
        return False
    num = isinstance(inst, (int, float)) and not isinstance(inst, bool)
    if num and ("minimum" in s and inst < s["minimum"] or "maximum" in s and inst > s["maximum"]
                or "exclusiveMinimum" in s and inst <= s["exclusiveMinimum"]
                or "exclusiveMaximum" in s and inst >= s["exclusiveMaximum"]):
        return False
    if isinstance(inst, str) and ("minLength" in s and len(inst) < s["minLength"]
                                  or "maxLength" in s and len(inst) > s["maxLength"]
                                  or "pattern" in s and not re.search(s["pattern"], inst)):
        return False
    if isinstance(inst, list):
        if "minItems" in s and len(inst) < s["minItems"] or \
           "maxItems" in s and len(inst) > s["maxItems"]:
            return False
        prefix = s.get("prefixItems", [])
        if any(not valid(x, p, root) for x, p in zip(inst, prefix)):
            return False
        if "items" in s and any(not valid(x, s["items"], root) for x in inst[len(prefix):]):
            return False
    if isinstance(inst, dict):
        if any(k not in inst for k in s.get("required", [])):
            return False
        props = s.get("properties", {})
        if any(not valid(inst[k], sub, root) for k, sub in props.items() if k in inst):
            return False
        if s.get("additionalProperties") is False and any(k not in props for k in inst):
            return False
    if "allOf" in s and not all(valid(inst, x, root) for x in s["allOf"]):
        return False
    if "anyOf" in s and not any(valid(inst, x, root) for x in s["anyOf"]):
        return False
    if "oneOf" in s and sum(valid(inst, x, root) for x in s["oneOf"]) != 1:
        return False
    if "if" in s:
        branch = s.get("then") if valid(inst, s["if"], root) else s.get("else")
        if branch is not None and not valid(inst, branch, root):
            return False
    return True


def pydantic_valid(d: dict) -> bool:
    try:
        SceneSpec.model_validate(d)
        return True
    except ValidationError:
        return False


def both(d: dict) -> tuple[bool, bool]:
    return valid(d, SCHEMA), pydantic_valid(d)


# ---------------------------------------------------------------------------
def test_validator_covers_every_keyword_in_the_exported_schema():
    assert keywords(SCHEMA) <= SUPPORTED, keywords(SCHEMA) - SUPPORTED


def test_validator_is_not_vacuous():
    bad = copy.deepcopy(EX["m3_framing"])
    bad["camera"]["lens_mm"] = "fifty"
    assert both(bad) == (False, False)
    bad = copy.deepcopy(EX["m3_framing"])
    bad["camera"]["mood"] = "epic"
    assert both(bad) == (False, False)


@pytest.mark.parametrize("name", list(EX))
def test_every_example_is_valid_in_both(name):
    assert both(EX[name]) == (True, True)


@pytest.mark.parametrize("name, version", [("scene_001", "1.0"), ("milestone1_primitives", "1.1"),
                                           ("m3_framing", "1.2")])
def test_legacy_camera_null_is_rejected_by_both(name, version):
    d = copy.deepcopy(EX[name])
    assert d.get("spec_version", "1.0") == version
    d["camera"] = None
    assert both(d) == (False, False)


def test_omitted_version_camera_null_is_rejected_by_both():
    d = copy.deepcopy(EX["scene_001"])
    d.pop("spec_version", None)
    d["camera"] = None
    assert both(d) == (False, False)


def test_legacy_camera_missing_is_rejected_by_both():
    d = copy.deepcopy(EX["m3_framing"])
    del d["camera"]
    assert both(d) == (False, False)


def test_legacy_shots_rejected_by_both():
    d = copy.deepcopy(EX["scene_001"])
    d["shots"] = [{"shot_id": "sh01", "frame_start": 1, "frame_end": 144,
                   "camera": copy.deepcopy(d["camera"])}]
    assert both(d) == (False, False)


def test_v13_shots_with_explicit_camera_null_accepted_by_both():
    d = copy.deepcopy(EX["m4_sequence"])
    d["camera"] = None
    assert both(d) == (True, True)


def test_v13_camera_and_shots_together_rejected_by_both():
    d = copy.deepcopy(EX["m4_sequence"])
    d["camera"] = copy.deepcopy(EX["m3_framing"]["camera"])
    assert both(d) == (False, False)


def test_v13_neither_camera_nor_shots_rejected_by_both():
    d = copy.deepcopy(EX["m4_sequence"])
    del d["shots"]
    assert both(d) == (False, False)


def test_v13_single_camera_form_accepted_by_both():
    d = copy.deepcopy(EX["m3_framing"])
    d["spec_version"] = "1.3"
    assert both(d) == (True, True)
