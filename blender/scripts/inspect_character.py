"""
inspect_character.py — read-only report of the characters and props in a built shot .blend.

    blender -b <shot>.blend --factory-startup --python-exit-code 1 \
        -P blender/scripts/inspect_character.py -- --out characters.json --frames 1,40,80 \
        [--objects ROOT-baton,AIM-sh01_wide-hero] [--isolate-tracks]

Never renders, and never modifies or saves the .blend. Reports, for every armature in the
scene: its NLA tracks and strips as build_scene.place_actions made them, and at each frame the
evaluated local pose channels (rotation_euler, location) and world head/tail of every bone.
For each --objects name it reports the evaluated world matrix at each frame, and for every
frame the active camera (after frame_set, so v1.3 marker cuts apply).

--isolate-tracks additionally evaluates each NLA track alone (all other tracks muted, in
memory only) so a test can check how strips combine during a crossfade.

Used by tests/test_character_builder.py to pin what build_scene.py actually builds.
"""
import argparse
import json
import sys
from pathlib import Path

import bpy


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser(prog="inspect_character.py")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--frames", required=True, help="comma-separated frame numbers")
    p.add_argument("--objects", default="", help="comma-separated object names")
    p.add_argument("--isolate-tracks", action="store_true")
    return p.parse_args(argv)


def r(v) -> float:
    return round(float(v), 6) + 0.0


def vec(v) -> list[float]:
    return [r(c) for c in v]


def nla_info(arm) -> dict:
    ad = arm.animation_data
    if ad is None:
        return {"action": None, "tracks": []}
    tracks = []
    for t in ad.nla_tracks:
        tracks.append({"name": t.name, "mute": t.mute, "strips": [{
            "name": s.name, "action": s.action.name if s.action else None,
            "action_library": s.action.library.filepath if s.action and s.action.library else None,
            "slot": s.action_slot.identifier if s.action_slot else None,
            "frame_start": r(s.frame_start), "frame_end": r(s.frame_end),
            "action_frame_start": r(s.action_frame_start),
            "action_frame_end": r(s.action_frame_end),
            "scale": r(s.scale), "repeat": r(s.repeat), "blend_in": r(s.blend_in),
            "blend_out": r(s.blend_out), "extrapolation": s.extrapolation,
            "blend_type": s.blend_type, "use_auto_blend": s.use_auto_blend,
            "influence": r(s.influence), "use_animated_influence": s.use_animated_influence,
        } for s in t.strips]})
    return {"action": ad.action.name if ad.action else None, "tracks": tracks}


def pose_at(arm) -> dict:
    ev = arm.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mw = ev.matrix_world
    return {pb.name: {"rotation_euler": vec(pb.rotation_euler), "location": vec(pb.location),
                      "head": vec(mw @ pb.head), "tail": vec(mw @ pb.tail),
                      "matrix_world": [vec(row) for row in (mw @ pb.matrix)]}
            for pb in ev.pose.bones}


def sample(scene, frames, armatures, objects) -> dict:
    out = {}
    for f in frames:
        scene.frame_set(f)
        dg = bpy.context.evaluated_depsgraph_get()
        out[str(f)] = {
            "active_camera": scene.camera.name if scene.camera else None,
            "armatures": {a.name: pose_at(a) for a in armatures},
            "objects": {o.name: [vec(row) for row in o.evaluated_get(dg).matrix_world]
                        for o in objects},
        }
    return out


def main() -> None:
    args = parse_args()
    scene = bpy.context.scene
    frames = [int(x) for x in args.frames.split(",") if x]
    names = [n for n in args.objects.split(",") if n]
    missing = [n for n in names if bpy.data.objects.get(n) is None]
    if missing:
        raise SystemExit(f"objects not found: {missing}")
    objects = [bpy.data.objects[n] for n in names]
    armatures = sorted((o for o in scene.objects if o.type == "ARMATURE"), key=lambda o: o.name)

    report = {
        "blend": bpy.data.filepath,
        "actions": sorted(a.name for a in bpy.data.actions),
        "armatures": {a.name: {"parent": a.parent.name if a.parent else None,
                               "nla": nla_info(a)} for a in armatures},
        "frames": sample(scene, frames, armatures, objects),
    }
    if args.isolate_tracks:
        isolated = {}
        for arm in armatures:
            tracks = list(arm.animation_data.nla_tracks) if arm.animation_data else []
            saved = [t.mute for t in tracks]
            per_track = {}
            try:
                for keep in tracks:
                    for t in tracks:
                        t.mute = t is not keep
                    poses = {}
                    for f in frames:
                        scene.frame_set(f)
                        poses[str(f)] = pose_at(arm)
                    per_track[keep.name] = poses
            finally:
                for t, m in zip(tracks, saved):
                    t.mute = m
            isolated[arm.name] = per_track
        report["isolated"] = isolated

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True))
    print(f"[inspect_character] wrote {args.out}")


if __name__ == "__main__":
    main()
