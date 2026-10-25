"""Plain-Python tests for the pbr-texture-sources skill's scripts/pbr_fetch.py, offline: reference and resolution
parsing, Poly Haven search ranking, map planning and name normalisation for both sources, the ambientCG zip
extraction (renaming, map selection, bundle mode, unsafe member names), the MD5 and size guards and source.json,
with the network replaced by fakes. Set PBR_FETCH_LIVE=1 to also run one live search against both APIs.

Host: plain Python 3.9+, standard library. Run from the repo root:
    python -B -m unittest discover -s tools/tests -p "test_pbr_texture_sources_*.py"
"""

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "pbr-texture-sources" / "scripts" / "pbr_fetch.py"


def load():
    keep = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("pbr_fetch_under_test", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.dont_write_bytecode = keep


M = load()

PH_ASSETS = {
    "red_brick_03": {"type": 1, "name": "Red Brick 03", "tags": ["red", "industrial"], "categories": ["brick", "wall"],
                     "description": "Free red brick wall.", "download_count": 100, "dimensions": [1000, 1000],
                     "max_resolution": [8192, 8192]},
    "brick_4": {"type": 1, "name": "Brick 4", "tags": ["moss"], "categories": ["brick"], "description": "red bricks",
                "download_count": 900, "dimensions": [500, 500], "max_resolution": [8192, 8192]},
    "oak_floor": {"type": 1, "name": "Oak Floor", "tags": ["wood"], "categories": ["floor"],
                  "description": "a textile-like weave", "download_count": 5000, "dimensions": [2000, 2000],
                  "max_resolution": [4096, 4096]},
}


def ph_entry(name, res, fmt, data):
    return {"url": "https://dl.example/%s_%s.%s" % (name, res, fmt), "md5": hashlib.md5(data).hexdigest(),
            "size": len(data)}


def ph_files(data=b"pixels"):
    files = {}
    for key in ("Diffuse", "nor_gl", "nor_dx", "Rough", "AO", "Displacement", "arm", "spec_ior"):
        files[key] = {r: {f: ph_entry(key, r, f, data) for f in ("jpg", "png")} for r in ("1k", "2k", "4k")}
    files["Displacement"]["2k"]["exr"] = ph_entry("Displacement", "2k", "exr", data)
    files["gltf"] = {"1k": {"gltf": dict(ph_entry("gltf", "1k", "gltf", data), include={
        "textures/a_diff_1k.jpg": ph_entry("a_diff", "1k", "jpg", data)})}}
    return files


def make_acg_zip(path, asset_id, attr, suffixes, extra=()):
    with zipfile.ZipFile(path, "w") as z:
        for s in suffixes:
            z.writestr("%s_%s_%s.jpg" % (asset_id, attr, s), b"img-" + s.encode())
        for name in extra:
            z.writestr(name, b"x")


class Parsing(unittest.TestCase):
    def test_refs(self):
        self.assertEqual(M.parse_ref("polyhaven:red_brick_03"), ("polyhaven", "red_brick_03"))
        self.assertEqual(M.parse_ref("AmbientCG:Bricks076C"), ("ambientcg", "Bricks076C"))
        for bad in ("red_brick_03", "texturecan:x", "polyhaven:../x", "polyhaven:"):
            with self.assertRaises(M.FetchError):
                M.parse_ref(bad)

    def test_resolutions(self):
        self.assertEqual(M.res_key("2K"), "2k")
        self.assertEqual(M.res_key("4096"), "4k")
        self.assertEqual(M.pick_res(["1k", "2k", "8k"], "4k"), "2k")
        self.assertEqual(M.pick_res(["4k", "8k"], "1k"), "4k")
        with self.assertRaises(M.FetchError):
            M.res_key("huge")


class PolyHavenSearch(unittest.TestCase):
    def test_and_and_rank(self):
        hits = M.match_polyhaven(["red", "brick"], PH_ASSETS, 10)
        self.assertEqual([h["id"] for h in hits], ["red_brick_03", "brick_4"])   # name/tag beats description
        self.assertEqual(hits[0]["ref"], "polyhaven:red_brick_03")
        self.assertEqual(hits[0]["size_m"], [1.0, 1.0])                         # millimetres -> metres
        self.assertEqual(hits[0]["max_res"], "8k")

    def test_prefix_not_substring_and_plural(self):
        self.assertEqual(M.match_polyhaven(["tile"], PH_ASSETS, 10), [])        # 'textile' is not 'tile'
        self.assertEqual([h["id"] for h in M.match_polyhaven(["floors"], PH_ASSETS, 10)], ["oak_floor"])

    def test_limit(self):
        self.assertEqual(len(M.match_polyhaven(["brick"], PH_ASSETS, 1)), 1)


class Planning(unittest.TestCase):
    def test_polyhaven_core(self):
        plan, notes = M.plan_polyhaven(ph_files(), "2k", "jpg")
        names = sorted(p["name"] for p in plan)
        self.assertEqual(names, ["AO", "BaseColor", "Height", "NormalGL", "Roughness"])
        self.assertEqual(notes, [])
        self.assertTrue(all(p["res"] == "2k" and p["fmt"] == "jpg" for p in plan))

    def test_polyhaven_all_both_and_fallbacks(self):
        plan, notes = M.plan_polyhaven(ph_files(), "8k", "exr", maps="all", normal="both")
        names = {p["name"] for p in plan}
        self.assertTrue({"NormalGL", "NormalDX", "ARM", "SpecIor"} <= names)
        self.assertNotIn("Gltf", names)                                          # bundles are not maps
        height = next(p for p in plan if p["name"] == "Height")
        self.assertEqual((height["res"], height["fmt"]), ("4k", "png"))          # no 8k, no 4k exr
        self.assertTrue(any("8k not offered" in n for n in notes))

    def test_polyhaven_named_maps_and_missing(self):
        files = ph_files()
        del files["AO"]
        plan, notes = M.plan_polyhaven(files, "1k", "jpg", maps="BaseColor,Normal,AO", normal="dx")
        self.assertEqual(sorted(p["name"] for p in plan), ["BaseColor", "NormalDX"])
        self.assertEqual(notes, ["AO: not offered for this asset"])

    def test_polyhaven_bundle(self):
        r, items = M.plan_polyhaven_bundle(ph_files(), "gltf", "4k")
        self.assertEqual(r, "1k")
        self.assertEqual([i[0] for i in items], ["gltf_1k.gltf", "textures/a_diff_1k.jpg"])
        with self.assertRaises(M.FetchError):
            M.plan_polyhaven_bundle(ph_files(), "blend", "1k")

    def test_ambientcg(self):
        asset = {"id": "X", "downloads": [
            {"attributes": a, "extension": "zip", "url": "u/" + a, "size": 1}
            for a in ("1K-JPG", "2K-JPG", "8K-JPG", "1K-PNG", "2K-PNG")]}
        d, r, f, notes = M.plan_ambientcg(asset, "4k", "png")
        self.assertEqual((d["attributes"], r, f), ("2K-PNG", "2k", "png"))
        self.assertEqual(notes, ["4k not offered, using 2k"])
        d, r, f, notes = M.plan_ambientcg(asset, "8k", "exr")
        self.assertEqual((d["attributes"], f), ("8K-JPG", "jpg"))
        with self.assertRaises(M.FetchError):
            M.plan_ambientcg({"id": "Y", "downloads": []}, "1k", "jpg")

    def test_ambientcg_hit(self):
        hit = M.ambientcg_hit({"id": "Bricks076C", "title": "Bricks 076 C", "maps": ["color", "ambient-occlusion",
                               "metalness", "normal"], "dimensions": {"width": 200, "height": 100},
                               "downloads": [{"attributes": "1K-JPG"}, {"attributes": "8K-PNG"}]})
        self.assertEqual(hit["maps"], ["BaseColor", "AO", "Metallic", "Normal"])
        self.assertEqual(hit["size_m"], [2.0, 1.0])                              # centimetres -> metres
        self.assertEqual(hit["max_res"], "8k")
        self.assertIsNone(M.ambientcg_hit({"id": "Z", "dimensions": {"width": 0, "height": 0}})["size_m"])


class Extraction(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.zip = os.path.join(self.dir, "a.zip")
        make_acg_zip(self.zip, "Metal063", "1K-JPG", ["Color", "NormalGL", "NormalDX", "Roughness", "Metalness",
                                                      "Displacement"],
                     extra=["Metal063_1K-JPG.mtlx", "Metal063.png", "Other_1K-JPG_Color.jpg"])

    def tearDown(self):
        self.tmp.cleanup()

    def test_rename_and_select(self):
        out = os.path.join(self.dir, "out")
        written, notes = M.extract_ambientcg(self.zip, "Metal063", "1K-JPG", out, "Metal063_1k")
        self.assertEqual(sorted(os.listdir(out)), ["Metal063_1k_BaseColor.jpg", "Metal063_1k_Height.jpg",
                                                   "Metal063_1k_Metallic.jpg", "Metal063_1k_NormalGL.jpg",
                                                   "Metal063_1k_Roughness.jpg"])
        self.assertEqual(notes, ["AO: not offered for this asset"])
        with open(os.path.join(out, "Metal063_1k_BaseColor.jpg"), "rb") as f:
            self.assertEqual(f.read(), b"img-Color")

    def test_bundle_keeps_names(self):
        out = os.path.join(self.dir, "out")
        written, _ = M.extract_ambientcg(self.zip, "Metal063", "1K-JPG", out, "p", bundle=True)
        self.assertIn("Metal063_1K-JPG.mtlx", os.listdir(out))
        self.assertIn("Metal063_1K-JPG_NormalDX.jpg", os.listdir(out))

    def test_unsafe_member_refused(self):
        bad = os.path.join(self.dir, "bad.zip")
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("../evil.jpg", b"x")
        with self.assertRaises(M.FetchError):
            M.extract_ambientcg(bad, "X", "1K-JPG", os.path.join(self.dir, "out"), "p", bundle=True)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "evil.jpg")))

    def test_safe_join(self):
        root = os.path.join(self.dir, "r")
        self.assertTrue(M.safe_join(root, "textures/a.jpg").startswith(os.path.abspath(root)))
        for bad in ("/etc/x", "C:/x", "a/../../x", "..", ""):
            with self.assertRaises(M.FetchError):
                M.safe_join(root, bad)


