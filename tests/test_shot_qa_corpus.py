"""Milestone 8 Gate 2: Shot QA on the historical M7 defect corpus and the approved scenes, through
the real builder and the geometry inspector. Run with: pytest -m blender tests/test_shot_qa_corpus.py

Each corpus case (tests/fixtures/m8_shot_qa/corpus.json) is built from its preserved historical
spec (minified copies in tests/fixtures/m8_shot_qa/specs/, with the source path and SHA-256
of the preserved file recorded) or from the approved example plus a small documented patch,
with run_shot(render=False) into tmp_path. The inspector reads every frame of the case's
window; workers/shot_qa.py must report the expected rule on the expected objects inside the
documented window. The approved M4, M6 and M7 examples are inspected at every frame.
Nothing is rendered and nothing outside tmp_path is written.
"""
import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from workers import config
from workers import shot_qa as Q
from workers.blender_job import REPO, run_shot

pytestmark = [
    pytest.mark.blender,
    pytest.mark.skipif(shutil.which(config.BLENDER_BIN) is None, reason="Blender not found"),
]

FIX = REPO / "tests" / "fixtures" / "m8_shot_qa"
CORPUS = json.loads((FIX / "corpus.json").read_text())
INSPECT = REPO / "blender" / "scripts" / "inspect_shot_geometry.py"

# Genuine findings on approved scenes, confirmed in their rendered frames during Gate 2 and
# accepted as known issues for Milestone 8 (Gate 2 decision): static neck-level tangents. They
# keep their error severity; the accepted-findings fixtures mark them accepted_issue.
KNOWN_ACCEPTED_ERRORS = {
    "m7_greeting": {("tangent", "sh04_two_shot", "host", "tree2_crown"),
                    ("tangent", "sh07_end_wide", "traveller", "tree3_crown")},
    "m6_character": {("tangent", "sh02_track", "hero", "pillar_right")},
    "m4_sequence": set(),
}


def base_spec(name: str) -> dict:
    if name == "approved":
        return json.loads((REPO / "schemas/examples/m7_greeting.json").read_text())
    return json.loads((FIX / "specs" / f"{name}.json").read_text())


def patched(spec: dict, patch: dict) -> dict:
    s = copy.deepcopy(spec)
    for sh in s["shots"]:
        for k, v in patch.get(sh["shot_id"], {}).items():
            if isinstance(v, dict):
                sh["camera"].setdefault(k, {}).update(v)
            else:
                sh["camera"][k] = v
    return s


def geometry(spec: dict, root: Path, frames=None) -> dict:
    report = run_shot(spec, root / "project", render=False)
    assert report["status"] == "ok" and report["returncode"] == 0, report
    out = root / "geometry.json"
    extra = ["--frames", ",".join(map(str, range(frames[0], frames[1] + 1)))] if frames else []
    proc = subprocess.run([config.BLENDER_BIN, "-b", report["blend"], "--factory-startup",
                           "--python-exit-code", "1", "-P", str(INSPECT), "--", "--out", str(out), *extra],
                          capture_output=True, text=True, errors="replace", timeout=900)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    return json.loads(out.read_text())


@pytest.fixture(scope="module")
def corpus_runs(tmp_path_factory):
    runs = {}
    for case in CORPUS["cases"]:
        spec = patched(base_spec(case["base"]), case["patch"])
        geo = geometry(spec, tmp_path_factory.mktemp(f"case{case['case']}"), case["frames"])
        runs[case["case"]] = (spec, geo, Q.build_report(geo, spec, {"case": case["case"]}))
    return runs


def matches(f: dict, exp: dict) -> bool:
    return (f["rule"] == exp["rule"] and f["severity"] == exp["severity"] and f["shot_id"] == exp["shot_id"]
            and all(o in f["objects"] for o in exp["objects"])
            and exp["window"][0] <= f["frames"][0] and f["frames"][1] <= exp["window"][1])


def test_fixture_specs_record_their_provenance():
    for name, prov in CORPUS["specs"].items():
        assert (FIX / "specs" / f"{name}.json").is_file()
        assert prov["source"].startswith("storage/projects/m7_greeting/") and len(prov["source_sha256"]) == 64
    for case in CORPUS["cases"]:
        assert case["provenance"] and (case["base"] == "approved" or case["base"] in CORPUS["specs"])


@pytest.mark.parametrize("case", [c["case"] for c in CORPUS["cases"] if c.get("status") != "not_reproduced"])
def test_each_historical_defect_is_detected_by_its_rule_inside_its_window(corpus_runs, case):
    exp = next(c for c in CORPUS["cases"] if c["case"] == case)["expected"]
    report = corpus_runs[case][2]
    hits = [f for f in report["findings"] if matches(f, exp)]
    assert hits, [(f["rule"], f["severity"], f["frames"], f["objects"]) for f in report["findings"]]


def test_case_1_does_not_reproduce_as_a_crop_and_the_measurement_says_why(corpus_runs):
    case = next(c for c in CORPUS["cases"] if c["case"] == 1)
    spec, geo, report = corpus_runs[1]
    exp = case["expected"]
    assert not [f for f in report["findings"] if f["rule"] == exp["absent_rule"]]
    scene = Q.Scene(geo, spec)
    cut = next(f for f in scene.frames if f["frame"] == 265)
    parts = scene.character_parts(cut, exp["character"])
    assert scene.in_frame_fraction(cut, [h for h, _ in parts.values()]) == pytest.approx(1.0)
    assert min(x for h, _ in parts.values() for x, _ in h) >= exp["min_left_margin"], "inside the left edge"


