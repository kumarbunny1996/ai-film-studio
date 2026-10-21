"""Milestone 11: the marked characters (mannequin.py --set m11), authored headless in Blender.

Two authoring runs into temporary folders; checked through inspect_asset.py (structure and
fingerprints, the project's determinism criterion) and a small read-only probe for what the
inspector does not report (material roughness and the marker's vertices). The unmarked m6/m7
outputs are pinned by tests/test_mannequin_assets.py and tests/test_mannequin_gestures_assets.py.
"""
import importlib.util
import json
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

GOLDEN_BLENDER = "5.2.2 LTS"
GOLDEN = {
    "characters/mannequin_marked.blend": "1fbd70515544675616d7db643f3702e832c21170f1f22a926fd11a7d8ce1cf94",
    "characters/mannequin_ochre_marked.blend": "061d0b72c250afb930d597d6c2350d4ce487abc3538fbb04d9da5344b2996867",
}
KEYS = [p.as_posix() for p in M.M11_OUTPUTS]
SETS = {KEYS[0]: M.MARKED, KEYS[1]: M.OCHRE_MARKED}
UNMARKED = {KEYS[0]: ("characters/mannequin.blend", M.BODY, M.ARMATURE),
            KEYS[1]: ("characters/mannequin_ochre.blend", M.OCHRE["body"], M.OCHRE["armature"])}
EVAL_FRAMES = [1, 9, 17, 25, 33]

# Read-only probe: roughness of every material, and every vertex with its groups and the
# material indices of its faces (rest positions, armature space).
PROBE = r"""
import bpy, json, sys
out, body = sys.argv[sys.argv.index("--") + 1:]
mats = {}
for m in bpy.data.materials:
    b = next((n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled"), None)
    mats[m.name] = round(b.inputs["Roughness"].default_value, 6) if b else None
ob = bpy.data.objects[body]
me = ob.data
names = {g.index: g.name for g in ob.vertex_groups}
face_mats = {v.index: set() for v in me.vertices}
for p in me.polygons:
    for i in p.vertices:
        face_mats[i].add(p.material_index)
verts = [{"co": [round(c, 6) for c in v.co], "groups": sorted(names[g.group] for g in v.groups),
          "mats": sorted(face_mats[v.index])} for v in me.vertices]
json.dump({"roughness": mats, "verts": verts}, open(out, "w"))
"""


def run(args, timeout=300):
    proc = subprocess.run([config.BLENDER_BIN, "-b", "--factory-startup", "--python-exit-code", "1", *args],
                          capture_output=True, text=True, errors="replace", timeout=timeout)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    return proc


def inspect(blend: Path, out: Path, *extra: str) -> dict:
    run(["-P", str(INSPECT), "--", "--blend", str(blend), "--out", str(out), *extra])
    return json.loads(out.read_text())


def probe(blend: Path, out: Path, body: str) -> dict:
    run([str(blend), "--python-expr", PROBE, "--", str(out), body])
    return json.loads(out.read_text())


def authored(root: Path, work: Path) -> dict:
    run(["-P", str(AUTHOR), "--", "--out-root", str(root), "--set", "m11"])
    return {k: inspect(root / k, work / f"{Path(k).stem}.json") for k in KEYS}


@pytest.fixture(scope="module")
def run_a(tmp_path_factory):
    base = tmp_path_factory.mktemp("marked_a")
    return base / "assets", authored(base / "assets", base), base


@pytest.fixture(scope="module")
def run_b(tmp_path_factory):
    base = tmp_path_factory.mktemp("marked_b")
    return base / "assets", authored(base / "assets", base), base


@pytest.fixture(scope="module")
def probes(run_a):
    root, _, base = run_a
    return {k: probe(root / k, base / f"{Path(k).stem}_probe.json", SETS[k]["body"]) for k in KEYS}


def box_corners(centre, dims):
    return {tuple(round(centre[i] + s[i] * dims[i] / 2, 6) for i in range(3))
            for s in [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]}


# ---------------------------------------------------------------------------
# Files and determinism
# ---------------------------------------------------------------------------
def test_writes_exactly_the_two_marked_files(run_a):
    root = run_a[0]
    assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()) == sorted(KEYS)


def test_refuses_to_overwrite_without_force(run_a):
    proc = subprocess.run([config.BLENDER_BIN, "-b", "--factory-startup", "--python-exit-code", "1",
                           "-P", str(AUTHOR), "--", "--out-root", str(run_a[0]), "--set", "m11"],
                          capture_output=True, text=True, errors="replace", timeout=300)
    assert proc.returncode == 2 and "REFUSED" in proc.stderr


def test_two_authoring_runs_have_identical_structural_fingerprints(run_a, run_b):
    for k in KEYS:
        assert run_a[1][k]["fingerprint"] == run_b[1][k]["fingerprint"], k


def test_fingerprints_match_the_pinned_golden_values(run_a):
    rep = run_a[1]
    if rep[KEYS[0]]["blender_version"] != GOLDEN_BLENDER:
        pytest.skip(f"golden fingerprints were pinned with Blender {GOLDEN_BLENDER}")
    assert {k: rep[k]["fingerprint"] for k in KEYS} == GOLDEN


@pytest.mark.parametrize("key", KEYS)
def test_file_holds_one_marked_character(run_a, key):
    rep, spec = run_a[1][key], SETS[key]
    assert rep["collections"] == {spec["collection"]: sorted([spec["armature"], spec["body"]])}
    assert sorted(rep["materials"]) == sorted(M.MATERIALS[m][0] for m in spec["materials"])
    assert rep["actions"] == {} if isinstance(rep["actions"], dict) else rep["actions"] == []


