"""Milestone 6: the mannequin authoring script and asset inspector in Blender. Run with:
pytest -m blender tests/test_mannequin_assets.py

Every run authors into pytest temporary directories only; nothing is written to assets/.
The assets are read back with the fixed, read-only blender/scripts/inspect_asset.py, which
appends them into an empty session the way build_scene.py does.
"""
import hashlib
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from workers import config
from workers.blender_job import REPO

pytestmark = [
    pytest.mark.blender,
    pytest.mark.skipif(shutil.which(config.BLENDER_BIN) is None, reason="Blender not found"),
]

AUTHOR = REPO / "blender" / "scripts" / "author_assets" / "mannequin.py"
INSPECT = REPO / "blender" / "scripts" / "inspect_asset.py"
_spec = importlib.util.spec_from_file_location("afs_mannequin", AUTHOR)
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

SLOT = "OBRIG-mannequin"
REPEAT = 2
EVAL_FRAMES = list(range(1, 1 + REPEAT * max(M.ACTION_FRAMES.values()) + 1))
# Structural fingerprints of the three files, as authored by Blender 5.2.2 LTS. A change here
# means the authoring script (or Blender's data model) changed what it builds.
GOLDEN_BLENDER = "5.2.2 LTS"
GOLDEN = {
    "characters/mannequin.blend": "8c42de5c7c482e813dd6433e87da700e5400cd21fbdaff20efe91b55d270c6b8",
    # R1S walk cycle (swing foot under the hips at mid-swing) and the soft-knee idle that
    # stands on the walk's frame-17 leg; was 8a300710... for the original straight-leg walk
    "actions/mannequin_actions.blend": "91d2b2b6d7ebf6c57fbee2ea6580dcdd2fae74fc4d2c53aae229a91c93f382ec",
    "props/mannequin_baton.blend": "e1fc43532ff274d3b907fe6c75b1edbb47b090b799c862e283482f248abfdd53",
}
KEYS = [p.as_posix() for p in M.OUTPUTS]


def author(out_root: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [config.BLENDER_BIN, "-b", "--factory-startup", "--python-exit-code", "1",
         "-P", str(AUTHOR), "--", "--out-root", str(out_root), *extra],
        capture_output=True, text=True, errors="replace", timeout=300)


def inspect(blend: Path, out: Path, *extra: str) -> dict:
    proc = subprocess.run(
        [config.BLENDER_BIN, "-b", "--factory-startup", "--python-exit-code", "1",
         "-P", str(INSPECT), "--", "--blend", str(blend), "--out", str(out), *extra],
        capture_output=True, text=True, errors="replace", timeout=300)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    return json.loads(out.read_text())


def authored_set(root: Path, work: Path) -> dict:
    proc = author(root)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    reports = {k: inspect(root / k, work / f"{Path(k).stem}.json") for k in KEYS}
    reports["evaluated"] = inspect(
        root / KEYS[0], work / "evaluated.json", "--evaluate-actions", str(root / KEYS[1]),
        "--armature", M.ARMATURE, "--frames", ",".join(map(str, EVAL_FRAMES)),
        "--repeat", str(REPEAT))["evaluated"]
    return reports


@pytest.fixture(scope="module")
def run_a(tmp_path_factory):
    base = tmp_path_factory.mktemp("mannequin_a")
    return base / "assets", authored_set(base / "assets", base)


@pytest.fixture(scope="module")
def run_b(tmp_path_factory):
    base = tmp_path_factory.mktemp("mannequin_b")
    return base / "assets", authored_set(base / "assets", base)


def digest(root: Path) -> dict[str, tuple[str, int]]:
    return {k: (hashlib.sha256((root / k).read_bytes()).hexdigest(), (root / k).stat().st_mtime_ns)
            for k in KEYS if (root / k).exists()}


# ---------------------------------------------------------------------------
# Files, contents and determinism
# ---------------------------------------------------------------------------
def test_writes_exactly_the_three_asset_files(run_a):
    root, _ = run_a
    files = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    assert files == sorted(KEYS), "no .tmp.blend or other leftovers"


