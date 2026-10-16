"""Worker-side helper: validate a SceneSpec, then run Blender headless on it.

Usage from an arq/RQ job:
    result = run_shot(spec_dict, project_dir=Path("storage/projects/demo"))
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from apps.api.schemas.scene_spec import (AssetManifest, SceneSpec, camera_warnings,
                                         shot_warnings, validate_against_manifest)
from workers import config

REPO = Path(__file__).resolve().parents[1]
ASSETS = REPO / "assets"

# Written next to build_report.json while the worker rewrites it; removed only once the
# rewrite has fully succeeded. While it exists, the on-disk report must not be trusted
# (workers/contact_sheet.py refuses the shot).
REPORT_INCOMPLETE = "build_report.json.incomplete"
REPORT_TMP = "build_report.json.tmp"


class SpecRejected(ValueError):
    """Raised with LLM-readable errors so the planning stage can retry."""
    def __init__(self, errors: list[str]):
        super().__init__("\n".join(errors))
        self.errors = errors


def validate(spec_dict: dict) -> SceneSpec:
    spec = SceneSpec.model_validate(spec_dict)  # raises pydantic.ValidationError
    manifest = AssetManifest.model_validate_json((ASSETS / "manifest.json").read_text())
    errors = validate_against_manifest(spec, manifest)
    if errors:
        raise SpecRejected(errors)
    return spec


def run_shot(spec_dict: dict, project_dir: Path, render: bool = True, smoke: bool = False) -> dict:
    """Blocks until Blender exits, so callers run Blender and FFmpeg strictly in sequence.
    smoke=True renders only the first 8 frames at 50% resolution."""
    spec = validate(spec_dict)
    shot_dir = project_dir / "shots" / spec.shot_id
    shot_dir.mkdir(parents=True, exist_ok=True)
    spec_path = shot_dir / "spec.json"
    spec_path.write_text(spec.model_dump_json(indent=2))

    template = REPO / "blender" / "templates" / f"{spec.style_template}.blend"
    # --factory-startup: ignore user prefs/add-ons, so builds are repeatable and lighter
    cmd = [config.BLENDER_BIN, "-b", "--factory-startup", "-t", str(config.BLENDER_THREADS)]
    if template.exists():
        cmd.append(str(template))          # opened read-only in effect: we save elsewhere
    cmd += ["--python-exit-code", "1",
            "-P", str(REPO / "blender" / "scripts" / "build_scene.py"), "--",
            "--spec", str(spec_path), "--assets-root", str(ASSETS), "--out", str(shot_dir)]
    if not render:
        cmd.append("--no-render")
    if smoke:
        cmd.append("--smoke")

    report_path = shot_dir / "build_report.json"
    # never mistake a previous run's report (or its unfinished rewrite) for this one
    for stale in (report_path, shot_dir / REPORT_INCOMPLETE, shot_dir / REPORT_TMP):
        stale.unlink(missing_ok=True)
    log_path = shot_dir / "blender.log"
    with log_path.open("w") as log:
        proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT,
                              timeout=config.BLENDER_TIMEOUT_S)

    report = _read_report(report_path, proc.returncode)
    if report.get("status") == "ok" and proc.returncode == 0:
        report = _merge_camera_warnings(report, report_path, spec)
    report["returncode"], report["log"] = proc.returncode, str(log_path)
    return report


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def rendered_frames_problem(report: dict) -> str | None:
    """Why a build report's frames are NOT a complete render, or None if they are.

    The builder writes `rendered_frames` when it renders only some frames (v1.3 multi-shot
    smoke: stills either side of each cut) while `frame_range` stays the full timeline. The
    frames directory is never cleared, so files from an earlier render can fill the gaps; the
    file count is therefore not evidence. Completeness is decided from the report alone:

      * no `rendered_frames` key: a legacy/complete report -> None (unchanged behaviour);
      * otherwise it must be a list of integers covering every frame of `frame_range`
        exactly once (order is irrelevant); anything else, including malformed metadata,
        is a problem. Consumers (encoder, contact sheet) refuse such reports.
    """
    if "rendered_frames" not in report:
        return None
    frames, fr = report["rendered_frames"], report.get("frame_range")
    if not (isinstance(fr, list) and len(fr) == 2 and all(_is_int(v) for v in fr)
            and fr[0] <= fr[1]):
        return f"frame_range {fr!r} is not a valid [start, end] pair"
    if not isinstance(frames, list) or not all(_is_int(f) for f in frames):
        return f"rendered_frames {frames!r} is not a list of integer frame numbers"
    start, end = fr
    expected = set(range(start, end + 1))
    dupes = sorted({f for f in frames if frames.count(f) > 1})
    unexpected = sorted(set(frames) - expected)
    missing = sorted(expected - set(frames))
    if dupes or unexpected or missing:
        parts = []
        if missing:
            parts.append(f"{len(missing)} of {len(expected)} frames in {start}-{end} were not "
                         f"rendered (first {missing[0]})")
        if unexpected:
            parts.append(f"frames outside {start}-{end}: {unexpected[:5]}")
        if dupes:
            parts.append(f"duplicated frames: {dupes[:5]}")
        return "; ".join(parts)
    return None


def _read_report(report_path: Path, returncode: int) -> dict:
    if not report_path.exists():
        return {"status": "crash", "error": f"Blender exited {returncode} without a report"}
    try:
        report = json.loads(report_path.read_text())
    except (OSError, ValueError) as e:
        return {"status": "crash", "error": f"unreadable {report_path.name}: {e}"}
    if not isinstance(report, dict):
        return {"status": "crash", "error": f"{report_path.name} is not a JSON object"}
    return report


def _merge_camera_warnings(report: dict, report_path: Path, spec: SceneSpec) -> dict:
    """Add camera_warnings() (settings a 1.0/1.1 spec contains but the builder ignores) and
    then shot_warnings() (advisory notes on a 1.3 shot list), in that order, after the
    builder's own warnings and without duplicates.

    Blender's Python has no pydantic, so the rules live only in the schema module and are
    applied here, after a successful build. The merged report is written back to disk so
    build_report.json stays the single record of the build.

    Write-ahead protocol, so a failed or interrupted rewrite can never leave a report that
    looks complete:
      1. create REPORT_INCOMPLETE next to the report;
      2. write the merged report to REPORT_TMP, flush it, then os.replace() it over the
         original (atomic on one volume: the old or the new report, never a truncated one);
      3. remove REPORT_INCOMPLETE only after the replace succeeded.
    Any failure returns status "report_error" and leaves the marker in place. A file held
    open by another process blocks both replacing and renaming on Windows, but not creating
    the marker. If the marker itself can't be created, the report is left untouched and the
    error says it may still read "ok".
    """
    existing = list(report.get("warnings", []))
    new = []
    for w in camera_warnings(spec) + shot_warnings(spec):
        if w not in existing and w not in new:
            new.append(w)
    if not new:
        return report
    merged = {**report, "warnings": list(report.get("warnings", [])) + new}
    marker, tmp = report_path.with_name(REPORT_INCOMPLETE), report_path.with_name(REPORT_TMP)
    failed = {**merged, "status": "report_error"}

    try:
        marker.write_text(json.dumps({"reason": "camera warning rewrite in progress",
                                      "report": report_path.name}, indent=2))
    except OSError as e:
        return {**failed, "error": f"could not write camera warnings to {report_path}: cannot "
                                   f"create {marker.name} ({e}); the on-disk report was left "
                                   "unchanged and may still read status 'ok' without them"}
    try:
        _write_durably(tmp, json.dumps(merged, indent=2))
        os.replace(tmp, report_path)
    except OSError as e:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return {**failed, "error": f"could not write camera warnings to {report_path}: {e}; "
                                   f"{marker.name} marks the on-disk report as incomplete"}
    try:
        marker.unlink()
    except OSError as e:
        return {**failed, "error": f"camera warnings were written to {report_path}, but "
                                   f"{marker.name} could not be removed ({e}); the shot stays "
                                   "marked incomplete"}
    return merged


def _write_durably(path: Path, text: str) -> None:
    with open(path, "w") as f:           # same default encoding as Path.write_text
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
