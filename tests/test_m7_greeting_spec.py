"""Milestone 7: the m7_greeting scene (no Blender).

Gate 1 staging: shot plan, cut positions and frame coverage, the 180-degree rule, the
traveller's walk and stop, and a pinhole check that both characters are fully in frame (feet
included) in the wide and two-shots. Gate 3 acting: the gesture schedule, eyelines, and the
raised hand's headroom in the wave shots. The pinhole model mirrors build_scene.setup_camera (Track To with -Z forward and
Y up, sensor 36 mm with AUTO fit, lens shift = -subject_offset in units of the frame width); it
is a planning check, and the cut-frame smoke render is the visual evidence.
"""
import importlib.util
import json
import math
from pathlib import Path

import pytest

from apps.api.schemas.scene_spec import (AssetManifest, SceneSpec, camera_warnings,
                                         shot_warnings, validate_against_manifest)
from workers.asset_preflight import manifest_problems

ROOT = Path(__file__).resolve().parents[1]
RAW = json.loads((ROOT / "schemas/examples/m7_greeting.json").read_text())
SPEC = SceneSpec.model_validate(RAW)
MANIFEST = AssetManifest.model_validate_json((ROOT / "assets/manifest.json").read_text())
_spec = importlib.util.spec_from_file_location(
    "afs_mannequin", ROOT / "blender/scripts/author_assets/mannequin.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

SHOTS = [("sh01_wide", 1, 84), ("sh02_host_look", 85, 124), ("sh02b_host_pov", 125, 168),
         ("sh03_walk", 169, 264), ("sh04_two_shot", 265, 360), ("sh05_host_wave", 361, 432),
         ("sh06_traveller_wave", 433, 504), ("sh07_end_wide", 505, 576)]
MIN_FRAMES = 24                  # the milestone's own floor: every shot at least one second
STOP_FRAME = 305
HEIGHT_M = 1.75                  # mannequin height (author_assets/mannequin.py)


def chars():
    return {c.name: c for c in SPEC.characters}


def root_at(name: str, f: int) -> list[float]:
    """Root location at frame f: linear between motion_path keys (the traveller's only segment
    is linear), held outside them; a character with no path stays at its transform."""
    c = chars()[name]
    keys = c.motion_path
    if not keys:
        return list(c.transform.location)
    if f <= keys[0].frame:
        return list(keys[0].location)
    for a, b in zip(keys, keys[1:]):
        if a.frame <= f <= b.frame:
            t = (f - a.frame) / (b.frame - a.frame)
            return [a.location[i] + t * (b.location[i] - a.location[i]) for i in range(3)]
    return list(keys[-1].location)


def cam_at(cam, f: int) -> list[float]:
    keys = cam.keys
    if f <= keys[0].frame:
        return list(keys[0].location)
    for a, b in zip(keys, keys[1:]):
        if a.frame <= f <= b.frame:
            t = (f - a.frame) / (b.frame - a.frame)   # eased keys: endpoints exact, middle approx
            return [a.location[i] + t * (b.location[i] - a.location[i]) for i in range(3)]
    return list(keys[-1].location)


def _sub(a, b): return [a[i] - b[i] for i in range(3)]
def _dot(a, b): return sum(a[i] * b[i] for i in range(3))
def _cross(a, b): return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
def _unit(a):
    n = math.sqrt(_dot(a, a))
    return [v / n for v in a]


def project(cam, f: int, p: list[float]) -> tuple[float, float]:
    """(x, y) of world point p in frame fractions from the centre (+-0.5 = frame edge)."""
    w, h = SPEC.render.resolution
    loc = cam_at(cam, f)
    target = root_at(cam.look_at, f)
    aim = [target[0], target[1], target[2] + cam.look_at_height]
    fwd = _unit(_sub(aim, loc))
    right = _unit(_cross(fwd, [0, 0, 1]))
    up = _cross(right, fwd)
    d = _sub(p, loc)
    depth = _dot(d, fwd)
    assert depth > 0, "point behind the camera"
    off = cam.framing.subject_offset if cam.framing else [0.0, 0.0]
    k = cam.lens_mm / 36
    return k * _dot(d, right) / depth + off[0], k * _dot(d, up) / depth * w / h + off[1]


def body_points(name: str, f: int) -> list[list[float]]:
    """Corners of a box around the character: +-0.3 m along x (walking stride), +-0.2 m along
    y, from the ground (feet) to the top of the head."""
    x, y, _ = root_at(name, f)
    return [[x + dx, y + dy, z] for dx in (-0.3, 0.3) for dy in (-0.2, 0.2) for z in (0.0, HEIGHT_M)]


def test_example_is_a_valid_buildable_eight_shot_scene():
    assert SPEC.spec_version == "1.3" and SPEC.camera is None
    assert [(s.shot_id, s.frame_start, s.frame_end) for s in SPEC.shots] == SHOTS
    assert validate_against_manifest(SPEC, MANIFEST) == []
    assert camera_warnings(SPEC) == [] and shot_warnings(SPEC) == []
    assert (SPEC.render.resolution, SPEC.render.fps) == ((640, 360), 24)


def test_shots_cover_the_timeline_in_order_with_cuts_at_the_planned_frames():
    assert (SPEC.render.frame_start, SPEC.render.frame_end) == (1, 576)
    covered = [f for s in SPEC.shots for f in range(s.frame_start, s.frame_end + 1)]
    assert covered == list(range(1, 577)), "every frame in exactly one shot, in order"
    assert [s.frame_start for s in SPEC.shots[1:]] == [85, 125, 169, 265, 361, 433, 505]
    assert all(s.frame_end - s.frame_start + 1 >= MIN_FRAMES for s in SPEC.shots)
    assert (SPEC.render.frame_end - SPEC.render.frame_start + 1) / SPEC.render.fps == 24.0


def test_b_is_the_ochre_variant_and_a_the_grey_mannequin():
    assert {c.name: c.asset_id for c in SPEC.characters} == {
        "host": "mannequin_ochre", "traveller": "mannequin"}
    assert [(p.name, p.asset_id, p.parent, p.parent_bone) for p in SPEC.props] == [
        ("baton", "mannequin_baton", "host", "hand.L")]


def test_asset_preflight_finds_every_file_the_spec_uses():
    assert manifest_problems(MANIFEST, spec=SPEC) == []


def test_host_idles_in_place_for_the_whole_scene_under_its_gestures():
    host = chars()["host"]
    assert host.motion_path == []
    assert (host.actions[0].action_id, host.actions[0].start_frame, host.actions[0].end_frame,
            host.actions[0].blend_in) == ("mannequin_idle", 1, 576, 0)


def test_traveller_walks_at_the_authored_speed_and_stops_at_mid_stance():
    t = chars()["traveller"]
    walk, idle, _ = t.actions
    assert (walk.action_id, walk.start_frame, walk.end_frame, walk.blend_in) == (
        "mannequin_walk", 1, STOP_FRAME, 0)
    assert (idle.action_id, idle.start_frame, idle.end_frame, idle.blend_in) == (
        "mannequin_idle", STOP_FRAME, 576, 8)
    # the walk's last frame is cycle frame 17, where it can crossfade into idle without sliding
    assert 1 + (walk.end_frame - walk.start_frame) % M.WALK["frames"] == 17
    (k0, k1) = t.motion_path
    assert (k0.frame, k1.frame) == (1, STOP_FRAME) and k0.easing.value == "linear"
    assert (k1.location[0] - k0.location[0]) / (k1.frame - k0.frame) == pytest.approx(
        M.WALK_M_PER_FRAME, abs=1e-8)
    assert k0.location[1:] == k1.location[1:] == [0.0, 0.0], "walks along the A-B axis"
    assert k0.rotation_z_deg == k1.rotation_z_deg == 90.0, "faces +X, toward the host"
    assert list(t.transform.location) == list(k0.location)


def test_traveller_stops_at_greeting_distance_from_the_host():
    gap = root_at("host", STOP_FRAME)[0] - root_at("traveller", STOP_FRAME)[0]
    assert gap == pytest.approx(2.2, abs=1e-9)


def test_every_camera_stays_on_one_side_of_the_interaction_axis():
    """180-degree rule. The axis is the line through the two characters' stop positions (y = 0
    here); every camera key must be strictly on the same (-Y) side of it."""
    a, b = root_at("traveller", STOP_FRAME), root_at("host", STOP_FRAME)
    axis = _sub(b, a)

    def side(p):
        d = _sub(p, a)
        return axis[0] * d[1] - axis[1] * d[0]

    sides = [side(k.location) for s in SPEC.shots for k in s.camera.keys]
    assert all(v < -0.5 for v in sides), sides


@pytest.mark.parametrize("shot_id", ["sh01_wide", "sh07_end_wide"])
def test_wide_shots_frame_the_host_and_the_whole_body(shot_id):
    s = next(x for x in SPEC.shots if x.shot_id == shot_id)
    for f in range(s.frame_start, s.frame_end + 1, 6):
        names = ["host"] + (["traveller"] if shot_id == "sh07_end_wide" else [])
        for name in names:
            for p in body_points(name, f):
                x, y = project(s.camera, f, p)
                assert abs(x) < 0.5 and abs(y) < 0.5, (shot_id, f, name, p, x, y)


def test_the_traveller_is_off_screen_in_the_opening_wide():
    s = SPEC.shots[0]
    for f in range(s.frame_start, s.frame_end + 1, 6):
        assert max(project(s.camera, f, p)[0] for p in body_points("traveller", f)) < -0.5


def test_two_shot_frames_both_characters_feet_to_head_from_the_cut():
    s = next(x for x in SPEC.shots if x.shot_id == "sh04_two_shot")
    for f in range(s.frame_start, s.frame_end + 1, 4):
        for name in ("host", "traveller"):
            pts = [project(s.camera, f, p) for p in body_points(name, f)]
            assert all(abs(x) < 0.45 and abs(y) < 0.45 for x, y in pts), (f, name, pts)
        hx = [project(s.camera, f, p)[0] for p in body_points("host", f)]
        tx = [project(s.camera, f, p)[0] for p in body_points("traveller", f)]
        assert max(tx) < min(hx), "traveller screen left, host screen right"


def sun_from() -> tuple[float, float]:
    """Horizontal direction the sun light comes FROM. build_scene.setup_lighting rotates the sun
    by (90 - elevation, 0, azimuth) and a sun shines along its local -Z, so the light travels
    along (-sin az, cos az) horizontally and comes from (sin az, -cos az)."""
    az = math.radians(SPEC.lighting.sun_azimuth_deg)
    return math.sin(az), -math.cos(az)


def facing(name: str) -> tuple[float, float]:
    """The mannequin faces -Y at rotation 0, so rotation_z r faces (sin r, -cos r)."""
    r = math.radians(chars()[name].transform.rotation_deg[2])
    return math.sin(r), -math.cos(r)


def test_the_sun_lights_both_characters_fronts():
    """Gate 1 review: at azimuth 300 the sun came from behind the traveller, so the reverse
    (sh06) saw only its shadow side."""
    f = sun_from()
    for name in ("traveller", "host"):
        assert f[0] * facing(name)[0] + f[1] * facing(name)[1] > 0.15, name


def test_every_shot_camera_sees_the_sunlit_side_of_its_subject():
    f = sun_from()
    for s in SPEC.shots:
        for frame in (s.frame_start, s.frame_end):
            subj, cam = root_at(s.camera.look_at, frame), cam_at(s.camera, frame)
            d = (cam[0] - subj[0], cam[1] - subj[1])
            assert (f[0] * d[0] + f[1] * d[1]) / math.hypot(*d) > 0.15, (s.shot_id, frame)


def prim(name: str):
    return next(p for p in SPEC.primitives if p.name == name)


def screen_box(cam, f: int, pts) -> tuple[float, float, float, float]:
    xy = [project(cam, f, p) for p in pts]
    return (min(x for x, _ in xy), max(x for x, _ in xy), min(y for _, y in xy), max(y for _, y in xy))


def test_look_shot_keeps_the_lamp_post_out_of_frame_and_the_head_clear_of_the_trees():
    """Gate 1 review: sh02 had a tree crown directly behind the host's head and the lamp post
    crowding the right edge. Boxes are conservative: the post's full height including the globe,
    and each tree's trunk plus the crown's bounding box."""
    s = next(x for x in SPEC.shots if x.shot_id == "sh02_host_look")
    post, globe = prim("lamp_post"), prim("lamp_globe")
    px, py, _ = post.transform.location
    r = post.size / 2 * post.keys[0].scale[0]
    top = globe.transform.location[2] + globe.size / 2
    post_pts = [[px + dx, py + dy, z] for dx in (-r, r) for dy in (-r, r) for z in (0.0, top)]
    hx, hy, _ = root_at("host", 1)
    head_pts = [[hx + dx, hy + dy, z] for dx in (-0.15, 0.15) for dy in (-0.15, 0.15)
                for z in (1.45, HEIGHT_M)]
    for f in range(s.frame_start, s.frame_end + 1, 6):
        assert screen_box(s.camera, f, post_pts)[0] > 0.5, f"lamp post in frame at {f}"
        h = screen_box(s.camera, f, head_pts)
        assert all(abs(v) < 0.5 for v in h), f"head not fully in frame at {f}"
        for i in (1, 2, 3):
            crown, trunk = prim(f"tree{i}_crown"), prim(f"tree{i}_trunk")
            tx, ty, cz = crown.transform.location
            cr = crown.size / 2
            pts = [[tx + dx, ty + dy, z] for dx in (-cr, cr) for dy in (-cr, cr)
                   for z in (0.0, cz + cr)]
            t = screen_box(s.camera, f, pts)
            overlap = h[0] < t[1] and t[0] < h[1] and h[2] < t[3] and t[2] < h[3]
            assert not overlap, f"tree{i} behind the head at {f}"


def test_look_shot_keeps_tree_trunks_clear_of_the_top_edge():
    """Gate 1 review: in sh02 tree1's trunk base sat at y +0.41, so a stub of bare trunk hung
    from the top edge. The shot is meant to have only ground behind the host, so every tree that
    is horizontally in frame must have its trunk base above the top edge with a margin."""
    s = next(x for x in SPEC.shots if x.shot_id == "sh02_host_look")
    margin = 0.03
    for f in range(s.frame_start, s.frame_end + 1, 3):
        for i in (1, 2, 3):
            trunk = prim(f"tree{i}_trunk")
            tx, ty, _ = trunk.transform.location
            r = trunk.size / 2 * trunk.keys[0].scale[0]
            box = screen_box(s.camera, f, [[tx + dx, ty + dy, 0.0]
                                           for dx in (-r, r) for dy in (-r, r)])
            if box[1] < -0.5 or box[0] > 0.5:
                continue                                    # outside the frame sideways
            assert box[2] > 0.5 + margin, f"tree{i} trunk base at y {box[2]:+.3f}, frame {f}"


def test_screen_direction_is_left_to_right_in_the_walk():
    s = next(x for x in SPEC.shots if x.shot_id == "sh03_walk")
    assert s.camera.look_at == "traveller"
    assert s.camera.framing.subject_offset[0] < 0, "lead room ahead of the walk (screen right)"
    xs = [root_at("traveller", f)[0] for f in (s.frame_start, s.frame_end)]
    assert xs[1] > xs[0]
    ks = s.camera.keys
    assert (ks[-1].location[0] - ks[0].location[0]) / (ks[-1].frame - ks[0].frame) == pytest.approx(
        M.WALK_M_PER_FRAME, abs=1e-6), "the dolly tracks at walking speed"


# ---------------------------------------------------------------------------
# Gate 3: acting (gesture schedule, eyelines, headroom)
# ---------------------------------------------------------------------------
# (character, action, start, end, blend_in, shot it plays in)
GESTURES = [("host", "mannequin_look", 100, 124, 6, "sh02_host_look"),
            ("host", "mannequin_wave", 366, 426, 6, "sh05_host_wave"),
            ("traveller", "mannequin_wave", 438, 498, 6, "sh06_traveller_wave")]
LOOK_HOLD = 17                   # gesture frame from which the look holds (mannequin.LOOK_WINDOW)


def shot(shot_id: str):
    return next(s for s in SPEC.shots if s.shot_id == shot_id)


def test_gesture_schedule_follows_the_beat_sheet():
    got = [(c.name, a.action_id, a.start_frame, a.end_frame, a.blend_in)
           for c in SPEC.characters for a in c.actions
           if MANIFEST.action(a.action_id).coverage == "partial"]
    assert got == [g[:5] for g in GESTURES]
    assert max(w[1] for w in M.LOOK_WINDOW.values()) == LOOK_HOLD


def test_each_character_starts_on_a_full_body_action_that_spans_its_gestures():
    for c in SPEC.characters:
        first = sorted(c.actions, key=lambda a: a.start_frame)[0]
        assert MANIFEST.action(first.action_id).coverage == "full", c.name
        for g in (a for a in c.actions if MANIFEST.action(a.action_id).coverage == "partial"):
            assert any(MANIFEST.action(a.action_id).coverage == "full"
                       and a.start_frame <= g.start_frame and g.end_frame <= a.end_frame
                       for a in c.actions), f"{c.name}: {g.action_id} has a full-body clip under it"


def test_gestures_do_not_overlap_on_a_character():
    for c in SPEC.characters:
        spans = sorted((a.start_frame, a.end_frame) for a in c.actions
                       if MANIFEST.action(a.action_id).coverage == "partial")
        assert all(a[1] < b[0] for a, b in zip(spans, spans[1:])), c.name


def test_each_gesture_plays_inside_its_shot():
    """Each clip is exactly its action. The waves play whole inside their shots; the look's
    turn completes inside sh02, and the clip's held tail runs on (the look holds to the end)."""
    for _, action, start, end, _, shot_id in GESTURES:
        assert end - start == M.GESTURE_FRAMES[action] == MANIFEST.action(action).frames, \
            "the clip is exactly the action: no 'holding last pose' and no truncation"
        s = shot(shot_id)
        last = start + LOOK_HOLD - 1 if action == "mannequin_look" else end
        assert s.frame_start < start and last < s.frame_end, (action, shot_id)


def test_the_look_turns_on_screen_then_cuts_to_what_b_sees():
    """Gate 3 visual revision: the turn alone barely reads on the faceless head, so sh02 cuts on
    the completed look to a reaction shot over B's shoulder toward A."""
    _, _, start, _, _, shot_id = GESTURES[0]
    held_from = start + LOOK_HOLD - 1
    assert start - shot(shot_id).frame_start >= 12, "B is seen still before turning"
    assert 6 <= shot(shot_id).frame_end - held_from <= 12, "the cut lands just after the turn"
    nxt = SPEC.shots[[x.shot_id for x in SPEC.shots].index(shot_id) + 1]
    assert (nxt.shot_id, nxt.frame_start, nxt.camera.look_at) == (
        "sh02b_host_pov", shot(shot_id).frame_end + 1, "traveller")


def test_both_wave_swings_are_on_screen():
    for _, action, start, _, _, shot_id in GESTURES[1:]:
        s = shot(shot_id)
        assert s.frame_start <= start + M.WAVE_SWING[0] - 1 and start + M.WAVE_SWING[1] - 1 <= s.frame_end


def facing_xy(rotation_z_deg: float) -> tuple[float, float]:
    r = math.radians(rotation_z_deg)              # the mannequin faces -Y at rotation 0
    return math.sin(r), -math.cos(r)


def test_eyelines_meet_at_the_greeting():
    """After the look, B's head yaw (body -50 deg plus the look's -40) points straight at A,
    and A, facing +X, points straight at B: within 1 degree, from the look's hold onward."""
    host, trav = chars()["host"], chars()["traveller"]
    head_yaw = host.transform.rotation_deg[2] + sum(M.LOOK_YAW_DEG.values())
    for f in (GESTURES[0][2] + LOOK_HOLD - 1, STOP_FRAME, 400, 470, 576):
        b, a = root_at("host", f), root_at("traveller", f)
        to_a = _unit([a[0] - b[0], a[1] - b[1], 0.0])
        to_b = _unit([b[0] - a[0], b[1] - a[1], 0.0])
        for face, to in ((facing_xy(head_yaw), to_a),
                         (facing_xy(trav.motion_path[-1].rotation_z_deg), to_b)):
            assert math.degrees(math.acos(min(1.0, face[0] * to[0] + face[1] * to[1]))) < 1.0, f


def _posed_hand_tips(name: str, rot_z: float, start: int, end: int, look: bool):
    """World tip of the right hand through a wave clip, posed with the script's FK: the idle
    under the wave (and the held look for B), the character's root and heading."""
    look_rot = dict(M.look_keys())[M.LOOK["frames"] + 1]
    c, s = math.cos(math.radians(rot_z)), math.sin(math.radians(rot_z))
    for gf, rot in M.wave_keys():
        f = start + gf - 1
        idle = M.idle_pose(((f - 1) % M.IDLE["frames"]) / M.IDLE["frames"])
        r = {b: list(v) for b, v in idle["rot"].items()}
        for b, axes in [*(look_rot.items() if look else ()), *rot.items()]:
            for i, v in axes.items():
                r[b][i] = v
        tip = M.bone_points(M.pose_matrices(r, idle["hips_loc"]))["hand.R"][1]
        x, y, z = root_at(name, f)
        yield f, [x + c * tip[0] - s * tip[1], y + s * tip[0] + c * tip[1], z + tip[2]]


@pytest.mark.parametrize("name, rot_z, g", [("host", -50.0, GESTURES[1]),
                                            ("traveller", 90.0, GESTURES[2])])
def test_the_raised_hand_keeps_headroom_in_its_wave_shot(name, rot_z, g):
    """The hand tip stays inside the frame with at least 10% of the frame height above it
    (pinhole estimate 0.18 below the top edge for B, 0.20 for A); confirmed on evaluated
    poses and cameras in tests/test_m7_greeting_builder.py."""
    _, _, start, end, _, shot_id = g
    cam = shot(shot_id).camera
    for f, p in _posed_hand_tips(name, rot_z, start, end, look=name == "host"):
        x, y = project(cam, f, p)
        assert abs(x) < 0.45 and y < 0.4, (f, x, y)


# ---------------------------------------------------------------------------
# Gate 3 visual revision: the reaction cut and the sh05 lamp-post clearance
# ---------------------------------------------------------------------------
B_HEAD = [2.0, 0.0, 1.65]                        # the host's head centre (root at x 2.0)


def test_reaction_shot_frames_a_whole_with_bs_head_in_the_foreground():
    s = shot("sh02b_host_pov")
    assert s.camera.focus_source() == "traveller" and s.camera.dof_enabled
    for f in range(s.frame_start, s.frame_end + 1, 4):
        a = [project(s.camera, f, p) for p in body_points("traveller", f)]
        assert all(abs(x) < 0.45 and abs(y) < 0.45 for x, y in a), f
        hx, hy = project(s.camera, f, B_HEAD)
        assert 0.15 <= hx <= 0.45 and -0.1 <= hy <= 0.4, (f, hx, hy)
        assert hx - 0.12 > max(x for x, _ in a), "B's head (about 0.1 wide) never covers A"


def test_bs_eyeline_points_toward_a_across_the_cut():
    """In sh02 (after the turn) and in the reaction shot, B's head points toward screen left,
    where A is: project the head centre and a point 0.5 m along B's facing."""
    yaw = math.radians(chars()["host"].transform.rotation_deg[2] + sum(M.LOOK_YAW_DEG.values()))
    ahead = [B_HEAD[0] + 0.5 * math.sin(yaw), B_HEAD[1] - 0.5 * math.cos(yaw), B_HEAD[2]]
    for shot_id, frames in (("sh02_host_look", (116, 124)), ("sh02b_host_pov", (125, 146, 168))):
        cam = shot(shot_id).camera
        for f in frames:
            assert project(cam, f, ahead)[0] < project(cam, f, B_HEAD)[0], (shot_id, f)
    cam = shot("sh02b_host_pov").camera
    for f in (125, 168):
        a = max(project(cam, f, p)[0] for p in body_points("traveller", f))
        assert a < project(cam, f, B_HEAD)[0], "A is screen left of B, where B looks"


def _posed_arm(rot_z: float, start: int, root: list[float], look: bool):
    """World elbow, wrist and hand tip of the waving arm at each scene frame of a wave clip."""
    look_rot = dict(M.look_keys())[M.LOOK["frames"] + 1]
    c, s = math.cos(math.radians(rot_z)), math.sin(math.radians(rot_z))
    for gf, rot in M.wave_keys():
        f = start + gf - 1
        idle = M.idle_pose(((f - 1) % M.IDLE["frames"]) / M.IDLE["frames"])
        r = {b: list(v) for b, v in idle["rot"].items()}
        for b, axes in [*(look_rot.items() if look else ()), *rot.items()]:
            for i, v in axes.items():
                r[b][i] = v
        pts = M.bone_points(M.pose_matrices(r, idle["hips_loc"]))
        yield f, [[root[0] + c * q[0] - s * q[1], root[1] + s * q[0] + c * q[1], root[2] + q[2]]
                  for q in (pts["upper_arm.R"][1], pts["forearm.R"][1], pts["hand.R"][1])]


def test_bs_waving_forearm_stays_clear_of_the_lamp_post_in_sh05():
    """Gate 3 visual revision: in revision 1 the forearm crossed the post early in the swing.
    On screen, the forearm and hand (radius 0.04 m) keep at least 1.5% of the frame width from
    the post (radius 0.048 m) through the raise, swing and lowering (designed: 2.7%)."""
    s = shot("sh05_host_wave")
    cam, k = s.camera, s.camera.lens_mm / 36
    post = prim("lamp_post").transform.location
    _, _, start, _, _, _ = GESTURES[1]
    for f, pts in _posed_arm(-50.0, start, root_at("host", start), look=True):
        if not 378 <= f <= 414:
            continue
        loc = cam_at(cam, f)
        px = project(cam, f, [post[0], post[1], 1.8])[0]
        pr = 0.048 * k / math.dist(loc[:2], post[:2])
        for a, b in zip(pts, pts[1:]):
            (xa, _), (xb, _) = project(cam, f, a), project(cam, f, b)
            lr = 0.04 * k / math.dist(loc[:2], b[:2])
            gap = max(min(xa, xb) - lr - (px + pr), (px - pr) - (max(xa, xb) + lr))
            assert gap > 0.015, (f, round(gap, 4))


# ---------------------------------------------------------------------------
# Set dressing: tree2 moved to (7, 17) to keep it out of sh05 (it showed as a sliver of
# crown at the top-left, behind A's head) without a tangent behind B's head elsewhere
# ---------------------------------------------------------------------------
def crown_triangle(cam, f: int, i: int) -> list[tuple[float, float]]:
    """Projected silhouette of tree i's cone (apex and the two base edges facing the camera),
    with x in frame-height units like y."""
    cr = prim(f"tree{i}_crown")
    x, y, cz = cr.transform.location
    r = cr.size / 2
    loc = cam_at(cam, f)
    n = math.hypot(x - loc[0], y - loc[1])
    px, py = -(y - loc[1]) / n * r, (x - loc[0]) / n * r
    w, h = SPEC.render.resolution
    pts = ([x, y, cz + r], [x + px, y + py, cz - r], [x - px, y - py, cz - r])
    return [(a * w / h, b) for a, b in (project(cam, f, p) for p in pts)]


def _seg_dist(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def _inside(p, tri) -> bool:
    s = [(a[0] - p[0]) * (b[1] - p[1]) - (b[0] - p[0]) * (a[1] - p[1])
         for a, b in zip(tri, tri[1:] + tri[:1])]
    return all(v >= 0 for v in s) or all(v <= 0 for v in s)


def test_no_tree_shows_in_bs_wave_shot():
    s = shot("sh05_host_wave")
    for f in range(s.frame_start, s.frame_end + 1, 4):
        for i in (1, 2, 3):
            cr = prim(f"tree{i}_crown")
            x, y, cz = cr.transform.location
            r = cr.size / 2
            pts = [[x, y, cz + r]] + [[x + r * math.cos(a), y + r * math.sin(a), cz - r]
                                      for a in (k * math.pi / 8 for k in range(16))]
            for p in pts:
                try:
                    px, py = project(s.camera, f, p)
                except AssertionError:                  # behind the camera
                    continue
                assert abs(px) > 0.5 or abs(py) > 0.5, (f, i)


@pytest.mark.parametrize("shot_id, frames", [("sh01_wide", (1, 42, 84)), ("sh04_two_shot", (300, 330, 360)),
                                             ("sh07_end_wide", (505, 540, 576))])
def test_bs_head_stands_clear_of_tree2_in_the_wides(shot_id, frames):
    """In the wides and the two-shot B's head (radius 0.1 m) keeps a gap from tree2's crown
    outline on screen (it touched it at the Gate 1 position, 5.5, 11)."""
    cam = shot(shot_id).camera
    w, h = SPEC.render.resolution
    for f in frames:
        tri = crown_triangle(cam, f, 2)
        hx, hy = project(cam, f, B_HEAD)
        head = (hx * w / h, hy)
        hr = 0.1 * cam.lens_mm / 36 * w / h / math.dist(cam_at(cam, f)[:2], B_HEAD[:2])
        assert not _inside(head, tri)
        assert min(_seg_dist(head, tri[i], tri[(i + 1) % 3]) for i in range(3)) - hr > 0.01, f


# ---------------------------------------------------------------------------
# Set dressing: the lamp post moved to (3.6, 0.4) after the final render showed it touching
# B's head in sh05 (no sh05 camera cleared both B's head and the waving forearm)
# ---------------------------------------------------------------------------
def _post_band(cam, f: int, z: float) -> tuple[float, float]:
    post = prim("lamp_post").transform.location
    k = cam.lens_mm / 36
    return (project(cam, f, [post[0], post[1], z])[0],
            0.048 * k / math.dist(cam_at(cam, f)[:2], post[:2]))


def test_the_lamp_post_stands_clear_of_bs_head_in_sh05():
    s = shot("sh05_host_wave")
    k = s.camera.lens_mm / 36
    for f in range(s.frame_start, s.frame_end + 1, 2):
        px, pr = _post_band(s.camera, f, B_HEAD[2])
        hx = project(s.camera, f, B_HEAD)[0]
        hr = 0.1 * k / math.dist(cam_at(s.camera, f)[:2], B_HEAD[:2])
        assert abs(px - hx) - pr - hr > 0.02, f


@pytest.mark.parametrize("shot_id", ["sh01_wide", "sh04_two_shot", "sh07_end_wide"])
def test_the_lamp_post_stands_beside_b_not_behind_in_the_wides(shot_id):
    s = shot(shot_id)
    k = s.camera.lens_mm / 36
    for f in (s.frame_start, s.frame_end):
        px, pr = _post_band(s.camera, f, 1.0)
        bx = project(s.camera, f, [2.0, 0.0, 1.0])[0]
        br = 0.22 * k / math.dist(cam_at(s.camera, f)[:2], [2.0, 0.0])
        assert px - pr - (bx + br) > 0.03, "the post is screen right of B, with a gap"
        assert abs(px) < 0.48, "and still in frame"
