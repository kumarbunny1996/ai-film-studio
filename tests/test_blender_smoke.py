"""Headless Blender smoke tests (8 frames at 320x180). Run with: pytest -m blender"""
import shutil
import subprocess
import struct
from pathlib import Path

import pytest

from workers import config
from workers.blender_job import REPO
from workers.encode import encode_png_sequence, probe, verify
from workers.run_milestone1 import DEFAULT_SPEC, run

pytestmark = [
    pytest.mark.blender,
    pytest.mark.skipif(shutil.which(config.BLENDER_BIN) is None, reason="Blender not found"),
]


def png_size(path: Path) -> tuple[int, int]:
    return struct.unpack(">II", path.read_bytes()[16:24])


def test_standalone_smoke_render(tmp_path):
    proc = subprocess.run(
        [config.BLENDER_BIN, "-b", "--factory-startup", "-t", str(config.BLENDER_THREADS),
         "--python-exit-code", "1", "-P", str(REPO / "blender/scripts/smoke_test.py"),
         "--", str(tmp_path)],
        capture_output=True, text=True, errors="replace", timeout=600)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    pngs = sorted(tmp_path.glob("smoke_*.png"))
    assert len(pngs) == 8
    assert all(png_size(p) == (320, 180) for p in pngs)

    info = probe(encode_png_sequence(tmp_path / "smoke_%04d.png", 1, 8, 24, tmp_path / "smoke.mp4"))
    assert verify(info, frames=8, width=320, height=180, fps=24) == []


def test_milestone_scene_smoke(tmp_path):
    """The real v1.1 primitives shot, cut to 8 frames at 320x180."""
    summary = run(DEFAULT_SPEC, tmp_path, smoke=True)
    assert summary["ok"], summary["errors"]
    v = summary["video"]
    assert (v["frames"], v["width"], v["height"], v["codec"]) == (8, 320, 180, "h264")
    # no style template exists yet, so the builder starts from an empty scene
    assert summary["blender"]["warnings"] == [
        "no style template loaded; starting from an empty scene"]
    assert summary["blender"]["memory_mb"]["peak_working_set"] > 0
