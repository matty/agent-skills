"""PBR value checks for exported texture maps: base colour, Unity-style metallic-smoothness and tangent-space normal
maps, plus for tiling maps the seam metrics, the tile-scale variation that makes a repeat read as a grid, and 3 x 3
composites.

Shipped identically in the pbr-texturing and vrchat-world-qa skills (tools/check_conventions.py fails when the copies
differ): the texturing skill runs it before reporting, QA runs it through `qa_measure.py --pbr`.

Host: plain Python 3.9+ with numpy, or Blender 4.2+ (bpy and its bundled numpy), no add-ons; tested on Blender 5.2.2.
Inside Blender it loads images with bpy (fast); elsewhere it reads PNG itself (8 and 16 bits per channel, every
filter, no interlacing; slow on big maps) and other formats through Pillow when that is installed.

Command line (exit 1 when any map has a PROBLEM, 2 when nothing could be checked; NOTE lines are advisory):
    python pbr_check.py "blender/textures/EXT/*.png" --map-px 1024 --json pbr.json
    blender -b --factory-startup --python-exit-code 1 --python pbr_check.py -- "blender/textures/*/*.png"
    python pbr_check.py "T_EXT_Brick_*.png" --targets '{"M_EXT_Brick": {"albedo_srgb": [60, 150], "roughness": [0.6, 0.95]}}'
    python pbr_check.py T_EXT_Brick_BaseColor.png --tiling --out qa/   # seams, tile-scale variation, 3 x 3 composite
    python pbr_check.py "T_TRIM_Sheet01_*.png" --trim                  # a trim sheet: the same, along U only

Maps pair by file name: T_<FAMILY>_<Name>_BaseColor.png (sRGB colour, A opacity or unused),
T_<FAMILY>_<Name>_MetallicSmoothness.png (R metallic, A smoothness = 1 - roughness, as Unity's Standard and VRChat's
Standard Lite read it) and T_<FAMILY>_<Name>_Normal.png (tangent space, OpenGL Y+). With a metallic-smoothness map,
each base-colour pixel is judged as metal (metallic 0.5 or more) or dielectric; without one, all as dielectric.
Targets (--targets JSON, or --spec world/spec.yaml's look.materials, which needs PyYAML) narrow one material:
albedo_srgb [lo, hi] for the dielectric median luma, roughness [lo, hi] for the median roughness, metal true/false.

As a module (QA and scripts): check_files(paths, map_px=None, targets=None, tiling=False, out_dir=None) (tiling True,
or "x" for a trim sheet) returns one dict per material with its stats, "problems" and "notes"; load(path) returns
(pixels, info), pixels a float32 (height, width, 4) array of stored codes / max code, rows top to bottom.
"""

import glob
import json
import math
import os
import re
import struct
import sys
import zlib

# Limits. Base colour (sRGB codes, judged as Rec. 709 luma): dielectrics no darker than 30 (tolerant) or 50 (strict)
# and no brighter than 240; raw metals 180-255 (70-100% reflectance); metallic is binary, greys only for blends:
# Adobe's "The PBR Guide, Part 2" (https://www.adobe.com/learn/substance-3d-designer/web/the-pbr-guide-part-2,
# checked 2026-10-18). Measured titanium is luma 171 (linear 0.441, 0.400, 0.361: https://physicallybased.info,
# checked 2026-10-18), so a metal fails only under 160 and gets a NOTE under the guide's 180. The percentiles, the
# shares and every smoothness and normal-map number are this check's own working rules.
PBR_LIMITS = dict(
    albedo_srgb=(30, 240),       # dielectric luma at the low and high percentile: a PROBLEM outside
    albedo_strict_low=50,        # the guide's strict dark limit: a NOTE between it and the tolerant 30
    albedo_percentiles=(1, 99),  # judged at these percentiles, so specks and island edges do not fail a map
    metal_srgb_min=160,          # raw metal luma at metal_percentile: a PROBLEM below (titanium measures 171)
    metal_strict_min=180,        # the guide's raw-metal floor: a NOTE between it and metal_srgb_min
    metal_percentile=5,
    metal_threshold=0.5,         # a pixel with metallic at least this is judged as metal
    metallic_mid=(0.1, 0.9),     # metallic strictly between these is a blend (grey metal)
    metallic_mid_share=0.10,     # a PROBLEM when more of the map than this is grey metal
    metallic_mid_note=0.02,      # a NOTE above this share
    metal_false_share=0.01,      # with the target metal: false, a PROBLEM when more of the map than this is metal
    smoothness_flat_std=0.02,    # a NOTE: smoothness this even reads as one flat sheen (CG-clean)
    smoothness_mirror=0.98,      # a NOTE when more than smoothness_mirror_share of the map is at least this smooth
    smoothness_mirror_share=0.05,
    alpha_cutoff=0.5,            # base-colour pixels less opaque than this (cutout) are left out
    normal_length=(0.9, 1.1),    # mean length of the decoded vectors: a PROBLEM outside (not a unit normal map, or
                                 # colour-converted on export)
    normal_neg_z_share=0.01,     # a PROBLEM when more pixels than this point into the surface (blue under 128)
    normal_bias=0.1,             # a NOTE when the mean X or Y is further from 0: the whole surface leans one way
    convention_r=0.3,            # Y-convention verdict when the mixed-derivative correlation is at least this far from 0
                                 # (measured: Substance 3D baker 16.0.7 bakes +0.72 OpenGL, -0.63 its DirectX default)
    convention_min_pixels=200,   # fewer content pixels than this: the convention is "unclear"
    convention_max_px=1024,      # the convention test pools a larger map down to at most this many pixels a side
    # Tiling maps (--tiling). Calibrated 2026-10-27 on 20 Poly Haven 1k tiling materials, each judged by eye in a
    # 3 x 3 composite: the six with an obvious grid measured tile_lf 0.0118-0.0205, ten with a milder repeat
    # 0.0012-0.0126, four with none 0.0000-0.0088; the windowed seam of all 20 (seamless) measured 0.08-1.06. At
    # 0.011, 7 of 20 fail: the six, and ganges_river_pebbles (0.0126), judged milder.
    tile_lf_sigma=0.125,         # tile-scale variation: Gaussian blur of this share of the tile per axis, wrapped
    tile_lf_chroma=2.0,          # OKLab a and b weighted against L: colour patches at this scale show more than tone
    tile_lf_problem=0.011,       # base colour: RMS OKLab distance of the blurred tile from its mean, a PROBLEM above
    tile_lf_note=0.006,          # and a NOTE above
    tile_lf_smoothness=0.01,     # smoothness: std of the blurred tile above this, a NOTE (sheen blotches)
    tile_lf_tilt_deg=2.0,        # normal map: RMS tilt of the blurred tile above this, a NOTE (shading blotches)
    tile_seam_windows=16,        # windowed seam: each wrap edge in this many windows
    tile_seam_note=1.0,          # its worst window against the texture's own p99.9 step: a NOTE above
    tile_seam_problem=1.5,       # a PROBLEM above
)

