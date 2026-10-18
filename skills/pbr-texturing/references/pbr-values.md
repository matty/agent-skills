# PBR values: the limits, measured materials and what the checker says

The metal/roughness workflow (base colour, metallic, roughness or its inverse smoothness, normal) as real-time engines
use it. Limits first, then measured materials to calibrate against, then how `scripts/pbr_check.py` judges a map.

## The limits

From Adobe's "The PBR Guide, Part 2" (https://www.adobe.com/learn/substance-3d-designer/web/the-pbr-guide-part-2,
checked 2026-10-18), sections "Base Color (RGB - sRGB) > Creation Guidelines", "Metallic (Grayscale - Linear)" and
"Dielectric F0":

| Rule | The guide's words |
|---|---|
| Dielectric base colour, dark end | "For dark values, you should not go under 30-50 sRGB": 30 is the tolerant limit, 50 the strict one |
| Dielectric base colour, bright end | "you should not have any values that are higher than 240 sRGB" |
| Raw metal base colour | "around 70-100% specular, which we can map to an sRGB range of 180-255" |
| Metallic | "often binary: black or white, metal or non-metal"; it "can represent a blended state" with "transitional gray values" (dust, oxidation, worn paint edges) |
| Dielectric F0 | "typically set to 0.04 (linear) 4% reflective": the shader applies it; nothing to paint |
| Roughness | "Be creative and tell a visual story about the surface"; "A good place to start with roughness is the normal map" |

## Measured materials

Linear base colours from the physicallybased.info database (https://physicallybased.info, read through
https://api.physicallybased.info/materials, checked 2026-10-18; its colours are linear: the 18% grey card is 0.18),
converted here to 8-bit sRGB and Rec. 709 luma, which is what the checker judges. The source column is each entry's own
measurement source. The database's roughness values are placeholders (0, 0.5, 0.9): do not calibrate roughness from
them.

| Material | Linear | sRGB | Luma | Source |
|---|---|---|---|---|
| Charcoal | 0.02, 0.02, 0.02 | 39, 39, 39 | 39 | https://chrisbrejon.com/articles/albedo-and-pointers-gamut/ |
| Tyre rubber | 0.023, 0.023, 0.023 | 42, 42, 42 | 42 | https://github.com/AntonPalmqvist/physically-based-api/tree/main/data/materials/tire/ |
| Blackboard | 0.039, 0.039, 0.039 | 56, 56, 56 | 56 | https://spectraldb.com/measurements/00079/ |
| Black toner | 0.05, 0.05, 0.05 | 63, 63, 63 | 63 | https://github.com/AntonPalmqvist/physically-based-api/tree/main/data/materials/toner-black/ |
| Brick | 0.262, 0.095, 0.061 | 140, 87, 70 | 97 | https://github.com/AntonPalmqvist/physically-based-api/tree/main/data/materials/brick/ |
| 18% grey card | 0.18, 0.18, 0.18 | 118, 118, 118 | 118 | https://en.wikipedia.org/w/index.php?title=Gray_card&oldid=1244084939 |
| Sand | 0.44, 0.386, 0.231 | 177, 167, 132 | 167 | https://civiltoday.com/civil-engineering-materials/sand/299-bulk-density-of-sand |
| Concrete | 0.51, 0.51, 0.51 | 189, 189, 189 | 189 | https://seblagarde.wordpress.com/2011/08/17/feeding-a-physical-based-lighting-mode/ |
| Porcelain | 0.745, 0.745, 0.723 | 224, 224, 221 | 224 | https://github.com/AntonPalmqvist/physically-based-api/tree/main/data/materials/porcelain/ |
| Marble | 0.83, 0.791, 0.753 | 235, 230, 225 | 231 | https://en.wikipedia.org/wiki/Marble |
| Office paper | 0.794, 0.834, 0.884 | 230, 235, 242 | 234 | https://github.com/AntonPalmqvist/physically-based-api/tree/main/data/materials/office-paper |
| Snow | 0.85, 0.85, 0.85 | 237, 237, 237 | 237 | https://seblagarde.wordpress.com/2011/08/17/feeding-a-physical-based-lighting-mode/ |
| Titanium (metal) | 0.441, 0.4, 0.361 | 177, 170, 162 | 171 | https://refractiveindex.info/?shelf=main&book=Ti&page=Palm |
| Iron (metal) | 0.53, 0.513, 0.494 | 192, 190, 187 | 190 | https://refractiveindex.info/?shelf=3d&book=metals&page=iron |
| Tungsten (metal) | 0.537, 0.536, 0.519 | 194, 193, 191 | 193 | https://refractiveindex.info/?shelf=main&book=W&page=Werner-DFT |
| Stainless steel (metal) | 0.669, 0.639, 0.598 | 214, 209, 203 | 210 | https://refractiveindex.info/?shelf=3d&book=metals&page=stainless_steel |
| Chromium (metal) | 0.654, 0.685, 0.701 | 211, 216, 218 | 215 | https://refractiveindex.info/?shelf=main&book=Cr&page=Sytchkova |
| Copper (metal) | 0.932, 0.623, 0.522 | 247, 207, 191 | 214 | https://refractiveindex.info/?shelf=main&book=Cu&page=Johnson |
| Brass (metal) | 0.91, 0.778, 0.423 | 245, 228, 174 | 228 | https://refractiveindex.info/?shelf=3d&book=metals&page=brass |
| Gold (metal) | 1.0, 0.773, 0.307 (stored 1.059 red) | 255, 228, 150 | 228 | https://refractiveindex.info/?shelf=main&book=Au&page=Babar |
| Aluminium (metal) | 0.916, 0.923, 0.924 | 245, 246, 246 | 246 | https://refractiveindex.info/?shelf=main&book=Al&page=Cheng |
| Silver (metal) | 0.991, 0.985, 0.974 | 254, 253, 252 | 253 | https://refractiveindex.info/?shelf=main&book=Ag&page=Babar |

What this shows: real dark materials (charcoal, rubber) sit between the tolerant 30 and the strict 50, so the strict
limit is a NOTE, never a failure; snow and paper stay under 240; and titanium, a real metal, is under the guide's 180,
so the checker fails a metal only under 160. A lab ultra-black (Musou Black, luma 18) and a lab white standard
(Spectralon, 254) fail, as they should in a game texture. These rows are pinned in the repo's plain tests.

## Roughness, briefly

- No absolute values: roughness is the material's history. Polished high spots and hand-worn edges smoother, crevices
  and dust rougher, water smoother and darker.
- Start from the normal map's detail (the guide's advice): fine bumps scatter light, so detailed areas usually read
  rougher.
