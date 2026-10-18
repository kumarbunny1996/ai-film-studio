"""Milestone 7: the gesture pose tables and the ochre variant's definition, without Blender.

The gestures (mannequin_look, mannequin_wave) key only the channels they move and are layered
over a continuous idle on a higher NLA track. These tests check the tables, and the layering
in plain Python with the script's own forward kinematics (pose_matrices, which reproduces
Blender's pose evaluation; cross-checked here against leg_fk and the rest skeleton). The
Blender side is tests/test_mannequin_gestures_assets.py.
"""
import importlib.util
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "afs_mannequin", ROOT / "blender" / "scripts" / "author_assets" / "mannequin.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

LOOK_BONES = {"spine", "chest", "neck", "head"}
WAVE_BONES = {"upper_arm.R", "forearm.R", "hand.R"}
LEG_BONES = {f"{b}.{s}" for b in ("thigh", "shin", "foot") for s in "LR"}
SHOULDER_Z = M.BONES["upper_arm.R"][1][2]                      # 1.42
HEAD_TOP_Z = M.BONES["head"][2][2]                             # 1.75


def full(rot: dict) -> dict:
    """Gesture keys ({bone: {axis: deg}}) as full Euler triples, other axes 0."""
    return {b: [axes.get(i, 0.0) for i in range(3)] for b, axes in rot.items()}


def layered(idle_pose: dict, gesture_rot: dict) -> dict:
    """What NLA REPLACE gives with the gesture at full influence over the idle: the gesture's
    keyed channels, the idle's everywhere else."""
    rot = {b: list(v) for b, v in idle_pose["rot"].items()}
    for bone, axes in gesture_rot.items():
        for axis, deg in axes.items():
            rot[bone][axis] = deg
    return rot


def idle_at(k: int) -> dict:
    """The idle pose at idle frame k (any integer), from the authored keys' phase."""
    return M.idle_pose(((k - 1) % M.IDLE["frames"]) / M.IDLE["frames"])


def facing(m) -> list[float]:
    """World facing of an up-pointing bone: its local Z, which is -Y (forward) at rest."""
    return [m[i][2] for i in range(3)]


def direction(m) -> list[float]:
    return [m[i][1] for i in range(3)]


def angle_deg(a, b) -> float:
    return math.degrees(math.acos(max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b))))))


# ---------------------------------------------------------------------------
# Forward kinematics used by the gestures and these tests
# ---------------------------------------------------------------------------
def test_rest_rotation_reproduces_the_scripts_up_and_down_bone_frames():
    flat = lambda m: [v for row in m for v in row]
    assert flat(M.rest_rotation((0, 0, 0), (0, 0, 1))) == pytest.approx(flat(M._UP))
    assert flat(M.rest_rotation((0, 0, 1), (0, 0, 0))) == pytest.approx(flat(M._DOWN))


@pytest.mark.parametrize("bone", sorted(M.BONES))
def test_rest_frames_are_right_handed_and_point_along_the_bone(bone):
    _, head, tail, _ = M.BONES[bone]
    r = M.rest_rotation(head, tail)
    cols = [[r[i][j] for i in range(3)] for j in range(3)]
    for a in range(3):
        for b in range(3):
            assert sum(cols[a][k] * cols[b][k] for k in range(3)) == pytest.approx(float(a == b), abs=1e-12)
    x, y, z = cols
    assert [x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2], x[0] * y[1] - x[1] * y[0]] == pytest.approx(z)
    d = [tail[i] - head[i] for i in range(3)]
    n = math.sqrt(sum(c * c for c in d))
    assert y == pytest.approx([c / n for c in d])


def test_pose_matrices_at_rest_put_every_bone_on_the_skeleton_table():
    pts = M.bone_points(M.pose_matrices({}))
    for bone, (_, head, tail, _) in M.BONES.items():
        assert pts[bone][0] == pytest.approx(head, abs=1e-12)
        assert pts[bone][1] == pytest.approx(tail, abs=1e-12)


@pytest.mark.parametrize("frame", [1, 5, 9, 17, 25, 30])
def test_pose_matrices_agree_with_leg_fk_on_the_walk(frame):
    pose = dict(M.actions()["mannequin_walk"])[frame]
    pts = M.bone_points(M.pose_matrices(pose["rot"], pose["hips_loc"]))
    for s in "LR":
        hip, knee, ankle = M.leg_fk(s, pose["rot"]["hips"], pose["hips_loc"],
                                    pose["rot"][f"thigh.{s}"], pose["rot"][f"shin.{s}"])
        assert pts[f"thigh.{s}"][0] == pytest.approx(hip, abs=1e-12)
        assert pts[f"thigh.{s}"][1] == pytest.approx(knee, abs=1e-12)
        assert pts[f"shin.{s}"][1] == pytest.approx(ankle, abs=1e-12)


