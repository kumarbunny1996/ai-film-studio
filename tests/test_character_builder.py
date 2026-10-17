"""Milestone 6: characters, actions and props through the real builder. Run with:
pytest -m blender tests/test_character_builder.py

Builds schemas/examples/m6_character.json (and small variants) with run_shot(render=False)
into tmp_path, using the installed assets/ mannequin files, and reads the result back with the
fixed, read-only blender/scripts/inspect_character.py and inspect_camera.py. Only the last
test renders: the 6 cut-boundary stills of a smoke build, at 320x180, into tmp_path.
"""
import copy
import importlib.util
import json
import math
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

from workers import config
from workers.blender_job import REPO, run_shot

pytestmark = [
    pytest.mark.blender,
    pytest.mark.skipif(shutil.which(config.BLENDER_BIN) is None, reason="Blender not found"),
]

M6 = json.loads((REPO / "schemas/examples/m6_character.json").read_text())
INSPECT_CHAR = REPO / "blender" / "scripts" / "inspect_character.py"
INSPECT_CAM = REPO / "blender" / "scripts" / "inspect_camera.py"
_spec = importlib.util.spec_from_file_location(
    "afs_mannequin", REPO / "blender/scripts/author_assets/mannequin.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

RIG, SLOT = "RIG-mannequin", "OBRIG-mannequin"
FRAMES = list(range(1, 121))
SHOTS = {s["shot_id"]: s for s in M6["shots"]}
AIMS = [f"AIM-{sid}-hero" for sid in SHOTS]
# the walk ends at left mid-stance (cycle frame 17) on frame 81, where the root stops; the
# idle crossfades in over 81-89 while the NLA holds the walk's last pose
WALK_START, WALK_END, IDLE_START, BLEND = 1, 81, 81, 8
BLEND_END = IDLE_START + BLEND
X0, X1, STOP = -0.761669, 1.926779, 81          # R1S walk: x0 = X1 - 80 * WALK_M_PER_FRAME
REST_ANKLE = M.BONES["shin.L"][2][2]
TOL = 1e-5


def inspect_char(blend: str, out: Path, frames, objects=(), isolate=False) -> dict:
    cmd = [config.BLENDER_BIN, "-b", blend, "--factory-startup", "--python-exit-code", "1",
           "-P", str(INSPECT_CHAR), "--", "--out", str(out),
           "--frames", ",".join(map(str, frames)), "--objects", ",".join(objects)]
    if isolate:
        cmd.append("--isolate-tracks")
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=600)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    return json.loads(out.read_text())


def build(spec: dict, root: Path, **kw) -> dict:
    report = run_shot(spec, root / "project", **{"render": False, **kw})
    assert report["status"] == "ok" and report["returncode"] == 0, report
    return report


@pytest.fixture(scope="module")
def m6(tmp_path_factory):
    root = tmp_path_factory.mktemp("m6_build")
    report = build(M6, root)
    data = inspect_char(report["blend"], root / "chars.json", FRAMES,
                        ["ROOT-hero", "ROOT-baton", *AIMS], isolate=True)
    return report, data


@pytest.fixture(scope="module")
def m6_camera(tmp_path_factory, m6):
    root = tmp_path_factory.mktemp("m6_camera")
    proc = subprocess.run(
        [config.BLENDER_BIN, "-b", m6[0]["blend"], "--factory-startup", "--python-exit-code",
         "1", "-P", str(INSPECT_CAM), "--", "--out", str(root / "cam.json"), "--frames",
         ",".join(map(str, FRAMES)), "--project", ",".join(AIMS), "--camera", "active"],
        capture_output=True, text=True, errors="replace", timeout=600)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    return json.loads((root / "cam.json").read_text())


def pose(data, f, rig=RIG) -> dict:
    return data["frames"][str(f)]["armatures"][rig]


def matrix(data, f, name) -> list[list[float]]:
    return data["frames"][str(f)]["objects"][name]


def table_pose(action: str, action_frame: int) -> dict:
    keys = dict(M.actions()[action])
    return keys[action_frame]


def assert_matches_table(bones: dict, expected: dict, where: str) -> None:
    for bone, rot in expected["rot"].items():
        got = bones[bone]["rotation_euler"]
        assert got == pytest.approx([math.radians(v) for v in rot], abs=TOL), (where, bone)
    assert bones["hips"]["location"] == pytest.approx(expected["hips_loc"], abs=TOL), where


