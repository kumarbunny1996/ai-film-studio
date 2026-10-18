"""Milestone 9 Gate 2: workers/assemble_film.py on small H.264 clips made with FFmpeg.

Clips are encoded once per session with the settings of workers/encode.py (libx264 veryfast,
crf 23, yuv420p, +faststart) at 160x96, each with its own hue so frame order is checkable,
plus one variant per incompatibility. Every test builds its own fake repository in tmp_path
(storage/projects/src/<clip>.mp4 with the summary.json run_milestone1 would write) and
assembles into it, so nothing outside tmp_path is read or written. FFmpeg and verification
failures inside the assembly are simulated with monkeypatch.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from workers import assemble_film as A
from workers import config
from workers.encode import probe

pytestmark = pytest.mark.skipif(shutil.which(config.FFMPEG_BIN) is None, reason="FFmpeg not found")

ROOT = Path(__file__).resolve().parents[1]
X264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p"]
VARIANTS = {   # name: (frames, extra input args, output args)
    "a": (24, [], X264), "b": (12, [], X264),
    "size": (12, [], X264 + ["-s", "176x96"]),
    "fps": (12, [], X264 + ["-r", "25"]),
    "pix": (12, [], ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv444p"]),
    "codec": (12, [], ["-c:v", "mpeg4", "-pix_fmt", "yuv420p"]),
    "timebase": (12, [], X264 + ["-video_track_timescale", "1000"]),
    "sar": (12, [], X264 + ["-aspect", "2:1"]),
    "params": (12, [], X264 + ["-x264-params", "ref=3"]),
    "audio": (12, ["-f", "lavfi", "-i", "sine=frequency=440:duration=1"],
              X264 + ["-map", "0:v", "-map", "1:a", "-c:a", "aac", "-shortest"]),
    "two_video": (12, [], X264 + ["-map", "0:v", "-map", "0:v"]),
}
HUES = {"a": 0, "b": 120}


@pytest.fixture(scope="session")
def clip_cache(tmp_path_factory):
    d = tmp_path_factory.mktemp("clips")
    for name, (frames, extra_in, out_args) in VARIANTS.items():
        rate = 25 if name == "fps" else 24
        src = f"testsrc2=size=160x96:rate={rate},hue=h={HUES.get(name, 240)}"
        subprocess.run([config.FFMPEG_BIN, "-v", "error", "-f", "lavfi", "-i", src, *extra_in,
                        "-frames:v", str(frames), *out_args, "-movflags", "+faststart",
                        str(d / f"{name}.mp4")], check=True)
    return d


def summary_for(mp4: Path, rel: str) -> dict:
    return {"ok": True, "errors": [], "mp4": rel.replace("/", "\\"), "video": probe(mp4)}


class Repo:
    """A fake repository with clips under storage/projects/src/."""

    def __init__(self, root: Path, cache: Path):
        self.root, self.cache = root, cache
        (root / "storage/projects/src").mkdir(parents=True)

    def add(self, name: str, as_name: str | None = None, summary: bool = True) -> str:
        rel = f"storage/projects/src/{as_name or name}.mp4"
        dst = self.root / rel
        shutil.copyfile(self.cache / f"{name}.mp4", dst)
        if summary:
            dst.with_name(dst.stem + ".summary.json").write_text(json.dumps(summary_for(dst, rel)))
        return rel

    def edit(self, clips, film_id="reel", **fmt) -> Path:
        d = {"edit_version": "1.0", "film_id": film_id,
             "format": {"codec": "h264", "pix_fmt": "yuv420p", "width": 160, "height": 96, "fps": 24,
                        "audio": "none", **fmt},
             "clips": [{"clip_id": cid, "source": rel, "sha256": A.sha256(self.root / rel),
                        "frames": probe(self.root / rel)["frames"]} for cid, rel in clips]}
        path = self.root.parent / f"{film_id}.edit.json"
        path.write_text(json.dumps(d, indent=2))
        return path

    def film(self, film_id="reel") -> Path:
        return self.root / "storage/projects" / film_id

    def snapshot(self) -> dict:
        return {p.relative_to(self.root).as_posix(): (A.sha256(p) if p.is_file() else "dir")
                for p in sorted(self.root.rglob("*"))}


@pytest.fixture
def repo(tmp_path, clip_cache):
    return Repo(tmp_path / "repo", clip_cache)


def fails(edit_path, repo, stage, *needles):
    """Assembly fails at `stage` with every needle in the errors, and nothing is written."""
    before = repo.snapshot()
    with pytest.raises(A.AssemblyError) as e:
        A.assemble(edit_path, repo.root)
    assert e.value.stage == stage, (e.value.stage, e.value.errors)
    text = "\n".join(e.value.errors)
    for n in needles:
        assert n in text, text
    assert str(repo.root) not in json.dumps(A.failure_report(e.value)), "no local paths in diagnostics"
    assert repo.snapshot() == before, "a failed assembly leaves the repository exactly as it was"
    return e.value


# ---------------------------------------------------------------------------------------------
# Success
# ---------------------------------------------------------------------------------------------
def test_two_clips_are_joined_in_order_without_reencoding(repo):
    a, b = repo.add("a"), repo.add("b")
    edit = repo.edit([("sc01", a), ("sc02", b)])
    before = {r: A.sha256(repo.root / r) for r in (a, b)}
    report = A.assemble(edit, repo.root)
    film = repo.film()
    assert sorted(p.name for p in film.iterdir()) == ["reel.assembly.ffmpeg.log", "reel.assembly.json", "reel.mp4"]
    assert report == json.loads((film / "reel.assembly.json").read_text())
    assert report["status"] == "verified" and report["human_approval_required"] is True
    assert report["total_frames"] == 36 and report["expected_duration_s"] == 1.5
    assert [(c["clip_id"], c["film_frames"], c["start_s"], c["end_s"]) for c in report["clips"]] == \
        [("sc01", [1, 24], 0.0, 1.0), ("sc02", [25, 36], 1.0, 1.5)]
    out = probe(film / "reel.mp4")
    assert (out["frames"], out["width"], out["height"], out["codec"], out["duration_s"]) == (36, 160, 96, "h264", 1.5)
    assert A.frame_md5s(film / "reel.mp4") == A.frame_md5s(repo.root / a) + A.frame_md5s(repo.root / b)
    assert report["output"]["sha256"] == A.sha256(film / "reel.mp4")
    assert {r: A.sha256(repo.root / r) for r in (a, b)} == before, "sources untouched"
    assert report["edit_list"]["sha256"] == A.sha256(edit) and report["edit_list"]["film_id"] == "reel"
    assert report["clips"][0]["summary"]["path"] == "storage/projects/src/a.summary.json"
    assert "<workspace>" in " ".join(report["ffmpeg"]["command"]) and "-c" in report["ffmpeg"]["command"]
    assert "-y" not in report["ffmpeg"]["command"] and "-n" in report["ffmpeg"]["command"]
    assert str(repo.root) not in json.dumps(report), "no checkout-specific paths in the report"


def test_identical_inputs_give_identical_films_and_reports(tmp_path, clip_cache):
    results = []
    for name in ("one", "two"):
        r = Repo(tmp_path / name / "repo", clip_cache)
        report = A.assemble(r.edit([("sc01", r.add("a")), ("sc02", r.add("b"))]), r.root)
        results.append(((r.film() / "reel.mp4").read_bytes(), report,
                        (r.film() / "reel.assembly.ffmpeg.log").read_text(encoding="utf-8")))
    assert results[0][0] == results[1][0]
    assert {**results[0][1], "edit_list": None} == {**results[1][1], "edit_list": None}
    assert results[0][2] == results[1][2], "the log holds no run-specific paths or addresses"
    assert "<addr>]" in results[0][2] and str(tmp_path) not in results[0][2]


def test_the_same_source_may_repeat_under_different_ids(repo):
    a, b = repo.add("a"), repo.add("b")
    report = A.assemble(repo.edit([("sc01", a), ("sc02", b), ("sc03", a)]), repo.root)
    assert report["total_frames"] == 60 and report["clips"][2]["film_frames"] == [37, 60]
    md5 = A.frame_md5s(repo.root / a)
    assert A.frame_md5s(repo.film() / "reel.mp4") == md5 + A.frame_md5s(repo.root / b) + md5


def test_an_existing_film_directory_keeps_its_other_files(repo):
    keep = repo.film() / "notes.txt"
    keep.parent.mkdir(parents=True)
    keep.write_text("mine")
    A.assemble(repo.edit([("sc01", repo.add("a"))]), repo.root)
    assert keep.read_text() == "mine"
    assert sorted(p.name for p in repo.film().iterdir()) == \
        ["notes.txt", "reel.assembly.ffmpeg.log", "reel.assembly.json", "reel.mp4"]


def test_cli_prints_success_and_structured_failure(repo, capsys, monkeypatch):
    monkeypatch.setattr(A, "REPO", repo.root)
    monkeypatch.setattr(A.assemble, "__defaults__", (repo.root,))
    edit = repo.edit([("sc01", repo.add("a"))])
    assert A.main(["--edit", str(edit)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"status": "verified", "film": "storage/projects/reel/reel.mp4",
                   "report": "storage/projects/reel/reel.assembly.json", "total_frames": 24, "duration_s": 1.0}
    assert A.main(["--edit", str(edit)]) == 1
    cap = capsys.readouterr()
    failure = json.loads(cap.out)
    assert failure["status"] == "failed" and failure["stage"] == "outputs" and failure["published"] is False
    assert "FAILED: mp4 already exists" in cap.err


# ---------------------------------------------------------------------------------------------
# The edit list and paths
# ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("source, needle", [
    ("storage/projects/../projects/src/a.mp4", "source"), ("C:/x/a.mp4", "source"),
    ("/storage/projects/src/a.mp4", "source"), ("storage/projects/reel/a.mp4", "output folder"),
])
def test_unsafe_sources_and_self_reference_are_rejected(repo, source, needle):
    a = repo.add("a")
    edit = repo.edit([("sc01", a)])
    d = json.loads(edit.read_text())
    d["clips"][0]["source"] = source
    edit.write_text(json.dumps(d))
    fails(edit, repo, "edit_list", needle)


def test_duplicate_clip_ids_and_unknown_fields_are_rejected(repo):
    a = repo.add("a")
    edit = repo.edit([("sc01", a), ("sc01", a)])
    fails(edit, repo, "edit_list", "duplicate clip_id")
    d = json.loads(edit.read_text())
    d["clips"] = d["clips"][:1]
    d["transitions"] = "crossfade"
    edit.write_text(json.dumps(d))
    fails(edit, repo, "edit_list", "transitions")
    edit.write_text("{not json")
    fails(edit, repo, "edit_list")


def test_missing_source_is_rejected(repo):
    a = repo.add("a")
    edit = repo.edit([("sc01", a)])
    (repo.root / a).unlink()
    fails(edit, repo, "sources", "source not found")


def test_a_junction_escaping_storage_is_rejected(repo, tmp_path, clip_cache):
    _winapi = pytest.importorskip("_winapi")
    outside = tmp_path / "outside"
    outside.mkdir()
    shutil.copyfile(clip_cache / "a.mp4", outside / "a.mp4")
    _winapi.CreateJunction(str(outside), str(repo.root / "storage/projects/linked"))
    rel = "storage/projects/linked/a.mp4"
    edit = repo.edit([("sc01", rel)])
    fails(edit, repo, "sources", "escape")


# ---------------------------------------------------------------------------------------------
# Hashes and summaries
# ---------------------------------------------------------------------------------------------
def test_hash_mismatch_reports_the_current_hash_and_never_edits_the_edit_list(repo):
    a = repo.add("a")
    edit = repo.edit([("sc01", a)])
    pinned = edit.read_text()
    with (repo.root / a).open("ab") as f:              # the source changed after approval
        f.write(b"\0")
    e = fails(edit, repo, "sources", "SHA-256 mismatch", A.sha256(repo.root / a), "update the edit list by hand")
    assert edit.read_text() == pinned
    assert len(e.errors) == 1


@pytest.mark.parametrize("mutate, needle", [
    (None, "no approved summary"),
    ("{broken", "unreadable summary"),
    ([], "not a JSON object"),
    ({"ok": False}, "is not approved"),
    ({"ok": "true"}, "is not approved"),
    ({"errors": ["frames: expected 24, got 23"]}, "is not approved"),
    ({"mp4": "storage\\projects\\src\\b.mp4"}, "describes"),
    ({"video": None}, "no video block"),
    ({"video": {"frames": 23}}, "video.frames is 23 but ffprobe reports 24"),
    ({"video": {"fps": 25.0}}, "video.fps"),
    ({"video": {"width": 320}}, "video.width"),
])
def test_summary_must_approve_this_exact_file(repo, mutate, needle):
    a = repo.add("a")
    repo.add("b")
    edit = repo.edit([("sc01", a)])
    path = repo.root / "storage/projects/src/a.summary.json"
    if mutate is None:
        path.unlink()
    elif isinstance(mutate, str):
        path.write_text(mutate)
    elif isinstance(mutate, list):
        path.write_text(json.dumps(mutate))
    else:
        s = json.loads(path.read_text())
        for k, v in mutate.items():
            s[k] = {**s[k], **v} if isinstance(v, dict) and isinstance(s.get(k), dict) else v
        path.write_text(json.dumps(s))
    fails(edit, repo, "sources", needle)


def test_declared_frame_count_must_match_the_decoded_count(repo):
    a = repo.add("a")
    edit = repo.edit([("sc01", a)])
    d = json.loads(edit.read_text())
    d["clips"][0]["frames"] = 25
    edit.write_text(json.dumps(d))
    fails(edit, repo, "sources", "decoded 24 frames, the edit list declares 25")


# ---------------------------------------------------------------------------------------------
# Format and stream-copy compatibility
# ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("variant, needles", [
    ("size", ["width is 176"]),
    ("fps", ["r_frame_rate is '25/1'"]),
    ("pix", ["pix_fmt is 'yuv444p'"]),
    ("codec", ["codec_name is 'mpeg4'"]),
    ("timebase", ["time_base is '1/1000' but sc01 has '1/12288'"]),
    ("sar", ["sample_aspect_ratio is"]),
    ("params", ["extradata_hash is"]),
    ("audio", ["found ['video', 'audio']"]),
    ("two_video", ["found ['video', 'video']"]),
])
def test_incompatible_clips_are_refused_before_ffmpeg_runs(repo, monkeypatch, variant, needles):
    a, other = repo.add("a"), repo.add(variant)
    edit = repo.edit([("sc01", a), ("sc02", other)])
    monkeypatch.setattr(A, "_concat", lambda *_: pytest.fail("FFmpeg must not run"))
    e = fails(edit, repo, "sources", *needles)
    assert all(err.startswith("clips[sc02]") for err in e.errors), e.errors


def test_the_declared_format_is_enforced_on_every_clip(repo):
    a = repo.add("a")
    fails(repo.edit([("sc01", a)], fps=25), repo, "sources", "r_frame_rate is '24/1'", "'25/1'")
    fails(repo.edit([("sc01", a)], width=320, height=180), repo, "sources", "width is 160", "height is 96")


def test_every_bad_clip_is_reported_at_once(repo):
    a, size, pix = repo.add("a"), repo.add("size"), repo.add("pix")
    e = fails(repo.edit([("sc01", a), ("sc02", size), ("sc03", pix)]), repo, "sources")
    assert {err.split(":")[0] for err in e.errors} == {"clips[sc02]", "clips[sc03]"}


# ---------------------------------------------------------------------------------------------
# Outputs: no overwrite, atomic publication, cleanup
# ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["reel.mp4", "reel.assembly.json", "reel.assembly.ffmpeg.log"])
def test_any_existing_output_is_refused_and_kept(repo, name):
    edit = repo.edit([("sc01", repo.add("a"))])
    existing = repo.film() / name
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"user-owned")
    fails(edit, repo, "outputs", "already exists, refusing to overwrite")
    assert existing.read_bytes() == b"user-owned"


def test_a_second_run_never_replaces_the_first(repo):
    edit = repo.edit([("sc01", repo.add("a"))])
    A.assemble(edit, repo.root)
    fails(edit, repo, "outputs", "mp4 already exists", "report already exists", "log already exists")


def test_a_film_directory_that_is_a_link_is_refused(repo):
    _winapi = pytest.importorskip("_winapi")
    a = repo.add("a")
    edit = repo.edit([("sc01", a)])
    _winapi.CreateJunction(str(repo.root / "storage/projects/src"), str(repo.film()))
    fails(edit, repo, "outputs", "film directory is a link")


def test_a_source_reaching_the_film_folder_through_a_link_is_refused(repo, clip_cache):
    _winapi = pytest.importorskip("_winapi")
    repo.film().mkdir(parents=True)
    shutil.copyfile(clip_cache / "a.mp4", repo.film() / "old.mp4")
    _winapi.CreateJunction(str(repo.film()), str(repo.root / "storage/projects/alias"))
    edit = repo.edit([("sc01", "storage/projects/alias/old.mp4")])
    fails(edit, repo, "sources", "resolves into the film's own output folder")


def test_sources_are_rehashed_after_assembly(repo, monkeypatch):
    a = repo.add("a")
    edit = repo.edit([("sc01", a)])
    real = A.verify_film

    def mutate_after(*args):
        result = real(*args)
        with (repo.root / a).open("ab") as f:
            f.write(b"\0")
        return result
    monkeypatch.setattr(A, "verify_film", mutate_after)
    with pytest.raises(A.AssemblyError) as e:
        A.assemble(edit, repo.root)
    assert e.value.stage == "verify" and "sources changed during assembly: ['sc01']" in e.value.errors[0]
    assert not repo.film().exists()


def test_report_records_the_rehash(repo):
    a = repo.add("a")
    report = A.assemble(repo.edit([("sc01", a)]), repo.root)
    assert report["clips"][0]["sha256_after"] == A.sha256(repo.root / a) == report["clips"][0]["sha256"]


def test_diagnostics_hide_local_paths_and_addresses(tmp_path):
    text = (f"[mov,mp4,m4a @ 000001c6069816c0] open {tmp_path / 'ws' / 'x'} from {tmp_path / 'repo'}\n"
            "24 fps, 24 tbr\nframe=  708 fps=0.0 q=-1.0 time=00:00:29.41 speed=1.93e+03x elapsed=0:00:00.01")
    assert A._anon(text, (tmp_path / "ws", "<workspace>"), (tmp_path / "repo", "<repo>")) == \
        (f"[mov,mp4,m4a @ <addr>] open <workspace>{os.sep}x from <repo>\n"
         "24 fps, 24 tbr\nframe=  708 fps=<run> q=-1.0 time=00:00:29.41 speed=<run> elapsed=<run>")


def test_film_path_that_is_a_file_is_refused(repo):
    edit = repo.edit([("sc01", repo.add("a"))])
    repo.film().write_text("not a directory")
    fails(edit, repo, "outputs", "not a directory")


def test_ffmpeg_failure_publishes_nothing_and_cleans_up(repo, monkeypatch):
    edit = repo.edit([("sc01", repo.add("a"))])
    real = A._run

    def broken(cmd):
        if "concat" in cmd:
            return subprocess.CompletedProcess(cmd, 1, "", "concat: something went wrong")
        return real(cmd)
    monkeypatch.setattr(A, "_run", broken)
    e = fails(edit, repo, "ffmpeg", "ffmpeg exited 1")
    assert "something went wrong" in e.detail["ffmpeg_stderr_tail"]
    assert A.failure_report(e)["status"] == "failed" and A.failure_report(e)["published"] is False
    assert not repo.film().exists(), "the film directory this run created is removed"


def test_verification_failure_publishes_nothing(repo, monkeypatch):
    edit = repo.edit([("sc01", repo.add("a")), ("sc02", repo.add("b"))])
    real = A.frame_md5s
    monkeypatch.setattr(A, "frame_md5s", lambda p: (lambda h: h[::-1] if A.PARTIAL_NAME in str(p) else h)(real(p)))
    fails(edit, repo, "verify", "decoded frames differ from the clips in edit order", "film frame 1")


def test_a_short_film_fails_the_frame_count(repo, monkeypatch):
    edit = repo.edit([("sc01", repo.add("a")), ("sc02", repo.add("b"))])
    real = A.probe
    monkeypatch.setattr(A, "probe", lambda p: {**real(p), "frames": 35} if A.PARTIAL_NAME in str(p) else real(p))
    fails(edit, repo, "verify", "film has 35 frames, expected 36")


def test_publication_is_rolled_back_if_an_output_appears_midway(repo, monkeypatch):
    edit = repo.edit([("sc01", repo.add("a"))])
    stale = repo.film() / ".assembly-from-another-run"
    stale.mkdir(parents=True)
    (stale / "keep.bin").write_bytes(b"x")
    real = A._publish

    def racing(src, dst):
        if dst.name.endswith(A.REPORT_SUFFIX):
            dst.write_text("written by someone else")          # appears between check and publish
        real(src, dst)
    monkeypatch.setattr(A, "_publish", racing)
    with pytest.raises(A.AssemblyError) as e:
        A.assemble(edit, repo.root)
    assert e.value.stage == "publish"
    assert sorted(p.name for p in repo.film().iterdir()) == [".assembly-from-another-run", "reel.assembly.json"]
    assert (repo.film() / "reel.assembly.json").read_text() == "written by someone else", "never replaced"
    assert (stale / "keep.bin").read_bytes() == b"x", "another run's workspace is not ours to clean"


def test_publish_never_replaces_an_existing_file(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.write_text("new")
    dst.write_text("old")
    with pytest.raises(FileExistsError):
        A._publish(src, dst)
    assert dst.read_text() == "old" and src.read_text() == "new"


def test_an_interrupted_run_cleans_its_workspace(repo, monkeypatch):
    edit = repo.edit([("sc01", repo.add("a"))])
    monkeypatch.setattr(A, "verify_film", lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    before = repo.snapshot()
    with pytest.raises(KeyboardInterrupt):
        A.assemble(edit, repo.root)
    assert repo.snapshot() == before


def test_concat_list_quotes_paths_safely():
    assert A._ffconcat_quote(Path("C:/a b/it's.mp4")) == "'C:/a b/it'\\''s.mp4'"


# ---------------------------------------------------------------------------------------------
# The approved example (read-only)
# ---------------------------------------------------------------------------------------------
def test_the_approved_example_passes_every_check_before_assembly():
    """Validates the real deliverables named by the example; writes nothing."""
    path = ROOT / "schemas/examples/greeting_reel.edit.json"
    edit = A.load_edit(path)
    if not all((ROOT / c.source).is_file() for c in edit.clips):
        pytest.skip("approved deliverables not present (storage/ is not tracked)")
    assert A.validate_sources(edit, ROOT) == []
    clips = A.check_clips(edit, ROOT)
    assert [len(c["frame_md5"]) for c in clips] == [576, 132]
