---
name: film-camera
description: Plan a shot's camera as validated SceneSpec JSON — shot size, focal length, camera position, XYZ rotation and keys, look-at tracking, off-centre subject placement (framing.subject_offset), clipping range, depth of field (focus object or focus distance), camera moves (push-in, dolly, orbit, zoom, crane, locked-off) and handheld shake. Use when filling or reviewing the `camera` section of a SceneSpec (v1.0, v1.1 or v1.2), turning a shot-list entry or a shot-composition plan into camera data, or deciding whether a requested camera behaviour needs a SceneSpec schema change. Planning only; never writes or runs Blender code.
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
   SceneSpec (`apps/api/schemas/scene_spec.py`), plus `spec_version` when a v1.2
   field is needed. Never write bpy/Python for Blender, never ask to run
   generated code, and never use a Blender MCP server or live Blender session.
   Plain arithmetic to choose numbers (distances, angles) is planning and is
   fine.
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
- **`film-animatic-review`** checks the rendered result (see the end of this
  skill).

## Versions

| Version | Camera capability |
|---|---|
| 1.0, 1.1 | Everything in the field table except the v1.2 rows. Still valid and built exactly as before |
| **1.2** | Adds `framing.subject_offset`, `clip_start_m`, `clip_end_m`, `focus_distance_m`, and turns two silently ignored cases into errors (see *Legacy behaviour*) |

- **v1.2 fields in 1.0/1.1 are rejected.** An omitted `spec_version` means
  1.0. Set `"spec_version": "1.2"` when you need a v1.2 field.
- **All versions:** every camera number must be finite. `NaN`, `Infinity` and
  `-Infinity` are rejected.

## Fields

"Measured" means checked by the no-render Blender tests in
`tests/test_camera_builder.py`, which read the evaluated camera back with
`blender/scripts/inspect_camera.py`. "Builder code" means implemented but not
separately measured.

| Field | Range / default | Behaviour | Basis |
|---|---|---|---|
| `shot_size` | `extreme_wide` … `extreme_close_up`, default `medium` | Informational only. It doesn't move the camera; make positions and lens match it | schema |
| `lens_mm` | 8–300, default 35 | Focal length. Perspective camera; sensor width fixed at **36 mm**, sensor fit `AUTO` | measured |
| `keys[].location` | 3 numbers, metres, Z-up | Camera position at that key frame | measured |
| `keys[].rotation_deg` | 3 numbers, degrees | **XYZ Euler** (R = Rz·Ry·Rx). The camera looks along R·(0, 0, −1), and its up direction is R·(0, 1, 0). Required on every key without `look_at` | measured |
| `keys[].lens_mm` | 8–300 | Animated focal length: the lens follows the keys (e.g. 24 at frame 1 → 50 at frame 96, in between at frame 48). Set it on the **first and last** key of a zoom | measured |
| `keys[].easing` | `ease_in_out` (default), `linear`, `constant` | Interpolation from this key to the next | builder code |
| `look_at` | instance name | A Track-To constraint (−Z track, Y up) aims at an `AIM-<name>` empty. Without `framing`, the aim point stays at frame centre (measured on every 5th frame of a moving camera) | measured |
| `look_at_height` | 0–10 m, **default 1.3** | Aim height above the target's origin; also the focus point. Set it explicitly for anything not human-sized | measured (primitives) |
| `dof_enabled` | bool, **default true** | Depth of field on or off; see *Depth of field* | measured |
| `focus_target` | instance name | Focus object; defaults to `look_at` | measured (via `look_at`) |
| `fstop` | 0.5–32, default 2.8 | Applied when there is a focus object, or (v1.2) a `focus_distance_m` | measured |
| `handheld_shake` | 0–1, default 0 | F-curve noise on the aim point (with `look_at`) or on rotation (without) | builder code |
| **`framing.subject_offset`** (1.2) | `[x, y]`, each −0.4…0.4; needs `look_at` | Places the tracked aim point off-centre using lens shift; see *Placing the subject* | measured |
| **`clip_start_m`** (1.2) | 0.001–10; unset = 0.1 | Near clipping distance | measured |
| **`clip_end_m`** (1.2) | 1–100000; unset = 1000 | Far clipping distance. When both are set, start must be less than end; setting one keeps the other's default | measured |
| **`focus_distance_m`** (1.2) | 0.05–10000 | Focus distance for depth of field **without** a focus object; needs `dof_enabled` | measured |

