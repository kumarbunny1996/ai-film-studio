# Milestone 10 — The Traveller's Question

**Objective.** A genuine story continuation of The Greeting (M7), made with the existing
assets, SceneSpec 1.3 and pipeline, then assembled with M7 into one film with the M9
assembler. There are no new characters, rigs, actions or asset files, no dialogue, faces,
titles or fades, and no AI video generation.

**Status.** Approved by the user on 2026-10-18 (`final_rev1`), and assembled with M7 into
`the_greeting_film`.

- **Gate 0:** branch `milestone-10-greeting-continuation`, from the M9 commit `340cf2f`
  (`main` is still M8).
- **Gate 1B:** a read-only feasibility audit of the SceneSpec, the builder and the assets.
- **Gate 2:** the spec, tests, asset preflight and geometry-only checks; then five
  low-resolution previews, the final render and the assembly.

## Story

A, the traveller, has just greeted B, the host. A looks off along the road it means to take:
the question. B turns that way and sets off, leading: the answer. B stops and waits, A catches
up, and the two walk on together onto the road, toward the low sun.

| Shot | Frames | Beat |
|---|---|---|
| `sh01_question_wide` | 1–96 | The pair where M7 left them. B's head turns back onto A |
| `sh02_traveller_question` | 97–132 | A looks toward the road (`mannequin_look`, 105–129) |
| `sh02b_road_ahead` | 133–168 | What A sees: the road running to the horizon (A's view) |
| `sh03_host_response` | 169–240 | B turns toward the road and sets off (209) while A watches |
| `sh04_host_leads` | 241–288 | B leads; A sets off after it (249) |
| `sh04b_road_insert` | 289–336 | The road ahead (a cutaway with no characters) |
| `sh05_catch_up` | 337–456 | B stops (385) and waits; A comes alongside; B walks on (409) |
| `sh06_together_wide` | 457–576 | The two walk together onto the road |

Total: 576 frames, 24 s at 24 fps, the same as M7.

## Continuity with The Greeting

- **Unchanged from M7:** render settings (Eevee, 640×360, 16 samples, no motion blur), world,
  golden-hour lighting, cast and the baton in B's left hand. The set is M7's primitives plus
  the road.
- **Starting state:** each character's root and heading at frame 1 equal M7's at frame 576.
  A is at (−0.2, 0) facing +X; B is at (2.0, 0) facing −50°.
- **The road can't be seen from M7.** It starts 8.5 m along the route, beyond every M7 camera
  on every frame, with a 3% frame margin. A test checks this with M7's own pinhole model.
- **B's head.** SceneSpec clips can't start mid-action, so B's held look from M7 restarts at
  M10 frame 1 (neutral head) and is back on A by frame 17. In the opening wide this is a few
  pixels and not visible in the frames.

## Blocking

All motion uses the existing walk, idle and look actions.

- **Route:** heading 50° (toward camera right and the low sun). A's look turns its head 40° to
  its right, from +X onto exactly this heading, so the look shows the way without a pointing
  gesture.
- **Turns.** Characters can't turn in place, so both turn while walking, on arcs keyed every
  4 frames at the authored walk speed (0.0336 m/frame). Heading and travel direction then
  agree to within 2°.
  - B turns 100° to its left on a 2.0 m arc (209–313).
  - A turns 40° to its right on a 1.93 m arc (249–289).
- **Walk starts.** A walk starting from idle crossfades in over 8 frames, and the root covers
  v·t²/8 during the crossfade so the stance foot stays planted. Body speed peaks briefly at
  1.87× walking speed; the bones show no pop.
- **B's stop** (385) lands on walk-cycle frame 17, the mid-stance frame M6 and M7 use to stop
  without sliding.
- **Spacing:** the two are never closer than 1.57 m. They end side by side, B 0.81 m ahead and
  1.39 m to A's camera side.

## Cameras

| Shot | Lens | Subject | Camera position (m) | Offset or rotation |
|---|---|---|---|---|
| `sh01_question_wide` | 26 mm | host | (−3.2, −7.2, 1.45) → (−3.0, −6.8, 1.42) | offset +0.15 |
| `sh02_traveller_question` | 45 mm | traveller | (0.9, −2.5, 1.35) | offset −0.17 |
| `sh02b_road_ahead` | 60 mm | none (fixed) | (0.0, −0.6, 1.6) | (90°, 0, −130°), level |
| `sh03_host_response` | 40 mm | host | (5.25, −4.25, 1.5) | offset +0.2 |
| `sh04_host_leads` | 40 mm | host | (−0.5, −7.5, 3.0) | offset 0 |
| `sh04b_road_insert` | 35 mm | none (fixed) | (2.025, −6.921, 2.5) | (72°, 0, −120°) |
| `sh05_catch_up` | 32 mm | traveller | (−2.794, −4.415, 1.4) → (0.27, −6.986, 1.4), dolly at walking speed | offset 0 |
| `sh06_together_wide` | 55 mm | host | (1.0, −12.0, 1.5) | offset −0.1 |

- **180° rule:** every camera is on the same side of the line between A and B at every cut,
  continuing M7's side.
- **Light:** every tracking shot sees its subject's sunlit side.
- **Screen direction:** walkers move left to right, as in M7.

## Set: the road

- **Shape:** a `plane` primitive, 2.6 m wide, running along the route from 8.5 m to 62 m, with
  its centreline between the two walking lanes.
- **Placement:** 1 cm above the 100 m ground, ending within 3 m of the ground's edge (the
  horizon).
- **Look:** a dusty earth colour (0.36, 0.3, 0.2), roughness 0.95.

## Why it looks like this: preview reviews

Every preview went into a new folder under `storage/projects/m10_travellers_question/`; none
was overwritten.

