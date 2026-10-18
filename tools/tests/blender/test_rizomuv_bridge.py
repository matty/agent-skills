"""Blender-hosted tests for rizomuv-uv-pipeline's scripts/blender_rizom.py with a fake RizomUV link (no RizomUV, no
licence): seams reach the seed topology, the layer order (UVMap at 0, the lightmap UV at 1, an imported first layer
reused rather than pushed into the lightmap slot), linked duplicates with modifiers='apply', a stretch map that
fails after the UVs are written, a failure after the write that still says what was written, the OK / REVIEW line
from the one grader, a strict-JSON report, checker_preview / checker_clear, save() without a .blend1, one job per
.blend (a lock and a changed-on-disk check), override and same-named linked meshes refused, the mesh name kept by
modifiers='apply', the thin-piece note, a lightmap UV packed for 64 px when too small and left unwritten (an old
one removed) when it fails, a timeout that does not stick to the next object, LOD1 at half the footprint, and the
revert that keeps another job's save, a failing lightmap fallback climbing to a larger footprint, and hard-surface
routes A and B after uv-unwrapping's apply_stack: never refused, their Triangulate and Weighted Normal kept, and
the kit FBX export's normals unchanged (modifiers='apply' bakes only a Mirror above them).

Host: Blender 4.2+ (bpy; tested on 5.2.2), run from anywhere:
    blender -b --factory-startup --python-exit-code 1 --python tools/tests/blender/test_rizomuv_bridge.py
Builds its fixtures in a temp folder, prints PASS <case> / FAIL <case>: <why>, and raises if any case failed.
"""

import json
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

import bmesh
import bpy

sys.dont_write_bytecode = True                  # never leave a __pycache__ in the skill
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "skills" / "rizomuv-uv-pipeline" / "scripts"))
sys.path.insert(0, str(ROOT / "tools" / "tests"))
import blender_rizom as br  # noqa: E402
import uv_metrics as um  # noqa: E402
from rizomuv_fake_link import FakeSession  # noqa: E402

br.RizomSession = FakeSession                   # unwrap_objects gets the fake instead of a RizomUV instance
TMP = Path(tempfile.mkdtemp(prefix="rizomuv_bridge_test_"))
RESULTS = []


def case(fn):
    FakeSession.link_kwargs = {}
    try:
        fn()
        RESULTS.append(("PASS", fn.__name__, ""))
        print("PASS", fn.__name__)
    except Exception as exc:  # noqa: BLE001 - every failure is reported, then the run fails
        RESULTS.append(("FAIL", fn.__name__, str(exc)))
        print("FAIL %s: %s" % (fn.__name__, exc))
        traceback.print_exc()


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def cube(name, loc=(0, 0, 0), size=1.0):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=size)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    bpy.context.scene.collection.objects.link(ob)
    return ob


def layers(ob):
    return [l.name for l in ob.data.uv_layers]


def EVERY_LIGHTMAP_PACK(params):
    return params["PaddingSizePx"] != 16                       # every pack but UV0's (16 px gaps at 1024)


def uv_bytes(ob, name):
    import numpy as np
    a = np.empty(2 * len(ob.data.loops), dtype=np.float32)
    ob.data.uv_layers[name].uv.foreach_get("vector", a)
    return a.tobytes()


def test_seams_split_the_seed_topology():
    ob = cube("SEAMS")
    plain = br.mesh_arrays(ob)
    check(len(set(plain["uvw_ids"])) == 8, "a closed cube without seams has 8 seed UV vertices")
    for e in ob.data.edges[:4]:
        e.use_seam = True
    cut = br.mesh_arrays(ob)
    check(len(set(cut["uvw_ids"])) > 8, "seams must split UV vertices (%d)" % len(set(cut["uvw_ids"])))
    check(cut["xyz"][:3] == list(ob.matrix_world @ ob.data.vertices[0].co), "world-space positions")


def test_layers_and_strict_report():
    ob = cube("ORDER", loc=(3, 0, 0))
    report = TMP / "report.json"
    reps = br.unwrap_objects([ob], kind="hard", report_path=str(report))
    check(layers(ob)[:2] == ["UVMap", "UVMap_Lightmap"], "layers %s" % layers(ob))
    check(reps[0]["written"] == ["UVMap", "UVMap_Lightmap"], "written %s" % reps[0]["written"])
    check(not reps[0]["failures"], "failures %s" % reps[0]["failures"])
    check(br._line(reps[0]).strip().startswith("OK"), br._line(reps[0]))
    json.loads(report.read_text(encoding="utf-8"), parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))
    l2 = reps[0]["layers"]["UVMap_Lightmap"]
    noted = any("probe-light it if it is a Free prop" in w for w in reps[0]["warnings"])
    check((l2["footprint_px"] < 64) == noted, "a note exactly under 64 px: %s" % l2["footprint_px"])
    check(abs(l2["footprint_px"] - 20 * (6.0 / l2["bbox_share"]) ** 0.5) < 0.02, "footprint at the measured b")
    check(l2["padding_pairs_below_min"] == 0 and l2["margin_ok"], "lightmap gaps at the footprint %s" % l2)


