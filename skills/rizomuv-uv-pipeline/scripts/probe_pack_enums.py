"""Re-verify the undocumented Pack behaviour this skill relies on. Run it after every RizomUV upgrade.

Host: any Python 3.6-3.13 that RizomUVLink supports (Blender's bundled python.exe works), RizomUV 2027.0.417+
installed (no bpy, no numpy).   <python> probe_pack_enums.py

The enum integers are not published (only their names), and three behaviours are not in the docs at all.
Each check prints PASS or FAIL; exit code 1 if anything changed. Measured PASS on 2027.0.598:
  - Scaling.Mode is 0-based in the documented order: 0 OFF, 1 SET_3D_AREA, 2-5 the average-ratio modes,
    6 USER_SPECIFIED, 7 TEXEL_DENSITY, 8 PIXEL (9 MAP is internal and crashes the command)
  - LayoutScalingMode: 0 DISABLED, 1 TRANSLATE_ONLY, 2 BEST_FIT, 3 FORCE_FIT
  - Scaling.Optimization defaults to "Fill": Scaling.Mode sets the islands' relative sizes, then the whole
    layout is scaled to fill the tile, so absolute requests (modes 1, 6, 7) are lost. Pass "None" for them
  - Scaling.TexelDensity is read per 100 mesh units (RizomUV takes the coordinates as centimetres), so
    metre input needs TD x 100. USER_SPECIFIED with SpecifiedScale = px_per_unit / map_px avoids the question
  - a scale that cannot fit in the tile leaves the islands untouched, with no error and the same return value
  - a top-level "Global" parameter is rejected, although the docstring describes one
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rizom_link import rizom_session  # noqa: E402

# 2 x 1 x 0.5 box (7 m2), every face its own island, island i seeded at scale SEED[i]
SX, SY, SZ = 2.0, 1.0, 0.5
SEED = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
FACES = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]


def box(k=1.0):
    v = [(x * SX * k, y * SY * k, z * SZ * k) for z in (0, 1) for y in (0, 1) for x in (0, 1)]
    sizes, ids, uvw_ids, uvw = [], [], [], []
    for fi, f in enumerate(FACES):
        pts = [v[i] for i in f]
        drop = next(a for a in range(3) if len({p[a] for p in pts}) == 1)
        keep = [a for a in range(3) if a != drop]
        sizes.append(4)
        ids.extend(f)
        for p in pts:
            uvw_ids.append(len(uvw) // 3)
            uvw.extend((p[keep[0]] * SEED[fi], p[keep[1]] * SEED[fi], 0.0))
    return v, {"Data.PolySizes": sizes, "Data.PolyXYZIDs": ids, "Data.CoordsXYZ": [c for p in v for c in p],
               "Data.PolyUVWIDs": uvw_ids, "Data.CoordsUVW": uvw}


def dist(a, b):  # math.dist needs 3.8
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def ratios(v, d):
    ids, uv = d["PolyUVWIDs"], d["CoordsUVW"]
    out = []
    for fi, f in enumerate(FACES):
        a, b, _, dd = (v[i] for i in f)
        a3 = dist(a, b) * dist(a, dd)
        p = [(uv[3 * ids[4 * fi + k]], uv[3 * ids[4 * fi + k] + 1]) for k in range(4)]
        a2 = abs(sum(p[k][0] * p[(k + 1) % 4][1] - p[(k + 1) % 4][0] * p[k][1] for k in range(4))) / 2
        out.append(math.sqrt(a2 / a3))
    us, vs = uv[0::3], uv[1::3]
    return out, (max(us) - min(us), max(vs) - min(vs))


def run(link, scaling=None, layout=1, k=1.0, extra=None):
    v, data = box(k)
    link.Load(data)
    link.IslandGroups({"Mode": "DistributeInTilesEvenly", "WorkingSet": "Visible"})
    p = {"RootGroup": "RootGroup", "WorkingSet": "Visible", "RecursionDepth": 1, "Translate": True,
         "Strategy": "PaddingPerfect", "UsePixelUnit": True, "PaddingSizePx": 4, "MarginSizePx": 2,
         "MapResolution": 1024, "Rotate": {"Step": 0.0}, "LayoutScalingMode": layout, "Device": "CPU"}
    if scaling is not None:
        p["Scaling"] = scaling
    p.update(extra or {})
    link.Pack(p)
    return ratios(v, link.Save({"Data": True})["Data"])


def main():
    avg = math.sqrt(sum(s * s * a for s, a in zip(SEED, (2, 2, 1, 1, .5, .5))) / 7.0)   # area-weighted seed ratio
    near = lambda r, x, tol=0.01: all(abs(q - x) <= tol * max(x, 1e-9) for q in r)  # noqa: E731
    seeds = lambda r: all(abs(q - s) < 1e-4 for q, s in zip(r, SEED))  # noqa: E731
    checks = []
    with rizom_session() as link:
        version = link.RizomUVVersion()
        none = lambda m, **kw: dict({"Mode": m, "Optimization": "None"}, **kw)  # noqa: E731
        fill0, fill6, fill2 = (run(link, {"Mode": 0})[0], run(link, {"Mode": 6, "SpecifiedScale": 0.05})[0],
                               run(link, {"Mode": 2})[0])
        checks.append(("default Optimization 'Fill' discards an absolute scale (mode 6 ends like mode 2)",
                       not near(fill6, 0.05) and near(fill6, fill2[0])))
        checks.append(("'Fill' keeps the relative island sizes Scaling.Mode set (mode 0)",
                       near([q / s for q, s in zip(fill0, SEED)], fill0[0] / SEED[0])))
        checks.append(("Scaling.Mode 0 = OFF (islands keep their scale)", seeds(run(link, none(0))[0])))
        checks.append(("Scaling.Mode 1 = SET_3D_AREA (ratio 1)", near(run(link, none(1), k=0.3)[0], 1.0)))
        for m in (2, 3, 4, 5):
            checks.append(("Scaling.Mode %d = an average-ratio mode" % m, near(run(link, none(m))[0], avg)))
        checks.append(("Scaling.Mode 6 = USER_SPECIFIED", near(run(link, none(6, SpecifiedScale=0.123))[0], 0.123)))
        checks.append(("Scaling.Mode 7 = TEXEL_DENSITY, per 100 units",
                       near(run(link, none(7, TexelDensity=30000.0))[0], 30000.0 / 100 / 1024)))
        r8 = run(link, none(8))[0]
        checks.append(("Scaling.Mode 8 = PIXEL (differs from 6 and 7)", not near(r8, 0.123) and not near(r8, avg)))
        _, ext1 = run(link, {"Mode": 2, "Optimization": "None"}, layout=1)
        _, ext2 = run(link, {"Mode": 2, "Optimization": "None"}, layout=2)
        checks.append(("LayoutScalingMode 1 = TRANSLATE_ONLY (no rescale)", max(ext1) < 0.97))
        checks.append(("LayoutScalingMode 2 = BEST_FIT (uniform scale up to the tile)",
                       max(ext2) > 0.98 and abs(ext2[0] / ext1[0] - ext2[1] / ext1[1]) < 0.005))
        _, ext3 = run(link, {"Mode": 2, "Optimization": "None"}, layout=3)
        checks.append(("LayoutScalingMode 3 = FORCE_FIT (both axes fill)", min(ext3) > 0.98))
        checks.append(("a scale that cannot fit leaves the islands untouched",
                       seeds(run(link, none(6, SpecifiedScale=0.6))[0])))
        try:
            run(link, extra={"Global": {"Scaling": {"Mode": 0}}})
            checks.append(("top-level 'Global' is rejected", False))
        except Exception as ex:  # noqa: BLE001  (must be the rejection itself, not any failure)
            checks.append(("top-level 'Global' is rejected ('not recognized')",
                           "Global" in str(ex) and "not recognized" in str(ex)))
    print("RizomUV", version)
    for label, ok in checks:
        print("  %s  %s" % ("PASS" if ok else "FAIL", label))
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
