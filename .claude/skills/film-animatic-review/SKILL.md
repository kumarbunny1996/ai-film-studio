---
name: film-animatic-review
description: Review checklist for a rendered animatic before the human_approval stage — run the contact-sheet worker, check its evidence (review/contact_sheet.png, review/frame_report.json) and the build outputs against explicit hard gates, then review framing, motion, lighting, continuity, cut boundaries (v1.3 multi-shot sequences) and frame aesthetics. Use after an animatic or smoke render finishes, when asked whether a shot is ready for approval, or when a render "looks wrong". Produces evidence and findings only; it never approves a shot.
---

<!-- Adapted from RobLe3/cc-blender-skill@a2634b588e80265e796aa53f8ab178d75105c2af,
     plugin/skills/animation-quality-gate/SKILL.md.
     MIT License, Copyright (c) 2026 RobLe3 (see LICENSE in this folder).
     Modified for AI Film Studio; every change is listed in UPSTREAM.md.
     The upstream script scripts/animation_contact_sheet.py is intentionally NOT included;
     the project worker workers/contact_sheet.py replaces it. -->

# Film Animatic Review (checklist)

Don't accept a shot because it rendered, or because the worker ran. Accept it
only when the evidence passes this checklist. Even then, **only a human
approves**: this checklist can say "ready for human approval", never
"approved".

## Four different things, never to be confused

| Outcome | What it means | What it does **not** mean |
|---|---|---|
| **Worker run succeeded** (exit 0, stdout `"status": "evidence_written"`) | Inputs passed validation and both review outputs were written for the frames on disk | That the shot is good, or even reviewable (gates below still apply) |
| **Flags and warnings** (`analysis.flags`, `warnings` in the report) | Diagnostic hints to look at in the frames | Proof of a defect, or, if absent, proof there is none |
| **Evidence sufficient for human review** (`READY_FOR_HUMAN_APPROVAL`) | Every hard gate passes and every warning and flag has been looked at | Approval |
| **Human approval** | A person accepted the shot | Something this skill, the worker or any render can produce |

The report always says `"verdict": "evidence_only"` and
`"human_approval_required": true`. Visual storytelling, composition,
animation quality and artistic intent always need human review.

## Rules

- Make the evidence only with the fixed worker below. Do **not** write ad-hoc
  contact-sheet or image-diff scripts, run one-off FFmpeg/Pillow/numpy
  commands to replace or supplement it, or install packages for it.
- Do **not** use Blender MCP or a live Blender session to inspect the shot.
- Do **not** use AI image or video models to judge, retouch or regenerate
  frames.
- You may look at `review/contact_sheet.png` and individual frames to write
  the review dimensions. Those notes support a human's decision; they don't
  replace it.

## Run the worker

```
uv run python -m workers.contact_sheet --shot-dir <shot-dir> [--samples N] [--cols N] [--thumb-width PX] [--force]
```

| Option | Default | Allowed | Meaning |
|---|---|---|---|
| `--shot-dir` | required | — | The shot directory, e.g. `storage/projects/milestone1/shots/m1_primitives` (it holds `build_report.json`, `spec.json` and `frames/`) |
| `--samples` | 12 | 1–200 | Frames on the sheet, evenly spaced; first and last are always included (a single-frame shot gives one) |
| `--cols` | 4 | 1–16 | Maximum grid columns |
| `--thumb-width` | 320 | 32–1920 | Thumbnail width in pixels; height follows the frame's aspect ratio |
| `--force` | off | — | Replace existing review output. Without it the worker refuses if either output exists |

On success it prints a JSON summary to stdout and exits 0. On failure it
prints `FAILED: <reason>` to stderr and exits 1:

- **If outputs already exist and `--force` wasn't given**, it refuses and
  leaves them untouched. Whether they belong to the current render is decided
  by hard gate 3.
- **Any other failure leaves neither output.** With `--force`, old outputs are
  removed first, so a failed rerun never leaves earlier results behind. FFmpeg diagnostics for the attempt are in
`review/contact_sheet.ffmpeg.log` and `review/frame_report.ffmpeg.log`.

Re-rendering a shot does **not** remove `review/`. After any re-render, run the
worker again with `--force` before reviewing.

## Composition QA (Milestone 8)

