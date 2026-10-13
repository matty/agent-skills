"""Kit library helpers: KIT pieces as collections, linked and placed as collection instances.

Kit rules (naming, pivots, KIT / ASM / MASTER files): the blender-kit-library skill's SKILL.md, or world-spec.md in
vrchat-world-orchestration. This file ships identically in both skills; keep the copies the same
(tools/check_conventions.py in the agent-skills repo checks it).

Host: Blender 4.1+ (bpy), no add-ons.

Load in Blender:  ns = {}; exec(open(r"<skill>/scripts/kit_library.py", encoding="utf-8").read(), ns)

    ns["new_piece"]("EXT_Wall_2x3_A")                         # in a KIT file: empty piece collection, offset zero
    ns["list_library"](r"//kits/KIT_Arch_Exterior.blend")     # piece collection names in a KIT or ASM file
    inst = ns["link_piece"](r"//kits/KIT_Arch_Exterior.blend", "EXT_Wall_2x3_A", location=(4, 0, 0), rot_z=90)
    ns["reload_libraries"]()                                  # after KIT files changed on disk
    rep = ns["audit_kit"](module=1.0); ns["problems"](rep)    # in a KIT file; read-only

From the command line (prints one line per piece; --json writes the full report; exit code 1 on problems):
    blender -b KIT_Arch_Exterior.blend --python kit_library.py -- --audit --module 1.0 [--json report.json]

Paths starting with // are relative to the open .blend, as everywhere in Blender.
"""

import json
import math
import re
import sys

import bpy
from mathutils import Matrix, Vector

NAME_RE = re.compile(r"^([A-Z]{2,5})_[A-Za-z0-9]+_(\d+(?:x\d+){0,2}|Free)_[A-Z]\d?$")
ASM_RE = re.compile(r"^ASM_[A-Za-z0-9]+_[A-Z]\d?$")
EPS = 1e-4


def _abs(path):
    return bpy.path.abspath(path).replace("\\", "/").lower()


def new_piece(name, parent=None):
    """Create (or return) the collection for one kit piece, linked under `parent` (default the scene collection)."""
    if not (NAME_RE.match(name) or ASM_RE.match(name)):
        raise ValueError("%r does not follow <FAMILY>_<Type>_<Size>_<Variant> or ASM_<Name>_<Variant>" % name)
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
        (parent or bpy.context.scene.collection).children.link(coll)
    coll.instance_offset = (0.0, 0.0, 0.0)
    return coll


def list_library(path):
    """Names of the collections in another .blend that look like kit pieces or assemblies."""
    with bpy.data.libraries.load(path, link=True) as (src, _dst):
        names = list(src.collections)
    return [n for n in names if NAME_RE.match(n) or ASM_RE.match(n)]


def link_collection(path, name, relative=True):
    """Link collection `name` from `path`, reusing it if this file already links it from there."""
    want = _abs(path)
    for coll in bpy.data.collections:
        if coll.name == name and coll.library and _abs(coll.library.filepath) == want:
            return coll
    with bpy.data.libraries.load(path, link=True, relative=relative) as (src, dst):
        if name not in src.collections:
            raise KeyError("no collection %r in %s" % (name, path))
        dst.collections = [name]
    return dst.collections[0]


def place(coll, location=(0.0, 0.0, 0.0), rot_z=0.0, name=None, into=None):
    """Add a collection instance of `coll` (an empty), rotated `rot_z` degrees about Z, into collection `into`."""
    inst = bpy.data.objects.new(name or coll.name, None)
    inst.instance_type = "COLLECTION"
    inst.instance_collection = coll
    inst.empty_display_size = 0.25
    inst.matrix_world = Matrix.Translation(Vector(location)) @ Matrix.Rotation(math.radians(rot_z), 4, "Z")
    (into or bpy.context.scene.collection).objects.link(inst)
    return inst


def link_piece(path, name, location=(0.0, 0.0, 0.0), rot_z=0.0, into=None, relative=True):
    """Link a piece from a KIT (or assembly from an ASM file) and place one instance of it."""
    return place(link_collection(path, name, relative), location, rot_z, into=into)


def reload_libraries(paths=None):
    """Reload linked libraries (all, or those whose file is in `paths`). Returns the reloaded file paths."""
    want = {_abs(p) for p in paths} if paths else None
    done = []
    for lib in bpy.data.libraries:
        if want is None or _abs(lib.filepath) in want:
            lib.reload()
            done.append(lib.filepath)
    return done


def _is_identity(mw):
    return all(abs(mw[i][j] - (1.0 if i == j else 0.0)) < EPS for i in range(4) for j in range(4))


