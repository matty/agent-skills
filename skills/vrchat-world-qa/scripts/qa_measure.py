"""Read-only measurements for world QA: kit pieces, placements, linking, plus orthographic review renders and overlays.

Host: Blender 4.1+ (bpy), no add-ons. Changes nothing in the file and never saves it.

Command line (open the file read-only; one JSON report, one summary line per piece):
    blender -b --factory-startup KIT_Arch_Exterior.blend --python qa_measure.py -- --module 1.0 --json report.json
    blender -b --factory-startup MASTER.blend --python qa_measure.py -- --module 1.0 --json report.json
            --render top --center 15 13 --extent 30 27 --px-per-m 20 --png plan_render.png
    blender -b --factory-startup MASTER.blend --python qa_measure.py -- --render front --center 8 20 3 --extent 12 6 --px-per-m 40
            --png elev.png --overlay world/diagrams/elevation_square_north_row.svg --overlay-out elev_overlay.svg
    blender -b --factory-startup MASTER.blend --python qa_measure.py -- --render back --center 3 1.2 1.5 --extent 4 3
            --clip 3 --png inside_south.png       # an interior wall from inside: --clip hides the wall behind you
    blender -b --factory-startup MASTER.blend --python qa_measure.py -- --view 2 1.8 1.7 3 4.4 0.9 24 --png view.png
            # perspective from a spec view: pos, target, lens (the views the gates and G4 compare against)

From a live Blender (Blender MCP execute_blender_code), without saving:
    ns = {}; exec(open(r"<skill>/scripts/qa_measure.py", encoding="utf-8").read(), ns)
    rep = ns["measure"](module=1.0)          # dict: pieces, placements, libraries, appended, stray
    ns["problems"](rep, piece_tris={"EXT": 800})

Per piece collection (name <FAMILY>_<Type>_<Size>_<Variant>): name check, LOD0 triangles (modifiers applied),
materials, UV layer count, n-gons, edges shared by more than two faces, loose vertices, non-identity object
transforms, bounds and extents in grid modules against the Size token, and the `kit_status` custom property.
Per placement (collection instance): asset, linked or local, position and Z rotation, on-grid and 90-degree checks.
Per file: every image a material uses (path, packed, size, channels, colour space; X2/X3); --tile-seam gives a
wrap-edge seam metric for tiling textures (X4). Per file also: linked libraries, the kit_status and LOD0 triangles of every linked piece (MASTER, ASM), kit-named
collections that are local copies (appended, not linked), stray meshes. Per mesh also coincident faces.
Deeper checks belong to the specialist skills: UV distortion, padding and texel density (uv-unwrapping),
topology flow (blender-mesh-topology), export settings (blender-to-unity).
"""

import json
import math
import os
import re
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

NAME_RE = re.compile(r"^([A-Z]{2,5})_[A-Za-z0-9]+_(\d+(?:x\d+){0,2}|Free)_[A-Z]\d?$")
EPS = 1e-4
STATUS_ORDER = ("grey", "modelled", "uv", "textured", "exported")   # collection custom property kit_status


def _identity(mw):
    return all(abs(mw[i][j] - (1.0 if i == j else 0.0)) < EPS for i in range(4) for j in range(4))


def _mesh_stats(ob, depsgraph):
    ev = ob.evaluated_get(depsgraph)
    me = ev.to_mesh()
    try:
        bm = bmesh.new()
        bm.from_mesh(me)
        tris = sum(len(f.verts) - 2 for f in bm.faces)
        ngons = sum(1 for f in bm.faces if len(f.verts) > 4)
        over = sum(1 for e in bm.edges if len(e.link_faces) > 2)
        boundary = sum(1 for e in bm.edges if len(e.link_faces) == 1)
        loose = sum(1 for v in bm.verts if not v.link_edges)
        # Coincident faces: two faces on the same set of positions (rounded to 0.1 mm), e.g. a leaf on its reveal.
        seen, coincident = set(), 0
        for f in bm.faces:
            key = tuple(sorted(tuple(round(c, 4) for c in v.co) for v in f.verts))
            coincident += key in seen
            seen.add(key)
        bm.free()
    finally:
        ev.to_mesh_clear()
    return {"tris": tris, "ngons": ngons, "edges_over_2_faces": over, "boundary_edges": boundary,
            "loose_verts": loose, "coincident_faces": coincident, "uv_layers": len(ob.data.uv_layers),
            "materials": [s.material.name if s.material else None for s in ob.material_slots]}