def test_files_hold_only_the_expected_datablocks(run_a):
    _, rep = run_a
    assert rep[KEYS[0]]["contents"] == {
        "armatures": [M.ARMATURE], "collections": [M.CHARACTER_COLLECTION],
        "materials": ["MAT-mannequin_accent", "MAT-mannequin_body"],
        "meshes": [M.BODY], "objects": [M.BODY, M.ARMATURE]}
    assert rep[KEYS[1]]["contents"] == {"actions": ["mannequin_idle", "mannequin_walk"]}
    assert rep[KEYS[2]]["contents"] == {
        "collections": [M.PROP_COLLECTION], "materials": ["MAT-mannequin_baton"],
        "meshes": [M.PROP_OBJECT], "objects": [M.PROP_OBJECT]}


def test_two_authoring_runs_have_identical_structural_fingerprints(run_a, run_b):
    for k in KEYS:
        assert run_a[1][k]["fingerprint"] == run_b[1][k]["fingerprint"], k


def test_fingerprints_match_the_pinned_golden_values(run_a):
    rep = run_a[1]
    if rep[KEYS[0]]["blender_version"] != GOLDEN_BLENDER:
        pytest.skip(f"golden fingerprints were pinned with Blender {GOLDEN_BLENDER}")
    assert {k: rep[k]["fingerprint"] for k in KEYS} == GOLDEN


# ---------------------------------------------------------------------------
# Character
# ---------------------------------------------------------------------------
def test_rig_matches_the_skeleton_table_in_rest_pose(run_a):
    rep = run_a[1][KEYS[0]]
    bones = rep["armatures"][M.ARMATURE]["bones"]
    assert set(bones) == set(M.BONES)
    for name, (parent, head, tail, connected) in M.BONES.items():
        b = bones[name]
        assert (b["parent"], b["connected"], b["deform"]) == (parent, connected, True), name
        assert b["head"] == pytest.approx(head, abs=1e-6) and b["tail"] == pytest.approx(tail, abs=1e-6)
    rig = rep["objects"][M.ARMATURE]
    assert rig["parent"] is None and not rig["has_animation_data"]
    for name, pb in rig["pose"].items():
        assert pb == {"rotation_mode": "XYZ", "location": [0.0] * 3,
                      "rotation_euler": [0.0] * 3, "scale": [1.0] * 3}, name


def test_body_is_rigidly_skinned_to_the_rig(run_a):
    rep = run_a[1][KEYS[0]]
    body = rep["objects"][M.BODY]
    assert (body["parent"], body["parent_type"]) == (M.ARMATURE, "OBJECT")
    assert body["modifiers"] == [{"type": "ARMATURE", "object": M.ARMATURE}]
    assert not body["has_animation_data"] and body["constraints"] == []
    assert set(body["vertex_groups"]) == set(M.BONES)
    assert all(g["vertices"] > 0 and g["weights"] == [1.0] for g in body["vertex_groups"].values())
    assert body["groups_per_vertex"] == [1], "every vertex belongs to exactly one bone"


def test_body_mesh_is_low_poly_stands_on_the_ground_and_faces_minus_y(run_a):
    mesh = run_a[1][KEYS[0]]["meshes"][M.BODY]
    (x0, y0, z0), (x1, y1, z1) = mesh["bounds"]
    assert mesh["triangles"] < 3000
    assert z0 == pytest.approx(0.0, abs=2e-3) and z1 == pytest.approx(1.75, abs=1e-6)
    assert y0 < -0.15 and y1 <= 0.1, "toes reach forward (-Y), nothing sticks out behind"
    assert x0 == pytest.approx(-x1, abs=1e-6)
    assert mesh["materials"] == ["MAT-mannequin_body", "MAT-mannequin_accent"]
    assert mesh["material_indices"] == [0, 1]


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------
def test_each_action_has_one_object_slot_and_a_closed_frame_range(run_a):
    acts = run_a[1][KEYS[1]]["actions"]
    for name, frames in M.ACTION_FRAMES.items():
        a = acts[name]
        assert a["slots"] == [{"identifier": SLOT, "target_id_type": "OBJECT"}], name
        assert a["layers"] == 1
        assert a["use_frame_range"] and not a["use_cyclic"]
        # build_scene.place_actions uses frame_range[1] - frame_range[0] as the loop length
        assert a["frame_range"] == [1.0, 1.0 + frames]


