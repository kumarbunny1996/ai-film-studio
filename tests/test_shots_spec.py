"""SceneSpec 1.3 shots (Milestone 4 schema stage). Fast: no Blender, no FFmpeg."""
import copy
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from apps.api.schemas.scene_spec import (MAX_SHOTS, MIN_SHOT_FRAMES, AssetManifest, SceneSpec,
                                         camera_warnings, shot_warnings,
                                         validate_against_manifest)

ROOT = Path(__file__).resolve().parents[1]
EX = {name: json.loads((ROOT / f"schemas/examples/{name}.json").read_text())
      for name in ("scene_001", "milestone1_primitives", "m3_framing", "m4_sequence")}
M4 = EX["m4_sequence"]
MANIFEST = AssetManifest.model_validate_json((ROOT / "assets/manifest.json").read_text())

# SHA-256 of model_dump_json() for each legacy example, recorded on main (cdd229c) before
# SceneSpec 1.3 existed. Any change to how 1.0-1.2 specs serialise breaks these.
LEGACY_DUMP_SHA256 = {
    "scene_001": "dc5e3d6e7b36e8bde642458083e47fa218d17913ba0ec4156f7e71ac75e8a044",
    "milestone1_primitives": "873a14271c4e27582a6ad386fdbe1429c21dc4856ff28ed6563d334875583a6a",
    "m3_framing": "07abd3d212800e3ca650e6bfb9b6f5f2c95b25b1cded64300bbd972e1ccdce33",
}


def m4(**top) -> dict:
    d = copy.deepcopy(M4)
    d.update(top)
    return d


def shots_of(d: dict) -> list[dict]:
    return d["shots"]


def rejected(d: dict, match: str):
    with pytest.raises(ValidationError, match=match):
        SceneSpec.model_validate(d)


def single_camera_v13() -> dict:
    """milestone1_primitives as a 1.3 single-camera spec."""
    d = copy.deepcopy(EX["milestone1_primitives"])
    d["spec_version"] = "1.3"
    return d


# ---------------------------------------------------------------------------
# The committed example
# ---------------------------------------------------------------------------
def test_m4_example_is_a_valid_three_shot_v13_spec():
    s = SceneSpec.model_validate(M4)
    assert s.spec_version == "1.3" and s.camera is None
    assert [(x.shot_id, x.frame_start, x.frame_end) for x in s.shots] == [
        ("sh01_wide", 1, 48), ("sh02_track", 49, 96), ("sh03_close", 97, 132)]
    assert validate_against_manifest(s, MANIFEST) == []
    assert camera_warnings(s) == [] and shot_warnings(s) == []
    assert [label for label, *_ in s.cameras()] == [
        "shots[sh01_wide].camera", "shots[sh02_track].camera", "shots[sh03_close].camera"]
    assert s.shots[2].camera.framing.subject_offset == [-0.1667, 0.0]


def test_v13_dump_omits_camera_and_round_trips():
    s = SceneSpec.model_validate(M4)
    d = json.loads(s.model_dump_json())
    assert "camera" not in d and len(d["shots"]) == 3
    assert SceneSpec.model_validate_json(s.model_dump_json()).model_dump_json() == s.model_dump_json()


def test_v13_single_camera_form_is_valid_and_has_no_shots_key():
    s = SceneSpec.model_validate(single_camera_v13())
    assert s.shots is None and s.camera.look_at == "pedestal"
    assert "shots" not in json.loads(s.model_dump_json())
    assert [label for label, *_ in s.cameras()] == ["camera"]


# ---------------------------------------------------------------------------
# Legacy compatibility (1.0-1.2)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", list(LEGACY_DUMP_SHA256))
def test_legacy_full_dump_is_byte_identical(name):
    dumped = SceneSpec.model_validate(EX[name]).model_dump_json()
    assert hashlib.sha256(dumped.encode()).hexdigest() == LEGACY_DUMP_SHA256[name]
    assert "shots" not in json.loads(dumped)


