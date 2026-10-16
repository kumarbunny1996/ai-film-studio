"""Contact-sheet worker (Milestone 2), on synthetic FFmpeg frames (no Blender needed)."""
import json
import math
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

import workers.contact_sheet as cs
from workers import config
from workers.contact_sheet import (INFO_THRESHOLDS, ContactSheetError, grid_shape, main, run,
                                   sample_frames, thumb_height)

needs_ffmpeg = pytest.mark.skipif(
    shutil.which(config.FFMPEG_BIN) is None or shutil.which(config.FFPROBE_BIN) is None,
    reason="ffmpeg/ffprobe not found")
DROP = object()          # report_patch value meaning "remove this key"


# ---------------------------------------------------------------------------
# Pure functions (no FFmpeg)
# ---------------------------------------------------------------------------
def test_sample_frames_spreads_evenly_with_both_endpoints():
    assert sample_frames(1, 96, 12) == [1, 10, 18, 27, 36, 44, 53, 61, 70, 79, 87, 96]
    assert sample_frames(101, 120, 4) == [101, 107, 114, 120]


def test_sample_frames_single_frame_range():
    assert sample_frames(5, 5, 12) == [5]
    assert sample_frames(5, 5, 1) == [5]


def test_sample_frames_one_sample_still_keeps_both_endpoints():
    # documented rule: with two or more frames, first and last always appear
    assert sample_frames(1, 10, 1) == [1, 10]


def test_sample_frames_more_samples_than_frames_returns_every_frame():
    assert sample_frames(3, 7, 50) == [3, 4, 5, 6, 7]
    assert sample_frames(3, 7, 5) == [3, 4, 5, 6, 7]


@pytest.mark.parametrize("n", [2, 3, 7, 96, 1441])
@pytest.mark.parametrize("k", [1, 2, 3, 12, 50])
def test_sample_frames_properties(n, k):
    start = 17
    s = sample_frames(start, start + n - 1, k)
    assert s == sorted(set(s))
    assert s[0] == start and s[-1] == start + n - 1
    assert len(s) == min(max(k, 2), n)


@pytest.mark.parametrize("args", [(5, 4, 3), (1, 10, 0), (1, 10, -2), (1.0, 10, 3), (True, 10, 3)])
def test_sample_frames_rejects_bad_input(args):
    with pytest.raises(ValueError):
        sample_frames(*args)


@pytest.mark.parametrize("n, cols, expected", [
    (12, 4, (4, 3)), (10, 4, (4, 3)), (3, 4, (3, 1)), (1, 4, (1, 1)), (5, 1, (1, 5)), (16, 16, (16, 1)),
])
def test_grid_shape(n, cols, expected):
    assert grid_shape(n, cols) == expected


@pytest.mark.parametrize("tw, w, h, expected", [
    (320, 640, 360, 180), (320, 1920, 1080, 180), (100, 333, 100, 30), (3, 2, 1, 2), (32, 4000, 10, 1),
])
def test_thumb_height_rounds_half_up(tw, w, h, expected):
    assert thumb_height(tw, w, h) == expected


# ---------------------------------------------------------------------------
# Synthetic shots
# ---------------------------------------------------------------------------
def ffmpeg_frames(out_pattern: Path, source: str, count: int, start: int, pix_fmt: str = "rgb24"):
    # a literal % in the directory must be doubled, or image2 expands it (see Render.pattern)
    pattern = str(out_pattern.parent).replace("%", "%%") + os.sep + out_pattern.name
    subprocess.run([config.FFMPEG_BIN, "-v", "error", "-f", "lavfi", "-i", source,
                    "-frames:v", str(count), "-start_number", str(start), "-pix_fmt", pix_fmt,
                    pattern], check=True)


def gray_ramp(size="160x90"):
    """Frame i (0-based) is a flat gray of 20 + 10*i, so a crop identifies the frame."""
    return f"color=c=black:s={size}:r=24,format=gray,geq=lum='min(255,20+10*N)'"


def make_shot(root: Path, start=1, count=12, *, size=(160, 90), source=None, pix_fmt="rgb24",
              name="shot", **report_patch) -> Path:
    """A shot dir like blender_job.run_shot leaves it; report_patch edits build_report.json."""
    shot = root / "shots" / name
    frames = shot / "frames"
    frames.mkdir(parents=True)
    spec = shot / "spec.json"
    spec.write_text("{}")
    old = time.time() - 3600                     # spec.json is written before Blender renders
    os.utime(spec, (old, old))
    source = source or f"testsrc=size={size[0]}x{size[1]}:rate=24"
    ffmpeg_frames(frames / f"{name}_%04d.png", source, count, start, pix_fmt)
    report = {"shot_id": name, "status": "ok", "warnings": [], "blender_version": "test",
              "frames_dir": str(frames), "frame_range": [start, start + count - 1],
              "resolution": list(size), "fps": 24}
    for k, v in report_patch.items():
        if v is DROP:
            report.pop(k, None)
        else:
            report[k] = v
    (shot / "build_report.json").write_text(json.dumps(report))
    return shot


def load_report(shot: Path) -> dict:
    return json.loads((shot / "review" / "frame_report.json").read_text())


