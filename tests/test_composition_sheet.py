"""Milestone 8 Gate 3: workers/composition_sheet.py on a small hand-made report and geometry.

Frames are flat-colour PNGs made with FFmpeg, one colour per frame, so a tile's background says
which frame it shows. The sheet runs over the corpus and the approved scenes in
tests/test_shot_qa_corpus.py.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from workers import composition_sheet as C
from workers import config

pytestmark = pytest.mark.skipif(shutil.which(config.FFMPEG_BIN) is None, reason="FFmpeg not found")

HEAD = [[0.45, 0.7], [0.55, 0.7], [0.55, 0.8], [0.45, 0.8]]
CHEST = [[0.42, 0.45], [0.58, 0.45], [0.58, 0.68], [0.42, 0.68]]
POST = [[0.56, 0.1], [0.6, 0.1], [0.6, 0.9], [0.56, 0.9]]
SLIVER = [[0.97, 0.3], [1.02, 0.3], [1.02, 0.6], [0.97, 0.6]]


def frame_colour(n):
    return (20 * n, 90, 140)


def geometry():
    frames = []
    for n in range(1, 7):
        frames.append({"frame": n, "shot_id": "s1", "objects": {
            "GEO-a": {"hull": HEAD[:2] + CHEST[:2] + CHEST[2:] + HEAD[2:], "depth": [5.0, 5.4], "in_frame": True,
                      "islands": {"head": {"hull": HEAD}, "chest": {"hull": CHEST}}},
            "PRIM-post": {"hull": POST, "depth": [9.0, 9.2], "in_frame": True, "islands": {"island_0": {"hull": POST}}},
            "PRIM-bush": {"hull": SLIVER, "depth": [7.0, 7.5], "in_frame": True,
                          "islands": {"island_0": {"hull": SLIVER}}}}})
    meta = {"GEO-a": {"owner": "a", "kind": "character", "islands": ["chest", "head"], "vertices": 0},
            "PRIM-post": {"owner": "post", "kind": "primitive", "islands": ["island_0"], "vertices": 0},
            "PRIM-bush": {"owner": "bush", "kind": "primitive", "islands": ["island_0"], "vertices": 0}}
    return {"schema": "shot_geometry.v1", "frame_range": [1, 6], "objects": meta, "armatures": {},
            "frames": frames}


def finding(fid, rule, severity, frames, worst, objects, accepted=None):
    return {"id": fid, "rule": rule, "rule_version": 1, "severity": severity, "shot_id": "s1",
            "frames": frames, "frame_count": frames[1] - frames[0] + 1,
            "objects": [{"kind": k, "id": v} for k, v in objects], "measured": {"gap": 0.004},
            "threshold": {}, "explanation": "", "evidence": {"geometry_frames": frames, "worst_frame": worst},
            "accepted": accepted}


TANGENT = finding("tangent:s1:a/head/post:1", "tangent", "error", [1, 6], 3,
                  [("character", "a"), ("part", "head"), ("primitive", "post"), ("part", "island_0")])
SLIVER_F = finding("edge_sliver:s1:bush/right:4", "edge_sliver", "warning", [4, 6], 5,
                   [("primitive", "bush"), ("edge", "right")],
                   {"kind": "accepted_issue", "reason": "A long reason. " * 20})
PASSING = finding("tangent:s1:a/chest/post:2", "tangent", "info", [2, 3], 2,
                  [("character", "a"), ("part", "chest"), ("primitive", "post"), ("part", "island_0")])


def report():
    return {"schema": "composition_report.v1", "verdict": "evidence_only", "human_approval_required": True,
            "scene": {"shot_id": "s1", "frame_range": [1, 6], "frames_evaluated": 6, "complete": True},
            "summary": {"error": 1, "warning": 0, "info": 1, "accepted": 1},
            "findings": [TANGENT, SLIVER_F, PASSING]}


def render_frames(d: Path, frames=(1, 2, 4)):
    d.mkdir(parents=True, exist_ok=True)
    for n in frames:
        r, g, b = frame_colour(n)
        subprocess.run([config.FFMPEG_BIN, "-v", "error", "-y", "-f", "lavfi", "-i",
                        f"color=c=0x{r:02x}{g:02x}{b:02x}:s=1280x720:d=1", "-frames:v", "1",
                        "-pix_fmt", "rgb24", str(d / f"s1_{n:04d}.png")], check=True)
    return d


def inputs(tmp_path, frames=(1, 2, 4)):
    (tmp_path / "report.json").write_text(json.dumps(report()))
    (tmp_path / "geometry.json").write_text(json.dumps(geometry()))
    render_frames(tmp_path / "frames", frames)
    return ["--report", str(tmp_path / "report.json"), "--geometry", str(tmp_path / "geometry.json"),
            "--frames-dir", str(tmp_path / "frames"), "--pattern", "s1_{frame:04d}.png"]


def pixels(png: Path):
    probe = subprocess.run([config.FFMPEG_BIN, "-v", "error", "-i", str(png), "-f", "rawvideo",
                            "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    index = json.loads(png.with_suffix(".json").read_text())
    width = C.COLS * C.TILE_W

    def at(x, y):
        i = (y * width + x) * 3
        return tuple(probe[i:i + 3])
    return index, at


def tile_px(tile, x, y):
    """Sheet pixel of normalized frame point (x, y) inside a tile."""
    px = min(tile["position"][0] + round(x * C.TILE_W), tile["position"][0] + C.TILE_W - 1)
    py = min(tile["position"][1] + round((1 - y) * C.TILE_H), tile["position"][1] + C.TILE_H - 1)
    return px, py


# ---------------------------------------------------------------------------
# Frame choice, outlines and captions
# ---------------------------------------------------------------------------
def test_choose_frame_prefers_the_worst_then_the_nearest_rendered_then_none(tmp_path):
    d = render_frames(tmp_path, (2, 4, 5))
    geo = {f["frame"]: f for f in geometry()["frames"]}
    assert C.choose_frame(SLIVER_F, geo, [d], "s1_{frame:04d}.png") == (5, d / "s1_0005.png")
    assert C.choose_frame(TANGENT, geo, [d], "s1_{frame:04d}.png") == (2, d / "s1_0002.png"), "tie: earlier"
    assert C.choose_frame(PASSING, geo, [tmp_path / "none"], "s1_{frame:04d}.png") == (2, None)
    outside = finding("x", "tangent", "error", [5, 6], 6, [("primitive", "post")])
    assert C.choose_frame(outside, geo, [render_frames(tmp_path / "early", (1,))], "s1_{frame:04d}.png") == (6, None), \
        "never a frame outside the finding"


def test_outlines_highlight_the_part_with_its_object_as_context():
    geo = geometry()
    fr = geo["frames"][0]
    assert C.outlines_for(TANGENT, geo, fr) == [("GEO-a", None, "context"), ("GEO-a", "head", "highlight"),
                                                ("PRIM-post", None, "context"), ("PRIM-post", "island_0", "highlight")]
    assert C.outlines_for(SLIVER_F, geo, fr) == [("PRIM-bush", None, "highlight")]


def test_captions_fit_the_tile_and_keep_the_id_and_acceptance():
    for f in (TANGENT, SLIVER_F, {**SLIVER_F, "id": "edge_sliver:" + "x" * 150}):
        lines = C._caption(1, f, 5, False)
        assert len(lines) <= C.CAPTION_LINES and all(len(ln) <= C.CAPTION_CHARS for ln in lines)
        assert lines[0].startswith(f"[1] {f['severity'].upper()} {f['rule']} s1 frames")
        assert "NO RENDERED FRAME" in " ".join(lines)
        ident = next(k for k, ln in enumerate(lines) if ln.startswith("id "))
        assert "".join(lines[ident:])[3:] == f["id"][:2 * C.CAPTION_CHARS - 3], "the ID, last, unwrapped"
    acc = C._caption(2, SLIVER_F, 5, True)
    assert any(ln.startswith("ACCEPTED (accepted_issue): A long reason.") for ln in acc)
    assert C.CAPTION_LINES * C.LINE_STEP + 6 <= C.CAPTION_H


# ---------------------------------------------------------------------------
# The sheet
# ---------------------------------------------------------------------------
def test_sheet_tiles_point_at_the_right_frame_and_object(tmp_path):
    out = tmp_path / "review" / "composition_sheet.png"
    assert C.main(inputs(tmp_path) + ["--out", str(out)]) == 0
    index, at = pixels(out)
    assert index["schema"] == "composition_sheet.v1" and index["verdict"] == "evidence_only"
    assert index["human_approval_required"] is True and index["info_not_drawn"] == 1
    assert index["inputs"]["report"]["file"] == "report.json" and len(index["inputs"]["geometry"]["sha256"]) == 64
    assert [(t["finding_id"], t["frame_shown"], t["rendered_frame"]) for t in index["tiles"]] == [
        (TANGENT["id"], 2, "s1_0002.png"), (SLIVER_F["id"], 4, "s1_0004.png")]
    tangent, sliver = index["tiles"]
    assert sliver["accepted"]["kind"] == "accepted_issue" and sliver["edges"] == ["right"]
    for tile, n in ((tangent, 2), (sliver, 4)):
        bg = at(*tile_px(tile, 0.1, 0.1))
        assert all(abs(a - b) <= 2 for a, b in zip(bg, frame_colour(n))), "the background is frame n"
    for x, y in HEAD + POST:
        assert at(*tile_px(tangent, x, y)) == C.COLORS["error"], (x, y)
    assert at(*tile_px(tangent, 0.42, 0.5)) == C.CONTEXT, "the rest of the character, as context"
    for x, y in SLIVER:
        if x <= 1:
            assert at(*tile_px(sliver, x, y)) == C.COLORS["warning"], (x, y)
    assert at(sliver["position"][0] + C.TILE_W - 2, sliver["position"][1] + 5) == C.COLORS["warning"], "edge"
    with_info = tmp_path / "info.png"
    assert C.main(inputs(tmp_path) + ["--out", str(with_info), "--include-info"]) == 0
    index = json.loads(with_info.with_suffix(".json").read_text())
    assert [t["severity"] for t in index["tiles"]] == ["error", "warning", "info"] and index["info_not_drawn"] == 0


def test_identical_inputs_give_identical_sheets(tmp_path):
    args = inputs(tmp_path)
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
        assert C.main(args + ["--out", str(tmp_path / name / "composition_sheet.png")]) == 0
    for f in ("composition_sheet.png", "composition_sheet.json"):
        assert (tmp_path / "a" / f).read_bytes() == (tmp_path / "b" / f).read_bytes(), f


def test_without_rendered_frames_the_outlines_go_on_a_plain_background(tmp_path):
    out = tmp_path / "s.png"
    assert C.main(inputs(tmp_path, frames=()) + ["--out", str(out)]) == 0
    index, at = pixels(out)
    assert [(t["frame_shown"], t["rendered_frame"]) for t in index["tiles"]] == [(3, None), (5, None)]
    assert at(*tile_px(index["tiles"][0], 0.1, 0.1)) == C.BLANK
    assert at(*tile_px(index["tiles"][0], *HEAD[0])) == C.COLORS["error"]


def test_existing_outputs_are_kept_without_force_and_a_failed_rerun_leaves_nothing(tmp_path, capsys):
    out = tmp_path / "s.png"
    args = inputs(tmp_path) + ["--out", str(out)]
    assert C.main(args) == 0
    before = out.read_bytes()
    assert C.main(args) == 1 and out.read_bytes() == before and "pass --force" in capsys.readouterr().err
    (tmp_path / "geometry.json").write_text(json.dumps({**geometry(), "schema": "other"}))
    assert C.main(args + ["--force"]) == 1
    assert not out.exists() and not out.with_suffix(".json").exists()
    (tmp_path / "geometry.json").write_text(json.dumps(geometry()))
    (tmp_path / "report.json").write_text(json.dumps({**report(), "schema": "other"}))
    assert C.main(args) == 1 and not out.exists() and "composition_report.v1" in capsys.readouterr().err


def test_shot_dir_mode_reads_the_review_folder_and_build_report(tmp_path):
    inputs(tmp_path)
    shot = tmp_path / "shot"
    (shot / "review").mkdir(parents=True)
    shutil.copy(tmp_path / "report.json", shot / "review" / "composition_report.json")
    shutil.copy(tmp_path / "geometry.json", shot / "review" / "shot_geometry.json")
    (shot / "build_report.json").write_text(json.dumps({"shot_id": "s1", "frames_dir": str(tmp_path / "frames")}))
    assert C.main(["--shot-dir", str(shot)]) == 0
    index = json.loads((shot / "review" / "composition_sheet.json").read_text())
    assert index["sheet"] == "composition_sheet.png" and index["tiles"][0]["rendered_frame"] == "s1_0002.png"
    assert index["inputs"]["report"]["file"] == "composition_report.json"
