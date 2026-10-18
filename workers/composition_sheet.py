"""Milestone 8: annotated composition sheet for a Shot QA report.

    uv run python -m workers.composition_sheet --shot-dir <shot-dir> [--include-info] [--force]
    uv run python -m workers.composition_sheet --report <composition_report.json> \
        --geometry <shot_geometry.json> --frames-dir <dir> [--frames-dir <dir> ...] \
        --pattern "<shot_id>_{frame:04d}.png" --out <composition_sheet.png> [--include-info]

With --shot-dir the inputs are <shot-dir>/review/composition_report.json and
<shot-dir>/review/shot_geometry.json, the frames come from build_report.json's frames_dir
named <shot_id>_####.png, and the outputs go to <shot-dir>/review/.

Writes composition_sheet.png, one tile per finding (errors and warnings, accepted ones included;
info findings are counted in the header and drawn only with --include-info), and
composition_sheet.json, the sheet's index: for every tile the finding, the frame shown, the
rendered frame used (or none) and the outlines drawn, with the tile's position on the sheet.

Each tile is an existing rendered frame scaled to 640x360 with the finding's outlines drawn from
the geometry of the same frame: the involved part thick, in the severity colour (error red,
warning amber, info grey), the rest of the involved object thin, and the frame edge for edge
slivers; below it a caption with the finding ID, rule, severity, shot, frame range, the frame
shown, the measured values and any acceptance. The frame shown is the finding's worst frame
when it was rendered, else the nearest rendered frame inside the finding's range; with no
rendered frame in range the outlines are drawn on a plain background and the caption says so.

Like the report, the sheet is evidence for a human: it never approves anything. Read-only:
nothing is rendered and no input is modified. FFmpeg decodes the frames, draws the captions and
encodes the PNG; outlines are drawn in Python. The same inputs give the same sheet, byte for byte
(FFmpeg's PNG encoder writes no timestamp).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from workers import config

SCHEMA = "composition_sheet.v1"
SHEET_NAME, INDEX_NAME = "composition_sheet.png", "composition_sheet.json"
TILE_W, TILE_H, CAPTION_H, COLS, HEADER_H = 640, 360, 140, 2, 52
CAPTION_CHARS = 84          # characters per caption line: 13 px Consolas in a 640 px tile
CAPTION_LINES = 8
LINE_STEP = 16              # pixels between caption lines
COLORS = {"error": (255, 45, 45), "warning": (255, 170, 0), "info": (170, 170, 170)}
CONTEXT = (255, 255, 255)
BLANK = (64, 64, 64)


class SheetError(RuntimeError):
    pass


# ---------------------------------------------------------------------------------------------
# Drawing on raw RGB
# ---------------------------------------------------------------------------------------------
def _clip(x0, y0, x1, y1, w, h):
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0), (dx, w - 1 - x0), (-dy, y0), (dy, h - 1 - y0)):
        if p == 0:
            if q < 0:
                return None
            continue
        t = q / p
        if p < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return None
    return x0 + t0 * dx, y0 + t0 * dy, x0 + t1 * dx, y0 + t1 * dy


def _line(buf, w, h, a, b, color, width):
    c = _clip(a[0], a[1], b[0], b[1], w, h)
    if c is None:
        return
    x0, y0, x1, y1 = (int(round(v)) for v in c)
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx + dy
    r = width // 2
    px = bytes(color)
    while True:
        for oy in range(-r, width - r):
            for ox in range(-r, width - r):
                x, y = x0 + ox, y0 + oy
                if 0 <= x < w and 0 <= y < h:
                    i = (y * w + x) * 3
                    buf[i:i + 3] = px
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def _polygon(buf, hull, color, width):
    pts = [(x * TILE_W, (1.0 - y) * TILE_H) for x, y in hull]
    if len(pts) == 1:
        pts = pts * 2
    for a, b in zip(pts, pts[1:] + pts[:1]):
        _line(buf, TILE_W, TILE_H, a, b, color, width)


def _edge(buf, side, color):
    w, h = TILE_W, TILE_H
    seg = {"left": ((1, 0), (1, h - 1)), "right": ((w - 2, 0), (w - 2, h - 1)),
           "top": ((0, 1), (w - 1, 1)), "bottom": ((0, h - 2), (w - 1, h - 2))}[side]
    _line(buf, w, h, seg[0], seg[1], color, 4)


# ---------------------------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------------------------
def _digest(path: Path) -> dict:
    return {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _decode(path: Path) -> bytearray:
    proc = subprocess.run([config.FFMPEG_BIN, "-v", "error", "-i", str(path), "-vf",
                           f"scale={TILE_W}:{TILE_H}:flags=bicubic", "-f", "rawvideo",
                           "-pix_fmt", "rgb24", "-"], capture_output=True, timeout=config.FFMPEG_TIMEOUT_S)
    if proc.returncode != 0 or len(proc.stdout) != TILE_W * TILE_H * 3:
        raise SheetError(f"could not decode {path}: {proc.stderr.decode(errors='replace')[-300:]}")
    return bytearray(proc.stdout)


def _encode(buf: bytes, out: Path) -> None:
    proc = subprocess.run([config.FFMPEG_BIN, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                           "-s", f"{TILE_W}x{TILE_H}", "-i", "-", "-frames:v", "1", str(out)],
                          input=bytes(buf), capture_output=True, timeout=config.FFMPEG_TIMEOUT_S)
    if proc.returncode != 0:
        raise SheetError(f"could not encode {out}: {proc.stderr.decode(errors='replace')[-300:]}")


def _rendered(frames_dirs, pattern, frame):
    for d in frames_dirs:
        p = Path(d) / pattern.format(frame=frame)
        if p.is_file():
            return p
    return None


def choose_frame(finding, geo_frames, frames_dirs, pattern):
    """(frame, rendered path or None): the worst frame if rendered, else the nearest rendered
    frame in the finding's range (ties to the earlier), else the worst frame unrendered."""
    start, end = finding["frames"]
    worst = finding["evidence"]["worst_frame"]
    candidates = sorted((abs(f - worst), f) for f in geo_frames if start <= f <= end)
    for _, f in candidates:
        path = _rendered(frames_dirs, pattern, f)
        if path is not None:
            return f, path
    return worst, None


