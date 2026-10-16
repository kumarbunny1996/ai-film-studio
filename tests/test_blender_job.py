"""workers/blender_job.run_shot without Blender: a fake subprocess writes the build report.

Covers the merging of camera_warnings() into build_report.json (Milestone 3, option (a)) and
how run_shot reports every kind of Blender outcome.
"""
import copy
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from workers import blender_job
from workers.blender_job import REPO, REPORT_INCOMPLETE, REPORT_TMP, run_shot
from workers.contact_sheet import ContactSheetError, load_render

M1 = json.loads((REPO / "schemas/examples/milestone1_primitives.json").read_text())
TEMPLATE_WARNING = "no style template loaded; starting from an empty scene"
ROTATION_WARNING = ("camera: rotation_deg on keys at frames [1] is ignored because look_at "
                    "'pedestal' controls rotation")


def ok_report(**extra) -> dict:
    return {"shot_id": "m1_primitives", "status": "ok", "warnings": [TEMPLATE_WARNING],
            "blender_version": "test", "timings": {"camera": 0.0},
            "camera": {"shift": [0.0, 0.0]}, "memory_mb": None, **extra}


def fake_blender(monkeypatch, report: dict | str | None, returncode: int = 0):
    """Replace the Blender subprocess: write `report` (dict -> JSON, str -> raw text,
    None -> nothing) to --out/build_report.json and exit with `returncode`."""
    calls = []

    def run(cmd, *args, **kwargs):
        calls.append(cmd)
        out = Path(cmd[cmd.index("--out") + 1])
        if report is not None:
            text = report if isinstance(report, str) else json.dumps(report, indent=2)
            (out / "build_report.json").write_text(text)
        return subprocess.CompletedProcess(cmd, returncode)
    monkeypatch.setattr(blender_job.subprocess, "run", run)
    return calls


def with_rotation_conflict() -> dict:
    d = copy.deepcopy(M1)                                 # v1.1, tracks the pedestal
    d["camera"]["keys"][0]["rotation_deg"] = [90, 0, 45]
    return d


def disk_report(tmp_path) -> dict:
    return json.loads((tmp_path / "shots" / "m1_primitives" / "build_report.json").read_text())


def shot(tmp_path) -> Path:
    return tmp_path / "shots" / "m1_primitives"


def assert_marked_incomplete(tmp_path):
    """The on-disk report must not be usable as a successful, complete build record."""
    assert (shot(tmp_path) / REPORT_INCOMPLETE).is_file()
    assert not (shot(tmp_path) / REPORT_TMP).exists()
    with pytest.raises(ContactSheetError, match="build_report.json failed or was interrupted"):
        load_render(shot(tmp_path))                    # the downstream acceptance path refuses


def assert_clean_success(tmp_path):
    assert not (shot(tmp_path) / REPORT_INCOMPLETE).exists()
    assert not (shot(tmp_path) / REPORT_TMP).exists()


# ---------------------------------------------------------------------------
def test_legacy_camera_warning_is_merged_in_memory_and_on_disk(tmp_path, monkeypatch):
    fake_blender(monkeypatch, ok_report())
    report = run_shot(with_rotation_conflict(), tmp_path, render=False)
    assert report["status"] == "ok"
    assert report["warnings"] == [TEMPLATE_WARNING, ROTATION_WARNING]   # builder's first
    on_disk = disk_report(tmp_path)
    assert on_disk["warnings"] == [TEMPLATE_WARNING, ROTATION_WARNING]
    assert {k: v for k, v in on_disk.items() if k != "warnings"} == \
           {k: v for k, v in ok_report().items() if k != "warnings"}      # nothing else changed
    assert "returncode" not in on_disk and "log" not in on_disk          # in-memory only, as before
    assert report["returncode"] == 0 and report["log"].endswith("blender.log")


def test_dof_without_focus_warning_is_merged(tmp_path, monkeypatch):
    d = copy.deepcopy(M1)
    d["camera"].pop("look_at")
    d["camera"]["dof_enabled"], d["camera"]["fstop"] = True, 8.0
    for k in d["camera"]["keys"]:
        k["rotation_deg"] = [80, 0, 0]
    fake_blender(monkeypatch, ok_report())
    report = run_shot(d, tmp_path, render=False)
    assert report["warnings"][1].startswith("camera: dof_enabled with no look_at or focus_target; "
                                            "fstop 8.0 is not applied")


@pytest.mark.parametrize("spec", [M1, {**copy.deepcopy(M1), "spec_version": "1.2"}],
                         ids=["clean-1.1", "clean-1.2"])