@pytest.mark.parametrize("version", ["1.0", "1.1", "1.2", None], ids=["1.0", "1.1", "1.2", "omitted"])
def test_shots_are_rejected_before_1_3(version):
    """scene_001 (no primitives, so valid in every version) with its camera moved into a
    single shot: only the shots gate can reject it."""
    d = copy.deepcopy(EX["scene_001"])
    d["shots"] = [{"shot_id": "sh01", "frame_start": 1, "frame_end": 144,
                   "camera": d.pop("camera")}]
    if version is None:
        d.pop("spec_version", None)
    else:
        d["spec_version"] = version
    rejected(d, "shots require spec_version 1.3")
    d["spec_version"] = "1.3"                              # the same spec is valid as 1.3
    assert len(SceneSpec.model_validate(d).shots) == 1


@pytest.mark.parametrize("name", list(LEGACY_DUMP_SHA256))
def test_camera_still_required_before_1_3(name):
    d = copy.deepcopy(EX[name])
    del d["camera"]
    rejected(d, f"camera is required for spec_version {d.get('spec_version', '1.0')}")


def test_legacy_conflicts_still_accepted_and_still_warned():
    d = copy.deepcopy(EX["milestone1_primitives"])          # 1.1
    d["camera"]["keys"][0]["rotation_deg"] = [90, 0, 45]
    s = SceneSpec.model_validate(d)
    assert camera_warnings(s) and "rotation_deg" in camera_warnings(s)[0]


# ---------------------------------------------------------------------------
# 1.3: exactly one of camera / shots
# ---------------------------------------------------------------------------
def test_v13_rejects_both_camera_and_shots():
    d = m4()
    d["camera"] = copy.deepcopy(EX["m3_framing"]["camera"])
    rejected(d, "either camera .* or shots .* not both")


def test_v13_rejects_neither_camera_nor_shots():
    d = m4()
    del d["shots"]
    rejected(d, "spec_version 1.3 needs camera .* or shots")


def test_explicit_null_counts_as_absent():
    d = m4(camera=None)
    assert SceneSpec.model_validate(d).camera is None
    d = single_camera_v13()
    d["shots"] = None
    assert SceneSpec.model_validate(d).shots is None


def test_shot_list_length_limits():
    rejected(m4(shots=[]), "shots")
    one = m4()
    s = copy.deepcopy(one["shots"][0])
    s["frame_end"] = 132
    s["camera"]["keys"][1]["frame"] = 132
    assert len(SceneSpec.model_validate(m4(shots=[s])).shots) == 1          # 1 shot is fine
    many = []
    for i in range(MAX_SHOTS + 1):
        x = copy.deepcopy(one["shots"][0])
        x["shot_id"] = f"sh{i:02d}"
        x["frame_start"], x["frame_end"] = 1 + i * 12, 12 + i * 12
        x["camera"]["keys"] = [{"frame": 1 + i * 12, "location": [0.0, -14.0, 3.5]}]
        many.append(x)
    d = m4(shots=many)
    d["render"]["frame_end"] = 12 * (MAX_SHOTS + 1)
    d["primitives"][3]["keys"][1]["frame"] = 12 * (MAX_SHOTS + 1)
    rejected(d, "shots")
    d["shots"] = many[:MAX_SHOTS]
    d["render"]["frame_end"] = 12 * MAX_SHOTS
    d["primitives"][3]["keys"][1]["frame"] = 12 * MAX_SHOTS
    assert len(SceneSpec.model_validate(d).shots) == MAX_SHOTS


# ---------------------------------------------------------------------------
# Unique ids, order, contiguity, coverage
# ---------------------------------------------------------------------------
def test_shot_ids_must_be_unique():
    d = m4()
    shots_of(d)[2]["shot_id"] = "sh01_wide"
    rejected(d, r"shot_id must be unique; duplicated: \['sh01_wide'\]")


@pytest.mark.parametrize("bad", ["Sh01", "1shot", "sh 01", "x"])
def test_shot_id_follows_identifier_rules(bad):
    d = m4()
    shots_of(d)[0]["shot_id"] = bad
    rejected(d, "shot_id")


def test_unknown_shot_field_rejected():
    d = m4()
    shots_of(d)[0]["transition"] = "dissolve"
    rejected(d, "transition")