# ---------------------------------------------------------------------------
# Key tables
# ---------------------------------------------------------------------------
def test_gesture_names_lengths_and_key_frames():
    g = M.gestures()
    assert set(g) == {"mannequin_look", "mannequin_wave"} == set(M.GESTURE_FRAMES)
    assert M.GESTURE_FRAMES == {"mannequin_look": 24, "mannequin_wave": 60}
    for name, keys in g.items():
        assert [f for f, _ in keys] == list(range(1, M.GESTURE_FRAMES[name] + 2)), name
    assert not set(g) & set(M.actions()), "gesture names do not collide with walk/idle"


def test_gestures_key_only_their_own_channels_and_never_the_legs_or_hips():
    look, wave = M.gestures()["mannequin_look"], M.gestures()["mannequin_wave"]
    for _, rot in look:
        assert set(rot) == LOOK_BONES and all(set(a) == {1} for a in rot.values()), \
            "the look keys only Y rotation, leaving the idle's breathing pitch in place"
    for _, rot in wave:
        assert set(rot) == WAVE_BONES and all(set(a) == {0, 1, 2} for a in rot.values())
    for _, rot in look + wave:
        assert not set(rot) & (LEG_BONES | {"hips"})


def test_gesture_key_values_are_finite_rounded_and_never_negative_zero():
    for keys in M.gestures().values():
        for _, rot in keys:
            for axes in rot.values():
                for v in axes.values():
                    assert math.isfinite(v) and v == round(v, 6)
                    assert math.copysign(1.0, v) > 0 or v != 0


# ---------------------------------------------------------------------------
# Look
# ---------------------------------------------------------------------------
def look_head_facing(rot) -> list[float]:
    return facing(M.pose_matrices(full(rot))["head"])


def test_look_starts_on_the_idle_yaw():
    first = M.gestures()["mannequin_look"][0][1]
    assert all(axes[1] == 0.0 for axes in first.values())
    assert all(idle_at(k)["rot"][b][1] == 0.0 for k in range(1, 49) for b in LOOK_BONES), \
        "the idle never yaws these bones, so the look's first key equals the idle"


def test_look_turns_the_head_40_degrees_to_the_characters_right_and_holds():
    keys = M.gestures()["mannequin_look"]
    target = [-math.sin(math.radians(40)), -math.cos(math.radians(40)), 0.0]   # toward -X
    for f, rot in keys:
        if f >= 17:
            assert look_head_facing(rot) == pytest.approx(target, abs=1e-9), f
            assert rot == keys[-1][1], f"holds from frame 17 (frame {f})"
    chest = facing(M.pose_matrices(full(keys[-1][1]))["chest"])
    assert math.degrees(math.atan2(-chest[0], -chest[1])) == pytest.approx(16.0, abs=1e-9), \
        "the chest (with the spine) carries 16 of the 40 degrees"


def test_look_eases_in_monotonically_without_overshoot_head_leading():
    keys = M.gestures()["mannequin_look"]
    yaw = [math.degrees(math.atan2(-v[0], -v[1])) for v in (look_head_facing(r) for _, r in keys)]
    steps = [b - a for a, b in zip(yaw, yaw[1:])]
    assert all(s >= -1e-9 for s in steps) and max(yaw) <= 40.0 + 1e-9
    assert max(steps) < 6.0, "under 6 deg/frame (measured 5.74)"
    assert max(abs(yaw[i + 1] - 2 * yaw[i] + yaw[i - 1]) for i in range(1, len(yaw) - 1)) < 1.5
    for (a, b) in zip(["head", "neck", "chest"], ["neck", "chest", "spine"]):
        assert M.LOOK_WINDOW[a][0] < M.LOOK_WINDOW[b][0] and M.LOOK_WINDOW[a][1] < M.LOOK_WINDOW[b][1]


# ---------------------------------------------------------------------------
# Wave
# ---------------------------------------------------------------------------
def wave_points(rot) -> dict:
    return M.bone_points(M.pose_matrices(full(rot)))


