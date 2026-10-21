"""scan_masks.py - read-only scan of every rendered mask (no angles printed).

    blender -b --factory-startup --python-exit-code 1 -P scan_masks.py -- <evidence_dir> <assignments.json>

Every pixel of every normal and unoccluded mask must be exactly one of the expected labels:
    normal mask: black, red (marker), green (head), blue (D3 nose)
    unoccluded:  black, red, blue (head and body hidden, so no green)
and per design: D0 has no red or blue; D1 and D2 have no blue; every normal mask shows green;
every unoccluded mask shows red. Writes <evidence_dir>/mask_scan.json; prints totals and the
ids of any failing file only.

rev4: append `rev4` after the two paths. Variants A-D all carry a nose (blue allowed), there is
no D0, and only 320 masks exist: 56 normal + 56 unoccluded = 112 files.
"""
import json
import sys
from pathlib import Path

import bpy
import numpy as np

SIZES = {"320": (320, 180), "640": (640, 360)}
LABELS = {"black": (0, 0, 0), "red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255)}


def load(path: Path):
    img = bpy.data.images.load(str(path))
    img.colorspace_settings.name = "Non-Color"
    w, h = img.size
    px = np.round(np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)[..., :3] * 255).astype(np.int32)
    bpy.data.images.remove(img)
    return (w, h), px


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1:]
    evidence, assignments = Path(argv[0]), Path(argv[1])
    rev4 = len(argv) > 2 and argv[2] == "rev4"
    sizes, expected = ({"320": SIZES["320"]}, 112) if rev4 else (SIZES, 196)
    design = {s["id"]: s["design"] for s in json.loads(assignments.read_text())["stills"]}
    rows, fails = [], []
    totals = {"files": 0, "stray_dark": 0, "unlabelled": 0}
    for kind in ("masks", "masks_raw"):
        for res, size in sizes.items():
            for path in sorted((evidence / kind / res).glob("*.png")):
                sid = path.stem
                d = design[sid]
                got, px = load(path)
                counts = {k: int((px == np.array(v)).all(axis=2).sum()) for k, v in LABELS.items()}
                n = px.shape[0] * px.shape[1]
                unlabelled = n - sum(counts.values())
                mx = px.max(axis=2)
                stray = int(((mx > 0) & (mx <= 4)).sum())
                allowed = {"black", "red", "green", "blue"} if kind == "masks" else {"black", "red", "blue"}
                if rev4 and d not in ("A", "B", "C", "D"):
                    problems_design = [f"unknown rev4 design {d}"]
                else:
                    problems_design = []
                if kind == "masks" and d == "D0":
                    allowed -= {"red", "blue"}
                if d in ("D1", "D2"):
                    allowed -= {"blue"}
                problems = problems_design
                if got != size:
                    problems.append(f"size {got}")
                if stray:
                    problems.append("stray dark pixels")
                if unlabelled:
                    problems.append("unlabelled pixels")
                problems += [f"unexpected {k}" for k, c in counts.items() if c and k not in allowed]
                if kind == "masks" and counts["green"] == 0:
                    problems.append("no head label")
                if kind == "masks_raw" and counts["red"] == 0:
                    problems.append("no marker label")
                if kind == "masks_raw" and d == "D0":
                    problems.append("D0 should have no unoccluded mask")
                totals["files"] += 1
                totals["stray_dark"] += stray
                totals["unlabelled"] += unlabelled
                rows.append({"kind": kind, "res": res, "id": sid, "design": d, "counts": counts,
                             "stray_dark": stray, "unlabelled": unlabelled, "problems": problems})
                if problems:
                    fails.append(f"{kind}/{res}/{sid}: {problems}")
    per_group = {}
    for r in rows:
        key = f"{r['kind']}/{r['res']}"
        per_group[key] = per_group.get(key, 0) + 1
    (evidence / "mask_scan.json").write_text(json.dumps(
        {"totals": totals, "files_per_group": per_group, "failures": fails, "rows": rows}, indent=1))
    print(f"[scan_masks] files per group: {per_group}")
    print(f"[scan_masks] totals: {totals}")
    print(f"[scan_masks] failing files: {len(fails)} {fails[:10]}")
    return 0 if not fails and totals["files"] == expected else 1


if __name__ == "__main__":
    sys.exit(main())