Three more fixed workers check composition from the built scene's geometry.
They are read-only: nothing is rendered, the scene isn't changed, and encoding
is never blocked. Run them in this order:

```
blender -b <shot-dir>/<shot_id>.blend --factory-startup --python-exit-code 1 \
    -P blender/scripts/inspect_shot_geometry.py -- --out <shot-dir>/review/shot_geometry.json
uv run python -m workers.shot_qa --shot-dir <shot-dir> [--accepted <accepted.json>]
uv run python -m workers.composition_sheet --shot-dir <shot-dir> [--include-info] [--force]
```

| Output (in `review/`) | Contents |
|---|---|
| `shot_geometry.json` (`shot_geometry.v1`) | Per frame: camera, active shot, projected outlines of every object and character part |
| `composition_report.json` (`composition_report.v1`) | Findings: `rule`, `severity`, `shot_id`, `frames`, `objects`, `measured`, `threshold`, `evidence.worst_frame`, `accepted`; plus `rules` and `limitations` |
| `composition_sheet.png` + `composition_sheet.json` (`composition_sheet.v1`) | One tile per error or warning: a rendered frame from the finding's range, with the involved part outlined thick in the severity colour (red error, amber warning), the rest of the object thin white and the frame edge for slivers. The caption gives the finding ID, rule, severity, frames, frame shown and measured values. The index records the frame and outlines of every tile |

- Like the frame report, these are **evidence only**
  (`"verdict": "evidence_only"`, `"human_approval_required": true`). A finding
  is a measured hint; no finding doesn't mean good composition.
- Check every tile in the frame itself. If a tile says "NO RENDERED FRAME",
  no frame in that range was rendered (e.g. a smoke render), so the outlines
  are on a plain background. Look at a full render before deciding.
- **`info`** findings, such as a limb sliding past an object, are counted in
  the sheet header and drawn only with `--include-info`.
- **Accepted** findings keep their severity and evidence, and are still
  drawn, with `accepted: {kind, reason}`. `accepted_issue` means a human
  accepted a real issue; `false_positive` means the finding itself is wrong.
  Only a human adds acceptances, in the `--accepted` file. Never use one to
  silence a finding nobody has looked at.
- Write each open error or warning down as a finding, or get it accepted.

## Evidence

Paths are relative to the shot directory unless stated.

| Evidence | Produced by | Key contents |
|---|---|---|
| Validated SceneSpec, `spec.json` | `workers/blender_job.py` (`SceneSpec` + `validate_against_manifest()`) | The shot as planned. The worker does not re-validate it |
| `build_report.json` | `blender/scripts/build_scene.py` | `status`, `warnings`, `frame_range`, `resolution` (actual rendered size), `fps`, `frames_dir`, `smoke` (smoke renders only); for v1.3 multi-shot: `shots`, `cuts`, and on smoke runs `smoke_frames` / `rendered_frames` |
| `frames/<shot_id>_####.png` | `build_scene.py` | One PNG per frame in `frame_range`; for a multi-shot smoke run only the `rendered_frames` stills are new (other files may be stale) |
| MP4 + `.ffmpeg.log` + `.summary.json` in the project directory | `workers/run_milestone1.py` only (`workers/encode.py`) | Encoded shot and ffprobe verification. `run_shot()` alone doesn't encode |
| **`review/contact_sheet.png`** | `workers/contact_sheet.py` | 8-bit RGB grid of sampled frames, in order, left to right, top to bottom. Each tile is labelled with its Blender frame number when `contact_sheet.labels` is true; unused cells are black |
| **`review/frame_report.json`** | `workers/contact_sheet.py` | Schema `frame_report.v1`; fields below |

`frame_report.json` fields to read:

- `verdict` (`"evidence_only"`), `human_approval_required` (`true`).
- `render`: `frame_range`, `frame_count`, `fps`, `resolution`,
  `source_pix_fmt`, `smoke`, `blender_version`, all copied from or checked
  against the build.
- `contact_sheet`: `sampled_frames`, `columns`, `rows`, `width`, `height`,
  `labels` (false means the label font was missing; see `warnings`).
- `analysis.frames[]`: per frame, `frame`, `yavg`, `ydif`, `scene_score`.
  `analysis.summary` holds `count`, `min`/`min_frame`, `max`/`max_frame` and
  `median` for each metric.
