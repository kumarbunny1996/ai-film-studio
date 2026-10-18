# Milestone 8 — Shot QA

**Objective.** A reusable, read-only composition checker for built scenes. It measures what the
camera actually sees, frame by frame, and reports composition problems with evidence a person can
check: cropping, edge slivers, tangents, raised-hand contacts, line crossings, screen direction,
eyelines and backlight. Its findings are evidence for human review. It never approves a shot,
blocks encoding or changes a scene.

**Status.** Gates 1–3 accepted. Branch `milestone-8-shot-qa`, from `main` at `f9251af` (M7).

- **Gate 1:** a shared projection module and a read-only geometry inspector.
- **Gate 2:** the composition rules, the report contract and a regression corpus of
  historical M7 defects.
- **Gate 3:** an annotated composition sheet, plus the review-skill update.

## Pipeline

All three steps are fixed workers. No LLM-generated code runs, nothing is rendered, nothing
makes a network call, and no input is modified.

```
blender -b <shot>.blend --factory-startup --python-exit-code 1 \
    -P blender/scripts/inspect_shot_geometry.py -- --out review/shot_geometry.json
python -m workers.shot_qa --shot-dir <shot-dir> [--accepted <accepted.json>]
python -m workers.composition_sheet --shot-dir <shot-dir> [--include-info] [--force]
```

| Step | Output (`review/`) | Schema |
|---|---|---|
| Geometry inspector | `shot_geometry.json` | `shot_geometry.v1` |
| Composition rules | `composition_report.json` | `composition_report.v1` |
| Annotated sheet | `composition_sheet.png` + `composition_sheet.json` | `composition_sheet.v1` |

Each report and sheet carries `"verdict": "evidence_only"` and
`"human_approval_required": true`. The `film-animatic-review` skill describes the outputs and
how to read them.

## Gate 1 — projection and geometry

- **`workers/projection.py`** reproduces Blender's camera projection
  (`BKE_camera_params_compute_viewplane` / `world_to_camera_view`). It covers:
  - sensor fit AUTO, HORIZONTAL and VERTICAL;
  - pixel aspect;
  - lens shift;
  - near-plane triangle clipping;
  - a convex hull per mesh island;
  - a separating-axis test for overlap with the frame.

  Frame coordinates run from (0,0) at the bottom left to (1,1) at the top right. Depth is in
  metres.
- **`blender/scripts/inspect_shot_geometry.py`** loads a built `.blend`. For every frame (or a
  chosen set of frames) it records:
  - the active shot, taken from the `CUT-` markers;
  - the camera;
  - every object's outline, depth and in-frame flag;
  - per-island outlines labelled by vertex group (character parts);
  - armature bone projections.

  Objects map back to SceneSpec names through the builder's `PRIM-` and `ROOT-` naming.
  `--reference` compares the projection against Blender's own `world_to_camera_view`. M3, M4 and
  M7 agree within 1e-4 for points beyond `clip_start`.
- Output is deterministic: values are rounded to 6 decimals and keys are sorted.

## Gate 2 — rules and report

The report is `workers/shot_qa.py`, `composition_report.v1`. Rules work in frame-height units.
Per-frame hits are merged into runs of consecutive frames, and each run becomes one finding
with:

- its ID, rule and rule version, and severity;
- the shot, frame range and objects;
- the measured values and the threshold;
- the worst frame;
- an `accepted` annotation, if any.

The report also lists every rule with its thresholds and limitations, and a summary that counts
open findings by severity plus accepted findings.

| Rule | Severity | Checks |
|---|---|---|
| `wide_body_cropped` | error | In a wide shot, no in-frame character is cut by a frame edge |
| `head_cropped` | error | A character mostly in frame doesn't have its head cut |
| `subject_headroom` | warning | Medium or closer: headroom above the subject (≥ 0.02) |
| `raised_hand_cropped` / `raised_hand_headroom` | error / warning | A raised hand stays in frame, with a margin |
| `edge_sliver` | warning | No thin sliver of an object pokes in from an edge |
| `tangent` | error (head/neck), warning (other parts) | A character's outline doesn't just touch an object at a different depth (gap ≤ 0.012 or overlap ≤ 5%, depth separation ≥ 0.3 m, ≥ 6 frames). A sliding contact (median relative speed > 0.002) becomes info |
| `raised_hand_contact` | warning | A raised hand or forearm doesn't touch or cross an object (≥ 2 frames) |
| `camera_side` | error | Across a cut, the camera stays on the same side of the line between two characters |
| `screen_direction` | warning | A moving character keeps its screen direction across a cut |
| `eyeline` | warning | Gaze directions stay consistent across a cut |
| `backlight` | warning | The camera sees the sunlit side of prominent characters (a heuristic) |

**Accepted findings** come from a human-written `--accepted` file. They keep their severity and
measured evidence; they are only marked `{kind, reason}`.

- `accepted_issue`: a real issue a person accepted.
- `false_positive`: the finding itself is wrong.

The approved scenes' acceptances are in `tests/fixtures/m8_shot_qa/accepted_*.json`.

### Regression corpus (historical M7 defects)

`tests/fixtures/m8_shot_qa/corpus.json` builds each case from a preserved historical spec. The
specs are minified copies, with their source path and SHA-256 recorded. Each case's expected
rule must fire on the expected objects inside the case's window.

