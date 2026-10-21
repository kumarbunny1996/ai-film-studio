"""
marker_test.py - M11 Gate 2 head-marker experiment (scratch tool, not part of the repo).

    blender -b --factory-startup -t 4 --python-exit-code 1 -P marker_test.py -- \
        --repo <repo> --out storage/projects/m11_readable_attention/marker_test_rev1 \
        --private <dir> (--preflight-only | --render)

Reads the existing mannequin assets (appended into memory, never saved) and builds the head
markers in memory only. Nothing under assets/ is written and no .blend is saved.

Phase A storage output (nothing that names an angle):
    --preflight-only  <out>/preflight/preflight_summary.json   pass/fail counts, only on a pass
    --render          <out>/stills/{320,640}/Sxx.png           opaque names
Private output (--private, outside the blind-review outputs):
    assignments.json      secret seed, body turns, pairings, opaque ids
    preflight_full.json   every measured value
    masks/, masks_raw/, diagnostics.json, experiment.json   (--render)
Console output carries counts and errors only, never target angles.

rev4 (--design-set rev4): D3 refinement screening. Variants A-D, 320x180 only, no D0, K ids.
    ... -- --design-set rev4 --repo <repo> \
        --out storage/projects/m11_readable_attention/marker_test_rev4 --private <new dir> --preflight-only \
        --reproduce-rev3 storage/projects/m11_readable_attention/marker_test_rev3
    ... -- --design-set rev4 ... --render --c-width <width reported by the preflight> \
        --reproduce-rev3 storage/projects/m11_readable_attention/marker_test_rev3
The preflight measures the rear cue (P12) and picks C's width by the pre-registered rule (0.10 if
the medium ratio is >= 0.50 for both colours, else 0.11 if >= 0.40, else stop), prints the ratios
and records them; --render refuses unless --c-width repeats that decision. Before any rev4 still,
two rev3 D3 stills are re-rendered as A into the private folder and must match rev3 exactly (P11).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import secrets
import sys
import time
from pathlib import Path

import bmesh
import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Matrix, Vector

ANGLES = (-140, -90, -40, 0, 40, 90, 140)
DESIGNS = ("D0", "D1", "D2", "D3")
CHARS = {"grey": ("mannequin", -0.45), "ochre": ("mannequin_ochre", 0.45)}
CAMS = {
    "med": {"lens": 40.0, "loc": (0.0, -3.0, 1.45), "rot": (90.0, 0.0, 0.0), "dof": True,
            "fstop": 4.0, "focus": 3.03, "head_px": 23.0},
    "wide": {"lens": 32.0, "loc": (0.0, -8.3, 1.7), "rot": (85.2, 0.0, 0.0), "dof": False,
             "head_px": 7.0},
}
# held look values (Y rotation, degrees); + = to the character's left, - = right
TURN = {"spine": 6.0, "chest": 10.0, "neck": 9.0, "head": 15.0}
LEG_BONES = ("hips", "thigh.L", "shin.L", "foot.L", "thigh.R", "shin.R", "foot.R")
MARKER_RGB, MARKER_ROUGHNESS = (0.03, 0.03, 0.035), 0.35
RESOLUTIONS = ((320, 180), (640, 360))
TOL = {"axis": 0.1, "turn": 0.1, "tilt": 0.1, "theta": 0.5, "h": 0.5, "pose": 1e-6,
       "margin": 0.05, "px_rel": 0.15, "ahead": 0.07, "lateral": 0.01, "vertical": 0.005}
# expected marker centre in the rig's rest frame (metres, facing -Y): forward, vertical vs head
MARKER_EXPECT = {("D1", "marker"): (0.085, 0.02), ("D3", "marker"): (0.085, 0.02),
                 ("D3", "nose"): (0.115, -0.025), ("D2", "marker"): (None, 0.0)}
HEAD_CENTRE_REST = (0.0, 0.0, 1.65)
ID_PREFIX = "S"

# rev4 (approved 2026-10-21): A = D3 as in rev3, B = A with a matte marker, C = narrower visor,
# D = C's visor with B's material. Every variant has its own (identical) nose.
DESIGN_SET = "rev3"
DESIGN_SETS = {
    "rev3": {"designs": ("D0", "D1", "D2", "D3"), "resolutions": ((320, 180), (640, 360)), "id_prefix": "S"},
    "rev4": {"designs": ("A", "B", "C", "D"), "resolutions": ((320, 180),), "id_prefix": "K"},
}
MATTE_ROUGHNESS = 0.85
D3_VISOR = ((0, -0.085, 1.67), (0.13, 0.05, 0.035))      # centre, (width, depth, height), rest frame
D3_NOSE = ((0, -0.115, 1.625), (0.035, 0.05, 0.04))
C_WIDTH, C_FALLBACK_WIDTH = 0.10, 0.11
# Width rule (pre-registered 2026-10-21), on the medium-camera outside-head ratio C/A for every
# colour: 0.10 only if >= C_SELECT_RATIO; otherwise 0.11, which must still be >= REAR_CUE_FLOOR;
# otherwise stop before rendering. REAR_CUE_FLOOR is also the post-render mask floor.
C_SELECT_RATIO = 0.50
REAR_CUE_FLOOR = 0.40
REAR_THETAS, REAR_RES = (-140, 140), (640, 360)
REV4_EXPECT = {"marker": (0.085, 0.02), "nose": (0.115, -0.025)}
REV3_RECORD = {"blender_version": "5.2.2 LTS", "marker_rgb": (0.03, 0.03, 0.035), "marker_roughness": 0.35}
# Beauty isolation for A/B and C/D (same geometry, so identical shadows, occlusion and outlines).
# A marker-material change can reach other pixels only through (i) the pixel reconstruction
# filter, whose radius (scene.render.filter_size, checked in P10 to be <= DILATE_PX) is covered
# by a square DILATE_PX band around the visible marker, and (ii) light reflected off the marker,
# whose albedo is the same 0.03 in both materials. Renders are deterministic (rev2 matched rev1
# byte for byte), so unchanged inputs give unchanged bytes. Outside the band at most 2 of 255
# code values may change (float rounding and dither flips where a near-zero indirect term moves);
# anything more is a real difference. Fixed before any rev4 render; never raised after a failure.
BEAUTY_TOL, DILATE_PX = 2.5 / 255, 2
PROTECTED = ("marker_test_rev1", "marker_test_rev2", "marker_test_rev3", "marker_test_rev4_aborted1")
# rev4 head_present: minimum head-mask area in 320x180 pixels, chosen by the group's camera id
# (approved 2026-10-21): medium 100, wide 19 (half the planned 7 px head's ~38 px). rev3 keeps its
# original "> 100", which it only ever applied to the first (medium) group.
HEAD_MIN_AREA = {"med": 100, "wide": 19}


def use_design_set(name: str) -> None:
    global DESIGN_SET, DESIGNS, RESOLUTIONS, ID_PREFIX
    s = DESIGN_SETS[name]
    DESIGN_SET, DESIGNS, RESOLUTIONS, ID_PREFIX = name, s["designs"], s["resolutions"], s["id_prefix"]


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser(prog="marker_test.py")
    p.add_argument("--repo", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--private", required=True, type=Path)
    p.add_argument("--assignments", type=Path,
                   help="existing assignments.json, read only (rev2 reuses rev1's)")
    p.add_argument("--compare-with", type=Path, action="append", default=[],
                   help="earlier run's output folder (repeatable); the first group's beauty PNGs must "
                        "match it: same decoded pixels, same IHDR, same chunks except tEXt Date/RenderTime")
    p.add_argument("--design-set", choices=sorted(DESIGN_SETS), default="rev3")
    p.add_argument("--c-width", type=float,
                   help="rev4 --render: must repeat the C width the preflight decided")
    p.add_argument("--reproduce-rev3", type=Path,
                   help="rev4 --render: rev3 output folder; two D3 stills are re-rendered as A and must match")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--render", action="store_true")
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Secret assignments (same for every design: comparability across markers)
# ---------------------------------------------------------------------------
def make_assignments(seed: int) -> dict:
    rng = random.Random(seed)
    turns = {}
    for cam in CAMS:
        turns[cam] = {}
        for col in CHARS:
            plus = set(rng.sample(ANGLES, rng.choice((3, 4))))
            turns[cam][col] = {str(a): (40 if a in plus else -40) for a in ANGLES}
    pairing = {}
    for cam in CAMS:
        while True:
            perm = list(range(len(ANGLES)))
            rng.shuffle(perm)
            if all(perm[i] != i for i in range(len(perm))):
                break
        pairing[cam] = perm
    stills = [{"design": d, "cam": cam, "slot": i, "grey": ANGLES[i],
               "ochre": ANGLES[pairing[cam][i]]}
              for d in DESIGNS for cam in CAMS for i in range(len(ANGLES))]
    order = list(range(len(stills)))
    rng.shuffle(order)
    for k, idx in enumerate(order):
        stills[idx]["id"] = f"{ID_PREFIX}{k + 1:02d}"
    return {"seed": seed, "turns": turns, "pairing": pairing, "stills": stills}


def load_assignments(private: Path, create: bool, given: Path | None = None) -> dict:
    if given is not None:
        return json.loads(given.read_text())             # read only, never written
    path = private / "assignments.json"
    if path.exists():
        return json.loads(path.read_text())
    if not create:
        raise SystemExit("[marker_test] REFUSED: no assignments; run --preflight-only first")
    data = make_assignments(secrets.randbits(63))
    private.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1))
    return data


def check_assignments(a: dict) -> list[str]:
    """Balance rules from the approved plan (no angles are printed)."""
    errs = []
    for cam in CAMS:
        perm = a["pairing"][cam]
        if sorted(perm) != list(range(7)) or any(perm[i] == i for i in range(7)):
            errs.append(f"pairing {cam} is not a permutation without fixed points")
        for col in CHARS:
            n_plus = sum(1 for v in a["turns"][cam][col].values() if v == 40)
            if n_plus not in (3, 4):
                errs.append(f"turns {cam}/{col} unbalanced")
    for d in DESIGNS:
        for cam in CAMS:
            group = [s for s in a["stills"] if s["design"] == d and s["cam"] == cam]
            for col in CHARS:
                if sorted(s[col] for s in group) != sorted(ANGLES):
                    errs.append(f"{d}/{cam}/{col} does not see all seven angles once")
            if any(s["grey"] == s["ochre"] for s in group):
                errs.append(f"{d}/{cam} has a still with equal angles")
    ids = [s["id"] for s in a["stills"]]
    if len(set(ids)) != len(DESIGNS) * len(CAMS) * len(ANGLES):
        errs.append("opaque ids are not unique")
    if any(not i.startswith(ID_PREFIX) for i in ids):
        errs.append(f"opaque ids do not all use the {ID_PREFIX} prefix")
    return errs


# ---------------------------------------------------------------------------
# Scene
# ---------------------------------------------------------------------------
def principled(name: str, rgb, roughness: float):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*rgb, 1.0)
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    return mat


def emission(name: str, rgb):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (*rgb, 1.0)
    em.inputs["Strength"].default_value = 1.0
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    return mat


def add_turn_track(arm, side: str):
    """In-memory head-turn action (the look's held Y values) on its own NLA track above the
    idle, REPLACE, as build_scene layers gestures. Muted until a still needs it."""
    sign = 1.0 if side == "L" else -1.0
    ad = arm.animation_data
    for bone, deg in TURN.items():
        pb = arm.pose.bones[bone]
        pb.rotation_euler[1] = math.radians(sign * deg)
        for f in (1, 2):
            pb.keyframe_insert("rotation_euler", index=1, frame=f, group=bone)
    act = ad.action
    act.name = f"TMP-turn{side}-{arm.name}"
    slot = getattr(ad, "action_slot", None)
    ad.action = None
    track = ad.nla_tracks.new()
    track.name = f"turn_{side}"
    strip = track.strips.new(f"turn_{side}", 1, act)
    if hasattr(strip, "action_slot") and strip.action_slot is None:
        slots = getattr(act, "slots", None)
        if slots and len(slots):
            strip.action_slot = slot if slot is not None else slots[0]
    strip.use_auto_blend = False
    strip.blend_in = strip.blend_out = 0.0
    strip.extrapolation = "HOLD_FORWARD"
    strip.blend_type = "REPLACE"
    track.mute = True
    for bone in TURN:
        arm.pose.bones[bone].rotation_euler[1] = 0.0
    return track


def build_markers(coll, arm, body, marker_mat, matte_mat=None) -> dict:
    """Marker meshes on the head bone. Geometry is given in the rig's rest frame and mapped
    into the head bone's tail space (bone parenting attaches at the tail)."""
    bone = arm.data.bones["head"]
    to_local = (bone.matrix_local @ Matrix.Translation((0.0, bone.length, 0.0))).inverted()
    body_mat = body.data.materials[0]

    def obj(name, bm, mat, role):
        mesh = bpy.data.meshes.new(name)
        bm.to_mesh(mesh)
        bm.free()
        mesh.materials.append(mat)
        o = bpy.data.objects.new(name, mesh)
        coll.objects.link(o)
        o.parent = arm
        o.parent_type = "BONE"
        o.parent_bone = "head"
        o.matrix_parent_inverse.identity()
        o.matrix_basis.identity()
        o["afs_role"] = role
        return o

    def box(centre, dims):
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.transform(bm, matrix=to_local @ Matrix.Translation(centre)
                            @ Matrix.Diagonal((*dims, 1.0)), verts=bm.verts)
        return bm

    def sphere_part(cap: bool):
        bm = bmesh.new()
        bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=16, radius=0.10)
        fwd = Vector((0.0, -1.0, 0.0))
        drop = [f for f in bm.faces
                if (f.calc_center_median().normalized().angle(fwd) <= math.radians(50)) != cap]
        bmesh.ops.delete(bm, geom=drop, context="FACES")
        bmesh.ops.transform(bm, matrix=to_local @ Matrix.Translation(HEAD_CENTRE_REST),
                            verts=bm.verts)
        return bm

    tag = arm.name
    if DESIGN_SET == "rev4":
        # C and D are built at both pre-registered widths; set_design shows only the decided one
        (vc, (vw, vd, vh)), (nc, nd) = D3_VISOR, D3_NOSE
        out = {}
        for d in DESIGNS:
            mat = marker_mat if d in ("A", "C") else matte_mat
            for key, w in ([(d, vw)] if d in ("A", "B") else
                           [(f"{d}@{x:.2f}", x) for x in (C_WIDTH, C_FALLBACK_WIDTH)]):
                out[key] = [obj(f"MK-{key}-visor-{tag}", box(vc, (w, vd, vh)), mat, "marker"),
                            obj(f"MK-{key}-nose-{tag}", box(nc, nd), body_mat, "nose")]
        return out
    return {
        "D0": [],
        "D1": [obj(f"MK-D1-visor-{tag}", box((0, -0.085, 1.67), (0.15, 0.05, 0.045)),
                   marker_mat, "marker")],
        "D2": [obj(f"MK-D2-cap-{tag}", sphere_part(True), marker_mat, "marker"),
               obj(f"MK-D2-head-{tag}", sphere_part(False), body_mat, "head")],
        "D3": [obj(f"MK-D3-visor-{tag}", box((0, -0.085, 1.67), (0.13, 0.05, 0.035)),
                   marker_mat, "marker"),
               obj(f"MK-D3-nose-{tag}", box((0, -0.115, 1.625), (0.035, 0.05, 0.04)),
                   body_mat, "nose")],
    }


