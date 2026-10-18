"""Milestone 7: the ochre variant and the gesture actions authored in Blender. Run with:
pytest -m blender tests/test_mannequin_gestures_assets.py

Every run authors (`mannequin.py --set m7`) into pytest temporary directories only; nothing is
written to assets/. The files are read back with the read-only blender/scripts/inspect_asset.py.
Evaluated layering over the idle, through the real builder, is in
tests/test_m7_gesture_layering.py.
"""
import hashlib
import importlib.util
import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from workers import config
from workers.blender_job import REPO

pytestmark = [
    pytest.mark.blender,
    pytest.mark.skipif(shutil.which(config.BLENDER_BIN) is None, reason="Blender not found"),
]

AUTHOR = REPO / "blender" / "scripts" / "author_assets" / "mannequin.py"
INSPECT = REPO / "blender" / "scripts" / "inspect_asset.py"
_spec = importlib.util.spec_from_file_location("afs_mannequin", AUTHOR)
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

SLOT = "OBRIG-mannequin"
OCHRE, GESTURES = M.OCHRE_FILE.as_posix(), M.GESTURES_FILE.as_posix()
KEYS = [OCHRE, GESTURES]
GREY_CHARACTER = REPO / "assets" / M.CHARACTER_FILE
WALK_IDLE = REPO / "assets" / M.ACTIONS_FILE
# Structural fingerprints of the two files, as authored by Blender 5.2.2 LTS.
GOLDEN_BLENDER = "5.2.2 LTS"
GOLDEN = {
    OCHRE: "57ff3bfd311f4ef8265f2d7d3ed1fec6e84721d690229321c5d73b0f1a1caab8",
    GESTURES: "a96a63d29cc24aa10aa87614afed32628b5b0fa7c52cb0dafbe22fb6646c19e9",
}
EVAL_FRAMES = [1, 5, 9, 17, 25, 33, 41]


def author(out_root: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [config.BLENDER_BIN, "-b", "--factory-startup", "--python-exit-code", "1",
         "-P", str(AUTHOR), "--", "--out-root", str(out_root), *extra],
        capture_output=True, text=True, errors="replace", timeout=300)


def inspect(blend: Path, out: Path, *extra: str) -> dict:
    proc = subprocess.run(
        [config.BLENDER_BIN, "-b", "--factory-startup", "--python-exit-code", "1",
         "-P", str(INSPECT), "--", "--blend", str(blend), "--out", str(out), *extra],
        capture_output=True, text=True, errors="replace", timeout=300)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    return json.loads(out.read_text())


def authored_set(root: Path, work: Path) -> dict:
    proc = author(root, "--set", "m7")
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    return {k: inspect(root / k, work / f"{Path(k).stem}.json") for k in KEYS}


@pytest.fixture(scope="module")
def run_a(tmp_path_factory):
    base = tmp_path_factory.mktemp("m7_a")
    return base / "assets", authored_set(base / "assets", base)


@pytest.fixture(scope="module")
def run_b(tmp_path_factory):
    base = tmp_path_factory.mktemp("m7_b")
    return base / "assets", authored_set(base / "assets", base)


@pytest.fixture(scope="module")
def grey(tmp_path_factory):
    """The installed Milestone 6 character, read-only, playing the installed walk and idle."""
    base = tmp_path_factory.mktemp("grey")
    return inspect(GREY_CHARACTER, base / "grey.json", "--evaluate-actions", str(WALK_IDLE),
                   "--armature", M.ARMATURE, "--frames", ",".join(map(str, EVAL_FRAMES)))


@pytest.fixture(scope="module")
def ochre_plays(tmp_path_factory, run_a):
    """The authored ochre rig playing the installed walk and idle, and (separately) the
    gestures, each placed alone as an NLA strip the way build_scene does."""
    base, (root, _) = tmp_path_factory.mktemp("ochre_plays"), run_a
    common = ["--armature", M.OCHRE["armature"], "--frames", ",".join(map(str, EVAL_FRAMES))]
    walk_idle = inspect(root / OCHRE, base / "walk_idle.json", "--evaluate-actions",
                        str(WALK_IDLE), *common)
    gestures = inspect(root / OCHRE, base / "gestures.json", "--evaluate-actions",
                       str(root / GESTURES), *common)
    return walk_idle["evaluated"], gestures["evaluated"]


