"""SceneSpec camera validation (Milestone 3). Fast: no Blender, no FFmpeg.

The golden dumps pin how valid legacy specs serialise. blender_job.run_shot writes exactly
this dump to spec.json for Blender, so a change here changes what the builder receives.
"""
import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from apps.api.schemas.scene_spec import (V12_CAMERA_FIELDS, AssetManifest, SceneSpec,
                                         camera_warnings, validate_against_manifest)

ROOT = Path(__file__).resolve().parents[1]
SCENE_001 = json.loads((ROOT / "schemas/examples/scene_001.json").read_text())      # v1.0
M1 = json.loads((ROOT / "schemas/examples/milestone1_primitives.json").read_text())  # v1.1

GOLDEN_CAMERA = {
    "scene_001": {
        "shot_size": "wide", "lens_mm": 40.0, "look_at": "girl", "look_at_height": 1.2,
        "keys": [
            {"frame": 1, "location": [-6.0, -11.0, 2.2], "rotation_deg": None, "lens_mm": None,
             "easing": "ease_in_out"},
            {"frame": 144, "location": [2.0, -10.0, 1.8], "rotation_deg": None, "lens_mm": None,
             "easing": "ease_in_out"}],
        "dof_enabled": True, "focus_target": "girl", "fstop": 4.0, "handheld_shake": 0.1},
    "milestone1_primitives": {
        "shot_size": "wide", "lens_mm": 35.0, "look_at": "pedestal", "look_at_height": 0.3,
        "keys": [
            {"frame": 1, "location": [-7.0, -7.0, 3.2], "rotation_deg": None, "lens_mm": None,
             "easing": "ease_in_out"},
            {"frame": 48, "location": [0.0, -9.5, 3.6], "rotation_deg": None, "lens_mm": None,
             "easing": "ease_in_out"},
            {"frame": 96, "location": [7.0, -7.0, 3.2], "rotation_deg": None, "lens_mm": None,
             "easing": "ease_in_out"}],
        "dof_enabled": False, "focus_target": None, "fstop": 2.8, "handheld_shake": 0.0},
}


def m1(**camera_patch) -> dict:
    d = copy.deepcopy(M1)
    d["camera"].update(camera_patch)
    return d


def explicit_rotation(**camera_patch) -> dict:
    """M1 with look_at removed and an explicit rotation on every key."""
    d = m1(**camera_patch)
    d["camera"].pop("look_at", None)
    for k in d["camera"]["keys"]:
        k["rotation_deg"] = [80.0, 0.0, -45.0]
    return d


def rejected(d: dict, match: str):
    with pytest.raises(ValidationError, match=match):
        SceneSpec.model_validate(d)


# ---------------------------------------------------------------------------
# Golden legacy serialisation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name, raw", [("scene_001", SCENE_001), ("milestone1_primitives", M1)])
def test_legacy_example_camera_dump_is_unchanged(name, raw):
    spec = SceneSpec.model_validate(raw)
    assert spec.model_dump(mode="json")["camera"] == GOLDEN_CAMERA[name]


@pytest.mark.parametrize("name, raw", [("scene_001", SCENE_001), ("milestone1_primitives", M1)])
def test_legacy_camera_dump_round_trips(name, raw):
    once = SceneSpec.model_validate(raw).model_dump_json()
    assert SceneSpec.model_validate_json(once).model_dump_json() == once


def test_example_versions_are_as_committed():
    assert SceneSpec.model_validate(SCENE_001).spec_version == "1.0"
    assert SceneSpec.model_validate(M1).spec_version == "1.1"


# ---------------------------------------------------------------------------
# Existing validators (previously untested)
# ---------------------------------------------------------------------------
def test_camera_is_required():
    d = copy.deepcopy(M1)
    del d["camera"]
    rejected(d, "camera")


def test_camera_needs_at_least_one_key():
    rejected(m1(keys=[]), "keys")


def test_camera_keys_must_be_ascending():
    d = m1()
    d["camera"]["keys"].reverse()
    rejected(d, "camera.keys must have unique, ascending frames")


def test_camera_keys_must_be_unique():
    d = m1()
    d["camera"]["keys"][1]["frame"] = 1
    rejected(d, "camera.keys must have unique, ascending frames")


def test_rotation_required_on_every_key_without_look_at():
    d = explicit_rotation()
    d["camera"]["keys"][1]["rotation_deg"] = None
    rejected(d, "camera keys need rotation_deg when camera.look_at is not set")
    assert SceneSpec.model_validate(explicit_rotation()).camera.look_at is None