ROLES = {"basecolor": "BaseColor", "albedo": "BaseColor", "albedotransparency": "BaseColor",
         "metallicsmoothness": "MetallicSmoothness", "normal": "Normal"}
OTHER_ROLES = {"occlusion", "ao", "emission", "height", "detailmask", "mask"}   # recognised, not judged here
MAP_RE = re.compile(r"^(.*)_([A-Za-z]+)$")
LUMA = (0.2126, 0.7152, 0.0722)


def _np():
    import numpy
    return numpy


# ---- loading ------------------------------------------------------------------------------------------------------

def png_header(path):
    """(width, height, bit depth, colour type, interlace) from a PNG's IHDR, or None for any other file."""
    with open(path, "rb") as f:
        head = f.read(33)
    if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    w, h, depth, colour, _comp, _filt, interlace = struct.unpack(">IIBBBBB", head[16:29])
    return w, h, depth, colour, interlace


PNG_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}      # PNG colour type -> channels stored


def _unfilter(raw, height, stride, bpp):
    """Undo PNG's per-row filters (None, Sub, Up, Average, Paeth) on the decompressed bytes."""
    np = _np()
    buf = np.frombuffer(raw, np.uint8)
    if buf.size != height * (stride + 1):
        raise ValueError("PNG image data is %d bytes, expected %d" % (buf.size, height * (stride + 1)))
    buf = buf.reshape(height, stride + 1)
    out = np.empty((height, stride), np.uint8)
    prev = np.zeros(stride, np.uint8)
    for y in range(height):
        ft, line = int(buf[y, 0]), buf[y, 1:]
        if ft == 0:
            cur = line.copy()
        elif ft == 1:        # Sub: running sum of each byte position within the pixel
            cur = (np.cumsum(line.reshape(-1, bpp), axis=0, dtype=np.uint32) % 256).astype(np.uint8).reshape(-1)
        elif ft == 2:        # Up (uint8 addition wraps modulo 256)
            cur = line + prev
        elif ft in (3, 4):   # Average and Paeth depend on the byte just decoded: a plain loop
            f, b, r = line.tolist(), prev.tolist(), [0] * stride
            for i in range(stride):
                a = r[i - bpp] if i >= bpp else 0
                if ft == 3:
                    r[i] = (f[i] + ((a + b[i]) >> 1)) & 255
                else:
                    c = b[i - bpp] if i >= bpp else 0
                    p = a + b[i] - c
                    pa, pb, pc = abs(p - a), abs(p - b[i]), abs(p - c)
                    pred = a if (pa <= pb and pa <= pc) else (b[i] if pb <= pc else c)
                    r[i] = (f[i] + pred) & 255
            cur = np.array(r, np.uint8)
        else:
            raise ValueError("PNG row %d has unknown filter type %d" % (y, ft))
        out[y] = cur
        prev = cur
    return out


