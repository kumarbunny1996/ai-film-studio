"""
SceneSpec — the contract between the LLM planning stages and Blender.

The LLM fills this structure (one SceneSpec per shot). It is validated twice:
  1. Structurally, by these Pydantic models.
  2. Against the asset library, by `validate_against_manifest()`.
Any error messages are fed back to the LLM for a retry.

Blender never sees anything that has not passed both checks.
"""
from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SPEC_VERSION = "1.0"

# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------
Vec3 = Annotated[list[float], Field(min_length=3, max_length=3)]
Frame = Annotated[int, Field(ge=1)]
Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,47}$")]


class Strict(BaseModel):
    """Reject unknown keys so LLM hallucinated fields fail loudly."""
    model_config = ConfigDict(extra="forbid", frozen=False)


class Easing(str, Enum):
    linear = "linear"
    ease_in_out = "ease_in_out"
    constant = "constant"


class Transform(Strict):
    location: Vec3 = [0.0, 0.0, 0.0]           # metres, Blender Z-up
    rotation_deg: Vec3 = [0.0, 0.0, 0.0]       # XYZ Euler, degrees
    scale: float = Field(1.0, gt=0, le=100)


class TransformKey(Strict):
    """A keyframe on an object's root (used for travel across the set)."""
    frame: Frame
    location: Vec3
    rotation_z_deg: float | None = None        # heading; None = keep previous
    easing: Easing = Easing.ease_in_out        # interpolation from this key to the next


# ---------------------------------------------------------------------------
# Render settings
# ---------------------------------------------------------------------------
class RenderQuality(str, Enum):
    animatic = "animatic"   # Eevee, half res, low samples — fast approval pass
    final = "final"         # engine/samples as configured


class RenderSettings(Strict):
    quality: RenderQuality = RenderQuality.animatic
    engine: Literal["eevee", "cycles"] = "eevee"
    resolution: tuple[int, int] = (1920, 1080)
    fps: Literal[24, 25, 30] = 24
    frame_start: Frame = 1
    frame_end: Frame = 120
    samples: int = Field(64, ge=1, le=4096)
    motion_blur: bool = True
    seed: int = 0

    @model_validator(mode="after")
    def _frames(self) -> "RenderSettings":
        if self.frame_end <= self.frame_start:
            raise ValueError("render.frame_end must be greater than render.frame_start")
        if self.frame_end - self.frame_start > 24 * 60:
            raise ValueError("a single shot may not exceed 60 seconds; split it")
        w, h = self.resolution
        if not (320 <= w <= 7680 and 240 <= h <= 4320):
            raise ValueError("render.resolution out of range")
        return self


# ---------------------------------------------------------------------------
# World / environment / lighting
# ---------------------------------------------------------------------------
class Environment(Strict):
    asset_id: Identifier | None = None         # set geometry (mountain meadow, forest…)
    hdri_id: Identifier | None = None          # sky / ambient light
    hdri_strength: float = Field(1.0, ge=0, le=20)
    hdri_rotation_deg: float = 0.0
    fog_density: float = Field(0.0, ge=0, le=1)  # world volume scatter

    @model_validator(mode="after")
    def _something(self) -> "Environment":
        if not self.asset_id and not self.hdri_id:
            raise ValueError("environment needs at least an asset_id or an hdri_id")
        return self


class LightingPreset(str, Enum):
    golden_hour = "golden_hour"
    overcast = "overcast"
    midday = "midday"
    blue_hour = "blue_hour"
    night = "night"


class Lighting(Strict):
    preset: LightingPreset = LightingPreset.golden_hour
    sun_elevation_deg: float | None = Field(None, ge=-10, le=90)  # override preset
    sun_azimuth_deg: float | None = Field(None, ge=0, lt=360)
    sun_strength: float | None = Field(None, ge=0, le=20)
    exposure: float = Field(0.0, ge=-5, le=5)


# ---------------------------------------------------------------------------
# Characters & props
# ---------------------------------------------------------------------------
class ActionClip(Strict):
    """An action from the action library placed on the NLA timeline."""
    action_id: Identifier                      # e.g. "walk_cycle", "idle_breathe"
    start_frame: Frame
    end_frame: Frame                           # clip is looped/stretched to fill
    speed: float = Field(1.0, gt=0.1, le=4)
    # Frames of crossfade FROM the previous clip into this one. Later clips sit on
    # higher NLA tracks, so overlap a clip's start with the previous clip's end.
    blend_in: int = Field(6, ge=0, le=48)

    @model_validator(mode="after")
    def _range(self) -> "ActionClip":
        if self.end_frame <= self.start_frame:
            raise ValueError(f"action '{self.action_id}': end_frame must be after start_frame")
        return self


