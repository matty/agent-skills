# Lightmap UVs (UV2): rules, failure modes, fixes

Unity bakes lightmaps into the **second UV channel** (`UV1` in Blender terms / `uv2`/`TEXCOORD1` in shaders). Everything that goes wrong with bakes goes wrong here first.

## Hard rules

1. **No overlapping islands.** Overlap means two surfaces share texels; one room's shadow appears on another wall. (UV0 for textures *may* overlap and tile; UV2 may not.)
2. **Everything inside 0–1 space.** Anything outside is undefined.
3. **Padding between islands** ≥ 2 texels at the *final baked* resolution, more for low resolutions. Too little padding = light bleeding across seams after mipmapping and filtering.
4. **Split islands on hard angles.** Continuing a UV island across a 90° corner smears the shadow terminator around it.
5. **Roughly uniform texel density per object**, then use *Scale In Lightmap* per renderer to weight importance.

## Authoring UV2 in Blender (preferred)

Control beats Unity's automatic packer for hero geometry:

1. Add a second UV map named `UVMap.001` / `Lightmap` (Object Data Properties → UV Maps → +). Order matters, not name: the second slot becomes UV2 in Unity.
2. With it active: `U → Lightmap Pack` (island margin ~0.2–0.4), or `Smart UV Project` (angle limit 66°, island margin 0.02–0.05) for cleaner results on architectural shapes.
3. `UV → Average Islands Scale` then re-pack to equalize texel density.
4. Keep the mesh's UV0 untouched — re-unwrapping the wrong channel is the most common accident.
5. Export FBX with both UV layers (default). In Unity, leave *Generate Lightmap UVs* **off** for these meshes.

There is a ready script at `../../blender-to-unity-vrchat/scripts/lightmap_uv2.py` that adds and packs a second UV channel across selected objects with a consistent margin.

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

Lightmap resolution is *texels per unit* and units are metres.

| Surface | Texels/unit |
|---|---|
| Large outdoor terrain, skybox-lit ground | 2–5 |
| General interior walls/floors | 8–15 |
| Hero surface with crisp contact shadows | 20–40 |
| Small props | let Scale In Lightmap drop them to 0.25–0.5× |

Set the scene value at the low end and promote individual renderers. That is the single biggest lever on bake time and build size.