def digest(root: Path, keys) -> dict[str, tuple[str, int]]:
    return {k: (hashlib.sha256((root / k).read_bytes()).hexdigest(), (root / k).stat().st_mtime_ns)
            for k in keys if (root / k).exists()}


# ---------------------------------------------------------------------------
# Files, contents and determinism
# ---------------------------------------------------------------------------
def test_writes_exactly_the_two_m7_files(run_a):
    root, _ = run_a
    files = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    assert files == sorted(KEYS), "no .tmp.blend, no Milestone 6 files, no work rig"


def test_files_hold_only_the_expected_datablocks(run_a):
    _, rep = run_a
    assert rep[OCHRE]["contents"] == {
        "armatures": [M.OCHRE["armature"]], "collections": [M.OCHRE["collection"]],
        "materials": ["MAT-mannequin_ochre_accent", "MAT-mannequin_ochre_body"],
        "meshes": [M.OCHRE["body"]], "objects": [M.OCHRE["body"], M.OCHRE["armature"]]}
    assert rep[GESTURES]["contents"] == {"actions": ["mannequin_look", "mannequin_wave"]}


def test_two_authoring_runs_have_identical_structural_fingerprints(run_a, run_b):
    for k in KEYS:
        assert run_a[1][k]["fingerprint"] == run_b[1][k]["fingerprint"], k


def test_fingerprints_match_the_pinned_golden_values(run_a):
    rep = run_a[1]
    if rep[OCHRE]["blender_version"] != GOLDEN_BLENDER:
        pytest.skip(f"golden fingerprints were pinned with Blender {GOLDEN_BLENDER}")
    assert {k: rep[k]["fingerprint"] for k in KEYS} == GOLDEN


# ---------------------------------------------------------------------------
# Gesture actions
# ---------------------------------------------------------------------------
def test_each_gesture_has_one_object_slot_and_its_frame_range(run_a):
    acts = run_a[1][GESTURES]["actions"]
    for name, frames in M.GESTURE_FRAMES.items():
        a = acts[name]
        assert a["slots"] == [{"identifier": SLOT, "target_id_type": "OBJECT"}], name
        assert a["layers"] == 1
        assert a["use_frame_range"] and not a["use_cyclic"]
        assert a["frame_range"] == [1.0, 1.0 + frames]


def test_gestures_key_exactly_their_table_channels_with_the_table_values(run_a):
    acts = run_a[1][GESTURES]["actions"]
    for name, keys in M.gestures().items():
        fcurves = acts[name]["fcurves"]
        expected = {f'{SLOT}|pose.bones["{b}"].rotation_euler[{i}]'
                    for b, axes in keys[0][1].items() for i in axes}
        assert set(fcurves) == expected, name
        assert not any("location" in p or "thigh" in p or "shin" in p or "foot" in p
                       or '"hips"' in p for p in fcurves), name
        for i, (frame, rot) in enumerate(keys):
            for bone, axes in rot.items():
                for axis, deg in axes.items():
                    got = fcurves[f'{SLOT}|pose.bones["{bone}"].rotation_euler[{axis}]']["keys"][i]
                    assert got == pytest.approx([frame, math.radians(deg)], abs=2e-6), (name, frame, bone)
        for path, fc in fcurves.items():
            assert fc["interpolation"] == ["BEZIER"] and fc["modifiers"] == [], path


# ---------------------------------------------------------------------------
# The ochre variant
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def grey_structure(tmp_path_factory):
    return inspect(GREY_CHARACTER, tmp_path_factory.mktemp("grey_s") / "grey.json")


def test_ochre_rig_is_the_mannequin_rig_under_its_own_name(run_a, grey_structure):
    ochre = run_a[1][OCHRE]
    assert ochre["armatures"][M.OCHRE["armature"]] == grey_structure["armatures"][M.ARMATURE]
    rig = ochre["objects"][M.OCHRE["armature"]]
    assert rig["pose"] == grey_structure["objects"][M.ARMATURE]["pose"]
    assert rig["parent"] is None and not rig["has_animation_data"]