def test_imported_first_layer_is_reused_not_pushed_to_index_1():
    ob = cube("IMPORTED", loc=(6, 0, 0))
    ob.data.uv_layers.new(name="UVChannel_1")
    reps = br.unwrap_objects([ob], kind="hard", uv2=None)
    check(layers(ob) == ["UVMap"], "layers %s" % layers(ob))
    check(any("renamed UVMap" in w for w in reps[0]["warnings"]), reps[0]["warnings"])


def test_second_layer_in_the_lightmap_slot_is_warned():
    ob = cube("TWO", loc=(9, 0, 0))
    ob.data.uv_layers.new(name="Other")
    ob.data.uv_layers.new(name="UVMap")
    reps = br.unwrap_objects([ob], kind="hard", uv2=None)
    check(layers(ob) == ["UVMap", "Other"], "layers %s" % layers(ob))
    check(any("index 1 holds 'Other'" in w for w in reps[0]["warnings"]), reps[0]["warnings"])


def test_apply_modifiers_on_linked_duplicates_unwraps_each():
    a = cube("DUP_A", loc=(0, 3, 0))
    b = bpy.data.objects.new("DUP_B", a.data)
    bpy.context.scene.collection.objects.link(b)
    for o in (a, b):
        o.modifiers.new("mirror", "MIRROR")
    reps = br.unwrap_objects([a, b], kind="hard", modifiers="apply")
    check(all("shared_mesh_of" not in r and "error" not in r for r in reps), [br._line(r) for r in reps])
    check(a.data != b.data and not a.modifiers and not b.modifiers, "each copy has its own mesh, modifiers applied")
    check("UVMap" in layers(b), "the second copy got UVs")


def test_plain_linked_duplicates_share():
    a = cube("SHARE_A", loc=(0, 6, 0))
    b = bpy.data.objects.new("SHARE_B", a.data)
    b.location = (2, 6, 0)
    bpy.context.scene.collection.objects.link(b)
    reps = br.unwrap_objects([a, b], kind="hard")
    check(reps[1].get("shared_mesh_of") == "SHARE_A", br._line(reps[1]))
    check(reps[0]["shared_by"] == ["SHARE_A", "SHARE_B"], reps[0].get("shared_by"))


def test_failed_stretch_map_is_a_warning_not_a_failure():
    FakeSession.link_kwargs = {"fail_raster": True}
    ob = cube("STRETCH", loc=(0, 9, 0))
    reps = br.unwrap_objects([ob], kind="hard", stretch_dir=str(TMP / "stretch"))
    check("error" not in reps[0], br._line(reps[0]))
    check(any(w.startswith("stretch map not written") for w in reps[0]["warnings"]), reps[0]["warnings"])
    check(reps[0]["written"] == ["UVMap", "UVMap_Lightmap"], reps[0]["written"])


def test_failure_after_the_write_says_what_was_written():
    a = cube("LATE_A", loc=(0, 12, 0))
    b = bpy.data.objects.new("LATE_B", a.data)                 # a second user: the density check runs after the write
    bpy.context.scene.collection.objects.link(b)
    keep = br.mesh_arrays

    def late(ob, *args, **kw):
        if ob.name == "LATE_B":
            raise RuntimeError("late failure")
        return keep(ob, *args, **kw)
    br.mesh_arrays = late
    try:
        reps = br.unwrap_objects([a], kind="hard")
    finally:
        br.mesh_arrays = keep
    check("late failure" in reps[0].get("error", ""), reps[0])
    check(reps[0]["written"] == ["UVMap", "UVMap_Lightmap"], reps[0])
    check("layers written: UVMap, UVMap_Lightmap" in br._line(reps[0]), br._line(reps[0]))


def test_distortion_prints_review_with_the_failure():
    FakeSession.link_kwargs = {"stretch": lambda auto: 1.5}
    ob = cube("STRETCHED", loc=(0, 15, 0))
    reps = br.unwrap_objects([ob], kind="hard", uv2=None)
    line = br._line(reps[0])
    check(line.strip().startswith("REVIEW") and "angular_p95" in line, line)
    check(len(reps[0]["attempts"]) == 3, "the whole ladder was tried: %s" % reps[0]["attempts"])


