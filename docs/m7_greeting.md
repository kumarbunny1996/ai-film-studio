# Milestone 7 — The Greeting

**Objective.** A 24-second, eight-shot scene in which one mannequin (B, the host) notices another
(A, the traveller) approaching and the two greet each other. It is built from SceneSpec v1.3 and
the existing pipeline, plus two upper-body gestures (look, wave) and an ochre variant of the host.

**Status.** Gate 3 (integration) is under review; the full film is not rendered yet.

- **Gate 1:** the staging prototype, `schemas/examples/m7_greeting.json`, using only the walk
  and idle.
- **Gate 2:** the look and wave gestures and the ochre variant, as assets.
- **Gate 3:** B is the ochre variant, A the grey mannequin, and the gestures are scheduled on
  the beats (see "Gate 3 — integration" below).

## Story

At golden hour, B waits beside a lamp post with a baton in hand. B looks toward the road. A walks
in from the left and stops a few steps away. B waves; A waves back. The two stand together as the
camera pulls back.

## Beat sheet

| # | Beat | Frames | Seconds | What carries it at Gate 1 | Gate 2 adds |
|---|---|---|---|---|---|
| 1 | B waits alone | 1–84 | 0.0–3.5 | Wide on B; empty road on screen left | — |
| 2 | B notices someone coming | 85–124, then 125–168 | 3.5–7.0 | Slightly high medium from B's left (slightly in front): B in left profile facing screen left (A's side), with lead room; head against the ground, lamp post out of frame; slow push-in. Gate 3 revision: cut on the completed look to sh02b, a reaction shot over B's left shoulder showing A far down the road | `mannequin_look`: head and chest turn about 40° to B's right, toward A, and hold |
| 3 | A approaches | 169–264 | 7.0–11.0 | Dolly tracking A left to right; B enters at screen right near the end | — |
| 4 | A arrives and stops | 265–360 | 11.0–15.0 | Locked two-shot; A stops at frame 305, 2.2 m from B | — |
| 5 | B greets | 361–432 | 15.0–18.0 | Over A's shoulder onto B, with headroom for a raised arm | `mannequin_wave` on B |
| 6 | A answers | 433–504 | 18.0–21.0 | Reverse, over B's shoulder onto A | `mannequin_wave` on A |
| 7 | Together | 505–576 | 21.0–24.0 | Wide two-shot, slow pull-back | — |

## World layout (metres, Z up)

- **Interaction axis:** the line y = 0, through both characters. Every camera is on the −Y side.
- **B (host):** at (2.0, 0, 0), rotation_z −50°. The body faces (−0.766, −0.643): three-quarters
  toward the cameras and 40° short of facing A. B holds the baton in `hand.L`, so the right hand
  stays free for the wave. B idles from frame 1 to 576 and never travels.
- **A (traveller):** walks along y = 0, facing +X (rotation_z 90°), from x −10.416102 at frame 1 to
  x −0.2 at frame 305. That is 0.0336056 m/frame, the authored R1S walk speed, so the planted foot
  holds still. The walk clip runs 1–305 and ends on cycle frame 17 (mid-stance); idle follows from
  305 with an 8-frame crossfade. A is off-screen until the tracking shot.
- **Set:** ground plane; a lamp post (thin cylinder, 3.2 m) with a warm globe at (3.6, 0.4) (at (2.9, 0.7) until
  the post-render fix below); three
  cone-and-trunk trees 9–17 m behind the axis: tree1 at (−4, 9), tree2 at (7, 17), tree3 at
  (−1, 14). Tree2 was at (5.5, 11) until the Gate 3 visual revision; see below.
- **Light:** `golden_hour` preset, sun elevation 14°, azimuth 10°. The light comes from
  (sin az, −cos az) = (0.17, −0.98): from behind the cameras, slightly toward +X, so it falls on
  both characters' fronts and shadows fall straight back. World colour is warm
  (0.55, 0.42, 0.32); exposure is 0.
  - Gate 1 first used azimuth 300°, which lit from −X, behind the traveller. The reverse (sh06)
    saw only the traveller's shadow side.
  - A single sun cannot both rake the scene and light two characters facing each other. The
    frontal key is the trade-off.

