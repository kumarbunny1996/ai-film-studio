"""Milestone 9 Gate 1: the EditList contract (apps/api/schemas/edit_list.py).

Structural rules are checked against both the Pydantic model and the exported JSON Schema
(schemas/edit_list.schema.json), with the small validator from tests/test_schema_parity.py.
Rules only Pydantic enforces (unique clip IDs, clips from the film's own output folder, Windows
device names) are tested on the model alone. validate_sources() is tested on a fake repository
in tmp_path, including a junction (and, where allowed, a symlink) that escapes storage/projects.
"""
import copy
import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from apps.api.schemas.edit_list import EDIT_VERSION, EditList, validate_sources
from tests.test_schema_parity import SUPPORTED, keywords, valid

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas/edit_list.schema.json").read_text())
EXAMPLE = json.loads((ROOT / "schemas/examples/greeting_reel.edit.json").read_text())
SHA = "0" * 64


def ecma(schema):
    """The schema with its patterns read as JSON Schema specifies (ECMA-262): a final "$" matches
    only at the very end of the string. Python's re lets "$" also match before a final newline,
    so the shared parity helper would accept "x.mp4\\n"; "\\Z" is ECMA's "$" in Python syntax.
    The committed schema is unchanged; only this test's reading of it is."""
    if isinstance(schema, dict):
        out = {k: ecma(v) for k, v in schema.items()}
        p = schema.get("pattern")
        if isinstance(p, str) and p.endswith("$") and not p.endswith("\\$"):
            out["pattern"] = p[:-1] + r"\Z"
        return out
    if isinstance(schema, list):
        return [ecma(v) for v in schema]
    return schema


ECMA_SCHEMA = ecma(SCHEMA)


def pydantic_valid(d) -> bool:
    try:
        EditList.model_validate(d)
        return True
    except ValidationError:
        return False


def both(d) -> tuple[bool, bool]:
    return valid(d, ECMA_SCHEMA, ECMA_SCHEMA), pydantic_valid(d)


def edit(**changes):
    d = copy.deepcopy(EXAMPLE)
    d.update(changes)
    return d


def with_clip(**changes):
    d = copy.deepcopy(EXAMPLE)
    d["clips"][0].update(changes)
    return d


def with_format(**changes):
    d = copy.deepcopy(EXAMPLE)
    d["format"].update(changes)
    return d


# ---------------------------------------------------------------------------
# Schema export and parity
# ---------------------------------------------------------------------------
def test_committed_schema_matches_the_model():
    assert SCHEMA == EditList.model_json_schema(), \
        "regenerate: python -m apps.api.schemas.edit_list > schemas/edit_list.schema.json"


def test_parity_validator_covers_every_keyword():
    assert keywords(SCHEMA) <= SUPPORTED, keywords(SCHEMA) - SUPPORTED


def test_example_is_valid_in_both_and_is_version_1_0():
    assert both(EXAMPLE) == (True, True)
    e = EditList.model_validate(EXAMPLE)
    assert e.edit_version == EDIT_VERSION == "1.0"
    assert e.output_path() == "storage/projects/greeting_reel/greeting_reel.mp4"
    assert [c.clip_id for c in e.clips] == ["sc01_greeting", "sc02_ball_sequence"], "order kept"


@pytest.mark.parametrize("d", [
    edit(edit_version="1.1"), edit(edit_version=1.0), {k: v for k, v in EXAMPLE.items() if k != "format"},
    edit(clips=[]), edit(clips=None), edit(director="ai"),                       # unknown top-level field
    with_clip(trim=[1, 10]), with_format(bitrate="2M"),                          # unknown nested fields
])
def test_structure_and_unknown_fields_are_rejected_by_both(d):
    assert both(d) == (False, False)


@pytest.mark.parametrize("film_id", ["Greeting", "1reel", "g", "greeting-reel", "greeting reel", "a" * 49,
                                     "greeting_réel", "", "../x"])
def test_film_id_must_be_a_slug(film_id):
    assert both(edit(film_id=film_id)) == (False, False)


@pytest.mark.parametrize("clip_id", ["Sc01", "s", "_sc01", "sc-01", "sc01/x", 7])
def test_clip_id_must_be_a_slug(clip_id):
    assert both(with_clip(clip_id=clip_id)) == (False, False)


@pytest.mark.parametrize("source", [
    "storage/projects/m7_greeting/final_rev2/m7_greeting.mp4",
    "storage/projects/a/b.mp4",
    "storage/projects/m7_greeting/final-rev.2/clip_v1.0.mp4",
])
def test_safe_relative_sources_are_accepted_by_both(source):
    assert both(with_clip(source=source)) == (True, True)


