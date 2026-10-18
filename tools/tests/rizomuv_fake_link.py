"""A stand-in for RizomUVLink, for the rizomuv-uv-pipeline tests: enough of Load, Select, Cut, Unfold, Optimize,
Count, IslandGroups, Pack, Save, RasterExport and Quit for scripts/rizom_uv.py to run without RizomUV or a licence.

Host: plain Python 3.9+, standard library (used by tools/tests/test_rizomuv_*.py and the Blender-hosted
tools/tests/blender/test_rizomuv_bridge.py). Not a test module itself.

What it does, deliberately simple and predictable:
  - Cut splits every polygon into its own island; Unfold lays each polygon flat isometrically (its own plane),
    times an optional U stretch chosen per Auto parameter set (stretch(auto) -> factor), to exercise the gate.
  - Pack does nothing until IslandGroups has run after a Load (like RizomUV after a fileless load). Fill mode
    scales every island by one factor, as large as fits (times coverage(auto), to fake a loose layout);
    USER_SPECIFIED (Scaling.Mode 6) uses SpecifiedScale and leaves the islands untouched when they do not fit (like
    RizomUV), or when overflow(auto) says so (a hard cut that joins a bevel ring into one long island). Islands go
    on shelves (turned long side along U when Rotate.Step > 0, as RizomUV may turn them) with PaddingSizePx between
    bounding boxes and MarginSizePx to the edge, at MapResolution; when
    overlap(params) says so, every island is stacked at the margin instead (a pack that breaks its padding). Every
    Pack's parameters are kept in .packs.
  - RasterExport writes a placeholder file, or raises when fail_raster is set.
"""

import math
import os


class FakeZEx(Exception):
    pass


