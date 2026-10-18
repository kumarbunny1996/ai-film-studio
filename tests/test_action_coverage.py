"""Milestone 7: action coverage metadata and the first-clip rule (no Blender).

ActionEntry.coverage ("full" | "partial", default "full") says whether an action keys every
bone of its rig. validate_against_manifest() rejects a character whose first clip, in the
builder's order, is partial: the builder holds that clip on the bottom NLA track for the whole
shot, and a partial action there leaves every bone it does not key in the rest pose. The
metadata is checked against the actual .blend files in tests/test_action_coverage_assets.py.
"""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from apps.api.schemas.scene_spec import (ActionEntry, AssetManifest, SceneSpec,
                                         validate_against_manifest)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_RAW = json.loads((ROOT / "assets/manifest.json").read_text())
MANIFEST = AssetManifest.model_validate(MANIFEST_RAW)
PARTIAL = {"mannequin_look", "mannequin_wave"}


def clip(action_id: str, start: int, end: int, blend_in: int = 6) -> dict:
    return {"action_id": action_id, "start_frame": start, "end_frame": end, "blend_in": blend_in}


def spec(*actions: dict, asset_id: str = "mannequin") -> SceneSpec:
    return SceneSpec.model_validate({
        "spec_version": "1.3", "project_id": "coverage", "scene_id": "sc01", "shot_id": "coverage",
        "description": "first-clip coverage", "environment": {"world_color": [0.5, 0.5, 0.5]},
        "render": {"frame_start": 1, "frame_end": 120},
        "characters": [{"name": "host", "asset_id": asset_id, "actions": list(actions)}],
        "camera": {"look_at": "host", "keys": [{"frame": 1, "location": [0, -6, 1.5]}]}})


def errors(*actions: dict, **kw) -> list[str]:
    return validate_against_manifest(spec(*actions, **kw), MANIFEST)


WAVE_FIRST = ("characters[host]: first clip 'mannequin_wave' is a partial-body gesture; "
              "start with a full-body action such as mannequin_idle")


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------
def test_only_the_two_gestures_are_partial():
    assert {a.id for a in MANIFEST.actions if a.coverage == "partial"} == PARTIAL
    assert all(a.coverage == "full" for a in MANIFEST.actions if a.id not in PARTIAL)


def test_omitted_coverage_means_full_so_existing_entries_are_unchanged():
    raw = {a["id"]: a for a in MANIFEST_RAW["actions"]}
    assert {i for i, a in raw.items() if "coverage" in a} == PARTIAL, \
        "every other entry still omits the field"
    entry = ActionEntry.model_validate({"id": "some_walk", "file": "actions/x.blend",
                                        "action_name": "x", "rig_type": "r", "frames": 10})
    assert entry.coverage == "full"


@pytest.mark.parametrize("bad", ["half", "FULL", "Partial", "", None, 1, True])
def test_invalid_coverage_values_are_rejected(bad):
    with pytest.raises(ValidationError, match="coverage"):
        ActionEntry.model_validate({"id": "some_walk", "file": "actions/x.blend",
                                    "action_name": "x", "rig_type": "r", "frames": 10,
                                    "coverage": bad})


def test_coverage_is_manifest_only_and_the_scenespec_schema_is_unchanged():
    exported = json.dumps(SceneSpec.model_json_schema())
    assert "coverage" not in exported
    assert json.loads((ROOT / "schemas/scene_spec.schema.json").read_text()) == \
        SceneSpec.model_json_schema()


# ---------------------------------------------------------------------------
# The first-clip rule
# ---------------------------------------------------------------------------
def test_a_gesture_first_timeline_is_rejected():
    assert errors(clip("mannequin_wave", 1, 61, 0), clip("mannequin_idle", 61, 120)) == [WAVE_FIRST]


def test_a_gesture_only_timeline_is_rejected():
    assert errors(clip("mannequin_wave", 1, 61, 0)) == [WAVE_FIRST]
    assert errors(clip("mannequin_look", 1, 25, 0)) == [
        "characters[host]: first clip 'mannequin_look' is a partial-body gesture; "
        "start with a full-body action such as mannequin_idle"]


def test_idle_then_gesture_is_accepted():
    assert errors(clip("mannequin_idle", 1, 120, 0), clip("mannequin_look", 20, 44),
                  clip("mannequin_wave", 50, 110)) == []


def test_walk_then_gesture_is_accepted():
    assert errors(clip("mannequin_walk", 1, 49, 0), clip("mannequin_wave", 50, 110)) == []
    assert errors(clip("mannequin_walk", 1, 49, 0), clip("mannequin_idle", 49, 120, 8),
                  clip("mannequin_wave", 60, 120)) == [], "walk, stop, then wave over the idle"


def test_the_rule_applies_to_the_ochre_variant_too():
    assert errors(clip("mannequin_wave", 1, 61, 0), asset_id="mannequin_ochre") == [WAVE_FIRST]
    assert errors(clip("mannequin_idle", 1, 120, 0), clip("mannequin_wave", 1, 61),
                  asset_id="mannequin_ochre") == []


def test_listing_order_does_not_matter_only_start_frames():
    """The builder sorts clips by start_frame (build_scene.place_actions), so a gesture listed
    first but starting later is not the first clip."""
    assert errors(clip("mannequin_wave", 50, 110), clip("mannequin_idle", 1, 120, 0)) == []


def test_equal_start_frames_keep_the_listed_order_like_the_builder():
    """place_actions uses sorted(..., key=start_frame), which is stable: among clips that start
    on the same frame the one listed first goes on the bottom track (pinned in Blender by
    tests/test_action_coverage_assets.py)."""
    assert errors(clip("mannequin_idle", 1, 120, 0), clip("mannequin_wave", 1, 61)) == []
    assert errors(clip("mannequin_wave", 1, 61, 0), clip("mannequin_idle", 1, 120, 0)) == [WAVE_FIRST]


def test_the_suggestion_comes_from_the_rigs_full_body_actions():
    full = sorted(a.id for a in MANIFEST.actions
                  if a.rig_type == "afs_mannequin_v1" and a.coverage == "full")
    assert full == ["mannequin_idle", "mannequin_walk"]
    m = MANIFEST.model_copy(deep=True)
    m.actions = [a for a in m.actions if a.id not in ("mannequin_idle", "mannequin_walk")]
    got = validate_against_manifest(spec(clip("mannequin_wave", 1, 61, 0)), m)
    assert got == ["characters[host]: first clip 'mannequin_wave' is a partial-body gesture; "
                   "start with a full-body action"]


def test_every_example_still_validates():
    for name in ("scene_001", "m6_character", "m7_greeting"):
        s = SceneSpec.model_validate_json((ROOT / f"schemas/examples/{name}.json").read_text())
        assert validate_against_manifest(s, MANIFEST) == [], name
