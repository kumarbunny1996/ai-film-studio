"""Milestone 8 Gate 2: workers/shot_qa.py rules and report, on small synthetic scenes (no Blender).

Scenes are built in world space and projected with workers/projection.py, the same module the
geometry inspector uses, so the cameras behave exactly like Blender's. The regression corpus
and the approved scenes run through the real builder in tests/test_shot_qa_corpus.py.
"""
import ast
import json
import math
from pathlib import Path

import pytest

from workers import projection as P
from workers import shot_qa as Q

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Synthetic scenes
# ---------------------------------------------------------------------------
def look_at(eye, target):
    f = [target[i] - eye[i] for i in range(3)]
    n = math.sqrt(sum(c * c for c in f))
    f = [c / n for c in f]
    r = [f[1], -f[0], 0.0]
    n = math.hypot(r[0], r[1])
    r = [c / n for c in r]
    up = [r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0]]
    return tuple((r[i], up[i], -f[i]) for i in range(3))


def cam(eye, target, lens=35.0, shift=(0.0, 0.0)) -> P.Camera:
    return P.Camera(location=tuple(eye), rotation=look_at(eye, target), lens=lens, sensor_width=36.0,
                    sensor_height=24.0, sensor_fit="AUTO", shift=shift, resolution=(640, 360))


def box(center, size):
    cx, cy, cz = center
    sx, sy, sz = (s / 2 for s in size)
    return [(cx + a * sx, cy + b * sy, cz + c * sz) for a in (-1, 1) for b in (-1, 1) for c in (-1, 1)]


def person(x, y, yaw_deg=0.0, hand_up=False):
    """A boxy person standing at (x, y) facing yaw (0 = -Y): {part: points}, {bone: (head, tail)}."""
    a = math.radians(yaw_deg)
    c, s = math.cos(a), math.sin(a)

    def w(px, py, pz):                                 # local (+X left, -Y forward) to world
        return (x + c * px - s * py, y + s * px + c * py, pz)

    parts = {"head": [w(*p) for p in box((0, 0, 1.65), (0.2, 0.2, 0.2))],
             "chest": [w(*p) for p in box((0, 0, 1.3), (0.38, 0.2, 0.3))],
             "hips": [w(*p) for p in box((0, 0, 0.95), (0.32, 0.18, 0.2))],
             "thigh.L": [w(*p) for p in box((0.1, 0, 0.5), (0.12, 0.12, 0.8))],
             "thigh.R": [w(*p) for p in box((-0.1, 0, 0.5), (0.12, 0.12, 0.8))],
             "hand.R": [w(*p) for p in box((-0.3, 0, 1.95 if hand_up else 0.9), (0.08, 0.08, 0.16))]}
    bones = {"hips": (w(0, 0, 0.95), w(0, 0, 1.05)), "head": (w(0, 0, 1.55), w(0, 0, 1.75)),
             "upper_arm.L": (w(0.18, 0, 1.42), w(0.25, 0, 1.15)),
             "upper_arm.R": (w(-0.18, 0, 1.42), w(-0.25, 0, 1.15)),
             "foot.L": (w(0.1, 0, 0.08), w(0.1, -0.15, 0.04)), "foot.R": (w(-0.1, 0, 0.08), w(-0.1, -0.15, 0.04))}
    return parts, bones


def scene(frames, objects_meta, spec):
    return {"schema": "shot_geometry.v1", "frame_range": [frames[0]["frame"], frames[-1]["frame"]],
            "objects": objects_meta, "armatures": {f"RIG-{o['owner']}": {"owner": o["owner"], "bones": []}
                                                    for o in objects_meta.values() if o["kind"] == "character"},
            "frames": frames}


