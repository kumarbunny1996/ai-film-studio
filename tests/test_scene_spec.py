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
    assert any("Valid: ['sheepdog', 'shepherd_girl']" in e for e in errors)