def test_shot_end_before_start_rejected():
    d = m4()
    shots_of(d)[1]["frame_end"] = 40
    rejected(d, "frame_end \\(40\\) is before frame_start \\(49\\)")


def test_shots_out_of_order_rejected():
    d = m4()
    d["shots"] = [d["shots"][1], d["shots"][0], d["shots"][2]]
    rejected(d, "gap before shot 'sh02_track'")


def test_gap_between_shots_rejected():
    d = m4()
    shots_of(d)[1]["frame_start"] = 52                     # frames 49-51 uncovered
    shots_of(d)[1]["camera"]["keys"][0]["frame"] = 52
    rejected(d, "gap before shot 'sh02_track': frames 49-51 are not covered")


def test_overlapping_shots_rejected():
    d = m4()
    shots_of(d)[1]["frame_start"] = 40                     # overlaps sh01 (1-48)
    shots_of(d)[1]["camera"]["keys"][0]["frame"] = 40
    rejected(d, "shot 'sh02_track' starts at frame 40, overlapping or out of order")


def test_shots_must_start_at_render_frame_start():
    d = m4()
    d["render"]["frame_start"] = 1
    shots_of(d)[0]["frame_start"] = 5
    shots_of(d)[0]["camera"]["keys"][0]["frame"] = 5
    rejected(d, "gap before shot 'sh01_wide': frames 1-4")


def test_shots_must_end_at_render_frame_end():
    d = m4()
    d["render"]["frame_end"] = 140
    rejected(d, "shots end at frame 132 but render.frame_end is 140")


def test_shots_may_not_run_past_render_frame_end():
    d = m4()
    d["render"]["frame_end"] = 120
    d["primitives"][3]["keys"][1]["frame"] = 120
    rejected(d, "shots end at frame 132 but render.frame_end is 120")


def test_shots_honour_a_render_range_not_starting_at_1():
    d = m4()
    d["render"]["frame_start"], d["render"]["frame_end"] = 101, 232
    d["primitives"][3]["keys"][0]["frame"], d["primitives"][3]["keys"][1]["frame"] = 101, 232
    for s in shots_of(d):
        s["frame_start"] += 100
        s["frame_end"] += 100
        for k in s["camera"]["keys"]:
            k["frame"] += 100
    assert [x.frame_start for x in SceneSpec.model_validate(d).shots] == [101, 149, 197]


# ---------------------------------------------------------------------------
# Every shot camera follows the camera rules
# ---------------------------------------------------------------------------
def test_shot_camera_keys_must_stay_inside_the_shot():
    d = m4()
    shots_of(d)[1]["camera"]["keys"][1]["frame"] = 100    # sh02 is 49-96
    rejected(d, r"shots\[sh02_track\].camera.keys at frames \[100\] are outside the shot's "
                "range 49-96")


def test_shot_camera_key_order_still_checked():
    d = m4()
    shots_of(d)[0]["camera"]["keys"].reverse()
    rejected(d, "camera.keys must have unique, ascending frames")


def test_shot_camera_look_at_must_exist():
    d = m4()
    shots_of(d)[2]["camera"]["look_at"] = "ghost"
    shots_of(d)[2]["camera"]["focus_target"] = None
    rejected(d, r"shots\[sh03_close\].camera.look_at 'ghost' is not a character, prop or primitive")


def test_shot_camera_focus_target_must_exist():
    d = m4()
    shots_of(d)[2]["camera"]["focus_target"] = "ghost"
    rejected(d, r"shots\[sh03_close\].camera.focus_target 'ghost'")


def test_shot_camera_rotation_with_look_at_is_an_error():
    d = m4()
    shots_of(d)[0]["camera"]["keys"][0]["rotation_deg"] = [80, 0, 0]
    rejected(d, r"shots\[sh01_wide\].camera.keys at frames \[1\] set rotation_deg, but "
                r"shots\[sh01_wide\].camera.look_at controls rotation")


def test_shot_camera_dof_needs_a_focus_source():
    d = m4()
    cam = shots_of(d)[1]["camera"]
    cam.pop("look_at")
    for k in cam["keys"]:
        k["rotation_deg"] = [80, 0, 0]
    rejected(d, r"shots\[sh02_track\].camera.dof_enabled needs something to focus on")