def test_focus_target_must_exist():
    rejected(m1(focus_target="ghost"), "focus_target")


@pytest.mark.parametrize("field, ok, bad", [
    ("lens_mm", [8, 300], [7.99, 300.01]),
    ("fstop", [0.5, 32], [0.49, 32.01]),
    ("handheld_shake", [0, 1], [-0.01, 1.01]),
    ("look_at_height", [0, 10], [-0.01, 10.01]),
])
def test_camera_numeric_ranges(field, ok, bad):
    for v in ok:
        assert getattr(SceneSpec.model_validate(m1(**{field: v})).camera, field) == v
    for v in bad:
        rejected(m1(**{field: v}), field)


@pytest.mark.parametrize("v, accepted", [(8, True), (300, True), (7.99, False), (300.01, False)])
def test_key_lens_range(v, accepted):
    d = m1()
    d["camera"]["keys"][0]["lens_mm"] = v
    if accepted:
        assert SceneSpec.model_validate(d).camera.keys[0].lens_mm == v
    else:
        rejected(d, "lens_mm")


@pytest.mark.parametrize("bad", [[0, 0], [0, 0, 0, 0], "0,0,0"])
def test_key_location_must_be_three_numbers(bad):
    d = m1()
    d["camera"]["keys"][0]["location"] = bad
    rejected(d, "location")


def test_unknown_camera_field_rejected():
    rejected(m1(roll_deg=10), "roll_deg")


# ---------------------------------------------------------------------------
# Legacy behaviour that v1.0/v1.1 must keep accepting (the builder ignores the extra data)
# ---------------------------------------------------------------------------
def test_legacy_accepts_rotation_together_with_look_at():
    d = m1()
    d["camera"]["keys"][0]["rotation_deg"] = [90, 0, 45]
    assert SceneSpec.model_validate(d).camera.keys[0].rotation_deg == [90, 0, 45]


def test_legacy_accepts_dof_without_focus_target():
    s = SceneSpec.model_validate(explicit_rotation(dof_enabled=True, fstop=8))
    assert s.camera.dof_enabled and s.camera.focus_target is None and s.camera.look_at is None


# ===========================================================================
# Milestone 3.2: finite numbers in every version
# ===========================================================================
NON_FINITE = [float("nan"), float("inf"), float("-inf")]
MANIFEST = AssetManifest.model_validate_json((ROOT / "assets/manifest.json").read_text())


def v12(raw: dict = M1, **camera_patch) -> dict:
    d = copy.deepcopy(raw)
    d["spec_version"] = "1.2"
    d["camera"].update(camera_patch)
    return d


def _set(d: dict, path: str, value) -> dict:
    """path like 'camera.keys.0.location.1' or 'camera.fstop'."""
    *parents, last = path.split(".")
    node = d
    for p in parents:
        node = node[int(p)] if p.isdigit() else node[p]
    node[int(last) if last.isdigit() else last] = value
    return d


LEGACY_PATHS = ["camera.keys.0.location.0", "camera.keys.1.location.2", "camera.keys.0.lens_mm",
                "camera.lens_mm", "camera.fstop", "camera.look_at_height", "camera.handheld_shake"]


@pytest.mark.parametrize("bad", NON_FINITE, ids=["nan", "inf", "-inf"])
@pytest.mark.parametrize("path", LEGACY_PATHS)
@pytest.mark.parametrize("version", ["1.0", "1.1", "1.2"])
def test_camera_numbers_must_be_finite_in_every_version(version, path, bad):
    base = SCENE_001 if version == "1.0" else M1
    d = copy.deepcopy(base)
    d["spec_version"] = version
    rejected(_set(d, path, bad), "finite number")


@pytest.mark.parametrize("bad", NON_FINITE, ids=["nan", "inf", "-inf"])
@pytest.mark.parametrize("version", ["1.0", "1.1", "1.2"])
def test_rotation_must_be_finite_in_every_version(version, bad):
    d = explicit_rotation()
    d["spec_version"] = version
    if version == "1.0":
        d["primitives"] = []                       # 1.0 has no primitives
        d["environment"] = {"hdri_id": "sky_golden_hour"}
    d["camera"]["keys"][2]["rotation_deg"][1] = bad
    rejected(d, "finite number")


