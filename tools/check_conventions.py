"""Check that conventions duplicated across skills still agree with each other.

Skills in this repo are independent (see AGENTS.md), so a few facts live in more than one skill: the kit piece,
assembly and material naming patterns, the VRChat platform budgets and limits, the FBX export settings, the
Blender -> Unity axis conversion, the VR texel-density classes, the lightmap planning constants (Bakery's too), the
kit_status values, the required Unity version, the PBR base-colour range, and two scripts each shipped identically
in two skills (kit_library.py, pbr_check.py). This finds every copy and fails if any disagrees with the canonical
value below. When a fact changes, change CANON here and every copy it lists. FORBIDDEN lists statements a review
found wrong, so they cannot creep back in.

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
    # each class gives at least two thirds of what a 20 ppd headset resolves (1150 / d) at the near edge of its band
    "texel_classes": [("2048", "< 0.75"), ("1024", "0.75-1.5"), ("512", "1.5-3"), ("256", "3-6"), ("128", "6-12"),
                      ("64", "> 12")],
    # the same classes as (px per m, nearest viewing distance in m from which the class applies), for scripts
    "texel_class_edges": [(2048, 0.0), (1024, 0.75), (512, 1.5), (256, 3.0), (128, 6.0), (64, 12.0)],
    # dielectric base-colour luma range in sRGB codes: Adobe's PBR Guide part 2 (tolerant dark limit, bright limit),
    # held by pbr_check.py (pbr-texturing and vrchat-world-qa) and the spec validator's look.materials targets
    "pbr_albedo_srgb": [30, 240],
    "pbr_albedo_text": "30-240",
    "material_re": r"^M_[A-Z]{2,5}_[A-Za-z0-9][A-Za-z0-9_]*$",
    "unity_version": "2022.3.22f1",
    # Other full Unity versions a skill may name, and why (anything else is a stale version).
    "other_unity_versions": {"2019.4.31f1": "the SDK template descriptor's stale, cosmetic Unity Version field"},
    # The kit export (blender-to-unity batch_export_fbx.py FBX_SETTINGS) and the Unity import (KitImport.cs).
    "fbx_export": dict(object_types={"MESH"}, use_custom_props=False, global_scale=1.0, apply_unit_scale=True,
                       apply_scale_options="FBX_SCALE_ALL", axis_forward="-Z", axis_up="Y", use_space_transform=True,
                       bake_space_transform=True, mesh_smooth_type="FACE", use_mesh_modifiers=True, use_subsurf=False,
                       use_mesh_edges=False, use_triangles=True, use_tspace=False, colors_type="NONE",
                       add_leaf_bones=False, bake_anim=False, embed_textures=False),
    "kit_path_mode": "STRIP",
    "unity_import": {"globalScale": "1f", "useFileUnits": "true", "bakeAxisConversion": "false", "isReadable": "false",
                     "generateSecondaryUV": "false", "importCameras": "false", "importLights": "false",
                     "importVisibility": "false", "importBlendShapes": "false", "addCollider": "false",
                     "importNormals": "ModelImporterNormals.Import", "animationType": "ModelImporterAnimationType.None",
                     "meshCompression": "ModelImporterMeshCompression.Off",
                     "importAnimation": "false",
                     "materialImportMode": "ModelImporterMaterialImportMode.ImportViaMaterialDescription",
                     "materialLocation": "ModelImporterMaterialLocation.InPrefab"},
    # Lightmap planning, measured in Unity 2022.3.22f1: the UV2 chart box's share of the tile to plan footprints with
    # (b), the box fill to plan to, the box fill above which a spill is likely (kit-like sets spilled at 0.79-0.90,
    # Lightmap Padding 2, 2026-10-17), and the footprint below which a Free prop is probe-lit (a grid piece under it
    # gets a note instead).
    "lightmap": {"coverage": 0.85, "plan": 0.65, "max": 0.80, "min_footprint_px": 64, "gap_texels": 2},
    # UV distortion gate shared by uv-unwrapping's audit and the RizomUV grader, and the texel-density bands
    "uv_gate": {"angular_p95": 1.15, "angular_p99": 1.5, "angular_max": 2.0, "area_p95": 0.20, "area_max": 2.0,
                "island_angular_p95": 1.25, "island_area_p95": 0.50},
    "uv_island_min_share": 0.005,
    "tile_phase_texels": 0.5,
    "free_scale_band": (0.8, 1.25),   # the even scale a Free piece may be placed at without its own scale_range
    "texel_band": {"unique": (0.8, 1.25), "tiling": (0.9, 1.1), "trim": (0.9, 1.1)},
    "sliver_quality": 0.02,     # triangle quality below which both UV graders skip a triangle as a sliver
    "mobile_limit_text": "104,857,600",      # VRChat's 100 MB mobile world limit in bytes (its MB is 2^20)
    "manual_sync_text": "280,496",           # bytes per Manual serialization (network-details page)
    "net_rate_text": "11 KB/s",              # Udon outbound per client (network-details page)
    "continuous_sync_text": "200 bytes",     # per Continuous serialization (network-details page)
    "pc_download_mb": 200,                   # VRChat asks public PC worlds to stay under 200 MB (not an SDK limit)
    "pc_download_text": "200 MB",
    "astc_background_text": "8x8",           # ASTC exceptions: background albedo 8x8, size-bound normal maps 5x5
    "astc_normal_text": "5x5",
    "probe_lit_families": ["PROP", "FOL"],   # only Free pieces of these families get the under-64 px probe-lit advice
    # LODn gets its own lightmap space at 0.5^n of LOD0's texel scale, so it costs 0.25^n of an LOD0 of its area
    # (Unity 2022.3.22f1, Progressive GPU, measured 0.995 / 0.492 / 0.250 for LOD0-2, 2026-10-17)
    "lod_lightmap_scale": 0.5,
    "lod_lightmap_cost": 0.25,
    "uv2_box_fill_note": 0.5,   # UV2 charts filling less of their bounding box get a note (Unity packs the box)
    # Bakery's sizing (ftBuildGraphics.cs as installed in a Unity 2022.3.22f1 project, read 2026-10-24): the area it
    # sums is 2 x the surface area, and its Default atlas packer insets each rect 3 texels; the lightmapper names the
    # scripts take; the Bakery effective-density gate (half the planned texels per metre)
    "bakery": {"area_factor": 2.0, "inset_texels": 3},
    "lightmappers": ["unity", "bakery"],
    "effective_density_min": 0.5,
    # Modifier types that change topology: the hard-surface hand-off to UV work applies the stack from the top down to
    # the last of them (uv-unwrapping's apply_stack and blender-mesh-topology's apply_for_uv_work)
    "topology_types": ["ARRAY", "BEVEL", "BOOLEAN", "BUILD", "DECIMATE", "EDGE_SPLIT", "MASK", "MIRROR", "MULTIRES",
                       "REMESH", "SCREW", "SKIN", "SOLIDIFY", "SUBSURF", "WELD", "WIREFRAME"],
}

# Script constants that must equal a CANON value: (file, constant, CANON key path).
CONSTANTS = [
    ("vrchat-world-orchestration/scripts/spec_validate.py", "LIGHTMAP_COVERAGE", ("lightmap", "coverage")),
    ("vrchat-world-orchestration/scripts/spec_validate.py", "LIGHTMAP_PLAN", ("lightmap", "plan")),
    ("vrchat-world-orchestration/scripts/spec_validate.py", "LIGHTMAP_MAX", ("lightmap", "max")),
    ("vrchat-world-orchestration/scripts/spec_validate.py", "MIN_FOOTPRINT_PX", ("lightmap", "min_footprint_px")),
    ("vrchat-lighting-and-baking/scripts/lightmap_budget.py", "COVERAGE", ("lightmap", "coverage")),
    ("vrchat-lighting-and-baking/scripts/lightmap_budget.py", "PLAN_FILL", ("lightmap", "plan")),
    ("vrchat-lighting-and-baking/scripts/lightmap_budget.py", "ERROR_FILL", ("lightmap", "max")),
    ("vrchat-lighting-and-baking/scripts/lightmap_budget.py", "PROBE_LIT_BELOW_PX", ("lightmap", "min_footprint_px")),
    ("vrchat-lighting-and-baking/scripts/lightmap_budget.py", "MIN_PADDING_TEXELS", ("lightmap", "gap_texels")),
    ("vrchat-world-qa/scripts/qa_measure.py", "LIGHTMAP_COVERAGE", ("lightmap", "coverage")),
    ("vrchat-world-qa/scripts/qa_measure.py", "MIN_FOOTPRINT_PX", ("lightmap", "min_footprint_px")),
    ("vrchat-world-orchestration/scripts/spec_validate.py", "PC_DOWNLOAD_MB", ("pc_download_mb",)),
    ("rizomuv-uv-pipeline/scripts/rizom_uv.py", "LIGHTMAP_GAP_TEXELS", ("lightmap", "gap_texels")),
    ("uv-unwrapping/scripts/uv_audit.py", "FOOTPRINT_COVERAGE", ("lightmap", "coverage")),
    ("uv-unwrapping/scripts/uv_audit.py", "LIGHTMAP_GAP_TEXELS", ("lightmap", "gap_texels")),
    ("uv-unwrapping/scripts/uv_audit.py", "SLIVER_QUALITY", ("sliver_quality",)),
    ("rizomuv-uv-pipeline/scripts/uv_metrics.py", "SLIVER_QUALITY", ("sliver_quality",)),
    ("rizomuv-uv-pipeline/scripts/rizom_uv.py", "LIGHTMAP_COVERAGE", ("lightmap", "coverage")),
    ("rizomuv-uv-pipeline/scripts/rizom_uv.py", "LIGHTMAP_MIN_FOOTPRINT_PX", ("lightmap", "min_footprint_px")),
    ("vrchat-world-qa/scripts/qa_measure.py", "STATUS_ORDER", ("kit_status",)),
    ("blender-kit-library/scripts/kit_library.py", "STATUS_ORDER", ("kit_status",)),
    ("vrchat-lighting-and-baking/scripts/lightmap_budget.py", "PROBE_LIT_FAMILIES", ("probe_lit_families",)),
    ("vrchat-world-orchestration/scripts/spec_validate.py", "PROBE_LIT_FAMILIES", ("probe_lit_families",)),
    ("vrchat-world-qa/scripts/qa_measure.py", "PROBE_LIT_FAMILIES", ("probe_lit_families",)),
    ("uv-unwrapping/scripts/uv_audit.py", "LOD_SCALE", ("lod_lightmap_scale",)),
    ("rizomuv-uv-pipeline/scripts/rizom_uv.py", "LOD_SCALE", ("lod_lightmap_scale",)),
    ("vrchat-lighting-and-baking/scripts/lightmap_budget.py", "LOD_SCALE", ("lod_lightmap_scale",)),
    ("vrchat-world-qa/scripts/qa_measure.py", "LOD_LIGHTMAP_SCALE", ("lod_lightmap_scale",)),
    ("vrchat-world-orchestration/scripts/spec_validate.py", "LOD_COST", ("lod_lightmap_cost",)),
    ("uv-unwrapping/scripts/uv_audit.py", "LIGHTMAP_BOX_FILL_NOTE", ("uv2_box_fill_note",)),
    ("rizomuv-uv-pipeline/scripts/rizom_uv.py", "LIGHTMAP_MIN_BOX_FILL", ("uv2_box_fill_note",)),
    ("vrchat-world-qa/scripts/qa_measure.py", "UV2_BOX_FILL_NOTE", ("uv2_box_fill_note",)),
    ("vrchat-lighting-and-baking/scripts/lightmap_budget.py", "BAKERY_AREA_FACTOR", ("bakery", "area_factor")),
    ("vrchat-lighting-and-baking/scripts/lightmap_budget.py", "BAKERY_INSET_TEXELS", ("bakery", "inset_texels")),
    ("vrchat-lighting-and-baking/scripts/lightmap_budget.py", "LIGHTMAPPERS", ("lightmappers",)),
    ("uv-unwrapping/scripts/uv_audit.py", "BAKERY_AREA_FACTOR", ("bakery", "area_factor")),
    ("uv-unwrapping/scripts/uv_audit.py", "BAKERY_INSET_TEXELS", ("bakery", "inset_texels")),
    ("uv-unwrapping/scripts/uv_audit.py", "LIGHTMAPPERS", ("lightmappers",)),
    ("uv-unwrapping/scripts/uv_audit.py", "EFFECTIVE_DENSITY_MIN", ("effective_density_min",)),
    ("rizomuv-uv-pipeline/scripts/rizom_uv.py", "BAKERY_AREA_FACTOR", ("bakery", "area_factor")),
    ("rizomuv-uv-pipeline/scripts/rizom_uv.py", "BAKERY_INSET_TEXELS", ("bakery", "inset_texels")),
    ("rizomuv-uv-pipeline/scripts/rizom_uv.py", "LIGHTMAPPERS", ("lightmappers",)),
    ("rizomuv-uv-pipeline/scripts/rizom_uv.py", "EFFECTIVE_DENSITY_MIN", ("effective_density_min",)),
    ("vrchat-world-qa/scripts/qa_measure.py", "BAKERY_AREA_FACTOR", ("bakery", "area_factor")),
    ("vrchat-world-qa/scripts/qa_measure.py", "BAKERY_INSET_TEXELS", ("bakery", "inset_texels")),
    ("vrchat-world-qa/scripts/qa_measure.py", "LIGHTMAPPERS", ("lightmappers",)),
    ("vrchat-world-qa/scripts/qa_measure.py", "EFFECTIVE_DENSITY_MIN", ("effective_density_min",)),
    ("vrchat-world-orchestration/scripts/spec_validate.py", "BAKERY_AREA_FACTOR", ("bakery", "area_factor")),
    ("vrchat-world-orchestration/scripts/spec_validate.py", "BAKERY_INSET_TEXELS", ("bakery", "inset_texels")),
    ("uv-unwrapping/scripts/uv_audit.py", "TOPOLOGY_TYPES", ("topology_types",)),
    ("blender-mesh-topology/scripts/hard_surface.py", "TOPOLOGY_TYPES", ("topology_types",)),
    ("blender-mesh-topology/scripts/detail_scale.py", "TEXEL_CLASSES", ("texel_class_edges",)),
    ("vrchat-world-orchestration/scripts/spec_validate.py", "ALBEDO_SRGB", ("pbr_albedo_srgb",)),
]

# The PBR checker ships identically in these skills (texturing self-checks, QA's X8 runs the same code).
PBR_CHECK_COPIES = ("pbr-texturing/scripts/pbr_check.py", "vrchat-world-qa/scripts/pbr_check.py")
TEXTURE_SEAMS_COPIES = ("pbr-texturing/scripts/texture_seams.py", "vrchat-world-qa/scripts/texture_seams.py")

# Text a file must contain because it states that fact: (CANON key, files).
TEXT_PRESENT = [
    ("mobile_limit_text", ["vrchat-world-optimization/SKILL.md", "vrchat-world-optimization/references/budgets.md",
                           "vrchat-world-sdk-setup/SKILL.md", "vrchat-world-sdk-setup/references/cross-platform.md",
                           "vrchat-texture-and-vram/SKILL.md", "vrchat-world-qa/references/checklists.md"]),
    ("manual_sync_text", ["vrchat-udon/SKILL.md", "vrchat-udon/references/networking-limits.md",
                          "vrchat-world-optimization/references/budgets.md"]),
    ("net_rate_text", ["vrchat-udon/SKILL.md", "vrchat-world-optimization/references/budgets.md"]),
    ("continuous_sync_text", ["vrchat-udon/SKILL.md", "vrchat-udon/references/networking-limits.md",
                              "vrchat-world-optimization/references/budgets.md"]),
    ("pc_download_text", ["vrchat-world-optimization/SKILL.md", "vrchat-world-optimization/references/budgets.md",
                          "vrchat-world-qa/references/checklists.md"]),
    ("astc_background_text", ["vrchat-texture-and-vram/SKILL.md", "vrchat-world-qa/references/checklists.md"]),
    ("astc_normal_text", ["vrchat-texture-and-vram/SKILL.md", "vrchat-world-qa/references/checklists.md"]),
    ("pbr_albedo_text", ["vrchat-world-qa/references/checklists.md", "vrchat-world-orchestration/references/world-spec.md",
                         "vrchat-world-orchestration/references/stages.md"]),
]

# A documented headless Blender run that executes Python must fail loudly: without --python-exit-code 1 an uncaught
# exception exits 0 and a failed run looks clean.
BLENDER_CMD = re.compile(r"""\bblender(?:\.exe)?["']?\s+(?:-b|--background)\b""")


