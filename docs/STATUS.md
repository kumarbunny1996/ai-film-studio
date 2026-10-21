# AI Film Studio — Project Status

_Reviewed 2026-10-19 against `main` @ `6a25118` (Milestone 10) and `storage/projects/`._

**Vision:** written story → 3D animated film, using existing AI models, reusable tools and
Blender. No foundation-model training, no AI video generation.

**Pipeline:** story → screenplay → shot_list → asset_resolution → scene_build → animatic →
human_approval → final_render → edit → final_film

| Stage | State |
|---|---|
| story → screenplay | ⬜ Not started |
| screenplay → shot_list | ⬜ Not started |
| asset_resolution | 🟨 Manifest + preflight exist; no automatic resolution |
| scene_build (SceneSpec → Blender) | ✅ Working (v1.3, multi-shot) |
| animatic + automated QA | ✅ Working (contact sheet, shot QA, composition sheet) |
| human_approval | 🟨 Manual, via review skill; no UI or recorded approval state |
| final_render | 🟨 Eevee 640×360 only |
| edit (assembly) | ✅ Working (stream-copy, video only) |
| final_film | 🟨 48 s, two-scene silent film made from hand-written specs |

---

## ✅ Completed

- **Foundations** — `CLAUDE.md` rules, uv/pytest setup, configurable Blender/FFmpeg paths
  (`workers/config.py`), film planning skills (camera, lighting, composition, animatic review).
- **M1** — SceneSpec v1.1 primitives, headless procedural Blender build, FFmpeg encode with
  ffprobe verification.
- **M2** — Contact-sheet worker with streamed FFmpeg frame analysis.
- **M3** — SceneSpec v1.2: camera framing, clipping, depth of field. Non-finite number rejection.
- **M4/M5** — SceneSpec v1.3 multi-shot scenes with timeline-marker cuts; visual pass.
- **M6** — Mannequin character library (authored in code) with the R1S walk cycle and idle.
- **M7 — The Greeting** — 24 s, 8-shot, two-character scene with look and wave gestures
  (ochre variant, baton prop).
- **M8 — Shot QA** — read-only geometry inspector, projection model, composition rules,
  regression corpus, annotated composition sheet.
- **M9 — Film assembly** — `EditList` 1.0 contract and deterministic assembler (SHA-256 pinned clips).
- **M10 — The Traveller's Question** — second scene; assembled with M7 into
  `the_greeting_film` (48 s). Approved 2026-10-18.
- **M11 — Readable attention** — head-direction marker tests (rev1–rev4, review round 2).
  Closed 2026-10-21: the user adopted **A** (rev3's D3 visor + nose). The test results are
  weak (no two independent reviewers); see `docs/m11_readable_attention.md`. Gate 3 added the
  new assets `mannequin_marked` and `mannequin_ochre_marked` (`mannequin.py --set m11`); the
  unmarked mannequins and the M7/M10 films are unchanged.
- **Tests** — 35 test modules (~10,000 lines) covering schemas, builders, assets, QA, assembly.

## 🟨 In progress

- Nothing in progress.

## ⬜ Pending

### Front half of the pipeline (the core of the vision — nothing built yet)
- [ ] Story → screenplay: LLM call with a Pydantic `Screenplay` schema (scenes, beats, characters, dialogue).
- [ ] Screenplay → shot list: LLM call with a `ShotList` schema, guided by the film-camera/lighting/composition skills.
- [ ] Asset resolution: map characters, props, places and actions to manifest IDs only; report what's missing.
- [ ] Shot list → SceneSpec generator, with a validate → error feedback → retry loop.
- [ ] Blocking/layout solver: deterministic placement, paths, walk-speed timing and turn arcs,
      so the LLM doesn't hand-compute coordinates (M7/M10 were hand-tuned).
- [ ] Anthropic API client, prompts, keys in env vars, cost/latency logging.

### Asset and animation library (the main limit on which stories can be told)
- [ ] Remove or supply the 4 manifest entries whose files don't exist (`shepherd_girl`, `sheepdog`,
      `alpine_meadow`, `human_actions.blend`). The rule is "never invent asset paths."
- [ ] Import pipeline for existing rigged characters and CC0/licensed animations
      (retarget to a standard rig) instead of authoring every asset in code.
- [ ] Wider action vocabulary: turn in place, sit, run, point, pick up/hand over, talk gestures.
- [ ] Faces/expressions (or a deliberate stylised alternative) and environment kits.

### Sound
- [ ] Dialogue (TTS), timing from audio length, lip sync or a talk gesture.
- [ ] Music and SFX beds; audio tracks in `EditList` and the assembler (currently `audio: none`).

### Production quality
- [ ] Final-render profile (higher resolution / samples; Cycles option) separate from previews.
- [ ] Assembler conform/re-encode mode, transitions, titles.
- [ ] Recorded approval state per shot (who, when, which revision).

### Product / platform (from `CLAUDE.md` stack)
- [ ] FastAPI backend (`apps/api` has schemas only).
- [ ] PostgreSQL models for projects, shots, revisions and approvals.
- [ ] Redis + arq job queue around the existing workers.
- [ ] React/TS/Vite dashboard (`apps/web` is empty): story input, shot review, approve/reject.
- [ ] `blender/templates`, `.claude/agents`, `.claude/commands`; Docker/WSL setup.

### Housekeeping
- [ ] Update stale status lines in `docs/m7_greeting.md` and `docs/m9_film_assembly.md`
      (they still say "under review" or "main is still M8").
- [ ] Delete merged milestone branches once they are confirmed merged.

---

## Recommended next steps

1. **M12 — Thin end-to-end slice.** A 3–5 sentence story goes to the LLM, which produces a screenplay,
   then a shot list, then a SceneSpec using only the existing mannequins (the marked variants),
   walk, idle, look and wave. The existing builder renders it to an MP4. Crude output is fine; the
   goal is to prove the "story in" step.
2. **M13 — Blocking solver**, so the LLM describes intent (who goes where, when) and code
   computes coordinates.
3. **M14 — Asset import + action library**, driven by what the M12 stories asked for and couldn't get.
4. **M15 — Dialogue and audio.**
5. **Then** API, queue, database and dashboard around a pipeline that already works.
