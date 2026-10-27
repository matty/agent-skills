"""Off-screen review renders for topology work: close-up wire, studio and reflective matcap, and contact sheets.

Host: Blender (bpy, gpu, numpy; tested on 5.2.2), live or headless.
Load in Blender:  ns = {}; exec(open(r"<skill>/scripts/review_render.py", encoding="utf-8").read(), ns)

    ns["render"](r"C:/.../corner-matcap.png", eye=(0, 2, -3), target=(0, 5, -1), light="MATCAP",
                 matcap="check_reflection_horizontal.exr", wire=True)
    with ns["isolate"](["MyPiece"], hide=["OldPiece"]): ns["render"](...)     # temporary visibility, restored after
    ns["contact_sheet"]([a.png, b.png, c.png, d.png], r"C:/.../sheet.png", cols=2)
    ns["compare"]("Cushion_dense", "Cushion_low", views=[(0, -1.2, 0.3), (1.2, 0, 0)], out=r"C:/.../compare.png",
                  light="MATCAP", matcap="check_reflection_horizontal.exr")   # before | after | silhouette

Pass absolute output paths. Live, it works while Blender's window is minimised (it draws through
gpu.types.GPUOffScreen, not a screenshot) using a 3D viewport in the current screen, switched to Solid shading with
the requested light for the render; its shading and overlay settings are restored afterwards.
Headless (blender -b --factory-startup file.blend --python-exit-code 1 --python your_script.py), where there is no
viewport, it falls back to a Workbench scene render: the same camera, light and matcap, with wire drawn by temporary
Wireframe-modifier copies that keep every modifier except subdivision. Objects inside collection instances render but
get no wire there: review a piece in its KIT file. Matcap names are Blender's (check_reflection_horizontal.exr ships
with 5.2.2).
A matcap shows curved bands across flat faces in a perspective view: that is the matcap, not smooth shading.
Back faces are culled by default, as the engine's stock shaders cull them (Unity's Standard, VRChat's mobile
shaders): a single-sided piece wound inside out vanishes here as it will in the game. cull=False shows them (to look
inside an open piece, or at cards a double-sided shader will draw).
"""

import contextlib
import os
import shutil
import tempfile

import bpy
import gpu
import numpy as np
from mathutils import Vector


def _view3d():
    area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')
    return area, next(r for r in area.regions if r.type == 'WINDOW'), area.spaces.active


def render(path, eye, target, matrix=None, lens=24, w=1200, h=800, light="STUDIO", matcap=None, wire=False,
           cull=True):
    """Render from eye towards target (object-space points, transformed by matrix if given, for example a placed
    object's matrix_world) to a PNG. light: 'STUDIO', 'MATCAP' (matcap: a studio-light name such as
    'check_reflection_horizontal.exr') or 'FLAT'. cull: hide back faces, as the engine does (default)."""
    eye, target = Vector(eye), Vector(target)
    if matrix is not None:
        eye, target = matrix @ eye, matrix @ target
    cd = bpy.data.cameras.new("_review_cam")
    cd.lens, cd.clip_start, cd.clip_end = lens, 0.02, 1000.0
    cam = bpy.data.objects.new("_review_cam", cd)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = eye
    cam.rotation_euler = (target - eye).to_track_quat('-Z', 'Y').to_euler()
    bpy.context.view_layer.update()
    if bpy.app.background or bpy.context.screen is None or not any(
            a.type == 'VIEW_3D' for a in bpy.context.screen.areas):
        try:
            return _render_scene(path, cam, w, h, light, matcap, wire, (target - eye).length, cull)
        finally:
            bpy.data.objects.remove(cam)
            bpy.data.cameras.remove(cd)
    area, region, sp = _view3d()
    sh, ov = sp.shading, sp.overlay
    keep_type = sh.type
    keep = (sh.light, sh.studio_light, sh.show_backface_culling, ov.show_overlays, ov.show_wireframes,
            ov.wireframe_threshold, ov.show_floor, ov.show_axis_x, ov.show_axis_y, ov.show_cursor,
            ov.show_object_origins)
    try:
        sh.type = 'SOLID'                     # the light settings below apply to Solid shading only
        sh.light = light
        sh.show_backface_culling = cull
        if matcap:
            sh.studio_light = matcap
        ov.show_overlays = True
        ov.show_wireframes, ov.wireframe_threshold = wire, 1.0
        ov.show_floor = ov.show_axis_x = ov.show_axis_y = ov.show_cursor = ov.show_object_origins = False
        view = cam.matrix_world.inverted()
        proj = cam.calc_matrix_camera(bpy.context.evaluated_depsgraph_get(), x=w, y=h)
        off = gpu.types.GPUOffScreen(w, h)
        try:
            off.draw_view3d(bpy.context.scene, bpy.context.view_layer, sp, region, view, proj,
                            do_color_management=True)
            buf = off.texture_color.read()
            buf.dimensions = w * h * 4
            px = np.asarray(buf, dtype=np.float32) / 255.0
        finally:
            off.free()
        _save(px, w, h, path)
    finally:
        (sh.light, sh.studio_light, sh.show_backface_culling, ov.show_overlays, ov.show_wireframes,
         ov.wireframe_threshold, ov.show_floor, ov.show_axis_x, ov.show_axis_y, ov.show_cursor,
         ov.show_object_origins) = keep
        sh.type = keep_type
        bpy.data.objects.remove(cam)
        bpy.data.cameras.remove(cd)
    return path