def read_png(path):
    """A PNG as a float32 (height, width, 4) array of stored codes / max code, rows top to bottom, plus
    (channels stored, bit depth). Grey, grey + alpha, RGB, RGBA at 8 or 16 bits, and 8-bit palettes."""
    np = _np()
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("%s is not a PNG" % path)
    pos, idat, plte, trns, ihdr = 8, [], None, None, None
    while pos + 8 <= len(data):
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if ctype == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif ctype == b"PLTE":
            plte = body
        elif ctype == b"tRNS":
            trns = body
        elif ctype == b"IDAT":
            idat.append(body)
        elif ctype == b"IEND":
            break
    if ihdr is None:
        raise ValueError("%s has no IHDR" % path)
    w, h, depth, colour, _comp, _filt, interlace = ihdr
    if interlace:
        raise ValueError("%s is interlaced: save it without interlacing" % path)
    if colour not in PNG_CHANNELS or depth not in ((8,) if colour == 3 else (8, 16)):
        raise ValueError("%s: colour type %d at %d bits is not supported (8 or 16 bits per channel)"
                         % (path, colour, depth))
    ch = PNG_CHANNELS[colour]
    bpp = ch * depth // 8
    rows = _unfilter(zlib.decompress(b"".join(idat)), h, w * bpp, bpp)
    if colour == 3:
        pal = np.frombuffer(plte, np.uint8).reshape(-1, 3).astype(np.float32) / 255.0
        alpha = np.ones(len(pal), np.float32)
        if trns:
            alpha[:len(trns)] = np.frombuffer(trns, np.uint8).astype(np.float32) / 255.0
        idx = rows.reshape(h, w)
        return np.dstack([pal[idx], alpha[idx]]).astype(np.float32), (4 if trns else 3, 8)
    if depth == 16:
        a = rows.view(">u2").reshape(h, w, ch).astype(np.float32) / 65535.0
    else:
        a = rows.reshape(h, w, ch).astype(np.float32) / 255.0
    return _rgba(a, ch), (ch, depth)


def _rgba(a, ch):
    np = _np()
    if ch == 1:
        return np.dstack([a[:, :, 0]] * 3 + [np.ones(a.shape[:2], np.float32)])
    if ch == 2:
        return np.dstack([a[:, :, 0]] * 3 + [a[:, :, 1]])
    if ch == 3:
        return np.dstack([a, np.ones(a.shape[:2], np.float32)])
    return a


def _load_bpy(path):
    import bpy
    np = _np()
    im = bpy.data.images.load(os.path.abspath(path), check_existing=False)
    try:
        im.colorspace_settings.name = "Non-Color"   # stored codes: no conversion (Blender linearises 16-bit PNGs)
        w, h = im.size
        if not w or not h:
            raise ValueError("Blender could not read %s" % path)
        px = np.empty(w * h * 4, np.float32)
        im.pixels.foreach_get(px)
        return px.reshape(h, w, 4)[::-1].copy()      # Blender's rows run bottom to top
    finally:
        bpy.data.images.remove(im)


def _in_blender():
    try:
        import bpy                                    # noqa: F401
        return hasattr(bpy, "data") and hasattr(bpy.data, "images")
    except ImportError:
        return False


def load(path):
    """(pixels, info): pixels a float32 (height, width, 4) array of stored codes / max code, rows top to bottom;
    info {"channels", "depth", "size", "loader"} with the channels and bit depth as stored (None when unknown)."""
    np = _np()
    head = png_header(path)
    ch = depth = None
    if head:
        ch, depth = PNG_CHANNELS.get(head[3]), head[2]
    if _in_blender():
        px, loader = _load_bpy(path), "bpy"
    elif head:
        px, (ch, depth) = read_png(path)
        loader = "png"
    else:
        try:
            from PIL import Image
        except ImportError:
            raise ValueError("%s is not a PNG and Pillow is not installed: export PNG" % path)
        with Image.open(path) as im:
            mode = im.mode
            im = im.convert("RGBA")
            px = np.asarray(im, np.float32) / 255.0
        ch, depth, loader = {"L": 1, "LA": 2, "RGB": 3, "RGBA": 4}.get(mode), 8, "pillow"
    if ch is None:                                    # unknown storage: alpha counts when it is used
        ch = 4 if float(px[:, :, 3].min()) < 1.0 else 3
    return px, {"channels": ch, "depth": depth, "size": [int(px.shape[1]), int(px.shape[0])], "loader": loader}


