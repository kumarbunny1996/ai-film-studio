"""Milestone 10: The Traveller's Question, scene 2 of The Greeting (no Blender).

Pins the approved blocking of schemas/examples/m10_travellers_question.json: continuity with
the approved M7 scene, the shot plan, the action schedule, the walks (authored speed, the
mid-stance stop, B's 2 m turn and A's 1.5 m turn keyed every 4 frames so the body never walks
sideways), clearances, the 180-degree rule at every cut, framing, light and screen direction.
The pinhole model is the one tests/test_m7_greeting_spec.py uses (Track To aim, sensor 36 mm,
lens shift = -subject_offset); it is a planning check, and the geometry-only build, composition
QA and the preview are the evidence.
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
RAW = json.loads((ROOT / "schemas/examples/m10_travellers_question.json").read_text(encoding="utf-8"))
SPEC = SceneSpec.model_validate(RAW)
M7 = SceneSpec.model_validate_json((ROOT / "schemas/examples/m7_greeting.json").read_text())
MANIFEST = AssetManifest.model_validate_json((ROOT / "assets/manifest.json").read_text())
_spec = importlib.util.spec_from_file_location(
    "afs_mannequin", ROOT / "blender/scripts/author_assets/mannequin.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

# Preview-2 review: eight shots. While A passes the lamp post (289-336) no camera on the right side
# of the line can show A or B clear of it (Gate 2 search), so the film cuts away to the road.
SHOTS = [("sh01_question_wide", 1, 96), ("sh02_traveller_question", 97, 132),
         ("sh02b_road_ahead", 133, 168), ("sh03_host_response", 169, 240),
         ("sh04_host_leads", 241, 288), ("sh04b_road_insert", 289, 336),
         ("sh05_catch_up", 337, 456), ("sh06_together_wide", 457, 576)]
INSERTS = ("sh02b_road_ahead", "sh04b_road_insert")                  # fixed cameras, no subject
TRACKING = [s for s, *_ in SHOTS if s not in INSERTS]               # shots with a look_at subject
LOOK_HOLD = 17                   # gesture frame from which the look holds (as in M7)
ROUTE = 50.0                     # heading of the road the two take: toward camera right and the sun
# Preview-2 review: B walks on to 385 and A follows from 249 (was 321 and 305), so the lamp post
# lines up behind A before sh05 instead of during the catch-up; A still catches up in sh05.
B_WALK_1, B_STOP, B_WALK_2 = 209, 385, 409
A_LOOK, A_WALK = 105, 249
HEIGHT_M = 1.75
LOOK_YAW = sum(M.LOOK_YAW_DEG.values())          # -40: the look turns the head to the right


def chars(spec=SPEC):
    return {c.name: c for c in spec.characters}


def _interp(keys, f, get):
    if f <= keys[0].frame:
        return get(keys[0])
    for a, b in zip(keys, keys[1:]):
        if a.frame <= f <= b.frame:
            t = (f - a.frame) / (b.frame - a.frame)
            va, vb = get(a), get(b)
            return [x + t * (y - x) for x, y in zip(va, vb)] if isinstance(va, list) else va + t * (vb - va)
    return get(keys[-1])


def root_at(name: str, f: int, spec=SPEC) -> list[float]:
    """Root location at frame f: linear between motion_path keys (every key here is linear),
    held before the first and after the last; no path = the transform."""
    c = chars(spec)[name]
    if not c.motion_path:
        return list(c.transform.location)
    return _interp(c.motion_path, f, lambda k: list(k.location))


def heading_at(name: str, f: int, spec=SPEC) -> float:
    c = chars(spec)[name]
    if not c.motion_path:
        return c.transform.rotation_deg[2]
    return _interp(c.motion_path, f, lambda k: k.rotation_z_deg)


def facing_xy(deg: float) -> tuple[float, float]:
    r = math.radians(deg)                        # the mannequin faces -Y at rotation 0
    return math.sin(r), -math.cos(r)


def shot(shot_id: str):
    return next(s for s in SPEC.shots if s.shot_id == shot_id)


def cam_at(cam, f: int) -> list[float]:
    return _interp(cam.keys, f, lambda k: list(k.location))


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
    fwd = _unit(_sub([target[0], target[1], target[2] + cam.look_at_height], loc))
    right = _unit(_cross(fwd, [0, 0, 1]))
    up = _cross(right, fwd)
    d = _sub(p, loc)
    depth = _dot(d, fwd)
    assert depth > 0, "point behind the camera"
    off = cam.framing.subject_offset if cam.framing else [0.0, 0.0]
    k = cam.lens_mm / 36
    return k * _dot(d, right) / depth + off[0], k * _dot(d, up) / depth * w / h + off[1]


def body_points(name: str, f: int) -> list[list[float]]:
    """Corners of a box around the character: +-0.3 m horizontally (the walk's stride and the
    turn), from the ground to the top of the head."""
    x, y, _ = root_at(name, f)
    return [[x + dx, y + dy, z] for dx in (-0.3, 0.3) for dy in (-0.3, 0.3) for z in (0.0, HEIGHT_M)]


def clip(name: str, action: str, start: int):
    return next(a for a in chars()[name].actions if a.action_id == action and a.start_frame == start)


# ---------------------------------------------------------------------------------------------
# The spec and continuity with The Greeting
# ---------------------------------------------------------------------------------------------
def test_spec_is_valid_with_every_asset_on_disk_and_no_warnings():
    assert SPEC.spec_version == "1.3" and SPEC.scene_id == "sc02"
    assert validate_against_manifest(SPEC, MANIFEST) == []
    assert manifest_problems(MANIFEST, spec=SPEC) == []
    assert camera_warnings(SPEC) == [] and shot_warnings(SPEC) == []


def test_shots_cover_the_24_second_timeline_in_the_planned_order():
    assert (SPEC.render.frame_start, SPEC.render.frame_end, SPEC.render.fps) == (1, 576, 24)
    assert [(s.shot_id, s.frame_start, s.frame_end) for s in SPEC.shots] == SHOTS


def test_render_set_light_and_cast_match_the_approved_greeting():
    """So the two scenes cut together and assemble by stream copy (same format and encoder). The
    set is M7's plus the road, which no M7 camera ever sees (tested below)."""
    assert SPEC.render == M7.render and SPEC.environment == M7.environment
    assert SPEC.lighting == M7.lighting
    assert SPEC.primitives[:-1] == M7.primitives and SPEC.primitives[-1].name == "road"
    assert SPEC.props == M7.props, "the baton stays in the host's left hand"
    assert {c.name: c.asset_id for c in SPEC.characters} == {c.name: c.asset_id for c in M7.characters}
    assert {a.action_id for c in SPEC.characters for a in c.actions} == {
        "mannequin_idle", "mannequin_look", "mannequin_walk"}, "no new or missing-file actions"


