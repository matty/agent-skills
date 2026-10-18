"""Draw plans and elevations from a world spec as SVG, so agents build from drawings generated from the one spec.

Host: plain Python 3.9+, plus PyYAML for .yaml specs (see spec_validate.py; .json works without it).

    python spec_to_svg.py world/spec.yaml --out world/diagrams [--px-per-m 20]

Writes, in --out:
    plan_overview.svg          every zone, with views (camera markers)
    plan_<zone>.svg            one zone: grid, rooms, openings, placement footprints, mirrors, views
    elevation_<id>.svg         one facade: courses of pieces, bottom course first, left to right as seen from the front
and deletes any other plan_*.svg or elevation_*.svg in --out (zones or elevations no longer in the spec), so the
folder never holds a stale drawing. Other files there (tasks.mmd, lightmap_budget.txt) are left alone.

Plans are top views in Blender coordinates: X to the right (east), Y up the page (north), 1 grid line per module.
Each SVG carries data-px-per-m, data-frame (the drawn area in SVG pixels: x y w h) and data-origin, so a QA render of
the same area can be overlaid on it. data-origin is, on a plan, the world X, Y at the top-left of the frame; on an
elevation, the facade's `origin` (its bottom-left seen from the front, world X, Y), whose horizontal axis runs left
to right as seen from the front. Footprints come from the piece names' Size tokens (naming rules in
../references/world-spec.md), pivots at the bottom-left corner, rotated about the pivot; assemblies use their `size`;
Free pieces are drawn as a labelled dot. An elevation shows the openings that run along its facade line, from rooms
in any zone. Run spec_validate.py first: this script draws what it is given, skips what it cannot resolve, and
reports a drawing it cannot make (a value of the wrong type) as an ERROR line with exit code 1, never a traceback.
"""

import argparse
import math
import os
import sys
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spec_validate import ID_RE, load, number, numbers, piece_extent, runs_along_x, valid_bounds  # noqa: E402

MARGIN = 40
OVERHEAD_M = 2.0     # placements this far above the zone floor are drawn as dashed outlines on plans
MAX_GRID_LINES = 5000
DRAW_ERRORS = (TypeError, ValueError, KeyError, IndexError, AttributeError, ZeroDivisionError, OverflowError)
COL = {"grid": "#e3e3e3", "grid5": "#c4c4c4", "zone": "#263238", "room": "#fff3e0", "room_edge": "#e65100",
       "door": "#2e7d32", "piece": "#90caf9", "piece_edge": "#0d47a1", "asm": "#ce93d8", "asm_edge": "#4a148c",
       "free": "#ef6c00", "view": "#c62828", "mirror": "#00838f", "text": "#212121"}


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


def _by_name(items):
    """{name: item} for the list entries that are mappings with a string name."""
    if not isinstance(items, list):
        return {}
    return {it["name"]: it for it in items if isinstance(it, dict) and isinstance(it.get("name"), str)}