def test_ochre_body_is_the_mannequin_body_with_ochre_materials(run_a, grey_structure):
    o_mesh = dict(run_a[1][OCHRE]["meshes"][M.OCHRE["body"]])
    g_mesh = dict(grey_structure["meshes"][M.BODY])
    assert o_mesh.pop("materials") == ["MAT-mannequin_ochre_body", "MAT-mannequin_ochre_accent"]
    assert g_mesh.pop("materials") == ["MAT-mannequin_body", "MAT-mannequin_accent"]
    assert o_mesh == g_mesh, "same geometry, counts, bounds and material slots"
    o_body = dict(run_a[1][OCHRE]["objects"][M.OCHRE["body"]])
    g_body = dict(grey_structure["objects"][M.BODY])
    assert o_body.pop("parent") == M.OCHRE["armature"] and g_body.pop("parent") == M.ARMATURE
    assert o_body.pop("data") == M.OCHRE["body"] and g_body.pop("data") == M.BODY
    assert o_body.pop("modifiers") == [{"type": "ARMATURE", "object": M.OCHRE["armature"]}]
    g_body.pop("modifiers")
    assert o_body == g_body, "same skinning, vertex groups and transform"


def test_ochre_colours_are_distinct_from_the_grey(run_a, grey_structure):
    o = run_a[1][OCHRE]["materials"]
    g = grey_structure["materials"]
    body, grey_body = o["MAT-mannequin_ochre_body"]["diffuse_color"], g["MAT-mannequin_body"]["diffuse_color"]
    assert body == [*M.MATERIALS["ochre_body"][1], 1.0]
    assert max(abs(a - b) for a, b in zip(body[:3], grey_body[:3])) > 0.3


def test_ochre_rig_plays_the_walk_and_idle_exactly_like_the_grey(ochre_plays, grey):
    walk_idle, _ = ochre_plays
    for name in ("mannequin_walk", "mannequin_idle"):
        assert walk_idle[name]["strip_slot"] == SLOT, name
        for f in map(str, EVAL_FRAMES):
            assert walk_idle[name]["frames"][f] == grey["evaluated"][name]["frames"][f], (name, f)


def test_gesture_strips_get_the_slot_on_the_ochre_rig(ochre_plays):
    _, gestures = ochre_plays
    for name in M.GESTURE_FRAMES:
        assert gestures[name]["strip_slot"] == SLOT, name


# ---------------------------------------------------------------------------
# Overwrite protection and separation from the Milestone 6 set
# ---------------------------------------------------------------------------
@pytest.fixture
def authored_once(tmp_path):
    root = tmp_path / "assets"
    proc = author(root, "--set", "m7")
    assert proc.returncode == 0, proc.stderr[-2000:]
    return root


def test_existing_m7_outputs_are_never_overwritten_without_force(authored_once):
    before = digest(authored_once, KEYS)
    proc = author(authored_once, "--set", "m7")
    assert proc.returncode != 0 and "REFUSED" in proc.stderr and "--force" in proc.stderr
    assert digest(authored_once, KEYS) == before


def test_force_rewrites_the_m7_files_with_the_same_structure(authored_once, tmp_path, run_a):
    before = digest(authored_once, KEYS)
    proc = author(authored_once, "--set", "m7", "--force")
    assert proc.returncode == 0, proc.stderr[-2000:]
    after = digest(authored_once, KEYS)
    assert all(after[k][1] != before[k][1] for k in KEYS), "every file was rewritten"
    for k in KEYS:
        assert inspect(authored_once / k, tmp_path / f"{Path(k).stem}.json")["fingerprint"] == \
            run_a[1][k]["fingerprint"], k


def test_the_m7_set_leaves_existing_m6_files_alone(tmp_path):
    root = tmp_path / "assets"
    assert author(root).returncode == 0                       # the Milestone 6 set
    m6 = [p.as_posix() for p in M.OUTPUTS]
    before = digest(root, m6)
    proc = author(root, "--set", "m7")
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert digest(root, m6) == before, "m7 neither refuses on nor rewrites the m6 files"
    files = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    assert files == sorted(m6 + KEYS)