def test_wave_starts_and_ends_on_the_idles_mean_arm_pose():
    keys = M.gestures()["mannequin_wave"]
    idle_arm = {f"{b}.R": [sum(idle_at(k)["rot"][f"{b}.R"][i] for k in range(1, 49)) / 48
                           for i in range(3)] for b in ("upper_arm", "forearm", "hand")}
    for f in (keys[0][0], keys[-1][0]):
        rot = full(dict(keys)[f])
        for bone in WAVE_BONES:
            assert rot[bone] == pytest.approx(idle_arm[bone], abs=1e-12), (f, bone)
    # the idle's own arm moves by at most 1 degree about that mean
    assert max(abs(idle_at(k)["rot"]["upper_arm.R"][0]) for k in range(1, 49)) == pytest.approx(1.0)


def test_wave_raises_the_hand_above_the_shoulder_and_head_for_the_whole_swing():
    for f, rot in M.gestures()["mannequin_wave"]:
        if M.WAVE_SWING[0] <= f <= M.WAVE_SWING[1]:
            hand = wave_points(rot)["hand.R"][1]
            assert hand[2] > HEAD_TOP_Z + 0.1 > SHOULDER_Z, (f, hand)


def test_wave_swings_the_hand_side_to_side_at_least_twice():
    keys = [(f, r) for f, r in M.gestures()["mannequin_wave"]
            if M.WAVE_SWING[0] <= f <= M.WAVE_SWING[1]]
    x = [wave_points(r)["hand.R"][1][0] for _, r in keys]
    turns = [i for i in range(1, len(x) - 1) if (x[i] - x[i - 1]) * (x[i + 1] - x[i]) < 0]
    assert len(turns) >= 4, "two swings out and two swings in"
    assert max(x) - min(x) > 0.15, "the hand travels over 15 cm side to side"
    flex = [r["forearm.R"][0] for _, r in keys]
    assert max(flex) == pytest.approx(M.WAVE_FLEX_DEG + M.WAVE_SWING_DEG, abs=1e-6)
    assert min(flex) == pytest.approx(M.WAVE_FLEX_DEG - M.WAVE_SWING_DEG, abs=1e-6)


def test_wave_keeps_the_hand_in_front_of_and_clear_of_the_body():
    for f, rot in M.gestures()["mannequin_wave"]:
        p = wave_points(rot)
        for bone in ("forearm.R", "hand.R"):
            tip = p[bone][1]
            assert tip[1] <= 0.0, (f, bone, "behind the body (the rig faces -Y)")
            assert tip[0] < -0.3, (f, bone, "inside the torso's width")


def test_wave_moves_smoothly():
    """Bone directions change under 20 deg/frame and the hand moves under 0.17 m/frame
    (measured 19.2 and 0.163, in the middle of the raise and the lowering), with no jerk:
    the hand's frame-to-frame acceleration stays under 0.06 m/frame^2 (measured 0.058)."""
    keys = M.gestures()["mannequin_wave"]
    mats = [M.pose_matrices(full(r)) for _, r in keys]
    hands = [M.bone_points(m)["hand.R"][1] for m in mats]
    for a, b in zip(mats, mats[1:]):
        for bone in WAVE_BONES:
            assert angle_deg(direction(a[bone]), direction(b[bone])) < 20.0, bone
    assert max(math.dist(a, b) for a, b in zip(hands, hands[1:])) < 0.17
    acc = [math.dist([hands[i + 1][k] - 2 * hands[i][k] + hands[i - 1][k] for k in range(3)],
                     [0, 0, 0]) for i in range(1, len(hands) - 1)]
    assert max(acc) < 0.06


# ---------------------------------------------------------------------------
# Layering over the idle (plain Python; Blender evaluates the same in the asset tests)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["mannequin_look", "mannequin_wave"])
def test_a_gesture_over_the_idle_leaves_legs_hips_and_feet_exactly_as_the_idle(name):
    for f, rot in M.gestures()[name]:
        for k in (f, f + 7, f + 20):                     # any idle phase under the gesture
            idle = idle_at(k)
            alone = M.bone_points(M.pose_matrices(idle["rot"], idle["hips_loc"]))
            both = M.bone_points(M.pose_matrices(layered(idle, rot), idle["hips_loc"]))
            for bone in LEG_BONES | {"hips"}:
                assert both[bone] == alone[bone], (name, f, k, bone)