def frame(n, shot_id, c: P.Camera, people=None, things=None):
    """people: {owner: (parts, bones)}; things: {name: points}."""
    objects, rigs = {}, {}
    for owner, (parts, bones) in (people or {}).items():
        islands = {lab: P.outline(c, pts) for lab, pts in parts.items()}
        islands = {k: v for k, v in islands.items() if v}
        allp = [p for pts in parts.values() for p in pts]
        whole = P.outline(c, allp)
        whole.update(in_frame=P.polygon_overlaps_frame(whole["hull"]), islands=islands)
        objects[f"GEO-{owner}"] = whole
        rigs[f"RIG-{owner}"] = {b: {"head": P.rounded_point(P.project(c, h)), "tail": P.rounded_point(P.project(c, t))}
                                for b, (h, t) in bones.items()}
    for name, pts in (things or {}).items():
        o = P.outline(c, pts)
        o.update(in_frame=P.polygon_overlaps_frame(o["hull"]), islands={"island_0": dict(o)})
        objects[f"PRIM-{name}"] = o
    return {"frame": n, "shot_id": shot_id, "camera_object": f"CAM-{shot_id}", "camera": c.to_dict(),
            "objects": objects, "armatures": rigs}


def meta(people=(), things=(), props=()):
    m = {f"GEO-{p}": {"owner": p, "kind": "character", "islands": [], "vertices": 0} for p in people}
    m.update({f"PRIM-{t}": {"owner": t, "kind": "primitive", "islands": ["island_0"], "vertices": 0} for t in things})
    m.update({f"PRIM-{t}": {"owner": t, "kind": "prop", "islands": ["island_0"], "vertices": 0} for t in props})
    return m


def spec(shots, lighting=None, props=()):
    return {"project_id": "t", "scene_id": "sc01", "shot_id": "t",
            "lighting": lighting or {"preset": "midday", "sun_azimuth_deg": 10, "sun_elevation_deg": 14},
            "shots": [{"shot_id": sid, "camera": cam} for sid, cam in shots],
            "props": [{"name": p, "parent": "a"} for p in props]}


def findings(geo, sp, accepted=None):
    return Q.build_report(geo, sp, {"test": True}, accepted)["findings"]


def rules(fs):
    return [(f["rule"], f["severity"]) for f in fs]


FRONT = cam((0.0, -6.0, 1.2), (0.0, 0.0, 1.0))


# ---------------------------------------------------------------------------
# Constants and helpers
# ---------------------------------------------------------------------------
def test_sun_presets_match_build_scene():
    tree = ast.parse((ROOT / "blender/scripts/build_scene.py").read_text())
    node = next(n for n in tree.body if isinstance(n, ast.Assign) and n.targets[0].id == "LIGHT_PRESETS")
    presets = ast.literal_eval(node.value)
    assert {k: (v[0], v[1]) for k, v in presets.items()} == Q.SUN_PRESETS


@pytest.mark.parametrize("res, shift", [((640, 360), (0.1, -0.05)), ((360, 640), (0.05, 0.1))])
def test_unproject_inverts_the_projection(res, shift):
    c = P.Camera(location=(1.0, -5.0, 1.5), rotation=look_at((1.0, -5.0, 1.5), (0.0, 0.0, 1.0)),
                 lens=40.0, sensor_width=36.0, sensor_height=24.0, sensor_fit="AUTO", shift=shift,
                 resolution=res)
    for p in [(0.3, 0.4, 1.2), (-2.0, 3.0, 0.1), (5.0, 8.0, 3.0)]:
        assert Q.unproject(c, P.project(c, p)) == pytest.approx(p, abs=1e-9)


def test_polygon_geometry_helpers():
    sq = [(0, 0), (1, 0), (1, 1), (0, 1)]
    assert Q.area(sq) == 1.0
    assert Q.area(Q.clip_rect(sq, 0.5, 0.0, 2.0, 2.0)) == pytest.approx(0.5)
    assert Q.area(Q.convex_clip([(0.5, 0.5), (1.5, 0.5), (1.5, 1.5), (0.5, 1.5)], sq)) == pytest.approx(0.25)
    assert Q.signed_distance(sq, [(2, 0), (3, 0), (3, 1)]) == pytest.approx(1.0)
    assert Q.signed_distance(sq, [(0.9, 0), (2, 0), (2, 1), (0.9, 1)]) == pytest.approx(-0.1)
    kind, measure, points = Q.contact(sq, [(1.005, 0.2), (2, 0.2), (2, 0.8)])
    assert kind == "gap" and measure == pytest.approx(0.005)
    assert all(q[0] == pytest.approx(1.0025) for q in points) and len(points) > 1


