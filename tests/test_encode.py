"""FFmpeg encode + ffprobe verification, on synthetic frames (no Blender needed)."""
import shutil
import subprocess

import pytest

from workers import config
from workers.encode import encode_png_sequence, probe, verify

pytestmark = pytest.mark.skipif(shutil.which(config.FFMPEG_BIN) is None, reason="ffmpeg not found")


@pytest.fixture
def frames(tmp_path):
    """12 numbered 320x180 PNGs starting at 1, like Blender writes them."""
    subprocess.run([config.FFMPEG_BIN, "-v", "error", "-f", "lavfi",
                    "-i", "testsrc=size=320x180:rate=24", "-frames:v", "12", "-start_number", "1",
                    str(tmp_path / "shot_%04d.png")], check=True)
    return tmp_path


def test_encode_and_verify(frames, tmp_path):
    mp4 = encode_png_sequence(frames / "shot_%04d.png", 1, 12, 24, tmp_path / "out.mp4")
    info = probe(mp4)
    assert verify(info, frames=12, width=320, height=180, fps=24) == []
    assert info["duration_s"] == pytest.approx(0.5, abs=0.05)


def test_verify_reports_every_mismatch(frames, tmp_path):
    info = probe(encode_png_sequence(frames / "shot_%04d.png", 1, 12, 24, tmp_path / "out.mp4"))
    errors = verify(info, frames=96, width=640, height=360, fps=25)
    assert len(errors) == 4 and any(e.startswith("frames") for e in errors)


def test_missing_frames_fail_loudly(tmp_path):
    with pytest.raises(Exception, match="ffmpeg exited"):
        encode_png_sequence(tmp_path / "none_%04d.png", 1, 8, 24, tmp_path / "out.mp4")