# ---------------------------------------------------------------------------
# Mesh, skinning, materials and the marker
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("key", KEYS)
def test_mesh_limits_and_material_slots(run_a, key):
    mesh = run_a[1][key]["meshes"][SETS[key]["body"]]
    (x0, y0, z0), (x1, y1, z1) = mesh["bounds"]
    assert mesh["triangles"] < 3000
    assert z0 == pytest.approx(0.0, abs=2e-3) and z1 == pytest.approx(1.75, abs=1e-6)
    assert y0 < -0.15 and y1 <= 0.1, "toes reach forward (-Y), nothing sticks out behind"
    assert x0 == pytest.approx(-x1, abs=1e-6)
    assert mesh["materials"] == [M.MATERIALS[m][0] for m in SETS[key]["materials"]]
    assert mesh["material_indices"] == [0, 1, 2]


@pytest.mark.parametrize("key", KEYS)
def test_rigidly_skinned_like_the_unmarked_character(run_a, key):
    body = run_a[1][key]["objects"][SETS[key]["body"]]
    assert (body["parent"], body["parent_type"]) == (SETS[key]["armature"], "OBJECT")
    assert body["modifiers"] == [{"type": "ARMATURE", "object": SETS[key]["armature"]}]
    assert set(body["vertex_groups"]) == set(M.BONES)
    assert all(g["weights"] == [1.0] for g in body["vertex_groups"].values())
    assert body["groups_per_vertex"] == [1]


@pytest.mark.parametrize("key", KEYS)
def test_marker_adds_exactly_two_boxes_to_the_head_group(run_a, key):
    committed = REPO / "assets" / UNMARKED[key][0]
    base = run_a[2]
    plain = inspect(committed, base / f"plain_{Path(key).stem}.json")
    unmarked = plain["objects"][UNMARKED[key][1]]["vertex_groups"]
    marked = run_a[1][key]["objects"][SETS[key]["body"]]["vertex_groups"]
    for bone in M.BONES:
        extra = 16 if bone == "head" else 0
        assert marked[bone]["vertices"] == unmarked[bone]["vertices"] + extra, bone
    t_plain = plain["meshes"][UNMARKED[key][1]]["triangles"]
    assert run_a[1][key]["meshes"][SETS[key]["body"]]["triangles"] == t_plain + 24


@pytest.mark.parametrize("key", KEYS)
def test_marker_roughness_and_unchanged_body_roughness(probes, key):
    rough = probes[key]["roughness"]
    body, accent, marker = (M.MATERIALS[m][0] for m in SETS[key]["materials"])
    assert rough[marker] == 0.35
    assert rough[body] == rough[accent] == 0.6


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("part", list(M.MARKER_A))
def test_marker_boxes_are_exactly_marker_a_on_the_head(probes, key, part):
    centre, dims, role = M.MARKER_A[part]
    verts = {tuple(v["co"]): v for v in probes[key]["verts"]}
    corners = box_corners(centre, dims)
    assert corners <= set(verts), f"{part}: every corner of the approved box exists"
    for c in corners:
        assert verts[c]["groups"] == ["head"], f"{part}: only on the head bone"
        assert verts[c]["mats"] == [M.MATERIAL_SLOT[role]], f"{part}: {role} material"


@pytest.mark.parametrize("key", KEYS)
def test_only_the_visor_uses_the_marker_material(probes, key):
    centre, dims, _ = M.MARKER_A["visor"]
    inside = box_corners(centre, dims)
    marker_verts = {tuple(v["co"]) for v in probes[key]["verts"] if 2 in v["mats"]}
    assert marker_verts == inside


# ---------------------------------------------------------------------------
# Rig and action compatibility
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("key", KEYS)
def test_rig_is_identical_to_the_unmarked_rig(run_a, key):
    bones = run_a[1][key]["armatures"][SETS[key]["armature"]]["bones"]
    assert set(bones) == set(M.BONES)
    for name, (parent, head, tail, connected) in M.BONES.items():
        b = bones[name]
        assert (b["parent"], b["connected"], b["deform"]) == (parent, connected, True), name
        assert b["head"] == pytest.approx(head, abs=1e-6) and b["tail"] == pytest.approx(tail, abs=1e-6)


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("actions", ["actions/mannequin_actions.blend", "actions/mannequin_gestures.blend"])
def test_existing_actions_pose_the_marked_rig_like_the_unmarked_rig(run_a, key, actions):
    root, _, base = run_a
    frames = ",".join(map(str, EVAL_FRAMES))
    stem = f"{Path(key).stem}_{Path(actions).stem}"
    marked = inspect(root / key, base / f"eval_{stem}.json", "--evaluate-actions", str(REPO / "assets" / actions),
                     "--armature", SETS[key]["armature"], "--frames", frames, "--repeat", "1")["evaluated"]
    plain = inspect(REPO / "assets" / UNMARKED[key][0], base / f"eval_plain_{stem}.json", "--evaluate-actions",
                    str(REPO / "assets" / actions), "--armature", UNMARKED[key][2], "--frames", frames,
                    "--repeat", "1")["evaluated"]
    assert set(marked) == set(plain) and marked
    for name in plain:
        assert marked[name]["frames"] == plain[name]["frames"], name
