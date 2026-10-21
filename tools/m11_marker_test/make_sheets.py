"""
make_sheets.py - M11 Gate 2 review sheets and scoring (scratch tool, not part of the repo).

Phase A (blind; nothing that names an angle):
    python make_sheets.py --repo <repo> --out <marker_test_rev1> --private <dir> --blind
        -> <out>/blind/blind_320_p1..p4.png, <out>/blind/answer_form.csv
Phase B (only after the answer form(s) are filled in):
    python make_sheets.py --repo <repo> --out <marker_test_rev1> --private <dir> --reveal \
        --answers <filled.csv> [--answers <second_reviewer.csv>]
        -> copies the private records into <out>, builds the comparison sheets, writes scores.json

Never overwrites: every output path must not exist yet.

rev4 (--design-set rev4): K01-K56, variants A-D, 320 only. --reveal needs exactly two filled
forms (the two rev3 reviewers), refuses forms with missing rows or unknown answers, and adds
an explicit score table plus the pre-registered screening decision to scores.json.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
import subprocess
import sys
from pathlib import Path

BINS = ["T", "TR", "R", "AR", "A", "AL", "L", "TL"]
TRUTH = {0: "T", 40: "TR", 90: "R", 140: "AR", -40: "TL", -90: "L", -140: "AL"}
PASS = {"med": 6.5, "wide": 5.5}
PER_PAGE, COLS = 14, 2
DESIGN_SETS = {"rev3": {"designs": ("D0", "D1", "D2", "D3"), "res": ("320", "640"), "prefix": "S"},
               "rev4": {"designs": ("A", "B", "C", "D"), "res": ("320",), "prefix": "K"}}
# rev4 screening (approved 2026-10-21): a candidate is recommended for expansion only if both
# reviewers pass it on both colours at medium and wide; total score, then fewer three-quarter
# -> profile errors, then simplicity (this order) only rank candidates that pass.
CANDIDATES, BASELINE = ("B", "C", "D"), "A"
THREE_QUARTER, PROFILE = {"TL", "TR"}, {"L", "R"}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="make_sheets.py")
    p.add_argument("--repo", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--private", required=True, type=Path)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--blind", action="store_true")
    mode.add_argument("--reveal", action="store_true")
    p.add_argument("--answers", type=Path, action="append", default=[])
    p.add_argument("--design-set", choices=sorted(DESIGN_SETS), default="rev3")
    p.add_argument("--evidence", type=Path,
                   help="folder with the run's private masks, masks_raw, diagnostics.json, "
                        "experiment.json and preflight_full.json (default: --private)")
    return p.parse_args()


def ffmpeg(repo: Path, args: list[str]) -> None:
    sys.path.insert(0, str(repo))
    from workers import config
    cmd = [config.FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-n", *args]
    subprocess.run(cmd, check=True)


def font(repo: Path) -> str | None:
    sys.path.insert(0, str(repo))
    from workers import config
    from workers.contact_sheet import _font_arg
    return _font_arg(Path(config.FFMPEG_FONTFILE))


def grid(repo: Path, tiles: list[tuple[Path, str]], cols: int, scale: int, out: Path) -> None:
    """Tiles (image, label) scaled by `scale` with hard pixel edges, labelled, in a grid."""
    f = font(repo)
    args, chains = [], []
    for i, (img, label) in enumerate(tiles):
        args += ["-i", str(img)]
        chain = f"[{i}:v]scale=iw*{scale}:ih*{scale}:flags=neighbor"
        if f and label:
            text = label.replace(":", r"\:")
            chain += (f",drawtext=fontfile='{f}':text='{text}':x=6:y=6:fontsize=20:"
                      "fontcolor=white:box=1:boxcolor=black@0.6")
        chains.append(chain + f"[t{i}]")
    n = len(tiles)
    rows = -(-n // cols)
    # xstack layout with explicit offsets built from the first tile's size
    layout = "|".join(("+".join(["w0"] * (i % cols)) or "0") + "_" +
                      ("+".join(["h0"] * (i // cols)) or "0") for i in range(n))
    inputs = "".join(f"[t{i}]" for i in range(n))
    fill = ":fill=black" if rows * cols != n else ""
    fc = ";".join(chains) + f";{inputs}xstack=inputs={n}:layout={layout}{fill}[out]"
    out.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg(repo, [*args, "-filter_complex", fc, "-map", "[out]", "-frames:v", "1", str(out)])


def page_order(a: dict) -> list[list[str]]:
    """Each (camera, slot) pose appears once per design; its four versions go to four
    different pages, in random page and position order (secret seed, nothing exposed)."""
    rng = random.Random(a["seed"] + 1)
    pages: list[list[str]] = [[] for _ in range(4)]
    groups: dict[tuple, list[str]] = {}
    for s in a["stills"]:
        groups.setdefault((s["cam"], s["slot"]), []).append(s["id"])
    for key in sorted(groups):
        ids = groups[key][:]
        rng.shuffle(ids)
        for page, sid in zip(pages, ids):
            page.append(sid)
    for page in pages:
        rng.shuffle(page)
    return pages


def blind(repo: Path, out: Path, private: Path, ds: dict) -> int:
    dest = out / "blind"
    if dest.exists():
        print(f"[make_sheets] REFUSED: {dest} exists", file=sys.stderr)
        return 2
    if ds["prefix"] == "K":
        rc = private / "rear_cue_mask_check.json"
        if not rc.exists() or json.loads(rc.read_text()).get("status") != "pass":
            print("[make_sheets] REFUSED: no passing rear_cue_mask_check.json for rev4", file=sys.stderr)
            return 2
    pages = page_order(json.loads((private / "assignments.json").read_text()))
    ids = [i for page in pages for i in page]
    pre = ds["prefix"]
    if sorted(ids) != [f"{pre}{k:02d}" for k in range(1, 57)] or any(len(p) != PER_PAGE for p in pages):
        print(f"[make_sheets] REFUSED: page order is not a partition of {pre}01-{pre}56", file=sys.stderr)
        return 2
    missing = [i for i in ids if not (out / "stills" / "320" / f"{i}.png").exists()]
    if missing:
        print(f"[make_sheets] REFUSED: missing stills {missing[:5]}", file=sys.stderr)
        return 2
    for n, page in enumerate(pages, 1):
        grid(repo, [(out / "stills" / "320" / f"{i}.png", i) for i in page], COLS, 2,
             dest / f"blind_320_p{n}.png")
    with open(dest / "answer_form.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["page", "still", "left_character", "right_character"])
        for n, page in enumerate(pages, 1):
            for i in page:
                w.writerow([n, i, "", ""])
    print(f"[make_sheets] wrote 4 blind pages and the answer form to {dest}")
    return 0


def score(a: dict, answers: Path, truth_map: dict = TRUTH) -> dict:
    """truth_map: angle -> label. The default is the screen-direction map used by rev1-rev4;
    review rounds may pass a pre-registered map (scoring by bin distance is unchanged)."""
    rows = {r["still"].strip(): r for r in csv.DictReader(open(answers, newline=""))}
    cells: dict[str, dict] = {}
    for s in a["stills"]:
        for col, field in (("grey", "left_character"), ("ochre", "right_character")):
            ans = (rows.get(s["id"], {}).get(field) or "").strip().upper()
            truth = truth_map[s[col]]
            if ans in BINS:
                d = abs(BINS.index(ans) - BINS.index(truth))
                pts = 1.0 if d == 0 else 0.5 if min(d, 8 - d) == 1 else 0.0
            else:
                pts = 0.0
            key = f"{s['design']}/{s['cam']}/{col}"
            c = cells.setdefault(key, {"points": 0.0, "exact": 0, "n": 0, "answers": []})
            c["points"] += pts
            c["exact"] += pts == 1.0
            c["n"] += 1
            c["answers"].append({"id": s["id"], "truth": truth, "answer": ans or "?"})
    for key, c in cells.items():
        c["complete_set"] = sorted(x["answer"] for x in c["answers"]) == sorted(truth_map.values())
    designs = sorted({k.split("/")[0] for k in cells})
    summary = {}
    for d in designs:
        g = {f"{cam}/{col}": cells[f"{d}/{cam}/{col}"]["points"]
             for cam in ("med", "wide") for col in ("grey", "ochre")}
        summary[d] = {"scores": g, "eligible": min(g["med/grey"], g["med/ochre"]) >= PASS["med"],
                      "wide_pass": min(g["wide/grey"], g["wide/ochre"]) >= PASS["wide"]}
    d0 = summary.get("D0", {}).get("scores", {})
    review = bool(d0) and (any(d0.get(f"med/{c}", 0) >= PASS["med"] for c in ("grey", "ochre")) or any(
        min(d0[f"med/{c}"] for c in ("grey", "ochre")) >= min(
            summary[d]["scores"][f"med/{c}"] for c in ("grey", "ochre")) for d in designs if d != "D0"))
    return {"answers_file": answers.name, "cells": cells, "summary": summary,
            "d0_test_design_review": review, "d0_above_body_only": {
                k: v > 3.5 for k, v in d0.items()}}


def check_form(a: dict, answers: Path) -> list[str]:
    """Missing or unknown rows and answers outside the 8 bins, '?' or blank (no truths shown)."""
    rows = list(csv.DictReader(open(answers, newline="")))
    ids = {s["id"] for s in a["stills"]}
    seen = [r["still"].strip() for r in rows]
    errs = [f"missing row {i}" for i in sorted(ids - set(seen))]
    errs += [f"unknown or repeated row {i}" for i in sorted(set(seen)) if i not in ids or seen.count(i) > 1]
    for r in rows:
        for field in ("left_character", "right_character"):
            ans = (r.get(field) or "").strip().upper()
            if ans not in BINS and ans not in ("", "?"):
                errs.append(f"{r['still'].strip()}/{field}: '{ans}' is not one of {BINS} or '?'")
    return errs


def score_table(scores: dict, designs) -> list[dict]:
    """One row per reviewer x variant x camera x colour. Exact 1, adjacent bin 0.5, other bins 0,
    '?' or blank 0. Pass: medium >= 6.5, wide >= 5.5 (unchanged)."""
    table = []
    for reviewer, sc in scores.items():
        for d in designs:
            for cam in ("med", "wide"):
                for col in ("grey", "ochre"):
                    c = sc["cells"][f"{d}/{cam}/{col}"]
                    kinds = {"exact": 0, "adjacent": 0, "wrong": 0, "unanswered": 0}
                    tq = 0
                    for x in c["answers"]:
                        if x["answer"] not in BINS:
                            kinds["unanswered"] += 1
                            continue
                        dist = abs(BINS.index(x["answer"]) - BINS.index(x["truth"]))
                        kinds["exact" if dist == 0 else "adjacent" if min(dist, 8 - dist) == 1 else "wrong"] += 1
                        tq += x["truth"] in THREE_QUARTER and x["answer"] in PROFILE
                    table.append({"reviewer": reviewer, "variant": d, "camera": cam, "colour": col,
                                  "points": c["points"], "n": c["n"], **kinds,
                                  "three_quarter_as_profile": tq, "threshold": PASS[cam],
                                  "pass": c["points"] >= PASS[cam]})
    return table


def screening_decision(table: list[dict]) -> dict:
    reviewers = sorted({r["reviewer"] for r in table})
    designs = [BASELINE, *CANDIDATES]
    rows = lambda d, rv=None: [r for r in table if r["variant"] == d and rv in (None, r["reviewer"])]
    passed = {d: {rv: all(r["pass"] for r in rows(d, rv)) for rv in reviewers} for d in designs}
    total = {d: sum(r["points"] for r in rows(d)) for d in designs}
    tq = {d: sum(r["three_quarter_as_profile"] for r in rows(d)) for d in designs}
    qualified = [d for d in CANDIDATES if all(passed[d].values())]
    ranking = sorted(qualified, key=lambda d: (-total[d], tq[d], CANDIDATES.index(d)))
    return {
        "rule": "candidate passes only if every reviewer passes it on both colours at medium "
                f"(>= {PASS['med']}) and wide (>= {PASS['wide']}); ranking among passing candidates "
                "only: total points (desc), three-quarter-as-profile errors (asc), simplicity B<C<D",
        "reviewers": reviewers, "pass_by_reviewer": passed, "total_points": total,
        "three_quarter_as_profile": tq, "qualified": qualified, "ranking": ranking,
        "recommended_for_expansion": ranking[0] if ranking else None,
        "baseline_also_passes": all(passed[BASELINE].values()),
        "outcome": ("recommend " + ranking[0] + " for expansion, pending separate approval") if ranking
                   else "no candidate passed; stop and report",
        "authorizes": "nothing: rev5 and Gate 3 need separate approval"}


def reveal(repo: Path, out: Path, private: Path, answers: list[Path], evidence: Path, ds: dict) -> int:
    rev4 = ds["prefix"] == "K"
    if not answers or (rev4 and len(answers) != 2):
        need = "exactly two filled --answers files" if rev4 else "at least one filled --answers file"
        print(f"[make_sheets] REFUSED: --reveal needs {need}", file=sys.stderr)
        return 2
    targets = [out / "masks", out / "masks_raw", out / "diagnostics.json", out / "experiment.json",
               out / "preflight" / "preflight.json", out / "blind" / "answer_key.json",
               out / "sheets", out / "scores.json"]
    clash = [str(p) for p in targets if p.exists()]
    if clash:
        print(f"[make_sheets] REFUSED: exists {clash}", file=sys.stderr)
        return 2
    a = json.loads((private / "assignments.json").read_text())
    if rev4:
        errs = {p.name: check_form(a, p) for p in answers}
        if any(errs.values()):
            print(f"[make_sheets] REFUSED: answer forms need fixing {errs}", file=sys.stderr)
            return 2
    scores = {p.stem: score(a, p) for p in answers}
    shutil.copytree(evidence / "masks", out / "masks")
    shutil.copytree(evidence / "masks_raw", out / "masks_raw")
    for src, dst in (("diagnostics.json", "diagnostics.json"), ("experiment.json", "experiment.json"),
                     ("preflight_full.json", "preflight/preflight.json")):
        shutil.copy2(evidence / src, out / dst)
    shutil.copy2(private / "assignments.json", out / "blind" / "answer_key.json")
    for res in ds["res"]:
        for cam in ("med", "wide"):
            tiles = []
            for d in ds["designs"]:
                group = sorted((s for s in a["stills"] if s["design"] == d and s["cam"] == cam),
                               key=lambda s: s["grey"])
                tiles += [(out / "stills" / res / f"{s['id']}.png",
                           f"{d} {s['id']} g{s['grey']:+d} o{s['ochre']:+d}") for s in group]
            grid(repo, tiles, 7, 1, out / "sheets" / f"compare_{res}_{cam}.png")
    if rev4:
        table = score_table(scores, ds["designs"])
        scores = {**scores, "score_table": table, "screening_decision": screening_decision(table)}
        print(f"[make_sheets] screening: {scores['screening_decision']['outcome']}")
    (out / "scores.json").write_text(json.dumps(scores, indent=1))
    print(f"[make_sheets] revealed; scores for {list(scores)}")
    return 0


def main() -> int:
    args = parse_args()
    repo = args.repo.resolve()
    out = args.out if args.out.is_absolute() else (repo / args.out)
    ds = DESIGN_SETS[args.design_set]
    if args.blind:
        return blind(repo, out, args.private.resolve(), ds)
    evidence = (args.evidence or args.private).resolve()
    return reveal(repo, out, args.private.resolve(), args.answers, evidence, ds)


if __name__ == "__main__":
    sys.exit(main())