def write_png(path, rgba):
    """Save a float (height, width, 3 or 4) array in 0-1 as an 8-bit RGBA PNG (rows top to bottom), for composites."""
    np = _np()
    a = np.asarray(rgba, np.float32)
    if a.shape[2] == 3:
        a = np.dstack([a, np.ones(a.shape[:2], np.float32)])
    b = (np.clip(a, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    h, w = b.shape[:2]
    raw = b"".join(b"\x00" + b[y].tobytes() for y in range(h))

    def chunk(t, body):
        return struct.pack(">I", len(body)) + t + body + struct.pack(">I", zlib.crc32(t + body) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


# ---- statistics -----------------------------------------------------------------------------------------------------

def luma(rgb):
    """Rec. 709 luma of sRGB values on the 0-255 scale (rgb in 0-1, any leading shape)."""
    return (rgb[..., 0] * LUMA[0] + rgb[..., 1] * LUMA[1] + rgb[..., 2] * LUMA[2]) * 255.0


def _pct(np, v, q):
    return round(float(np.percentile(v, q)), 1) if v.size else None


def base_color_stats(px, info, metallic=None, limits=PBR_LIMITS):
    """Luma percentiles of the dielectric and the metal pixels. metallic: a (height, width) array or None."""
    np = _np()
    keep = np.ones(px.shape[:2], bool)
    if info.get("channels") in (2, 4):
        keep &= px[:, :, 3] >= limits["alpha_cutoff"]
    metal = np.zeros(px.shape[:2], bool)
    if metallic is not None and metallic.shape == metal.shape:
        metal = metallic >= limits["metal_threshold"]
    lum = luma(px[:, :, :3])
    die, met = lum[keep & ~metal], lum[keep & metal]
    lo, hi = limits["albedo_percentiles"]
    return {"pixels": int(keep.sum()), "metal_share": round(float((keep & metal).sum()) / max(int(keep.sum()), 1), 4),
            "dielectric_luma_p%g" % lo: _pct(np, die, lo), "dielectric_luma_p50": _pct(np, die, 50),
            "dielectric_luma_p%g" % hi: _pct(np, die, hi),
            "metal_luma_p%g" % limits["metal_percentile"]: _pct(np, met, limits["metal_percentile"]),
            "opacity_used": bool(info.get("channels") in (2, 4) and float(px[:, :, 3].min()) < 1.0)}


def metallic_smoothness_stats(px, info, limits=PBR_LIMITS):
    np = _np()
    m, s = px[:, :, 0], px[:, :, 3]
    lo, hi = limits["metallic_mid"]
    return {"has_alpha": info.get("channels") in (2, 4),
            "metal_share": round(float((m >= limits["metal_threshold"]).mean()), 4),
            "metallic_mid_share": round(float(((m > lo) & (m < hi)).mean()), 4),
            "smoothness_mean": round(float(s.mean()), 4), "smoothness_std": round(float(s.std()), 4),
            "smoothness_p1": round(float(np.percentile(s, 1)), 4), "smoothness_p50": round(float(np.percentile(s, 50)), 4),
            "smoothness_p99": round(float(np.percentile(s, 99)), 4),
            "mirror_share": round(float((s >= limits["smoothness_mirror"]).mean()), 4)}


def _pool(a, f):
    """Average-pool a (height, width) array by an integer factor (cropping the remainder)."""
    if f <= 1:
        return a
    h, w = (a.shape[0] // f) * f, (a.shape[1] // f) * f
    return a[:h, :w].reshape(h // f, f, w // f, f).mean(axis=(1, 3))


def normal_convention(n, limits=PBR_LIMITS):
    """Which green-channel convention a tangent-space normal map follows. A normal map that comes from a surface (a
    bake, or a height map) is the slope field of a height h, so its two estimates of the mixed derivative agree:
    d(gx)/dv = d(gy)/du = -h_uv for slopes gx, gy read as OpenGL (X right, Y up), while a DirectX map (Y down) makes
    them opposite. Their correlation r over the map is about +1 for OpenGL, -1 for DirectX and 0 for noise; island
    borders and padding weaken it but do not flip its sign. n: decoded vectors (height, width, 3), rows top to bottom.
    Returns ("opengl" | "directx" | "unclear", r, content pixels). A flipped red channel reads as "directx" too, and a
    map with no mixed-derivative content (straight grooves only, a flat map) is "unclear"."""
    np = _np()
    nz = np.clip(n[:, :, 2], 0.2, None)
    gx, gy = n[:, :, 0] / nz, n[:, :, 1] / nz              # slopes: X along the row, Y up the image
    f = max(1, int(math.ceil(max(n.shape[:2]) / float(limits["convention_max_px"]))))
    gx, gy = _pool(gx, f), _pool(gy, f)
    if min(gx.shape) < 8:
        return "unclear", None, 0
    a = -np.gradient(gx, axis=0)[2:-2, 2:-2]   # d(gx)/dv with v up the image (= -row); one-sided borders dropped
    b = np.gradient(gy, axis=1)[2:-2, 2:-2]    # d(gy)/du
    count = int(((np.abs(a) + np.abs(b)) > 1e-3).sum())
    if count < limits["convention_min_pixels"]:
        return "unclear", None, count
    r = float((a * b).sum()) / math.sqrt(float((a * a).sum()) * float((b * b).sum()) + 1e-30)
    if r >= limits["convention_r"]:
        return "opengl", round(r, 3), count
    if r <= -limits["convention_r"]:
        return "directx", round(r, 3), count
    return "unclear", round(r, 3), count


def normal_stats(px, limits=PBR_LIMITS):
    np = _np()
    n = px[:, :, :3] * 2.0 - 1.0
    length = np.sqrt((n * n).sum(axis=2))
    conv, r, count = normal_convention(n, limits)
    return {"length_mean": round(float(length.mean()), 4), "length_p1": round(float(np.percentile(length, 1)), 4),
            "length_p99": round(float(np.percentile(length, 99)), 4),
            "neg_z_share": round(float((n[:, :, 2] < 0.0).mean()), 4),
            "mean_x": round(float(n[:, :, 0].mean()), 4), "mean_y": round(float(n[:, :, 1].mean()), 4),
            "convention": conv, "convention_r": r, "convention_pixels": count}


def tile_seam(px):
    """Seam metric for a tiling texture: the mean colour step across the wrap edges against the mean step between
    neighbouring pixels inside the tile, per axis (the same maths as vrchat-world-qa's qa_measure --tile-seam). Ratios
    at or below about 1 mean no visible seam; above, look at a 3 x 3 composite (a feature crossing the edge, or a
    smooth gradient whose steepest step falls on it, can raise it to about 1.6 legitimately)."""
    np = _np()
    a = px[:, :, :3]
    inner_x = float(np.abs(np.diff(a, axis=1)).mean())
    inner_y = float(np.abs(np.diff(a, axis=0)).mean())
    edge_x = float(np.abs(a[:, 0] - a[:, -1]).mean())
    edge_y = float(np.abs(a[0] - a[-1]).mean())
    return {"edge_x": round(edge_x, 5), "inner_x": round(inner_x, 5), "ratio_x": round(edge_x / max(inner_x, 1e-9), 2),
            "edge_y": round(edge_y, 5), "inner_y": round(inner_y, 5), "ratio_y": round(edge_y / max(inner_y, 1e-9), 2),
            "window_x": _window_seam(a, 1), "window_y": _window_seam(a, 0)}


def _window_seam(a, axis, windows=PBR_LIMITS["tile_seam_windows"]):
    """A seam along part of a wrap edge, which the whole-edge mean dilutes (a step on 5% of the edge): the wrap step
    averaged in windows of 1/windows of the edge, its worst window against the p99.9 of the same window statistic
    over every interior pixel pair, so a texture's own strong edges (plank gaps, grout) mask a seam no stronger
    than they are. axis 1: the x wrap (left against right column), 0: the y wrap."""
    np = _np()
    if axis == 0:
        a = a.transpose(1, 0, 2)
    n = a.shape[0]
    size = max(2, n // windows)
    k = n // size
    if k < 1 or a.shape[1] < 3:
        return None
    inner = np.abs(np.diff(a, axis=1)).mean(axis=2)[:k * size].reshape(k, size, -1).mean(axis=1)
    edge = np.abs(a[:, 0] - a[:, -1]).mean(axis=1)[:k * size].reshape(k, size).mean(axis=1)
    return round(float(edge.max()) / max(float(np.percentile(inner, 99.9)), 1e-9), 2)


def _blur_wrap(a, sigma_share, axes="xy"):
    """Gaussian blur of a (height, width) array with wrap-around (a tiling map), sigma a share of each axis; axes
    "x" (a trim sheet) blurs across the rows at a quarter of it: a strip constant along U stays constant along each
    row however it is blurred in V, so this only quiets the noise a blur along U alone leaves."""
    np = _np()
    h, w = a.shape
    fy = np.fft.fftfreq(h)[:, None] * h * (sigma_share if axes == "xy" else sigma_share / 4.0)
    fx = np.fft.fftfreq(w)[None, :] * w * sigma_share
    return np.real(np.fft.ifft2(np.fft.fft2(a) * np.exp(-2.0 * math.pi ** 2 * (fy * fy + fx * fx))))


def oklab(rgb):
    """sRGB-encoded colour (..., 3) in 0-1 to OKLab (Bjorn Ottosson, https://bottosson.github.io/posts/oklab/)."""
    np = _np()
    c = np.clip(np.asarray(rgb, dtype=np.float64), 0.0, 1.0)
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929], [0.2119034982, 0.6806995451, 0.1073969566],
                   [0.0883024619, 0.2817188376, 0.6299787005]])
    m2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468], [1.9779984951, -2.4285922050, 0.4505937099],
                   [0.0259040371, 0.7827717662, -0.8086757660]])
    return np.cbrt(c @ m1.T) @ m2.T