# ---------------------------------------------------------------------------
# Cropping and headroom
# ---------------------------------------------------------------------------
def test_wide_shot_flags_a_character_cut_by_the_frame_edge_but_not_a_whole_or_absent_one():
    sp = spec([("w", {"shot_size": "wide"})])
    for x, expect in ((-3.25, [("wide_body_cropped", "error")]), (0.0, []), (-9.0, [])):
        geo = scene([frame(1, "w", FRONT, {"a": person(x, 0.0)})], meta(["a"]), sp)
        assert rules(findings(geo, sp)) == expect, x


def test_head_cut_by_the_top_edge_is_an_error_but_a_side_entrance_is_not():
    sp = spec([("m", {"shot_size": "medium"})])
    low = cam((0.0, -2.0, 0.8), (0.0, 0.0, 0.8), lens=30.0)          # head above the frame
    geo = scene([frame(1, "m", low, {"a": person(0.0, 0.0)})], meta(["a"]), sp)
    assert ("head_cropped", "error") in rules(findings(geo, sp))
    side = cam((0.0, -4.0, 1.2), (0.0, 0.0, 1.2), lens=35.0, shift=(-0.43, 0.0))  # at the left edge
    geo = scene([frame(1, "m", side, {"a": person(-1.0, 0.0)})], meta(["a"]), sp)
    assert "head_cropped" not in [r for r, _ in rules(findings(geo, sp))]


def shifted_so(point, y_target, eye=(0.0, -3.0, 1.2), target=(0.0, 0.0, 1.2), lens=35.0):
    """A camera whose vertical lens shift puts world `point` at frame height y_target."""
    c = cam(eye, target, lens)
    y0 = P.project(c, point)[1]
    return cam(eye, target, lens, shift=(0.0, (y0 - y_target) / c.aspect()))


def test_subject_headroom_and_raised_hand_cropping():
    sp = spec([("m", {"shot_size": "medium", "look_at": "a"})])
    head_top = (0.0, -0.1, 1.75)                       # front-top edge of the head box
    tight = shifted_so(head_top, 0.995)
    geo = scene([frame(1, "m", tight, {"a": person(0.0, 0.0)})], meta(["a"]), sp)
    assert rules(findings(geo, sp)) == [("subject_headroom", "warning")]
    room = shifted_so(head_top, 0.9)
    geo = scene([frame(1, "m", room, {"a": person(0.0, 0.0, hand_up=True)})], meta(["a"]), sp)
    assert ("raised_hand_cropped", "error") in rules(findings(geo, sp)), "the raised hand leaves the frame"
    geo = scene([frame(1, "m", room, {"a": person(0.0, 0.0)})], meta(["a"]), sp)
    assert rules(findings(geo, sp)) == []


# ---------------------------------------------------------------------------
# Edge slivers
# ---------------------------------------------------------------------------
def test_edge_sliver_flags_a_thin_poke_but_not_a_large_part_a_spanning_or_an_attached_object():
    sp = spec([("w", {"shot_size": "wide"})], props=["stick"])
    sliver = box((-4.5, 2.0, 1.0), (1.0, 0.2, 2.0))        # the frame's left edge at y = 2 is x -4.11
    big = box((-2.0, 2.0, 1.0), (2.0, 1.0, 2.0))
    ground = [(-50, -5, 0), (50, -5, 0), (50, 50, 0), (-50, 50, 0)]
    geo = scene([frame(1, "w", FRONT, things={"post": sliver, "big": big, "ground": ground, "stick": sliver})],
                meta(things=["post", "big", "ground"], props=["stick"]), sp)
    fs = findings(geo, sp)
    assert [(f["rule"], f["objects"][0]["id"], f["objects"][1]["id"]) for f in fs] == [("edge_sliver", "post", "left")]