- `analysis.flags[]`: `frame`, `kind` (`dark_frame`, `large_difference`,
  `scene_change`, `brightness_jump`), `metric`, `value`, `threshold`.
- `analysis.thresholds`: the values the flags used, with
  `"calibrated": false`.
- `warnings[]`, `tools`, `logs`, `inputs`.

### Reading the metrics

All luma metrics are on an 8-bit scale (0–255), whether the PNGs are 8- or
16-bit.

- **`yavg`**: average brightness of the frame. Look at sudden changes
  between frames (`brightness_jump`) and very dark frames (`dark_frame`).
- **`ydif`**: mean brightness difference from the previous frame. It's high
  for fast motion and for glitches alike.
- **`scene_score`**: FFmpeg's scene-change score against the previous frame.
  High values suggest a cut or pop.

`ydif` and `scene_score` are `null` for the first frame (there's no previous
frame) and are left out of the summaries. These are **diagnostic signals
only**. The thresholds are uncalibrated, a flag is not a confirmed defect,
and no flags doesn't mean no defects. Check every flagged frame in the
frames themselves.

### Stale-frame warnings

The worker warns about PNGs in `frames_dir` outside `frame_range`, and about
expected frames older than `spec.json`. Animatic renders don't overwrite
existing frames, so leftovers from an earlier render are possible. These
warnings are **hints, not proof**: a frame can be older and still correct, and
no warning doesn't prove the frames are fresh. Resolve or record each one. If
you can't rule out mixed renders, report `NOT_REVIEWABLE` and ask for a clean
re-render.

**What an animatic is** (`setup_render` in `build_scene.py`): with
`render.quality: "animatic"`, the builder forces Eevee, at most 16 samples,
50% of `render.resolution` and no motion blur. A smoke render is also 50% and
stops after 8 frames. Judge framing, motion, timing and light direction, not
final image quality, noise or motion blur.

## Multi-shot sequences (SceneSpec v1.3)

**Pipeline:**
1. Validate the spec and render it in full:
   `uv run python -m workers.run_milestone1 --spec <spec.json> --project <project-dir>`.
   This validates the SceneSpec, renders the **whole timeline** in one Blender
   pass (cuts are camera switches on that timeline), checks every frame,
   encodes and runs ffprobe.
2. Check `build_report.json`: `status: ok`, `shots` (each shot's camera
   object, marker and settings) and `cuts`.
3. Encode **only a complete, contiguous frame sequence**. `run_milestone1`
   does this; don't encode frames by hand.
4. Run the contact-sheet worker on the shot directory.
5. Inspect compositions **and every cut**: open the frames immediately before
   and after each cut (`cuts[i] - 1` and `cuts[i]`), as well as the contact
   sheet, which may not sample cut frames.
6. A human approves. Nothing else does.

**Smoke mode for multi-shot specs** (`--smoke`) renders only the **first and
last frame of each shot**, at 50% resolution, as stills. It's a diagnostic
check that every shot camera renders. **It is not an animation.** Its report
lists `smoke_frames` and `rendered_frames`, while `frame_range` stays the full
timeline.

**Partial output is refused, from the report itself:**
- If `rendered_frames` doesn't cover every frame of `frame_range` exactly
  once, the encoder stops with "Partial (smoke) render; not encodable". The
  contact-sheet worker stops with "Partial (smoke) render; not reviewable".
  The same applies to malformed `rendered_frames` or `frame_range`.
- This holds **even when stale frame files from an earlier render fill the
  folder**: file existence, size and age are not evidence of completeness.
- The guard never deletes or modifies existing frames.
- Treat such a shot as `NOT_REVIEWABLE` and do a full render.

**Metrics at cuts are supporting evidence only.** A high `scene_score` or
`ydif` at a cut frame is expected, but it doesn't prove the cut is correct;
inspect the frames. The 180° rule and other continuity checks are **not**
automated (see `film-camera`).

## NOT_REVIEWABLE

Report `NOT_REVIEWABLE` with the reason when any of these apply.

- **The worker failed** (exit 1, `FAILED: …`). It fails, writing no outputs,
  when:
  - `build_report.json` is missing or unreadable, or `status` isn't `"ok"`;
  - `shot_id`, `frames_dir`, `frame_range`, `resolution` or `fps` is missing
    or invalid;
  - `frames_dir` is missing or outside the shot directory;
  - any expected frame is missing, or the first or last frame's size differs
    from `resolution`;
  - a frame can't be decoded, FFmpeg/ffprobe fails, is missing or times out,
    or the analysis covers fewer frames than expected;
  - the report's `rendered_frames` doesn't cover `frame_range` exactly once
    ("Partial (smoke) render; not reviewable").