def channels(bones: dict) -> list[float]:
    return [v for b in sorted(bones) for v in (*bones[b]["rotation_euler"], *bones[b]["location"])]


# ---------------------------------------------------------------------------
# External actions and NLA
# ---------------------------------------------------------------------------
def test_actions_are_appended_once_and_placed_on_two_nla_tracks(m6):
    report, data = m6
    assert report["warnings"] == ["no style template loaded; starting from an empty scene"]
    assert {"mannequin_walk", "mannequin_idle"} <= set(data["actions"])
    assert not any(a.startswith("mannequin_") and "." in a for a in data["actions"])
    arm = data["armatures"][RIG]
    assert arm["parent"] == "ROOT-hero" and arm["nla"]["action"] is None
    tracks = arm["nla"]["tracks"]
    assert [t["name"] for t in tracks] == ["00_mannequin_walk", "01_mannequin_idle"]
    walk, idle = (t["strips"][0] for t in tracks)
    for s in (walk, idle):
        assert s["slot"] == SLOT and s["action_library"] is None      # appended, not linked
        assert (s["blend_type"], s["use_auto_blend"], s["scale"]) == ("REPLACE", False, 1.0)
    assert (walk["frame_start"], walk["frame_end"], walk["extrapolation"]) == (1.0, 81.0, "HOLD")
    assert walk["repeat"] == pytest.approx(80 / 32) and walk["blend_in"] == 0.0
    assert (idle["frame_start"], idle["frame_end"], idle["extrapolation"]) == (81.0, 120.0,
                                                                               "HOLD_FORWARD")
    assert idle["repeat"] == pytest.approx(39 / 48) and idle["blend_in"] == 8.0


# ---------------------------------------------------------------------------
# Evaluated poses
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("f", [1, 5, 9, 33, 41, 61, 69])
def test_walk_pose_matches_the_authored_keys(m6, f):
    action_frame = 1 + (f - WALK_START) % M.WALK["frames"]
    assert_matches_table(pose(m6[1], f), table_pose("mannequin_walk", action_frame), f"frame {f}")


@pytest.mark.parametrize("f", [93, 99, 105, 111, 117])
def test_idle_pose_matches_the_authored_keys(m6, f):
    action_frame = 1 + (f - IDLE_START) % M.IDLE["frames"]
    assert_matches_table(pose(m6[1], f), table_pose("mannequin_idle", action_frame), f"frame {f}")


def test_frame_one_is_the_walk_not_the_rest_pose(m6):
    bones, key = pose(m6[1], 1), table_pose("mannequin_walk", 1)
    for bone in ("forearm.L", "shin.L", "thigh.L"):
        authored = math.radians(key["rot"][bone][0])
        assert abs(authored) > 0.2, f"{bone} is clearly away from the rest pose at frame 1"
        assert bones[bone]["rotation_euler"][0] == pytest.approx(authored, abs=TOL), bone