def _bounds(objs):
    lo, hi = Vector((math.inf,) * 3), Vector((-math.inf,) * 3)
    for ob in objs:
        for c in ob.bound_box:
            p = ob.matrix_world @ Vector(c)
            lo, hi = Vector(map(min, lo, p)), Vector(map(max, hi, p))
    return lo, hi


def measure_piece(coll, module, depsgraph):
    m = NAME_RE.match(coll.name)
    rep = {"piece": coll.name, "name_ok": bool(m), "kit_status": coll.get("kit_status"), "objects": {},
           "transform_issues": []}
    objs = list(coll.all_objects)
    render = [o for o in objs if o.type == "MESH" and not o.name.endswith("_COL")]
    for ob in objs:
        if not _identity(ob.matrix_world):
            rep["transform_issues"].append(ob.name)
        if ob.type == "MESH":
            rep["objects"][ob.name] = _mesh_stats(ob, depsgraph)
    lod0 = [o for o in render if "_LOD" not in o.name or o.name.endswith("_LOD0")]
    rep["lod0_tris"] = sum(rep["objects"][o.name]["tris"] for o in lod0)
    rep["has_collision"] = any(o.name.endswith("_COL") for o in objs)
    if render:
        lo, hi = _bounds(render)
        rep["bounds_m"] = [round(v, 4) for v in (*lo, *hi)]
        ext = [(hi[i] - lo[i]) / module for i in range(3)]
        rep["extent_modules"] = [round(e, 3) for e in ext]
        if m and m.group(2) != "Free":
            want = [int(t) for t in m.group(2).split("x")]
            grid = [e for e in ext if e >= 0.5]
            rep["size_ok"] = [round(e) for e in grid] == want and all(abs(e - round(e)) <= 0.01 for e in grid)
            rep["pivot_ok"] = all(abs(v) <= 0.01 for v in lo)
    return rep


def measure(module=1.0, scene=None):
    scene = scene or bpy.context.scene
    dg = bpy.context.evaluated_depsgraph_get()
    local_kit = [c for c in bpy.data.collections if c.library is None and NAME_RE.match(c.name)]
    linked_names = {c.name for c in bpy.data.collections if c.library is not None}
    places = []
    for ob in scene.objects:
        if ob.instance_type == "COLLECTION" and ob.instance_collection is not None:
            coll = ob.instance_collection
            loc, rot, _s = ob.matrix_world.decompose()
            rz = math.degrees(rot.to_euler().z)
            grid_piece = bool(NAME_RE.match(coll.name)) and NAME_RE.match(coll.name).group(2) != "Free"
            places.append({
                "object": ob.name, "asset": coll.name, "linked": coll.library is not None,
                "id": ob.get("placement_id"), "pos": [round(v, 4) for v in loc], "rot_z": round(rz, 3),
                "on_grid": (not grid_piece) or all(abs(v / module - round(v / module)) < 1e-3 for v in loc[:2]),
                "right_angle": (not grid_piece) or abs((rz + 360.0) % 90.0) < 1e-2 or abs((rz + 360.0) % 90.0 - 90) < 1e-2,
            })
    used_locally = {p["asset"] for p in places if not p["linked"]}
    owned = {o.name for c in local_kit for o in c.all_objects}
    return {
        "file": bpy.data.filepath,
        "module": module,
        "libraries": [lib.filepath for lib in bpy.data.libraries],
        "pieces": [measure_piece(c, module, dg) for c in sorted(local_kit, key=lambda c: c.name)],
        "images": measure_images(),
        # In MASTER or an ASM file: what each linked piece currently is, as loaded from its KIT file.
        "linked_pieces": [{"piece": c.name, "library": c.library.filepath, "kit_status": c.get("kit_status"),
                           "tris": sum(sum(len(p.vertices) - 2 for p in o.data.polygons)
                                       for o in c.all_objects if o.type == "MESH" and not o.name.endswith("_COL")
                                       and ("_LOD" not in o.name or o.name.endswith("_LOD0")))}
                          for c in sorted(bpy.data.collections, key=lambda c: c.name)
                          if c.library is not None and NAME_RE.match(c.name)],
        "placements": places,
        # a kit-named local collection that is also placed here is a copy, not a link
        "appended": sorted(n for n in used_locally if NAME_RE.match(n)),
        "shadowing_linked": sorted(c.name for c in local_kit if c.name in linked_names),
        "stray_meshes": sorted(o.name for o in scene.objects
                               if o.type == "MESH" and o.library is None and o.name not in owned),
    }


