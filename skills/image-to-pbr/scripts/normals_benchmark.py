"""Measure DeepBump and the built-in normals against scanned ground truth, and check that image_to_pbr.py's DeepBump
gate picks whichever is closer. Re-run it when the DeepBump pin, the gate thresholds or the built-in method change.

Host: plain Python 3.9+ with numpy, and Pillow for most library PNGs (ambientCG's are not plain 8-bit RGB). Needs
DeepBump installed by setup_deepbump.py. Imports image_to_pbr.py from this folder.

Input: folders each holding one material's colour map (a file name containing BaseColor, Color or diff) and its
OpenGL normal map (NormalGL or nor_gl), such as CC0 scans from Poly Haven or ambientCG at 1k. The colour map stands in
for the photo; scans are already delit, so this measures relief recovery, not delighting.

    python normals_benchmark.py <materials folder> [--preset Rock064=stone ...] [--json out.json]

Each subfolder is one material; its preset is taken from --preset name=preset (a substring of the folder name) or
is stone. Per material it prints, for both methods: slope correlation with the scan (scale-free; 1 = same relief,
negative = inverted), mean angle to the scan after matching the 90th-percentile tilt, and DeepBump's gate verdict.
The summary gives the mean error of each method, of the gated choice and of the best choice per material.
"""

import argparse
import glob
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import image_to_pbr as m  # noqa: E402


def _find(folder, keys):
    for f in sorted(glob.glob(os.path.join(folder, "*"))):
        low = os.path.basename(f).lower()
        if any(k in low for k in keys) and low.endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff")):
            return f
    return None


def slopes(nrm):
    n = nrm * 2 - 1
    nz = np.maximum(n[..., 2], 1e-3)
    return n[..., 0] / nz, n[..., 1] / nz


def slope_corr(a, b):
    return float((a[0] * b[0] + a[1] * b[1]).sum()
                 / math.sqrt((a[0] ** 2 + a[1] ** 2).sum() * (b[0] ** 2 + b[1] ** 2).sum() + 1e-12))


def angle_error(pred, gt):
    """Mean angle in degrees after scaling pred's slopes so its 90th-percentile tilt matches gt's."""
    f = np.percentile(np.hypot(*gt), 90) / max(np.percentile(np.hypot(*pred), 90), 1e-6)
    a = np.stack([pred[0] * f, pred[1] * f, np.ones_like(pred[0])], -1)
    b = np.stack([gt[0], gt[1], np.ones_like(gt[0])], -1)
    a /= np.linalg.norm(a, axis=-1, keepdims=True)
    b /= np.linalg.norm(b, axis=-1, keepdims=True)
    return float(np.degrees(np.arccos(np.clip((a * b).sum(-1), -1, 1))).mean())


def main(argv):
    ap = argparse.ArgumentParser(prog="normals_benchmark.py", description=__doc__.split("\n")[0])
    ap.add_argument("folder")
    ap.add_argument("--preset", nargs="*", default=[], help="name=preset, name a substring of the folder name")
    ap.add_argument("--size", type=int, default=1024)
    ap.add_argument("--deepbump", help="DeepBump install folder (default: setup_deepbump.py's)")
    ap.add_argument("--json", help="also write the rows here")
    a = ap.parse_args(argv)
    presets = dict(p.split("=", 1) for p in a.preset)
    rows = []
    for d in sorted(glob.glob(os.path.join(a.folder, "*"))):
        col, nor = _find(d, ("basecolor", "color", "diff")), _find(d, ("normalgl", "nor_gl"))
        if not os.path.isdir(d) or not col or not nor:
            continue
        name = os.path.basename(d)
        preset = next((v for k, v in presets.items() if k in name), "stone")
        rgb, gt = m.load(col)[0][..., :3], m.load(nor)[0][..., :3]
        s = min(rgb.shape[:2] + gt.shape[:2])
        rgb, gt = rgb[:s, :s], gt[:s, :s]
        if s > a.size:
            rgb, gt, s = m.resize(rgb, a.size, a.size), m.resize(gt, a.size, a.size), a.size
        p = m.PRESETS[preset]
        builtin = m.normal_map(m.height_map(rgb, p["bands"], s, True), p["tilt_deg"])[0]
        try:
            deep = m.run_deepbump(rgb, a.deepbump)[0]
        except m.DeepBumpUnavailable as e:
            print("DeepBump unavailable (%s): nothing to benchmark" % e, file=sys.stderr)
            return 1
        gate = m.deepbump_gate(deep, True)
        G = slopes(gt)
        r = {"material": name, "preset": preset, "gate_ok": gate["ok"], "gate": gate}
        for k, n in (("builtin", builtin), ("deepbump", deep)):
            S = slopes(n)
            r[k] = {"corr": round(slope_corr(S, G), 3), "err_deg": round(angle_error(S, G), 2)}
        r["closer"] = "deepbump" if r["deepbump"]["err_deg"] < r["builtin"]["err_deg"] else "builtin"
        r["gated"] = "deepbump" if gate["ok"] else "builtin"
        rows.append(r)
        print("%-28s %-8s builtin corr %+.2f err %5.1f | deepbump corr %+.2f err %5.1f | tilt p90 %5.1f integ %.2f "
              "| gate %s, closer %s%s" % (name[:28], preset, r["builtin"]["corr"], r["builtin"]["err_deg"],
                                          r["deepbump"]["corr"], r["deepbump"]["err_deg"],
                                          gate["raw_tilt_deg_p50_p90"][1], gate["integrable_fraction"],
                                          r["gated"], r["closer"], "" if r["gated"] == r["closer"] else "  <- differs"),
              flush=True)
    if not rows:
        print("no material folders with a colour and an OpenGL normal map under %s" % a.folder, file=sys.stderr)
        return 2
    mean = lambda f: round(sum(f(r) for r in rows) / len(rows), 2)
    print("mean angle error over %d: builtin %.2f, deepbump %.2f, gated %.2f, best per material %.2f; gate picked the "
          "closer one %d times" % (len(rows), mean(lambda r: r["builtin"]["err_deg"]),
                                   mean(lambda r: r["deepbump"]["err_deg"]), mean(lambda r: r[r["gated"]]["err_deg"]),
                                   mean(lambda r: min(r["builtin"]["err_deg"], r["deepbump"]["err_deg"])),
                                   sum(r["gated"] == r["closer"] for r in rows)))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
