"""Encode a rendered PNG sequence to MP4 with FFmpeg (libx264), then verify it with ffprobe."""
from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from pathlib import Path

from workers import config


class EncodeError(RuntimeError):
    pass


def encode_png_sequence(pattern: Path, start: int, frames: int, fps: int, out: Path) -> Path:
    """pattern is an FFmpeg image pattern such as frames/shot_%04d.png.
    The log is written next to the MP4 as <name>.ffmpeg.log."""
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [config.FFMPEG_BIN, "-hide_banner", "-y",
           "-framerate", str(fps), "-start_number", str(start), "-i", str(pattern),
           "-frames:v", str(frames),
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
           "-threads", str(config.FFMPEG_THREADS), "-movflags", "+faststart", str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                          timeout=config.FFMPEG_TIMEOUT_S)
    out.with_suffix(".ffmpeg.log").write_text(" ".join(cmd) + "\n\n" + proc.stderr)
    if proc.returncode != 0 or not out.exists():
        raise EncodeError(f"ffmpeg exited {proc.returncode}: {proc.stderr.strip()[-800:]}")
    return out


def probe(video: Path) -> dict:
    """Decode-count the first video stream and return its key properties."""
    cmd = [config.FFPROBE_BIN, "-v", "error", "-select_streams", "v:0", "-count_frames",
           "-show_entries",
           "stream=codec_name,width,height,pix_fmt,r_frame_rate,nb_read_frames:format=duration",
           "-of", "json", str(video)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=config.FFMPEG_TIMEOUT_S)
    if proc.returncode != 0:
        raise EncodeError(f"ffprobe exited {proc.returncode}: {proc.stderr.strip()[-800:]}")
    data = json.loads(proc.stdout)
    if not data.get("streams"):
        raise EncodeError(f"ffprobe found no video stream in {video}")
    s = data["streams"][0]
    return {"codec": s.get("codec_name"), "width": s.get("width"), "height": s.get("height"),
            "pix_fmt": s.get("pix_fmt"), "fps": float(Fraction(s.get("r_frame_rate", "0/1"))),
            "frames": int(s.get("nb_read_frames", 0)),
            "duration_s": float(data.get("format", {}).get("duration", 0))}


def verify(info: dict, frames: int, width: int, height: int, fps: int) -> list[str]:
    """Empty list means the video is exactly what was rendered."""
    expected = {"codec": "h264", "pix_fmt": "yuv420p", "width": width, "height": height,
                "frames": frames}
    errors = [f"{k}: expected {v}, got {info.get(k)}" for k, v in expected.items()
              if info.get(k) != v]
    if abs(info.get("fps", 0) - fps) > 0.01:
        errors.append(f"fps: expected {fps}, got {info.get('fps')}")
    return errors