def _deviation(b, axes):
    """b less its mean: the whole map's, or with axes "x" each row's own (strips of a trim sheet differ on purpose)."""
    return b - (b.mean(axis=1, keepdims=True) if axes == "x" else b.mean(axis=(0, 1), keepdims=True))


def tile_uniformity(px, role, limits=PBR_LIMITS, axes="xy"):
    """Tile-scale variation in a tiling map: what draws a grid on a wall once the map repeats, however seamless its
    edges. The map is blurred with wrap-around at tile_lf_sigma of the tile, which keeps the variation one to three
    times per tile (patches, a light band, a darker corner) and removes the detail. BaseColor: RMS OKLab distance
    of the blurred map from its mean, chroma weighted tile_lf_chroma (`lf`); MetallicSmoothness: std of the blurred
    smoothness (`lf_smoothness`); Normal: RMS tilt in degrees of the blurred vectors (`lf_tilt_deg`). Repeated
    distinctive features (one big pale rock, a crack) are not measured: look at the composite for those. axes "x":
    a trim sheet, judged along its strips only (blurred along U, each row against its own mean)."""
    np = _np()
    s = limits["tile_lf_sigma"]
    if role == "BaseColor":
        lab = oklab(px[:, :, :3]) * np.array([1.0, limits["tile_lf_chroma"], limits["tile_lf_chroma"]])
        d = _deviation(np.dstack([_blur_wrap(lab[:, :, k], s, axes) for k in range(3)]), axes)
        return {"lf": round(float(np.sqrt((d * d).sum(axis=2).mean())), 4)}
    if role == "MetallicSmoothness":
        d = _deviation(_blur_wrap(px[:, :, 3].astype(np.float64), s, axes), axes)
        return {"lf_smoothness": round(float(np.sqrt((d * d).mean())), 4)}
    if role == "Normal":
        n = px[:, :, :3].astype(np.float64) * 2.0 - 1.0
        bx, by = (_deviation(_blur_wrap(n[:, :, c], s, axes), axes) for c in (0, 1))
        nz = np.clip(_blur_wrap(n[:, :, 2], s, axes), 0.2, None)
        tilt = np.degrees(np.arctan(np.hypot(bx, by) / nz))
        return {"lf_tilt_deg": round(float(np.sqrt((tilt * tilt).mean())), 2)}
    return {}


