"""
build_scene.py — turn one validated SceneSpec JSON into a Blender shot and render it.

Run headless, always starting from the style template (never edit the template itself):

    blender -b blender/templates/spring_style.blend --python-exit-code 1 \
        -P blender/scripts/build_scene.py -- \
        --spec storage/projects/demo/specs/sc01_sh01.json \
        --assets-root assets \
        --out storage/projects/demo/shots/sc01_sh01

Outputs in --out:
    <shot_id>.blend         the assembled shot (open it to debug)
    frames/<shot_id>_####.png
    build_report.json       status, warnings, timings, peak memory — read by the worker

Pass --smoke to render only the first 8 frames at 50% resolution (a quick, low-memory
check of the real shot before a full render).

The spec MUST already be validated by apps/api/schemas/scene_spec.py
(Blender's bundled Python has no pydantic). This script only does light sanity checks.
Spec 1.0 shots are built from library assets; 1.1 adds procedural primitives
(bmesh geometry + Principled BSDF materials) that need no asset files.
Tested against the Blender 4.2+ API; version differences (Eevee Next, layered actions,
video media types) are handled by the small compatibility helpers below.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
import traceback
from pathlib import Path

import bmesh
import bpy
from mathutils import Euler

SUPPORTED_SPECS = ("1.0", "1.1")
SHOT_COLLECTION = "SHOT"
SMOKE_FRAMES = 8

EASING = {"linear": "LINEAR", "ease_in_out": "BEZIER", "constant": "CONSTANT"}

# elevation°, azimuth°, strength, RGB colour — used when the template has no LGT-<preset>
LIGHT_PRESETS = {
    "golden_hour": (8.0, 250.0, 3.0, (1.00, 0.72, 0.45)),
    "overcast":    (45.0, 180.0, 0.6, (0.90, 0.93, 1.00)),
    "midday":      (62.0, 160.0, 4.5, (1.00, 0.97, 0.92)),
    "blue_hour":   (2.0, 270.0, 0.3, (0.55, 0.65, 1.00)),
    "night":       (35.0, 120.0, 0.08, (0.50, 0.60, 1.00)),
}


class BuildError(RuntimeError):
    """A spec/asset problem the worker should report back (not a Blender crash)."""


class Report:
    def __init__(self, shot_id: str):
        self.data = {"shot_id": shot_id, "status": "running", "warnings": [],
                     "blender_version": bpy.app.version_string, "timings": {}}
        self._t = time.time()

    def warn(self, msg: str) -> None:
        print(f"[build_scene] WARNING: {msg}")
        self.data["warnings"].append(msg)

    def lap(self, name: str) -> None:
        now = time.time()
        self.data["timings"][name] = round(now - self._t, 2)
        self._t = now

    def write(self, out: Path) -> None:
        self.data["memory_mb"] = peak_memory_mb()
        out.mkdir(parents=True, exist_ok=True)
        (out / "build_report.json").write_text(json.dumps(self.data, indent=2))


def peak_memory_mb() -> dict | None:
    """Peak RAM of this Blender process so far, for watching low-memory machines."""
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                    (n, ctypes.c_size_t) for n in (
                        "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                        "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                        "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]

            c = Counters()
            c.cb = ctypes.sizeof(Counters)
            kernel32 = ctypes.windll.kernel32
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            get_info = ctypes.windll.psapi.GetProcessMemoryInfo
            get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            get_info.restype = wintypes.BOOL
            if not get_info(kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb):
                return None
            return {"peak_working_set": round(c.PeakWorkingSetSize / 2**20, 1),
                    "peak_committed": round(c.PeakPagefileUsage / 2**20, 1)}
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return {"peak_working_set": round(peak / (2**20 if sys.platform == "darwin" else 2**10), 1)}
    except Exception:  # noqa: BLE001 — memory stats are diagnostic only
        return None


# ---------------------------------------------------------------------------
# Compatibility helpers
# ---------------------------------------------------------------------------
def eevee_engine_id(scene) -> str:
    items = {i.identifier for i in scene.render.bl_rna.properties["engine"].enum_items}
    return "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in items else "BLENDER_EEVEE"


def fcurves_of(id_data) -> list:
    """F-curves of an ID's active action, for both legacy and layered (4.4+) actions."""
    ad = getattr(id_data, "animation_data", None)
    if not ad or not ad.action:
        return []
    action = ad.action
    slot = getattr(ad, "action_slot", None)
    if slot is not None and getattr(action, "layers", None):
        curves = []
        for layer in action.layers:
            for strip in layer.strips:
                try:
                    bag = strip.channelbag(slot)
                except (AttributeError, TypeError):
                    bag = None
                if bag:
                    curves.extend(bag.fcurves)
        if curves:
            return curves
    return list(getattr(action, "fcurves", []))


