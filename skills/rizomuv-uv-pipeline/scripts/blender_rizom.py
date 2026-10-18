"""Blender <-> RizomUV bridge: unwrap meshes headless and in memory, write UV0 and the lightmap UV, grade them.

Host: Blender 4.2+ (bpy + its bundled numpy), RizomUV 2027.0.417+ installed. No files are written for the
transfer: geometry goes to RizomUV as arrays and the UVs come back the same way. Normals, materials and every
other attribute stay in Blender.

    import sys; sys.dont_write_bytecode = True; sys.path.insert(0, r"<skill>/scripts")
    import blender_rizom as br
    br.unwrap_selected(kind="organic")                       # UVMap (1024 px, 16 px gaps) + UVMap_Lightmap, graded
    br.unwrap_selected(kind="hard", uv0=br.ru.pack_spec(1024, px_per_unit=512))   # 512 px/m texel density
    br.unwrap_selected(lightmap_texels_per_m=10, lightmap_scale=0.5)   # the scene's Lightmap Resolution and the
                                                                         # renderers' Scale In Lightmap

From a script with no UI (the scene is saved only if you ask; --python-exit-code 1 makes a Python error exit 1,
and raise_on_failure turns FAIL lines into one; REVIEW and FAIL lines alone never set the exit code):
    blender -b --factory-startup --python-exit-code 1 scene.blend --python-expr "import sys; \
        sys.dont_write_bytecode = True; sys.path.insert(0, r'<skill>/scripts'); import blender_rizom as br; \
        reps = br.unwrap_objects(br.meshes_matching('KIT_*'), kind='hard'); br.save(); br.raise_on_failure(reps)"

What is read
  - The mesh data with its world transform, taken fresh from the depsgraph (a transform set earlier in the same
    script counts), so texel density is in pixels per metre of the placed object.
  - Seams you mark (edge use_seam) become seams in RizomUV; its Auto cuts are added on top. Mark the structural
    ones (mitres, springing lines, the back of a revolved part) on generated pieces: they decide packing quality.
  - Per object, custom properties win over the arguments: "rizom_kind" ("hard" | "organic"), "rizom_directional"
    ("grain" | "upright" | a Rotate.Initial axis map | 0 for none) and "rizom_lightmap_scale" (the renderer's
    Scale In Lightmap).
  - Linked objects and meshes (from a library .blend) and library-override meshes are refused: their new UVs would
    be lost on save. Unwrap them in their KIT file.
  - One Blender job per .blend: unwrap_objects() and save() hold a lock file next to the open .blend
    (<name>.blend.rizomuv-lock, freed when this Blender exits or opens another file) and refuse when another job
    holds it, or when another process saved the file after this Blender loaded it. Two jobs saving one .blend keep
    only the last save, and the other job's UVs are lost. Limits: the file time is recorded when this module is
    first imported and at every later load and save, so if another process may have saved the file since a
    Blender opened it before the import, revert or reopen it there first (File > Revert drops unsaved edits); and
    the lock only stops jobs that use this module, so close the .blend in other Blenders.
  - Modifiers: an object with modifiers on in the viewport is refused (modifiers="refuse"), because the base mesh
    is not what exports (a Mirror doubles it, a Subdivision changes it). A Triangulate, Weighted Normal or Normal
    Edit (SAFE_MODIFIERS) never counts and is never applied or removed, and a modifier off in the viewport is
    inactive: after uv-unwrapping's apply_stack, pass modifiers="ignore", never "apply" on a hard-surface piece.
    modifiers="apply" bakes the counted modifiers into a mesh of the object's own and removes only those
    (destructive; under the old mesh's name when no other object uses it, so linked duplicates with modifiers are
    each unwrapped); modifiers="ignore" is for modifiers that cannot change the faces.
What is written
  - "UVMap" (texture channel) at index 0 and "UVMap_Lightmap" (the lightmap channel in most engines) at index 1.
    Other layers are kept, after them and in their order (an engine sees them as the third channel and up); a mesh
    that would need more than 8 layers is refused before anything changes. When no lightmap layer is written and
    the mesh has none, the old first layer is reused for UVMap (renamed, overwritten) instead of being pushed into
    the lightmap slot.
  - UV0 is written when its pack fits, REVIEW or not; when UV0 does not fit, nothing is written. The lightmap
    layer is written when it passes its layout (no overlap, gaps >= 2 texels). When the smallest renderer's
    footprint is too small for 2-texel gaps (under 64 px), it is packed for 64 px instead and noted: every render
    mesh keeps a valid UV2. A lightmap layer that fails is not written, and an older UVMap_Lightmap is removed
    rather than left at index 1 for another footprint. The report says why.
  - LODs: a <Piece>_LOD<n> object (or mesh) is lightmapped at 0.5^n of the texel scale (Unity gives each LOD its
    own atlas space), so its UV2 is packed for that smaller footprint.
  - Every written layer is graded: UV0 on the distortion gate, its layout (padding and margin in map pixels) and
    a coverage floor; the lightmap layer on its layout in lightmap texels at each renderer's footprint, measured
    from the layout's bounding box (gaps >= 2 texels, >= 1 to the edge). A layer that fails prints REVIEW.
  - Linked duplicates share one mesh, so unwrap_objects() unwraps each mesh once, packs its lightmap UV for the
    smallest of its renderers and reports the texel density and lightmap footprint every user ends up with.
"""