| Case | Source | Expected | Result |
|---|---|---|---|
| 1 | Gate 1 planning values (sh04 35 mm) | `wide_body_cropped` | **Not reproduced.** A is whole in frame at the cut, 0.040 frame heights from the left edge; the original report came from planning's box model. Kept as a documented non-detection |
| 2 | Gate 1 rev 1 | tree1 trunk `edge_sliver` at the top, sh02 | Detected |
| 3 | Gate 3 rev 1 | `raised_hand_contact`, host / lamp post, sh05 | Detected |
| 4 | Gate 3 rev 2 | tree2 crown `edge_sliver` at the left, sh05 | Detected |
| 5 | Final rev 1 | head / lamp post `tangent` (error), sh05 | Detected |
| 6 | Gate 1 first pass (sun azimuth 300°) | `backlight`, traveller, sh06 | Detected |
| 7 | Approved spec with the sh06 camera mirrored | `camera_side` (error) at 433 | Detected |

### Approved scenes

After the acceptances, M4, M6 and M7 have **0 open errors and 0 open warnings**.

| Scene | Accepted | Info |
|---|---|---|
| M7 The Greeting | 5: neck/tree2 crown (sh04, error); neck/tree3 crown (sh07, error); chest/lamp post and hips/lamp post (sh05); tree1 crown sliver (sh06) | 11 limb pass-bys during the sh03 walk |
| M6 character | 2: neck/right pillar (sh02, error); right pillar sliver (sh03) | 0 |
| M4 sequence | 2: pillar slivers (sh02, sh03) | 0 |

The M7 lamp post behind B's lowered arm is not flagged. A test pins this.

## Gate 3 — composition sheet

`workers/composition_sheet.py` draws one 640×360 tile for each error and warning, accepted ones
included. Info findings are counted in the header and drawn only with `--include-info`.

**Frame choice.** The tile uses the finding's worst frame if it was rendered. Otherwise it uses
the nearest rendered frame inside the finding's range. If no frame in the range was rendered,
the outlines are drawn on a plain background and the caption says so.

**Outlines.** They come from the geometry of the frame shown:

- the involved part, thick, in the severity colour (red error, amber warning, grey info);
- the rest of the object, thin white;
- the frame edge, for slivers.

**Caption.** Up to 8 lines, wrapped to the tile width:

- index, severity, rule, shot;
- frame range, worst frame, frame shown;
- objects;
- measured values;
- acceptance;
- finding ID.

**Index.** `composition_sheet.json` records, for every tile:

- the finding ID and rule;
- the frame shown and the rendered file;
- the outlines drawn;
- the tile's position.

It also records the SHA-256 of both inputs.

**How it's built.** Outlines are drawn in Python. FFmpeg decodes the frames, draws the captions
and composites in RGB, so outline colours are exact. The same inputs give a byte-identical PNG
and index.

**Failure handling** follows the contact-sheet worker:

- without `--force`, existing outputs are never replaced;
- a failed run leaves no output.

## Evidence

All under `storage/projects/m7_greeting/`. Earlier renders and evidence are unchanged
(1,919 storage files and 23 Gate 1 files verified by checksum).

- `m8_gate1_geometry/`: M7 geometry, reference checks for M3, M4 and M7, raw overlays.
- `m8_gate2_qa/`: Gate 2 reports for the corpus and the approved scenes.
- `m8_gate3_sheets/`: a report, sheet and index for corpus cases 1–7 and for approved M4, M6
  and M7.
  - Case 7 was never rendered, and case 3's raised-hand frames weren't rendered (only cut
    frames were), so those tiles use plain backgrounds.
  - The M6 sheet uses the M6 production-preview frames, whose geometry matches a fresh build.

## Performance (M7, 576 frames, 640×360)

| Step | Time | Peak memory |
|---|---|---|
| Inspector | 19.5 s | 480 MB |
| `shot_qa` | 15.2 s | 164 MB |
| `composition_sheet` | 1.5 s | 164 MB (mostly loading the 37.7 MB geometry; FFmpeg children not measured) |

## Tests

| File | Tests | Kind |
|---|---|---|
| `tests/test_projection.py` | 19 | fast |
| `tests/test_shot_qa.py` | 23 | fast (synthetic scenes) |
| `tests/test_composition_sheet.py` | 8 | fast (needs FFmpeg) |
| `tests/test_shot_geometry_inspector.py` | 11 | Blender |
| `tests/test_shot_qa_corpus.py` | 17 | Blender (builds without rendering) |

At Gate 3:

- the fast suite (`-m "not blender and not render"`) passed, 668 tests;
- the Blender inspector and corpus tests passed, 11 and 17;
- the render-marked M1 test was not run.

## Known limitations

- Geometry only. The rules see outlines, not pixels, so lighting, texture contrast and
  silhouette readability against similar colours aren't measured.
- Thresholds were calibrated on M4, M6 and M7 and the seven-case corpus. Other scene types may
  need recalibration.
- Convex hulls per island overstate concave shapes, so a gap inside a concave outline can be
  missed.
- `backlight` and `eyeline` are heuristics. Line and eyeline checks consider character pairs
  only.
- Camera-side and eyeline tiles outline whole characters.
- `shot_geometry.v1` is large (37.7 MB for M7). Size optimisation is deferred.
- The workers aren't wired into `run_milestone1` or the API yet. They're run by hand or from
  the review skill.