def test_shot_camera_without_look_at_needs_rotation():
    d = m4()
    cam = shots_of(d)[0]["camera"]
    cam.pop("look_at")
    rejected(d, "camera keys need rotation_deg when camera.look_at is not set")


@pytest.mark.parametrize("patch, match", [
    ({"lens_mm": 7}, "lens_mm"),
    ({"fstop": 40}, "fstop"),
    ({"framing": {"subject_offset": [0.5, 0]}}, "subject_offset"),
    ({"clip_start_m": 5, "clip_end_m": 2}, "must be less than"),
    ({"look_at_height": float("nan")}, "finite number"),
])
def test_shot_camera_field_rules_still_apply(patch, match):
    d = m4()
    shots_of(d)[2]["camera"].update(patch)
    rejected(d, match)


def test_v12_fields_are_allowed_in_v13_shots():
    s = SceneSpec.model_validate(M4)
    close = s.shots[2].camera
    assert (close.clip_start_m, close.clip_end_m) == (0.05, 100.0)
    assert close.focus_source() == "hero"


# ---------------------------------------------------------------------------
# shot_warnings(): advisory only, never a validation error
# ---------------------------------------------------------------------------
def test_short_shot_is_valid_but_warned():
    d = m4()
    shots_of(d)[0]["frame_end"] = 8                       # sh01: 8 frames
    shots_of(d)[0]["camera"]["keys"][1]["frame"] = 8
    shots_of(d)[1]["frame_start"] = 9
    shots_of(d)[1]["camera"]["keys"][0]["frame"] = 9
    s = SceneSpec.model_validate(d)                       # still valid
    assert shot_warnings(s) == [
        f"shot 'sh01_wide' is 8 frame(s) long (frames 1-8); shots under {MIN_SHOT_FRAMES} "
        "frames are very short"]


def test_exactly_min_length_is_not_warned():
    d = m4()
    shots_of(d)[0]["frame_end"] = MIN_SHOT_FRAMES
    shots_of(d)[0]["camera"]["keys"][1]["frame"] = MIN_SHOT_FRAMES
    shots_of(d)[1]["frame_start"] = MIN_SHOT_FRAMES + 1
    shots_of(d)[1]["camera"]["keys"][0]["frame"] = MIN_SHOT_FRAMES + 1
    assert shot_warnings(SceneSpec.model_validate(d)) == []


@pytest.mark.parametrize("name", ["scene_001", "milestone1_primitives", "m3_framing"])
def test_shot_warnings_empty_for_single_camera_specs(name):
    assert shot_warnings(SceneSpec.model_validate(EX[name])) == []


# ---------------------------------------------------------------------------
# Exported JSON Schema
# ---------------------------------------------------------------------------
def test_json_schema_describes_v13():
    schema = SceneSpec.model_json_schema()
    assert schema["properties"]["spec_version"]["enum"] == ["1.0", "1.1", "1.2", "1.3"]
    assert "camera" not in schema["required"]               # moved into the version rules
    shots = schema["properties"]["shots"]["anyOf"][0]
    assert (shots["minItems"], shots["maxItems"]) == (1, MAX_SHOTS)
    assert schema["$defs"]["Shot"]["required"] == ["shot_id", "frame_start", "frame_end", "camera"]
    assert schema["$defs"]["Shot"]["additionalProperties"] is False
    legacy, v13 = schema["allOf"][2], schema["allOf"][3]
    assert legacy["if"] == {"properties": {"spec_version": {"enum": ["1.0", "1.1", "1.2"]}}}
    assert legacy["then"]["required"] == ["camera"]
    assert legacy["then"]["properties"]["shots"] == {"type": "null"}
    assert v13["if"]["properties"]["spec_version"] == {"const": "1.3"}
    branches = v13["then"]["oneOf"]
    assert [b["required"] for b in branches] == [["camera"], ["shots"]]


def test_committed_json_schema_matches():
    committed = json.loads((ROOT / "schemas/scene_spec.schema.json").read_text())
    assert committed == SceneSpec.model_json_schema()
