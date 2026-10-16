# Upstream provenance — film-camera

| | |
|---|---|
| Repository | https://github.com/RobLe3/cc-blender-skill |
| Commit | `a2634b588e80265e796aa53f8ab178d75105c2af` (main, 2026-10-12) |
| License | MIT, Copyright (c) 2026 RobLe3 — upstream `LICENSE` copied unchanged to `./LICENSE` |
| Status | **Adapted (modified)** |

## Sources

| Upstream path | Upstream blob SHA | Used for |
|---|---|---|
| `plugin/skills/blender-cameras/SKILL.md` | `eb3ab060c1267cb4e4e8bccd235bd25426d68e60` | `SKILL.md`, `references/camera-reference.md` |
| `plugin/skills/blender-cameras/references/overview.md` | `8d7323fbcd8cd957297e283d94d9d246c17ecb89` | `references/camera-reference.md` |
| `LICENSE` | `3ecc5d3f39fce33e91b7101ed3eab5ec4bc3077e` | `LICENSE` (unchanged) |

Not used: `plugin/skills/blender-cameras/evals/evals.json`.

## Changes made

Removed:

- The `allowed-tools` frontmatter granting `mcp__blender__*` /
  `mcp__blender_official__*` tools, including `execute_blender_code`.
- The "MCP backend" section and its required read of the upstream file
  `plugin/skills/text-to-blender/references/mcp-backends.md` (not copied).
- Every Python/bpy recipe: the bounding-box hero camera, portrait,
  establishing, product, composition overlay, orbit pivot, dolly, and the
  compositor snippets. Their guidance was kept as tables and key patterns.
- The viewport composition-overlay recipe (it has no effect on renders) and
  the `GEO-`/`CAM-` naming assumptions.
- The external "Sources" link list.

Changed:

- The framing formula now uses our builder's fixed 36 mm sensor *width* and
  the render aspect ratio. Upstream used a 24 mm sensor height (3:2 full
  frame).
- FOV figures are now horizontal angles for 36 mm. Upstream quoted
  approximate diagonal angles; the reference file notes the difference.
- The orbit recipe (pivot empty plus a 360° rotation key) is rewritten as
  camera-key placement, with a warning that per-axis interpolation cuts
  inside the arc.
- Pitfall fixes are now expressed as spec-level changes.

Added (project-specific, not from upstream):

- Hard rules: output only SceneSpec JSON; validate with Pydantic and the
  manifest; Blender runs only via `setup_camera()` in
  `blender/scripts/build_scene.py`; no MCP, no generated code, no AI
  image/video generation.
- A table of the SceneSpec `camera` fields, their defaults and the builder's
  behaviour, as read from project commit `13dd49a`: aim point centred,
  `look_at_height` also sets focus and follows instance scale and rotation,
  per-key lens animation overrides `camera.lens_mm`, f-stop ignored without a
  focus target, and the shake implementation.
- A shot-size → frame-height heuristic, the headroom rule
  (`look_at_height ≈ eye_height − H/6`), an explicit-rotation formula for
  off-centre framing (verified numerically, not yet on a render), and an
  Euler-unwrap rule for rotation keys.
- A camera-move pattern table, a validator/builder checklist, the division
  of labour with `shot-composition` and `film-lighting`, a schema-gap note
  format and the list of known camera gaps.

Updated for SceneSpec v1.2 (Milestone 3, project branch `milestone3/camera`):

- A versions table; the v1.2 fields `framing.subject_offset`, `clip_start_m`,
  `clip_end_m` and `focus_distance_m`; finite-number validation; and each
  field marked as measured by `tests/test_camera_builder.py` or builder code
  only.
- Subject placement by `framing.subject_offset`. Its sign convention and
  lens-shift formula were measured with `world_to_camera_view` for 16:9,
  2.39:1 and square frames; portrait frames are refused. This replaces the
  earlier advice to place subjects off-centre by changing the rotation.
- An explicit depth-of-field strategy table with the v1.2 focus rules, a
  clipping section, and legacy 1.0/1.1 behaviour with the build-report
  warnings the worker adds.
- The verified example `schemas/examples/m3_framing.json`, and a pointer to
  contact-sheet review as evidence that still needs human approval.
- Known gaps updated: aim offset, clipping and focus distance are no longer
  gaps; roll with `look_at`, non-perspective projection, sensor control,
  portrait framing, per-key focus and path cameras still are.
- `references/camera-reference.md`: two sentences updated for focus distance
  and subject offset.