class FakeLink:
    def __init__(self, stretch=None, fail_raster=False, coverage=None, overflow=None, overlap=None):
        self.stretch = stretch or (lambda auto: 1.0)
        self.coverage = coverage or (lambda auto: 1.0)      # < 1 shrinks a fill pack: a sprawling, loose layout
        self.overflow = overflow or (lambda auto: False)    # True: a texel-density pack does not fit
        self.overlap = overlap or (lambda params: False)    # True: the islands are stacked on each other
        self.fail_raster = fail_raster
        self.auto, self.grouped, self.calls, self.packs = {}, False, [], []
        self.sizes = self.xid = self.xyz = self.uid = self.uvw = None

    # ---- helpers
    def _polys(self):
        c = 0
        for n in self.sizes:
            yield list(range(c, c + n))
            c += n

    def _islands(self):
        parent = list(range(len(self.uvw) // 3))

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a
        for corners in self._polys():
            r0 = find(self.uid[corners[0]])
            for c in corners[1:]:
                r = find(self.uid[c])
                if r != r0:
                    parent[r] = r0
        groups = {}
        for v in range(len(parent)):
            groups.setdefault(find(v), []).append(v)
        used = set(self.uid)
        return [sorted(v for v in vs if v in used) for vs in groups.values() if any(v in used for v in vs)]

    # ---- commands
    def Load(self, p):
        self.calls.append("Load")
        self.sizes, self.xid = list(p["Data.PolySizes"]), list(p["Data.PolyXYZIDs"])
        self.xyz, self.uid, self.uvw = list(p["Data.CoordsXYZ"]), list(p["Data.PolyUVWIDs"]), list(p["Data.CoordsUVW"])
        self.grouped = False
        return {}

    def Select(self, p):
        if "Auto" in p:
            self.auto = p["Auto"]

    def Cut(self, p):
        uid, uvw = [], []
        for corners in self._polys():
            for c in corners:
                uid.append(len(uvw) // 3)
                uvw.extend(self.uvw[3 * self.uid[c]:3 * self.uid[c] + 3])
        self.uid, self.uvw = uid, uvw

    def Unfold(self, p):
        k = float(self.stretch(self.auto))
        for corners in self._polys():
            P = [self.xyz[3 * self.xid[c]:3 * self.xid[c] + 3] for c in corners]
            o = P[0]
            e1 = [P[1][i] - o[i] for i in range(3)]
            n = [0.0, 0.0, 0.0]
            for a in range(len(P)):                                   # Newell normal
                b = (a + 1) % len(P)
                n[0] += (P[a][1] - P[b][1]) * (P[a][2] + P[b][2])
                n[1] += (P[a][2] - P[b][2]) * (P[a][0] + P[b][0])
                n[2] += (P[a][0] - P[b][0]) * (P[a][1] + P[b][1])
            ln, l1 = math.sqrt(sum(x * x for x in n)), math.sqrt(sum(x * x for x in e1))
            x = [e / l1 for e in e1]
            nn = [e / ln for e in n]
            y = [nn[1] * x[2] - nn[2] * x[1], nn[2] * x[0] - nn[0] * x[2], nn[0] * x[1] - nn[1] * x[0]]
            for c, q in zip(corners, P):
                d = [q[i] - o[i] for i in range(3)]
                u = sum(d[i] * x[i] for i in range(3)) * k
                v = sum(d[i] * y[i] for i in range(3))
                self.uvw[3 * self.uid[c]:3 * self.uid[c] + 3] = [u, v, 0.0]

    def Optimize(self, p):
        pass

    def Count(self, path):
        return len(self._islands())

    def IslandGroups(self, p):
        self.grouped = True

    def _shelf(self, boxes, s, pad, margin):
        """Positions (x, y) for boxes (w, h) scaled by s, or None when they do not fit in the tile."""
        order = sorted(range(len(boxes)), key=lambda i: -boxes[i][1])
        x, y, row_h, pos = margin, margin, 0.0, {}
        for i in order:
            w, h = boxes[i][0] * s, boxes[i][1] * s
            if x + w > 1 - margin + 1e-12:
                x, y, row_h = margin, y + row_h + pad, 0.0
            if x + w > 1 - margin + 1e-12 or y + h > 1 - margin + 1e-12:
                return None
            pos[i] = (x, y)
            x, row_h = x + w + pad, max(row_h, h)
        return pos

    def Pack(self, p):
        self.calls.append("Pack")
        self.packs.append(p)
        if not self.grouped:
            return {"Coverages": []}
        res = float(p.get("MapResolution", 2048))
        pad, margin = p.get("PaddingSizePx", 16) / res, p.get("MarginSizePx", 8) / res
        isl = self._islands()
        turn = float(p.get("Rotate", {}).get("Step", 0) or 0) > 0
        boxes, mins = [], []
        for vs in isl:
            us, vv = [self.uvw[3 * v] for v in vs], [self.uvw[3 * v + 1] for v in vs]
            if turn and max(vv) - min(vv) > max(us) - min(us) + 1e-12:     # long side along U, a 90-degree turn
                for v in vs:
                    self.uvw[3 * v], self.uvw[3 * v + 1] = -self.uvw[3 * v + 1], self.uvw[3 * v]
                us, vv = [self.uvw[3 * v] for v in vs], [self.uvw[3 * v + 1] for v in vs]
            mins.append((min(us), min(vv)))
            boxes.append((max(us) - min(us), max(vv) - min(vv)))
        scaling = p.get("Scaling", {})
        if scaling.get("Mode") == 6:
            s = float(scaling["SpecifiedScale"])
            pos = None if self.overflow(self.auto) else self._shelf(boxes, s, pad, margin)
            if pos is None:
                return {"Coverages": []}                      # does not fit: untouched, no error
        else:
            lo, hi = 0.0, 1.0 / max(max(max(b) for b in boxes), 1e-9)
            for _ in range(60):
                mid = (lo + hi) / 2
                lo, hi = (mid, hi) if self._shelf(boxes, mid, pad, margin) is not None else (lo, mid)
            s = lo * float(self.coverage(self.auto))
            pos = self._shelf(boxes, s, pad, margin)
        if self.overlap(p):
            s = (1 - 2 * margin) / max(max(max(b) for b in boxes), 1e-9)
            pos = {i: (margin, margin) for i in range(len(boxes))}
        for i, vs in enumerate(isl):
            for v in vs:
                self.uvw[3 * v] = (self.uvw[3 * v] - mins[i][0]) * s + pos[i][0]
                self.uvw[3 * v + 1] = (self.uvw[3 * v + 1] - mins[i][1]) * s + pos[i][1]
        return {"Coverages": []}

    def Save(self, p):
        return {"Data": {"PolySizes": list(self.sizes), "PolyUVWIDs": list(self.uid), "CoordsUVW": list(self.uvw)}}

    def RasterExport(self, p):
        if self.fail_raster:
            raise FakeZEx("RasterExport failed (fake)")
        with open(p["FilePath"], "wb") as fh:
            fh.write(b"fake")

    def Quit(self, p=None):
        self.calls.append("Quit")

    def RizomUVVersion(self):
        return "2027.0.598.gfake"


class FakeSession:
    """Stands in for rizom_link.RizomSession in blender_rizom.unwrap_objects."""
    CZEx = FakeZEx
    link_kwargs = {}
    restart_fails = False
    instances = []

    def __init__(self, *a, **kw):
        self.link, self.timed_out, self.version, self.port, self.pid = None, False, "2027.0.598.gfake", 61000, 0
        self.started = self.closed = 0
        FakeSession.instances.append(self)

    def start(self):
        self.link = FakeLink(**FakeSession.link_kwargs)
        self.link.session = self
        self.started += 1
        return self.link

    def alive(self):
        return self.link is not None

    def restart(self):
        if FakeSession.restart_fails:
            raise RuntimeError("no licence token (fake)")
        return self.start()

    def close(self, grace=None):
        self.closed += 1

    def deadline(self, seconds):
        import contextlib
        return contextlib.nullcontext()


def box_mesh(size=1.0, offset=(0.0, 0.0, 0.0)):
    """A cube as rizom_uv mesh arrays: 6 quads, seed UVs = positions, no seams."""
    v = [(x * size + offset[0], y * size + offset[1], z * size + offset[2])
         for z in (0, 1) for y in (0, 1) for x in (0, 1)]
    faces = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    xid = [i for f in faces for i in f]
    xyz = [c for p in v for c in p]
    return {"sizes": [4] * 6, "xyz_ids": xid, "xyz": xyz, "uvw_ids": list(xid), "uvw": list(xyz)}


if __name__ == "__main__":
    print(__doc__)
    print("scratch path check:", os.path.basename(__file__))
