"""Match a generated or baked base colour map to the colours of its input image(s).

Host: Blender 4.2+ (bpy for image IO and its bundled numpy), headless:

  blender -b --factory-startup --python-exit-code 1 --python colour_match.py -- \
      --texture T_PROP_Cushion_BaseColor.png --reference front.png [--reference left.png ...] \
      --out T_PROP_Cushion_BaseColor.png [--lightness] [--json report.json]

Why: the image-to-3D generators' texture stage shifts colour. *Measured* 2026-11-02 (Pixal3D, single and
multi-view, ComfyUI 0.43.2): a dusty-rose cushion (input hue 2 degrees, saturation 0.30) came back tan (hue 30-35,
the blue channel down by a quarter), although the views fed to the model still measured hue 2; a barrel came back
about 15% darker and less saturated. The map's detail is right; its colour statistics are not.

What: a Reinhard-style transfer in CIE Lab. Statistics come from the reference's object pixels (pixels that differ
from the colour at the image border, so a plain studio background drops out; alpha is used when present) and from
the texture's written texels (not black, not the bake's neutral 0.5 grey); only those are changed, so the dilated
padding round each island moves with it and gutters stay black. By default only the chroma (a, b) moves: the
reference's lightness includes the studio lighting that should not be painted into an albedo. --lightness matches
L too.

As a module: ns = {}; exec(open(path).read(), ns); ns["match"](texture, [refs], out, lightness=False)
returns the report (mean sRGB, hue in degrees, saturation and value of reference, before and after).
"""
from __future__ import annotations

import colorsys
import json
import sys
from pathlib import Path

import bpy
import numpy as np

# ---- colour maths (sRGB-encoded 0-1 in, D65) ----------------------------------------------------------------------

_M = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]])
_MI = np.linalg.inv(_M)
_WHITE = np.array([0.95047, 1.0, 1.08883])


def _lin(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _enc(c):
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1.0 / 2.4) - 0.055)


def srgb_to_lab(rgb):
    xyz = _lin(rgb) @ _M.T / _WHITE
    f = np.where(xyz > (6 / 29) ** 3, np.cbrt(xyz), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def lab_to_srgb(lab):
    fy = (lab[..., 0] + 16) / 116
    f = np.stack([fy + lab[..., 1] / 500, fy, fy - lab[..., 2] / 200], -1)
    xyz = np.where(f > 6 / 29, f ** 3, 3 * (6 / 29) ** 2 * (f - 4 / 29)) * _WHITE
    return _enc(xyz @ _MI.T)


# ---- image IO ------------------------------------------------------------------------------------------------------

def load(path) -> np.ndarray:
    """H x W x 4 floats, the stored (sRGB-encoded) values, rows top to bottom."""
    img = bpy.data.images.load(str(Path(path).resolve()), check_existing=False)
    img.colorspace_settings.name = "Non-Color"
    w, h = img.size
    a = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(a)
    has_alpha = img.alpha_mode != "NONE" and img.depth in (32, 64)
    bpy.data.images.remove(img)
    a = a.reshape(h, w, 4)[::-1].copy()
    if not has_alpha:
        a[..., 3] = 1.0
    return a


def save(path, rgba):
    h, w = rgba.shape[:2]
    img = bpy.data.images.new("colour_match_out", w, h, alpha=True)
    img.colorspace_settings.name = "Non-Color"           # the values are already sRGB-encoded: write them as they are
    img.pixels.foreach_set(np.ascontiguousarray(rgba[::-1], np.float32).ravel())
    img.filepath_raw = str(Path(path).resolve())
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)


# ---- masks and statistics ------------------------------------------------------------------------------------------

def reference_pixels(a, tol=0.06):
    """Object pixels of a reference: alpha over 0.5, and away from the border's median colour (the background)."""
    border = np.concatenate([a[0, :, :3], a[-1, :, :3], a[:, 0, :3], a[:, -1, :3]])
    bg = np.median(border, axis=0)
    keep = (a[..., 3] > 0.5) & (np.abs(a[..., :3] - bg).max(-1) > tol)
    return a[..., :3][keep]


def texture_mask(a):
    """Written texels: not black (gutters) and not the bake's neutral 0.5 grey (stored as 128/255 in 8 bits)."""
    rgb = a[..., :3]
    return (rgb.max(-1) > 0.02) & (np.abs(rgb - 0.5).max(-1) > 2.5e-3)


def _summary(rgb):
    m = rgb.reshape(-1, 3).mean(0)
    h, s, v = colorsys.rgb_to_hsv(*[float(x) for x in m])
    lab = srgb_to_lab(rgb.reshape(-1, 3)).mean(0)
    return {"mean_srgb": [round(float(x), 3) for x in m], "hue_deg": round(h * 360, 1), "sat": round(s, 3),
            "val": round(v, 3), "lab": [round(float(x), 2) for x in lab]}


def match(texture, references, out, lightness=False):
    tex = load(texture)
    ref = np.concatenate([reference_pixels(load(r)) for r in references])
    if len(ref) < 100:
        raise ValueError("too few object pixels in the reference(s): is the background the colour at the border?")
    keep = texture_mask(tex)                  # gutters and uncovered padding are left as they are
    src = tex[..., :3][keep]
    lab_r, lab_s = srgb_to_lab(ref), srgb_to_lab(src)
    mu_r, sd_r = lab_r.mean(0), lab_r.std(0) + 1e-6
    mu_s, sd_s = lab_s.mean(0), lab_s.std(0) + 1e-6
    chans = (0, 1, 2) if lightness else (1, 2)
    for c in chans:
        lab_s[:, c] = (lab_s[:, c] - mu_s[c]) / sd_s[c] * sd_r[c] + mu_r[c]
    after = lab_to_srgb(lab_s)
    out_rgb = tex[..., :3].copy()
    out_rgb[keep] = after
    save(out, np.dstack([out_rgb, tex[..., 3:4]]))
    return {"reference": _summary(ref), "before": _summary(src), "after": _summary(after),
            "lightness_matched": bool(lightness), "reference_pixels": int(len(ref)), "texels": int(len(src)),
            "out": str(out)}


def _main():
    import argparse
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--texture", required=True)
    ap.add_argument("--reference", action="append", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--lightness", action="store_true")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    rep = match(a.texture, a.reference, a.out, a.lightness)
    text = json.dumps(rep, indent=1)
    print(text)
    if a.json:
        Path(a.json).write_text(text, encoding="utf-8")


if __name__ == "__main__" and "--" in sys.argv:
    _main()