@pytest.fixture(scope="module")
def approved(tmp_path_factory):
    out = {}
    for name in KNOWN_ACCEPTED_ERRORS:
        spec = json.loads((REPO / f"schemas/examples/{name}.json").read_text())
        geo = geometry(spec, tmp_path_factory.mktemp(name))
        acc = json.loads((FIX / f"accepted_{name}.json").read_text())
        out[name] = (geo, spec, Q.build_report(geo, spec, {"scene": name}, acc))
    return out


@pytest.mark.parametrize("name", list(KNOWN_ACCEPTED_ERRORS))
def test_approved_scenes_have_no_unexplained_errors_or_warnings(approved, name):
    geo, spec, report = approved[name]
    assert report["scene"]["complete"], "every frame evaluated"
    assert report["summary"]["error"] == 0 and report["summary"]["warning"] == 0, "nothing unexplained"
    accepted_errors = {(f["rule"], f["shot_id"], f["objects"][0]["id"], f["objects"][2]["id"])
                       for f in report["findings"] if f["severity"] == "error"}
    assert accepted_errors == KNOWN_ACCEPTED_ERRORS[name]
    for f in report["findings"]:
        if f["severity"] == "error":
            assert f["accepted"]["kind"] == "accepted_issue" and f["measured"], "kept with its evidence"


def test_the_report_is_identical_for_identical_input(approved, tmp_path):
    geo, spec, _ = approved["m7_greeting"]
    (tmp_path / "g.json").write_text(json.dumps(geo))
    (tmp_path / "s.json").write_text(json.dumps(spec))
    for out in ("a.json", "b.json"):
        assert Q.main(["--geometry", str(tmp_path / "g.json"), "--spec", str(tmp_path / "s.json"),
                       "--out", str(tmp_path / out),
                       "--accepted", str(FIX / "accepted_m7_greeting.json")]) == 0
    assert (tmp_path / "a.json").read_bytes() == (tmp_path / "b.json").read_bytes()


# ---------------------------------------------------------------------------------------------
# Gate 3: the composition sheet points every tile at its finding's frame and objects
# ---------------------------------------------------------------------------------------------
def sheet_checks(report: dict, geo: dict, out: Path) -> dict:
    """Builds the sheet with every finding drawn (no rendered frames: plain backgrounds) and
    checks each tile against its finding and the geometry of the frame it shows."""
    from workers import composition_sheet as S
    index = S.build_sheet(report, geo, [], "none_{frame:04d}.png", out, include_info=True)
    raw = subprocess.run([config.FFMPEG_BIN, "-v", "error", "-i", str(out), "-f", "rawvideo", "-pix_fmt",
                          "rgb24", "-"], capture_output=True, check=True).stdout
    width = S.COLS * S.TILE_W
    by_frame = {f["frame"]: f for f in geo["frames"]}
    by_id = {f["id"]: f for f in report["findings"]}
    assert [t["finding_id"] for t in index["tiles"]] == [f["id"] for f in report["findings"]]
    for tile in index["tiles"]:
        f = by_id[tile["finding_id"]]
        assert f["frames"][0] <= tile["frame_shown"] <= f["frames"][1]
        assert tile["frame_shown"] == f["evidence"]["worst_frame"]
        named = {(o["kind"], o["id"]) for o in f["objects"] if o["kind"] not in ("part", "edge")}
        drawn = {(geo["objects"][o["object"]]["kind"], geo["objects"][o["object"]]["owner"])
                 for o in tile["outlines"]}
        assert drawn == named, (tile["finding_id"], drawn)
        parts = [o["id"] for o in f["objects"] if o["kind"] == "part"]
        for o in tile["outlines"]:
            if o["role"] != "highlight":
                continue
            assert o["part"] is None or o["part"] in parts
            entry = by_frame[tile["frame_shown"]]["objects"][o["object"]]
            hull = entry["islands"][o["part"]]["hull"] if o["part"] else entry["hull"]
            for x, y in hull:
                if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0:
                    px = min(tile["position"][0] + round(x * S.TILE_W), tile["position"][0] + S.TILE_W - 1)
                    py = min(tile["position"][1] + round((1 - y) * S.TILE_H), tile["position"][1] + S.TILE_H - 1)
                    i = (py * width + px) * 3
                    assert tuple(raw[i:i + 3]) == S.COLORS[f["severity"]], (tile["finding_id"], x, y)
    return index


def test_sheet_tiles_match_their_findings_on_the_corpus(corpus_runs, tmp_path):
    for case, (_, geo, report) in corpus_runs.items():
        index = sheet_checks(report, geo, tmp_path / f"case{case}.png")
        if case != 1:
            exp = next(c for c in CORPUS["cases"] if c["case"] == case)["expected"]
            assert any(matches(next(f for f in report["findings"] if f["id"] == t["finding_id"]), exp)
                       for t in index["tiles"]), f"case {case}: the defect has a tile"


@pytest.mark.parametrize("name", list(KNOWN_ACCEPTED_ERRORS))
def test_sheet_tiles_match_their_findings_on_the_approved_scenes(approved, name, tmp_path):
    geo, _, report = approved[name]
    sheet_checks(report, geo, tmp_path / "sheet.png")


def test_the_m7_lamp_post_behind_the_lowered_arm_stays_unflagged(approved):
    _, _, report = approved["m7_greeting"]
    arm = ("upper_arm", "forearm", "hand")
    for f in report["findings"]:
        ids = [o["id"] for o in f["objects"]]
        if "lamp_post" in ids:
            assert not any(i.startswith(arm) for i in ids), f["id"]
            assert f["accepted"]["kind"] == "accepted_issue", "only the accepted torso tangents"
