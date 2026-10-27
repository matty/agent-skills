"""Turn one image (a photo, a scan or a generated pattern) into a tiling PBR map set: base colour, normal, height,
roughness, ambient occlusion and metallic, with the values held to measured PBR ranges and a report to check.

Host: plain Python 3.9+ with numpy. Pillow is optional: PNG is read and written without it (8 and 16 bits per channel,
grey, grey-alpha, RGB and RGBA, no palette or interlacing); JPEG, WebP, TIFF and paletted PNG need Pillow.
Also runs inside Blender 4.2+ (its bundled numpy); tested with numpy 2.2.
Normals: --normals auto (default) uses DeepBump's machine-learning model (https://github.com/HugoTini/DeepBump,
GPL-3.0) when setup_deepbump.py has installed it, except for presets in DEEPBUMP_AUTO_SKIP, and otherwise the built-in
luminance method; the report's normal_source says which ran, and a NOTE (a PROBLEM with --normals deepbump) says
why DeepBump did not. DeepBump runs as a separate process in its own venv; nothing of it is imported here.

Command line (exit 0 on success, 1 when the report has a PROBLEM, 2 on bad input):
    python image_to_pbr.py rug.png --out textures/RUG --family RUG --name Persian --preset fabric
    python image_to_pbr.py wall.jpg --out tex --family INT --name Plaster --preset plaster --size 2048 --make-tileable
    python image_to_pbr.py rug.png --out tex --family RUG --name Persian --preset fabric --pack orm --preview
    python image_to_pbr.py rock.jpg --out tex --family EXT --name Rock --preset stone --normals deepbump

Writes T_<FAMILY>_<Name>_<Map>.png for BaseColor (8-bit sRGB), Normal (16-bit, tangent space, OpenGL Y+), Height
(16-bit, linear, 0.5 = the mean surface), Roughness and AO (8-bit linear), plus packed maps: --pack unity (default)
adds MetallicSmoothness (R metallic, A smoothness = 1 - roughness), --pack orm adds ORM (R AO, G roughness, B metallic),
--pack none adds nothing. Also <out>/image_to_pbr_report.json (settings, measurements, problems and notes) and
<out>/T_<FAMILY>_<Name>_source.json (the source's path, size, SHA-256 and the PNG chunks it carried, such as a C2PA
manifest in caBX). With --preview: a 3 x 3 tile of the base colour and a lit preview (base colour shaded by the normal
map and AO under a raking light) to look at.

As a module: convert(src, out_dir, family, name, preset="fabric", **options) returns the report dict;
load(path) returns (pixels, info) with pixels a float32 (h, w, 4) array of codes / max code, rows top to bottom.
"""

import argparse
import hashlib
import json
import math
import os
import re
import struct
import sys
import zlib

import numpy as np

# Dielectric base-colour luma, sRGB codes: Adobe's PBR Guide part 2 (tolerant dark limit 30, bright limit 240),
# https://www.adobe.com/learn/substance-3d-designer/web/the-pbr-guide-part-2 (checked 2026-10-25).
ALBEDO_SRGB = (30, 240)

# Starting points per material class (practice; calibrate against measured references before shipping).
# roughness: median and the spread cavities and peaks push it; tilt_deg: the 90th-percentile slope the normal map is
# scaled to; bands: weights of fine (sigma 1 px), mid (4 px) and broad (16 px) detail in the height map, at 1024 px;
# ao_min: the 2nd-percentile AO; metallic: 0 or 1.
PRESETS = {
    "fabric":  dict(roughness=0.88, spread=0.08, tilt_deg=28, bands=(1.0, 0.35, 0.05), ao_min=0.70, metallic=0),
    "stone":   dict(roughness=0.75, spread=0.15, tilt_deg=35, bands=(0.5, 0.8, 0.6), ao_min=0.55, metallic=0),
    "brick":   dict(roughness=0.82, spread=0.12, tilt_deg=35, bands=(0.4, 0.8, 0.8), ao_min=0.50, metallic=0),
    "plaster": dict(roughness=0.85, spread=0.08, tilt_deg=15, bands=(0.6, 0.6, 0.3), ao_min=0.80, metallic=0),
    "wood":    dict(roughness=0.60, spread=0.15, tilt_deg=12, bands=(0.8, 0.5, 0.1), ao_min=0.80, metallic=0),
    "ground":  dict(roughness=0.90, spread=0.08, tilt_deg=40, bands=(0.5, 0.9, 0.7), ao_min=0.45, metallic=0),
    "leather": dict(roughness=0.55, spread=0.15, tilt_deg=15, bands=(1.0, 0.4, 0.1), ao_min=0.80, metallic=0),
    "metal":   dict(roughness=0.40, spread=0.20, tilt_deg=10, bands=(0.8, 0.4, 0.1), ao_min=0.85, metallic=1),
}