class CharacterInstance(Strict):
    name: Identifier                           # unique in this shot, e.g. "girl"
    asset_id: Identifier                       # entry in assets/manifest.json
    transform: Transform = Transform()
    motion_path: list[TransformKey] = []       # root travel; empty = stays put
    actions: list[ActionClip] = Field(..., min_length=1)

    @field_validator("motion_path")
    @classmethod
    def _sorted(cls, v: list[TransformKey]) -> list[TransformKey]:
        frames = [k.frame for k in v]
        if frames != sorted(frames) or len(set(frames)) != len(frames):
            raise ValueError("motion_path keys must have unique, ascending frames")
        return v


class PropInstance(Strict):
    name: Identifier
    asset_id: Identifier
    transform: Transform = Transform()
    parent: Identifier | None = None           # attach to a character instance
    parent_bone: str | None = None             # e.g. "hand.R" — requires parent


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------
class ShotSize(str, Enum):
    extreme_wide = "extreme_wide"
    wide = "wide"
    medium = "medium"
    close_up = "close_up"
    extreme_close_up = "extreme_close_up"


class CameraKey(Strict):
    frame: Frame
    location: Vec3
    rotation_deg: Vec3 | None = None           # ignored when camera.look_at is set
    lens_mm: float | None = Field(None, ge=8, le=300)  # animate focal length (zoom)
    easing: Easing = Easing.ease_in_out


class Camera(Strict):
    shot_size: ShotSize = ShotSize.medium      # informational; used by planners/QA
    lens_mm: float = Field(35, ge=8, le=300)
    look_at: Identifier | None = None          # character/prop name to track
    look_at_height: float = Field(1.3, ge=0, le=10)  # aim offset above target root (m)
    keys: list[CameraKey] = Field(..., min_length=1)
    dof_enabled: bool = True
    focus_target: Identifier | None = None     # defaults to look_at
    fstop: float = Field(2.8, ge=0.5, le=32)
    handheld_shake: float = Field(0.0, ge=0, le=1)

    @field_validator("keys")
    @classmethod
    def _sorted(cls, v: list[CameraKey]) -> list[CameraKey]:
        frames = [k.frame for k in v]
        if frames != sorted(frames) or len(set(frames)) != len(frames):
            raise ValueError("camera.keys must have unique, ascending frames")
        return v

    @model_validator(mode="after")
    def _rotation(self) -> "Camera":
        if self.look_at is None and any(k.rotation_deg is None for k in self.keys):
            raise ValueError("camera keys need rotation_deg when camera.look_at is not set")
        return self


# ---------------------------------------------------------------------------
# The SceneSpec
# ---------------------------------------------------------------------------
class SceneSpec(Strict):
    spec_version: Literal["1.0"] = SPEC_VERSION
    project_id: str
    scene_id: Identifier                       # e.g. "sc03"
    shot_id: Identifier                        # e.g. "sc03_sh02"
    description: str = Field(..., max_length=600)   # human-readable intent of the shot
    style_template: Identifier = "spring_style"     # blender/templates/<id>.blend
    render: RenderSettings = RenderSettings()
    environment: Environment
    lighting: Lighting = Lighting()
    characters: list[CharacterInstance] = []
    props: list[PropInstance] = []
    camera: Camera

    @model_validator(mode="after")
    def _cross_checks(self) -> "SceneSpec":
        fs, fe = self.render.frame_start, self.render.frame_end
        names = [c.name for c in self.characters] + [p.name for p in self.props]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"instance names must be unique; duplicated: {sorted(dupes)}")
        known = set(names)
        char_names = {c.name for c in self.characters}

        def in_range(f: int, where: str) -> None:
            if not fs <= f <= fe:
                raise ValueError(f"{where}: frame {f} outside shot range {fs}-{fe}")

        for c in self.characters:
            for k in c.motion_path:
                in_range(k.frame, f"characters[{c.name}].motion_path")
            for a in c.actions:
                in_range(a.start_frame, f"characters[{c.name}].actions[{a.action_id}]")
                in_range(a.end_frame, f"characters[{c.name}].actions[{a.action_id}]")
            first = min(a.start_frame for a in c.actions)
            if first > fs:
                raise ValueError(
                    f"character '{c.name}' has no action at frame {fs}; "
                    "add an idle clip so it never T-poses")

        for p in self.props:
            if p.parent and p.parent not in char_names:
                raise ValueError(f"prop '{p.name}' parent '{p.parent}' is not a character")
            if p.parent_bone and not p.parent:
                raise ValueError(f"prop '{p.name}' has parent_bone but no parent")

        for k in self.camera.keys:
            in_range(k.frame, "camera.keys")
        for ref, label in ((self.camera.look_at, "look_at"),
                           (self.camera.focus_target, "focus_target")):
            if ref and ref not in known:
                raise ValueError(f"camera.{label} '{ref}' is not a character or prop in this shot")
        return self


