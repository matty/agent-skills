"""Blender <-> RizomUV bridge: unwrap meshes headless and in memory, write UV0 and the lightmap UV, grade them.

Host: Blender 4.2+ (bpy + its bundled numpy), RizomUV 2027.0.417+ installed. No files are written for the
transfer: geometry goes to RizomUV as arrays and the UVs come back the same way. Normals, materials and every
other attribute stay in Blender.

    import sys; sys.path.insert(0, r"<skill>/scripts")
    import blender_rizom as br
    br.unwrap_selected(kind="organic")                     # UVMap (1024/8/4) + UVMap_Lightmap (128/4/2), graded
    br.unwrap_selected(kind="hard", uv0=br.ru.pack_spec(1024, 8, 4, px_per_unit=512))   # 512 px/m texel density

From a script with no UI (the scene is saved only if you ask):
    blender -b --factory-startup scene.blend --python-expr "import sys; sys.path.insert(0, r'<skill>/scripts'); \
        import blender_rizom as br; br.unwrap_objects(br.meshes_matching('KIT_*'), kind='hard'); br.save()"

What is read
  - The mesh data with its world transform, taken fresh from the depsgraph (a transform set earlier in the same
    script counts), so texel density is in pixels per metre of the placed object.
  - Seams you mark (edge use_seam) become seams in RizomUV; its Auto cuts are added on top. Mark the structural
    ones (mitres, springing lines, the back of a revolved part) on generated pieces: they decide packing quality.
  - Kind per object: the custom property "rizom_kind" ("hard" | "organic", any case) wins over the kind argument.
  - Modifiers: an object with enabled modifiers is refused (modifiers="refuse"), because the base mesh is not what
    exports (a Mirror doubles it, a Subdivision changes it). modifiers="apply" bakes them into the mesh first
    (destructive: the modifiers are removed, and linked duplicates keep the old mesh); modifiers="ignore" is for
    modifiers that cannot change the faces. SAFE_MODIFIERS never block.
What is written
  - "UVMap" (texture channel) at index 0 and "UVMap_Lightmap" (the lightmap channel in most engines) at index 1. Other layers are kept,
    after them and in their order (an engine sees them as the third channel and up); a mesh that would need more than 8 layers is
    refused before anything changes.
  - A layer is written only when its pack fits; when UV0 does not fit, nothing is written. The report says why.
  - Linked duplicates share one mesh, so unwrap_objects() unwraps each mesh once and reports the texel density
    every user ends up with (it differs when their world scales differ).
"""

import os
import sys
import time

import bpy

_HERE = os.path.dirname(os.path.abspath(globals().get("__file__") or ""))
if _HERE and _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import rizom_uv as ru  # noqa: E402
import uv_metrics as um  # noqa: E402
from rizom_link import RizomSession  # noqa: E402

UV0_NAME, UV2_NAME = "UVMap", "UVMap_Lightmap"
UV0 = ru.pack_spec(1024, 8, 4)        # texture channel: per-piece map, filled
UV2 = ru.pack_spec(128, 4, 2)         # lightmap channel, fixed 128 px; uv2="footprint" sizes it from the mesh area
SAFE_MODIFIERS = {"WEIGHTED_NORMAL", "NORMAL_EDIT"}
MAX_UV_LAYERS = 8


def meshes_matching(pattern="*"):
    import fnmatch
    return [o for o in bpy.data.objects if o.type == "MESH" and fnmatch.fnmatch(o.name, pattern)]


# ----------------------------------------------------------------------------------------------- reading
def _world_matrix(ob):
    try:
        dg = bpy.context.evaluated_depsgraph_get()     # updates the depsgraph: fresh transforms
        return ob.evaluated_get(dg).matrix_world.copy()
    except Exception:  # noqa: BLE001  (object outside the view layer)
        bpy.context.view_layer.update()
        return ob.matrix_world.copy()


def active_modifiers(ob):
    return [m for m in ob.modifiers if (m.show_viewport or m.show_render) and m.type not in SAFE_MODIFIERS]


