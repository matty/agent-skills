"""Plain-Python tests of local-3d-generation's UI-to-API workflow conversion (scripts/comfy.py), against a
hand-written object_info, so no ComfyUI server is needed.

Covers widget order from object_info, the frontend-only control_after_generate and upload values, dynamic combos
(dotted child keys), defaults for inputs a template predates, subgraph flattening ('outer:inner' ids, inputs fed
from outside, outputs to outside), Reroute, legacy PrimitiveNode, muted and bypassed nodes, notes, and --set
target lookup by id, class or title. collect() runs against a fake server: text outputs (GetMeshInfo) are reported
and never fetched as files (the 2026-11-02 dry run crashed with a 404 doing that), temp previews are skipped, a
3D file in a subfolder is fetched, a failed fetch is an error rather than a crash, and seconds come from the
execution timestamps.

Host: plain Python 3.10+, standard library. Run from the repo root:
    python -B -m unittest discover -s tools/tests -p "test_local_3d_generation_*.py"
"""

import importlib.util
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "local-3d-generation" / "scripts" / "comfy.py"

spec = importlib.util.spec_from_file_location("comfy_l3d", SCRIPT)
comfy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comfy)


INFO = {
    "Loader": {"input": {"required": {"name": ["COMBO", {"options": ["a.safetensors"]}]}},
               "output": ["MODEL"]},
    "Sampler": {"input": {"required": {
        "model": ["MODEL", {}],
        "seed": ["INT", {"default": 0, "control_after_generate": True}],
        "steps": ["INT", {"default": 20}],
        "cfg": ["FLOAT", {"default": 7.0}],
    }, "optional": {"shift": ["FLOAT", {"default": 3.0}]}},
        "input_order": {"required": ["model", "seed", "steps", "cfg"], "optional": ["shift"]},
        "output": ["LATENT"]},
    "LoadImage": {"input": {"required": {"image": ["COMBO", {"image_upload": True}]}},
                  "output": ["IMAGE", "MASK"]},
    "Remesh": {"input": {"required": {
        "mesh": ["MESH", {}],
        "resolution": ["INT", {"default": 512}],
        "mode": ["COMFY_DYNAMICCOMBO_V3", {"options": [
            {"key": "udf", "inputs": {"required": {"qef": ["BOOLEAN", {"default": False}],
                                                   "band": ["FLOAT", {"default": 1.0}]}}},
            {"key": "sdf", "inputs": {"required": {"iso": ["FLOAT", {"default": 0.0}]}}},
        ]}],
        "max_faces": ["INT", {"default": 1000}],
    }}, "output": ["MESH"]},
    "Filter": {"input": {"required": {"latent": ["LATENT", {}]}}, "output": ["LATENT"]},
    "Save": {"input": {"required": {"latent": ["LATENT", {}], "prefix": ["STRING", {"default": "x"}]}},
             "output": [], "output_node": True},
    "IntConst": {"input": {"required": {"value": ["INT", {}]}}, "output": ["INT"]},
    "Crop": {"input": {"required": {"image": ["IMAGE", {}],
                                    "crop_region": ["BOUNDING_BOX", {"default": {"x": 0, "y": 0, "width": 512,
                                                                                 "height": 512},
                                                                     "socketless": True, "component": "ImageCrop"}]}},
             "output": ["IMAGE"]},
}


def node(nid, typ, widgets=None, inputs=(), outputs=(), mode=0, title=None):
    n = {"id": nid, "type": typ, "mode": mode, "widgets_values": widgets if widgets is not None else [],
         "inputs": [dict(i) for i in inputs], "outputs": [dict(o) for o in outputs]}
    if title:
        n["title"] = title
    return n