def head_slot(body) -> list[int]:
    """Give the head ball its own material slot, pointing at the same body material (the
    beauty render is unchanged), so the mask pass can colour the head alone."""
    mesh = body.data
    gi = body.vertex_groups["head"].index
    head_verts = {v.index for v in mesh.vertices
                  if any(g.group == gi and g.weight > 0.5 for g in v.groups)}
    mesh.materials.append(mesh.materials[0])
    polys = []
    for p in mesh.polygons:
        if all(v in head_verts for v in p.vertices):
            p.material_index = 2
            polys.append(p.index)
    return sorted(head_verts), polys


def build(repo: Path, tmp: Path) -> dict:
    sys.path.insert(0, str(repo / "blender" / "scripts"))
    import build_scene as bs

    bpy.ops.wm.read_factory_settings(use_empty=True)
    factory_view = bpy.context.scene.view_settings.view_transform
    spec = json.loads((repo / "schemas" / "examples" / "m10_travellers_question.json").read_text())
    manifest = json.loads((repo / "assets" / "manifest.json").read_text())
    lib = bs.Library((repo / "assets").resolve(), manifest)
    scene = bpy.context.scene
    coll = bs.shot_collection(scene)
    report = bs.Report("m11_marker_test")
    render = dict(spec["render"], resolution=[320, 180], frame_start=1, frame_end=1)
    bs.setup_render(scene, render, "m11_marker_test", tmp)
    scene.render.image_settings.color_depth = "8"
    bs.setup_world(scene, lib, spec["environment"])
    bs.setup_lighting(scene, coll, spec.get("lighting", {}), report)
    ground_spec = next(p for p in spec["primitives"] if p["name"] == "ground")
    ground = bs.build_primitives([ground_spec], coll, report)["ground"]
    marker_mat = principled("MAT-m11-marker", MARKER_RGB, MARKER_ROUGHNESS)
    matte_mat = principled("MAT-m11-marker-matte", MARKER_RGB, MATTE_ROUGHNESS) \
        if DESIGN_SET == "rev4" else None

    chars = {}
    for col, (asset_id, x) in CHARS.items():
        entry = lib.asset(asset_id)
        root, c = bs.instance_asset(lib, col, asset_id, coll)
        root.location = (x, 0.0, 0.0)
        arm = bs.find_armature(c, entry.get("armature"))
        bs.place_actions(lib, arm, {"name": col, "actions": [
            {"action_id": "mannequin_idle", "start_frame": 1, "end_frame": 49}]}, report)
        body = next(o for o in c.all_objects if o.type == "MESH" and o.parent == arm)
        head_verts, head_polys = head_slot(body)
        mask = body.modifiers.new("HEADMASK", "MASK")
        mask.vertex_group = "head"
        mask.invert_vertex_group = True
        mask.show_render = mask.show_viewport = False
        tracks = {s: add_turn_track(arm, s) for s in ("R", "L")}
        chars[col] = {"root": root, "arm": arm, "body": body, "tracks": tracks, "x": x,
                      "head_verts": head_verts, "head_polys": head_polys, "mask": mask,
                      "markers": build_markers(coll, arm, body, marker_mat, matte_mat)}

    cams = {}
    for name, cs in CAMS.items():
        data = bpy.data.cameras.new(f"CAM-{name}")
        data.lens, data.sensor_width = cs["lens"], 36
        data.dof.use_dof = cs["dof"]
        if cs["dof"]:
            data.dof.focus_distance, data.dof.aperture_fstop = cs["focus"], cs["fstop"]
        cam = bpy.data.objects.new(f"CAM-{name}", data)
        coll.objects.link(cam)
        cam.location = cs["loc"]
        cam.rotation_euler = [math.radians(d) for d in cs["rot"]]
        cams[name] = cam
    scene.camera = cams["med"]
    scene.frame_set(1)
    return {"bs": bs, "scene": scene, "spec": spec, "ground": ground, "chars": chars,
            "cams": cams, "marker_mat": marker_mat, "matte_mat": matte_mat, "c_width": None,
            "factory_view": factory_view, "warnings": report.data["warnings"]}


# ---------------------------------------------------------------------------
# Measurement helpers
# ---------------------------------------------------------------------------
AXES = {"+X": (0, 1), "-X": (0, -1), "+Y": (1, 1), "-Y": (1, -1), "+Z": (2, 1), "-Z": (2, -1)}


def eval_arm(arm):
    return arm.evaluated_get(bpy.context.evaluated_depsgraph_get())


def bone_world(arm, bone: str) -> Matrix:
    return eval_arm(arm).matrix_world @ eval_arm(arm).pose.bones[bone].matrix


def axis_vec(m: Matrix, axis: str) -> Vector:
    col, sign = AXES[axis]
    return (m.to_3x3().col[col] * sign).normalized()


def yaw(v: Vector) -> float:
    return math.degrees(math.atan2(v.y, v.x))


def wrap(a: float) -> float:
    return (a + 180.0) % 360.0 - 180.0


def head_centre(arm) -> Vector:
    pb = eval_arm(arm).pose.bones["head"]
    return eval_arm(arm).matrix_world @ ((pb.head + pb.tail) / 2)


