# Milestone 11 — Readable attention (head-direction marker)

**Objective.** Make the mannequin's head direction readable on screen, so looks (M7, M10)
read at medium and wide shot sizes, using a simple head marker. Candidates were judged in blind
still tests against pre-registered thresholds. There are no new rigs, faces or actions.

**Status.** Closed on 2026-10-21 by the user's decision: **adopt A**, the D3 marker of rev3.
Gate 3 added A to the mannequin as two new character assets, `mannequin_marked` and
`mannequin_ochre_marked`; the unmarked mannequins, M7 and M10 are unchanged. Read the caveats
below before relying on the test results.

## Adopted design: A (rev3's D3)

Both parts are parented to the `head` bone. Positions are in the rig's rest frame (metres; the
character faces −Y).

| Part | Size (W × D × H) | Centre | Material |
|---|---|---|---|
| Visor | 0.13 × 0.05 × 0.035 | (0, −0.085, 1.67) | Principled, base colour (0.03, 0.03, 0.035), roughness 0.35 |
| Nose | 0.035 × 0.05 × 0.04 | (0, −0.115, 1.625) | The body material of each character |

## Test method

- Two mannequins (grey and ochre) in one still, each with its head at one of seven angles
  relative to the camera (0, ±40, ±90, ±140 degrees). Body turns of ±40 degrees were assigned
  at random so the body did not give the answer away.
- Medium camera (40 mm, head about 23 px wide at 320×180) and wide camera (32 mm, about 7 px).
- 56 stills per round at 320×180. Each pose appears once per design, ids are opaque and
  random, and the four versions of a pose sit on four different review pages.
- Scoring: eight direction bins; exact = 1, adjacent bin = 0.5, other = 0, `?` = 0.
  A design passes when, for every reviewer, both colours score ≥ 6.5/7 on the medium camera
  and ≥ 5.5/7 on the wide camera.

## History

