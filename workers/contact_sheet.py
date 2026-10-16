"""Milestone 2: contact sheet + frame analysis for one rendered shot, as evidence for review.

    uv run python -m workers.contact_sheet --shot-dir storage/projects/milestone1/shots/m1_primitives

Reads <shot-dir>/build_report.json (written by blender/scripts/build_scene.py) and writes
<shot-dir>/review/:
    contact_sheet.png           sampled frames in order, labelled with Blender frame numbers
    frame_report.json           schema frame_report.v1: inputs, samples, luma metrics, warnings
    contact_sheet.ffmpeg.log    FFmpeg command + stderr of the contact-sheet pass
    frame_report.ffmpeg.log     FFmpeg command + stderr of the analysis pass

The report is evidence for a human. It never approves a shot: `verdict` is always
"evidence_only" and `human_approval_required` is always true. Analysis flags use
informational thresholds that are NOT calibrated and do not prove or rule out defects.

FFmpeg streams the PNG sequence in both passes; Python never holds image data.

Contact-sheet grid:
    columns = min(--cols, number of samples)
    rows    = ceil(number of samples / columns)
    thumb   = --thumb-width x round(--thumb-width * height / width)   (rounded half up)
    sheet   = columns * thumb_width  x  rows * thumb_height, 8-bit RGB (rgb24) PNG
Samples fill the grid left to right, top to bottom; unused cells in the last row are black.

Analysis conventions:
    Luma is converted to 8-bit grayscale (format=gray) before signalstats, so 8-bit and
    16-bit PNGs give comparable numbers on a 0-255 scale.
    Filter frame index n (0-based) maps to Blender frame frame_start + n.
    Difference metrics (ydif, scene_score) compare a frame with the previous one, so they
    are null for the first frame and left out of the summaries.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from workers import config
from workers.blender_job import REPORT_INCOMPLETE

SCHEMA = "frame_report.v1"
REVIEW_DIR = "review"
SHEET_NAME = "contact_sheet.png"
REPORT_NAME = "frame_report.json"
SHEET_PARTIAL = "contact_sheet.partial.png"
REPORT_PARTIAL = "frame_report.json.partial"
SHEET_LOG = "contact_sheet.ffmpeg.log"
ANALYSIS_LOG = "frame_report.ffmpeg.log"
_SCRATCH_NAMES = (SHEET_PARTIAL, REPORT_PARTIAL, SHEET_LOG, ANALYSIS_LOG)

MAX_SAMPLES = 200
MAX_COLS = 16
THUMB_WIDTH_RANGE = (32, 1920)
MAX_SHEET_PIXELS = 64_000_000                  # keeps a mistyped argument from exhausting RAM

# Informational only, on 8-bit luma (0-255). NOT calibrated: the single baseline so far is
# the Milestone 1 shot (YDIF max 0.61, scene score max 0.085, |dYAVG| max 0.12).
INFO_THRESHOLDS = {
    "dark_frame_yavg_below": 16.0,
    "large_difference_ydif_at_least": 25.0,
    "brightness_jump_at_least": 8.0,
    "scene_score_at_least": 10.0,
}

_SHOT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_FRAME_LINE = re.compile(r"^frame:(\d+)\s+pts:\S+\s+pts_time:\S+")
_METRIC_KEYS = {"lavfi.signalstats.YAVG": "yavg", "lavfi.signalstats.YDIF": "ydif",
                "lavfi.scd.score": "scene_score"}


class ContactSheetError(RuntimeError):
    pass


@dataclass
class Render:
    """A rendered shot whose build report and frames passed validation."""
    shot_dir: Path
    report_path: Path
    spec_path: Path | None
    shot_id: str
    frames_dir: Path
    start: int
    end: int
    fps: int
    width: int
    height: int
    smoke: bool
    blender_version: str | None
    source_pix_fmt: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return self.end - self.start + 1

    def frame_path(self, frame: int) -> Path:
        return self.frames_dir / f"{self.shot_id}_{frame:04d}.png"

    @property
    def pattern(self) -> str:
        """FFmpeg image2 pattern; a literal % in the directory must be doubled."""
        return str(self.frames_dir).replace("%", "%%") + os.sep + f"{self.shot_id}_%04d.png"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def sample_frames(start: int, end: int, count: int) -> list[int]:
    """Evenly spaced Blender frame numbers across the inclusive range start..end.

    Sorted and unique. A single-frame range returns [start]. Otherwise the first and last
    frames are always included, so the result has max(count, 2) frames, capped at the
    number of frames in the range (every frame when count >= that number).
    """
    if not (_is_int(start) and _is_int(end) and _is_int(count)):
        raise ValueError("start, end and count must be integers")
    if end < start:
        raise ValueError(f"invalid frame range {start}-{end}")
    if count < 1:
        raise ValueError("count must be at least 1")
    n = end - start + 1
    if n == 1:
        return [start]
    k = min(max(count, 2), n)
    # round(i * (n - 1) / (k - 1)) with exact integer maths, halves rounded up
    picks = {start + (2 * i * (n - 1) + (k - 1)) // (2 * (k - 1)) for i in range(k)}
    return sorted(picks)


def grid_shape(n_samples: int, cols: int) -> tuple[int, int]:
    """(columns, rows) of the contact sheet; see the module docstring."""
    columns = min(cols, n_samples)
    return columns, math.ceil(n_samples / columns)


def thumb_height(thumb_width: int, width: int, height: int) -> int:
    return max(1, (2 * thumb_width * height + width) // (2 * width))


def _summary(values: list[tuple[int, float]]) -> dict | None:
    """min / max / median of (frame, value) pairs; extrema report their first frame."""
    if not values:
        return None
    lo = min(values, key=lambda fv: fv[1])
    hi = max(values, key=lambda fv: fv[1])
    return {"count": len(values), "min": lo[1], "min_frame": lo[0], "max": hi[1],
            "max_frame": hi[0], "median": round(statistics.median(v for _, v in values), 4)}


# ---------------------------------------------------------------------------
# Subprocess helpers (argument lists only, never a shell)
# ---------------------------------------------------------------------------
def _run(cmd: list[str], log: Path | None, what: str) -> subprocess.CompletedProcess:
    see = f" (log: {log})" if log else ""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                              timeout=config.FFMPEG_TIMEOUT_S)
    except subprocess.TimeoutExpired as e:
        if log:
            stderr = e.stderr if isinstance(e.stderr, str) else ""
            log.write_text(" ".join(cmd) + f"\n\nTIMEOUT after {config.FFMPEG_TIMEOUT_S}s "
                           "(FFMPEG_TIMEOUT_S)\n" + stderr)
        raise ContactSheetError(f"{what} timed out after {config.FFMPEG_TIMEOUT_S}s "
                                f"(raise FFMPEG_TIMEOUT_S if the shot is long){see}") from e
    except OSError as e:
        raise ContactSheetError(f"{what}: cannot run {cmd[0]!r} ({e}); install FFmpeg or "
                                "set FFMPEG_BIN / FFPROBE_BIN") from e
    if log:
        log.write_text(" ".join(cmd) + "\n\n" + proc.stderr)
    if proc.returncode != 0:
        raise ContactSheetError(f"{what} failed (exit {proc.returncode}): "
                                f"{proc.stderr.strip()[-800:]}{see}")
    return proc


def _probe_image(path: Path) -> dict:
    cmd = [config.FFPROBE_BIN, "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=width,height,pix_fmt", "-of", "json", str(path)]
    proc = _run(cmd, None, f"ffprobe {path.name}")
    streams = json.loads(proc.stdout).get("streams") or []
    if not streams:
        raise ContactSheetError(f"ffprobe found no image in {path}")
    return streams[0]


def _tool_version(binary: str) -> str | None:
    try:
        proc = subprocess.run([binary, "-version"], capture_output=True, text=True,
                              errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    first = proc.stdout.splitlines()[0].strip() if proc.stdout else ""
    return first if proc.returncode == 0 and first else None


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------
def _inside(child: Path, parent: Path) -> bool:
    return Path(os.path.normcase(child)).is_relative_to(Path(os.path.normcase(parent)))


def load_render(shot_dir: Path) -> Render:
    """Validate build_report.json and every expected frame. Writes nothing."""
    if not shot_dir.is_dir():
        raise ContactSheetError(f"shot directory not found: {shot_dir}")
    shot_dir = shot_dir.resolve(strict=True)
    report_path = shot_dir / "build_report.json"
    marker = shot_dir / REPORT_INCOMPLETE
    if marker.exists():
        raise ContactSheetError(f"{marker} exists: the worker's rewrite of build_report.json "
                                "failed or was interrupted, so the report may be stale or "
                                "incomplete; re-run the build")
    if not report_path.is_file():
        raise ContactSheetError(f"{report_path} not found; the render did not complete "
                                "(PNG files alone are not evidence of a successful render)")
    try:
        report = json.loads(report_path.read_text())
    except (OSError, ValueError) as e:
        raise ContactSheetError(f"cannot read {report_path}: {e}") from e
    if not isinstance(report, dict):
        raise ContactSheetError(f"{report_path} is not a JSON object")

    if report.get("status") != "ok":
        raise ContactSheetError(f"build status is {report.get('status')!r}, not 'ok'"
                                + (f": {report['error']}" if report.get("error") else ""))
    missing = [k for k in ("shot_id", "frames_dir", "frame_range", "resolution", "fps")
               if k not in report]
    if missing:
        raise ContactSheetError(f"build_report.json lacks {missing}; was the shot rendered "
                                "(not built with --no-render)?")

    shot_id = report["shot_id"]
    if not isinstance(shot_id, str) or not _SHOT_ID.match(shot_id):
        raise ContactSheetError(f"invalid shot_id {shot_id!r}")
    fr = report["frame_range"]
    if not (isinstance(fr, list) and len(fr) == 2 and all(_is_int(v) for v in fr)):
        raise ContactSheetError(f"invalid frame_range {fr!r}; expected [start, end] integers")
    start, end = fr
    if start < 0 or end < start:
        raise ContactSheetError(f"invalid frame_range {fr!r}")
    res = report["resolution"]
    if not (isinstance(res, list) and len(res) == 2 and all(_is_int(v) and v > 0 for v in res)):
        raise ContactSheetError(f"invalid resolution {res!r}; expected [width, height]")
    fps = report["fps"]
    if not (_is_int(fps) and 1 <= fps <= 240):
        raise ContactSheetError(f"invalid fps {fps!r}; expected an integer 1-240")

    raw = report["frames_dir"]
    if not isinstance(raw, str) or not raw:
        raise ContactSheetError(f"invalid frames_dir {raw!r}")
    frames_dir = Path(raw) if Path(raw).is_absolute() else shot_dir / raw
    if not frames_dir.is_dir():
        raise ContactSheetError(f"frames_dir not found: {frames_dir}")
    frames_dir = frames_dir.resolve(strict=True)
    if not _inside(frames_dir, shot_dir):
        raise ContactSheetError(f"frames_dir {frames_dir} is outside the shot directory {shot_dir}")

    spec_path = shot_dir / "spec.json"
    r = Render(shot_dir=shot_dir, report_path=report_path,
               spec_path=spec_path if spec_path.is_file() else None, shot_id=shot_id,
               frames_dir=frames_dir, start=start, end=end, fps=fps, width=res[0],
               height=res[1], smoke=bool(report.get("smoke", False)),
               blender_version=report.get("blender_version"))

    absent = [f for f in range(start, end + 1) if not r.frame_path(f).is_file()]
    if absent:
        raise ContactSheetError(f"{len(absent)} of {r.count} expected frames missing in "
                                f"{frames_dir}, first {r.frame_path(absent[0]).name}")

    for f in sorted({start, end}):
        info = _probe_image(r.frame_path(f))
        if (info.get("width"), info.get("height")) != (r.width, r.height):
            raise ContactSheetError(
                f"frame {f} is {info.get('width')}x{info.get('height')} but build_report.json "
                f"says {r.width}x{r.height}; the frames may come from a different render")
        if r.source_pix_fmt is None:
            r.source_pix_fmt = info.get("pix_fmt")
        elif info.get("pix_fmt") != r.source_pix_fmt:
            r.warnings.append(f"frames {start} and {end} have different pixel formats "
                              f"({r.source_pix_fmt}, {info.get('pix_fmt')})")

    expected = {r.frame_path(f).name for f in range(start, end + 1)}
    extras = sorted(p.name for p in frames_dir.glob("*.png") if p.name not in expected)
    if extras:
        r.warnings.append(
            f"{len(extras)} PNG file(s) in frames_dir are outside the expected range "
            f"{start}-{end} (e.g. {extras[:3]}); possibly left by an earlier render. "
            "This is not proof that the expected frames are stale or fresh.")
    if r.spec_path is None:
        r.warnings.append("spec.json not found in the shot directory; frame age not checked")
    else:
        spec_mtime = r.spec_path.stat().st_mtime
        older = [f for f in range(start, end + 1) if r.frame_path(f).stat().st_mtime < spec_mtime]
        if older:
            r.warnings.append(
                f"{len(older)} of {r.count} expected frames are older than spec.json "
                f"(e.g. frames {older[:5]}); they may be stale from an earlier render, since "
                "animatic renders do not overwrite existing frames. This is a timestamp hint, "
                "not proof that the frames are stale or fresh.")
    return r


# ---------------------------------------------------------------------------
# FFmpeg passes
# ---------------------------------------------------------------------------
def _font_arg(font: Path) -> str | None:
    """FFmpeg filter-option form of a font path, or None if it can't be quoted safely."""
    s = str(font).replace("\\", "/")
    if "'" in s:
        return None
    return s.replace(":", "\\:")