import atexit
import json
import os
import socket
import sys
import time

import bpy

_HERE = os.path.dirname(os.path.abspath(globals().get("__file__") or ""))
if _HERE and _HERE not in sys.path:
    sys.path.insert(0, _HERE)

_KEEP_BYTECODE, sys.dont_write_bytecode = sys.dont_write_bytecode, True   # no __pycache__ in the skill folder
import rizom_uv as ru  # noqa: E402
import uv_metrics as um  # noqa: E402
import rizom_link as rl  # noqa: E402
from rizom_link import RizomSession  # noqa: E402
sys.dont_write_bytecode = _KEEP_BYTECODE

UV0_NAME, UV2_NAME = "UVMap", "UVMap_Lightmap"
UV0 = ru.pack_spec(1024)              # texture channel: per-piece map, filled, 16 px gaps and 8 px margin
SAFE_MODIFIERS = {"WEIGHTED_NORMAL", "NORMAL_EDIT", "TRIANGULATE"}   # never counted, applied or removed: a
# hard-surface stack's Triangulate and Weighted Normal carry its normals to export (clearing them: 12.59 deg off)
MAX_UV_LAYERS = 8
LOCK_SUFFIX = ".rizomuv-lock"


# ----------------------------------------------------------------------------------------------- one job per .blend
_BLEND = {"path": None, "mtime": None}   # the open .blend, and its file time when this Blender loaded or saved it
_BLEND_LOCKS = {}                        # path -> rizom_link.FileLock held by this Blender


def _note_blend(*_):
    """Remember the open .blend and its modification time (at import, and after every load and save here); let go
    of the lock on a file this Blender no longer has open."""
    path = os.path.abspath(bpy.data.filepath) if bpy.data.filepath else None
    for held in [k for k in _BLEND_LOCKS if k != path]:
        _drop_lock(held)
    try:
        mtime = os.stat(path).st_mtime_ns if path else None
    except OSError:
        mtime = None
    _BLEND.update(path=path, mtime=mtime)


@bpy.app.handlers.persistent
def _rizom_blend_handler(*_):
    _note_blend()


def _drop_lock(path):
    lock = _BLEND_LOCKS.pop(path, None)
    if lock is None:
        return
    for attempt in (0, 1):            # POSIX unlinks while still holding it; Windows only once it is closed
        try:
            os.remove(lock.path)
        except OSError:
            pass
        if attempt == 0:
            lock.release()


def _drop_locks():
    for path in list(_BLEND_LOCKS):
        _drop_lock(path)


for _handlers in (bpy.app.handlers.load_post, bpy.app.handlers.save_post):
    for _old in [f for f in _handlers if getattr(f, "__name__", "") == "_rizom_blend_handler"]:
        _handlers.remove(_old)        # a reloaded module replaces its handler
    _handlers.append(_rizom_blend_handler)
atexit.register(_drop_locks)
_note_blend()


