"""Milestone 6: the standalone manifest file preflight (workers/asset_preflight.py)."""
import json
from pathlib import Path

from apps.api.schemas.scene_spec import AssetManifest, SceneSpec
from workers import asset_preflight
from workers.asset_preflight import manifest_problems, referenced_files
from workers.blender_job import validate

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_RAW = json.loads((ROOT / "assets/manifest.json").read_text())
MANIFEST = AssetManifest.model_validate(MANIFEST_RAW)
SCENE_001 = SceneSpec.model_validate_json((ROOT / "schemas/examples/scene_001.json").read_text())
M6 = SceneSpec.model_validate_json((ROOT / "schemas/examples/m6_character.json").read_text())

# The 1.0 fictional entries were never authored; they stay in the manifest for now.
FICTIONAL_MISSING = [
    "missing file actions/human_actions.blend (used by idle_breathe, look_around, walk_cycle)",
    "missing file actions/quadruped_actions.blend (used by dog_idle, dog_trot)",
    "missing file characters/sheepdog.blend (used by sheepdog)",
    "missing file characters/shepherd_girl.blend (used by shepherd_girl)",
    "missing file environments/alpine_meadow.blend (used by alpine_meadow)",
    "missing file hdri/kloofendal_43d_clear_4k.exr (used by sky_golden_hour)",
    "missing file props/walking_staff.blend (used by walking_staff)",
]


def manifest(**patch) -> AssetManifest:
    return AssetManifest.model_validate({**MANIFEST_RAW, **patch})


def test_whole_manifest_reports_exactly_the_fictional_files():
    assert manifest_problems(MANIFEST) == FICTIONAL_MISSING


def test_the_mannequin_files_exist():
    files = referenced_files(M6, MANIFEST)
    assert files == {"characters/mannequin.blend": ["mannequin"],
                     "actions/mannequin_actions.blend": ["mannequin_idle", "mannequin_walk"],
                     "props/mannequin_baton.blend": ["mannequin_baton"]}
    assert manifest_problems(MANIFEST, spec=M6) == []


def test_spec_mode_checks_only_what_the_spec_uses():
    # scene_001 uses walk_cycle and look_around but not idle_breathe
    assert manifest_problems(MANIFEST, spec=SCENE_001) == [
        "missing file actions/human_actions.blend (used by look_around, walk_cycle)",
        *FICTIONAL_MISSING[1:]]


def test_scene_001_still_passes_validation_unchanged():
    """The preflight is standalone: validate() (used by run_shot) still accepts scene_001
    even though its files do not exist."""
    assert validate(SCENE_001.model_dump(mode="json")).shot_id == "sc01_sh01"


def test_duplicate_ids_are_reported():
    by_id = lambda kind, i: next(e for e in MANIFEST_RAW[kind] if e["id"] == i)
    dup_asset = {**by_id("assets", "mannequin_baton"), "file": "characters/other.blend"}
    dup_action = {**by_id("actions", "mannequin_walk")}
    m = manifest(assets=MANIFEST_RAW["assets"] + [dup_asset],
                 actions=MANIFEST_RAW["actions"] + [dup_action])
    problems = manifest_problems(m, spec=M6)
    assert problems == [
        "duplicate asset id 'mannequin_baton': only the first entry is used",
        "duplicate action id 'mannequin_walk': only the first entry is used"]


def test_paths_outside_the_assets_root_are_reported(tmp_path):
    (tmp_path / "outside.blend").write_bytes(b"")
    root = tmp_path / "assets"
    root.mkdir()
    entry = {**MANIFEST_RAW["assets"][-1], "file": "../outside.blend"}
    problems = manifest_problems(AssetManifest.model_validate({"assets": [entry], "actions": []}),
                                 root)
    assert len(problems) == 1 and "is outside" in problems[0]


def test_missing_and_present_files_against_another_root(tmp_path):
    (tmp_path / "props").mkdir()
    (tmp_path / "props" / "mannequin_baton.blend").write_bytes(b"")
    problems = manifest_problems(MANIFEST, tmp_path, spec=M6)
    assert problems == [
        "missing file actions/mannequin_actions.blend (used by mannequin_idle, mannequin_walk)",
        "missing file characters/mannequin.blend (used by mannequin)"]


def test_cli_exit_codes(capsys):
    assert asset_preflight.main([]) == 1
    assert capsys.readouterr().out.splitlines() == FICTIONAL_MISSING
    assert asset_preflight.main(["--spec", str(ROOT / "schemas/examples/m6_character.json")]) == 0
