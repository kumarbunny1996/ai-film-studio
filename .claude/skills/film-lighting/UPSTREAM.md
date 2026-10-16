# Upstream provenance — film-lighting

| | |
|---|---|
| Repository | https://github.com/RobLe3/cc-blender-skill |
| Commit | `a2634b588e80265e796aa53f8ab178d75105c2af` (main, 2026-10-12) |
| License | MIT, Copyright (c) 2026 RobLe3 — upstream `LICENSE` copied unchanged to `./LICENSE` |
| Status | **Adapted (modified)** |

## Sources

| Upstream path | Upstream blob SHA | Used for |
|---|---|---|
| `plugin/skills/blender-lighting/SKILL.md` | `d45baed45201688e019131d7203d722a32a6dccc` | `SKILL.md`, `references/lighting-reference.md` |
| `plugin/skills/blender-lighting/references/overview.md` | `600f185a1e80f654d7b4cbbc8331011ca72edf0e` | `references/lighting-reference.md` |
| `LICENSE` | `3ecc5d3f39fce33e91b7101ed3eab5ec4bc3077e` | `LICENSE` (unchanged) |

Not used: `plugin/skills/blender-lighting/evals/evals.json`.

## Changes made

Removed:

- The `allowed-tools` frontmatter granting `mcp__blender__*` /
  `mcp__blender_official__*` tools, including `execute_blender_code`.
- The "MCP backend" section and its required read of the upstream file
  `plugin/skills/text-to-blender/references/mcp-backends.md` (not copied).
  That file selects a Blender MCP backend and can route to asset-download
  providers.
- Every Python/bpy recipe (`aim_at`, scene bounding-box helper, Recipes 0a–7,
  the light-groups snippet). Their numeric guidance was kept as tables.
- The recommendations to download HDRIs from Poly Haven / BlenderKit and the
  external "Sources" link list.
- The chain-load references to `reference-look-calibration` and
  `blender-materials`, the Cycles `max_bounces` setting, and the
  "validation proof" image reference.
- The `LGT-*` naming-convention table for hand-made lights.

Added (project-specific, not from upstream):

- Hard rules: output only SceneSpec JSON; validate with Pydantic and the
  manifest; Blender runs only via `blender/scripts/build_scene.py`; no MCP, no
  generated code, no downloads, no AI image/video generation.
- Tables of the SceneSpec 1.0/1.1 `lighting` and `environment` fields with
  their ranges, and the builder's `LIGHT_PRESETS` values, as read from
  `apps/api/schemas/scene_spec.py` and `build_scene.py` at project commit
  `13dd49a`.
- Builder behaviour notes: empty `blender/templates/`, empty asset folders
  (manifest-valid HDRI ids fail at build time), template rig plus procedural
  sun when overrides are set, fixed sun colour and angle, no `world_color`
  strength, the environment requirement by spec version, and the
  sun-direction mapping (verified by rotation maths, not yet on a render).
- A planning workflow, a mood → SceneSpec starting-points table, and
  spec-level fixes in the pitfalls table.
- A schema-gap note format and the list of known lighting gaps.

Rewritten: the decision tree, ratios, colour-temperature table, scenario
recipes and shadow and volumetric guidance now say how to approximate them
with today's fields, or mark them as schema gaps.