def guard_blend():
    """Refuse a second job on the open .blend. Takes a lock file next to it (held until this Blender exits or opens
    another file) and raises RuntimeError when another Blender job holds it, or when the file on disk was saved by
    another process after this Blender loaded it (saving this copy would throw that work away). An unsaved file,
    or a folder where the lock file cannot be made, is not guarded. Returns the guarded path or None."""
    path = os.path.abspath(bpy.data.filepath) if bpy.data.filepath else None
    if path != _BLEND["path"]:
        _note_blend()
    if not path:
        return None
    try:
        now = os.stat(path).st_mtime_ns
    except OSError:
        now = None
    if _BLEND["mtime"] is not None and now is not None and now != _BLEND["mtime"]:
        raise RuntimeError("%s was saved by another process after this Blender loaded it: unwrapping and saving this "
                           "copy would throw that work away. Reopen the file, and give each parallel job its own "
                           ".blend" % path)
    if path not in _BLEND_LOCKS:
        lock = rl.FileLock(path + LOCK_SUFFIX, offset=1 << 20)
        if lock.acquire():
            lock.note("Blender PID %d on %s, since %s" % (os.getpid(), socket.gethostname(),
                                                           time.strftime("%Y-%m-%d %H:%M:%S")))
            _BLEND_LOCKS[path] = lock
        elif lock.open_error is None:
            raise RuntimeError("%s is held by another Blender job (%s): two jobs saving one .blend keep only the last "
                               "save, and the other's UVs are lost. Give each parallel job its own .blend, or unwrap "
                               "all its meshes in one unwrap_objects call" % (path, lock.holder() or lock.path))
    return path


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
    """The modifiers that change what exports: on in the viewport and not in SAFE_MODIFIERS. One off in the viewport
    is inactive (uv-unwrapping's apply_stack leaves its Triangulate off until after layout)."""
    return [m for m in ob.modifiers if m.show_viewport and m.type not in SAFE_MODIFIERS]


def check_object(ob, modifiers="refuse"):
    """Raise a clear TypeError/ValueError if ob cannot be unwrapped as it stands."""
    if modifiers not in ("refuse", "apply", "ignore"):
        raise ValueError("modifiers must be 'refuse', 'apply' or 'ignore', not %r" % (modifiers,))
    kind = getattr(ob, "type", type(ob).__name__)
    if kind != "MESH":
        raise TypeError("%s is a %s object, not a mesh" % (getattr(ob, "name", ob), kind))
    me = ob.data
    lib = getattr(ob, "library", None) or getattr(me, "library", None)
    if lib is not None:
        raise ValueError("%s is linked from %s: new UVs on a linked mesh are lost on save. Unwrap it in its KIT "
                         "file" % (ob.name, getattr(lib, "filepath", lib)))
    if getattr(me, "override_library", None) is not None:
        raise ValueError("%s uses a library override of mesh %s: new UVs on an override mesh are lost on save and "
                         "reload. Unwrap it in its KIT file" % (ob.name, me.name))
    if len(me.polygons) == 0:
        raise ValueError("%s has no faces" % ob.name)
    if not any(p.area > 0 for p in me.polygons):
        raise ValueError("every face of %s has zero area" % ob.name)
    mods = active_modifiers(ob)
    if mods and modifiers == "refuse":
        raise ValueError("%s has modifiers %s: the base mesh is not what exports. After uv-unwrapping's "
                         "apply_stack (keep_mirror=False before this layout), pass modifiers='ignore'; never 'apply' "
                         "on a hard-surface piece. Otherwise apply them, or pass modifiers='apply' (bakes these in; a "
                         "Triangulate or Weighted Normal stays) or 'ignore' (only if they cannot change the faces)"
                         % (ob.name, [m.type for m in mods]))


