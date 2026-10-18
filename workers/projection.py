"""Camera projection and 2D outline geometry for Shot QA (Milestone 8).

Shared by blender/scripts/inspect_shot_geometry.py (which imports it inside Blender) and the
Shot QA worker. Pure Python, standard library only, so Blender's bundled Python can import it;
it never imports bpy.

Coordinates follow bpy_extras.object_utils.world_to_camera_view: a projected point is
(x, y, depth) with (0, 0) the bottom-left and (1, 1) the top-right corner of the rendered frame,
and depth the distance in front of the camera along its view axis (metres; negative = behind).

The camera model reproduces Blender's perspective view plane (BKE_camera_params_compute_viewplane):
  * sensor size: sensor_height for sensor_fit VERTICAL, otherwise sensor_width;
  * fit: AUTO fits the larger of the frame's width and height (pixel aspect included);
  * the view plane spans sensor_size / lens per metre of depth along the fitted dimension, and
    lens shift moves it by shift * (that span), so shift is in units of the fitted dimension.
Only perspective cameras are supported (build_scene.py builds no others).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

NEAR_EPS = 1e-6          # points closer than this to the camera plane count as behind it


def _r(v: float) -> float:
    return round(float(v), 6) + 0.0                     # + 0.0 turns -0.0 into 0.0


@dataclass(frozen=True)
class Camera:
    """An evaluated perspective camera. `rotation` holds the camera's world axes as columns
    (local X right, local Y up, local -Z the view direction); scale must be removed."""
    location: tuple[float, float, float]
    rotation: tuple[tuple[float, float, float], ...]   # 3x3, rows of the world matrix
    lens: float
    sensor_width: float
    sensor_height: float
    sensor_fit: str                                    # "AUTO" | "HORIZONTAL" | "VERTICAL"
    shift: tuple[float, float]
    resolution: tuple[int, int]
    pixel_aspect: tuple[float, float] = (1.0, 1.0)
    clip_start: float = 0.1
    clip_end: float = 1000.0

    @classmethod
    def from_dict(cls, d: dict) -> "Camera":
        return cls(location=tuple(d["location"]), rotation=tuple(tuple(r) for r in d["rotation"]),
                   lens=d["lens"], sensor_width=d["sensor_width"],
                   sensor_height=d["sensor_height"], sensor_fit=d["sensor_fit"],
                   shift=tuple(d["shift"]), resolution=tuple(d["resolution"]),
                   pixel_aspect=tuple(d.get("pixel_aspect", (1.0, 1.0))),
                   clip_start=d.get("clip_start", 0.1), clip_end=d.get("clip_end", 1000.0))

    def to_dict(self) -> dict:
        return {"location": [_r(v) for v in self.location],
                "rotation": [[_r(v) for v in row] for row in self.rotation],
                "lens": _r(self.lens), "sensor_width": _r(self.sensor_width),
                "sensor_height": _r(self.sensor_height), "sensor_fit": self.sensor_fit,
                "shift": [_r(v) for v in self.shift], "resolution": list(self.resolution),
                "pixel_aspect": [_r(v) for v in self.pixel_aspect],
                "clip_start": _r(self.clip_start), "clip_end": _r(self.clip_end)}

    # -- view plane ------------------------------------------------------------------------
    def fit(self) -> str:
        """The dimension the sensor spans: "HORIZONTAL" or "VERTICAL"."""
        if self.sensor_fit in ("HORIZONTAL", "VERTICAL"):
            return self.sensor_fit
        w = self.resolution[0] * self.pixel_aspect[0]
        h = self.resolution[1] * self.pixel_aspect[1]
        return "HORIZONTAL" if w >= h else "VERTICAL"

    def sensor_size(self) -> float:
        return self.sensor_height if self.sensor_fit == "VERTICAL" else self.sensor_width

    def aspect(self) -> float:
        """Frame width over height in display units (pixel aspect included)."""
        return (self.resolution[0] * self.pixel_aspect[0]) / (self.resolution[1] * self.pixel_aspect[1])


def to_camera(cam: Camera, p) -> tuple[float, float, float]:
    """(x right, y up, depth in front) of world point p in the camera's frame."""
    d = [p[i] - cam.location[i] for i in range(3)]
    r = cam.rotation
    x = r[0][0] * d[0] + r[1][0] * d[1] + r[2][0] * d[2]
    y = r[0][1] * d[0] + r[1][1] * d[1] + r[2][1] * d[2]
    z = r[0][2] * d[0] + r[1][2] * d[1] + r[2][2] * d[2]
    return x, y, -z


