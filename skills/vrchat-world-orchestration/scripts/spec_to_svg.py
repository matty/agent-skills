"""Draw plans and elevations from a world spec as SVG, so agents build from drawings generated from the one spec.

Host: plain Python 3.9+, plus PyYAML for .yaml specs (see spec_validate.py; .json works without it).

    python spec_to_svg.py world/spec.yaml --out world/diagrams [--px-per-m 20]

Writes, in --out:
    plan_overview.svg          every zone, with views (camera markers)
    plan_<zone>.svg            one zone: grid, rooms, openings, placement footprints, views
    elevation_<id>.svg         one facade: courses of pieces, bottom course first, left to right as seen from the front

Plans are top views in Blender coordinates: X to the right (east), Y up the page (north), 1 grid line per module.
Each SVG carries data-px-per-m, data-origin (world X, Y of the drawing's top-left) and data-frame (the drawn
area in SVG pixels: x y w h) so a QA render of the same area can be overlaid on it. Footprints come
from the piece names' Size tokens (naming rules in ../references/world-spec.md), pivots at the
bottom-left corner, rotated about the pivot; assemblies use their `size`; Free pieces are drawn as a labelled dot.
Run spec_validate.py first: this script draws what it is given and skips what it cannot resolve.
"""

import argparse
import math
import os
import sys
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spec_validate import load, piece_extent  # noqa: E402

MARGIN = 40
OVERHEAD_M = 2.0     # placements this far above the zone floor are drawn as dashed outlines on plans
COL = {"grid": "#e3e3e3", "grid5": "#c4c4c4", "zone": "#263238", "room": "#fff3e0", "room_edge": "#e65100",
       "door": "#2e7d32", "piece": "#90caf9", "piece_edge": "#0d47a1", "asm": "#ce93d8", "asm_edge": "#4a148c",
       "free": "#ef6c00", "view": "#c62828", "text": "#212121"}


class Svg:
    def __init__(self, w, h, title, px, origin, frame):
        self.parts = []
        self.head = ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" '
                     'data-px-per-m="%g" data-origin="%g,%g" data-frame="%.1f %.1f %.1f %.1f" '
                     'font-family="Segoe UI, Arial, sans-serif">'
                     % (w, h, w, h, px, origin[0], origin[1], *frame))
        self.add('<rect width="100%" height="100%" fill="#ffffff"/>')
        self.add('<title>%s</title>' % escape(title))

    def add(self, s):
        self.parts.append(s)

    def text(self, x, y, s, size=11, anchor="start", colour=None, weight="normal", rotate=None):
        rot = ' transform="rotate(%g %g %g)"' % (rotate, x, y) if rotate else ""
        self.add('<text x="%.1f" y="%.1f" font-size="%g" text-anchor="%s" fill="%s" font-weight="%s"%s>%s</text>'
                 % (x, y, size, anchor, colour or COL["text"], weight, rot, escape(str(s))))

    def save(self, path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.head + "\n" + "\n".join(self.parts) + "\n</svg>\n")


