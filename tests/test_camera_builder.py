"""What blender/scripts/build_scene.py actually builds for the camera. Run with: pytest -m blender

Each case validates a SceneSpec, builds it headless with run_shot(render=False) into tmp_path
(no frames rendered, no deliverables touched), then reads the evaluated camera back with the
fixed, read-only blender/scripts/inspect_camera.py. Projected positions come from Blender's own
world_to_camera_view, so framing claims are measured, not derived from sign conventions.
"""
import copy
import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from workers import config
from workers.blender_job import REPO, run_shot

pytestmark = [
    pytest.mark.blender,
    pytest.mark.skipif(shutil.which(config.BLENDER_BIN) is None, reason="Blender not found"),
]

M1 = json.loads((REPO / "schemas/examples/milestone1_primitives.json").read_text())
INSPECT = REPO / "blender" / "scripts" / "inspect_camera.py"
TOL = 1e-4


def build_and_inspect(spec: dict, tmp_path: Path, frames: list[int], project=()) -> tuple[dict, dict]:
    report = run_shot(spec, tmp_path / "project", render=False)
    assert report["status"] == "ok" and report["returncode"] == 0, report
    out = tmp_path / "camera.json"
    proc = subprocess.run(
        [config.BLENDER_BIN, "-b", report["blend"], "--factory-startup", "--python-exit-code", "1",
         "-P", str(INSPECT), "--", "--out", str(out), "--frames", ",".join(map(str, frames)),
         "--project", ",".join(project)],
        capture_output=True, text=True, errors="replace", timeout=300)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    return report, json.loads(out.read_text())


def m1(**camera_patch) -> dict:
    d = copy.deepcopy(M1)
    d["camera"].update(camera_patch)
    return d


def euler_xyz(deg) -> list[list[float]]:
    """Blender XYZ Euler as a rotation matrix: R = Rz @ Ry @ Rx."""
    x, y, z = (math.radians(a) for a in deg)
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    return [[cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx],
            [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx],
            [-sy, cy * sx, cy * cx]]


def apply(m, v):
    return [sum(m[r][c] * v[c] for c in range(3)) for r in range(3)]


def close(a, b, tol=TOL) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b, strict=True))


def by_frame(cam: dict) -> dict[int, dict]:
    return {f["frame"]: f for f in cam["frames"]}


# ---------------------------------------------------------------------------
def test_milestone_camera_baseline(tmp_path):
    """The committed Milestone 1 camera, exactly as built today."""
    report, cam = build_and_inspect(M1, tmp_path, [1, 24, 48, 72, 96],
                                    project=["AIM-pedestal", "PRIM-pedestal"])
    assert "frames_dir" not in report                      # --no-render: nothing rendered
    assert cam["scene_camera"] == "CAM-shot"
    assert cam["resolution"] == [640, 360, 100]            # quality "final"
    assert cam["camera"] == {
        "type": "PERSP", "sensor_width": 36.0, "sensor_fit": "AUTO", "rotation_mode": "XYZ",
        "parent": None, "dof_focus_object": None,
        "constraints": [{"type": "TRACK_TO", "target": "AIM-pedestal",
                         "track_axis": "TRACK_NEGATIVE_Z", "up_axis": "UP_Y"}]}
    frames = by_frame(cam)
    for k in M1["camera"]["keys"]:
        assert close(frames[k["frame"]]["location"], k["location"])
    for f in frames.values():
        assert f["lens"] == pytest.approx(35.0)
        assert (f["clip_start"], f["clip_end"]) == (pytest.approx(0.1), pytest.approx(1000.0))
        assert f["shift"] == [0.0, 0.0]
        assert f["dof"]["use"] is False
        x, y, depth = f["projected"]["AIM-pedestal"]
        assert (x, y) == (pytest.approx(0.5, abs=TOL), pytest.approx(0.5, abs=TOL)) and depth > 0
    # the aim point is look_at_height above the pedestal's origin (0, 0, 0.5)
    assert frames[1]["projected"]["PRIM-pedestal"][1] < 0.5          # origin sits below centre


