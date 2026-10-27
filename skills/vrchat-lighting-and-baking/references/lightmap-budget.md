# Lightmap budget: footprint, gaps, capacity, LODs, verification

How big each renderer is in a lightmap, whether its UV2 gaps survive at that size, and whether everything fits.
Measured in Unity 2022.3.22f1 with the Progressive GPU lightmapper: the dry run (2026-10-16, one room, 17 lightmapped
renderers) and dedicated packing and LOD bakes (2026-10-17). Bakery sizes renderers differently: section Bakery.
`scripts/lightmap_budget.py` does the arithmetic below (`--lightmapper bakery` for Bakery's).

## What Unity packs: the chart box

Unity packs each renderer's UV2 **chart box** (the bounding box of all its UV2 charts together) into the lightmap,
unrotated, not its whole 0-1 tile. Measured 2026-10-17: other renderers' boxes sat inside one renderer's scaled tile
but outside its box, boxes sat exactly the Lightmap Padding apart, and one tile even started outside the atlas. Unity
rounds the box's longer side to whole texels.

## Footprint (texel scale), Unity Progressive

The footprint is how many lightmap pixels one UV unit spans, the side of the renderer's scaled 0-1 tile:

    footprint_px = texels_per_m x sqrt(A / b) x Scale In Lightmap x LOD scale

- A = the mesh's surface area in m2 (for a box-like piece, 2(xy + yz + xz) is close enough).
- b = the area of the UV2 charts' bounding box (all charts together) as a share of the 0-1 tile. Plan with b = 0.85
  before the UV2 exists; check with the mesh's measured b. LOD scale is 0.5^n for LODn (1 for LOD0).
- Measured: b predicts what Unity gave within 0.6% (exact for b from 0.125 to 1 in the 2026-10-17 bakes), and the
  charts' own area does not (7-23% off):

| Mesh (60 texels/m, dry run) | b | Predicted | Unity gave |
|---|---|---|---|
| Wall 2 x 3 x 0.2 m | 0.850 | 243.5 px | 242.8 px |
| Door | 0.909 | 237.3 px | 236.7 px |
| Floor 2 x 2 x 0.1 m | 0.788 | 200.5 px | 200.3 px |
| Desk | 0.952 | 144.2 px | 143.4 px |

- After a bake, read the real value: footprint_px = renderer.lightmapScaleOffset.x x the lightmap's width.
- Space inside the box costs texels even where no chart sits: the surface gets an effective density of
  texels_per_m x sqrt(charts' area / box area). Pack the charts to fill their box; its aspect ratio does not matter (a
  long corridor's chart along U costs nothing extra).

## Gaps

A UV2 gap of g (in UV units) is g x footprint_px texels in the lightmap. Keep it at 2 texels or more between charts
and 1 or more to the tile edge, or neighbouring charts share texels and bleed (Unity reports them as overlapping UVs).

| Need | Formula |
|---|---|
| Gap to pack | g = 2 / (texels_per_m x sqrt(A) x Scale In Lightmap): 2 texels at the worst case b = 1, so it holds whatever the packer does (a full pack's bounding box approaches the whole tile) |
| Check after packing | g x footprint_px >= 2 at the mesh's measured b; after the bake, at the footprint Unity gave |
| Lowest Lightmap Resolution a packed UV2 tolerates | texels_per_m >= 2 / (g x sqrt(A / b) x Scale In Lightmap), with b = 1 until it is measured |

Pack the UV2 for the footprint the mesh will get (the `uv-unwrapping` skill packs to a pixel size), not for a whole
1024 map: a margin chosen for 1024 is a fraction of a texel on a 128 px footprint. Never lower Scale In Lightmap
below what the gaps were packed for. Example, the dry run's desk at 60 texels/m: gaps packed for 2 texels at the
0.85 plan (152.6 px) come to 1.89 texels at its real b (0.952, 144.2 px); packed for b = 1 they come to 2.05.

## Under 64 px (house guidance, no published source)

| Piece | Under 64 px |
|---|---|
| Free prop: a Free-sized piece of the PROP or FOL family | Probe-lit: Contribute GI on, Receive Global Illumination = Light Probes (it still bounces light into the bake), and it takes no lightmap space |
| Grid piece (walls, floors, ceilings, facades, ZONE shells) | Never probe-lit by this rule, and never a blocker: a note only. Probe-lit objects get "constant ambient lighting across the surface", which "is more noticeable on larger GameObjects" (https://docs.unity3d.com/2022.3/Documentation/Manual/class-LightProbeProxyVolume.html). It stays lightmapped and counted; raise its Scale In Lightmap where its lighting detail matters |
| A prop that must change with a light switch | Lightmapped in every state copy whatever its size, and counted per state (the script's KIND `lightmap`) |

At the 10-20 texels/m this skill recommends for interiors, a 2 x 3 x 0.2 m wall is about 61 px at 15 texels/m, and
facades at 6-10 texels/m sit under 64 px too, so a blanket rule would make whole rooms and streets probe-lit. In the
script, KIND grid (alias shell) is a grid piece, and it is the default for every name except a Free-sized piece of a
`PROBE_LIT_FAMILIES` family (PROP, FOL): a Free-sized ZONE shell (terrain, a building shell) is a grid piece.

## Capacity

A renderer's chart box costs footprint_px^2 x b = (texels_per_m x Scale In Lightmap x LOD scale)^2 x A pixels,
whatever its UV2 layout (measured 24,002 px^2 against 24,000 predicted). Plan with:

    sum((texels_per_m x Scale In Lightmap x LOD scale)^2 x A x copies x lighting states)
        <= 0.65 x max_px^2 x lightmap count            warn above 0.65, error above 0.80

Measured (Unity 2022.3.22f1, Progressive GPU, Lightmap Padding 2, one 512 map, 2026-10-17), as box fill:

- 16 equal full-tile squares pack in an exact grid (n x side + (n - 1) x padding <= the map side) and fit up to
  0.97 of the map (126 px each); at 127 px they spill.
- Four kit-like sets of 30 boxes (aspects 1:1 to 1:6, long sides spread 1:10, about 22-320 px at the spill) spilled
  at 0.79, 0.84, 0.87 and 0.90 (mean 0.85).
  A set that spills moves only 1-2 boxes into a small second map (128-256 px).
- A larger Lightmap Padding lowers every spill: at padding 10 the same squares fit up to 120 px (0.88) and spill at
  121 px (0.89).
- The dry run's final bake, 7 walls, a door, 8 slabs and a desk at 60 texels/m, fitted one 1024 map at about 0.65 as
  chart boxes (the formula above; 0.77 counted as whole scaled tiles).

So plan to 0.65. Between 0.65 and 0.80 a spill is possible; above 0.80 one is likely (one mixed set already spilled
at 0.791). These thresholds assume Lightmap Padding 2.

Max Lightmap Size is 1024 whenever the world ships to Quest or iOS (one bake serves every platform), 2048 only in a
PC-only world. Lighting states multiply the count: every switched piece is baked once per state.

The same dry run's first bake (one 512 map, every grid piece at about 113 px) also failed on the gaps: its
8 px @ 512 UV2 gaps came to 1.76 texels, and Unity reported overlapping UVs on the ceiling slabs.

## LODs

LOD1 and beyond are lightmapped by default (Receive Global Illumination = Lightmaps), each in its own atlas space, at
LOD scale 0.5^n of LOD0's texel scale (measured 0.995 / 0.492 / 0.250 for LOD0-2, whatever the LOD transition
heights; Unity's own LOD level scale reads 1 / 0.5 / 0.25). So:

| | Rule |
|---|---|
| Cost of LODn | 0.25^n x (texels_per_m x Scale In Lightmap)^2 x A_n: LOD1 and LOD2 of similar area make the piece cost about 1.31x its LOD0 |
| UV2 gaps of LODn | Packed and checked at its own footprint: g = 2 / (texels_per_m x sqrt(A_n) x Scale In Lightmap x 0.5^n), so LOD1 needs gaps twice LOD0's in UV units |
| LOD1+ probe-lit | Receive Global Illumination = Light Probes takes a LOD out of the atlas (measured), but its lighting changes at the LOD switch |

`lightmap_budget.py` takes `lods` (LODs after LOD0) and `lod_lightmap: false` (LOD1+ probe-lit) per piece, read as
in the world spec, and prints each LOD's footprint, cost and pack gap.

## Bakery: footprint, gaps, density, capacity

Read from Bakery's scripts as installed in a Unity 2022.3.22f1 project, 2026-10-24 (the scripts carry no version
string): `Assets/Editor/x64/Bakery/scripts/ftBuildGraphics.cs` (the area loop in `CalculateHolderUVBounds`,
`ApplyAreaToUVBounds`, `Pack`, the xatlas pack, `NormalizeAutoAtlases`) and `Assets/Bakery/BakeryProjectSettings.cs`
(the defaults). With Bakery's defaults: Alternative Scale In Lightmap off (on, it treats Scale In Lightmap linearly
and rounds sizes: this section does not apply) and Hole Filling off. Measured in a bake on 2026-10-27 (below); the
cinema numbers are the repo owner's (GitHub issue #8). `lightmap_budget.py --lightmapper bakery` does the arithmetic.

| | Unity Progressive | Bakery |
|---|---|---|
| What sizes a renderer | its area and b: texels_per_m x sqrt(A / b) x S per UV unit | its area only: a rect of side L = texels_per_m x sqrt(2 x A x S) texels. The area loop sums abs(cross) over the triangles (2 x A); the division by the UV area is commented out ("uv layouts always have empty spaces") |
| Scale In Lightmap S | linear | multiplies the area (`area *= scaleInLm` before `ApplyAreaToUVBounds`): a linear factor s needs S = s^2 |
| UV2 bounds' aspect | free: the box costs (texels_per_m x S)^2 x A whatever its shape | L goes to the bounds' short side, L x aspect to the long side: a thin column of charts in bounds 0.06 x 1 costs 1 / 0.06, about 17 times L^2 (issue #8: about 15x its area) |
| Rect edge | Lightmap Padding between boxes | Default packer: the rect is inset `texelPaddingForDefaultAtlasPacker` (3) texels on every side, then the bounds are mapped onto what is left. xatlas: no inset, `texelPaddingForXatlasAtlasPacker` texels between rects (1 by default; read the project's `BakeryProjectSettings`: 2 in the cinema). ftBuildGraphics' static default is xatlas; the scene's Bakery settings can pick either |
| LODs | 0.5^n of LOD0's texel scale | no LOD factor: each LOD is sized by its own area; `Pack` keeps each scene LOD level in lightmaps of its own; a `BakerySharedLodUv` component on the LOD Group makes LOD1+ share LOD0's |
| A part-empty lightmap | as packed | the Default packer scales every rect up to fill it (`NormalizeAutoAtlases`), never down: the footprint below is a floor |
| A rect longer than the map | (one tile) | Default packer: the long side is clamped to the map and the short side keeps its footprint, so density is uneven. xatlas: the whole chart shrinks to fit the lightmap group's resolution, so both sides lose density (measured) |

Footprint, the same along both axes:

    footprint_px = (L - 2 x p) / w_short,    L = texels_per_m x sqrt(2 x A x S)

- w_short = the short side of the UV2 charts' bounding box in UV units (1 when it fills the tile); p = 3 under the
  Default packer, 0 under xatlas. The scripts assume p = 3, which holds under both.
- Gaps: pack for the box filling the tile, gap in UV = 2 / (L - 6), and 1 texel to the edge. `uv-unwrapping`'s
  `pack_lightmap` and `rizomuv-uv-pipeline` do it with `lightmapper="bakery"`.
- Against Unity at S = 1 with square bounds, the footprint is sqrt(2) = 1.41 times Unity's before the inset, more for
  oblong bounds. Gaps packed for Unity's b = 1 footprint (texels_per_m x sqrt(A) x S) hold under Bakery while
  sqrt(2 x S) >= S x w_short: always up to S = 2 under xatlas. The Default packer's 6 texels break them on small rects
  (Unity footprints under about 15 px at S = 1), and above S = 2 they can fail anywhere: repack for Bakery.

Measured in a bake (2026-10-27, Bakery as installed in the cinema's Unity 2022.3.22f1 project, Texels Per Unit 20,
throwaway scene): five quads, `lightmapScaleOffset` x the lightmap's size.

| Renderer | A (m2), S, UV2 bounds | Formula (px per UV unit) | Default packer | xatlas |
|---|---|---|---|---|
| oblong | 2, 1, 1 x 0.125 | (40 - 6) / 0.125 = 272 | short side 272, exact; long side clamped to 122 (the 128 map less 6) | about 34 texels on the short side (formula 40): shrunk to fit |
| oblong | 2, 4, 1 x 0.125 | (80 - 6) / 0.125 = 592 | short side 592, exact; long side clamped | about 33 (formula 80): shrunk to fit |
| square | 1, 1, 1 x 1 | 28.3 - 6 = 22.3 | 30.3 (alone in its own 32 px map, scaled up to fill it) | 31 texels |
| square | 4, 1, 1 x 1 | 56.6 - 6 = 50.6 | 60.6 (own 64 px map) | 59 texels |
| square | 4, 4, 1 x 1 | 113.1 - 6 = 107.1 | 121.2 (own 128 px map) | 115 texels |

- The short-side footprint, the 3-texel inset and sqrt(S) hold exactly where nothing rescales the rect: S = 4
  doubles the footprint under both packers, never quadruples it.
- A part-empty atlas scales rects up, never down: the footprint above is a floor, as planned.
- xatlas gives each chart about L plus its padding, so p = 0 is a floor too, while the chart fits. Its atlas is then
  stretched onto a square texture: here a 255 x 195 texel atlas went onto a 256 x 256 lightmap, so V got 1.31 times
  the texels of U. Read both axes of `lightmapScaleOffset`, and gate on the smaller.
- An oblong UV2 long enough to pass the map loses density under either packer: the Default packer on its long side
  only, xatlas on both. Lay UV2 charts out so their bounds stay near square.

Effective density, the texels per metre the surface gets, for either lightmapper:

    effective_texels_per_m = footprint_px x sqrt(a / A),    a = the UV2 charts' own area in UV units

- Bakery: about texels_per_m x sqrt(2 x S x a) / w_short (xatlas). Unity: texels_per_m x S x sqrt(charts' area / box
  area). Neither looks at the charts' area when it sizes a renderer, so charts that fill little of their box bake at
  little density. The usual cause is many charts packed for a small footprint, where 2-texel gaps take most of the
  tile; `pack_lightmap`'s 64 px fallback makes exactly that on a many-chart mesh.
- **Gate (Bakery):** every lightmapped renderer of 64 px or more gets at least 0.5 x texels_per_m x min(1, sqrt(S))
  effective texels per metre, half the density planned for it. `uv_audit` with `lightmapper="bakery"` reports an
  issue below it, RizomUV's report a warning, and the snippet below prints it after a bake for either lightmapper.
  Under Unity the same number drops under half only when the charts fill under a quarter of their box.
- The cinema (VRChat, Bakery, issue #8): of 1,174 lightmapped renderers, 100 were under 10 effective texels/m; a
  588-chart channelled wall panel (6.98 m2) had a coverage of 0.0002, so 0.43 texels/m.

Fix a renderer under the gate, in this order:

1. Raise its Scale In Lightmap: S = s^2 for a linear factor s.
2. Repack its UV2 for the larger footprint: 2-texel gaps at texels_per_m x s x sqrt(2 x A_min) texels (less 6 under
   the Default packer), A_min = the smallest renderer using the mesh.
3. Bake with the xatlas packer and 2 px padding (`texelPaddingForXatlasAtlasPacker`), so no rect loses its edge to
   the inset.
4. Stretch the UV2 bounds of thin emitters and strips to the tile: a 0.06 x 1 column costs about 17 x L^2, stretched
   it costs L^2.
5. Bake again and read the snippet's effective density.

On the cinema: 112 meshes repacked, every lightmapped renderer at 10 texels/m or more, for 0.4 Mpx of extra atlas;
with the whole recipe above, every lightmapped renderer at 10 texels/m or more with 2-texel gaps in 4.8 Mpx (2
lightmaps of 2048).

Capacity: a rect costs L^2 x aspect = 2 x A x S x texels_per_m^2 x aspect px^2, each LOD at its own area. That is
twice Unity's at S = 1 for square bounds, and S scales it linearly (Unity: S^2). Sum it x copies x lighting states
against the same 0.65 plan and 0.80 limit: those were measured with Unity's packer and are assumed for Bakery's.
When a lightmap is full Bakery starts another, so a spill shows as an extra lightmap: count them after the bake.

## Texel density

| Surface | Texels per metre |
|---|---|
| Large outdoor terrain, skybox-lit ground | 2-5 |
| Facades and exteriors seen from a distance | 6-10 |
| Interior walls and floors | 10-20 |
| Hero surface with crisp contact shadows | 20-40 |
| Small free props | probe-lit when the footprint is under 64 px |

Set the scene value at the low end and promote renderers with Scale In Lightmap. Doubling Lightmap Resolution
quadruples the texel count. Pick the resolution before the UV2 is packed: it sets every piece's footprint and so its
gap.

## Lightmap memory

| Platform | Format | Bytes per pixel |
|---|---|---|
| PC | BC6H (Lightmap Encoding High Quality) or DXT5 (Normal Quality, RGBM) | 1 |
| Android and iOS | ASTC, 3.56 bits per pixel | about 0.45 |

Add a third for mipmaps. Directional mode adds a second map of the same size ("about twice as much video memory").
Measured: one 1024 BC6H lightmap with mips = 1.33 MB (2^20 bytes). Sources:
https://docs.unity3d.com/2022.3/Documentation/Manual/Lightmaps-TechnicalInformation.html,
https://docs.unity3d.com/2022.3/Documentation/Manual/class-LightingSettings.html (checked 2026-10-17).

## Verify after a bake (Unity Editor C#)

Both snippets are method bodies that end in a `return`: Unity MCP's `execute_code` wraps them in
`public static object Execute()`, and in an Editor script they go inside a static method that returns `object`.

This one prints, per lightmapped renderer, its footprint and the smallest UV2 gap it tolerates (2 / footprint), and
compares that with the gap its mesh was packed with, from `packed` (mesh name -> gap in UV units, from the UV2 brief
or the packing log). It also prints the effective density, footprint x sqrt(UV2 charts' area / surface area) from
the mesh in world space, and flags it under half of `texelsPerM`: the gate, for Progressive and Bakery alike, as
both write `lightmapScaleOffset`. Run it in Edit mode, not Play mode: static batching combines the meshes there,
and mesh data is readable "in the Unity Editor outside of the game and rendering loop, regardless of" Read/Write
(https://docs.unity3d.com/2022.3/Documentation/ScriptReference/Mesh-isReadable.html, checked 2026-10-24).
`Lightmapping.HasUVOverlaps` is internal in 2022.3, hence the reflection. Its `overlaps True` is Unity's own verdict
from the bake and wins: when it disagrees with an "ok", the `packed` entry is wrong or the mesh was repacked since,
so re-measure that UV2's gap. The flag is Unity's lightmapper's: after a Bakery bake, rely on Bakery's own UV
validation for overlaps.

```csharp
float texelsPerM = 20f;                     // Lightmap Resolution (Bakery: Texels Per Unit), for the density gate
var packed = new System.Collections.Generic.Dictionary<string, float>
{
    { "INT_Wall_2x3_A", 0.0089f },          // one entry per mesh: the gap its UV2 was packed with
    { "STR_Floor_2x2_A", 0.0112f },
};
var maps = UnityEngine.LightmapSettings.lightmaps;
var hasOverlaps = typeof(UnityEditor.Lightmapping).GetMethod("HasUVOverlaps",
    System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.NonPublic);
var report = new System.Text.StringBuilder();
int failing = 0, unknown = 0, overlapping = 0, thin = 0;
foreach (var r in UnityEngine.Object.FindObjectsOfType<UnityEngine.MeshRenderer>())
{
    if (r.lightmapIndex < 0 || r.lightmapIndex >= maps.Length) continue;      // not lightmapped
    float px = r.lightmapScaleOffset.x * maps[r.lightmapIndex].lightmapColor.width;
    float needed = 2f / px;                                                     // smallest gap this footprint tolerates
    var filter = r.GetComponent<UnityEngine.MeshFilter>();
    var m = filter != null ? filter.sharedMesh : null;
    string mesh = m != null ? m.name : r.name;
    string verdict = "packed gap unknown";
    float gap;
    if (packed.TryGetValue(mesh, out gap))
    {
        verdict = gap >= needed ? "ok" : "UNDER 2 TEXELS";
        if (gap < needed) failing++;
    }
    else unknown++;
    double area = 0, uvArea = 0;                    // world-space surface area, and the lightmap UV's charts' area
    if (m != null)
    {
        var v = m.vertices;
        var uv = m.uv2.Length == v.Length ? m.uv2 : m.uv;                       // without a UV2 both bake from UV0
        var t = m.triangles;
        var w = r.transform.localToWorldMatrix;
        for (int i = 0; i + 2 < t.Length; i += 3)
        {
            var a = w.MultiplyPoint3x4(v[t[i]]);
            var b = w.MultiplyPoint3x4(v[t[i + 1]]);
            var c = w.MultiplyPoint3x4(v[t[i + 2]]);
            area += 0.5 * UnityEngine.Vector3.Cross(b - a, c - a).magnitude;
            if (uv.Length == v.Length)
            {
                var p = uv[t[i]];
                var q = uv[t[i + 1]];
                var s = uv[t[i + 2]];
                uvArea += 0.5 * System.Math.Abs((q.x - p.x) * (s.y - p.y) - (s.x - p.x) * (q.y - p.y));
            }
        }
    }
    double eff = area > 0 ? px * System.Math.Sqrt(uvArea / area) : 0;          // effective texels per metre
    string low = eff < 0.5 * texelsPerM ? " UNDER HALF" : "";
    if (low.Length > 0) thin++;
    object overlap = hasOverlaps != null ? hasOverlaps.Invoke(null, new object[] { r }) : "n/a";
    if (overlap is bool o && o) overlapping++;
    report.AppendLine($"{r.name} ({mesh}): map {r.lightmapIndex}, footprint {px:F1} px, needs gaps >= {needed:F4} UV, " +
                      $"{verdict}, effective {eff:F1} texels/m{low}, overlaps {overlap}");
}
report.AppendLine($"{failing} renderer(s) with UV2 gaps under 2 texels, {overlapping} with overlapping UVs, " +
                  $"{thin} under half of {texelsPerM} effective texels/m, {unknown} with no packed gap in the table");
return report.ToString();
```

A renderer whose Scale In Lightmap is under 1 on purpose is judged against half of its own planned density (Unity:
texels_per_m x S; Bakery: texels_per_m x sqrt(S)); a UNDER HALF on a renderer under 64 px is the 64 px rule's
business (a probe-lit prop, or a grid piece's note), not the gate's.

Overlap warnings also land in Editor.log (`%LOCALAPPDATA%/Unity/Editor/Editor.log`): "There are N objects in the
Scene with overlapping UV's". The console loses them once it is cleared.

## Scripted bakes (Unity MCP), Unity 2022.3

A scene can point at a LightingSettings asset that does not exist (VRChat's template scene does), and then
`Lightmapping.lightingSettings` throws. When it is missing, the snippet creates one next to the scene
(`<Scene>_Lighting.lighting`, never overwriting an existing asset) and assigns it; save the scene afterwards so the
link sticks. When the scene already has one, the snippet edits it, and every scene sharing that asset gets the values.

```csharp
var scene = UnityEngine.SceneManagement.SceneManager.GetActiveScene();
if (string.IsNullOrEmpty(scene.path)) return "save the scene first";
UnityEngine.LightingSettings s;
if (!UnityEditor.Lightmapping.TryGetLightingSettings(out s) || s == null)
{
    string path = UnityEditor.AssetDatabase.GenerateUniqueAssetPath(
        System.IO.Path.ChangeExtension(scene.path, null) + "_Lighting.lighting");
    s = new UnityEngine.LightingSettings { name = System.IO.Path.GetFileNameWithoutExtension(path) };
    UnityEditor.AssetDatabase.CreateAsset(s, path);
    UnityEditor.Lightmapping.lightingSettings = s;
    UnityEditor.SceneManagement.EditorSceneManager.MarkSceneDirty(scene);
}
s.lightmapper = UnityEngine.LightingSettings.Lightmapper.ProgressiveGPU;
s.lightmapResolution = 20f;                                        // texels per metre, from the plan
s.lightmapMaxSize = 1024;                                          // 1024 when the world ships to Quest or iOS
s.lightmapPadding = 2;                                             // clamps to at least 2
s.lightmapCompression = UnityEngine.LightmapCompression.NormalQuality;
s.directionalityMode = UnityEngine.LightmapsMode.NonDirectional;
s.ao = true;
s.autoGenerate = false;
bool started = UnityEditor.Lightmapping.BakeAsync();
return started ? "bake started: poll UnityEditor.Lightmapping.isRunning" : "bake did not start: see the console";
```

- `Lightmapping.buildProgress` stays at 0 while the GPU lightmapper compiles its kernels on the first bake (about
  45 s, measured 2026-10-16): watch Editor.log rather than the progress value.
- Never bake in a Unity started with `-nographics`: "-nographics does not allow you to bake GI, because Enlighten
  requires a GPU for Meta Pass rendering"
  (https://docs.unity3d.com/2022.3/Documentation/Manual/EditorCommandLineArguments.html, checked 2026-10-17). Measured
  2026-10-17: with lightmap-static objects in the scene, the batch-mode editor crashed during the bake. Batch mode
  without `-nographics`, or an open editor, bakes.
- Source: https://docs.unity3d.com/2022.3/Documentation/ScriptReference/LightingSettings.html and
  https://docs.unity3d.com/2022.3/Documentation/ScriptReference/Lightmapping.html (checked 2026-10-17); the enum
  `Lightmapper` is nested in `LightingSettings`, and `TryGetLightingSettings`, the `lightingSettings` setter and
  `LightingSettings`' public constructor exist in UnityEngine/UnityEditor.CoreModule 2022.3.22f1.