1. **Geometry builds** (`geometry_rev1`–`rev3`):
   - Walk starts slid 7.3 cm, because the crossfade dragged the planted foot with the root.
     Easing the root fixed it.
   - A 1.5 m turn for A slid 3.4 cm; it became a ~2 m turn.
   - Camera tweaks cleared a head–tree tangent.
2. **`preview_rev1`:**
   - The lamp post rose out of A's head in sh05.
   - A's look didn't read.
   - The closing wide was too small.
   - In sh03 the post stood on the frame edge.
3. **`preview_rev2`:**
   - Added a road-ahead reaction cut, which showed only empty ground (there was no road).
   - sh04 had become tiny.
   - No sh05 camera on the correct side of the 180° line could keep the post clear.
4. **Revised blocking:** B walks on to 385 and A follows from 249, so the post no longer
   crosses either character in sh05.
   - The crossing moved into sh04 instead, where no camera, single or depth-staged shot avoids
     it.
   - So 289–336 became a road insert with no characters, making eight shots.
   - The road was added.
5. **`preview_rev3`:** the 0.5 m insert camera saw the road edge-on as a sliver, so it was
   raised. `preview_rev4` was the corrected render.
6. **`preview_rev5`:**
   - A's view showed the road as a separate patch, so the lens became 60 mm and level, and the
     road was extended to the horizon.
   - In sh04, tree crowns sat behind both heads, so the camera was raised to 3 m.
7. **Motion review on `preview_rev5`, then `final_rev1`.**

## Evidence (final render)

`storage/projects/m10_travellers_question/final_rev1/` (not tracked).

- **Render:** 576 frames, 640×360, h264 yuv420p, 24 fps, 24.0 s, summary `ok: true`. Render
  time 122 s; peak 487 MB working set, 1.8 GB committed.
- **MP4 SHA-256:** `907a8a5cb0b392adb372f09e6e2778f7026e80252e7b3c23f9188ffd5ef55a4a`.
- **Contact sheet and frame report:** flags only at cuts (97, 169, 241, 337).
- **Composition QA:** 0 errors and 10 warnings, all edge slivers.
  - **The one visible warning:** a tree2 trunk stub at the top edge of sh04, frames 282–288
    (3% of the frame deep). It comes from the raised camera that keeps the trees away from the
    heads; four alternative cameras did no better.
  - **The other nine show under 1% of the object.** One is a single frame (265) of tree1's
    crown at the top edge.
- **Foot slide** (largest drift of a planted contact point):
  - turns and walk starts 2.41–2.68 cm (limit 3 cm, fixed before measuring);
  - straight walking and standing 0.03 cm (limit 0.2 cm).
- **Pose pops:** at most 9.2°/frame at a walk start, against 7.5°/frame in a steady walk (M7's
  limit is 20°/frame).

## The complete film

- **Edit list:** `schemas/examples/the_greeting_film.edit.json`, M7 `final_rev2` followed by M10
  `final_rev1`, each pinned by SHA-256.
- **Command:** `python -m workers.assemble_film --edit schemas/examples/the_greeting_film.edit.json`
- **Output:** `storage/projects/the_greeting_film/the_greeting_film.mp4` (not tracked). SHA-256
  `938df2b8e0a4d3e3a6892b759dbb6ed11ab2380df33ed9f52419501381e8be65`.
  - 1,152 frames, 48.0 s, one h264 High stream at 640×360, 24/1 fps, time base 1/12288.
  - M7 is film frames 1–576 (0–24 s); M10 is film frames 577–1,152 (24–48 s).
- **Verification:**
  - the assembler reports `verified`;
  - a separate FFmpeg decode shows all 1,152 frames identical to M7's followed by M10's;
  - both sources' SHA-256 are unchanged;
  - all 5,554 earlier storage files are unchanged;
  - the log carries no local paths.
- **Approval:** verified is not approved. A human approves the film by watching it, at least
  across the scene cut at frames 576/577.

## Tests

- **`tests/test_m10_travellers_question_spec.py`** (57 tests, no Blender) covers:
  - continuity with M7, and the shot plan;
  - the action schedule, walk speeds, the stop phase, eased starts, the 2 m turns and facing
    while walking;
  - spacing and the lamp-post clearance;
  - the story beats: the look along the road, the reaction cut, and each beat on screen;
  - the 180° rule at every cut, framing, light and screen direction;
  - the post never behind a body;
  - both inserts showing no characters, plus road share and continuity;
  - the road never visible in M7;
  - no tree behind a head in sh04;
  - the film edit list.
- **`tests/test_m10_travellers_question_builder.py`** (9 Blender tests; builds without
  rendering) covers:
  - planted-foot drift per contact (3 cm while turning or starting, 2 mm otherwise);
  - the baton in B's left hand;
  - the held look giving way to the walk;
  - the camera active in each shot, and clearances;
  - no pose pops, with the walk starts and the stop within 1.3× the steady walk.

## Known limitations

- **B's head** restarts its look at M10 frame 1. A clip-offset feature would remove this; it
  isn't visible at the opening wide's scale.
- **The eased walk starts** briefly move the body at 1.87× walking speed. The bones show no
  pop, but only playback judges the feel.
- **The road insert is a still image** (a static camera with nothing moving) for 2 s.
- **sh04's raised camera** shows a trunk stub at the top edge for 7 frames.
- **The lamp post** stands where the road begins. Any route past it from the meeting point
  crosses it in some camera on the correct side of the 180° line. That's why the film cuts
  away at 289–336.
- **No new animation.** There is no pointing, nodding or faces; the question and answer are
  carried by gaze, staging and cutting.
- **Preview specs** (`render.quality: "animatic"`) were scratch copies of the committed spec;
  the committed spec is the final one.