def test_report_left_byte_identical_when_there_is_nothing_to_merge(tmp_path, monkeypatch, spec):
    fake_blender(monkeypatch, ok_report())
    report = run_shot(spec, tmp_path, render=False)
    written = json.dumps(ok_report(), indent=2)
    assert (tmp_path / "shots/m1_primitives/build_report.json").read_text() == written
    assert report["warnings"] == [TEMPLATE_WARNING]


def test_merge_does_not_duplicate_existing_warnings(tmp_path, monkeypatch):
    fake_blender(monkeypatch, ok_report(warnings=[TEMPLATE_WARNING, ROTATION_WARNING]))
    report = run_shot(with_rotation_conflict(), tmp_path, render=False)
    assert report["warnings"] == [TEMPLATE_WARNING, ROTATION_WARNING]


@pytest.mark.parametrize("status, returncode", [("spec_error", 1), ("crash", 1), ("ok", 1)])
def test_no_merge_unless_the_build_succeeded(tmp_path, monkeypatch, status, returncode):
    raw = ok_report(status=status, error="boom")
    fake_blender(monkeypatch, raw, returncode)
    report = run_shot(with_rotation_conflict(), tmp_path, render=False)
    assert report["status"] == status and report["returncode"] == returncode
    assert ROTATION_WARNING not in report["warnings"]
    assert disk_report(tmp_path) == raw                       # disk untouched


def test_missing_report_is_a_crash(tmp_path, monkeypatch):
    fake_blender(monkeypatch, None, returncode=3221225477)
    report = run_shot(M1, tmp_path, render=False)
    assert report["status"] == "crash"
    assert report["error"] == "Blender exited 3221225477 without a report"


@pytest.mark.parametrize("raw, match", [("{not json", "unreadable build_report.json"),
                                        ("[1, 2]", "is not a JSON object")])
def test_unreadable_report_is_a_crash_not_an_exception(tmp_path, monkeypatch, raw, match):
    fake_blender(monkeypatch, raw)
    report = run_shot(M1, tmp_path, render=False)
    assert report["status"] == "crash" and match in report["error"]


def test_failure_to_persist_warnings_is_reported(tmp_path, monkeypatch):
    fake_blender(monkeypatch, ok_report())
    fake = blender_job.subprocess.run
    report_file = tmp_path / "shots" / "m1_primitives" / "build_report.json"

    def run_then_lock(cmd, *a, **kw):                  # Blender writes, then the file is locked
        proc = fake(cmd, *a, **kw)
        os.chmod(report_file, stat.S_IREAD)            # a real OS-level write failure follows
        return proc
    monkeypatch.setattr(blender_job.subprocess, "run", run_then_lock)
    try:
        report = run_shot(with_rotation_conflict(), tmp_path, render=False)
    finally:
        os.chmod(report_file, stat.S_IREAD | stat.S_IWRITE)
    assert report["status"] == "report_error"
    assert "could not write camera warnings" in report["error"]
    assert ROTATION_WARNING in report["warnings"]       # still visible to the caller
    assert disk_report(tmp_path) == ok_report()          # original kept intact, not truncated
    assert_marked_incomplete(tmp_path)


def test_report_error_fails_the_milestone_pipeline(tmp_path, monkeypatch):
    from workers import run_milestone1
    monkeypatch.setattr(run_milestone1, "run_shot", lambda *a, **k: {
        "status": "report_error", "error": "could not write", "returncode": 0, "log": "x.log"})
    with pytest.raises(run_milestone1.PipelineError, match="report_error"):
        run_milestone1.run(REPO / "schemas/examples/milestone1_primitives.json", tmp_path)


def test_v12_dof_requirement_is_enforced_before_blender_runs(tmp_path, monkeypatch):
    calls = fake_blender(monkeypatch, ok_report())
    d = copy.deepcopy(M1)
    d["spec_version"] = "1.2"
    d["camera"].pop("look_at")
    d["camera"]["dof_enabled"] = True
    for k in d["camera"]["keys"]:
        k["rotation_deg"] = [80, 0, 0]
    with pytest.raises(ValidationError, match="dof_enabled needs something to focus on"):
        run_shot(d, tmp_path, render=False)
    assert calls == [] and not (tmp_path / "shots").exists()


# ===========================================================================
# M2: a failed report rewrite must never leave a report that looks successful
# ===========================================================================
def test_successful_merge_leaves_no_marker_and_the_same_bytes_as_before(tmp_path, monkeypatch):
    fake_blender(monkeypatch, ok_report())
    report = run_shot(with_rotation_conflict(), tmp_path, render=False)
    assert report["status"] == "ok"
    expected = {**ok_report(), "warnings": [TEMPLATE_WARNING, ROTATION_WARNING]}
    assert (shot(tmp_path) / "build_report.json").read_text() == json.dumps(expected, indent=2)
    assert_clean_success(tmp_path)