@pytest.mark.parametrize("source", [
    "/storage/projects/a/b.mp4",                                   # absolute (POSIX)
    "C:/x/storage/projects/a/b.mp4", "C:storage/projects/a/b.mp4",  # drive letters
    "//server/share/storage/projects/a/b.mp4",                     # UNC
    "storage\\projects\\a\\b.mp4", "storage/projects/a\\b.mp4",    # backslashes
    "storage/projects/../projects/a/b.mp4", "storage/projects/a/../../../etc/b.mp4",
    "storage/projects/./a/b.mp4", "storage/projects/a/./b.mp4", "storage/projects/a/../b.mp4",
    "storage/projects/b.mp4",                                      # no project folder
    "storage/projects//a/b.mp4", "storage/projects/a/",            # empty segment / no file
    "./storage/projects/a/b.mp4", "storage/other/a/b.mp4", "assets/a/b.mp4",
    "Storage/Projects/a/b.mp4",                                    # the prefix is exact
    "storage/projects/a/.hidden.mp4", "storage/projects/a./b.mp4", # hidden, trailing dot
    "storage/projects/a/b.mp4:stream", "storage/projects/a/b c.mp4",
    "storage/projects/a/b.MP4", "storage/projects/a/b.mov", "storage/projects/a/b.png",
    "storage/projects/a/b.mp4 ",
    "storage/projects/" + "a/" * 120 + "b.mp4",                    # longer than 240
    "", 5,
])
def test_unsafe_sources_are_rejected_by_both(source):
    assert both(with_clip(source=source)) == (False, False)


@pytest.mark.parametrize("sha", ["A" * 64, "0" * 63, "0" * 65, "g" * 64, "", None, " " + "0" * 63])
def test_sha256_must_be_64_lowercase_hex(sha):
    assert both(with_clip(sha256=sha)) == (False, False)


@pytest.mark.parametrize("frames, ok", [(1, True), (576, True), (0, False), (-1, False), (1.5, False),
                                        ("576", False), (True, False), (24 * 3600 + 1, False)])
def test_frame_counts_are_positive_integers(frames, ok):
    assert both(with_clip(frames=frames)) == (ok, ok)


@pytest.mark.parametrize("change", [
    {"codec": "hevc"}, {"pix_fmt": "yuv444p"}, {"width": 0}, {"height": 8}, {"width": 640.0 + 0.5},
    {"fps": 23.976}, {"fps": 60}, {"fps": "24"}, {"audio": "aac"}, {"audio": None},
])
def test_format_is_explicit_and_limited_to_what_the_pipeline_produces(change):
    assert both(with_format(**change)) == (False, False)


@pytest.mark.parametrize("field", ["codec", "pix_fmt", "width", "height", "fps", "audio"])
def test_every_format_field_is_required(field):
    d = copy.deepcopy(EXAMPLE)
    del d["format"][field]
    assert both(d) == (False, False)


@pytest.mark.parametrize("field", ["clip_id", "source", "sha256", "frames"])
def test_every_clip_field_is_required(field):
    d = copy.deepcopy(EXAMPLE)
    del d["clips"][0][field]
    assert both(d) == (False, False)


# ---------------------------------------------------------------------------
# Rules Pydantic enforces beyond the schema
# ---------------------------------------------------------------------------
def test_clip_ids_are_unique():
    d = copy.deepcopy(EXAMPLE)
    d["clips"][1]["clip_id"] = d["clips"][0]["clip_id"]
    with pytest.raises(ValidationError, match="duplicate clip_id 'sc01_greeting'"):
        EditList.model_validate(d)


def test_the_same_source_may_appear_twice_under_different_ids():
    d = copy.deepcopy(EXAMPLE)
    d["clips"].append({**d["clips"][0], "clip_id": "sc03_greeting_again"})
    assert pydantic_valid(d)


@pytest.mark.parametrize("source", ["storage/projects/greeting_reel/old/a.mp4",
                                    "storage/projects/greeting_reel/greeting_reel.mp4",
                                    "storage/projects/Greeting_Reel/a/b.mp4"])
def test_no_clip_comes_from_the_films_own_output_folder(source):
    with pytest.raises(ValidationError, match="output folder"):
        EditList.model_validate(with_clip(source=source))
    assert pydantic_valid(with_clip(source="storage/projects/greeting_reel_v1/a/b.mp4"))


@pytest.mark.parametrize("seg", ["con", "NUL", "aux.mp4", "com1", "lpt9.txt"])
def test_windows_device_names_are_rejected(seg):
    source = f"storage/projects/{seg}/b.mp4" if not seg.endswith(".mp4") else f"storage/projects/a/{seg}"
    with pytest.raises(ValidationError, match="device name"):
        EditList.model_validate(with_clip(source=source))


@pytest.mark.parametrize("d", [with_clip(source="storage/projects/a/b.mp4\n"), edit(film_id="greeting_reel\n"),
                               with_clip(clip_id="sc01_greeting\n"), with_clip(sha256="0" * 64 + "\n")])