@pytest.mark.parametrize("name", ["host", "traveller"])
def test_each_character_starts_where_the_greeting_ends(name):
    assert root_at(name, 1) == pytest.approx(root_at(name, 576, M7), abs=1e-9)
    assert heading_at(name, 1) == pytest.approx(heading_at(name, 576, M7), abs=1e-9)
    assert list(chars()[name].transform.location) == pytest.approx(root_at(name, 1))
    assert chars()[name].transform.rotation_deg[2] == pytest.approx(heading_at(name, 1))


def test_the_host_turns_its_head_back_onto_a_at_once():
    """No clip can start mid-action, so B's head (held on A at the end of M7) starts neutral;
    the look plays again from frame 1 and holds from frame 17, in the opening wide."""
    look = clip("host", "mannequin_look", 1)
    assert (look.end_frame - look.start_frame, look.blend_in) == (M.LOOK["frames"], 6)


# ---------------------------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------------------------
def test_action_schedule_follows_the_blocking():
    def sched(name):
        return [(a.action_id, a.start_frame, a.end_frame, a.blend_in) for a in chars()[name].actions]
    assert sched("host") == [("mannequin_idle", 1, 576, 0), ("mannequin_look", 1, 25, 6),
                             ("mannequin_walk", B_WALK_1, B_STOP, 8),
                             ("mannequin_idle", B_STOP, B_WALK_2, 8),
                             ("mannequin_walk", B_WALK_2, 576, 8)]
    assert sched("traveller") == [("mannequin_idle", 1, 576, 0),
                                  ("mannequin_look", A_LOOK, A_LOOK + 24, 6),
                                  ("mannequin_walk", A_WALK, 576, 8)]


def test_the_hosts_stop_lands_on_the_walks_mid_stance_frame():
    """As in M6/M7: the walk's last frame is cycle frame 17 (left foot flat under the hips), where
    it crossfades into idle without sliding."""
    walk = clip("host", "mannequin_walk", B_WALK_1)
    assert 1 + (walk.end_frame - walk.start_frame) % M.WALK["frames"] == 17


EASE = 8                         # walk starts: frames of the idle -> walk crossfade (blend_in)
STARTS = {"host": (B_WALK_1, B_WALK_2), "traveller": (A_WALK,)}


def easing_start(name: str, f: int) -> int | None:
    """Frames into a walk start's crossfade (0-7) for the step f -> f+1, else None."""
    return next((f - s for s in STARTS[name] if s <= f < s + EASE), None)


def walking(name: str, f: int) -> bool:
    """True when frame f -> f+1 lies inside one of the character's walk clips."""
    return any(a.action_id == "mannequin_walk" and a.start_frame <= f < a.end_frame
               for a in chars()[name].actions)


@pytest.mark.parametrize("name", ["host", "traveller"])
def test_roots_travel_at_the_authored_walk_speed_only_while_walking(name):
    """Keys are linear and each chord is walked at WALK_M_PER_FRAME, so the planted foot keeps
    its place; outside the walk clips the root does not move at all. A walk that starts from
    idle eases in: under the linear 8-frame crossfade the root covers v t^2 / 8 after t frames
    (the stance foot stays planted; measured in the builder test), and is back on the path,
    at full speed, 8 frames after the start."""
    assert all(k.easing.value == "linear" for k in chars()[name].motion_path[:-1])
    for c in chars()[name].actions:
        if c.action_id == "mannequin_walk":
            assert c.start_frame in STARTS[name] and c.blend_in == EASE
    v = M.WALK_M_PER_FRAME
    for f in range(1, 576):
        step = math.dist(root_at(name, f)[:2], root_at(name, f + 1)[:2])
        t = easing_start(name, f)
        if t is not None:
            assert step == pytest.approx(v * (2 * t + 1) / EASE, rel=2e-3), (name, f)
        elif walking(name, f):
            assert step == pytest.approx(v, rel=1e-4), (name, f)
        else:
            assert step == pytest.approx(0.0, abs=1e-9), (name, f)


