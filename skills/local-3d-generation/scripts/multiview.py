#!/usr/bin/env python3
"""Views for ComfyUI's multi-view template (3d_pixal3d_multi_views): split a turnaround sheet into square,
same-scale views by each view's outline, and wire separate view images into the converted API prompt.

Host: Python 3.10+ (standard library) and the ffmpeg / ffprobe command-line tools on PATH.

  python multiview.py split SHEET.png OUT_DIR [--prefix cushion] [--names front,left,back,right]
  python multiview.py wire MV_API.json OUT_API.json --front F.png --left L.png --back B.png --right R.png

split: the sheet is one row of views on a plain background (any spacing: generated sheets rarely sit on equal
quarters). Columns holding pixels that differ from the background (the median of the top and bottom rows) by more
than --tol out of 255 in any channel are grouped into runs, one per view; each run is cropped at full height with a small margin and padded to a square with the background colour, so
every view keeps the sheet's scale (the conditioning node asks for "the same scale in every view"). Fails unless it
finds exactly as many runs as names. An object close to the background's own colour (white on white) cannot be
found: ask for a contrasting plain background, or give separate views.

wire: in a prompt converted with comfy.py from 3d_pixal3d_multi_views, each view's crop of the sheet becomes a
LoadImage of the given file name (upload the files with comfy.py run --upload); the sheet loader is removed.
Views left out are disconnected (the node takes any subset; the first connected, in front, left, back, right order,
is the front the mesh is posed to).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

VIEWS = ("front", "left", "back", "right")


def _size(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout.strip()
    w, h = map(int, out.split(",")[:2])
    return w, h


def view_runs(sheet, tol=18, min_px=20):
    """Column ranges [(x0, x1), ...] that hold coloured pixels, left to right, and the background colour."""
    w, h = _size(sheet)
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(sheet), "-f", "rawvideo", "-pix_fmt", "rgb24",
                          "-"], capture_output=True, check=True).stdout
    border = [raw[i:i + 3] for i in range(0, w * 3, 3)] + [raw[(h - 1) * w * 3 + i:(h - 1) * w * 3 + i + 3]
                                                           for i in range(0, w * 3, 3)]
    bg = tuple(sorted(px[c] for px in border)[len(border) // 2] for c in range(3))   # median of the top/bottom rows
    occ = [0] * w
    for y in range(0, h, 2):
        row = raw[y * w * 3:(y + 1) * w * 3]
        for x in range(w):
            if max(abs(row[3 * x] - bg[0]), abs(row[3 * x + 1] - bg[1]), abs(row[3 * x + 2] - bg[2])) > tol:
                occ[x] += 1
    runs, start = [], None
    for x, c in enumerate(occ + [0]):
        if c > 2 and start is None:
            start = x
        elif c <= 2 and start is not None:
            if x - start > min_px:
                runs.append((start, x))
            start = None
    return runs, bg, (w, h)


def split(sheet, out_dir, prefix="view", names=VIEWS, margin=12, tol=18):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    runs, bg, (w, h) = view_runs(sheet, tol=tol)
    if len(runs) != len(names):
        raise SystemExit(f"found {len(runs)} views in {sheet}, expected {len(names)}: {runs} "
                         f"(raise or lower --tol, or crop the views by hand)")
    colour = "0x%02x%02x%02x" % bg
    paths = {}
    for (x0, x1), n in zip(runs, names):
        x0, x1 = max(0, x0 - margin), min(w, x1 + margin)
        side = max(h, x1 - x0)
        p = out_dir / f"{prefix}_{n}.png"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(sheet), "-vf",
                        f"crop={x1 - x0}:{h}:{x0}:0,pad={side}:{side}:(ow-iw)/2:(oh-ih)/2:color={colour}", str(p)],
                       check=True)
        paths[n] = {"path": str(p), "columns": [x0, x1], "size": side}
    return paths


def wire(prompt, files):
    """files: {view: file name in the server's input folder}; returns the prompt changed in place."""
    cond = next((nid for nid, e in prompt.items() if e["class_type"] == "Pixal3DMultiViewConditioning"), None)
    if cond is None:
        raise SystemExit("no Pixal3DMultiViewConditioning node: convert tpl:3d_pixal3d_multi_views first")
    crops = {}
    for view in VIEWS:
        link = prompt[cond]["inputs"].get(view)
        if not link:
            continue
        node = link[0]
        # follow images inputs upstream to the node that reads the sheet (ImageCropV2 in the template)
        while prompt[node]["class_type"] != "ImageCropV2":
            ins = prompt[node]["inputs"]
            nxt = ins.get("images") or ins.get("image")
            if not (isinstance(nxt, list) and nxt[0] in prompt):
                raise SystemExit(f"{view}: no sheet crop found upstream of node {link[0]}")
            node = nxt[0]
        crops[view] = node
    for view, node in crops.items():
        if view in files:
            prompt[node] = {"class_type": "LoadImage", "inputs": {"image": files[view]},
                            "_meta": {"title": f"view {view}"}}
        else:
            del prompt[cond]["inputs"][view]
    for nid in [n for n, e in prompt.items() if e["class_type"] == "LoadImage" and n not in crops.values()]:
        del prompt[nid]
    while True:                                               # the crop chains of views left out, node by node
        dangling = {nid for nid, e in prompt.items()
                    if any(isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and v[0] not in prompt
                           for v in e["inputs"].values())}
        if not dangling:
            return prompt
        for nid in dangling:
            del prompt[nid]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("split")
    s.add_argument("sheet"); s.add_argument("out_dir")
    s.add_argument("--prefix", default="view"); s.add_argument("--names", default=",".join(VIEWS))
    s.add_argument("--tol", type=int, default=18)
    w = sub.add_parser("wire")
    w.add_argument("api"); w.add_argument("out")
    for v in VIEWS:
        w.add_argument("--" + v)
    a = ap.parse_args(argv)
    if a.cmd == "split":
        print(json.dumps(split(a.sheet, a.out_dir, a.prefix, a.names.split(","), tol=a.tol), indent=1))
    else:
        p = json.loads(Path(a.api).read_text(encoding="utf-8"))
        files = {v: Path(getattr(a, v)).name for v in VIEWS if getattr(a, v)}
        Path(a.out).write_text(json.dumps(wire(p, files), indent=1), encoding="utf-8")
        print(f"wired {sorted(files)} -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