def outlines_for(finding, geo, frame):
    """[(object name, part or None, role)] for the finding's objects in this frame's geometry:
    'highlight' for the part (or the whole object when no part is named), 'context' for the
    rest of an object whose part is highlighted."""
    owners = {}
    for name, meta in geo["objects"].items():
        owners.setdefault((meta["kind"], meta["owner"]), []).append(name)
    objs = finding["objects"]
    out = []
    for i, o in enumerate(objs):
        if o["kind"] in ("part", "edge"):
            continue
        part = objs[i + 1]["id"] if i + 1 < len(objs) and objs[i + 1]["kind"] == "part" else None
        for name in sorted(owners.get((o["kind"], o["id"]), [])):
            entry = frame["objects"].get(name)
            if entry is None:
                continue
            if part is not None and part in entry["islands"]:
                out.append((name, None, "context"))
                out.append((name, part, "highlight"))
            else:
                out.append((name, None, "highlight"))
    return out


def _wrap(text, width=CAPTION_CHARS):
    out, line = [], ""
    for word in text.split():
        while len(word) > width:                          # break over-long tokens
            if line:
                out.append(line)
                line = ""
            out.append(word[:width])
            word = word[width:]
        if line and len(line) + 1 + len(word) > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}" if line else word
    if line:
        out.append(line)
    return out


def _caption(i, finding, frame, rendered):
    """Caption lines: at most CAPTION_LINES, each at most CAPTION_CHARS long."""
    m = ", ".join(f"{k} {v}" for k, v in sorted(finding["measured"].items()) if k != "cut_frames")
    objs = " / ".join(f"{o['kind']} {o['id']}" for o in finding["objects"])
    shown = f"shown {frame}" + ("" if rendered else " NO RENDERED FRAME: outlines on a plain background")
    lines = _wrap(f"[{i}] {finding['severity'].upper()} {finding['rule']} {finding['shot_id']} "
                  f"frames {finding['frames'][0]}-{finding['frames'][1]} worst "
                  f"{finding['evidence']['worst_frame']} {shown}") + _wrap(objs) + _wrap(m)
    if finding.get("accepted"):
        acc = _wrap(f"ACCEPTED ({finding['accepted']['kind']}): {finding['accepted']['reason']}")
        lines += acc if len(acc) <= 2 else [acc[0], acc[1][:CAPTION_CHARS - 3] + "..."]
    ident = f"id {finding['id']}"
    ident = [ident[k:k + CAPTION_CHARS] for k in range(0, len(ident), CAPTION_CHARS)][:2]
    lines = lines[:CAPTION_LINES - len(ident)] + ident
    return [ln.replace("\\", "/") for ln in lines]