def plan(spec, zones, path, px, title, draw_grid=True):
    module = spec["grid"]["module"]
    families = spec.get("families") or {}
    pieces = {p["name"]: p for p in spec.get("pieces") or []}
    asms = {a["name"]: a for a in spec.get("assemblies") or []}
    x0 = min(z["bounds"][0] for z in zones)
    y0 = min(z["bounds"][1] for z in zones)
    x1 = max(z["bounds"][2] for z in zones)
    y1 = max(z["bounds"][3] for z in zones)
    w = (x1 - x0) * px + 2 * MARGIN
    h = (y1 - y0) * px + 2 * MARGIN + 30
    svg = Svg(w, h, title, px, (x0, y1), (MARGIN, MARGIN + 30, (x1 - x0) * px, (y1 - y0) * px))
    X = lambda x: MARGIN + (x - x0) * px
    Y = lambda y: MARGIN + 30 + (y1 - y) * px

    if draw_grid:
        n = 0
        x = math.floor(x0 / module) * module
        while x <= x1 + 1e-9:
            c = COL["grid5"] if round(x / module) % 5 == 0 else COL["grid"]
            svg.add('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s"/>' % (X(x), Y(y0), X(x), Y(y1), c))
            x += module
            n += 1
        y = math.floor(y0 / module) * module
        while y <= y1 + 1e-9:
            c = COL["grid5"] if round(y / module) % 5 == 0 else COL["grid"]
            svg.add('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s"/>' % (X(x0), Y(y), X(x1), Y(y), c))
            y += module

    for z in zones:
        b = z["bounds"]
        svg.add('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="none" stroke="%s" stroke-width="2"/>'
                % (X(b[0]), Y(b[3]), (b[2] - b[0]) * px, (b[3] - b[1]) * px, COL["zone"]))
        svg.text(X(b[0]) + 4, Y(b[3]) + 14, "%s (%s)" % (z.get("name", z["id"]), z.get("kind", "")), 12,
                 weight="bold")
        for r in z.get("rooms") or []:
            rb = r["bounds"]
            svg.add('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" fill-opacity="0.7" stroke="%s"/>'
                    % (X(rb[0]), Y(rb[3]), (rb[2] - rb[0]) * px, (rb[3] - rb[1]) * px, COL["room"],
                       COL["room_edge"]))
            svg.text((X(rb[0]) + X(rb[2])) / 2, (Y(rb[1]) + Y(rb[3])) / 2, r.get("name", r["id"]), 11, "middle")
            svg.text((X(rb[0]) + X(rb[2])) / 2, (Y(rb[1]) + Y(rb[3])) / 2 + 13,
                     "%g x %g m, h %g" % (rb[2] - rb[0], rb[3] - rb[1], r.get("height", 0)), 9, "middle")
            for o in r.get("openings") or []:
                ax, ay = o["at"]
                half = o.get("width", 1) / 2
                horizontal = min(abs(ay - rb[1]), abs(ay - rb[3])) <= min(abs(ax - rb[0]), abs(ax - rb[2]))
                if horizontal:
                    pts = (X(ax), Y(ay), X(ax + 2 * half), Y(ay))
                else:
                    pts = (X(ax), Y(ay), X(ax), Y(ay + 2 * half))
                svg.add('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="5"/>'
                        % (*pts, COL["door"]))
                svg.text(pts[0], pts[1] - 5, "%s %gx%g" % (o.get("type", ""), o.get("width", 0), o.get("height", 0)),
                         8, colour=COL["door"])

        overhead = set()
        for pl in z.get("placements") or []:
            ref, pos, rot = pl["ref"], pl.get("pos", [0, 0, 0]), math.radians(pl.get("rot", 0))
            if ref in asms and isinstance(asms[ref].get("size"), list):
                ext, fill, edge = asms[ref]["size"], COL["asm"], COL["asm_edge"]
            elif ref in pieces:
                ext, fill, edge = piece_extent(ref, module, families), COL["piece"], COL["piece_edge"]
            else:
                ext = None
            if not ext:
                svg.add('<circle cx="%.1f" cy="%.1f" r="4" fill="%s"/>' % (X(pos[0]), Y(pos[1]), COL["free"]))
                svg.text(X(pos[0]) + 6, Y(pos[1]) + 3, ref, 8, colour=COL["free"])
                continue
            c, s = math.cos(rot), math.sin(rot)
            corners = [(0, 0), (ext[0], 0), (ext[0], ext[1]), (0, ext[1])]
            pts = " ".join("%.1f,%.1f" % (X(pos[0] + cx * c - cy * s), Y(pos[1] + cx * s + cy * c))
                           for cx, cy in corners)
            if len(pos) > 2 and pos[2] - z.get("floor_z", 0) >= OVERHEAD_M:
                # Ceilings and other overhead pieces: outline only, so they do not hide what stands below.
                svg.add('<polygon points="%s" fill="none" stroke="%s" stroke-dasharray="4 3"/>' % (pts, edge))
                overhead.add(ref)
                continue
            svg.add('<polygon points="%s" fill="%s" fill-opacity="0.6" stroke="%s"/>' % (pts, fill, edge))
            svg.add('<circle cx="%.1f" cy="%.1f" r="2.5" fill="%s"/>' % (X(pos[0]), Y(pos[1]), edge))
            mx = pos[0] + (ext[0] / 2) * c - (ext[1] / 2) * s
            my = pos[1] + (ext[0] / 2) * s + (ext[1] / 2) * c
            thin = min(abs(ext[0]), abs(ext[1])) * px < 14
            svg.text(X(mx), Y(my) + (14 if thin else 3), ref, 8, "middle", colour=edge)
        if overhead:
            svg.text(X(b[0]) + 4, Y(b[1]) - 6, "dashed: overhead, %g m or more above the floor (%s)"
                     % (OVERHEAD_M, ", ".join(sorted(overhead))), 8, colour=COL["piece_edge"])

    for v in spec.get("views") or []:
        p, t = v["pos"], v["target"]
        if not (x0 <= p[0] <= x1 and y0 <= p[1] <= y1):
            continue
        dx, dy = t[0] - p[0], t[1] - p[1]
        d = math.hypot(dx, dy) or 1.0
        ex, ey = p[0] + dx / d * 3 * module, p[1] + dy / d * 3 * module
        svg.add('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="2"/>'
                % (X(p[0]), Y(p[1]), X(ex), Y(ey), COL["view"]))
        svg.add('<circle cx="%.1f" cy="%.1f" r="5" fill="%s"/>' % (X(p[0]), Y(p[1]), COL["view"]))
        svg.text(X(p[0]) + 7, Y(p[1]) + 14, "view %s" % v["id"], 9, colour=COL["view"])

    svg.text(MARGIN, 20, title, 14, weight="bold")
    bar = 5 * module
    svg.add('<rect x="%.1f" y="%.1f" width="%.1f" height="5" fill="%s"/>' % (w - MARGIN - bar * px, 12, bar * px,
                                                                            COL["text"]))
    svg.text(w - MARGIN - bar * px / 2, 30, "%g m" % bar, 9, "middle")
    svg.text(w - MARGIN - bar * px - 18, 22, "N \u2191", 11, "middle", weight="bold")
    svg.save(path)


