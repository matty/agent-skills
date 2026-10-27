"""Flatten the tile-scale variation out of a tiling map set, so its repeat stops reading as a grid.

A seamless tile still draws a grid on a wall when one part of it is lighter, greener or rougher than the rest: the
patch comes back every tile period. pbr_check.py --tiling measures that variation (tile_uniformity, a PROBLEM above
tile_lf_problem); this removes it, keeping the detail. A tiling map is periodic, so its tile-scale variation is
exactly its lowest harmonics: each map's harmonics up to --cycles cycles per tile (default 2) are taken out, tapering
(raised cosine) to none at twice that, and everything finer is kept. A blur-and-subtract at pbr_check's own scale
(1/8 of the tile) leaves a quarter of a once-per-tile wave behind, since that blur passes only 0.74 of it.
Variation the surface should have goes back on at another period, from another layer (a macro map, decals,
variants, the lightmap: pbr-texturing references/wear-and-variation.md).

Measured on Poly Haven 1k base colours (2026-10-27, tile_lf from pbr_check): weathered_brown_planks 0.0139 ->
0.0012, brown_mud_leaves_01 0.0118 -> 0.0019, cobblestone_floor_04 0.0201 -> 0.0036, aerial_grass_rock 0.0180 ->
0.0025, rocks_ground_02 0.0205 -> 0.0034; each 3 x 3 composite lost its bands and patches and kept its detail. What
it cannot remove: a distinctive feature inside the tile (rocks_ground_02's large pale rocks still repeat): retouch it
out or make it a decal.

Host: plain Python 3.9+ with numpy (or Blender's Python); imports pbr_check.py from this folder.

Command line (exit 0 when every map was written, 1 when one could not be read or has no known role, 2 when no file
matched):
    python tile_flatten.py "textures/T_EXT_Ground_*.png" --out textures/flat
    python tile_flatten.py "lib/forest_ground_1k_*.png" --out flat --keep 0.25    # keep a quarter of the variation

Roles come from the file name's last word: BaseColor / Albedo / Diffuse (sRGB colour, flattened by a gain per
channel in linear light, so the detail keeps its contrast and colour patches go as well as tone), Roughness /
Smoothness / AO / Height / Displacement and other grey maps (an offset on channel 0), MetallicSmoothness (an offset
on the smoothness in A; metallic stays binary), Normal / NormalGL / NormalDX (the low-harmonic tilt removed,
vectors renormalised). Flatten every map of a set together, or a patch stays in the maps left alone. Each output keeps
its source's channel count and bit depth and is a PNG: the names in --out are the source names with .png (a .jpg or
.tga source, read through Blender or Pillow, comes out as <name>.png).

As a module: flatten(px, role, cycles=2.0, keep=0.0) returns the new float (height, width, 4) array; role_of(path).
"""

import glob
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pbr_check as pc  # noqa: E402

COLOUR = {"basecolor", "albedo", "diffuse", "albedotransparency", "color", "colour"}
NORMAL = {"normal", "normalgl", "normaldx"}
PACKED = {"metallicsmoothness"}
GREY = {"roughness", "smoothness", "ao", "occlusion", "height", "displacement", "bump", "specular", "gloss",
        "glossiness"}


def role_of(path):
    """'colour', 'normal', 'packed', 'grey' or None, from the last word of the file name."""
    stem = os.path.splitext(os.path.basename(path))[0]
    word = stem.rsplit("_", 1)[-1].lower()
    for name, words in (("colour", COLOUR), ("normal", NORMAL), ("packed", PACKED), ("grey", GREY)):
        if word in words:
            return name
    return None


def _srgb_to_linear(c):
    np = pc._np()
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(c):
    np = pc._np()
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1.0 / 2.4) - 0.055)


def low_harmonics(a, cycles=2.0):
    """The part of a periodic (height, width) array made of harmonics up to `cycles` cycles per tile, tapering
    (raised cosine) to none at 2 x cycles; the mean (0 cycles) included."""
    np = pc._np()
    h, w = a.shape
    k = np.hypot(np.fft.fftfreq(h)[:, None] * h, np.fft.fftfreq(w)[None, :] * w)
    t = np.clip((2.0 * cycles - k) / max(cycles, 1e-9), 0.0, 1.0)
    return np.real(np.fft.ifft2(np.fft.fft2(a) * (0.5 - 0.5 * np.cos(np.pi * t))))