@pytest.mark.parametrize("name, max_crab", [("host", 2.0), ("traveller", 2.6)])
def test_the_body_always_faces_where_it_walks(name, max_crab):
    """Heading and path direction agree within half the angle between keys (keys every 4
    frames), so the walk never goes sideways; this is what the dense keys are for."""
    for f in range(1, 576):
        if not walking(name, f):
            continue
        a, b = root_at(name, f), root_at(name, f + 1)
        move = math.degrees(math.atan2(b[0] - a[0], -(b[1] - a[1])))       # heading of the motion
        mid = (heading_at(name, f) + heading_at(name, f + 1)) / 2
        assert abs((move - mid + 180) % 360 - 180) <= max_crab, (name, f, move, mid)


def _circle(points):
    """Centre and radius of the circle through three points."""
    (ax, ay), (bx, by), (cx, cy) = points
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    return (ux, uy), math.hypot(ax - ux, ay - uy)


def test_the_hosts_turn_is_a_2_m_walking_arc_from_its_greeting_angle_onto_the_road():
    keys = [k for k in chars()["host"].motion_path if B_WALK_1 <= k.frame <= 313]
    assert (keys[0].rotation_z_deg, keys[-1].rotation_z_deg) == (-50.0, ROUTE), "100 degrees, to its left"
    arc = [k for k in keys if k.frame >= B_WALK_1 + EASE]
    assert all(b.frame - a.frame == 4 for a, b in zip(arc, arc[1:])), "keyed every 4 frames after the start"
    centre, r = _circle([keys[0].location[:2], arc[12].location[:2], keys[-1].location[:2]])
    assert r == pytest.approx(2.0, abs=0.01), "the approved 2 m turn"
    # eased-start keys lie on the arc's 4-frame chords: at most the chord's sagitta inside it
    assert all(math.dist(k.location[:2], centre) == pytest.approx(r, abs=2e-3) for k in keys)
    assert max_turn_rate("host") < 1.0, "under one degree per frame once walking"


def max_turn_rate(name: str, eased: bool = False) -> float:
    """Largest heading change per frame, outside (or, with eased, inside) the walk starts. In a
    start the heading follows the eased path, so it turns up to (2 t + 1) / 8 times as fast."""
    return max(abs(heading_at(name, f + 1) - heading_at(name, f)) for f in range(1, 576)
               if (easing_start(name, f) is not None) == eased)


def test_the_travellers_turn_onto_the_road_is_also_a_2_m_arc():
    """Gate 2 measurement: a 1.5 m turn straight out of the walk start slid A's planted foot
    3.4 cm (limit 3 cm), so A turns on the same ~2 m radius as B."""
    keys = [k for k in chars()["traveller"].motion_path if k.frame <= A_WALK + 40]
    assert (keys[0].frame, keys[0].rotation_z_deg, keys[-1].rotation_z_deg) == (A_WALK, 90.0, ROUTE)
    _, r = _circle([keys[0].location[:2], keys[-4].location[:2], keys[-1].location[:2]])
    assert r == pytest.approx(1.93, abs=0.01)
    assert max_turn_rate("traveller") <= 1.0 + 1e-9, "4 degrees per 4-frame key"


@pytest.mark.parametrize("name", ["host", "traveller"])
def test_turning_during_a_walk_start_stays_under_two_degrees_per_frame(name):
    assert max_turn_rate(name, eased=True) < 1.9


def test_both_end_on_the_road_walking_side_by_side_with_the_host_slightly_ahead():
    d = facing_xy(ROUTE)
    left = (-d[1], d[0])
    for f in (B_WALK_2, 456, 516, 576):
        a, b = root_at("traveller", f), root_at("host", f)
        assert heading_at("traveller", f) == heading_at("host", f) == ROUTE
        ahead = (b[0] - a[0]) * d[0] + (b[1] - a[1]) * d[1]
        beside = (a[0] - b[0]) * left[0] + (a[1] - b[1]) * left[1]
        assert ahead == pytest.approx(0.807, abs=0.01) and beside == pytest.approx(1.387, abs=0.01), f


def test_the_host_waits_until_a_is_almost_level():
    a, b = root_at("traveller", B_WALK_2), root_at("host", B_WALK_2)
    d = facing_xy(ROUTE)
    assert (b[0] - a[0]) * d[0] + (b[1] - a[1]) * d[1] < 0.85, "B sets off again as A comes alongside"


def test_nobody_collides_or_brushes_the_lamp_post():
    post = next(p for p in SPEC.primitives if p.name == "lamp_post").transform.location
    for f in range(1, 577):
        assert math.dist(root_at("traveller", f)[:2], root_at("host", f)[:2]) > 1.4, f
        for name in ("traveller", "host"):
            assert math.dist(root_at(name, f)[:2], post[:2]) > 1.5, (name, f)