def test_partial_gate_keeps_the_other_checks():
    FakeSession.link_kwargs = {"stretch": lambda auto: 1.3}
    ob = cube("GATE", loc=(0, 18, 0))
    reps = br.unwrap_objects([ob], kind="hard", uv2=None, gate={"angular_p95": 1.4})
    check(not reps[0]["failures"], reps[0]["failures"])
    reps = br.unwrap_objects([ob], kind="hard", uv2=None, gate={"angular_p95": 1.4, "angular_max": 1.2})
    check(any(f.startswith("angular_max") for f in reps[0]["failures"]), reps[0]["failures"])


def test_checker_preview_leaves_the_mesh_alone():
    ob = cube("CHECKER", loc=(0, 21, 0))
    mat = bpy.data.materials.new("Paint")
    ob.data.materials.append(mat)
    br.checker_preview(ob)
    check(ob.material_slots[0].link == "OBJECT" and ob.material_slots[0].material.name == "RIZOM_UVGrid",
          "the slot shows the checker")
    check(list(ob.data.materials) == [mat], "the mesh keeps its own materials")
    br.checker_clear(ob)
    check(ob.material_slots[0].link == "DATA" and ob.material_slots[0].material == mat, "restored")
    bare = cube("CHECKER_BARE", loc=(3, 21, 0))
    br.checker_preview(bare)
    check(bare.material_slots[0].material.name == "RIZOM_UVGrid", "a mesh with no slot shows the checker")
    br.checker_clear(bare)
    check(len(bare.data.materials) == 0 and "rizom_checker" not in bare, "the added slot is removed")


def test_linked_mesh_is_refused():
    lib = TMP / "lib_kit.blend"
    src = cube("KIT_Linked", loc=(0, 24, 0))
    bpy.data.libraries.write(str(lib), {src})
    bpy.data.objects.remove(src)
    with bpy.data.libraries.load(str(lib), link=True) as (_, dst):
        dst.objects = ["KIT_Linked"]
    linked = dst.objects[0]
    bpy.context.scene.collection.objects.link(linked)
    check(linked.library is not None and linked.data.library is not None, "the fixture is linked")
    reps = br.unwrap_objects([linked], kind="hard")
    check("KIT file" in reps[0].get("error", "") and reps[0]["written"] == [], reps[0])
    check(layers(linked) == [], "no layers on the linked mesh: %s" % layers(linked))


def test_per_object_directional_and_lightmap_scale():
    ob = cube("PROPS", loc=(0, 27, 0))
    ob["rizom_directional"] = "upright"
    ob["rizom_lightmap_scale"] = 0.5
    reps = br.unwrap_objects([ob], kind="hard", lightmap_texels_per_m=20)
    link = FakeSession.instances[-1].link
    check(link.packs[0]["Rotate"] == {"Step": 0.0, "Initial": "Z|+V|X|+U"}, link.packs[0]["Rotate"])
    l2 = reps[0]["layers"]["UVMap_Lightmap"]
    want = 20 * (6.0 / l2["bbox_share"]) ** 0.5 * 0.5
    check(abs(l2["footprint_px"] - want) < 0.02, "footprint %s, want %.2f" % (l2["footprint_px"], want))
    check(reps[0]["directional"] == "upright", reps[0]["directional"])


def test_shared_mesh_lightmap_is_packed_for_the_smallest_renderer():
    a = cube("LM_FULL", loc=(0, 30, 0))
    b = bpy.data.objects.new("LM_HALF", a.data)
    b.scale = (0.5, 0.5, 0.5)
    b.location = (3, 30, 0)
    bpy.context.scene.collection.objects.link(b)
    reps = br.unwrap_objects([a, b], kind="hard", lightmap_texels_per_m=20)
    l2 = reps[0]["layers"]["UVMap_Lightmap"]
    check(set(l2["footprints_px"]) == {"LM_FULL", "LM_HALF"}, l2.get("footprints_px"))
    check(l2["graded_at_px"] == l2["footprints_px"]["LM_HALF"] and not l2["failures"], l2)
    check(reps[1].get("shared_mesh_of") == "LM_FULL", br._line(reps[1]))


