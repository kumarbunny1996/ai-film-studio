"""
EditList — the contract for assembling independently rendered scenes into one film (M9).

An edit list names approved scene deliverables (MP4s written by workers/run_milestone1.py) in
film order, pins each one by SHA-256 and frame count, and states the video format every clip
must already have. Assembly copies the video streams; it never converts. It is validated twice:
  1. Structurally, by these Pydantic models (no filesystem access).
  2. Against the filesystem, by `validate_sources()`: every source must be an existing regular
     file whose real path (symlinks and junctions resolved) stays inside storage/projects/.
The assembler (Gate 2) adds the checks that need the media: SHA-256, the clip's summary.json
and ffprobe properties.

Versions:
  1.0  whole clips in order; one video stream each, no audio; format h264 / yuv420p.

The film is written to storage/projects/<film_id>/<film_id>.mp4, a path derived from film_id
and never taken from the edit list; no clip may come from that folder.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EDIT_VERSION = "1.0"
STORAGE_ROOT = "storage/projects"

Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,47}$")]

# A relative POSIX path under storage/projects/ ending in .mp4. Each segment starts with a
# letter, digit or underscore and does not end with a dot, so "", ".", "..", hidden names and
# names Windows would silently alias (trailing dots) cannot appear; backslashes, colons (drive
# letters, alternate data streams), spaces and absolute paths are outside the character set.
_SEGMENT = r"[A-Za-z0-9_](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9_-])?"
SOURCE_PATTERN = rf"^storage/projects/(?:{_SEGMENT}/)+{_SEGMENT}\.mp4$"
SourcePath = Annotated[str, Field(pattern=SOURCE_PATTERN, max_length=240)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

# Device names Windows resolves anywhere in a path, whatever the extension (Pydantic only).
_RESERVED = re.compile(r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$", re.IGNORECASE)


class Strict(BaseModel):
    """Reject unknown keys and non-finite numbers, as SceneSpec does, and never coerce types
    ("576" or true is not a frame count), so the model accepts exactly what the schema does."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class VideoFormat(Strict):
    """The format every clip must already have; assembly never converts."""
    codec: Literal["h264"] = Field(description="ffprobe codec_name")
    pix_fmt: Literal["yuv420p"]
    width: int = Field(ge=16, le=7680)
    height: int = Field(ge=16, le=4320)
    fps: Literal[24, 25, 30] = Field(description="constant frame rate; ffprobe r_frame_rate N/1")
    audio: Literal["none"] = Field(description="1.0: clips must have no audio stream")


class Clip(Strict):
    clip_id: Identifier
    source: SourcePath = Field(description="relative POSIX path under storage/projects/")
    sha256: Sha256 = Field(description="SHA-256 of the source file, lowercase hex")
    frames: int = Field(ge=1, le=24 * 60 * 60, description="decoded video frames in the clip")

    @field_validator("source")
    @classmethod
    def _no_device_names(cls, v: str) -> str:
        bad = [seg for seg in v.split("/") if _RESERVED.match(seg)]
        if bad:
            raise ValueError(f"source uses a Windows device name: {bad[0]!r}")
        return v


class EditList(Strict):
    edit_version: Literal["1.0"]
    film_id: Identifier = Field(description="output: storage/projects/<film_id>/<film_id>.mp4")
    format: VideoFormat
    clips: list[Clip] = Field(min_length=1, max_length=1000, description="in film order")

    @model_validator(mode="after")
    def _clips(self) -> "EditList":
        seen: set[str] = set()
        for c in self.clips:
            if c.clip_id in seen:
                raise ValueError(f"duplicate clip_id '{c.clip_id}'")
            seen.add(c.clip_id)
        out_dir = f"{STORAGE_ROOT}/{self.film_id}/".lower()
        inside = [c.clip_id for c in self.clips if c.source.lower().startswith(out_dir)]
        if inside:
            raise ValueError(f"clips {inside} come from the film's own output folder "
                             f"{out_dir}; assembly writes there")
        return self

    def output_path(self) -> str:
        return f"{STORAGE_ROOT}/{self.film_id}/{self.film_id}.mp4"


def validate_sources(edit: EditList, repo_root: Path) -> list[str]:
    """Filesystem checks; empty list means every source is an existing regular file whose
    real path (symlinks and junctions resolved) is inside <repo_root>/storage/projects."""
    errors: list[str] = []
    storage = (repo_root / STORAGE_ROOT).resolve()
    for c in edit.clips:
        path = repo_root / c.source
        where = f"clips[{c.clip_id}]"
        try:
            real = path.resolve(strict=True)
        except (FileNotFoundError, OSError):
            errors.append(f"{where}: source not found: {c.source}")
            continue
        if not real.is_relative_to(storage):
            errors.append(f"{where}: source resolves outside {STORAGE_ROOT}/ "
                          f"(symlink or junction escape): {c.source}")
        elif not real.is_file():
            errors.append(f"{where}: source is not a regular file: {c.source}")
    return errors


if __name__ == "__main__":
    # Export JSON Schema: python -m apps.api.schemas.edit_list > schemas/edit_list.schema.json
    import json
    print(json.dumps(EditList.model_json_schema(), indent=2))