# ---------------------------------------------------------------------------------------------
# Story beats: the question (A's look) and the answer (B leads the way)
# ---------------------------------------------------------------------------------------------
def test_as_look_points_along_the_road_they_take():
    """The question without a pointing gesture: the look turns A's head 40 degrees to its right,
    from +X onto exactly the heading B then leads them along."""
    assert heading_at("traveller", A_LOOK) + LOOK_YAW == pytest.approx(ROUTE)


def test_each_beat_plays_on_screen_in_its_shot():
    s2, s3, s4, s5 = (shot(i) for i in ("sh02_traveller_question", "sh03_host_response",
                                         "sh04_host_leads", "sh05_catch_up"))
    assert s2.frame_start + 8 <= A_LOOK, "A is seen still before turning its head"
    assert s3.camera.look_at == "host" and s3.frame_end - B_WALK_1 + 1 >= 24, "B sets off on screen"
    assert s4.frame_start <= A_WALK and s4.frame_end - A_WALK + 1 >= 24, "A sets off after B, on screen"
    assert s5.frame_start + 24 <= B_STOP and B_WALK_2 - B_STOP >= 24, "B stops and waits a second"
    assert B_WALK_2 <= s5.frame_end - 24, "A catches up and they walk on, on screen"


def test_the_look_cuts_to_the_road_ahead_just_after_the_turn():
    """As in M7's reaction cut: the turn completes on screen, and the cut lands 6-12 frames
    into the hold, on what A is looking at."""
    held_from = A_LOOK + LOOK_HOLD - 1
    s2, pov = shot("sh02_traveller_question"), shot("sh02b_road_ahead")
    assert 6 <= s2.frame_end - held_from <= 12
    assert pov.frame_start == s2.frame_end + 1 and pov.frame_end - pov.frame_start + 1 >= 24


def pov_project(cam, p):
    """Frame position of world point p for a fixed camera with rotation_deg and no look_at:
    the camera looks along its local -Z rotated by Euler XYZ (rx, 0, rz)."""
    rx, _, rz = (math.radians(a) for a in cam.keys[0].rotation_deg)
    fwd = [-math.sin(rz) * math.sin(rx), math.cos(rz) * math.sin(rx), -math.cos(rx)]
    right = _unit(_cross(fwd, [0, 0, 1]))
    up = _cross(right, fwd)
    d = _sub(p, cam.keys[0].location)
    depth = _dot(d, fwd)
    if depth <= 0:
        return None
    w, h = SPEC.render.resolution
    k = cam.lens_mm / 36
    return k * _dot(d, right) / depth, k * _dot(d, up) / depth * w / h


def insert_is_clear(cam, f0, f1):
    """No character box and no part of the lamp post in a fixed camera's frame."""
    for f in range(f0, f1 + 1, 2):
        for name in ("traveller", "host"):
            for p in body_points(name, f):
                q = pov_project(cam, p)
                assert q is None or abs(q[0]) > 0.5 or abs(q[1]) > 0.5, (name, f)
    for z in (0.1, 1.6, 3.4):
        q = pov_project(cam, [POST[0], POST[1], z])
        assert q is None or abs(q[0]) > 0.5 or abs(q[1]) > 0.5, z


def test_the_road_insert_covers_as_crossing_of_the_post_without_either_character():
    """The cutaway between B leading and the catch-up: raised beside the road, looking down it
    toward the sun; the pair and the lamp post are behind and beside the camera. Preview 3 used a
    0.5 m camera, which saw the road edge-on as a thin sliver; this one fills the frame with it."""
    s = shot("sh04b_road_insert")
    cam = s.camera
    assert cam.look_at is None and not cam.dof_enabled and len(cam.keys) == 1
    pov = shot("sh02b_road_ahead").camera.keys[0]
    assert math.dist(cam.keys[0].location, pov.location) > 5.0, "a different angle from A's POV"
    insert_is_clear(cam, s.frame_start, s.frame_end)
    assert road_share(cam) > 0.15


def test_the_road_ahead_is_what_a_sees_without_either_character():
    cam = shot("sh02b_road_ahead").camera
    assert cam.look_at is None and not cam.dof_enabled and len(cam.keys) == 1
    rx, _, rz = cam.keys[0].rotation_deg
    look = (-math.sin(math.radians(rz)), math.cos(math.radians(rz)))
    gaze = facing_xy(heading_at("traveller", A_LOOK) + LOOK_YAW)
    assert math.degrees(math.acos(look[0] * gaze[0] + look[1] * gaze[1])) < 1.0, "along A's gaze"
    assert 80 <= rx <= 90, "eye level, slightly down"
    eye = root_at("traveller", A_LOOK)
    assert math.dist(cam.keys[0].location[:2], eye[:2]) < 0.8 and 1.4 <= cam.keys[0].location[2] <= 1.7
    for f in range(133, 169, 4):
        for name in ("traveller", "host"):
            for p in body_points(name, f):
                q = pov_project(cam, p)
                assert q is None or abs(q[0]) > 0.5 or abs(q[1]) > 0.5, (name, f)