def check_blender_commands():
    for rel in skill_text_files():
        lines = read(rel).splitlines()
        for i, line in enumerate(lines):
            if not BLENDER_CMD.search(line):
                continue
            cmd, indent, j = line, len(line) - len(line.lstrip()), i + 1
            while j < len(lines) and lines[j].strip() and (
                    len(lines[j]) - len(lines[j].lstrip()) > indent or lines[j - 1].rstrip().endswith(("\\", "^", "`"))):
                cmd += " " + lines[j].strip()
                j += 1
            if re.search(r"--python(?:-expr)?\s", cmd) and not re.search(r"--python-exit-code\s+1", cmd):
                fail(rel, "line %d: a headless Blender command without --python-exit-code 1" % (i + 1))

# Statements found wrong in the 2026-10-17 review. Each must never come back in any skill file.
FORBIDDEN = [
    (r"(?<![\d,.])280 bytes", "Manual sync carries about 280,496 bytes per serialization, not 280"),
    (r"VRC\.Editor\.UpdateLayers", "UpdateLayers is in the global namespace (VRCCore-Editor.dll)"),
    (r"10\^6 bytes|MB\s*=\s*10\^6", "VRChat's MB is 2^20 bytes (SDK ValidationHelpers.BYTES_TO_MB = 1048576)"),
    (r"(?i)VR clients render single[- ]pass instanced|VRChat( client)? renders? single[- ]pass instanced",
     "the VRChat client renders single-pass stereo, not SPS-I (developer update 2026-06-25)"),
    (r"VRC(Graphics|Shader)\b(?![^\n]*SDKBase)[^\n]{0,80}VRC\.SDK3\.Rendering"
     r"|VRC\.SDK3\.Rendering(?![^\n]*SDKBase)[^\n]{0,40}VRC(Graphics|Shader)\b",
     "VRCGraphics and VRCShader are in VRC.SDKBase (VRC.SDK3.Rendering holds VRCQualitySettings, VRCCameraSettings, ...)"),
    (r"(?i)drop MirrorReflection", "mirrors must reflect MirrorReflection (the local player) and not PlayerLocal"),
    (r"(?i)mobile shaders without an instancing variant|Standard Lite[^\n]{0,120}and has no GPU-instancing variant",
     "VRChat/Mobile/Standard Lite supports GPU instancing; only VRChat/Mobile/Lightmapped lacks it"),
    (r"(?i)add UdonSharp from (the )?VCC", "UdonSharp ships inside the Worlds SDK since 3.4.0"),
    (r"(?i)UV2[^\n]{0,60}padding for a (512|1024|2048) (light)?map|padding for a (512|1024|2048) lightmap",
     "UV2 padding is sized for each piece's own footprint"),
    (r"(?i)raise (pack margin )?to 8.16", "Generate Lightmap UVs: Margin Method Calculate, not a fixed Pack Margin"),
    (r"(?i)\(preferred\) or Unity \*\*Light Probes", "light probes are always required alongside Light Volumes"),
    (r"(?i)\*\*Subtractive\*\* on Quest", "cross-platform worlds keep every light Baked"),
    (r"(?i)not for the entire world, or you lose frustum", "static batching keeps per-object culling"),
    (r"(?i)Shader Graph shaders do not work in Built-in RP", "Shader Graph 14 has a Built-In target"),
    (r"(?i)scipy[^\n]{0,40}ships with Blender's Python", "Blender 5.2 bundles numpy but not scipy"),
    (r"(?i)occlusion culling does not apply inside reflections|does nothing (inside|for) mirrors",
     "mirrors use occlusion culling unless Turn Off Mirror Occlusion is ticked"),
    (r"(?i)Unity 6 BiRP build has been in open beta", "uploads from Unity 6 are rejected: never advise an upgrade"),
    (r"(?i)roughness/metallic/AO into one image|metallic/AO/roughness in one map",
     "Standard reads metallic from R and smoothness from A; occlusion is its own map"),
    (r"(?i)Empty list = the VRCWorld", "an empty spawn list is a build-blocking SDK error"),
    (r"(?i)error above 0\.75", "lightmap fill errors above 0.80 (CANON lightmap max)"),
    (r"(?i)thinner than half a module", "the Size token skips any axis under one module (thickness)"),
    (r"(?i)mobile renders no realtime", "Standard Lite still takes the main directional light (unshadowed); say why "
                                        "every light is Baked without claiming mobile renders none"),
    (r"(?i)UV2 (for|on) every lightmapped (piece|mesh)",
     "every kit render mesh carries a UV2 (LODs and probe-lit props too, not _COL); gaps matter on lightmapped ones"),
    (r"""(?i)^description:\s*[^"'\s][^\n]*: """, "a plain YAML description cannot hold ': ' (strict parsers reject it)"),
    # any generic Tuple<...> (new, a field, a return type, List<Tuple<...>>), System.Tuple<...> or Tuple.Create(;
    # ValueTuple and prose that names `System.Tuple` without type arguments pass
    (r"\bSystem\.Tuple\s*<|\bTuple\.Create\s*\(|(?<![\w.])Tuple\s*<",
     "ExCSS.Unity also defines System.Tuple, so MCP execute_code fails with CS0433: use KeyValuePair, a value tuple "
     "or an anonymous type"),
    # footprint^2 in any spelling (footprint_px^2, (footprint_px)^2, footprint_px(...) ** 2) and sum(footprint...;
    # "footprint_px^2 x b", the box's area, is the one correct use
    (r"footprint(?:_px)?(?:\([^)]*\))?\)?\s*(?:\^|\*\*)\s*2(?!\s*x\s*b\b)|sum\(footprint",
     "Unity packs each renderer's UV2 chart box (measured 2026-10-17): capacity sums (texels_per_m x Scale In "
     "Lightmap x LOD scale)^2 x A x copies x states, not footprint^2"),
    (r"https://wiki\.polycount\.com",
     "Polycount's https host refuses connections (checked 2026-10-17): cite http://wiki.polycount.com/..."),
    (r"(?i)reads? about (twice|double)",
     "the Profiler's runtime size can read up to twice the storage size (2x on 2026-10-16, 1.00-1.01x on 2026-10-17)"),
    # found wrong in the 2026-10-18 asset-quality review
    (r"(?i)mesh compression\W+low or medium|low or medium at ship time",
     "kit pieces keep Mesh Compression Off: Medium stepped tiling UVs 0.6 px at a joint and cut 2-texel UV2 gaps to "
     "1.8 texels (Unity 2022.3.22f1, measured 2026-10-18)"),
    (r"(?i)painter has no automation",
     "Painter 11.1's Python API bakes, layers smart materials and exports; an agent reaches it through a bridge"),
    (r"(?i)Lightmap Compression Normal Quality",
     "Lightmap Compression High Quality: on Windows Low, Normal and High store BC6H at the same size (measured "
     "2026-10-18)"),
    (r"(?i)T512 \(0-3 m\)|512 px/m at 0-3",
     "texel classes: T2048 under 0.75 m, T1024 0.75-1.5 m, T512 1.5-3 m (CANON texel_classes)"),
]

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
    """Each budget is one number no looser than the Quest target (it binds every platform), or a one-line
    per-platform mapping ({pc: 500000, quest: 250000}) whose values are no looser than each platform's target."""
    text = read(rel)
    for key in ("world_tris", "view_tris", "materials", "setpass", "batches", "texture_vram_mb"):
        m = re.search(r"^\s*%s:\s*(\d+|\{[^}\n]*\})" % key, text, re.M)
        if not m:
            fail(rel, "template budgets.%s missing" % key)
            continue
        if m.group(1).startswith("{"):
            values = {p: int(v) for p, v in re.findall(r"(\w+):\s*(\d+)", m.group(1))}
            if "quest" not in values:
                fail(rel, "budgets.%s per platform has no quest value" % key)
        else:
            values = {"quest": int(m.group(1))}
        for plat, v in values.items():
            want = CANON["budgets"].get("quest" if plat == "ios" else plat, {}).get(key)
            if want is None or v > want:
                fail(rel, "budgets.%s.%s = %d is looser than the %s target %s" % (key, plat, v, plat, want))