def check_object(ob, modifiers="refuse"):
    """Raise a clear TypeError/ValueError if ob cannot be unwrapped as it stands."""
    if modifiers not in ("refuse", "apply", "ignore"):
        raise ValueError("modifiers must be 'refuse', 'apply' or 'ignore', not %r" % (modifiers,))
    kind = getattr(ob, "type", type(ob).__name__)
    if kind != "MESH":
        raise TypeError("%s is a %s object, not a mesh" % (getattr(ob, "name", ob), kind))
    me = ob.data
    if len(me.polygons) == 0:
        raise ValueError("%s has no faces" % ob.name)
    if not any(p.area > 0 for p in me.polygons):
        raise ValueError("every face of %s has zero area" % ob.name)
    mods = active_modifiers(ob)
    if mods and modifiers == "refuse":
        raise ValueError("%s has modifiers %s: the base mesh is not what exports. Apply them, or pass "
                         "modifiers='apply' (bakes them in) or modifiers='ignore' (only if they cannot change the "
                         "faces)" % (ob.name, [m.type for m in mods]))


def apply_modifiers(ob):
    """Replace ob's mesh with its evaluated mesh and remove the modifiers (destructive)."""
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    old = ob.data
    ob.modifiers.clear()
    ob.data = me
    if old.users == 0:
        bpy.data.meshes.remove(old)


