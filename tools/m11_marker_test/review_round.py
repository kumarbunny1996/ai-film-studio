"""
review_round.py - M11 rev4 review round 2: a new blind review of the existing rev4 images (no
new renders). New opaque ids, a new secret seed, a new page order, written instructions with
worked examples, one packet per reviewer, both forms locked before anything is revealed.

    python review_round.py --repo <repo> --prepare --rev4 <rev4 out> --rev3 <rev3 out> \
        --out <round out> --private <dir>
    python review_round.py --repo <repo> --lock --out <round out> --private <dir> \
        --answers <reviewer 1 form> --answers <reviewer 2 form>
    python review_round.py --repo <repo> --reveal --out <round out> --private <dir>

Labels use the character's own (anatomical) left and right, pre-registered 2026-10-21: a head
turned toward the character's own left is TL/L/AL. rev1-rev4 scored screen direction, so the
truth map here is make_sheets.TRUTH mirrored; scoring by bin distance, adjacency and the
thresholds are unchanged. Never overwrites: every output path must not exist yet.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import itertools
import json
import random
import secrets
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_sheets as ms  # noqa: E402

ROUND, OUT_NAME, PREFIX = "rev4_review2", "marker_test_rev4_review2", "Q"
PROTECTED = ("marker_test_rev1", "marker_test_rev2", "marker_test_rev3", "marker_test_rev4",
             "marker_test_rev4_aborted1")
MIRROR = {"T": "T", "TR": "TL", "TL": "TR", "R": "L", "L": "R", "AR": "AL", "AL": "AR", "A": "A"}
ANATOMICAL = {angle: MIRROR[label] for angle, label in ms.TRUTH.items()}
DESIGNS = ("A", "B", "C", "D")
LABELS = ("T", "TL", "TR", "L", "R", "AL", "AR", "?")


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def refuse(msg: str) -> int:
    print(f"[review_round] REFUSED: {msg}", file=sys.stderr)
    return 2


def path_problem(out: Path, private: Path) -> str | None:
    if out.name != OUT_NAME:
        return f"the round writes only to a folder named {OUT_NAME}, not {out.name}"
    if private == out or out in private.parents or private in out.parents:
        return "the private folder must be outside the round output and vice versa"
    if any(q.name in PROTECTED for p in (out, private) for q in (p, *p.parents)):
        return f"output and private folders must not be inside {PROTECTED}"
    return None


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------
def new_assignments(key4: dict, seed: int) -> dict:
    """New opaque ids for the 56 rev4 stills (same images, same poses)."""
    rng = random.Random(seed)
    src = [{k: s[k] for k in ("id", "design", "cam", "slot", "grey", "ochre")} for s in key4["stills"]]
    order = list(range(len(src)))
    rng.shuffle(order)
    stills = []
    for k, idx in enumerate(order):
        s = src[idx]
        stills.append({"id": f"{PREFIX}{k + 1:02d}", "source_id": s["id"],
                       **{f: s[f] for f in ("design", "cam", "slot", "grey", "ochre")}})
    stills.sort(key=lambda s: s["id"])
    a = {"round": ROUND, "seed": seed, "convention": "anatomical", "stills": stills}
    a["pages"] = ms.page_order(a)                      # its own rng, seeded from this seed
    return a


def check_assignments(a: dict, key4: dict) -> list[str]:
    errs = []
    ids = [s["id"] for s in a["stills"]]
    if sorted(ids) != [f"{PREFIX}{k:02d}" for k in range(1, 57)]:
        errs.append("ids are not exactly Q01-Q56")
    if sorted(s["source_id"] for s in a["stills"]) != sorted(s["id"] for s in key4["stills"]):
        errs.append("the new ids are not a one-to-one relabelling of the rev4 stills")
    by_src = {s["id"]: s for s in key4["stills"]}
    if any(any(s[f] != by_src[s["source_id"]][f] for f in ("design", "cam", "slot", "grey", "ochre"))
           for s in a["stills"]):
        errs.append("a relabelled still does not carry its rev4 design and pose")
    for d in DESIGNS:
        for cam in ("med", "wide"):
            for col in ("grey", "ochre"):
                seen = sorted(s[col] for s in a["stills"] if s["design"] == d and s["cam"] == cam)
                if seen != sorted(ms.TRUTH):
                    errs.append(f"{d}/{cam}/{col} does not see all seven angles once")
    pages = a["pages"]
    page_of = {i: n for n, p in enumerate(pages) for i in p}
    if [len(p) for p in pages] != [ms.PER_PAGE] * 4 or sorted(page_of) != sorted(ids):
        errs.append("pages are not four pages of 14 covering every id once")
    for cam in ("med", "wide"):
        for slot in range(7):
            grp = [s["id"] for s in a["stills"] if s["cam"] == cam and s["slot"] == slot]
            if len({page_of[i] for i in grp}) != 4:
                errs.append(f"the four variants of {cam}/slot {slot} are not on four pages")
    return errs


def pick_examples(rev3: Path) -> tuple[list[dict], list[str]]:
    """Two medium and two wide rev3 D1 stills whose eight figures cover all seven angles, plus
    one rev3 D0 (no marker) wide still for '?'. Only id, design, cam, slot and angles are kept
    from rev3's revealed experiment.json."""
    src = rev3 / "experiment.json"
    keep = [{k: s[k] for k in ("id", "design", "cam", "slot", "grey", "ochre")}
            for s in json.loads(src.read_text())["assignments"]["stills"] if s["design"] in ("D0", "D1")]
    d1 = sorted((s for s in keep if s["design"] == "D1"), key=lambda s: (s["cam"], s["slot"]))
    med, wide = [s for s in d1 if s["cam"] == "med"], [s for s in d1 if s["cam"] == "wide"]
    chosen = next(m + w for m in itertools.combinations(med, 2) for w in itertools.combinations(wide, 2)
                  if len({s[c] for s in m + w for c in ("grey", "ochre")}) == 7)
    unknown = min((s for s in keep if s["design"] == "D0" and s["cam"] == "wide"), key=lambda s: s["slot"])
    examples = [{**s, "left": ANATOMICAL[s["grey"]], "right": ANATOMICAL[s["ochre"]]} for s in chosen]
    examples.append({**unknown, "left": "?", "right": "?"})
    return examples, [str(src)]


