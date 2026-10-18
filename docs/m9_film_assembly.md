# Milestone 9 — Film Assembly

**Objective.** Join independently rendered, approved scenes into one film. The edit is
described by a deterministic, validated edit list and carried out by fixed tools (FFmpeg
stream copy, ffprobe). There is no new renderer, no AI video generation and no LLM-generated
code.

**Status.** Gate 3 (final audit) is under review. Gates 1 and 2 are complete. The technical
reel is **technically verified** (frames, checksums, streams) but has **not been watched**.
Nobody has reviewed it visually or approved it as a film (see "Verified is not approved"
below).

- **Gate 0:** branch `milestone-9-film-assembly`, from `main` at `305b11e` (M8).
- **Gate 1:** the `EditList` contract, its JSON Schema, an example, and tests.
- **Gate 2:** the assembler, `workers/assemble_film.py`, and a technical reel assembled from
  the approved M7 and M4 deliverables.
- **Later (M10):** a second scene for The Greeting, assembled with scene 1 into a two-scene
  film.

## Decisions (approved at discovery)

1. **Copy, never convert.** Version 1 joins video streams without re-encoding. A clip that
   doesn't match the declared format is refused; it isn't silently converted. A
   conform/re-encode mode is deferred.
2. **Approval chain.** Every clip is an approved scene deliverable from `run_milestone1`
   under `storage/projects/`, pinned by SHA-256. Gate 2 also requires its `<name>.summary.json`
   to have `ok: true`, with a `video` block that matches ffprobe.
3. **No overwriting.** If the film's output already exists, assembly is refused. There is no
   `--force` in version 1.
4. **The Gate 2 demo is a technical reel** of existing approved deliverables. A real second
   scene is M10.
5. SceneSpec, `encode.py`, `run_milestone1.py`, assets, the manifest and every existing
   deliverable are unchanged.

## The contract — `EditList` 1.0

- Model: `apps/api/schemas/edit_list.py`.
- Schema: `schemas/edit_list.schema.json`. It must equal `EditList.model_json_schema()`;
  regenerate it with `python -m apps.api.schemas.edit_list > schemas/edit_list.schema.json`.
- Example: `schemas/examples/greeting_reel.edit.json`.

```json
{
  "edit_version": "1.0",
  "film_id": "greeting_reel",
  "format": {"codec": "h264", "pix_fmt": "yuv420p", "width": 640, "height": 360,
             "fps": 24, "audio": "none"},
  "clips": [
    {"clip_id": "sc01_greeting",
     "source": "storage/projects/m7_greeting/final_rev2/m7_greeting.mp4",
     "sha256": "a43dffc26a73796c429a60f57e44b1cd45acaf40c7c898355db9a639eb9e8098",
     "frames": 576},
    {"clip_id": "sc02_ball_sequence",
     "source": "storage/projects/m6_demo/m4_sequence.mp4",
     "sha256": "23c95da547c2caa3678d0978cb7f84b9e898bfe67fa70ba8e748445665238e00",
     "frames": 132}
  ]
}
```

| Field | Rule |
|---|---|
| (every object) | Unknown fields rejected. Types never coerced (strict mode: `"576"` or `true` is not a frame count). Non-finite numbers rejected |
| `edit_version` | `"1.0"` |
| `film_id` | Slug `^[a-z][a-z0-9_]{1,47}$`, the same rule as SceneSpec identifiers. The output is always `storage/projects/<film_id>/<film_id>.mp4`; it is derived, never given |
| `format` | Required, every field explicit: `codec` `"h264"`, `pix_fmt` `"yuv420p"`, `width` 16–7680, `height` 16–4320, `fps` 24, 25 or 30 (integer, constant), `audio` `"none"`. These are the values the existing encoder produces |
| `clips` | 1–1000 clips, in film order. Whole clips only (no trims) |
| `clips[].clip_id` | Slug, unique within the edit list |
| `clips[].source` | Safe relative POSIX path under `storage/projects/` ending in `.mp4` (see below) |
| `clips[].sha256` | 64 lowercase hex characters |
| `clips[].frames` | Integer 1–86,400 (one hour at 24 fps): the clip's decoded frame count |

The same source may appear twice under different clip IDs, for example to repeat a shot.

### Source paths

The schema pattern is:

```
^storage/projects/(?:SEG/)+SEG\.mp4$
SEG = [A-Za-z0-9_](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9_-])?
```

