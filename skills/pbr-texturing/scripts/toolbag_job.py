"""The bake job that runs inside Marmoset Toolbag: read a job JSON, build a baker, bake, write a result JSON, quit.

Host: Marmoset Toolbag 5's embedded Python (the mset module; measured on 5.0.3.3). Not run by hand: toolbag_bake.py
launches it as
    toolbag.exe -hide toolbag_job.py <job.json> <result.json>
and waits for <result.json>. Inside Toolbag __file__ is not defined, so every path comes in through sys.argv and
the job. The job ({"probe": true} only checks that a script runs) is built by toolbag_bake.build_job():
- every FBX goes through the baker's quick loader, which groups by name: the low object <stem>_low, each high
  object <stem>_high (one file per high), one stem. mset.importModel plus parenting under High baked the high at the
  wrong scale (the 1 m test cube lost its bevels), and a .glb is not read at all;
- each high material's transfer textures are assigned explicitly (FBX textures do not arrive): albedo as sRGB,
  roughness and metalness as data, through Material.getSubroutine(...).setField(<map field>, mset.Texture(path)) (a
  plain path string is ignored without an error);
- the cage: every Low group's maxOffset / minOffset, converted from metres to scene units (an FBX scene is in cm);
- the lows' tangent space set to Mikk (Unity's); ignore back faces and a smooth cage on;
- maps picked by Toolbag's default suffix, renamed to our _<Suffix>, written as <out_dir>/<name>_<Suffix>.png.
The result: {"ok", "version", "maps": {map: path}, "seconds", "warnings", "error"}; Toolbag exits 0 or 1.
"""

import json
import os
import sys
import time
import traceback

import mset

TEXTURE_SLOTS = {   # our map -> (material subroutine, the shader it should be, sRGB)
    "basecolor": ("albedo", "Albedo", True),
    "roughness": ("microsurface", "Roughness", False),
    "metallic": ("reflectivity", "Metalness", False),
}


def _walk(obj):
    yield obj
    for c in obj.getChildren():
        yield from _walk(c)


def _assign_textures(high_root, textures, warnings):
    done = 0
    for ob in _walk(high_root):
        if not isinstance(ob, mset.SubMeshObject):
            continue
        mat = ob.material
        entry = textures.get(mat.name) or textures.get("*")
        if not entry:
            continue
        for m, path in entry.items():
            cat, shader, srgb = TEXTURE_SLOTS[m]
            sub = mat.getSubroutine(cat)
            if sub is None or sub.name != shader:
                mat.setSubroutine(cat, shader)
                sub = mat.getSubroutine(cat)
            field = next((f for f in sub.getFieldNames() if f.endswith("Map")), None)
            if field is None:
                warnings.append("%s: %s has no map field (%s)" % (mat.name, shader, sub.getFieldNames()))
                continue
            tex = mset.Texture(path)
            tex.sRGB = srgb
            sub.setField(field, tex)
            done += 1
    return done


def run(job, R):
    warnings = R["warnings"]
    mset.newScene()
    b = mset.BakerObject()
    b.name = job["name"]
    b.importModel(job["low"])
    low_groups = [o for o in _walk(b) if isinstance(o, mset.BakerTargetObject)]
    if not low_groups or not any(isinstance(o, mset.MeshObject) for g in low_groups for o in _walk(g)):
        raise RuntimeError("the low FBX made no Low group with a mesh: name its object <stem>_low")
    for p in job["highs"]:
        b.importModel(p)       # the quick loader: mset.importModel + reparenting baked at the wrong scale
    highs = [o for o in _walk(b) if o.name == "High" and not isinstance(o, mset.BakerTargetObject)]
    if len(highs) != 1 or not any(isinstance(o, mset.MeshObject) for o in _walk(highs[0])):
        raise RuntimeError("the high FBX files made %d High groups with meshes; name every high object "
                           "<stem>_high, the low <stem>_low (one stem)" % len(highs))
    high = highs[0]
    if job.get("textures"):
        R["textures_assigned"] = _assign_textures(high, job["textures"], warnings)
        if not R["textures_assigned"]:
            warnings.append("no high material matched job textures %s" % sorted(job["textures"]))
    us = mset.getSceneUnitScale()
    R["unit_scale"] = us
    for g in low_groups:
        g.maxOffset = job["cage_out"] / us
        g.minOffset = -job["cage_in"] / us
        for o in _walk(g):
            if isinstance(o, mset.MeshObject):
                o.tangentSpace = "Mikk"
    b.outputPath = os.path.join(job["out_dir"], job["name"] + ".png")
    b.outputWidth, b.outputHeight = job["width"], job["height"]
    b.outputBits = job["bits"]
    b.outputSamples = job["samples"]
    b.ignoreBackfaces = job.get("ignore_backfaces", True)
    b.smoothCage = True
    try:
        b.edgePadding = "Custom"
        b.edgePaddingSize = job["margin"]
    except Exception:                                  # older builds: only None / Moderate / Extreme
        b.edgePadding = "Extreme"
        warnings.append("edgePadding Custom refused: Extreme used")
    by_suffix = {v: k for k, v in job["toolbag_maps"].items()}
    found = set()
    for mp in b.getAllMaps():
        mp.resetSuffix()
        ours = by_suffix.get(mp.suffix)
        mp.enabled = ours is not None
        if ours is None:
            continue
        found.add(ours)
        mp.suffix = job["suffixes"][ours]
        if ours == "normal":
            mp.flipX = mp.flipY = mp.flipZ = False
        if ours == "ao" and job.get("ao_distance"):
            mp.searchDistance = job["ao_distance"] / us
    missing = set(job["maps"]) - found
    if missing:
        raise RuntimeError("Toolbag has no map with suffix %s" % ", ".join(job["toolbag_maps"][m] for m in missing))
    t = time.time()
    b.bake()
    R["seconds"] = round(time.time() - t, 3)
    for m in job["maps"]:
        p = os.path.join(job["out_dir"], "%s_%s.png" % (job["name"], job["suffixes"][m]))
        if not os.path.isfile(p):
            raise RuntimeError("bake wrote no %s" % p)
        R["maps"][m] = p
    R["ok"] = True


def main():
    job_path, res_path = sys.argv[-2], sys.argv[-1]
    R = {"ok": False, "version": None, "maps": {}, "warnings": [], "error": None}
    try:
        R["version"] = mset.getToolbagVersion()
        with open(job_path, encoding="utf-8") as f:
            job = json.load(f)
        if job.get("probe"):
            R["ok"] = True
        else:
            run(job, R)
    except Exception:
        R["error"] = traceback.format_exc()
    tmp = res_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(R, f, indent=1)
    os.replace(tmp, res_path)                          # appears whole: the launcher polls for it
    mset.quit(0 if R["ok"] else 1)


main()