## Shot list

| Shot | Frames | Lens | Camera keys (location) | Aim (look_at, height) | Subject offset | DoF |
|---|---|---|---|---|---|---|
| sh01_wide | 1–84 | 28 mm | (0.6, −9.5, 2.0) → (0.75, −9.0, 1.95) | host, 1.0 | +0.15 (B right of centre) | off |
| sh02_host_look | 85–124 | 57 mm | (3.8, −3.2, 2.85) → (3.667797, −3.067797, 2.783898): the original push-in line, ended at frame 124 | host, 1.35 | +0.1667 (right third) | f/2.8 on host |
| sh02b_host_pov | 125–168 | 50 mm | (3.4, −0.4, 1.6), locked; over B's left shoulder | traveller, 1.0 | −0.05 | f/4 on traveller |
| sh03_walk | 169–264 | 40 mm | (−4.470361, −6.5, 1.2) → (−1.277829, −6.5, 1.2), linear: the original dolly line from frame 169 | traveller, 0.9 | −0.15 (lead room ahead) | f/4 on traveller |
| sh04_two_shot | 265–360 | 30 mm | (0.9, −6.0, 1.4), locked | host, 0.9 | +0.22 (B right, A left) | off |
| sh05_host_wave | 361–432 | 40 mm | (−1.6, −1.9, 1.6) → (−1.5, −1.8, 1.6): 0.5 m toward −Y from Gate 1, to clear the lamp post | host, 1.3 | +0.15 | f/4 on host |
| sh06_traveller_wave | 433–504 | 40 mm | (3.6, −1.6, 1.6) → (3.5, −1.5, 1.6) | traveller, 1.3 | −0.15 | f/4 on traveller |
| sh07_end_wide | 505–576 | 28 mm | (0.9, −8.5, 1.9) → (0.9, −9.6, 2.1) | host, 0.9 | +0.15 | off |

Shot lengths: 84, 40, 44, 96, 96, 72, 72, 72 frames (at least 40, against a milestone floor of 24).
Cuts fall at 85, 125, 169, 265, 361, 433 and 505. Render: Eevee, 640×360, 24 fps, 16 samples, no
motion blur.

## Eyelines and screen direction

- **A** walks screen left to right in every shot that shows the walk. At the stop, A faces +X,
  straight at B, so A's eyeline to B is 0°.
- **B**'s body faces 40° away from the line to A. In the look beat, B's head (with some chest)
  turns 40° to B's right and holds, so B is looking at A from sh02 on. B stays turned toward A
  for both waves.