def composite_3x3(px, max_px=2048):
    """The map repeated 3 x 3 (pooled down so the composite is at most max_px a side), to look at for seams and
    repetition."""
    np = _np()
    tiled = np.tile(px, (3, 3, 1))
    f = max(1, int(math.ceil(max(tiled.shape[:2]) / float(max_px))))
    if f > 1:
        tiled = np.dstack([_pool(tiled[:, :, c], f) for c in range(tiled.shape[2])])
    return tiled


# ---- judging --------------------------------------------------------------------------------------------------------

def _pow2(n):
    return n > 0 and (n & (n - 1)) == 0


def material_key(path):
    """(material name or None, map role or None, key) from T_<FAMILY>_<Name>_<Map>.<ext>."""
    stem = os.path.splitext(os.path.basename(path))[0]
    m = MAP_RE.match(stem)
    if not m:
        return None, None, stem
    base, suffix = m.group(1), m.group(2).lower()
    role = ROLES.get(suffix, suffix if suffix in OTHER_ROLES else None)
    if role is None:
        return None, None, stem
    mat = "M_" + base[2:] if base.startswith("T_") else None
    return mat, role, base


def judge(result, targets=None, limits=PBR_LIMITS):
    """Fill result["problems"] (blocking) and result["notes"] (advisory) from its stats and optional targets."""
    p, n = result.setdefault("problems", []), result.setdefault("notes", [])
    t = targets or {}
    lo_q, hi_q = limits["albedo_percentiles"]
    bc = result.get("base_color")
    if bc:
        lo, hi = limits["albedo_srgb"]
        d_lo, d_hi = bc.get("dielectric_luma_p%g" % lo_q), bc.get("dielectric_luma_p%g" % hi_q)
        if d_lo is not None and d_lo < lo:
            p.append("base colour too dark: dielectric luma p%g %.1f under %d sRGB" % (lo_q, d_lo, lo))
        elif d_lo is not None and d_lo < limits["albedo_strict_low"]:
            n.append("base colour dark: dielectric luma p%g %.1f under the strict %d sRGB"
                     % (lo_q, d_lo, limits["albedo_strict_low"]))
        if d_hi is not None and d_hi > hi:
            p.append("base colour too bright: dielectric luma p%g %.1f over %d sRGB" % (hi_q, d_hi, hi))
        m_lo = bc.get("metal_luma_p%g" % limits["metal_percentile"])
        if m_lo is not None and m_lo < limits["metal_srgb_min"]:
            p.append("metal too dark: metal luma p%g %.1f under %d sRGB (dirt or rust on metal lowers metallic, "
                     "not only the colour)" % (limits["metal_percentile"], m_lo, limits["metal_srgb_min"]))
        elif m_lo is not None and m_lo < limits["metal_strict_min"]:
            n.append("metal dark: metal luma p%g %.1f under the guide's %d sRGB (right for titanium, 171; otherwise "
                     "dirt belongs in metallic)" % (limits["metal_percentile"], m_lo, limits["metal_strict_min"]))
        if "albedo_srgb" in t and bc.get("dielectric_luma_p50") is not None:
            a, b = t["albedo_srgb"]
            if not a <= bc["dielectric_luma_p50"] <= b:
                p.append("base colour off target: dielectric luma median %.1f outside %g-%g"
                         % (bc["dielectric_luma_p50"], a, b))
    ms = result.get("metallic_smoothness")
    if ms:
        if not ms["has_alpha"]:
            p.append("metallic-smoothness map has no alpha: Standard reads smoothness from A, so it renders fully "
                     "smooth")
        if ms["metallic_mid_share"] > limits["metallic_mid_share"]:
            p.append("metallic not binary: %.1f%% of the map between %g and %g"
                     % (100 * ms["metallic_mid_share"], limits["metallic_mid"][0], limits["metallic_mid"][1]))
        elif ms["metallic_mid_share"] > limits["metallic_mid_note"]:
            n.append("metallic greys on %.1f%% of the map: only blends (dust, paint wear) should be grey"
                     % (100 * ms["metallic_mid_share"]))
        if ms["has_alpha"]:
            if ms["smoothness_std"] < limits["smoothness_flat_std"]:
                n.append("smoothness almost uniform (std %.3f): one flat sheen reads as CG-clean" % ms["smoothness_std"])
            if ms["mirror_share"] > limits["smoothness_mirror_share"]:
                n.append("%.1f%% of the map is mirror-smooth (smoothness %g or more)"
                         % (100 * ms["mirror_share"], limits["smoothness_mirror"]))
            if "roughness" in t:
                a, b = t["roughness"]
                r = round(1.0 - ms["smoothness_p50"], 4)
                if not a <= r <= b:
                    p.append("roughness off target: median %.2f outside %g-%g" % (r, a, b))
        if t.get("metal") is False and ms["metal_share"] > limits["metal_false_share"]:
            p.append("metal where the target has none: %.1f%% of the map" % (100 * ms["metal_share"]))
        if t.get("metal") is True and ms["metal_share"] < 0.5:
            n.append("target is metal, but only %.1f%% of the map is" % (100 * ms["metal_share"]))
    nm = result.get("normal")
    if nm:
        lo, hi = limits["normal_length"]
        if not lo <= nm["length_mean"] <= hi:
            p.append("normal map vectors have mean length %.3f (expected %g-%g): not a unit normal map, or "
                     "colour-converted on export" % (nm["length_mean"], lo, hi))
        if nm["neg_z_share"] > limits["normal_neg_z_share"]:
            p.append("normal map points into the surface on %.1f%% of pixels" % (100 * nm["neg_z_share"]))
        if max(abs(nm["mean_x"]), abs(nm["mean_y"])) > limits["normal_bias"]:
            n.append("normal map leans: mean X %.3f, Y %.3f" % (nm["mean_x"], nm["mean_y"]))
        if nm["convention"] == "directx":
            p.append("normal map reads as DirectX (Y-) or with a flipped red channel (Y correlation %s): flip "
                     "green for OpenGL (Y+)" % nm["convention_r"])
        elif nm["convention"] == "unclear":
            n.append("normal map Y convention unclear (Y correlation %s): check a look-dev render lit from above"
                     % nm["convention_r"])
    for role, info in sorted(result.get("sizes", {}).items()):
        w, h = info["size"]
        if not (_pow2(w) and _pow2(h)):
            p.append("%s is %d x %d: not a power of two" % (role, w, h))
        if result.get("map_px") and max(w, h) > result["map_px"]:
            p.append("%s is %d x %d: larger than map_px %d" % (role, w, h, result["map_px"]))
    for role in result.get("unjudged", []):
        n.append("%s map recognised, not judged" % role)
    return result