# ---- export settings, axes, kit_status, shared scripts -------------------------------------------------------------

FBX_TEXT = [r"-Z\s*Forward", r"Y\s*Up", r"FBX\s*All", r"Use Space Transform\W+on", r"Bake Space Transform(\s*\([^)]*\))?\W+on\b",
            r"Path\s*Mode[^\n]{0,40}Strip"]
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
    # raw bytes: copies that differ only in line endings are still different files on a linked install
    digests = {rel: hashlib.sha256(open(path(rel), "rb").read()).hexdigest() for rel in rels}
    if len(set(digests.values())) > 1:
        fail(rels[0], "copies differ: " + ", ".join(rels))


# ---- script constants, text copies, Unity version, known-wrong statements -----------------------------------------

def canon_value(keys):
    v = CANON
    for k in keys:
        v = v[k]
    return v


MISSING = object()


def module_constant(rel, name):
    """The literal value of a top-level `name = ...` in a script, or MISSING: a literal, dict(key=literal, ...), or
    frozenset(...) / set(...) of a literal (returned as a frozenset, compared without order)."""
    for node in ast.parse(read(rel)).body:
        if not isinstance(node, ast.Assign):
            continue
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id == name:
                v = node.value
                if isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id == "dict" and not v.args:
                    return {kw.arg: ast.literal_eval(kw.value) for kw in v.keywords}
                if (isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id in ("frozenset", "set")
                        and len(v.args) == 1 and not v.keywords):
                    return frozenset(ast.literal_eval(v.args[0]))
                return ast.literal_eval(v)
            if isinstance(t, ast.Tuple) and isinstance(node.value, ast.Tuple):     # A, B = 2.0, 1.0
                for target, value in zip(t.elts, node.value.elts):
                    if isinstance(target, ast.Name) and target.id == name:
                        return ast.literal_eval(value)
    return MISSING