@pytest.mark.parametrize("path, bad", [
    ("camera.framing", {"subject_offset": [float("nan"), 0]}),
    ("camera.clip_start_m", float("inf")),
    ("camera.clip_end_m", float("inf")),
])
def test_v12_camera_numbers_must_be_finite(path, bad):
    rejected(_set(v12(), path, bad), "finite number")


def test_focus_distance_must_be_finite():
    d = explicit_rotation(dof_enabled=True, focus_distance_m=float("nan"))
    d["spec_version"] = "1.2"
    rejected(d, "finite number")


def test_non_finite_json_literals_are_rejected():
    """Python's json module writes and reads NaN/Infinity; validating JSON text must still fail."""
    for token in ("NaN", "Infinity", "-Infinity"):
        text = json.dumps(M1).replace('"look_at_height": 0.3', f'"look_at_height": {token}')
        assert token in text
        with pytest.raises(ValidationError):
            SceneSpec.model_validate_json(text)
        with pytest.raises(ValidationError, match="finite number"):
            SceneSpec.model_validate(json.loads(text))


def test_finite_check_keeps_valid_legacy_specs_identical():
    for name, raw in (("scene_001", SCENE_001), ("milestone1_primitives", M1)):
        assert SceneSpec.model_validate(raw).model_dump(mode="json")["camera"] == GOLDEN_CAMERA[name]


# ===========================================================================
# Milestone 3.3: SceneSpec 1.2 camera fields
# ===========================================================================
def test_existing_examples_are_valid_unchanged_as_v12():
    for name, raw in (("scene_001", SCENE_001), ("milestone1_primitives", M1)):
        s = SceneSpec.model_validate(v12(raw))
        assert s.spec_version == "1.2"
        assert s.model_dump(mode="json")["camera"] == GOLDEN_CAMERA[name]   # nothing added
        assert validate_against_manifest(s, MANIFEST) == []


def test_unset_v12_fields_never_appear_in_dumps():
    for raw in (SCENE_001, M1, v12()):
        cam = SceneSpec.model_validate(raw).model_dump(mode="json")["camera"]
        assert not set(V12_CAMERA_FIELDS) & set(cam)
        assert not set(V12_CAMERA_FIELDS) & set(json.loads(
            SceneSpec.model_validate(raw).model_dump_json())["camera"])


FULL_V12 = dict(framing={"subject_offset": [-1 / 6, 0.05]}, clip_start_m=0.05, clip_end_m=250.0,
                dof_enabled=True, fstop=4.0)


def test_v12_fields_are_accepted_and_serialised():
    s = SceneSpec.model_validate(v12(**FULL_V12))
    c = s.camera
    assert c.framing.subject_offset == [pytest.approx(-1 / 6), 0.05]
    assert (c.clip_start_m, c.clip_end_m) == (0.05, 250.0)
    dumped = s.model_dump(mode="json")["camera"]
    assert dumped["framing"] == {"subject_offset": [pytest.approx(-1 / 6), 0.05]}
    assert dumped["clip_start_m"] == 0.05 and dumped["clip_end_m"] == 250.0
    assert "focus_distance_m" not in dumped                       # still unset -> omitted
    again = SceneSpec.model_validate_json(s.model_dump_json())
    assert again.model_dump_json() == s.model_dump_json()


def test_focus_distance_is_accepted_for_dof_without_a_focus_object():
    d = explicit_rotation(dof_enabled=True, fstop=2.0, focus_distance_m=3.5)
    d["spec_version"] = "1.2"
    c = SceneSpec.model_validate(d).camera
    assert c.focus_distance_m == 3.5 and c.focus_source() == "distance"


@pytest.mark.parametrize("field, ok, bad", [
    ("clip_start_m", [0.001, 10], [0.0009, 10.01, 0]),
    ("clip_end_m", [1, 100_000], [0.99, 100_001]),
])
def test_v12_clip_ranges(field, ok, bad):
    for v in ok:
        assert getattr(SceneSpec.model_validate(v12(**{field: v})).camera, field) == v
    for v in bad:
        rejected(v12(**{field: v}), field)


@pytest.mark.parametrize("v, accepted", [(0.05, True), (10_000, True), (0.049, False),
                                         (10_001, False)])
def test_v12_focus_distance_range(v, accepted):
    d = explicit_rotation(dof_enabled=True, focus_distance_m=v)
    d["spec_version"] = "1.2"
    if accepted:
        assert SceneSpec.model_validate(d).camera.focus_distance_m == v
    else:
        rejected(d, "focus_distance_m")