# ---------------------------------------------------------------------------------------------
# Cameras: 180-degree rule, framing, light, screen direction
# ---------------------------------------------------------------------------------------------
def test_every_cut_keeps_the_camera_on_one_side_of_the_line_between_them():
    """The line through A and B at the cut frame; the outgoing and incoming cameras are on the
    same side (the -Y side of The Greeting), clearly off the line."""
    for prev, nxt in zip(SPEC.shots, SPEC.shots[1:]):
        f = nxt.frame_start
        a, b = root_at("traveller", f), root_at("host", f)
        axis = _sub(b, a)
        side = lambda p: axis[0] * (p[1] - a[1]) - axis[1] * (p[0] - a[0])
        assert side(cam_at(prev.camera, f - 1)) < -1.0 and side(cam_at(nxt.camera, f)) < -1.0, f


def test_the_opening_continues_the_greetings_camera_side():
    m7_last = M7.shots[-1].camera
    a, b = root_at("traveller", 1), root_at("host", 1)
    for cam in (m7_last, shot("sh01_question_wide").camera):
        p = cam.keys[-1].location if cam is m7_last else cam.keys[0].location
        assert (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) < -1.0


def in_frame(cam, f, name, margin=0.5) -> bool:
    return all(abs(x) < margin and abs(y) < margin for x, y in (project(cam, f, p) for p in body_points(name, f)))


@pytest.mark.parametrize("shot_id", ["sh01_question_wide", "sh03_host_response", "sh04_host_leads",
                                     "sh05_catch_up", "sh06_together_wide"])
def test_both_characters_are_whole_in_frame(shot_id):
    s = shot(shot_id)
    for f in range(s.frame_start, s.frame_end + 1, 4):
        for name in ("traveller", "host"):
            assert in_frame(s.camera, f, name), (shot_id, f, name)


def test_the_question_shot_is_a_on_its_own_with_room_where_it_looks():
    s = shot("sh02_traveller_question")
    for f in range(s.frame_start, s.frame_end + 1, 4):
        assert min(project(s.camera, f, p)[0] for p in body_points("host", f)) > 0.5, "B out of frame"
        head = root_at("traveller", f)[:2] + [1.65]
        x, y = project(s.camera, f, head)
        assert -0.35 < x < -0.05 and 0.0 < y < 0.4, (f, x, y)
    yaw = facing_xy(heading_at("traveller", A_LOOK) + LOOK_YAW)
    head = root_at("traveller", A_LOOK)[:2] + [1.65]
    ahead = [head[0] + 0.5 * yaw[0], head[1] + 0.5 * yaw[1], head[2]]
    assert project(s.camera, A_LOOK + 20, ahead)[0] > project(s.camera, A_LOOK + 20, head)[0], \
        "A looks toward screen right, into the room left in front of it"


def test_the_closing_wide_keeps_the_two_apart_on_screen():
    """B walks on the camera side of A, so the bodies (about 0.4 m wide) must not overlap."""
    s = shot("sh06_together_wide")
    k = s.camera.lens_mm / 36
    for f in range(s.frame_start, s.frame_end + 1, 4):
        c = cam_at(s.camera, f)
        xa = project(s.camera, f, root_at("traveller", f)[:2] + [1.0])[0]
        xb = project(s.camera, f, root_at("host", f)[:2] + [1.0])[0]
        half = sum(k * 0.2 / math.dist(c[:2], root_at(n, f)[:2]) for n in ("traveller", "host"))
        assert abs(xb - xa) - half > 0.02, f


def sun_from() -> tuple[float, float]:
    az = math.radians(SPEC.lighting.sun_azimuth_deg)
    return math.sin(az), -math.cos(az)


def test_the_walkers_face_into_the_low_sun_and_every_camera_sees_their_lit_side():
    f = sun_from()
    d = facing_xy(ROUTE)
    assert f[0] * d[0] + f[1] * d[1] > 0.7, "they walk toward the golden-hour sun"
    for s in SPEC.shots:
        if s.shot_id not in TRACKING:
            continue                             # the inserts look at the road, not at a subject
        for frame in (s.frame_start, s.frame_end):
            subj, cam = root_at(s.camera.look_at, frame), cam_at(s.camera, frame)
            v = (cam[0] - subj[0], cam[1] - subj[1])
            assert (f[0] * v[0] + f[1] * v[1]) / math.hypot(*v) > 0.3, (s.shot_id, frame)


@pytest.mark.parametrize("shot_id, name", [("sh04_host_leads", "traveller"), ("sh05_catch_up", "traveller"),
                                           ("sh05_catch_up", "host"), ("sh06_together_wide", "host"),
                                           ("sh06_together_wide", "traveller")])
def test_screen_direction_is_left_to_right_like_the_greetings_walk(shot_id, name):
    """The character crossing the frame moves left to right. In sh04 that is A (B, tracked, stays
    centred while it turns toward the camera); A is still turning onto the road there, so every
    walking frame counts, not only those at the road's heading."""
    s = shot(shot_id)
    frames = [f for f in range(s.frame_start, s.frame_end) if walking(name, f) and walking(name, f + 6)
              and (shot_id == "sh04_host_leads" or heading_at(name, f) == ROUTE)]
    assert len(frames) >= 24, (shot_id, name)
    for f in frames[::6]:
        # where the character is now and 6 frames later, both seen by the camera of frame f
        p0 = project(s.camera, f, root_at(name, f)[:2] + [1.0])
        p1 = project(s.camera, f, root_at(name, f + 6)[:2] + [1.0])
        assert p1[0] > p0[0], (shot_id, name, f)


