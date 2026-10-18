"""Milestone 9: assemble approved scene MP4s into one film, as an EditList 1.0 describes.

    uv run python -m workers.assemble_film --edit schemas/examples/greeting_reel.edit.json

Writes, only after every check passes, three new files in storage/projects/<film_id>/:
    <film_id>.mp4                   the film: the clips' video streams copied in order
    <film_id>.assembly.ffmpeg.log   FFmpeg command and stderr of the concatenation
    <film_id>.assembly.json         schema assembly_report.v1, status "verified" (written last)

The video is copied, never re-encoded or converted (FFmpeg concat demuxer, -c copy). Before
FFmpeg runs, every clip must pass:
    the EditList model and validate_sources() (safe path, inside storage/projects/, a file);
    its pinned SHA-256;
    its sibling <name>.summary.json from run_milestone1: ok true, no errors, naming this file,
        with a video block equal to ffprobe;
    ffprobe: exactly one stream, video, with the declared codec, pix_fmt, size and constant
        frame rate, and the declared frame count;
    stream-copy compatibility with the first clip: profile, level, time base, sample aspect
        ratio, colour properties, field order and codec parameter data (extradata hash).
The concatenated film is then verified in a private workspace: ffprobe properties, total
frames, duration, and the decoded frame checksums (framemd5) equal to the clips' checksums in
edit order. The sources' SHA-256 are checked again afterwards.

Nothing is ever overwritten. If any of the three output names exists, or the film directory
is a symlink or junction, assembly is refused before anything is created; so is a source whose
real path lies inside the film directory. Diagnostics name files relative to the repository
and mask FFmpeg's run-specific paths, addresses and timings. The workspace is a new directory storage/projects/<film_id>/
.assembly-<random>/; on any failure it is removed (with the film directory, if this run
created it and it is empty), and nothing is published. Files are published with no-clobber
renames, report last; if one fails, the files this run already published are removed.

On failure the CLI prints "FAILED: <reason>" lines to stderr, an assembly_report.v1 with
status "failed" (stage, errors, nothing published) to stdout, and exits 1. The edit list is
never modified; hash mismatches print the file's current hash for diagnosis only.

The film is evidence for a human: human_approval_required is always true.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from pydantic import ValidationError

from apps.api.schemas.edit_list import STORAGE_ROOT, EditList, validate_sources
from workers import config
from workers.encode import EncodeError, probe

REPO = Path(__file__).resolve().parents[1]
SCHEMA = "assembly_report.v1"
REPORT_SUFFIX, LOG_SUFFIX = ".assembly.json", ".assembly.ffmpeg.log"
WORKSPACE_PREFIX = ".assembly-"
PARTIAL_NAME, LIST_NAME = "film.partial.mp4", "concat.ffconcat"

# ffprobe stream fields that must be identical across clips for a safe stream copy
COMPAT_FIELDS = ("codec_tag_string", "profile", "level", "time_base", "sample_aspect_ratio",
                 "field_order", "color_range", "color_space", "color_transfer", "color_primaries",
                 "extradata_hash")
SUMMARY_VIDEO_KEYS = ("codec", "width", "height", "pix_fmt", "fps", "frames", "duration_s")


class AssemblyError(RuntimeError):
    def __init__(self, stage: str, errors: list[str], **detail):
        super().__init__("; ".join(errors))
        self.stage, self.errors, self.detail = stage, errors, detail


# ---------------------------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------------------------
def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    """Every tool call goes through here: an argument list, never a shell."""
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                          timeout=config.FFMPEG_TIMEOUT_S)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def streams(path: Path) -> list[dict]:
    """Every stream of the file, with the fields stream copy depends on."""
    proc = _run([config.FFPROBE_BIN, "-v", "error", "-show_data_hash", "sha256", "-show_entries",
                 "stream=index,codec_type,codec_name,width,height,pix_fmt,r_frame_rate,"
                 "avg_frame_rate," + ",".join(COMPAT_FIELDS), "-of", "json", str(path)])
    if proc.returncode != 0:
        raise EncodeError(f"ffprobe exited {proc.returncode}: {proc.stderr.strip()[-400:]}")
    return json.loads(proc.stdout).get("streams", [])


def frame_md5s(path: Path) -> list[str]:
    """Decoded checksum of every video frame, in presentation order."""
    proc = _run([config.FFMPEG_BIN, "-nostdin", "-hide_banner", "-v", "error", "-i", str(path),
                 "-map", "0:v:0", "-f", "framemd5", "-"])
    if proc.returncode != 0:
        raise EncodeError(f"framemd5 exited {proc.returncode}: {proc.stderr.strip()[-400:]}")
    return [ln.rsplit(",", 1)[1].strip() for ln in proc.stdout.splitlines()
            if ln and not ln.startswith("#")]


def tool_version(binary: str) -> str:
    proc = _run([binary, "-version"])
    return proc.stdout.splitlines()[0] if proc.returncode == 0 and proc.stdout else "unknown"


def _ffconcat_quote(path: Path) -> str:
    """A concat-script path in single quotes; a quote inside becomes '\\'' (FFmpeg's rule)."""
    return "'" + path.as_posix().replace("'", "'\\''") + "'"


# ---------------------------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------------------------
def load_edit(edit_path: Path) -> EditList:
    try:
        return EditList.model_validate_json(edit_path.read_text(encoding="utf-8"))
    except OSError as e:
        raise AssemblyError("edit_list", [f"cannot read edit list {edit_path}: {e}"]) from e
    except ValidationError as e:
        raise AssemblyError("edit_list", [f"{'.'.join(map(str, err['loc'])) or '<root>'}: {err['msg']}"
                                          for err in e.errors()]) from e


def output_paths(edit: EditList, repo_root: Path) -> dict[str, Path]:
    film_dir = repo_root / STORAGE_ROOT / edit.film_id
    return {"dir": film_dir, "mp4": film_dir / f"{edit.film_id}.mp4",
            "log": film_dir / f"{edit.film_id}{LOG_SUFFIX}",
            "report": film_dir / f"{edit.film_id}{REPORT_SUFFIX}"}


def check_outputs(out: dict[str, Path], repo_root: Path) -> list[str]:
    rel = {k: p.relative_to(repo_root).as_posix() for k, p in out.items()}
    errors = [f"{k} already exists, refusing to overwrite: {rel[k]}"
              for k, p in out.items() if k != "dir" and os.path.lexists(p)]
    d = out["dir"]
    if os.path.lexists(d):
        if d.is_symlink() or d.is_junction():          # would write into another folder
            errors.append(f"film directory is a link, refusing to write through it: {rel['dir']}")
        elif not d.is_dir():
            errors.append(f"film path exists and is not a directory: {rel['dir']}")
        elif not d.resolve().is_relative_to((repo_root / STORAGE_ROOT).resolve()):
            errors.append(f"film directory resolves outside {STORAGE_ROOT}/: {rel['dir']}")
    return errors


def check_self_reference(edit: EditList, out: dict[str, Path], repo_root: Path) -> list[str]:
    """The contract refuses sources written under the film's folder; this also catches a source
    whose real path (through a link elsewhere in storage/projects/) lies inside it."""
    film = out["dir"].resolve()
    return [f"clips[{c.clip_id}]: source resolves into the film's own output folder: {c.source}"
            for c in edit.clips if (repo_root / c.source).resolve().is_relative_to(film)]


_ADDRESS = re.compile(r" @ (?:0x)?[0-9A-Fa-f]{6,}\]")
_TIMING = re.compile(r"\b(fps|speed|elapsed)=\s*\S+")      # FFmpeg's final progress line


def _anon(text: str, *paths: tuple[Path, str]) -> str:
    """Diagnostics without run- or machine-specific data: local paths become placeholders,
    FFmpeg's memory addresses ("[mov,mp4 @ 000001c6069816c0]") and the measured fps, speed and
    elapsed time of its final progress line are masked."""
    for path, label in paths:
        text = text.replace(str(path), label)
    return _TIMING.sub(r"\1=<run>", _ADDRESS.sub(" @ <addr>]", text))


def _summary_errors(clip, src: Path, info: dict, repo_root: Path) -> tuple[list[str], dict]:
    where = f"clips[{clip.clip_id}]"
    path = src.with_name(src.stem + ".summary.json")
    if not path.is_file():
        return [f"{where}: no approved summary {path.name} next to the source "
                f"(written by run_milestone1)"], {}
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return [f"{where}: unreadable summary {path.name}: {e}"], {}
    record = {"path": path.relative_to(repo_root).as_posix(), "sha256": sha256(path)}
    if not isinstance(summary, dict):
        return [f"{where}: summary {path.name} is not a JSON object"], record
    errors = []
    if summary.get("ok") is not True or summary.get("errors"):
        errors.append(f"{where}: summary {path.name} is not approved "
                      f"(ok={summary.get('ok')!r}, errors={summary.get('errors')!r})")
    named = str(summary.get("mp4", "")).replace("\\", "/")
    named_path = Path(named) if Path(named).is_absolute() else repo_root / named
    try:
        same = bool(named) and named_path.resolve(strict=True) == src.resolve(strict=True)
    except OSError:
        same = False
    if not same:
        errors.append(f"{where}: summary {path.name} describes {summary.get('mp4')!r}, not this file")
    video = summary.get("video")
    if not isinstance(video, dict):
        errors.append(f"{where}: summary {path.name} has no video block")
        return errors, record
    for k in SUMMARY_VIDEO_KEYS:
        want, got = video.get(k), info.get(k)
        tol = {"fps": 0.01, "duration_s": 0.001}.get(k)
        bad = (not isinstance(want, (int, float)) or abs(want - got) > tol) if tol else want != got
        if bad:
            errors.append(f"{where}: summary video.{k} is {want!r} but ffprobe reports {got!r}")
    return errors, record


def check_clips(edit: EditList, repo_root: Path) -> list[dict]:
    """Every per-clip check, before FFmpeg writes anything. Collects all errors."""
    fmt = edit.format
    errors, clips, first = [], [], None
    for i, clip in enumerate(edit.clips):
        where = f"clips[{clip.clip_id}]"
        src = (repo_root / clip.source).resolve(strict=True)
        actual = sha256(src)
        if actual != clip.sha256:
            errors.append(f"{where}: SHA-256 mismatch: the edit list pins {clip.sha256}, the file "
                          f"is now {actual} (if the scene was re-rendered and re-approved, update "
                          f"the edit list by hand)")
            continue
        try:
            info, strs = probe(src), streams(src)
        except EncodeError as e:
            errors.append(f"{where}: cannot probe the source: {e}")
            continue
        summary_errors, summary = _summary_errors(clip, src, info, repo_root)
        errors += summary_errors
        kinds = [s.get("codec_type") for s in strs]
        if kinds != ["video"]:
            errors.append(f"{where}: expected exactly one video stream and nothing else "
                          f"(format audio 'none'), found {kinds}")
        v = next((s for s in strs if s.get("codec_type") == "video"), {})
        want = {"codec_name": fmt.codec, "pix_fmt": fmt.pix_fmt, "width": fmt.width,
                "height": fmt.height, "r_frame_rate": f"{fmt.fps}/1", "avg_frame_rate": f"{fmt.fps}/1"}
        errors += [f"{where}: {k} is {v.get(k)!r}, the edit list's format requires {w!r} "
                   f"(assembly does not convert)" for k, w in want.items() if v.get(k) != w]
        if info["frames"] != clip.frames:
            errors.append(f"{where}: decoded {info['frames']} frames, the edit list declares {clip.frames}")
        compat = {k: v.get(k) for k in COMPAT_FIELDS}
        if first is None:
            first = (clip.clip_id, compat)
        else:
            errors += [f"{where}: {k} is {compat[k]!r} but {first[0]} has {first[1][k]!r}; "
                       f"stream copy needs identical streams" for k in COMPAT_FIELDS
                       if compat[k] != first[1][k]]
        clips.append({"index": i, "clip_id": clip.clip_id, "source": clip.source, "path": src,
                      "sha256": actual, "frames": clip.frames, "summary": summary,
                      "probe": info, "stream": {k: v.get(k) for k in sorted(v) if k != "index"}})
    if errors:
        raise AssemblyError("sources", errors)
    for c in clips:                                  # decoded checksums, only once all is valid
        c["frame_md5"] = frame_md5s(c["path"])
        if len(c["frame_md5"]) != c["frames"]:
            raise AssemblyError("sources", [f"clips[{c['clip_id']}]: framemd5 gave "
                                            f"{len(c['frame_md5'])} frames, expected {c['frames']}"])
    return clips


# ---------------------------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------------------------
def _concat(clips: list[dict], workspace: Path) -> tuple[Path, list[str], subprocess.CompletedProcess]:
    listing = workspace / LIST_NAME
    listing.write_text("ffconcat version 1.0\n" + "".join(
        f"file {_ffconcat_quote(c['path'])}\n" for c in clips), encoding="utf-8")
    partial = workspace / PARTIAL_NAME
    # -n: never overwrite; -protocol_whitelist file: the list may only name local files
    cmd = [config.FFMPEG_BIN, "-hide_banner", "-nostdin", "-nostats", "-n",
           "-f", "concat", "-safe", "0", "-protocol_whitelist", "file", "-i", str(listing),
           "-map", "0:v:0", "-c", "copy", "-map_metadata", "-1", "-fflags", "+bitexact",
           "-movflags", "+faststart", "-threads", str(config.FFMPEG_THREADS), str(partial)]
    return partial, cmd, _run(cmd)


def verify_film(partial: Path, clips: list[dict], fmt) -> tuple[dict, list[str]]:
    errors = []
    info, strs = probe(partial), streams(partial)
    total = sum(c["frames"] for c in clips)
    if [s.get("codec_type") for s in strs] != ["video"]:
        errors.append(f"film streams are {[s.get('codec_type') for s in strs]}, expected one video stream")
    v = strs[0] if strs else {}
    for k, w in {"codec_name": fmt.codec, "pix_fmt": fmt.pix_fmt, "width": fmt.width,
                 "height": fmt.height, "r_frame_rate": f"{fmt.fps}/1"}.items():
        if v.get(k) != w:
            errors.append(f"film {k} is {v.get(k)!r}, expected {w!r}")
    for k in COMPAT_FIELDS:
        if v.get(k) != clips[0]["stream"].get(k):
            errors.append(f"film {k} is {v.get(k)!r}, the clips have {clips[0]['stream'].get(k)!r}")
    if info["frames"] != total:
        errors.append(f"film has {info['frames']} frames, expected {total}")
    expected_s = total / fmt.fps
    if abs(info["duration_s"] - expected_s) > 0.5 / fmt.fps:
        errors.append(f"film lasts {info['duration_s']} s, expected {expected_s:.6f} s")
    md5 = frame_md5s(partial)
    expected = [h for c in clips for h in c["frame_md5"]]
    if md5 != expected:
        first = next((i for i, (a, b) in enumerate(zip(md5, expected)) if a != b), min(len(md5), len(expected)))
        errors.append(f"decoded frames differ from the clips in edit order: {len(md5)} frames, "
                      f"first difference at film frame {first + 1}")
    return {"probe": info, "stream": {k: v.get(k) for k in sorted(v) if k != "index"},
            "frame_md5_digest": hashlib.sha256("\n".join(md5).encode()).hexdigest()}, errors


def _publish(src: Path, dst: Path) -> None:
    """Move src to dst atomically, failing if dst exists (never replaces a file)."""
    if os.name == "nt":
        os.rename(src, dst)                       # Windows rename refuses an existing target
    else:
        os.link(src, dst)                         # link refuses an existing target
        os.unlink(src)


def assemble(edit_path: Path, repo_root: Path = REPO) -> dict:
    """Assemble and verify; returns the published assembly_report.v1 (status "verified")."""
    repo_root = repo_root.resolve()
    edit = load_edit(edit_path)
    errors = validate_sources(edit, repo_root)
    if errors:
        raise AssemblyError("sources", errors)
    out = output_paths(edit, repo_root)
    errors = check_outputs(out, repo_root)
    if errors:
        raise AssemblyError("outputs", errors)
    errors = check_self_reference(edit, out, repo_root)
    if errors:
        raise AssemblyError("sources", errors)
    try:
        clips = check_clips(edit, repo_root)
    except (EncodeError, OSError, subprocess.TimeoutExpired) as e:
        raise AssemblyError("sources", [f"{type(e).__name__}: {e}"]) from e

    created_dir = not os.path.lexists(out["dir"])
    out["dir"].mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix=WORKSPACE_PREFIX, dir=out["dir"]))
    published: list[Path] = []
    places = ((workspace, "<workspace>"), (repo_root, "<repo>"))
    try:
        partial, cmd, proc = _concat(clips, workspace)
        log = workspace / "assembly.ffmpeg.log"
        shown = [_anon(a, *places) for a in cmd]
        log.write_text(" ".join(shown) + "\n\n" + _anon(proc.stderr, *places), encoding="utf-8")
        if proc.returncode != 0 or not partial.is_file():
            raise AssemblyError("ffmpeg", [f"ffmpeg exited {proc.returncode}"],
                                ffmpeg_stderr_tail=_anon(proc.stderr.strip(), *places)[-1500:])
        film, errors = verify_film(partial, clips, edit.format)
        if errors:
            raise AssemblyError("verify", errors)
        for c in clips:                           # re-hash: the sources must not have changed
            c["sha256_after"] = sha256(c["path"])
        changed = [c["clip_id"] for c in clips if c["sha256_after"] != c["sha256"]]
        if changed:
            raise AssemblyError("verify", [f"sources changed during assembly: {changed}"])

        report = _report(edit, edit_path, repo_root, clips, film, sha256(partial), partial.stat().st_size,
                         shown, out)
        report_tmp = workspace / "assembly.json"
        report_tmp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        for src, dst in ((partial, out["mp4"]), (log, out["log"]), (report_tmp, out["report"])):
            _publish(src, dst)
            published.append(dst)
        return report
    except BaseException as e:
        for p in published:                       # only files this run published
            p.unlink(missing_ok=True)
        published.clear()
        if isinstance(e, FileExistsError):
            raise AssemblyError("publish", [f"an output appeared during assembly, nothing "
                                            f"published: {e.filename2 or e.filename}"]) from e
        if isinstance(e, (EncodeError, subprocess.TimeoutExpired, OSError)):
            raise AssemblyError("assembly", [_anon(f"{type(e).__name__}: {e}", *places)]) from e
        raise
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
        if created_dir and not published:
            try:
                out["dir"].rmdir()                # only if this run created it and it is empty
            except OSError:
                pass


def _report(edit, edit_path, repo_root, clips, film, film_sha, size, cmd, out) -> dict:
    try:
        edit_name = edit_path.resolve().relative_to(repo_root).as_posix()
    except ValueError:
        edit_name = edit_path.name
    rows, start = [], 1
    for c in clips:
        end = start + c["frames"] - 1
        rows.append({"index": c["index"], "clip_id": c["clip_id"], "source": c["source"],
                     "sha256": c["sha256"], "sha256_after": c["sha256_after"], "summary": c["summary"],
                     "frames": c["frames"], "film_frames": [start, end],
                     "start_s": round((start - 1) / edit.format.fps, 6),
                     "end_s": round(end / edit.format.fps, 6),
                     "probe": c["probe"], "stream": c["stream"],
                     "frame_md5_digest": hashlib.sha256("\n".join(c["frame_md5"]).encode()).hexdigest()})
        start = end + 1
    total = start - 1
    rel = {k: p.relative_to(repo_root).as_posix() for k, p in out.items()}
    return {"schema": SCHEMA, "status": "verified", "human_approval_required": True,
            "edit_list": {"path": edit_name, "sha256": sha256(edit_path), "edit_version": edit.edit_version,
                          "film_id": edit.film_id, "format": edit.format.model_dump()},
            "clips": rows, "total_frames": total,
            "expected_duration_s": round(total / edit.format.fps, 6),
            "output": {"path": rel["mp4"], "sha256": film_sha, "size_bytes": size, **film},
            "checks": {"sources_sha256_before_and_after": True, "summaries_approved": True,
                       "stream_copy_compatible": True, "frame_count": True, "duration": True,
                       "decoded_frames_in_edit_order": True},
            "files": {"film": rel["mp4"], "log": rel["log"], "report": rel["report"]},
            "ffmpeg": {"command": cmd, "version": tool_version(config.FFMPEG_BIN),
                       "ffprobe_version": tool_version(config.FFPROBE_BIN)}}


def failure_report(e: AssemblyError) -> dict:
    return {"schema": SCHEMA, "status": "failed", "human_approval_required": True,
            "stage": e.stage, "errors": e.errors, "published": False, **e.detail}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="assemble_film")
    p.add_argument("--edit", type=Path, required=True, help="EditList 1.0 JSON file")
    a = p.parse_args(argv)
    try:
        report = assemble(a.edit)
    except AssemblyError as e:
        for err in e.errors:
            print(f"FAILED: {err}", file=sys.stderr)
        print(json.dumps(failure_report(e), indent=2))
        return 1
    print(json.dumps({"status": "verified", "film": report["files"]["film"],
                      "report": report["files"]["report"], "total_frames": report["total_frames"],
                      "duration_s": report["output"]["probe"]["duration_s"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