def test_low_coverage_takes_the_organic_preset():
    FakeSession.link_kwargs = {"coverage": lambda auto: 1.0 if "QuasiDevelopable" in auto else 0.3}
    ob = cube("SPRAWL", loc=(0, 33, 0))
    reps = br.unwrap_objects([ob], kind="hard", uv2=None)
    check(reps[0]["attempt"] == "organic preset" and not reps[0]["failures"], br._line(reps[0]))
    check(reps[0]["attempts"][0]["gate_failures"][0].startswith("coverage"), reps[0]["attempts"][0])


def test_bad_arguments_fail_before_rizomuv_starts():
    ob = cube("ARGS", loc=(0, 36, 0))
    before = len(FakeSession.instances)
    for kw, exc in (({"gate": 1.3}, TypeError), ({"gate": {"angular_p59": 1.2}}, ValueError),
                    ({"report_path": str(TMP / "missing" / "r.json")}, FileNotFoundError)):
        try:
            br.unwrap_objects([ob], **kw)
            raise AssertionError("%s did not raise" % kw)
        except exc:
            pass
    check(len(FakeSession.instances) == before, "no session was started")


def test_failed_restart_reports_every_object():
    objs = [cube("RS_%d" % i, loc=(i * 3, 39, 0)) for i in range(3)]
    keep = br.unwrap_object

    def flaky(link, ob, *a, **kw):
        if ob.name == "RS_1":
            raise FakeSession.CZEx("RizomUV is not responding (fake)")
        return keep(link, ob, *a, **kw)
    br.unwrap_object = flaky
    FakeSession.restart_fails = True
    try:
        reps = br.unwrap_objects(objs, kind="hard", uv2=None)
    finally:
        br.unwrap_object = keep
        FakeSession.restart_fails = False
    check([r["object"] for r in reps] == ["RS_0", "RS_1", "RS_2"], [r["object"] for r in reps])
    check("restart failed" in reps[1]["error"] and "not attempted" in reps[2]["error"], [r.get("error") for r in reps])
    try:
        br.raise_on_failure(reps)
        raise AssertionError("raise_on_failure did not raise")
    except RuntimeError as ex:
        check("RS_1" in str(ex) and "RS_2" in str(ex), str(ex))
    br.raise_on_failure(reps[:1])                                # nothing failed: no exception


def test_one_job_per_blend():
    import subprocess
    path = TMP / "guard.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    ob = cube("GUARD", loc=(0, 42, 0))
    scripts = str(ROOT / "skills" / "rizomuv-uv-pipeline" / "scripts")
    holder = subprocess.Popen(
        [sys.executable, "-B", "-c", "import sys; sys.path.insert(0, %r); import rizom_link as rl; "
         "l = rl.FileLock(%r, 1 << 20); ok = l.acquire(); l.note('Blender PID 99 on another host'); "
         "print('held' if ok else 'busy', flush=True); sys.stdin.read()" % (scripts, str(path) + br.LOCK_SUFFIX)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    try:
        check(holder.stdout.readline().strip() == "held", "the other job holds the lock")
        for call in (lambda: br.unwrap_objects([ob], kind="hard", uv2=None), br.save):
            try:
                call()
                raise AssertionError("worked on a .blend another job holds")
            except RuntimeError as ex:
                check("held by another Blender job" in str(ex) and "PID 99" in str(ex), str(ex))
    finally:
        holder.stdin.close()
        holder.wait(10)
    reps = br.unwrap_objects([ob], kind="hard", uv2=None)      # free again: this Blender takes the lock
    check(reps[0].get("written") == ["UVMap"], br._line(reps[0]))
    check(os.path.exists(str(path) + br.LOCK_SUFFIX), "a lock file next to the .blend")
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5 * 10 ** 9))     # another process saved it meanwhile
    try:
        br.save()
        raise AssertionError("saved over a .blend another process had saved")
    except RuntimeError as ex:
        check("saved by another process" in str(ex), str(ex))
    bpy.ops.wm.save_as_mainfile(filepath=str(TMP / "guard_after.blend"))   # another file: the old lock goes
    check(not os.path.exists(str(path) + br.LOCK_SUFFIX), "the old lock file is removed")