- On screen, B looks and waves toward screen left and A toward screen right. sh05 (over A's
  shoulder) and sh06 (over B's shoulder) are a matched reverse pair on the −Y side.

## Acceptance criteria

**Gate 1 (staging prototype):**

- **Validation:** the spec validates as SceneSpec 1.3 against the manifest, with no camera or
  shot warnings, and `workers.asset_preflight --spec` reports 0 problems.
- **Shots:** seven shots exactly cover frames 1–576, each at least 24 frames long, with cuts at
  85, 145, 265, 361, 433 and 505.
- **Assets:** only the existing mannequin, baton, walk and idle are used. No schema or builder
  change.
- **Walk:** the traveller's root speed equals the authored walk speed (to 1e-8 m/frame), and the
  walk ends on cycle frame 17 at the stop.
- **180° rule:** every camera key is on the −Y side of the A–B axis.
- **Framing** (pinhole model in `tests/test_m7_greeting_spec.py`, confirmed visually in the
  cut-frame smoke render):
  - In sh01 and sh07, the whole bodies are in frame, feet included.
  - In sh04, both characters are in frame from the cut, with A screen left and B screen right.
  - A is off-screen in sh01.
  - In sh02, the lamp post is out of frame, no tree is behind B's head, and no tree trunk
    hangs from the top edge (trunk bases at least 0.03 of the frame height above it).
- **Light:** the sun lights both characters' fronts, and every shot's camera sees the sunlit
  side of its subject.
- **Smoke render:** the cut-frame render (both sides of every cut) builds with status `ok`. The
  frames show the intended staging.

**Milestone (Gates 2–4):**

- **Assets:** `mannequin_look` and `mannequin_wave` live in a new actions file, and an ochre host
  variant in a new character file. The M6 asset files and their fingerprints stay unchanged.
- **Gestures leave the legs alone:** during a gesture, the legs and hips equal the idle pose
  (within 1e-6), and the feet move less than 1 mm.
- **Look:** the head turn holds at 35–50° relative to the hips, with no channel jump above a set
  degrees-per-frame limit.
- **Wave:** the hand rises above shoulder height and makes at least two side-to-side swings. The
  wave starts and ends on the idle arm pose.
- **Eyeline:** during the look and both waves, each head faces within 20° of the other character.
- **Film:** the full render is an h264, yuv420p MP4 at 24 fps, 576 frames, 24.0 s, checked by
  `verify()`. The contact sheet and frame report show no black or blown frames.
- **Resources:** the full render takes at most 10 minutes and peaks under 2 GB, on AC power.
- **Human review:** a viewer can tell the story from the film without reading the description.

## Gate 2 — gesture assets

Authored by `blender/scripts/author_assets/mannequin.py --set m7`. The default `--set m6` still
writes only the Milestone 6 files, unchanged.

| Asset | File | Structural fingerprint (Blender 5.2.2) |
|---|---|---|
| `mannequin_ochre` (character) | `assets/characters/mannequin_ochre.blend` | `57ff3bfd…1caab8` |
| `mannequin_look`, `mannequin_wave` (actions) | `assets/actions/mannequin_gestures.blend` | `a96a63d2…46c19e9` |

- **`mannequin_ochre`:** the mannequin's skeleton, mesh, skinning and rig type
  (`afs_mannequin_v1`) under its own names (`CH-`, `RIG-`, `GEO-mannequin_ochre`). The body is
  ochre and the hands and feet dark red-brown. It plays the walk, idle and gestures exactly
  like the grey mannequin.
- **`mannequin_look`** (24 frames, not loopable): the head leads and the neck, chest and spine
  follow. The head's world yaw reaches 40° to the character's right by frame 17 and holds;
  the chest carries 16° of it. Only the Y rotation of spine, chest, neck and head is keyed.
- **`mannequin_wave`** (60 frames, not loopable), right arm only:
  - Frames 1–19: the upper arm rises out and forward. The elbow flexes from frame 7, so the hand
    stays in front of the body.
  - Frames 19–43: the forearm swings ±22° about 60° of flexion, two full cycles, with the hand
    1.86–1.90 m high.
  - Frames 43–61: the arm lowers back to the idle's mean arm pose.

### How the gestures must be used (Gate 3)

- **Layer them over a continuous idle.** Put a gesture clip on top of an idle clip that spans
  it. Overlapping clips are valid SceneSpec 1.3, and `build_scene.place_actions` stacks clips
  on NLA tracks in start order, so no schema or builder change is needed.
- **A gesture is never a character's first clip** (the validator enforces this).
  - **Why:** `build_scene.place_actions` sorts a character's clips by `start_frame` and puts
    the first on the bottom NLA track, held before and after its range. A full-body clip there
    poses every channel on every frame. A partial action there leaves every bone it does not
    key in the rest pose wherever no full-body clip covers the frame: straight legs, hips at
    rest height, the rest arms, no breathing.
  - **Evidence:** a builder probe confirmed the rest-pose fallback for wave-only and
    wave-then-idle timelines, and showed it does not depend on evaluation order. (An earlier
    note here said such channels "keep stale values". That was only true in the asset
    inspector, which removes each action's track before evaluating the next. The builder does
    not do that.)
  - **Metadata:** `ActionEntry.coverage` in the manifest is `"full"` (the default, so entries
    that omit it are unchanged) or `"partial"`. Only `mannequin_look` and `mannequin_wave` are
    `"partial"`. `tests/test_action_coverage_assets.py` checks the metadata against the
    `.blend` files: a full action keys every bone's rotation and the root bone's location in
    one slot, and a partial one does not.
  - **The rule:** `validate_against_manifest()` takes each character's first clip in the
    builder's order (`sorted` by `start_frame`, stable, so among clips on the same frame the
    one listed first). If it is partial, validation rejects the spec with an error that names
    the character and action and suggests a full-body action, e.g.
    `characters[host]: first clip 'mannequin_wave' is a partial-body gesture; start with a
    full-body action such as mannequin_idle`.
  - **What it does not check:** that later frames stay covered. None need checking, because
    the bottom clip covers the whole shot. It also does not require the base action to loop
    and never inserts an idle. `coverage` is manifest-only: the SceneSpec schema and version
    (1.3) are unchanged.