# ---------------------------------------------------------------------------
# Asset manifest + library validation
# ---------------------------------------------------------------------------
class AssetType(str, Enum):
    character = "character"
    prop = "prop"
    environment = "environment"
    hdri = "hdri"


class AssetEntry(Strict):
    id: Identifier
    type: AssetType
    file: str                                  # path relative to assets/
    collection: str | None = None              # collection to append (not for hdri)
    armature: str | None = None                # characters only
    rig_type: str | None = None                # e.g. "rigify_human", "quadruped_v1"
    bones: list[str] = []                      # sockets props may attach to
    license: str
    notes: str = ""


class ActionEntry(Strict):
    id: Identifier
    file: str                                  # .blend in assets/ containing the action
    action_name: str                           # name inside that file
    rig_type: str                              # only valid on matching rigs
    frames: int = Field(..., ge=1)             # source length (for looping maths)
    loopable: bool = False


class AssetManifest(Strict):
    assets: list[AssetEntry]
    actions: list[ActionEntry]

    def asset(self, asset_id: str) -> AssetEntry | None:
        return next((a for a in self.assets if a.id == asset_id), None)

    def action(self, action_id: str) -> ActionEntry | None:
        return next((a for a in self.actions if a.id == action_id), None)


def validate_against_manifest(spec: SceneSpec, manifest: AssetManifest) -> list[str]:
    """Return human/LLM-readable errors. Empty list means the shot is buildable."""
    errors: list[str] = []

    def need(asset_id: str | None, kind: AssetType, where: str) -> AssetEntry | None:
        if asset_id is None:
            return None
        entry = manifest.asset(asset_id)
        if entry is None:
            valid = sorted(a.id for a in manifest.assets if a.type == kind)
            errors.append(f"{where}: unknown {kind.value} '{asset_id}'. Valid: {valid}")
        elif entry.type != kind:
            errors.append(f"{where}: '{asset_id}' is a {entry.type.value}, not a {kind.value}")
            return None
        return entry

    need(spec.environment.asset_id, AssetType.environment, "environment.asset_id")
    need(spec.environment.hdri_id, AssetType.hdri, "environment.hdri_id")

    rigs: dict[str, AssetEntry] = {}
    for c in spec.characters:
        entry = need(c.asset_id, AssetType.character, f"characters[{c.name}]")
        if not entry:
            continue
        rigs[c.name] = entry
        for clip in c.actions:
            act = manifest.action(clip.action_id)
            if act is None:
                valid = sorted(a.id for a in manifest.actions if a.rig_type == entry.rig_type)
                errors.append(f"characters[{c.name}]: unknown action '{clip.action_id}'. "
                              f"Valid for this rig: {valid}")
            elif act.rig_type != entry.rig_type:
                errors.append(f"characters[{c.name}]: action '{clip.action_id}' is for rig "
                              f"'{act.rig_type}', character uses '{entry.rig_type}'")
            elif not act.loopable and (clip.end_frame - clip.start_frame) * clip.speed > act.frames * 1.5:
                errors.append(f"characters[{c.name}]: action '{clip.action_id}' is not loopable "
                              f"({act.frames} frames) but the clip asks for "
                              f"{clip.end_frame - clip.start_frame} frames")

    for p in spec.props:
        need(p.asset_id, AssetType.prop, f"props[{p.name}]")
        if p.parent_bone and p.parent in rigs and p.parent_bone not in rigs[p.parent].bones:
            errors.append(f"props[{p.name}]: bone '{p.parent_bone}' not exposed on "
                          f"'{rigs[p.parent].id}'. Valid: {rigs[p.parent].bones}")
    return errors


if __name__ == "__main__":
    # Export JSON Schema for the LLM prompt / frontend: python -m apps.api.schemas.scene_spec
    import json
    print(json.dumps(SceneSpec.model_json_schema(), indent=2))