class ConvertTests(unittest.TestCase):
    def test_widgets_controls_dynamic_combo_and_defaults(self):
        ui = {"nodes": [
            node(1, "Loader", ["a.safetensors"], outputs=[{"type": "MODEL"}]),
            # seed, control value, steps, cfg; shift is newer than the workflow
            node(2, "Sampler", [42, "randomize", 8, 1.0],
                 inputs=[{"name": "model", "type": "MODEL", "link": 1}], outputs=[{"type": "LATENT"}]),
            node(3, "LoadImage", ["cat.png", "image"], outputs=[{"type": "IMAGE"}, {"type": "MASK"}]),
            node(4, "Remesh", [768, "udf", True, 0.5, 70000]),
            node(5, "Save", ["out"], inputs=[{"name": "latent", "type": "LATENT", "link": 2}]),
            node(6, "MarkdownNote", ["hello"]),
        ], "links": [[1, 1, 0, 2, 0, "MODEL"], [2, 2, 0, 5, 0, "LATENT"]]}
        p, warns = comfy.convert(ui, INFO)
        self.assertEqual(p["2"]["inputs"], {"seed": 42, "steps": 8, "cfg": 1.0, "shift": 3.0,
                                            "model": ["1", 0]})
        self.assertEqual(p["3"]["inputs"], {"image": "cat.png"})
        self.assertEqual(p["4"]["inputs"], {"resolution": 768, "mode": "udf", "mode.qef": True,
                                            "mode.band": 0.5, "max_faces": 70000})
        self.assertNotIn("6", p)
        self.assertTrue(any("shift" in w and "default" in w for w in warns), warns)
        self.assertFalse(any("left over" in w for w in warns), warns)

    def test_reroute_primitive_bypass_and_mute(self):
        ui = {"nodes": [
            node(1, "Loader", ["a.safetensors"], outputs=[{"type": "MODEL"}]),
            node(2, "Reroute", inputs=[{"name": "", "type": "*", "link": 1}], outputs=[{"type": "MODEL"}]),
            node(3, "PrimitiveNode", [7], outputs=[{"type": "INT", "widget": {"name": "steps"}}]),
            node(4, "Sampler", [1, "fixed", 20, 2.0, 1.0],
                 inputs=[{"name": "model", "type": "MODEL", "link": 2},
                         {"name": "steps", "type": "INT", "widget": {"name": "steps"}, "link": 3}],
                 outputs=[{"type": "LATENT"}]),
            node(5, "Filter", inputs=[{"name": "latent", "type": "LATENT", "link": 4}],
                 outputs=[{"type": "LATENT"}], mode=4),          # bypassed
            node(6, "Save", ["out"], inputs=[{"name": "latent", "type": "LATENT", "link": 5}]),
            node(7, "Save", ["muted"], mode=2),
        ], "links": [[1, 1, 0, 2, 0, "MODEL"], [2, 2, 0, 4, 0, "MODEL"], [3, 3, 0, 4, 1, "INT"],
                     [4, 4, 0, 5, 0, "LATENT"], [5, 5, 0, 6, 0, "LATENT"]]}
        p, _ = comfy.convert(ui, INFO)
        self.assertEqual(sorted(p), ["1", "4", "6"])
        self.assertEqual(p["4"]["inputs"]["model"], ["1", 0])
        self.assertEqual(p["4"]["inputs"]["steps"], 7)
        self.assertEqual(p["6"]["inputs"]["latent"], ["4", 0])

    def test_subgraph_flattening(self):
        sg = {"id": "sg-1", "name": "inner",
              "inputs": [{"name": "steps", "type": "INT"}, {"name": "seed", "type": "INT"}],
              "outputs": [{"name": "LATENT", "type": "LATENT"}],
              "nodes": [node(10, "Loader", ["a.safetensors"], outputs=[{"type": "MODEL"}]),
                        node(11, "Sampler", [5, "fixed", 20, 1.0, 3.0],
                             inputs=[{"name": "model", "type": "MODEL", "link": 100},
                                     {"name": "steps", "type": "INT", "link": 101},
                                     {"name": "seed", "type": "INT", "link": 102}],
                             outputs=[{"type": "LATENT"}])],
              "links": [{"id": 100, "origin_id": 10, "origin_slot": 0, "target_id": 11, "target_slot": 0},
                        {"id": 101, "origin_id": -10, "origin_slot": 0, "target_id": 11, "target_slot": 1},
                        {"id": 102, "origin_id": -10, "origin_slot": 1, "target_id": 11, "target_slot": 2},
                        {"id": 103, "origin_id": 11, "origin_slot": 0, "target_id": -20, "target_slot": 0}]}
        ui = {"definitions": {"subgraphs": [sg]}, "nodes": [
            node(1, "IntConst", [12], outputs=[{"type": "INT"}]),
            # steps fed from outside; seed is a promoted widget with no link: the inner value stands
            node(57, "sg-1", [], inputs=[{"name": "steps", "type": "INT", "link": 1},
                                         {"name": "seed", "type": "INT", "widget": {"name": "seed"},
                                          "link": None}],
                 outputs=[{"type": "LATENT"}]),
            node(9, "Save", ["out"], inputs=[{"name": "latent", "type": "LATENT", "link": 2}]),
        ], "links": [[1, 1, 0, 57, 0, "INT"], [2, 57, 0, 9, 0, "LATENT"]]}
        p, warns = comfy.convert(ui, INFO)
        self.assertEqual(sorted(p), ["1", "57:10", "57:11", "9"])
        s = p["57:11"]["inputs"]
        self.assertEqual(s["model"], ["57:10", 0])
        self.assertEqual(s["steps"], ["1", 0])
        self.assertEqual(s["seed"], 5)
        self.assertEqual(p["9"]["inputs"]["latent"], ["57:11", 0])
        self.assertFalse(warns, warns)

    def test_custom_widget_type_and_component_extras(self):
        box = {"x": 4728, "y": 0, "width": 1608, "height": 2688}
        ui = {"nodes": [node(1, "Crop", [box, 0, 0, 512, 512])], "links": []}
        p, warns = comfy.convert(ui, INFO)
        self.assertEqual(p["1"]["inputs"], {"crop_region": box})
        self.assertFalse(warns, warns)

    def test_unknown_class_is_reported(self):
        p, warns = comfy.convert({"nodes": [node(1, "NotInstalled", [1])], "links": []}, INFO)
        self.assertEqual(p, {})
        self.assertTrue(any("not on this server" in w for w in warns))


