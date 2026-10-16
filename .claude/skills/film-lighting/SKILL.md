---
name: film-lighting
description: Plan the lighting and world of a shot as validated SceneSpec JSON — choose a lighting preset, sun overrides, exposure, HDRI or world colour and fog to express a mood (golden hour, overcast, night, moody, dramatic, warm/cool contrast). Use when filling or reviewing the `lighting` and `environment` sections of a SceneSpec, when a story beat asks for a lighting mood, or when deciding whether a requested look needs a SceneSpec schema change. Planning only; never writes or runs Blender code.
---

<!-- Adapted from RobLe3/cc-blender-skill@a2634b588e80265e796aa53f8ab178d75105c2af,
     plugin/skills/blender-lighting/SKILL.md and references/overview.md.
     MIT License, Copyright (c) 2026 RobLe3 (see LICENSE in this folder).
     Modified for AI Film Studio; every change is listed in UPSTREAM.md. -->

# Film Lighting (SceneSpec planning)

Light shots the way a cinematographer does — with structure, intent and
physically reasonable values — but express every decision as **SceneSpec JSON**.

## Hard rules

1. **Output is data, not code.** Produce or edit only the `lighting` and
   `environment` objects of a SceneSpec (`apps/api/schemas/scene_spec.py`).
   Never write bpy/Python for Blender, never ask to run generated code, and
   never use a Blender MCP server or live Blender session.
2. **Validate before handing off.** The spec must pass `SceneSpec` (Pydantic,
   `extra="forbid"`, so unknown keys fail) and `validate_against_manifest()`.
   Feed any validation errors back into the plan and retry; do not bypass them.
3. **Blender executes only through the fixed builder.**
   `blender/scripts/build_scene.py` turns the validated spec into lights and a
   world, run headless by the worker. This skill does not modify that script.
4. **No downloads, no invented assets.** An HDRI may only be referenced by an
   `hdri_id` that exists in `assets/manifest.json` with `"type": "hdri"`. Never
   suggest fetching HDRIs or other files from the internet, and never write a
   file path into a spec.
5. **No AI image/video generation** for lighting reference or look matching.
6. **Gaps are reported, not worked around.** If the look needs something the
   schema cannot express, keep the closest valid spec and write a schema-gap
   note (format below). Do not smuggle extra lights in through other fields.

## What the schema can express today (SceneSpec 1.0 / 1.1)

`lighting`:

| Field | Range | Builder behaviour (`setup_lighting`) |
|---|---|---|
| `preset` | `golden_hour` `overcast` `midday` `blue_hour` `night` | Picks a sun elevation, azimuth, strength and colour (table below). If the style template has a collection `LGT-<preset>`, that hand-built rig is used instead. |
| `sun_elevation_deg` | −10 … 90 | Overrides preset elevation. 0 = horizon, 90 = straight down. |
| `sun_azimuth_deg` | 0 … <360 | Overrides preset azimuth (see direction note). |
| `sun_strength` | 0 … 20 | Overrides preset sun energy. |
| `exposure` | −5 … 5 | Scene exposure in stops (Color Management). |

`environment`:

| Field | Range | Builder behaviour (`setup_world`) |
|---|---|---|
| `hdri_id` | manifest id | Environment texture as world light and background. |
| `hdri_strength` | 0 … 20 | World strength for the HDRI. |
| `hdri_rotation_deg` | any | Rotates the HDRI around Z — moves its bright side. |
| `world_color` | RGB 0–1 (v1.1) | Flat sky colour, used only when there is no HDRI. Also acts as flat ambient fill. |
| `fog_density` | 0 … 1 | World Volume Scatter density (uniform haze). |
| `asset_id` | manifest id | Set geometry; not lighting, but it shapes shadows and bounce. |

`environment` must name at least one of `asset_id` or `hdri_id` (spec 1.0),
or one of `asset_id`, `hdri_id` or `world_color` (spec 1.1). `world_color`
has **no strength field**: control its brightness through the RGB values.

Preset values in `build_scene.py` (`LIGHT_PRESETS`), used when no template rig applies:

| Preset | Elevation° | Azimuth° | Strength | Colour (RGB) | Reads as |
|---|---|---|---|---|---|
| `golden_hour` | 8 | 250 | 3.0 | (1.00, 0.72, 0.45) | Low warm sun, long shadows |
| `overcast` | 45 | 180 | 0.6 | (0.90, 0.93, 1.00) | Weak cool light; relies on world for fill |
| `midday` | 62 | 160 | 4.5 | (1.00, 0.97, 0.92) | High, neutral, short hard shadows |
| `blue_hour` | 2 | 270 | 0.3 | (0.55, 0.65, 1.00) | Very dim cool horizon light |
| `night` | 35 | 120 | 0.08 | (0.50, 0.60, 1.00) | Moonlight; world/exposure carry the frame |

Builder facts to plan around:

- `blender/templates/` is currently empty, so **no `LGT-<preset>` rigs exist
  yet**; every shot currently gets the single procedural sun `SUN-shot`.
- **No asset files exist yet.** `assets/hdri/` (and the character, prop and
  environment folders) are empty. `sky_golden_hour` is listed in the manifest,
  so a spec using it passes `validate_against_manifest()`, which checks ids,
  not files. The build then fails when it tries to load the image. Until HDRI
  files are added, plan worlds with `world_color` (spec 1.1).