def test_the_follow_dolly_tracks_a_at_walking_speed_along_the_road():
    ks = shot("sh05_catch_up").camera.keys
    assert ks[0].easing.value == "linear"
    step = [(ks[1].location[i] - ks[0].location[i]) / (ks[1].frame - ks[0].frame) for i in (0, 1)]
    d = facing_xy(ROUTE)
    assert step == pytest.approx([M.WALK_M_PER_FRAME * d[0], M.WALK_M_PER_FRAME * d[1]], abs=2e-4)


# ---------------------------------------------------------------------------------------------
# The lamp post (preview 1 review): never behind a body, except the known stretch in sh05
# ---------------------------------------------------------------------------------------------
POST = next(p for p in SPEC.primitives if p.name == "lamp_post").transform.location


def post_gap(cam, f, name):
    """Screen gap between the post (radius 0.06 m, full height) and a body box (+-0.25 m,
    0.2-1.7 m), in frame widths; None if the post or the body is out of frame."""
    def xs(points):
        return [project(cam, f, q)[0] for q in points]
    p = xs([[POST[0] + dx, POST[1] + dy, z] for dx in (-0.06, 0.06) for dy in (-0.06, 0.06) for z in (0.1, 3.2)])
    x, y, _ = root_at(name, f)
    b = xs([[x + dx, y + dy, z] for dx in (-0.25, 0.25) for dy in (-0.25, 0.25) for z in (0.2, 1.7)])
    if max(p) < -0.5 or min(p) > 0.5 or max(b) < -0.5 or min(b) > 0.5:
        return None
    return max(min(p) - max(b), min(b) - max(p))


@pytest.mark.parametrize("shot_id", TRACKING)
def test_the_lamp_post_never_stands_behind_a_body(shot_id):
    """Preview 1 had the post rising out of A's head in sh05; no camera on the right side of the
    line could avoid it with the original timing, so the blocking changed (see B_STOP)."""
    s = shot(shot_id)
    for f in range(s.frame_start, s.frame_end + 1, 2):
        for name in ("traveller", "host"):
            g = post_gap(s.camera, f, name)
            assert g is None or g > 0.02, (shot_id, f, name, g)


def test_the_lamp_post_is_out_of_frame_in_the_hosts_response():
    """Preview 1 had the post as a thick vertical on the right edge of sh03; now the post and
    its globe (radius 0.17 m) stay just past the right edge, with the camera tracking B."""
    s = shot("sh03_host_response")
    globe = next(p for p in SPEC.primitives if p.name == "lamp_globe").transform.location
    for f in range(s.frame_start, s.frame_end + 1):
        xs = [project(s.camera, f, [POST[0], POST[1], z])[0] for z in (0.1, 3.2)]
        xs += [project(s.camera, f, [globe[0] + dx, globe[1], globe[2]])[0] for dx in (-0.17, 0.17)]
        assert min(xs) > 0.51, (f, xs)


def test_the_closing_wide_ends_with_the_pair_large_enough_to_read():
    s = shot("sh06_together_wide")
    for name in ("traveller", "host"):
        ys = [project(s.camera, 576, p)[1] for p in body_points(name, 576)]
        assert max(ys) - min(ys) > 0.38, name


def test_the_two_never_overlap_on_screen_while_b_leads():
    """Revision 2 review: a camera that cleared the post had B walk across A on screen; keep
    the two bodies (stride boxes) apart in sh04 as B turns, walks and waits."""
    s = shot("sh04_host_leads")
    for f in range(s.frame_start, s.frame_end + 1, 2):
        a = [project(s.camera, f, p)[0] for p in body_points("traveller", f)]
        b = [project(s.camera, f, p)[0] for p in body_points("host", f)]
        assert max(min(b) - max(a), min(a) - max(b)) > 0.03, f


# ---------------------------------------------------------------------------------------------
# The road (preview-2 review): what A looks toward, invisible to every camera of The Greeting
# ---------------------------------------------------------------------------------------------
ROAD = next(p for p in SPEC.primitives if p.name == "road")
ROAD_START, ROAD_WIDTH = 8.5, 2.6                 # metres along the route from the origin; width
GROUND_HALF = 50.0                                # the 100 m ground plane


def road_points(step=0.5):
    """Points over the road strip (centreline and edges), from its plane primitive."""
    length, width, _ = ROAD.keys[0].scale
    c = ROAD.transform.location
    yaw = math.radians(ROAD.transform.rotation_deg[2])
    ax, ay = (math.cos(yaw), math.sin(yaw)), (-math.sin(yaw), math.cos(yaw))
    pts, t = [], -length / 2
    while t <= length / 2:
        for u in (-width / 2, 0.0, width / 2):
            pts.append([c[0] + t * ax[0] + u * ay[0], c[1] + t * ax[1] + u * ay[1], c[2]])
        t += step
    return pts