def _facade_openings(spec, e, width, tol=0.5):
    """Room openings that lie in this facade, as (u0, u1, height, label): u is metres from the facade's left edge as
    seen from the front. An opening belongs to the facade when its wall line is within `tol` m of the facade plane."""
    ox, oy = (e.get("origin") or [0, 0])[:2]
    facing = e.get("facing", "south")
    # u (left to right as seen from the front) per facing; `along` is the world axis the facade runs along.
    to_u = {"south": lambda x, y: x - ox, "north": lambda x, y: ox - x,
            "west": lambda x, y: oy - y, "east": lambda x, y: y - oy}.get(facing)
    if to_u is None:
        return []
    along_x = facing in ("south", "north")
    out = []
    for z in spec.get("zones") or []:
        if z.get("id") != e.get("zone"):
            continue
        for r in z.get("rooms") or []:
            for o in r.get("openings") or []:
                ax, ay = o["at"]
                wdt = o.get("width", 1)
                if abs((ay - oy) if along_x else (ax - ox)) > tol:
                    continue
                u0, u1 = sorted((to_u(ax, ay), to_u(ax + wdt, ay) if along_x else to_u(ax, ay + wdt)))
                if u1 <= 0 or u0 >= width:
                    continue
                out.append((max(u0, 0), min(u1, width), o.get("height", 2.1),
                            "%s %gx%g" % (o.get("type", ""), wdt, o.get("height", 0))))
    return out


