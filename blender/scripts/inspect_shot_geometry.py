"""
inspect_shot_geometry.py — read-only 2D geometry of a built shot, frame by frame (Milestone 8).

    blender -b <shot>.blend --factory-startup --python-exit-code 1 \
        -P blender/scripts/inspect_shot_geometry.py -- --out geometry.json \
        [--frames 1,85,124 | --step 2] [--reference]

Never renders, and never modifies or saves the .blend. For each sampled frame (after
scene.frame_set, so v1.3 timeline-marker cuts apply) it records, through the active camera:

  * the camera (world position and axes, lens, sensor, fit, shift, resolution, clipping) and
    the shot it belongs to (the latest CUT-<shot_id> marker at or before the frame);
  * for every visible mesh object, evaluated with its modifiers (armature deformation
    included): the convex outline of each connected mesh island, the outline of the whole
    object, and their depth ranges. Mannequin body parts and SceneSpec primitives are convex
    islands, so the union of island outlines is the exact silhouette;
  * for every armature: the head and tail of every pose bone.

Projection is done by workers/projection.py, the module the Shot QA worker uses; this script
only gathers evaluated geometry. --reference also projects every bone point and every mesh
vertex the renderer could show (at least clip_start in front of the camera) with Blender's own
bpy_extras world_to_camera_view and reports the largest differences: absolute x/y error for
points within REFERENCE_MARGIN of the frame, relative x/y error |difference| / max(1, |x or y|)
for all of them (far off-screen, coordinates grow as 1/depth and Blender's single-precision
matrices dominate), and absolute depth error. A verification mode; it is slow.

Objects are labelled with the SceneSpec name they were built from, using build_scene.py's
naming: PRIM-<name> for primitives, and objects under ROOT-<name> (characters, props,
environment). Coordinates: (0, 0) bottom-left and (1, 1) top-right of the frame; depth in
metres in front of the camera. Values are rounded to 6 decimals and keys sorted, so the same
.blend gives the same report.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from workers import projection as P                                    # noqa: E402

SCHEMA = "shot_geometry.v1"
REFERENCE_MARGIN = 0.5          # frame widths/heights beyond each edge counted as "near the frame"


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser(prog="inspect_shot_geometry.py")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--frames", default="", help="comma-separated frames (default: every --step)")
    p.add_argument("--step", type=int, default=1, help="sample every Nth frame of the scene")
    p.add_argument("--reference", action="store_true",
                   help="also measure the projection against world_to_camera_view")
    return p.parse_args(argv)


def owner_of(obj) -> tuple[str, str]:
    """(SceneSpec name, kind) of an object from build_scene.py's naming."""
    if obj.name.startswith("PRIM-"):
        return obj.name[len("PRIM-"):], "primitive"
    o = obj
    while o is not None:
        if o.name.startswith("ROOT-"):
            name = o.name[len("ROOT-"):]
            if name == "environment":
                return name, "environment"
            has_rig = any(c.type == "ARMATURE" for c in o.children_recursive)
            return name, "character" if has_rig else "prop"
        o = o.parent
    return obj.name, "other"


def camera_of(scene, cam_obj) -> P.Camera:
    m = cam_obj.matrix_world.normalized()
    data = cam_obj.data
    return P.Camera(
        location=tuple(m.translation),
        rotation=tuple(tuple(m[i][j] for j in range(3)) for i in range(3)),
        lens=data.lens, sensor_width=data.sensor_width, sensor_height=data.sensor_height,
        sensor_fit=data.sensor_fit, shift=(data.shift_x, data.shift_y),
        resolution=(scene.render.resolution_x, scene.render.resolution_y),
        pixel_aspect=(scene.render.pixel_aspect_x, scene.render.pixel_aspect_y),
        clip_start=data.clip_start, clip_end=data.clip_end)


def shot_at(scene, frame: int) -> str | None:
    cuts = [m for m in scene.timeline_markers if m.name.startswith("CUT-") and m.frame <= frame]
    return max(cuts, key=lambda m: m.frame).name[len("CUT-"):] if cuts else None


def island_labels(obj, groups: list[list[int]]) -> list[str]:
    """Vertex-group name of each island when every vertex of it belongs to the same one
    group (rigidly skinned parts), else island_<n>. Duplicates get a numeric suffix."""
    names = {g.index: g.name for g in obj.vertex_groups}
    labels = []
    for n, verts in enumerate(groups):
        owners = set()
        for v in verts:
            gs = obj.data.vertices[v].groups
            owners.add(names[gs[0].group] if len(gs) == 1 else None)
        labels.append(owners.pop() if len(owners) == 1 and None not in owners else f"island_{n}")
    seen: dict[str, int] = {}
    out = []
    for lab in labels:
        seen[lab] = seen.get(lab, 0) + 1
        out.append(lab if seen[lab] == 1 else f"{lab}.{seen[lab] - 1}")
    return out


