"""
gate3_equivalence.py - M11 Gate 3: the marked character assets reproduce marker A of the M11
experiment. Re-renders rev3's two reference stills (D3 = A; medium S21 and wide S50, slot 0)
with mannequin_marked / mannequin_ochre_marked and no test-harness marker objects, and compares
them with the M11 references: at most 2/255 difference outside a 2 px dilation of the reference
marker region (BEAUTY_TOL, DILATE_PX), for the beauty and the mask images.

    blender -b --factory-startup -t 4 --python-exit-code 1 -P gate3_equivalence.py -- \
        --repo <repo> --rev3 storage/projects/m11_readable_attention/marker_test_rev3 \
        --out storage/projects/m11_readable_attention/marker_test_rev4_gate3_equivalence \
        --private <new private dir>

Renders exactly four images: two beauty stills (public, with copies of the reference stills)
and two masks (private). Never overwrites: every output folder must not exist yet.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import marker_test as mt  # noqa: E402

OUT_NAME = "marker_test_rev4_gate3_equivalence"
MARKED = {"grey": ("mannequin_marked", -0.45), "ochre": ("mannequin_ochre_marked", 0.45)}
MASK_RGB = {"black": (0, 0, 0), "red": (1, 0, 0), "green": (0, 1, 0), "blue": (0, 0, 1)}


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser(prog="gate3_equivalence.py")
    for name in ("--repo", "--rev3", "--out", "--private"):
        p.add_argument(name, required=True, type=Path)
    return p.parse_args(argv)


def build_marked(repo: Path, tmp: Path) -> dict:
    """The M11 scene (same spec, lighting, world, ground, cameras, poses) with the marked assets
    and no harness markers: build_markers builds nothing and the head keeps its own materials."""
    mt.use_design_set("rev3")
    mt.CHARS.clear()
    mt.CHARS.update(MARKED)
    mt.build_markers = lambda coll, arm, body, marker_mat, matte_mat=None: {}
    mt.head_slot = lambda body: ([], [])
    ctx = mt.build(repo, tmp)
    names = [o.name for o in ctx["scene"].objects if o.name.startswith("MK-")]
    if names:
        raise RuntimeError(f"harness marker objects present: {names}")
    return ctx


def box_corners(centre, dims) -> set[tuple]:
    return {tuple(round(centre[i] + s[i] * dims[i] / 2, 5) for i in range(3))
            for s in [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]}


def classify(body, nose: set[tuple]) -> dict[int, str]:
    """Polygon -> mask label on the marked mesh: marker slot -> red, the nose box -> blue, the
    rest of the head bone's polygons -> green, everything else -> black."""
    me = body.data
    head = body.vertex_groups["head"].index
    in_head = {v.index for v in me.vertices if any(g.group == head and g.weight > 0.5 for g in v.groups)}
    marker_slot = next(i for i, m in enumerate(me.materials) if m.name.split(".")[0].endswith("marker"))
    labels = {}
    for p in me.polygons:
        vs = list(p.vertices)
        if p.material_index == marker_slot:
            labels[p.index] = "red"
        elif all(tuple(round(c, 5) for c in me.vertices[i].co) in nose for i in vs):
            labels[p.index] = "blue"
        elif all(i in in_head for i in vs):
            labels[p.index] = "green"
        else:
            labels[p.index] = "black"
    return labels


def render_mask(ctx, path: Path, nose: set[tuple]) -> dict:
    """Flat emission labels, as the M11 masks (MaskMode): black world and ground, Standard view,
    one sample, no dither, the smallest pixel filter. Everything is restored afterwards."""
    scene = ctx["scene"]
    mats = {k: mt.emission(f"MAT-g3mask-{k}", rgb) for k, rgb in MASK_RGB.items()}
    bg = next(n for n in scene.world.node_tree.nodes if n.bl_idname == "ShaderNodeBackground")
    saved = {"world": tuple(bg.inputs["Color"].default_value), "view": scene.view_settings.view_transform,
             "look": scene.view_settings.look, "samples": scene.eevee.taa_render_samples,
             "dither": scene.render.dither_intensity, "filter": scene.render.filter_size,
             "ground": ctx["ground"].data.materials[0], "bodies": {}}
    counts = {}
    try:
        bg.inputs["Color"].default_value = (0, 0, 0, 1)
        scene.view_settings.view_transform, scene.view_settings.look = "Standard", "None"
        scene.eevee.taa_render_samples = 1
        scene.render.dither_intensity = 0.0
        scene.render.filter_size = scene.render.bl_rna.properties["filter_size"].hard_min
        ctx["ground"].data.materials[0] = mats["black"]
        for col, ch in ctx["chars"].items():
            me = ch["body"].data
            labels = classify(ch["body"], nose)
            saved["bodies"][col] = ([m for m in me.materials], [p.material_index for p in me.polygons])
            base = len(me.materials)
            order = list(MASK_RGB)
            for k in order:
                me.materials.append(mats[k])
            for p in me.polygons:
                p.material_index = base + order.index(labels[p.index])
            counts[col] = {k: sum(1 for v in labels.values() if v == k) for k in order}
        mt.render_still(scene, path)
    finally:
        for col, (materials, indices) in saved["bodies"].items():
            me = ctx["chars"][col]["body"].data
            for p, i in zip(me.polygons, indices):
                p.material_index = i
            while len(me.materials) > len(materials):
                me.materials.pop()
        bg.inputs["Color"].default_value = saved["world"]
        scene.view_settings.view_transform, scene.view_settings.look = saved["view"], saved["look"]
        scene.eevee.taa_render_samples = saved["samples"]
        scene.render.dither_intensity = saved["dither"]
        scene.render.filter_size = saved["filter"]
        ctx["ground"].data.materials[0] = saved["ground"]
    return counts