# ---------------------------------------------------------------------------
# Tangents and raised hands
# ---------------------------------------------------------------------------
def head_touching(frames, gap_m=0.0, behind=3.0):
    """A pole behind a person whose left edge (screen) meets the head's right edge."""
    pole = box((0.1 + 0.15 + gap_m, behind, 1.5), (0.3, 0.3, 3.0))
    c = cam((0.0, -4.0, 1.4), (0.0, 0.0, 1.4))
    # widen the pole so its projected edge meets the head's projected edge
    scale = (4.0 + behind) / 4.0
    pole = box((0.1 * scale + 0.15 + gap_m, behind, 1.5), (0.3, 0.3, 3.0))
    return [frame(n, "m", c, {"a": person(0.0, 0.0)}, {"pole": pole}) for n in range(1, frames + 1)], c


def test_a_head_kissing_a_background_object_is_an_error_after_six_frames():
    sp = spec([("m", {"shot_size": "medium"})])
    fr, _ = head_touching(6)
    fs = findings(scene(fr, meta(["a"], ["pole"]), sp), sp)
    hits = [f for f in fs if f["rule"] == "tangent"]
    assert hits and hits[0]["severity"] == "error" and {"kind": "part", "id": "head"} in hits[0]["objects"]
    assert hits[0]["frames"] == [1, 6]
    fr, _ = head_touching(5)
    assert not [f for f in findings(scene(fr, meta(["a"], ["pole"]), sp), sp) if f["rule"] == "tangent"], \
        "shorter than min_frames"


def test_a_contact_that_slides_past_is_info_not_a_static_tangent():
    """A person walking past a background pole: the outlines touch for many frames, but they
    slide past each other, so the finding is info, not an error."""
    sp = spec([("m", {"shot_size": "medium"})])
    c = cam((0.0, -4.0, 1.4), (0.0, 0.0, 1.4))
    scale = 7.0 / 4.0
    fr = []
    for n in range(1, 9):
        dx = 0.004 * n                                  # the pole drifts relative to the person
        pole = box((0.1 * scale + 0.15 + dx * scale, 3.0, 1.5), (0.3, 0.3, 3.0))
        fr.append(frame(n, "m", c, {"a": person(dx, 0.0)}, {"pole": pole}))
    static = [f for f in findings(scene(fr, meta(["a"], ["pole"]), sp), sp) if f["rule"] == "tangent"]
    assert static and all(f["severity"] != "info" for f in static), "moving together: still static"
    # the pole slides down along its own edge: the gap stays, the outlines move past each other
    fr = [frame(n, "m", c, {"a": person(0.0, 0.0)}, {"pole": box((0.1 * scale + 0.15, 3.0, 1.9 - 0.05 * n), (0.3, 0.3, 3.0))})
          for n in range(1, 9)]
    moving = [f for f in findings(scene(fr, meta(["a"], ["pole"]), sp), sp) if f["rule"] == "tangent"]
    assert moving and all(f["severity"] == "info" and f["measured"]["relative_speed"] > 0.002 for f in moving)


def test_deep_overlaps_and_physically_touching_pairs_are_not_tangents():
    sp = spec([("m", {"shot_size": "medium"})])
    c = cam((0.0, -4.0, 1.4), (0.0, 0.0, 1.4))
    behind = box((0.0, 3.0, 1.5), (0.3, 0.3, 3.0))         # straight behind the person: deep overlap
    touching = box((0.25, 0.0, 1.5), (0.1, 0.1, 3.0))      # beside the head, same depth
    fr = [frame(n, "m", c, {"a": person(0.0, 0.0)}, {"behind": behind, "touching": touching}) for n in range(1, 9)]
    assert not [f for f in findings(scene(fr, meta(["a"], ["behind", "touching"]), sp), sp) if f["rule"] == "tangent"]