def test_override_mesh_is_refused():
    lib = TMP / "lib_override.blend"
    col = bpy.data.collections.new("KIT_OV")
    src = cube("KIT_Override", loc=(0, 45, 0))
    bpy.context.scene.collection.objects.unlink(src)
    col.objects.link(src)
    bpy.data.libraries.write(str(lib), {col})
    me = src.data
    bpy.data.objects.remove(src)
    bpy.data.meshes.remove(me)
    bpy.data.collections.remove(col)
    with bpy.data.libraries.load(str(lib), link=True) as (_, dst):
        dst.collections = ["KIT_OV"]
    bpy.context.scene.collection.children.link(dst.collections[0])
    dst.collections[0].override_hierarchy_create(bpy.context.scene, bpy.context.view_layer, do_fully_editable=True)
    ob = next(o for o in bpy.data.objects if o.override_library and o.name.startswith("KIT_Override"))
    ob.data.override_create(remap_local_usages=True)
    check(ob.data.override_library is not None and ob.data.library is None, "the fixture's mesh is a local override")
    reps = br.unwrap_objects([ob], kind="hard", uv2=None)
    check("library override" in reps[0].get("error", "") and "KIT file" in reps[0]["error"], br._line(reps[0]))
    check(layers(ob) == [], layers(ob))


def test_linked_mesh_with_a_local_name_is_fail_not_shared():
    lib = TMP / "lib_beam.blend"
    src = cube("LIB_Beam")
    me = src.data
    me.name = "Beam"
    bpy.data.libraries.write(str(lib), {src})
    bpy.data.objects.remove(src)
    bpy.data.meshes.remove(me)
    local = cube("KIT_Beam_Local", loc=(0, 48, 0))
    local.data.name = "Beam"
    with bpy.data.libraries.load(str(lib), link=True) as (_, dst):
        dst.objects = ["LIB_Beam"]
    linked = dst.objects[0]
    bpy.context.scene.collection.objects.link(linked)
    check(local.data.name == "Beam" and linked.data.name == "Beam", "two meshes called Beam")
    reps = br.unwrap_objects([local, linked], kind="hard", uv2=None)
    check("error" not in reps[0] and "KIT file" in reps[1].get("error", ""), [br._line(r) for r in reps])


def test_apply_keeps_the_mesh_name():
    ob = cube("KIT_MirrorName", loc=(0, 51, 0))
    ob.modifiers.new("mirror", "MIRROR")
    reps = br.unwrap_objects([ob], kind="hard", uv2=None, modifiers="apply")
    check("error" not in reps[0] and not ob.modifiers, br._line(reps[0]))
    check(ob.data.name == "KIT_MirrorName", "mesh name %s" % ob.data.name)


def test_thin_piece_is_ok_with_a_note():
    ob = cube("KIT_ThinBeam", loc=(0, 54, 0))
    ob.scale = (3.0, 0.12, 0.12)
    bpy.context.view_layer.update()
    reps = br.unwrap_objects([ob], kind="hard", uv2=None)
    line = br._line(reps[0])
    check(line.strip().startswith("OK") and "thin piece" in line, line)
    check(reps[0]["layers"]["UVMap"]["coverage"] < 0.35, reps[0]["layers"]["UVMap"]["coverage"])
    check(any(w.startswith("thin piece") and "trim" in w for w in reps[0]["warnings"]), reps[0]["warnings"])


def test_lightmap_too_small_is_packed_for_64_px():
    ob = cube("KIT_TinyLM", loc=(0, 57, 0), size=0.2)
    ob["rizom_lightmap_scale"] = 0.1                             # 20 x sqrt(0.24) x 0.1 = 1 px for 6 charts
    reps = br.unwrap_objects([ob], kind="hard", lightmap_texels_per_m=20)
    line = br._line(reps[0])
    check(line.strip().startswith("OK") and "UV2 packed for 64 px: too small" in line, line)
    check(layers(ob) == ["UVMap", "UVMap_Lightmap"], layers(ob))          # every render mesh keeps a UV2
    l2 = reps[0]["layers"]["UVMap_Lightmap"]
    check("probe-light it (a Free prop" in l2["fallback"] and l2["graded_at_px"] >= 64, l2)
    br.raise_on_failure(reps, review=True)                       # a note, not a review


def test_old_lightmap_is_replaced_by_the_64_px_fallback():
    ob = cube("KIT_RepackLM", loc=(0, 69, 0))
    br.unwrap_objects([ob], kind="hard", lightmap_texels_per_m=20)
    before = uv_bytes(ob, "UVMap_Lightmap")
    ob["rizom_lightmap_scale"] = 0.02
    reps = br.unwrap_objects([ob], kind="hard", lightmap_texels_per_m=20)
    check(layers(ob) == ["UVMap", "UVMap_Lightmap"] and uv_bytes(ob, "UVMap_Lightmap") != before, layers(ob))
    check("UV2 packed for 64 px" in br._line(reps[0]), br._line(reps[0]))