def apply_modifiers(ob):
    """Bake ob's active modifiers (active_modifiers) into a mesh of its own and remove only those (destructive). A
    Triangulate, Weighted Normal or Normal Edit is held off for the bake and kept, and a modifier off in the
    viewport is left alone, so a hard-surface stack keeps its normals at export. The new mesh takes the old one's
    name when no other object still uses the old one (an exported FBX keeps its mesh name). Returns its name."""
    baked = active_modifiers(ob)
    held = [m for m in ob.modifiers if m.show_viewport and m.type in SAFE_MODIFIERS]
    for m in held:
        m.show_viewport = False
    try:
        dg = bpy.context.evaluated_depsgraph_get()
        me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    finally:
        for m in held:
            m.show_viewport = True
    old = ob.data
    name = old.name
    for m in baked:
        ob.modifiers.remove(m)
    ob.data = me
    if old.users == 0:
        bpy.data.meshes.remove(old)
        me.name = name
    return me.name


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
    uvl = me.uv_layers[split_on_uv].uv if split_on_uv else None
    same = (lambda a, b: (uvl[a].vector - uvl[b].vector).length < 1e-6) if uvl else (lambda a, b: True)
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
    import numpy as np
    mesh = mesh_arrays(ob, world=world)
    me = ob.data
    a = np.empty(2 * len(me.loops), dtype=np.float64)
    me.uv_layers[layer].uv.foreach_get("vector", a)
    a = a.reshape(-1, 2)
    ids, coords, seen = [], [], {}
    for li in range(len(me.loops)):
        k = (round(float(a[li, 0]), 7), round(float(a[li, 1]), 7), me.loops[li].vertex_index)
        if k not in seen:
            seen[k] = len(seen)
            coords.extend((float(a[li, 0]), float(a[li, 1]), 0.0))
        ids.append(seen[k])
    order = [li for p in me.polygons for li in p.loop_indices]
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
        lay.uv.foreach_get("vector", a)
        data[lay.name] = a
    while len(me.uv_layers):
        me.uv_layers.remove(me.uv_layers[0])
    for name in want:
        lay = me.uv_layers.new(name=name, do_init=False)
        if name in data:
            lay.uv.foreach_set("vector", data[name])
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
    layer.uv.foreach_set("vector", uv.ravel())
    return layer


def _write_layers(ob, write, warnings):
    """Write order: UVMap at 0, UVMap_Lightmap at 1 when written or already there, the rest after. With no lightmap
    layer before or after, the old first layer is reused for UVMap so nothing lands in the lightmap slot."""
    existing = [l.name for l in ob.data.uv_layers]
    lightmap_after = UV2_NAME in write or UV2_NAME in existing
    if not lightmap_after and existing and UV0_NAME not in existing:
        warnings.append("layer %r renamed UVMap and overwritten (no lightmap layer, so nothing moves to index 1)"
                        % existing[0])
        ob.data.uv_layers[0].name = UV0_NAME
        existing[0] = UV0_NAME
    order_layers(ob, [n for n in (UV0_NAME, UV2_NAME) if n in write or n in existing])
    names = [l.name for l in ob.data.uv_layers]
    if not lightmap_after and len(names) > 1:
        warnings.append("index 1 holds %r, which an engine will use as the lightmap UV: remove it or write a "
                        "lightmap layer" % names[1])


# ----------------------------------------------------------------------------------------------- unwrapping
def world_area(ob):
    """Surface area of ob's mesh in m2 as placed (world matrix applied; exact polygon areas)."""
    import numpy as np
    me = ob.data
    mw = np.array(_world_matrix(ob))
    co = np.empty(3 * len(me.vertices))
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3) @ mw[:3, :3].T + mw[:3, 3]
    lv = np.empty(len(me.loops), dtype=np.int64)
    me.loops.foreach_get("vertex_index", lv)
    ls = np.empty(len(me.polygons), dtype=np.int64)
    lt = np.empty(len(me.polygons), dtype=np.int64)
    me.polygons.foreach_get("loop_start", ls)
    me.polygons.foreach_get("loop_total", lt)
    order = np.repeat(ls, lt) + (np.arange(int(lt.sum())) - np.repeat(np.cumsum(lt) - lt, lt))
    mesh = {"sizes": lt, "xyz_ids": lv[order], "xyz": co.ravel(), "uvw_ids": np.zeros(len(order), np.int64),
            "uvw": np.zeros(3)}
    return float(um.polygon_areas(mesh, mesh["uvw_ids"], mesh["uvw"])[0].sum())


def renderers(ob, lightmap_scale=1.0):
    """Every object that renders ob's mesh, ob first: {name: (surface area in m2 as placed, lightmap scale)}. The
    scale is the object's "rizom_lightmap_scale" property, else lightmap_scale, times 0.5^n for a <Piece>_LOD<n>
    object or mesh (rizom_uv.lod_scale)."""
    users = [ob] + [o for o in bpy.data.objects if o.data == ob.data and o != ob]

    def lod(o):
        return ru.lod_scale(o.name) if ru.lod_level(o.name) else ru.lod_scale(o.data.name)
    return {o.name: (world_area(o), float(o.get("rizom_lightmap_scale", lightmap_scale)) * lod(o)) for o in users}