class SetInputTests(unittest.TestCase):
    def test_switching_dynamic_combo_swaps_children(self):
        p = {"4": {"class_type": "Remesh", "inputs": {"resolution": 768, "mode": "udf", "mode.qef": True,
                                                      "mode.band": 0.5, "max_faces": 7}}}
        notes = comfy.set_input(p, "4", "mode", "sdf", INFO)
        self.assertEqual(p["4"]["inputs"], {"resolution": 768, "mode": "sdf", "mode.iso": 0.0, "max_faces": 7})
        self.assertEqual(len(notes), 1)
        comfy.set_input(p, "4", "mode.iso", 0.2, INFO)          # a child set afterwards stands
        self.assertEqual(p["4"]["inputs"]["mode.iso"], 0.2)

    def test_unknown_option_refused(self):
        p = {"4": {"class_type": "Remesh", "inputs": {"mode": "udf"}}}
        with self.assertRaises(SystemExit):
            comfy.set_input(p, "4", "mode", "solid", INFO)

    def test_plain_input(self):
        p = {"2": {"class_type": "Sampler", "inputs": {"seed": 1}}}
        self.assertEqual(comfy.set_input(p, "2", "seed", 9, INFO), [])
        self.assertEqual(p["2"]["inputs"]["seed"], 9)


mspec = importlib.util.spec_from_file_location("multiview_l3d", ROOT / "skills" / "local-3d-generation" / "scripts"
                                               / "multiview.py")
multiview = importlib.util.module_from_spec(mspec)
mspec.loader.exec_module(multiview)


def mv_prompt():
    """The multi-view template's shape: one sheet loader, per view a crop -> background removal -> crop to mask ->
    save, all four into the conditioning node."""
    p = {"364": {"class_type": "LoadImage", "inputs": {"image": "sheet.png"}},
         "193": {"class_type": "LoadBackgroundRemovalModel", "inputs": {}},
         "324": {"class_type": "Pixal3DMultiViewConditioning", "inputs": {"fov": 20}}}
    for i, v in enumerate(multiview.VIEWS):
        crop, rb, ctm, save = (str(1000 + 10 * i + k) for k in range(4))
        p[crop] = {"class_type": "ImageCropV2", "inputs": {"image": ["364", 0], "crop_region": {}}}
        p[rb] = {"class_type": "RemoveBackground", "inputs": {"bg_removal_model": ["193", 0], "image": [crop, 0]}}
        p[ctm] = {"class_type": "ImageCropToMask", "inputs": {"images": [crop, 0], "masks": [rb, 0]}}
        p[save] = {"class_type": "SaveImageAdvanced", "inputs": {"images": [ctm, 0]}}
        p["324"]["inputs"][v] = [save, 0]
    return p