def probe(path: Path) -> dict:
    out = subprocess.run([config.FFPROBE_BIN, "-v", "error", "-show_entries",
                          "stream=width,height,pix_fmt", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)["streams"][0]


def region_yavg(image: Path, x: int, y: int, w: int, h: int) -> float:
    out = subprocess.run([config.FFMPEG_BIN, "-v", "error", "-i", str(image), "-vf",
                          f"crop={w}:{h}:{x}:{y},format=gray,signalstats,metadata=mode=print:file=-",
                          "-f", "null", "-"], capture_output=True, text=True, check=True).stdout
    return float(next(l for l in out.splitlines() if "YAVG=" in l).split("=")[1])


def all_keys(obj) -> set[str]:
    if isinstance(obj, dict):
        return set(obj) | set().union(*(all_keys(v) for v in obj.values()))
    if isinstance(obj, list):
        return set().union(*(all_keys(v) for v in obj)) if obj else set()
    return set()


# ---------------------------------------------------------------------------
# Contact sheet
# ---------------------------------------------------------------------------
@needs_ffmpeg
def test_default_sheet_is_4x3_grid_of_320px_rgb24(tmp_path):
    shot = make_shot(tmp_path, count=12, size=(160, 90))
    summary = run(shot)
    sheet = shot / "review" / "contact_sheet.png"
    assert probe(sheet) == {"width": 1280, "height": 540, "pix_fmt": "rgb24"}
    cs = load_report(shot)["contact_sheet"]
    assert (cs["columns"], cs["rows"], cs["thumb_width"], cs["thumb_height"]) == (4, 3, 320, 180)
    assert cs["sampled_frames"] == list(range(1, 13)) == summary["sampled_frames"]
    assert summary["sheet_size"] == [1280, 540]


@needs_ffmpeg
def test_sheet_keeps_frame_order_and_offset(tmp_path):
    """Each tile's centre gray identifies its source frame: 20 + 10 * (frame - start)."""
    shot = make_shot(tmp_path, start=101, count=20, source=gray_ramp())
    run(shot, samples=4, cols=4, thumb_width=160)
    rep = load_report(shot)
    assert rep["contact_sheet"]["sampled_frames"] == [101, 107, 114, 120]
    sheet = shot / "review" / "contact_sheet.png"
    for col, frame in enumerate([101, 107, 114, 120]):
        # centre of the tile, clear of the top-left frame label
        assert region_yavg(sheet, col * 160 + 60, 40, 40, 30) == pytest.approx(
            20 + 10 * (frame - 101), abs=3)


@needs_ffmpeg
def test_partial_grid_pads_last_row_with_black(tmp_path):
    shot = make_shot(tmp_path, count=10, source=gray_ramp())
    run(shot, samples=10, cols=4, thumb_width=160)
    sheet = shot / "review" / "contact_sheet.png"
    assert probe(sheet)["width"] == 640 and probe(sheet)["height"] == 270     # 4x3 grid
    assert region_yavg(sheet, 1 * 160 + 60, 2 * 90 + 40, 40, 30) == pytest.approx(110, abs=3)  # frame 10
    assert region_yavg(sheet, 2 * 160 + 20, 2 * 90 + 20, 100, 50) < 1                 # empty cell
    assert region_yavg(sheet, 3 * 160 + 20, 2 * 90 + 20, 100, 50) < 1


@needs_ffmpeg
def test_single_frame_shot(tmp_path):
    shot = make_shot(tmp_path, start=7, count=1)
    run(shot)
    rep = load_report(shot)
    assert rep["contact_sheet"]["sampled_frames"] == [7]
    assert (rep["contact_sheet"]["width"], rep["contact_sheet"]["height"]) == (320, 180)
    assert rep["analysis"]["frames"] == [{"frame": 7, "yavg": rep["analysis"]["frames"][0]["yavg"],
                                          "ydif": None, "scene_score": None}]
    assert rep["analysis"]["summary"]["ydif"] is None


@needs_ffmpeg
@pytest.mark.skipif(not Path(config.FFMPEG_FONTFILE).is_file(), reason="label font not installed")
def test_labels_drawn_when_font_exists(tmp_path):
    shot = make_shot(tmp_path, count=4)
    run(shot)
    cs = load_report(shot)["contact_sheet"]
    assert cs["labels"] is True and Path(cs["label_font"]) == Path(config.FFMPEG_FONTFILE)


@needs_ffmpeg
def test_missing_font_gives_unlabelled_sheet_and_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "FFMPEG_FONTFILE", str(tmp_path / "no_such_font.ttf"))
    shot = make_shot(tmp_path, count=4)
    run(shot)
    rep = load_report(shot)
    assert rep["contact_sheet"]["labels"] is False
    assert any("no frame labels" in w for w in rep["warnings"])
    assert probe(shot / "review" / "contact_sheet.png")["pix_fmt"] == "rgb24"


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
@needs_ffmpeg
def test_analysis_numbers_frames_from_frame_start(tmp_path):
    shot = make_shot(tmp_path, start=5, count=12)
    run(shot)
    a = load_report(shot)["analysis"]
    assert [f["frame"] for f in a["frames"]] == list(range(5, 17))
    first, rest = a["frames"][0], a["frames"][1:]
    assert first["ydif"] is None and first["scene_score"] is None      # documented convention
    assert all(isinstance(f["ydif"], float) and isinstance(f["scene_score"], float) for f in rest)
    assert a["summary"]["ydif"]["count"] == 11 and a["summary"]["yavg"]["count"] == 12
    assert 5 <= a["summary"]["yavg"]["min_frame"] <= 16


@needs_ffmpeg
def test_gray_ramp_metrics_are_exact_on_8bit_scale(tmp_path):
    shot = make_shot(tmp_path, count=5, source=gray_ramp())
    run(shot)
    frames = load_report(shot)["analysis"]["frames"]
    assert [f["yavg"] for f in frames] == pytest.approx([20, 30, 40, 50, 60], abs=1)
    assert [f["ydif"] for f in frames[1:]] == pytest.approx([10, 10, 10, 10], abs=1)


