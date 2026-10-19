"""Plain-Python tests for 3d-form-design's scripts/form_audit.py on extruded profiles built here: a plain box, a small
chamfer, an oversized chamfer (the soap-bar case), a 3-segment round merged into one section, a cylinder's facets
and a plank's sides not taken for bevels, chamfers on the bottom contact face, one bevel width on parts of very
different size, a floating part, size tiers, silhouettes, the OBJ reader and the CLI's exit code.

Host: plain Python 3.9+, standard library. Run from the repo root:
    python -B -m unittest discover -s tools/tests -p "test_form_design_*.py"
"""

import importlib.util
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "3d-form-design" / "scripts" / "form_audit.py"


def load():
    keep = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("form_audit_under_test", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.dont_write_bytecode = keep


fa = load()


def rect_profile(w, h, c=0.0, segments=1):
    """Counter-clockwise (x, z) profile of a w x h rectangle centred on x, base at z=0, corners cut by c (segments > 1:
    a round of radius c)."""
    if c == 0:
        return [(-w / 2, 0), (w / 2, 0), (w / 2, h), (-w / 2, h)]
    pts = []
    corners = [((w / 2 - c, c), -90), ((w / 2 - c, h - c), 0), ((-w / 2 + c, h - c), 90), ((-w / 2 + c, c), 180)]
    for (cx, cz), start in corners:
        for k in range(segments + 1):
            a = math.radians(start + 90.0 * k / segments)
            if segments == 1:
                # a straight chamfer: the two tangent points only
                pass
            pts.append((cx + c * math.cos(a), cz + c * math.sin(a)))
    return pts


def circle_profile(r, n, z0=None):
    z0 = r if z0 is None else z0
    return [(r * math.cos(2 * math.pi * k / n), z0 + r * math.sin(2 * math.pi * k / n)) for k in range(n)]


def extrude(profile, length, offset=(0.0, 0.0, 0.0), base=0):
    """Extrude an (x, z) profile along +y; returns verts, faces (side quads, two n-gon caps), indices from base."""
    n = len(profile)
    ox, oy, oz = offset
    verts = [(x + ox, oy, z + oz) for x, z in profile] + [(x + ox, oy + length, z + oz) for x, z in profile]
    faces = []
    for i in range(n):
        j = (i + 1) % n
        faces.append((base + i, base + n + i, base + n + j, base + j))   # outward
    faces.append(tuple(base + i for i in range(n)))
    faces.append(tuple(base + n + i for i in reversed(range(n))))
    return verts, faces


def chamfered_cube(a, c, z0=None):
    """A cube of half-size a with every edge chamfered by c, as a one-segment Bevel modifier makes it: 6 faces, 12
    edge quads, 8 corner triangles, outward winding; resting on z=0 unless z0 is given."""
    b = a - c
    z0 = a if z0 is None else z0
    idx, verts = {}, []

    def v(sx, sy, sz, axis):
        k = (sx, sy, sz, axis)
        if k not in idx:
            p = [sx * b, sy * b, sz * b]
            p[axis] = (sx, sy, sz)[axis] * a
            idx[k] = len(verts)
            verts.append((p[0], p[1], p[2] + z0))
        return idx[k]

    faces = []
    signs = (-1, 1)
    for axis in range(3):
        for s in signs:
            q = []
            for u, w in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                c3 = [u, w]
                c3.insert(axis, s)
                q.append(v(c3[0], c3[1], c3[2], axis))
            faces.append(q)
        o1, o2 = [k for k in range(3) if k != axis]
        for s1 in signs:
            for s2 in signs:
                lo, hi = [0, 0, 0], [0, 0, 0]
                lo[axis], hi[axis] = -1, 1
                lo[o1] = hi[o1] = s1
                lo[o2] = hi[o2] = s2
                faces.append([v(*lo, o1), v(*hi, o1), v(*hi, o2), v(*lo, o2)])
    for sx in signs:
        for sy in signs:
            for sz in signs:
                faces.append([v(sx, sy, sz, 0), v(sx, sy, sz, 1), v(sx, sy, sz, 2)])
    out = []
    for f in faces:
        pts = [verts[i] for i in f]
        cen = [sum(p[k] for p in pts) / len(pts) for k in range(3)]
        cen[2] -= z0
        n = fa._newell(pts)[0]
        out.append(tuple(f) if sum(n[k] * cen[k] for k in range(3)) > 0 else tuple(reversed(f)))
    return verts, out


def combine(*meshes):
    verts, faces = [], []
    for v, f in meshes:
        b = len(verts)
        verts += v
        faces += [tuple(i + b for i in face) for face in f]
    return verts, faces


def keys(r):
    return [k for k, _ in fa.problems(r)]


class Bevels(unittest.TestCase):
    def test_plain_box_has_no_bevels_and_is_blocky(self):
        r = fa.audit(*extrude(rect_profile(0.4, 0.4), 1.0))
        self.assertEqual(r["bevels"], [])
        self.assertEqual(r["hard_edge_count"], 12)
        self.assertIn("blocky", keys(r))
        self.assertAlmostEqual(r["parts"][0]["fill"], 1.0, places=6)
        self.assertAlmostEqual(r["silhouettes"]["front"]["rectangularity"], 1.0, places=6)

    def test_small_chamfer_measured(self):
        r = fa.audit(*extrude(rect_profile(0.4, 0.4, 0.01), 1.0))
        self.assertEqual(len(r["bevels"]), 4)
        for s in r["bevels"]:
            self.assertAlmostEqual(s["width"], 0.01 * math.sqrt(2), places=6)
            self.assertAlmostEqual(s["flat"], 0.38, places=6)
            self.assertAlmostEqual(s["turn"], 90.0, places=4)
        self.assertNotIn("over_bevelled", keys(r))
        self.assertEqual(len(r["bevel_tiers"]), 1)

    def test_soap_bar_chamfer_fails(self):
        r = fa.audit(*extrude(rect_profile(0.05, 0.05, 0.02), 0.5))
        self.assertEqual(len(r["bevels"]), 4)
        self.assertIn("over_bevelled", keys(r))

    def test_round_merges_segments(self):
        r = fa.audit(*extrude(rect_profile(0.4, 0.4, 0.02, segments=3), 1.0))
        self.assertEqual(len(r["bevels"]), 4)
        arc = 3 * 2 * 0.02 * math.sin(math.radians(15))   # three chords of a 90 deg arc
        for s in r["bevels"]:
            self.assertEqual(len(s["faces"]), 3)
            self.assertAlmostEqual(s["width"], arc, places=6)

    def test_cylinder_and_plank_sides_are_not_bevels(self):
        r = fa.audit(*extrude(circle_profile(0.1, 32), 1.0))
        self.assertEqual(r["bevels"], [])
        r = fa.audit(*extrude(rect_profile(1.0, 0.02), 1.0))
        self.assertEqual(r["bevels"], [])

    def test_contact_bevel(self):
        r = fa.audit(*extrude(rect_profile(0.4, 0.4, 0.01), 1.0))
        self.assertEqual(sum(1 for s in r["bevels"] if s["contact"]), 2)
        self.assertIn("contact_bevelled", keys(r))

    def test_every_edge_bevelled_warning(self):
        # chamfered along the length only: the cap edges stay hard, so no warning
        r = fa.audit(*extrude(rect_profile(0.4, 0.4, 0.01), 1.0))
        self.assertNotIn("warn_every_edge_bevelled", keys(r))
        self.assertGreater(r["hard_edge_count"], 0)

    def test_one_width_on_parts_of_different_size(self):
        big = extrude(rect_profile(1.0, 0.1, 0.005), 1.0)
        small = extrude(rect_profile(0.05, 0.05, 0.005), 0.2, offset=(0.0, 0.4, 0.1), base=len(big[0]))
        r = fa.audit(*combine(big, ([v for v in small[0]], [tuple(i - len(big[0]) for i in f) for f in small[1]])))
        self.assertEqual(len(r["bevels"]), 8)
        self.assertIn("one_bevel_width", keys(r))

    def test_bevel_modifier_cube(self):
        r = fa.audit(*chamfered_cube(0.25, 0.01))
        self.assertEqual(len(r["bevels"]), 12)
        for sec in r["bevels"]:
            self.assertAlmostEqual(sec["width"], 0.01 * math.sqrt(2), places=6)
            self.assertAlmostEqual(sec["flat"], 0.48, places=6)
        self.assertEqual(sum(1 for sec in r["bevels"] if sec["contact"]), 4)
        self.assertEqual(r["hard_edge_count"], 0)
        k = keys(r)
        self.assertIn("warn_every_edge_bevelled", k)
        self.assertNotIn("over_bevelled", k)

    def test_soap_bar_cube(self):
        r = fa.audit(*chamfered_cube(0.05, 0.04))
        self.assertEqual(len(r["bevels"]), 12)
        self.assertIn("over_bevelled", keys(r))

    def test_tiers(self):
        t = fa.tiers([(0.002, 1.0), (0.0024, 1.0), (0.005, 2.0), (0.006, 1.0), (0.02, 0.5)])
        self.assertEqual([x["count"] for x in t], [2, 2, 1])
        self.assertAlmostEqual(t[1]["length"], 3.0)


class Parts(unittest.TestCase):
    def test_floating_part(self):
        a = extrude(rect_profile(0.4, 0.4), 0.4)
        b = extrude(rect_profile(0.1, 0.1), 0.1, offset=(0.0, 0.0, 1.0))
        r = fa.audit(*combine(a, b))
        self.assertIn("floating_parts", keys(r))
        c = extrude(rect_profile(0.1, 0.1), 0.1, offset=(0.0, 0.0, 0.4))   # sitting on top of a
        r = fa.audit(*combine(a, c))
        self.assertNotIn("floating_parts", keys(r))

    def test_size_tiers(self):
        self.assertEqual(fa.size_tiers([1.0, 0.9, 0.5, 0.2, 0.1]), 4)
        self.assertEqual(fa.size_tiers([1.0, 0.9, 0.5, 0.3, 0.2]), 3)
        self.assertEqual(fa.size_tiers([1.0, 0.8, 0.7]), 1)

    def test_cylinder_fill(self):
        r = fa.audit(*extrude(circle_profile(0.1, 64), 1.0))
        self.assertAlmostEqual(r["parts"][0]["fill"], math.pi / 4, places=2)
        self.assertNotIn("blocky", keys(r))
        self.assertAlmostEqual(r["silhouettes"]["front"]["rectangularity"], math.pi / 4, delta=0.03)
        self.assertGreater(r["silhouettes"]["front"]["solidity"], 0.95)


class Files(unittest.TestCase):
    def test_obj_and_cli(self):
        verts, faces = extrude(rect_profile(0.05, 0.05, 0.02), 0.5)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "soap.obj")
            with open(path, "w", encoding="utf-8") as fh:
                for x, y, z in verts:
                    fh.write("v %r %r %r\n" % (x, z, -y))   # written Y up
                for f in faces:
                    fh.write("f %s\n" % " ".join("%d/1/1" % (i + 1) for i in f))
            v2, f2 = fa.read_obj(path, y_up=True)
            for a, b in zip(verts, v2):
                for p, q in zip(a, b):
                    self.assertAlmostEqual(p, q, places=9)
            run = subprocess.run([sys.executable, "-B", str(SCRIPT), path, "--y-up"], capture_output=True, text=True)
            self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
            self.assertIn("over_bevelled", run.stdout)


if __name__ == "__main__":
    unittest.main()
