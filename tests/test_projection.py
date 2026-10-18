"""Milestone 8 Gate 1: workers/projection.py, the shared camera projection and outline module
(no Blender). Agreement with Blender's own world_to_camera_view on built scenes is in
tests/test_shot_geometry_inspector.py; these tests pin the camera model, the outline geometry
and the module's agreement with the projection formulas already used in the tests.
"""
import math

import pytest

from workers import projection as P

S36_50 = 36.0 / 50.0                     # fitted span per metre of depth for 50 mm on 36 mm


def cam(**kw) -> P.Camera:
    """A camera at the origin looking down -Z (Blender's camera rest orientation), 50 mm on a
    36 x 24 mm sensor, 640 x 360, unless overridden."""
    base = dict(location=(0.0, 0.0, 0.0), rotation=((1, 0, 0), (0, 1, 0), (0, 0, 1)), lens=50.0,
                sensor_width=36.0, sensor_height=24.0, sensor_fit="AUTO", shift=(0.0, 0.0),
                resolution=(640, 360))
    base.update(kw)
    return P.Camera(**base)


def look_at(eye, target) -> tuple:
    """Rotation rows of a camera at eye whose -Z points at target with +Y up (Track To with
    TRACK_NEGATIVE_Z / UP_Y, as build_scene.py sets it)."""
    f = [target[i] - eye[i] for i in range(3)]
    n = math.sqrt(sum(c * c for c in f))
    f = [c / n for c in f]
    right = [f[1], -f[0], 0.0]                          # f x world up
    n = math.hypot(right[0], right[1])
    right = [c / n for c in right]
    up = [right[1] * f[2] - right[2] * f[1], right[2] * f[0] - right[0] * f[2],
          right[0] * f[1] - right[1] * f[0]]
    back = [-c for c in f]
    return tuple((right[i], up[i], back[i]) for i in range(3))


# ---------------------------------------------------------------------------
# Camera model
# ---------------------------------------------------------------------------
def test_a_point_on_the_view_axis_projects_to_the_frame_centre():
    assert P.project(cam(), (0.0, 0.0, -5.0)) == pytest.approx((0.5, 0.5, 5.0))


def test_landscape_auto_fit_spans_the_sensor_width_across_the_frame_width():
    c = cam()
    edge = 5.0 * S36_50 / 2                             # half the fitted span at 5 m
    assert P.project(c, (edge, 0.0, -5.0))[0] == pytest.approx(1.0)
    assert P.project(c, (-edge, 0.0, -5.0))[0] == pytest.approx(0.0)
    vedge = edge * 360 / 640                            # height = width / aspect
    assert P.project(c, (0.0, vedge, -5.0))[1] == pytest.approx(1.0)
    assert c.fit() == "HORIZONTAL"


def test_portrait_auto_fit_spans_the_sensor_width_across_the_frame_height():
    c = cam(resolution=(360, 640))
    edge = 5.0 * S36_50 / 2
    assert c.fit() == "VERTICAL"
    assert P.project(c, (0.0, edge, -5.0))[1] == pytest.approx(1.0)
    assert P.project(c, (edge * 360 / 640, 0.0, -5.0))[0] == pytest.approx(1.0)


def test_explicit_vertical_fit_uses_the_sensor_height():
    c = cam(sensor_fit="VERTICAL")
    edge = 5.0 * (24.0 / 50.0) / 2
    assert P.project(c, (0.0, edge, -5.0))[1] == pytest.approx(1.0)
    assert P.project(c, (edge * 640 / 360, 0.0, -5.0))[0] == pytest.approx(1.0)


def test_pixel_aspect_enters_the_frame_aspect_and_the_auto_fit():
    c = cam(resolution=(400, 400), pixel_aspect=(2.0, 1.0))      # displays 800 x 400
    assert c.aspect() == pytest.approx(2.0) and c.fit() == "HORIZONTAL"