def test_a_contact_is_hidden_only_when_nearer_parts_cover_the_whole_touching_stretch():
    chest = [(0.0, 0.0), (0.4, 0.0), (0.4, 0.4), (0.0, 0.4)]
    post = [(0.405, -0.5), (0.45, -0.5), (0.45, 1.0), (0.405, 1.0)]       # 0.005 to the right
    kind, gap, points = Q.contact(chest, post, max_gap=0.012)
    assert kind == "gap" and gap == pytest.approx(0.005)
    ys = sorted(q[1] for q in points)
    assert ys[0] == pytest.approx(0.0) and ys[-1] == pytest.approx(0.4), "the whole parallel edge"
    covered = lambda arm, depth: all(Q._hidden(q, {"a": {"chest": (chest, [4.0, 4.2]), "arm": (arm, depth)}},
                                               ("a", "chest"), None, far_depth=5.4) for q in points)
    assert covered([(0.35, -0.1), (0.5, -0.1), (0.5, 0.5), (0.35, 0.5)], [3.8, 3.9]), "arm over all of it"
    assert not covered([(0.35, 0.1), (0.5, 0.1), (0.5, 0.3), (0.35, 0.3)], [3.8, 3.9]), "partly exposed"
    assert not covered([(0.35, -0.1), (0.5, -0.1), (0.5, 0.5), (0.35, 0.5)], [5.5, 5.6]), "arm behind the post"


def test_a_raised_hand_touching_an_object_is_a_warning_but_a_lowered_one_is_not():
    sp = spec([("m", {"shot_size": "medium"})])
    c = cam((0.0, -4.0, 1.4), (0.0, 0.0, 1.4))
    scale = 7.0 / 4.0
    pole = box((-0.34 * scale, 3.0, 1.5), (0.3, 0.3, 3.0))  # its right edge meets the raised hand
    fr = [frame(n, "m", c, {"a": person(0.0, 0.0, hand_up=True)}, {"pole": pole}) for n in range(1, 4)]
    assert "raised_hand_contact" in [f["rule"] for f in findings(scene(fr, meta(["a"], ["pole"]), sp), sp)]
    fr = [frame(n, "m", c, {"a": person(0.0, 0.0, hand_up=False)}, {"pole": pole}) for n in range(1, 4)]
    assert "raised_hand_contact" not in [f["rule"] for f in findings(scene(fr, meta(["a"], ["pole"]), sp), sp)]


# ---------------------------------------------------------------------------
# Cuts: camera side, eyelines, screen direction
# ---------------------------------------------------------------------------
def two_shot_cut(second_eye):
    """A at (-1, 0) facing +X, B at (1, 0) facing -X; a cut from a camera at -Y to second_eye."""
    a, b = person(-1.0, 0.0, 90.0), person(1.0, 0.0, -90.0)
    c1 = cam((0.0, -5.0, 1.4), (0.0, 0.0, 1.2))
    c2 = cam(second_eye, (0.0, 0.0, 1.2))
    fr = [frame(1, "s1", c1, {"a": a, "b": b}), frame(2, "s1", c1, {"a": a, "b": b}),
          frame(3, "s2", c2, {"a": a, "b": b}), frame(4, "s2", c2, {"a": a, "b": b})]
    sp = spec([("s1", {"shot_size": "medium"}), ("s2", {"shot_size": "medium"})])
    return scene(fr, meta(["a", "b"]), sp), sp


def test_crossing_the_line_at_a_cut_is_an_error_with_eyeline_warnings():
    geo, sp = two_shot_cut((0.5, 5.0, 1.4))
    got = rules(findings(geo, sp))
    assert ("camera_side", "error") in got and ("eyeline", "warning") in got


def test_a_cut_on_the_same_side_of_the_line_is_clean():
    geo, sp = two_shot_cut((1.5, -4.0, 1.4))
    assert not [r for r in rules(findings(geo, sp)) if r[0] in ("camera_side", "eyeline")]


def test_a_reversed_screen_direction_across_a_cut_is_a_warning():
    c1 = cam((0.0, -6.0, 1.2), (0.0, 0.0, 1.0))
    c2 = cam((0.0, 6.0, 1.2), (0.0, 0.0, 1.0))            # opposite side: motion reverses on screen
    fr = [frame(n, "s1" if n <= 2 else "s2", c1 if n <= 2 else c2, {"a": person(-0.5 + 0.1 * n, 0.0, 90.0)})
          for n in range(1, 5)]
    sp = spec([("s1", {"shot_size": "wide"}), ("s2", {"shot_size": "wide"})])
    assert ("screen_direction", "warning") in rules(findings(scene(fr, meta(["a"]), sp), sp))