def eval_points(obj, indices=None) -> list[Vector]:
    oe = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = oe.to_mesh()
    vs = me.vertices
    pts = [oe.matrix_world @ vs[i].co for i in (indices if indices is not None else range(len(vs)))]
    oe.to_mesh_clear()
    return pts


def eval_polys(obj) -> list[list[Vector]]:
    oe = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = oe.to_mesh()
    out = [[oe.matrix_world @ me.vertices[i].co for i in p.vertices] for p in me.polygons]
    oe.to_mesh_clear()
    return out


def raster(scene, cam, polys, w: int, h: int) -> set[int]:
    """Pixel centres covered by the projected polygons (fan triangulation)."""
    cover = set()
    for poly in polys:
        pts = [world_to_camera_view(scene, cam, p) for p in poly]
        if any(p.z <= 0 for p in pts):
            continue
        pts = [(p.x * w, p.y * h) for p in pts]
        for k in range(1, len(pts) - 1):
            (ax, ay), (bx, by), (cx, cy) = pts[0], pts[k], pts[k + 1]
            den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
            if abs(den) < 1e-12:
                continue
            for py in range(max(0, int(min(ay, by, cy))), min(h, int(max(ay, by, cy)) + 1)):
                for px in range(max(0, int(min(ax, bx, cx))), min(w, int(max(ax, bx, cx)) + 1)):
                    x, y = px + 0.5, py + 0.5
                    l1 = ((by - cy) * (x - cx) + (cx - bx) * (y - cy)) / den
                    l2 = ((cy - ay) * (x - cx) + (ax - cx) * (y - cy)) / den
                    if l1 >= 0 and l2 >= 0 and l1 + l2 <= 1:
                        cover.add(py * w + px)
    return cover


def visible_pixels(ctx, cam, target, pixels: set[int], w: int, h: int) -> int:
    """How many of `pixels` (pixel centres, row 0 at the bottom as in raster) have a camera ray
    whose first hit is `target`. Every other marker object is disabled in the viewport for the
    cast and restored afterwards; hide_render is not touched."""
    scene = ctx["scene"]
    markers = [o for ch in ctx["chars"].values() for objs in ch["markers"].values() for o in objs]
    saved = {o.name: o.hide_viewport for o in markers}
    try:
        for o in markers:
            o.hide_viewport = o is not target
        bpy.context.view_layer.update()
        dg = bpy.context.evaluated_depsgraph_get()
        tr, br, bl, tl = [cam.matrix_world @ v for v in cam.data.view_frame(scene=scene)]
        origin = cam.matrix_world.translation.copy()
        n = 0
        for p in pixels:
            py, px = divmod(p, w)
            point = bl + (br - bl) * ((px + 0.5) / w) + (tl - bl) * ((py + 0.5) / h)
            hit, _, _, _, obj, _ = scene.ray_cast(dg, origin, (point - origin).normalized())
            n += bool(hit and obj is not None and obj.name == target.name)
        return n
    finally:
        for o in markers:
            o.hide_viewport = saved[o.name]
        bpy.context.view_layer.update()


def pose_still(ctx, a: dict, cam: str, slot: int) -> dict:
    """Root rotations and turn tracks for one (camera, slot); returns the targets."""
    scene, chars = ctx["scene"], ctx["chars"]
    cloc = Vector(CAMS[cam]["loc"])
    targets = {}
    perm = a["pairing"][cam]
    for col, ch in chars.items():
        theta = ANGLES[slot] if col == "grey" else ANGLES[perm[slot]]
        h = a["turns"][cam][col][str(theta)]
        phi_c = math.degrees(math.atan2(cloc.y - 0.0, cloc.x - ch["x"]))
        body = phi_c + theta - h
        ch["root"].rotation_euler = (0.0, 0.0, math.radians(body - 270.0))
        ch["tracks"]["R"].mute = h > 0
        ch["tracks"]["L"].mute = h < 0
        targets[col] = {"theta": theta, "h": h}
    scene.camera = ctx["cams"][cam]
    scene.frame_set(1)
    return targets


def marker_key(ctx, design: str) -> str:
    """rev4 C and D resolve to the width the preflight decided; never a default."""
    if DESIGN_SET == "rev4" and design in ("C", "D"):
        if ctx["c_width"] is None:
            raise RuntimeError("C width has not been decided by the rear-cue preflight")
        return f"{design}@{ctx['c_width']:.2f}"
    return design


def pose_angle(ctx, cam: str, theta: int, h: int) -> None:
    """Both characters at one view angle and head turn (geometry checks; no assignments)."""
    cloc = Vector(CAMS[cam]["loc"])
    for ch in ctx["chars"].values():
        phi_c = math.degrees(math.atan2(cloc.y - 0.0, cloc.x - ch["x"]))
        ch["root"].rotation_euler = (0.0, 0.0, math.radians(phi_c + theta - h - 270.0))
        ch["tracks"]["R"].mute = h > 0
        ch["tracks"]["L"].mute = h < 0
    ctx["scene"].camera = ctx["cams"][cam]
    ctx["scene"].frame_set(1)


def set_design(ctx, design: str) -> None:
    key = marker_key(ctx, design)
    for ch in ctx["chars"].values():
        for d, objs in ch["markers"].items():
            for o in objs:
                o.hide_render = d != key
        ch["mask"].show_render = ch["mask"].show_viewport = design == "D2"


# ---------------------------------------------------------------------------
# Mask mode (flat emission colours, depth-tested; raw = head and body hidden)
# ---------------------------------------------------------------------------
class MaskMode:
    def __init__(self, ctx):
        self.ctx = ctx
        self.mats = {k: emission(f"MAT-mask-{k}", rgb) for k, rgb in
                     {"black": (0, 0, 0), "red": (1, 0, 0), "green": (0, 1, 0),
                      "blue": (0, 0, 1)}.items()}
        self.saved = None

    def colour_of(self, role: str) -> str:
        return {"marker": "red", "nose": "blue", "head": "green"}[role]

    def enter(self, raw: bool = False) -> None:
        ctx, scene = self.ctx, self.ctx["scene"]
        world_bg = next(n for n in scene.world.node_tree.nodes if n.bl_idname == "ShaderNodeBackground")
        s = {"world": tuple(world_bg.inputs["Color"].default_value),
             "view": scene.view_settings.view_transform, "look": scene.view_settings.look,
             "samples": scene.eevee.taa_render_samples,
             "dither": scene.render.dither_intensity,
             "filter": scene.render.filter_size if hasattr(scene.render, "filter_size") else None,
             "ground": ctx["ground"].data.materials[0], "ground_hide": ctx["ground"].hide_render,
             "bodies": {}, "markers": {}, "hidden": {}}
        world_bg.inputs["Color"].default_value = (0, 0, 0, 1)
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.look = "None"
        scene.eevee.taa_render_samples = 1
        scene.render.dither_intensity = 0.0            # 8-bit dither puts (1,1,1) noise on black
        if s["filter"] is not None:
            scene.render.filter_size = scene.render.bl_rna.properties["filter_size"].hard_min
        ctx["ground"].data.materials[0] = self.mats["black"]
        ctx["ground"].hide_render = raw
        for col, ch in ctx["chars"].items():
            me = ch["body"].data
            s["bodies"][col] = [me.materials[i] for i in range(len(me.materials))]
            s["hidden"][ch["body"].name] = ch["body"].hide_render
            me.materials[0] = me.materials[1] = self.mats["black"]
            me.materials[2] = self.mats["green"]
            ch["body"].hide_render = raw
            for objs in ch["markers"].values():
                for o in objs:
                    s["markers"][o.name] = o.data.materials[0]
                    o.data.materials[0] = self.mats[self.colour_of(o["afs_role"])]
                    if raw and o["afs_role"] == "head":
                        s["hidden"][o.name] = o.hide_render
                        o.hide_render = True
        self.saved, self.world_bg = s, world_bg

    def exit(self) -> None:
        ctx, scene, s = self.ctx, self.ctx["scene"], self.saved
        self.world_bg.inputs["Color"].default_value = s["world"]
        scene.view_settings.view_transform, scene.view_settings.look = s["view"], s["look"]
        scene.eevee.taa_render_samples = s["samples"]
        scene.render.dither_intensity = s["dither"]
        if s["filter"] is not None:
            scene.render.filter_size = s["filter"]
        ctx["ground"].data.materials[0] = s["ground"]
        ctx["ground"].hide_render = s["ground_hide"]
        for col, ch in ctx["chars"].items():
            for i, m in enumerate(s["bodies"][col]):
                ch["body"].data.materials[i] = m
            for objs in ch["markers"].values():
                for o in objs:
                    o.data.materials[0] = s["markers"][o.name]
        for name, hidden in s["hidden"].items():
            bpy.data.objects[name].hide_render = hidden
        self.saved = None


# ---------------------------------------------------------------------------
# Preflight (no rendering)
# ---------------------------------------------------------------------------
class Checks:
    def __init__(self, n: int = 9):
        self.items: dict[str, list] = {f"P{i}": [] for i in range(1, n + 1)}

    def add(self, pid: str, ok: bool, label: str, **values) -> None:
        self.items[pid].append({"ok": bool(ok), "item": label, **values})

    def counts(self) -> dict:
        return {k: {"passed": sum(i["ok"] for i in v), "failed": sum(not i["ok"] for i in v)}
                for k, v in self.items.items()}

    def all_ok(self) -> bool:
        return all(i["ok"] for v in self.items.values() for i in v) and \
            all(len(v) for v in self.items.values())