def check_files(paths, map_px=None, targets=None, tiling=False, out_dir=None, limits=PBR_LIMITS):
    """Check every map in paths, grouped by material. targets: {material: {albedo_srgb, roughness, metal}}.
    tiling: False, True (tiles both ways) or "x" (a trim sheet: its strips tile along U only)."""
    axes = "x" if tiling == "x" else "xy"
    groups, unknown = {}, []
    for path in paths:
        mat, role, key = material_key(path)
        if role is None:
            unknown.append(path)
            continue
        groups.setdefault(key, {"material": mat, "maps": {}})["maps"][role] = path
    results = []
    for key, g in sorted(groups.items()):
        r = {"material": g["material"], "key": key, "maps": dict(g["maps"]), "map_px": map_px, "sizes": {},
             "unjudged": sorted(k for k in g["maps"] if k in OTHER_ROLES), "problems": [], "notes": []}
        loaded = {}
        for role, path in sorted(g["maps"].items()):
            try:
                loaded[role] = load(path)
                r["sizes"][role] = {"size": loaded[role][1]["size"], "channels": loaded[role][1]["channels"],
                                    "depth": loaded[role][1]["depth"]}
            except (ValueError, OSError) as e:
                r["problems"].append("%s map unreadable: %s" % (role, e))
        metallic = None
        if "MetallicSmoothness" in loaded:
            px, info = loaded["MetallicSmoothness"]
            r["metallic_smoothness"] = metallic_smoothness_stats(px, info, limits)
            metallic = px[:, :, 0]
        if "BaseColor" in loaded:
            px, info = loaded["BaseColor"]
            if metallic is not None and metallic.shape != px.shape[:2]:
                r["notes"].append("metallic-smoothness and base colour differ in size: base colour judged as all "
                                  "dielectric")
            r["base_color"] = base_color_stats(px, info, metallic, limits)
        if "Normal" in loaded:
            r["normal"] = normal_stats(loaded["Normal"][0], limits)
        if tiling:
            r["tile_seam"] = {}
            for role, (px, _info) in sorted(loaded.items()):
                r["tile_seam"][role] = tile_seam(px)
                if out_dir:
                    os.makedirs(out_dir, exist_ok=True)
                    dst = os.path.join(out_dir, "%s_%s_3x3.png" % (key, role))
                    write_png(dst, composite_3x3(px))
                    r["tile_seam"][role]["composite"] = dst
                ts = r["tile_seam"][role]
                ratio = ts["ratio_x"] if axes == "x" else max(ts["ratio_x"], ts["ratio_y"])
                if ratio > 1.0:
                    r["notes"].append("%s seam ratio x %.2f, y %.2f over 1: look at its 3 x 3 composite"
                                      % (role, ts["ratio_x"], ts["ratio_y"]))
                win = max(w for w in (ts["window_x"], ts["window_y"] if axes == "xy" else None, 0.0)
                          if w is not None)
                if win > limits["tile_seam_problem"]:
                    r["problems"].append("%s seam along part of a wrap edge: worst window %.2f x the texture's own "
                                         "p99.9 step (over %.1f; window x %s, y %s): make it seamless before use"
                                         % (role, win, limits["tile_seam_problem"], ts["window_x"], ts["window_y"]))
                elif win > limits["tile_seam_note"]:
                    r["notes"].append("%s worst wrap-edge window %.2f x the texture's p99.9 step: look at the composite"
                                      % (role, win))
                tu = tile_uniformity(px, role, limits, axes)
                ts.update(tu)
                if "lf" in tu and axes == "x" and tu["lf"] > limits["tile_lf_problem"]:
                    r["notes"].append("%s variation along the strips %.4f over %.3f (trim sheets are not calibrated: "
                                      "judge a long trim run in a wide view)" % (role, tu["lf"], limits["tile_lf_problem"]))
                elif "lf" in tu and axes == "x":
                    pass
                elif "lf" in tu and tu["lf"] > limits["tile_lf_problem"]:
                    r["problems"].append("%s tile-scale variation %.4f over %.3f: the repeat will read as a grid; "
                                         "flatten its low frequencies and take variation from another layer"
                                         % (role, tu["lf"], limits["tile_lf_problem"]))
                elif "lf" in tu and tu["lf"] > limits["tile_lf_note"]:
                    r["notes"].append("%s tile-scale variation %.4f over %.3f: judge the repeat in a wide view"
                                      % (role, tu["lf"], limits["tile_lf_note"]))
                if tu.get("lf_smoothness", 0) > limits["tile_lf_smoothness"]:
                    r["notes"].append("%s tile-scale smoothness variation %.4f over %.2f: sheen blotches repeat"
                                      % (role, tu["lf_smoothness"], limits["tile_lf_smoothness"]))
                if tu.get("lf_tilt_deg", 0) > limits["tile_lf_tilt_deg"]:
                    r["notes"].append("%s tile-scale normal tilt %.2f deg over %.1f: shading blotches repeat"
                                      % (role, tu["lf_tilt_deg"], limits["tile_lf_tilt_deg"]))
        judge(r, (targets or {}).get(g["material"]) or (targets or {}).get(key), limits)
        results.append(r)
    for path in unknown:
        results.append({"material": None, "key": os.path.basename(path), "maps": {}, "problems": [],
                        "notes": ["not checked: the name does not end in a known map type (_BaseColor, "
                                  "_MetallicSmoothness, _Normal)"]})
    return results