def measure_images():
    """Every image a material in this file uses: path (relative or not), packed, size, channels, colour space, and
    which materials use it. For X2/X3 (sizes, channel packing, colour space as loaded)."""
    users = {}
    for mat in bpy.data.materials:
        if mat.node_tree is None:
            continue
        for n in mat.node_tree.nodes:
            if n.type == "TEX_IMAGE" and n.image is not None:
                users.setdefault(n.image.name, set()).add(mat.name)
    out = []
    for name, mats in sorted(users.items()):
        im = bpy.data.images[name]
        out.append({"image": name, "filepath": im.filepath, "relative": im.filepath.startswith("//"),
                    "packed": im.packed_file is not None, "size": list(im.size), "channels": im.channels,
                    "colorspace": im.colorspace_settings.name, "alpha_mode": im.alpha_mode,
                    "materials": sorted(mats)})
    return out


def tile_seam(path):
    """Seam metric for a tiling texture (X4): the mean colour step across the wrap edges against the mean step
    between neighbouring pixels inside the tile, per axis. Ratios near or below 1 mean no visible seam."""
    import numpy as np
    im = bpy.data.images.load(os.path.abspath(path), check_existing=False)
    try:
        w, h = im.size
        px = np.empty(w * h * 4, np.float32)
        im.pixels.foreach_get(px)
        a = px.reshape(h, w, 4)[:, :, :3]
        inner_x = float(np.abs(np.diff(a, axis=1)).mean())
        inner_y = float(np.abs(np.diff(a, axis=0)).mean())
        edge_x = float(np.abs(a[:, 0] - a[:, -1]).mean())
        edge_y = float(np.abs(a[0] - a[-1]).mean())
        return {"image": path, "size": [w, h], "edge_x": round(edge_x, 5), "inner_x": round(inner_x, 5),
                "ratio_x": round(edge_x / max(inner_x, 1e-9), 2), "edge_y": round(edge_y, 5),
                "inner_y": round(inner_y, 5), "ratio_y": round(edge_y / max(inner_y, 1e-9), 2)}
    finally:
        bpy.data.images.remove(im)


def problems(rep, piece_tris=None):
    """Readable failures. piece_tris: {family: max LOD0 triangles}."""
    out = []
    for p in rep["pieces"]:
        n = p["piece"]
        if not p["name_ok"]:
            out.append("%s: name does not follow <FAMILY>_<Type>_<Size>_<Variant>" % n)
        if p["transform_issues"]:
            out.append("%s: non-identity transforms on %s" % (n, ", ".join(p["transform_issues"])))
        if p.get("size_ok") is False:
            out.append("%s: extents %s modules do not match the Size token" % (n, p.get("extent_modules")))
        if p.get("pivot_ok") is False:
            out.append("%s: min corner %s not at the origin" % (n, p.get("bounds_m", [])[:3]))
        fam = n.split("_")[0]
        if piece_tris and fam in piece_tris and p["lod0_tris"] > piece_tris[fam]:
            out.append("%s: %d LOD0 tris > budget %d" % (n, p["lod0_tris"], piece_tris[fam]))
        # Greybox (kit_status "grey") may still have n-gons; empty material slots are allowed until "textured".
        stage = STATUS_ORDER.index(p["kit_status"]) if p.get("kit_status") in STATUS_ORDER else len(STATUS_ORDER)
        for on, st in p["objects"].items():
            if st["ngons"] and stage >= STATUS_ORDER.index("modelled"):
                out.append("%s/%s: %d n-gons" % (n, on, st["ngons"]))
            if st["edges_over_2_faces"]:
                out.append("%s/%s: %d edges shared by 3+ faces" % (n, on, st["edges_over_2_faces"]))
            if st.get("coincident_faces"):
                out.append("%s/%s: %d coincident faces" % (n, on, st["coincident_faces"]))
            if st["loose_verts"]:
                out.append("%s/%s: %d loose vertices" % (n, on, st["loose_verts"]))
            if None in st["materials"] and stage >= STATUS_ORDER.index("textured"):
                out.append("%s/%s: empty material slot" % (n, on))
    for pl in rep["placements"]:
        if not pl["on_grid"]:
            out.append("placement %s (%s) off grid at %s" % (pl["object"], pl["asset"], pl["pos"][:2]))
        if not pl["right_angle"]:
            out.append("placement %s (%s) rotated %s deg" % (pl["object"], pl["asset"], pl["rot_z"]))
    out += ["%s is placed from a local copy (appended), not linked" % n for n in rep["appended"]]
    out += ["local collection %s shadows a linked one of the same name" % n for n in rep["shadowing_linked"]]
    return out


# Camera direction (eye towards target) and up, Blender axes. An elevation of a facade facing south is "front",
# north "back", east "right", west "left"; a plan is "top".
VIEWS = {
    "top": ((0, 0, -1), (0, 1, 0)), "front": ((0, 1, 0), (0, 0, 1)), "back": ((0, -1, 0), (0, 0, 1)),
    "right": ((-1, 0, 0), (0, 0, 1)), "left": ((1, 0, 0), (0, 0, 1)),
}


