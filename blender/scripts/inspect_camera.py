"""
inspect_camera.py — read-only report of the evaluated shot camera in a saved .blend.

    blender -b <shot>.blend --factory-startup --python-exit-code 1 \
        -P blender/scripts/inspect_camera.py -- --out camera.json --frames 1,48,96 \
        --project PRIM-pedestal,AIM-pedestal

Never renders and never modifies or saves the .blend. For each requested frame it writes the
evaluated camera (after constraints and F-curve modifiers): world position, view and up
vectors, lens, clipping, shift and depth of field, plus where each --project object's world
origin lands in normalised camera coordinates (0,0 = bottom-left, 1,1 = top-right of the
rendered frame, as bpy_extras.object_utils.world_to_camera_view defines them).

--camera chooses what to inspect:
    CAM-shot (default)  the single-camera shot camera; output exactly as before
    <name>              any other camera object by name, fixed for every frame
    active              v1.3 multi-shot: after scene.frame_set(f), whichever camera the
                        timeline markers made active (scene.camera). Adds "markers",
                        "cameras" and a per-frame "active_camera". frame_set is required:
                        assigning scene.frame_current does not switch marker cameras.

Used by tests/test_camera_builder.py and tests/test_multishot_builder.py to pin what
build_scene.py actually builds.
"""
import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view

CAMERA_NAME = "CAM-shot"


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser(prog="inspect_camera.py")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--frames", required=True, help="comma-separated frame numbers")
    p.add_argument("--project", default="", help="comma-separated object names to project")
    p.add_argument("--camera", default=CAMERA_NAME,
                   help=f"camera object name, or 'active' (default {CAMERA_NAME})")
    return p.parse_args(argv)


def vec(v) -> list[float]:
    return [round(float(c), 6) for c in v]


def camera_info(cam) -> dict:
    data = cam.data
    return {
        "type": data.type, "sensor_width": round(data.sensor_width, 6),
        "sensor_fit": data.sensor_fit, "rotation_mode": cam.rotation_mode,
        "parent": cam.parent.name if cam.parent else None,
        "constraints": [{"type": c.type, "target": c.target.name if c.target else None,
                         "track_axis": getattr(c, "track_axis", None),
                         "up_axis": getattr(c, "up_axis", None)} for c in cam.constraints],
        "dof_focus_object": data.dof.focus_object.name if data.dof.focus_object else None,
    }


def main() -> None:
    args = parse_args()
    scene = bpy.context.scene
    active_mode = args.camera == "active"
    if active_mode:
        if not scene.timeline_markers or scene.camera is None:
            raise SystemExit(f"--camera active needs timeline markers and a scene camera in "
                             f"{bpy.data.filepath}")
        fixed = None
    else:
        fixed = bpy.data.objects.get(args.camera)
        if fixed is None or fixed.type != "CAMERA":
            raise SystemExit(f"no camera object {args.camera!r} in {bpy.data.filepath}")
    names = [n for n in args.project.split(",") if n]
    missing = [n for n in names if bpy.data.objects.get(n) is None]
    if missing:
        raise SystemExit(f"objects not found: {missing}")

    out = {
        "blend": bpy.data.filepath,
        "scene_camera": scene.camera.name if scene.camera else None,
        "resolution": [scene.render.resolution_x, scene.render.resolution_y,
                       scene.render.resolution_percentage],
        "camera": camera_info(fixed) if fixed else None,
        "frames": [],
    }
    if active_mode:
        markers = sorted(scene.timeline_markers, key=lambda m: m.frame)
        out["markers"] = [{"name": m.name, "frame": m.frame,
                           "camera": m.camera.name if m.camera else None} for m in markers]
        out["cameras"] = {m.camera.name: camera_info(m.camera) for m in markers if m.camera}
    for f in (int(x) for x in args.frames.split(",")):
        scene.frame_set(f)
        depsgraph = bpy.context.evaluated_depsgraph_get()
        cam = scene.camera if active_mode else fixed
        ev = cam.evaluated_get(depsgraph)
        m = ev.matrix_world
        data = ev.data                                   # animated lens etc. at this frame
        frame = {
            "frame": f,
            "location": vec(m.translation),
            "view_dir": vec(-m.col[2].xyz.normalized()),     # cameras look down local -Z
            "up_dir": vec(m.col[1].xyz.normalized()),
            "rotation_euler_deg": vec(math.degrees(a) for a in m.to_euler("XYZ")),
            "lens": round(data.lens, 6),
            "clip_start": round(data.clip_start, 6), "clip_end": round(data.clip_end, 6),
            "shift": [round(data.shift_x, 6), round(data.shift_y, 6)],
            "dof": {"use": data.dof.use_dof, "fstop": round(data.dof.aperture_fstop, 6),
                    "focus_distance": round(data.dof.focus_distance, 6)},
            "projected": {},
        }
        if active_mode:
            frame["active_camera"] = cam.name
        for n in names:
            obj = bpy.data.objects[n].evaluated_get(depsgraph)
            p = world_to_camera_view(scene, ev, obj.matrix_world.translation)
            frame["projected"][n] = vec(p)        # x, y normalised; z = depth along view (m)
        out["frames"].append(frame)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2))
    print(f"[inspect_camera] wrote {args.out}")


if __name__ == "__main__":
    main()