@needs_ffmpeg
def test_8bit_and_16bit_sources_give_comparable_metrics(tmp_path):
    """Both are reduced to 8-bit gray before signalstats. The same picture stored at 8 or
    16 bits can differ by at most one 8-bit code value per pixel after conversion, so
    per-frame means (YAVG) and mean differences (YDIF) agree within 1.0."""
    s8 = make_shot(tmp_path / "a", count=12, pix_fmt="rgb24")
    s16 = make_shot(tmp_path / "b", count=12, pix_fmt="rgb48be")
    run(s8), run(s16)
    r8, r16 = load_report(s8), load_report(s16)
    assert (r8["render"]["source_pix_fmt"], r16["render"]["source_pix_fmt"]) == ("rgb24", "rgb48be")
    for f8, f16 in zip(r8["analysis"]["frames"], r16["analysis"]["frames"], strict=True):
        assert f16["yavg"] == pytest.approx(f8["yavg"], abs=1.0)
        if f8["ydif"] is not None:
            assert f16["ydif"] == pytest.approx(f8["ydif"], abs=1.0)


@needs_ffmpeg
def test_clean_sequence_has_no_flags(tmp_path):
    shot = make_shot(tmp_path, count=24)
    run(shot)
    rep = load_report(shot)
    assert rep["analysis"]["flags"] == []
    assert not any("analysis flag" in w for w in rep["warnings"])


@needs_ffmpeg
def test_black_frame_and_jump_are_flagged_as_information_only(tmp_path):
    shot = make_shot(tmp_path, count=24)
    frames = shot / "frames"
    ffmpeg_frames(frames / "shot_%04d.png", "color=c=black:s=160x90:r=24", 1, 10)     # frame 10
    ffmpeg_frames(frames / "shot_%04d.png", "color=c=white:s=160x90:r=24", 7, 18)     # 18-24
    summary = run(shot)
    rep = load_report(shot)
    a = rep["analysis"]
    by_frame = {f["frame"]: f for f in a["frames"]}
    assert by_frame[10]["yavg"] < INFO_THRESHOLDS["dark_frame_yavg_below"]
    assert by_frame[18]["ydif"] > by_frame[17]["ydif"]
    kinds = {(f["frame"], f["kind"]) for f in a["flags"]}
    assert {(10, "dark_frame"), (10, "large_difference"), (11, "large_difference"),
            (18, "large_difference"), (18, "brightness_jump")} <= kinds
    assert a["summary"]["yavg"]["min_frame"] == 10
    assert a["thresholds"]["calibrated"] is False
    assert any("not a confirmed defect" in w for w in rep["warnings"])
    # metrics are evidence, never a verdict
    assert rep["verdict"] == "evidence_only" and rep["human_approval_required"] is True
    assert summary["flags"] == len(a["flags"])


# ---------------------------------------------------------------------------
# Report contract
# ---------------------------------------------------------------------------
@needs_ffmpeg
def test_report_contract_and_no_approval(tmp_path):
    shot = make_shot(tmp_path, start=3, count=8)
    summary = run(shot)
    rep = load_report(shot)
    assert rep["schema"] == "frame_report.v1"
    assert rep["verdict"] == "evidence_only" and rep["human_approval_required"] is True
    assert not any("approv" in k and k != "human_approval_required"
                   for k in all_keys(rep) | all_keys(summary))
    assert rep["render"] == {"frame_range": [3, 10], "frame_count": 8, "fps": 24,
                             "resolution": [160, 90], "source_pix_fmt": "rgb24", "smoke": False,
                             "blender_version": "test"}
    assert rep["inputs"]["frames_dir"] == str((shot / "frames").resolve())
    assert rep["inputs"]["frame_pattern"] == "shot_%04d.png"
    assert rep["tools"]["ffmpeg"].startswith("ffmpeg version")
    for log in rep["logs"].values():
        assert Path(log).is_file() and Path(log).parent == (shot / "review").resolve()


@needs_ffmpeg
def test_report_is_deterministic(tmp_path):
    shot = make_shot(tmp_path, count=6)
    run(shot)
    first = (shot / "review" / "frame_report.json").read_text()
    run(shot, force=True)
    assert (shot / "review" / "frame_report.json").read_text() == first


# ---------------------------------------------------------------------------
# Input validation: every failure writes nothing
# ---------------------------------------------------------------------------
def _expect_rejected(shot: Path, match: str):
    with pytest.raises(ContactSheetError, match=match):
        run(shot)
    assert not (shot / "review").exists()


@needs_ffmpeg
def test_missing_frame_is_an_error(tmp_path):
    shot = make_shot(tmp_path, count=8)
    (shot / "frames" / "shot_0004.png").unlink()
    _expect_rejected(shot, r"1 of 8 expected frames missing.*shot_0004\.png")


@needs_ffmpeg
@pytest.mark.parametrize("status", ["crash", "spec_error", "running", None])
def test_unsuccessful_build_is_rejected_even_with_pngs(tmp_path, status):
    shot = make_shot(tmp_path, count=4, status=status)
    _expect_rejected(shot, "build status")


@needs_ffmpeg
def test_missing_build_report_is_rejected(tmp_path):
    shot = make_shot(tmp_path, count=4)
    (shot / "build_report.json").unlink()
    _expect_rejected(shot, "render did not complete")


