"""Shot QA: read-only composition checks on a built shot (Milestone 8).

    uv run python -m workers.shot_qa --geometry <shot_geometry.json> --spec <spec.json> \
        --out <composition_report.json> [--accepted <accepted.json>]
    uv run python -m workers.shot_qa --shot-dir <shot-dir> [--accepted <accepted.json>]

With --shot-dir the inputs are <shot-dir>/review/shot_geometry.json (written by
blender/scripts/inspect_shot_geometry.py) and <shot-dir>/spec.json, and the report goes to
<shot-dir>/review/composition_report.json.

The report is evidence for a human, like workers/contact_sheet.py's: `verdict` is always
"evidence_only" and `human_approval_required` always true. Findings never approve, block or
change anything. Every rule is a heuristic over 2D outlines, depths and bone points; its
limitations are written into the report. A projected overlap is not proof of a visual
collision, so rules abstain where visibility is ambiguous.

Geometry comes only from the inspector's report (shot_geometry.v1). The SceneSpec adds what
geometry cannot carry: shot sizes and look_at subjects, the sun, and which props are attached
to characters. World positions of characters are recovered by inverting the frame's camera
projection (exact to the inspector's 6-decimal rounding).

Units: frame coordinates are converted to frame-height units (x times width/height), so a
distance of 0.01 is 1% of the frame height whichever axis it lies on.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

from workers.projection import Camera

SCHEMA = "composition_report.v1"
GEOMETRY_SCHEMA = "shot_geometry.v1"

# elevation deg, azimuth deg of build_scene.LIGHT_PRESETS (pinned by tests/test_shot_qa.py)
SUN_PRESETS = {"golden_hour": (8.0, 250.0), "overcast": (45.0, 180.0), "midday": (62.0, 160.0),
               "blue_hour": (2.0, 270.0), "night": (35.0, 120.0)}
DIFFUSE_PRESETS = {"overcast", "night"}
WIDE_SIZES = {"wide", "extreme_wide"}
HEAD_PARTS = ("head", "neck")
HAND_PARTS = ("hand", "forearm")

# Rule definitions: id -> (version, default severity, description, thresholds, limitations)
RULES = {
    "wide_body_cropped": (1, "error",
        "In a wide shot every character that is in frame is whole: none is cut by a frame edge.",
        {"min_in_frame_fraction": 0.02, "max_in_frame_fraction": 0.98},
        "Fraction is the summed area of a character's part outlines inside the frame; parts "
        "overlapping on screen are counted twice. Characters fully outside are not flagged."),
    "head_cropped": (1, "error",
        "A character that is mostly in frame does not have its head cut by a frame edge.",
        {"min_body_in_frame": 0.5, "min_head_in_frame": 0.95, "min_extra_head_crop": 0.25},
        "Flagged when the head is cut by the top edge, or is cut by more than min_extra_head_crop "
        "beyond the body (a character crossing a side edge has head and body cut together). A "
        "character mostly out of frame (entering, exiting or an over-the-shoulder foreground) is "
        "not checked; heads are found by part names containing 'head'."),
    "subject_headroom": (1, "warning",
        "In a medium or closer shot the camera's subject has headroom above the head.",
        {"min_top_margin": 0.02},
        "Subject = the shot camera's look_at. Margin is from the top of the head outline to the "
        "top edge, in frame heights."),
    "raised_hand_cropped": (1, "error",
        "A hand raised above the head stays in frame while the head is in frame.",
        {"min_hand_in_frame": 0.9},
        "Raised = the hand's projected top is above the head's projected top."),
    "raised_hand_headroom": (1, "warning",
        "A raised hand keeps a margin from the frame edge.",
        {"min_margin": 0.03},
        "Margin in frame heights from the hand outline to the nearest frame edge."),
    "edge_sliver": (1, "warning",
        "No object pokes a thin sliver into the frame from an edge.",
        {"max_depth_into_frame": 0.12, "max_visible_fraction": 0.5},
        "Characters, props attached to characters and objects spanning the frame are not "
        "checked. Depth into frame is measured perpendicular to the edge, as a fraction of the "
        "frame's width (left/right edges) or height (top/bottom)."),
    "tangent": (1, "error",
        "A character's outline and another object's outline at a different depth do not just "
        "touch on screen (error for head or neck, warning for other parts).",
        {"max_gap": 0.012, "max_overlap_fraction": 0.05, "min_depth_separation_m": 0.3,
         "min_frames": 6, "max_relative_speed": 0.002},
        "Uses convex part outlines. A tangent is a gap below max_gap, or an overlap covering at "
        "most max_overlap_fraction of the smaller outline; outlines crossing more deeply (one "
        "clearly in front of the other) are not tangents. A contact point inside a nearer part "
        "of the same character is hidden and skipped. Pairs closer than min_depth_separation_m in "
        "depth are treated as physically touching and skipped. Contacts lasting fewer than "
        "min_frames consecutive evaluated frames are not reported. A contact that slides (median "
        "relative screen speed of the two outlines above max_relative_speed, in frame heights "
        "per frame: a character walking past an object) is reported as info, not as a "
        "static tangent."),
    "raised_hand_contact": (1, "warning",
        "A raised hand or forearm does not touch or cross another object's outline at a "
        "different depth (a gesture reads against a clear background).",
        {"max_gap": 0.02, "min_depth_separation_m": 0.3, "min_frames": 2},
        "Raised = the part's top is above the base of the character's head on screen. Any "
        "overlap counts (the hand is drawn over or behind the object), and so does a gap below "
        "max_gap. Contacts outside the frame are ignored."),
    "camera_side": (1, "error",
        "Across a cut the camera stays on the same side of the line between two characters.",
        {"min_abs_sin": 0.1},
        "Checked for every pair of characters with at least one in frame on each side of the "
        "cut. Cameras nearly on the line (|sin| below min_abs_sin) are ambiguous and skipped."),
    "screen_direction": (1, "warning",
        "A character moving across the frame keeps its screen direction across a cut.",
        {"min_speed": 0.002},
        "Speed is the hips' horizontal screen motion per frame, in frame heights; both sides "
        "of the cut must be moving and in frame. Needs the frames next to the cut."),
    "eyeline": (1, "warning",
        "Across a cut a character looking at another keeps looking the same way on screen, "
        "and two characters seen in separate shots look toward each other.",
        {"max_gaze_angle_deg": 50.0, "min_screen_component": 0.35},
        "Gaze is approximated by the chest's facing (perpendicular to the shoulders, on the "
        "feet's side); head turns beyond the chest are not observable from bone points. Gazes "
        "mostly toward or away from the camera are ambiguous and skipped."),
    "backlight": (1, "warning",
        "The camera sees the sunlit side of each prominent character (a heuristic; a backlit "
        "subject may be intended).",
        {"max_seen_side": -0.25, "min_height_in_frame": 0.15, "max_sun_elevation_deg": 60.0},
        "Uses the SceneSpec sun (preset plus overrides) only, not template lights or the "
        "world; skipped for overcast and night presets and for high suns. seen_side is the "
        "cosine between the sun direction and the direction to the camera, horizontally."),
}


# ---------------------------------------------------------------------------------------------
# Small geometry helpers (frame-height units)
# ---------------------------------------------------------------------------------------------
def to_h(poly, aspect):
    return [(x * aspect, y) for x, y in poly]


def area(poly) -> float:
    n = len(poly)
    if n < 3:
        return 0.0
    return abs(sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1]
                   for i in range(n))) / 2


def clip_rect(poly, x0, y0, x1, y1):
    """Convex polygon clipped to an axis-aligned rectangle (Sutherland-Hodgman)."""
    def clip(pts, inside, cut):
        out = []
        for i in range(len(pts)):
            a, b = pts[i], pts[(i + 1) % len(pts)]
            if inside(a):
                out.append(a)
            if inside(a) != inside(b):
                out.append(cut(a, b))
        return out

    def lerp_x(x):
        return lambda a, b: (x, a[1] + (x - a[0]) * (b[1] - a[1]) / (b[0] - a[0]))

    def lerp_y(y):
        return lambda a, b: (a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1]), y)

    pts = list(poly)
    for inside, cut in ((lambda p: p[0] >= x0, lerp_x(x0)), (lambda p: p[0] <= x1, lerp_x(x1)),
                        (lambda p: p[1] >= y0, lerp_y(y0)), (lambda p: p[1] <= y1, lerp_y(y1))):
        if not pts:
            break
        pts = clip(pts, inside, cut)
    return pts


def _axes(poly):
    n = len(poly)
    for i in range(n):
        dx, dy = poly[(i + 1) % n][0] - poly[i][0], poly[(i + 1) % n][1] - poly[i][1]
        length = math.hypot(dx, dy)
        if length > 0:
            yield (-dy / length, dx / length)


def _seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    dd = dx * dx + dy * dy
    t = 0.0 if dd == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / dd))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def convex_clip(subject, clipper):
    """Intersection of two convex polygons (counter-clockwise clipper)."""
    out = list(subject)
    n = len(clipper)
    for i in range(n):
        if not out:
            break
        a, b = clipper[i], clipper[(i + 1) % n]

        def inside(p, a=a, b=b):
            return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) >= 0

        pts, out = out, []
        for j in range(len(pts)):
            p, q = pts[j], pts[(j + 1) % len(pts)]
            if inside(p):
                out.append(p)
            if inside(p) != inside(q):
                dx, dy = q[0] - p[0], q[1] - p[1]
                ex, ey = b[0] - a[0], b[1] - a[1]
                den = ex * dy - ey * dx
                if den:
                    t = (ey * (p[0] - a[0]) - ex * (p[1] - a[1])) / den
                    out.append((p[0] + t * dx, p[1] + t * dy))
    return out


def closest_points(a, b):
    """(distance, point on a, point on b) of two separated convex outlines."""
    best = (math.inf, None, None)
    for poly, other, first in ((a, b, True), (b, a, False)):
        for p in poly:
            for i in range(len(other)):
                q0, q1 = other[i], other[(i + 1) % len(other)]
                dx, dy = q1[0] - q0[0], q1[1] - q0[1]
                dd = dx * dx + dy * dy
                t = 0.0 if dd == 0 else max(0.0, min(1.0, ((p[0] - q0[0]) * dx + (p[1] - q0[1]) * dy) / dd))
                q = (q0[0] + t * dx, q0[1] + t * dy)
                d = math.hypot(p[0] - q[0], p[1] - q[1])
                if d < best[0]:
                    best = (d, p, q) if first else (d, q, p)
    return best


def point_in_convex(p, poly) -> bool:
    if len(poly) < 3:
        return False
    signs = [(poly[(i + 1) % len(poly)][0] - poly[i][0]) * (p[1] - poly[i][1])
             - (poly[(i + 1) % len(poly)][1] - poly[i][1]) * (p[0] - poly[i][0])
             for i in range(len(poly))]
    return all(v >= 0 for v in signs) or all(v <= 0 for v in signs)


CONTACT_SAMPLES = 8          # points per outline edge when tracing a touching stretch


def _dist_to(p, poly):
    return min(_seg_dist(p, poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly)))


def _nearest_on(p, poly):
    best, point = math.inf, p
    for i in range(len(poly)):
        q0, q1 = poly[i], poly[(i + 1) % len(poly)]
        dx, dy = q1[0] - q0[0], q1[1] - q0[1]
        dd = dx * dx + dy * dy
        t = 0.0 if dd == 0 else max(0.0, min(1.0, ((p[0] - q0[0]) * dx + (p[1] - q0[1]) * dy) / dd))
        q = (q0[0] + t * dx, q0[1] + t * dy)
        d = math.hypot(p[0] - q[0], p[1] - q[1])
        if d < best:
            best, point = d, q
    return point


def contact(a, b, max_gap=0.0):
    """(kind, measure, contact points) of two convex outlines.

    Separated: ("gap", distance, points), the points being midpoints between each outline and
    the other along the stretch where they are within max(max_gap, distance) of each other
    (edges sampled CONTACT_SAMPLES times), so a long parallel near-touch is traced, not just
    its closest corner. Overlapping: ("overlap", intersection area / smaller area, the
    intersection's vertices and centroid)."""
    if signed_distance(a, b) > 0:
        d, pa, pb = closest_points(a, b)
        reach = max(max_gap, d) + 1e-12
        points = []
        for poly, other in ((a, b), (b, a)):
            for i in range(len(poly)):
                p0, p1 = poly[i], poly[(i + 1) % len(poly)]
                for k in range(CONTACT_SAMPLES + 1):
                    t = k / CONTACT_SAMPLES
                    p = (p0[0] + t * (p1[0] - p0[0]), p0[1] + t * (p1[1] - p0[1]))
                    if _dist_to(p, other) <= reach:
                        q = _nearest_on(p, other)
                        points.append(((p[0] + q[0]) / 2, (p[1] + q[1]) / 2))
        return "gap", d, points or [((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2)]
    inter = convex_clip(a, b)
    small = min(area(a), area(b))
    if len(inter) < 3 or small == 0:
        return "overlap", 0.0, [a[0]]
    cx = sum(p[0] for p in inter) / len(inter)
    cy = sum(p[1] for p in inter) / len(inter)
    return "overlap", area(inter) / small, list(inter) + [(cx, cy)]


def signed_distance(a, b) -> float:
    """Separation of two convex polygons (> 0), or minus their penetration depth (<= 0),
    via separating axes. Points and segments count as degenerate polygons."""
    axes = list(_axes(a)) + list(_axes(b))
    if len(a) < 3 and len(b) < 3:
        axes += [(1.0, 0.0), (0.0, 1.0)]
    best_overlap = math.inf
    for nx, ny in axes:
        pa = [nx * x + ny * y for x, y in a]
        pb = [nx * x + ny * y for x, y in b]
        overlap = min(max(pa), max(pb)) - max(min(pa), min(pb))
        if overlap < 0:
            # separated: exact distance between the outlines
            return min(min(_seg_dist(p, b[i], b[(i + 1) % len(b)]) for i in range(len(b)) for p in a),
                       min(_seg_dist(p, a[i], a[(i + 1) % len(a)]) for i in range(len(a)) for p in b))
        best_overlap = min(best_overlap, overlap)
    return -best_overlap


def bbox(poly):
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def unproject(cam: Camera, p) -> tuple[float, float, float]:
    """World point of a projected (x, y, depth), inverting workers.projection.project."""
    x, y, depth = p
    s = cam.sensor_size() / cam.lens
    a = cam.aspect()
    if cam.fit() == "HORIZONTAL":
        u, v = x - 0.5 + cam.shift[0], (y - 0.5) / a + cam.shift[1]
    else:
        u, v = (x - 0.5) * a + cam.shift[0], y - 0.5 + cam.shift[1]
    local = (u * depth * s, v * depth * s, -depth)
    r = cam.rotation
    return tuple(cam.location[i] + sum(r[i][j] * local[j] for j in range(3)) for i in range(3))


def _fmt(v):
    if isinstance(v, float):
        return round(v, 4) + 0.0
    if isinstance(v, (list, tuple)):
        return [_fmt(x) for x in v]
    if isinstance(v, dict):
        return {k: _fmt(x) for k, x in sorted(v.items())}
    return v


# ---------------------------------------------------------------------------------------------
# Scene model built from the geometry and the spec
# ---------------------------------------------------------------------------------------------
class Scene:
    def __init__(self, geo: dict, spec: dict):
        if geo.get("schema") != GEOMETRY_SCHEMA:
            raise ValueError(f"geometry schema {geo.get('schema')!r}, expected {GEOMETRY_SCHEMA}")
        self.geo, self.spec = geo, spec
        self.frames = geo["frames"]
        self.objects = geo["objects"]
        self.char_meshes = {n: o["owner"] for n, o in self.objects.items() if o["kind"] == "character"}
        self.rigs = {a["owner"]: n for n, a in geo["armatures"].items()}
        self.attached = {p["name"] for p in spec.get("props", []) if p.get("parent")}
        self.shots = {s["shot_id"]: s for s in spec.get("shots") or []}

    def shot_camera(self, shot_id):
        if shot_id is None:
            return self.spec.get("camera") or {}
        return self.shots.get(shot_id, {}).get("camera", {})

    @staticmethod
    def camera(frame) -> Camera:
        return Camera.from_dict(frame["camera"])

    def bone(self, frame, owner, bone, end="head"):
        rig = self.rigs.get(owner)
        b = frame["armatures"].get(rig, {}).get(bone) if rig else None
        return b[end] if b else None

    def world_bone(self, frame, owner, bone, end="head"):
        p = self.bone(frame, owner, bone, end)
        if p is None or p[2] <= 0:
            return None
        return unproject(self.camera(frame), p)

    def character_parts(self, frame, owner):
        """{part label: (hull in height units, depth)} of a character in this frame."""
        aspect = self.camera(frame).aspect()
        out = {}
        for mesh, own in self.char_meshes.items():
            if own != owner or mesh not in frame["objects"]:
                continue
            for label, isl in frame["objects"][mesh]["islands"].items():
                out[label] = (to_h(isl["hull"], aspect), isl["depth"])
        return out

    def in_frame_fraction(self, frame, hulls) -> float:
        aspect = self.camera(frame).aspect()
        total = inside = 0.0
        for hull in hulls:
            a = area(hull)
            total += a
            inside += area(clip_rect(hull, 0.0, 0.0, aspect, 1.0)) if a else 0.0
        return inside / total if total else 0.0

    def facing(self, frame, owner):
        """Horizontal unit facing of a character from its shoulders and feet (world)."""
        l, r = self.world_bone(frame, owner, "upper_arm.L"), self.world_bone(frame, owner, "upper_arm.R")
        feet = [(self.world_bone(frame, owner, f"foot.{s}"), self.world_bone(frame, owner, f"foot.{s}", "tail"))
                for s in "LR"]
        if None in (l, r) or any(None in f for f in feet):
            return None
        sx, sy = l[0] - r[0], l[1] - r[1]
        fx = sum(t[0] - h[0] for h, t in feet)
        fy = sum(t[1] - h[1] for h, t in feet)
        nx, ny = sy, -sx
        if nx * fx + ny * fy < 0:
            nx, ny = -nx, -ny
        n = math.hypot(nx, ny)
        return (nx / n, ny / n) if n else None

    def characters(self):
        return sorted(set(self.char_meshes.values()))


# ---------------------------------------------------------------------------------------------
# Rules: each yields per-frame hits (frame, shot, objects, measured dict, severity)
# ---------------------------------------------------------------------------------------------
def _part_kind(label):
    low = label.lower()
    return "head" if any(h in low for h in HEAD_PARTS) else "hand" if any(h in low for h in HAND_PARTS) else "body"


def rule_cropping(scene: Scene):
    t_wide = RULES["wide_body_cropped"][3]
    t_head = RULES["head_cropped"][3]
    t_room = RULES["subject_headroom"][3]
    t_hand = RULES["raised_hand_cropped"][3]
    t_hroom = RULES["raised_hand_headroom"][3]
    for f in scene.frames:
        cam = scene.shot_camera(f["shot_id"])
        size = cam.get("shot_size", "medium")
        aspect = scene.camera(f).aspect()
        for owner in scene.characters():
            parts = scene.character_parts(f, owner)
            if not parts:
                continue
            body = scene.in_frame_fraction(f, [h for h, _ in parts.values()])
            if body == 0.0:
                continue
            ref = [("character", owner)]
            if size in WIDE_SIZES and t_wide["min_in_frame_fraction"] < body < t_wide["max_in_frame_fraction"]:
                yield "wide_body_cropped", f, ref, {"in_frame_fraction": body}, None
            heads = [h for lab, (h, _) in parts.items() if _part_kind(lab) == "head" and "head" in lab.lower()]
            if not heads:
                continue
            head = heads[0]
            head_in = scene.in_frame_fraction(f, [head])
            if (body >= t_head["min_body_in_frame"] and head_in < t_head["min_head_in_frame"]
                    and (bbox(head)[3] > 1.0 or head_in < body - t_head["min_extra_head_crop"])):
                yield "head_cropped", f, ref + [("part", "head")], {"head_in_frame_fraction": head_in,
                                                                     "body_in_frame_fraction": body}, None
            head_top = bbox(head)[3]
            if (size not in WIDE_SIZES and cam.get("look_at") == owner and head_in >= 0.95
                    and 1.0 - head_top < t_room["min_top_margin"]):
                yield "subject_headroom", f, ref, {"top_margin": 1.0 - head_top}, None
            if head_in < 0.95:
                continue
            for lab, (hull, _) in sorted(parts.items()):
                if not lab.lower().startswith("hand") or bbox(hull)[3] <= head_top:
                    continue
                hand_in = scene.in_frame_fraction(f, [hull])
                x0, y0, x1, y1 = bbox(hull)
                margin = min(x0, y0, aspect - x1, 1.0 - y1)
                if hand_in < t_hand["min_hand_in_frame"]:
                    yield "raised_hand_cropped", f, ref + [("part", lab)], {"hand_in_frame_fraction": hand_in}, None
                elif margin < t_hroom["min_margin"]:
                    yield "raised_hand_headroom", f, ref + [("part", lab)], {"margin": margin}, None


def rule_edge_sliver(scene: Scene):
    t = RULES["edge_sliver"][3]
    for f in scene.frames:
        aspect = scene.camera(f).aspect()
        for name, o in sorted(f["objects"].items()):
            meta = scene.objects[name]
            if meta["kind"] == "character" or meta["owner"] in scene.attached or not o["in_frame"]:
                continue
            hull = to_h(o["hull"], aspect)
            x0, y0, x1, y1 = bbox(hull)
            if (x0 < 0 and x1 > aspect) or (y0 < 0 and y1 > 1):
                continue                                   # spans the frame: background
            visible = clip_rect(hull, 0.0, 0.0, aspect, 1.0)
            total = area(hull)
            if not visible or total == 0:
                continue
            fraction = area(visible) / total
            vx0, vy0, vx1, vy1 = bbox(visible)
            for edge, crossed, depth_in in (("left", x0 < 0, vx1 / aspect),
                                            ("right", x1 > aspect, (aspect - vx0) / aspect),
                                            ("bottom", y0 < 0, vy1), ("top", y1 > 1, 1.0 - vy0)):
                if crossed and depth_in <= t["max_depth_into_frame"] and fraction <= t["max_visible_fraction"]:
                    yield "edge_sliver", f, [(meta["kind"], meta["owner"]), ("edge", edge)], \
                        {"depth_into_frame": depth_in, "visible_fraction": fraction}, None


def rule_tangent(scene: Scene):
    t = RULES["tangent"][3]
    for f in scene.frames:
        aspect = scene.camera(f).aspect()
        others = []
        for name, o in sorted(f["objects"].items()):
            meta = scene.objects[name]
            if meta["kind"] == "character" or meta["owner"] in scene.attached:
                continue
            for lab, isl in sorted(o["islands"].items()):
                others.append(((meta["kind"], meta["owner"]), lab, to_h(isl["hull"], aspect), isl["depth"]))
        chars = scene.characters()
        parts = {c: scene.character_parts(f, c) for c in chars}
        for c in chars:
            for lab, (hull, depth) in sorted(parts[c].items()):
                if len(hull) < 3 or scene.in_frame_fraction(f, [hull]) == 0.0:
                    continue
                cands = list(others)
                for c2 in chars:
                    if c2 > c:                             # each character pair once
                        cands += [(("character", c2), l2, h2, d2) for l2, (h2, d2) in sorted(parts[c2].items())]
                hx0, hy0, hx1, hy1 = bbox(hull)
                for ref, lab2, hull2, depth2 in cands:
                    if len(hull2) < 3:
                        continue
                    bx0, by0, bx1, by1 = bbox(hull2)
                    g = t["max_gap"]
                    if bx0 > hx1 + g or hx0 > bx1 + g or by0 > hy1 + g or hy0 > by1 + g:
                        continue
                    sep = max(depth2[0] - depth[1], depth[0] - depth2[1])
                    if sep < t["min_depth_separation_m"]:
                        continue                           # touching in depth, not a pictorial tangent
                    kind, measure, points = contact(hull, hull2, t["max_gap"])
                    if kind == "gap" and measure > t["max_gap"]:
                        continue
                    if kind == "overlap" and measure > t["max_overlap_fraction"]:
                        continue
                    points = [q for q in points if 0.0 <= q[0] <= aspect and 0.0 <= q[1] <= 1.0]
                    if not points:
                        continue                           # the contact is outside the frame
                    second = (ref[1], lab2) if ref[0] == "character" else None
                    far = max(depth[0], depth2[0])
                    if all(_hidden(q, parts, (c, lab), second, far) for q in points):
                        continue                           # wholly inside a nearer silhouette
                    severity = "error" if _part_kind(lab) == "head" or (
                        ref[0] == "character" and _part_kind(lab2) == "head") else "warning"
                    objs = [("character", c), ("part", lab), ref, ("part", lab2)]
                    measured = {"gap": measure} if kind == "gap" else {"overlap_fraction": measure}
                    measured["depth_separation_m"] = sep
                    measured["_offset"] = (_centroid(hull)[0] - _centroid(hull2)[0],
                                           _centroid(hull)[1] - _centroid(hull2)[1])
                    yield "tangent", f, objs, measured, severity


def _centroid(poly):
    return sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly)


def _hidden(point, parts, first, second, far_depth) -> bool:
    """Whether a contact point lies inside another part, of either character involved, that is
    nearer the camera than the farther of the two touching outlines."""
    owners = {first[0]} | ({second[0]} if second else set())
    for owner in owners:
        for lab, (hull, depth) in parts[owner].items():
            if (owner, lab) in (first, second):
                continue
            if depth[0] < far_depth and point_in_convex(point, hull):
                return True
    return False


def rule_raised_hand_contact(scene: Scene):
    t = RULES["raised_hand_contact"][3]
    for f in scene.frames:
        aspect = scene.camera(f).aspect()
        others = []
        for name, o in sorted(f["objects"].items()):
            meta = scene.objects[name]
            if meta["kind"] == "character" or meta["owner"] in scene.attached:
                continue
            for lab, isl in sorted(o["islands"].items()):
                others.append(((meta["kind"], meta["owner"]), lab, to_h(isl["hull"], aspect), isl["depth"]))
        for c in scene.characters():
            head_base = scene.bone(f, c, "head")
            if head_base is None or head_base[2] <= 0:
                continue
            parts = scene.character_parts(f, c)
            cands = list(others)
            for c2 in scene.characters():
                if c2 != c:
                    cands += [(("character", c2), l2, h2, d2) for l2, (h2, d2) in sorted(scene.character_parts(f, c2).items())]
            for lab, (hull, depth) in sorted(parts.items()):
                if _part_kind(lab) != "hand" or len(hull) < 3 or bbox(hull)[3] <= head_base[1]:
                    continue
                for ref, lab2, hull2, depth2 in cands:
                    if len(hull2) < 3:
                        continue
                    sep = max(depth2[0] - depth[1], depth[0] - depth2[1])
                    if sep < t["min_depth_separation_m"]:
                        continue
                    kind, measure, points = contact(hull, hull2, t["max_gap"])
                    if kind == "gap" and measure > t["max_gap"]:
                        continue
                    if not any(0.0 <= q[0] <= aspect and 0.0 <= q[1] <= 1.0 for q in points):
                        continue
                    measured = {"gap": measure} if kind == "gap" else {"overlap_fraction": measure}
                    measured["depth_separation_m"] = sep
                    yield "raised_hand_contact", f, [("character", c), ("part", lab), ref, ("part", lab2)], \
                        measured, None


def _cuts(scene: Scene):
    fr = scene.frames
    return [(fr[i - 1], fr[i]) for i in range(1, len(fr)) if fr[i]["shot_id"] != fr[i - 1]["shot_id"]]


def _in_frame(scene, frame, owner):
    parts = scene.character_parts(frame, owner)
    return bool(parts) and scene.in_frame_fraction(frame, [h for h, _ in parts.values()]) > 0.0


def rule_camera_side(scene: Scene):
    t = RULES["camera_side"][3]
    chars = scene.characters()
    for before, after in _cuts(scene):
        for i, a in enumerate(chars):
            for b in chars[i + 1:]:
                if not (_in_frame(scene, before, a) or _in_frame(scene, before, b)):
                    continue
                if not (_in_frame(scene, after, a) or _in_frame(scene, after, b)):
                    continue
                sides = []
                for f in (before, after):
                    pa, pb = scene.world_bone(f, a, "hips"), scene.world_bone(f, b, "hips")
                    if pa is None or pb is None:
                        break
                    cam = scene.camera(f).location
                    ax, ay = pb[0] - pa[0], pb[1] - pa[1]
                    cx, cy = cam[0] - pa[0], cam[1] - pa[1]
                    norm = math.hypot(ax, ay) * math.hypot(cx, cy)
                    sides.append((ax * cy - ay * cx) / norm if norm else 0.0)
                if len(sides) < 2 or min(abs(s) for s in sides) < t["min_abs_sin"]:
                    continue
                if (sides[0] > 0) != (sides[1] > 0):
                    yield "camera_side", after, [("character", a), ("character", b)], \
                        {"sin_before": sides[0], "sin_after": sides[1],
                         "cut_frames": [before["frame"], after["frame"]]}, None


def _screen_x(scene, frame, owner):
    p = scene.bone(frame, owner, "hips")
    return p[0] * scene.camera(frame).aspect() if p and p[2] > 0 else None


def rule_screen_direction(scene: Scene):
    t = RULES["screen_direction"][3]
    idx = {f["frame"]: i for i, f in enumerate(scene.frames)}
    for before, after in _cuts(scene):
        i, j = idx[before["frame"]], idx[after["frame"]]
        if i == 0 or j + 1 >= len(scene.frames):
            continue
        prev, nxt = scene.frames[i - 1], scene.frames[j + 1]
        if prev["shot_id"] != before["shot_id"] or nxt["shot_id"] != after["shot_id"]:
            continue
        for owner in scene.characters():
            if not (_in_frame(scene, before, owner) and _in_frame(scene, after, owner)):
                continue
            xs = [_screen_x(scene, f, owner) for f in (prev, before, after, nxt)]
            if None in xs:
                continue
            v1 = (xs[1] - xs[0]) / (before["frame"] - prev["frame"])
            v2 = (xs[3] - xs[2]) / (nxt["frame"] - after["frame"])
            if abs(v1) >= t["min_speed"] and abs(v2) >= t["min_speed"] and (v1 > 0) != (v2 > 0):
                yield "screen_direction", after, [("character", owner)], \
                    {"speed_before": v1, "speed_after": v2, "cut_frames": [before["frame"], after["frame"]]}, None


def _gaze(scene, frame, owner):
    """(target, screen sign) of a character's gaze in this frame, or None if ambiguous."""
    t = RULES["eyeline"][3]
    g = scene.facing(frame, owner)
    me = scene.world_bone(frame, owner, "hips")
    if g is None or me is None:
        return None
    best = None
    for other in scene.characters():
        if other == owner:
            continue
        p = scene.world_bone(frame, other, "hips")
        if p is None:
            continue
        dx, dy = p[0] - me[0], p[1] - me[1]
        n = math.hypot(dx, dy)
        if n == 0:
            continue
        ang = math.degrees(math.acos(max(-1.0, min(1.0, (g[0] * dx + g[1] * dy) / n))))
        if ang <= t["max_gaze_angle_deg"] and (best is None or ang < best[1]):
            best = (other, ang)
    if best is None:
        return None
    r = scene.camera(frame).rotation                   # camera right = first column of rotation
    gx = g[0] * r[0][0] + g[1] * r[1][0]
    if abs(gx) < t["min_screen_component"]:
        return None
    return best[0], (1 if gx > 0 else -1)


def rule_eyeline(scene: Scene):
    chars = scene.characters()
    for before, after in _cuts(scene):
        vis_b = {c: _in_frame(scene, before, c) for c in chars}
        vis_a = {c: _in_frame(scene, after, c) for c in chars}
        gb = {c: _gaze(scene, before, c) for c in chars if vis_b[c]}
        ga = {c: _gaze(scene, after, c) for c in chars if vis_a[c]}
        cut = [before["frame"], after["frame"]]
        for c in chars:
            if gb.get(c) and ga.get(c) and gb[c][0] == ga[c][0] and gb[c][1] != ga[c][1]:
                yield "eyeline", after, [("character", c), ("character", gb[c][0])], \
                    {"screen_side_before": gb[c][1], "screen_side_after": ga[c][1], "cut_frames": cut}, None
        for x in chars:
            for y in chars:
                if x == y or not (gb.get(x) and ga.get(y)) or vis_a.get(x) or vis_b.get(y):
                    continue
                if gb[x][0] == y and ga[y][0] == x and gb[x][1] == ga[y][1]:
                    yield "eyeline", after, [("character", x), ("character", y)], \
                        {"screen_side_before": gb[x][1], "screen_side_after": ga[y][1], "cut_frames": cut}, None


def sun(spec: dict):
    """(elevation deg, horizontal 'from' unit vector, preset) of the SceneSpec sun."""
    lighting = spec.get("lighting") or {}
    preset = lighting.get("preset", "golden_hour")
    elev, az = SUN_PRESETS[preset]
    if lighting.get("sun_elevation_deg") is not None:
        elev = lighting["sun_elevation_deg"]
    if lighting.get("sun_azimuth_deg") is not None:
        az = lighting["sun_azimuth_deg"]
    a = math.radians(az)
    return elev, (math.sin(a), -math.cos(a)), preset


def rule_backlight(scene: Scene):
    t = RULES["backlight"][3]
    elev, frm, preset = sun(scene.spec)
    if preset in DIFFUSE_PRESETS or elev > t["max_sun_elevation_deg"]:
        return
    for f in scene.frames:
        cam = scene.camera(f).location
        for owner in scene.characters():
            parts = scene.character_parts(f, owner)
            if not parts or scene.in_frame_fraction(f, [h for h, _ in parts.values()]) == 0.0:
                continue
            ys = [y for h, _ in parts.values() for _, y in h]
            height = min(max(ys), 1.0) - max(min(ys), 0.0)
            if height < t["min_height_in_frame"]:
                continue
            p = scene.world_bone(f, owner, "hips")
            if p is None:
                continue
            dx, dy = cam[0] - p[0], cam[1] - p[1]
            n = math.hypot(dx, dy)
            seen = (frm[0] * dx + frm[1] * dy) / n if n else 0.0
            if seen <= t["max_seen_side"]:
                yield "backlight", f, [("character", owner)], {"seen_side": seen, "sun_elevation_deg": elev}, None


ALL_RULES = (rule_cropping, rule_edge_sliver, rule_tangent, rule_raised_hand_contact, rule_camera_side,
             rule_screen_direction, rule_eyeline, rule_backlight)


# ---------------------------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------------------------
WORST = {"in_frame_fraction": max, "head_in_frame_fraction": min, "body_in_frame_fraction": max,
         "top_margin": min, "hand_in_frame_fraction": min, "margin": min, "depth_into_frame": min,
         "visible_fraction": min, "signed_distance": lambda vs: min(vs, key=abs),
         "depth_separation_m": min, "seen_side": min, "gap": min, "overlap_fraction": max}


def _merge(hits, frame_numbers):
    """Group per-frame hits by (rule, shot, objects, severity) into runs of consecutive
    sampled frames."""
    pos = {f: i for i, f in enumerate(frame_numbers)}
    groups: dict[tuple, list] = {}
    for rule, frame, objs, measured, severity in hits:
        key = (rule, frame["shot_id"], tuple(objs), severity or RULES[rule][1])
        groups.setdefault(key, []).append((frame["frame"], measured))
    runs = []
    for key, items in groups.items():
        items.sort(key=lambda x: x[0])
        run = [items[0]]
        for item in items[1:]:
            if pos[item[0]] == pos[run[-1][0]] + 1:
                run.append(item)
            else:
                runs.append((key, run))
                run = [item]
        runs.append((key, run))
    return runs


MIN_FRAMES = {"tangent": RULES["tangent"][3]["min_frames"],
              "raised_hand_contact": RULES["raised_hand_contact"][3]["min_frames"]}


def _explain(rule, objs, measured):
    names = ", ".join(f"{k} {v}" for k, v in objs)
    return f"{RULES[rule][2]} Involves {names}."


def build_report(geo: dict, spec: dict, inputs: dict, accepted: list | None = None) -> dict:
    scene = Scene(geo, spec)
    hits = [h for rule in ALL_RULES for h in rule(scene)]
    frame_numbers = [f["frame"] for f in scene.frames]
    findings = []
    for (rule, shot, objs, severity), run in _merge(hits, frame_numbers):
        if len(run) < MIN_FRAMES.get(rule, 1):
            continue
        version, _, _, thresholds, limitations = RULES[rule]
        offsets = [m.pop("_offset") for _, m in run if "_offset" in m]
        extra = {}
        if offsets:
            frames = [fr for fr, _ in run]
            speeds = sorted(math.hypot(b[0] - a[0], b[1] - a[1]) / (f2 - f1)
                            for a, b, f1, f2 in zip(offsets, offsets[1:], frames, frames[1:]))
            speed = speeds[len(speeds) // 2] if speeds else 0.0
            extra["relative_speed"] = speed
            if speed > thresholds["max_relative_speed"]:
                severity = "info"
        keys = sorted({k for _, m in run for k in m})
        measured = {}
        for k in keys:
            vals = [m[k] for _, m in run if k in m]
            if k in WORST:
                measured[k] = WORST[k](vals)
            elif k == "cut_frames":
                measured[k] = vals[0]
            else:
                measured[k] = vals[0]
        worst = run[0][0]
        if keys and keys[0] in WORST:
            target = measured[keys[0]]
            worst = next(fr for fr, m in run if m.get(keys[0]) == target)
        measured.update(extra)
        objects = [{"kind": k, "id": v} for k, v in objs]
        start, end = run[0][0], run[-1][0]
        fid = f"{rule}:{shot}:{'/'.join(f'{k}={v}' for k, v in objs)}:{start}"
        finding = {"id": fid, "rule": rule, "rule_version": version, "severity": severity,
                   "shot_id": shot, "frames": [start, end], "frame_count": len(run),
                   "objects": objects, "measured": measured, "threshold": thresholds,
                   "explanation": _explain(rule, objs, measured),
                   "evidence": {"geometry_frames": [start, end], "worst_frame": worst},
                   "accepted": None}
        for acc in accepted or []:
            if (acc["rule"] == rule and acc.get("shot_id") == shot
                    and all(o in objects for o in acc.get("objects", []))
                    and acc["frames"][0] <= start and end <= acc["frames"][1]):
                finding["accepted"] = {"kind": acc.get("kind", "accepted_issue"), "reason": acc["reason"]}
        findings.append(_fmt(finding))
    order = {"error": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda f: (order[f["severity"]], f["frames"][0], f["rule"], f["id"]))
    fr = geo["frame_range"]
    summary = {s: sum(1 for f in findings if f["severity"] == s and not f["accepted"]) for s in order}
    summary["accepted"] = sum(1 for f in findings if f["accepted"])
    return {
        "schema": SCHEMA, "verdict": "evidence_only", "human_approval_required": True,
        "inputs": inputs,
        "scene": {"project_id": spec.get("project_id"), "scene_id": spec.get("scene_id"),
                  "shot_id": spec.get("shot_id"), "frame_range": fr,
                  "frames_evaluated": len(frame_numbers),
                  "complete": frame_numbers == list(range(fr[0], fr[1] + 1)),
                  "first_frame": frame_numbers[0] if frame_numbers else None,
                  "last_frame": frame_numbers[-1] if frame_numbers else None},
        "rules": [{"id": rid, "version": v, "severity": sev, "description": d,
                   "thresholds": _fmt(th), "limitations": lim}
                  for rid, (v, sev, d, th, lim) in sorted(RULES.items())],
        "summary": summary,
        "findings": findings,
        "limitations": [
            "Findings are heuristics over convex part outlines, depths and bone points; they "
            "are evidence for a human and never approve or block a shot.",
            "Outline overlap is not proof of visibility: occlusion between objects is "
            "approximated with per-outline depth ranges only.",
            "Rules that compare frames across a cut need the frames on both sides of it; with "
            "sampled geometry (complete = false) cuts between samples are approximated.",
            "Lighting is judged from the SceneSpec sun only and cannot know intent.",
        ],
    }


def _digest(path: Path) -> dict:
    return {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="shot_qa")
    p.add_argument("--shot-dir", type=Path)
    p.add_argument("--geometry", type=Path)
    p.add_argument("--spec", type=Path)
    p.add_argument("--out", type=Path)
    p.add_argument("--accepted", type=Path,
                   help="accepted-finding annotations: a JSON list of {rule, shot_id, objects, "
                        "frames, kind ('false_positive' | 'accepted_issue'), reason}")
    a = p.parse_args(argv)
    if a.shot_dir:
        a.geometry = a.geometry or a.shot_dir / "review" / "shot_geometry.json"
        a.spec = a.spec or a.shot_dir / "spec.json"
        a.out = a.out or a.shot_dir / "review" / "composition_report.json"
    if not (a.geometry and a.spec and a.out):
        p.error("give --shot-dir, or all of --geometry, --spec and --out")
    try:
        geo = json.loads(a.geometry.read_text())
        spec = json.loads(a.spec.read_text())
        accepted = json.loads(a.accepted.read_text()) if a.accepted else None
        inputs = {"geometry": _digest(a.geometry), "spec": _digest(a.spec),
                  "accepted": _digest(a.accepted) if a.accepted else None}
        report = build_report(geo, spec, inputs, accepted)
    except (OSError, ValueError, KeyError) as e:
        print(f"FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    print(json.dumps({"status": "evidence_written", "report": str(a.out), **report["summary"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