- When a template rig *does* exist and any sun override is set, the builder
  keeps the template rig **and** adds the procedural sun. Avoid overrides on
  template-rigged presets unless that double source is intended.
- Sun colour and sun angle (shadow softness, fixed at 1.5°) cannot be set
  per shot.
- **Sun direction** (from the builder's rotation `X = 90° − elevation`,
  `Z = azimuth`): the light comes *from* −Y at azimuth 0°, from +X at 90°,
  from +Y at 180° and from −X at 270°. Cameras in our specs usually sit on the
  −Y side, so ~0° is front light, ~90°/270° side light, ~180° back/rim light.
  This mapping is verified by rotation maths against the builder code but
  has not yet been confirmed on a render. Check it on the first animatic.

## Workflow

1. **Read the beat.** Note the mood, time of day, interior/exterior, the main
   subject, and the camera position (`camera.keys[0].location`) — light
   direction only means something relative to the camera.
2. **Pick the closest preset** from the mood table below.
3. **Aim the sun for shape.** Set `sun_azimuth_deg` relative to the camera:
   side or three-quarter back light (roughly 60–150° away from the camera's
   bearing) models form and separates the subject; front light flattens.
4. **Set fill with the world.** The schema has no fill lamp, so fill comes
   from `hdri_strength` or `world_color`. A brighter or lighter world gives a
   lower key:fill contrast; a darker world gives a higher one.
5. **Balance with `exposure`,** not by pushing `sun_strength` to extremes.
   Night and blue hour will likely need extra exposure; +1 to +2 stops is an
   untested starting point.
6. **Add haze sparingly.** `fog_density` is uniform world fog and is costly
   to render. Start around 0.005–0.02 and treat it as a visual check, not a
   fixed value.
7. **Validate**, then hand the spec on. List any schema gaps you hit.

## Mood → SceneSpec starting points

These are untested starting points for an animatic, not final values. Any
HDRI option assumes the HDRI file exists (see builder facts above).

| Mood | Starting point |
|---|---|
| Warm natural exterior | `golden_hour`; azimuth ~90° from the camera bearing for side light; HDRI at low `hdri_strength`, or a dim warm-neutral `world_color` |
| Neutral daylight | `midday`; HDRI strength ~1.0 or light-blue `world_color` |
| Soft, gloomy, even | `overcast`; brighter neutral-cool `world_color`; exposure 0 to +0.5 |
| Melancholy / dusk | `blue_hour`; deep blue `world_color`; exposure +1 to +2 |
| Night | `night`; very dark blue `world_color`; exposure +1.5 to +2.5; optional light fog |
| Dramatic / low-key | Any preset with low `sun_elevation_deg` (5–20°) from the side or behind; dark `world_color`; no extra fill. True single-spot noir needs a schema change |
| Stylised / cartoon | `midday` or `golden_hour`; saturated `world_color`; stronger sun |

## Lighting knowledge to apply

**Contrast (key:fill ratios):** high-key commercial ~2:1, portrait ~4:1,
low-key drama 8:1 or more. A rim at 50–100% of the key separates a subject
from the background. In today's schema the key is the sun and the fill is the
world, so you set the ratio with `sun_strength` against `hdri_strength` or the
brightness of `world_color`.

**Colour temperature:** a warm key with a cool fill (the "golden/teal" look) is
a dependable cinematic contrast. With one fixed-colour sun, get it by pairing
a warm preset with a cool `world_color`, or the reverse at night. RGB
equivalents are in `references/lighting-reference.md`.

**Shadows:** almost nothing in nature has perfectly hard shadows. Sun angle is
fixed at 1.5°, so softness can't be planned per shot yet — record a gap if a
beat depends on it.

## Common pitfalls

| Symptom in the animatic | Spec-level fix |
|---|---|
| Half the subject pitch black | Raise `hdri_strength` or lighten `world_color` (fill) |
| Flat, lifeless image | Move the sun off the camera axis; lower world brightness to raise contrast |
| Everything too dark | Raise `exposure` before raising `sun_strength` |
| Backlight blows out the subject | Lower `sun_strength`, or bring the azimuth toward the side |
| Materials look dull, no reflections | Use an HDRI from the manifest instead of a flat `world_color`, once its file exists |
| Hazy mess, slow render | Lower `fog_density` |

## Schema-gap note format

When a beat needs something listed here, keep the closest valid spec and add
a note for a human to review as a possible future SceneSpec version:

```
SCHEMA GAP (lighting)
Shot: <shot_id>
Needed: <e.g. warm practical lamp inside the hut>
Closest valid spec used: <what you set instead>
Proposed field(s): <e.g. lighting.lights[] with type, position, colour, energy>
Builder change needed: <e.g. fixed function in build_scene.py>
```

Known gaps right now:

- No extra lights: no key/fill/rim rig, area, spot or point lights, and no
  practical lights (lamps, candles, screens).
- No per-shot sun colour or sun angle (shadow softness).
- No light linking, light groups or emissive practicals on primitives.
- No colour-management look (AgX/Filmic contrast) per shot.
- Template light rigs (`LGT-<preset>`) are supported by the builder but none
  exist yet.
- No strength control for `world_color`.

## Reference

Load `references/lighting-reference.md` for the full colour-temperature table,
three-point placement theory (for writing gap proposals) and per-scenario
notes.
