import copy, json
from pathlib import Path

import pytest
from pydantic import ValidationError

from apps.api.schemas.scene_spec import AssetManifest, SceneSpec, validate_against_manifest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = json.loads((ROOT / "schemas/examples/scene_001.json").read_text())
MANIFEST = AssetManifest.model_validate_json((ROOT / "assets/manifest.json").read_text())


def spec(**patch):
    d = copy.deepcopy(EXAMPLE)
    d.update(patch)
    return d


def test_example_is_valid_and_buildable():
    s = SceneSpec.model_validate(EXAMPLE)
    assert validate_against_manifest(s, MANIFEST) == []


def test_unknown_fields_rejected():
    with pytest.raises(ValidationError):
        SceneSpec.model_validate(spec(mood="epic"))


def test_camera_target_must_exist():
    d = spec(); d["camera"]["look_at"] = "wolf"
    with pytest.raises(ValidationError, match="look_at"):
        SceneSpec.model_validate(d)


def test_character_must_not_tpose_at_start():
    d = spec(); d["characters"][0]["actions"][0]["start_frame"] = 10
    with pytest.raises(ValidationError, match="T-pose"):
        SceneSpec.model_validate(d)


def test_frames_outside_shot_rejected():
    d = spec(); d["camera"]["keys"][1]["frame"] = 500
    with pytest.raises(ValidationError, match="outside shot range"):
        SceneSpec.model_validate(d)


def test_wrong_rig_action_reported_for_llm_retry():
    d = spec(); d["characters"][1]["actions"][0]["action_id"] = "walk_cycle"
    errors = validate_against_manifest(SceneSpec.model_validate(d), MANIFEST)
    assert any("quadruped_v1" in e for e in errors)


def test_unknown_asset_lists_valid_options():
    d = spec(); d["characters"][0]["asset_id"] = "knight"
    errors = validate_against_manifest(SceneSpec.model_validate(d), MANIFEST)
    assert any("Valid: ['mannequin', 'mannequin_ochre', 'sheepdog', 'shepherd_girl']" in e
               for e in errors)


# ---------------------------------------------------------------------------
# v1.1: procedural primitives, with v1.0 compatibility
# ---------------------------------------------------------------------------
M1 = json.loads((ROOT / "schemas/examples/milestone1_primitives.json").read_text())


def m1(**patch):
    d = copy.deepcopy(M1)
    d.update(patch)
    return d


def test_v10_example_still_declares_and_validates_as_10():
    s = SceneSpec.model_validate(EXAMPLE)
    assert s.spec_version == "1.0" and s.primitives == []


def test_missing_spec_version_means_10():
    d = spec(); del d["spec_version"]
    assert SceneSpec.model_validate(d).spec_version == "1.0"


def test_asset_scene_is_also_valid_as_11():
    s = SceneSpec.model_validate(spec(spec_version="1.1"))
    assert validate_against_manifest(s, MANIFEST) == []


def test_milestone_example_is_valid_and_buildable():
    s = SceneSpec.model_validate(M1)
    assert s.spec_version == "1.1"
    assert [p.name for p in s.primitives] == ["ground", "pedestal", "cube", "ball", "cone"]
    assert (s.render.resolution, s.render.fps, s.render.frame_end) == ((640, 360), 24, 96)
    assert validate_against_manifest(s, MANIFEST) == []


def test_primitives_rejected_in_10():
    d = spec(); d["primitives"] = [{"name": "box", "shape": "cube"}]
    with pytest.raises(ValidationError, match="primitives require spec_version 1.1"):
        SceneSpec.model_validate(d)


def test_world_color_rejected_in_10():
    d = spec(); d["environment"]["world_color"] = [0.5, 0.5, 0.5]
    with pytest.raises(ValidationError, match="world_color requires spec_version 1.1"):
        SceneSpec.model_validate(d)


def test_10_still_needs_asset_or_hdri():
    d = spec(); d["environment"] = {"fog_density": 0.1}
    with pytest.raises(ValidationError, match="asset_id or an hdri_id"):
        SceneSpec.model_validate(d)


def test_11_needs_some_environment():
    with pytest.raises(ValidationError, match="world_color"):
        SceneSpec.model_validate(m1(environment={}))


def test_unknown_spec_version_rejected():
    with pytest.raises(ValidationError):
        SceneSpec.model_validate(m1(spec_version="2.0"))


@pytest.mark.parametrize("field, value", [
    ("shape", "pyramid"),
    ("size", 0),
    ("material", {"base_color": [1.5, 0, 0]}),
    ("material", {"base_color": [1, 0]}),
    ("material", {"roughness": 2}),
    ("glow", True),
    ("name", "Bad Name"),
])
def test_invalid_primitive_fields_rejected(field, value):
    d = m1(); d["primitives"][2][field] = value
    with pytest.raises(ValidationError):
        SceneSpec.model_validate(d)


def test_primitive_key_must_set_a_channel():
    d = m1(); d["primitives"][2]["keys"][0] = {"frame": 1}
    with pytest.raises(ValidationError, match="sets no channel"):
        SceneSpec.model_validate(d)


def test_primitive_key_scale_must_be_positive():
    d = m1(); d["primitives"][2]["keys"][0]["scale"] = [1, 1, 0]
    with pytest.raises(ValidationError, match="scale must be > 0"):
        SceneSpec.model_validate(d)


