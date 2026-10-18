# Upstream provenance — film-animatic-review

| | |
|---|---|
| Repository | https://github.com/RobLe3/cc-blender-skill |
| Commit | `a2634b588e80265e796aa53f8ab178d75105c2af` (main, 2026-10-12) |
| License | MIT, Copyright (c) 2026 RobLe3 — upstream `LICENSE` copied unchanged to `./LICENSE` |
| Status | **Adapted (modified), checklist only** |

## Sources

| Upstream path | Upstream blob SHA | Used for |
|---|---|---|
| `plugin/skills/animation-quality-gate/SKILL.md` | `1932467d196bc695b6c5ee8a5ad4015811f32826` | `SKILL.md` |
| `plugin/skills/animation-quality-gate/scripts/animation_contact_sheet.py` | `a997a357954f652a25d29d6a43c38ac87dd7d58a` | **Not copied** (reviewed only) |
| `LICENSE` | `3ecc5d3f39fce33e91b7101ed3eab5ec4bc3077e` | `LICENSE` (unchanged) |

## Changes made

Removed:

- The `allowed-tools` frontmatter granting `mcp__blender__*` /
  `mcp__blender_official__*` tools, including `execute_blender_code`.
- The "MCP backend" section and its required read of the upstream file
  `plugin/skills/text-to-blender/references/mcp-backends.md` (not copied).
- The "RALPH trigger" and its chain-load of `quality-refinement-autoloop`.
- The upstream review dimensions "layer separation", "texture coherence" and
  "export truth", which belong to the upstream layered/GLB export workflow.
- Gates specific to the upstream project's exports: GLB texture-swap claims,
  HUD/avatar context elements, locked-geometry morphs.
- The `scripts/animation_contact_sheet.py` script. It needs Pillow, which
  isn't in the project `.venv`, `uv.lock`, system Python or Blender's bundled
  Python. It has unbounded input and output paths, overwrites silently,
  doesn't create the report's parent folder, and loads all frames into
  memory at once.
  It is replaced by the project's own worker, `workers/contact_sheet.py`
  (project commit `5992e2c`), which is FFmpeg-only and covered by tests.

Kept and adapted:

- "Don't accept an animation because it rendered."
- "No final animation without a contact sheet" (now hard gate 3, which also
  requires the frame report and that both match the current render).
- Review dimensions: subject dominance, silhouette stability, motion
  coherence and frame aesthetics, re-scoped for film shots.

Added (project-specific, not from upstream):

- A table separating a successful worker run, informational flags and
  warnings, evidence sufficient for human review, and human approval.
- A ban on ad-hoc stand-in scripts, MCP inspection and AI image/video models.
- How to run `workers/contact_sheet.py` (CLI options, exit behaviour,
  `--force`), an evidence table with its outputs `review/contact_sheet.png`
  and `review/frame_report.json` (`frame_report.v1` fields), how to read the
  YAVG/YDIF/scene-score metrics and stale-frame warnings as hints only, and
  the `NOT_REVIEWABLE` conditions, as read from project commit `5992e2c`.
  (Until that commit, this section said the worker did not exist yet.)
- A note on what animatic and smoke renders are (Eevee, 50% resolution, no
  motion blur; smoke = 8 frames), and resolution checks done against
  `build_report.json`, as read from project commit `13dd49a`.
- Hard gates, dimensions for lighting, temporal artefacts and continuity, a
  report format with statuses (`NOT_REVIEWABLE`, `CHANGES_REQUESTED`,
  `READY_FOR_HUMAN_APPROVAL`; never "approved"), and routing of fixes to
  SceneSpec fields via `film-camera`, `film-lighting` and `shot-composition`.

Updated for SceneSpec v1.3 (Milestone 4, project branch `milestone4/multishot-schema`):

- A multi-shot section: the full-render pipeline with `run_milestone1`, the
  `shots`/`cuts` build-report fields, and reviewing the frames either side of
  every cut as well as the contact sheet.
- What multi-shot smoke mode renders (first and last frame of each shot, 50%,
  stills), and the encoder and contact-sheet refusals of partial
  `rendered_frames` reports, which hold even when stale frames fill the folder.
- Scene-change metrics at cuts are supporting evidence only; the 180° rule is
  not automated.
- The partial-render refusal added to NOT_REVIEWABLE and the hard gates, and a
  Cuts line in the report format.

Updated for Milestone 8 (Shot QA, project branch `milestone-8-shot-qa`):

- A Composition QA section: the fixed workers `inspect_shot_geometry.py`,
  `workers.shot_qa` and `workers.composition_sheet`, their `review/` outputs,
  evidence-only semantics, and what `info`, `accepted_issue` and
  `false_positive` mean.

Updated for Milestone 9 (film assembly, project branch `milestone-9-film-assembly`):

- A Film assembly section: the fixed worker `workers.assemble_film`, its EditList input,
  outputs and no-overwrite policy, and that a verified film still needs human approval.
