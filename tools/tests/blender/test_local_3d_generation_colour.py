"""Blender test of local-3d-generation's scripts/colour_match.py on images built here, in a temp folder.

Reference: a dusty-rose disc (sRGB 0.72, 0.53, 0.51, with some texture) on a light-grey background. Texture: the
same pattern shifted to tan (0.66, 0.55, 0.39, the shift Pixal3D's texture stage made on a cushion, 2026-11-02),
with black gutters and the bake's neutral 0.5 grey padding, which must not count in the statistics.

Asserted: sRGB to Lab and back is exact to 1e-5; after matching, the texture's mean hue is within 2 degrees of the
reference's and its saturation within 0.02; with the default (chroma only) its Lab lightness is unchanged within 0.5,
and with lightness=True it moves to the reference's; the gutters and padding do not count (the texel count); a
reference with no object pixels is refused.

Repo tooling, not a skill file: it loads the skill's script by path.
Host: Blender 4.2+ (bpy and its bundled numpy), headless:
    blender -b --factory-startup --python-exit-code 1 --python tools/tests/blender/test_local_3d_generation_colour.py
"""

import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "skills" / "local-3d-generation" / "scripts" / "colour_match.py"
NS = {"__name__": "colour_match_test"}
exec(compile(SCRIPT.read_text(encoding="utf-8"), str(SCRIPT), "exec"), NS)
FAILS = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def pattern(size, rng):
    return 1.0 + 0.08 * rng.standard_normal((size, size, 1))


def main():
    rng = np.random.default_rng(0)
    lab_round = NS["srgb_to_lab"](NS["lab_to_srgb"](NS["srgb_to_lab"](rng.random((64, 3)))))
    back = NS["srgb_to_lab"](rng.random((64, 3)))
    rgb = rng.random((64, 3))
    check(np.abs(NS["lab_to_srgb"](NS["srgb_to_lab"](rgb)) - rgb).max() < 1e-5, "sRGB -> Lab -> sRGB is exact")
    del lab_round, back

    n = 128
    yy, xx = np.mgrid[0:n, 0:n]
    disc = (xx - n / 2) ** 2 + (yy - n / 2) ** 2 < (n * 0.35) ** 2
    ref = np.ones((n, n, 4), np.float32)
    ref[..., :3] = 0.86                                           # light-grey studio background
    ref[disc, :3] = (np.array([0.72, 0.53, 0.51]) * pattern(n, rng))[disc]
    tex = np.ones((n, n, 4), np.float32)
    tex[..., :3] = (np.array([0.66, 0.55, 0.39]) * pattern(n, rng))
    tex[:, :8, :3] = 0.0                                           # gutter
    tex[:8, :, :3] = 0.5                                           # bake padding left neutral (128/255 once saved)
    with tempfile.TemporaryDirectory() as td:
        rp, tp = Path(td) / "ref.png", Path(td) / "tex.png"
        NS["save"](rp, np.clip(ref, 0, 1))
        NS["save"](tp, np.clip(tex, 0, 1))
        r = NS["match"](tp, [rp], Path(td) / "out.png")
        ref_s, after, before = r["reference"], r["after"], r["before"]
        check(abs(after["hue_deg"] - ref_s["hue_deg"]) < 2.0,
              f"hue moved to the reference ({before['hue_deg']} -> {after['hue_deg']}, reference {ref_s['hue_deg']})")
        check(abs(after["sat"] - ref_s["sat"]) < 0.02, f"saturation matched ({after['sat']} vs {ref_s['sat']})")
        check(abs(after["lab"][0] - before["lab"][0]) < 0.5,
              f"lightness L kept by default ({before['lab'][0]} -> {after['lab'][0]})")
        check(r["texels"] == (n - 8) * (n - 8), f"gutter and padding not counted ({r['texels']} texels)")
        out = NS["load"](Path(td) / "out.png")
        check(out.shape == (n, n, 4) and abs(float(out[n // 2, n // 2, 0]) - float(out[n // 2, n // 2, 2])) > 0.1,
              "written map reads back, red above blue")
        r2 = NS["match"](tp, [rp], Path(td) / "out2.png", lightness=True)
        check(abs(r2["after"]["lab"][0] - ref_s["lab"][0]) < 0.5,
              f"lightness=True matches L too ({r2['after']['lab'][0]} vs {ref_s['lab'][0]})")
        blank = np.ones((n, n, 4), np.float32) * 0.86
        bp = Path(td) / "blank.png"
        NS["save"](bp, blank)
        try:
            NS["match"](tp, [bp], Path(td) / "out3.png")
            check(False, "a reference with no object pixels must be refused")
        except ValueError:
            check(True, "a reference with no object pixels is refused")
    if FAILS:
        raise SystemExit(f"{len(FAILS)} check(s) failed")


try:
    main()
except SystemExit:
    raise
except Exception:
    import traceback
    traceback.print_exc()
    sys.exit(1)
