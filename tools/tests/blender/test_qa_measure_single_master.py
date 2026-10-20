"""vrchat-world-qa's qa_measure.py on a single MASTER (blender-kit-library's default layout): local pieces under KIT
and assemblies under ASM are not reported as copies, their kit checks still run, layout problems are reported, each
placement names the assembly holding it, and an --isolate render of an excluded piece shows the piece.

Host: Blender 5.2 (bpy), headless:
    blender -b --factory-startup --python-exit-code 1 --python tools/tests/blender/test_qa_measure_single_master.py
Builds its fixture with blender-kit-library's kit_library.py in a temp folder; prints PASS / FAIL per case and raises
if any case failed.
"""

import shutil
import subprocess
import tempfile
import traceback
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[3]
QA = ROOT / "skills" / "vrchat-world-qa" / "scripts" / "qa_measure.py"
KIT_LIBRARY = ROOT / "skills" / "blender-kit-library" / "scripts" / "kit_library.py"
TMP = Path(tempfile.mkdtemp(prefix="qa_single_test_"))
MASTER = TMP / "blender" / "MASTER.blend"


def load(path):
    ns = {"__file__": str(path)}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), ns)
    return ns


def box(name, size):
    x1, y1, z1 = size
    me = bpy.data.meshes.new(name)
    v = [(0, 0, 0), (x1, 0, 0), (x1, y1, 0), (0, y1, 0), (0, 0, z1), (x1, 0, z1), (x1, y1, z1), (0, y1, z1)]
    me.from_pydata(v, [], [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)])
    me.uv_layers.new(name="UV0")
    me.uv_layers.new(name="UV1")
    return bpy.data.objects.new(name, me)


def build():
    kit = load(KIT_LIBRARY)
    kit["new_master"](str(MASTER))
    wall = kit["new_piece"]("INT_Wall_2x3_A")
    wall.objects.link(box("INT_Wall_2x3_A", (2.0, 0.2, 3.0)))
    wall["kit_status"] = "grey"
    asm = kit["new_piece"]("ASM_Room_A")
    kit["place_piece"]("INT_Wall_2x3_A", into=asm).name = "RoomWall"
    kit["place_piece"]("INT_Wall_2x3_A", location=(4, 0, 0)).name = "LayoutWall"
    kit["place_piece"]("ASM_Room_A", location=(0, 4, 0)).name = "LayoutRoom"
    kit["save_file"]()
    return kit


def test_clean_single_master_has_no_layout_problems():
    build()
    qa = load(QA)
    rep = qa["measure"](module=1.0, role="master")
    assert rep["layout"] == "single", rep["layout"]
    assert [p["piece"] for p in rep["pieces"]] == ["INT_Wall_2x3_A"], rep["pieces"]
    probs = qa["problems"](rep, expect_status="grey")
    assert probs == [], probs
    where = {p["object"]: p["assembly"] for p in rep["placements"]}
    assert where == {"RoomWall": "ASM_Room_A", "LayoutWall": None, "LayoutRoom": None}, where
    assert rep["appended"] == [], rep["appended"]


def test_kit_checks_run_on_master_pieces():
    build()
    bpy.data.objects["INT_Wall_2x3_A"].location.x = 0.5                 # pivot off the corner
    qa = load(QA)
    probs = qa["problems"](qa["measure"](module=1.0, role="master"), expect_status="grey")
    assert any("INT_Wall_2x3_A" in p for p in probs), probs


def test_layout_problems_are_reported():
    kit = build()
    kit["new_piece"]("INT_Wall_2x3_B", parent=bpy.data.collections["MASTER"]).objects.link(
        box("INT_Wall_2x3_B", (2.0, 0.2, 3.0)))
    bpy.context.view_layer.layer_collection.children["KIT"].exclude = False
    qa = load(QA)
    probs = qa["problems"](qa["measure"](module=1.0, role="master"))
    assert any("INT_Wall_2x3_B: piece outside KIT" in p for p in probs), probs
    assert any("KIT is in the view layer" in p for p in probs), probs


def test_isolate_render_shows_an_excluded_piece():
    build()
    png = TMP / "wall.png"
    p = subprocess.run([bpy.app.binary_path, "-b", "--factory-startup", "--python-exit-code", "1", str(MASTER),
                        "--python", str(QA), "--", "--module", "1.0", "--isolate", "INT_Wall_2x3_A", "--render",
                        "front", "--center", "1", "0", "1.5", "--extent", "3", "4", "--px-per-m", "20", "--png",
                        str(png)], capture_output=True, text=True, timeout=300)
    assert png.exists(), p.stdout + p.stderr
    img = bpy.data.images.load(str(png))
    px = list(img.pixels)
    centre = (img.size[1] // 2 * img.size[0] + img.size[0] // 2) * 4
    corner = 0
    assert px[centre:centre + 3] != px[corner:corner + 3], "the isolated piece did not render (still excluded?)"
    bpy.ops.wm.open_mainfile(filepath=str(MASTER))
    assert bpy.context.view_layer.layer_collection.children["KIT"].exclude, "the render left KIT included"


CASES = [test_clean_single_master_has_no_layout_problems, test_kit_checks_run_on_master_pieces,
         test_layout_problems_are_reported, test_isolate_render_shows_an_excluded_piece]


def main():
    failed = []
    for fn in CASES:
        try:
            fn()
            print("PASS %s" % fn.__name__)
        except Exception as e:
            failed.append(fn.__name__)
            print("FAIL %s: %s" % (fn.__name__, e))
            traceback.print_exc()
    shutil.rmtree(TMP, ignore_errors=True)
    print("%d case(s), %d failed" % (len(CASES), len(failed)))
    if failed:
        raise RuntimeError("failed: " + ", ".join(failed))


main()