def _bounds(objs):
    lo = Vector((math.inf,) * 3)
    hi = Vector((-math.inf,) * 3)
    for ob in objs:
        for corner in ob.bound_box:
            p = ob.matrix_world @ Vector(corner)
            lo = Vector(map(min, lo, p))
            hi = Vector(map(max, hi, p))
    return lo, hi


def audit_piece(coll, module=1.0, materials=None):
    """Report for one piece collection. materials: allowed name prefixes (default M_<FAMILY>_ and M_TRIM_)."""
    rep = {"piece": coll.name, "issues": []}
    issues = rep["issues"]
    m = NAME_RE.match(coll.name)
    if not m:
        issues.append("name does not match <FAMILY>_<Type>_<Size>_<Variant>")
        return rep
    family, size = m.group(1), m.group(2)
    prefixes = tuple(materials or ("M_%s_" % family, "M_TRIM_"))
    if Vector(coll.instance_offset).length > EPS:
        issues.append("instance_offset is %s, not zero" % tuple(round(v, 4) for v in coll.instance_offset))

    objs = list(coll.all_objects)
    meshes = [o for o in objs if o.type == "MESH"]
    render = [o for o in meshes if not o.name.endswith("_COL")]
    if not render:
        issues.append("no render mesh")
        return rep
    for ob in objs:
        if not _is_identity(ob.matrix_world):
            issues.append("%s: transform is not identity (origin must be the piece pivot, rotation/scale applied)"
                          % ob.name)
    for ob in render:
        if len(ob.data.uv_layers) < 2:
            issues.append("%s: no UV2 (lightmap) layer" % ob.name)
        for slot in ob.material_slots:
            if slot.material is None:
                issues.append("%s: empty material slot" % ob.name)
            elif not slot.material.name.startswith(prefixes):
                issues.append("%s: material %s outside %s" % (ob.name, slot.material.name, "/".join(prefixes)))

    lo, hi = _bounds(render)
    rep["bounds_m"] = [round(v, 4) for v in (*lo, *hi)]
    if size != "Free":
        if any(abs(v) > 0.01 for v in lo):
            issues.append("min corner %s is not at the origin (pivot must be bottom-left)"
                          % tuple(round(v, 3) for v in lo))
        ext = [(hi[i] - lo[i]) / module for i in range(3)]
        grid = [e for e in ext if e >= 0.5]
        want = [int(t) for t in size.split("x")]
        rep["extent_modules"] = [round(e, 3) for e in ext]
        if [round(e) for e in grid] != want or any(abs(e - round(e)) > 0.01 for e in grid):
            issues.append("extents %s modules do not match size %s" % ([round(e, 3) for e in ext], size))
    return rep


def audit_kit(module=1.0, materials=None):
    """Audit every piece collection in this file, plus mesh objects that sit outside any piece."""
    pieces = [c for c in bpy.data.collections if c.library is None and NAME_RE.match(c.name)]
    reps = [audit_piece(c, module, materials) for c in sorted(pieces, key=lambda c: c.name)]
    owned = {o.name for c in pieces for o in c.all_objects}
    stray = [o.name for o in bpy.data.objects if o.library is None and o.type == "MESH" and o.name not in owned]
    odd = [c.name for c in bpy.data.collections
           if c.library is None and not NAME_RE.match(c.name) and not ASM_RE.match(c.name) and c.objects]
    return {"module": module, "pieces": reps, "stray_meshes": stray, "unnamed_collections": odd}


def problems(report):
    """Flat list of readable failures from audit_kit() (empty when the kit passes)."""
    out = ["%s: %s" % (r["piece"], i) for r in report["pieces"] for i in r["issues"]]
    out += ["stray mesh outside any piece collection: %s" % n for n in report["stray_meshes"]]
    out += ["collection with objects but no kit name: %s" % n for n in report["unnamed_collections"]]
    return out


def _main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if "--audit" not in argv:
        return
    module = float(argv[argv.index("--module") + 1]) if "--module" in argv else 1.0
    rep = audit_kit(module)
    for r in rep["pieces"]:
        print("%-32s %s" % (r["piece"], "ok" if not r["issues"] else "; ".join(r["issues"])))
    probs = problems(rep)
    for p in probs[len([i for r in rep["pieces"] for i in r["issues"]]):]:
        print(p)
    if "--json" in argv:
        with open(argv[argv.index("--json") + 1], "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2)
    print("[kit_library] %d piece(s), %d problem(s)" % (len(rep["pieces"]), len(probs)))
    if bpy.app.background:
        sys.exit(1 if probs else 0)


if __name__ == "__main__":
    _main()