def test_replace_failure_keeps_the_original_and_marks_it_incomplete(tmp_path, monkeypatch):
    fake_blender(monkeypatch, ok_report())

    def replace(src, dst):
        raise PermissionError(5, "Access is denied (simulated)")
    monkeypatch.setattr(blender_job.os, "replace", replace)
    report = run_shot(with_rotation_conflict(), tmp_path, render=False)
    assert report["status"] == "report_error"
    assert "Access is denied (simulated)" in report["error"]
    assert f"{REPORT_INCOMPLETE} marks the on-disk report as incomplete" in report["error"]
    assert disk_report(tmp_path) == ok_report()          # original untouched
    assert_marked_incomplete(tmp_path)


def test_temp_write_failure_keeps_the_original_and_marks_it_incomplete(tmp_path, monkeypatch):
    fake_blender(monkeypatch, ok_report())

    def write(path, text):
        raise OSError(28, "No space left on device (simulated)")
    monkeypatch.setattr(blender_job, "_write_durably", write)
    report = run_shot(with_rotation_conflict(), tmp_path, render=False)
    assert report["status"] == "report_error" and "No space left" in report["error"]
    assert disk_report(tmp_path) == ok_report()
    assert_marked_incomplete(tmp_path)


def test_report_held_open_by_another_process(tmp_path, monkeypatch):
    """A real lock: on Windows an open handle blocks both replacing and renaming the report.
    Whatever the platform does, the disk must not show a complete-looking stale report."""
    fake_blender(monkeypatch, ok_report())
    fake = blender_job.subprocess.run
    handles = []

    def run_then_open(cmd, *a, **kw):
        proc = fake(cmd, *a, **kw)
        handles.append(open(shot(tmp_path) / "build_report.json"))   # e.g. a viewer or scanner
        return proc
    monkeypatch.setattr(blender_job.subprocess, "run", run_then_open)
    try:
        report = run_shot(with_rotation_conflict(), tmp_path, render=False)
    finally:
        for h in handles:
            h.close()
    if report["status"] == "ok":                          # platforms that allow the replace
        assert ROTATION_WARNING in disk_report(tmp_path)["warnings"]
        assert_clean_success(tmp_path)
    else:                                                 # Windows
        assert report["status"] == "report_error"
        assert disk_report(tmp_path) == ok_report()
        assert_marked_incomplete(tmp_path)


def test_marker_creation_failure_is_reported_with_its_limitation(tmp_path, monkeypatch):
    """If even the marker can't be created, nothing on disk is touched and the error says
    plainly that the report may still read 'ok' (the documented limitation)."""
    fake_blender(monkeypatch, ok_report())
    real_write_text = Path.write_text

    def write_text(self, *a, **kw):
        if self.name == REPORT_INCOMPLETE:
            raise PermissionError(5, "Access is denied (simulated)")
        return real_write_text(self, *a, **kw)
    monkeypatch.setattr(Path, "write_text", write_text)
    report = run_shot(with_rotation_conflict(), tmp_path, render=False)
    assert report["status"] == "report_error"
    assert "may still read status 'ok'" in report["error"]
    assert disk_report(tmp_path) == ok_report()
    assert not (shot(tmp_path) / REPORT_TMP).exists()
    assert not (shot(tmp_path) / REPORT_INCOMPLETE).exists()


def test_marker_removal_failure_keeps_the_shot_marked(tmp_path, monkeypatch):
    fake_blender(monkeypatch, ok_report())
    real_unlink = Path.unlink

    def unlink(self, *a, **kw):
        if self.name == REPORT_INCOMPLETE and (self.parent / "build_report.json").exists():
            raise PermissionError(32, "being used by another process (simulated)")
        return real_unlink(self, *a, **kw)
    monkeypatch.setattr(Path, "unlink", unlink)
    report = run_shot(with_rotation_conflict(), tmp_path, render=False)
    assert report["status"] == "report_error" and "could not be removed" in report["error"]
    assert ROTATION_WARNING in disk_report(tmp_path)["warnings"]     # the rewrite itself worked
    assert (shot(tmp_path) / REPORT_INCOMPLETE).is_file()            # but stays fail-safe
    with pytest.raises(ContactSheetError, match="failed or was interrupted"):
        load_render(shot(tmp_path))


def test_interrupted_rewrite_leaves_the_marker(tmp_path, monkeypatch):
    """A crash or Ctrl+C between writing the temp file and replacing the report."""
    fake_blender(monkeypatch, ok_report())

    def replace(src, dst):
        raise KeyboardInterrupt
    monkeypatch.setattr(blender_job.os, "replace", replace)
    with pytest.raises(KeyboardInterrupt):
        run_shot(with_rotation_conflict(), tmp_path, render=False)
    assert disk_report(tmp_path) == ok_report()
    assert (shot(tmp_path) / REPORT_INCOMPLETE).is_file()
    with pytest.raises(ContactSheetError, match="failed or was interrupted"):
        load_render(shot(tmp_path))


