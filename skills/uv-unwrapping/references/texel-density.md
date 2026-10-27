# Texel density for VR: choosing it

How many texture pixels per metre a surface needs in a headset, and how to keep one density across a world. Worked
out for a PC VR dark ride (Oct 2026), where every viewing position is known; the method carries to any world.
Setting a density in Blender: `uv_audit.layout(..., px_per_m=...)` (SKILL.md section 2). Hitting it exactly with
RizomUV's packer: the `rizomuv-uv-pipeline` skill.

## Principle: match the display

A texture only needs as many texels per metre as the headset shows pixels per metre at the closest distance anyone
sees the surface from. Fewer looks soft; more is memory the GPU never samples (it reads a smaller mip).

Plan with about 20 pixels per degree. Published figures (checked 2026-10-17): Quest 2 and Quest 3S 20, Quest 3 25
(https://roadtovr.com/quest-3s-quest-3-quest-2-specs-compared/, 2024-09-25), Bigscreen Beyond 28
(https://roadtovr.com/bigscreen-beyond-pc-vr-steam-release-price-specs/, 2023-02-13). For a headset without a
published figure, divide its horizontal pixels per eye by its horizontal field of view in degrees. One metre at
distance d spans 57.3 / d degrees, so at 20 ppd the screen shows about

    px_per_m = 1150 / d          770 at 1.5 m, 380 at 3 m, 190 at 6 m, 95 at 12 m

## Classes by viewing distance

Quantise to powers of two so textures and trims line up. Each class gives at least two thirds of what the headset
resolves at the near edge of its band (512 px/m at 1.5 m, where 770 would be needed); closer than its band, a
surface looks soft.

| Class | Nearest viewing distance | Target | Typical surfaces |
|---|---|---|---|
| T2048 | < 0.75 m | 2048 px/m | pickups and anything held to the face: small unique surfaces, never a wall |
| T1024 | 0.75-1.5 m | 1024 px/m | what players lean over or handle: desk and counter tops, switches, door handles, a seat's arms |
| T512 | 1.5-3 m | 512 px/m | surfaces seen from a couple of metres: the far side of a desk, door reveals, a ride vehicle |
| T256 | 3-6 m | 256 px/m | the far side of a room, upper walls, most ceilings |
| T128 | 6-12 m | 128 px/m | back walls of large halls, beds beyond a hedge, a facade seen across a garden |
| T64 | > 12 m | 64 px/m | skyline, treeline cards, the sky dome |

The bands assume about 20 pixels per degree (Quest 2 and 3S). Quest 3 resolves 1.25 times more and Bigscreen Beyond
1.4 times: the same classes look slightly softer there. Budgets, not the headset, cap the classes.

When viewers follow a fixed path (a ride), measure it: sample eye points along the path for every seat, take the
shortest distance from any of them to each placed instance, and assign its class automatically. In a walkable
world, use the distance players normally look at a surface from, at eye height; a prop used in several places takes
the class of its nearest instance.

**Surfaces players can walk right up to** (walls and floors along a walkway, at 0.5-1 m) are the exception: by
distance alone they would be T1024 or T2048 across the whole world, four to sixteen times the texels of T512. Keep
them at the world's shared tiling or trim density (T512 in most worlds) and add a **detail map** for the close look:
a small, finely tiled albedo and normal that the shader multiplies in (Unity's Standard: Detail Albedo x2 and Detail
Normal Map, masked by a Detail Mask, `engine-notes.md`). It adds close-range texels for one small texture per
material. Give a surface its own higher class only where players are meant to inspect it (a mural, a noticeboard,
a control panel).

## Shared trims and tiling materials

One density everywhere (512 px/m for a T512-led world), authored once: a 2048 trim sheet covers 4 m of strip; a
2048 tile repeats every 4 m. Far surfaces use the **same** material and sample lower mips. Do not make
lower-density copies: they cost a material and a texture, break batching and instancing, and save nothing. Raise
anisotropic filtering (4+) on floors seen at grazing angles. Trim UVs are best generated where the mesh is built
(exact strip coordinates); otherwise match strips to the trim rows by hand (workflows.md, Modular piece). Neither
this skill nor `rizomuv-uv-pipeline` automates trim matching; RizomUV's Hotspot does it interactively in RizomUV.

## Unique textures: map size

    map_px = next_pow2(px_per_m x sqrt(area_m2 / coverage))      coverage about 0.65, capped by the platform

`area_m2` is the surface that needs its own texels: stacked copies count once. A crate with four identical sides
needs a 2048 map counted over its full surface but fits a 1024 counted once per stack (it packed at coverage 0.60).
A piece that does not fit at its class on the capped map (`layout` reports `fits` False): split it into two texture
sets or remove faces nobody sees, rather than letting its density drop below 0.8x its class.

**A hero prop over the cap.** A chest of 0.9 x 0.5 x 0.5 m has about 2.3 m2 of surface; at T2048 (seen within 0.75 m)
it needs `next_pow2(2048 x sqrt(2.3 / 0.65))` = 4096 px (*derived*), over a 2048 PC cap, and a 1024 mobile override
leaves about 545 px/m. In this order:

1. Stack what repeats (both ends, the four brackets: but unstack copies seen together, so their wear differs) and
   drop faces nobody sees (the base, the back against a wall; an openable inside counts as seen).
2. Split the texture by material into two or three sets (wood, iron, leather), each its own map at the class: each
   set is a draw call, which a hero prop seen up close earns.
3. Close-range sharpness on the mobile build from a detail map on the largest material (wood grain, leather grain) at
   its own tiling: it costs a small map and holds the class where the override halves the main one.
4. Report the class each set reaches on each platform; never let a set fall under 0.8x its class silently.

## Lightmaps are a different density

Lightmaps run at a few to a few tens of texels per metre, set per scene and weighted per renderer with a lightmap
scale; the numbers and bake settings belong to the engine's lighting setup (`vrchat-lighting-and-baking` for Unity /
VRChat). The UV2 is packed for the smallest texel scale the renderer can get and audited at the scale it measures to
get; its charts should fill their bounding box, at any aspect ratio, since the lightmapper packs that box and empty
space inside it lowers the effective density to `texels_per_m x sqrt(charts' area / box area)`. Each LOD is packed
for its own scale, 0.5^n (SKILL.md section 9).

## Checks

- Unique and atlas textures within 0.8-1.25x of their class; shared trims and tiling materials within 10%
  (0.9-1.1x) of the world density. The audit applies these bands by `purpose`.
- Even density inside one piece: `texel_cv` <= 0.15, unless varied on purpose (faces marked `uv_low_density`).
- A debug checker coloured by class shows mismatches at a glance before anyone signs off a scene.
