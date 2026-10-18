"""Milestone 7: the gestures layered over a continuous idle, through the real builder. Run with:
pytest -m blender tests/test_m7_gesture_layering.py

Builds two small v1.3 scenes with run_shot(render=False) into tmp_path, using the installed
assets: an idle-only baseline (the grey host idles; the ochre traveller walks, stops at
mid-stance and idles) and the same scene with the gestures added on top (host: look 20-44,
wave 50-110; traveller: wave 70-130), then reads both back with the read-only
blender/scripts/inspect_character.py and compares the evaluated poses frame by frame.
Nothing is rendered. No schema or builder change is involved: overlapping clips are already
valid SceneSpec 1.3, and build_scene.place_actions stacks them on NLA tracks in start order.
"""
import copy
import importlib.util
import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from workers import config
from workers.blender_job import REPO, run_shot

pytestmark = [
    pytest.mark.blender,
    pytest.mark.skipif(shutil.which(config.BLENDER_BIN) is None, reason="Blender not found"),
]

INSPECT_CHAR = REPO / "blender" / "scripts" / "inspect_character.py"
_spec = importlib.util.spec_from_file_location(
    "afs_mannequin", REPO / "blender/scripts/author_assets/mannequin.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

SLOT = "OBRIG-mannequin"
HOST, TRAVELLER = "RIG-mannequin", "RIG-mannequin_ochre"
FRAMES = list(range(1, 131))
TOL = 1e-5
LOOK_AT, LOOK_END, WAVE_AT, WAVE_END, T_WAVE_AT = 20, 44, 50, 110, 70
BLEND = 6
LOOK = dict(M.look_keys())
WAVE = dict(M.wave_keys())
LOOK_BONES = ("spine", "chest", "neck", "head")
ARM = ("upper_arm.R", "forearm.R", "hand.R")
LEGS = ["hips"] + [f"{b}.{s}" for b in ("thigh", "shin", "foot") for s in "LR"]
X0 = -3.0
X1 = round(X0 + 48 * M.WALK_M_PER_FRAME, 6)       # walk 1-49 ends on cycle frame 17

BASE = {
    "spec_version": "1.3", "project_id": "m7_layering", "scene_id": "sc01",
    "shot_id": "layering", "description": "gesture layering over a continuous idle",
    "environment": {"world_color": [0.5, 0.5, 0.5]},
    "render": {"resolution": [640, 360], "frame_start": 1, "frame_end": 130},
    "characters": [
        {"name": "host", "asset_id": "mannequin",
         "actions": [{"action_id": "mannequin_idle", "start_frame": 1, "end_frame": 130,
                      "blend_in": 0}]},
        {"name": "traveller", "asset_id": "mannequin_ochre",
         "transform": {"location": [X0, 0, 0], "rotation_deg": [0, 0, 90]},
         "motion_path": [
             {"frame": 1, "location": [X0, 0, 0], "rotation_z_deg": 90, "easing": "linear"},
             {"frame": 49, "location": [X1, 0, 0], "rotation_z_deg": 90}],
         "actions": [
             {"action_id": "mannequin_walk", "start_frame": 1, "end_frame": 49, "blend_in": 0},
             {"action_id": "mannequin_idle", "start_frame": 49, "end_frame": 130, "blend_in": 8}]}],
    "camera": {"look_at": "host", "dof_enabled": False,
               "keys": [{"frame": 1, "location": [0, -8, 1.5]}]},
}
LAYERED = copy.deepcopy(BASE)
LAYERED["characters"][0]["actions"] += [
    {"action_id": "mannequin_look", "start_frame": LOOK_AT, "end_frame": LOOK_END, "blend_in": BLEND},
    {"action_id": "mannequin_wave", "start_frame": WAVE_AT, "end_frame": WAVE_END, "blend_in": BLEND}]
LAYERED["characters"][1]["actions"] += [
    {"action_id": "mannequin_wave", "start_frame": T_WAVE_AT, "end_frame": 130, "blend_in": BLEND}]


def build_and_inspect(spec: dict, root: Path) -> tuple[dict, dict]:
    report = run_shot(spec, root / "project", render=False)
    assert report["status"] == "ok" and report["returncode"] == 0, report
    out = root / "chars.json"
    proc = subprocess.run(
        [config.BLENDER_BIN, "-b", report["blend"], "--factory-startup", "--python-exit-code", "1",
         "-P", str(INSPECT_CHAR), "--", "--out", str(out), "--frames", ",".join(map(str, FRAMES)),
         "--objects", "ROOT-host,ROOT-traveller"],
        capture_output=True, text=True, errors="replace", timeout=600)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    return report, json.loads(out.read_text())


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    return build_and_inspect(BASE, tmp_path_factory.mktemp("m7_base"))


@pytest.fixture(scope="module")
def layered(tmp_path_factory):
    return build_and_inspect(LAYERED, tmp_path_factory.mktemp("m7_layered"))


def pose(data, f, rig) -> dict:
    return data["frames"][str(f)]["armatures"][rig]


def direction(bone: dict) -> list[float]:
    m = bone["matrix_world"]
    return [m[i][1] for i in range(3)]


def angle_deg(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b)) / (math.dist(a, [0, 0, 0]) * math.dist(b, [0, 0, 0]))
    return math.degrees(math.acos(max(-1.0, min(1.0, dot))))


