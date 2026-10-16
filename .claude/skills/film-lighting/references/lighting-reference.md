<!-- Adapted from RobLe3/cc-blender-skill@a2634b588e80265e796aa53f8ab178d75105c2af,
     plugin/skills/blender-lighting/SKILL.md and references/overview.md.
     MIT License, Copyright (c) 2026 RobLe3 (see ../LICENSE).
     Modified for AI Film Studio; see ../UPSTREAM.md. Code recipes removed. -->

# Lighting reference

This is background knowledge for planning SceneSpec lighting and for writing
schema-gap proposals. Nothing here is an instruction to build lights by hand
or to run code; only `blender/scripts/build_scene.py` creates lights, from a
validated spec.

## Light types (vocabulary for gap proposals)

| Type | Behaviour | Typical use |
|---|---|---|
| Sun | Parallel rays from "infinity" | Sunlight, moonlight. **The only lamp the builder creates from spec fields today.** (Hand-built `LGT-<preset>` template rigs could hold other types, but none exist yet.) |
| Area | Rectangular/disk emitter; soft shadows | Softboxes, windows, fill, most interior key light |
| Spot | Cone with falloff | Stage light, headlights, noir key, rim |
| Point | Omnidirectional | Bulbs, candles, small practicals |
| World / HDRI | 360° environment | Ambient fill, reflections, sky. Supported via `environment` |

## Three-point lighting (for future schema work)

- **Key:** brightest; defines mood and shape. Usually ~45° to one side of the
  camera and above the subject.
- **Fill:** opposite side to the key, larger and softer, 1/4 to 1/2 of the key.
- **Rim / back:** behind the subject, often cooler, 50–100% of the key; it
  separates the subject from the background. Keep it at or below key strength.

Upstream recipes place lights at a distance of about 1.5 × the subject's
largest dimension (minimum 1 m) and scale energy with distance squared,
targeting ~100 W at 1.5 m for a 1 m subject. A future builder function could
use the same rule. In today's schema, the sun is the key and the world is
the fill.

Typical key:fill:rim ratios by subject material (upstream guidance):

| Subject | Key:Fill:Rim | Key colour temperature |
|---|---|---|
| Metal (default) | 4:1:2 | warm 3200 K |
| Glass | 3:1:1.2 | neutral 5500 K (a strong rim washes out transmission) |
| Wood | 4:1:1.5 | warm 3000 K |
| Fabric | 3:1:0.5 | neutral 5500 K |
| Skin | 4:1:1 | warm 3500 K |
| Product | 5:1:1.5 | neutral 5000 K |

Contrast styles: high-key ~2:1 key:fill, medium ~4:1, low-key 8:1 or more.

## Colour temperature → linear RGB (approximate)

| Source | Kelvin | RGB |
|---|---|---|
| Candle | 1850 | (1.0, 0.6, 0.3) |
| LED warm | 3000 | (1.0, 0.8, 0.6) |
| Tungsten bulb | 3200 | (1.0, 0.85, 0.6) |
| Halogen | 3400 | (1.0, 0.9, 0.7) |
| Sunset / golden hour | 3500 | (1.0, 0.85, 0.65) |
| Daylight noon | 5500 | (1.0, 1.0, 1.0) |
| Overcast sky | 6500 | (0.95, 0.95, 1.0) |
| Blue hour | 8000 | (0.8, 0.9, 1.0) |
| Shade / open sky | 10000 | (0.7, 0.85, 1.0) |

These values suit `environment.world_color` and any future light-colour
field. A warm key (~3200 K) with a cool fill (~5500–6500 K) is the classic
"golden/teal" contrast.

## Scenario notes

"World strength" values below are upstream Blender values. In SceneSpec
they map to `environment.hdri_strength`. `world_color` has no strength
field, so use a darker or lighter colour instead.

- **Sunlit exterior:** sun as key plus a sky HDRI around strength 1.0. No fill
  lamp is needed because the sky provides it.
- **HDRI-grounded look:** an HDRI on its own often looks flat. Use it as fill
  at strength 0.3–0.5 under a directional key.
- **Interior window light:** cool, fairly sharp sun through the window, a low
  world (around 0.2), warm practicals and slight haze. Practicals and window
  geometry need a schema change and a set asset.
- **Noir / dramatic:** a single hard source about 60° from above, little or no
  fill (1/8 of the key at most), a cool dim world, and haze for light shafts.
- **Practical-dominated scene** (lamp, candle or screen in shot): world
  strength about 0.10–0.20 so the practical dominates, a small soft ambient
  fill from the camera direction, and emissive materials. All of this needs
  a schema change.
- **Stylised animation:** high contrast (4:1 or more), hard sun shadows and
  saturated colour.

## Shadow softness

Area lights: a larger size gives softer shadows. Sun: a larger angle gives
softer shadows (about 0.5° is a realistic sun; about 5° looks like soft
overcast). The builder fixes the sun at 1.5°.

## Volumetrics

Keep haze subtle: heavy volume scatter makes a muddy image and long render
times. The world `fog_density` is uniform, so god rays need a lamp-driven
setup that is not yet in the schema.

## Light groups (future)

Cycles light groups would let you re-balance key, fill and rim in
compositing without re-rendering. That's worth considering once the schema
supports more than one lamp.