def flatten(px, role, cycles=2.0, keep=0.0):
    """px: float (height, width, 4) in 0-1 as pbr_check.load returns it. keep: the share of the tile-scale variation
    to leave in (0 removes it)."""
    np = pc._np()
    out = np.array(px, dtype=np.float64)
    k = 1.0 - keep
    if role == "colour":
        lin = _srgb_to_linear(out[:, :, :3])
        for c in range(3):
            broad = np.maximum(low_harmonics(lin[:, :, c], cycles), 1e-5)
            lin[:, :, c] *= (lin[:, :, c].mean() / broad) ** k
        out[:, :, :3] = _linear_to_srgb(lin)
    elif role == "normal":
        v = out[:, :, :3] * 2.0 - 1.0
        for c in (0, 1):
            b = low_harmonics(v[:, :, c], cycles)
            v[:, :, c] -= k * (b - b.mean())
        v[:, :, 2] = np.maximum(v[:, :, 2], 0.05)
        v /= np.linalg.norm(v, axis=2, keepdims=True)
        out[:, :, :3] = v * 0.5 + 0.5
    elif role in ("grey", "packed"):
        ch = 3 if role == "packed" else 0
        b = low_harmonics(out[:, :, ch], cycles)
        out[:, :, ch] -= k * (b - b.mean())
        if role == "grey":
            out[:, :, 1] = out[:, :, 2] = out[:, :, 0]
    else:
        raise ValueError("unknown role %r" % role)
    return np.clip(out, 0.0, 1.0).astype(np.float32)


def write_png(path, px, channels=4, depth=8):
    """Save float (height, width, 4) in 0-1 as a PNG of 1-4 channels at 8 or 16 bits (rows top to bottom)."""
    np = pc._np()
    channels = channels or 4
    a = np.asarray(px, np.float64)
    a = a[:, :, :1] if channels == 1 else (np.dstack([a[:, :, 0], a[:, :, 3]]) if channels == 2 else
                                           a[:, :, :channels])
    depth = 16 if depth == 16 else 8
    top = 65535.0 if depth == 16 else 255.0
    b = np.round(np.clip(a, 0.0, 1.0) * top).astype(">u2" if depth == 16 else np.uint8)
    h, w = b.shape[:2]
    raw = b"".join(b"\x00" + b[y].tobytes() for y in range(h))
    colour_type = {1: 0, 2: 4, 3: 2, 4: 6}[channels]

    def chunk(t, body):
        return struct.pack(">I", len(body)) + t + body + struct.pack(">I", zlib.crc32(t + body) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, depth, colour_type, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def _measure(px, role):
    """The pbr_check figure for this role: lf (colour), lf_smoothness (packed), lf_tilt_deg (normal), or the std of
    a grey map's blurred channel."""
    if role == "colour":
        return pc.tile_uniformity(px, "BaseColor")["lf"]
    if role == "packed":
        return pc.tile_uniformity(px, "MetallicSmoothness")["lf_smoothness"]
    if role == "normal":
        return pc.tile_uniformity(px, "Normal")["lf_tilt_deg"]
    return round(float(pc._blur_wrap(px[:, :, 0].astype("float64"), pc.PBR_LIMITS["tile_lf_sigma"]).std()), 4)


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="tile_flatten.py", description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="+", help="maps or quoted globs; the role comes from the name's last word")
    ap.add_argument("--out", required=True, help="folder for the flattened maps (never the source folder)")
    ap.add_argument("--cycles", type=float, default=2.0,
                    help="remove harmonics up to this many cycles per tile, tapering to none at twice it "
                         "(default %(default)s)")
    ap.add_argument("--keep", type=float, default=0.0, help="share of the tile-scale variation to keep, 0-1")
    args = ap.parse_args(argv)
    paths = []
    for p in args.paths:
        hits = sorted(glob.glob(p))
        paths.extend(hits if hits else [p])
    paths = [p for p in paths if os.path.isfile(p)]
    if not paths:
        print("[flatten] no files matched")
        return 2
    os.makedirs(args.out, exist_ok=True)
    bad = 0
    for path in paths:
        dst = os.path.join(args.out, os.path.splitext(os.path.basename(path))[0] + ".png")
        if os.path.abspath(args.out) == os.path.dirname(os.path.abspath(path)):
            print("PROBLEM %s: --out is the source folder; refusing to overwrite" % path)
            bad += 1
            continue
        role = role_of(path)
        if role is None:
            print("PROBLEM %s: no known map role in the name (BaseColor, Normal, Roughness, ...)" % path)
            bad += 1
            continue
        try:
            px, info = pc.load(path)
        except (ValueError, OSError) as e:
            print("PROBLEM %s: unreadable: %s" % (path, e))
            bad += 1
            continue
        flat = flatten(px, role, args.cycles, args.keep)
        write_png(dst, flat, info.get("channels"), info.get("depth"))
        print("[flatten] %s (%s): %s -> %s" % (os.path.basename(path), role, _measure(px, role), _measure(flat, role)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]))