def max_bone_turn(data, f, rig, bones=None) -> float:
    """Largest change in any bone's world direction from frame f-1 to f, in degrees."""
    a, b = pose(data, f - 1, rig), pose(data, f, rig)
    return max(angle_deg(direction(a[n]), direction(b[n])) for n in (bones or a))


# ---------------------------------------------------------------------------
# How the builder stacks the clips
# ---------------------------------------------------------------------------
def test_gestures_stack_on_higher_tracks_with_the_mannequin_slot(layered):
    report, data = layered
    assert report["warnings"] == ["no style template loaded; starting from an empty scene"], \
        "no 'not loopable; holding' warning: each gesture clip is exactly its action's length"
    tracks = {rig: data["armatures"][rig]["nla"]["tracks"] for rig in (HOST, TRAVELLER)}
    assert [t["name"] for t in tracks[HOST]] == [
        "00_mannequin_idle", "01_mannequin_look", "02_mannequin_wave"]
    assert [t["name"] for t in tracks[TRAVELLER]] == [
        "00_mannequin_walk", "01_mannequin_idle", "02_mannequin_wave"]
    for rig in (HOST, TRAVELLER):
        for t in tracks[rig]:
            s = t["strips"][0]
            assert s["slot"] == SLOT and s["blend_type"] == "REPLACE", (rig, t["name"])
            if t["name"].split("_", 1)[1] in M.GESTURE_FRAMES:
                assert (s["extrapolation"], s["blend_in"], s["repeat"]) == ("HOLD_FORWARD", 6.0, 1.0)


# ---------------------------------------------------------------------------
# Legs, hips and everything the gestures do not key come from the idle
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rig", [HOST, TRAVELLER])
def test_legs_hips_and_feet_are_identical_to_the_idle_only_build(base, layered, rig):
    """No foot sliding or leg change from layering: the leg chain and hips evaluate exactly as
    without the gestures, at every frame (so the walk, the stop and the idle stance are
    untouched)."""
    for f in FRAMES:
        a, b = pose(base[1], f, rig), pose(layered[1], f, rig)
        for bone in LEGS:
            for key in ("head", "tail", "rotation_euler", "location"):
                assert b[bone][key] == pytest.approx(a[bone][key], abs=1e-6), (rig, f, bone, key)


@pytest.mark.parametrize("rig, first", [(HOST, LOOK_AT), (TRAVELLER, T_WAVE_AT)])
def test_nothing_changes_until_the_first_gesture_starts(base, layered, rig, first):
    for f in range(1, first + 1):                       # at the start frame its influence is 0
        assert pose(layered[1], f, rig) == pose(base[1], f, rig), (rig, f)


def test_the_bones_the_look_turns_keep_the_idles_breathing(base, layered):
    for f in FRAMES:
        a, b = pose(base[1], f, HOST), pose(layered[1], f, HOST)
        for bone in LOOK_BONES:
            for axis in (0, 2):
                assert b[bone]["rotation_euler"][axis] == pytest.approx(
                    a[bone]["rotation_euler"][axis], abs=TOL), (f, bone, axis)


def test_the_traveller_upper_body_is_untouched_apart_from_the_waving_arm(base, layered):
    for f in FRAMES:
        a, b = pose(base[1], f, TRAVELLER), pose(layered[1], f, TRAVELLER)
        for bone in set(a) - set(ARM):
            assert b[bone]["rotation_euler"] == pytest.approx(a[bone]["rotation_euler"], abs=TOL)


# ---------------------------------------------------------------------------
# Look
# ---------------------------------------------------------------------------
def test_look_blends_in_linearly_over_the_idle_then_follows_its_keys_and_holds(layered):
    data = layered[1]
    for f in range(LOOK_AT, 131):
        w = min(1.0, (f - LOOK_AT) / BLEND)
        key = LOOK[min(f - LOOK_AT + 1, M.LOOK["frames"] + 1)]   # held after the clip
        for bone in LOOK_BONES:
            got = pose(data, f, HOST)[bone]["rotation_euler"][1]
            assert got == pytest.approx(w * math.radians(key[bone][1]), abs=TOL), (f, bone)