INSTRUCTIONS = """# Head-direction review - instructions

Thank you for reviewing. Please work alone: do not discuss the images or your answers with
anyone, and use only the files in this packet.

## What you have

- `review_p1.png` to `review_p4.png`: 56 small images, each labelled with an id (Q01 to Q56).
- `examples.png`: five worked examples (not part of the test).
- `{form}`: your answer form.

Each image shows two figures. For each figure, judge **which way its head is facing**.

## Which figure goes in which column

- `left_character`: the figure standing on the **left side of the image**.
- `right_character`: the figure standing on the **right side of the image**.

## The labels: how far the head has turned, toward the figure's OWN left or right

Imagine every figure first stands **facing you** (T). Its head has then turned toward its
**own** left or its **own** right, and the label says which way and how far. Left and right
mean the figure's own body, not the sides of the picture: a figure facing you has its own left
hand on the right side of your screen, so turning toward its own left moves its face toward the
**right of the image**.

Keep counting the turn from the facing-you position, also when the figure ends up facing away:
a figure that kept turning to its own left (AL) shows you the back of its head with its face
pointing away **and to the right of the image**.

| Label | Turn from facing you | What you see on screen |
|---|---|---|
| T  | none | Face toward you. |
| TL | about 40 degrees to its own left | Most of the face; it points slightly to the **right** of the image. |
| TR | about 40 degrees to its own right | Most of the face; it points slightly to the **left** of the image. |
| L  | about 90 degrees to its own left | Side view (profile) looking to the **right** of the image. |
| R  | about 90 degrees to its own right | Side view (profile) looking to the **left** of the image. |
| AL | about 140 degrees to its own left | Mostly the back of the head; the face points away and to the **right** of the image. |
| AR | about 140 degrees to its own right | Mostly the back of the head; the face points away and to the **left** of the image. |
| ?  | cannot tell | Use only when you really cannot decide. |

## Worked examples

`examples.png` shows each label at least once, with both figure colours and both camera
distances. Its tile captions give the correct answers in the same left/right sense as above.
Example 5 has no head marker; there '?' is an acceptable answer.

## Filling in the form

- Enter exactly one label per cell: T, TL, TR, L, R, AL, AR or ?. Do not leave cells blank.
- Do not add, remove, rename or reorder rows or columns; keep the file name.
- Return the form to the experiment coordinator only, and keep a copy unchanged.
"""


