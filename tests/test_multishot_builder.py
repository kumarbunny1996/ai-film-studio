"""SceneSpec 1.3 in the Blender builder (Milestone 4). Run with: pytest -m blender

Builds into tmp_path with run_shot(render=False) and reads the result back with the fixed,
read-only blender/scripts/inspect_camera.py. The active camera is read with --camera active
(scene.camera after frame_set). Only the smoke tests render: 6 frames at 320x180 (smoke = 50% of 640x360).
"""
import copy
import json
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

from workers import config
from workers.blender_job import ASSETS, REPO, run_shot

pytestmark = [
    pytest.mark.blender,
    pytest.mark.skipif(shutil.which(config.BLENDER_BIN) is None, reason="Blender not found"),
]

M1 = json.loads((REPO / "schemas/examples/milestone1_primitives.json").read_text())
M4 = json.loads((REPO / "schemas/examples/m4_sequence.json").read_text())
INSPECT = REPO / "blender" / "scripts" / "inspect_camera.py"
BUILD = REPO / "blender" / "scripts" / "build_scene.py"
TEMPLATE_WARNING = "no style template loaded; starting from an empty scene"
TOL = 1e-4
EXPECTED_CAMERA = {1: "CAM-sh01_wide", 48: "CAM-sh01_wide", 49: "CAM-sh02_track",
                   50: "CAM-sh02_track", 96: "CAM-sh02_track", 97: "CAM-sh03_close",
                   98: "CAM-sh03_close", 132: "CAM-sh03_close"}
LEGACY_REPORT_KEYS = ("shot_id", "status", "warnings", "blender_version", "timings", "blend",
                      "memory_mb")


def inspect(blend: str, out: Path, frames, project=(), camera=None) -> dict:
    cmd = [config.BLENDER_BIN, "-b", blend, "--factory-startup", "--python-exit-code", "1",
           "-P", str(INSPECT), "--", "--out", str(out), "--frames", ",".join(map(str, frames)),
           "--project", ",".join(project)]
    if camera:
        cmd += ["--camera", camera]
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=300)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    return json.loads(out.read_text())


def build(spec: dict, tmp_path: Path, **kw) -> dict:
    report = run_shot(spec, tmp_path / "project", **{"render": False, **kw})
    assert report["status"] == "ok" and report["returncode"] == 0, report
    return report


def raw_build(spec: dict, tmp_path: Path) -> dict:
    """Run build_scene.py on a spec WITHOUT SceneSpec validation, to check the builder's
    own safety checks."""
    out = tmp_path / "raw"
    out.mkdir()
    spec_path = out / "spec.json"
    spec_path.write_text(json.dumps(spec))
    proc = subprocess.run([config.BLENDER_BIN, "-b", "--factory-startup", "--python-exit-code",
                           "1", "-P", str(BUILD), "--", "--spec", str(spec_path),
                           "--assets-root", str(ASSETS), "--out", str(out), "--no-render"],
                          capture_output=True, text=True, errors="replace", timeout=300)
    report = json.loads((out / "build_report.json").read_text())
    report["returncode"] = proc.returncode
    return report


def by_frame(cam: dict) -> dict[int, dict]:
    return {f["frame"]: f for f in cam["frames"]}


def m4(**render) -> dict:
    d = copy.deepcopy(M4)
    d["render"].update(render)
    return d


# ---------------------------------------------------------------------------
# Single-camera v1.3 is the existing single-camera build
# ---------------------------------------------------------------------------
def test_v13_single_camera_builds_exactly_like_v12(tmp_path):
    v12 = copy.deepcopy(M1)
    v12["spec_version"] = "1.2"
    v13 = copy.deepcopy(M1)
    v13["spec_version"] = "1.3"
    frames = [1, 24, 48, 72, 96]
    r12 = build(v12, tmp_path / "a")
    r13 = build(v13, tmp_path / "b")
    c12 = inspect(r12["blend"], tmp_path / "a.json", frames, ["AIM-pedestal"])
    c13 = inspect(r13["blend"], tmp_path / "b.json", frames, ["AIM-pedestal"])
    assert {k: v for k, v in c13.items() if k != "blend"} == \
           {k: v for k, v in c12.items() if k != "blend"}
    assert r13["camera"] == r12["camera"]
    assert "shots" not in r13 and "cuts" not in r13
    assert r13["warnings"] == [TEMPLATE_WARNING]


