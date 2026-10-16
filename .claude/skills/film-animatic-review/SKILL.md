---
name: film-animatic-review
description: Review checklist for a rendered animatic before the human_approval stage — technical checks, framing, motion, lighting, continuity and frame aesthetics, with explicit hard gates. Use after an animatic or smoke render finishes, when asked whether a shot is ready for approval, or when a render "looks wrong". Checklist only; it cannot mark a shot visually approved until the contact-sheet worker exists and its outputs are present.
---

<!-- Adapted from RobLe3/cc-blender-skill@a2634b588e80265e796aa53f8ab178d75105c2af,
     plugin/skills/animation-quality-gate/SKILL.md.
     MIT License, Copyright (c) 2026 RobLe3 (see LICENSE in this folder).
     Modified for AI Film Studio; every change is listed in UPSTREAM.md.
     The upstream script scripts/animation_contact_sheet.py is intentionally NOT included. -->

# Film Animatic Review (checklist)

Don't accept a shot because it rendered. Accept it only when the evidence
passes this checklist. Even then, **only a human approves**: this checklist
can say "ready for human approval", never "approved".

## Status: the visual quality gate is NOT operational yet

> **The contact-sheet / frame-difference worker does not exist yet.** It is
> planned as a fixed, tested project worker, to be designed and tested in a
> separate stage. Until it exists and its required outputs (below) are present
> for the exact render under review, **visual approval cannot be claimed**.
> Report the shot as `NOT_REVIEWABLE (visual gate unavailable)`, plus any
> technical findings.

While the worker doesn't exist:

- Do **not** write an ad-hoc contact-sheet or image-diff script, run one-off
  FFmpeg/Pillow/numpy commands to stand in for it, or install packages for it.
- Do **not** use Blender MCP or a live Blender session to inspect the shot.
- Do **not** use AI image or video models to judge, retouch or regenerate
  frames.
- You may look at individual PNG frames that already exist, as *preliminary
  notes*. Label them preliminary; they don't satisfy the gate.

## Evidence

| Evidence | Exists today? | Source |
|---|---|---|
| Validated SceneSpec for the shot | Yes | Passed `SceneSpec` + `validate_against_manifest()` |
| `build_report.json` (`status`, `warnings`, `frame_range`, `resolution`, `fps`, `frames_dir`) | Yes | Written by `blender/scripts/build_scene.py` |
| Rendered PNG frames `<shot_id>_####.png` | Yes | In `frames_dir` from the build report |
| Encoded MP4 + `.ffmpeg.log` | Yes, via `workers/run_milestone1.py` only | `workers/encode.py` (`run_shot()` in `workers/blender_job.py` alone doesn't encode) |
| ffprobe verification (frame count, size, fps) | Yes, via `workers/run_milestone1.py` only | `workers.encode.probe()` / `verify()` |
| **Contact sheet image** of sampled frames | **No — required** | Future contact-sheet worker |
| **Frame-difference report** (machine-readable, per frame pair, with warnings) | **No — required** | Future contact-sheet worker |

The worker's exact output file names, sampling rule and thresholds will be set
when it is designed. Don't invent them here or in a review.

**What an animatic is** (`setup_render` in `build_scene.py`): with
`render.quality: "animatic"`, the builder forces Eevee, at most 16 samples,
50% of `render.resolution` and no motion blur. A smoke render is also 50% and
stops after 8 frames. Judge framing, motion, timing and light direction, not
final image quality, noise or motion blur.

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
   as final.
3. The contact sheet **and** the frame-difference report exist for this exact
   render (same shot_id and frame range). **Currently always fails → status
   `NOT_REVIEWABLE`.**
4. No unexplained high frame-to-frame jump in the difference report (once
   thresholds exist).
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
6. **Temporal artefacts:** flicker, popping or frame-to-frame visual jumps.
   This needs the frame-difference report; don't claim it from a few frames.
7. **Continuity with neighbouring shots:** 180° rule, screen direction,
   time-of-day and lighting match.
8. **Frame aesthetics:** sampled frames work as stills — composition, depth
   layers, colour.

## Report format

```
ANIMATIC REVIEW — <shot_id>
Status: NOT_REVIEWABLE | CHANGES_REQUESTED | READY_FOR_HUMAN_APPROVAL
Render: <frames_dir>, frames <start>-<end>, <w>x<h> @ <fps>, smoke=<true|false>
Hard gates: 1 <pass/fail> · 2 <…> · 3 <…> · 4 <…> · 5 <…>
Dimensions: <1–8 with pass / fail / not checked>
Findings: <each issue → which SceneSpec field to change, or which schema gap blocks it>
Preliminary notes (not gate evidence): <optional>
```

`READY_FOR_HUMAN_APPROVAL` needs every hard gate to pass, so it can't be
reached until the contact-sheet worker exists.

## When a shot fails

Fix the **spec**, not the render. Route each finding to a SceneSpec change
(camera via `film-camera`, lighting via `film-lighting`, composition via
`shot-composition`), re-validate, and re-run the fixed pipeline. If the fix
needs something the schema can't express, write a schema-gap note instead of
working around it. Stop rebuilding after repeated failures on the same
dimension and ask a human.
