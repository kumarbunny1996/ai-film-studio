"""Milestone 11: head marker A in the mannequin authoring tables, without Blender.

The marked characters (--set m11) are the mannequins plus MARKER_A: a dark visor and a
body-coloured nose, rigidly on the head bone. The values must equal the design adopted in M11
(tools/m11_marker_test/marker_test.py, design A = rev3's D3). The Blender side is in
tests/test_mannequin_marked_assets.py.
"""
import ast
import importlib.util
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "blender" / "scripts" / "author_assets" / "mannequin.py"
M11_SCRIPT = ROOT / "tools" / "m11_marker_test" / "marker_test.py"


def load():
    spec = importlib.util.spec_from_file_location("afs_mannequin", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = load()


def m11_constants() -> dict:
    """Module-level literal assignments of the M11 experiment script (read, never imported:
    it needs bpy)."""
    out = {}
    for node in ast.parse(M11_SCRIPT.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                continue
            if isinstance(target, ast.Name):
                out[target.id] = value
            elif isinstance(target, ast.Tuple) and isinstance(value, tuple):
                out.update({t.id: v for t, v in zip(target.elts, value) if isinstance(t, ast.Name)})
    return out


def test_marker_a_is_exactly_the_approved_design():
    assert M.MARKER_A == {
        "visor": ((0.0, -0.085, 1.67), (0.13, 0.05, 0.035), "marker"),
        "nose": ((0.0, -0.115, 1.625), (0.035, 0.05, 0.04), "body"),
    }
    assert M.MARKER_BONE == "head"
    assert M.MATERIALS["marker"] == ("MAT-mannequin_marker", (0.03, 0.03, 0.035))
    assert M.MATERIALS["ochre_marker"] == ("MAT-mannequin_ochre_marker", (0.03, 0.03, 0.035))
    assert M.MARKER_ROUGHNESS == 0.35


def test_marker_a_matches_the_m11_experiment():
    c = m11_constants()
    (vc, vd, _), (nc, nd, _) = M.MARKER_A["visor"], M.MARKER_A["nose"]
    assert c["D3_VISOR"] == (vc, vd)
    assert c["D3_NOSE"] == (nc, nd)
    assert tuple(c["MARKER_RGB"]) == M.MATERIALS["marker"][1]
    assert c["MARKER_ROUGHNESS"] == M.MARKER_ROUGHNESS


def test_only_the_marker_materials_change_roughness():
    rough = {k: M.MATERIAL_ROUGHNESS.get(k, M.ROUGHNESS) for k in M.MATERIALS}
    assert M.ROUGHNESS == 0.6
    assert {k for k, v in rough.items() if v != 0.6} == {"marker", "ochre_marker"}
    assert rough["marker"] == rough["ochre_marker"] == 0.35


@pytest.mark.parametrize("part", ["visor", "nose"])
def test_marker_parts_sit_in_front_of_the_head_on_the_head_bone(part):
    centre, dims, _ = M.MARKER_A[part]
    _, head, tail, _ = M.BONES["head"]
    ball = [(head[i] + tail[i]) / 2 for i in range(3)]                 # head ball centre
    radius = M.PARTS["head"][1][0]
    assert centre[0] == 0.0, "centred left-right"
    assert head[2] <= centre[2] - dims[2] / 2 and centre[2] + dims[2] / 2 <= tail[2], "within the head bone's height"
    assert centre[1] < 0, "on the face side (-Y)"
    front = centre[1] - dims[1] / 2
    dz = centre[2] - ball[2]
    surface = -math.sqrt(radius ** 2 - dz ** 2)                         # head surface ahead at that height
    assert front < surface, "protrudes in front of the head ball"
    assert centre[1] + dims[1] / 2 > surface, "attached: the back of the box is inside the head"


def test_visor_is_above_the_nose_and_the_nose_reaches_further_forward():
    (vc, vd, _), (nc, nd, _) = M.MARKER_A["visor"], M.MARKER_A["nose"]
    assert vc[2] - vd[2] / 2 > nc[2] - nd[2] / 2 and vc[2] > nc[2]
    assert nc[1] - nd[1] / 2 < vc[1] - vd[1] / 2


def test_marked_sets_use_their_own_names_and_the_same_rig():
    names = lambda s: {s["collection"], s["armature"], s["body"]}
    sets = [{"collection": M.CHARACTER_COLLECTION, "armature": M.ARMATURE, "body": M.BODY},
            M.OCHRE, M.MARKED, M.OCHRE_MARKED]
    all_names = [n for s in sets for n in names(s)]
    assert len(all_names) == len(set(all_names)), "every character set has distinct names"
    assert M.MARKED["materials"] == ("body", "accent", "marker")
    assert M.OCHRE_MARKED["materials"] == ("ochre_body", "ochre_accent", "ochre_marker")
    assert [M.MATERIAL_SLOT[k] for k in ("body", "accent", "marker")] == [0, 1, 2]
    assert M.M11_OUTPUTS == (Path("characters/mannequin_marked.blend"),
                             Path("characters/mannequin_ochre_marked.blend"))
    assert not set(M.M11_OUTPUTS) & set(M.OUTPUTS + M.M7_OUTPUTS), "never overwrites m6/m7 files"
    assert M.RIG_TYPE == "afs_mannequin_v1"


def test_parse_args_accepts_m11_and_keeps_the_m6_default():
    assert M.parse_args(["--out-root", "x"]).set == "m6"
    assert M.parse_args(["--out-root", "x", "--set", "m11"]).set == "m11"
