"""
inspect_asset.py — read-only structural report of an asset .blend, with a fingerprint.

    blender -b --factory-startup --python-exit-code 1 -P blender/scripts/inspect_asset.py -- \
        --blend <asset.blend> --out report.json \
        [--evaluate-actions <actions.blend> --armature RIG-x --frames 1,9,17 --repeat 2]

Starts from an empty factory scene and appends everything in --blend, the way
build_scene.py consumes assets; never renders, and never modifies or saves any .blend.

The report lists every datablock in the file by type ("contents", so stray texts, scenes or
images are visible) and, for the appended data, collections, objects, armatures (bones in
rest pose), meshes (counts, bounds, vertex-group weights), materials and actions (frame
range, slots, F-curves with every key). "fingerprint" is the SHA-256 of that structure as
canonical JSON, rounded to 6 decimals; it excludes file paths and the Blender version, so two
authoring runs of the same script produce the same fingerprint.

--evaluate-actions appends the actions from a second file, places each one alone as an NLA
strip on --armature (the way build_scene.place_actions does: strips.new at frame 1, repeat
--repeat) and reports the slot the strip got, its frame range, and evaluated world bone
heads/tails at --frames. Nothing is kept: the session is never saved.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import bpy

ID_TYPES = ("actions", "armatures", "brushes", "cameras", "collections", "curves", "fonts",
            "images", "lights", "materials", "meshes", "node_groups", "objects", "scenes",
            "texts", "textures", "worlds")
APPENDED = ("collections", "objects", "armatures", "meshes", "materials", "actions")


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser(prog="inspect_asset.py")
    p.add_argument("--blend", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--evaluate-actions", type=Path)
    p.add_argument("--armature")
    p.add_argument("--frames", default="")
    p.add_argument("--repeat", type=float, default=1.0)
    return p.parse_args(argv)


def r(v) -> float:
    return round(float(v), 6) + 0.0


def vec(v) -> list[float]:
    return [r(c) for c in v]


def contents(path: Path) -> dict[str, list[str]]:
    with bpy.data.libraries.load(str(path), link=False) as (src, _):
        return {t: sorted(getattr(src, t)) for t in ID_TYPES if getattr(src, t, None)}


def append_all(path: Path) -> None:
    with bpy.data.libraries.load(str(path), link=False) as (src, dst):
        for t in APPENDED:
            setattr(dst, t, list(getattr(src, t)))


def mesh_info(me) -> dict:
    me.calc_loop_triangles()
    co = [v.co for v in me.vertices]
    lo = [min(c[i] for c in co) for i in range(3)] if co else [0, 0, 0]
    hi = [max(c[i] for c in co) for i in range(3)] if co else [0, 0, 0]
    return {"vertices": len(me.vertices), "polygons": len(me.polygons),
            "triangles": len(me.loop_triangles), "bounds": [vec(lo), vec(hi)],
            "materials": [m.name if m else None for m in me.materials],
            "material_indices": sorted({p.material_index for p in me.polygons})}


def object_info(obj) -> dict:
    info = {"type": obj.type, "parent": obj.parent.name if obj.parent else None,
            "parent_type": obj.parent_type, "parent_bone": obj.parent_bone or None,
            "data": obj.data.name if obj.data else None,
            "matrix_world": [vec(row) for row in obj.matrix_world],
            "rotation_mode": obj.rotation_mode,
            "has_animation_data": obj.animation_data is not None,
            "modifiers": [{"type": m.type, "object": getattr(getattr(m, "object", None),
                                                           "name", None)}
                          for m in obj.modifiers],
            "constraints": [c.type for c in obj.constraints]}
    if obj.type == "MESH":
        names = [g.name for g in obj.vertex_groups]
        groups: dict[str, dict] = {n: {"vertices": 0, "weights": set()} for n in names}
        per_vertex = []
        for v in obj.data.vertices:
            per_vertex.append(len(v.groups))
            for g in v.groups:
                entry = groups[names[g.group]]
                entry["vertices"] += 1
                entry["weights"].add(r(g.weight))
        info["vertex_groups"] = {n: {"vertices": g["vertices"], "weights": sorted(g["weights"])}
                                 for n, g in groups.items()}
        info["groups_per_vertex"] = sorted(set(per_vertex))
    if obj.type == "ARMATURE":
        info["pose"] = {pb.name: {"rotation_mode": pb.rotation_mode,
                                  "location": vec(pb.location),
                                  "rotation_euler": vec(pb.rotation_euler),
                                  "scale": vec(pb.scale)} for pb in obj.pose.bones}
    return info


def armature_info(arm) -> dict:
    return {"bones": {b.name: {"parent": b.parent.name if b.parent else None,
                               "head": vec(b.head_local), "tail": vec(b.tail_local),
                               "connected": b.use_connect, "length": r(b.length),
                               "x_axis": vec(b.matrix_local.col[0].xyz),
                               "deform": b.use_deform} for b in arm.bones}}


def channelbags(act) -> list[tuple[str, object]]:
    out = []
    for layer in act.layers:
        for strip in layer.strips:
            for slot in act.slots:
                bag = strip.channelbag(slot)
                if bag:
                    out.append((slot.identifier, bag))
    return out


def action_info(act) -> dict:
    curves = {}
    for slot_id, bag in channelbags(act):
        for fc in bag.fcurves:
            curves[f"{slot_id}|{fc.data_path}[{fc.array_index}]"] = {
                "keys": [[r(k.co.x), r(k.co.y)] for k in fc.keyframe_points],
                "interpolation": sorted({k.interpolation for k in fc.keyframe_points}),
                "modifiers": [m.type for m in fc.modifiers],
                "group": fc.group.name if fc.group else None}
    return {"frame_range": vec(act.frame_range), "use_frame_range": act.use_frame_range,
            "use_cyclic": act.use_cyclic,
            "slots": [{"identifier": s.identifier, "target_id_type": s.target_id_type}
                      for s in act.slots],
            "layers": len(act.layers), "fcurves": dict(sorted(curves.items()))}


def evaluate(path: Path, armature: str, frames: list[int], repeat: float) -> dict:
    rig = bpy.data.objects.get(armature)
    if rig is None or rig.type != "ARMATURE":
        raise SystemExit(f"no armature {armature!r} in the inspected asset")
    scene = bpy.context.scene
    with bpy.data.libraries.load(str(path), link=False) as (src, dst):
        dst.actions = list(src.actions)
    out = {}
    ad = rig.animation_data_create()
    for act in dst.actions:
        for track in list(ad.nla_tracks):
            ad.nla_tracks.remove(track)
        strip = ad.nla_tracks.new().strips.new(act.name, 1, act)
        strip.repeat = repeat
        sampled = {}
        for f in frames:
            scene.frame_set(f)
            ev = rig.evaluated_get(bpy.context.evaluated_depsgraph_get())
            mw = ev.matrix_world
            sampled[str(f)] = {pb.name: {"head": vec(mw @ pb.head), "tail": vec(mw @ pb.tail)}
                               for pb in ev.pose.bones}
        out[act.name] = {"strip_slot": strip.action_slot.identifier if strip.action_slot else None,
                         "strip_frames": [r(strip.frame_start), r(strip.frame_end)],
                         "frames": sampled}
    return out


def main() -> None:
    args = parse_args()
    blend = args.blend.resolve()
    if not blend.is_file():
        raise SystemExit(f"no such file: {blend}")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    report = {"blend": str(blend), "blender_version": bpy.app.version_string,
              "contents": contents(blend)}
    append_all(blend)
    scene = bpy.context.scene
    for coll in bpy.data.collections:
        scene.collection.children.link(coll)
    bpy.context.view_layer.update()

    structure = {
        "contents": report["contents"],
        "collections": {c.name: sorted(o.name for o in c.objects) for c in bpy.data.collections},
        "objects": {o.name: object_info(o) for o in bpy.data.objects},
        "armatures": {a.name: armature_info(a) for a in bpy.data.armatures},
        "meshes": {m.name: mesh_info(m) for m in bpy.data.meshes},
        "materials": {m.name: {"diffuse_color": vec(m.diffuse_color)} for m in bpy.data.materials},
        "actions": {a.name: action_info(a) for a in bpy.data.actions},
    }
    canonical = json.dumps(structure, sort_keys=True, separators=(",", ":"))
    report.update(structure)
    report["fingerprint"] = hashlib.sha256(canonical.encode()).hexdigest()
    if args.evaluate_actions:
        frames = [int(x) for x in args.frames.split(",") if x]
        report["evaluated"] = evaluate(args.evaluate_actions.resolve(), args.armature, frames,
                                       args.repeat)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True))
    print(f"[inspect_asset] wrote {args.out} fingerprint {report['fingerprint']}")


if __name__ == "__main__":
    main()
