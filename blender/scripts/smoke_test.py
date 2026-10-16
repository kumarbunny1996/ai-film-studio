"""Smoke test: proves headless Blender + Eevee render works on this machine.
    blender -b --factory-startup -t 4 --python-exit-code 1 -P blender/scripts/smoke_test.py -- <out_dir>

Renders 8 frames at 320x180 with low samples; <out_dir> defaults to <system temp>/afs_smoke.
"""
import math, sys, tempfile
from pathlib import Path
import bpy

FRAMES, WIDTH, HEIGHT, SAMPLES = 8, 320, 180, 8

out = Path(sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv[:-1]
           else Path(tempfile.gettempdir()) / "afs_smoke")
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
items = {i.identifier for i in scene.render.bl_rna.properties["engine"].enum_items}
scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in items else "BLENDER_EEVEE"
scene.eevee.taa_render_samples = SAMPLES
scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = WIDTH, HEIGHT, 100
scene.frame_start, scene.frame_end = 1, FRAMES

bpy.ops.mesh.primitive_monkey_add(location=(0, 0, 1))
monkey = bpy.context.object
monkey.keyframe_insert("rotation_euler", frame=1)
monkey.rotation_euler.z = math.radians(90)
monkey.keyframe_insert("rotation_euler", frame=FRAMES)
bpy.ops.mesh.primitive_plane_add(size=20)
bpy.ops.object.light_add(type="SUN", rotation=(math.radians(50), 0, math.radians(30)))
bpy.ops.object.camera_add(location=(0, -6, 2), rotation=(math.radians(80), 0, 0))
scene.camera = bpy.context.object

scene.render.filepath = str(out / "smoke_####")
img = scene.render.image_settings
if hasattr(img, "media_type"):
    img.media_type = "IMAGE"
img.file_format = "PNG"
bpy.ops.render.render(animation=True)
print(f"SMOKE OK — Blender {bpy.app.version_string}, engine {scene.render.engine}, "
      f"{FRAMES} frames {WIDTH}x{HEIGHT} in {out}")