# ---------------------------------------------------------------------------------------------
# Sheet
# ---------------------------------------------------------------------------------------------
def build_sheet(report: dict, geo: dict, frames_dirs, pattern: str, out_png: Path,
                include_info: bool = False) -> dict:
    if report.get("schema") != "composition_report.v1":
        raise SheetError(f"report schema {report.get('schema')!r}, expected composition_report.v1")
    if geo.get("schema") != "shot_geometry.v1":
        raise SheetError(f"geometry schema {geo.get('schema')!r}, expected shot_geometry.v1")
    by_frame = {f["frame"]: f for f in geo["frames"]}
    findings = [f for f in report["findings"] if include_info or f["severity"] != "info"]
    omitted = sum(1 for f in report["findings"] if f["severity"] == "info") if not include_info else 0
    tiles = []
    with tempfile.TemporaryDirectory(prefix="afs_sheet_") as tmp:
        tmp = Path(tmp)
        images = []
        for i, finding in enumerate(findings, 1):
            frame_no, path = choose_frame(finding, by_frame, frames_dirs, pattern)
            frame = by_frame.get(frame_no)
            if frame is None:
                raise SheetError(f"finding {finding['id']}: frame {frame_no} is not in the geometry")
            buf = _decode(path) if path else bytearray(bytes(BLANK) * (TILE_W * TILE_H))
            drawn = outlines_for(finding, geo, frame)
            color = COLORS[finding["severity"]]
            for name, part, role in drawn:                # context first, then highlights on top
                if role == "context":
                    for isl in frame["objects"][name]["islands"].values():
                        _polygon(buf, isl["hull"], CONTEXT, 1)
            for name, part, role in drawn:
                if role == "highlight":
                    entry = frame["objects"][name]
                    _polygon(buf, entry["islands"][part]["hull"] if part else entry["hull"], color, 3)
            for o in finding["objects"]:
                if o["kind"] == "edge":
                    _edge(buf, o["id"], color)
            img = tmp / f"tile_{i:03d}.png"
            _encode(buf, img)
            images.append((img, _line_files(tmp, f"caption_{i:03d}",
                                            _caption(i, finding, frame_no, path is not None))))
            col, row = (i - 1) % COLS, (i - 1) // COLS
            tiles.append({"index": i, "finding_id": finding["id"], "rule": finding["rule"],
                          "severity": finding["severity"], "accepted": finding.get("accepted"),
                          "frames": finding["frames"], "frame_shown": frame_no,
                          "rendered_frame": path.name if path else None,
                          "outlines": [{"object": n, "part": p, "role": r} for n, p, r in drawn],
                          "edges": [o["id"] for o in finding["objects"] if o["kind"] == "edge"],
                          "position": [col * TILE_W, HEADER_H + row * (TILE_H + CAPTION_H)],
                          "size": [TILE_W, TILE_H]})
        s = report["summary"]
        scene = report["scene"]
        header = _line_files(tmp, "header", [
            f"Composition QA  {scene.get('shot_id')}  frames {scene['frame_range'][0]}-{scene['frame_range'][1]}"
            f"  evaluated {scene['frames_evaluated']}{'' if scene['complete'] else ' (sampled)'}",
            f"open: {s['error']} error, {s['warning']} warning, {s['info']} info   accepted: {s['accepted']}"
            f"   tiles: {len(findings)}{f'   info not drawn: {omitted}' if omitted else ''}"
            "   EVIDENCE ONLY - human approval required"])
        _compose(images, header, out_png, tmp)
    return {"schema": SCHEMA, "verdict": "evidence_only", "human_approval_required": True,
            "sheet": out_png.name, "tile_size": [TILE_W, TILE_H], "caption_height": CAPTION_H,
            "header_height": HEADER_H, "columns": COLS, "info_not_drawn": omitted, "tiles": tiles}


def _line_files(tmp: Path, stem: str, lines) -> list:
    """One text file per line (no newline bytes), so drawtext places every line explicitly."""
    paths = []
    for k, line in enumerate(lines):
        path = tmp / f"{stem}_{k}.txt"
        path.write_bytes(line.encode("utf-8"))
        paths.append(path)
    return paths


def _ff_path(p: Path) -> str:
    return str(p).replace("\\", "/").replace(":", "\\:")