def test_old_lightmap_is_removed_when_the_new_one_fails():
    ob = cube("KIT_StaleLM", loc=(0, 72, 0))
    br.unwrap_objects([ob], kind="hard", lightmap_texels_per_m=40)           # 98 px: a clean UV2
    check(layers(ob) == ["UVMap", "UVMap_Lightmap"], layers(ob))
    FakeSession.link_kwargs = {"overlap": EVERY_LIGHTMAP_PACK}                 # nothing passes up to 4096 px
    reps = br.unwrap_objects([ob], kind="hard", lightmap_texels_per_m=40)
    line = br._line(reps[0])
    check(line.strip().startswith("REVIEW") and "old UV2 removed" in line, line)
    check(layers(ob) == ["UVMap"] and reps[0]["removed"] == ["UVMap_Lightmap"], (layers(ob), reps[0]["removed"]))


def test_timeout_then_a_refusal_reports_the_refusal():
    slow = cube("TO_SLOW", loc=(0, 75, 0))
    mirrored = cube("TO_MIRROR", loc=(3, 75, 0))
    mirrored.modifiers.new("mirror", "MIRROR")
    plain = cube("TO_PLAIN", loc=(6, 75, 0))
    keep = br.unwrap_object

    def hang(link, ob, *a, **kw):
        if ob.name == "TO_SLOW":
            link.session.timed_out = True                       # what the deadline helper leaves behind
            raise FakeSession.CZEx("RizomUV is not responding (fake)")
        return keep(link, ob, *a, **kw)
    br.unwrap_object = hang
    try:
        reps = br.unwrap_objects([slow, mirrored, plain], kind="hard", uv2=None)
    finally:
        br.unwrap_object = keep
    s = FakeSession.instances[-1]
    check("timed out" in reps[0]["error"], reps[0])
    check("has modifiers" in reps[1].get("error", "") and "timed out" not in reps[1]["error"], reps[1])
    check("error" not in reps[2], br._line(reps[2]))
    check(s.started == 2, "one restart, for the timeout only: %d starts" % s.started)


def test_lod1_gets_half_the_lightmap_footprint():
    a = cube("KIT_LodPiece_LOD0", loc=(0, 78, 0))
    b = cube("KIT_LodPiece_LOD1", loc=(3, 78, 0))
    reps = br.unwrap_objects([a, b], kind="hard", lightmap_texels_per_m=40)
    l0, l1 = (r["layers"]["UVMap_Lightmap"] for r in reps)
    k0 = l0["footprints_px"]["KIT_LodPiece_LOD0"] * l0["bbox_share"] ** 0.5     # texels_per_m x sqrt(A) x scale
    k1 = l1["footprints_px"]["KIT_LodPiece_LOD1"] * l1["bbox_share"] ** 0.5
    check(abs(k1 / k0 - 0.5) < 0.01, "LOD1 / LOD0 footprint %.3f" % (k1 / k0))
    check(l1["pack"]["pad_px"] / l1["pack"]["map_px"] > l0["pack"]["pad_px"] / l0["pack"]["map_px"], (l0, l1))


def test_revert_after_another_jobs_save_keeps_its_work():
    path = TMP / "s6.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    marker = bpy.data.objects.new("FROM_BATCH", None)
    bpy.context.scene.collection.objects.link(marker)
    other = TMP / "s6_other.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(other), copy=True)      # what another job saved
    bpy.data.objects.remove(marker)
    shutil.copy(str(other), str(path))
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5 * 10 ** 9))
    try:
        br.save()
        raise AssertionError("saved over another job's save")
    except RuntimeError as ex:
        check("saved by another process" in str(ex), str(ex))
    bpy.ops.wm.revert_mainfile()                                     # the documented remedy
    check("FROM_BATCH" in bpy.data.objects, "the revert loaded the other job's object")
    br.save()                                                        # the file time was read again at the load
    bpy.ops.wm.save_as_mainfile(filepath=str(TMP / "s6_after.blend"))


def test_failed_lightmap_layout_is_not_written():
    FakeSession.link_kwargs = {"overlap": EVERY_LIGHTMAP_PACK}
    ob = cube("KIT_BadLM", loc=(0, 60, 0))
    reps = br.unwrap_objects([ob], kind="hard", lightmap_texels_per_m=20)
    line = br._line(reps[0])
    check(line.strip().startswith("REVIEW") and "UVMap_Lightmap: overlap" in line, line)
    check(any(w.startswith("lightmap footprint") for w in reps[0]["warnings"]) and "px under 64" in line,
          "the under-64 note also when no UV2 is written: " + line)
    check(layers(ob) == ["UVMap"], layers(ob))
    check(any(w.startswith("UVMap_Lightmap not written: it failed its layout") for w in reps[0]["warnings"]),
          reps[0]["warnings"])