def test_actions_key_the_same_channels_with_closed_loops(run_a):
    acts = run_a[1][KEYS[1]]["actions"]
    expected = {f'{SLOT}|pose.bones["{b}"].rotation_euler[{i}]' for b in M.BONES for i in range(3)}
    expected |= {f'{SLOT}|pose.bones["hips"].location[{i}]' for i in range(3)}
    tables = M.actions()
    for name, act in acts.items():
        assert set(act["fcurves"]) == expected, name
        frames = [f for f, _ in tables[name]]
        for path, fc in act["fcurves"].items():
            assert [k[0] for k in fc["keys"]] == frames, path
            assert fc["keys"][0][1] == fc["keys"][-1][1], f"{name} {path} does not loop"
            assert fc["interpolation"] == ["BEZIER"] and fc["modifiers"] == []


def test_action_keys_match_the_pose_tables(run_a):
    import math
    acts = run_a[1][KEYS[1]]["actions"]
    for name, keys in M.actions().items():
        fcurves = acts[name]["fcurves"]
        for i, (frame, pose) in enumerate(keys):
            for bone, rot in pose["rot"].items():
                for axis in range(3):
                    got = fcurves[f'{SLOT}|pose.bones["{bone}"].rotation_euler[{axis}]']["keys"][i]
                    assert got[1] == pytest.approx(math.radians(rot[axis]), abs=2e-6)
            for axis in range(3):
                got = fcurves[f'{SLOT}|pose.bones["hips"].location[{axis}]']["keys"][i]
                assert got[1] == pytest.approx(pose["hips_loc"][axis], abs=2e-6)


# ---------------------------------------------------------------------------
# Actions evaluated on the appended rig through an NLA strip (Blender 5.2 layered actions)
# ---------------------------------------------------------------------------
def test_strips_new_assigns_the_slot_of_an_appended_action(run_a):
    ev = run_a[1]["evaluated"]
    for name, frames in M.ACTION_FRAMES.items():
        assert ev[name]["strip_slot"] == SLOT
        assert ev[name]["strip_frames"] == [1.0, 1.0 + REPEAT * frames]


@pytest.mark.parametrize("name", list(M.ACTION_FRAMES))
def test_repeated_strip_loops_without_a_pop(run_a, name):
    sampled, n = run_a[1]["evaluated"][name]["frames"], M.ACTION_FRAMES[name]
    for f in range(1, n + 1):
        assert sampled[str(f)] == sampled[str(f + n)], f"{name}: frame {f} vs {f + n}"
    assert sampled["1"] == sampled[str(1 + REPEAT * n)]


def line_y(top, bottom, z):
    t = (z - top[2]) / (bottom[2] - top[2])
    return top[1] + t * (bottom[1] - top[1])


def test_walk_knees_bend_backward_and_elbows_forward(run_a):
    walk = run_a[1]["evaluated"]["mannequin_walk"]["frames"]
    for f, b in walk.items():
        for s in "LR":
            hip, knee, ankle = b[f"thigh.{s}"]["head"], b[f"thigh.{s}"]["tail"], b[f"shin.{s}"]["tail"]
            if abs(hip[2] - ankle[2]) > 1e-6:
                assert knee[1] <= line_y(hip, ankle, knee[2]) + 1e-6, (f, s, "knee bends forward")
            sh, el, wr = (b[f"upper_arm.{s}"]["head"], b[f"upper_arm.{s}"]["tail"],
                          b[f"forearm.{s}"]["tail"])
            assert el[1] >= line_y(sh, wr, el[2]) - 1e-6, (f, s, "elbow bends backward")


