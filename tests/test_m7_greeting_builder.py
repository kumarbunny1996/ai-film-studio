"""Milestone 7 Gate 3: The Greeting through the real builder. Run with:
pytest -m blender tests/test_m7_greeting_builder.py

Builds schemas/examples/m7_greeting.json and its idle-only twin (the same spec with the
partial-coverage gesture clips removed) with run_shot(render=False) into tmp_path, then reads
the evaluated poses of every frame with the read-only inspect_character.py and the active
camera of every frame with inspect_camera.py. Nothing is rendered.

Screen positions use the evaluated camera: x = k (d.right)/(d.view) - shift_x, and
y = (k (d.up)/(d.view) - shift_y) * width/height, with k = lens / 36 mm (sensor fit AUTO,
landscape), in frame fractions from the centre (+-0.5 = the frame edges).
"""
import copy
import importlib.util
import json
import math
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

RAW = json.loads((REPO / "schemas/examples/m7_greeting.json").read_text())
MANIFEST = AssetManifest.model_validate_json((ASSETS / "manifest.json").read_text())
INSPECT_CHAR = REPO / "blender" / "scripts" / "inspect_character.py"
INSPECT_CAM = REPO / "blender" / "scripts" / "inspect_camera.py"
_spec = importlib.util.spec_from_file_location(
    "afs_mannequin", REPO / "blender/scripts/author_assets/mannequin.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

SLOT = "OBRIG-mannequin"
HOST, TRAVELLER = "RIG-mannequin_ochre", "RIG-mannequin"
FRAMES = list(range(1, 577))
W, H = RAW["render"]["resolution"]
LOOK_AT, WAVE_B, WAVE_A, STOP = 100, 366, 438, 305
LOOK_HELD = LOOK_AT + 16
LEGS = ["hips"] + [f"{b}.{s}" for b in ("thigh", "shin", "foot") for s in "LR"]
ARM = ("upper_arm.R", "forearm.R", "hand.R")
TOL = 1e-5


def idle_only(spec: dict) -> dict:
    twin = copy.deepcopy(spec)
    for c in twin["characters"]:
        c["actions"] = [a for a in c["actions"] if MANIFEST.action(a["action_id"]).coverage == "full"]
    return twin


def build(spec: dict, root: Path, cameras: bool) -> tuple[dict, dict, dict | None]:
    report = run_shot(spec, root / "project", render=False)
    assert report["status"] == "ok" and report["returncode"] == 0, report
    blend, frames = report["blend"], ",".join(map(str, FRAMES))
    run = lambda script, *args: subprocess.run(
        [config.BLENDER_BIN, "-b", blend, "--factory-startup", "--python-exit-code", "1",
         "-P", str(script), "--", *args], capture_output=True, text=True, errors="replace",
        timeout=900)
    proc = run(INSPECT_CHAR, "--out", str(root / "chars.json"), "--frames", frames,
               "--objects", "ROOT-host,ROOT-traveller")
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    cams = None
    if cameras:
        proc = run(INSPECT_CAM, "--out", str(root / "cams.json"), "--frames", frames,
                   "--camera", "active")
        assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
        cams = {c["frame"]: c for c in json.loads((root / "cams.json").read_text())["frames"]}
    return report, json.loads((root / "chars.json").read_text()), cams


@pytest.fixture(scope="module")
def scene(tmp_path_factory):
    return build(RAW, tmp_path_factory.mktemp("m7_scene"), cameras=True)


@pytest.fixture(scope="module")
def baseline(tmp_path_factory):
    return build(idle_only(RAW), tmp_path_factory.mktemp("m7_idle_only"), cameras=False)


def pose(data, f, rig) -> dict:
    return data["frames"][str(f)]["armatures"][rig]


def root_xy(data, f, name) -> list[float]:
    m = data["frames"][str(f)]["objects"][f"ROOT-{name}"]
    return [m[0][3], m[1][3]]


def project(cams, f, p) -> tuple[float, float]:
    c = cams[f]
    v, u = c["view_dir"], c["up_dir"]
    r = [v[1] * u[2] - v[2] * u[1], v[2] * u[0] - v[0] * u[2], v[0] * u[1] - v[1] * u[0]]
    d = [p[i] - c["location"][i] for i in range(3)]
    z = sum(d[i] * v[i] for i in range(3))
    k = c["lens"] / 36
    return (k * sum(d[i] * r[i] for i in range(3)) / z - c["shift"][0],
            (k * sum(d[i] * u[i] for i in range(3)) / z - c["shift"][1]) * W / H)


def angle_deg(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b)) / (math.dist(a, [0] * len(a)) * math.dist(b, [0] * len(b)))
    return math.degrees(math.acos(max(-1.0, min(1.0, dot))))


