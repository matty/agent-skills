"""Look-dev renders, the PBR check and the final-look image statistics of the vrchat-world-qa skill's qa_measure.py.

Builds two spheres that differ only in their material's node roughness, texture maps with planted faults and a grey
test card in a temp folder, runs qa_measure in fresh headless Blenders, and checks that --light lookdev shows the
roughness Workbench cannot, that the look-dev rig restores the scene it changes, that --pbr reports the planted faults
and passes the good maps, and that --image-stats reports luma percentiles and the clipped and crushed shares.

Host: Blender 5.2.2 (bpy and its bundled numpy), headless:
    blender -b --factory-startup --python-exit-code 1 --python tools/tests/blender/test_qa_measure_lookdev.py
Prints PASS <case> / FAIL <case>: <why> for each case and raises if any failed. Writes only to a temp folder, removed
when every case passes (kept, and printed, when one fails).
"""

import json
import math
import shutil
import subprocess
import tempfile
import time
import traceback
from pathlib import Path

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
QA = ROOT / "skills" / "vrchat-world-qa" / "scripts" / "qa_measure.py"
BLENDER = bpy.app.binary_path
VIEW = ["0", "-3.2", "0.9", "0", "0", "0.5", "50"]       # both spheres, glossy on the left


# ---- fixtures -------------------------------------------------------------------------------------------------------

def principled(mat):
    return next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")


def sphere(name, x, roughness):
    me = bpy.data.meshes.new(name)
    ob = bpy.data.objects.new(name, me)
    coll = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(coll)
    coll.objects.link(ob)
    import bmesh
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=48, v_segments=24, radius=0.5)
    bm.to_mesh(me)
    bm.free()
    me.shade_smooth()
    ob.location = (x, 0.0, 0.5)
    mat = bpy.data.materials.new("M_TST_" + name.split("_")[1])
    if not mat.node_tree:
        mat.use_nodes = True
    bsdf = principled(mat)
    bsdf.inputs["Base Color"].default_value = (0.5, 0.5, 0.5, 1.0)
    bsdf.inputs["Metallic"].default_value = 0.0
    bsdf.inputs["Roughness"].default_value = roughness      # the viewport display values stay equal (Workbench)
    me.materials.append(mat)
    return ob


def save_png(path, rows_top_down):
    """An RGBA float array (rows top to bottom) as an 8-bit PNG through Blender (its pixel rows run bottom to top)."""
    a = np.asarray(rows_top_down, np.float32)
    h, w = a.shape[:2]
    img = bpy.data.images.new(Path(path).stem, w, h, alpha=True)
    img.pixels.foreach_set(a[::-1].ravel())
    img.filepath_raw = str(path)
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)