def test_walk_swings_the_left_leg_forward_at_a_quarter_cycle(run_a):
    """Pins FORWARD on the evaluated rig (the rig faces -Y): at the left heel strike the left
    leg is forward, the legs are split with the right one behind, and the arms counter-swing.
    The right-thigh check was revised for the R1S walk: the old `thigh.R tail y > 0.15` came
    from the original walk's straight +-25 deg legs and is out of reach at the 18 deg stride
    (a straight trailing leg gives 0.45 sin 18 = 0.139). It never tested hip extension, which
    the current cycle lacks (the trailing thigh stays in front of vertical): a known limitation
    recorded in the Milestone 6 review, not something this test establishes."""
    b = run_a[1]["evaluated"]["mannequin_walk"]["frames"]["9"]
    assert b["thigh.L"]["tail"][1] < -0.15
    assert b["thigh.R"]["tail"][1] - b["thigh.L"]["tail"][1] > 0.15, "legs split, right behind left"
    assert b["shin.R"]["tail"][1] - b["thigh.R"]["head"][1] > 0.2, "trailing foot well behind its hip"
    assert b["upper_arm.L"]["tail"][1] > b["upper_arm.R"]["tail"][1], "arms counter-swing"


def test_walk_keeps_a_contact_point_on_its_rest_height_at_every_key(run_a):
    """At every key one foot is on the ground: its ankle on its rest height (foot flat) or,
    while the heel rises, its toe (foot tail) on its rest height."""
    walk = run_a[1]["evaluated"]["mannequin_walk"]["frames"]
    rest, toe = M.BONES["shin.L"][2][2], M.BONES["foot.L"][2][2]
    for f in range(1, 1 + REPEAT * M.ACTION_FRAMES["mannequin_walk"] + 1, M.WALK["step"]):
        b = walk[str(f)]
        gap = min(min(abs(b[f"shin.{s}"]["tail"][2] - rest), abs(b[f"foot.{s}"]["tail"][2] - toe)) for s in "LR")
        assert gap < 1e-4, f
    # mid-swing clearance at cycle frame 1 (phase 0: no pelvis yaw, so the sagittal leg is exact)
    k = dict(M.actions()["mannequin_walk"])[1]
    a, b = k["rot"]["thigh.L"][0] / M.FORWARD, -k["rot"]["shin.L"][0] / M.FORWARD
    swing = walk["1"]["shin.L"]["tail"][2]
    assert swing == pytest.approx(M.HIP_Z + k["hips_loc"][1] - M.ankle_drop(a, b), abs=1e-5)
    assert swing >= rest + M.WALK_CLEAR_M, "mid-swing clearance"


def test_walk_stance_ankle_moves_back_at_exactly_the_walk_speed(run_a):
    """In place (no root motion), a planted contact point must move backward (+Y: the rig faces
    -Y) at WALK_M_PER_FRAME, so that root travel at that speed holds it still in the world: the
    toe for the whole stance (heel strike to toe-off, 16 frame steps), the ankle while the foot
    is flat (until the heel rises after 11.2 frames: 11 frame steps)."""
    walk = run_a[1]["evaluated"]["mannequin_walk"]["frames"]
    rest, toe_rest = M.BONES["shin.L"][2][2], M.BONES["foot.L"][2][2]
    # lateral tolerance: the ankle is solved onto its footprint (1e-6); the toe follows the
    # yawing foot and drifts sideways by up to 4e-6 m per frame
    for bone, end, z_rest, steps, x_tol in (("shin", "tail", rest, 11, 1e-6), ("foot", "tail", toe_rest, 16, 1e-5)):
        pairs = 0
        for f in range(2, 1 + REPEAT * M.ACTION_FRAMES["mannequin_walk"] + 1):
            for s in "LR":
                a, b = walk[str(f - 1)][f"{bone}.{s}"][end], walk[str(f)][f"{bone}.{s}"][end]
                if abs(a[2] - z_rest) < 1e-5 and abs(b[2] - z_rest) < 1e-5:
                    pairs += 1
                    assert b[1] - a[1] == pytest.approx(M.WALK_M_PER_FRAME, abs=1e-5), (bone, f, s)
                    assert b[0] == pytest.approx(a[0], abs=x_tol), (bone, f, s)
        assert pairs == 2 * REPEAT * steps, f"{bone}: each foot is planted for {steps} frame steps per cycle"
    landings = [(f, s) for f in range(2, 66) for s in "LR"
                if walk[str(f - 1)][f"shin.{s}"]["tail"][2] > rest + 1e-5
                and abs(walk[str(f)][f"shin.{s}"]["tail"][2] - rest) < 1e-5]
    assert landings == [(9, "L"), (25, "R"), (41, "L"), (57, "R")]


