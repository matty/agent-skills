"""Plain-Python tests for blender-mesh-topology's scripts/topology_audit.py determinism_hash: it must see faces, not
only vertex positions, and ignore vertex order, face order and where a face's loop starts.

Host: plain Python 3.9+ (the module imports bmesh only inside audit()). Run from the repo root:
    python -B -m unittest discover -s tools/tests -p "test_topology_*.py"
"""

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "blender-mesh-topology" / "scripts" / "topology_audit.py"


def load():
    keep = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("topology_audit_under_test", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.dont_write_bytecode = keep


ta = load()


def obj(verts, faces):
    return SimpleNamespace(data=SimpleNamespace(
        vertices=[SimpleNamespace(co=v) for v in verts],
        polygons=[SimpleNamespace(vertices=list(f)) for f in faces]))


SQUARE = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]


class DeterminismHash(unittest.TestCase):
    def test_same_mesh_any_order_same_hash(self):
        a = obj(SQUARE, [(0, 1, 2), (0, 2, 3)])
        order = [2, 0, 3, 1]                                     # new index -> old index
        old_to_new = {old: new for new, old in enumerate(order)}
        b = obj([SQUARE[i] for i in order],
                [tuple(old_to_new[i] for i in f) for f in [(2, 3, 0), (1, 2, 0)]])   # faces reordered and rotated
        self.assertEqual(ta.determinism_hash(a), ta.determinism_hash(b))

    def test_other_diagonal_changes_the_hash(self):
        a = obj(SQUARE, [(0, 1, 2), (0, 2, 3)])
        b = obj(SQUARE, [(0, 1, 3), (1, 2, 3)])
        self.assertNotEqual(ta.determinism_hash(a), ta.determinism_hash(b))

    def test_flipped_face_changes_the_hash(self):
        a = obj(SQUARE, [(0, 1, 2, 3)])
        b = obj(SQUARE, [(3, 2, 1, 0)])
        self.assertNotEqual(ta.determinism_hash(a), ta.determinism_hash(b))

    def test_quad_versus_two_triangles(self):
        a = obj(SQUARE, [(0, 1, 2, 3)])
        b = obj(SQUARE, [(0, 1, 2), (0, 2, 3)])
        self.assertNotEqual(ta.determinism_hash(a), ta.determinism_hash(b))

    def test_moved_vertex_changes_the_hash_but_noise_below_digits_does_not(self):
        a = obj(SQUARE, [(0, 1, 2, 3)])
        b = obj([(0, 0, 0), (1, 0, 0), (1, 1.001, 0), (0, 1, 0)], [(0, 1, 2, 3)])
        c = obj([(0, 0, 0), (1, 0, 0), (1, 1.000001, 0), (0, 1, 0)], [(0, 1, 2, 3)])
        self.assertNotEqual(ta.determinism_hash(a), ta.determinism_hash(b))
        self.assertEqual(ta.determinism_hash(a), ta.determinism_hash(c))

    def test_negative_zero_is_zero(self):
        a = obj([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0)], [(0, 1, 2)])
        b = obj([(-0.0, 0.0, -0.000001), (1.0, -0.0, 0.0), (1.0, 1.0, 0.0)], [(0, 1, 2)])
        self.assertEqual(ta.determinism_hash(a), ta.determinism_hash(b))


if __name__ == "__main__":
    unittest.main()