def set_key_interpolation(id_data, frame: int, easing: str) -> None:
    interp = EASING.get(easing, "BEZIER")
    for fc in fcurves_of(id_data):
        for kp in fc.keyframe_points:
            if abs(kp.co.x - frame) < 0.5:
                kp.interpolation = interp


def add_noise(id_data, data_path: str, strength: float, scale: float, seed: int) -> None:
    rng = random.Random(seed)
    for fc in fcurves_of(id_data):
        if fc.data_path == data_path:
            mod = fc.modifiers.new("NOISE")
            mod.strength = strength
            mod.scale = scale
            mod.phase = rng.uniform(0, 100)


# ---------------------------------------------------------------------------
# Asset loading
# ---------------------------------------------------------------------------
class Library:
    def __init__(self, root: Path, manifest: dict):
        self.root = root
        self.assets = {a["id"]: a for a in manifest["assets"]}
        self.actions = {a["id"]: a for a in manifest["actions"]}
        self._action_cache: dict[tuple[str, str], bpy.types.Action] = {}

    def asset(self, asset_id: str) -> dict:
        if asset_id not in self.assets:
            raise BuildError(f"asset '{asset_id}' not in manifest")
        return self.assets[asset_id]

    def path(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if not p.exists():
            raise BuildError(f"asset file missing: {p}")
        return p

    def append_collection(self, asset_id: str) -> bpy.types.Collection:
        entry = self.asset(asset_id)
        blend, name = self.path(entry["file"]), entry.get("collection")
        if not name:
            raise BuildError(f"asset '{asset_id}' has no collection to append")
        with bpy.data.libraries.load(str(blend), link=False) as (src, dst):
            if name not in src.collections:
                raise BuildError(f"collection '{name}' not found in {blend.name}; "
                                 f"available: {list(src.collections)[:20]}")
            dst.collections = [name]
        return dst.collections[0]

    def action(self, action_id: str) -> tuple[bpy.types.Action, dict]:
        if action_id not in self.actions:
            raise BuildError(f"action '{action_id}' not in manifest")
        entry = self.actions[action_id]
        key = (entry["file"], entry["action_name"])
        if key not in self._action_cache:
            blend = self.path(entry["file"])
            with bpy.data.libraries.load(str(blend), link=False) as (src, dst):
                if entry["action_name"] not in src.actions:
                    raise BuildError(f"action '{entry['action_name']}' not in {blend.name}")
                dst.actions = [entry["action_name"]]
            act = dst.actions[0]
            act.use_fake_user = True
            self._action_cache[key] = act
        return self._action_cache[key], entry


# ---------------------------------------------------------------------------
# Scene building blocks
# ---------------------------------------------------------------------------
def shot_collection(scene) -> bpy.types.Collection:
    coll = bpy.data.collections.get(SHOT_COLLECTION)
    if coll is None:
        coll = bpy.data.collections.new(SHOT_COLLECTION)
        scene.collection.children.link(coll)
    return coll


def make_empty(name: str, coll, size: float = 0.5) -> bpy.types.Object:
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_size = size
    coll.objects.link(obj)
    return obj


def apply_transform(obj, t: dict) -> None:
    obj.location = t.get("location", [0, 0, 0])
    obj.rotation_euler = Euler([math.radians(d) for d in t.get("rotation_deg", [0, 0, 0])])
    s = t.get("scale", 1.0)
    obj.scale = (s, s, s)


def instance_asset(lib: Library, name: str, asset_id: str, shot_coll) -> tuple:
    """Append an asset collection and put everything under one ROOT empty we control."""
    coll = lib.append_collection(asset_id)
    shot_coll.children.link(coll)
    root = make_empty(f"ROOT-{name}", shot_coll)
    for obj in coll.all_objects:
        if obj.parent is None:
            obj.parent = root
            obj.matrix_parent_inverse = root.matrix_world.inverted()
    return root, coll


def find_armature(coll, wanted: str | None):
    arms = [o for o in coll.all_objects if o.type == "ARMATURE"]
    if wanted:
        for o in arms:
            if o.name == wanted or o.name.startswith(wanted + "."):
                return o
    return arms[0] if arms else None


def key_motion_path(root, keys: list[dict]) -> None:
    for k in keys:
        f = k["frame"]
        root.location = k["location"]
        root.keyframe_insert("location", frame=f)
        if k.get("rotation_z_deg") is not None:
            root.rotation_euler.z = math.radians(k["rotation_z_deg"])
            root.keyframe_insert("rotation_euler", index=2, frame=f)
    for k in keys:
        set_key_interpolation(root, k["frame"], k.get("easing", "ease_in_out"))


def place_actions(lib: Library, arm, char: dict, report: Report) -> None:
    """One NLA track per clip, stacked in time order: later clips override earlier ones,
    blend_in crossfades, HOLD_FORWARD prevents gaps falling back to the rest pose."""
    ad = arm.animation_data or arm.animation_data_create()
    ad.action = None
    for track in list(ad.nla_tracks):
        ad.nla_tracks.remove(track)

    clips = sorted(char["actions"], key=lambda c: c["start_frame"])
    for i, clip in enumerate(clips):
        action, entry = lib.action(clip["action_id"])
        start, end = clip["start_frame"], clip["end_frame"]
        speed = clip.get("speed", 1.0)

        track = ad.nla_tracks.new()
        track.name = f"{i:02d}_{clip['action_id']}"
        strip = track.strips.new(clip["action_id"], int(start), action)

        if hasattr(strip, "action_slot") and strip.action_slot is None:
            slots = getattr(action, "slots", None)
            if slots and len(slots):
                try:
                    strip.action_slot = slots[0]
                except (AttributeError, TypeError):
                    report.warn(f"could not assign action slot for {clip['action_id']}")

        src_len = max(1.0, action.frame_range[1] - action.frame_range[0])
        strip.scale = 1.0 / speed
        wanted = end - start
        repeat = wanted / (src_len * strip.scale)
        if not entry.get("loopable", False) and repeat > 1.0:
            report.warn(f"{char['name']}: '{clip['action_id']}' is not loopable; "
                        f"holding its last pose for {int(wanted - src_len * strip.scale)} frames")
            repeat = 1.0
        strip.repeat = max(0.1, repeat)

        strip.use_auto_blend = False
        strip.blend_in = min(clip.get("blend_in", 6), (strip.frame_end - strip.frame_start) / 2)
        strip.extrapolation = "HOLD" if i == 0 else "HOLD_FORWARD"
        strip.blend_type = "REPLACE"


def setup_world(scene, lib: Library, env: dict) -> None:
    hdri_id, fog = env.get("hdri_id"), env.get("fog_density", 0.0)
    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    nt = world.node_tree

    if hdri_id:
        entry = lib.asset(hdri_id)
        img = bpy.data.images.load(str(lib.path(entry["file"])), check_existing=True)
        nt.nodes.clear()
        out = nt.nodes.new("ShaderNodeOutputWorld")
        bg = nt.nodes.new("ShaderNodeBackground")
        tex = nt.nodes.new("ShaderNodeTexEnvironment")
        mapping = nt.nodes.new("ShaderNodeMapping")
        coord = nt.nodes.new("ShaderNodeTexCoord")
        tex.image = img
        bg.inputs["Strength"].default_value = env.get("hdri_strength", 1.0)
        mapping.inputs["Rotation"].default_value[2] = math.radians(env.get("hdri_rotation_deg", 0.0))
        nt.links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
        nt.links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
        nt.links.new(tex.outputs["Color"], bg.inputs["Color"])
        nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    elif env.get("world_color"):
        nt.nodes.clear()
        out = nt.nodes.new("ShaderNodeOutputWorld")
        bg = nt.nodes.new("ShaderNodeBackground")
        bg.inputs["Color"].default_value = (*env["world_color"], 1.0)
        nt.links.new(bg.outputs["Background"], out.inputs["Surface"])

    if fog > 0:
        out = next((n for n in nt.nodes if n.bl_idname == "ShaderNodeOutputWorld"), None)
        if out is None:
            out = nt.nodes.new("ShaderNodeOutputWorld")
        vol = nt.nodes.new("ShaderNodeVolumeScatter")
        vol.inputs["Density"].default_value = fog
        nt.links.new(vol.outputs["Volume"], out.inputs["Volume"])


def setup_lighting(scene, shot_coll, lighting: dict, report: Report) -> None:
    preset = lighting.get("preset", "golden_hour")
    scene.view_settings.exposure = lighting.get("exposure", 0.0)

    # Prefer hand-built light rigs in the template: collections named LGT-<preset>
    rigs = [c for c in bpy.data.collections if c.name.startswith("LGT-")]
    if rigs:
        found = False
        for layer_coll in scene.view_layers[0].layer_collection.children:
            if layer_coll.name.startswith("LGT-"):
                layer_coll.exclude = layer_coll.name != f"LGT-{preset}"
                found |= layer_coll.name == f"LGT-{preset}"
        if found and all(lighting.get(k) is None for k in
                         ("sun_elevation_deg", "sun_azimuth_deg", "sun_strength")):
            return
        if not found:
            report.warn(f"template has no LGT-{preset}; using procedural sun")

    elev, az, strength, color = LIGHT_PRESETS[preset]
    elev = lighting.get("sun_elevation_deg") if lighting.get("sun_elevation_deg") is not None else elev
    az = lighting.get("sun_azimuth_deg") if lighting.get("sun_azimuth_deg") is not None else az
    strength = lighting.get("sun_strength") if lighting.get("sun_strength") is not None else strength

    sun_data = bpy.data.lights.new("SUN-shot", "SUN")
    sun_data.energy = strength
    sun_data.color = color
    sun_data.angle = math.radians(1.5)
    sun = bpy.data.objects.new("SUN-shot", sun_data)
    shot_coll.objects.link(sun)
    sun.rotation_euler = Euler((math.radians(90 - elev), 0, math.radians(az)))


def primitive_mesh(name: str, shape: str, size: float) -> bpy.types.Mesh:
    """Geometry is centred on the object origin; size = edge / diameter / height."""
    bm = bmesh.new()
    r = size / 2
    if shape == "cube":
        bmesh.ops.create_cube(bm, size=size)
    elif shape == "sphere":
        bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=r)
    elif shape in ("cylinder", "cone"):
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=32, radius1=r,
                              radius2=r if shape == "cylinder" else 0.0, depth=size)
    elif shape == "plane":
        bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=r)
    else:
        bm.free()
        raise BuildError(f"unknown primitive shape '{shape}'")
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    if shape == "sphere":
        for poly in mesh.polygons:
            poly.use_smooth = True
    return mesh