- Avoid the two extremes on large areas: a smoothness near 1 is a mirror.

## Specular shimmer in VR

A headset resolves about 20 pixels per degree and the head never stops moving, so a highlight that lands on detail
finer than a pixel flickers from frame to frame: busy, high-frequency normal maps under high smoothness sparkle, worst
on floors seen at grazing angles and on the far side of a room, where the detail sits in the smaller mips (*practice*,
all of it):

- Lower smoothness where the normal map is busy; keep high smoothness for surfaces that really are smooth.
- Keep sub-texel normal detail out of the map: detail smaller than a texel at the surface's texel density cannot be
  shown, only aliased. Blur or drop it before export; let the roughness carry it instead.
- Mip maps average the normals, which shortens them and loses the bumpiness at a distance while the surface stays
  glossy: fade fine normal detail out in the lower mips, or move the lost variance into roughness in those mips
  (Toksvig-style: the shorter the averaged normal, the rougher the mip), where the tool can.
- Prefer a shader with geometric specular anti-aliasing, which raises roughness where the geometry's normals change
  quickly on screen. Unity's Standard has none; VRChat's mobile Standard Lite has it on by default
  (`references/engine-notes.md`).
- Judge it moving: in a headset, or by comparing look-dev renders from slightly shifted cameras, never from one still
  frame.

## How `pbr_check.py` judges

Maps pair by name (`T_<FAMILY>_<Name>_BaseColor`, `_MetallicSmoothness`, `_Normal`; `_AlbedoTransparency` counts as
base colour). Pixels are the stored codes (16-bit PNGs included: inside Blender the image is read as Non-Color, since
Blender otherwise linearises them: a stored 0.5 reads 0.214, measured on 5.2.2).

| Map | Measure | PROBLEM | NOTE |
|---|---|---|---|
| Base colour | Rec. 709 luma of the sRGB codes; dielectric pixels at the 1st and 99th percentile, metal pixels (metallic 0.5 or more) at the 5th; cutout pixels (alpha under 0.5) left out | Dielectric p1 under 30 or p99 over 240; metal p5 under 160; the dielectric median outside a target `albedo_srgb` | Dielectric p1 under 50; metal p5 under 180 |
| Metallic-smoothness | R: share of pixels strictly between 0.1 and 0.9; A: spread, median, share at 0.98 or more | No alpha channel (Unity's Standard then renders it fully smooth); more than 10% grey metal; median roughness (1 - A) outside a target `roughness`; metal on more than 1% of a `metal: false` target | Grey metal over 2%; smoothness spread (std) under 0.02; more than 5% mirror-smooth; a `metal: true` target under 50% metal |
| Normal | Decoded vectors (2c - 1): mean length, share with Z under 0, mean X and Y, and the Y convention | Mean length outside 0.9-1.1 (not a normal map, or colour-converted on export); more than 1% of texels pointing inwards; the convention reads DirectX | Mean X or Y beyond 0.1 (the whole surface leans); convention unclear |
| Every map | Size | Not a power of two; larger than `--map-px` | |
| Tiling (`--tiling`) | The mean step across the wrap edges over the mean step inside, per axis | | Ratio over 1: look at the 3 x 3 composite (a smooth gradient whose steepest step lands on the edge legitimately reads about 1.6) |

**The Y convention.** A normal map that comes from a surface (a bake, or a height map) is the slope field of a height,
so its two estimates of the height's mixed derivative agree for the right Y sign and are opposite for the wrong one.
The checker correlates them over the map: r near +1 is OpenGL (Y+), near -1 DirectX (Y-) or a flipped red channel,
near 0 means no evidence (a flat map, straight grooves only, noise). It decides at |r| 0.3 or more. Measured
2026-10-18 on the repo's bake fixture: the Substance 3D baker's OpenGL bake +0.72, its default (DirectX) bake -0.63,
Cycles bakes +0.53 to +0.59 with a flipped copy at the same value negated; island borders, mirrored and rotated islands
leave the sign intact (plain tests). A map with both channels flipped is a valid surface with dents for bumps:
statistics cannot see that, a look-dev render lit from one side can.

Use `--targets '{"M_EXT_Brick": {"albedo_srgb": [60, 150], "roughness": [0.6, 0.95], "metal": false}}'` (or
`--spec world/spec.yaml`, which reads `look.materials` and needs PyYAML) to hold a material to its art direction.