- **Rejected by the pattern:**
  - absolute paths, drive letters and UNC paths;
  - backslashes;
  - `.`, `..` and empty segments, hence no traversal;
  - hidden names (a segment starting with a dot);
  - segments ending in a dot, which Windows silently strips;
  - colons (drive letters and alternate data streams);
  - spaces, and any extension other than lowercase `.mp4`;
  - a file directly in `storage/projects/` (a project folder is required);
  - paths over 240 characters.

  The `storage/projects/` prefix is exact and case-sensitive.

  A trailing newline is rejected by both the schema and the model. JSON Schema patterns use
  ECMA-262 regular expressions, where `$` matches only at the very end of the string, and
  Pydantic's regex engine does the same. Python's `re`, by contrast, also lets `$` match before
  a final newline. The parity test therefore reads the committed schema's anchors with ECMA
  semantics (`\Z` in Python), and a separate test pins down this dialect difference. Node.js
  (ECMA-262) was used to confirm that the committed patterns reject `"…/b.mp4\n"`.
- **Rejected by the model only:**
  - Windows device names (`con`, `nul`, `aux`, `prn`, `com0-9`, `lpt0-9`, with any extension)
    in any segment;
  - any clip from the film's own output folder `storage/projects/<film_id>/` (compared
    case-insensitively), so assembly can never read what it writes. The assembler also
    refuses a source whose *real* path lies in that folder through a link (Gate 3).

### Filesystem validation — `validate_sources(edit, repo_root)`

This is a separate step, like `validate_against_manifest()` for SceneSpec. It returns a list of
errors, one per failing clip, with every clip checked. It reads no file contents and writes
nothing. For each clip:

- the source must exist;
- its real path, with symlinks and directory junctions resolved, must be inside
  `<repo_root>/storage/projects/`. Otherwise it is reported as an escape;
- it must be a regular file.

A link that stays inside `storage/projects/` is allowed.

### Checks that need the media (Gate 2)

- The SHA-256 must match the file.
- The sibling `<name>.summary.json` must have `ok: true`.
- ffprobe must report codec, pix_fmt, width, height, fps and decoded frame count equal to
  `format` and to `frames`.
- There must be exactly one video stream and no audio, subtitle or data stream.
- Sample aspect ratio, timebase and codec parameter data (extradata) must be identical across
  clips, otherwise stream copy is unsafe.
- The output must not already exist.

These are implemented in `workers/assemble_film.py`; see "Gate 2" below.

## Validation (Gate 1)

`tests/test_edit_list.py` checks the structural rules against **both** the Pydantic model and
the exported JSON Schema. It uses the parity validator from `tests/test_schema_parity.py`,
reading pattern anchors with ECMA-262 semantics (see "Source paths"); the shared helper itself
is unchanged. It also checks:

- the committed schema equals the export;
- unknown fields at every level;
- slugs, unique IDs, and the output-folder rule;
- 29 unsafe and 3 safe source paths, plus device names on the model;
- a trailing newline on every pattern (source, film_id, clip_id, sha256), rejected by both;
- SHA-256 values, frame counts, and every format value and required field;
- `validate_sources()` on a fake repository: a missing file, a directory, a junction that
  escapes `storage/projects/` (rejected) and one that stays inside (accepted), several clips
  reported together, and nothing written;
- the example's sources exist in this repository (skipped where `storage/` is absent).

A symlink-escape test runs where symlinks can be created. On this Windows machine (no symlink
privilege) it is skipped, and the junction test covers the same escape.

## Gate 2 — the assembler

```
python -m workers.assemble_film --edit schemas/examples/greeting_reel.edit.json
```

### Outputs

Three new files in `storage/projects/<film_id>/`. The names are fixed by `film_id`:

| File | Contents |
|---|---|
| `<film_id>.mp4` | The film: the clips' video streams copied in edit order |
| `<film_id>.assembly.ffmpeg.log` | FFmpeg command and stderr of the concatenation. Run-specific paths become `<workspace>`/`<repo>`, and memory addresses and the measured fps, speed and elapsed time become `<addr>`/`<run>`, so identical inputs give an identical log |
| `<film_id>.assembly.json` | `assembly_report.v1`, `status: "verified"`. Written last |

### Order of operations

Every step before 5 writes nothing.

1. Load the edit list with the `EditList` model. Errors are at stage `edit_list`.
2. Run `validate_sources()`: a safe path, inside `storage/projects/` after resolving symlinks
   and junctions, and a regular file. Stage `sources`.
