"""Milestone 6: the m6_character example and the mannequin manifest entries (no Blender)."""
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path

import pytest

from apps.api.schemas.scene_spec import (AssetManifest, SceneSpec, camera_warnings,
                                         shot_warnings, validate_against_manifest)

ROOT = Path(__file__).resolve().parents[1]
RAW = json.loads((ROOT / "schemas/examples/m6_character.json").read_text())
MANIFEST = AssetManifest.model_validate_json((ROOT / "assets/manifest.json").read_text())
_spec = importlib.util.spec_from_file_location(
    "afs_mannequin", ROOT / "blender/scripts/author_assets/mannequin.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

# SHA-256 of model_dump_json() for the example as committed in Milestone 6.
# Updated in the Milestone 6 walk-cycle review: walk 1-81 / idle 81-120 (stop at left mid-stance),
# root stop at frame 81, x 1.926779, and sh02 look_at_height 1.1 -> 0.9 (room under the feet).
# Updated again for the sh02 dolly hold: a key at frame 81 (x 1.041026, on the original line)
# and the frame-88 key moved to the hold position; description notes the hold.
# Updated for the R1S walk cycle: the walk is slower (0.0336056 m/frame), so the root starts at
# x -0.761669 (= 1.926779 - 80 * 0.0336056) instead of -1.75, keeping the frame-81 stop,
# cameras and cuts; the description's speed reads 0.03361 m/frame.
M6_DUMP_SHA256 = "114a0385ab4121efbdeddbac08f853b452ed449aad7df39acf6d9be2573699e4"


def walk_m_per_frame() -> float:
    """Average travel of the authored walk: a heel lands WALK_CONTACT_DEG in front of the hip
    on a leg of length THIGH_M + SHIN_M and the footprint moves back to the same angle behind,
    so each step is 2 * leg * sin(WALK_CONTACT_DEG); two steps per cycle."""
    step = 2 * (M.THIGH_M + M.SHIN_M) * math.sin(math.radians(M.WALK_CONTACT_DEG))
    return 2 * step / M.WALK["frames"]


def test_example_is_a_valid_buildable_three_shot_character_scene():
    s = SceneSpec.model_validate(RAW)
    assert s.spec_version == "1.3" and s.camera is None
    assert [(x.shot_id, x.frame_start, x.frame_end) for x in s.shots] == [
        ("sh01_wide", 1, 48), ("sh02_track", 49, 88), ("sh03_close", 89, 120)]
    assert validate_against_manifest(s, MANIFEST) == []
    assert camera_warnings(s) == [] and shot_warnings(s) == []
    assert all(sh.camera.look_at == "hero" for sh in s.shots)


def test_example_dump_is_pinned():
    dump = SceneSpec.model_validate(RAW).model_dump_json()
    assert hashlib.sha256(dump.encode()).hexdigest() == M6_DUMP_SHA256


def test_walk_ends_at_mid_stance_then_crossfades_into_idle():
    walk, idle = RAW["characters"][0]["actions"]
    assert (walk["action_id"], walk["start_frame"], walk["end_frame"]) == ("mannequin_walk", 1, 81)
    assert (idle["action_id"], idle["start_frame"], idle["end_frame"]) == ("mannequin_idle", 81, 120)
    assert walk["blend_in"] == 0, "the first clip has nothing to crossfade from"
    assert idle["blend_in"] == 8
    # the walk's last frame is cycle frame 17 (phase 0.5): left foot flat under the hips, at
    # mid-stance with the pelvis and chest unrotated
    cycle_frame = 1 + (walk["end_frame"] - walk["start_frame"]) % M.WALK["frames"]
    assert cycle_frame == 17
    pose = dict(M.actions()["mannequin_walk"])[cycle_frame]
    ankle = M.leg_fk("L", pose["rot"]["hips"], pose["hips_loc"], pose["rot"]["thigh.L"], pose["rot"]["shin.L"])[2]
    assert ankle == pytest.approx([0.1, 0.0, M.ANKLE_Z], abs=2e-6)
    assert pose["rot"]["hips"][1] == 0.0 and pose["rot"]["chest"][1] == pose["rot"]["spine"][1] == 0.0


def test_root_motion_matches_the_authored_walk_speed_and_stops_with_the_walk():
    keys = RAW["characters"][0]["motion_path"]
    (f0, x0), (f1, x1) = [(k["frame"], k["location"][0]) for k in keys]
    assert walk_m_per_frame() == pytest.approx(M.WALK_M_PER_FRAME, abs=1e-12)
    assert (x1 - x0) / (f1 - f0) == pytest.approx(M.WALK_M_PER_FRAME, abs=1e-8)
    assert keys[0]["easing"] == "linear"
    assert all(k["rotation_z_deg"] == 90 for k in keys), "faces -Y, so +90 walks along +X"
    walk, _ = RAW["characters"][0]["actions"]
    assert f1 == walk["end_frame"], "the root stops on the walk's last (mid-stance) frame"


def test_manifest_notes_record_the_walk_speed():
    notes = MANIFEST.asset("mannequin").notes
    assert f"{walk_m_per_frame():.6f} m/frame" in notes
    assert f"{walk_m_per_frame() * M.WALK['frames']:.6f} m per 32-frame cycle" in notes
    assert "planted foot is stationary" in notes and "sliding" not in notes.replace(
        "without sliding", "")


def test_only_the_tracking_shot_camera_changed():
    """Milestone 6 review: sh02's aim was lowered from 1.1 m to 0.9 m to leave room under the
    feet, and its dolly now holds from frame 81, where the character stops, so the camera
    does not keep travelling and swing into a fast pan. The 81 key sits on the original
    49 -> 88 line, so frames 49-81 are unchanged. Cut frames and the other shots are as
    reviewed."""
    shots = {s["shot_id"]: s for s in RAW["shots"]}
    assert [(s["frame_start"], s["frame_end"]) for s in RAW["shots"]] == [(1, 48), (49, 88), (89, 120)]
    sh02 = shots["sh02_track"]["camera"]
    assert sh02["look_at_height"] == 0.9
    assert sh02["keys"] == [
        {"frame": 49, "location": [-0.6, -5.5, 1.4], "easing": "linear"},
        {"frame": 81, "location": [1.041026, -5.5, 1.4], "easing": "constant"},
        {"frame": 88, "location": [1.041026, -5.5, 1.4]}]
    on_old_line = -0.6 + (1.4 - -0.6) * (81 - 49) / (88 - 49)
    assert sh02["keys"][1]["location"][0] == pytest.approx(on_old_line, abs=1e-6)
    walk, _ = RAW["characters"][0]["actions"]
    assert sh02["keys"][1]["frame"] == walk["end_frame"], "the camera stops with the character"
    assert shots["sh01_wide"]["camera"]["look_at_height"] == 1.1
    assert shots["sh03_close"]["camera"]["look_at_height"] == 1.45


def test_manifest_entries_match_the_authored_assets():
    char = MANIFEST.asset("mannequin")
    assert (char.type.value, char.file, char.collection, char.armature, char.rig_type) == (
        "character", M.CHARACTER_FILE.as_posix(), M.CHARACTER_COLLECTION, M.ARMATURE, M.RIG_TYPE)
    assert set(char.bones) <= set(M.BONES) and "hand.R" in char.bones
    prop = MANIFEST.asset("mannequin_baton")
    assert (prop.type.value, prop.file, prop.collection) == (
        "prop", M.PROP_FILE.as_posix(), M.PROP_COLLECTION)
    for action_id, frames in M.ACTION_FRAMES.items():
        a = MANIFEST.action(action_id)
        assert (a.file, a.action_name, a.rig_type, a.frames, a.loopable) == (
            M.ACTIONS_FILE.as_posix(), action_id, M.RIG_TYPE, frames, True)


def test_existing_manifest_entries_are_preserved():
    ids = [a.id for a in MANIFEST.assets], [a.id for a in MANIFEST.actions]
    # Milestone 7 added mannequin_ochre (beside mannequin) and the two gestures (at the end);
    # Milestone 11 added the two marked characters after mannequin_ochre
    assert ids == (["shepherd_girl", "sheepdog", "walking_staff", "alpine_meadow",
                    "sky_golden_hour", "mannequin", "mannequin_ochre", "mannequin_marked",
                    "mannequin_ochre_marked", "mannequin_baton"],
                   ["idle_breathe", "walk_cycle", "look_around", "dog_idle", "dog_trot",
                    "mannequin_idle", "mannequin_walk", "mannequin_look", "mannequin_wave"])


def test_mannequin_actions_are_rejected_on_other_rigs():
    d = copy.deepcopy(RAW)
    d["characters"][0]["asset_id"] = "shepherd_girl"
    errors = validate_against_manifest(SceneSpec.model_validate(d), MANIFEST)
    assert any("is for rig 'afs_mannequin_v1'" in e for e in errors)


def test_baton_needs_a_bone_the_mannequin_exposes():
    d = copy.deepcopy(RAW)
    d["props"][0]["parent_bone"] = "DEF-hand.R"
    errors = validate_against_manifest(SceneSpec.model_validate(d), MANIFEST)
    assert errors == ["props[baton]: bone 'DEF-hand.R' not exposed on 'mannequin'. "
                      "Valid: ['hand.R', 'hand.L', 'head', 'chest', 'hips']"]