QA_CITERS = ["vrchat-world-orchestration/SKILL.md", "vrchat-world-orchestration/references/stages.md",
             "vrchat-world-orchestration/references/subagent-briefs.md",
             "vrchat-world-orchestration/references/ledger.md", "vrchat-world-orchestration/references/world-spec.md",
             "vrchat-world-orchestration/references/mechanics.md",
             "vrchat-world-orchestration/references/texturing.md"]


def check_qa_ids():
    """Every QA check id orchestration cites (B1, U1-U6, ...) is a row in vrchat-world-qa's checklists."""
    rel = "vrchat-world-qa/references/checklists.md"
    rows = set(re.findall(r"^\|\s*([A-Z]\d{1,2})\s*\|", read(rel), re.M))
    if not rows:
        fail(rel, "no check rows found")
        return
    letters = "".join(sorted({r[0] for r in rows}))          # the check families QA defines (A, B, C, E, G, ...)
    qa_id = re.compile(r"\b([%s])(\d{1,2})(?:\s*-\s*\1?(\d{1,2}))?\b" % letters)
    for citer in QA_CITERS:
        for i, line in enumerate(read(citer).splitlines(), 1):
            if not re.search(r"(?i)\bQA\b|check", line):
                continue                             # ids are cited on QA / Checks lines
            for m in qa_id.finditer(line):
                letter, lo, hi = m.group(1), int(m.group(2)), int(m.group(3) or m.group(2))
                for n in range(lo, hi + 1):
                    if "%s%d" % (letter, n) not in rows:
                        fail(citer, "line %d cites QA check %s%d, which %s has no row for" % (i, letter, n, rel))