3. Check the outputs. Assembly is refused (stage `outputs`) if any of the three files exists,
   or if the film path is a file, a symlink or junction, or escapes `storage/projects/`. There
   is no `--force`. Then refuse any source whose real path lies inside the film folder (stage
   `sources`).
4. Check every clip (stage `sources`; all errors are collected and reported together):
   - **SHA-256** equals the pinned value. A mismatch prints the file's current hash for
     diagnosis; the edit list is never modified.
   - **Summary.** The sibling `<name>.summary.json` must have `ok` exactly `true`, no
     `errors`, an `mp4` that resolves to this very file, and a `video` block equal to
     `encode.probe()`: codec, width, height, pix_fmt and frames exactly; fps within 0.01;
     duration within 0.001 s.
   - **Streams.** Exactly one stream, a video stream (`audio: "none"`). `codec_name`,
     `pix_fmt`, `width`, `height`, `r_frame_rate` and `avg_frame_rate` must equal the
     declared format, and the decoded frame count must equal `frames`.
   - **Stream-copy compatibility** with the first clip: `codec_tag_string`, `profile`,
     `level`, `time_base`, `sample_aspect_ratio`, `field_order`, the colour properties and
     `extradata_hash` (the H.264 parameter sets).
   - **Decoded frame checksums** (`framemd5`) of every clip, computed only after everything
     above passes.
5. Create a private workspace `storage/projects/<film_id>/.assembly-<random>/`, creating the
   film directory if needed.
6. Write a concat script there. Paths are single-quoted with FFmpeg's escaping, and
   `-protocol_whitelist file` keeps them to local files.
7. Run FFmpeg with an argument list (no shell): `-n` (never overwrite), concat demuxer,
   `-c copy`, `-map 0:v:0`, `-map_metadata -1`, `-fflags +bitexact`, `-movflags +faststart`.
   It writes `film.partial.mp4` inside the workspace. A non-zero exit is stage `ffmpeg`.
8. Verify the film (stage `verify`):
   - one video stream;
   - the declared format, and stream-copy properties equal to the clips';
   - total frames equal to the sum of the clips';
   - duration within half a frame of frames ÷ fps;
   - decoded frame checksums equal to the clips' checksums in edit order;
   - every source's SHA-256 unchanged (re-hashed; recorded as `sha256_after`).
9. Publish with no-clobber renames: the MP4, then the log, then the report. If a target has
   appeared in the meantime, the files this run already published are removed and nothing is
   replaced (stage `publish`).
10. Clean up, always: the workspace is removed, along with the film directory if this run
    created it and nothing was published. Other files in the film directory, including other
    runs' workspaces, are never touched.

### The report — `assembly_report.v1`

- `status` (`"verified"`) and `human_approval_required` (`true`).
- `edit_list`: path, SHA-256, version, film_id and format.
- `clips[]`, in order:
  - clip_id, source, `sha256` and `sha256_after`;
  - summary path and SHA-256;
  - `frames` and `film_frames` (first and last film frame, 1-based);
  - `start_s` and `end_s`;
  - the ffprobe values, and a digest of the decoded frame checksums.
- `total_frames` and `expected_duration_s`.
- `output`: path, SHA-256, size, probe, stream, and the frame-checksum digest.
- `checks`, `files`, and `ffmpeg` (command, FFmpeg and ffprobe versions).

The report holds no timings and no run-specific paths. Identical inputs give an identical
report, apart from `edit_list.path`, which is relative to the repository.