def test_next_build_clears_leftovers_of_a_failed_rewrite(tmp_path, monkeypatch):
    d = shot(tmp_path)
    d.mkdir(parents=True)
    (d / REPORT_INCOMPLETE).write_text("left by an earlier failed rewrite")
    (d / REPORT_TMP).write_text("{}")
    fake_blender(monkeypatch, ok_report())
    report = run_shot(M1, tmp_path, render=False)              # clean spec: nothing to merge
    assert report["status"] == "ok"
    assert_clean_success(tmp_path)


def test_no_marker_when_there_is_nothing_to_merge(tmp_path, monkeypatch):
    fake_blender(monkeypatch, ok_report())
    run_shot(M1, tmp_path, render=False)
    assert_clean_success(tmp_path)


# ===========================================================================
# Milestone 4: shot_warnings() merged with camera_warnings()
# ===========================================================================
M4 = json.loads((REPO / "schemas/examples/m4_sequence.json").read_text())
SHORT_SHOT_WARNING = ("shot 'sh01_wide' is 8 frame(s) long (frames 1-8); shots under 12 "
                      "frames are very short")


def with_short_first_shot() -> dict:
    d = copy.deepcopy(M4)
    d["shots"][0]["frame_end"] = 8
    d["shots"][0]["camera"]["keys"][1]["frame"] = 8
    d["shots"][1]["frame_start"] = 9
    d["shots"][1]["camera"]["keys"][0]["frame"] = 9
    return d


def m4_report(tmp_path) -> dict:
    return json.loads((tmp_path / "shots" / "m4_sequence" / "build_report.json").read_text())


def test_shot_warning_is_merged_in_memory_and_on_disk(tmp_path, monkeypatch):
    fake_blender(monkeypatch, ok_report(shot_id="m4_sequence"))
    report = run_shot(with_short_first_shot(), tmp_path, render=False)
    assert report["status"] == "ok"
    assert report["warnings"] == [TEMPLATE_WARNING, SHORT_SHOT_WARNING]
    assert m4_report(tmp_path)["warnings"] == [TEMPLATE_WARNING, SHORT_SHOT_WARNING]
    assert not (tmp_path / "shots" / "m4_sequence" / REPORT_INCOMPLETE).exists()


def test_shot_warning_is_not_duplicated(tmp_path, monkeypatch):
    fake_blender(monkeypatch, ok_report(shot_id="m4_sequence",
                                        warnings=[TEMPLATE_WARNING, SHORT_SHOT_WARNING]))
    report = run_shot(with_short_first_shot(), tmp_path, render=False)
    assert report["warnings"] == [TEMPLATE_WARNING, SHORT_SHOT_WARNING]


def test_clean_multishot_spec_leaves_the_report_byte_identical(tmp_path, monkeypatch):
    fake_blender(monkeypatch, ok_report(shot_id="m4_sequence"))
    report = run_shot(M4, tmp_path, render=False)
    assert report["warnings"] == [TEMPLATE_WARNING]
    written = json.dumps(ok_report(shot_id="m4_sequence"), indent=2)
    assert (tmp_path / "shots" / "m4_sequence" / "build_report.json").read_text() == written


def test_camera_warnings_come_before_shot_warnings(tmp_path, monkeypatch):
    """camera_warnings() only fires for 1.0/1.1 and shot_warnings() only for 1.3, so the two
    never meet in one valid spec; the merge order is still camera first, then shots."""
    monkeypatch.setattr(blender_job, "camera_warnings", lambda s: ["cam w", "dup"])
    monkeypatch.setattr(blender_job, "shot_warnings", lambda s: ["dup", "shot w"])
    fake_blender(monkeypatch, ok_report(shot_id="m4_sequence"))
    report = run_shot(M4, tmp_path, render=False)
    assert report["warnings"] == [TEMPLATE_WARNING, "cam w", "dup", "shot w"]   # deduplicated


def test_shot_warning_merge_failure_uses_the_incomplete_marker(tmp_path, monkeypatch):
    fake_blender(monkeypatch, ok_report(shot_id="m4_sequence"))

    def replace(src, dst):
        raise PermissionError(5, "Access is denied (simulated)")
    monkeypatch.setattr(blender_job.os, "replace", replace)
    report = run_shot(with_short_first_shot(), tmp_path, render=False)
    assert report["status"] == "report_error"
    assert SHORT_SHOT_WARNING not in m4_report(tmp_path)["warnings"]
    assert (tmp_path / "shots" / "m4_sequence" / REPORT_INCOMPLETE).is_file()
    with pytest.raises(ContactSheetError, match="failed or was interrupted"):
        load_render(tmp_path / "shots" / "m4_sequence")