def lightmap_spec_for(ob, mesh, uv2, lightmap_texels_per_m, lightmap_scale):
    """The lightmap pack for ob: uv2="footprint" packs for the smallest renderer of its mesh at the scene's texels
    per metre and each renderer's Scale In Lightmap (rizom_uv.lightmap_spec); a pack_spec dict is used as given."""
    if uv2 == "footprint":
        return ru.lightmap_spec(mesh, lightmap_texels_per_m, users=renderers(ob, lightmap_scale))
    return uv2


def _directional(ob, directional):
    """ob's "rizom_directional" property (a string, or a number: 0 none, 1 grain) wins over the argument."""
    v = ob.get("rizom_directional")
    if v is None:
        return directional
    if isinstance(v, (int, float)):
        return bool(v)
    return str(v) if str(v).lower() not in ("", "0", "none", "false") else False


def unwrap_object(link, ob, kind="hard", uv0=UV0, uv2="footprint", gate=None, stretch_png=None, grade=True,
                  modifiers="refuse", lightmap_texels_per_m=20.0, lightmap_scale=1.0, directional=False,
                  time_budget=None, progress=None):
    """Unwrap ob once, pack UV0 and (unless uv2 is None) the lightmap UV from the same islands, write the layers
    that fit, and return a report: attempt used, failures, warnings and per-layer metrics.
    uv2="footprint" (default) packs the lightmap UV with gaps >= 2 texels for the smallest renderer of the mesh at
    lightmap_texels_per_m (the scene's Lightmap Resolution) x its Scale In Lightmap ("rizom_lightmap_scale", else
    lightmap_scale), and grades it at each renderer's footprint from the layout's measured bounding box.
    directional ("rizom_directional" wins): "grain" (or True) lays each island's long side along U, "upright" turns
    world up to +V, another string is Pack's Rotate.Initial. progress (a dict) receives "written" as soon as
    layers are written, so a later failure can still say what changed."""
    t = time.perf_counter()
    check_object(ob, modifiers)
    kind = ru.resolve_kind(ob.get("rizom_kind", kind))
    direction = _directional(ob, directional)
    warnings = []
    if modifiers == "apply" and active_modifiers(ob):
        warnings.append("modifiers applied: %s" % [m.type for m in active_modifiers(ob)])
        old_name = ob.data.name
        if apply_modifiers(ob) != old_name:
            warnings.append("mesh %s is still used by other objects: %s now has its own mesh %s"
                            % (old_name, ob.name, ob.data.name))
    mesh = mesh_arrays(ob)
    packs = {UV0_NAME: ru.directional(uv0, direction)}
    spec2 = lightmap_spec_for(ob, mesh, uv2, lightmap_texels_per_m, lightmap_scale) if uv2 else None
    if spec2:
        packs[UV2_NAME] = spec2
    _layer_plan(ob, list(packs))                      # refuse now, not after the unwrap, if layers cannot fit
    res = ru.unwrap_gated(link, mesh, kind, packs, gate=gate, time_budget=time_budget)
    fits = {n: res["packs"][n]["fits"] for n in packs}
    uv2_fails = res["failures"].get(UV2_NAME) if UV2_NAME in packs else None
    if uv2_fails and res["reports"].get(UV2_NAME, {}).get("fallback_ok"):
        uv2_fails = None                         # re-packed for a larger footprint: written, its line says REVIEW
    write = [n for n in packs if fits[n] and not (n == UV2_NAME and uv2_fails)] if fits[UV0_NAME] else []
    removed = []
    if write and UV2_NAME in packs and UV2_NAME not in write and UV2_NAME in ob.data.uv_layers:
        ob.data.uv_layers.remove(ob.data.uv_layers[UV2_NAME])     # packed for another footprint: never keep it
        removed.append(UV2_NAME)
        warnings.append("the old %s was removed: the new one failed, and the old one was packed for another "
                        "footprint" % UV2_NAME)
    if write:
        _write_layers(ob, write, warnings)
        for n in write:
            write_uv(ob, n, res["packs"][n]["uvw_ids"], res["packs"][n]["uvw"])
        if progress is not None:
            progress["written"] = list(write)
    for n in packs:
        if not fits[n]:
            spec = packs[n]
            warnings.append("%s does not fit (%s on %d px): %s" % (
                n, ("%s px/m" % spec["px_per_unit"]) if spec.get("px_per_unit") else "fill", spec["map_px"],
                "nothing written" if n == UV0_NAME else "layer not written"))
        elif n == UV2_NAME and uv2_fails and fits[UV0_NAME]:
            warnings.append("%s not written: it failed its layout (%s)" % (n, "; ".join(uv2_fails)))
    session = getattr(link, "session", None)
    rep = {"object": ob.name, "mesh": ob.data.name, "kind": kind, "attempt": res["attempt"],
           "attempts": res["attempts"], "islands": res["islands"], "faces": len(mesh["sizes"]),
           "directional": direction or False, "gate_failures": res["gate_failures"], "failures": [],
           "warnings": warnings, "written": write, "removed": removed,
           "rizomuv": session.version if session else link.RizomUVVersion(), "layers": {}}
    for name, spec in packs.items():
        p, lrep = res["packs"][name], res["reports"].get(name, {})
        seen = lrep.get("footprint_px") or spec["map_px"]          # texels per metre at the size that is seen
        layer = {"fits": p["fits"], "written": name in write,
                 "px_per_unit": round(p["px_per_unit"] * seen / spec["map_px"], 2), "map_px": spec["map_px"],
                 "pack": {"map_px": spec["map_px"], "pad_px": spec["pad_px"], "margin_px": spec["margin_px"]}}
        if grade:
            layer.update(lrep)
            fails = list(res["failures"].get(name, []))
            layer["failures"] = fails
            rep["failures"] += [("%s: %s" % (name, f)) if name != UV0_NAME else f for f in fails]
            if name in write or name == UV2_NAME:      # lightmap notes even when no UV2 was written
                warnings += [w for w in lrep.get("warnings", []) if w not in warnings]
        rep["layers"][name] = layer
    users = [o for o in bpy.data.objects if o.data == ob.data and o != ob]
    if users and UV0_NAME in write:
        p0 = res["packs"][UV0_NAME]
        per = {ob.name: um.texel_density(mesh, p0["uvw_ids"], p0["uvw"], uv0["map_px"])["px_per_unit_mean"]}
        for o in users:
            per[o.name] = um.texel_density(mesh_arrays(o), p0["uvw_ids"], p0["uvw"], uv0["map_px"])["px_per_unit_mean"]
        rep["shared_by"] = sorted(per)
        rep["px_per_unit_per_user"] = per
        if max(per.values()) > 1.01 * min(per.values()):
            warnings.append("mesh %s is shared by objects with different world scales: texel density differs "
                            "per object (%s)" % (ob.data.name, ", ".join("%s %.0f" % kv for kv in sorted(per.items()))))
    if stretch_png and UV0_NAME in write:
        p0 = res["packs"][UV0_NAME]
        try:
            ru.load_layout(link, mesh, p0["uvw_ids"], p0["uvw"])     # exactly the layout that was graded and written
            rep["stretch_neutral"] = ru.stretch_map(link, mesh, stretch_png)
            rep["stretch_png"] = os.path.abspath(stretch_png)
        except Exception as ex:  # noqa: BLE001  (the UVs are written: a missing map is a warning, not a failure)
            warnings.append("stretch map not written (%s: %s)" % (type(ex).__name__, ex))
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
                   priority=None, headless=True, **kw):
    """Unwrap each mesh in one headless RizomUV session; prints one line per object and returns the reports.

    - Linked duplicates: each mesh datablock is unwrapped once (its first object here); the others report
      "shared_mesh_of" and the first one's report lists every user's texel density. With modifiers="apply" an
      object that has modifiers gets its own mesh, so it is always unwrapped itself.
    - One bad mesh costs that mesh, not the batch. If RizomUV dies or an object runs past `timeout` seconds,
      the instance is killed, a new one is started and the batch continues. The retry ladder stops starting new
      attempts at 80% of timeout, so a slow mesh keeps its best attempt instead of losing all of them.
    - A failure after the layers were written says which ones were ("written" in the report).
    - Stretch maps: stretch_dir writes <object>_stretch.png per object; a single stretch_png path gets the
      object name added when there are several objects.
    - priority: "normal", "below_normal" or "idle" for the RizomUV instance (default RIZOMUV_PRIORITY).
    - headless=False drives RizomUV with its window (any version RizomUVLink supports).
    - A bad gate or a report_path in a missing folder raises before RizomUV starts, and so does a .blend that
      another Blender job holds or saved since this one loaded it (guard_blend). If RizomUV cannot be restarted,
      the objects not reached are reported as FAIL "not attempted".
    - Every object is checked (check_object) before it can be SHARED: a refused object is FAIL even when its mesh
      shares a name with one already unwrapped. A timeout belongs to its own object: the next one starts clean.
    - timeout: 60 s is plenty for kit pieces (a few hundred faces take about a second); keep the default 600 s
      for dense meshes (an 82k-face auto-seam: 15-29 s on an idle machine, up to 158 s with other jobs running)."""
    objects = list(objects)
    um.merge_gate(kw.get("gate"))                       # a bad gate fails now, not once per object
    if report_path and not os.path.isdir(os.path.dirname(os.path.abspath(report_path))):
        raise FileNotFoundError("the folder of report_path %s does not exist" % report_path)
    guard_blend()
    modifiers = kw.get("modifiers", "refuse")
    reps, done = [], {}                                 # done: mesh datablock (as_pointer) -> first object
    session = RizomSession(priority=priority, headless=headless)
    session.start()
    apply = kw.get("modifiers") == "apply"
    try:
        for idx, ob in enumerate(objects):
            png = _stretch_path(stretch_dir, stretch_png, ob, len(objects) > 1)
            progress = {}
            session.timed_out = False                     # an earlier object's timeout is not this one's
            try:
                check_object(ob, modifiers)               # refused objects are FAIL, never SHARED
                if ob.data.as_pointer() in done and not (apply and active_modifiers(ob)):
                    r = {"object": ob.name, "mesh": ob.data.name, "shared_mesh_of": done[ob.data.as_pointer()]}
                    reps.append(r)
                    print(_line(r))
                    continue
                if not session.alive():
                    session.restart()
                with session.deadline(timeout):
                    r = unwrap_object(session.link, ob, kind, stretch_png=png, progress=progress,
                                      time_budget=0.8 * timeout if timeout else None, **kw)
                done[ob.data.as_pointer()] = ob.name      # the mesh it has now (apply gives it a new one)
            except Exception as ex:  # noqa: BLE001  (reported per object; the batch goes on)
                name = getattr(ob, "name", str(ob))
                if session.timed_out:
                    r = {"object": name, "error": "timed out after %g s; RizomUV restarted" % timeout}
                elif not session.alive() or isinstance(ex, session.CZEx):
                    r = {"object": name, "error": "RizomUV failed (%s: %s); restarted" % (type(ex).__name__, ex)}
                else:
                    r = {"object": name, "error": "%s: %s" % (type(ex).__name__, ex)}
                r["written"] = progress.get("written", [])
                if session.timed_out or not session.alive() or isinstance(ex, session.CZEx):
                    try:
                        session.restart()
                    except Exception as rex:  # noqa: BLE001
                        r["error"] += "; restart failed (%s), batch stopped" % rex
                        reps.append(r)
                        print(_line(r))
                        for rest in objects[idx + 1:]:
                            nr = {"object": getattr(rest, "name", str(rest)), "written": [],
                                  "error": "not attempted: RizomUV could not be restarted (%s)" % rex}
                            reps.append(nr)
                            print(_line(nr))
                        break
            reps.append(r)
            print(_line(r))
    finally:
        session.close()
    if report_path:
        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump(um.json_safe(reps), fh, indent=1, allow_nan=False, default=str)
    return reps