On failure the CLI exits 1. It prints `FAILED: <error>` lines to stderr and, to stdout, an
`assembly_report.v1` with `status: "failed"`, `stage`, `errors` and `published: false` (plus
FFmpeg's stderr tail for stage `ffmpeg`). Nothing is written to `storage/`.

Errors name files by repository-relative path, and FFmpeg output is masked as in the log.
Diagnostics therefore don't carry the local checkout path (which includes the user name).
The only exception is the edit-list path the user typed.

A `verified` report means only that the film is exactly the approved clips, copied in order.
It says nothing about whether the film works as a film.

### Verified is not approved

- **Technical verification (automatic, done).** The film's streams, frame count and duration
  are right, and every decoded frame equals the corresponding source frame in edit order.
- **Visual and story approval (human, not done).** Someone watches the film, at least across
  every scene boundary (`clips[].film_frames`), and decides it is acceptable. The worker
  cannot do this, and the report's `human_approval_required: true` says so.

### Technical reel (Gate 2 evidence)

`storage/projects/greeting_reel/`, assembled from `schemas/examples/greeting_reel.edit.json`.
It is a technical check of the tool, not a story: M7's ending cuts straight to the unrelated
M4 ball sequence. **It has not been watched.** Everything below is checksum and ffprobe
evidence.

| | Value |
|---|---|
| Clips | `sc01_greeting` (M7 final_rev2), film frames 1–576, 0–24 s; `sc02_ball_sequence` (M4, `m6_demo`), film frames 577–708, 24–29.5 s |
| Film | 708 frames, 29.5 s, h264 High, 640×360, yuv420p, 24/1 fps, time base 1/12288, 1 stream |
| `greeting_reel.mp4` SHA-256 | `8b4a74572bf6d3a2cd33b637e8ad2dccadc1ff9010ce5342ebddd4fa12b425cb`, the same bytes as the discovery feasibility test |
| Independent check | Decoded frame checksums of the film equal M7's followed by M4's (708 of 708) |
| Sources | SHA-256 identical before and after. All 1,985 pre-existing files under `storage/projects/` unchanged |
| Runtime | 1.66 s for a full run (checks, FFmpeg, verification) on a scratch copy; Python peak working set 32 MB (FFmpeg children not measured) |
| Gate 3 audit (read-only) | The report's output SHA-256, size, frame-checksum digests, sources, summaries and edit-list hash all match the files on disk; the log's command equals the report's; no `.assembly-*` workspace left behind |
| After the Gate 3 fixes | Re-running the fixed assembler in a scratch copy gives the same film bytes and the same report (apart from `edit_list.path`). The reel's files were not touched |
| Existing reel log | `greeting_reel.assembly.ffmpeg.log` **predates the diagnostic-masking fix** and is kept unchanged as the original Gate 2 evidence. It still contains the original unmasked diagnostics: 4 FFmpeg memory addresses (`@ 000001c6…]`) and the run's measured `fps=0.0 speed=1.93e+03x elapsed=0:00:00.01`. Its paths were already masked at Gate 2 (`<workspace>`); it holds no local user paths. Masked with the current rules, it is identical to the log the fixed assembler writes. Logs from future runs are masked |

### Tests (Gate 2)

`tests/test_assemble_film.py` (49 tests, needs FFmpeg) runs on small H.264 clips encoded with
`encode.py`'s settings, each in its own fake repository in `tmp_path`. It covers:

- **Success:** order, frame ranges, report contents, no `-y`, identical output for identical
  inputs, a repeated source, an existing film directory, and the CLI.
- **Rejections:**
  - unsafe paths and self-reference;
  - duplicate IDs and unknown fields;
  - a missing source and a junction escape;
  - a hash mismatch, and every summary failure;
  - a declared frame count that differs from the decoded count;
  - each incompatibility: size, fps, pix_fmt, codec, time base, SAR, codec parameters, audio,
    and a second video stream.
- **Outputs:**
  - every output collision, and a second run;
  - a simulated FFmpeg failure, verification failure, short film and interruption;
  - a publication race, and no-clobber publish.
- **The approved example:** a read-only check that it passes every pre-assembly check.

Every failure test checks that the fake repository is byte-identical afterwards, and that
the failure report contains no local repository path.

Gate 3 added tests for:

- a film directory that is a junction;
- a source reaching the film folder through a junction;
- sources re-hashed after assembly, and `sha256_after` recorded from the re-hash;
- masked diagnostics;
- identical logs for identical inputs.

The total is 54 tests.

## Known limitations

- Whole clips only: no trims, transitions, titles or audio.
- One format per film. There is no conversion between formats.
- `fps` is an integer, so 23.976 / 29.97 deliverables are out of scope (the pipeline renders
  24, 25 or 30).
- The SHA-256 is pinned when the edit list is written. Re-rendering a scene changes its hash,
  so the edit list must be updated deliberately.
- Byte-identical films hold only for the same FFmpeg build (the report records the version).
- A summary's `mp4` path written on Windows (backslashes, possibly absolute) is resolved
  relative to the repository. Summaries from another machine may not match and are refused.
- No film-level review sheet yet: a human reviews the film itself, at least around each scene
  boundary (`film_frames` in the report).
- The film's MP4 is not re-checked when it is played or copied later; its SHA-256 is in the
  report.
- Link checks resolve real paths at check time. Someone replacing a folder with a link while
  an assembly runs is not defended against; the sources are re-hashed after assembly, but
  the output folder is not re-checked.
- The symlink-escape test is skipped on Windows accounts without the symlink privilege; the
  junction tests cover the same escape.
- The concatenation was tested only with clips produced by this pipeline's encoder settings.
