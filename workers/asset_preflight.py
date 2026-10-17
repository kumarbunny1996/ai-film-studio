"""Asset manifest preflight: files that are missing on disk, and duplicate ids.

    uv run python -m workers.asset_preflight                  # the whole manifest
    uv run python -m workers.asset_preflight --spec <spec>    # only the files a spec uses

validate_against_manifest() checks a SceneSpec against the manifest's *entries*; it never
looks at the disk. This module checks the entries against the disk, so a manifest entry whose
file was never made (or a typo in a path) is found before Blender runs instead of as a
"asset file missing" spec_error from build_scene.py. It is standalone: run_shot() does not
call it yet, and validation semantics are unchanged.

AssetManifest.asset()/action() return the first entry with an id, so a duplicate id silently
shadows the later entry; this reports it.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from apps.api.schemas.scene_spec import AssetManifest, SceneSpec
from workers.blender_job import ASSETS


def _duplicates(ids: list[str]) -> list[str]:
    return sorted({i for i in ids if ids.count(i) > 1})


def referenced_files(spec: SceneSpec, manifest: AssetManifest) -> dict[str, list[str]]:
    """manifest file -> the asset/action ids in `spec` that need it. Ids that are not in the
    manifest are skipped: validate_against_manifest() reports those."""
    used: dict[str, list[str]] = {}

    def add(entry) -> None:
        if entry is not None:
            used.setdefault(entry.file, []).append(entry.id)

    env = spec.environment
    for asset_id in (env.asset_id, env.hdri_id):
        if asset_id:
            add(manifest.asset(asset_id))
    for c in spec.characters:
        add(manifest.asset(c.asset_id))
        for clip in c.actions:
            add(manifest.action(clip.action_id))
    for p in spec.props:
        add(manifest.asset(p.asset_id))
    return {f: sorted(set(ids)) for f, ids in used.items()}


def manifest_problems(manifest: AssetManifest, assets_root: Path = ASSETS,
                      spec: SceneSpec | None = None) -> list[str]:
    """Human-readable problems; [] means every checked file exists and ids are unique.

    With `spec`, only the files that spec references are checked for existence (duplicate
    ids are always reported, since they change what any spec resolves to)."""
    problems = []
    for kind, ids in (("asset", [a.id for a in manifest.assets]),
                      ("action", [a.id for a in manifest.actions])):
        for dup in _duplicates(ids):
            problems.append(f"duplicate {kind} id '{dup}': only the first entry is used")

    if spec is None:
        files: dict[str, list[str]] = {}
        for entry in [*manifest.assets, *manifest.actions]:
            files.setdefault(entry.file, []).append(entry.id)
    else:
        files = referenced_files(spec, manifest)

    root = assets_root.resolve()
    for rel, ids in sorted(files.items()):
        path = (root / rel).resolve()
        if not path.is_relative_to(root):
            problems.append(f"{rel} (used by {', '.join(sorted(set(ids)))}) is outside {root}")
        elif not path.is_file():
            problems.append(f"missing file {rel} (used by {', '.join(sorted(set(ids)))})")
    return problems


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="asset_preflight")
    p.add_argument("--assets-root", type=Path, default=ASSETS)
    p.add_argument("--manifest", type=Path, help="defaults to <assets-root>/manifest.json")
    p.add_argument("--spec", type=Path, help="check only the files this SceneSpec uses")
    args = p.parse_args(argv)
    manifest = AssetManifest.model_validate_json(
        (args.manifest or args.assets_root / "manifest.json").read_text())
    spec = SceneSpec.model_validate(json.loads(args.spec.read_text())) if args.spec else None
    problems = manifest_problems(manifest, args.assets_root, spec)
    for line in problems:
        print(line)
    print(f"{len(problems)} problem(s)", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