@pytest.mark.parametrize("res, shift", [((640, 360), (0.1, -0.05)), ((360, 360), (0.2, 0.2)),
                                        ((360, 640), (0.1, 0.1))])
def test_lens_shift_moves_the_frame_in_units_of_the_fitted_dimension(res, shift):
    c = cam(resolution=res, shift=shift)
    x, y, _ = P.project(c, (0.0, 0.0, -5.0))
    a = c.aspect()
    if c.fit() == "HORIZONTAL":
        assert (x, y) == pytest.approx((0.5 - shift[0], 0.5 - shift[1] * a))
    else:
        assert (x, y) == pytest.approx((0.5 - shift[0] / a, 0.5 - shift[1]))


def test_points_behind_the_camera_have_negative_depth_and_the_camera_plane_maps_to_the_centre():
    assert P.project(cam(), (0.0, 0.0, 3.0))[2] == pytest.approx(-3.0)
    assert P.project(cam(), (1.0, 1.0, 0.0)) == (0.5, 0.5, 0.0)


def test_camera_round_trips_through_its_dict_with_rounding_and_no_negative_zero():
    c = cam(location=(-0.0, 1.23456789, 2.0), shift=(-0.0, 0.1))
    d = c.to_dict()
    assert d["location"] == [0.0, 1.234568, 2.0] and math.copysign(1.0, d["shift"][0]) > 0
    assert P.Camera.from_dict(d).to_dict() == d


# ---------------------------------------------------------------------------
# Agreement with the projections the existing tests use
# ---------------------------------------------------------------------------
def inspect_camera_frame(c: P.Camera) -> dict:
    """The fields tests/test_character_builder.py and tests/test_m7_greeting_builder.py read
    from blender/scripts/inspect_camera.py."""
    r = c.rotation
    return {"location": list(c.location), "view_dir": [-r[0][2], -r[1][2], -r[2][2]],
            "up_dir": [r[0][1], r[1][1], r[2][1]], "lens": c.lens, "shift": list(c.shift)}


POINTS = [(1.0, 2.0, 1.5), (-0.5, 3.0, 0.2), (2.5, 6.0, 2.4), (0.0, 1.0, 1.0)]


def test_matches_the_m6_character_builder_projection():
    from tests.test_character_builder import project as m6_project
    c = cam(location=(0.4, -5.5, 1.4), rotation=look_at((0.4, -5.5, 1.4), (0.8, 0.0, 0.9)),
            shift=(0.08, -0.02))
    for p in POINTS:
        x, y, _ = P.project(c, p)
        assert (x, y) == pytest.approx(m6_project(inspect_camera_frame(c), list(p)), abs=1e-12)


def test_matches_the_m7_builder_projection_measured_from_the_centre():
    import tests.test_m7_greeting_builder as B
    c = cam(location=(-1.6, -1.9, 1.6), rotation=look_at((-1.6, -1.9, 1.6), (2.0, 0.0, 1.3)),
            lens=40.0, shift=(-0.15, 0.0))
    cams = {1: inspect_camera_frame(c)}
    for p in POINTS:
        x, y, _ = P.project(c, p)
        assert (x - 0.5, y - 0.5) == pytest.approx(B.project(cams, 1, list(p)), abs=1e-12)


def test_matches_the_m7_spec_pinhole_for_a_tracking_shot():
    """The spec-level pinhole in tests/test_m7_greeting_spec.py builds the camera from look_at
    and subject_offset; the module given the same camera agrees with it."""
    import tests.test_m7_greeting_spec as T
    s = next(x for x in T.SPEC.shots if x.shot_id == "sh05_host_wave")
    f = 361
    loc = T.cam_at(s.camera, f)
    root = T.root_at(s.camera.look_at, f)
    aim = [root[0], root[1], root[2] + s.camera.look_at_height]
    off = s.camera.framing.subject_offset
    w, h = T.SPEC.render.resolution
    c = cam(location=tuple(loc), rotation=look_at(loc, aim), lens=s.camera.lens_mm,
            shift=(-off[0], -off[1] * h / w), resolution=(w, h))
    for p in POINTS:
        x, y, _ = P.project(c, p)
        assert (x - 0.5, y - 0.5) == pytest.approx(T.project(s.camera, f, list(p)), abs=1e-9)