TASK_BRIEFS = "vrchat-world-orchestration/references/subagent-briefs.md"
QA_CHECKLISTS = "vrchat-world-qa/references/checklists.md"


def qa_check_ids(text, letters):
    """The QA check ids a text names, ranges expanded ("B2-B7, M9" -> B2 ... B7, M9), without G1-G5 (every task)."""
    found = set()
    for m in re.finditer(r"\b([%s])(\d{1,2})(?:\s*-\s*\1?(\d{1,2}))?\b" % letters, text):
        lo, hi = int(m.group(2)), int(m.group(3) or m.group(2))
        found.update("%s%d" % (m.group(1), n) for n in range(lo, hi + 1))
    return {c for c in found if not c.startswith("G")}


def check_task_checks():
    """Each filled brief in orchestration's subagent-briefs.md ("**Stage 6, T-UV-EXT (UV artist).** ... Checks:
    U1-U6 ...") names the same QA checks as vrchat-world-qa's "Checks per task" row for its kind of task
    (`T-UV-<FAMILY>`), so the builder's acceptance checks and QA's never drift apart (round 4 left T-RENAME's apart)."""
    text = read(QA_CHECKLISTS)
    letters = "".join(sorted(set(re.findall(r"^\|\s*([A-Z])\d{1,2}\s*\|", text, re.M))))
    parts = text.split("## Checks per task", 1)
    if len(parts) < 2 or not letters:
        fail(QA_CHECKLISTS, 'no "Checks per task" table or no check rows')
        return
    rows = {}
    for line in parts[1].split("\n## ", 1)[0].splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3:
            for task in re.findall(r"`(T-[^`]+)`", cells[1]):
                rows[task] = qa_check_ids(cells[2], letters)

    def row_for(task):
        """The row for a concrete task id: an exact row (T-GREY-MASTER), else the longest matching pattern."""
        if task in rows:
            return task
        hits = [t for t in rows
                if re.match("^%s$" % "[A-Z0-9-]+".join(map(re.escape, re.split(r"<[^>]+>", t))), task)]
        return max(hits, key=len) if hits else None

    briefs = read(TASK_BRIEFS)
    found = 0
    for m in re.finditer(r"\*\*(?:Stages? [\d-]+(?: in small mode)?|Any stage after \d+), (T-[A-Z0-9-]+)[^*]*\*\*"
                         r"(.*?)(?=\n\n|\*\*Stages? \d|\*\*Any stage|\Z)", briefs, re.S):
        found += 1
        task, line = m.group(1), briefs.count("\n", 0, m.start()) + 1
        named = re.search(r"\bChecks:\s*(.*?)(?:\.\s|\Z)", m.group(2), re.S)
        row = row_for(task)
        if not named:
            fail(TASK_BRIEFS, "line %d: the %s brief names no Checks" % (line, task))
        elif row is None:
            fail(TASK_BRIEFS, "line %d: %s has no row in %s's Checks per task" % (line, task, QA_CHECKLISTS))
        elif qa_check_ids(named.group(1), letters) != rows[row]:
            fail(TASK_BRIEFS, "line %d: %s's brief checks %s, QA's row %s checks %s"
                 % (line, task, sorted(qa_check_ids(named.group(1), letters)), row, sorted(rows[row])))
    if not found:
        fail(TASK_BRIEFS, 'no "**Stage <n>, T-...**" briefs found to compare with QA\'s rows')


