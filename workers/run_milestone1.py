"""Milestone 1: SceneSpec -> Blender PNG frames -> FFmpeg MP4 -> ffprobe check.

    uv run python -m workers.run_milestone1 --smoke   # 8 frames at 50% resolution
    uv run python -m workers.run_milestone1           # full shot

Blender and FFmpeg run strictly one after the other, never at the same time.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from workers.blender_job import REPO, rendered_frames_problem, run_shot
from workers.encode import encode_png_sequence, probe, verify

DEFAULT_SPEC = REPO / "schemas" / "examples" / "milestone1_primitives.json"
DEFAULT_PROJECT = REPO / "storage" / "projects" / "milestone1"


class PipelineError(RuntimeError):
    pass


def run(spec_path: Path, project_dir: Path, smoke: bool = False) -> dict:
    report = run_shot(json.loads(spec_path.read_text()), project_dir, smoke=smoke)
    if report.get("status") != "ok" or report.get("returncode") != 0:
        raise PipelineError(f"Blender failed ({report.get('status')}, exit "
                            f"{report.get('returncode')}): {report.get('error')} — see {report['log']}")

    # Decided from the report, before any file checks or FFmpeg: stale files from an earlier
    # render can fill the gaps of a partial render, so their presence proves nothing.
    problem = rendered_frames_problem(report)
    if problem:
        raise PipelineError(f"Partial (smoke) render; not encodable: {problem}")

    shot_id = report["shot_id"]
    start, end = report["frame_range"]
    width, height = report["resolution"]
    frames_dir = Path(report["frames_dir"])
    missing = [f for f in range(start, end + 1)
               if not (frames_dir / f"{shot_id}_{f:04d}.png").exists()]
    if missing:
        raise PipelineError(f"{len(missing)} frames missing in {frames_dir}, first {missing[0]}")

    count = end - start + 1
    mp4 = project_dir / f"{shot_id}{'_smoke' if smoke else ''}.mp4"
    encode_png_sequence(frames_dir / f"{shot_id}_%04d.png", start, count, report["fps"], mp4)
    info = probe(mp4)
    errors = verify(info, count, width, height, report["fps"])

    summary = {"ok": not errors, "errors": errors, "mp4": str(mp4), "video": info,
               "blender": {k: report.get(k) for k in
                           ("blender_version", "timings", "memory_mb", "warnings", "log")}}
    mp4.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2))
    if errors:
        raise PipelineError("MP4 verification failed: " + "; ".join(errors))
    return summary


def main() -> int:
    p = argparse.ArgumentParser(prog="run_milestone1")
    p.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    p.add_argument("--project", type=Path, help="defaults to storage/projects/milestone1[_smoke]")
    p.add_argument("--smoke", action="store_true", help="first 8 frames at 50%% resolution")
    args = p.parse_args()
    project = args.project or DEFAULT_PROJECT.with_name(
        DEFAULT_PROJECT.name + ("_smoke" if args.smoke else ""))
    try:
        summary = run(args.spec, project, smoke=args.smoke)
    except Exception as e:  # noqa: BLE001 — report every failure to the operator
        print(f"FAILED: {e}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
