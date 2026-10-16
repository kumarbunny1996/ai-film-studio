---
name: film-camera
description: Plan a shot's camera as validated SceneSpec JSON — shot size, focal length, camera position and keys, look-at target and aim height, depth of field, camera moves (push-in, dolly, orbit, zoom, crane, locked-off) and handheld shake. Use when filling or reviewing the `camera` section of a SceneSpec, turning a shot-list entry or a shot-composition plan into camera data, or deciding whether a requested camera behaviour needs a SceneSpec schema change. Planning only; never writes or runs Blender code.
---

<!-- Adapted from RobLe3/cc-blender-skill@a2634b588e80265e796aa53f8ab178d75105c2af,
     plugin/skills/blender-cameras/SKILL.md and references/overview.md.
     MIT License, Copyright (c) 2026 RobLe3 (see LICENSE in this folder).
     Modified for AI Film Studio; every change is listed in UPSTREAM.md. -->

# Film Camera (SceneSpec planning)

Make the decisions a cinematographer makes — focal length for feel, f-stop for
focus, position and movement for storytelling — and express them as
**SceneSpec `camera` JSON**.

## Hard rules

1. **Output is data, not code.** Produce or edit only the `camera` object of a
   SceneSpec (`apps/api/schemas/scene_spec.py`). Never write bpy/Python for
   Blender, never ask to run generated code, and never use a Blender MCP
   server or live Blender session. Plain arithmetic to choose numbers
   (distances, angles) is planning and is fine.
2. **Validate before handing off.** The spec must pass `SceneSpec` (unknown
   keys fail) and `validate_against_manifest()`. Feed errors back and retry.
3. **Blender executes only through the fixed builder** —
   `setup_camera()` in `blender/scripts/build_scene.py`, run headless by the
   worker. This skill does not modify it.
4. **No AI image/video generation** for storyboards, previs or reference.
5. **Gaps are reported, not worked around** (format at the end).

## Division of labour

- **`shot-composition`** decides *what* the frame should say: focal point,
  foreground/midground/background layers, negative space, entry/exit direction,
  motivated movement, safe areas. Its web, social-media and 9:16 material
  doesn't apply; our shots render landscape (`render.resolution`, usually
  16:9). Its CSS/JS/Three.js snippets are illustrations only: never run or
  port them; take the idea and express it as `camera.keys`.
- **`film-camera`** (this skill) turns that plan into `camera` fields.
- **`film-lighting`** sets light direction *relative to this camera*, so
  settle the camera position first.

## What the schema can express today

| Field | Range | Builder behaviour |
|---|---|---|
| `shot_size` | `extreme_wide` `wide` `medium` `close_up` `extreme_close_up` | Informational only (planners and QA). It does not move the camera — you must make positions and lens match it. |
| `lens_mm` | 8–300, default 35 | Focal length. Sensor width is fixed at **36 mm** (full frame). Ignored once any key sets `lens_mm` (see `keys[]`). |
| `look_at` | instance name | Track-To constraint: the camera always points at an aim empty on that character, prop or primitive. **The aim point is always centred in frame.** |
| `look_at_height` | 0–10 m, **default 1.3** | Aim point height above the target's origin. For characters and props the aim empty is parented to the instance, so the offset scales with `transform.scale` and follows its rotation. For primitives it follows position only. It also sets the **focus point**, even when `focus_target` is a different object. Set it explicitly for anything that isn't human-sized. |
| `keys[]` | ≥1 key, frames unique, ascending, inside render range | Each key sets `location` (m, Z-up), and optionally `rotation_deg` (ignored with `look_at`; **required on every key without it**), `lens_mm` and `easing` (interpolation to the next key). A key's `lens_mm` is keyframed only on that key. Once any key has one, the lens is animated for the whole shot and `camera.lens_mm` no longer applies: before the first lens key the lens holds that key's value, after the last it holds the last value. |
| `dof_enabled` | bool, **default true** | Depth of field on or off. Set it to `false` explicitly when there's no focus target. |
| `focus_target` | instance name | Focus object; defaults to `look_at`. |
| `fstop` | 0.5–32, default 2.8 | Aperture. **Only applied when a focus target exists** (`focus_target` or `look_at`). |
| `handheld_shake` | 0–1 | F-curve noise. With `look_at`, a noise modifier of strength 0.08 × value on the aim point's location (metres); without it, strength 0.012 × value on camera rotation (radians). |

Easing values: `ease_in_out` (Bezier — smooth, eases at the first and last
key), `linear` (constant speed, but visible corners at each middle key),
`constant` (holds, then jumps — this reads as a cut, so avoid it on camera
location).