| Round | Designs | Outcome |
|---|---|---|
| rev1, rev2 | D0–D3 | Pipeline and preflight development. |
| rev3 | D0 (none), D1 (wide visor), D2 (cap), D3 (visor + nose) | Two reviewers. None passed. D3 best (medium 5.5–6.0, wide 4.5–5.5), D1 next, D0 0–2.5. The main failure was three-quarter views read as profiles. |
| rev4 aborted run | A–D | Stopped after 32 of 168 images: the head-presence check used a fixed 100 px minimum that only suits the medium camera. Fixed to medium 100 px and wide 19 px; the partial run is preserved as `marker_test_rev4_aborted1`. |
| rev4 | A = D3, B = A with a matte marker (roughness 0.85), C = visor 0.11 m wide (chosen by the pre-registered rear-cue rule), D = C + B's material | All 172 renders passed every validation (reproduction of rev3, isolation, masks). Official result: no candidate passed, every cell 6.0 (medium) / 6.0 (wide). The two forms were byte-identical and never used TL or TR, so every three-quarter view counted as a miss. |
| rev4 resubmission | — | One revised form, made after the reveal and mixing left/right conventions. Kept as supplementary only (`scores_supplementary_post_reveal.json`). |
| Review round 2 | A–D, same rev4 images | New ids (Q01–Q56), new seed, anatomical labels (the figure's own left and right, counted as a turn from facing the camera), written instructions with worked examples, forms locked before the reveal. The two forms were byte-identical; the user accepted them as a recorded protocol deviation. 112/112 answers exact, so all four designs pass. The rule recommends B only through its simplicity tie-break. |

## Decision

The user accepted the round-2 result and chose A. All four designs scored identically, so
nothing favours the changes in B, C or D, and A is the design already specified and validated
in rev3 and rev4.

## Caveats

- **No round produced two independent judgements.** In rev4 and in round 2 the two forms were
  the same file.
- **Round 2 cannot rule out contamination.** Its perfect score is far above every earlier round
  (for example, the wide camera's 7 px heads and every three-quarter view were all exact). It
  reused images whose angles rev4's reveal had already published, and independence of the
  reviewers could not be verified.
- **Label conventions differ between rounds.** rev1–rev4 scored screen direction; round 2
  scored anatomical direction (the truth map mirrored; points, adjacency and thresholds
  unchanged).
- The evidence therefore supports A as acceptable to the user, not that A meets the thresholds
  under independent review or that it beats B, C or D.

## Gate 3: the marked characters

`mannequin.py --set m11` writes `characters/mannequin_marked.blend` and
`characters/mannequin_ochre_marked.blend`. Each is the mannequin with marker A added to its
body mesh as two boxes (`MARKER_A`) rigidly weighted to the `head` bone, under its own
collection, armature, body and marker-material names. Material slot 2 is the marker (roughness
0.35); every other material keeps roughness 0.6. The rig, bones, rig type and actions are
unchanged, so every `afs_mannequin_v1` action plays on them. The m6 and m7 sets are unchanged.

- **Baseline:** these character files are never byte-identical between authoring runs (Blender
  writes session-specific bytes), so, as in the existing asset tests, determinism is the
  structural fingerprint of `blender/scripts/inspect_asset.py`. The modified script still
  produces the pinned fingerprints for all five existing files, and the two action files byte
  for byte.
- **Tests:** `tests/test_mannequin_marker_tables.py` (plain Python: the exact design, matching
  the M11 experiment's constants, placement in front of the head) and
  `tests/test_mannequin_marked_assets.py` (Blender: files, pinned fingerprints, material slots
  and roughness, 16 extra head vertices, the exact box corners, the rig, and every existing
  action posing the marked rig exactly like the unmarked one).
- **Equivalence:** `tools/m11_marker_test/gate3_equivalence.py` re-rendered rev3's two
  reference stills (S21 medium, S50 wide) with the marked assets and no test-harness markers
  (four renders: two beauty, two masks). Both masks and the wide beauty are pixel-identical to
  the M11 references; the medium beauty differs in one pixel by 1/255, within the criterion of
  at most 2/255 outside a 2 px band around the marker. Report:
  `marker_test_rev4_gate3_equivalence/equivalence_report.json`.

The approved films keep the unmarked assets; new scenes choose the marked ones by asset id.

## Evidence

All under `storage/projects/m11_readable_attention/` (not in Git):

- `marker_test_rev1` … `marker_test_rev3`: earlier rounds, unchanged.
- `marker_test_rev4_aborted1`: the stopped run (33 files), preserved unchanged.
- `marker_test_rev4`: the 56 stills, blind pages and form, the revealed key, masks, diagnostics,
  `scores.json` and the supplementary scores.
- `marker_test_rev4_review2`: the reviewer packets, instructions, examples, `answer_key.json` and
  `scores.json` (with the lock record and the deviation).
- `marker_test_rev4_gate3_equivalence`: the Gate 3 reference copies, renders and report (the
  masks are in the private folder).

Private records (assignments, locked forms, validation records) are in
`%LOCALAPPDATA%\AI-Film-Studio\private\m11\`, which only the user's account and SYSTEM can
read. The original rev1–rev3 scripts and private records are archived in
`%LOCALAPPDATA%\AI-Film-Studio\private\m11_rev1_rev3_archive\`, with `ARCHIVE_MANIFEST.json`.

## Tools

`tools/m11_marker_test/`:

- `marker_test.py`: builds the scene, preflight P1–P12, renders, validates (`--design-set rev4`).
- `scan_masks.py`: label scan of every mask.
- `make_sheets.py`: blind pages, answer forms and scoring.
- `review_round.py`: a new blind review of existing images (`--prepare`, `--lock`, `--reveal`).
- `gate3_equivalence.py`: the Gate 3 comparison of the marked assets with the M11 references.

`.gitattributes` pins these scripts to LF line endings.

## Remaining work

- Use the marked characters in new scenes (M12 onward). M7 and M10 stay unmarked unless a
  re-render is separately decided.
- Future perception tests: two reviewers who have never seen the material, each sending their
  own form.