def _render_scene(path, cam, w, h, light, matcap, wire, distance, cull=True):
    """Headless path (blender -b has no 3D viewport or GPU context for GPUOffScreen): a Workbench scene render.
    Wireframe overlays do not exist in a render, so wire=True adds temporary copies of the visible meshes with a
    Wireframe modifier after their own modifiers (subdivision dropped, so the wire is the cage the viewport shows),
    drawn dark, and removes them afterwards. Nothing is saved."""
    scene = bpy.context.scene
    sh = scene.display.shading
    keep_scene = (scene.camera, scene.render.engine, scene.render.resolution_x, scene.render.resolution_y,
                  scene.render.resolution_percentage, scene.render.filepath, scene.render.image_settings.file_format)
    keep_sh = (sh.light, sh.studio_light, sh.color_type, sh.single_color[:], sh.show_backface_culling)
    shown = [o for o in scene.objects if o.type == 'MESH' and o.visible_get()]
    # A render ignores viewport hide flags (isolate() sets those), so hide the hidden ones from the render as well.
    unrender = [o for o in scene.objects if o.type == 'MESH' and not o.visible_get() and not o.hide_render]
    copies = []
    try:
        for o in unrender:
            o.hide_render = True
        scene.camera = cam
        scene.render.engine = 'BLENDER_WORKBENCH'
        scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = w, h, 100
        scene.render.image_settings.file_format = 'PNG'
        scene.render.filepath = path
        sh.light = light
        sh.show_backface_culling = cull
        if matcap:
            sh.studio_light = matcap
        if wire:
            sh.color_type = 'OBJECT'           # originals light grey, wire copies near black
            thickness = max(0.0015, distance * 0.0012)
            for ob in shown:
                dup = ob.copy()                 # shares the mesh data; only the copy gets the modifier
                for m in [m for m in dup.modifiers if m.type in {'SUBSURF', 'MULTIRES'}]:
                    dup.modifiers.remove(m)     # keep mirror, array, bevel...: the wire must match the surface
                mod = dup.modifiers.new("_review_wire", 'WIREFRAME')
                mod.thickness, mod.use_even_offset, mod.use_replace = thickness, True, True
                dup.color = (0.02, 0.02, 0.02, 1.0)
                scene.collection.objects.link(dup)
                copies.append((dup, ob, ob.color[:]))
                ob.color = (0.8, 0.8, 0.8, 1.0)
        bpy.ops.render.render(write_still=True)
    finally:
        for o in unrender:
            o.hide_render = False
        for dup, ob, colour in copies:
            ob.color = colour
            bpy.data.objects.remove(dup)
        (scene.camera, scene.render.engine, scene.render.resolution_x, scene.render.resolution_y,
         scene.render.resolution_percentage, scene.render.filepath,
         scene.render.image_settings.file_format) = keep_scene
        sh.light, sh.studio_light, sh.color_type, sh.single_color, sh.show_backface_culling = keep_sh
    return path


def _save(px, w, h, path):
    img = bpy.data.images.new("_review_img", w, h, alpha=True)
    try:
        img.pixels.foreach_set(np.asarray(px, dtype=np.float32).ravel())
        img.filepath_raw = path
        img.file_format = 'PNG'
        img.save()
    finally:
        bpy.data.images.remove(img)


@contextlib.contextmanager
def isolate(show, hide=()):
    """Temporarily show the named objects and hide others named in `hide` (view-layer hide flags), restoring them on
    exit. Objects in excluded collections cannot be shown this way: link previews into a visible collection of your own
    rather than un-excluding the user's."""
    names = list(show) + list(hide)
    was = {n: bpy.data.objects[n].hide_get() for n in names}
    try:
        for n in show:
            bpy.data.objects[n].hide_set(False)
        for n in hide:
            bpy.data.objects[n].hide_set(True)
        bpy.context.view_layer.update()
        yield
    finally:
        for n, h in was.items():
            bpy.data.objects[n].hide_set(h)
        bpy.context.view_layer.update()


