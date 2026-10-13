"""Check that conventions duplicated across skills still agree with each other.

Skills in this repo are independent (see AGENTS.md), so a few facts live in more than one skill: the kit piece
naming pattern, the VRChat platform budgets, the FBX export settings, the Blender -> Unity axis conversion, the
VR texel-density classes, the kit_status values, and one script shipped identically in two skills. This finds every copy and fails if any
disagrees with the canonical value below. When a fact changes, change CANON here and every copy it lists.

Host: plain Python 3.9+, standard library. Run from anywhere:
    python tools/check_conventions.py          # exit 1 on any mismatch
"""

import ast
import hashlib
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills")

CANON = {
    "piece_re": r"^[A-Z]{2,5}_[A-Za-z0-9]+_(\d+(x\d+){0,2}|Free)_[A-Z]\d?$",
    "asm_re": r"^ASM_[A-Za-z0-9]+_[A-Z]\d?$",
    "budgets": {   # practical targets (upper bounds); quest download is the hard limit
        "pc": {"world_tris": 1_000_000, "view_tris": 300_000, "setpass": 150, "batches": 400, "materials": 60,
               "map_px": 2048, "texture_vram_mb": 1500, "lightmap_px": 2048},
        "quest": {"world_tris": 250_000, "view_tris": 100_000, "setpass": 50, "batches": 150, "materials": 25,
                  "map_px": 1024, "texture_vram_mb": 150, "lightmap_px": 1024, "download_mb": 100},
    },
    "kit_status": ["grey", "modelled", "uv", "textured", "exported"],
    "axis_text": "(-x, z, -y)",
    "texel_rule": "1150 / d",
    "texel_classes": [("512", "0-3"), ("256", "3-6"), ("128", "6-12"), ("64", "> 12")],
}

# Row labels (regex, case-insensitive) for the budget tables in markdown.
ROWS = {
    "world_tris": r"world triangles", "view_tris": r"triangles (visible )?in one view", "setpass": r"setpass",
    "batches": r"^batches", "materials": r"unique materials", "map_px": r"max texture",
    "texture_vram_mb": r"texture vram", "lightmap_px": r"^lightmap", "download_mb": r"download size",
}

FAIL = []


def path(rel):
    return os.path.normpath(os.path.join(ROOT, rel))


def read(rel):
    with open(path(rel), encoding="utf-8") as f:
        return f.read()


def fail(rel, msg):
    FAIL.append("%s: %s" % (rel, msg))


def norm_re(r):
    """Ignore grouping that does not change what matches: (?: ) and a capture group around the family code."""
    return r.replace("?:", "").replace("^([A-Z]{2,5})_", "^[A-Z]{2,5}_")


# ---- naming patterns --------------------------------------------------------------------------------------------

def check_regex_py(rel, var, key):
    m = re.search(r'%s\s*=\s*re\.compile\(r"([^"]+)"\)' % var, read(rel))
    if not m:
        fail(rel, "no %s found" % var)
    elif norm_re(m.group(1)) != CANON[key]:
        fail(rel, "%s is %s, canon %s" % (var, m.group(1), CANON[key]))


def check_regex_md(rel, key):
    found = re.findall(r"`(\^[^`]+\$)`", read(rel))
    if CANON[key] not in [norm_re(f) for f in found]:
        fail(rel, "does not state the %s pattern %s (found %s)" % (key, CANON[key], found))


# ---- budgets ----------------------------------------------------------------------------------------------------

def number(cell):
    """Upper bound in a table cell: '500k-1M (scene dependent)' -> 1000000, '< 1.5 GB' -> 1500 (MB)."""
    cell = re.sub(r"\(.*?\)", "", cell).replace("**", "")
    vals = []
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(k|M|GB|MB)?\b", cell):
        v = float(num)
        v *= {"k": 1e3, "M": 1e6, "GB": 1e3, "MB": 1, "": 1}[unit or ""]
        vals.append(v)
    return max(vals) if vals else None


def table_rows(text):
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and not set(cells[0]) <= set("-: "):
            yield cells


def check_budget_md(rel, require):
    seen = set()
    for cells in table_rows(read(rel)):
        for key, pat in ROWS.items():
            if not re.search(pat, cells[0], re.I):
                continue
            for col, plat in ((1, "pc"), (2, "quest")):
                want = CANON["budgets"][plat].get(key)
                got = number(cells[col]) if col < len(cells) else None
                if want is None or got is None:
                    continue
                seen.add(key)
                if abs(got - want) > 1e-6:
                    fail(rel, "%s %s is %g, canon %g  [%s]" % (plat, key, got, want, cells[0]))
    for key in require:
        if key not in seen:
            fail(rel, "budget row for %s not found" % key)


def check_budget_hard_limit(rel):
    m = re.search(r"Quest world download size \| \*\*(\d+) MB", read(rel))
    if not m or int(m.group(1)) != CANON["budgets"]["quest"]["download_mb"]:
        fail(rel, "Quest download hard limit missing or not %d MB" % CANON["budgets"]["quest"]["download_mb"])


def check_budget_py(rel):
    tree = ast.parse(read(rel))
    vals = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in ("PLATFORM_LIMITS", "QUEST_DOWNLOAD_MB"):
                vals[node.targets[0].id] = ast.literal_eval(node.value)
    limits = vals.get("PLATFORM_LIMITS", {})
    for plat, canon in CANON["budgets"].items():
        for key, want in canon.items():
            if key == "download_mb":
                got = vals.get("QUEST_DOWNLOAD_MB")
            else:
                got = limits.get(plat, {}).get(key)
            if got != want:
                fail(rel, "%s %s is %s, canon %s" % (plat, key, got, want))


