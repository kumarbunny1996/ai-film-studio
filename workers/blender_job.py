"""Worker-side helper: validate a SceneSpec, then run Blender headless on it.

Usage from an arq/RQ job:
    result = run_shot(spec_dict, project_dir=Path("storage/projects/demo"))
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from apps.api.schemas.scene_spec import AssetManifest, SceneSpec, validate_against_manifest

REPO = Path(__file__).resolve().parents[1]
BLENDER = os.environ.get("BLENDER_BIN", "blender")
ASSETS = REPO / "assets"
TIMEOUT_S = int(os.environ.get("BLENDER_TIMEOUT_S", 60 * 60))


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


def run_shot(spec_dict: dict, project_dir: Path, render: bool = True) -> dict:
    spec = validate(spec_dict)
    shot_dir = project_dir / "shots" / spec.shot_id
    shot_dir.mkdir(parents=True, exist_ok=True)
    spec_path = shot_dir / "spec.json"
    spec_path.write_text(spec.model_dump_json(indent=2))

    template = REPO / "blender" / "templates" / f"{spec.style_template}.blend"
    cmd = [BLENDER, "-b"]
    if template.exists():
        cmd.append(str(template))          # opened read-only in effect: we save elsewhere
    cmd += ["--python-exit-code", "1",
            "-P", str(REPO / "blender" / "scripts" / "build_scene.py"), "--",
            "--spec", str(spec_path), "--assets-root", str(ASSETS), "--out", str(shot_dir)]
    if not render:
        cmd.append("--no-render")

    log_path = shot_dir / "blender.log"
    with log_path.open("w") as log:
        proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, timeout=TIMEOUT_S)

    report_path = shot_dir / "build_report.json"
    report = json.loads(report_path.read_text()) if report_path.exists() else {
        "status": "crash", "error": f"Blender exited {proc.returncode} without a report"}
    report["returncode"], report["log"] = proc.returncode, str(log_path)
    return report