def raise_on_failure(reps, review=False):
    """Raise RuntimeError naming every FAIL object (and every REVIEW one with review=True), so a headless run with
    --python-exit-code 1 exits 1. FAIL and REVIEW lines alone never set Blender's exit code."""
    bad = [r for r in reps if "error" in r]
    if review:
        bad += [r for r in reps if "error" not in r and "shared_mesh_of" not in r and _state(r) == "REVIEW"]
    if bad:
        raise RuntimeError("%d object(s) %s: %s" % (len(bad), "failed or need review" if review else "failed",
                                                    "; ".join(_line(r).strip() for r in bad)))


def unwrap_selected(kind="hard", **kw):
    return unwrap_objects([o for o in bpy.context.selected_objects if o.type == "MESH"], kind, **kw)


def save():
    """Save the open .blend (no .blend1 backup: headless saves set save_version = 0 first). Refuses, like
    unwrap_objects, a file another Blender job holds or another process saved after this Blender loaded it."""
    guard_blend()
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_mainfile()


def checker_preview(ob, size=1024):
    """Show a colour grid on ob without touching its mesh: each material slot is switched to an object-level link
    showing RIZOM_UVGrid (a mesh with no slot gets one). checker_clear(ob) puts everything back."""
    mat = bpy.data.materials.get("RIZOM_UVGrid") or bpy.data.materials.new("RIZOM_UVGrid")
    if getattr(mat, "node_tree", None) is None:
        mat.use_nodes = True
    nt = mat.node_tree
    tex = next((n for n in nt.nodes if n.type == "TEX_IMAGE"), None) or nt.nodes.new("ShaderNodeTexImage")
    img = bpy.data.images.get("RIZOM_UVGrid") or bpy.data.images.new("RIZOM_UVGrid", size, size)
    img.generated_type = "COLOR_GRID"
    tex.image = img
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    if "rizom_checker" not in ob:
        if not ob.material_slots:
            ob.data.materials.append(None)
            ob["rizom_checker_added_slot"] = True
        ob["rizom_checker"] = json.dumps([[s.link, s.material.name if (s.link == "OBJECT" and s.material) else None]
                                          for s in ob.material_slots])
    for slot in ob.material_slots:
        slot.link = "OBJECT"
        slot.material = mat