def test_idle_keeps_both_feet_planted(run_a):
    idle = run_a[1]["evaluated"]["mannequin_idle"]["frames"]
    rest = {s: M.BONES[f"shin.{s}"][2] for s in "LR"}
    for f, b in idle.items():
        for s in "LR":
            assert b[f"shin.{s}"]["tail"] == pytest.approx(list(rest[s]), abs=1e-6), (f, s)
    assert idle["1"]["chest"]["tail"] != idle["13"]["chest"]["tail"], "the chest breathes"


# ---------------------------------------------------------------------------
# Prop
# ---------------------------------------------------------------------------
def test_baton_prop_has_its_grip_at_the_origin(run_a):
    rep = run_a[1][KEYS[2]]
    obj = rep["objects"][M.PROP_OBJECT]
    assert obj["parent"] is None and obj["modifiers"] == [] and not obj["has_animation_data"]
    assert rep["collections"] == {M.PROP_COLLECTION: [M.PROP_OBJECT]}
    assert rep["meshes"][M.PROP_OBJECT]["bounds"] == [[-0.015, -0.015, -0.3], [0.015, 0.015, 0.6]]


# ---------------------------------------------------------------------------
# Overwrite protection
# ---------------------------------------------------------------------------
@pytest.fixture
def authored_once(tmp_path):
    root = tmp_path / "assets"
    proc = author(root)
    assert proc.returncode == 0, proc.stderr[-2000:]
    return root


def test_existing_outputs_are_never_overwritten_without_force(authored_once):
    before = digest(authored_once)
    proc = author(authored_once)
    assert proc.returncode != 0
    assert "REFUSED" in proc.stderr and "--force" in proc.stderr
    assert digest(authored_once) == before


def test_one_existing_output_blocks_writing_the_others(authored_once):
    for k in KEYS[1:]:
        (authored_once / k).unlink()
    before = digest(authored_once)
    proc = author(authored_once)
    assert proc.returncode != 0 and "REFUSED" in proc.stderr
    assert digest(authored_once) == before
    assert not any((authored_once / k).exists() for k in KEYS[1:])
    assert not list(authored_once.rglob("*.tmp.blend"))


def test_force_overwrites_with_the_same_structure(authored_once, tmp_path, run_a):
    before = digest(authored_once)
    proc = author(authored_once, "--force")
    assert proc.returncode == 0, proc.stderr[-2000:]
    after = digest(authored_once)
    assert all(after[k][1] != before[k][1] for k in KEYS), "every file was rewritten"
    for k in KEYS:
        rep = inspect(authored_once / k, tmp_path / f"{Path(k).stem}.json")
        assert rep["fingerprint"] == run_a[1][k]["fingerprint"], k
    assert not list(authored_once.rglob("*.tmp.blend"))


def test_out_root_is_required(tmp_path):
    proc = subprocess.run(
        [config.BLENDER_BIN, "-b", "--factory-startup", "--python-exit-code", "1",
         "-P", str(AUTHOR), "--"], cwd=tmp_path,
        capture_output=True, text=True, errors="replace", timeout=300)
    assert proc.returncode != 0 and "--out-root" in proc.stderr
    assert list(tmp_path.iterdir()) == []