def test_track_to_keeps_aim_centred_between_keys(tmp_path):
    _, cam = build_and_inspect(M1, tmp_path, list(range(1, 97, 5)), project=["AIM-pedestal"])
    for f in cam["frames"]:
        x, y, _ = f["projected"]["AIM-pedestal"]
        assert abs(x - 0.5) < TOL and abs(y - 0.5) < TOL, f["frame"]


def test_explicit_rotation_without_look_at(tmp_path):
    spec = m1()
    spec["camera"].pop("look_at")
    rots = [[80.0, 0.0, -45.0], [75.0, 0.0, 0.0], [80.0, 0.0, 45.0]]
    for k, r in zip(spec["camera"]["keys"], rots):
        k["rotation_deg"] = r
    _, cam = build_and_inspect(spec, tmp_path, [1, 48, 96])
    assert cam["camera"]["constraints"] == []
    frames = by_frame(cam)
    for k, r in zip(spec["camera"]["keys"], rots):
        f = frames[k["frame"]]
        R = euler_xyz(r)
        assert close(f["view_dir"], apply(R, [0, 0, -1]))        # degrees, XYZ, looks down -Z
        assert close(f["up_dir"], apply(R, [0, 1, 0]))
        assert close(f["location"], k["location"])


def test_rotation_with_look_at_is_ignored_in_legacy_specs(tmp_path):
    spec = m1()
    for k in spec["camera"]["keys"]:
        k["rotation_deg"] = [0.0, 0.0, 0.0]                # would look straight down
    _, cam = build_and_inspect(spec, tmp_path, [1, 96], project=["AIM-pedestal"])
    assert cam["camera"]["constraints"][0]["type"] == "TRACK_TO"
    for f in cam["frames"]:
        assert close(f["projected"]["AIM-pedestal"][:2], [0.5, 0.5])


def test_dof_with_look_at_focuses_on_aim_point(tmp_path):
    _, cam = build_and_inspect(m1(dof_enabled=True, fstop=5.6), tmp_path, [1])
    assert cam["camera"]["dof_focus_object"] == "AIM-pedestal"
    assert cam["frames"][0]["dof"] == {"use": True, "fstop": pytest.approx(5.6),
                                       "focus_distance": pytest.approx(10.0)}


def test_dof_without_focus_target_ignores_fstop_in_legacy_specs(tmp_path):
    """Current builder behaviour: DoF is on, but with no focus target the spec's fstop is not
    applied and Blender's defaults (f/2.8, 10 m) are used."""
    spec = m1(dof_enabled=True, fstop=8.0)
    spec["camera"].pop("look_at")
    for k in spec["camera"]["keys"]:
        k["rotation_deg"] = [80.0, 0.0, 0.0]
    _, cam = build_and_inspect(spec, tmp_path, [1])
    assert cam["camera"]["dof_focus_object"] is None
    assert cam["frames"][0]["dof"] == {"use": True, "fstop": pytest.approx(2.8),
                                       "focus_distance": pytest.approx(10.0)}


def test_animated_lens_follows_keys(tmp_path):
    spec = m1()
    spec["camera"]["keys"][0]["lens_mm"] = 24
    spec["camera"]["keys"][2]["lens_mm"] = 50
    _, cam = build_and_inspect(spec, tmp_path, [1, 48, 96])
    frames = by_frame(cam)
    assert frames[1]["lens"] == pytest.approx(24) and frames[96]["lens"] == pytest.approx(50)
    assert 24 < frames[48]["lens"] < 50


# ===========================================================================
# Stage 4: SceneSpec 1.2 camera fields in the builder
# ===========================================================================
TEMPLATE_WARNING = "no style template loaded; starting from an empty scene"
LEGACY_CAMERA_REPORT = {
    "type": "PERSP", "sensor_width": 36.0, "sensor_fit": "AUTO", "lens_mm": 35.0,
    "lens_animated": False, "look_at": "pedestal", "look_at_height": 0.3,
    "subject_offset": None, "shift": [0.0, 0.0], "clip": [0.1, 1000.0],
    "dof": {"enabled": False, "focus_object": None, "focus_distance_m": None, "fstop": None},
    "handheld_shake": 0.0}