def render_ortho(path, view, center, extent, px_per_m=20.0, distance=200.0, clip=None):
    """Orthographic Workbench render of everything visible. view: top/front/back/right/left ("front" looks along +Y,
    so it shows a facade facing south). extent: (width, height) in metres of the framed area. clip: if given, only
    geometry from `clip` metres in front of the centre plane onward is drawn (an interior wall seen from inside the
    room, without the opposite wall in the way). Restores the scene."""
    fwd, up = (Vector(v) for v in VIEWS[view])
    c = Vector((list(center) + [0, 0, 0])[:3])
    cam_data = bpy.data.cameras.new("qa_cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = max(extent)
    cam_data.clip_end = distance * 2
    if clip is not None:
        cam_data.clip_start = max(0.001, distance - clip)
    right = fwd.cross(up)
    matrix = Matrix.Translation(c - fwd * distance) @ Matrix((right, up, -fwd)).transposed().to_4x4()
    return _render(path, cam_data, matrix, (max(16, int(round(extent[0] * px_per_m))),
                                            max(16, int(round(extent[1] * px_per_m)))))


def render_view(path, pos, target, lens=24.0, size=(1280, 720)):
    """Perspective Workbench render from a spec view: camera at `pos` looking at `target` (world metres), focal length
    `lens` mm. Use the spec's `views` so the comparison is never framed after seeing the result. Restores the scene."""
    cam_data = bpy.data.cameras.new("qa_cam")
    cam_data.lens = lens
    cam_data.clip_start = 0.05
    direction = Vector(target) - Vector(pos)
    rot = direction.to_track_quat("-Z", "Y").to_matrix().to_4x4()
    return _render(path, cam_data, Matrix.Translation(Vector(pos)) @ rot, size)


def _render(path, cam_data, matrix, size):
    scene = bpy.context.scene
    cam = bpy.data.objects.new("qa_cam", cam_data)
    scene.collection.objects.link(cam)
    cam.matrix_world = matrix
    saved = (scene.camera, scene.render.engine, scene.render.resolution_x, scene.render.resolution_y,
             scene.render.resolution_percentage, scene.render.filepath, scene.render.film_transparent)
    # Workbench's default flat grey hides every edge between same-coloured faces; colour each object, shade cavities
    # and outline objects so pieces, openings and seams read in the render.
    shading = scene.display.shading
    saved_shading = {k: getattr(shading, k) for k in ("color_type", "show_cavity", "show_object_outline")}
    try:
        scene.camera = cam
        for k, v in (("color_type", "RANDOM"), ("show_cavity", True), ("show_object_outline", True)):
            try:
                setattr(shading, k, v)
            except (TypeError, AttributeError) as exc:
                print("[qa] shading %s not set: %s" % (k, exc))
        try:
            scene.render.engine = "BLENDER_WORKBENCH"
        except TypeError as exc:
            print("[qa] cannot select Workbench:", exc)
        scene.render.resolution_x, scene.render.resolution_y = size
        scene.render.resolution_percentage = 100
        scene.render.film_transparent = cam_data.type == "ORTHO"
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
    finally:
        (scene.camera, scene.render.engine, scene.render.resolution_x, scene.render.resolution_y,
         scene.render.resolution_percentage, scene.render.filepath, scene.render.film_transparent) = saved
        for k, v in saved_shading.items():
            setattr(shading, k, v)
        bpy.data.objects.remove(cam)
        bpy.data.cameras.remove(cam_data)
    return path


def overlay_svg(render_png, reference, out_svg, opacity=0.5, size=None):
    """An SVG that lays a reference drawing over a render at the same scale, for any browser to open. A reference
    SVG with a data-frame attribute (spec_to_svg output) is cropped to its drawn area; a PNG is stretched to the
    render. The render must cover the same world area: a plan's zone bounds, an elevation's width x height."""
    w, h = size or tuple(bpy.data.images.load(render_png, check_existing=True).size[:])
    def rel(p):
        try:
            return os.path.relpath(os.path.abspath(p), os.path.dirname(os.path.abspath(out_svg))).replace("\\", "/")
        except ValueError:  # Windows: different drives have no relative path
            return "file:///" + os.path.abspath(p).replace("\\", "/").lstrip("/")
    ref = '<image href="%s" width="%d" height="%d" opacity="%g" preserveAspectRatio="none"/>' % (
        rel(reference), w, h, opacity)
    if reference.lower().endswith(".svg"):
        with open(reference, encoding="utf-8") as f:
            head = f.read(2000)
        frame = re.search(r'data-frame="([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+)"', head)
        full = re.search(r'<svg[^>]* width="([\d.]+)" height="([\d.]+)"', head)
        if frame and full:
            fx, fy, fw, fh = frame.groups()
            ref = ('<svg width="%d" height="%d" viewBox="%s %s %s %s" preserveAspectRatio="none" opacity="%g">'
                   '<image href="%s" width="%s" height="%s"/></svg>'
                   % (w, h, fx, fy, fw, fh, opacity, rel(reference), full.group(1), full.group(2)))
    with open(out_svg, "w", encoding="utf-8") as f:
        f.write('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d">'
                '<rect width="100%%" height="100%%" fill="#fff"/><image href="%s" width="%d" height="%d"/>%s</svg>\n'
                % (w, h, rel(render_png), w, h, ref))
    return out_svg


def _main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not argv:
        return
    import argparse
    ap = argparse.ArgumentParser(prog="qa_measure.py")
    ap.add_argument("--module", type=float, default=1.0)
    ap.add_argument("--json")
    ap.add_argument("--piece-tris", help='JSON, e.g. {"EXT": 800}')
    ap.add_argument("--render", choices=sorted(VIEWS))
    ap.add_argument("--center", type=float, nargs="+")
    ap.add_argument("--extent", type=float, nargs=2)
    ap.add_argument("--px-per-m", type=float, default=20.0)
    ap.add_argument("--clip", type=float, help="ortho only: draw only geometry from this many metres in front of "
                    "the centre plane onward (an interior wall from inside the room)")
    ap.add_argument("--view", type=float, nargs=7, metavar=("PX", "PY", "PZ", "TX", "TY", "TZ", "LENS"),
                    help="perspective render from a spec view: pos, target and lens")
    ap.add_argument("--tile-seam", nargs="+", metavar="PNG", help="seam metric for tiling textures (X4)")
    ap.add_argument("--png")
    ap.add_argument("--overlay")
    ap.add_argument("--overlay-out")
    a = ap.parse_args(argv)
    # Blender resolves a relative output path against something other than the shell's working folder (it wrote
    # to C:/world/... once); make every output path absolute here, where the working folder is still known.
    for k in ("json", "png", "overlay", "overlay_out"):
        if getattr(a, k):
            setattr(a, k, os.path.abspath(getattr(a, k)))
    rep = measure(a.module)
    probs = problems(rep, json.loads(a.piece_tris) if a.piece_tris else None)
    for p in rep["pieces"]:
        print("%-32s %6d tris  status=%s" % (p["piece"], p["lod0_tris"], p["kit_status"]))
    for p in rep["linked_pieces"]:
        print("%-32s %6d tris  status=%s  (linked)" % (p["piece"], p["tris"], p["kit_status"]))
    print("[qa] %d piece(s), %d linked piece(s), %d placement(s), %d librar(ies)"
          % (len(rep["pieces"]), len(rep["linked_pieces"]), len(rep["placements"]), len(rep["libraries"])))
    for p in probs:
        print("[qa] PROBLEM " + p)
    if a.json:
        rep["problems"] = probs
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2)
    for im in rep["images"]:
        print("[qa] image %-40s %sx%s ch%d %-10s %s%s" % (im["image"], im["size"][0], im["size"][1], im["channels"],
              im["colorspace"], "relative" if im["relative"] else "ABSOLUTE", " packed" if im["packed"] else ""))
    if a.tile_seam:
        rep["tile_seam"] = [tile_seam(p) for p in a.tile_seam]
        for t in rep["tile_seam"]:
            print("[qa] seam %s: x %.2f, y %.2f (edge step / inner step)" % (os.path.basename(t["image"]),
                  t["ratio_x"], t["ratio_y"]))
        if a.json:
            with open(a.json, "w", encoding="utf-8") as f:
                json.dump(rep, f, indent=2)
    if a.view:
        render_view(a.png, a.view[0:3], a.view[3:6], a.view[6])
        print("[qa] rendered " + a.png)
    elif a.render:
        render_ortho(a.png, a.render, a.center, a.extent, a.px_per_m, clip=a.clip)
        print("[qa] rendered " + a.png)
        if a.overlay:
            size = (max(16, int(round(a.extent[0] * a.px_per_m))), max(16, int(round(a.extent[1] * a.px_per_m))))
            print("[qa] overlay " + overlay_svg(a.png, a.overlay, a.overlay_out or a.png + ".overlay.svg",
                                               size=size))


if __name__ == "__main__":
    _main()
