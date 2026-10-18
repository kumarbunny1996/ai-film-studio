"""Milestone 10: The Traveller's Question through the real builder. Run with:
pytest -m blender tests/test_m10_travellers_question_builder.py

Builds schemas/examples/m10_travellers_question.json with run_shot(render=False) into tmp_path
and reads the evaluated poses and active camera of every frame with the read-only
inspect_character.py. Nothing is rendered.

Foot sliding is measured per ground contact: a foot is on the ground while its ankle (foot
flat) or its toe (heel raised) is within 2 mm of its rest height, and the contact's drift is
the largest horizontal distance that point moves from where it landed. The limits were fixed
before the first measurement: 3 cm per contact while turning or starting a walk (about 3-4 px
in the closest shot at 640x360), 2 mm everywhere else (straight walking, the stop, standing).
"""
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

RAW = json.loads((REPO / "schemas/examples/m10_travellers_question.json").read_text(encoding="utf-8"))
INSPECT_CHAR = REPO / "blender" / "scripts" / "inspect_character.py"
_spec = importlib.util.spec_from_file_location(
    "afs_mannequin", REPO / "blender/scripts/author_assets/mannequin.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

RIGS = {"host": "RIG-mannequin_ochre", "traveller": "RIG-mannequin"}
FRAMES = list(range(1, 577))
REST_ANKLE, REST_TOE = M.BONES["shin.L"][2][2], M.BONES["foot.L"][2][2]
GROUND_MM = 0.002
# where each character turns or starts a walk (eased crossfade): the 3 cm limit applies there.
# Turns are 104 frames (B, 2 m arc) and 40 frames (A) from the first walk; each walk start eases
# over its 8-frame crossfade. Derived from the spec's walk clips.
WALKS = {c["name"]: [a["start_frame"] for a in c["actions"] if a["action_id"] == "mannequin_walk"]
         for c in RAW["characters"]}
TURN_FRAMES = {"host": 104, "traveller": 40}
MOVING = {n: [(w[0], w[0] + TURN_FRAMES[n])] + [(s, s + 8) for s in w[1:]] for n, w in WALKS.items()}
TURN_LIMIT_M, STILL_LIMIT_M = 0.03, 0.002


@pytest.fixture(scope="module")
def scene(tmp_path_factory):
    root = tmp_path_factory.mktemp("m10")
    report = run_shot(RAW, root / "project", render=False)
    assert report["status"] == "ok" and report["returncode"] == 0, report
    run = lambda script, *args: subprocess.run(
        [config.BLENDER_BIN, "-b", report["blend"], "--factory-startup", "--python-exit-code", "1",
         "-P", str(script), "--", *args], capture_output=True, text=True, errors="replace", timeout=900)
    frames = ",".join(map(str, FRAMES))
    proc = run(INSPECT_CHAR, "--out", str(root / "chars.json"), "--frames", frames,
               "--objects", "ROOT-host,ROOT-traveller,ROOT-baton")
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    return report, json.loads((root / "chars.json").read_text())


def pose(data, f, rig) -> dict:
    return data["frames"][str(f)]["armatures"][rig]


def root_xy(data, f, name) -> list[float]:
    m = data["frames"][str(f)]["objects"][f"ROOT-{name}"]
    return [m[0][3], m[1][3]]


def contacts(data, rig, side):
    """[(first frame, last frame, drift in m)] for every ground contact of one foot."""
    out, run, kind_prev = [], [], None
    for f in FRAMES + [None]:
        kind, p = None, None
        if f is not None:
            b = pose(data, f, rig)
            ankle, toe = b[f"shin.{side}"]["tail"], b[f"foot.{side}"]["tail"]
            if ankle[2] <= REST_ANKLE + GROUND_MM:
                kind, p = "ankle", ankle
            elif toe[2] <= REST_TOE + GROUND_MM:
                kind, p = "toe", toe
        if kind and kind == kind_prev:
            run.append((f, p))
            continue
        if len(run) > 1:
            x0, y0 = run[0][1][:2]
            out.append((run[0][0], run[-1][0], max(math.hypot(q[0] - x0, q[1] - y0) for _, q in run)))
        run, kind_prev = ([(f, p)] if kind else []), kind
    return out


@pytest.mark.parametrize("name", ["host", "traveller"])
def test_planted_feet_hold_through_the_turns_starts_and_stop(scene, name):
    _, data = scene
    worst = {"moving": 0.0, "still": 0.0}
    for side in "LR":
        for f0, f1, drift in contacts(data, RIGS[name], side):
            where = "moving" if any(f0 <= e and f1 >= s for s, e in MOVING[name]) else "still"
            worst[where] = max(worst[where], drift)
            limit = TURN_LIMIT_M if where == "moving" else STILL_LIMIT_M
            assert drift <= limit, (name, side, f0, f1, round(drift, 4))
    assert worst["moving"] > 0.005, "the measurement sees the turn (not a vacuous pass)"


def test_the_baton_stays_in_the_hosts_left_hand_while_walking(scene):
    _, data = scene
    for f in FRAMES:
        baton = data["frames"][str(f)]["objects"]["ROOT-baton"]
        assert [baton[i][3] for i in range(3)] == pytest.approx(
            pose(data, f, RIGS["host"])["hand.L"]["tail"], abs=1e-5), f
    walked = math.dist([data["frames"]["209"]["objects"]["ROOT-baton"][i][3] for i in range(3)],
                       [data["frames"]["321"]["objects"]["ROOT-baton"][i][3] for i in range(3)])
    assert walked > 2.5, "the baton travels with the host"


def head_turn(data, f, rig) -> float:
    """Head yaw relative to the hips, from each bone's sideways (X) axis on the ground."""
    def yaw(bone):
        m = bone["matrix_world"]
        return math.degrees(math.atan2(m[1][0], m[0][0]))
    b = pose(data, f, rig)
    return (yaw(b["head"]) - yaw(b["hips"]) + 180) % 360 - 180


@pytest.mark.parametrize("name, look_held, walk_from", [("host", (17, WALKS["host"][0] - 1), WALKS["host"][0] + 8),
                                                     ("traveller", (121, WALKS["traveller"][0] - 1), WALKS["traveller"][0] + 8)])
def test_the_held_look_gives_way_to_the_walk(scene, name, look_held, walk_from):
    """The look turns the head 40 degrees right and holds; the walk (a full-body clip on a
    higher track) takes the head back to the front over its 8-frame crossfade."""
    _, data = scene
    rig = RIGS[name]
    for f in range(look_held[0], look_held[1] + 1, 8):
        assert head_turn(data, f, rig) == pytest.approx(-40.0, abs=0.5), (name, f)
    for f in range(walk_from, walk_from + 40, 4):
        assert abs(head_turn(data, f, rig)) < 4.0, (name, f)


def test_each_shot_is_seen_through_its_own_camera(scene):
    _, data = scene
    for s in RAW["shots"]:
        for f in (s["frame_start"], s["frame_end"]):
            assert data["frames"][str(f)]["active_camera"] == f"CAM-{s['shot_id']}", f


def test_the_evaluated_walkers_never_come_close(scene):
    _, data = scene
    assert min(math.dist(root_xy(data, f, "host"), root_xy(data, f, "traveller")) for f in FRAMES) > 1.4


def bone_turn(data, f, rig) -> float:
    """Largest change of any bone's direction (its Y axis) from frame f-1 to f, in degrees."""
    def ang(a, b):
        dot = sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))
        return math.degrees(math.acos(max(-1.0, min(1.0, dot))))
    a, b = pose(data, f - 1, rig), pose(data, f, rig)
    return max(ang([a[n]["matrix_world"][i][1] for i in range(3)], [b[n]["matrix_world"][i][1] for i in range(3)])
               for n in a)


@pytest.mark.parametrize("name", ["host", "traveller"])
def test_no_pose_pops_and_the_walk_starts_stay_close_to_the_steady_walk(scene, name):
    """M7's limit (under 20 deg/frame for every bone, every frame). Final-render review: the eased
    starts and B's stop move no bone more than 1.3 times the steady walk's worst frame (measured
    9.2 vs 7.5 deg)."""
    _, data = scene
    rig = RIGS[name]
    for f in FRAMES[1:]:
        assert bone_turn(data, f, rig) < 20.0, (name, f)
    steady = max(bone_turn(data, f, rig) for f in range(460, 520))
    stop = [s for c in RAW["characters"] if c["name"] == name for a in c["actions"]
            if a["action_id"] == "mannequin_idle" and a["start_frame"] > 1 for s in (a["start_frame"],)]
    for s in WALKS[name] + stop:
        worst = max(bone_turn(data, f, rig) for f in range(s, s + 12))
        assert worst <= 1.3 * steady, (name, s, round(worst, 2), round(steady, 2))