def make_contact_sheet(r: Render, samples: list[int], cols: int, thumb_w: int,
                       out: Path, log: Path) -> dict:
    """One streamed FFmpeg pass: trim -> select samples -> scale -> label -> tile -> rgb24."""
    columns, rows = grid_shape(len(samples), cols)
    thumb_h = thumb_height(thumb_w, r.width, r.height)
    select = "+".join(f"eq(n,{f - r.start})" for f in samples)
    chain = [f"trim=end_frame={r.count}", f"select='{select}'", f"scale={thumb_w}:{thumb_h}"]

    font = Path(config.FFMPEG_FONTFILE)
    font_arg = _font_arg(font) if font.is_file() else None
    warnings = []
    if font_arg:
        size = max(10, thumb_w // 16)
        # t * fps recovers the input index n (image2 timebase is 1/fps); add frame_start
        label = f"%{{eif\\:trunc(t*{r.fps}+0.5)+{r.start}\\:d}}"
        chain.append(f"drawtext=fontfile='{font_arg}':text='{label}':x=4:y=4:"
                     f"fontsize={size}:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=3")
    else:
        warnings.append(f"font {font} is unavailable; contact sheet has no frame labels")
    chain += [f"tile={columns}x{rows}", "format=rgb24"]

    # -xerror: a frame that fails to decode would otherwise be dropped silently, shifting
    # every later sample index; make it fatal instead
    cmd = [config.FFMPEG_BIN, "-hide_banner", "-nostdin", "-y", "-v", "error", "-xerror",
           "-framerate", str(r.fps), "-start_number", str(r.start), "-i", r.pattern,
           "-vf", ",".join(chain), "-frames:v", "1", "-update", "1",
           "-threads", str(config.FFMPEG_THREADS), str(out)]
    _run(cmd, log, "contact sheet")
    if not out.is_file():
        raise ContactSheetError(f"FFmpeg reported success but wrote no {out.name}")

    info = _probe_image(out)
    expected = (columns * thumb_w, rows * thumb_h)
    if (info.get("width"), info.get("height")) != expected or info.get("pix_fmt") != "rgb24":
        raise ContactSheetError(f"contact sheet is {info.get('width')}x{info.get('height')} "
                                f"{info.get('pix_fmt')}, expected {expected[0]}x{expected[1]} rgb24")
    return {"columns": columns, "rows": rows, "thumb_width": thumb_w, "thumb_height": thumb_h,
            "width": expected[0], "height": expected[1], "pix_fmt": "rgb24",
            "labels": bool(font_arg), "label_font": str(font) if font_arg else None,
            "warnings": warnings}


def analyse_frames(r: Render, log: Path) -> list[dict]:
    """One streamed FFmpeg pass of 8-bit luma statistics; one entry per expected frame."""
    vf = (f"trim=end_frame={r.count},format=gray,signalstats,"
          f"scdet=threshold={INFO_THRESHOLDS['scene_score_at_least']},metadata=mode=print:file=-")
    cmd = [config.FFMPEG_BIN, "-hide_banner", "-nostdin", "-v", "error", "-xerror",
           "-framerate", str(r.fps), "-start_number", str(r.start), "-i", r.pattern,
           "-vf", vf, "-threads", str(config.FFMPEG_THREADS), "-f", "null", "-"]
    proc = _run(cmd, log, "frame analysis")

    rows: dict[int, dict] = {}
    current = None
    for line in proc.stdout.splitlines():
        m = _FRAME_LINE.match(line)
        if m:
            current = rows.setdefault(int(m[1]), {})
            continue
        key, sep, value = line.strip().partition("=")
        if sep and current is not None and key in _METRIC_KEYS:
            try:
                current[_METRIC_KEYS[key]] = float(value)
            except ValueError:
                pass

    if sorted(rows) != list(range(r.count)):
        raise ContactSheetError(f"frame analysis incomplete: FFmpeg reported {len(rows)} of "
                                f"{r.count} frames; no report written")
    lacking = [r.start + n for n, m in rows.items() if "yavg" not in m or "ydif" not in m]
    if lacking:
        raise ContactSheetError(f"frame analysis incomplete: no luma statistics for frames "
                                f"{lacking[:5]}; no report written")

    frames = []
    for n in range(r.count):
        m = rows[n]
        score = m.get("scene_score")
        frames.append({"frame": r.start + n, "yavg": round(m["yavg"], 4),
                       "ydif": None if n == 0 else round(m["ydif"], 4),
                       "scene_score": None if n == 0 or score is None else round(score, 4)})
    return frames


def _flags(frames: list[dict]) -> list[dict]:
    t = INFO_THRESHOLDS
    out = []
    prev = None
    for f in frames:
        checks = [
            ("dark_frame", "yavg", f["yavg"], f["yavg"] < t["dark_frame_yavg_below"],
             t["dark_frame_yavg_below"]),
            ("large_difference", "ydif", f["ydif"],
             f["ydif"] is not None and f["ydif"] >= t["large_difference_ydif_at_least"],
             t["large_difference_ydif_at_least"]),
            ("scene_change", "scene_score", f["scene_score"],
             f["scene_score"] is not None and f["scene_score"] >= t["scene_score_at_least"],
             t["scene_score_at_least"]),
        ]
        if prev is not None:
            jump = round(abs(f["yavg"] - prev["yavg"]), 4)
            checks.append(("brightness_jump", "yavg_delta", jump,
                           jump >= t["brightness_jump_at_least"], t["brightness_jump_at_least"]))
        out += [{"frame": f["frame"], "kind": kind, "metric": metric, "value": value,
                 "threshold": thr} for kind, metric, value, hit, thr in checks if hit]
        prev = f
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def run(shot_dir: Path, samples: int = 12, cols: int = 4, thumb_width: int = 320,
        force: bool = False) -> dict:
    for name, v, lo, hi in (("samples", samples, 1, MAX_SAMPLES), ("cols", cols, 1, MAX_COLS),
                            ("thumb-width", thumb_width, *THUMB_WIDTH_RANGE)):
        if not (_is_int(v) and lo <= v <= hi):
            raise ContactSheetError(f"--{name} must be an integer {lo}-{hi}, got {v!r}")

    review = Path(shot_dir) / REVIEW_DIR
    sheet, report_out = review / SHEET_NAME, review / REPORT_NAME
    existing = [p for p in (sheet, report_out) if p.exists()]
    if existing and not force:
        raise ContactSheetError(f"review output already exists: {[str(p) for p in existing]}; "
                                "pass --force to replace it")
    # From here on this run owns the review outputs. Remove old results (--force), partial
    # files left by an interrupted run, and old logs, so nothing from an earlier attempt can
    # be mistaken for this one, even if this run fails before writing anything.
    for name in (SHEET_NAME, REPORT_NAME, *_SCRATCH_NAMES):
        (review / name).unlink(missing_ok=True)

    r = load_render(Path(shot_dir))
    picks = sample_frames(r.start, r.end, samples)
    columns, rows = grid_shape(len(picks), cols)
    thumb_h = thumb_height(thumb_width, r.width, r.height)
    if columns * thumb_width * rows * thumb_h > MAX_SHEET_PIXELS:
        raise ContactSheetError(f"contact sheet would exceed {MAX_SHEET_PIXELS} pixels; "
                                "use fewer samples or a smaller --thumb-width")

    review = r.shot_dir / REVIEW_DIR
    sheet, report_out = review / SHEET_NAME, review / REPORT_NAME
    sheet_tmp, report_tmp = review / SHEET_PARTIAL, review / REPORT_PARTIAL
    sheet_log, analysis_log = review / SHEET_LOG, review / ANALYSIS_LOG
    review.mkdir(exist_ok=True)
    try:
        geometry = make_contact_sheet(r, picks, cols, thumb_width, sheet_tmp, sheet_log)
        frames = analyse_frames(r, analysis_log)
        flags = _flags(frames)

        warnings = r.warnings + geometry.pop("warnings")
        if flags:
            warnings.append(f"{len(flags)} informational analysis flag(s); thresholds are "
                            "uncalibrated and a flag is not a confirmed defect")
        report = {
            "schema": SCHEMA,
            "shot_id": r.shot_id,
            "verdict": "evidence_only",
            "human_approval_required": True,
            "inputs": {"shot_dir": str(r.shot_dir), "build_report": str(r.report_path),
                       "spec": str(r.spec_path) if r.spec_path else None,
                       "frames_dir": str(r.frames_dir),
                       "frame_pattern": f"{r.shot_id}_%04d.png"},
            "render": {"frame_range": [r.start, r.end], "frame_count": r.count, "fps": r.fps,
                       "resolution": [r.width, r.height], "source_pix_fmt": r.source_pix_fmt,
                       "smoke": r.smoke, "blender_version": r.blender_version},
            "contact_sheet": {"path": str(sheet), "samples_requested": samples,
                              "sampled_frames": picks, "max_columns": cols, **geometry},
            "analysis": {
                "luma": "8-bit grayscale (format=gray) before signalstats; 0-255 scale",
                "frame_numbering": "frame = frame_start + n (n = 0-based filter index)",
                "first_frame_difference": "ydif and scene_score are null for the first "
                                          "frame (no previous frame) and excluded from summaries",
                "note": "Metrics are evidence for human review. They do not prove or rule "
                        "out visual defects.",
                "thresholds": {**INFO_THRESHOLDS, "calibrated": False},
                "summary": {
                    "yavg": _summary([(f["frame"], f["yavg"]) for f in frames]),
                    "ydif": _summary([(f["frame"], f["ydif"]) for f in frames
                                      if f["ydif"] is not None]),
                    "scene_score": _summary([(f["frame"], f["scene_score"]) for f in frames
                                             if f["scene_score"] is not None]),
                },
                "flags": flags,
                "frames": frames,
            },
            "warnings": warnings,
            "tools": {"ffmpeg": _tool_version(config.FFMPEG_BIN),
                      "ffprobe": _tool_version(config.FFPROBE_BIN)},
            "logs": {"contact_sheet": str(sheet_log), "analysis": str(analysis_log)},
        }
        report_tmp.write_text(json.dumps(report, indent=2) + "\n")
        os.replace(sheet_tmp, sheet)
        os.replace(report_tmp, report_out)       # the report appears last, only on success
    except BaseException:
        for p in (sheet_tmp, report_tmp, sheet, report_out):
            p.unlink(missing_ok=True)
        raise

    return {"status": "evidence_written", "verdict": "evidence_only",
            "human_approval_required": True, "shot_id": r.shot_id,
            "contact_sheet": str(sheet), "frame_report": str(report_out),
            "sampled_frames": picks, "sheet_size": [geometry["width"], geometry["height"]],
            "flags": len(flags), "warnings": warnings}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="contact_sheet",
                                description="Write review evidence for one rendered shot.")
    p.add_argument("--shot-dir", required=True, type=Path,
                   help="e.g. storage/projects/milestone1/shots/m1_primitives")
    p.add_argument("--samples", type=int, default=12, help="frames on the sheet (default 12)")
    p.add_argument("--cols", type=int, default=4, help="maximum grid columns (default 4)")
    p.add_argument("--thumb-width", type=int, default=320, help="thumbnail width px (default 320)")
    p.add_argument("--force", action="store_true", help="replace existing review output")
    args = p.parse_args(argv)
    try:
        summary = run(args.shot_dir, args.samples, args.cols, args.thumb_width, args.force)
    except Exception as e:  # noqa: BLE001 — report every failure to the operator
        print(f"FAILED: {e}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
