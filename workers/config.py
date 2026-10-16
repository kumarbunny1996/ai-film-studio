"""Tool locations and resource limits. Every value can be overridden by an env var."""
from __future__ import annotations

import os
import sys

_DEFAULT_BLENDER = (r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
                    if sys.platform == "win32" else "blender")

BLENDER_BIN = os.environ.get("BLENDER_BIN", _DEFAULT_BLENDER)
FFMPEG_BIN = os.environ.get("FFMPEG_BIN", "ffmpeg")
FFPROBE_BIN = os.environ.get("FFPROBE_BIN", "ffprobe")

# Render threads. 4 of 12 keeps this 8 GB laptop responsive and memory peaks down.
BLENDER_THREADS = int(os.environ.get("BLENDER_THREADS", 4))
BLENDER_TIMEOUT_S = int(os.environ.get("BLENDER_TIMEOUT_S", 60 * 60))
FFMPEG_THREADS = int(os.environ.get("FFMPEG_THREADS", 4))
FFMPEG_TIMEOUT_S = int(os.environ.get("FFMPEG_TIMEOUT_S", 10 * 60))