- **Required outputs are missing**: either `review/contact_sheet.png` or
  `review/frame_report.json`.
- **The outputs aren't for this render**:
  - `frame_report.json` is older than `build_report.json`;
  - `render.frame_range`, `resolution` or `fps` in the report differs from
    `build_report.json`.
- **Unresolved stale-frame doubt** (see above).

## Hard gates (any failure = not ready)

1. `build_report.json` has `status: "ok"`; every warning is read and either
   resolved or written down as accepted, with a reason. While
   `blender/templates/` is empty, expect "no style template loaded; starting
   from an empty scene".
2. ffprobe verification passes against `build_report.json`: frame count from
   `frame_range`, `resolution` (already scaled for animatic or smoke renders)
   and `fps`. Don't compare resolution with the SceneSpec's
   `render.resolution`, which is full size. The frame range must match the
   SceneSpec unless it's a smoke render, and a smoke render is never accepted
   as final. A multi-shot smoke render can't be encoded at all ("Partial
   (smoke) render; not encodable").
3. The worker succeeded for this exact render: both review outputs exist,
   `frame_report.json` is newer than `build_report.json`, and its `render`
   block matches the build report.
4. Every entry in the report's `warnings` and `analysis.flags` has been checked
   in the frames and either explained (e.g. intended fast motion) or written
   down as a finding.
5. No character T-pose, no camera below ground or inside geometry, no
   subject leaving frame unintentionally.

## Review dimensions

Check each one and record pass, fail or not checked.

1. **Subject dominance:** the main subject reads first and isn't lost in the
   set, haze or background.
2. **Framing:** matches `camera.shot_size`; headroom and lead room are
   sensible; nothing critical is cropped; the horizon is deliberate (see
   `film-camera`).
3. **Silhouette and geometry stability:** no unintended pops, intersections,
   scale jumps or objects passing through each other.
4. **Motion coherence:** easing feels deliberate; arcs are clean; camera
   moves are motivated and smooth (no orbit drifting inward, no jitter unless
   `handheld_shake` is set); characters show no foot sliding.
5. **Lighting coherence:** exposure is stable, with no flicker or sudden
   brightness change; the light direction suits the mood (see
   `film-lighting`).
6. **Temporal artefacts:** flicker, popping or frame-to-frame jumps. Use the
   report's per-frame metrics to find candidates, then confirm or dismiss
   them in the frames. Don't judge this from the contact sheet alone; it
   samples only some frames.
7. **Continuity with neighbouring shots:** 180° rule, screen direction,
   time-of-day and lighting match.
8. **Frame aesthetics:** sampled frames work as stills — composition, depth
   layers, colour.

## Report format

```
ANIMATIC REVIEW — <shot_id>
Status: NOT_REVIEWABLE | CHANGES_REQUESTED | READY_FOR_HUMAN_APPROVAL
Render: <frames_dir>, frames <start>-<end>, <w>x<h> @ <fps>, smoke=<true|false>
Evidence: review/contact_sheet.png, review/frame_report.json (sampled <frames>)
Cuts (v1.3): <frame N-1 | N for each cut → camera before/after, checked visually>
Hard gates: 1 <pass/fail> · 2 <…> · 3 <…> · 4 <…> · 5 <…>
Flags/warnings: <each one → explained / finding>
Dimensions: <1–8 with pass / fail / not checked>
Findings: <each issue → which SceneSpec field to change, or which schema gap blocks it>
```

`READY_FOR_HUMAN_APPROVAL` needs every hard gate to pass. It means the
evidence is complete enough for a person to decide, not that the shot is
approved.

## When a shot fails

Fix the **spec**, not the render. Route each finding to a SceneSpec change
(camera via `film-camera`, lighting via `film-lighting`, composition via
`shot-composition`), re-validate, re-run the fixed pipeline, then re-run the
worker with `--force`. If the fix needs something the schema can't express,
write a schema-gap note instead of working around it. Stop rebuilding after
repeated failures on the same dimension and ask a human.