class GetWithFakeNetwork(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = self.tmp.name
        self._json, self._dl = M.http_json, M.http_download

    def tearDown(self):
        M.http_json, M.http_download = self._json, self._dl
        self.tmp.cleanup()

    def fake(self, json_by_url, bytes_by_url):
        def http_json(url, retries=2):
            for prefix, value in json_by_url.items():
                if url.startswith(prefix):
                    return value
            raise M.FetchError("unexpected %s" % url)

        def http_download(url, path, retries=2):
            data = bytes_by_url(url)
            with open(path, "wb") as f:
                f.write(data)
            return hashlib.md5(data).hexdigest(), len(data)
        M.http_json, M.http_download = http_json, http_download

    def test_polyhaven_get_and_record(self):
        self.fake({M.POLYHAVEN_API + "/info/": dict(PH_ASSETS["red_brick_03"], authors={"A": "All"}),
                   M.POLYHAVEN_API + "/files/": ph_files()}, lambda url: b"pixels")
        rec = M.get("polyhaven:red_brick_03", self.out, "1k", log=lambda *_: None)
        folder = os.path.join(self.out, "polyhaven_red_brick_03")
        self.assertIn("red_brick_03_1k_BaseColor.jpg", os.listdir(folder))
        with open(os.path.join(folder, "source.json"), encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved, rec)
        self.assertEqual(rec["licence"], "CC0-1.0")
        self.assertIn("Poly Haven", rec["credit"])
        self.assertEqual(rec["size_m"], [1.0, 1.0])
        self.assertEqual(len(rec["files"]), 5)

    def test_md5_mismatch_fails_and_removes(self):
        self.fake({M.POLYHAVEN_API + "/info/": PH_ASSETS["red_brick_03"], M.POLYHAVEN_API + "/files/": ph_files()},
                  lambda url: b"corrupted")
        with self.assertRaises(M.FetchError):
            M.get("polyhaven:red_brick_03", self.out, "1k", log=lambda *_: None)
        folder = os.path.join(self.out, "polyhaven_red_brick_03")
        self.assertFalse([n for n in os.listdir(folder) if n.endswith(".jpg")])

    def test_not_a_texture(self):
        self.fake({M.POLYHAVEN_API + "/info/": {"type": 0, "name": "An HDRI"}}, lambda url: b"")
        with self.assertRaises(M.FetchError):
            M.get("polyhaven:some_hdri", self.out, "1k", log=lambda *_: None)

    def test_max_mb(self):
        big = ph_files()
        for by_res in big.values():
            for fmts in by_res.values():
                for e in fmts.values():
                    e["size"] = 400 * 10 ** 6
        self.fake({M.POLYHAVEN_API + "/info/": PH_ASSETS["red_brick_03"], M.POLYHAVEN_API + "/files/": big},
                  lambda url: b"")
        with self.assertRaises(M.FetchError):
            M.get("polyhaven:red_brick_03", self.out, "1k", max_mb=500, log=lambda *_: None)

    def test_ambientcg_get(self):
        src = os.path.join(self.out, "src.zip")
        make_acg_zip(src, "Bricks076C", "2K-JPG", ["Color", "NormalGL", "Roughness", "AmbientOcclusion",
                                                   "Displacement"])
        data = Path(src).read_bytes()
        asset = {"id": "Bricks076C", "title": "Bricks 076 C", "dimensions": {"width": 200, "height": 200},
                 "downloads": [{"attributes": "2K-JPG", "extension": "zip", "url": "https://z/2k", "size": len(data)}]}
        self.fake({M.AMBIENTCG_API: {"assets": [asset]}}, lambda url: data)
        rec = M.get("ambientcg:Bricks076C", self.out, "4k", log=lambda *_: None)
        self.assertEqual(rec["res"], "2k")
        self.assertEqual(sorted(f["map"] for f in rec["files"]), ["AO", "BaseColor", "Height", "NormalGL",
                                                                  "Roughness"])
        self.assertIn("4k not offered, using 2k", rec["notes"])
        self.assertIn("Bricks 076 C", rec["credit"])

    def test_ambientcg_size_mismatch(self):
        src = os.path.join(self.out, "src.zip")
        make_acg_zip(src, "B", "1K-JPG", ["Color"])
        data = Path(src).read_bytes()
        asset = {"id": "B", "downloads": [{"attributes": "1K-JPG", "extension": "zip", "url": "u", "size": 1}]}
        self.fake({M.AMBIENTCG_API: {"assets": [asset]}}, lambda url: data)
        with self.assertRaises(M.FetchError):
            M.get("ambientcg:B", self.out, "1k", log=lambda *_: None)


@unittest.skipUnless(os.environ.get("PBR_FETCH_LIVE") == "1", "set PBR_FETCH_LIVE=1 for the live API check")
class Live(unittest.TestCase):
    def test_search_both(self):
        hits, errors = M.search(["brick"], limit=2)
        self.assertEqual(errors, [])
        self.assertEqual({h["source"] for h in hits}, {"polyhaven", "ambientcg"})


if __name__ == "__main__":
    unittest.main()