def check_tile_phase():
    """The half-texel tolerance a tiling face or placement may sit off the tile grid: uv_audit (each face), the spec
    validator and qa_measure (each placement); and the phase-variant suffix the two placement checks read."""
    for rel, name in (("uv-unwrapping/scripts/uv_audit.py", "TILE_PHASE_PX"),
                      ("vrchat-world-orchestration/scripts/spec_validate.py", "TILE_PHASE_TEXELS"),
                      ("vrchat-world-qa/scripts/qa_measure.py", "TILE_PHASE_TEXELS")):
        got = module_constant(rel, name)
        if got != CANON["tile_phase_texels"]:
            fail(rel, "%s is %r, canon %r" % (name, got, CANON["tile_phase_texels"]))
    pat = r'PHASE_VARIANT_RE = re\.compile\((r"[^"]*")\)'
    a = re.search(pat, read("vrchat-world-orchestration/scripts/spec_validate.py"))
    b = re.search(pat, read("vrchat-world-qa/scripts/qa_measure.py"))
    if not (a and b and a.group(1) == b.group(1)):
        fail("vrchat-world-qa/scripts/qa_measure.py", "PHASE_VARIANT_RE differs from spec_validate's (or is missing)")
    for rel in ("vrchat-world-orchestration/scripts/spec_validate.py", "vrchat-world-qa/scripts/qa_measure.py"):
        got = module_constant(rel, "FREE_SCALE_BAND")
        if got != CANON["free_scale_band"]:
            fail(rel, "FREE_SCALE_BAND is %r, canon %r" % (got, CANON["free_scale_band"]))


