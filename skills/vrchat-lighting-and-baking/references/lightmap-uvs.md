# Lightmap UVs (UV2): rules, failure modes, fixes

Unity bakes lightmaps into the **second UV channel** (`UV1` in Blender terms / `uv2`/`TEXCOORD1` in shaders). Everything that goes wrong with bakes goes wrong here first.

## Hard rules

1. **No overlapping islands.** Overlap means two surfaces share texels; one room's shadow appears on another wall. (UV0 for textures *may* overlap and tile; UV2 may not.)
2. **Everything inside 0–1 space.** Anything outside is undefined.
3. **Padding between islands** ≥ 2 texels at the *final baked* resolution, more for low resolutions. Too little padding = light bleeding across seams after mipmapping and filtering.
4. **Split islands on hard angles.** Continuing a UV island across a 90° corner smears the shadow terminator around it.
5. **Roughly uniform texel density per object**, then use *Scale In Lightmap* per renderer to weight importance.

## Authoring UV2 in Blender (preferred)

Control beats Unity's automatic packer for hero geometry. How to make a good UV2 is the `uv-unwrapping` skill's
job (and `rizomuv-uv-pipeline` automates it); without either, the minimum that bakes cleanly:

1. Add a **second** UV map (order matters, not name: the second slot becomes UV2 in Unity). Never re-unwrap UV0 by
   accident: make the new map active first.
2. Unwrap it into few, large charts cut at hard angles: Smart UV Project at about 66 deg works for architecture.
   Blender's Lightmap Pack makes one chart per face and suits only very simple meshes.
3. Average Islands Scale, then pack with padding in **pixels at the rectangle the mesh will get in the lightmap**
   (its footprint, below), not at 1024: 2 texels minimum, 4 safer. A margin chosen for a whole 1024 map is a
   fraction of a texel on a small object and bleeds.
4. Export with both UV layers; in Unity leave *Generate Lightmap UVs* **off** for these meshes.

Footprint in pixels = sqrt(surface area in m2) x lightmap texels per metre x Scale In Lightmap, divided by about
sqrt(0.7-0.85) when the charts do not fill their square (measured 2026-10-16 in Unity 2022.3: a 2 x 3 x 0.2 m wall at
60 texels/m got 243 px, a 2 x 2 x 0.1 m slab 200 px).

How many renderers fit one lightmap: Unity packs each renderer's UV2 rectangle whole, without rotating it, and spills
into a second map once the rectangles fill about 0.75-0.8 of it (same test: 16 renderers filled one 512 map at 113 px
each, and spilled at 121 px). So the padding rule is also a capacity rule: if every piece needs 128 px to keep its
UV2 gaps at 2 texels, a 512 map holds about 12 of them. Check the sum of footprints squared against 0.65 x the map
area before choosing the lightmap size, not after the bake.

Unity 2022.3 notes: the lightmapper is `LightingSettings.lightmapper`; lightmap padding clamps to at least 2; and
`Lightmapping.buildProgress` stays at 0 while the GPU lightmapper compiles its kernels on the first bake (about 45 s),
so watch the Editor log rather than the progress value.

## Letting Unity generate them

Fine for kitbash props and anything non-hero. Mesh importer → *Generate Lightmap UVs*, then tune under Advanced:

| Setting | Effect |
|---|---|
| Hard Angle (default 88) | Lower → more splits, fewer smeared corners |
| Angle Error (default 8) | Lower → more faithful, more islands |
| Area Error (default 15) | Lower → less distortion |
| Pack Margin (default 4) | **Raise to 8–16** for low texel densities; the default bleeds |

Unity regenerates on every reimport, so a change to the mesh reshuffles the atlas and invalidates the bake — expect to re-bake.

## Symptom → cause

| Symptom | Cause |
|---|---|
| Shadow of one object appearing on an unrelated surface | Overlapping UV2 islands |
| Dark or bright fringes along island borders | Insufficient pack margin / too-low texel density |
| Blocky, pixelated shadows | Texel density too low — raise Scale In Lightmap for that renderer, not the whole scene |
| Visible seams across a flat wall | Islands split where they should be continuous, or no seam stitching |
| Only part of a mesh is lit | UV2 island outside 0–1, or the mesh is not Contribute GI |
| Bake time exploded and 6 lightmaps appeared | Scene lightmap resolution too high, or Scale In Lightmap left high on large meshes |
| Lightmaps enormous in the build | Resolution × map count; also Directional mode (doubles data) |

## Practical texel-density guide

Lightmap resolution is *texels per unit* and units are metres. This skill owns these numbers.

| Surface | Texels/unit |
|---|---|
| Large outdoor terrain, skybox-lit ground | 2-5 |
| Facades and exteriors seen from a distance | 6-10 |
| General interior walls/floors | 10-20 |
| Hero surface with crisp contact shadows | 20-40 |
| Small props | let Scale In Lightmap drop them to 0.25-0.5x |

Set the scene value at the low end and promote individual renderers. That is the single biggest lever on bake time and build size.