- **Clip lengths:** each gesture clip should be its action's length (look 24, wave 60 frames).
  Clips longer than 1.5× the action length are rejected, since the actions don't loop. After
  the clip, NLA holds the last key.
- **Blend-in:** the measured clean crossfade is 6 frames.

### Layering limitations

- **After the wave, the arm stops breathing.** NLA holds the wave's last key (the idle's mean
  arm pose), so that arm no longer moves with the idle's ±1° breathing. The builder sets no
  blend-out.
- **The look holds for the rest of the scene.** There is no turn-back action; a later look
  back would need its own gesture.
- **The wave follows the chest.** Its arm turns with whatever the look does to the chest. The
  host therefore waves toward where it looks, which is intended here.

## Gate 3 — integration

**Cast.** B (host) is `mannequin_ochre`. It still holds the baton (`hand.L`), which was its
Gate 1 stand-in for the colour. A (traveller) is the grey `mannequin`. The cameras, sun,
staging and sh02 framing are as approved in Gate 1.

**Gesture schedule** (each clip is exactly its action's length, blend-in 6 frames):

| Character | Clip | Frames | Inside shot | On screen |
|---|---|---|---|---|
| B | `mannequin_idle` (base) | 1–576 | all | full-body base for B's gestures |
| B | `mannequin_look` | 100–124 | sh02 (85–124) | B is still 85–99 and turns 100–116; the cut to the reaction shot comes 8 frames later (125). The look then holds for the rest of the film |
| B | `mannequin_wave` | 366–426 | sh05 (361–432) | raise 366–384, swing 384–408, lower 408–426 |
| A | `mannequin_walk`, then `mannequin_idle` (base) | 1–305, 305–576 | — | stops on cycle frame 17 at 305 |
| A | `mannequin_wave` | 438–498 | sh06 (433–504) | raise 438–456, swing 456–480, lower 480–498 |

**Measured** on the built scene (`tests/test_m7_greeting_builder.py`, against an idle-only twin
of the spec):

- **Legs and hips:** identical on every frame (difference 0). Nothing changes before each
  character's first gesture.
- **Eyelines:** B's head points at A within 0.001° from frame 116 to the end. A's head points
  at B from the stop on.
- **Motion:** no bone turns faster than 19.2°/frame. At gesture boundaries, motion stays
  under 0.35°/frame.
- **Headroom:** the raised hand stays at least 0.18 of the frame height below the top edge in
  sh05 (B) and 0.19 in sh06 (A).
- **Over-the-shoulder:** B's hand stays at least 0.3 frame-widths from A's head in sh05.
- **Framing:** wides and the two-shot keep both whole bodies in frame through the evaluated
  cameras.

**Smoke evidence:** at 320×180, in `storage/projects/m7_greeting/`:

- `gate3_rev1/shots/m7_greeting/review/` (revision 1, seven shots): `cut_frames_sheet.png`
  (14 cut stills) and `gesture_frames_sheet.png` (20 stills).
- `gate3_rev2/shots/m7_greeting/review/` (the visual revision): `cut_frames_sheet.png`
  (16 cut stills), `gesture_frames_sheet.png` (20 stills, including the reaction shot), and
  `compare_rev1_rev2.png` (sh02 and sh05, revision 1 beside revision 2).

**Visual revision (after revision 1).**

- **The look barely read.** The head is a featureless sphere, and in sh02 the turn goes away
  from the camera.
  - **Fix (editorial, no asset change):** sh02 now ends on frame 124, 8 frames after the turn
    completes. It cuts to the new sh02b, which shows what B sees: A far down the road, with B's
    turned head and shoulders in the right foreground.
  - **Paid for by:** sh03's first 24 frames, so the scene keeps 576 frames. The look's clip
    and timing are unchanged.
  - **Tests:** the reaction shot frames A whole, with B's head clear of A. B's eyeline points
    toward screen left, toward A, in both sh02 and sh02b.
- **In sh05, B's forearm crossed the lamp post** around frames 384–390.
  - **Fix:** both sh05 camera keys moved 0.5 m toward −Y, about a 7° orbit around B.
  - **Result:** the forearm and hand keep at least 1.5% of the frame width from the post
    (designed for 2.7%). The hand's headroom improves (top at 0.30 instead of 0.32). The
    hand stays at least 0.35 frame-widths from A's head.
  - **Side effects:** B is about 4% smaller in sh05. A's foreground head sits slightly
    further left.
  - **The move exposed a sliver of tree2's crown** at sh05's top-left corner, behind A's
    head. No camera position cleared both the post and the tree by a safe margin.
    - **Fix:** tree2 (trunk and crown) moved from (5.5, 11) to (7, 17). It is now out of
      sh05 and still a background tree in sh01, sh03, sh04 and sh07, farther and smaller.
    - **Bonus:** B's head no longer touches its crown outline in the wides and two-shot
      (it did at the Gate 1 position). In sh03 the crown no longer touches the top edge
      or B's entrance.
    - **Tests:** pinned in `tests/test_m7_greeting_spec.py`.

### Full render (final_rev1)

`storage/projects/m7_greeting/final_rev1/`:

- **Film:** `m7_greeting.mp4`, h264, 640×360, yuv420p, 24 fps, 576 frames, 24.0 s, verified
  with ffprobe by `workers.run_milestone1`. Blender rendered it in 124 s, with a peak of
  487 MB in use.
- **Review evidence:** `shots/m7_greeting/review/contact_sheet.png` (24 samples) and
  `frame_report.json`. All 8 analysis flags fall on cut frames (85, 125, 361 and 505) and
  come from the change of camera and background there. No flag falls inside a shot.
- **Review status:** ready for human approval (film-animatic-review checklist). Nothing is
  approved until a person accepts it.
- **Finding:** in sh05 the lamp post's right edge touched the left edge of B's head. The 0.5 m
  camera move that cleared the waving forearm had brought the post behind B's head line.
  - **No sh05 camera fixed it:** on B's left, the post only fits in the narrow gap between B's
    head and the swinging forearm.
  - **Fix:** the lamp post and globe moved from (2.9, 0.7) to (3.6, 0.4). In sh05 the post now
    stands on B's other side, clear of the head (0.038 of the frame width) and far from the
    waving arm.
  - **Other shots:** the post stays beside B in sh01, sh04 and sh07, further from B's body. It
    stays out of frame in sh02, sh02b, sh03 and sh06.
  - **Tests:** pinned in `tests/test_m7_greeting_spec.py`. The film was re-rendered as
    `final_rev2`.

## Known limitations (carried)

- The R1S gait has no trailing hip extension (Milestone 6); it is not addressed here.
- Characters cannot turn in place, so B is staged at a fixed three-quarter angle.
- Static non-uniform primitive scale is expressed as a single scale key at frame 1. The schema's
  `transform.scale` is uniform only.
- No faces, audio, titles or fades.