@pytest.mark.parametrize("offset, accepted", [
    ([0, 0], True), ([0.4, -0.4], True), ([-1 / 6, 1 / 6], True),
    ([0.41, 0], False), ([0, -0.41], False), ([0.1], False), ([0, 0, 0], False), ("0,0", False),
])
def test_subject_offset_shape_and_range(offset, accepted):
    d = v12(framing={"subject_offset": offset})
    if accepted:
        assert SceneSpec.model_validate(d).camera.framing.subject_offset == pytest.approx(offset)
    else:
        rejected(d, "subject_offset")


def test_framing_needs_subject_offset_and_no_extra_keys():
    rejected(v12(framing={}), "subject_offset")
    rejected(v12(framing={"subject_offset": [0, 0], "roll": 3}), "roll")


def test_framing_needs_look_at():
    d = explicit_rotation(dof_enabled=False, framing={"subject_offset": [0.1, 0]})
    d["spec_version"] = "1.2"
    rejected(d, "framing.subject_offset needs camera.look_at")


@pytest.mark.parametrize("start, end", [(5, 2), (5, 5)])
def test_clip_start_must_be_below_clip_end(start, end):
    rejected(v12(clip_start_m=start, clip_end_m=end), "must be less than")


def test_one_sided_clip_is_fine():
    assert SceneSpec.model_validate(v12(clip_start_m=10)).camera.clip_end_m is None
    assert SceneSpec.model_validate(v12(clip_end_m=1)).camera.clip_start_m is None


def test_focus_distance_needs_dof_enabled():
    d = explicit_rotation(dof_enabled=False, focus_distance_m=3)
    d["spec_version"] = "1.2"
    rejected(d, "focus_distance_m needs camera.dof_enabled")


def test_focus_distance_conflicts_with_look_at():
    rejected(v12(dof_enabled=True, focus_distance_m=3), "only for depth of field without a "
             "focus object")                                    # M1 tracks the pedestal


def test_focus_distance_conflicts_with_focus_target():
    d = explicit_rotation(dof_enabled=True, focus_distance_m=3, focus_target="pedestal")
    d["spec_version"] = "1.2"
    rejected(d, "only for depth of field without a focus object")


# --- version restrictions ------------------------------------------------------
V12_SAMPLES = {"framing": {"subject_offset": [0.1, 0]}, "clip_start_m": 0.05,
               "clip_end_m": 500, "focus_distance_m": 3}


def legacy_with(version: str | None, field: str) -> dict:
    """A spec that is valid in `version` except for one v1.2 camera field.
    version None = spec_version omitted (which means 1.0)."""
    base = M1 if version == "1.1" else SCENE_001
    d = copy.deepcopy(base)
    cam = d["camera"]
    if field == "focus_distance_m":      # valid only for DoF with no focus object at all
        cam.pop("look_at", None)
        cam.pop("focus_target", None)
        cam["dof_enabled"] = True
        for k in cam["keys"]:
            k["rotation_deg"] = [80.0, 0.0, 0.0]
    cam[field] = V12_SAMPLES[field]
    if version is None:
        d.pop("spec_version", None)
    else:
        d["spec_version"] = version
    return d


@pytest.mark.parametrize("field", list(V12_SAMPLES))
@pytest.mark.parametrize("version", ["1.0", "1.1", None], ids=["1.0", "1.1", "omitted"])
def test_v12_fields_are_rejected_before_1_2(version, field):
    d = legacy_with(version, field)
    rejected(d, f"camera.{field} require\\(s\\) spec_version 1.2")
    d["spec_version"] = "1.2"                          # the same spec is valid as 1.2
    assert getattr(SceneSpec.model_validate(d).camera, field) is not None


def test_several_v12_fields_are_all_named_in_the_error():
    d = m1(clip_start_m=0.05, clip_end_m=500)
    rejected(d, "camera.clip_start_m, camera.clip_end_m require")


def test_unknown_spec_version_still_rejected():
    rejected(v12() | {"spec_version": "1.3"}, "spec_version")


# --- conflict rules: errors in 1.2, accepted (with warnings) in 1.0/1.1 ----------
def test_v12_rejects_rotation_with_look_at():
    d = v12()
    d["camera"]["keys"][1]["rotation_deg"] = [90, 0, 0]
    rejected(d, r"frames \[48\] set rotation_deg, but camera.look_at controls rotation")


def test_v12_rejects_dof_with_nothing_to_focus_on():
    d = explicit_rotation(dof_enabled=True)
    d["spec_version"] = "1.2"
    rejected(d, "dof_enabled needs something to focus on")