## Workflow

1. **Read the shot.** Take its purpose from the shot list and the
   shot-composition plan: subject, shot size, emotion, movement, duration
   (`render.frame_start`…`frame_end`), aspect ratio (`render.resolution`).
2. **Choose the lens for feel** (table below), then **the distance for size**
   (framing maths below). Changing the lens while keeping the subject the same
   size changes perspective and background compression; it isn't a free
   zoom.
3. **Set the aim.** Use `look_at` the main subject, and set `look_at_height`
   so the important feature sits where you want it vertically.
4. **Design the move** from the patterns below. Every move needs a motive:
   reveal, follow, intensify, or settle.
5. **Set focus.** `dof_enabled: true` only with a focus target; choose
   `fstop` from the table.
6. **Check against the validator rules** and the pitfalls list, then hand the
   spec on. List any schema gaps.

## Focal length (36 mm sensor, landscape frame)

| Lens | Horizontal FOV | Frame width per metre of distance | Feel / use |
|---|---|---|---|
| 14 mm | 104° | 2.57 m | Extreme wide, distorted; claustrophobic interiors |
| 24 mm | 74° | 1.50 m | Spectacle, establishing, exaggerated depth |
| 28–35 mm | 65–54° | 1.29–1.03 m | Natural wide, "documentary"; environments, groups |
| **50 mm** | 40° | 0.72 m | Neutral, close to human eye; default storytelling |
| **85 mm** | 24° | 0.42 m | Flattering portraits and character close-ups |
| 100–135 mm | 20–15° | 0.36–0.27 m | Isolated subject, compressed background |
| 200 mm+ | ≤10° | ≤0.18 m | Long-lens compression, surveillance feel |

Quick rule: 85 mm for intimacy, 24 mm for spectacle, 50 mm for neutral. Use
50 mm or longer for faces; wide lenses distort them.

## Framing maths

At distance `D` metres (camera to aim point), with lens `f` mm and aspect
`a = width / height`:

```
frame width  = D × 36 / f
frame height = D × 36 / (f × a)
distance for a wanted frame height H:  D = H × f × a / 36
```

Example: 1.1 m of frame height (a medium shot) at 50 mm and 16:9 →
D = 1.1 × 50 × 1.778 / 36 ≈ **2.7 m**.

Shot size, for a standing person of height `P`. These are planning
heuristics, not schema rules:

| `shot_size` | Frame height H | Typical lens | Aim height |
|---|---|---|---|
| `extreme_wide` | ≥ 6 × P (figure small in the landscape) | 24–35 mm | horizon / set centre |
| `wide` | 1.3–1.6 × P (full body with head and foot room) | 28–35 mm | ~0.55 × P |
| `medium` | 0.55–0.65 × P (waist up) | 35–50 mm | see rule below |
| `close_up` | 0.25–0.30 × P (head and shoulders) | 50–85 mm | see rule below |
| `extreme_close_up` | 0.08–0.12 × P (eyes, hands, detail) | 85–135 mm | the detail itself |