def elevation(spec, e, path, px):
    module = spec["grid"]["module"]
    families = spec.get("families") or {}
    rows, height, width = [], 0.0, 0.0
    for course in e.get("courses") or []:
        x, row_h, row = 0.0, 0.0, []
        for name in course:
            ext = piece_extent(name, module, families)
            if not ext:
                continue
            row.append((name, x, ext[0], ext[2]))
            x += ext[0]
            row_h = max(row_h, ext[2])
        rows.append((height, row))
        height += row_h
        width = max(width, x)
    w = max(width * px + 2 * MARGIN, 640)
    h = height * px + 2 * MARGIN + 50
    ground = MARGIN + 40 + height * px
    svg = Svg(w, h, "Elevation %s" % e["id"], px, tuple(e.get("origin", [0, 0, 0])[:2]),
              (MARGIN, ground - height * px, width * px, height * px))
    for base, row in rows:
        for name, x, pw, ph in row:
            fam = name.split("_")[0]
            svg.add('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" fill-opacity="%s" stroke="%s"/>'
                    % (MARGIN + x * px, ground - (base + ph) * px, pw * px, ph * px, COL["piece"],
                       "0.35" if fam == "TRIM" else "0.6", COL["piece_edge"]))
            cx, cy = MARGIN + (x + pw / 2) * px, ground - (base + ph / 2) * px
            label = name.replace(fam + "_", "", 1)
            if pw * px < len(label) * 5.5:
                svg.text(cx + 3, cy, label, 8, "middle", colour=COL["piece_edge"], rotate=-90)
            else:
                svg.text(cx, cy, label, 9, "middle", colour=COL["piece_edge"])
    for u0, u1, oh, label in _facade_openings(spec, e, width):
        svg.add('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#ffffff" fill-opacity="0.85" stroke="%s" '
                'stroke-width="2" stroke-dasharray="5 3"/>'
                % (MARGIN + u0 * px, ground - oh * px, (u1 - u0) * px, oh * px, COL["door"]))
        svg.text(MARGIN + (u0 + u1) / 2 * px, ground - oh * px - 4, label, 9, "middle", colour=COL["door"])
    svg.add('<line x1="%d" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="2"/>'
            % (MARGIN - 10, ground, MARGIN + width * px + 10, ground, COL["zone"]))
    for i in range(int(round(width / module)) + 1):
        svg.add('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s"/>'
                % (MARGIN + i * module * px, ground, MARGIN + i * module * px, ground + 5, COL["zone"]))
    svg.text(MARGIN, 20, "Elevation %s" % e["id"], 14, weight="bold")
    svg.text(MARGIN, 38, "zone %s, facade facing %s, origin %s, %g m wide x %g m high"
             % (e.get("zone"), e.get("facing"), e.get("origin"), width, height), 11)
    svg.text(MARGIN, ground + 20, "left to right as seen from the front; bottom course first in the spec", 9)
    svg.save(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("spec")
    ap.add_argument("--out", required=True)
    ap.add_argument("--px-per-m", type=float, default=20.0)
    a = ap.parse_args()
    spec = load(a.spec)
    os.makedirs(a.out, exist_ok=True)
    zones = [z for z in spec.get("zones") or [] if isinstance(z.get("bounds"), list) and len(z["bounds"]) == 4]
    written = []
    if zones:
        p = os.path.join(a.out, "plan_overview.svg")
        plan(spec, zones, p, max(2.0, a.px_per_m / 4), "%s - overview" % spec["world"]["name"], draw_grid=False)
        written.append(p)
    for z in zones:
        p = os.path.join(a.out, "plan_%s.svg" % z["id"])
        plan(spec, [z], p, a.px_per_m, "Plan %s - %s" % (z["id"], z.get("name", "")))
        written.append(p)
    for e in spec.get("elevations") or []:
        p = os.path.join(a.out, "elevation_%s.svg" % e["id"])
        elevation(spec, e, p, a.px_per_m * 2)          # facades read better at twice the plan scale
        written.append(p)
    print("\n".join("wrote " + p for p in written))


if __name__ == "__main__":
    main()