def test_the_road_is_a_flat_strip_along_the_route_under_both_walking_lanes():
    assert ROAD.shape.value == "plane" and ROAD.size == 1.0 and len(ROAD.keys) == 1
    length, width, _ = ROAD.keys[0].scale
    assert width == ROAD_WIDTH and ROAD.transform.rotation_deg[2] == ROUTE - 90, "its length runs along the route"
    d, left = facing_xy(ROUTE), (-facing_xy(ROUTE)[1], facing_xy(ROUTE)[0])
    c = ROAD.transform.location
    assert (c[0] * d[0] + c[1] * d[1]) - length / 2 == pytest.approx(ROAD_START, abs=1e-3)
    centre_lane = c[0] * left[0] + c[1] * left[1]
    for name in ("traveller", "host"):
        lane = root_at(name, 576)[0] * left[0] + root_at(name, 576)[1] * left[1]
        assert abs(lane - centre_lane) + 0.3 < width / 2, name
    assert all(abs(p[0]) < 50 and abs(p[1]) < 50 for p in road_points()), "on the 100 m ground"
    assert 0 < c[2] <= 0.02, "just above the ground"


def test_the_greeting_never_shows_the_road():
    """Continuity: the road starts beyond every camera of the approved M7 scene, on every frame
    (pinhole model of tests/test_m7_greeting_spec.py), with a 3% frame margin."""
    import test_m7_greeting_spec as m7
    pts = road_points(0.5)
    for s in m7.SPEC.shots:
        for f in range(s.frame_start, s.frame_end + 1, 3):
            for p in pts:
                try:
                    x, y = m7.project(s.camera, f, p)
                except AssertionError:           # behind the camera
                    continue
                assert abs(x) > 0.53 or abs(y) > 0.53, (s.shot_id, f, p)


@pytest.mark.parametrize("shot_id", INSERTS)
def test_both_inserts_show_the_road_leading_away(shot_id):
    cam = shot(shot_id).camera
    seen = [q for q in (pov_project(cam, p) for p in road_points(1.0)) if q and abs(q[0]) < 0.45 and abs(q[1]) < 0.45]
    assert len(seen) > 40, len(seen)


def test_the_two_step_onto_the_road_together_at_the_end():
    d, left = facing_xy(ROUTE), (-facing_xy(ROUTE)[1], facing_xy(ROUTE)[0])
    for name in ("traveller", "host"):
        x, y, _ = root_at(name, 576)
        assert x * d[0] + y * d[1] > ROAD_START + 1.0, name


def road_share(cam):
    """Share of a fixed camera's frame that shows road: rays through a grid of frame points are
    cast onto the ground (z = 0) and tested against the road strip."""
    length, width, _ = ROAD.keys[0].scale
    c = ROAD.transform.location
    d, left = facing_xy(ROUTE), (-facing_xy(ROUTE)[1], facing_xy(ROUTE)[0])
    rx, rz = (math.radians(a) for a in (cam.keys[0].rotation_deg[0], cam.keys[0].rotation_deg[2]))
    fwd = [-math.sin(rz) * math.sin(rx), math.cos(rz) * math.sin(rx), -math.cos(rx)]
    right = _unit(_cross(fwd, [0, 0, 1]))
    up = _cross(right, fwd)
    k, loc = cam.lens_mm / 36, cam.keys[0].location
    w, h = SPEC.render.resolution
    hits = total = 0
    for i in range(-10, 11):
        for j in range(-6, 7):
            sx, sy = i / 20, j / 12 * h / w
            ray = [fwd[n] + sx / k * right[n] + sy / k * up[n] for n in range(3)]
            total += 1
            if ray[2] < 0:
                t = -loc[2] / ray[2]
                x, y = loc[0] + t * ray[0] - c[0], loc[1] + t * ray[1] - c[1]
                hits += abs(x * d[0] + y * d[1]) <= length / 2 and abs(x * left[0] + y * left[1]) <= width / 2
    return hits / total


def test_as_view_of_the_road_is_continuous_from_the_frame_edge_to_the_horizon():
    """Preview-3 review: at 35 mm the road showed as a patch, starting 8.5 m ahead (it cannot
    start nearer without entering M7's views) and stopping short of the ground's edge. A's view
    now runs level at 60 mm, so the road enters at the bottom edge, and it runs on to the edge of
    the ground, which is the horizon in this set."""
    cam = shot("sh02b_road_ahead").camera
    assert road_share(cam) > 0.08
    d = facing_xy(ROUTE)
    near = pov_project(cam, [ROAD_START * d[0], ROAD_START * d[1], 0.01])
    assert near[1] < -0.5, "the road's near end is below the frame: it enters at the bottom edge"
    length = ROAD.keys[0].scale[0]
    far = ROAD_START + length
    ground_edge = min(GROUND_HALF / abs(d[0]), GROUND_HALF / abs(d[1]))     # along the route
    assert 0 < ground_edge - far < 4.0, "the road ends within a few metres of the ground's edge"
    y_far = pov_project(cam, [far * d[0], far * d[1], 0.0])[1]
    y_edge = pov_project(cam, [ground_edge * d[0], ground_edge * d[1], 0.0])[1]
    assert abs(y_edge - y_far) < 0.01, "no visible band of grass between the road's end and the horizon"