def checker_clear(ob):
    """Undo checker_preview: the slots' links and object-level materials as they were."""
    saved = ob.get("rizom_checker")
    if saved is None:
        return
    for slot, (link, name) in zip(ob.material_slots, json.loads(saved)):
        slot.material = bpy.data.materials.get(name) if name else None
        slot.link = link
    if ob.get("rizom_checker_added_slot"):
        ob.data.materials.pop(index=len(ob.data.materials) - 1)
        del ob["rizom_checker_added_slot"]
    del ob["rizom_checker"]


def _unfit(r):
    return [n for n, v in r.get("layers", {}).items() if not v.get("fits", True)]


def _state(r):
    return "OK" if not r.get("failures", r.get("gate_failures", [])) and not _unfit(r) else "REVIEW"


def _line(r):
    if "error" in r:
        wrote = (" (layers written: %s)" % ", ".join(r["written"])) if r.get("written") else ""
        return "  FAIL   %-28s %s%s" % (r["object"], r["error"], wrote)
    if "shared_mesh_of" in r:
        return "  SHARED %-28s uses the UVs of %s (one mesh)" % (r["object"], r["shared_mesh_of"])
    l0 = r["layers"].get(UV0_NAME, {})
    d = l0.get("distortion", {})
    fails = r.get("failures", r.get("gate_failures", []))
    state = "%-6s" % _state(r)
    notes = list(fails) + ["%s does not fit" % n for n in _unfit(r)]
    for w in r.get("warnings", []):
        if w.startswith("lightmap footprint"):
            notes.append(w.split(":")[0].replace("lightmap footprint", "lightmap"))
        elif w.startswith("lightmap UV packed for"):
            notes.append("UV2 packed for %s px: too small" % w.split()[4])
        elif w.startswith("many islands"):
            notes.append("many islands")
        elif w.startswith("lightmap charts fill"):
            notes.append("UV2 box " + w.split()[3] + " full")
        elif w.startswith("the old " + UV2_NAME):
            notes.append("old UV2 removed")
        elif w.startswith("thin piece"):
            notes.append("thin piece")
    return ("  %s %-28s %-7s %3d isl  cov %s  ang p95 %s  area p95 %s  %s  [%s] %.2fs"
            % (state, r["object"], r["kind"], r["islands"], l0.get("coverage"), d.get("angular_p95"),
               d.get("area_local_p95"), "; ".join(notes) or "gate ok", r["attempt"], r["seconds"]))
