"""Milestone 7: action coverage metadata against the actual .blend files, and the builder's
clip order for equal start frames. Run with:
pytest -m blender tests/test_action_coverage_assets.py

For every manifest action whose file exists, the action's F-curves are read with the
read-only blender/scripts/inspect_asset.py. Blender 5.2 stores them per action slot (layered
actions), reported as "<slot identifier>|<data path>[<index>]". The rig's bones, each bone's
rotation mode and the root bone come from a character asset of the same rig_type, not from
names. An action marked "full" must key, in one slot, every bone's rotation channels and the
root bone's location; one marked "partial" must not.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from apps.api.schemas.scene_spec import AssetManifest
from workers import config
from workers.blender_job import ASSETS, REPO, run_shot

pytestmark = [
    pytest.mark.blender,
    pytest.mark.skipif(shutil.which(config.BLENDER_BIN) is None, reason="Blender not found"),
]

INSPECT = REPO / "blender" / "scripts" / "inspect_asset.py"
INSPECT_CHAR = REPO / "blender" / "scripts" / "inspect_character.py"
MANIFEST = AssetManifest.model_validate_json((ASSETS / "manifest.json").read_text())
# The manifest's placeholder actions, whose files have never existed (see asset_preflight)
PLACEHOLDERS = {"idle_breathe", "walk_cycle", "look_around", "dog_idle", "dog_trot"}
ROTATION_CHANNELS = {"XYZ": ("rotation_euler", 3), "XZY": ("rotation_euler", 3),
                     "YXZ": ("rotation_euler", 3), "YZX": ("rotation_euler", 3),
                     "ZXY": ("rotation_euler", 3), "ZYX": ("rotation_euler", 3),
                     "QUATERNION": ("rotation_quaternion", 4),
                     "AXIS_ANGLE": ("rotation_axis_angle", 4)}


def inspect(blend: Path, out: Path) -> dict:
    proc = subprocess.run(
        [config.BLENDER_BIN, "-b", "--factory-startup", "--python-exit-code", "1",
         "-P", str(INSPECT), "--", "--blend", str(blend), "--out", str(out)],
        capture_output=True, text=True, errors="replace", timeout=300)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    return json.loads(out.read_text())


@pytest.fixture(scope="module")
def reports(tmp_path_factory):
    """Inspection of every existing action file and of one character per rig type."""
    base = tmp_path_factory.mktemp("coverage")
    files = sorted({a.file for a in MANIFEST.actions if (ASSETS / a.file).is_file()})
    actions = {f: inspect(ASSETS / f, base / f"{Path(f).stem}.json") for f in files}
    rigs = {}
    for a in MANIFEST.assets:
        if a.type.value == "character" and a.rig_type not in rigs and (ASSETS / a.file).is_file():
            rep = inspect(ASSETS / a.file, base / f"rig_{a.id}.json")
            bones = rep["armatures"][rep["objects"][a.armature]["data"]]["bones"]
            pose = rep["objects"][a.armature]["pose"]
            rigs[a.rig_type] = {
                "rotation": {b: ROTATION_CHANNELS[pose[b]["rotation_mode"]] for b in bones},
                "root": [b for b, info in bones.items() if info["parent"] is None]}
    return actions, rigs


def required_channels(rig: dict) -> set[str]:
    out = {f'pose.bones["{b}"].{path}[{i}]' for b, (path, n) in rig["rotation"].items()
           for i in range(n)}
    assert len(rig["root"]) == 1, "one root bone"
    out |= {f'pose.bones["{rig["root"][0]}"].location[{i}]' for i in range(3)}
    return out


def test_every_action_file_that_exists_is_checked_and_only_placeholders_are_missing(reports):
    actions, rigs = reports
    missing = {a.id for a in MANIFEST.actions if not (ASSETS / a.file).is_file()}
    assert missing == PLACEHOLDERS, "only the known placeholder actions cannot be inspected"
    checked = {a.id for a in MANIFEST.actions if a.file in actions}
    assert checked == {a.id for a in MANIFEST.actions} - PLACEHOLDERS
    assert {a.rig_type for a in MANIFEST.actions if a.id in checked} <= set(rigs)


@pytest.mark.parametrize("action_id", sorted(
    a.id for a in MANIFEST.actions if a.id not in PLACEHOLDERS))
def test_coverage_metadata_matches_the_keyed_channels(reports, action_id):
    actions, rigs = reports
    entry = MANIFEST.action(action_id)
    act = actions[entry.file]["actions"][entry.action_name]
    assert len(act["slots"]) == 1, "one slot holds all of the action's channels"
    slot = act["slots"][0]["identifier"]
    keyed = {path.split("|", 1)[1] for path in act["fcurves"] if path.startswith(f"{slot}|")}
    assert len(keyed) == len(act["fcurves"]), "no F-curves outside the slot"
    required = required_channels(rigs[entry.rig_type])
    if entry.coverage == "full":
        assert required <= keyed, f"{action_id} is marked full but misses {sorted(required - keyed)[:5]}"
    else:
        assert required - keyed, f"{action_id} is marked partial but keys every bone and the root"
        assert keyed, f"{action_id} keys nothing"


def test_equal_start_frames_go_on_tracks_in_listed_order(tmp_path):
    """The validator assumes build_scene.place_actions puts, among clips starting on the same
    frame, the one listed first on the bottom track; this pins it on a real build. The idle
    is listed first, so it is the base and the wave layers over it."""
    spec = {
        "spec_version": "1.3", "project_id": "coverage", "scene_id": "sc01", "shot_id": "order",
        "description": "equal start frames", "environment": {"world_color": [0.5, 0.5, 0.5]},
        "render": {"frame_start": 1, "frame_end": 61},
        "characters": [{"name": "host", "asset_id": "mannequin", "actions": [
            {"action_id": "mannequin_idle", "start_frame": 1, "end_frame": 61, "blend_in": 0},
            {"action_id": "mannequin_wave", "start_frame": 1, "end_frame": 61, "blend_in": 6}]}],
        "camera": {"look_at": "host", "dof_enabled": False,
                   "keys": [{"frame": 1, "location": [0, -6, 1.5]}]}}
    report = run_shot(spec, tmp_path / "project", render=False)
    assert report["status"] == "ok" and report["returncode"] == 0, report
    out = tmp_path / "chars.json"
    proc = subprocess.run(
        [config.BLENDER_BIN, "-b", report["blend"], "--factory-startup", "--python-exit-code", "1",
         "-P", str(INSPECT_CHAR), "--", "--out", str(out), "--frames", "1,30"],
        capture_output=True, text=True, errors="replace", timeout=600)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    data = json.loads(out.read_text())
    tracks = data["armatures"]["RIG-mannequin"]["nla"]["tracks"]
    assert [t["name"] for t in tracks] == ["00_mannequin_idle", "01_mannequin_wave"]
    knee = data["frames"]["30"]["armatures"]["RIG-mannequin"]["shin.L"]["rotation_euler"][0]
    assert abs(knee) > 0.05, "the legs stand on the idle's soft knee, not the straight rest pose"