**Headroom rule:** Track-To centres the aim point. To put the eyes on the
upper-third line, aim **below** them by one sixth of the frame height:
`look_at_height ≈ eye_height − H / 6` (measured from the target's origin).

**Horizontal rule of thirds:** `look_at` always centres the subject
horizontally. For an off-centre subject, either accept centring and get
balance from foreground or background elements, or omit `look_at` and give
explicit `rotation_deg` on every key. A Blender camera looks down its −Z axis:
for camera `C` and target `T` with `d = T − C`:

```
rotation_deg = [90 + atan2(d.z, hypot(d.x, d.y)),  0,  atan2(d.y, d.x) − 90]
```

To push the subject one third off centre, change the Z rotation by
`atan(tan(hfov/2) / 3)` (about 6.8° at 50 mm). Positive Z pans the view left,
which moves the subject right in frame. The formula and sign are verified
numerically against Blender's XYZ Euler / −Z view convention, but not yet on
a render in this repo, so check the first animatic. Also flag the gap:
there's no aim-offset field.

**Unwrap rotations between keys.** Keys interpolate Euler angles as plain
numbers. A Z rotation going from 170° to −170° spins 340° the long way
instead of 20°. Add or subtract 360° so each key's Z is within 180° of the
previous key's.

## Camera move patterns (as keys)

| Move | Keys | Notes |
|---|---|---|
| Locked-off | 1 key | The strongest default. Movement should be earned. |
| Push-in | 2 keys on the camera→aim line, same `lens_mm`, `ease_in_out` | Builds intensity. Distinct from a zoom: perspective changes. |
| Pull-out / reveal | 2 keys moving away, often rising | Reveals context or isolation. |
| Zoom | Same `location` on every key, with `lens_mm` on **every** key (at least the first and last) | Reads as news or surveillance; use sparingly. |
| Dolly-zoom (vertigo) | Move closer while `lens_mm` (set on every key) decreases so `D/f` stays constant | The subject stays the same size; the background warps. |
| Truck / track | Lateral keys with `look_at` | Parallax: foreground moves faster than background. |
| Crane / pedestal | Keys changing Z | A rise to reveal or a descend to enter. |
| Orbit / arc | Keys on a circle around the aim point, **≤30–45° apart**, all `ease_in_out` | Keys are interpolated per axis, not along a circle, so the camera cuts inside the arc between keys. Keep spacing tight and check the distance at the midpoints. |
| Follow | Keys tracking a character's `motion_path`, with `look_at` that character | Match timing to the motion path's keys. |
| Handheld | Any of the above plus `handheld_shake` 0.1–0.3 | Tension, documentary feel. Keep it at 0 for calm or animatic-clarity shots. |

**Continuity across shots:** keep the 180° rule. If character A is on screen
left looking right in one shot, keep A on the left in the next, and keep
cameras on one side of the line of action. Keep screen direction consistent
for characters travelling across cuts.

## Depth of field

| f-stop | Depth of field | Use |
|---|---|---|
| 1.2–2.0 | Razor thin | Hero close-ups, dreamy isolation |
| 2.8 | Shallow | Standard portrait (schema default) |
| 4 | Moderate | Two characters both sharp |
| 5.6–8 | Medium–deep | Groups, subject in environment |
| 11+ | Very deep | Landscapes, "everything sharp" |

Halving the f-number roughly doubles the background blur. Longer lenses and
closer subjects also make depth of field shallower. Set `dof_enabled: false`
for establishing or extreme-wide shots, and whenever there's no focus target.

## Validator and builder checks before handoff

- `keys` frames are unique, ascending and inside `render.frame_start…frame_end`.
- No `look_at` → every key has `rotation_deg`, unwrapped (consecutive Z
  rotations within 180° of each other).
- If any key sets `lens_mm`, the first key sets it too, so the opening lens
  is the one you intended.
- `look_at` / `focus_target` name a character, prop or primitive **in this shot**.
- `dof_enabled` (default `true`) → a focus target exists, or the f-stop is
  silently ignored. Otherwise set `dof_enabled: false`.
- `look_at_height` is set deliberately. The 1.3 m default aims above small
  props and primitives.
- Camera Z stays above the ground and outside geometry on every key *and*
  between keys (interpolation can dip). The ground plane in procedural
  shots is usually at Z = 0.
- The camera never passes through or extremely close to its aim point, which
  makes Track-To spin wildly.
- Lens, distance and `shot_size` agree (use the framing maths).

## Common pitfalls

| Symptom | Spec-level fix |
|---|---|
| Distorted face | Lens 50 mm or longer; step back |
| Subject soft, background sharp | Set `focus_target` (or `look_at`); check `look_at_height` |
| Dead-centre, static framing | Use depth layers, a motivated move, or explicit rotation for thirds |
| Orbit drifts closer mid-move | More keys, closer together; push the middle keys outward |
| Camera dips below ground | Raise the key Z values; add keys near low points |
| Sky dominates a landscape | Lower the aim so the horizon sits on the lower third |
| Move feels mechanical | `ease_in_out`; fewer, more deliberate keys |

## Schema-gap note format

```
SCHEMA GAP (camera)
Shot: <shot_id>
Needed: <e.g. subject on left third while tracking>
Closest valid spec used: <what you set instead>
Proposed field(s): <e.g. camera.aim_offset_frame: [x, y] in frame units>
Builder change needed: <e.g. offset in setup_camera()>
```

Known gaps right now:

- No horizontal or vertical aim offset with `look_at` (subject always centred).
- No camera roll / Dutch angle with `look_at`.
- No sensor width or sensor fit (fixed 36 mm), no orthographic camera, no
  clip start/end.
- No numeric focus distance, no per-key `fstop` or focus pull between targets.
- No path-following camera (curve), no shake frequency control.
- `shot_size` is not checked against the actual framing.

## Reference

Load `references/camera-reference.md` for full-FOV notes, sensor sizes (for
gap proposals), composition rules and cinematic effects vocabulary.