def prepare(repo: Path, rev4: Path, rev3: Path, out: Path, private: Path) -> int:
    if problem := path_problem(out, private):
        return refuse(problem)
    if out.exists():
        return refuse(f"{out} exists")
    if (private / "assignments.json").exists():
        return refuse(f"{private / 'assignments.json'} exists; the round needs a new seed")
    key4 = json.loads((rev4 / "blind" / "answer_key.json").read_text())
    rec4 = json.loads((rev4 / "experiment.json").read_text())["sha256"]
    files_read = [str(rev4 / "blind" / "answer_key.json"), str(rev4 / "experiment.json")]
    bad = [s["id"] for s in key4["stills"]
           if sha256(rev4 / "stills" / "320" / f"{s['id']}.png") != rec4.get(f"stills\\320\\{s['id']}.png")]
    if len(key4["stills"]) != 56 or bad:
        return refuse(f"rev4 stills do not match rev4's recorded hashes: {bad[:5]}")
    a = new_assignments(key4, secrets.randbits(63))
    errs = check_assignments(a, key4)
    if errs:
        return refuse(f"assignment checks failed: {errs}")
    examples, read3 = pick_examples(rev3)
    covered = {lab for e in examples for lab in (e["left"], e["right"])}
    if covered != set(LABELS):
        return refuse(f"examples do not cover every label: {sorted(covered)}")

    private.mkdir(parents=True, exist_ok=True)
    (private / "assignments.json").write_text(json.dumps(a, indent=1))
    packet = out / "packet"
    sheets = []
    for n, page in enumerate(a["pages"], 1):
        src = {s["id"]: s["source_id"] for s in a["stills"]}
        tiles = [(rev4 / "stills" / "320" / f"{src[i]}.png", i) for i in page]
        ms.grid(repo, tiles, ms.COLS, 2, packet / f"review_p{n}.png")
        sheets.append(packet / f"review_p{n}.png")
    ex_tiles = [(rev3 / "stills" / "320" / f"{e['id']}.png",
                 f"Example {k}  left figure {e['left']}  /  right figure {e['right']}")
                for k, e in enumerate(examples, 1)]
    ms.grid(repo, ex_tiles, 1, 2, packet / "examples.png")
    forms = {}
    for r in (1, 2):
        name = f"answer_form_reviewer_{r}.csv"
        p = out / "forms" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["page", "still", "left_character", "right_character"])
            for n, page in enumerate(a["pages"], 1):
                for i in page:
                    w.writerow([n, i, "", ""])
        forms[r] = p
    zips = {}
    for r, form in forms.items():
        instr = INSTRUCTIONS.format(form=form.name)
        z = out / f"packet_reviewer_{r}.zip"
        with zipfile.ZipFile(z, "x", zipfile.ZIP_DEFLATED) as zf:
            for p in sheets + [packet / "examples.png"]:
                zf.write(p, p.name)
            zf.writestr("INSTRUCTIONS.md", instr)
            zf.write(form, form.name)
        zips[r] = z
    (packet / "INSTRUCTIONS.md").write_text(INSTRUCTIONS.format(form="answer_form_reviewer_N.csv"))
    public = {"round": ROUND, "convention": "anatomical (the figure's own left and right)",
              "labels": list(LABELS), "created": now(),
              "files": {str(p.relative_to(out)).replace("\\", "/"): sha256(p)
                        for p in sorted(out.rglob("*")) if p.is_file()}}
    (out / "packet_manifest.json").write_text(json.dumps(public, indent=1))
    (private / "prepare_record.json").write_text(json.dumps({
        "round": ROUND, "created": now(), "assignments_sha256": sha256(private / "assignments.json"),
        "rev4_files_read": files_read, "rev3_files_read": read3,
        "examples": [{k: e[k] for k in ("id", "design", "cam", "slot", "left", "right")} for e in examples],
        "example_sha256": {e["id"]: sha256(rev3 / "stills" / "320" / f"{e['id']}.png") for e in examples},
        "packet_manifest_sha256": sha256(out / "packet_manifest.json")}, indent=1))
    print(f"[review_round] prepared {ROUND}: 4 review pages, examples, instructions, "
          f"2 blank forms, 2 reviewer packets in {out}")
    return 0