def test_default_inspector_output_is_unchanged_for_single_camera(tmp_path):
    report = build(M1, tmp_path)
    cam = inspect(report["blend"], tmp_path / "c.json", [1], ["AIM-pedestal"])
    assert list(cam) == ["blend", "scene_camera", "resolution", "camera", "frames"]
    assert "active_camera" not in cam["frames"][0] and "markers" not in cam


# ---------------------------------------------------------------------------
# Multi-shot: cameras, markers, report
# ---------------------------------------------------------------------------
def test_multishot_report(tmp_path):
    report = build(M4, tmp_path)
    for key in LEGACY_REPORT_KEYS:
        assert key in report, key
    assert "camera" not in report                       # no single camera in this form
    assert report["warnings"] == [TEMPLATE_WARNING]
    assert report["cuts"] == [49, 97]
    shots = report["shots"]
    assert [(s["shot_id"], s["frame_range"], s["frame_count"], s["camera_object"], s["marker"])
            for s in shots] == [
        ("sh01_wide", [1, 48], 48, "CAM-sh01_wide", "CUT-sh01_wide"),
        ("sh02_track", [49, 96], 48, "CAM-sh02_track", "CUT-sh02_track"),
        ("sh03_close", [97, 132], 36, "CAM-sh03_close", "CUT-sh03_close")]
    wide, track, close = (s["camera"] for s in shots)
    assert (wide["lens_mm"], track["lens_mm"], close["lens_mm"]) == (28.0, 50.0, 85.0)
    assert wide["dof"]["enabled"] is False
    assert track["dof"]["focus_object"] == "AIM-sh02_track-hero"
    assert close["dof"] == {"enabled": True, "focus_object": "AIM-sh03_close-hero",
                            "focus_distance_m": None, "fstop": pytest.approx(2.8)}
    assert close["subject_offset"] == [-0.1667, 0.0]
    assert close["shift"] == [pytest.approx(0.1667), 0.0]
    assert close["clip"] == [pytest.approx(0.05), pytest.approx(100.0)]


def test_markers_bind_each_camera_at_its_shot_start(tmp_path):
    report = build(M4, tmp_path)
    cam = inspect(report["blend"], tmp_path / "c.json", [1], camera="active")
    assert cam["scene_camera"] == "CAM-sh01_wide"         # saved after frame_set(start)
    assert cam["markers"] == [
        {"name": "CUT-sh01_wide", "frame": 1, "camera": "CAM-sh01_wide"},
        {"name": "CUT-sh02_track", "frame": 49, "camera": "CAM-sh02_track"},
        {"name": "CUT-sh03_close", "frame": 97, "camera": "CAM-sh03_close"}]
    for shot, cinfo in cam["cameras"].items():
        sid = shot.removeprefix("CAM-")
        assert cinfo["type"] == "PERSP" and cinfo["sensor_width"] == 36.0
        assert cinfo["constraints"] == [{"type": "TRACK_TO", "target": f"AIM-{sid}-hero",
                                         "track_axis": "TRACK_NEGATIVE_Z", "up_axis": "UP_Y"}]


def test_active_camera_on_both_sides_of_every_cut(tmp_path):
    report = build(M4, tmp_path)
    frames = list(EXPECTED_CAMERA)
    for order in (frames, list(reversed(frames))):       # not dependent on visiting order
        cam = inspect(report["blend"], tmp_path / "c.json", order, camera="active")
        assert {f["frame"]: f["active_camera"] for f in cam["frames"]} == EXPECTED_CAMERA


def test_each_shot_frames_the_subject_with_its_own_camera(tmp_path):
    report = build(M4, tmp_path)
    frames = [1, 24, 48, 49, 72, 96, 97, 110, 132]
    cam = by_frame(inspect(report["blend"], tmp_path / "c.json", frames, ["PRIM-hero"],
                           camera="active"))
    for f in frames:
        x, y, depth = cam[f]["projected"]["PRIM-hero"]
        want_x = 0.5 - 0.1667 if f >= 97 else 0.5          # sh03 holds it on the left third
        assert (x, y) == (pytest.approx(want_x, abs=TOL), pytest.approx(0.5, abs=TOL)), f
        assert depth > 0
    assert cam[48]["lens"] == pytest.approx(28) and cam[49]["lens"] == pytest.approx(50)
    assert cam[97]["lens"] == pytest.approx(85) and cam[97]["shift"] == [pytest.approx(0.1667), 0.0]