def main() -> None:
    args = parse_args()
    scene = bpy.context.scene
    if args.frames:
        frames = [int(x) for x in args.frames.split(",") if x]
    else:
        frames = list(range(scene.frame_start, scene.frame_end + 1, max(1, args.step)))

    meshes = sorted((o for o in scene.objects if o.type == "MESH" and o.visible_get()),
                    key=lambda o: o.name)
    rigs = sorted((o for o in scene.objects if o.type == "ARMATURE"), key=lambda o: o.name)
    topology = {}
    for o in meshes:                                 # topology is fixed; deformation is not
        polys = [list(p.vertices) for p in o.data.polygons]
        groups = P.islands(len(o.data.vertices), polys)
        topology[o.name] = {"islands": groups, "labels": island_labels(o, groups)}

    report = {
        "schema": SCHEMA, "blend": bpy.data.filepath, "blender_version": bpy.app.version_string,
        "units": "frame coordinates: (0, 0) bottom-left, (1, 1) top-right; depth in metres "
                 "in front of the camera",
        "frame_range": [scene.frame_start, scene.frame_end], "frames_sampled": frames,
        "objects": {o.name: {"owner": owner_of(o)[0], "kind": owner_of(o)[1],
                             "vertices": len(o.data.vertices),
                             "islands": topology[o.name]["labels"]} for o in meshes},
        "armatures": {a.name: {"owner": owner_of(a)[0], "bones": sorted(b.name for b in a.pose.bones)}
                      for a in rigs},
        "frames": [],
    }
    ref = {"points": 0, "near_frame_points": 0, "near_frame_abs_xy": 0.0, "rel_xy": 0.0,
           "abs_depth": 0.0}

    def check(cam_obj, cam, world):
        if not args.reference:
            return
        mine = P.project(cam, world)
        if mine[2] < cam.clip_start:
            return
        theirs = world_to_camera_view(scene, cam_obj, Vector(world))
        ref["points"] += 1
        dxy = [abs(mine[i] - theirs[i]) for i in range(2)]
        ref["rel_xy"] = max(ref["rel_xy"], *(dxy[i] / max(1.0, abs(mine[i])) for i in range(2)))
        ref["abs_depth"] = max(ref["abs_depth"], abs(mine[2] - theirs[2]))
        if all(-REFERENCE_MARGIN <= mine[i] <= 1 + REFERENCE_MARGIN for i in range(2)):
            ref["near_frame_points"] += 1
            ref["near_frame_abs_xy"] = max(ref["near_frame_abs_xy"], *dxy)

    for f in frames:
        scene.frame_set(f)
        dg = bpy.context.evaluated_depsgraph_get()
        cam_obj = scene.camera.evaluated_get(dg)
        cam = camera_of(scene, cam_obj)
        entry = {"frame": f, "camera_object": scene.camera.name, "shot_id": shot_at(scene, f),
                 "camera": cam.to_dict(), "objects": {}, "armatures": {}}
        for o in meshes:
            ev = o.evaluated_get(dg)
            me = ev.to_mesh()
            try:
                mw = ev.matrix_world
                world = [tuple(mw @ v.co) for v in me.vertices]
                me.calc_loop_triangles()
                tris = [tuple(t.vertices) for t in me.loop_triangles]
            finally:
                ev.to_mesh_clear()
            whole = P.outline(cam, world, tris)
            if whole is None:
                continue
            tri_of = {}
            for t in tris:
                tri_of.setdefault(t[0], []).append(t)
            isl = {}
            for label, verts in zip(topology[o.name]["labels"], topology[o.name]["islands"]):
                vset = set(verts)
                local = {v: i for i, v in enumerate(verts)}
                ts = [tuple(local[i] for i in t) for v in verts for t in tri_of.get(v, ())
                      if all(i in vset for i in t)]
                out = P.outline(cam, [world[v] for v in verts], ts)
                if out is not None:
                    isl[label] = out
            whole["in_frame"] = P.polygon_overlaps_frame(whole["hull"])
            whole["islands"] = isl
            entry["objects"][o.name] = whole
            for w in world:
                check(cam_obj, cam, w)
        for a in rigs:
            ev = a.evaluated_get(dg)
            mw = ev.matrix_world
            bones = {}
            for pb in ev.pose.bones:
                head, tail = mw @ pb.head, mw @ pb.tail
                bones[pb.name] = {"head": P.rounded_point(P.project(cam, tuple(head))),
                                  "tail": P.rounded_point(P.project(cam, tuple(tail)))}
                check(cam_obj, cam, tuple(head))
                check(cam_obj, cam, tuple(tail))
            entry["armatures"][a.name] = bones
        report["frames"].append(entry)

    if args.reference:
        report["reference"] = {
            "margin": REFERENCE_MARGIN, "points": ref["points"],
            "near_frame_points": ref["near_frame_points"],
            "max_near_frame_abs_xy_error": float(f"{ref['near_frame_abs_xy']:.3e}"),
            "max_rel_xy_error": float(f"{ref['rel_xy']:.3e}"),
            "max_abs_depth_error": float(f"{ref['abs_depth']:.3e}")}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, sort_keys=True))
    print(f"[inspect_shot_geometry] wrote {args.out} ({len(frames)} frames)")


if __name__ == "__main__":
    main()