def mesh_arrays(ob, world=True, split_on_uv=None):
    """RizomUV Data arrays for ob. UV topology is split at seam edges (and, with split_on_uv=<layer name>, at
    that layer's island borders too); seed UV coordinates are the 3D positions."""
    me = ob.data
    mw = _world_matrix(ob) if world else None
    co = [(mw @ v.co) if mw is not None else v.co for v in me.vertices]
    xyz = [c for p in co for c in (p.x, p.y, p.z)]
    loops = me.loops
    parent = list(range(len(loops)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    seam = {tuple(sorted(e.vertices)): e.use_seam for e in me.edges}
    uvl = me.uv_layers[split_on_uv].data if split_on_uv else None
    same = (lambda a, b: (uvl[a].uv - uvl[b].uv).length < 1e-6) if uvl else (lambda a, b: True)
    owners = {}
    for p in me.polygons:
        li = list(p.loop_indices)
        for i in range(len(li)):
            a, b = li[i], li[(i + 1) % len(li)]
            va, vb = loops[a].vertex_index, loops[b].vertex_index
            owners.setdefault((min(va, vb), max(va, vb)), []).append({va: a, vb: b})
    for key, own in owners.items():
        if len(own) != 2 or seam.get(key, False):
            continue
        if not all(same(own[0][v], own[1][v]) for v in key):
            continue
        for v in key:
            ra, rb = find(own[0][v]), find(own[1][v])
            parent[ra] = rb
    roots, uvw_ids, uvw, sizes, xyz_ids = {}, [], [], [], []
    for p in me.polygons:
        sizes.append(p.loop_total)
        for li in p.loop_indices:
            vi = loops[li].vertex_index
            xyz_ids.append(vi)
            r = find(li)
            if r not in roots:
                roots[r] = len(roots)
                uvw.extend(xyz[3 * vi:3 * vi + 3])
            uvw_ids.append(roots[r])
    return {"sizes": sizes, "xyz_ids": xyz_ids, "xyz": xyz, "uvw_ids": uvw_ids, "uvw": uvw}


def uv_arrays(ob, layer, world=True):
    """(mesh, uvw_ids, uvw) for an existing UV layer, ready for uv_metrics (grade any UVs, not only RizomUV's)."""
    mesh = mesh_arrays(ob, world=world)
    uv = ob.data.uv_layers[layer].data
    ids, coords, seen = [], [], {}
    for li in range(len(ob.data.loops)):
        k = (round(uv[li].uv[0], 7), round(uv[li].uv[1], 7), ob.data.loops[li].vertex_index)
        if k not in seen:
            seen[k] = len(seen)
            coords.extend((uv[li].uv[0], uv[li].uv[1], 0.0))
        ids.append(seen[k])
    order = [li for p in ob.data.polygons for li in p.loop_indices]
    return mesh, [ids[li] for li in order], coords


# ----------------------------------------------------------------------------------------------- writing
def _layer_plan(ob, names):
    existing = [l.name for l in ob.data.uv_layers]
    want = list(names) + [n for n in existing if n not in names]
    if len(want) > MAX_UV_LAYERS:
        raise ValueError("%s would need %d UV layers and Blender allows %d: remove some of %s"
                         % (ob.name, len(want), MAX_UV_LAYERS, existing))
    return existing, want


def order_layers(ob, names=(UV0_NAME, UV2_NAME)):
    """Put the layers `names` at indices 0, 1, ... (creating missing ones) and keep every other layer after them
    in its order, data intact. Blender cannot reorder layers, so they are rebuilt when the order is wrong. The
    first name becomes the active and render-active layer. Raises before changing anything if the mesh would
    need more than 8 layers. Returns True if the layers were rebuilt."""
    import numpy as np
    me = ob.data
    existing, want = _layer_plan(ob, names)
    if existing[:len(names)] == list(names):
        return False
    n = len(me.loops)
    data = {}
    for lay in me.uv_layers:
        a = np.empty(2 * n, dtype=np.float32)
        lay.data.foreach_get("uv", a)
        data[lay.name] = a
    while len(me.uv_layers):
        me.uv_layers.remove(me.uv_layers[0])
    for name in want:
        lay = me.uv_layers.new(name=name, do_init=False)
        if name in data:
            lay.data.foreach_set("uv", data[name])
    me.uv_layers.active_index = 0
    me.uv_layers[0].active_render = True
    return True


ensure_layers = order_layers   # earlier name, kept for scripts that call it


def write_uv(ob, name, uvw_ids, uvw):
    """Write one layer corner by corner (the corner order of mesh_arrays)."""
    import numpy as np
    me = ob.data
    layer = me.uv_layers.get(name) or me.uv_layers.new(name=name)
    ls = np.empty(len(me.polygons), dtype=np.int32)
    lt = np.empty(len(me.polygons), dtype=np.int32)
    me.polygons.foreach_get("loop_start", ls)
    me.polygons.foreach_get("loop_total", lt)
    order = np.repeat(ls, lt) + (np.arange(int(lt.sum())) - np.repeat(np.cumsum(lt) - lt, lt))
    co = np.asarray(uvw, dtype=np.float64).reshape(-1, 3)[:, :2]
    uv = np.zeros((len(me.loops), 2), dtype=np.float32)
    uv[order] = co[np.asarray(uvw_ids, dtype=np.int64)]
    layer.data.foreach_set("uv", uv.ravel())
    return layer


# ----------------------------------------------------------------------------------------------- unwrapping
def unwrap_object(link, ob, kind="hard", uv0=UV0, uv2=UV2, gate=None, stretch_png=None, grade=True,
                  modifiers="refuse", lightmap_texels_per_m=20.0):
    """Unwrap ob once, pack UV0 and (unless uv2 is None) the lightmap UV from the same islands, write the layers
    that fit, and return a report: attempt used, gate failures, warnings and per-layer metrics.
    uv2="footprint" sizes the lightmap UV from the mesh area at lightmap_texels_per_m (rizom_uv.lightmap_footprint)."""
    t = time.perf_counter()
    check_object(ob, modifiers)
    kind = ru.resolve_kind(ob.get("rizom_kind", kind))
    warnings = []
    if modifiers == "apply" and active_modifiers(ob):
        warnings.append("modifiers applied: %s" % [m.type for m in active_modifiers(ob)])
        apply_modifiers(ob)
    mesh = mesh_arrays(ob)
    if uv2 == "footprint":
        area = ru._areas(mesh, mesh["uvw_ids"], mesh["uvw"])[0]
        uv2 = ru.pack_spec(ru.lightmap_footprint(area, lightmap_texels_per_m), 4, 2)
    packs = {UV0_NAME: uv0}
    if uv2:
        packs[UV2_NAME] = uv2
    _layer_plan(ob, list(packs))                      # refuse now, not after the unwrap, if layers cannot fit
    res = ru.unwrap_gated(link, mesh, kind, packs, gate=gate)
    fits = {n: res["packs"][n]["fits"] for n in packs}
    write = [n for n in packs if fits[n]] if fits[UV0_NAME] else []
    existing = [l.name for l in ob.data.uv_layers]
    if write:
        order_layers(ob, [n for n in (UV0_NAME, UV2_NAME) if n in write or n in existing])
        for n in write:
            write_uv(ob, n, res["packs"][n]["uvw_ids"], res["packs"][n]["uvw"])
    for n in packs:
        if not fits[n]:
            spec = packs[n]
            warnings.append("%s does not fit (%s on %d px): %s" % (
                n, ("%s px/m" % spec["px_per_unit"]) if spec.get("px_per_unit") else "fill", spec["map_px"],
                "nothing written" if n == UV0_NAME else "layer not written"))
    session = getattr(link, "session", None)
    rep = {"object": ob.name, "mesh": ob.data.name, "kind": kind, "attempt": res["attempt"],
           "attempts": res["attempts"], "islands": res["islands"], "faces": len(mesh["sizes"]),
           "gate_failures": res["gate_failures"], "warnings": warnings,
           "rizomuv": session.version if session else link.RizomUVVersion(), "layers": {}}
    for name, spec in packs.items():
        p = res["packs"][name]
        layer = {"fits": p["fits"], "written": name in write, "px_per_unit": round(p["px_per_unit"], 2),
                 "map_px": spec["map_px"]}
        if grade:
            layer.update(um.report(mesh, p["uvw_ids"], p["uvw"], spec["map_px"], pad_px=spec["pad_px"],
                                   margin_px=spec["margin_px"]))
        rep["layers"][name] = layer
    users = [o for o in bpy.data.objects if o.data == ob.data and o != ob]
    if users and UV0_NAME in write:
        p0 = res["packs"][UV0_NAME]
        per = {ob.name: rep["layers"][UV0_NAME]["px_per_unit"]}
        for o in users:
            per[o.name] = um.texel_density(mesh_arrays(o), p0["uvw_ids"], p0["uvw"], uv0["map_px"])["px_per_unit_mean"]
        rep["shared_by"] = sorted(per)
        rep["px_per_unit_per_user"] = per
        if max(per.values()) > 1.01 * min(per.values()):
            warnings.append("mesh %s is shared by objects with different world scales: texel density differs "
                            "per object (%s)" % (ob.data.name, ", ".join("%s %.0f" % kv for kv in sorted(per.items()))))
    if stretch_png:
        p0 = res["packs"][UV0_NAME]
        ru.load_layout(link, mesh, p0["uvw_ids"], p0["uvw"])     # exactly the layout that was graded and written
        rep["stretch_neutral"] = ru.stretch_map(link, mesh, stretch_png)
        rep["stretch_png"] = os.path.abspath(stretch_png)
    rep["seconds"] = round(time.perf_counter() - t, 2)
    return rep


def _stretch_path(stretch_dir, stretch_png, ob, many):
    if stretch_dir:
        return os.path.join(stretch_dir, "%s_stretch.png" % bpy.path.clean_name(ob.name))
    if stretch_png and many:
        stem, ext = os.path.splitext(stretch_png)
        return "%s_%s%s" % (stem, bpy.path.clean_name(ob.name), ext or ".png")
    return stretch_png


def unwrap_objects(objects, kind="hard", report_path=None, stretch_dir=None, stretch_png=None, timeout=600.0,
                   priority=None, **kw):
    """Unwrap each mesh in one headless RizomUV session; prints one line per object and returns the reports.

    - Linked duplicates: each mesh datablock is unwrapped once (its first object here); the others report
      "shared_mesh_of" and the first one's report lists every user's texel density.
    - One bad mesh costs that mesh, not the batch. If RizomUV dies or an object runs past `timeout` seconds,
      the instance is killed, a new one is started and the batch continues.
    - Stretch maps: stretch_dir writes <object>_stretch.png per object; a single stretch_png path gets the
      object name added when there are several objects.
    - priority: "normal", "below_normal" or "idle" for the RizomUV instance (default RIZOMUV_PRIORITY)."""
    objects = list(objects)
    reps, done = [], {}
    session = RizomSession(priority=priority)
    session.start()
    try:
        for ob in objects:
            data = getattr(ob, "data", None)
            if data is not None and getattr(ob, "type", None) == "MESH" and data.name in done:
                r = {"object": ob.name, "mesh": data.name, "shared_mesh_of": done[data.name]}
                reps.append(r)
                print(_line(r))
                continue
            png = _stretch_path(stretch_dir, stretch_png, ob, len(objects) > 1)
            try:
                if not session.alive():
                    session.restart()
                with session.deadline(timeout):
                    r = unwrap_object(session.link, ob, kind, stretch_png=png, **kw)
                if data is not None:
                    done[data.name] = ob.name
            except Exception as ex:  # noqa: BLE001  (reported per object; the batch goes on)
                name = getattr(ob, "name", str(ob))
                if session.timed_out:
                    r = {"object": name, "error": "timed out after %g s; RizomUV restarted" % timeout}
                elif not session.alive() or isinstance(ex, session.CZEx):
                    r = {"object": name, "error": "RizomUV failed (%s: %s); restarted" % (type(ex).__name__, ex)}
                else:
                    r = {"object": name, "error": "%s: %s" % (type(ex).__name__, ex)}
                if session.timed_out or not session.alive() or isinstance(ex, session.CZEx):
                    try:
                        session.restart()
                    except Exception as rex:  # noqa: BLE001
                        r["error"] += "; restart failed (%s), batch stopped" % rex
                        reps.append(r)
                        print(_line(r))
                        break
            reps.append(r)
            print(_line(r))
    finally:
        session.close()
    if report_path:
        import json
        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump(reps, fh, indent=1, default=str)
    return reps


def unwrap_selected(kind="hard", **kw):
    return unwrap_objects([o for o in bpy.context.selected_objects if o.type == "MESH"], kind, **kw)


def save():
    bpy.ops.wm.save_mainfile()


def checker_preview(ob, size=1024):
    """Assign a generated colour-grid material so stretching and density read at a glance in the viewport."""
    mat = bpy.data.materials.get("RIZOM_UVGrid") or bpy.data.materials.new("RIZOM_UVGrid")
    mat.use_nodes = True
    nt = mat.node_tree
    tex = next((n for n in nt.nodes if n.type == "TEX_IMAGE"), None) or nt.nodes.new("ShaderNodeTexImage")
    img = bpy.data.images.get("RIZOM_UVGrid") or bpy.data.images.new("RIZOM_UVGrid", size, size)
    img.generated_type = "COLOR_GRID"
    tex.image = img
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    if mat.name not in [m.name for m in ob.data.materials if m]:
        ob.data.materials.append(mat)


def _line(r):
    if "error" in r:
        return "  FAIL   %-28s %s" % (r["object"], r["error"])
    if "shared_mesh_of" in r:
        return "  SHARED %-28s uses the UVs of %s (one mesh)" % (r["object"], r["shared_mesh_of"])
    l0 = r["layers"].get(UV0_NAME, {})
    d = l0.get("distortion", {})
    unfit = [n for n, v in r["layers"].items() if not v.get("fits", True)]
    state = "OK    " if not r["gate_failures"] and not unfit else "REVIEW"
    notes = list(r["gate_failures"]) + ["%s does not fit" % n for n in unfit]
    return ("  %s %-28s %-7s %3d isl  cov %s  ang p95 %s  area p95 %s  %s  [%s] %.2fs"
            % (state, r["object"], r["kind"], r["islands"], l0.get("coverage"), d.get("angular_p95"),
               d.get("area_local_p95"), "; ".join(notes) or "gate ok", r["attempt"], r["seconds"]))