def bone_turn(data, f, rig) -> float:
    a, b = pose(data, f - 1, rig), pose(data, f, rig)
    return max(angle_deg([a[n]["matrix_world"][i][1] for i in range(3)],
                         [b[n]["matrix_world"][i][1] for i in range(3)]) for n in a)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
def test_clips_stack_in_the_planned_order_with_the_mannequin_slot(scene):
    report, data, _ = scene
    assert report["warnings"] == ["no style template loaded; starting from an empty scene"]
    tracks = {rig: data["armatures"][rig]["nla"]["tracks"] for rig in (HOST, TRAVELLER)}
    assert [t["name"] for t in tracks[HOST]] == [
        "00_mannequin_idle", "01_mannequin_look", "02_mannequin_wave"]
    assert [t["name"] for t in tracks[TRAVELLER]] == [
        "00_mannequin_walk", "01_mannequin_idle", "02_mannequin_wave"]
    for rig in (HOST, TRAVELLER):
        assert {t["strips"][0]["slot"] for t in tracks[rig]} == {SLOT}


def test_the_cast_is_the_ochre_host_and_the_grey_traveller(scene):
    arms = scene[1]["armatures"]
    assert set(arms) == {HOST, TRAVELLER}
    assert (arms[HOST]["parent"], arms[TRAVELLER]["parent"]) == ("ROOT-host", "ROOT-traveller")


# ---------------------------------------------------------------------------
# Legs, hips and everything before the gestures
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rig", [HOST, TRAVELLER])
def test_legs_and_hips_are_identical_to_the_idle_only_build_on_every_frame(scene, baseline, rig):
    for f in FRAMES:
        a, b = pose(baseline[1], f, rig), pose(scene[1], f, rig)
        for bone in LEGS:
            for key in ("head", "tail", "rotation_euler", "location"):
                assert b[bone][key] == pytest.approx(a[bone][key], abs=1e-6), (rig, f, bone, key)


@pytest.mark.parametrize("rig, first", [(HOST, LOOK_AT), (TRAVELLER, WAVE_A)])
def test_nothing_changes_until_the_first_gesture_starts(scene, baseline, rig, first):
    for f in range(1, first + 1):
        assert pose(scene[1], f, rig) == pose(baseline[1], f, rig), (rig, f)


# ---------------------------------------------------------------------------
# Look and eyelines
# ---------------------------------------------------------------------------
def head_xy(data, f, rig) -> list[float]:
    m = pose(data, f, rig)["head"]["matrix_world"]
    return [m[0][2], m[1][2]]                          # the head's local Z is its facing


def test_b_turns_its_head_onto_a_and_holds_it_to_the_end(scene, baseline):
    data = scene[1]
    for f in range(LOOK_HELD, 577):
        to_a = [root_xy(data, f, "traveller")[i] - root_xy(data, f, "host")[i] for i in range(2)]
        assert angle_deg(head_xy(data, f, HOST), to_a) < 0.5, f
    before = [root_xy(data, 99, "traveller")[i] - root_xy(data, 99, "host")[i] for i in range(2)]
    assert angle_deg(head_xy(data, 99, HOST), before) > 35, "before the look B faces 40 deg off"