def test_a_failing_fallback_climbs_to_a_larger_footprint():
    FakeSession.link_kwargs = {"overlap": lambda params: params["MapResolution"] == 128}      # 64 and 128 px fail
    ob = cube("KIT_ClimbLM", loc=(0, 63, 0))
    reps = br.unwrap_objects([ob], kind="hard", lightmap_texels_per_m=20)
    line = br._line(reps[0])
    check(line.strip().startswith("OK") and "UV2 packed for 256 px: too small" in line, line)
    check(layers(ob) == ["UVMap", "UVMap_Lightmap"], layers(ob))
    check("probe-lit only, or raise its Scale In Lightmap" in reps[0]["layers"]["UVMap_Lightmap"]["fallback"], reps[0])


FBX = dict(object_types={"MESH"}, use_custom_props=False, global_scale=1.0, apply_unit_scale=True,
           apply_scale_options="FBX_SCALE_ALL", axis_forward="-Z", axis_up="Y", use_space_transform=True,
           bake_space_transform=True, mesh_smooth_type="FACE", use_mesh_modifiers=True, use_subsurf=False,
           use_mesh_edges=False, use_triangles=True, use_tspace=False, colors_type="NONE", add_leaf_bones=False,
           bake_anim=False, embed_textures=False, path_mode="STRIP")         # blender-to-unity's kit export


def hard_surface_panel(name, route, loc, x0=0.0):
    """A 1 x 0.08 x 2 m panel as uv-unwrapping's apply_stack leaves it: Bevel applied (route A: Harden Normals;
    route B: Face Strength, then a Weighted Normal), Triangulate (Keep Normals) off in the viewport."""
    import math
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(1.0, 0.08, 2.0), verts=bm.verts)
    bmesh.ops.translate(bm, vec=(x0, 0, 0), verts=bm.verts)
    for f in bm.faces:
        f.smooth = True
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    bpy.context.scene.collection.objects.link(ob)
    bev = ob.modifiers.new("Bevel", "BEVEL")
    bev.limit_method, bev.width, bev.segments = "ANGLE", 0.01, 2
    bev.angle_limit = math.radians(30)
    if route == "A":
        bev.harden_normals = True
    else:
        bev.face_strength_mode = "FSTR_AFFECTED"
    tri = ob.modifiers.new("Triangulate", "TRIANGULATE")
    tri.min_vertices, tri.keep_custom_normals = 4, True
    if route == "B":
        wn = ob.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")
        wn.mode, wn.keep_sharp, wn.use_face_influence = "FACE_AREA", True, True
    with bpy.context.temp_override(object=ob, active_object=ob, selected_objects=[ob],
                                   selected_editable_objects=[ob]):
        bpy.ops.object.modifier_apply(modifier="Bevel")
    tri.show_viewport = False
    return ob


def twin(ob, name):
    c = ob.copy()
    c.data = ob.data.copy()
    c.name = name
    bpy.context.scene.collection.objects.link(c)
    return c


def fbx_normals(ob):
    """Corner (position, normal) pairs of ob after the kit FBX export and a re-import, its Triangulate back on."""
    for m in ob.modifiers:
        if m.type == "TRIANGULATE":
            m.show_viewport = True
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    path = str(TMP / (ob.name + ".fbx"))
    bpy.ops.export_scene.fbx(filepath=path, use_selection=True, **FBX)
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=path)
    imp = [o for o in bpy.data.objects if o not in before and o.type == "MESH"][0]
    me = imp.data
    res = [(me.vertices[lp.vertex_index].co.copy(), me.corner_normals[i].vector.copy())
           for i, lp in enumerate(me.loops)]
    bpy.data.objects.remove(imp)
    return res


def worst_angle(a, b):
    import math
    from mathutils.kdtree import KDTree
    kd = KDTree(len(b))
    for i, (co, _) in enumerate(b):
        kd.insert(co, i)
    kd.balance()
    worst = 0.0
    for co, n in a:
        near = kd.find_range(co, 1e-4)
        if not near:
            return float("inf")
        worst = max(worst, min(math.degrees(n.angle(b[i][1], 0.0)) for _, i, _ in near))
    return worst