def v12(resolution=None, **camera_patch) -> dict:
    d = m1(**camera_patch)
    d["spec_version"] = "1.2"
    if resolution:
        d["render"]["resolution"] = list(resolution)
    return d


def strip_paths(cam: dict) -> dict:
    return {k: v for k, v in cam.items() if k != "blend"}


def test_legacy_report_has_camera_block_and_all_previous_fields(tmp_path):
    report, _ = build_and_inspect(M1, tmp_path, [1])
    assert report["camera"] == LEGACY_CAMERA_REPORT
    for key in ("shot_id", "status", "warnings", "blender_version", "timings", "blend", "memory_mb"):
        assert key in report, key
    assert report["warnings"] == [TEMPLATE_WARNING]          # nothing new for a clean legacy spec
    assert "camera" in report["timings"]
    on_disk = json.loads((tmp_path / "project/shots/m1_primitives/build_report.json").read_text())
    assert on_disk["camera"] == LEGACY_CAMERA_REPORT


def test_v12_without_new_fields_builds_the_identical_camera(tmp_path):
    frames = [1, 24, 48, 72, 96]
    r11, c11 = build_and_inspect(M1, tmp_path / "v11", frames, project=["AIM-pedestal"])
    r12, c12 = build_and_inspect(v12(), tmp_path / "v12", frames, project=["AIM-pedestal"])
    assert strip_paths(c12) == strip_paths(c11)
    assert r12["camera"] == r11["camera"] == LEGACY_CAMERA_REPORT


@pytest.mark.parametrize("resolution, offset", [
    ((640, 360), [-1 / 6, 0.0]),        # left third line
    ((640, 360), [1 / 6, 1 / 6]),       # right third, upper third
    ((640, 360), [0.0, -0.3]),
    ((640, 360), [0.4, -0.4]),          # schema limits
    ((1280, 536), [0.1, 0.2]),          # 2.39:1 scope, a different landscape aspect
    ((360, 360), [0.25, 0.25]),         # square
], ids=["16x9-left-third", "16x9-upper-right-third", "16x9-low", "16x9-limits", "scope", "square"])
def test_subject_offset_places_the_aim_point_where_specified(tmp_path, resolution, offset):
    """Measured with world_to_camera_view on the evaluated camera at every 8th frame of a
    moving, tracking camera: the aim point sits at (0.5 + x, 0.5 + y) of the frame."""
    report, cam = build_and_inspect(v12(resolution, framing={"subject_offset": offset}),
                                    tmp_path, list(range(1, 97, 8)), project=["AIM-pedestal"])
    for f in cam["frames"]:
        x, y, depth = f["projected"]["AIM-pedestal"]
        assert (x, y) == (pytest.approx(0.5 + offset[0], abs=TOL),
                          pytest.approx(0.5 + offset[1], abs=TOL)), f["frame"]
        assert depth > 0
    w, h = resolution
    assert report["camera"]["subject_offset"] == pytest.approx(offset)
    assert report["camera"]["shift"] == pytest.approx([-offset[0], -offset[1] * h / w], abs=1e-6)
    assert cam["frames"][0]["shift"] == pytest.approx(report["camera"]["shift"], abs=1e-6)


def test_subject_offset_on_a_portrait_frame_is_refused(tmp_path):
    report = run_shot(v12((360, 640), framing={"subject_offset": [0.1, 0]}),
                      tmp_path / "project", render=False)
    assert report["status"] == "spec_error" and report["returncode"] != 0
    assert "only supported for landscape or square frames; render.resolution is 360x640" \
        in report["error"]


