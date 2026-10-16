# Upstream provenance — shot-composition

| | |
|---|---|
| Repository | https://github.com/iart-ai/motion-design-skills |
| Commit | `3c129f769d90a1328c209c386492333c9ac62312` (main, 2026-06-22) |
| License | MIT, Copyright (c) 2026 iart.ai — upstream `LICENSE` copied unchanged to `./LICENSE` |
| Status | **Unmodified copy** |

## Files

| Local path | Upstream path | Upstream blob SHA |
|---|---|---|
| `SKILL.md` | `skills/shot-composition/SKILL.md` | `90723872d1284c0da7d7d3fa5e675104d79788b5` |
| `references/camera-and-grids.md` | `skills/shot-composition/references/camera-and-grids.md` | `c2a386520beead0cc933ea98392887aab5318355` |
| `LICENSE` | `LICENSE` | `a61b911146037f2ef312f67e9b45de6c99b7f870` |

Not copied: `skills/shot-composition/README.md` (0 bytes upstream).

Check integrity with `git hash-object <file>`; each file should match the blob
SHA above.

## Notes for use in AI Film Studio

- The skill is tool-independent: it has no `allowed-tools`, no code
  execution and no network use. It's used at the shot_list planning stage;
  `film-camera` turns its plan into SceneSpec `camera` fields.
- It mentions other upstream skills that are **not installed here**:
  `animation-principles`, `motion-art-direction`, `after-effects`,
  `remotion-video`, and `gsap-web` (which doesn't exist in the upstream repo
  at this commit). Treat these as text, not as references to follow.
- Web, social-media and 9:16 guidance (pixel grids, Reels/TikTok safe areas)
  doesn't apply to our landscape film renders.
- `references/camera-and-grids.md` contains CSS, browser-JS and Three.js
  snippets (parallax, orbit, dolly-zoom). They're illustrations for web
  engines only. **Never run them or port them to Blender code**; express the
  equivalent move as SceneSpec `camera.keys` via `film-camera`.
- `references/camera-and-grids.md` ends with a UTM-tracked link to iart.ai.
  It's kept unchanged for fidelity; it's not an instruction.