# ---------------------------------------------------------------------------
# Lock and reveal
# ---------------------------------------------------------------------------
def lock(out: Path, private: Path, answers: list[Path], accept_identical: str | None = None) -> int:
    if problem := path_problem(out, private):
        return refuse(problem)
    if len(answers) != 2:
        return refuse("--lock needs exactly two filled forms, reviewer 1 then reviewer 2")
    rec = private / "lock.json"
    if rec.exists() or (private / "locked").exists():
        return refuse(f"{rec} exists; forms are already locked")
    if answers[0].resolve() == answers[1].resolve():
        return refuse("the two forms are the same file")
    byte_identical = sha256(answers[0]) == sha256(answers[1])
    if byte_identical and not accept_identical:
        return refuse("the two forms are byte-identical (use --accept-identical <reason> only on the "
                      "experiment owner's explicit decision; it is recorded as a protocol deviation)")
    a = json.loads((private / "assignments.json").read_text())
    errs = {p.name: ms.check_form(a, p) for p in answers}
    if any(errs.values()):
        return refuse(f"answer forms need fixing before locking {errs}")
    (private / "locked").mkdir()
    entries, given = [], []
    for r, p in enumerate(answers, 1):
        dest = private / "locked" / f"reviewer_{r}.csv"
        shutil.copy2(p, dest)
        st = p.stat()
        entries.append({"reviewer": r, "source": str(p), "size": st.st_size, "sha256": sha256(p),
                        "modified": datetime.datetime.fromtimestamp(st.st_mtime).astimezone().isoformat(timespec="seconds"),
                        "locked_copy": str(dest), "locked_sha256": sha256(dest)})
        given.append({(row["still"].strip(), f): (row.get(f) or "").strip().upper()
                      for row in csv.DictReader(open(p, newline="")) for f in ("left_character", "right_character")})
    identical = given[0] == given[1]
    record = {"round": ROUND, "locked": now(), "forms": entries, "answers_identical": identical}
    if byte_identical:
        record["protocol_deviation"] = {
            "what": "the two forms are byte-identical; the reviewers' answers are not independent",
            "accepted_by": "experiment owner", "reason": accept_identical,
            "effect": "both forms are scored, but the two-reviewer pass rule reduces to one judgement"}
    rec.write_text(json.dumps(record, indent=1))
    print(f"[review_round] locked 2 forms: {[e['sha256'][:16] for e in entries]}"
          + ("; WARNING: the two forms give identical answers" if identical else ""))
    return 0


def reveal(out: Path, private: Path) -> int:
    if problem := path_problem(out, private):
        return refuse(problem)
    rec = private / "lock.json"
    if not rec.exists():
        return refuse("no lock.json: both forms must be locked before the reveal")
    clash = [str(p) for p in (out / "scores.json", out / "answer_key.json") if p.exists()]
    if clash:
        return refuse(f"exists {clash}")
    lk = json.loads(rec.read_text())
    changed = [e["reviewer"] for e in lk["forms"] if sha256(Path(e["locked_copy"])) != e["locked_sha256"]]
    if changed:
        return refuse(f"locked forms changed since locking: reviewers {changed}")
    a = json.loads((private / "assignments.json").read_text())
    scores = {f"reviewer_{e['reviewer']}": ms.score(a, Path(e["locked_copy"]), truth_map=ANATOMICAL)
              for e in lk["forms"]}
    table = ms.score_table(scores, DESIGNS)
    decision = ms.screening_decision(table)
    shutil.copy2(private / "assignments.json", out / "answer_key.json")
    (out / "scores.json").write_text(json.dumps({
        "round": ROUND, "convention": "anatomical", "truth_map": {str(k): v for k, v in ANATOMICAL.items()},
        "lock": lk, **scores, "score_table": table, "screening_decision": decision}, indent=1))
    print(f"[review_round] screening: {decision['outcome']}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="review_round.py")
    p.add_argument("--repo", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--private", required=True, type=Path)
    p.add_argument("--rev4", type=Path)
    p.add_argument("--rev3", type=Path)
    p.add_argument("--answers", type=Path, action="append", default=[])
    p.add_argument("--accept-identical", metavar="REASON",
                   help="--lock only: accept byte-identical forms on the experiment owner's decision")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--lock", action="store_true")
    mode.add_argument("--reveal", action="store_true")
    args = p.parse_args()
    repo = args.repo.resolve()
    rel = lambda x: x if x.is_absolute() else repo / x
    out, private = rel(args.out).resolve(), args.private.resolve()
    if args.prepare:
        if not (args.rev4 and args.rev3):
            return refuse("--prepare needs --rev4 and --rev3")
        return prepare(repo, rel(args.rev4), rel(args.rev3), out, private)
    if args.lock:
        return lock(out, private, args.answers, args.accept_identical)
    return reveal(out, private)


if __name__ == "__main__":
    sys.exit(main())