def bumps(n=128, seed=5):
    """A height field with round bumps (power-of-two size: the PBR check flags any other)."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float64)
    h = np.zeros((n, n))
    for _ in range(10):
        cx, cy, r = rng.uniform(8, n - 8), rng.uniform(8, n - 8), rng.uniform(4, 12)
        h += np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * r * r)) * rng.uniform(2, 5)
    return h


def normal_map(h, green=1.0):
    """OpenGL tangent-space normals of z = h (X right, Y up the image), encoded to 0-1, as RGBA rows top to bottom."""
    n = np.dstack([-np.gradient(h, axis=1), np.gradient(h, axis=0) * green, np.ones_like(h)])
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    return np.dstack([(n + 1.0) / 2.0, np.ones(h.shape)])


def flat(value, n=64, alpha=1.0):
    a = np.empty((n, n, 4), np.float32)
    a[...] = (value, value, value, alpha)
    return a


def build(d):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.preferences.filepaths.save_version = 0
    sphere("TST_Glossy_Free_A", -0.7, 0.1)
    sphere("TST_Rough_Free_A", 0.7, 0.9)
    lamp = bpy.data.objects.new("Scene_Lamp", bpy.data.lights.new("Scene_Lamp", "POINT"))
    lamp.location = (0.0, -1.0, 3.0)
    bpy.context.scene.collection.objects.link(lamp)
    f = {"spheres": d / "KIT_LookDev.blend"}
    bpy.ops.wm.save_as_mainfile(filepath=str(f["spheres"]))

    maps = d / "maps"
    maps.mkdir()
    ms = flat(0.0)
    ms[:, :, 3] = np.linspace(0.3, 0.7, ms.shape[1])[None, :]           # smoothness varies, metallic 0
    save_png(maps / "T_TST_Good_BaseColor.png", flat(0.5))
    save_png(maps / "T_TST_Good_MetallicSmoothness.png", ms)
    save_png(maps / "T_TST_Good_Normal.png", normal_map(bumps()))
    save_png(maps / "T_TST_Bad_BaseColor.png", flat(0.05))                 # 13 sRGB: too dark
    save_png(maps / "T_TST_Bad_Normal.png", normal_map(bumps(), green=-1.0))   # DirectX
    f["maps"] = maps

    card = np.zeros((100, 100, 4), np.float32)
    card[:, :, 3] = 1.0
    card[30:60, :, :3] = 128 / 255.0                                       # 30% black, 30% grey, 40% white
    card[60:, :, :3] = 1.0
    f["card"] = d / "card.png"
    save_png(f["card"], card)
    return f


# ---- running qa_measure ---------------------------------------------------------------------------------------------

def run_qa(blend, args, json_path):
    cmd = [BLENDER, "-b", "--factory-startup"] + ([str(blend)] if blend else [])
    cmd += ["--python-exit-code", "1", "--python", str(QA), "--"] + [str(a) for a in args] + ["--json", str(json_path)]
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    seconds = time.time() - t0
    if p.returncode != 0 or not Path(json_path).exists():
        raise RuntimeError("exit %s: %s" % (p.returncode, (p.stdout + p.stderr)[-2000:]))
    return p, json.loads(Path(json_path).read_text(encoding="utf-8")), seconds


def halves(png):
    """Brightest luma (0-255) in the left and the right half of a render."""
    im = bpy.data.images.load(str(png), check_existing=False)
    try:
        w, h = im.size
        px = np.empty(w * h * 4, np.float32)
        im.pixels.foreach_get(px)
        a = px.reshape(h, w, 4)[:, :, :3] @ np.array([0.2126, 0.7152, 0.0722], np.float32) * 255.0
        return float(a[:, : w // 2].max()), float(a[:, w // 2:].max())
    finally:
        bpy.data.images.remove(im)


# ---- cases ----------------------------------------------------------------------------------------------------------

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def check(cond, why):
    if not cond:
        raise AssertionError(why)


@case
def lookdev_shows_roughness_workbench_does_not(d, f):
    look, wb = d / "look.png", d / "wb.png"
    p, rep, secs = run_qa(f["spheres"], ["--module", "1.0", "--view"] + VIEW + ["--light", "lookdev", "--png", look],
                          d / "look.json")
    check(look.exists() and rep["renders"], "no look-dev render: %s" % p.stdout[-600:])
    glossy, rough = halves(look)
    print("  look-dev: glossy max luma %.1f, rough %.1f, run %.1f s" % (glossy, rough, secs))
    check(glossy - rough >= 25, "look-dev highlight glossy %.1f vs rough %.1f" % (glossy, rough))
    r = rep["renders"][0]
    for k in ("luma_p1", "luma_p50", "luma_p99", "clipped_share", "crushed_share"):
        check(r.get(k) is not None, "render stats lack %s: %s" % (k, r))
    check(r["crushed_share"] < 0.05, "the grey world should keep the frame off black: %s" % r)
    _p, _rep, _s = run_qa(f["spheres"], ["--module", "1.0", "--view"] + VIEW
                          + ["--light", "studio", "--color", "material", "--png", wb], d / "wb.json")
    g2, r2 = halves(wb)
    print("  workbench: glossy max luma %.1f, rough %.1f" % (g2, r2))
    check(abs(g2 - r2) < 8, "Workbench should ignore the node roughness: %.1f vs %.1f" % (g2, r2))


@case
def lookdev_rig_restores_the_scene(d, f):
    bpy.ops.wm.open_mainfile(filepath=str(f["spheres"]))
    scene = bpy.context.scene

    def state():
        return {"engine": scene.render.engine, "world": scene.world.name if scene.world else None,
                "camera": scene.camera.name if scene.camera else None,
                "lamp_hidden": bpy.data.objects["Scene_Lamp"].hide_render,
                "view": scene.view_settings.view_transform, "samples": scene.eevee.taa_render_samples,
                "objects": len(bpy.data.objects), "lights": len(bpy.data.lights), "worlds": len(bpy.data.worlds),
                "cameras": len(bpy.data.cameras)}

    before = state()
    ns = {"__file__": str(QA)}
    exec(compile(QA.read_text(encoding="utf-8"), "qa_measure.py", "exec"), ns)
    ns["render_view"](str(d / "inproc.png"), (0, -3.2, 0.9), (0, 0, 0.5), 50.0, light="lookdev")
    check((d / "inproc.png").exists(), "no render written")
    check(state() == before, "scene changed: %s -> %s" % (before, state()))
    bpy.ops.wm.read_factory_settings(use_empty=True)


@case
def pbr_reports_faults_and_passes_good_maps(d, f):
    p, rep, _s = run_qa(None, ["--pbr", str(f["maps"] / "T_TST_*.png"), "--map-px", "1024"], d / "pbr.json")
    out = p.stdout
    check("[qa] PROBLEM pbr M_TST_Bad: base colour too dark" in out, out[-1500:])
    check(any("PROBLEM pbr M_TST_Bad" in line and "DirectX" in line for line in out.splitlines()), out[-1500:])
    check("PROBLEM pbr M_TST_Good" not in out, out[-1500:])
    by = {r["material"]: r for r in rep["pbr"]}
    check(sorted(by) == ["M_TST_Bad", "M_TST_Good"], sorted(by))
    check(by["M_TST_Good"]["normal"]["convention"] == "opengl", by["M_TST_Good"]["normal"])
    check(any(x.startswith("pbr M_TST_Bad: ") for x in rep["problems"]), rep["problems"])
    p2, rep2, _s = run_qa(None, ["--pbr", str(f["maps"] / "T_TST_Good_*.png"), "--pbr-targets",
                                 json.dumps({"M_TST_Good": {"albedo_srgb": [10, 60]}})], d / "pbr_t.json")
    check("PROBLEM pbr M_TST_Good: base colour off target" in p2.stdout, p2.stdout[-1500:])


@case
def image_stats_reports_luma_and_clipping(d, f):
    _p, rep, _s = run_qa(None, ["--image-stats", f["card"]], d / "card.json")
    s = rep["image_stats"][0]
    check(abs(s["clipped_share"] - 0.4) < 1e-3 and abs(s["crushed_share"] - 0.3) < 1e-3, s)
    check(s["luma_p1"] == 0.0 and abs(s["luma_p50"] - 128) <= 0.5 and abs(s["luma_p99"] - 255) <= 0.5, s)


def main():
    d = Path(tempfile.mkdtemp(prefix="qa_measure_lookdev_"))
    failed = []
    try:
        f = build(d)
    except Exception:
        traceback.print_exc()
        raise RuntimeError("fixture build failed (fixtures in %s)" % d)
    for fn in CASES:
        try:
            fn(d, f)
            print("PASS %s" % fn.__name__)
        except Exception as exc:
            failed.append(fn.__name__)
            print("FAIL %s: %s" % (fn.__name__, exc))
    if not failed:
        shutil.rmtree(d, ignore_errors=True)
    print("%d case(s), %d failed%s" % (len(CASES), len(failed), " (fixtures kept in %s)" % d if failed else ""))
    if failed:
        raise RuntimeError("failed: " + ", ".join(failed))


main()