Easing advice:
- `ease_in_out` (Bezier) is smooth and eases at the first and last key.
- `linear` gives constant speed, with visible corners at middle keys.
- `constant` holds, then jumps, which reads as a cut, so avoid it on camera
  location.

For characters and props, the builder parents the aim empty to the instance, so
`look_at_height` scales with `transform.scale` and follows its rotation; for
primitives it follows position only. Only the primitive case is measured (no
character assets exist yet).

## Workflow

1. **Read the shot.** Take its purpose from the shot list and the
   shot-composition plan: subject, shot size, emotion, movement, duration
   (`render.frame_start`…`frame_end`), aspect ratio (`render.resolution`).
2. **Choose the lens for feel** (table below), then **the distance for size**
   (framing maths below). Changing the lens while keeping the subject the same
   size changes perspective and background compression; it isn't a free
   zoom.
3. **Aim and place the subject.** Use `look_at` for the main subject and set
   `look_at_height`. For an off-centre subject in v1.2, add
   `framing.subject_offset`.
4. **Design the move** from the patterns below. Every move needs a motive:
   reveal, follow, intensify, or settle.
5. **Choose the focus strategy** explicitly (see *Depth of field*) and pick
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
| `medium` | 0.55–0.65 × P (waist up) | 35–50 mm | see *Placing the subject* |
| `close_up` | 0.25–0.30 × P (head and shoulders) | 50–85 mm | see *Placing the subject* |
| `extreme_close_up` | 0.08–0.12 × P (eyes, hands, detail) | 85–135 mm | the detail itself |

## Placing the subject

### v1.2: `framing.subject_offset`

`subject_offset: [x, y]` puts the `look_at` aim point at **(0.5 + x, 0.5 + y)**
of the frame. Here (0, 0) is bottom-left and (1, 1) is top-right, so **+x
moves the subject right and +y moves it up**.

| Want | `subject_offset` |
|---|---|
| Left third line | `[-0.1667, 0]` |
| Right third line | `[0.1667, 0]` |
| Eyes or detail on the upper third line | `[0, 0.1667]` (aim at the eyes) |
| Upper-right third intersection | `[0.1667, 0.1667]` |

- **How it works:** the builder sets lens shift to `(−x, −y × height / width)`.
  The camera still points at the subject while the image window moves, so
  Track-To keeps working on moving cameras, and perspective comes from the
  camera position as usual.
- **Measured** with Blender's `world_to_camera_view` on the evaluated camera,
  every 8th frame of the moving Milestone 1 camera, to within 1e-4:
  - 640×360 (16:9) at `[-1/6, 0]`, `[1/6, 1/6]`, `[0, -0.3]` and the `[0.4, -0.4]` limits;
  - 1280×536 (2.39:1) at `[0.1, 0.2]`;
  - 360×360 (square) at `[0.25, 0.25]`.
- **Supported frames: landscape and square only.** A portrait frame
  (`height > width`) with `subject_offset` is refused at build time
  (`spec_error`: "only supported for landscape or square frames"). Portrait
  frames without `framing` build normally.
- **Needs `look_at`.** The offset places the tracked subject.

### 1.0/1.1, or without `look_at`

- **Headroom without an offset:** Track-To centres the aim point. To put the
  eyes on the upper-third line, aim **below** them by one sixth of the frame
  height: `look_at_height ≈ eye_height − H / 6`. This is planning arithmetic,
  not measured.
- **Explicit rotation instead of tracking:** give `rotation_deg` on every key.
  To point camera `C` at target `T`, with `d = T − C`:

  ```
  rotation_deg = [90 + atan2(d.z, hypot(d.x, d.y)),  0,  atan2(d.y, d.x) − 90]
  ```

  The XYZ-Euler / −Z view convention this relies on is measured. The formula
  itself was checked numerically, not in a render. Off-centre placement by
  changing the rotation is no longer recommended; use `subject_offset` (v1.2).