def project_camera_point(cam: Camera, c) -> tuple[float, float, float]:
    """Frame position (x, y, depth) of a camera-space point (x, y, depth)."""
    x, y, depth = c
    if depth == 0.0:
        return 0.5, 0.5, 0.0                           # as world_to_camera_view does
    s = cam.sensor_size() / cam.lens                   # fitted span per metre of depth
    u, v = x / (depth * s), y / (depth * s)            # in units of the fitted dimension
    a = cam.aspect()
    if cam.fit() == "HORIZONTAL":
        return 0.5 + u - cam.shift[0], 0.5 + (v - cam.shift[1]) * a, depth
    return 0.5 + (u - cam.shift[0]) / a, 0.5 + v - cam.shift[1], depth


def project(cam: Camera, p) -> tuple[float, float, float]:
    """Frame position (x, y, depth) of world point p, like world_to_camera_view."""
    return project_camera_point(cam, to_camera(cam, p))


# ---------------------------------------------------------------------------------------------
# Outlines
# ---------------------------------------------------------------------------------------------
def convex_hull(points) -> list[tuple[float, float]]:
    """Convex hull (Andrew's monotone chain), counter-clockwise from the lowest-x (then
    lowest-y) point, without collinear points. Deterministic for a given point set."""
    pts = sorted(set((float(x), float(y)) for x, y in points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def clip_near(poly, near: float) -> list[tuple[float, float, float]]:
    """Clip a camera-space polygon to depth >= near (Sutherland-Hodgman, one plane)."""
    out = []
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        a_in, b_in = a[2] >= near, b[2] >= near
        if a_in:
            out.append(a)
        if a_in != b_in:
            t = (near - a[2]) / (b[2] - a[2])
            out.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]), near))
    return out


def outline(cam: Camera, vertices, triangles=()) -> dict | None:
    """2D outline of world-space geometry: the convex hull of its projection, with the depth
    range of the part in front of the camera. Geometry that crosses the camera's near plane
    (clip_start) is clipped triangle by triangle, so `triangles` (vertex index triples) is
    required for it; geometry wholly in front needs only its vertices. None if nothing is in
    front of the near plane."""
    near = max(cam.clip_start, NEAR_EPS)
    cs = [to_camera(cam, v) for v in vertices]
    if not cs:
        return None
    if min(c[2] for c in cs) >= near:
        kept = cs
    else:
        kept = []
        for tri in triangles:
            kept.extend(clip_near([cs[i] for i in tri], near))
        if not kept:
            return None
    proj = [project_camera_point(cam, c) for c in kept]
    hull = convex_hull([(p[0], p[1]) for p in proj])
    return {"hull": [[_r(x), _r(y)] for x, y in hull],
            "depth": [_r(min(p[2] for p in proj)), _r(max(p[2] for p in proj))]}


def polygon_overlaps_frame(hull) -> bool:
    """Whether a convex polygon in frame coordinates overlaps the frame [0, 1] x [0, 1]
    (separating-axis test, touching counts as overlap)."""
    if not hull:
        return False
    xs, ys = [p[0] for p in hull], [p[1] for p in hull]
    if max(xs) < 0 or min(xs) > 1 or max(ys) < 0 or min(ys) > 1:
        return False
    if len(hull) < 3:
        return True
    corners = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    n = len(hull)
    for i in range(n):
        ax, ay = hull[i]
        bx, by = hull[(i + 1) % n]
        nx, ny = by - ay, ax - bx                      # outward normal of a CCW edge
        if all(nx * (cx - ax) + ny * (cy - ay) > 0 for cx, cy in corners):
            return False
    return True


def islands(vertex_count: int, polygons) -> list[list[int]]:
    """Connected vertex sets of a mesh (polygons as vertex index lists), each sorted, ordered
    by their lowest vertex index."""
    parent = list(range(vertex_count))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for poly in polygons:
        root = find(poly[0])
        for v in poly[1:]:
            rv = find(v)
            if rv != root:
                parent[rv] = root
    groups: dict[int, list[int]] = {}
    for v in range(vertex_count):
        groups.setdefault(find(v), []).append(v)
    return sorted(groups.values(), key=lambda g: g[0])


def rounded_point(p) -> list[float]:
    return [_r(v) for v in p]