def test_the_host_head_turns_40_degrees_to_its_right_and_keeps_it_through_the_wave(layered):
    data = layered[1]
    for f in range(LOOK_AT + 16, 131):                  # the look holds from its frame 17
        z = [pose(data, f, HOST)["head"]["matrix_world"][i][2] for i in range(3)]
        assert math.degrees(math.atan2(-z[0], -z[1])) == pytest.approx(40.0, abs=0.01), f


# ---------------------------------------------------------------------------
# Wave
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rig, start, end", [(HOST, WAVE_AT, WAVE_END), (TRAVELLER, T_WAVE_AT, 130)])
def test_wave_crossfades_from_the_idle_then_follows_its_keys(base, layered, rig, start, end):
    for f in range(start, end + 1):
        w = min(1.0, (f - start) / BLEND)
        key = WAVE[f - start + 1]
        for bone in ARM:
            for i in range(3):
                idle = pose(base[1], f, rig)[bone]["rotation_euler"][i]
                got = pose(layered[1], f, rig)[bone]["rotation_euler"][i]
                assert got == pytest.approx((1 - w) * idle + w * math.radians(key[bone][i]),
                                            abs=TOL), (rig, f, bone, i)


def test_after_the_wave_the_arm_holds_the_idles_mean_pose_within_its_breathing(base, layered):
    """Known layering limitation: NLA holds the wave's last key (the idle's mean arm pose), so
    the arm stops breathing; the idle's own arm moves only +-1 degree about that pose."""
    last = WAVE[M.WAVE["frames"] + 1]
    for f in range(WAVE_END + 1, 131):
        for bone in ARM:
            got = pose(layered[1], f, HOST)[bone]["rotation_euler"]
            assert got == pytest.approx([math.radians(v) for v in last[bone].values()], abs=TOL)
            idle = pose(base[1], f, HOST)[bone]["rotation_euler"]
            assert max(abs(a - b) for a, b in zip(got, idle)) <= math.radians(1.0) + TOL, (f, bone)


@pytest.mark.parametrize("rig, start", [(HOST, WAVE_AT), (TRAVELLER, T_WAVE_AT)])
def test_wave_raises_the_hand_above_the_head_and_swings_it_side_to_side_twice(layered, rig, start):
    data = layered[1]
    swing = range(start + M.WAVE_SWING[0] - 1, start + M.WAVE_SWING[1])
    across, heights = [], []
    for f in swing:
        b = pose(data, f, rig)
        chest_x = [b["chest"]["matrix_world"][i][0] for i in range(3)]   # the body's side axis
        across.append(sum(h * c for h, c in zip(b["hand.R"]["tail"], chest_x)))
        heights.append(b["hand.R"]["tail"][2])
    turns = sum(1 for i in range(1, len(across) - 1)
                if (across[i] - across[i - 1]) * (across[i + 1] - across[i]) < 0)
    assert turns >= 4 and max(across) - min(across) > 0.15
    assert min(heights) > M.BONES["head"][2][2] + 0.1, "hand above the head (and the shoulder)"


# ---------------------------------------------------------------------------
# No popping
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rig", [HOST, TRAVELLER])
def test_no_bone_jumps_anywhere_and_gesture_boundaries_are_seamless(layered, rig):
    """Every bone's world direction turns under 20 deg/frame everywhere (the wave's measured
    peak is 19.2, mid-raise), and on the frames where a gesture starts, finishes blending in,
    or ends, nothing turns more than 1 deg/frame (measured under 0.4)."""
    data = layered[1]
    for f in FRAMES[1:]:
        assert max_bone_turn(data, f, rig) < 20.0, (rig, f)
    if rig == HOST:
        edges = [LOOK_AT, LOOK_AT + 1, WAVE_AT, WAVE_AT + 1, LOOK_END + 1, WAVE_END + 1, WAVE_END + 2]
    else:
        edges = [T_WAVE_AT, T_WAVE_AT + 1]
    for f in edges:
        assert max_bone_turn(data, f, rig) < 1.0, (rig, f)


@pytest.mark.parametrize("rig, start", [(HOST, WAVE_AT), (TRAVELLER, T_WAVE_AT)])
def test_the_hand_moves_without_jerks(layered, rig, start):
    """Hand speed under 0.17 m/frame and acceleration under 0.06 m/frame^2 over the wave
    (measured 0.164 and 0.059 with the idle and the look underneath)."""
    data = layered[1]
    h = [pose(data, f, rig)["hand.R"]["tail"] for f in range(start, min(start + 61, 131))]
    assert max(math.dist(a, b) for a, b in zip(h, h[1:])) < 0.17
    acc = [math.dist([h[i + 1][k] - 2 * h[i][k] + h[i - 1][k] for k in range(3)], [0, 0, 0])
           for i in range(1, len(h) - 1)]
    assert max(acc) < 0.06