- **Unwrap rotations between keys.** Keys interpolate Euler angles as plain
  numbers: a Z rotation from 170° to −170° spins 340° the long way. Add or
  subtract 360° so each key's Z is within 180° of the previous key's.

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

`subject_offset` holds for every frame of a tracking move. It's a constant
offset, not keyable.

**Continuity across shots:** keep the 180° rule. If character A is on screen
left looking right in one shot, keep A on the left in the next, and keep
cameras on one side of the line of action. Keep screen direction consistent
for characters travelling across cuts.

## Depth of field

**Choose a focus strategy explicitly.** In v1.2, `dof_enabled: true`
(the default) must have something to focus on:

| Strategy | Fields | Result | Basis |
|---|---|---|---|
| Focus on the tracked subject | `look_at` (optionally `focus_target` = the same name) | Focus object `AIM-<target>`, `fstop` applied | measured |
| Focus on another object | `focus_target` naming a different instance | Focus object `AIM-<focus_target>` at `look_at_height`, `fstop` applied | builder code |
| Focus at a distance (no focus object) | `focus_distance_m`, with no `look_at`/`focus_target` (v1.2) | `focus_distance` and `fstop` applied | measured |
| No depth of field | `dof_enabled: false` | Off | measured |

In v1.2, depth of field with no focus object and no `focus_distance_m` is a
validation error. So is `focus_distance_m` together with `look_at` or
`focus_target`, or without `dof_enabled`.

| f-stop | Depth of field | Use |
|---|---|---|
| 1.2–2.0 | Razor thin | Hero close-ups, dreamy isolation |
| 2.8 | Shallow | Standard portrait (schema default) |
| 4 | Moderate | Two characters both sharp |
| 5.6–8 | Medium–deep | Groups, subject in environment |
| 11+ | Very deep | Landscapes, "everything sharp" |

Halving the f-number roughly doubles the background blur. Longer lenses and
closer subjects also make depth of field shallower. Use `dof_enabled: false`
for establishing or extreme-wide shots.

## Clipping

Leave `clip_start_m`/`clip_end_m` unset unless a shot needs them (v1.2):

- Raise `clip_start_m` only if near geometry must be cut away.
- Lower it (e.g. 0.02) for extreme close-ups of small props that get clipped at
  the 0.1 m default.
- Lower `clip_end_m` for small sets.
- Raise it (up to 100000) for very large environments.

## Legacy behaviour (1.0/1.1)

1.0/1.1 specs keep validating and building exactly as before. Two cases that
v1.2 rejects are still accepted there. After a successful build, the worker
adds a warning for each to `build_report.json`:

| Legacy case | Builder behaviour (measured) | Build-report warning |
|---|---|---|
| `rotation_deg` on keys together with `look_at` | Rotation ignored; Track-To aims the camera | `camera: rotation_deg on keys at frames [...] is ignored because look_at '<name>' controls rotation` |
| `dof_enabled` with no `look_at` or `focus_target` | Depth of field on, but `fstop` not applied; Blender's defaults (f/2.8, 10 m) are used | `camera: dof_enabled with no look_at or focus_target; fstop <n> is not applied and Blender's default focus is used` |

To fix either, move the shot to `spec_version` 1.2 and resolve it, or just
remove the ignored data.

## Validator and builder checks before handoff

- **Version and numbers:** `spec_version` is `"1.2"` if any v1.2 field is used.
  All camera numbers are finite.
- **Keys:** frames are unique, ascending and inside `render.frame_start…frame_end`.
- **Rotation:** without `look_at`, every key has `rotation_deg`, unwrapped. In
  1.2, keys must **not** have `rotation_deg` when `look_at` is set.
- **Lens:** if any key sets `lens_mm`, the first key sets it too.
- **References:** `look_at` and `focus_target` name a character, prop or
  primitive **in this shot**.
- **Focus:** one focus strategy is chosen (table above).
- **Aim height:** `look_at_height` is set deliberately. The 1.3 m default
  aims above small props and primitives.
- **Framing:** `subject_offset` is only used with `look_at` and a landscape or
  square `render.resolution`.
- **Clipping:** `clip_start_m < clip_end_m` when both are set.
- **Camera path:**
  - Camera Z stays above the ground and outside geometry on every key *and*
    between keys (interpolation can dip). The ground plane in procedural
    shots is usually at Z = 0.
  - The camera never passes through or very close to its aim point, which
    makes Track-To spin wildly.
- **Size:** lens, distance and `shot_size` agree (use the framing maths).

## Verified example

`schemas/examples/m3_framing.json` (v1.2) is the reference shot for these
fields:

- **Scene:** a red sphere on a pedestal.
- **Camera:** 50 mm, tracking `hero` with `look_at_height` 0, pushing in from
  7.0 m to 4.5 m over frames 1–48.
- **Framing and focus:** `subject_offset [-0.1667, 0]`, clip 0.05–100 m, depth
  of field on `focus_target: "hero"` at f/4. Rendered at 640×360.

When it was rendered for review:

- `build_report.json` recorded `shift [0.1667, 0]`.
- The aim point measured at **x = 0.3333, y = 0.5000 on all 12 sampled
  frames**.
- The contact sheet showed the sphere on the left third line throughout.

The automated test (`tests/test_camera_spec.py`) checks that the spec is
valid and documents this camera. The placement measurement was a one-off
inspection of that render.

## After rendering: review is evidence, not approval

The builder writes the effective camera settings to `build_report.json` under
`camera`: lens, `shift`, `clip`, `dof` (focus object, focus distance, f-stop),
`subject_offset`, `look_at`, `lens_animated` and `handheld_shake`. Use them to
confirm the spec was applied.

Then produce review evidence with the contact-sheet worker and follow
`film-animatic-review`:

```
uv run python -m workers.contact_sheet --shot-dir <shot-dir>
```

The worker's `review/contact_sheet.png` and `review/frame_report.json` are
evidence for a human: `verdict` is always `evidence_only` and
`human_approval_required` is always `true`. Measured placement or a clean
report does not approve a shot. Composition, storytelling and camera motion
still need a person to sign off.

## Common pitfalls

| Symptom | Spec-level fix |
|---|---|
| Distorted face | Lens 50 mm or longer; step back |
| Subject soft, background sharp | Choose a focus strategy; check `look_at_height` |
| Dead-centre, static framing | `framing.subject_offset` (v1.2), depth layers, or a motivated move |
| Validation: "dof_enabled needs something to focus on" (1.2) | Add `look_at`/`focus_target`, set `focus_distance_m`, or set `dof_enabled: false` |
| Validation: rotation_deg with look_at (1.2) | Remove `rotation_deg` from the keys, or remove `look_at` |
| Build `spec_error` "only supported for landscape or square frames" | Remove `framing`, or use a landscape/square `render.resolution` |
| Small prop clipped in an extreme close-up | Lower `clip_start_m` (v1.2) |
| Orbit drifts closer mid-move | More keys, closer together; push the middle keys outward |
| Camera dips below ground | Raise the key Z values; add keys near low points |
| Sky dominates a landscape | Lower the aim so the horizon sits on the lower third |
| Move feels mechanical | `ease_in_out`; fewer, more deliberate keys |

## Schema-gap note format

```
SCHEMA GAP (camera)
Shot: <shot_id>
Needed: <e.g. Dutch angle while tracking the subject>
Closest valid spec used: <what you set instead>
Proposed field(s): <e.g. camera.roll_deg>
Builder change needed: <e.g. roll after the Track-To constraint in setup_camera()>
```

Known gaps right now:

- No camera roll / Dutch angle with `look_at`.
- No orthographic or panoramic projection: perspective only.
- No sensor width or sensor fit control (fixed 36 mm, `AUTO`).
- No `subject_offset` for portrait frames, and the offset can't be keyed over
  time.
- No per-key `fstop` or focus pull between targets.
- No path-following camera (curve), no shake frequency control.
- `shot_size` is not checked against the actual framing.

## Reference

Load `references/camera-reference.md` for full-FOV notes, sensor sizes (for
gap proposals), composition rules and cinematic effects vocabulary.
