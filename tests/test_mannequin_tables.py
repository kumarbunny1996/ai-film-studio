"""Milestone 6: the mannequin authoring script's skeleton and pose tables, without Blender.

blender/scripts/author_assets/mannequin.py imports bpy only inside its authoring functions,
so its tables load in plain Python. The Blender side is in tests/test_mannequin_assets.py.
"""
import importlib.util
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "blender" / "scripts" / "author_assets" / "mannequin.py"


def load():
    spec = importlib.util.spec_from_file_location("afs_mannequin", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = load()
EXPECTED_BONES = {"hips", "spine", "chest", "neck", "head",
                  *(f"{b}.{s}" for s in "LR"
                    for b in ("upper_arm", "forearm", "hand", "thigh", "shin", "foot"))}


def test_module_loads_without_bpy():
    import sys
    assert "bpy" not in sys.modules


def test_skeleton_has_the_17_named_bones_with_valid_parents():
    assert set(M.BONES) == EXPECTED_BONES and len(M.BONES) == 17
    roots = [n for n, (parent, *_) in M.BONES.items() if parent is None]
    assert roots == ["hips"]
    for name, (parent, head, tail, connected) in M.BONES.items():
        assert math.dist(head, tail) > 0.05, name
        if parent:
            assert parent in M.BONES
            if connected:
                assert head == M.BONES[parent][2], f"{name} is connected but not at its parent's tail"


def test_skeleton_is_mirror_symmetric():
    for name, (parent, head, tail, connected) in M.BONES.items():
        if name.endswith(".L"):
            p, h, t, c = M.BONES[name[:-1] + "R"]
            assert (h, t) == ((-head[0], head[1], head[2]), (-tail[0], tail[1], tail[2]))
            assert c == connected and (p or "").replace(".R", ".L") == (parent or "")


def test_proportions_and_facing():
    assert M.BONES["head"][2][2] == pytest.approx(1.75)
    assert M.BONES["foot.L"][2][1] < 0, "toes point -Y (the character faces -Y)"
    assert M.THIGH_M == pytest.approx(0.45) and M.SHIN_M == pytest.approx(0.42)


def test_every_bone_has_one_body_part():
    assert set(M.PARTS) == set(M.BONES)
    assert {shape for shape, *_ in M.PARTS.values()} <= {"box", "ball", "cyl"}
    assert {mat for *_, mat in M.PARTS.values()} <= set(M.MATERIALS)


def test_outputs_mirror_the_assets_layout():
    assert [p.as_posix() for p in M.OUTPUTS] == [
        "characters/mannequin.blend", "actions/mannequin_actions.blend",
        "props/mannequin_baton.blend"]
    assert M.RIG_TYPE == "afs_mannequin_v1"


@pytest.mark.parametrize("name, frames, step", [("mannequin_walk", 32, 1), ("mannequin_idle", 48, 6)])
def test_key_frames_and_loop_closure(name, frames, step):
    keys = M.actions()[name]
    assert [f for f, _ in keys] == list(range(1, frames + 2, step))
    assert M.ACTION_FRAMES[name] == frames
    assert keys[-1][1] == keys[0][1], "the last key must repeat the first exactly"


def test_both_actions_key_the_same_full_channel_set():
    for name, keys in M.actions().items():
        for frame, pose in keys:
            assert set(pose["rot"]) == set(M.BONES), (name, frame)
            assert all(len(v) == 3 for v in pose["rot"].values())
            assert len(pose["hips_loc"]) == 3


def test_key_values_are_finite_rounded_and_never_negative_zero():
    for keys in M.actions().values():
        for _, pose in keys:
            for v in [*sum(pose["rot"].values(), []), *pose["hips_loc"]]:
                assert math.isfinite(v) and v == round(v, 6)
                assert math.copysign(1.0, v) > 0 or v != 0


def leg(pose, side):
    """thigh forward angle a and knee flexion b, in degrees, back out of the pose."""
    return (pose["rot"][f"thigh.{side}"][0] / M.FORWARD,
            -pose["rot"][f"shin.{side}"][0] / M.FORWARD)


WALK_KEYS = dict(M.actions()["mannequin_walk"])


def walk_key(frame):
    """walk key at an unwrapped frame (frame 33 = frame 1 of the next cycle)"""
    return WALK_KEYS[1 + (frame - 1) % M.WALK["frames"]]


def ankle(frame, side):
    """World (forward, lateral, height) of a walk ankle with the root travelling
    WALK_M_PER_FRAME, from the keyed rotations through the 3D hips -> thigh -> shin chain
    (the pelvis yaws, so the hip joints move). The rig faces -Y: forward is -y."""
    k = walk_key(frame)
    a = M.leg_fk(side, k["rot"]["hips"], k["hips_loc"], k["rot"][f"thigh.{side}"], k["rot"][f"shin.{side}"])[2]
    return (frame - 1) * M.WALK_M_PER_FRAME - a[1], a[0], a[2]


def test_walk_stance_ankle_sits_on_the_planted_footprint_in_3d():
    """Every stance key puts the ankle exactly where the planted foot model says: on its rest
    height over the footprint while the foot is flat, then on the arc about the fixed toe while
    the heel rises. Two cycles, unwrapped."""
    for f in range(1, 2 * M.WALK["frames"] + 1):
        for s, x_side in (("L", 0.1), ("R", -0.1)):
            p = (f - 1) / M.WALK["frames"]
            lg = M.walk_leg(p, s)
            if lg["stance"]:
                x, z, _ = M.walk_stance_foot(p, lg["q"])
                assert ankle(f, s) == pytest.approx((x, x_side, z), abs=2e-6), (f, s)
    for frame, pose in WALK_KEYS.items():
        assert pose["hips_loc"][0] == pose["hips_loc"][2] == 0.0


def test_walk_knees_only_flex_feet_follow_the_heel_rise_and_legs_alternate():
    half = M.WALK["frames"] // 2
    for frame, pose in WALK_KEYS.items():
        for s in "LR":
            a, b = leg(pose, s)
            assert b >= 0, (frame, s)
            lg = M.walk_leg((frame - 1) / M.WALK["frames"], s)
            if lg["stance"]:              # flat foot (0), then toe-down by the heel-rise pitch
                foot = pose["rot"][f"foot.{s}"][0] / M.FORWARD
                assert a - b + foot == pytest.approx(-math.degrees(lg["pitch"]), abs=1e-5), (frame, s)
        # the right leg does what the left did half a cycle earlier
        later = walk_key(frame + half)
        for bone in ("thigh", "shin", "foot"):
            assert later["rot"][f"{bone}.R"][0] == pytest.approx(pose["rot"][f"{bone}.L"][0], abs=1e-6), frame
    # left heel strike: the ankle drops onto its rest height STEP_HALF_M ahead of the hips
    assert ankle(8, "L")[2] > M.ANKLE_Z + 0.008
    assert ankle(9, "L") == pytest.approx((8 * M.WALK_M_PER_FRAME + M.STEP_HALF_M, 0.1, M.ANKLE_Z), abs=2e-6)


def test_the_planted_foot_is_stationary_and_heels_land_at_contact():
    frames = range(1, M.WALK["frames"] + 2)
    down = {s: [f for f in frames if ankle(f, s)[2] == pytest.approx(M.ANKLE_Z, abs=2e-6)] for s in "LR"}
    # flat foot from the heel strike until the heel rises (q > WALK_Q_HEEL, 11.2 frames later):
    # left 9-20, right 25-36 (= 25-33 and 1-4); the toe stays down until toe-off (25 / 9)
    assert down["L"] == list(range(9, 21))
    assert down["R"] == [*range(1, 5), *range(25, 34)]
    for s, flat in (("L", range(9, 21)), ("R", range(25, 37))):
        xs = [ankle(f, s)[0] for f in flat]
        assert max(xs) - min(xs) < 2e-6, f"{s} planted ankle moves {max(xs) - min(xs)} m"
    for f in range(1, 2 * M.WALK["frames"] + 1):
        for s in "LR":
            assert ankle(f, s)[2] >= M.ANKLE_Z - 2e-6, "no ankle below its rest height"


def contact_point_world(p, side):
    """World (forward, height) of a leg's ankle and toe at phase p from the unrounded model
    (sagittal plane; the pelvis yaw moves the hip joint sideways only)."""
    lg = M.walk_leg(p, side)
    a, b = math.radians(lg["a"]), math.radians(lg["b"])
    ax = M.walk_root(p) + M.THIGH_M * math.sin(a) + M.SHIN_M * math.sin(a - b)
    az = M.HIP_Z + M.walk_pelvis(p) - M.ankle_drop(lg["a"], lg["b"])
    tilt = M.FOOT_TILT + lg["pitch"]
    return (ax, az), (ax + M.FOOT_LEN * math.cos(tilt), az - M.FOOT_LEN * math.sin(tilt))


def test_the_swing_foot_leaves_from_the_toe_and_lands_on_the_heel_with_zero_world_speed():
    eps = 1e-6
    # left toe-off at phase 0.75 (q = 0.5): the toe, the last contact point, does not drag
    (_, toe0), (_, toe1) = contact_point_world(0.75, "L"), contact_point_world(0.75 + eps, "L")
    assert toe0[1] == pytest.approx(M.TOE_Z, abs=1e-9)
    assert abs(toe1[0] - toe0[0]) / eps < 1e-4 and abs(toe1[1] - toe0[1]) / eps < 1e-4
    # left heel strike at phase 1.25: the ankle arrives with zero forward world speed ...
    (a0, _), (a1, _) = contact_point_world(1.25 - 2 * eps, "L"), contact_point_world(1.25 - eps, "L")
    assert abs(a1[0] - a0[0]) / eps < 1e-3
    # ... but drops onto the ground rather than skimming in: in the last airborne frame it is at
    # least 8 mm up and descends at >= 25 deg (no more than 15 mm down, 25 mm forward)
    (x8, _, z8), (x9, _, z9) = ankle(8, "L"), ankle(9, "L")
    drop, forward = z8 - z9, x9 - x8
    assert z8 - M.ANKLE_Z >= 0.008 and math.degrees(math.atan2(drop, forward)) >= 25
    assert 0 < drop <= 0.015 and 0 <= forward <= 0.025
    # mid-swing (left, cycle frame 1) clears the ground by at least the clearance curve
    assert ankle(1, "L")[2] >= M.ANKLE_Z + M.WALK_CLEAR_M


def test_the_walk_is_within_reach_on_a_fine_phase_grid():
    for i in range(3201):
        M.walk_pose(i / 3200)                  # leg_ik raises if a target is out of reach


def test_leg_ik_round_trips_and_rejects_unreachable_targets():
    for forward, drop in ((0.0, 0.75), (0.3, 0.7), (-0.35, 0.78), (0.0, M.LEG_M)):
        a, b = M.leg_ik(forward, drop)
        ar, br = math.radians(a), math.radians(b)
        assert M.THIGH_M * math.sin(ar) + M.SHIN_M * math.sin(ar - br) == pytest.approx(forward, abs=1e-7)
        assert M.ankle_drop(a, b) == pytest.approx(drop, abs=1e-7)
        assert b >= 0
    with pytest.raises(ValueError, match="out of reach"):
        M.leg_ik(0.5, 0.8)


def test_cycle_frame_17_is_left_mid_stance():
    """the stop pose: left foot flat directly under the hips, pelvis at its high point, no yaw"""
    pose = WALK_KEYS[17]
    assert ankle(17, "L") == pytest.approx((16 * M.WALK_M_PER_FRAME, 0.1, M.ANKLE_Z), abs=2e-6)
    assert all(pose["rot"][b][1] == 0.0 for b in ("hips", "spine", "chest", "neck", "head"))
    assert pose["hips_loc"] == [0.0, round(M.WALK_H_MID, 6), 0.0]
    assert pose["hips_loc"][1] == max(k["hips_loc"][1] for k in WALK_KEYS.values())
    assert M.WALK_M_PER_FRAME == pytest.approx(1.075379 / 32, abs=1e-7)


def test_walk_pelvis_and_chest_counter_rotate_with_the_gaze_forward():
    """world yaws (about vertical): pelvis +-WALK_PELVIS_YAW_DEG, chest +-WALK_CHEST_YAW_DEG in
    anti-phase, head 0 (each upward bone's local Y rotation adds to its parent's)"""
    pelvis, chest, head = [], [], []
    for frame, pose in WALK_KEYS.items():
        r = pose["rot"]
        pelvis.append(r["hips"][1])
        chest.append(r["hips"][1] + r["spine"][1] + r["chest"][1])
        head.append(chest[-1] + r["neck"][1] + r["head"][1])
    assert max(map(abs, pelvis)) == pytest.approx(M.WALK_PELVIS_YAW_DEG, abs=1e-5)
    assert max(map(abs, chest)) == pytest.approx(M.WALK_CHEST_YAW_DEG, abs=1e-5)
    assert all(p * c <= 0 for p, c in zip(pelvis, chest)), "anti-phase"
    assert max(map(abs, head)) < 3e-6


def test_idle_keeps_legs_and_hips_still_on_the_walks_stop_leg():
    """Both idle legs stand exactly like the walk's held mid-stance leg (cycle frame 17), on
    every key, so the walk -> idle crossfade leaves the planted left leg unchanged; both feet
    are flat on their rest height directly under the hips."""
    stop = WALK_KEYS[17]
    for frame, pose in M.actions()["mannequin_idle"]:
        assert pose["hips_loc"] == stop["hips_loc"], frame
        for s in "LR":
            for b in ("thigh", "shin", "foot"):
                assert pose["rot"][f"{b}.{s}"] == stop["rot"][f"{b}.L"], (frame, b, s)
            a, b = leg(pose, s)
            ar, br = math.radians(a), math.radians(b)
            assert M.THIGH_M * math.sin(ar) + M.SHIN_M * math.sin(ar - br) == pytest.approx(0.0, abs=2e-6)
            assert M.HIP_Z + pose["hips_loc"][1] - M.ankle_drop(a, b) == pytest.approx(M.ANKLE_Z, abs=2e-6)
            assert a - b + pose["rot"][f"foot.{s}"][0] / M.FORWARD == pytest.approx(0.0, abs=1e-5), "foot flat"


def test_key_table_rejects_a_step_that_does_not_divide_the_cycle():
    with pytest.raises(ValueError, match="multiple"):
        M.key_table(M.idle_pose, 48, 5)