def test_primitive_keys_sorted_and_in_range():
    d = m1(); d["primitives"][3]["keys"].reverse()
    with pytest.raises(ValidationError, match="ascending"):
        SceneSpec.model_validate(d)
    d = m1(); d["primitives"][2]["keys"][1]["frame"] = 200
    with pytest.raises(ValidationError, match="outside shot range"):
        SceneSpec.model_validate(d)


def test_primitive_names_unique_across_instances():
    d = m1(); d["primitives"][3]["name"] = "cube"
    with pytest.raises(ValidationError, match="unique"):
        SceneSpec.model_validate(d)


def test_camera_may_track_a_primitive_but_not_a_ghost():
    assert SceneSpec.model_validate(M1).camera.look_at == "pedestal"
    d = m1(); d["camera"]["look_at"] = "pyramid"
    with pytest.raises(ValidationError, match="look_at"):
        SceneSpec.model_validate(d)


def test_committed_json_schema_is_current():
    committed = json.loads((ROOT / "schemas/scene_spec.schema.json").read_text())
    assert committed == SceneSpec.model_json_schema(), \
        "regenerate: python -m apps.api.schemas.scene_spec > schemas/scene_spec.schema.json"


def test_json_schema_describes_both_versions():
    schema = SceneSpec.model_json_schema()
    assert schema["properties"]["spec_version"]["enum"] == ["1.0", "1.1", "1.2", "1.3"]
    rule = schema["allOf"][0]
    assert rule["if"]["properties"]["spec_version"]["const"] == "1.0"
    assert rule["then"]["properties"]["primitives"]["maxItems"] == 0
    assert "Primitive" in schema["$defs"] and "primitives" in schema["properties"]


# ---------------------------------------------------------------------------
# Finite numbers everywhere (M1): NaN/+-inf must never reach Blender
# ---------------------------------------------------------------------------
NON_FINITE = [float("nan"), float("inf"), float("-inf")]
EXAMPLES = {name: json.loads((ROOT / f"schemas/examples/{name}.json").read_text())
            for name in ("scene_001", "milestone1_primitives", "m3_framing")}


def numeric_paths(obj, path=()):
    """Every int/float leaf in a spec (bools excluded)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from numeric_paths(v, path + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from numeric_paths(v, path + (i,))
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        yield path


def with_value(raw: dict, path: tuple, value) -> dict:
    d = copy.deepcopy(raw)
    node = d
    for p in path[:-1]:
        node = node[p]
    node[path[-1]] = value
    return d


@pytest.mark.parametrize("name", list(EXAMPLES))
def test_every_number_in_every_example_must_be_finite(name):
    """Exhaustive: each numeric field of each committed example, set to NaN, inf and -inf,
    is rejected (before the fix, 246 of these were accepted)."""
    raw = EXAMPLES[name]
    paths = list(numeric_paths(raw))
    assert paths, name
    accepted = []
    for path in paths:
        for bad in NON_FINITE:
            try:
                SceneSpec.model_validate(with_value(raw, path, bad))
                accepted.append((".".join(map(str, path)), bad))
            except ValidationError:
                pass
    assert accepted == []


@pytest.mark.parametrize("bad", NON_FINITE, ids=["nan", "inf", "-inf"])
@pytest.mark.parametrize("name, path", [
    ("milestone1_primitives", ("primitives", 1, "transform", "location", 0)),
    ("milestone1_primitives", ("primitives", 2, "keys", 0, "location", 1)),
    ("milestone1_primitives", ("primitives", 2, "keys", 0, "rotation_deg", 2)),
    ("scene_001", ("characters", 0, "transform", "location", 2)),
    ("scene_001", ("characters", 0, "transform", "rotation_deg", 0)),
    ("scene_001", ("characters", 0, "motion_path", 0, "location", 0)),
    ("scene_001", ("characters", 0, "motion_path", 0, "rotation_z_deg")),
    ("scene_001", ("environment", "hdri_rotation_deg")),
], ids=["prim-transform", "prim-key-location", "prim-key-rotation", "char-transform-location",
        "char-transform-rotation", "motion-path-location", "motion-path-heading", "hdri-rotation"])
def test_previously_accepted_unbounded_fields_now_reject_non_finite(name, path, bad):
    with pytest.raises(ValidationError, match="finite number"):
        SceneSpec.model_validate(with_value(EXAMPLES[name], path, bad))


def test_non_finite_json_literals_are_rejected_outside_the_camera():
    text = json.dumps(EXAMPLES["milestone1_primitives"]).replace(
        '"location": [0, 0, 0.5]', '"location": [NaN, 0, 0.5]', 1)
    assert "NaN" in text
    with pytest.raises(ValidationError):
        SceneSpec.model_validate_json(text)
    with pytest.raises(ValidationError, match="finite number"):
        SceneSpec.model_validate(json.loads(text))


def test_finite_check_applies_to_every_model():
    import inspect
    from apps.api.schemas import scene_spec as S
    models = [o for o in vars(S).values() if inspect.isclass(o) and issubclass(o, S.Strict)]
    assert len(models) > 10
    assert all(m.model_config.get("allow_inf_nan") is False for m in models)
    assert all(m.model_config.get("extra") == "forbid" for m in models)


@pytest.mark.parametrize("name", list(EXAMPLES))
def test_valid_examples_are_unchanged_by_the_finite_check(name):
    raw = EXAMPLES[name]
    once = SceneSpec.model_validate(raw).model_dump_json()
    assert SceneSpec.model_validate_json(once).model_dump_json() == once