def test_a_trailing_newline_is_rejected_by_both(d):
    assert both(d) == (False, False)


def test_every_pattern_is_anchored_and_the_python_dollar_quirk_is_explicit():
    """Every pattern ends in "$"; under ECMA-262 (and Pydantic) it rejects a final newline.
    Plain Python re.search would accept one, which is why the parity check uses ecma()."""
    import re
    patterns = []

    def walk(s):
        if isinstance(s, dict):
            if isinstance(s.get("pattern"), str):
                patterns.append(s["pattern"])
            for v in s.values():
                walk(v)
        elif isinstance(s, list):
            for v in s:
                walk(v)
    walk(SCHEMA)
    assert len(patterns) == 4 and all(p.startswith("^") and p.endswith("$") for p in patterns)
    source = SCHEMA["$defs"]["Clip"]["properties"]["source"]["pattern"]
    assert re.search(source, "storage/projects/a/b.mp4\n"), "Python's '$' quirk, documented"
    assert not re.search(source[:-1] + r"\Z", "storage/projects/a/b.mp4\n")
    assert not pydantic_valid(with_clip(source="storage/projects/a/b.mp4\n"))


def test_non_finite_numbers_are_rejected():
    for bad in (float("nan"), float("inf")):
        assert not pydantic_valid(with_format(width=bad))


# ---------------------------------------------------------------------------
# validate_sources(): the filesystem
# ---------------------------------------------------------------------------
def fake_repo(tmp_path) -> Path:
    repo = tmp_path / "repo"
    clip = repo / "storage/projects/sc/final/sc.mp4"
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"not really a video")
    (repo / "storage/projects/sc/dir.mp4").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.mp4").write_bytes(b"secret")
    return repo


def one(source):
    return EditList.model_validate({**EXAMPLE, "clips": [{"clip_id": "sc01", "source": source,
                                                         "sha256": SHA, "frames": 1}]})


def test_existing_regular_file_inside_storage_passes(tmp_path):
    assert validate_sources(one("storage/projects/sc/final/sc.mp4"), fake_repo(tmp_path)) == []


def test_missing_source_and_directory_are_reported(tmp_path):
    repo = fake_repo(tmp_path)
    assert validate_sources(one("storage/projects/sc/final/none.mp4"), repo) == \
        ["clips[sc01]: source not found: storage/projects/sc/final/none.mp4"]
    assert validate_sources(one("storage/projects/sc/dir.mp4"), repo) == \
        ["clips[sc01]: source is not a regular file: storage/projects/sc/dir.mp4"]


def test_a_junction_escaping_storage_is_rejected(tmp_path):
    _winapi = pytest.importorskip("_winapi")
    if not hasattr(_winapi, "CreateJunction"):
        pytest.skip("no directory junctions on this platform")
    repo = fake_repo(tmp_path)
    _winapi.CreateJunction(str(tmp_path / "outside"), str(repo / "storage/projects/linked"))
    errors = validate_sources(one("storage/projects/linked/x.mp4"), repo)
    assert len(errors) == 1 and "escape" in errors[0]
    _winapi.CreateJunction(str(repo / "storage/projects/sc"), str(repo / "storage/projects/alias"))
    assert validate_sources(one("storage/projects/alias/final/sc.mp4"), repo) == [], \
        "a link that stays inside storage/projects is fine"


def test_a_symlink_escaping_storage_is_rejected(tmp_path):
    repo = fake_repo(tmp_path)
    link = repo / "storage/projects/sc/final/link.mp4"
    try:
        os.symlink(tmp_path / "outside" / "x.mp4", link)
    except OSError as e:                                   # Windows without symlink privilege
        pytest.skip(f"cannot create symlinks here: {e}")
    errors = validate_sources(one("storage/projects/sc/final/link.mp4"), repo)
    assert len(errors) == 1 and "escape" in errors[0]


def test_every_clip_is_checked_and_nothing_is_written(tmp_path):
    repo = fake_repo(tmp_path)
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    d = {**EXAMPLE, "clips": [{"clip_id": f"sc0{i}", "source": s, "sha256": SHA, "frames": 1} for i, s in
                              enumerate(["storage/projects/sc/final/sc.mp4", "storage/projects/a/b.mp4",
                                         "storage/projects/c/d.mp4"], 1)]}
    errors = validate_sources(EditList.model_validate(d), repo)
    assert [e.split(":")[0] for e in errors] == ["clips[sc02]", "clips[sc03]"]
    assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*")) == before


def test_the_example_sources_exist_in_this_repository():
    """The example names the approved M7 and M4 deliverables; skipped on a clone without them."""
    e = EditList.model_validate(EXAMPLE)
    if not all((ROOT / c.source).is_file() for c in e.clips):
        pytest.skip("approved deliverables not present (storage/ is not tracked)")
    assert validate_sources(e, ROOT) == []