def test_crossfade_is_a_linear_mix_across_the_overlap(m6):
    data = m6[1]
    iso = data["isolated"][RIG]
    walk, idle = iso["00_mannequin_walk"], iso["01_mannequin_idle"]
    for f in range(IDLE_START, BLEND_END + 1):
        w = (f - IDLE_START) / BLEND
        full, wv, iv = channels(pose(data, f)), channels(walk[str(f)]), channels(idle[str(f)])
        # REPLACE over the rest values (all 0): the muted-walk idle track is already idle * w
        assert full == pytest.approx([a * (1 - w) + b for a, b in zip(wv, iv)], abs=TOL), f
        # after its last frame the walk track holds its final (mid-stance) pose
        assert wv == pytest.approx(channels(walk[str(WALK_END)]), abs=TOL), f
    mid = str(IDLE_START + BLEND // 2)
    assert channels(pose(data, int(mid))) != pytest.approx(channels(walk[mid]), abs=1e-3)


def test_outside_the_overlap_only_one_clip_acts(m6):
    data = m6[1]
    iso = data["isolated"][RIG]
    for f in range(1, IDLE_START + 1):
        assert channels(pose(data, f)) == pytest.approx(channels(iso["00_mannequin_walk"][str(f)]), abs=TOL)
    for f in range(BLEND_END, 121):
        assert channels(pose(data, f)) == pytest.approx(channels(iso["01_mannequin_idle"][str(f)]), abs=TOL)


# ---------------------------------------------------------------------------
# Root motion, look-at and the baton
# ---------------------------------------------------------------------------
def root_x(f: int) -> float:
    return X0 + (X1 - X0) * (min(f, STOP) - 1) / (STOP - 1)


def test_root_follows_the_motion_path_facing_plus_x(m6):
    for f in FRAMES:
        m = matrix(m6[1], f, "ROOT-hero")
        assert [m[0][3], m[1][3], m[2][3]] == pytest.approx([root_x(f), 0, 0], abs=TOL), f
        assert [m[0][0], m[1][0]] == pytest.approx([0, 1], abs=TOL), "local +X turned to world +Y"
        assert [m[0][1], m[1][1]] == pytest.approx([-1, 0], abs=TOL), "local -Y (front) is world +X"


def planted(b: dict, side: str) -> bool:
    return abs(b[f"shin.{side}"]["tail"][2] - REST_ANKLE) < 1e-5


def contact_point(b: dict, side: str):
    """the ankle when it is on its rest height (foot flat), else the toe (foot tail) when it is
    on its rest height (heel raised), else None (foot in the air)"""
    if planted(b, side):
        return "ankle", b[f"shin.{side}"]["tail"]
    if abs(b[f"foot.{side}"]["tail"][2] - M.BONES[f"foot.{side}"][2][2]) < 1e-5:
        return "toe", b[f"foot.{side}"]["tail"]
    return None, None


def test_a_planted_foot_never_slides_in_the_world(m6):
    """Over the whole shot, including the stop: whenever the same contact point (ankle, or the
    toe while the heel is up) is on the ground in two consecutive frames, it has not moved."""
    pairs = 0
    for f in FRAMES[1:]:
        a, b = pose(m6[1], f - 1), pose(m6[1], f)
        for s in "LR":
            (ka, pa), (kb, pb) = contact_point(a, s), contact_point(b, s)
            if ka and ka == kb:
                pairs += 1
                assert math.hypot(pb[0] - pa[0], pb[1] - pa[1]) < 1e-5, (f, s, ka)
    assert pairs > 130


def test_heels_land_on_the_authored_contact_frames_and_never_sink(m6):
    landings = [(f, s) for f in FRAMES[1:] for s in "LR"
                if not planted(pose(m6[1], f - 1), s) and planted(pose(m6[1], f), s)]
    # walk contacts every 16 frames; the right foot's last landing is the end of the settle
    assert landings == [(9, "L"), (25, "R"), (41, "L"), (57, "R"), (73, "L"), (BLEND_END, "R")]
    for f in FRAMES:
        b = pose(m6[1], f)
        for s in "LR":
            assert b[f"shin.{s}"]["tail"][2] >= REST_ANKLE - 1e-5, (f, s)
            assert b[f"foot.{s}"]["tail"][2] >= M.BONES[f"foot.{s}"][2][2] - 1e-5, (f, s)


def test_the_stop_settles_without_sliding(m6):
    data = m6[1]
    for f in range(STOP + 1, 121):
        assert matrix(data, f, "ROOT-hero")[0][3] == pytest.approx(X1, abs=TOL), "root stopped"
    left = [pose(data, f)["shin.L"]["tail"] for f in range(IDLE_START, BLEND_END + 1)]
    right = [pose(data, f)["shin.R"]["tail"] for f in range(IDLE_START, BLEND_END + 1)]
    assert all(p == pytest.approx(left[0], abs=1e-5) for p in left), "left foot planted"
    assert left[0][0] == pytest.approx(X1, abs=1e-4), "the stop is over the planted foot"
    travel = max(math.hypot(p[0] - right[0][0], p[1] - right[0][1]) for p in right)
    assert travel < 2e-3, f"the right foot comes down {travel:.4f} m off vertical"
    zs = [p[2] for p in right]
    # held walk pose = cycle frame 17 (phase 0.5: no pelvis yaw, so the sagittal leg is exact)
    k = dict(M.actions()["mannequin_walk"])[17]
    a, b = k["rot"]["thigh.R"][0] / M.FORWARD, -k["rot"]["shin.R"][0] / M.FORWARD
    assert zs[0] == pytest.approx(M.HIP_Z + k["hips_loc"][1] - M.ankle_drop(a, b), abs=1e-4)
    assert zs == sorted(zs, reverse=True) and zs[-1] == pytest.approx(REST_ANKLE, abs=1e-5)


def test_aim_points_follow_the_root_at_each_shots_height(m6):
    for sid, shot in SHOTS.items():
        h = shot["camera"]["look_at_height"]
        for f in FRAMES:
            m = matrix(m6[1], f, f"AIM-{sid}-hero")
            assert [m[0][3], m[1][3], m[2][3]] == pytest.approx([root_x(f), 0, h], abs=TOL), (sid, f)


def test_each_shot_camera_tracks_the_walking_character(m6_camera):
    for fr in m6_camera["frames"]:
        f = fr["frame"]
        sid = next(s for s, sh in SHOTS.items() if sh["frame_start"] <= f <= sh["frame_end"])
        assert fr["active_camera"] == f"CAM-{sid}", f
        offset = SHOTS[sid]["camera"].get("framing", {}).get("subject_offset", [0, 0])
        x, y, _ = fr["projected"][f"AIM-{sid}-hero"]
        assert [x, y] == pytest.approx([0.5 + offset[0], 0.5 + offset[1]], abs=1e-3), (sid, f)


def project(cam: dict, p: list[float], width=640, height=360) -> tuple[float, float]:
    """Normalised frame position of world point p for an inspect_camera frame (sensor 36 mm,
    fit AUTO, landscape): 0,0 bottom-left, 1,1 top-right. Lens shift moves the frame, so it
    is subtracted."""
    loc, view, up = cam["location"], cam["view_dir"], cam["up_dir"]
    right = [view[1] * up[2] - view[2] * up[1], view[2] * up[0] - view[0] * up[2],
             view[0] * up[1] - view[1] * up[0]]
    d = [p[i] - loc[i] for i in range(3)]
    depth, k = sum(d[i] * view[i] for i in range(3)), cam["lens"] / 36.0
    x = sum(d[i] * right[i] for i in range(3)) / depth * k + 0.5 - cam["shift"][0]
    y = (sum(d[i] * up[i] for i in range(3)) / depth * k - cam["shift"][1]) * width / height + 0.5
    return x, y


def test_tracking_camera_dollies_until_the_stop_then_holds(m6_camera):
    """sh02 travels on its original 49 -> 88 line until frame 81, then holds: once the
    character has stopped, neither the camera position nor its pan changes."""
    frames = {fr["frame"]: fr for fr in m6_camera["frames"]}
    for f in range(49, STOP + 1):
        x = -0.6 + 2.0 * (f - 49) / (88 - 49)
        assert frames[f]["location"] == pytest.approx([x, -5.5, 1.4], abs=1e-5), f
    for f in range(STOP, 89):
        assert frames[f]["location"] == pytest.approx(frames[STOP]["location"], abs=1e-6), f
        assert frames[f]["view_dir"] == pytest.approx(frames[STOP]["view_dir"], abs=1e-6), f


def test_tracking_shot_leaves_room_below_the_feet_and_above_the_head(m6, m6_camera):
    shot = SHOTS["sh02_track"]
    soles, heads = [], []
    for fr in m6_camera["frames"]:
        f = fr["frame"]
        aim_name = f"AIM-{fr['active_camera'][len('CAM-'):]}-hero"
        aim = [matrix(m6[1], f, aim_name)[i][3] for i in range(3)]
        assert project(fr, aim) == pytest.approx(tuple(fr["projected"][aim_name][:2]), abs=1e-4)
        if not shot["frame_start"] <= f <= shot["frame_end"]:
            continue
        b = pose(m6[1], f)
        # sole: the foot is a 0.045 m radius cylinder around the foot bone
        soles.append(min(project(fr, [*b[f"foot.{s}"]["tail"][:2],
                                      b[f"foot.{s}"]["tail"][2] - 0.045])[1] for s in "LR"))
        heads.append(project(fr, b["head"]["tail"])[1])
    assert min(soles) >= 0.08, f"feet only {min(soles):.3f} of the frame above the bottom edge"
    assert max(heads) <= 0.92, f"head top at {max(heads):.3f} of the frame height"


def rot3(m):
    return [row[:3] for row in m]


def mat_t_mul(a, b):
    """a^T @ b for 3x3 lists."""
    return [[sum(a[k][i] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def test_baton_rides_on_the_hand_r_tail(m6):
    data = m6[1]
    for f in FRAMES:
        hand = pose(data, f)["hand.R"]
        baton = matrix(data, f, "ROOT-baton")
        assert [baton[i][3] for i in range(3)] == pytest.approx(hand["tail"], abs=TOL), f
        # transform [180, 0, 0] in bone space: baton axes = hand axes with Y and Z flipped
        rel = mat_t_mul(rot3(hand["matrix_world"]), rot3(baton))
        assert sum(rel, []) == pytest.approx([1, 0, 0, 0, -1, 0, 0, 0, -1], abs=1e-5), f
    a, b = matrix(data, 1, "ROOT-baton"), matrix(data, 9, "ROOT-baton")
    travel = math.dist([a[i][3] for i in range(3)], [b[i][3] for i in range(3)])
    assert travel > 0.3, "the baton travels with the walking hand"


# ---------------------------------------------------------------------------
# Variants
# ---------------------------------------------------------------------------
def test_first_clip_with_the_default_blend_in_starts_in_the_walk_pose(tmp_path, m6):
    """Reproduces the Milestone 6 builder fix: with the schema default blend_in (6) on the
    first clip, Blender faded the lowest NLA strip in from the rest pose over frames 1-7."""
    d = copy.deepcopy(M6)
    del d["characters"][0]["actions"][0]["blend_in"]
    report = build(d, tmp_path)
    data = inspect_char(report["blend"], tmp_path / "chars.json", [1, 2, 4, 7, 9])
    walk = data["armatures"][RIG]["nla"]["tracks"][0]["strips"][0]
    assert walk["blend_in"] == 0.0
    for f in (1, 2, 4, 7, 9):
        assert channels(pose(data, f)) == pytest.approx(channels(pose(m6[1], f)), abs=TOL), f


def test_two_instances_of_one_character_share_actions_but_not_tracks(tmp_path, m6):
    d = copy.deepcopy(M6)
    d["characters"].append({
        "name": "extra", "asset_id": "mannequin",
        "transform": {"location": [0.0, 3.0, 0.0]},
        "actions": [{"action_id": "mannequin_idle", "start_frame": 1, "end_frame": 120}]})
    report = build(d, tmp_path)
    data = inspect_char(report["blend"], tmp_path / "chars.json", [1, 13, 37, 97],
                        ["ROOT-hero", "ROOT-extra"])
    assert set(data["armatures"]) == {RIG, f"{RIG}.001"}
    assert [a for a in data["actions"] if a.startswith("mannequin_")] == ["mannequin_idle",
                                                                          "mannequin_walk"]
    extra = data["armatures"][f"{RIG}.001"]
    assert extra["parent"] == "ROOT-extra"
    assert [t["name"] for t in extra["nla"]["tracks"]] == ["00_mannequin_idle"]
    assert extra["nla"]["tracks"][0]["strips"][0]["slot"] == SLOT
    for f in (1, 13, 37, 97):
        assert_matches_table(pose(data, f, f"{RIG}.001"),
                             table_pose("mannequin_idle", 1 + (f - 1) % 48), f"extra {f}")
        assert channels(pose(data, f)) == pytest.approx(channels(pose(m6[1], f)), abs=TOL)
        m = matrix(data, f, "ROOT-extra")
        assert [m[0][3], m[1][3], m[2][3]] == pytest.approx([0, 3, 0], abs=TOL)


# ---------------------------------------------------------------------------
# Smoke render (temporary): both sides of every cut, 320x180
# ---------------------------------------------------------------------------
def png_size(path: Path) -> tuple[int, int]:
    return struct.unpack(">II", path.read_bytes()[16:24])


def test_smoke_render_of_the_cut_frames(tmp_path):
    report = run_shot(M6, tmp_path / "project", smoke=True)
    assert report["status"] == "ok" and report["returncode"] == 0, report
    assert report["rendered_frames"] == [1, 48, 49, 88, 89, 120]
    pngs = sorted(Path(report["frames_dir"]).glob("m6_character_*.png"))
    assert [p.name for p in pngs] == [f"m6_character_{f:04d}.png" for f in (1, 48, 49, 88, 89, 120)]
    assert all(png_size(p) == (320, 180) for p in pngs)
    assert report["memory_mb"]["peak_working_set"] < 1024