def check_uv_gate():
    """uv-unwrapping's LIMITS and RizomUV's GATE carry the same distortion gate; uv_audit's TEXEL_BAND the bands."""
    for rel, name, rename in (("uv-unwrapping/scripts/uv_audit.py", "LIMITS", {}),
                              ("rizomuv-uv-pipeline/scripts/uv_metrics.py", "GATE",
                               {"area_p95": "area_local_p95", "area_max": "area_local_max",
                                "island_area_p95": "island_area_local_p95"})):
        got = module_constant(rel, name)
        if got is MISSING:
            fail(rel, "no %s dict" % name)
            continue
        for k, want in CANON["uv_gate"].items():
            if got.get(rename.get(k, k)) != want:
                fail(rel, "%s[%r] is %r, canon %r" % (name, rename.get(k, k), got.get(rename.get(k, k)), want))
        if module_constant(rel, "ISLAND_MIN_SHARE") != CANON["uv_island_min_share"]:
            fail(rel, "ISLAND_MIN_SHARE is %r, canon %r" % (module_constant(rel, "ISLAND_MIN_SHARE"),
                                                           CANON["uv_island_min_share"]))
    rel = "uv-unwrapping/scripts/uv_audit.py"
    bands = module_constant(rel, "TEXEL_BAND")
    for purpose, want in CANON["texel_band"].items():
        if bands is MISSING or tuple(bands.get(purpose, ())) != want:
            fail(rel, "TEXEL_BAND[%r] is not %r" % (purpose, want))


def check_fbx_and_import():
    rel = "blender-to-unity/scripts/batch_export_fbx.py"
    got = module_constant(rel, "FBX_SETTINGS")
    want = CANON["fbx_export"]
    if got is MISSING:
        fail(rel, "no FBX_SETTINGS dict")
    else:
        for k in sorted(set(got) | set(want)):
            if got.get(k, MISSING) != want.get(k, MISSING):
                fail(rel, "FBX_SETTINGS %s is %r, canon %r" % (k, got.get(k, "(missing)"), want.get(k, "(missing)")))
    if module_constant(rel, "KIT_PATH_MODE") != CANON["kit_path_mode"]:
        fail(rel, "KIT_PATH_MODE is not %r" % CANON["kit_path_mode"])
    rel = "blender-to-unity/scripts/unity/Editor/KitImport.cs"
    text = read(rel)
    for prop, value in CANON["unity_import"].items():
        if not re.search(r"importer\.%s\s*=\s*%s\s*;" % (re.escape(prop), re.escape(value)), text):
            fail(rel, "does not set importer.%s = %s" % (prop, value))


def check_constants():
    for rel, name, keys in CONSTANTS:
        if not os.path.exists(path(rel)):
            fail(rel, "file missing (expected constant %s)" % name)
            continue
        try:
            got = module_constant(rel, name)
        except ValueError:
            fail(rel, "%s is not a literal" % name)
            continue
        want = canon_value(keys)
        if got is MISSING:
            fail(rel, "no %s found" % name)
        elif isinstance(got, frozenset):
            if got != frozenset(want):
                fail(rel, "%s differs from canon %s: missing %s, not in canon %s"
                     % (name, "/".join(keys), sorted(frozenset(want) - got), sorted(got - frozenset(want))))
        elif (list(got) if isinstance(got, tuple) else got) != want:
            fail(rel, "%s is %r, canon %r" % (name, got, want))


def check_text_present():
    for key, rels in TEXT_PRESENT:
        for rel in rels:
            if CANON[key] not in read(rel):
                fail(rel, "does not state %s" % CANON[key])


def skill_text_files():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if f.endswith((".md", ".py", ".cs", ".shader", ".yaml", ".yml", ".json")):
                full = os.path.join(base, f)
                yield os.path.relpath(full, ROOT).replace("\\", "/")


def check_versions_and_forbidden():
    for rel in skill_text_files():
        text = read(rel)
        for m in re.finditer(r"\b20\d\d\.\d+\.\d+f\d+\b", text):
            if m.group(0) != CANON["unity_version"] and m.group(0) not in CANON["other_unity_versions"]:
                fail(rel, "Unity version %s, canon %s" % (m.group(0), CANON["unity_version"]))
        for pat, why in FORBIDDEN:
            for m in re.finditer(pat, text, re.M):
                line = text.count("\n", 0, m.start()) + 1
                fail(rel, "line %d says %r: %s" % (line, m.group(0), why))
        # code that calls VRCGraphics / VRCShader needs `using VRC.SDKBase;`, not only VRC.SDK3.Rendering
        if re.search(r"\bVRC(Graphics|Shader)\.", text) and "using VRC.SDK3.Rendering;" in text \
                and "using VRC.SDKBase;" not in text:
            fail(rel, "uses VRCGraphics/VRCShader with `using VRC.SDK3.Rendering;` but without `using VRC.SDKBase;`")