@needs_ffmpeg
@pytest.mark.parametrize("key", ["frames_dir", "frame_range", "resolution", "fps", "shot_id"])
def test_missing_render_metadata_is_rejected(tmp_path, key):
    shot = make_shot(tmp_path, count=4, **{key: DROP})
    _expect_rejected(shot, "lacks")


@needs_ffmpeg
def test_frames_outside_shot_dir_are_rejected(tmp_path):
    elsewhere = make_shot(tmp_path / "other", count=4)
    shot = make_shot(tmp_path / "main", count=4, frames_dir=str(elsewhere / "frames"))
    _expect_rejected(shot, "outside the shot directory")


@needs_ffmpeg
def test_relative_escape_from_shot_dir_is_rejected(tmp_path):
    make_shot(tmp_path / "other", count=4)
    shot = make_shot(tmp_path / "main", count=4, frames_dir="../../../other/shots/shot/frames")
    _expect_rejected(shot, "outside the shot directory")


@needs_ffmpeg
@pytest.mark.parametrize("frame_range", [[5, 2], [1], [1, 2, 3], ["1", "4"], [True, 4], [-1, 4], "1-4"])
def test_invalid_frame_range_is_rejected(tmp_path, frame_range):
    shot = make_shot(tmp_path, count=4, frame_range=frame_range)
    _expect_rejected(shot, "invalid frame_range")


@needs_ffmpeg
@pytest.mark.parametrize("patch, match", [
    ({"fps": 0}, "invalid fps"), ({"fps": 23.976}, "invalid fps"),
    ({"resolution": [160]}, "invalid resolution"), ({"resolution": [0, 90]}, "invalid resolution"),
    ({"shot_id": "../x"}, "invalid shot_id"), ({"frames_dir": ""}, "invalid frames_dir"),
])
def test_invalid_metadata_is_rejected(tmp_path, patch, match):
    shot = make_shot(tmp_path, count=4, **patch)
    _expect_rejected(shot, match)


@needs_ffmpeg
def test_resolution_mismatch_is_rejected(tmp_path):
    shot = make_shot(tmp_path, count=4, resolution=[320, 180])
    _expect_rejected(shot, "different render")


@pytest.mark.parametrize("kw, match", [
    ({"samples": 0}, "--samples"), ({"samples": 201}, "--samples"), ({"cols": 0}, "--cols"),
    ({"cols": 17}, "--cols"), ({"thumb_width": 10}, "--thumb-width"),
])
def test_bad_arguments_are_rejected_before_anything_is_read(tmp_path, kw, match):
    with pytest.raises(ContactSheetError, match=match):
        run(tmp_path / "does_not_exist", **kw)


# ---------------------------------------------------------------------------
# Stale-frame hints
# ---------------------------------------------------------------------------
@needs_ffmpeg
def test_extra_and_old_frames_are_warnings_not_errors(tmp_path):
    shot = make_shot(tmp_path, count=6)
    frames = shot / "frames"
    shutil.copy(frames / "shot_0001.png", frames / "shot_0099.png")
    old = time.time() - 7200
    os.utime(frames / "shot_0003.png", (old, old))
    run(shot)
    warnings = load_report(shot)["warnings"]
    assert any("1 PNG file(s)" in w and "shot_0099.png" in w and "not proof" in w for w in warnings)
    assert any("1 of 6 expected frames are older than spec.json" in w and "[3]" in w
               and "not proof" in w for w in warnings)
    assert load_report(shot)["contact_sheet"]["sampled_frames"] == [1, 2, 3, 4, 5, 6]


@needs_ffmpeg
def test_fresh_frames_have_no_stale_warnings(tmp_path):
    shot = make_shot(tmp_path, count=6)
    run(shot)
    assert load_report(shot)["warnings"] == []


# ---------------------------------------------------------------------------
# Overwrite protection and failure cleanup
# ---------------------------------------------------------------------------
@needs_ffmpeg
def test_existing_output_is_not_overwritten_without_force(tmp_path):
    shot = make_shot(tmp_path, count=8)
    run(shot, samples=4)
    before = (shot / "review" / "frame_report.json").read_text()
    with pytest.raises(ContactSheetError, match="already exists.*--force"):
        run(shot, samples=8)
    assert (shot / "review" / "frame_report.json").read_text() == before

    run(shot, samples=8, force=True)
    assert load_report(shot)["contact_sheet"]["sampled_frames"] == list(range(1, 9))


@needs_ffmpeg
def test_either_existing_output_blocks_overwrite(tmp_path):
    shot = make_shot(tmp_path, count=4)
    (shot / "review").mkdir()
    (shot / "review" / "contact_sheet.png").write_bytes(b"old")
    with pytest.raises(ContactSheetError, match="already exists"):
        run(shot)
    assert (shot / "review" / "contact_sheet.png").read_bytes() == b"old"


@needs_ffmpeg
def test_failed_forced_run_leaves_no_outputs(tmp_path):
    shot = make_shot(tmp_path, count=8)
    run(shot)
    (shot / "frames" / "shot_0005.png").write_bytes(b"not a png")   # undecodable mid-sequence
    # the sheet pass itself must fail (-xerror), not silently drop the frame and shift samples
    with pytest.raises(ContactSheetError, match="contact sheet failed"):
        run(shot, force=True)
    review = shot / "review"
    leftovers = sorted(p.name for p in review.iterdir() if not p.name.endswith(".ffmpeg.log"))
    assert leftovers == []      # old results removed, nothing partial left behind