def test_hard_surface_after_apply_stack_keeps_its_normals():
    for k, route in enumerate(("A", "B")):
        base = hard_surface_panel("HS_%s" % route, route, loc=(0, 84 + 3 * k, 0))
        mods = [(m.type, m.show_viewport) for m in base.modifiers]
        ref = fbx_normals(twin(base, "HS_%s_ref" % route))
        for mode in ("refuse", "ignore", "apply"):
            ob = twin(base, "HS_%s_%s" % (route, mode))
            reps = br.unwrap_objects([ob], kind="hard", uv2=None, modifiers=mode)
            check("error" not in reps[0], "route %s %s refused: %s" % (route, mode, br._line(reps[0])))
            check([(m.type, m.show_viewport) for m in ob.modifiers] == mods,
                  "route %s %s left %s" % (route, mode, [(m.type, m.show_viewport) for m in ob.modifiers]))
            ang = worst_angle(fbx_normals(ob), ref)
            check(ang < 0.01, "route %s modifiers=%r: exported normals %.2f deg off the live stack"
                  % (route, mode, ang))


def test_apply_bakes_only_the_modifiers_that_count():
    ob = hard_surface_panel("HS_Mirror", "B", loc=(0, 90, 0), x0=1.0)
    m = ob.modifiers.new("Mirror", "MIRROR")
    with bpy.context.temp_override(object=ob, active_object=ob):
        bpy.ops.object.modifier_move_to_index(modifier=m.name, index=0)
    ref = fbx_normals(twin(ob, "HS_Mirror_ref"))
    ob.modifiers["Triangulate"].show_viewport = False
    try:
        br.check_object(ob)
        raise AssertionError("a live Mirror was not refused")
    except ValueError as ex:
        check("After uv-unwrapping's apply_stack" in str(ex) and "never 'apply' on a hard-surface piece" in str(ex),
              str(ex))
    reps = br.unwrap_objects([ob], kind="hard", uv2=None, modifiers="apply")
    check("error" not in reps[0], br._line(reps[0]))
    left = [(x.type, x.show_viewport) for x in ob.modifiers]
    check(left == [("TRIANGULATE", False), ("WEIGHTED_NORMAL", True)], "only the Mirror is baked: %s" % left)
    ang = worst_angle(fbx_normals(ob), ref)
    check(ang < 0.01, "exported normals %.2f deg off the live stack" % ang)


def test_save_writes_no_backup():
    path = TMP / "scene.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    br.save()
    br.save()
    check(path.is_file() and not (TMP / "scene.blend1").exists(), "no .blend1 next to %s" % path)


for fn in (test_seams_split_the_seed_topology, test_layers_and_strict_report,
           test_imported_first_layer_is_reused_not_pushed_to_index_1, test_second_layer_in_the_lightmap_slot_is_warned,
           test_apply_modifiers_on_linked_duplicates_unwraps_each, test_plain_linked_duplicates_share,
           test_failed_stretch_map_is_a_warning_not_a_failure, test_failure_after_the_write_says_what_was_written,
           test_distortion_prints_review_with_the_failure, test_partial_gate_keeps_the_other_checks,
           test_checker_preview_leaves_the_mesh_alone, test_linked_mesh_is_refused,
           test_per_object_directional_and_lightmap_scale,
           test_shared_mesh_lightmap_is_packed_for_the_smallest_renderer,
           test_low_coverage_takes_the_organic_preset, test_bad_arguments_fail_before_rizomuv_starts,
           test_failed_restart_reports_every_object, test_one_job_per_blend, test_override_mesh_is_refused,
           test_linked_mesh_with_a_local_name_is_fail_not_shared, test_apply_keeps_the_mesh_name,
           test_thin_piece_is_ok_with_a_note, test_lightmap_too_small_is_packed_for_64_px,
           test_failed_lightmap_layout_is_not_written, test_old_lightmap_is_replaced_by_the_64_px_fallback,
           test_old_lightmap_is_removed_when_the_new_one_fails, test_timeout_then_a_refusal_reports_the_refusal,
           test_lod1_gets_half_the_lightmap_footprint, test_revert_after_another_jobs_save_keeps_its_work,
           test_a_failing_fallback_climbs_to_a_larger_footprint, test_hard_surface_after_apply_stack_keeps_its_normals,
           test_apply_bakes_only_the_modifiers_that_count, test_save_writes_no_backup):
    case(fn)

bpy.ops.wm.read_factory_settings(use_empty=True)          # let go of scene.blend before removing the folder
br._drop_locks()                                          # and of the .blend lock files
shutil.rmtree(TMP, ignore_errors=True)
failed = [r for r in RESULTS if r[0] == "FAIL"]
print("%d case(s), %d failed" % (len(RESULTS), len(failed)))
if failed:
    raise SystemExit("FAILED: " + ", ".join(r[1] for r in failed))