def _list(v):
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def plan(spec, zones, path, px, title, draw_grid=True):
    module = spec["grid"]["module"]
    families = spec.get("families") or {}
    pieces = _by_name(spec.get("pieces"))
    asms = _by_name(spec.get("assemblies"))
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
        if max(x1 - x0, y1 - y0) / module > MAX_GRID_LINES:
            raise ValueError("the zone spans more than %d modules of %g m" % (MAX_GRID_LINES, module))
        x = math.floor(x0 / module) * module
        while x <= x1 + 1e-9:
            c = COL["grid5"] if round(x / module) % 5 == 0 else COL["grid"]
            svg.add('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s"/>' % (X(x), Y(y0), X(x), Y(y1), c))
            x += module
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
        for r in _list(z.get("rooms")):
            rb = r.get("bounds")
            if not numbers(rb, 4):
                continue                               # spec_validate reports it
            svg.add('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" fill-opacity="0.7" stroke="%s"/>'
                    % (X(rb[0]), Y(rb[3]), (rb[2] - rb[0]) * px, (rb[3] - rb[1]) * px, COL["room"],
                       COL["room_edge"]))
            svg.text((X(rb[0]) + X(rb[2])) / 2, (Y(rb[1]) + Y(rb[3])) / 2, r.get("name", r.get("id")), 11, "middle")
            svg.text((X(rb[0]) + X(rb[2])) / 2, (Y(rb[1]) + Y(rb[3])) / 2 + 13,
                     "%g x %g m, h %g" % (rb[2] - rb[0], rb[3] - rb[1], r.get("height", 0)), 9, "middle")
            for o in _list(r.get("openings")):
                if not _valid_opening(o):
                    continue                           # spec_validate reports it
                ax, ay = o["at"]
                half = o.get("width", 1) / 2
                if runs_along_x(rb, ax, ay):
                    pts = (X(ax), Y(ay), X(ax + 2 * half), Y(ay))
                else:
                    pts = (X(ax), Y(ay), X(ax), Y(ay + 2 * half))
                svg.add('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="5"/>'
                        % (*pts, COL["door"]))
                svg.text(pts[0], pts[1] - 5, "%s %gx%g" % (o.get("type", ""), o.get("width", 0), o.get("height", 0)),
                         8, colour=COL["door"])

        overhead = set()
        for pl in _list(z.get("placements")):
            ref, pos = pl.get("ref"), pl.get("pos", [0, 0, 0])
            if not (isinstance(ref, str) and numbers(pos) and len(pos) >= 2 and number(pl.get("rot", 0))):
                continue                               # spec_validate reports it
            rot = math.radians(pl.get("rot", 0))
            if ref in asms and numbers(asms[ref].get("size"), 3):
                ext, fill, edge = asms[ref]["size"], COL["asm"], COL["asm_edge"]
            elif ref in pieces:
                ext, fill, edge = (piece_extent(ref, module, families, pieces[ref].get("size")), COL["piece"],
                                   COL["piece_edge"])
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

        for mi in _list(z.get("mirrors")):
            p, size = mi.get("pos"), mi.get("size")
            if not (numbers(p, 3) and numbers(size, 2) and number(mi.get("rot", 0))):
                continue                               # spec_validate reports it
            r = math.radians(mi.get("rot", 0))
            dx, dy = math.cos(r) * size[0] / 2, math.sin(r) * size[0] / 2
            fx, fy = math.sin(r) * 0.4, -math.cos(r) * 0.4      # the mirror faces -Y at rot 0
            svg.add('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="4"/>'
                    % (X(p[0] - dx), Y(p[1] - dy), X(p[0] + dx), Y(p[1] + dy), COL["mirror"]))
            svg.add('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="2"/>'
                    % (X(p[0]), Y(p[1]), X(p[0] + fx), Y(p[1] + fy), COL["mirror"]))
            svg.text(X(p[0] + fx) + 4, Y(p[1] + fy) + 4, "mirror %s %gx%g" % (mi.get("id"), size[0], size[1]), 8,
                     colour=COL["mirror"])

    for v in _list(spec.get("views")):
        if not (numbers(v.get("pos"), 3) and numbers(v.get("target"), 3)):
            continue                                   # spec_validate reports it
        p, t = v["pos"], v["target"]
        if not (x0 <= p[0] <= x1 and y0 <= p[1] <= y1):
            continue
        dx, dy = t[0] - p[0], t[1] - p[1]
        d = math.hypot(dx, dy) or 1.0
        ex, ey = p[0] + dx / d * 3 * module, p[1] + dy / d * 3 * module
        svg.add('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="2"/>'
                % (X(p[0]), Y(p[1]), X(ex), Y(ey), COL["view"]))
        svg.add('<circle cx="%.1f" cy="%.1f" r="5" fill="%s"/>' % (X(p[0]), Y(p[1]), COL["view"]))
        svg.text(X(p[0]) + 7, Y(p[1]) + 14, "view %s" % v.get("id"), 9, colour=COL["view"])

    svg.text(MARGIN, 20, title, 14, weight="bold")
    bar = 5 * module
    svg.add('<rect x="%.1f" y="%.1f" width="%.1f" height="5" fill="%s"/>' % (w - MARGIN - bar * px, 12, bar * px,
                                                                            COL["text"]))
    svg.text(w - MARGIN - bar * px / 2, 30, "%g m" % bar, 9, "middle")
    nx = w - MARGIN - bar * px - 18                    # north arrow: a triangle pointing up the page, and "N"
    svg.add('<polygon points="%.1f,%.1f %.1f,%.1f %.1f,%.1f" fill="%s"/>'
            % (nx + 9, 6, nx + 5, 16, nx + 13, 16, COL["text"]))
    svg.text(nx, 22, "N", 11, "middle", weight="bold")
    svg.save(path)


def _facade_openings(spec, e, width, tol=0.5):
    """Room openings in this facade, as (u0, u1, bottom, top, label): u is metres from the facade's left edge as seen
    from the front, bottom and top metres above the facade's base (the zone's floor_z plus the opening's `sill`). An
    opening belongs to the facade when it runs along the facade (an opening in a side wall, at right angles to it,
    does not) and its wall line is within `tol` m of the facade plane, whichever zone its room is in: a shop front
    placed in the plaza zone shows the doors of the rooms in the shop's zone."""
    origin = e.get("origin") or [0, 0, 0]
    ox, oy = origin[:2]
    base_z = origin[2] if len(origin) > 2 else 0
    facing = e.get("facing", "south")
    # u (left to right as seen from the front) per facing; `along_x` says which world axis the facade runs along.
    to_u = {"south": lambda x, y: x - ox, "north": lambda x, y: ox - x,
            "west": lambda x, y: oy - y, "east": lambda x, y: y - oy}.get(facing)
    if to_u is None:
        return []
    along_x = facing in ("south", "north")
    out = []
    for z in _list(spec.get("zones")):
        for r in _list(z.get("rooms")):
            rb = r.get("bounds")
            if not numbers(rb, 4):
                continue
            for o in _list(r.get("openings")):
                if not _valid_opening(o):
                    continue
                ax, ay = o["at"]
                if runs_along_x(rb, ax, ay) != along_x:
                    continue                           # a side-wall opening, at right angles to this facade
                wdt = o.get("width", 1)
                if abs((ay - oy) if along_x else (ax - ox)) > tol:
                    continue
                u0, u1 = sorted((to_u(ax, ay), to_u(ax + wdt, ay) if along_x else to_u(ax, ay + wdt)))
                if u1 <= 0 or u0 >= width:
                    continue
                sill = o.get("sill", 0) or 0
                bottom = z.get("floor_z", 0) - base_z + sill
                label = "%s %gx%g" % (o.get("type", ""), wdt, o.get("height", 0))
                out.append((max(u0, 0), min(u1, width), bottom, bottom + o.get("height", 2.1),
                            label + (" sill %g" % sill if sill else "")))
    return out