def _load(path):
    im = bpy.data.images.load(path)
    try:
        return np.array(im.pixels[:], dtype=np.float32).reshape(im.size[1], im.size[0], 4)
    finally:
        bpy.data.images.remove(im)


def contact_sheet(paths, out, cols=2):
    """Tile equally sized PNGs into one image, left to right, top to bottom."""
    ims = [_load(p) for p in paths]
    h, w = ims[0].shape[:2]
    rows = [ims[i:i + cols] + [np.zeros_like(ims[0])] * (cols - len(ims[i:i + cols])) for i in range(0, len(ims), cols)]
    grid = np.vstack([np.hstack(r) for r in rows][::-1])        # Blender images are stored bottom row first
    _save(grid, grid.shape[1], grid.shape[0], out)
    return out


def _centre(ob):
    """World-space centre of the object's bounding box (modifiers included, as it draws)."""
    pts = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
    return sum(pts, Vector()) / len(pts)


def _silhouette(px, tol=0.02):
    """Pixels that differ from the background, taken as the most common of the four corner colours."""
    corners = [tuple(np.round(px[y, x, :3], 3)) for y in (0, -1) for x in (0, -1)]
    bg = np.array(max(set(corners), key=corners.count))
    return np.abs(px[..., :3] - bg).max(-1) > tol


def compare(before, after, views, out, wire=(True, False), silhouette=True, **render_kw):
    """Before | after review sheet of two objects (names), e.g. a dense source and its low. Each object is rendered
    alone (every other visible mesh hidden with isolate()) from the same eye and target relative to its own
    bounding-box centre, so a copy placed beside the original is framed exactly as the original is. Never render both
    in one wide frame: perspective shears the object off the frame's centre, and a correct low reads as distorted.
    views: eye offsets from the centre, or (eye offset, target offset) pairs. wire: one sheet row per view and per
    value (wire, then plain shading by default). silhouette=True adds a third column from the plain renders: grey
    where both cover the pixel, red where only before does, blue where only after does. render_kw go to render()
    (lens, w, h, light, matcap). Returns {"sheet": out, "mismatch": [per view, pixels covered by one object only /
    pixels covered by either]}."""
    if not wire:
        raise ValueError("compare() needs at least one wire value: wire=(True, False), (True,) or (False,)")
    obs = [bpy.data.objects[before], bpy.data.objects[after]]
    others = [o.name for o in bpy.context.view_layer.objects if o.type == 'MESH' and o.visible_get()
              and o.name not in (before, after)]
    tmp = tempfile.mkdtemp(prefix="review_compare_")
    tiles, mismatch = [], []
    try:
        for vi, v in enumerate(views):
            eye_off, target_off = (v if len(v) == 2 and len(v[0]) == 3 else (v, (0.0, 0.0, 0.0)))
            masks = []
            for wi, w in enumerate(list(wire) + ([False] if silhouette and False not in wire else [])):
                row = []
                for k, ob in enumerate(obs):
                    c = _centre(ob)
                    p = os.path.join(tmp, "v%d_w%d_%d.png" % (vi, wi, k))
                    with isolate([ob.name], hide=[obs[1 - k].name] + others):
                        render(p, eye=c + Vector(eye_off), target=c + Vector(target_off), wire=w, **render_kw)
                    row.append(p)
                if not w and silhouette and not masks:
                    masks = [_silhouette(_load(p)) for p in row]
                if wi < len(wire):
                    tiles.append(row)
            if silhouette:
                a, b = masks
                img = np.ones(a.shape + (4,), np.float32)
                img[..., :3] = 1.0
                img[a & b, :3] = 0.55
                img[a & ~b, :3] = (0.85, 0.1, 0.1)
                img[b & ~a, :3] = (0.1, 0.25, 0.9)
                p = os.path.join(tmp, "v%d_sil.png" % vi)
                _save(img, img.shape[1], img.shape[0], p)
                for row in tiles[-len(wire):]:
                    row.append(p)
                mismatch.append(round(float((a ^ b).sum()) / max(int((a | b).sum()), 1), 4))
        contact_sheet([p for row in tiles for p in row], out, cols=3 if silhouette else 2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {"sheet": out, "mismatch": mismatch}