def preflight(ctx, a: dict) -> Checks:
    scene, chars = ctx["scene"], ctx["chars"]
    ck = Checks(12 if DESIGN_SET == "rev4" else 9)

    def neutral(rot_deg: float):
        for ch in chars.values():
            ch["root"].rotation_euler = (0.0, 0.0, math.radians(rot_deg))
            ch["tracks"]["R"].mute = ch["tracks"]["L"].mute = True
        scene.frame_set(1)

    # P1: which head-bone axis is "forward" (and the same for hips)
    neutral(0.0)
    axes = {}
    for col, ch in chars.items():
        for bone in ("head", "hips"):
            m = bone_world(ch["arm"], bone)
            close = {n: math.degrees(axis_vec(m, n).angle(Vector((0, -1, 0)))) for n in AXES}
            hits = [n for n, d in close.items() if d <= TOL["axis"]]
            ck.add("P1", len(hits) == 1, f"{col}/{bone}", axis=hits, min_deg=round(min(close.values()), 4))
            if len(hits) == 1:
                axes[(col, bone)] = hits[0]
    if len(axes) != 4 or len({axes[(c, "head")] for c in chars}) != 1:
        return ck
    fwd_axis = axes[("grey", "head")]

    def fwd(arm, bone="head") -> Vector:
        return axis_vec(bone_world(arm, bone), fwd_axis)

    # P2: rotation_z 90 faces +X
    neutral(90.0)
    for col, ch in chars.items():
        d = math.degrees(fwd(ch["arm"]).angle(Vector((1, 0, 0))))
        ck.add("P2", d <= TOL["axis"], col, deg_from_plus_x=round(d, 4))

    # P3/P4: layering of the right and left turns over idle frame 1
    neutral(0.0)
    idle = {col: {b: eval_arm(ch["arm"]).pose.bones[b].matrix.copy() for b in LEG_BONES}
            for col, ch in chars.items()}
    for col, ch in chars.items():
        for side, expect in (("R", -40.0), ("L", 40.0)):
            ch["tracks"]["R"].mute, ch["tracks"]["L"].mute = side != "R", side != "L"
            scene.frame_set(1)
            rel = wrap(yaw(fwd(ch["arm"])) - yaw(fwd(ch["arm"], "hips")))
            ck.add("P3", abs(rel - expect) <= TOL["turn"], f"{col}/{side}",
                   rel_deg=round(rel, 4), expect=expect)
            ev = eval_arm(ch["arm"]).pose.bones
            dleg = max(max(abs(x - y) for rx, ry in zip(ev[b].matrix, idle[col][b])
                           for x, y in zip(rx, ry)) for b in LEG_BONES)
            up = axis_vec(bone_world(ch["arm"], "head"), "+Y")
            tilt = math.degrees(up.angle(Vector((0, 0, 1))))
            sign = 1.0 if side == "L" else -1.0
            dval = max(abs(ev[b].rotation_euler[1] - math.radians(sign * v)) for b, v in TURN.items())
            ck.add("P4", dleg <= TOL["pose"] and tilt <= TOL["tilt"] and dval <= 1e-6,
                   f"{col}/{side}", legs_max_diff=dleg, head_tilt_deg=round(tilt, 5),
                   y_readback_max_rad=dval)
            ch["tracks"]["R"].mute = ch["tracks"]["L"].mute = True

    # P5-P7 per (camera, slot); poses are identical across designs
    for cam in CAMS:
        cs, cobj = CAMS[cam], ctx["cams"][cam]
        for slot in range(len(ANGLES)):
            targets = pose_still(ctx, a, cam, slot)
            cloc = Vector(cs["loc"])
            covers = {}
            for col, ch in chars.items():
                arm, t = ch["arm"], targets[col]
                hc, f = head_centre(arm), fwd(arm)
                fh = Vector((f.x, f.y, 0)).normalized()
                vc = Vector((cloc.x - hc.x, cloc.y - hc.y, 0)).normalized()
                theta = math.degrees(math.atan2(vc.x * fh.y - vc.y * fh.x, vc.dot(fh)))
                h = wrap(yaw(f) - yaw(fwd(arm, "hips")))
                a0 = world_to_camera_view(scene, cobj, hc)
                a1 = world_to_camera_view(scene, cobj, hc + fh * 0.3)
                side_ok = True if t["theta"] == 0 else \
                    (a1.x - a0.x) * math.sin(math.radians(t["theta"])) > 0
                ck.add("P5", abs(wrap(theta - t["theta"])) <= TOL["theta"]
                       and abs(wrap(h - t["h"])) <= TOL["h"] and side_ok,
                       f"{cam}/s{slot}/{col}", theta_err=round(wrap(theta - t["theta"]), 4),
                       h_err=round(wrap(h - t["h"]), 4), screen_side_ok=side_ok,
                       theta=t["theta"], h=t["h"])
                # P6: head margin and size at 320, silhouettes at 640x360
                hp = [world_to_camera_view(scene, cobj, p) for p in eval_points(ch["body"], ch["head_verts"])]
                xs, ys = [p.x for p in hp], [p.y for p in hp]
                inside = min(xs) >= TOL["margin"] and max(xs) <= 1 - TOL["margin"] and \
                    min(ys) >= TOL["margin"] and max(ys) <= 1 - TOL["margin"]
                px = (max(xs) - min(xs)) * 320
                size_ok = abs(px - cs["head_px"]) <= TOL["px_rel"] * cs["head_px"]
                covers[col] = raster(scene, cobj, eval_polys(ch["body"]), 640, 360)
                ck.add("P6", inside and size_ok, f"{cam}/s{slot}/{col}/head",
                       head_in_margin=inside, head_px_320=round(px, 2), plan_px=cs["head_px"])
                # P7: every marker part sits where designed and follows the head
                hc_up = axis_vec(bone_world(arm, "head"), "+Y")
                for d, objs in ch["markers"].items():
                    for o in objs:
                        role = o["afs_role"]
                        if role == "head":
                            continue
                        pts = eval_points(o)
                        cen = sum(pts, Vector()) / len(pts)
                        rel = cen - hc
                        ahead = rel.dot(f)
                        lateral = rel.dot(fh.cross(Vector((0, 0, 1))))
                        vertical = rel.dot(hc_up)
                        exp_ahead, exp_vert = REV4_EXPECT[role] if DESIGN_SET == "rev4" \
                            else MARKER_EXPECT[(d, role)]
                        ok = ahead >= TOL["ahead"] and abs(lateral) <= TOL["lateral"] and \
                            abs(vertical - exp_vert) <= TOL["vertical"]
                        if exp_ahead is not None:
                            ok = ok and abs(ahead - exp_ahead) <= TOL["vertical"]
                        ck.add("P7", ok, f"{cam}/s{slot}/{col}/{d}/{role}", ahead=round(ahead, 4),
                               lateral=round(lateral, 4), vertical=round(vertical, 4))
            overlap = len(covers["grey"] & covers["ochre"])
            ck.add("P6", overlap == 0, f"{cam}/s{slot}/silhouettes", overlap_px_640=overlap)

    # P8: mask colour assignment (set up, inspected, restored; nothing rendered)
    mm = MaskMode(ctx)
    dither_before = scene.render.dither_intensity
    for raw in (False, True):
        mm.enter(raw=raw)
        ck.add("P8", scene.render.dither_intensity == 0.0, f"dither_off/{'raw' if raw else 'mask'}")
        for col, ch in chars.items():
            me = ch["body"].data
            heads = set(ch["head_polys"])
            bad = [p.index for p in me.polygons
                   if (p.material_index == 2) != (p.index in heads)]
            slots_ok = me.materials[0] == mm.mats["black"] and me.materials[1] == mm.mats["black"] \
                and me.materials[2] == mm.mats["green"]
            roles_ok = all(o.data.materials[0] == mm.mats[mm.colour_of(o["afs_role"])]
                           for objs in ch["markers"].values() for o in objs)
            hide_ok = ch["body"].hide_render == raw and all(
                o.hide_render for objs in ch["markers"].values() for o in objs
                if o["afs_role"] == "head") if raw else True
            ck.add("P8", not bad and slots_ok and roles_ok and hide_ok and len(heads) > 0,
                   f"{col}/{'raw' if raw else 'mask'}", head_polys=len(heads),
                   misassigned=len(bad), slots_ok=slots_ok, roles_ok=roles_ok, hide_ok=hide_ok)
        ck.add("P8", ctx["ground"].data.materials[0] == mm.mats["black"]
               and tuple(mm.world_bg.inputs["Color"].default_value)[:3] == (0, 0, 0),
               f"ground_world/{'raw' if raw else 'mask'}")
        mm.exit()
    ck.add("P8", scene.render.dither_intensity == dither_before, "dither_restored",
           dither=scene.render.dither_intensity)
    for col, ch in chars.items():
        me = ch["body"].data
        ck.add("P8", me.materials[2] == me.materials[0] and me.materials[0].name.startswith("MAT-")
               and not ch["body"].hide_render, f"{col}/restored")
    set_design(ctx, "D0")

    # P9: settings read back
    spec = ctx["spec"]
    for cam, cs in CAMS.items():
        c = ctx["cams"][cam]
        ok = abs(c.data.lens - cs["lens"]) < 1e-6 and (c.location - Vector(cs["loc"])).length < 1e-6 \
            and all(abs(math.degrees(r) - e) < 1e-4 for r, e in zip(c.rotation_euler, cs["rot"])) \
            and c.data.dof.use_dof == cs["dof"] and c.data.sensor_width == 36
        if cs["dof"]:
            ok = ok and abs(c.data.dof.focus_distance - cs["focus"]) < 1e-6 \
                and abs(c.data.dof.aperture_fstop - cs["fstop"]) < 1e-6 and c.data.dof.focus_object is None
        ck.add("P9", ok, f"camera/{cam}")
    lt = spec["lighting"]
    sun = bpy.data.objects["SUN-shot"]
    pre = ctx["bs"].LIGHT_PRESETS[lt["preset"]]
    sun_ok = all(abs(math.degrees(r) - e) < 1e-4 for r, e in
                 zip(sun.rotation_euler, (90 - lt["sun_elevation_deg"], 0, lt["sun_azimuth_deg"]))) \
        and abs(sun.data.energy - pre[2]) < 1e-6 and \
        all(abs(x - y) < 1e-6 for x, y in zip(sun.data.color, pre[3]))
    ck.add("P9", sun_ok, "sun")
    bg = next(n for n in scene.world.node_tree.nodes if n.bl_idname == "ShaderNodeBackground")
    ck.add("P9", all(abs(x - y) < 1e-6 for x, y in
                     zip(bg.inputs["Color"].default_value, spec["environment"]["world_color"])), "world")
    r = spec["render"]
    blur = getattr(scene.render, "use_motion_blur", getattr(scene.eevee, "use_motion_blur", None))
    ck.add("P9", scene.render.engine == ctx["bs"].eevee_engine_id(scene)
           and scene.eevee.taa_render_samples == r["samples"] and blur == r["motion_blur"]
           and scene.view_settings.view_transform == ctx["factory_view"]
           and abs(scene.view_settings.exposure - lt.get("exposure", 0.0)) < 1e-9, "render",
           engine=scene.render.engine, samples=scene.eevee.taa_render_samples,
           view_transform=scene.view_settings.view_transform)
    gm = ctx["ground"].data.materials[0]
    bsdf = next(n for n in gm.node_tree.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled")
    gspec = next(p for p in spec["primitives"] if p["name"] == "ground")["material"]
    ck.add("P9", all(abs(x - y) < 1e-6 for x, y in
                     zip(bsdf.inputs["Base Color"].default_value, gspec["base_color"])), "ground")
    if DESIGN_SET == "rev4":
        rev4_checks(ctx, ck, fwd_axis)
    return ck


def principled_inputs(mat) -> dict:
    b = next(n for n in mat.node_tree.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled")
    vals = {i.identifier: (tuple(i.default_value) if hasattr(i.default_value, "__len__")
                           else i.default_value) for i in b.inputs if hasattr(i, "default_value")}
    vals["_node"] = (b.distribution, b.subsurface_method, len(mat.node_tree.nodes),
                     len(mat.node_tree.links), tuple(mat.diffuse_color))
    return vals


def scene_fingerprint(ctx) -> str:
    """Everything a variant must not change: render, view, world and every non-marker object."""
    scene, r = ctx["scene"], ctx["scene"].render
    bg = next(n for n in scene.world.node_tree.nodes if n.bl_idname == "ShaderNodeBackground")
    objs = sorted((o.name, o.hide_render, [round(x, 9) for x in o.matrix_world.translation],
                   [m.name for m in o.data.materials] if o.type == "MESH" else [])
                  for o in scene.objects if not o.name.startswith("MK-"))
    return hashlib.sha256(json.dumps({
        "engine": r.engine, "res": (r.resolution_x, r.resolution_y), "pct": r.resolution_percentage,
        "samples": scene.eevee.taa_render_samples, "view": scene.view_settings.view_transform,
        "look": scene.view_settings.look, "exposure": scene.view_settings.exposure,
        "dither": r.dither_intensity, "camera": scene.camera.name,
        "world": list(bg.inputs["Color"].default_value), "objects": objs}).encode()).hexdigest()


def select_c_width(medium: dict) -> float | None:
    """medium[width][colour]: outside-head ratio C/A at the medium camera. The pre-registered rule;
    None means stop before rendering."""
    def meets(wd, threshold):
        return all(r is not None and r >= threshold for r in medium[wd].values())
    if meets(C_WIDTH, C_SELECT_RATIO):
        return C_WIDTH
    return C_FALLBACK_WIDTH if meets(C_FALLBACK_WIDTH, REAR_CUE_FLOOR) else None


def rev4_checks(ctx, ck: Checks, fwd_axis: str) -> None:
    """P12 rear-cue floor (decides C's width), then P10 variant isolation and P11 rev3 readback."""
    scene, chars = ctx["scene"], ctx["chars"]
    w, h = REAR_RES
    keys = ("A", f"C@{C_WIDTH:.2f}", f"C@{C_FALLBACK_WIDTH:.2f}")

    def part(ch, key, role):
        return next(o for o in ch["markers"][key] if o["afs_role"] == role)

    # P12, a geometric proxy (not a claim about what a render shows). Per camera, colour and visor,
    # summed over the rear angles and both head turns at 640x360 pixel centres:
    #   projected     pixels the visor projects to
    #   outside_head  of those, pixels outside the projected head outline (the decision proxy)
    #   visible       pixels whose camera ray first hits the visor (head, nose, body, ground and
    #                 the other character present; other markers disabled for the cast)
    # The rendered masks are checked against the proxy after rendering (rear_cue_mask_check).
    stats = {f"{cam}/{col}/{k}": {"projected": 0, "outside_head": 0, "visible": 0}
             for cam in CAMS for col in chars for k in keys}
    for cam in CAMS:
        cobj = ctx["cams"][cam]
        for theta in REAR_THETAS:
            for turn in (-40, 40):
                pose_angle(ctx, cam, theta, turn)
                for col, ch in chars.items():
                    polys = eval_polys(ch["body"])
                    head = raster(scene, cobj, [polys[i] for i in ch["head_polys"]], w, h)
                    for k in keys:
                        visor = part(ch, k, "marker")
                        proj = raster(scene, cobj, eval_polys(visor), w, h)
                        st = stats[f"{cam}/{col}/{k}"]
                        st["projected"] += len(proj)
                        st["outside_head"] += len(proj - head)
                        st["visible"] += visible_pixels(ctx, cobj, visor, proj, w, h)

    def ratio(metric, k, cc):
        base = stats[f"{cc}/A"][metric]
        return round(stats[f"{cc}/{k}"][metric] / base, 4) if base else None

    ratios = {metric: {k: {f"{cam}/{col}": ratio(metric, k, f"{cam}/{col}") for cam in CAMS for col in chars}
                       for k in keys[1:]} for metric in ("projected", "outside_head", "visible")}

    medium = {wd: {col: ratios["outside_head"][k][f"med/{col}"] for col in chars}
              for wd, k in ((C_WIDTH, keys[1]), (C_FALLBACK_WIDTH, keys[2]))}
    chosen = select_c_width(medium)
    rule = (f"0.10 if medium outside_head ratio >= {C_SELECT_RATIO} for every colour; else 0.11 if "
            f">= {REAR_CUE_FLOOR}; else stop before rendering")
    for col in chars:
        a_med = stats[f"med/{col}/A"]
        ck.add("P12", a_med["outside_head"] > 0 and a_med["visible"] > 0, f"{col}/A_rear_cue_present",
               **{f"A_{m}": v for m, v in a_med.items()})
    ck.add("P12", chosen is not None, "rear_cue_width_rule", rule=rule, select_ratio=C_SELECT_RATIO,
           floor=REAR_CUE_FLOOR, decided_on="outside_head ratio, medium camera, every colour",
           medium_ratios={f"{wd:.2f}": r for wd, r in medium.items()},
           c_width=chosen, fallback_used=chosen == C_FALLBACK_WIDTH)
    ctx["c_width"] = chosen
    ctx["rear_cue"] = {"rule": rule, "select_ratio": C_SELECT_RATIO, "floor": REAR_CUE_FLOOR,
                       "decided_on": "outside_head ratio, medium camera, every colour",
                       "measured_at": f"{w}x{h} pixel centres, theta {list(REAR_THETAS)}, head turns -40/+40",
                       "stats": stats, "ratios": ratios, "c_width": chosen,
                       "fallback_used": chosen == C_FALLBACK_WIDTH,
                       "proxy_note": "geometric proxy; no anti-aliasing, depth of field or lighting"}
    if chosen is None:
        return

    # P10: each variant differs only in its intended variable
    for ch in chars.values():
        ch["root"].rotation_euler = (0.0, 0.0, 0.0)
        ch["tracks"]["R"].mute = ch["tracks"]["L"].mute = True
    scene.frame_set(1)
    c, d = f"C@{chosen:.2f}", f"D@{chosen:.2f}"
    vw, vd, vh = D3_VISOR[1]
    for col, ch in chars.items():
        verts = lambda o: [tuple(v.co) for v in o.data.vertices]
        ck.add("P10", verts(part(ch, "A", "marker")) == verts(part(ch, "B", "marker")), f"{col}/A_B_same_visor")
        ck.add("P10", verts(part(ch, c, "marker")) == verts(part(ch, d, "marker")), f"{col}/C_D_same_visor")
        ck.add("P10", verts(part(ch, "A", "marker")) != verts(part(ch, c, "marker")), f"{col}/A_C_visor_differs")
        noses = [verts(part(ch, k, "nose")) for k in ch["markers"]]
        ck.add("P10", all(n == noses[0] for n in noses), f"{col}/nose_identical_in_every_variant")
        hb = bone_world(ch["arm"], "head")
        f, u = axis_vec(hb, fwd_axis), axis_vec(hb, "+Y")
        axes = (f.cross(u).normalized(), f, u)
        for key, width in (("A", vw), ("B", vw), (c, chosen), (d, chosen)):
            for role, dims in (("marker", (width, vd, vh)), ("nose", D3_NOSE[1])):
                pts = eval_points(part(ch, key, role))
                ext = [max(p.dot(ax) for p in pts) - min(p.dot(ax) for p in pts) for ax in axes]
                ck.add("P10", all(abs(e - x) <= 1e-4 for e, x in zip(ext, dims)), f"{col}/{key}/{role}_extents",
                       extents=[round(e, 5) for e in ext], expect=list(dims))
            want = ctx["marker_mat"] if key[0] in "AC" else ctx["matte_mat"]
            ck.add("P10", part(ch, key, "marker").data.materials[0] == want
                   and part(ch, key, "nose").data.materials[0] == ch["body"].data.materials[0],
                   f"{col}/{key}/materials")
    ia, ib = principled_inputs(ctx["marker_mat"]), principled_inputs(ctx["matte_mat"])
    differ = sorted(k for k in ia if ia[k] != ib.get(k))
    ck.add("P10", differ == ["Roughness"] and abs(ia["Roughness"] - MARKER_ROUGHNESS) < 1e-6
           and abs(ib["Roughness"] - MATTE_ROUGHNESS) < 1e-6, "materials/only_roughness_differs",
           differing=differ, roughness=[round(ia["Roughness"], 6), round(ib["Roughness"], 6)])
    prints, shown = {}, {}
    for design in DESIGNS:
        set_design(ctx, design)
        prints[design] = scene_fingerprint(ctx)
        shown[design] = sorted(o.name for o in scene.objects if o.name.startswith("MK-") and not o.hide_render)
    ck.add("P10", len(set(prints.values())) == 1, "scene/identical_across_variants")
    for design in DESIGNS:
        key = marker_key(ctx, design)
        ok = len(shown[design]) == 2 * len(chars) and all(n.startswith(f"MK-{key}-") for n in shown[design])
        ck.add("P10", ok, f"{design}/only_its_own_marker_renders", shown=shown[design])
    set_design(ctx, "D0")
    mk = [o for o in scene.objects if o.name.startswith("MK-")]
    ck.add("P10", not any(o.hide_viewport for o in mk), "markers/viewport_restored_after_ray_casts")
    fs = getattr(scene.render, "filter_size", None)
    ck.add("P10", fs is not None and fs <= DILATE_PX, "isolation_basis/filter_within_band",
           filter_size_px=fs, band_px=DILATE_PX, tol_255=round(BEAUTY_TOL * 255, 2),
           eevee_raytracing=getattr(scene.eevee, "use_raytracing", None),
           eevee_shadows=getattr(scene.eevee, "use_shadows", None))

    # P11: A is rev3's D3 (render-time pixel reproduction follows in --render)
    mm = ctx["marker_mat"]
    ck.add("P11", bpy.app.version_string == REV3_RECORD["blender_version"], "blender_version",
           version=bpy.app.version_string)
    ck.add("P11", all(abs(x - y) < 1e-6 for x, y in zip(principled_inputs(mm)["Base Color"],
                                                       (*REV3_RECORD["marker_rgb"], 1.0)))
           and abs(principled_inputs(mm)["Roughness"] - REV3_RECORD["marker_roughness"]) < 1e-6,
           "A/marker_material_matches_rev3")
    ck.add("P11", D3_VISOR == ((0, -0.085, 1.67), (0.13, 0.05, 0.035))
           and D3_NOSE == ((0, -0.115, 1.625), (0.035, 0.05, 0.04)), "A/geometry_matches_rev3_D3")
    ref = ctx.get("rev3_ref")
    ck.add("P11", ref is not None and not ref["errors"] and sorted(ref["stills"]) == sorted(CAMS),
           "rev3_reference_verified", errors=ref["errors"] if ref else ["no reference given"],
           stills={c: {k: v for k, v in s.items()} for c, s in (ref or {}).get("stills", {}).items()},
           files_read=(ref or {}).get("files_read", []))


# ---------------------------------------------------------------------------
# Render (Phase A) and diagnostics (private until the blind read is scored)
# ---------------------------------------------------------------------------
def render_still(scene, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def srgb_to_linear(c):
    import numpy as np
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def load_px(path: Path):
    import numpy as np
    img = bpy.data.images.load(str(path))
    img.colorspace_settings.name = "Non-Color"
    w, h = img.size
    px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
    bpy.data.images.remove(img)
    return px


def measure(beauty, mask, raw, split_x: float) -> dict:
    import numpy as np
    out = {}
    h, w = mask.shape[:2]
    xs = np.arange(w)[None, :].repeat(h, 0)
    lum = None
    if beauty is not None:
        lin = srgb_to_linear(beauty[..., :3])
        lum = 0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]
    for col, sel in (("grey", xs < split_x), ("ochre", xs >= split_x)):
        R, G, B = (mask[..., i] * sel for i in range(3))
        clean_r = (R > 0.9) & (G < 0.1) & (B < 0.1)
        clean_g = (G > 0.9) & (R < 0.1) & (B < 0.1)
        head = R + G + B
        area = float(head.sum())
        m = {"head_area": round(area, 2), "marker_area": round(float(R.sum()), 2),
             "marker_clean": int(clean_r.sum()), "nose_area": round(float(B.sum()), 2)}
        if lum is not None:
            m["beauty_mean_lum"] = round(float(lum[sel].mean()), 4)
        if raw is not None:
            m["raw_green"] = round(float((raw[..., 1] * sel).sum()), 2)
            Rr = raw[..., 0] * sel
            m["raw_area"] = round(float(Rr.sum()), 2)
            m["raw_clean"] = int(((Rr > 0.9) & (raw[..., 1] < 0.1) & (raw[..., 2] < 0.1) & sel).sum())
            m["visible_ratio"] = round(m["marker_area"] / m["raw_area"], 4) if m["raw_area"] > 0 else None
        if R.sum() > 0 and area > 0:
            radius = math.sqrt(area / math.pi)
            m["centre_offset"] = round(float(((R * xs).sum() / R.sum() - (head * xs).sum() / area) / radius), 4)
        if lum is not None and clean_r.sum() and clean_g.sum():
            lh, lm = float(lum[clean_g].mean()), float(lum[clean_r].mean())
            m["contrast"] = round((lh + 0.05) / (lm + 0.05), 3)
        out[col] = m
    return out


class MaskValidationError(RuntimeError):
    pass


def d2_mesh_check(ctx) -> list[dict]:
    """With D2 active the evaluated body must lose exactly the original head ball."""
    rows = []
    for col, ch in ctx["chars"].items():
        counts = {}
        for d in ("D0", "D2"):
            set_design(ctx, d)
            ctx["scene"].frame_set(1)
            counts[d] = len(eval_points(ch["body"]))
        ok = counts["D0"] - counts["D2"] == len(ch["head_verts"])
        rows.append({"ok": ok, "item": f"{col}/D2_head_removed", "verts_D0": counts["D0"],
                     "verts_D2": counts["D2"], "head_verts": len(ch["head_verts"])})
    set_design(ctx, "D0")
    return rows


def stray_dark(px) -> int:
    """Mask pixels that are neither pure black nor a mask colour: any value in (0, 4/255]
    with every channel at or below it (dither or filter residue on the background)."""
    import numpy as np
    rgb = px[..., :3]
    mx = rgb.max(axis=2)
    return int(((mx > 0) & (mx <= 4.5 / 255)).sum())


VOLATILE_TEXT = (b"Date", b"RenderTime")


def png_chunks(path: Path) -> list[tuple[bytes, bytes]]:
    import struct
    data = path.read_bytes()
    pos, out = 8, []
    while pos < len(data):
        (n,) = struct.unpack(">I", data[pos:pos + 4])
        out.append((data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]))
        pos += 12 + n
    return out


def same_image(new: Path, old: Path) -> dict:
    """Option 1 (approved): identical decoded pixels, identical IHDR, and identical chunks
    except Blender's tEXt Date and RenderTime stamps."""
    import numpy as np
    keep = lambda cs: [(k, v) for k, v in cs
                       if not (k == b"tEXt" and v.split(b"\x00", 1)[0] in VOLATILE_TEXT)]
    cn, co = png_chunks(new), png_chunks(old)
    ihdr = dict(cn).get(b"IHDR") == dict(co).get(b"IHDR")
    chunks = keep(cn) == keep(co)
    pixels = bool(np.array_equal(load_px(new), load_px(old)))
    return {"ok": ihdr and chunks and pixels, "ihdr_same": ihdr, "chunks_same_except_volatile": chunks,
            "pixels_same": pixels}


def head_present_ok(area: float, cam: str) -> bool:
    """rev4: the head mask covers at least the camera's minimum; an unknown camera is an error."""
    return area >= HEAD_MIN_AREA[cam]


def validate_group(a: dict, out: Path, private: Path, group: list[dict], w: int, split: float,
                   compare_with: list[Path]) -> list[dict]:
    """Structural checks on the first rendered (camera, slot) group, all four designs."""
    m = {}
    rows = []

    def add(ok, item, **v):
        rows.append({"ok": bool(ok), "item": item, **v})

    for s in group:
        raw_p = private / "masks_raw" / str(w) / f"{s['id']}.png"
        mask = load_px(private / "masks" / str(w) / f"{s['id']}.png")
        raw = load_px(raw_p) if raw_p.exists() else None
        add(stray_dark(mask) == 0, f"{s['design']}/mask_background_black", stray=stray_dark(mask))
        if raw is not None:
            add(stray_dark(raw) == 0, f"{s['design']}/raw_background_black", stray=stray_dark(raw))
        m[s["design"]] = measure(load_px(out / "stills" / str(w) / f"{s['id']}.png"), mask, raw, split)
        for earlier in compare_with:
            new, old = out / "stills" / str(w) / f"{s['id']}.png", earlier / "stills" / str(w) / f"{s['id']}.png"
            res = same_image(new, old) if old.exists() else {"ok": False}
            add(res["ok"], f"{s['design']}/beauty_matches_{earlier.name}", earlier_exists=old.exists(),
                **{k: v for k, v in res.items() if k != "ok"})

    cam = group[0]["cam"]
    for col in CHARS:
        theta = abs(group[0][col])
        front = theta <= 90
        d0 = m["D0"][col] if "D0" in m else None
        for d in DESIGNS:
            x = m[d][col]
            if DESIGN_SET == "rev4":
                add(head_present_ok(x["head_area"], cam), f"{d}/{col}/head_present",
                    head_area=x["head_area"], camera=cam, min_area=HEAD_MIN_AREA[cam])
            else:
                add(x["head_area"] > 100, f"{d}/{col}/head_present", head_area=x["head_area"])
            add(x["beauty_mean_lum"] > 0.02, f"{d}/{col}/beauty_not_black", lum=x["beauty_mean_lum"])
            if d == "D0":
                add(x["marker_area"] < 0.5 and x["nose_area"] < 0.5, f"D0/{col}/no_marker",
                    marker_area=x["marker_area"], nose_area=x["nose_area"])
                continue
            add(x["raw_green"] < 0.5, f"{d}/{col}/raw_has_no_head_or_body", raw_green=x["raw_green"])
            add(x["raw_area"] > 0, f"{d}/{col}/raw_marker_present", raw_area=x["raw_area"])
            if front:
                add(x["marker_clean"] >= 1, f"{d}/{col}/marker_visible_from_front",
                    marker_clean=x["marker_clean"])
            if (d == "D3" or DESIGN_SET == "rev4") and front:
                add(x["nose_area"] > 0, f"{d}/{col}/nose_present", nose_area=x["nose_area"])
            if d == "D2":
                rel = abs(x["head_area"] - d0["head_area"]) / d0["head_area"]
                add(rel <= 0.15, f"D2/{col}/head_area_matches_D0", rel_diff=round(rel, 4))
    return rows


def dilate(m, r: int):
    """Square (Chebyshev) dilation by r pixels; no wrap-around at the image edges."""
    import numpy as np
    h, w = m.shape
    p = np.pad(m, r)
    out = np.zeros_like(m)
    for dy in range(2 * r + 1):
        for dx in range(2 * r + 1):
            out |= p[dy:dy + h, dx:dx + w]
    return out


def beauty_isolation(mask, bx, by) -> dict:
    """Two beauty images that must differ only within DILATE_PX of the red (visible marker)
    pixels of `mask`; see BEAUTY_TOL for the basis of the tolerance."""
    import numpy as np
    if mask.shape[:2] != bx.shape[:2] or bx.shape[:2] != by.shape[:2]:
        return {"ok": False, "shape_mismatch": [list(x.shape[:2]) for x in (mask, bx, by)]}
    near = dilate(mask[..., 0] > 0.5, DILATE_PX)
    diff = np.abs(bx[..., :3] - by[..., :3]).max(axis=2)
    outside = float(diff[~near].max()) if (~near).any() else 0.0
    return {"ok": outside <= BEAUTY_TOL, "max_outside_255": round(outside * 255, 2),
            "pixels_outside_over_tol": int((diff[~near] > BEAUTY_TOL).sum()),
            "pixels_inside_changed": int((diff[near] > 0).sum()), "band_px": int(near.sum())}


def isolation_checks(out: Path, private: Path, group: list[dict], w: int) -> list[dict]:
    """rev4, one (camera, slot) group: A/B and C/D share geometry, so their masks must be
    identical and their beauty may differ only within DILATE_PX of the marker."""
    import numpy as np
    sid = {s["design"]: s["id"] for s in group}
    rows = []
    for x, y in (("A", "B"), ("C", "D")):
        for kind in ("masks", "masks_raw"):
            mx, my = (load_px(private / kind / str(w) / f"{sid[d]}.png") for d in (x, y))
            rows.append({"ok": bool(np.array_equal(mx, my)), "item": f"{x}{y}/{kind}_identical"})
        mask = load_px(private / "masks" / str(w) / f"{sid[x]}.png")
        bx, by = (load_px(out / "stills" / str(w) / f"{sid[d]}.png") for d in (x, y))
        res = beauty_isolation(mask, bx, by)
        rows.append({"item": f"{x}{y}/beauty_differs_only_near_marker", **res})
    return rows


def png_size(path: Path) -> tuple[int, int]:
    import struct
    return struct.unpack(">II", dict(png_chunks(path))[b"IHDR"][:8])


def rev3_reference(rev3: Path) -> dict:
    """The two reproduction references: the slot-0 D3 still of each camera. experiment.json is
    parsed in memory and only these fields are kept: assignments.stills entries (id, design, cam,
    slot) for D3 slot 0, assignments.pairing[cam] and assignments.turns[cam] (needed to pose the
    still) and sha256["stills\\320\\<id>.png"]. answer_key.json and private records are never
    opened. Each reference is checked: recorded hash, 320x180, design D3, the intended camera."""
    src = rev3 / "experiment.json"
    raw = json.loads(src.read_text())
    a, recorded = raw["assignments"], raw["sha256"]
    ref = {"files_read": [str(src)], "fields_kept": [
        "assignments.stills[design=D3, slot=0].{id,design,cam,slot}", "assignments.pairing[cam]",
        "assignments.turns[cam]", "sha256[stills\\320\\<id>.png]"],
        "stills": {}, "pairing": {}, "turns": {}, "errors": []}
    for cam in CAMS:
        hits = [x for x in a["stills"] if x["design"] == "D3" and x["cam"] == cam and x["slot"] == 0]
        if len(hits) != 1:
            ref["errors"].append(f"{cam}: expected one D3 slot-0 still, found {len(hits)}")
            continue
        s = {k: hits[0][k] for k in ("id", "design", "cam", "slot")}
        consistent = hits[0]["grey"] == ANGLES[0] and hits[0]["ochre"] == ANGLES[a["pairing"][cam][0]]
        beauty, mask = rev3 / "stills" / "320" / f"{s['id']}.png", rev3 / "masks" / "320" / f"{s['id']}.png"
        want = recorded.get(f"stills\\320\\{s['id']}.png")
        missing = [f"{cam}: missing {p.name} in {p.parent}" for p in (beauty, mask) if not p.exists()]
        if missing:
            ref["errors"] += missing
            continue
        ref["files_read"] += [str(beauty), str(mask)]
        s.update(beauty_sha256=sha256(beauty), mask_sha256=sha256(mask), beauty_recorded_sha256=want,
                 beauty_size=list(png_size(beauty)), mask_size=list(png_size(mask)))
        if not consistent:
            ref["errors"].append(f"{cam}: still record disagrees with the recorded pairing")
        if want is None or s["beauty_sha256"] != want:
            ref["errors"].append(f"{cam}: reference beauty hash differs from rev3's record")
        if s["beauty_size"] != [320, 180] or s["mask_size"] != [320, 180]:
            ref["errors"].append(f"{cam}: reference size is not 320x180")
        if s["design"] != "D3" or s["cam"] != cam:
            ref["errors"].append(f"{cam}: reference is not the intended D3 {cam} still")
        ref["stills"][cam] = s
        ref["pairing"][cam], ref["turns"][cam] = a["pairing"][cam], a["turns"][cam]
    del raw, a, recorded
    return ref


def reproduce_rev3(ctx, rev3: Path, private: Path) -> list[dict]:
    """P11 at render time: the verified references, re-rendered as A, must match rev3: same
    decoded pixels and size, same PNG chunks except tEXt Date/RenderTime, and zero beauty
    isolation difference. Output stays private; the console shows pass/fail only."""
    import numpy as np
    scene, ref = ctx["scene"], ctx["rev3_ref"]
    pose = {"pairing": ref["pairing"], "turns": ref["turns"]}
    mm = MaskMode(ctx)
    scene.render.resolution_x, scene.render.resolution_y = 320, 180
    rows = []
    for cam in CAMS:
        sid = ref["stills"][cam]["id"]
        pose_still(ctx, pose, cam, 0)
        set_design(ctx, "A")
        beauty, mask = private / "repro" / "stills" / f"{sid}.png", private / "repro" / "masks" / f"{sid}.png"
        render_still(scene, beauty)
        render_mask(scene, mm, mask, raw=False)
        old_b, old_m = rev3 / "stills" / "320" / f"{sid}.png", rev3 / "masks" / "320" / f"{sid}.png"
        for kind, new, old, want in (("beauty", beauty, old_b, ref["stills"][cam]["beauty_sha256"]),
                                     ("mask", mask, old_m, ref["stills"][cam]["mask_sha256"])):
            res = same_image(new, old)
            unchanged = sha256(old) == want                 # reference untouched since the preflight
            rows.append({"ok": res["ok"] and unchanged and png_size(new) == png_size(old),
                         "item": f"P11/{cam}/{kind}_matches_rev3", "reference_unchanged": unchanged,
                         "size": list(png_size(new)), **{k: v for k, v in res.items() if k != "ok"}})
        iso = beauty_isolation(load_px(old_m), load_px(old_b), load_px(beauty))
        rows.append({"item": f"P11/{cam}/isolation_metric_zero", **iso,
                     "ok": iso["ok"] and iso["max_outside_255"] == 0 and iso["pixels_inside_changed"] == 0})
    set_design(ctx, "D0")
    return rows


def rear_cue_mask_check(a: dict, private: Path, log: list, proxy: dict) -> dict:
    """After rendering: visible marker pixels (clean red) in the 320 medium masks at the rear
    angles, C over A per colour, on the same poses. The proxy chose C's width because its
    outside-head ratio met the floor; a mask ratio below the floor, or no visible rear marker for
    A, contradicts the proxy and stops the run before any blind sheet is made."""
    split = {e["id"]: e["split_x"] for e in log if e["res"] == 320}
    sums = {col: {"A": 0, "C": 0} for col in CHARS}
    for s in a["stills"]:
        if s["cam"] != "med" or s["design"] not in ("A", "C"):
            continue
        m = measure(None, load_px(private / "masks" / "320" / f"{s['id']}.png"), None, split[s["id"]])
        for col in CHARS:
            if abs(s[col]) == 140:
                sums[col][s["design"]] += m[col]["marker_clean"]
    ratios = {col: round(v["C"] / v["A"], 4) if v["A"] else None for col, v in sums.items()}
    ok = all(r is not None and r >= REAR_CUE_FLOOR for r in ratios.values())
    key = f"C@{proxy['c_width']:.2f}"
    return {"status": "pass" if ok else "contradiction", "floor": REAR_CUE_FLOOR,
            "mask_visible_pixels_320": sums, "mask_ratio": ratios,
            "proxy_outside_head_ratio": {col: proxy["ratios"]["outside_head"][key][f"med/{col}"] for col in CHARS},
            "proxy_visible_ratio": {col: proxy["ratios"]["visible"][key][f"med/{col}"] for col in CHARS}}


def render_mask(scene, mm: MaskMode, path: Path, raw: bool) -> None:
    mm.enter(raw=raw)
    try:
        render_still(scene, path)
    finally:
        mm.exit()                                      # dither and materials always restored


def render_all(ctx, a: dict, out: Path, private: Path, compare_with: list[Path] = ()) -> dict:
    scene = ctx["scene"]
    mm = MaskMode(ctx)
    log, t0 = [], time.time()
    validation = d2_mesh_check(ctx) if "D2" in DESIGNS else []
    if not all(r["ok"] for r in validation):
        (private / "mask_validation.json").write_text(json.dumps(validation, indent=1))
        raise MaskValidationError("D2 head replacement failed on the evaluated mesh")
    first = True
    for w, h in RESOLUTIONS:
        scene.render.resolution_x, scene.render.resolution_y = w, h
        for cam in CAMS:
            for slot in range(len(ANGLES)):
                pose_still(ctx, a, cam, slot)
                cobj = ctx["cams"][cam]
                split = sum(world_to_camera_view(scene, cobj, head_centre(ch["arm"])).x
                            for ch in ctx["chars"].values()) / 2 * w
                group = [s for s in a["stills"] if s["cam"] == cam and s["slot"] == slot]
                for s in group:
                    set_design(ctx, s["design"])
                    sid = s["id"]
                    dither = scene.render.dither_intensity
                    render_still(scene, out / "stills" / str(w) / f"{sid}.png")
                    render_mask(scene, mm, private / "masks" / str(w) / f"{sid}.png", raw=False)
                    if s["design"] != "D0":
                        render_mask(scene, mm, private / "masks_raw" / str(w) / f"{sid}.png", raw=True)
                    if scene.render.dither_intensity != dither:
                        raise MaskValidationError("beauty dither setting was not restored")
                    log.append({"id": sid, "res": w, "split_x": round(split, 3)})
                    print(f"[marker_test] rendered {sid} at {w}x{h}")
                if first or DESIGN_SET == "rev4":             # rev4 validates every group
                    rows = validate_group(a, out, private, group, w, split, compare_with if first else [])
                    if DESIGN_SET == "rev4":
                        rows = [{**r, "group": f"{cam}/s{slot}"}
                                for r in rows + isolation_checks(out, private, group, w)]
                    first = False
                    validation += rows
                    (private / "mask_validation.json").write_text(json.dumps(validation, indent=1))
                    bad = [r["item"] for r in validation if not r["ok"]]
                    print(f"[marker_test] {'group' if DESIGN_SET == 'rev4' else 'first-group'} mask "
                          f"validation: {len(validation)} checks, {len(bad)} failed {bad}")
                    if bad:
                        raise MaskValidationError(f"mask validation failed: {bad}")
    set_design(ctx, "D0")
    return {"render_s": round(time.time() - t0, 1), "log": log}


def diagnostics(a: dict, out: Path, private: Path, log: list) -> dict:
    by = {(e["id"], e["res"]): e["split_x"] for e in log}
    rows, size_errors = [], []
    for s in a["stills"]:
        for w, h in RESOLUTIONS:
            sid = s["id"]
            raw_p = private / "masks_raw" / str(w) / f"{sid}.png"
            imgs = [load_px(out / "stills" / str(w) / f"{sid}.png"),
                    load_px(private / "masks" / str(w) / f"{sid}.png"),
                    load_px(raw_p) if raw_p.exists() else None]
            size_errors += [f"{sid}@{w}" for im in imgs if im is not None and im.shape[:2] != (h, w)]
            m = measure(*imgs, by[(sid, w)])
            rows.append({"id": sid, "res": w, "design": s["design"], "cam": s["cam"],
                         "grey": {"theta": s["grey"], **m["grey"]},
                         "ochre": {"theta": s["ochre"], **m["ochre"]}})
    print(f"[marker_test] diagnostics: {len(rows)} rows, size errors {size_errors}")
    return {"rows": rows, "size_errors": size_errors}


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    args = parse_args()
    use_design_set(args.design_set)
    repo, private = args.repo.resolve(), args.private.resolve()
    out = (repo / args.out).resolve() if not args.out.is_absolute() else args.out
    summary_path = out / "preflight" / "preflight_summary.json"
    if DESIGN_SET == "rev4":
        refuse = None
        if out.name != "marker_test_rev4":
            refuse = f"rev4 writes only to a folder named marker_test_rev4, not {out.name}"
        elif args.assignments:
            refuse = "rev4 uses its own new secret seed; --assignments is not allowed"
        elif private == out or out in private.parents or private in out.parents:
            refuse = "the private folder must be outside the review output and vice versa"
        elif any(q.name in PROTECTED for p in (out, private) for q in (p, *p.parents)):
            refuse = f"output and private folders must not be inside {PROTECTED}"
        elif args.reproduce_rev3 is None:
            refuse = "rev4 needs --reproduce-rev3 (reference stills are verified in every preflight)"
        elif args.preflight_only and (private / "assignments.json").exists():
            refuse = f"{private / 'assignments.json'} exists; rev4 needs a new seed in a new folder"
        elif args.render and args.c_width is None:
            refuse = "rev4 --render needs --c-width"
        if refuse:
            print(f"[marker_test] REFUSED: {refuse}", file=sys.stderr)
            return 2
    if args.preflight_only and out.exists():
        print(f"[marker_test] REFUSED: {out} exists", file=sys.stderr)
        return 2
    if args.render:
        if not summary_path.exists() or json.loads(summary_path.read_text())["status"] != "pass":
            print("[marker_test] REFUSED: no passing preflight summary", file=sys.stderr)
            return 2
        for sub in (out / "stills", private / "masks", private / "masks_raw"):
            if sub.exists():
                print(f"[marker_test] REFUSED: {sub} exists", file=sys.stderr)
                return 2

    given = args.assignments.resolve() if args.assignments else None
    a = load_assignments(private, create=args.preflight_only, given=given)
    errs = check_assignments(a)
    digest = hashlib.sha256(json.dumps(a, sort_keys=True).encode()).hexdigest()
    ctx = build(repo, private / "tmp_render")
    if DESIGN_SET == "rev4":
        rev3 = args.reproduce_rev3 if args.reproduce_rev3.is_absolute() else repo / args.reproduce_rev3
        ctx["rev3"], ctx["rev3_ref"] = rev3, rev3_reference(rev3)
    t0 = time.time()
    ck = preflight(ctx, a)
    full = {"assignments_ok": not errs, "assignment_errors": errs, "assignments_sha256": digest,
            "blender_version": bpy.app.version_string, "build_warnings": ctx["warnings"],
            "preflight_s": round(time.time() - t0, 1), "counts": ck.counts(), "items": ck.items}
    if DESIGN_SET == "rev4":
        full["design_set"], full["rear_cue"] = DESIGN_SET, ctx.get("rear_cue")
        full["rev3_reference"] = {k: v for k, v in ctx["rev3_ref"].items() if k not in ("pairing", "turns")}
    ok = ck.all_ok() and not errs
    full["status"] = "pass" if ok else "fail"
    private.mkdir(parents=True, exist_ok=True)
    # the render run repeats the preflight into its own file; the original is never rewritten
    record = private / ("preflight_full.json" if args.preflight_only else "preflight_render.json")
    if record.exists():
        print(f"[marker_test] REFUSED: {record} exists", file=sys.stderr)
        return 2
    record.write_text(json.dumps(full, indent=1))
    print(f"[marker_test] assignments balanced: {not errs} {errs}")
    for pid, c in ck.counts().items():
        print(f"[marker_test] {pid}: passed {c['passed']} failed {c['failed']}")
    if DESIGN_SET == "rev4" and ctx.get("rear_cue"):       # aggregate over the rear angles only
        rc = ctx["rear_cue"]
        print(f"[marker_test] rear-cue proxy ({rc['measured_at']}); rule: {rc['rule']}")
        for key, st in rc["stats"].items():
            print(f"[marker_test]   {key}: {st}")
        for metric, r in rc["ratios"].items():
            print(f"[marker_test]   ratio {metric}: {json.dumps(r)}")
        print(f"[marker_test] C width decided: {rc['c_width']} (fallback used: {rc['fallback_used']})")
    if not ok:
        for pid, items in ck.items.items():          # labels and errors only, no targets
            for i in items:
                if not i["ok"]:
                    shown = {k: v for k, v in i.items() if k not in ("theta", "h")}
                    print(f"[marker_test] FAIL {pid} {shown}")
        print("[marker_test] preflight FAILED; nothing written to storage")
        return 1

    if args.preflight_only:
        summary_path.parent.mkdir(parents=True)
        summary = {"status": "pass", "blender_version": bpy.app.version_string,
                   "counts": ck.counts(), "assignments_balanced": True}
        if DESIGN_SET == "rev4":
            summary.update(design_set=DESIGN_SET, rear_cue=ctx["rear_cue"],
                           rev3_reference_files_read=ctx["rev3_ref"]["files_read"])
        summary_path.write_text(json.dumps(summary, indent=1))
        print(f"[marker_test] preflight PASSED; wrote {summary_path}")
        return 0

    if json.loads((private / "preflight_full.json").read_text())["assignments_sha256"] != digest:
        return 2
    if DESIGN_SET == "rev4":
        decided = json.loads((private / "preflight_full.json").read_text())["rear_cue"]["c_width"]
        if not (decided == ctx["c_width"] and abs(args.c_width - decided) < 1e-9):
            print(f"[marker_test] REFUSED: --c-width {args.c_width} does not repeat the preflight "
                  f"decision {decided} (this run measured {ctx['c_width']})", file=sys.stderr)
            return 2
        if (private / "repro").exists():
            print(f"[marker_test] REFUSED: {private / 'repro'} exists", file=sys.stderr)
            return 2
        repro = reproduce_rev3(ctx, ctx["rev3"], private)
        (private / "repro_validation.json").write_text(json.dumps(repro, indent=1))
        bad = [r["item"] for r in repro if not r["ok"]]
        print(f"[marker_test] rev3 reproduction: {len(repro)} checks, {len(bad)} failed {bad}")
        if bad:
            print("[marker_test] STOPPED: A does not reproduce rev3's D3; no rev4 still rendered")
            return 1
    try:
        compare = [c if c.is_absolute() else (repo / c) for c in args.compare_with]
        res = render_all(ctx, a, out, private, compare)
    except MaskValidationError as e:
        print(f"[marker_test] STOPPED: {e}; partial output preserved, nothing overwritten")
        return 1
    diag = diagnostics(a, out, private, res["log"])
    (private / "diagnostics.json").write_text(json.dumps(diag, indent=1))
    stills = sorted((out / "stills").rglob("*.png"))
    record = {
        "blender_version": bpy.app.version_string, "cams": CAMS, "chars": CHARS,
        "designs": list(DESIGNS), "angles": list(ANGLES), "marker_rgb": MARKER_RGB,
        "marker_roughness": MARKER_ROUGHNESS, "render_s": res["render_s"],
        "memory_mb": ctx["bs"].peak_memory_mb(), "assignments": a, "log": res["log"],
        "sha256": {str(p.relative_to(out)): sha256(p) for p in stills}}
    if DESIGN_SET == "rev4":
        record.update(design_set=DESIGN_SET, rear_cue=ctx["rear_cue"], variants={
            "A": {"visor": D3_VISOR, "nose": D3_NOSE, "roughness": MARKER_ROUGHNESS},
            "B": {"visor": D3_VISOR, "nose": D3_NOSE, "roughness": MATTE_ROUGHNESS},
            "C": {"visor": (D3_VISOR[0], (ctx["c_width"], *D3_VISOR[1][1:])), "nose": D3_NOSE,
                  "roughness": MARKER_ROUGHNESS},
            "D": {"visor": (D3_VISOR[0], (ctx["c_width"], *D3_VISOR[1][1:])), "nose": D3_NOSE,
                  "roughness": MATTE_ROUGHNESS}})
    (private / "experiment.json").write_text(json.dumps(record, indent=1))
    print(f"[marker_test] rendered {len(stills)} stills in {res['render_s']} s")
    if DESIGN_SET == "rev4":
        rc = rear_cue_mask_check(a, private, res["log"], ctx["rear_cue"])
        (private / "rear_cue_mask_check.json").write_text(json.dumps(rc, indent=1))
        print(f"[marker_test] rear cue in masks: {rc['status']}; mask ratio {rc['mask_ratio']}, "
              f"proxy outside-head {rc['proxy_outside_head_ratio']}, proxy visible {rc['proxy_visible_ratio']}")
        if rc["status"] != "pass":
            print("[marker_test] STOPPED: the rendered masks contradict the rear-cue proxy; "
                  "no blind sheets until this is reviewed")
            return 1
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 2
        print(e, file=sys.stderr)
    sys.exit(code)
