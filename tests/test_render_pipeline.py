"""Full Milestone 1 render: 96 frames, 640x360, 24 fps. Run with: pytest -m render

Writes the deliverable to storage/projects/milestone1/ (git-ignored) rather than a temp
dir, so the slow render is not repeated just to produce the final MP4.
"""
import shutil

import pytest

from workers import config
from workers.run_milestone1 import DEFAULT_PROJECT, DEFAULT_SPEC, run

pytestmark = [
    pytest.mark.render,
    pytest.mark.skipif(shutil.which(config.BLENDER_BIN) is None, reason="Blender not found"),
]


def test_full_milestone_render():
    summary = run(DEFAULT_SPEC, DEFAULT_PROJECT)
    assert summary["ok"], summary["errors"]
    v = summary["video"]
    assert (v["codec"], v["pix_fmt"], v["width"], v["height"]) == ("h264", "yuv420p", 640, 360)
    assert (v["frames"], v["fps"]) == (96, 24.0)
    assert v["duration_s"] == pytest.approx(4.0, abs=0.05)