def compare(ref_mask: Path, ref: Path, new: Path) -> dict:
    import numpy as np
    m, a, b = mt.load_px(ref_mask), mt.load_px(ref), mt.load_px(new)
    iso = mt.beauty_isolation(m, a, b)
    diff = np.abs(a[..., :3] - b[..., :3]).max(axis=2)
    return {**iso, "size_ref": list(a.shape[:2][::-1]), "size_new": list(b.shape[:2][::-1]),
            "pixels_differing": int((diff > 0).sum()), "max_anywhere_255": round(float(diff.max()) * 255, 2),
            "pixels_same_exactly": bool((diff == 0).all())}


def main() -> int:
    import importlib.util
    args = parse_args()
    repo = args.repo.resolve()
    spec = importlib.util.spec_from_file_location(
        "afs_mannequin", repo / "blender" / "scripts" / "author_assets" / "mannequin.py")
    M = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(M)
    nose = box_corners(*M.MARKER_A["nose"][:2])
    rel = lambda p: p if p.is_absolute() else repo / p
    rev3, out, private = rel(args.rev3), rel(args.out).resolve(), args.private.resolve()
    if out.name != OUT_NAME:
        return mt_refuse(f"writes only to a folder named {OUT_NAME}")
    for p in (out, private):
        if p.exists():
            return mt_refuse(f"{p} exists")
    if private == out or out in private.parents or private in out.parents:
        return mt_refuse("private must be outside the output folder and vice versa")
    if any(q.name in mt.PROTECTED for p in (out, private) for q in (p, *p.parents)):
        return mt_refuse(f"output and private folders must not be inside {mt.PROTECTED}")
    ref = mt.rev3_reference(rev3)
    if ref["errors"]:
        return mt_refuse(f"rev3 references failed verification: {ref['errors']}")
    ctx = build_marked(repo, private / "tmp_render")
    scene = ctx["scene"]
    scene.render.resolution_x, scene.render.resolution_y = 320, 180
    pose = {"pairing": ref["pairing"], "turns": ref["turns"]}
    (out / "reference").mkdir(parents=True)
    rows, label_counts = [], {}
    for cam in mt.CAMS:
        sid = ref["stills"][cam]["id"]
        mt.pose_still(ctx, pose, cam, 0)
        beauty, mask = out / "renders" / f"{sid}.png", private / "masks" / f"{sid}.png"
        mt.render_still(scene, beauty)
        label_counts[sid] = render_mask(ctx, mask, nose)
        shutil.copy2(rev3 / "stills" / "320" / f"{sid}.png", out / "reference" / f"{sid}.png")
        ref_mask = rev3 / "masks" / "320" / f"{sid}.png"
        for kind, a, b in (("beauty", rev3 / "stills" / "320" / f"{sid}.png", beauty), ("mask", ref_mask, mask)):
            res = compare(ref_mask, a, b)
            rows.append({"still": sid, "camera": cam, "kind": kind,
                         "reference_sha256": mt.sha256(a), "render_sha256": mt.sha256(b), **res})
            print(f"[gate3] {sid} {cam} {kind}: ok={res['ok']} max outside band {res['max_outside_255']}/255, "
                  f"max anywhere {res['max_anywhere_255']}/255, {res['pixels_differing']} px differ")
    ok = all(r["ok"] for r in rows)
    report = {"criterion": f"max difference outside a {mt.DILATE_PX} px dilation of the reference marker "
                           f"region <= {round(mt.BEAUTY_TOL * 255, 2)}/255 (8-bit levels, so at most 2)",
              "status": "pass" if ok else "fail", "assets": {k: v[0] for k, v in MARKED.items()},
              "harness_markers": 0, "renders": 4, "rows": rows,
              "rev3_files_read": ref["files_read"], "blender_version": bpy.app.version_string}
    (out / "equivalence_report.json").write_text(json.dumps(report, indent=1))
    (private / "gate3_private.json").write_text(json.dumps(
        {"rev3_reference": {k: v for k, v in ref.items() if k not in ("pairing", "turns")},
         "mask_label_polygons": label_counts}, indent=1))
    print(f"[gate3] equivalence {report['status']}")
    return 0 if ok else 1


def mt_refuse(msg: str) -> int:
    print(f"[gate3] REFUSED: {msg}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