@needs_ffmpeg
def test_failed_validation_with_force_removes_old_outputs(tmp_path):
    shot = make_shot(tmp_path, count=4)
    run(shot)
    report = json.loads((shot / "build_report.json").read_text())
    report["status"] = "crash"
    (shot / "build_report.json").write_text(json.dumps(report))
    with pytest.raises(ContactSheetError, match="build status"):
        run(shot, force=True)
    assert not (shot / "review" / "contact_sheet.png").exists()
    assert not (shot / "review" / "frame_report.json").exists()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
@needs_ffmpeg
def test_cli_success_prints_json(tmp_path, capsys):
    shot = make_shot(tmp_path, count=6)
    assert main(["--shot-dir", str(shot), "--samples", "3", "--cols", "3",
                 "--thumb-width", "64"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "evidence_written" and out["verdict"] == "evidence_only"
    assert out["sampled_frames"] == [1, 4, 6] and out["sheet_size"] == [192, 36]


@needs_ffmpeg
def test_cli_failure_reports_to_stderr(tmp_path, capsys):
    shot = make_shot(tmp_path, count=4)
    assert main(["--shot-dir", str(shot)]) == 0
    capsys.readouterr()
    assert main(["--shot-dir", str(shot)]) == 1
    err = capsys.readouterr().err
    assert err.startswith("FAILED: ") and "--force" in err
    assert main(["--shot-dir", str(tmp_path / "nope")]) == 1
    assert "shot directory not found" in capsys.readouterr().err


# ===========================================================================
# Final review: failure recovery, environment failures, % paths, report integrity
# ===========================================================================
RESULTS = (cs.SHEET_NAME, cs.REPORT_NAME, cs.SHEET_PARTIAL, cs.REPORT_PARTIAL)


def review_files(shot: Path) -> list[str]:
    review = shot / "review"
    return sorted(p.name for p in review.iterdir()) if review.is_dir() else []


def assert_no_results(shot: Path):
    """Neither a result nor a partial file may survive a failed run."""
    left = [n for n in review_files(shot) if n in RESULTS]
    assert left == [], f"stale/partial output left behind: {left}"


def fake_subprocess(monkeypatch, match, action):
    """Route matching FFmpeg/ffprobe commands to `action`; everything else runs for real."""
    real = subprocess.run

    def fake(cmd, *args, **kwargs):
        return action(cmd) if match(cmd) else real(cmd, *args, **kwargs)
    monkeypatch.setattr(cs.subprocess, "run", fake)


def is_sheet_pass(cmd) -> bool:
    return any("tile=" in str(c) for c in cmd)


def is_analysis_pass(cmd) -> bool:
    return any("signalstats" in str(c) for c in cmd) and "null" in cmd


# --- 1. partial output recovery -------------------------------------------
@needs_ffmpeg
@pytest.mark.parametrize("keep", [cs.SHEET_NAME, cs.REPORT_NAME])
def test_force_when_only_one_output_exists(tmp_path, keep):
    shot = make_shot(tmp_path, count=8)
    run(shot, samples=4)
    other = cs.REPORT_NAME if keep == cs.SHEET_NAME else cs.SHEET_NAME
    (shot / "review" / other).unlink()
    kept = (shot / "review" / keep).read_bytes()

    with pytest.raises(ContactSheetError, match=f"already exists.*{keep}.*--force"):
        run(shot, samples=8)
    assert (shot / "review" / keep).read_bytes() == kept          # untouched without --force
    assert not (shot / "review" / other).exists()

    run(shot, samples=8, force=True)
    rep = load_report(shot)                                         # both regenerated together
    assert rep["contact_sheet"]["sampled_frames"] == list(range(1, 9))
    assert probe(shot / "review" / cs.SHEET_NAME)["width"] == rep["contact_sheet"]["width"]


@needs_ffmpeg
def test_force_with_one_output_and_failing_run_leaves_nothing(tmp_path):
    shot = make_shot(tmp_path, count=8)
    run(shot)
    (shot / "review" / cs.REPORT_NAME).unlink()                     # only the sheet remains
    (shot / "frames" / "shot_0004.png").unlink()
    with pytest.raises(ContactSheetError, match="missing"):
        run(shot, force=True)
    assert_no_results(shot)


@needs_ffmpeg
def test_leftovers_of_an_interrupted_run_are_cleared_even_when_the_new_run_fails(tmp_path):
    shot = make_shot(tmp_path, count=4, status="crash")
    review = shot / "review"
    review.mkdir()
    for name in (cs.SHEET_PARTIAL, cs.REPORT_PARTIAL, cs.SHEET_LOG, cs.ANALYSIS_LOG):
        (review / name).write_text("left by a killed process")
    with pytest.raises(ContactSheetError, match="build status"):
        run(shot)                                                    # no --force needed
    assert review_files(shot) == []


@needs_ffmpeg
def test_sheet_failure_keeps_only_this_attempts_diagnostics(tmp_path):
    shot = make_shot(tmp_path, count=8)
    run(shot)                                       # leaves logs from a successful attempt
    (shot / "frames" / "shot_0005.png").write_bytes(b"not a png")
    with pytest.raises(ContactSheetError) as e:
        run(shot, force=True)
    msg = str(e.value)
    assert "contact sheet failed (exit" in msg and "Invalid" in msg and cs.SHEET_LOG in msg
    assert_no_results(shot)
    # the analysis never ran this time, so its old log must not suggest otherwise
    assert review_files(shot) == [cs.SHEET_LOG]
    assert "Invalid PNG" in (shot / "review" / cs.SHEET_LOG).read_text()


@needs_ffmpeg
def test_analysis_failure_after_successful_sheet_leaves_no_sheet(tmp_path, monkeypatch):
    shot = make_shot(tmp_path, count=8)
    fake_subprocess(monkeypatch, is_analysis_pass, lambda cmd: subprocess.CompletedProcess(
        cmd, 1, "", "simulated analysis failure"))
    with pytest.raises(ContactSheetError, match=r"frame analysis failed \(exit 1\): simulated"):
        run(shot)
    assert_no_results(shot)                         # the finished sheet is discarded too
    assert "simulated analysis failure" in (shot / "review" / cs.ANALYSIS_LOG).read_text()


@needs_ffmpeg
def test_incomplete_analysis_output_is_rejected(tmp_path, monkeypatch):
    shot = make_shot(tmp_path, count=8)
    partial = "".join(f"frame:{n} pts:{n} pts_time:{n / 24}\nlavfi.signalstats.YAVG=100\n"
                      f"lavfi.signalstats.YDIF=1\n" for n in range(5))      # 5 of 8 frames
    fake_subprocess(monkeypatch, is_analysis_pass,
                    lambda cmd: subprocess.CompletedProcess(cmd, 0, partial, ""))
    with pytest.raises(ContactSheetError, match="incomplete: FFmpeg reported 5 of 8 frames"):
        run(shot)
    assert_no_results(shot)


@needs_ffmpeg
def test_analysis_missing_luma_stats_is_rejected(tmp_path, monkeypatch):
    shot = make_shot(tmp_path, count=3)
    out = "".join(f"frame:{n} pts:{n} pts_time:0\nlavfi.signalstats.YAVG=100\n" for n in range(3))
    fake_subprocess(monkeypatch, is_analysis_pass,
                    lambda cmd: subprocess.CompletedProcess(cmd, 0, out, ""))
    with pytest.raises(ContactSheetError, match=r"no luma statistics for frames \[1, 2, 3\]"):
        run(shot)
    assert_no_results(shot)


@needs_ffmpeg
def test_failure_while_publishing_leaves_neither_output(tmp_path, monkeypatch):
    """The sheet is moved into place first; if publishing the report then fails, the sheet
    must be withdrawn so a sheet never appears without its report."""
    shot = make_shot(tmp_path, count=4)
    real_replace = os.replace

    def replace(src, dst):
        if Path(dst).name == cs.REPORT_NAME:
            raise OSError("disk full (simulated)")
        return real_replace(src, dst)
    monkeypatch.setattr(cs.os, "replace", replace)
    with pytest.raises(OSError, match="simulated"):
        run(shot)
    assert_no_results(shot)


# --- 2. FFmpeg missing, timeouts, % paths ----------------------------------
@needs_ffmpeg
def test_missing_ffmpeg_is_reported_with_the_override_to_use(tmp_path, monkeypatch, capsys):
    shot = make_shot(tmp_path, count=4)
    monkeypatch.setattr(config, "FFMPEG_BIN", str(tmp_path / "no_ffmpeg.exe"))
    assert main(["--shot-dir", str(shot)]) == 1
    err = capsys.readouterr().err
    assert err.startswith("FAILED: contact sheet: cannot run") and "no_ffmpeg.exe" in err
    assert "FFMPEG_BIN" in err
    assert_no_results(shot)


@needs_ffmpeg
def test_missing_ffprobe_fails_before_any_output(tmp_path, monkeypatch, capsys):
    shot = make_shot(tmp_path, count=4)
    monkeypatch.setattr(config, "FFPROBE_BIN", str(tmp_path / "no_ffprobe.exe"))
    assert main(["--shot-dir", str(shot)]) == 1
    err = capsys.readouterr().err
    assert "cannot run" in err and "no_ffprobe.exe" in err and "FFPROBE_BIN" in err
    assert not (shot / "review").exists()


@needs_ffmpeg
def test_real_timeout_is_reported(tmp_path, monkeypatch, capsys):
    """A real subprocess timeout (the first ffprobe cannot finish in 1 ms)."""
    shot = make_shot(tmp_path, count=4)
    monkeypatch.setattr(config, "FFMPEG_TIMEOUT_S", 0.001)
    assert main(["--shot-dir", str(shot)]) == 1
    err = capsys.readouterr().err
    assert "timed out after 0.001s" in err and "FFMPEG_TIMEOUT_S" in err
    assert not (shot / "review").exists()


@needs_ffmpeg
@pytest.mark.parametrize("match, label, log", [
    (is_sheet_pass, "contact sheet", cs.SHEET_LOG),
    (is_analysis_pass, "frame analysis", cs.ANALYSIS_LOG),
])
def test_timeout_in_each_pass_is_logged_and_cleaned_up(tmp_path, monkeypatch, match, label, log):
    shot = make_shot(tmp_path, count=6)

    def timeout(cmd):
        raise subprocess.TimeoutExpired(cmd, config.FFMPEG_TIMEOUT_S, output="",
                                        stderr="frame=3 (simulated partial stderr)")
    fake_subprocess(monkeypatch, match, timeout)
    with pytest.raises(ContactSheetError, match=f"{label} timed out") as e:
        run(shot)
    assert log in str(e.value)                       # points the operator at the log
    text = (shot / "review" / log).read_text()
    assert "TIMEOUT after" in text and "simulated partial stderr" in text
    assert_no_results(shot)


@needs_ffmpeg
def test_paths_containing_percent_and_spaces(tmp_path):
    """% in a directory name must not be expanded by FFmpeg's image2 pattern (it is doubled),
    nor by the single-file contact-sheet output (-update 1)."""
    root = tmp_path / "100% done" / "dir %04d %d"
    shot = make_shot(root, start=11, count=10, source=gray_ramp())
    summary = run(shot, samples=4, cols=4, thumb_width=160)
    rep = load_report(shot)
    assert "%" in rep["inputs"]["frames_dir"] and summary["sampled_frames"] == [11, 14, 17, 20]
    sheet = shot / "review" / cs.SHEET_NAME
    assert sheet.is_file() and probe(sheet)["width"] == 640
    for col, frame in enumerate([11, 14, 17, 20]):    # the right frames, in order
        assert region_yavg(sheet, col * 160 + 60, 40, 40, 30) == pytest.approx(
            20 + 10 * (frame - 11), abs=3)
    assert [f["frame"] for f in rep["analysis"]["frames"]] == list(range(11, 21))


# --- 3. report integrity -----------------------------------------------------
@needs_ffmpeg
@pytest.mark.parametrize("start, count, samples, cols", [
    (1, 1, 12, 4), (5, 12, 12, 4), (101, 20, 4, 4), (3, 7, 50, 3), (1, 2, 1, 4),
])
def test_report_internal_consistency(tmp_path, start, count, samples, cols):
    shot = make_shot(tmp_path, start=start, count=count)
    summary = run(shot, samples=samples, cols=cols, thumb_width=64)
    rep = load_report(shot)
    end = start + count - 1
    frames, a, sheet = rep["analysis"]["frames"], rep["analysis"], rep["contact_sheet"]

    assert rep["render"]["frame_range"] == [start, end]
    assert rep["render"]["frame_count"] == count == len(frames)
    assert [f["frame"] for f in frames] == list(range(start, end + 1))
    assert frames[0]["ydif"] is None and frames[0]["scene_score"] is None
    assert all(f["ydif"] is not None and f["scene_score"] is not None for f in frames[1:])

    assert a["summary"]["yavg"]["count"] == count
    for key in ("ydif", "scene_score"):
        s = a["summary"][key]
        if count == 1:
            assert s is None
        else:
            assert s["count"] == count - 1
            by_frame = {f["frame"]: f[key] for f in frames}
            assert by_frame[s["min_frame"]] == s["min"] and by_frame[s["max_frame"]] == s["max"]
            assert s["min"] <= s["median"] <= s["max"]

    picks = sheet["sampled_frames"]
    assert picks == sorted(set(picks)) and picks[0] == start and picks[-1] == end
    assert picks == summary["sampled_frames"]
    columns = min(cols, len(picks))
    assert (sheet["columns"], sheet["rows"]) == (columns, math.ceil(len(picks) / columns))
    assert sheet["width"] == sheet["columns"] * sheet["thumb_width"]
    assert sheet["height"] == sheet["rows"] * sheet["thumb_height"]
    assert {f["frame"] for f in a["flags"]} <= set(range(start, end + 1))
    assert rep["verdict"] == "evidence_only" and rep["human_approval_required"] is True
    assert summary["verdict"] == "evidence_only" and summary["human_approval_required"] is True


def key_paths(obj, prefix="") -> set[str]:
    """Every key path in the report; list items share the path of their list."""
    if isinstance(obj, dict):
        return {prefix} | set().union(*(key_paths(v, f"{prefix}.{k}") for k, v in obj.items()))
    if isinstance(obj, list):
        return {prefix} | (set().union(*(key_paths(v, prefix + "[]") for v in obj)) if obj else set())
    return {prefix}


@needs_ffmpeg
def test_report_structure_is_fixed_across_shots(tmp_path):
    a = make_shot(tmp_path / "a", count=3)
    b = make_shot(tmp_path / "b", start=50, count=30, size=(320, 180))
    run(a), run(b, samples=7, cols=2)
    ra, rb = load_report(a), load_report(b)
    assert list(ra) == ["schema", "shot_id", "verdict", "human_approval_required", "inputs",
                        "render", "contact_sheet", "analysis", "warnings", "tools", "logs"]
    assert list(ra) == list(rb)
    assert list(ra["analysis"]) == list(rb["analysis"])
    assert list(ra["analysis"]["frames"][0]) == ["frame", "yavg", "ydif", "scene_score"]
    # identical key paths (apart from list contents such as flags, which may be empty)
    assert {p for p in key_paths(ra) if "flags[]" not in p} == \
           {p for p in key_paths(rb) if "flags[]" not in p}
    text = (a / "review" / cs.REPORT_NAME).read_text()
    assert text.endswith("}\n") and text == json.dumps(ra, indent=2) + "\n"


@needs_ffmpeg
def test_evidence_only_fields_are_constant_even_with_flags_and_warnings(tmp_path):
    shot = make_shot(tmp_path, count=12)
    ffmpeg_frames(shot / "frames" / "shot_%04d.png", "color=c=black:s=160x90:r=24", 1, 6)
    shutil.copy(shot / "frames" / "shot_0001.png", shot / "frames" / "shot_0200.png")
    run(shot)
    rep = load_report(shot)
    assert rep["analysis"]["flags"] and rep["warnings"]             # evidence of problems...
    assert rep["verdict"] == "evidence_only"                         # ...never becomes a verdict
    assert rep["human_approval_required"] is True
    assert not any("approv" in k and k != "human_approval_required" for k in all_keys(rep))


# --- CLI exit status, diagnostics and leftovers for every failure kind --------
def _corrupt(shot):
    (shot / "frames" / "shot_0003.png").write_bytes(b"junk")


def _drop_frame(shot):
    (shot / "frames" / "shot_0003.png").unlink()


def _crash(shot):
    rep = json.loads((shot / "build_report.json").read_text())
    rep["status"] = "crash"
    rep["error"] = "RuntimeError: boom"
    (shot / "build_report.json").write_text(json.dumps(rep))


@needs_ffmpeg
@pytest.mark.parametrize("breakit, expected", [
    (_drop_frame, "1 of 6 expected frames missing"),
    (_crash, "build status is 'crash', not 'ok': RuntimeError: boom"),
    (_corrupt, "contact sheet failed (exit"),
])
@pytest.mark.parametrize("had_previous_output", [False, True])
def test_cli_failures_exit_1_with_diagnostics_and_no_results(tmp_path, capsys, breakit,
                                                             expected, had_previous_output):
    shot = make_shot(tmp_path, count=6)
    if had_previous_output:
        assert main(["--shot-dir", str(shot)]) == 0
    capsys.readouterr()
    breakit(shot)
    argv = ["--shot-dir", str(shot)] + (["--force"] if had_previous_output else [])
    assert main(argv) == 1
    captured = capsys.readouterr()
    assert captured.out == ""                         # no success JSON on failure
    assert captured.err.startswith("FAILED: ") and expected in captured.err
    assert_no_results(shot)


# --- M2: an incompletely rewritten build report is never accepted -------------------
@needs_ffmpeg
def test_shot_marked_incomplete_is_refused_even_though_the_report_says_ok(tmp_path):
    from workers.blender_job import REPORT_INCOMPLETE
    shot = make_shot(tmp_path, count=4)               # valid frames, report status "ok"
    (shot / REPORT_INCOMPLETE).write_text("camera warning rewrite in progress")
    _expect_rejected(shot, "rewrite of build_report.json failed or was interrupted")


@needs_ffmpeg
def test_incomplete_marker_with_force_removes_old_evidence_and_refuses(tmp_path, capsys):
    from workers.blender_job import REPORT_INCOMPLETE
    shot = make_shot(tmp_path, count=4)
    assert main(["--shot-dir", str(shot)]) == 0               # evidence from a good build
    capsys.readouterr()
    (shot / REPORT_INCOMPLETE).write_text("rewrite failed")
    assert main(["--shot-dir", str(shot), "--force"]) == 1
    assert "failed or was interrupted" in capsys.readouterr().err
    assert_no_results(shot)


# --- Audit P1-1: partial (smoke) renders are never reviewed -----------------------
SMOKE_24 = [1, 8, 9, 16, 17, 24]          # first and last frame of shots 1-8, 9-16, 17-24


def frame_snapshot(shot: Path) -> dict:
    import hashlib
    return {p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in sorted((shot / "frames").glob("*.png"))}


@needs_ffmpeg
def test_smoke_over_stale_full_render_is_refused_before_any_output(tmp_path):
    shot = make_shot(tmp_path, count=24, smoke=True, smoke_frames=SMOKE_24,
                     rendered_frames=SMOKE_24)
    ffmpeg_frames(shot / "frames" / "shot_%04d.png", "color=c=red:s=160x90:r=24", 1, 1)
    before = frame_snapshot(shot)
    assert len(before) == 24                       # every expected file exists: not evidence
    with pytest.raises(ContactSheetError, match=r"Partial \(smoke\) render; not reviewable: 18 "
                                                r"of 24 frames in 1-24 were not rendered"):
        run(shot)
    assert not (shot / "review").exists()          # nothing published, nothing partial
    assert frame_snapshot(shot) == before          # stale frames untouched


@needs_ffmpeg
def test_partial_render_with_force_removes_old_review_and_publishes_nothing(tmp_path, capsys):
    shot = make_shot(tmp_path, count=24)
    assert main(["--shot-dir", str(shot)]) == 0           # review of an earlier full render
    capsys.readouterr()
    rep = json.loads((shot / "build_report.json").read_text())
    rep.update(smoke=True, smoke_frames=SMOKE_24, rendered_frames=SMOKE_24)
    (shot / "build_report.json").write_text(json.dumps(rep))
    before = frame_snapshot(shot)
    assert main(["--shot-dir", str(shot), "--force"]) == 1
    assert "Partial (smoke) render; not reviewable" in capsys.readouterr().err
    assert_no_results(shot)                               # old evidence not left looking current
    assert frame_snapshot(shot) == before


@needs_ffmpeg
@pytest.mark.parametrize("order", ["sorted", "reversed"])
def test_complete_rendered_frames_is_reviewed(tmp_path, order):
    frames = list(range(1, 25)) if order == "sorted" else list(range(24, 0, -1))
    shot = make_shot(tmp_path, count=24, rendered_frames=frames)
    run(shot)
    assert load_report(shot)["render"]["frame_count"] == 24


@needs_ffmpeg
@pytest.mark.parametrize("rendered", [
    [f for f in range(1, 25) if f != 12], list(range(1, 25)) + [12], list(range(1, 26)),
    [], [True] * 24, [str(f) for f in range(1, 25)], [float(f) for f in range(1, 25)],
    "1-24", None,
], ids=["one-missing", "duplicate", "unexpected", "empty", "bools", "strings", "floats",
        "not-a-list", "null"])
def test_malformed_or_incomplete_rendered_frames_are_not_reviewed(tmp_path, rendered):
    shot = make_shot(tmp_path, count=24, rendered_frames=rendered)
    before = frame_snapshot(shot)
    _expect_rejected(shot, r"Partial \(smoke\) render; not reviewable")
    assert frame_snapshot(shot) == before