def test_a_looks_at_b_from_the_stop_on(scene):
    data = scene[1]
    for f in range(STOP, 577):
        to_b = [root_xy(data, f, "host")[i] - root_xy(data, f, "traveller")[i] for i in range(2)]
        assert angle_deg(head_xy(data, f, TRAVELLER), to_b) < 0.5, f


# ---------------------------------------------------------------------------
# Waves
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rig, start", [(HOST, WAVE_B), (TRAVELLER, WAVE_A)])
def test_each_wave_swings_twice_with_the_hand_above_the_head(scene, rig, start):
    data = scene[1]
    across, heights = [], []
    for f in range(start + M.WAVE_SWING[0] - 1, start + M.WAVE_SWING[1]):
        b = pose(data, f, rig)
        side = [b["chest"]["matrix_world"][i][0] for i in range(3)]
        across.append(sum(h * s for h, s in zip(b["hand.R"]["tail"], side)))
        heights.append(b["hand.R"]["tail"][2])
    turns = sum(1 for i in range(1, len(across) - 1)
                if (across[i] - across[i - 1]) * (across[i + 1] - across[i]) < 0)
    assert turns >= 4 and max(across) - min(across) > 0.15
    assert min(heights) > M.BONES["head"][2][2] + 0.1


@pytest.mark.parametrize("rig, end", [(HOST, WAVE_B + 60), (TRAVELLER, WAVE_A + 60)])
def test_after_each_wave_the_arm_rests_on_the_idles_mean_pose(scene, baseline, rig, end):
    last = dict(M.wave_keys())[M.WAVE["frames"] + 1]
    for f in range(end + 1, 577):
        for bone in ARM:
            got = pose(scene[1], f, rig)[bone]["rotation_euler"]
            assert got == pytest.approx([math.radians(v) for v in last[bone].values()], abs=TOL)
            idle = pose(baseline[1], f, rig)[bone]["rotation_euler"]
            assert max(abs(a - b) for a, b in zip(got, idle)) <= math.radians(1.0) + TOL


# ---------------------------------------------------------------------------
# Motion quality
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rig, edges", [
    (HOST, [LOOK_AT, LOOK_AT + 1, LOOK_AT + 24, LOOK_AT + 25, WAVE_B, WAVE_B + 1,
            WAVE_B + 60, WAVE_B + 61, WAVE_B + 62]),
    (TRAVELLER, [WAVE_A, WAVE_A + 1, WAVE_A + 60, WAVE_A + 61, WAVE_A + 62])])
def test_no_pose_pops(scene, rig, edges):
    """Every bone turns under 20 deg/frame on every frame (measured peak 19.2, mid-raise),
    and under 1 deg/frame where a gesture starts or ends (measured under 0.35)."""
    data = scene[1]
    for f in FRAMES[1:]:
        assert bone_turn(data, f, rig) < 20.0, (rig, f)
    for f in edges:
        assert bone_turn(data, f, rig) < 1.0, (rig, f)


# ---------------------------------------------------------------------------
# Framing through the evaluated cameras
# ---------------------------------------------------------------------------
def test_each_frame_is_shot_by_its_planned_camera(scene):
    cams = scene[2]
    for s in RAW["shots"]:
        for f in range(s["frame_start"], s["frame_end"] + 1):
            assert cams[f]["active_camera"] == f"CAM-{s['shot_id']}", f


@pytest.mark.parametrize("rig, start, shot_id", [(HOST, WAVE_B, "sh05_host_wave"),
                                                 (TRAVELLER, WAVE_A, "sh06_traveller_wave")])