# Presets where auto does not use DeepBump: measured 2026-10-25 on a flat-pile rug, DeepBump embossed the dyed motifs
# as raised pillows and lost the pile weave; on fabric the colour pattern is dye, not relief.
DEEPBUMP_AUTO_SKIP = {"fabric"}

SEAM_RATIO_TILEABLE = 1.5   # wrap-edge difference / interior difference; above this the source does not tile


# ---- PNG I/O ----------------------------------------------------------------------------------------------------------

def png_chunks(path):
    """[(type, length)] of every chunk in a PNG, or [] for another format."""
    out = []
    with open(path, "rb") as f:
        if f.read(8) != b"\x89PNG\r\n\x1a\n":
            return out
        while True:
            head = f.read(8)
            if len(head) < 8:
                break
            n, t = struct.unpack(">I4s", head)
            out.append((t.decode("latin-1"), n))
            f.seek(n + 4, 1)
            if t == b"IEND":
                break
    return out


def _unfilter(raw, height, stride, bpp):
    out = np.zeros((height, stride), np.uint8)
    prev = np.zeros(stride, np.int32)
    pos = 0
    for y in range(height):
        ft = raw[pos]
        line = np.frombuffer(raw, np.uint8, stride, pos + 1).astype(np.int32)
        pos += stride + 1
        if ft == 0:
            cur = line
        elif ft == 2:
            cur = (line + prev) & 255
        else:
            cur = line.copy()
            for x in range(stride):                   # sub, average, paeth: sequential in x
                a = cur[x - bpp] if x >= bpp else 0
                b = prev[x]
                if ft == 1:
                    p = a
                elif ft == 3:
                    p = (a + b) >> 1
                else:
                    c = prev[x - bpp] if x >= bpp else 0
                    pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                    p = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                cur[x] = (cur[x] + p) & 255
        out[y] = cur
        prev = cur
    return out


