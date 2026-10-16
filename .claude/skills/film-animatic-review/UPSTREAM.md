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
  A fixed, tested project worker will replace it in a separate stage.

Kept and adapted:

- "Don't accept an animation because it rendered."
- "No final animation without a contact sheet" (now hard gate 3).
- Review dimensions: subject dominance, silhouette stability, motion
  coherence and frame aesthetics, re-scoped for film shots.

Added (project-specific, not from upstream):

- A status box saying the contact-sheet worker doesn't exist and visual
  approval can't be claimed until its outputs exist.
- A ban on ad-hoc stand-in scripts, MCP inspection and AI image/video models.
- An evidence table listing which inputs exist today (`build_report.json`,
  PNG frames, MP4 and ffprobe verification via `workers/run_milestone1.py`)
  and which are required but missing.
- A note on what animatic and smoke renders are (Eevee, 50% resolution, no
  motion blur; smoke = 8 frames), and resolution checks done against
  `build_report.json`, as read from project commit `13dd49a`.
- Hard gates, dimensions for lighting, temporal artefacts and continuity, a
  report format with statuses (`NOT_REVIEWABLE`, `CHANGES_REQUESTED`,
  `READY_FOR_HUMAN_APPROVAL`; never "approved"), and routing of fixes to
  SceneSpec fields via `film-camera`, `film-lighting` and `shot-composition`.