def _valid_opening(o):
    """An opening with a usable `at` and, when given, numeric width, height and sill."""
    return (numbers(o.get("at"), 2) and all(number(o.get(k, 1)) for k in ("width", "height"))
            and (o.get("sill") is None or number(o.get("sill"))))


def elevation(spec, e, path, px):
    module = spec["grid"]["module"]
    families = spec.get("families") or {}
    sizes = {name: pc.get("size") for name, pc in _by_name(spec.get("pieces")).items()}
    rows, height, width = [], 0.0, 0.0
    for course in e.get("courses") or []:
        x, row_h, row = 0.0, 0.0, []
        for name in course:
            ext = piece_extent(name, module, families, sizes.get(name)) if isinstance(name, str) else None
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
    for u0, u1, bottom, top, label in _facade_openings(spec, e, width):
        svg.add('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#ffffff" fill-opacity="0.85" stroke="%s" '
                'stroke-width="2" stroke-dasharray="5 3"/>'
                % (MARGIN + u0 * px, ground - top * px, (u1 - u0) * px, (top - bottom) * px, COL["door"]))
        svg.text(MARGIN + (u0 + u1) / 2 * px, ground - top * px - 4, label, 9, "middle", colour=COL["door"])
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


def render(spec, out, px_per_m=20.0):
    """Draw every plan and elevation of `spec` into `out`. Returns (written paths, problems, attempted): a drawing
    whose part of the spec has a value of the wrong type is skipped with a problem line instead of a traceback;
    `attempted` is False when nothing could be drawn at all (no usable grid.module), so no drawing counts as stale."""
    if not isinstance(spec, dict):
        return [], ["the spec is not a mapping"], False
    grid = spec.get("grid")
    module = grid.get("module") if isinstance(grid, dict) else None
    if not (number(module) and module > 0):
        return [], ["grid.module must be a positive number of metres, got %r" % (module,)], False
    os.makedirs(out, exist_ok=True)
    zones = [z for z in _list(spec.get("zones")) if valid_bounds(z.get("bounds"))]
    world = spec.get("world") if isinstance(spec.get("world"), dict) else {}
    name = world.get("name") or "World"                # spec_validate reports a missing name
    jobs, problems = [], []
    if zones:
        jobs.append(("plan_overview.svg",
                     lambda p: plan(spec, zones, p, max(2.0, px_per_m / 4), "%s - overview" % name, draw_grid=False)))
    for z in zones:
        jobs.append(("plan_%s.svg" % z.get("id"),
                     lambda p, z=z: plan(spec, [z], p, px_per_m, "Plan %s - %s" % (z["id"], z.get("name", "")))))
    for e in _list(spec.get("elevations")):
        jobs.append(("elevation_%s.svg" % e.get("id"),
                     lambda p, e=e: elevation(spec, e, p, px_per_m * 2)))   # facades read better at twice the scale
    written = []
    for fname, draw in jobs:
        if not ID_RE.match(fname.split("_", 1)[1][:-4]):
            problems.append("%s skipped: ids name files, so they take letters, digits, _ and - only" % fname)
            continue
        p = os.path.join(out, fname)
        try:
            draw(p)
            written.append(p)
        except DRAW_ERRORS as exc:
            problems.append("%s skipped: a value of the wrong type in its part of the spec (%s: %s); run "
                            "spec_validate.py and fix its errors" % (fname, type(exc).__name__, exc))
    return written, problems, True


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("spec")
    ap.add_argument("--out", required=True)
    ap.add_argument("--px-per-m", type=float, default=20.0)
    a = ap.parse_args()
    written, problems, attempted = render(load(a.spec), a.out, a.px_per_m)
    print("\n".join("wrote " + p for p in written))
    if attempted:
        keep = {os.path.basename(p) for p in written}
        for name in sorted(os.listdir(a.out)):
            if (name.endswith(".svg") and name.startswith(("plan_", "elevation_")) and name not in keep
                    and os.path.isfile(os.path.join(a.out, name))):
                os.remove(os.path.join(a.out, name))
                print("removed %s (not in the spec any more, or not drawable)" % os.path.join(a.out, name))
    for p in problems:
        print("ERROR %s" % p)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