def test_the_raised_hand_keeps_headroom_in_its_wave_shot(scene, rig, start, shot_id):
    """At least 10% of the frame height above the hand tip for the whole wave (measured 0.18
    for B in sh05, 0.19 for A in sh06)."""
    data, cams = scene[1], scene[2]
    for f in range(start, start + 61):
        assert cams[f]["active_camera"] == f"CAM-{shot_id}"
        x, y = project(cams, f, pose(data, f, rig)["hand.R"]["tail"])
        assert abs(x) < 0.45 and y < 0.4, (f, x, y)


def test_bs_wave_stays_clear_of_as_head_in_the_over_the_shoulder(scene):
    data, cams = scene[1], scene[2]
    for f in range(361, 433):
        hand = project(cams, f, pose(data, f, HOST)["hand.R"]["tail"])
        head = project(cams, f, pose(data, f, TRAVELLER)["head"]["tail"])
        assert math.dist(hand, head) > 0.25, f


@pytest.mark.parametrize("shot_id, rigs", [("sh01_wide", [HOST]),
                                           ("sh04_two_shot", [HOST, TRAVELLER]),
                                           ("sh07_end_wide", [HOST, TRAVELLER])])
def test_wides_and_two_shot_keep_whole_bodies_in_frame(scene, shot_id, rigs):
    data, cams = scene[1], scene[2]
    s = next(x for x in RAW["shots"] if x["shot_id"] == shot_id)
    for f in range(s["frame_start"], s["frame_end"] + 1):
        for rig in rigs:
            b = pose(data, f, rig)
            for bone in ("head", "hand.L", "hand.R", "shin.L", "shin.R", "foot.L", "foot.R"):
                x, y = project(cams, f, b[bone]["tail"])
                assert abs(x) < 0.45 and abs(y) < 0.45, (shot_id, f, rig, bone)


# ---------------------------------------------------------------------------
# Gate 3 visual revision: reaction cut and sh05 lamp-post clearance (evaluated)
# ---------------------------------------------------------------------------
def test_reaction_shot_shows_a_whole_and_bs_head_in_the_right_foreground(scene):
    data, cams = scene[1], scene[2]
    for f in range(125, 169):
        assert cams[f]["active_camera"] == "CAM-sh02b_host_pov"
        a = pose(data, f, TRAVELLER)
        ax = []
        for bone in ("head", "hand.L", "hand.R", "foot.L", "foot.R"):
            x, y = project(cams, f, a[bone]["tail"])
            assert abs(x) < 0.45 and abs(y) < 0.45, (f, bone)
            ax.append(x)
        hx, hy = project(cams, f, pose(data, f, HOST)["head"]["head"])   # B's neck/head joint
        assert 0.15 <= hx <= 0.45 and -0.1 <= hy <= 0.4 and hx - 0.12 > max(ax), (f, hx, hy)


def test_bs_forearm_clears_the_lamp_post_in_sh05(scene):
    """Forearm and hand (radius 0.04 m) keep over 1.5% of the frame width from the post
    (radius 0.048 m) on screen from the raise to the lowering."""
    data, cams = scene[1], scene[2]
    post = next(p for p in RAW["primitives"] if p["name"] == "lamp_post")["transform"]["location"]
    for f in range(WAVE_B + 12, WAVE_B + 49):
        c = cams[f]
        k = c["lens"] / 36
        px = project(cams, f, [post[0], post[1], 1.8])[0]
        pr = 0.048 * k / math.dist(c["location"][:2], post[:2])
        b = pose(data, f, HOST)
        pts = [b["upper_arm.R"]["tail"], b["forearm.R"]["tail"], b["hand.R"]["tail"]]
        for p0, p1 in zip(pts, pts[1:]):
            x0, x1 = project(cams, f, p0)[0], project(cams, f, p1)[0]
            lr = 0.04 * k / math.dist(c["location"][:2], p1[:2])
            assert max(min(x0, x1) - lr - (px + pr), (px - pr) - (max(x0, x1) + lr)) > 0.015, f