class MultiviewWireTests(unittest.TestCase):
    def test_all_views(self):
        p = multiview.wire(mv_prompt(), {v: f"c_{v}.png" for v in multiview.VIEWS})
        loads = {e["inputs"]["image"] for e in p.values() if e["class_type"] == "LoadImage"}
        self.assertEqual(loads, {f"c_{v}.png" for v in multiview.VIEWS})
        self.assertNotIn("364", p)
        self.assertEqual(sum(1 for e in p.values() if e["class_type"] == "SaveImageAdvanced"), 4)

    def test_subset_prunes_whole_chains(self):
        p = multiview.wire(mv_prompt(), {"front": "f.png", "left": "l.png"})
        self.assertEqual(sorted(k for k in p["324"]["inputs"] if k in multiview.VIEWS), ["front", "left"])
        for e in p.values():                                    # nothing points at a removed node
            for v in e["inputs"].values():
                if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                    self.assertIn(v[0], p)
        self.assertEqual(sum(1 for e in p.values() if e["class_type"] == "RemoveBackground"), 2)

    def test_needs_the_multiview_template(self):
        with self.assertRaises(SystemExit):
            multiview.wire({"1": {"class_type": "KSampler", "inputs": {}}}, {"front": "f.png"})


class FindNodeTests(unittest.TestCase):
    P = {"3": {"class_type": "KSampler", "inputs": {}},
         "4": {"class_type": "KSampler", "inputs": {}},
         "9": {"class_type": "SaveImage", "inputs": {}, "_meta": {"title": "Final"}}}

    def test_by_id_class_title(self):
        self.assertEqual(comfy.find_node(self.P, "4"), "4")
        self.assertEqual(comfy.find_node(self.P, "SaveImage"), "9")
        self.assertEqual(comfy.find_node(self.P, "Final"), "9")

    def test_ambiguous_class_refused(self):
        with self.assertRaises(SystemExit):
            comfy.find_node(self.P, "KSampler")


class CoerceTests(unittest.TestCase):
    def test_values(self):
        self.assertEqual(comfy._coerce("12"), 12)
        self.assertIs(comfy._coerce("true"), True)
        self.assertEqual(comfy._coerce("barrel.png"), "barrel.png")
        self.assertEqual(comfy._coerce("a weathered barrel, three-quarter view"),
                         "a weathered barrel, three-quarter view")


HISTORY = {"p1": {"status": {"status_str": "success", "messages": [
    ["execution_start", {"timestamp": 1000}], ["execution_success", {"timestamp": 693100}]]},
    "outputs": {
        "202": {"text": ["Vertices:   23,521,475 (23.52M)\nFaces:      47,651,718 (47.65M)"]},
        "164": {"images": [{"filename": "ComfyUI_temp_x_00001_.png", "subfolder": "", "type": "temp"}]},
        "322": {"3d": [{"filename": "barrel_00001.glb", "subfolder": "3d", "type": "output"}],
                "camera_info": [None], "model_3d_info": []},
        "9": {"images": [{"filename": "gone.png", "subfolder": "", "type": "output"}]},
    }}}


class FakeComfy(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urlparse(self.path)
        if u.path.startswith("/history/"):
            pid = u.path.rsplit("/", 1)[1]
            body = json.dumps({pid: HISTORY[pid]} if pid in HISTORY else {}).encode()
        elif u.path == "/view":
            q = parse_qs(u.query)
            if q.get("filename") == ["barrel_00001.glb"] and q.get("subfolder") == ["3d"]:
                body = b"glTF-fake"
            else:
                self.send_response(404); self.end_headers(); return
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200); self.end_headers(); self.wfile.write(body)


class CollectTests(unittest.TestCase):
    def test_outputs(self):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeComfy)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as td:
                url = f"http://127.0.0.1:{srv.server_address[1]}"
                s = comfy.collect(url, "p1", Path(td))
                self.assertEqual(s["status"], "success")
                self.assertEqual(s["seconds"], 692.1)
                self.assertEqual([f["node"] for f in s["files"]], ["322"])
                self.assertEqual(Path(s["files"][0]["path"]).read_bytes(), b"glTF-fake")
                self.assertIn("47,651,718", s["text"]["202"])
                self.assertEqual(len(s["errors"]), 1)
                self.assertIn("gone.png", s["errors"][0])
        finally:
            srv.shutdown()


if __name__ == "__main__":
    unittest.main()