def test_the_look_keeps_the_idles_breathing():
    look = dict(M.gestures()["mannequin_look"])[25]
    for k in (1, 7, 13):
        idle = idle_at(k)
        rot = layered(idle, look)
        for bone in LOOK_BONES:
            assert rot[bone][0] == idle["rot"][bone][0], "breathing pitch comes from the idle"


# ---------------------------------------------------------------------------
# The ochre variant
# ---------------------------------------------------------------------------
def test_ochre_variant_names_are_its_own_and_its_colours_differ_from_the_grey():
    names = {M.OCHRE["collection"], M.OCHRE["armature"], M.OCHRE["body"]}
    assert names == {"CH-mannequin_ochre", "RIG-mannequin_ochre", "GEO-mannequin_ochre"}
    assert not names & {M.CHARACTER_COLLECTION, M.ARMATURE, M.BODY}
    body, accent = (M.MATERIALS[k] for k in M.OCHRE["materials"])
    assert (body[0], accent[0]) == ("MAT-mannequin_ochre_body", "MAT-mannequin_ochre_accent")
    grey = M.MATERIALS["body"][1]
    assert max(abs(a - b) for a, b in zip(body[1], grey)) > 0.3
    assert body[1][0] > body[1][1] > body[1][2], "ochre: red > green > blue"


def test_manifest_entries_match_the_authored_m7_assets():
    from apps.api.schemas.scene_spec import AssetManifest
    manifest = AssetManifest.model_validate_json((ROOT / "assets/manifest.json").read_text())
    ochre, grey = manifest.asset("mannequin_ochre"), manifest.asset("mannequin")
    assert (ochre.type.value, ochre.file, ochre.collection, ochre.armature) == (
        "character", M.OCHRE_FILE.as_posix(), M.OCHRE["collection"], M.OCHRE["armature"])
    assert (ochre.rig_type, ochre.bones) == (grey.rig_type, grey.bones) == (M.RIG_TYPE, grey.bones)
    for name, frames in M.GESTURE_FRAMES.items():
        a = manifest.action(name)
        assert (a.file, a.action_name, a.rig_type, a.frames, a.loopable, a.coverage) == (
            M.GESTURES_FILE.as_posix(), name, M.RIG_TYPE, frames, False, "partial")
    for name in M.ACTION_FRAMES:                       # walk and idle key every bone
        assert manifest.action(name).coverage == "full"


def layered_spec(host_actions: list[dict]) -> dict:
    return {"spec_version": "1.3", "project_id": "layering", "scene_id": "sc01", "shot_id": "layering",
            "description": "gesture layering", "environment": {"world_color": [0.5, 0.5, 0.5]},
            "render": {"frame_start": 1, "frame_end": 120},
            "characters": [{"name": "host", "asset_id": "mannequin_ochre", "actions": host_actions}],
            "camera": {"look_at": "host", "keys": [{"frame": 1, "location": [0, -6, 1.5]}]}}


def test_existing_schema_accepts_gestures_layered_over_a_continuous_idle():
    from apps.api.schemas.scene_spec import AssetManifest, SceneSpec, validate_against_manifest
    manifest = AssetManifest.model_validate_json((ROOT / "assets/manifest.json").read_text())
    ok = layered_spec([
        {"action_id": "mannequin_idle", "start_frame": 1, "end_frame": 120, "blend_in": 0},
        {"action_id": "mannequin_look", "start_frame": 20, "end_frame": 44},
        {"action_id": "mannequin_wave", "start_frame": 50, "end_frame": 110}])
    assert validate_against_manifest(SceneSpec.model_validate(ok), manifest) == []
    # gestures are not loopable: a clip over 1.5x the action's length is rejected for a retry
    long = layered_spec([
        {"action_id": "mannequin_idle", "start_frame": 1, "end_frame": 120, "blend_in": 0},
        {"action_id": "mannequin_look", "start_frame": 20, "end_frame": 60}])
    errors = validate_against_manifest(SceneSpec.model_validate(long), manifest)
    assert errors == ["characters[host]: action 'mannequin_look' is not loopable (24 frames) "
                      "but the clip asks for 40 frames"]


def test_m7_outputs_are_new_files_beside_the_m6_set():
    assert [p.as_posix() for p in M.M7_OUTPUTS] == [
        "characters/mannequin_ochre.blend", "actions/mannequin_gestures.blend"]
    assert not set(M.M7_OUTPUTS) & set(M.OUTPUTS)