# ---------------------------------------------------------------------------
# Outlines
# ---------------------------------------------------------------------------
def test_convex_hull_is_ccw_from_the_lowest_x_without_interior_duplicate_or_collinear_points():
    pts = [(0, 0), (1, 0), (2, 0), (2, 2), (0, 2), (1, 1), (0, 0), (0, 1)]
    assert P.convex_hull(pts) == [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]
    assert P.convex_hull([(1, 1), (1, 1)]) == [(1.0, 1.0)]
    assert P.convex_hull(list(reversed(pts))) == P.convex_hull(pts), "order-independent"


def test_clip_near_cuts_a_triangle_at_the_plane():
    tri = [(0.0, 0.0, 2.0), (1.0, 0.0, -2.0), (0.0, 1.0, -2.0)]
    out = P.clip_near(tri, 1.0)
    assert out == [(0.0, 0.0, 2.0), (0.25, 0.0, 1.0), (0.0, 0.25, 1.0)]
    assert P.clip_near([(0, 0, -1), (1, 0, -1), (0, 1, -1)], 0.1) == []


def test_outline_of_geometry_in_front_uses_its_vertices():
    c = cam()
    square = [(-1, -1, -5), (1, -1, -5), (1, 1, -5), (-1, 1, -5), (0, 0, -6)]
    out = P.outline(c, square)
    assert out["depth"] == [5.0, 6.0] and len(out["hull"]) == 4
    assert out["hull"][0] == [round(P.project(c, (-1, -1, -5))[0], 6), round(P.project(c, (-1, -1, -5))[1], 6)]


def test_outline_of_geometry_crossing_the_near_plane_is_clipped_not_flipped():
    c = cam(clip_start=0.1)
    ground = [(-50, -1, 50), (50, -1, 50), (50, -1, -50), (-50, -1, -50)]   # under and around
    tris = [(0, 1, 2), (0, 2, 3)]
    out = P.outline(c, ground, tris)
    assert out["depth"][0] == pytest.approx(0.1) and out["depth"][1] == pytest.approx(50.0)
    assert max(y for _, y in out["hull"]) < 0.5, "the ground stays below the horizon"
    assert P.outline(c, [(0, 0, 1), (1, 0, 1), (0, 1, 1)], [(0, 1, 2)]) is None, "all behind"


def test_frame_overlap_uses_separating_axes():
    assert P.polygon_overlaps_frame([[0.2, 0.2], [0.4, 0.2], [0.3, 0.4]])
    assert P.polygon_overlaps_frame([[-0.5, -0.5], [1.5, -0.5], [1.5, 1.5], [-0.5, 1.5]]), "covers it"
    assert P.polygon_overlaps_frame([[1.0, 0.2], [1.5, 0.2], [1.5, 0.4]]), "touching the edge"
    assert not P.polygon_overlaps_frame([[1.01, 0.2], [1.5, 0.2], [1.5, 0.4]])
    # bounding boxes overlap, but the triangle passes outside the top-right corner
    assert not P.polygon_overlaps_frame([[1.1, 0.95], [1.6, 1.6], [0.95, 1.1]])
    assert P.polygon_overlaps_frame([[1.05, 0.8], [1.6, 1.6], [0.8, 1.05]]), "corner (1, 1) inside"
    assert not P.polygon_overlaps_frame([])


def test_islands_are_connected_vertex_sets_in_a_stable_order():
    polys = [[3, 4, 5], [0, 1, 2], [2, 6]]
    assert P.islands(7, polys) == [[0, 1, 2, 6], [3, 4, 5]]
    assert P.islands(2, []) == [[0], [1]]