# ---------------------------------------------------------------------------------------------
# Heads against the trees (preview-3 review): no tree crown or trunk behind a head in sh04
# ---------------------------------------------------------------------------------------------
HEAD_Z, HEAD_R = 1.65, 0.12


def _hull(points):
    pts = sorted(set(points))
    def turn(o, a, b): return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, hi = [], []
    for q in pts:
        while len(lo) >= 2 and turn(lo[-2], lo[-1], q) <= 0: lo.pop()
        lo.append(q)
    for q in reversed(pts):
        while len(hi) >= 2 and turn(hi[-2], hi[-1], q) <= 0: hi.pop()
        hi.append(q)
    return lo[:-1] + hi[:-1]


def _gap(a, b):
    """Distance between two convex screen polygons; -1 if they overlap (separating-axis test)."""
    for poly in (a, b):
        for i in range(len(poly)):
            (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % len(poly)]
            nx, ny = y1 - y0, x0 - x1
            pa = [nx * x + ny * y for x, y in a]
            pb = [nx * x + ny * y for x, y in b]
            if max(pa) < min(pb) or max(pb) < min(pa):
                break
        else:
            continue
        break
    else:
        return -1.0
    def seg(p, q0, q1):
        dx, dy = q1[0] - q0[0], q1[1] - q0[1]
        t = max(0.0, min(1.0, ((p[0] - q0[0]) * dx + (p[1] - q0[1]) * dy) / (dx * dx + dy * dy)))
        return math.hypot(p[0] - q0[0] - t * dx, p[1] - q0[1] - t * dy)
    return min(seg(p, q[i], q[(i + 1) % len(q)]) for p_, q in ((a, b), (b, a)) for p in p_ for i in range(len(q)))


def tree_silhouettes(cam, f):
    out = []
    for prim in SPEC.primitives:
        if not prim.name.startswith("tree"):
            continue
        c, size = prim.transform.location, prim.size
        sx, sz = (prim.keys[0].scale[0], prim.keys[0].scale[2]) if prim.keys else (1.0, 1.0)
        r, z0, z1 = size / 2 * sx, c[2] - size / 2 * sz, c[2] + size / 2 * sz
        ring = [[c[0] + r * math.cos(a), c[1] + r * math.sin(a)] for a in (2 * math.pi * k / 16 for k in range(16))]
        pts = [q + [z0] for q in ring] + ([q + [z1] for q in ring] if prim.shape.value == "cylinder" else [[c[0], c[1], z1]])
        out.append((prim.name, _hull([tuple(project(cam, f, q)) for q in pts])))
    return out


def head_outline(cam, f, name):
    x, y, _ = root_at(name, f)
    pts = [[x + HEAD_R * math.cos(a), y + HEAD_R * math.sin(a), HEAD_Z + dz]
           for a in (2 * math.pi * k / 12 for k in range(12)) for dz in (-HEAD_R, 0.0, HEAD_R)]
    return _hull([tuple(project(cam, f, q)) for q in pts])


def test_no_tree_stands_behind_a_head_while_b_leads():
    """Preview 3's sh04 camera, at head height, put tree crowns behind both heads (QA reports only
    near-touches, not a head inside a crown). The camera is now raised and looks down on the pair,
    so both heads sit against the grass: every head keeps 2% of the frame width from every tree."""
    s = shot("sh04_host_leads")
    for f in range(s.frame_start, s.frame_end + 1, 2):
        trees = tree_silhouettes(s.camera, f)
        for name in ("traveller", "host"):
            h = head_outline(s.camera, f, name)
            for tree, sil in trees:
                if max(x for x, _ in sil) < -0.5 or min(x for x, _ in sil) > 0.5:
                    continue
                assert _gap(h, sil) > 0.02, (f, name, tree)


# ---------------------------------------------------------------------------------------------
# The complete film: The Greeting followed by this scene, assembled with the M9 worker
# ---------------------------------------------------------------------------------------------
def test_the_film_edit_list_joins_the_approved_greeting_and_this_scene_in_order():
    from apps.api.schemas.edit_list import EditList, validate_sources
    edit = EditList.model_validate_json((ROOT / "schemas/examples/the_greeting_film.edit.json").read_text())
    assert edit.film_id == "the_greeting_film"
    assert [(c.clip_id, c.source, c.frames) for c in edit.clips] == [
        ("sc01_greeting", "storage/projects/m7_greeting/final_rev2/m7_greeting.mp4", 576),
        ("sc02_travellers_question", "storage/projects/m10_travellers_question/final_rev1/m10_travellers_question.mp4",
         SPEC.render.frame_end - SPEC.render.frame_start + 1)]
    f = edit.format
    assert (f.width, f.height, f.fps) == (*SPEC.render.resolution, SPEC.render.fps) and f.audio == "none"
    if all((ROOT / c.source).is_file() for c in edit.clips):            # storage/ is not tracked
        import hashlib
        assert validate_sources(edit, ROOT) == []
        for c in edit.clips:
            assert hashlib.sha256((ROOT / c.source).read_bytes()).hexdigest() == c.sha256, c.clip_id