def test_portrait_frame_without_framing_still_builds(tmp_path):
    report, cam = build_and_inspect(v12((360, 640)), tmp_path, [1], project=["AIM-pedestal"])
    assert report["camera"]["shift"] == [0.0, 0.0]
    assert cam["frames"][0]["projected"]["AIM-pedestal"][:2] == [pytest.approx(0.5, abs=TOL)] * 2


def test_clip_range_is_applied(tmp_path):
    report, cam = build_and_inspect(v12(clip_start_m=0.02, clip_end_m=250), tmp_path, [1, 96])
    for f in cam["frames"]:
        assert (f["clip_start"], f["clip_end"]) == (pytest.approx(0.02), pytest.approx(250))
    assert report["camera"]["clip"] == [pytest.approx(0.02), pytest.approx(250)]


def test_one_sided_clip_keeps_the_other_default(tmp_path):
    report, _ = build_and_inspect(v12(clip_end_m=40), tmp_path, [1])
    assert report["camera"]["clip"] == [pytest.approx(0.1), pytest.approx(40)]


def test_focus_distance_with_fstop_for_dof_without_a_focus_object(tmp_path):
    spec = v12(dof_enabled=True, fstop=2.0, focus_distance_m=3.5)
    spec["camera"].pop("look_at")
    for k in spec["camera"]["keys"]:
        k["rotation_deg"] = [80.0, 0.0, 0.0]
    report, cam = build_and_inspect(spec, tmp_path, [1])
    assert cam["camera"]["dof_focus_object"] is None
    assert cam["frames"][0]["dof"] == {"use": True, "fstop": pytest.approx(2.0),
                                       "focus_distance": pytest.approx(3.5)}
    assert report["camera"]["dof"] == {"enabled": True, "focus_object": None,
                                       "focus_distance_m": pytest.approx(3.5),
                                       "fstop": pytest.approx(2.0)}


def test_focus_object_dof_is_reported(tmp_path):
    report, _ = build_and_inspect(v12(dof_enabled=True, fstop=5.6), tmp_path, [1])
    assert report["camera"]["dof"] == {"enabled": True, "focus_object": "AIM-pedestal",
                                       "focus_distance_m": None, "fstop": pytest.approx(5.6)}


def test_all_v12_fields_together(tmp_path):
    spec = v12(framing={"subject_offset": [-1 / 6, 0.1]}, clip_start_m=0.05, clip_end_m=300,
               dof_enabled=True, fstop=4.0)
    report, cam = build_and_inspect(spec, tmp_path, [1, 48, 96], project=["AIM-pedestal"])
    for f in cam["frames"]:
        assert f["projected"]["AIM-pedestal"][:2] == [pytest.approx(0.5 - 1 / 6, abs=TOL),
                                                     pytest.approx(0.6, abs=TOL)]
        assert (f["clip_start"], f["clip_end"]) == (pytest.approx(0.05), pytest.approx(300))
        assert f["dof"]["use"] is True and f["dof"]["fstop"] == pytest.approx(4.0)
    assert cam["camera"]["constraints"][0]["type"] == "TRACK_TO"      # look_at unchanged


def test_legacy_conflict_warning_reaches_the_report_on_disk(tmp_path):
    spec = m1()
    spec["camera"]["keys"][0]["rotation_deg"] = [0.0, 0.0, 0.0]
    report, cam = build_and_inspect(spec, tmp_path, [1], project=["AIM-pedestal"])
    expected = ("camera: rotation_deg on keys at frames [1] is ignored because look_at "
                "'pedestal' controls rotation")
    assert report["warnings"] == [TEMPLATE_WARNING, expected]
    on_disk = json.loads((tmp_path / "project/shots/m1_primitives/build_report.json").read_text())
    assert on_disk["warnings"] == [TEMPLATE_WARNING, expected]
    assert on_disk["camera"] == LEGACY_CAMERA_REPORT                # behaviour itself unchanged
    assert cam["frames"][0]["projected"]["AIM-pedestal"][:2] == [pytest.approx(0.5, abs=TOL)] * 2