def _texts(files, x, y, size, step):
    font = _ff_path(Path(config.FFMPEG_FONTFILE))
    return ",".join(f"drawtext=fontfile='{font}':fontcolor=white:fontsize={size}:expansion=none:"
                    f"textfile='{_ff_path(f)}':x={x}:y={y + k * step}" for k, f in enumerate(files))


def _compose(images, header: list, out: Path, tmp: Path) -> None:
    draw = Path(config.FFMPEG_FONTFILE).is_file()
    rows = max(1, -(-len(images) // COLS))
    width, height = COLS * TILE_W, HEADER_H + rows * (TILE_H + CAPTION_H)
    args = [config.FFMPEG_BIN, "-v", "error", "-y", "-f", "lavfi", "-i",
            f"color=c=black:s={width}x{height}:d=1"]
    parts = []
    head = "[0:v]format=rgb24,"                         # composite in RGB: exact outline colours
    if draw:
        parts.append(f"{head}{_texts(header, 10, 8, 15, 20)}[base0]")
    else:
        parts.append(f"{head}null[base0]")
    for i, (img, cap) in enumerate(images, 1):
        args += ["-i", str(img)]
        col, row = (i - 1) % COLS, (i - 1) // COLS
        x, y = col * TILE_W, HEADER_H + row * (TILE_H + CAPTION_H)
        parts.append(f"[base{i - 1}][{i}:v]overlay={x}:{y}:format=rgb[ov{i}]")
        if draw:
            parts.append(f"[ov{i}]{_texts(cap, x + 8, y + TILE_H + 6, 13, LINE_STEP)}[base{i}]")
        else:
            parts.append(f"[ov{i}]null[base{i}]")
    args += ["-filter_complex", ";".join(parts), "-map", f"[base{len(images)}]", "-frames:v", "1",
             str(out)]
    proc = subprocess.run(args, capture_output=True, text=True, errors="replace",
                          timeout=config.FFMPEG_TIMEOUT_S)
    if proc.returncode != 0 or not out.is_file():
        raise SheetError(f"ffmpeg exited {proc.returncode}: {proc.stderr[-500:]}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="composition_sheet")
    p.add_argument("--shot-dir", type=Path)
    p.add_argument("--report", type=Path)
    p.add_argument("--geometry", type=Path)
    p.add_argument("--frames-dir", type=Path, action="append", default=[])
    p.add_argument("--pattern", help="frame file name, e.g. m7_greeting_{frame:04d}.png")
    p.add_argument("--out", type=Path)
    p.add_argument("--include-info", action="store_true")
    p.add_argument("--force", action="store_true", help="replace an existing sheet")
    a = p.parse_args(argv)
    try:
        if a.shot_dir:
            build = json.loads((a.shot_dir / "build_report.json").read_text())
            a.report = a.report or a.shot_dir / "review" / "composition_report.json"
            a.geometry = a.geometry or a.shot_dir / "review" / "shot_geometry.json"
            a.frames_dir = a.frames_dir or [Path(build["frames_dir"])]
            a.pattern = a.pattern or f"{build['shot_id']}_{{frame:04d}}.png"
            a.out = a.out or a.shot_dir / "review" / SHEET_NAME
        if not (a.report and a.geometry and a.pattern and a.out):
            p.error("give --shot-dir, or --report, --geometry, --pattern and --out")
        index_path = a.out.with_name(a.out.stem + ".json")
        if (a.out.exists() or index_path.exists()) and not a.force:
            print(f"FAILED: {a.out.name} or {index_path.name} exists; pass --force to replace it",
                  file=sys.stderr)
            return 1
    except (OSError, ValueError, KeyError) as e:
        print(f"FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    for old in (a.out, index_path):                       # a failed rerun never leaves old results
        old.unlink(missing_ok=True)
    try:
        report = json.loads(a.report.read_text())
        geo = json.loads(a.geometry.read_text())
        a.out.parent.mkdir(parents=True, exist_ok=True)
        index = build_sheet(report, geo, a.frames_dir, a.pattern, a.out, a.include_info)
        index["inputs"] = {"report": _digest(a.report), "geometry": _digest(a.geometry)}
        index_path.write_text(json.dumps(index, indent=1, sort_keys=True) + "\n")
    except (OSError, ValueError, KeyError, SheetError, subprocess.TimeoutExpired) as e:
        for partial in (a.out, index_path):
            partial.unlink(missing_ok=True)
        print(f"FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "evidence_written", "sheet": str(a.out), "tiles": len(index["tiles"]),
                      "info_not_drawn": index["info_not_drawn"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