def test_v12_dof_default_true_needs_a_focus_source():
    """dof_enabled defaults to true, so a 1.2 camera without look_at must decide explicitly."""
    d = explicit_rotation()
    d["camera"].pop("dof_enabled")
    d["spec_version"] = "1.2"
    rejected(d, "dof_enabled needs something to focus on")


@pytest.mark.parametrize("fix, source", [
    ({"dof_enabled": False}, None),
    ({"focus_target": "pedestal"}, "pedestal"),
    ({"focus_distance_m": 4.0}, "distance"),
])
def test_v12_dof_conflict_resolutions(fix, source):
    d = explicit_rotation(**{"dof_enabled": True, **fix})
    d["spec_version"] = "1.2"
    assert SceneSpec.model_validate(d).camera.focus_source() == source


@pytest.mark.parametrize("version", ["1.0", "1.1"])
def test_legacy_conflicts_still_accepted(version):
    d = copy.deepcopy(SCENE_001 if version == "1.0" else M1)
    d["camera"]["keys"][0]["rotation_deg"] = [90, 0, 45]
    assert SceneSpec.model_validate(d).camera.keys[0].rotation_deg == [90, 0, 45]
    d = explicit_rotation(dof_enabled=True)
    d["spec_version"] = version
    if version == "1.0":
        d["primitives"], d["environment"] = [], {"hdri_id": "sky_golden_hour"}
        d["camera"]["look_at"] = None
    assert SceneSpec.model_validate(d).camera.dof_enabled


# --- camera_warnings: what the builder stage will report for legacy shots ---------
def test_camera_warnings_for_legacy_conflicts():
    d = m1()
    d["camera"]["keys"][0]["rotation_deg"] = [90, 0, 45]
    d["camera"]["keys"][2]["rotation_deg"] = [90, 0, 0]
    assert camera_warnings(SceneSpec.model_validate(d)) == [
        "camera: rotation_deg on keys at frames [1, 96] is ignored because look_at "
        "'pedestal' controls rotation"]
    w = camera_warnings(SceneSpec.model_validate(explicit_rotation(dof_enabled=True, fstop=8)))
    assert w == ["camera: dof_enabled with no look_at or focus_target; fstop 8.0 is not "
                 "applied and Blender's default focus is used"]


def test_camera_warnings_empty_for_clean_specs_and_for_v12():
    assert camera_warnings(SceneSpec.model_validate(SCENE_001)) == []
    assert camera_warnings(SceneSpec.model_validate(M1)) == []
    assert camera_warnings(SceneSpec.model_validate(v12(**FULL_V12))) == []


# --- committed v1.2 example ------------------------------------------------------
def test_m3_framing_example_is_valid_v12_with_its_documented_camera():
    raw = json.loads((ROOT / "schemas/examples/m3_framing.json").read_text())
    s = SceneSpec.model_validate(raw)
    assert s.spec_version == "1.2" and validate_against_manifest(s, MANIFEST) == []
    c = s.camera
    assert c.look_at == "hero" and c.framing.subject_offset == [-0.1667, 0.0]    # left third
    assert (c.clip_start_m, c.clip_end_m) == (0.05, 100.0)
    assert c.dof_enabled and c.focus_source() == "hero" and c.fstop == 4.0
    assert (s.render.resolution, s.render.frame_start, s.render.frame_end) == ((640, 360), 1, 48)
    assert camera_warnings(s) == []


# --- exported JSON Schema -------------------------------------------------------
def test_json_schema_gates_v12_camera_fields():
    schema = SceneSpec.model_json_schema()
    gate = schema["allOf"][1]
    assert gate["if"] == {"properties": {"spec_version": {"enum": ["1.0", "1.1"]}}}
    assert gate["then"]["properties"]["camera"]["properties"] == {
        name: {"type": "null"} for name in V12_CAMERA_FIELDS}
    cam = schema["$defs"]["Camera"]
    assert set(V12_CAMERA_FIELDS) <= set(cam["properties"])
    assert not set(V12_CAMERA_FIELDS) & set(cam.get("required", []))
    framing = schema["$defs"]["Framing"]
    assert framing["required"] == ["subject_offset"] and framing["additionalProperties"] is False
    items = framing["properties"]["subject_offset"]
    assert (items["minItems"], items["maxItems"]) == (2, 2)
    assert (items["items"]["minimum"], items["items"]["maximum"]) == (-0.4, 0.4)
