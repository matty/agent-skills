"""Viewing-distance maths for finishing a piece: texel class, stereo relief and the narrowest feature that holds up.

Host: plain Python 3.9+, standard library only (no Blender needed).

    python detail_scale.py 0.5 1 2 5 10            # a table at 20 pixels per degree (Quest 2 and 3S)
    python detail_scale.py 0.5 1 2 --ppd 25        # Quest 3
    import detail_scale as ds; ds.stereo_relief_m(1.0)   # 0.0139

Every number follows from the headset's pixels per degree (ppd) and the distance d (m) a surface is seen from
(references/form-and-detail.md has the reasoning):
- px_per_m(d): what the headset resolves on a surface at d, 1150 / d at 20 ppd (one metre at d spans 57.3 / d deg),
  scaled by ppd / 20.
- texel_class(d): the TEXEL_CLASSES entry whose band holds d. Each class gives at least two thirds of px_per_m at
  the near edge of its band; above 20 ppd the distance is scaled by 20 / ppd first, so a class steps up sooner.
- stereo_relief_m(d): the depth step that shifts one pixel between the two eyes, d^2 x theta_px / IPD with
  theta_px = (pi / 180) / ppd (about 0.014 x d^2 m at 20 ppd). Shallower relief looks the same as a normal map.
- min_width_m(d, px=2): the narrowest chamfer or thin part that stays px pixels wide at d; narrower ones shimmer.
"""

import argparse
import math
import sys

PX_PER_M_AT_1M = 1150      # pixels per metre of surface at 1 m on a 20 ppd headset: 57.3 deg per radian x 20
BASE_PPD = 20              # Quest 2 and 3S; Quest 3 is 25 (sources in references/form-and-detail.md)
IPD_M = 0.063              # interpupillary distance used for the stereo rule, the adult mean in metres
# (px per m, nearest viewing distance in m from which the class applies), nearest first
TEXEL_CLASSES = ((2048, 0.0), (1024, 0.75), (512, 1.5), (256, 3.0), (128, 6.0), (64, 12.0))


def _check(d, ppd):
    if not d > 0:
        raise ValueError("distance must be above 0 m, got %r" % (d,))
    if not ppd > 0:
        raise ValueError("ppd must be above 0, got %r" % (ppd,))


def px_per_m(d, ppd=BASE_PPD):
    """Pixels per metre of surface a headset of `ppd` pixels per degree resolves at `d` metres."""
    _check(d, ppd)
    return PX_PER_M_AT_1M * (ppd / BASE_PPD) / d


def texel_class(d, ppd=BASE_PPD):
    """The texel class (px per m) for a surface whose nearest viewing distance is `d` metres."""
    if d == 0:
        return TEXEL_CLASSES[0][0]
    _check(d, ppd)
    eff = d * BASE_PPD / ppd
    px = TEXEL_CLASSES[0][0]
    for cls, start in TEXEL_CLASSES:
        if eff >= start:
            px = cls
    return px


def stereo_relief_m(d, ppd=BASE_PPD, ipd=IPD_M):
    """Depth step (m) at `d` metres that gives one pixel of binocular disparity: d^2 x theta_px / IPD."""
    _check(d, ppd)
    if not ipd > 0:
        raise ValueError("ipd must be above 0 m, got %r" % (ipd,))
    theta_px = math.radians(1.0) / ppd
    return d * d * theta_px / ipd


def min_width_m(d, px=2, ppd=BASE_PPD):
    """Width (m) that spans `px` pixels at `d` metres: the narrowest chamfer or thin part that does not shimmer."""
    _check(d, ppd)
    return px / px_per_m(d, ppd)


def table(distances, ppd=BASE_PPD, px=2):
    """Rows of (d, px_per_m, class, relief mm, width mm) for the CLI and for reports."""
    return [(d, px_per_m(d, ppd), texel_class(d, ppd), stereo_relief_m(d, ppd) * 1000.0,
             min_width_m(d, px, ppd) * 1000.0) for d in distances]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("distances", nargs="+", type=float, help="viewing distances in metres")
    ap.add_argument("--ppd", type=float, default=BASE_PPD, help="headset pixels per degree (default 20)")
    ap.add_argument("--px", type=float, default=2, help="pixels a feature must span (default 2)")
    args = ap.parse_args(argv)
    try:
        rows = table(args.distances, args.ppd, args.px)
    except ValueError as e:
        ap.error(str(e))
    print("%8s %10s %7s %12s %12s" % ("d (m)", "px/m", "class", "relief mm", "%g px mm" % args.px))
    for d, need, cls, relief, width in rows:
        print("%8.2f %10.0f %7s %12.1f %12.1f" % (d, need, "T%d" % cls, relief, width))
    print("at %g ppd; relief: shallower reads as a normal map; width: narrower shimmers" % args.ppd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