def read_png(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos, idat, ihdr = 8, [], None
    while pos < len(data):
        n, t = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        if t == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif t == b"IDAT":
            idat.append(body)
        pos += 12 + n
    w, h, depth, ctype, _, _, interlace = ihdr
    ch = {0: 1, 2: 3, 4: 2, 6: 4}.get(ctype)
    if ch is None or interlace or depth not in (8, 16):
        raise ValueError("PNG colour type %d, depth %d, interlace %d needs Pillow" % (ctype, depth, interlace))
    bpp = ch * depth // 8
    rows = _unfilter(zlib.decompress(b"".join(idat)), h, w * bpp, bpp)
    if depth == 16:
        a = rows.reshape(h, w * ch, 2).astype(np.uint32)
        a = ((a[..., 0] << 8) | a[..., 1]).reshape(h, w, ch).astype(np.float32) / 65535.0
    else:
        a = rows.reshape(h, w, ch).astype(np.float32) / 255.0
    return _rgba(a, ch), depth


def _rgba(a, ch):
    h, w = a.shape[:2]
    out = np.ones((h, w, 4), np.float32)
    if ch in (1, 2):
        out[..., :3] = a[..., :1]
    else:
        out[..., :3] = a[..., :3]
    if ch in (2, 4):
        out[..., 3] = a[..., -1]
    return out


def load(path):
    """(pixels, info): pixels float32 (h, w, 4), codes / max code, rows top to bottom."""
    try:
        px, depth = read_png(path)
        return px, {"loader": "png", "bits": depth}
    except (ValueError, TypeError):
        pass
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit("cannot read %s without Pillow (PNG 8/16-bit non-interlaced is built in)" % path)
    im = Image.open(path)
    bits = 16 if im.mode in ("I;16", "I") else 8
    im = im.convert("RGBA") if bits == 8 else im
    a = np.asarray(im).astype(np.float32) / (65535.0 if bits == 16 else 255.0)
    if a.ndim == 2:
        a = a[..., None]
    return _rgba(a, a.shape[2]), {"loader": "pillow", "bits": bits}


def write_png(path, a, bits=8, dither=False, seed=0):
    """Write a (h, w) or (h, w, c) array of 0-1 values; c in 1-4. Only IHDR, IDAT and IEND chunks."""
    a = np.asarray(a, np.float64)
    if a.ndim == 2:
        a = a[..., None]
    h, w, c = a.shape
    top = 65535 if bits == 16 else 255
    v = np.clip(a, 0, 1) * top
    if dither and bits == 8:
        v = v + np.random.default_rng(seed).uniform(-0.5, 0.5, v.shape)
    v = np.clip(np.rint(v), 0, top)
    v = np.ascontiguousarray(v.astype(">u2" if bits == 16 else np.uint8))
    raw = np.concatenate([np.zeros((h, 1), np.uint8), v.reshape(h, -1).view(np.uint8)], axis=1).tobytes()
    ctype = {1: 0, 2: 4, 3: 2, 4: 6}[c]

    def chunk(t, body):
        return struct.pack(">I", len(body)) + t + body + struct.pack(">I", zlib.crc32(t + body) & 0xFFFFFFFF)

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, bits, ctype, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


# ---- maths ------------------------------------------------------------------------------------------------------------

def srgb_to_linear(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c):
    c = np.clip(c, 0, None)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def luma(rgb):
    return rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722


def blur(a, sigma, wrap=True):
    """Gaussian blur of a (h, w) or (h, w, c) array through the FFT: wraps at the edges (right for tiling maps);
    wrap=False mirror-pads first."""
    if sigma <= 0:
        return a
    if not wrap:
        h, w = a.shape[:2]
        p = np.concatenate([a, a[::-1]], 0)
        p = np.concatenate([p, p[:, ::-1]], 1)
        return blur(p, sigma, True)[:h, :w]
    h, w = a.shape[:2]
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.rfftfreq(w)[None, :]
    k = np.exp(-2 * (math.pi * sigma) ** 2 * (fx * fx + fy * fy))
    if a.ndim == 3:
        k = k[..., None]
    return np.fft.irfft2(np.fft.rfft2(a, axes=(0, 1)) * k, s=(h, w), axes=(0, 1)).astype(np.float32)


def seam_ratios(a):
    """(across the left-right wrap, across the top-bottom wrap): the mean difference across the wrap edge / the mean
    difference between neighbouring interior columns (rows). About 1 for a map that tiles; well above 1 is a seam."""
    g = luma(a[..., :3]) if a.ndim == 3 else a
    lr = np.abs(g[:, 0] - g[:, -1]).mean() / max(float(np.abs(np.diff(g, axis=1)).mean()), 1e-6)
    tb = np.abs(g[0, :] - g[-1, :]).mean() / max(float(np.abs(np.diff(g, axis=0)).mean()), 1e-6)
    return float(lr), float(tb)


def seam_ratio(a):
    return max(seam_ratios(a))


def seam_visible(a):
    """True when a wrap edge differs more than SEAM_RATIO_TILEABLE times the mean neighbour difference and more than
    the 99th percentile of the map's own interior neighbour pairs: sparse maps (AO, roughness) have a wide spread,
    so one fixed ratio flags them falsely."""
    g = luma(a[..., :3]) if a.ndim == 3 else a
    for axis, r in zip((1, 0), seam_ratios(a)):
        d = np.abs(np.diff(g, axis=axis)).mean(axis=1 - axis)
        if r > max(SEAM_RATIO_TILEABLE, _pct(d / max(float(d.mean()), 1e-6), 99)):
            return True
    return False


def fit_period(g, axis, max_score=0.6):
    """For a repeating pattern that does not tile at the image size: the largest whole number of repeats along axis
    and the offset where cropping to it wraps best. Returns (start, length, score) or None when there is no clear
    repeat. score is the shift difference at length / the mean shift difference (0 = a perfect repeat)."""
    g = g if axis == 0 else g.T
    n = g.shape[0]
    ds = np.arange(max(8, n // 8), n - max(8, n // 8))
    s = np.array([np.abs(g[d:] - g[:-d]).mean() for d in ds])
    base = float(s.mean())
    # repeats are local minima of the shift difference (the lowest within r px) scoring under max_score of the mean;
    # a smooth pattern scores low over a whole dip, so the longest low shift alone lands on the dip's shoulder
    r = max(3, n // 64)
    pad = np.pad(s, r, mode="edge")
    lowest = np.min(np.lib.stride_tricks.sliding_window_view(pad, 2 * r + 1), axis=1)
    good = ds[(s <= lowest) & (s < max_score * base)]
    if not len(good):
        return None
    length = int(good.max())
    overlap = feather_px(length) if n - length >= feather_px(length) else 0
    rows = np.abs(g[length:] - g[:-length]).mean(axis=1)       # rows[y]: row y + length vs row y
    start = int(np.argmin(rows[:n - length - overlap + 1]))
    return start, length, float(s[ds == length][0] / base)


def feather_px(length):
    return max(8, length // 32)


def crop_wrap(a, axis, start, length):
    """Crop length rows (axis 0) or columns (axis 1) from start. When the source has the rows that follow the crop
    (the next repeat, at the same phase), blend them into the crop's first rows, so the last row runs straight into
    the first; only fine detail that does not repeat (weave, grain) is averaged, over a narrow band."""
    a = a if axis == 0 else a.swapaxes(0, 1)
    o = feather_px(length)
    if start + length + o <= a.shape[0]:
        seg = a[start:start + length + o]
        t = ((np.arange(o) + 0.5) / o).reshape((o,) + (1,) * (a.ndim - 1))
        t = t * t * (3 - 2 * t)
        out = np.concatenate([seg[length:] * (1 - t) + seg[:o] * t, seg[o:length]], 0)
    else:
        out = a[start:start + length]
    return out if axis == 0 else out.swapaxes(0, 1)


def _weights(n_in, n_out, wrap):
    """(n_out, n_in) resampling matrix: a tent filter widened by the scale factor (antialiased when shrinking)."""
    scale = n_in / n_out
    support = max(1.0, scale)
    centres = (np.arange(n_out) + 0.5) * scale - 0.5
    idx = np.arange(n_in)
    d = idx[None, :] - centres[:, None]
    if wrap:
        d = (d + n_in / 2) % n_in - n_in / 2
    w = np.clip(1 - np.abs(d) / support, 0, None)
    if not wrap:
        w[:, 0] += np.clip(1 - np.abs(-1 - centres) / support, 0, None)        # clamp the edge
        w[:, -1] += np.clip(1 - np.abs(n_in - centres) / support, 0, None)
    return (w / w.sum(1, keepdims=True)).astype(np.float32)


def resize(a, h, w, wrap=True):
    wy, wx = _weights(a.shape[0], h, wrap), _weights(a.shape[1], w, wrap)
    return np.einsum("yi,ijc,xj->yxc", wy, a, wx, optimize=True) if a.ndim == 3 else wy @ a @ wx.T


def make_tileable(a, border=0.25):
    """Cross-fade the image with itself offset by half: the offset copy covers the wrap seams, the original the
    centre. Ghosts large features where they cross the blend; best on even, irregular textures."""
    h, w = a.shape[:2]
    off = np.roll(a, (h // 2, w // 2), (0, 1))
    def ramp(n):
        t = np.minimum(np.arange(n) + 0.5, n - np.arange(n) - 0.5) / (n * border)
        t = np.clip(t, 0, 1)
        return t * t * (3 - 2 * t)
    m = (ramp(h)[:, None] * ramp(w)[None, :])[..., None]
    return a * m + off * (1 - m)


def pow2_floor(n):
    return 1 << (int(n).bit_length() - 1)


def _pct(v, q):
    return float(np.percentile(v, q))


# ---- the conversion ---------------------------------------------------------------------------------------------------

def base_colour(rgb, delight_sigma, wrap, lo=ALBEDO_SRGB[0], hi=ALBEDO_SRGB[1]):
    """Remove broad lighting gradients (divide by the blurred luminance in linear light), then bring the luma into
    the dielectric range by an affine remap of its 0.5th-99.5th percentiles, keeping chroma. Returns (srgb, stats)."""
    lin = srgb_to_linear(rgb)
    stats = {}
    if delight_sigma:
        y = luma(lin)
        broad = blur(y, delight_sigma, wrap)
        gain = (y.mean() / np.maximum(broad, 1e-4))[..., None]
        stats["delight_gain_range"] = [round(float(gain.min()), 3), round(float(gain.max()), 3)]
        lin = lin * gain
    srgb = linear_to_srgb(lin)
    y = luma(srgb) * 255
    p_lo, p_hi = _pct(y, 0.5), _pct(y, 99.5)
    stats["luma_before"] = [round(p_lo, 1), round(float(np.median(y)), 1), round(p_hi, 1)]
    t_lo, t_hi = max(p_lo, lo), min(p_hi, hi)
    if (t_lo, t_hi) != (p_lo, p_hi) and p_hi > p_lo:
        y2 = t_lo + (y - p_lo) * (t_hi - t_lo) / (p_hi - p_lo)
        y2 = np.clip(y2, lo, hi)
        srgb = srgb * (y2 / np.maximum(y, 1e-3))[..., None]
        stats["luma_remap"] = [[round(p_lo, 1), round(p_hi, 1)], [round(t_lo, 1), round(t_hi, 1)]]
    srgb = np.clip(srgb, 0, 1)
    y = luma(srgb) * 255
    stats["luma_after"] = [round(_pct(y, 0.5), 1), round(float(np.median(y)), 1), round(_pct(y, 99.5), 1)]
    return srgb, stats


def height_map(rgb, bands, size, wrap):
    """Height from relative (log) luminance contrast in three bands, so dark and light dyes or stains give the same
    relief for the same surface; broad colour areas add little. 0.5 = the mean surface, the 0.5th-99.5th
    percentiles span 0-1."""
    s = size / 1024.0
    ly = np.log(np.maximum(luma(srgb_to_linear(rgb)), 1e-4))
    sig = [1.0 * s, 4.0 * s, 16.0 * s, 64.0 * s]
    levels = [ly] + [blur(ly, g, wrap) for g in sig]
    h = np.zeros_like(ly)
    for wgt, a, b in zip(bands, levels[:3], levels[2:]):     # fine: ly - b4, mid: b1 - b16, broad: b4 - b64
        if wgt:
            d = a - b
            h += wgt * d / max(float(d.std()), 1e-6)
    lo, hi = _pct(h, 0.5), _pct(h, 99.5)
    return np.clip(0.5 + (h - (lo + hi) / 2) / max(hi - lo, 1e-6), 0, 1).astype(np.float32)


def normal_map(height, tilt_deg):
    """Tangent-space normal, OpenGL convention (green = +V = up the image), scaled so the 90th-percentile slope
    tilts tilt_deg. Returns (rgb 0-1, scale used)."""
    dx = (np.roll(height, -1, 1) - np.roll(height, 1, 1)) / 2
    drow = (np.roll(height, -1, 0) - np.roll(height, 1, 0)) / 2
    slope = np.hypot(dx, drow)
    p90 = max(_pct(slope, 90), 1e-6)
    k = math.tan(math.radians(tilt_deg)) / p90
    n = np.stack([-dx * k, drow * k, np.ones_like(height)], -1)    # rows run down the image: +V = -row
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    return n * 0.5 + 0.5, k


def ao_map(height, size, ao_min, wrap):
    """Cavity occlusion: how far each texel sits below its neighbourhood at two radii, scaled so the 2nd percentile
    reaches ao_min."""
    s = size / 1024.0
    cav = sum(np.maximum(blur(height, r * s, wrap) - height, 0) for r in (2.0, 8.0))
    p98 = max(_pct(cav, 98), 1e-6)
    return np.clip(1 - (1 - ao_min) * cav / p98, 0, 1).astype(np.float32)


def roughness_map(height, ao, preset):
    """The preset's median roughness, rougher in cavities and smoother on worn peaks by up to the preset's spread."""
    d = (0.5 - height) + 0.5 * (1 - ao) / max(1 - preset["ao_min"], 1e-3) - 0.25
    d = d / max(_pct(np.abs(d), 98), 1e-6)
    r = preset["roughness"] + preset["spread"] * np.clip(d, -1, 1)
    return np.clip(r, 0.02, 1).astype(np.float32)


class DeepBumpUnavailable(Exception):
    pass


def deepbump_root():
    """DeepBump's install folder, as setup_deepbump.py chooses it."""
    env = os.environ.get("IMAGE_TO_PBR_DEEPBUMP")
    if env:
        return env
    base = os.environ.get("LOCALAPPDATA") if os.name == "nt" else None
    return os.path.join(base or os.path.join(os.path.expanduser("~"), ".cache"), "agent-skills", "deepbump")


_DEEPBUMP_RUN = r"""
import sys
sys.path.insert(0, sys.argv[1])
import numpy as np
import module_color_to_normals as c2n
img = np.load(sys.argv[2])
np.save(sys.argv[3], c2n.apply(img, sys.argv[4], None).astype(np.float32))
"""


def run_deepbump(rgb, root=None, overlap="LARGE", timeout=900, python=None):
    """DeepBump's colour-to-normal model on rgb (h, w, 3, 0-1), in its own venv and process. Returns (normals as
    (h, w, 3) 0-1, OpenGL, wrap-padded so tiling maps stay tiling; its install record). Raises DeepBumpUnavailable
    with the reason when it is not installed or fails."""
    import subprocess
    import tempfile
    root = os.path.abspath(root or deepbump_root())
    vpy = python or os.path.join(root, "venv", "Scripts" if os.name == "nt" else "bin",
                                 "python.exe" if os.name == "nt" else "python")
    src = os.path.join(root, "DeepBump")
    if not os.path.isfile(vpy) or not os.path.isfile(os.path.join(src, "module_color_to_normals.py")):
        raise DeepBumpUnavailable("not installed at %s" % root)
    record = {}
    try:
        with open(os.path.join(root, "deepbump.json"), encoding="utf-8") as f:
            record = json.load(f)
    except (OSError, ValueError):
        pass
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")   # it prints U+2192 arrows
    with tempfile.TemporaryDirectory() as d:
        i, o = os.path.join(d, "in.npy"), os.path.join(d, "out.npy")
        np.save(i, np.ascontiguousarray(np.transpose(rgb[..., :3], (2, 0, 1)), np.float32))
        try:
            p = subprocess.run([vpy, "-B", "-c", _DEEPBUMP_RUN, src, i, o, overlap], capture_output=True, text=True,
                               timeout=timeout, env=env)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise DeepBumpUnavailable("failed to run: %s" % e)
        if p.returncode or not os.path.isfile(o):
            last = (p.stderr.strip().splitlines() or ["exit %d" % p.returncode])[-1]
            raise DeepBumpUnavailable("failed: %s" % last)
        n = np.transpose(np.load(o), (1, 2, 0))
    if n.shape[:2] != rgb.shape[:2] or not np.isfinite(n).all():
        raise DeepBumpUnavailable("returned a %s map for a %s image" % (n.shape, rgb.shape))
    return np.clip(n, 0, 1).astype(np.float32), record


def scale_normals(nrm, tilt_deg, flip=False):
    """Scale a 0-1 OpenGL normal map's slopes so the 90th-percentile tilt is tilt_deg (flip: invert the relief).
    Returns (map, factor)."""
    n = nrm * 2 - 1
    nz = np.maximum(n[..., 2], 1e-3)
    slope = np.hypot(n[..., 0], n[..., 1]) / nz
    f = math.tan(math.radians(tilt_deg)) / max(_pct(slope, 90), 1e-6)
    sx, sy = n[..., 0] / nz * f, n[..., 1] / nz * f
    if flip:
        sx, sy = -sx, -sy
    out = np.stack([sx, sy, np.ones_like(sx)], -1)
    out /= np.linalg.norm(out, axis=-1, keepdims=True)
    return (out * 0.5 + 0.5).astype(np.float32), f


def height_from_normals(nrm, wrap=True):
    """Integrate a 0-1 OpenGL normal map into a height map (least squares through the FFT; mirrored first when the
    map does not tile). 0.5 = the mean surface, the 0.5th-99.5th percentiles span 0-1."""
    n = nrm * 2 - 1
    nz = np.maximum(n[..., 2], 1e-3)
    gx, grow = -n[..., 0] / nz, n[..., 1] / nz           # dh/dx and dh/drow, as normal_map writes them
    h, w = gx.shape
    if not wrap:
        gx = np.concatenate([gx, -gx[:, ::-1]], 1)
        grow = np.concatenate([grow, grow[:, ::-1]], 1)
        gx = np.concatenate([gx, gx[::-1]], 0)
        grow = np.concatenate([grow, -grow[::-1]], 0)
    H, W = gx.shape
    wy = 2 * math.pi * np.fft.fftfreq(H)[:, None]
    wx = 2 * math.pi * np.fft.fftfreq(W)[None, :]
    den = wx * wx + wy * wy
    den[0, 0] = 1
    z = (-1j * wx * np.fft.fft2(gx) - 1j * wy * np.fft.fft2(grow)) / den
    z[0, 0] = 0
    z = np.real(np.fft.ifft2(z))[:h, :w]
    lo, hi = _pct(z, 0.5), _pct(z, 99.5)
    return np.clip(0.5 + (z - (lo + hi) / 2) / max(hi - lo, 1e-6), 0, 1).astype(np.float32)


def lit_preview(bc, nrm, ao, light=(-0.5, 0.6, 0.62)):
    l = np.asarray(light, np.float32)
    l /= np.linalg.norm(l)
    n = nrm * 2 - 1
    lam = np.clip((n * l).sum(-1), 0, 1)
    lin = srgb_to_linear(bc) * (0.25 + 0.95 * lam)[..., None] * ao[..., None]
    return linear_to_srgb(lin)


def convert(src, out_dir, family, name, preset="fabric", size=None, make_tileable_=False, tiling=None,
            delight=True, roughness=None, tilt_deg=None, bands=None, ao_min=None, metallic=None, invert_height=False,
            pack="unity", preview=False, normals="auto", deepbump=None):
    if not re.match(r"^[A-Z]{2,5}$", family) or not re.match(r"^[A-Za-z0-9]+$", name):
        raise ValueError("family is 2-5 capitals, name is letters and digits: T_<FAMILY>_<Name>_<Map>.png")
    p = dict(PRESETS[preset])
    for k, v in (("roughness", roughness), ("tilt_deg", tilt_deg), ("bands", bands), ("ao_min", ao_min),
                 ("metallic", metallic)):
        if v is not None:
            p[k] = tuple(v) if k == "bands" else v
    report = {"source": os.path.abspath(src), "preset": preset, "settings": p, "problems": [], "notes": [],
              "maps": {}}
    px, info = load(src)
    rgb = px[..., :3]
    h0, w0 = rgb.shape[:2]
    report["source_px"] = [w0, h0]
    if px[..., 3].min() < 1:
        report["notes"].append("source alpha ignored (min %.2f)" % float(px[..., 3].min()))

    srs = seam_ratios(rgb)
    sr = max(srs)
    report["source_seam_ratio"] = {"left_right": round(srs[0], 2), "top_bottom": round(srs[1], 2)}
    tiles = not seam_visible(rgb) if tiling is None else tiling
    if not tiles and make_tileable_:
        g = luma(rgb)
        for axis in (1, 0):                    # 1: columns (left-right wrap), 0: rows (top-bottom wrap)
            if srs[1 - axis] <= SEAM_RATIO_TILEABLE:
                continue
            fit = fit_period(g, axis)
            if fit is None:
                continue
            start, length, score = fit
            rgb = crop_wrap(rgb, axis, start, length)
            g = luma(rgb)
            report["notes"].append("cropped %s to %d px from %d (a whole number of pattern repeats, shift score "
                                   "%.2f)" % ("rows" if axis == 0 else "columns", length, start, score))
        if seam_visible(rgb):
            before = seam_ratio(rgb)
            rgb = make_tileable(rgb)
            report["notes"].append("made tileable by a half-offset cross-fade (seam ratio %.2f -> %.2f); check the "
                                   "preview for ghosted features" % (before, seam_ratio(rgb)))
        h0, w0 = rgb.shape[:2]
        report["tileable_px"] = [w0, h0]
        tiles = True
    elif not tiles:
        report["problems"].append("source seam ratio %.2f: it does not tile; pass --make-tileable, or --no-tiling "
                                  "for a unique (non-repeating) map" % sr)

    if size is None:
        size = min(pow2_floor(min(w0, h0)), 2048)
    report["tile_aspect"] = round(w0 / h0, 4)
    if w0 != h0:
        report["notes"].append("the tile is %dx%d (aspect %.3f) and the maps are square: set the material's tiling "
                               "or UV scale so one tile covers %.3f times as much width as height, or the pattern "
                               "is squashed" % (w0, h0, w0 / h0, w0 / h0))
    if size > min(w0, h0):
        report["notes"].append("upscaled %d -> %d px: no detail is added; the map is softer than its size says"
                               % (min(w0, h0), size))
    rgb = np.clip(resize(rgb, size, size, wrap=tiles), 0, 1)

    bc, bstats = base_colour(rgb, size / 8.0 if delight else 0, tiles)
    report["base_colour"] = bstats
    nrm = None
    report["normal_source"] = "builtin"
    if normals == "auto" and preset in DEEPBUMP_AUTO_SKIP:
        report["notes"].append("normals: built-in method; auto skips DeepBump for the %s preset (it embosses dyed "
                               "patterns as relief); pass --normals deepbump to use it anyway" % preset)
    elif normals in ("auto", "deepbump"):
        try:
            raw, rec = run_deepbump(rgb, deepbump)
            nrm, k = scale_normals(raw, p["tilt_deg"], invert_height)
            hgt = height_from_normals(nrm, tiles)
            tilt = np.degrees(np.arccos(np.clip(raw[..., 2] * 2 - 1, -1, 1)))
            report["normal_source"] = "deepbump %s" % rec.get("commit", "(no install record)")[:12]
            report["deepbump_raw_tilt_deg_p50_p90"] = [round(_pct(tilt, 50), 1), round(_pct(tilt, 90), 1)]
        except DeepBumpUnavailable as e:
            msg = ("DeepBump unavailable (%s): used the built-in luminance method instead; install it with "
                   "setup_deepbump.py" % e)
            report["problems" if normals == "deepbump" else "notes"].append(msg)
    if nrm is None:
        hgt = height_map(rgb, p["bands"], size, tiles)
        if invert_height:
            hgt = 1 - hgt
        nrm, k = normal_map(hgt, p["tilt_deg"])
    ao = ao_map(hgt, size, p["ao_min"], tiles)
    rough = roughness_map(hgt, ao, p)
    metal = np.full_like(hgt, float(p["metallic"]))
    if p["metallic"]:
        y = luma(bc) * 255
        if _pct(y, 5) < 180:
            report["problems"].append("metal preset but base colour luma 5th percentile %.0f < 180: raw metal is "
                                      "180-255 sRGB; brighten it or use a dielectric preset" % _pct(y, 5))

    stem = os.path.join(out_dir, "T_%s_%s_" % (family, name))
    files = {"BaseColor": (bc, 8, True), "Normal": (nrm, 16, False), "Height": (hgt, 16, False),
             "Roughness": (rough, 8, True), "AO": (ao, 8, True)}
    if pack == "unity":
        files["MetallicSmoothness"] = (np.stack([metal, np.zeros_like(metal), np.zeros_like(metal), 1 - rough], -1),
                                       8, True)
    elif pack == "orm":
        files["ORM"] = (np.stack([ao, rough, metal], -1), 8, True)
    for role, (a, bits, dith) in files.items():
        path = stem + role + ".png"
        write_png(path, a, bits, dither=dith)
        report["maps"][role] = {"path": os.path.abspath(path), "bits": bits, "seam_ratio": round(seam_ratio(a), 2),
                                "seam_visible": bool(tiles and a.std() > 1e-4 and seam_visible(a))}

    tilt = np.degrees(np.arccos(np.clip(nrm[..., 2] * 2 - 1, -1, 1)))
    report["measured"] = {
        "px": size, "tiles": bool(tiles), "normal_scale": round(k, 3),
        "normal_tilt_deg_p50_p90_p99": [round(_pct(tilt, q), 1) for q in (50, 90, 99)],
        "roughness_p2_p50_p98": [round(_pct(rough, q), 3) for q in (2, 50, 98)],
        "ao_p2_p50": [round(_pct(ao, q), 3) for q in (2, 50)],
        "height_std": round(float(hgt.std()), 3),
    }
    if tiles:
        bad = {r: m["seam_ratio"] for r, m in report["maps"].items() if m["seam_visible"]}
        if bad:
            report["problems"].append("maps with a visible seam: %s" % bad)
    if report["measured"]["normal_tilt_deg_p50_p90_p99"][2] > 70:
        report["notes"].append("1% of normals tilt over 70 degrees: lower --tilt-deg if it sparkles in VR")

    chunks = png_chunks(src)
    with open(src, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    known = {"IHDR", "PLTE", "IDAT", "IEND"}
    side = {"source": os.path.abspath(src), "sha256": digest, "px": report["source_px"], "loader": info,
            "ancillary_png_chunks": sorted({t for t, _ in chunks if t not in known}),
            "c2pa_manifest_in_source": any(t == "caBX" for t, _ in chunks),
            "tile_px": report.get("tileable_px", [w0, h0]), "tile_aspect": report["tile_aspect"],
            "maps": sorted(os.path.basename(m["path"]) for m in report["maps"].values())}
    with open(stem + "source.json", "w", encoding="utf-8") as f:
        json.dump(side, f, indent=2)
    report["source_record"] = os.path.abspath(stem + "source.json")
    if side["c2pa_manifest_in_source"]:
        report["notes"].append("the source carries a C2PA manifest (content credentials): its origin is recorded in "
                               "%s; record the licence and generator terms beside the maps too"
                               % os.path.basename(stem + "source.json"))

    if preview:
        write_png(os.path.join(out_dir, "preview_tile3x3.png"), np.tile(bc, (3, 3, 1))[::2, ::2] if size > 1024
                  else np.tile(bc, (3, 3, 1)), 8)
        write_png(os.path.join(out_dir, "preview_lit.png"), np.tile(lit_preview(bc, nrm, ao), (2, 2, 1)), 8)
        report["previews"] = [os.path.abspath(os.path.join(out_dir, n)) for n in ("preview_tile3x3.png",
                                                                                   "preview_lit.png")]
    with open(os.path.join(out_dir, "image_to_pbr_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    return report


def main(argv):
    ap = argparse.ArgumentParser(prog="image_to_pbr.py", description=__doc__.split("\n")[0])
    ap.add_argument("src")
    ap.add_argument("--out", required=True)
    ap.add_argument("--family", required=True, help="2-5 capitals, e.g. RUG, INT")
    ap.add_argument("--name", required=True, help="letters and digits, e.g. Persian")
    ap.add_argument("--preset", choices=sorted(PRESETS), default="fabric")
    ap.add_argument("--size", type=int, help="output px (power of two); default the largest that fits, up to 2048")
    ap.add_argument("--make-tileable", action="store_true", help="cross-fade the seams when the source does not tile")
    t = ap.add_mutually_exclusive_group()
    t.add_argument("--tiling", dest="tiling", action="store_true", default=None, help="treat as tiling regardless")
    t.add_argument("--no-tiling", dest="tiling", action="store_false", help="a unique map: no wrap, no seam gate")
    ap.add_argument("--no-delight", action="store_true", help="keep broad lighting gradients in the base colour")
    ap.add_argument("--roughness", type=float, help="median roughness (overrides the preset)")
    ap.add_argument("--tilt-deg", type=float, help="90th-percentile normal tilt in degrees (overrides the preset)")
    ap.add_argument("--bands", type=float, nargs=3, metavar=("FINE", "MID", "BROAD"), help="height band weights")
    ap.add_argument("--ao-min", type=float, help="2nd-percentile AO (overrides the preset)")
    ap.add_argument("--metallic", type=int, choices=(0, 1))
    ap.add_argument("--invert-height", action="store_true", help="dark is high (e.g. raised dark grout)")
    ap.add_argument("--pack", choices=("unity", "orm", "none"), default="unity")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--normals", choices=("auto", "deepbump", "builtin"), default="auto",
                    help="auto: DeepBump when installed (not for fabric), else built-in; deepbump: a PROBLEM if missing")
    ap.add_argument("--deepbump", help="DeepBump install folder (default: setup_deepbump.py's)")
    a = ap.parse_args(argv)
    if a.size and a.size & (a.size - 1):
        print("--size must be a power of two", file=sys.stderr)
        return 2
    try:
        r = convert(a.src, a.out, a.family, a.name, a.preset, a.size, a.make_tileable, a.tiling, not a.no_delight,
                    a.roughness, a.tilt_deg, a.bands, a.ao_min, a.metallic, a.invert_height, a.pack, a.preview,
                    a.normals, a.deepbump)
    except (ValueError, OSError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    m = r["measured"]
    print("%s -> %s (%d px, tiles: %s, normals: %s)" % (os.path.basename(a.src), os.path.abspath(a.out), m["px"],
                                                         m["tiles"], r["normal_source"]))
    print("  base colour luma p0.5/median/p99.5: %s -> %s" % (r["base_colour"]["luma_before"],
                                                            r["base_colour"]["luma_after"]))
    print("  normal tilt p50/p90/p99: %s deg; roughness p2/p50/p98: %s; AO p2/p50: %s"
          % (m["normal_tilt_deg_p50_p90_p99"], m["roughness_p2_p50_p98"], m["ao_p2_p50"]))
    print("  seam ratios: %s" % {k: v["seam_ratio"] for k, v in r["maps"].items()})
    for n in r["notes"]:
        print("NOTE: " + n)
    for pr in r["problems"]:
        print("PROBLEM: " + pr)
    return 1 if r["problems"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