def primitive_material(name: str, m: dict, report: Report) -> bpy.types.Material:
    color = (*m.get("base_color", [0.8, 0.8, 0.8]), 1.0)
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color                  # viewport / Workbench colour
    if mat.node_tree is None:
        mat.use_nodes = True
    bsdf = next((n for n in mat.node_tree.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled"), None)
    if bsdf is None:
        report.warn(f"{name}: no Principled BSDF node; using viewport colour only")
        return mat
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = m.get("roughness", 0.5)
    bsdf.inputs["Metallic"].default_value = m.get("metallic", 0.0)
    return mat


def key_primitive(obj, keys: list[dict]) -> None:
    for k in keys:
        f = k["frame"]
        if k.get("location") is not None:
            obj.location = k["location"]
            obj.keyframe_insert("location", frame=f)
        if k.get("rotation_deg") is not None:
            obj.rotation_euler = Euler([math.radians(d) for d in k["rotation_deg"]])
            obj.keyframe_insert("rotation_euler", frame=f)
        if k.get("scale") is not None:
            obj.scale = k["scale"]
            obj.keyframe_insert("scale", frame=f)
    for k in keys:
        set_key_interpolation(obj, k["frame"], k.get("easing", "ease_in_out"))


def build_primitives(prims: list[dict], shot_coll, report: Report) -> dict[str, bpy.types.Object]:
    objs = {}
    for p in prims:
        name = p["name"]
        mesh = primitive_mesh(f"PRIM-{name}", p["shape"], p.get("size", 1.0))
        mesh.materials.append(primitive_material(f"MAT-{name}", p.get("material", {}), report))
        obj = bpy.data.objects.new(f"PRIM-{name}", mesh)
        obj["afs_primitive"] = p["shape"]
        shot_coll.objects.link(obj)
        apply_transform(obj, p.get("transform", {}))
        key_primitive(obj, p.get("keys", []))
        objs[name] = obj
    return objs


def aim_target(name: str, roots: dict, height: float, shot_coll) -> bpy.types.Object:
    if name not in roots:
        raise BuildError(f"camera target '{name}' does not exist in this shot")
    aim = bpy.data.objects.get(f"AIM-{name}")
    if aim is None:
        aim = make_empty(f"AIM-{name}", shot_coll, 0.2)
        target = roots[name]
        if target.get("afs_primitive"):
            # follow position only, so a spinning or squashing primitive doesn't swing the aim
            con = aim.constraints.new("COPY_LOCATION")
            con.target = target
            con.use_offset = True
        else:
            aim.parent = target
        aim.location = (0, 0, height)
    return aim


def setup_camera(scene, shot_coll, cam_spec: dict, roots: dict, seed: int) -> None:
    data = bpy.data.cameras.new("CAM-shot")
    data.lens = cam_spec.get("lens_mm", 35)
    data.sensor_width = 36
    cam = bpy.data.objects.new("CAM-shot", data)
    shot_coll.objects.link(cam)
    scene.camera = cam

    look_at = cam_spec.get("look_at")
    height = cam_spec.get("look_at_height", 1.3)
    for k in cam_spec["keys"]:
        f = k["frame"]
        cam.location = k["location"]
        cam.keyframe_insert("location", frame=f)
        if not look_at and k.get("rotation_deg"):
            cam.rotation_euler = Euler([math.radians(d) for d in k["rotation_deg"]])
            cam.keyframe_insert("rotation_euler", frame=f)
        if k.get("lens_mm"):
            data.lens = k["lens_mm"]
            data.keyframe_insert("lens", frame=f)
    for k in cam_spec["keys"]:
        set_key_interpolation(cam, k["frame"], k.get("easing", "ease_in_out"))
        set_key_interpolation(data, k["frame"], k.get("easing", "ease_in_out"))

    shake = cam_spec.get("handheld_shake", 0.0)
    if look_at:
        aim = aim_target(look_at, roots, height, shot_coll)
        con = cam.constraints.new("TRACK_TO")
        con.target = aim
        con.track_axis = "TRACK_NEGATIVE_Z"
        con.up_axis = "UP_Y"
        if shake > 0:
            # shake the aim point, not the camera, so tracking stays stable
            aim.keyframe_insert("location", frame=scene.frame_start)
            add_noise(aim, "location", strength=0.08 * shake, scale=18, seed=seed)
    elif shake > 0:
        if not fcurves_of(cam) or not any(fc.data_path == "rotation_euler" for fc in fcurves_of(cam)):
            cam.keyframe_insert("rotation_euler", frame=scene.frame_start)
        add_noise(cam, "rotation_euler", strength=0.012 * shake, scale=18, seed=seed)

    data.dof.use_dof = cam_spec.get("dof_enabled", True)
    focus = cam_spec.get("focus_target") or look_at
    if data.dof.use_dof and focus:
        data.dof.focus_object = aim_target(focus, roots, height, shot_coll)
        data.dof.aperture_fstop = cam_spec.get("fstop", 2.8)


def setup_render(scene, r: dict, shot_id: str, out: Path) -> None:
    animatic = r.get("quality", "animatic") == "animatic"
    engine = "eevee" if animatic else r.get("engine", "eevee")
    samples = min(r.get("samples", 64), 16) if animatic else r.get("samples", 64)

    scene.render.engine = eevee_engine_id(scene) if engine == "eevee" else "CYCLES"
    if engine == "eevee":
        scene.eevee.taa_render_samples = samples
    else:
        scene.cycles.samples = samples
        scene.cycles.seed = r.get("seed", 0)
        scene.cycles.use_denoising = True

    w, h = r.get("resolution", [1920, 1080])
    scene.render.resolution_x, scene.render.resolution_y = w, h
    scene.render.resolution_percentage = 50 if animatic else 100
    scene.render.fps, scene.render.fps_base = r.get("fps", 24), 1.0
    scene.frame_start, scene.frame_end = r["frame_start"], r["frame_end"]
    scene.frame_set(r["frame_start"])

    blur = r.get("motion_blur", True) and not animatic
    if hasattr(scene.render, "use_motion_blur"):
        scene.render.use_motion_blur = blur
    elif hasattr(scene.eevee, "use_motion_blur"):
        scene.eevee.use_motion_blur = blur

    # Render a PNG sequence; the FFmpeg worker encodes. Frames are resumable and
    # avoid Blender's version-specific video settings.
    img = scene.render.image_settings
    if hasattr(img, "media_type"):
        img.media_type = "IMAGE"
    img.file_format = "PNG"
    img.color_mode = "RGB"
    img.color_depth = "8" if animatic else "16"
    (out / "frames").mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(out / "frames" / f"{shot_id}_####")
    scene.render.use_overwrite = not animatic
    scene.render.use_placeholder = False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser(prog="build_scene.py")
    p.add_argument("--spec", required=True, type=Path)
    p.add_argument("--assets-root", default=Path("assets"), type=Path)
    p.add_argument("--manifest", type=Path, help="defaults to <assets-root>/manifest.json")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--no-render", action="store_true", help="build and save .blend only")
    p.add_argument("--smoke", action="store_true",
                   help=f"render only the first {SMOKE_FRAMES} frames at 50%% resolution")
    return p.parse_args(argv)


def build(args: argparse.Namespace, report: Report, spec: dict) -> None:
    if spec.get("spec_version", "1.0") not in SUPPORTED_SPECS:
        raise BuildError(f"spec_version {spec.get('spec_version')} not in {SUPPORTED_SPECS}")
    if not bpy.data.filepath:
        report.warn("no style template loaded; starting from an empty scene")
        bpy.ops.wm.read_factory_settings(use_empty=True)

    root = args.assets_root.resolve()
    manifest = json.loads((args.manifest or root / "manifest.json").read_text())
    lib = Library(root, manifest)
    scene = bpy.context.scene
    shot_coll = shot_collection(scene)
    seed = spec["render"].get("seed", 0)
    out = args.out.resolve()

    setup_render(scene, spec["render"], spec["shot_id"], out)
    if args.smoke:
        scene.frame_end = min(scene.frame_end, scene.frame_start + SMOKE_FRAMES - 1)
        scene.render.resolution_percentage = 50
        report.data["smoke"] = True
    report.lap("render_setup")

    env = spec["environment"]
    if env.get("asset_id"):
        instance_asset(lib, "environment", env["asset_id"], shot_coll)
    setup_world(scene, lib, env)
    setup_lighting(scene, shot_coll, spec.get("lighting", {}), report)
    report.lap("environment")

    roots: dict[str, bpy.types.Object] = {}
    armatures: dict[str, bpy.types.Object] = {}
    for char in spec.get("characters", []):
        entry = lib.asset(char["asset_id"])
        root_obj, coll = instance_asset(lib, char["name"], char["asset_id"], shot_coll)
        apply_transform(root_obj, char.get("transform", {}))
        if char.get("motion_path"):
            key_motion_path(root_obj, char["motion_path"])
        arm = find_armature(coll, entry.get("armature"))
        if arm is None:
            raise BuildError(f"character '{char['name']}' ({char['asset_id']}) has no armature")
        place_actions(lib, arm, char, report)
        roots[char["name"]], armatures[char["name"]] = root_obj, arm
    report.lap("characters")

    for prop in spec.get("props", []):
        root_obj, _ = instance_asset(lib, prop["name"], prop["asset_id"], shot_coll)
        apply_transform(root_obj, prop.get("transform", {}))
        parent = prop.get("parent")
        if parent:
            arm = armatures[parent]
            bone = prop.get("parent_bone")
            root_obj.parent = arm
            if bone:
                if bone not in arm.data.bones:
                    raise BuildError(f"prop '{prop['name']}': bone '{bone}' not on {arm.name}")
                root_obj.parent_type = "BONE"
                root_obj.parent_bone = bone
            root_obj.matrix_parent_inverse.identity()  # transform is relative to bone/rig
        roots[prop["name"]] = root_obj
    report.lap("props")

    roots.update(build_primitives(spec.get("primitives", []), shot_coll, report))
    report.lap("primitives")

    setup_camera(scene, shot_coll, spec["camera"], roots, seed)
    report.lap("camera")

    out.mkdir(parents=True, exist_ok=True)
    blend_path = out / f"{spec['shot_id']}.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    report.data["blend"] = str(blend_path)
    report.lap("save")

    if not args.no_render:
        bpy.ops.render.render(animation=True)
        report.data["frames_dir"] = str(out / "frames")
        report.data["frame_range"] = [scene.frame_start, scene.frame_end]
        pct = scene.render.resolution_percentage / 100
        report.data["resolution"] = [round(scene.render.resolution_x * pct),
                                     round(scene.render.resolution_y * pct)]
        report.data["fps"] = scene.render.fps
        report.lap("render")


def main() -> None:
    args = parse_args()
    spec = json.loads(args.spec.read_text())
    report = Report(spec.get("shot_id", "unknown"))
    try:
        build(args, report, spec)
        report.data["status"] = "ok"
    except BuildError as e:
        report.data.update(status="spec_error", error=str(e))
        raise
    except Exception as e:  # noqa: BLE001 — record everything for the worker
        report.data.update(status="crash", error=f"{type(e).__name__}: {e}",
                           traceback=traceback.format_exc())
        raise
    finally:
        report.write(args.out.resolve())


if __name__ == "__main__":
    main()
