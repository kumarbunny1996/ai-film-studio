"""run_milestone1.run() refuses partial renders (audit P1-1). No Blender: run_shot is replaced
by a stand-in that returns the report the builder would write; frames come from FFmpeg."""
import hashlib
import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from workers import config, run_milestone1
from workers.blender_job import rendered_frames_problem
from workers.run_milestone1 import PipelineError

needs_ffmpeg = pytest.mark.skipif(shutil.which(config.FFMPEG_BIN) is None,
                                  reason="ffmpeg not found")
SHOT = "seq"
FULL = list(range(1, 25))                       # a 24-frame, three-shot timeline: 1-8, 9-16, 17-24
SMOKE = [1, 8, 9, 16, 17, 24]                   # first and last frame of every shot


def frames_dir(project: Path) -> Path:
    return project / "shots" / SHOT / "frames"


def make_frames(project: Path, frames, color: str):
    d = frames_dir(project)
    d.mkdir(parents=True, exist_ok=True)
    for f in frames:
        subprocess.run([config.FFMPEG_BIN, "-v", "error", "-y", "-f", "lavfi", "-i",
                        f"color=c={color}:s=320x240:r=24", "-frames:v", "1", "-update", "1",
                        str(d / f"{SHOT}_{f:04d}.png")], check=True)


def snapshot(project: Path) -> dict:
    return {p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in sorted(frames_dir(project).glob("*.png"))}


def report(project: Path, **extra) -> dict:
    r = {"shot_id": SHOT, "status": "ok", "warnings": [], "returncode": 0,
         "log": str(project / "blender.log"), "frames_dir": str(frames_dir(project)),
         "frame_range": [1, 24], "resolution": [320, 240], "fps": 24}
    r.update(extra)
    return r


def run_with(monkeypatch, tmp_path, rep: dict, *, smoke=False, ffmpeg_allowed=True):
    monkeypatch.setattr(run_milestone1, "run_shot", lambda spec, project_dir, smoke=False: rep)
    if not ffmpeg_allowed:
        def forbidden(*a, **k):
            raise AssertionError("FFmpeg/ffprobe must not be called for a refused report")
        monkeypatch.setattr(run_milestone1, "encode_png_sequence", forbidden)
        monkeypatch.setattr(run_milestone1, "probe", forbidden)
    spec = tmp_path / "spec.json"
    spec.write_text("{}")
    return run_milestone1.run(spec, tmp_path / "project", smoke=smoke)


# ---------------------------------------------------------------------------
# The audited failure: smoke stills over a previous complete render
# ---------------------------------------------------------------------------
@needs_ffmpeg
def test_smoke_over_stale_full_render_is_refused_before_ffmpeg(tmp_path, monkeypatch):
    project = tmp_path / "project"
    make_frames(project, FULL, "gray")                     # an earlier complete render
    make_frames(project, SMOKE, "red")                     # this run's smoke stills
    before = snapshot(project)
    assert len(before) == 24                               # every file exists: not evidence
    rep = report(project, smoke=True, smoke_frames=SMOKE, rendered_frames=SMOKE)
    with pytest.raises(PipelineError, match=r"Partial \(smoke\) render; not encodable: 18 of 24 "
                                            r"frames in 1-24 were not rendered \(first 2\)"):
        run_with(monkeypatch, tmp_path, rep, smoke=True, ffmpeg_allowed=False)
    assert snapshot(project) == before                     # stale frames untouched
    assert not list(project.glob("*.mp4")) and not list(project.glob("*.summary.json"))


# ---------------------------------------------------------------------------
# Complete renders are still encoded
# ---------------------------------------------------------------------------
@needs_ffmpeg
@pytest.mark.parametrize("order", ["sorted", "shuffled"])
def test_complete_rendered_frames_is_encoded(tmp_path, monkeypatch, order):
    project = tmp_path / "project"
    make_frames(project, FULL, "gray")
    frames = FULL[:] if order == "sorted" else random.Random(1).sample(FULL, len(FULL))
    summary = run_with(monkeypatch, tmp_path, report(project, rendered_frames=frames))
    assert summary["ok"] and summary["video"]["frames"] == 24


@needs_ffmpeg
def test_legacy_report_without_rendered_frames_is_unchanged(tmp_path, monkeypatch):
    project = tmp_path / "project"
    make_frames(project, FULL, "gray")
    summary = run_with(monkeypatch, tmp_path, report(project))
    assert summary["ok"] and summary["video"]["frames"] == 24
    assert summary["video"]["width"] == 320


def test_legacy_missing_frames_check_still_applies(tmp_path, monkeypatch):
    project = tmp_path / "project"
    frames_dir(project).mkdir(parents=True)                # nothing rendered
    with pytest.raises(PipelineError, match="24 frames missing"):
        run_with(monkeypatch, tmp_path, report(project), ffmpeg_allowed=False)


# ---------------------------------------------------------------------------
# Malformed or incomplete rendered_frames never bypass the guard
# ---------------------------------------------------------------------------
BAD_RENDERED = {
    "one-missing": [f for f in FULL if f != 12],
    "duplicate": FULL + [12],
    "unexpected-frame": FULL + [25],
    "frame-zero": [0] + FULL,
    "empty": [],
    "bools": [True] * 24,
    "strings": [str(f) for f in FULL],
    "floats": [float(f) for f in FULL],
    "not-a-list": "1-24",
    "null": None,
    "dict": {"1": True},
}


@pytest.mark.parametrize("rendered", BAD_RENDERED.values(), ids=BAD_RENDERED.keys())
def test_malformed_or_incomplete_rendered_frames_are_refused(tmp_path, monkeypatch, rendered):
    project = tmp_path / "project"
    frames_dir(project).mkdir(parents=True)
    with pytest.raises(PipelineError, match=r"Partial \(smoke\) render; not encodable"):
        run_with(monkeypatch, tmp_path, report(project, rendered_frames=rendered),
                 ffmpeg_allowed=False)


@pytest.mark.parametrize("frame_range", [[24, 1], ["1", "24"], [1], None, [True, 24]],
                         ids=["reversed", "strings", "short", "null", "bool"])
def test_rendered_frames_with_malformed_frame_range_is_refused(tmp_path, monkeypatch, frame_range):
    project = tmp_path / "project"
    frames_dir(project).mkdir(parents=True)
    rep = report(project, rendered_frames=FULL, frame_range=frame_range)
    with pytest.raises(PipelineError, match=r"Partial \(smoke\) render; not encodable: "
                                            r"frame_range .* is not a valid"):
        run_with(monkeypatch, tmp_path, rep, ffmpeg_allowed=False)


# ---------------------------------------------------------------------------
# The shared contract itself
# ---------------------------------------------------------------------------
def test_rendered_frames_problem_contract():
    assert rendered_frames_problem({"frame_range": [1, 24]}) is None          # legacy
    assert rendered_frames_problem({"frame_range": [1, 24], "rendered_frames": FULL}) is None
    assert rendered_frames_problem({"frame_range": [5, 5], "rendered_frames": [5]}) is None
    msg = rendered_frames_problem({"frame_range": [1, 24], "rendered_frames": SMOKE})
    assert msg == "18 of 24 frames in 1-24 were not rendered (first 2)"
    msg = rendered_frames_problem({"frame_range": [1, 3], "rendered_frames": [1, 2, 2, 3, 9]})
    assert msg == "frames outside 1-3: [9]; duplicated frames: [2]"