# ---------------------------------------------------------------------------
# Backlighting
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("lighting, flagged", [
    ({"preset": "midday", "sun_azimuth_deg": 180, "sun_elevation_deg": 14}, True),    # sun behind A
    ({"preset": "midday", "sun_azimuth_deg": 0, "sun_elevation_deg": 14}, False),     # sun behind camera
    ({"preset": "overcast", "sun_azimuth_deg": 180}, False),                          # diffuse
    ({"preset": "midday", "sun_azimuth_deg": 180, "sun_elevation_deg": 75}, False)])  # high sun
def test_backlight_flags_a_camera_looking_into_the_sun(lighting, flagged):
    sp = spec([("m", {"shot_size": "medium"})], lighting)
    geo = scene([frame(1, "m", cam((0.0, -3.0, 1.2), (0.0, 0.0, 1.0)), {"a": person(0.0, 0.0)})], meta(["a"]), sp)
    assert (("backlight", "warning") in rules(findings(geo, sp))) == flagged


# ---------------------------------------------------------------------------
# Report contract
# ---------------------------------------------------------------------------
def test_report_contract_ordering_and_determinism():
    geo, sp = two_shot_cut((0.5, 5.0, 1.4))
    a = Q.build_report(geo, sp, {"geometry": {"file": "g.json", "sha256": "0"}})
    b = Q.build_report(json.loads(json.dumps(geo)), json.loads(json.dumps(sp)), {"geometry": {"file": "g.json", "sha256": "0"}})
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert (a["schema"], a["verdict"], a["human_approval_required"]) == ("composition_report.v1", "evidence_only", True)
    assert [r["id"] for r in a["rules"]] == sorted(Q.RULES)
    assert all({"id", "version", "severity", "thresholds", "limitations", "description"} <= set(r) for r in a["rules"])
    order = {"error": 0, "warning": 1, "info": 2}
    keys = [(order[f["severity"]], f["frames"][0], f["rule"], f["id"]) for f in a["findings"]]
    assert keys == sorted(keys)
    for f in a["findings"]:
        assert {"id", "rule", "rule_version", "severity", "shot_id", "frames", "objects", "measured",
                "threshold", "explanation", "evidence", "accepted"} <= set(f)
    assert a["summary"]["error"] == sum(1 for f in a["findings"] if f["severity"] == "error")


def test_accepted_annotations_mark_findings_without_hiding_them():
    geo, sp = two_shot_cut((0.5, 5.0, 1.4))
    acc = [{"rule": "camera_side", "shot_id": "s2", "frames": [3, 3], "kind": "false_positive",
            "objects": [{"kind": "character", "id": "a"}], "reason": "test"}]
    r = Q.build_report(geo, sp, {}, acc)
    hit = next(f for f in r["findings"] if f["rule"] == "camera_side")
    assert hit["accepted"] == {"kind": "false_positive", "reason": "test"}
    assert r["summary"]["error"] == 0 and r["summary"]["accepted"] >= 1


def test_cli_writes_the_review_report_and_refuses_other_geometry(tmp_path):
    geo, sp = two_shot_cut((1.5, -4.0, 1.4))
    (tmp_path / "review").mkdir()
    (tmp_path / "review" / "shot_geometry.json").write_text(json.dumps(geo))
    (tmp_path / "spec.json").write_text(json.dumps(sp))
    assert Q.main(["--shot-dir", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "review" / "composition_report.json").read_text())
    assert report["inputs"]["geometry"]["file"] == "shot_geometry.json"
    (tmp_path / "review" / "shot_geometry.json").write_text(json.dumps({**geo, "schema": "other"}))
    assert Q.main(["--shot-dir", str(tmp_path), "--out", str(tmp_path / "x.json")]) == 1
    assert not (tmp_path / "x.json").exists()