def test_shots_have_independent_aim_points(tmp_path):
    """Two shots tracking the same subject at different look_at_height must not share an
    aim empty (a shared one would silently use the first shot's height)."""
    spec = m4()
    spec["shots"][1]["camera"]["look_at_height"] = 0.5
    report = build(spec, tmp_path)
    cam = by_frame(inspect(report["blend"], tmp_path / "c.json", [24, 72],
                           ["PRIM-hero", "AIM-sh02_track-hero"], camera="active"))
    assert cam[24]["projected"]["PRIM-hero"][1] == pytest.approx(0.5, abs=TOL)       # sh01: 0 m
    assert cam[72]["projected"]["AIM-sh02_track-hero"][:2] == [pytest.approx(0.5, abs=TOL)] * 2
    assert cam[72]["projected"]["PRIM-hero"][1] < 0.5 - 0.01                       # aimed 0.5 m above
    assert report["shots"][1]["camera"]["look_at_height"] == 0.5


def test_short_shot_warning_reaches_the_report_on_disk(tmp_path):
    spec = m4()
    spec["shots"][0]["frame_end"] = 8
    spec["shots"][0]["camera"]["keys"][1]["frame"] = 8
    spec["shots"][1]["frame_start"] = 9
    spec["shots"][1]["camera"]["keys"][0]["frame"] = 9
    report = build(spec, tmp_path)
    warning = ("shot 'sh01_wide' is 8 frame(s) long (frames 1-8); shots under 12 frames are "
               "very short")
    assert report["warnings"] == [TEMPLATE_WARNING, warning]
    disk = json.loads((tmp_path / "project/shots/m4_sequence/build_report.json").read_text())
    assert disk["warnings"] == [TEMPLATE_WARNING, warning] and disk["cuts"] == [9, 97]


# ---------------------------------------------------------------------------
# Smoke mode: both sides of every cut, at 50 %
# ---------------------------------------------------------------------------
def png_size(path: Path) -> tuple[int, int]:
    return struct.unpack(">II", path.read_bytes()[16:24])


def test_multishot_smoke_renders_both_sides_of_every_cut(tmp_path):
    report = run_shot(m4(), tmp_path / "project", render=True, smoke=True)
    assert report["status"] == "ok" and report["returncode"] == 0, report
    expected = [1, 48, 49, 96, 97, 132]                  # first and last frame of every shot
    assert report["smoke"] is True
    assert report["smoke_frames"] == report["rendered_frames"] == expected
    assert report["frame_range"] == [1, 132] and report["resolution"] == [320, 180]
    frames_dir = Path(report["frames_dir"])
    pngs = sorted(p.name for p in frames_dir.glob("*.png"))
    assert pngs == [f"m4_sequence_{f:04d}.png" for f in expected]
    assert all(png_size(frames_dir / n) == (320, 180) for n in pngs)


def test_multishot_smoke_is_not_mistaken_for_a_full_render(tmp_path):
    """A real multi-shot smoke render reports rendered_frames, so the encode pipeline refuses
    it from the report itself (not from missing files, which stale frames could hide)."""
    from workers.run_milestone1 import PipelineError, run
    spec_path = tmp_path / "m4_small.json"
    spec_path.write_text(json.dumps(m4()))
    with pytest.raises(PipelineError, match=r"Partial \(smoke\) render; not encodable: 126 of "
                                            r"132 frames in 1-132 were not rendered"):
        run(spec_path, tmp_path / "project", smoke=True)
    assert not list((tmp_path / "project").glob("*.mp4"))


# ---------------------------------------------------------------------------
# The builder's own safety checks (no SceneSpec validation in front of it)
# ---------------------------------------------------------------------------
def test_unsupported_version_fails_safely(tmp_path):
    report = raw_build({**copy.deepcopy(M4), "spec_version": "1.4"}, tmp_path)
    assert report["status"] == "spec_error" and report["returncode"] == 1
    assert "spec_version 1.4 not in" in report["error"]
    assert "blend" not in report


def test_spec_with_neither_camera_nor_shots_fails_safely(tmp_path):
    d = copy.deepcopy(M4)
    d.pop("shots")
    report = raw_build(d, tmp_path)
    assert report["status"] == "spec_error" and "neither camera nor shots" in report["error"]


def test_shot_tracking_a_missing_object_fails_safely(tmp_path):
    d = copy.deepcopy(M4)
    d["shots"][2]["camera"]["look_at"] = "ghost"
    d["shots"][2]["camera"]["focus_target"] = None
    report = raw_build(d, tmp_path)
    assert report["status"] == "spec_error" and report["returncode"] == 1
    assert "camera target 'ghost' does not exist" in report["error"]
    assert "blend" not in report