# ---- command line ---------------------------------------------------------------------------------------------------

def _targets(args):
    t = {}
    if args.spec:
        try:
            import yaml
        except ImportError:
            raise SystemExit("--spec needs PyYAML: pass --targets JSON instead")
        with open(args.spec, encoding="utf-8") as f:
            spec = yaml.safe_load(f) or {}
        t.update(((spec.get("look") or {}).get("materials")) or {})
    if args.targets:
        raw = args.targets
        if raw.startswith("@"):
            with open(raw[1:], encoding="utf-8") as f:
                raw = f.read()
        t.update(json.loads(raw))
    return t


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="pbr_check.py", description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="+", help="maps or quoted globs (T_<FAMILY>_<Name>_<Map>.png)")
    ap.add_argument("--map-px", type=int, help="the family's map_px: larger maps are a PROBLEM")
    ap.add_argument("--targets", help='JSON {"M_<FAMILY>_<Name>": {"albedo_srgb": [lo, hi], "roughness": [lo, hi], '
                                      '"metal": false}}, or @file')
    ap.add_argument("--spec", help="world/spec.yaml: targets from look.materials (needs PyYAML)")
    ap.add_argument("--tiling", action="store_true", help="also the seam and tile-scale variation checks per map")
    ap.add_argument("--trim", action="store_true", help="a trim sheet: --tiling along U only (strips differ in V)")
    ap.add_argument("--out", help="with --tiling or --trim: write a 3 x 3 composite per map here")
    ap.add_argument("--json", help="write the results here")
    args = ap.parse_args(argv)
    paths = []
    for p in args.paths:
        hits = sorted(glob.glob(p))
        paths.extend(hits if hits else [p])
    paths = [p for p in paths if os.path.isfile(p)]
    if not paths:
        print("[pbr] no files matched")
        return 2
    results = check_files(paths, args.map_px, _targets(args), "x" if args.trim else args.tiling, args.out)
    bad = 0
    for r in results:
        name = r["material"] or r["key"]
        bc, ms, nm = r.get("base_color") or {}, r.get("metallic_smoothness") or {}, r.get("normal") or {}
        parts = []
        if bc:
            parts.append("luma p1/p50/p99 %s/%s/%s" % (bc.get("dielectric_luma_p1"), bc.get("dielectric_luma_p50"),
                                                        bc.get("dielectric_luma_p99")))
        if ms:
            parts.append("metal %.0f%%, grey %.1f%%, smoothness %.2f +- %.2f" % (
                100 * ms["metal_share"], 100 * ms["metallic_mid_share"], ms["smoothness_mean"], ms["smoothness_std"]))
        if nm:
            parts.append("normal |n| %.3f, %s" % (nm["length_mean"], nm["convention"]))
        print("[pbr] %s: %s" % (name, "; ".join(parts) or "no judged maps"))
        for msg in r["problems"]:
            print("PROBLEM %s: %s" % (name, msg))
        for msg in r["notes"]:
            print("NOTE %s: %s" % (name, msg))
        bad += bool(r["problems"])
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
    print("[pbr] %d material(s), %d with problems" % (len(results), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    # Blender passes the script's own arguments after "--"; sys.exit sets Blender's exit code as well
    sys.exit(main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]))