def check_budget_template(rel):
    text = read(rel)
    q = CANON["budgets"]["quest"]
    for key in ("world_tris", "view_tris", "materials", "setpass", "batches", "texture_vram_mb"):
        m = re.search(r"^\s*%s:\s*(\d+)" % key, text, re.M)
        if not m or int(m.group(1)) > q[key]:
            fail(rel, "template budgets.%s missing or looser than quest %d" % (key, q[key]))


# ---- export settings, axes, kit_status, shared scripts -------------------------------------------------------------

FBX_TEXT = [r"-Z\s*Forward", r"Y\s*Up", r"FBX\s*All", r"Use Space Transform\W+on", r"Bake Space Transform(\s*\([^)]*\))?\W+on\b"]
FBX_CODE = [r'axis_forward="-Z"', r'axis_up="Y"', r'apply_scale_options="FBX_SCALE_ALL"',
            r"use_space_transform=True", r"bake_space_transform=True"]


def check_patterns(rel, pats, what):
    text = read(rel)
    for p in pats:
        if not re.search(p, text, re.I):
            fail(rel, "%s: missing %s" % (what, p))


def check_axis_matrix(rel):
    m = re.search(r"C = Matrix\(\(\((.+?)\)\)\)", read(rel))
    want = "-1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0"
    if not m or m.group(1).replace(" ", "") != want.replace(" ", ""):
        fail(rel, "axis matrix C is not Unity = (-x, z, -y)")


def check_identical(*rels):
    digests = {rel: hashlib.sha256(read(rel).encode()).hexdigest() for rel in rels}
    if len(set(digests.values())) > 1:
        fail(rels[0], "copies differ: " + ", ".join(rels))


def main():
    check_regex_py("blender-kit-library/scripts/kit_library.py", "NAME_RE", "piece_re")
    check_regex_py("blender-kit-library/scripts/kit_library.py", "ASM_RE", "asm_re")
    check_regex_py("vrchat-world-orchestration/scripts/spec_validate.py", "NAME_RE", "piece_re")
    check_regex_py("vrchat-world-orchestration/scripts/spec_validate.py", "ASM_RE", "asm_re")
    check_regex_py("vrchat-world-qa/scripts/qa_measure.py", "NAME_RE", "piece_re")
    for rel in ("blender-kit-library/SKILL.md",
                "vrchat-world-orchestration/references/world-spec.md"):
        check_regex_md(rel, "piece_re")
        check_regex_md(rel, "asm_re")

    all_rows = list(ROWS)
    check_budget_md("vrchat-world-optimization/references/budgets.md",
                    [k for k in all_rows if k != "download_mb"])
    check_budget_hard_limit("vrchat-world-optimization/references/budgets.md")
    check_budget_md("vrchat-world-optimization/SKILL.md", ["world_tris", "setpass", "map_px", "download_mb"])
    check_budget_md("vrchat-world-qa/references/checklists.md", all_rows)
    check_budget_py("vrchat-world-orchestration/scripts/spec_validate.py")
    check_budget_template("vrchat-world-orchestration/templates/spec.yaml")

    check_patterns("blender-to-unity/scripts/batch_export_fbx.py", FBX_CODE, "FBX settings")
    for rel in ("blender-to-unity/references/fbx-export.md",
                "blender-unity-placement-sync/SKILL.md",
                "vrchat-world-orchestration/references/stages.md"):
        check_patterns(rel, FBX_TEXT, "FBX settings")

    check_axis_matrix("blender-unity-placement-sync/scripts/export_placements.py")
    for rel in ("blender-unity-placement-sync/SKILL.md", "vrchat-world-qa/references/visual-review.md"):
        if CANON["axis_text"] not in read(rel):
            fail(rel, "does not state the axis conversion %s" % CANON["axis_text"])

    status_re = r"[\s,`]+".join("`?%s`?" % s for s in CANON["kit_status"])
    for rel in ("vrchat-world-orchestration/SKILL.md", "vrchat-world-orchestration/references/world-spec.md"):
        if not re.search(status_re, read(rel)):
            fail(rel, "kit_status values are not %s" % ", ".join(CANON["kit_status"]))

    for rel in ("uv-unwrapping/SKILL.md", "uv-unwrapping/references/texel-density.md",
                "rizomuv-uv-pipeline/SKILL.md", "rizomuv-uv-pipeline/references/texel-density.md"):
        text = read(rel)
        if CANON["texel_rule"] not in text:
            fail(rel, "does not state the texel rule %s" % CANON["texel_rule"])
        if rel.endswith("rizomuv-uv-pipeline/SKILL.md"):
            if "512 / 256 / 128 / 64" not in text:
                fail(rel, "texel classes are not 512 / 256 / 128 / 64")
            continue
        for px, dist in CANON["texel_classes"]:
            # the class and its distance band appear together on one line (a table row or a sentence)
            if not any(re.search(r"(?<!\d)%s(?!\d)" % px, line) and dist in line for line in text.splitlines()):
                fail(rel, "texel class %s px/m at %s m not found" % (px, dist))

    check_identical("blender-kit-library/scripts/kit_library.py",
                    "vrchat-world-orchestration/scripts/kit_library.py")

    if FAIL:
        print("\n".join("MISMATCH " + f for f in FAIL))
        print("%d mismatch(es)" % len(FAIL))
        sys.exit(1)
    print("conventions agree across skills")


if __name__ == "__main__":
    main()