def main():
    check_regex_py("blender-kit-library/scripts/kit_library.py", "NAME_RE", "piece_re")
    check_regex_py("blender-kit-library/scripts/kit_library.py", "ASM_RE", "asm_re")
    check_regex_py("vrchat-world-orchestration/scripts/spec_validate.py", "NAME_RE", "piece_re")
    check_regex_py("vrchat-world-orchestration/scripts/spec_validate.py", "ASM_RE", "asm_re")
    check_regex_py("vrchat-world-qa/scripts/qa_measure.py", "NAME_RE", "piece_re")
    check_regex_py("vrchat-world-qa/scripts/qa_measure.py", "ASM_RE", "asm_re")
    check_regex_py("vrchat-world-qa/scripts/qa_measure.py", "MAT_RE", "material_re")
    check_regex_py("vrchat-world-orchestration/scripts/spec_validate.py", "MAT_RE", "material_re")
    check_regex_py("blender-kit-library/scripts/kit_library.py", "MAT_RE", "material_re")
    check_regex_py("blender-kit-library/scripts/kit_library.py", "ASM_RE", "asm_re")
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
    if 'PLATFORM_LIMITS["ios"] = PLATFORM_LIMITS["quest"]' not in read("vrchat-world-orchestration/scripts/spec_validate.py"):
        fail("vrchat-world-orchestration/scripts/spec_validate.py", "ios must use the Quest limits")
    check_budget_template("vrchat-world-orchestration/templates/spec.yaml")
    check_budget_template("vrchat-world-orchestration/references/example-spec.yaml")

    check_patterns("blender-to-unity/scripts/batch_export_fbx.py", FBX_CODE, "FBX settings")
    check_regex_py("blender-to-unity/scripts/batch_export_fbx.py", "PIECE_RE", "piece_re")
    check_fbx_and_import()
    for rel in ("blender-to-unity/references/fbx-export.md",
                "blender-unity-placement-sync/SKILL.md",
                "vrchat-world-orchestration/references/stages.md"):
        check_patterns(rel, FBX_TEXT, "FBX settings")

    check_axis_matrix("blender-unity-placement-sync/scripts/export_placements.py")
    for rel in ("blender-unity-placement-sync/SKILL.md", "vrchat-world-qa/references/visual-review.md"):
        if CANON["axis_text"] not in read(rel):
            fail(rel, "does not state the axis conversion %s" % CANON["axis_text"])

    # the five values in order on one line; a few words may sit between them ("`grey` at stage 4, `modelled` 5")
    status_re = r"[^\n]{1,25}?".join("`?%s`?" % s for s in CANON["kit_status"])
    for rel in ("vrchat-world-orchestration/SKILL.md", "vrchat-world-orchestration/references/world-spec.md",
                "blender-kit-library/SKILL.md", "vrchat-world-qa/references/checklists.md"):
        if not re.search(status_re, read(rel)):
            fail(rel, "kit_status values are not %s" % ", ".join(CANON["kit_status"]))

    for rel in ("uv-unwrapping/SKILL.md", "uv-unwrapping/references/texel-density.md",
                "rizomuv-uv-pipeline/SKILL.md", "rizomuv-uv-pipeline/references/texel-density.md"):
        text = read(rel)
        if CANON["texel_rule"] not in text:
            fail(rel, "does not state the texel rule %s" % CANON["texel_rule"])
        if rel.endswith("rizomuv-uv-pipeline/SKILL.md"):
            listed = " / ".join(px for px, _dist in CANON["texel_classes"])
            if listed not in text:
                fail(rel, "texel classes are not %s" % listed)
            continue
        for px, dist in CANON["texel_classes"]:
            # the class and its distance band appear together on one line (a table row or a sentence)
            if not any(re.search(r"(?<!\d)%s(?!\d)" % px, line) and dist in line for line in text.splitlines()):
                fail(rel, "texel class %s px/m at %s m not found" % (px, dist))

    check_identical("blender-kit-library/scripts/kit_library.py",
                    "vrchat-world-orchestration/scripts/kit_library.py")
    check_identical(*PBR_CHECK_COPIES)
    check_identical(*TEXTURE_SEAMS_COPIES)
    for rel in PBR_CHECK_COPIES:
        limits = module_constant(rel, "PBR_LIMITS")
        if limits is MISSING or list(limits.get("albedo_srgb", ())) != CANON["pbr_albedo_srgb"]:
            fail(rel, "PBR_LIMITS albedo_srgb is not %r" % (CANON["pbr_albedo_srgb"],))

    edges = CANON["texel_class_edges"]
    bands = ["< %g" % edges[1][1]] + ["%g-%g" % (a[1], b[1]) for a, b in zip(edges[1:], edges[2:])] \
        + ["> %g" % edges[-1][1]]
    if [(str(px), band) for (px, _d), band in zip(edges, bands)] != CANON["texel_classes"]:
        fail("../tools/check_conventions.py", "CANON texel_classes %r and texel_class_edges %r disagree"
             % (CANON["texel_classes"], edges))
    if abs(CANON["lod_lightmap_cost"] - CANON["lod_lightmap_scale"] ** 2) > 1e-12:
        fail("../tools/check_conventions.py", "CANON lod_lightmap_cost %r is not lod_lightmap_scale %r squared"
             % (CANON["lod_lightmap_cost"], CANON["lod_lightmap_scale"]))
    check_constants()
    check_uv_gate()
    check_tile_phase()
    check_qa_ids()
    check_task_checks()
    check_blender_commands()
    check_text_present()
    check_versions_and_forbidden()

    if FAIL:
        print("\n".join("MISMATCH " + f for f in FAIL))
        print("%d mismatch(es)" % len(FAIL))
        sys.exit(1)
    print("conventions agree across skills")


if __name__ == "__main__":
    main()
