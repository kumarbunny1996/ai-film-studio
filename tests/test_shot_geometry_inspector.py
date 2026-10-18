"""Milestone 8 Gate 1: blender/scripts/inspect_shot_geometry.py on built scenes. Run with:
pytest -m blender tests/test_shot_geometry_inspector.py

Builds the M3 (single camera, subject offset), M4 (three cut cameras with offsets) and M7 (eight
cut cameras, two characters, props, primitives) examples with run_shot(render=False) into
tmp_path, then runs the read-only inspector with --reference, which projects every bone point
and every mesh vertex in front of the camera both with workers/projection.py and with Blender's
world_to_camera_view. Nothing is rendered and nothing is written outside tmp_path.
"""
import hashlib
import json
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

INSPECT = REPO / "blender" / "scripts" / "inspect_shot_geometry.py"
TOL = 1e-4
EXAMPLES = {"m3_framing": 2, "m4_sequence": 2, "m7_greeting": 4}      # example -> sample step


def spec(name: str) -> dict:
    return json.loads((REPO / f"schemas/examples/{name}.json").read_text())


def inspect(blend: str, out: Path, *extra: str) -> dict:
    proc = subprocess.run(
        [config.BLENDER_BIN, "-b", blend, "--factory-startup", "--python-exit-code", "1",
         "-P", str(INSPECT), "--", "--out", str(out), *extra],
        capture_output=True, text=True, errors="replace", timeout=900)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    return json.loads(out.read_text())


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = {}
    for name in EXAMPLES:
        root = tmp_path_factory.mktemp(name)
        report = run_shot(spec(name), root / "project", render=False)
        assert report["status"] == "ok" and report["returncode"] == 0, report
        out[name] = report["blend"]
    return out


@pytest.fixture(scope="module")
def geometry(built, tmp_path_factory):
    out = {}
    for name, step in EXAMPLES.items():
        root = tmp_path_factory.mktemp(f"{name}_geometry")
        out[name] = inspect(built[name], root / "geometry.json", "--step", str(step), "--reference")
    return out


def sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Projection against Blender
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", list(EXAMPLES))
def test_projection_matches_world_to_camera_view(geometry, name):
    """Every bone point and mesh vertex at least clip_start in front of the camera: absolute
    x/y error near the frame (within half a frame of it), relative x/y error everywhere (far
    off-screen the coordinates grow as 1/depth and Blender's single-precision matrices
    dominate: a ground corner 0.16 m in front of the M3 camera projects to x = 107), and
    absolute depth error, all within 1e-4."""
    ref = geometry[name]["reference"]
    assert ref["margin"] == 0.5 and ref["near_frame_points"] > 1000
    assert ref["max_near_frame_abs_xy_error"] <= TOL, ref
    assert ref["max_rel_xy_error"] <= TOL, ref
    assert ref["max_abs_depth_error"] <= TOL, ref


def test_the_cameras_checked_include_lens_shift(geometry):
    shifts = {name: {tuple(f["camera"]["shift"]) for f in g["frames"]} for name, g in geometry.items()}
    for name in EXAMPLES:
        assert any(s != (0.0, 0.0) for s in shifts[name]), name


# ---------------------------------------------------------------------------
# Cameras and cuts
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", list(EXAMPLES))
def test_each_frame_reports_the_camera_and_shot_the_timeline_uses(geometry, name):
    s = spec(name)
    g = geometry[name]
    assert g["schema"] == "shot_geometry.v1"
    assert g["frame_range"] == [s["render"]["frame_start"], s["render"]["frame_end"]]
    assert g["frames_sampled"] == list(range(s["render"]["frame_start"], s["render"]["frame_end"] + 1,
                                             EXAMPLES[name]))
    for f in g["frames"]:
        if "shots" in s:
            shot = next(x for x in s["shots"] if x["frame_start"] <= f["frame"] <= x["frame_end"])
            assert (f["shot_id"], f["camera_object"]) == (shot["shot_id"], f"CAM-{shot['shot_id']}")
        else:
            assert (f["shot_id"], f["camera_object"]) == (None, "CAM-shot")
        assert f["camera"]["resolution"] == s["render"]["resolution"]


# ---------------------------------------------------------------------------
# Objects, islands and outlines
# ---------------------------------------------------------------------------
def test_objects_are_labelled_with_their_scenespec_names(geometry):
    objs = geometry["m7_greeting"]["objects"]
    prims = {p["name"] for p in spec("m7_greeting")["primitives"]}
    assert {o["owner"] for o in objs.values() if o["kind"] == "primitive"} == prims
    chars = {o["owner"]: o for o in objs.values() if o["kind"] == "character"}
    assert set(chars) == {"host", "traveller"}
    bones = set(geometry["m7_greeting"]["armatures"]["RIG-mannequin"]["bones"])
    for c in chars.values():
        assert set(c["islands"]) == bones, "one rigid part per bone"
    assert {o["owner"]: o["kind"] for o in objs.values() if o["kind"] == "prop"} == {"baton": "prop"}
    assert all(len(o["islands"]) == 1 for o in objs.values() if o["kind"] == "primitive")


def test_outlines_contain_their_islands_and_report_in_front_depths(geometry):
    for f in geometry["m7_greeting"]["frames"]:
        for name, o in f["objects"].items():
            assert o["depth"][0] > 0 and o["depth"][0] <= o["depth"][1], (f["frame"], name)
            xs, ys = [p[0] for p in o["hull"]], [p[1] for p in o["hull"]]
            for isl in o["islands"].values():
                for x, y in isl["hull"]:
                    assert min(xs) - 1e-6 <= x <= max(xs) + 1e-6 and min(ys) - 1e-6 <= y <= max(ys) + 1e-6


def test_the_outlines_agree_with_the_approved_m7_framing(geometry):
    """Facts the approved M7 scene was built to satisfy (pinned by its own spec tests): no tree
    in sh05, the lamp post out of frame in sh02, both characters whole in sh04."""
    for f in geometry["m7_greeting"]["frames"]:
        objs = f["objects"]
        if f["shot_id"] == "sh05_host_wave":
            assert not any(objs[n]["in_frame"] for n in objs if "tree" in n), f["frame"]
            assert objs["PRIM-lamp_post"]["in_frame"]
        if f["shot_id"] == "sh02_host_look":
            assert "PRIM-lamp_post" not in objs or not objs["PRIM-lamp_post"]["in_frame"], f["frame"]
        if f["shot_id"] == "sh04_two_shot":
            for name in ("GEO-mannequin", "GEO-mannequin_ochre"):
                assert all(0 < x < 1 and 0 < y < 1 for x, y in objs[name]["hull"]), (f["frame"], name)


# ---------------------------------------------------------------------------
# Read-only and deterministic
# ---------------------------------------------------------------------------
def test_inspection_is_read_only_and_deterministic(built, tmp_path):
    blend = built["m7_greeting"]
    before = sha(blend)
    folder = sorted(p.name for p in Path(blend).parent.iterdir())
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    inspect(blend, a, "--step", "8")
    inspect(blend, b, "--step", "8")
    assert a.read_bytes() == b.read_bytes(), "the same .blend gives the same report"
    assert sha(blend) == before and sorted(p.name for p in Path(blend).parent.iterdir()) == folder
