"""Smoke test: proves headless Blender + Eevee render works on this machine.
    blender -b --factory-startup --python-exit-code 1 -P blender/scripts/smoke_test.py -- /tmp/afs_smoke
"""
import math, sys
from pathlib import Path
import bpy

out = Path(sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "/tmp/afs_smoke")
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
items = {i.identifier for i in scene.render.bl_rna.properties["engine"].enum_items}
scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in items else "BLENDER_EEVEE"
scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 640, 360, 100
scene.frame_start, scene.frame_end = 1, 2

bpy.ops.mesh.primitive_monkey_add(location=(0, 0, 1))
bpy.ops.mesh.primitive_plane_add(size=20)
bpy.ops.object.light_add(type="SUN", rotation=(math.radians(50), 0, math.radians(30)))
bpy.ops.object.camera_add(location=(0, -6, 2), rotation=(math.radians(80), 0, 0))
scene.camera = bpy.context.object

scene.render.filepath = str(out / "smoke_####")
scene.render.image_settings.file_format = "PNG"
bpy.ops.render.render(animation=True)
print(f"SMOKE OK — Blender {bpy.app.version_string}, engine {scene.render.engine}, frames in {out}")
