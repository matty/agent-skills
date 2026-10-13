# Texel density for VR: choosing it

How many texture pixels per metre a surface needs in a headset, and how to keep one density across a world. Worked
out for a PC VRChat dark ride (Oct 2026), where every viewing position is known; the method carries to any world.
Setting a density in Blender: `uv_audit.set_texel_density` (SKILL.md section 6). Hitting it exactly with RizomUV's
packer: the `rizomuv-uv-pipeline` skill.

## Principle: match the display

A texture only needs as many texels per metre as the headset shows pixels per metre at the closest distance anyone
sees the surface from. Fewer looks soft; more is memory the GPU never samples (it reads a smaller mip).

A headset shows roughly 20 pixels per degree (Index about 14, Quest 3 about 25, Bigscreen Beyond about 32; take
horizontal pixels per eye divided by the horizontal field of view for any other device, and re-check these as
headsets change). One metre at distance d spans 57.3 / d degrees, so at 20 ppd the screen shows about

    px_per_m = 1150 / d          770 at 1.5 m, 380 at 3 m, 190 at 6 m, 95 at 12 m

## Classes by viewing distance

Quantise to powers of two so textures and trims line up:

| Class | Nearest viewing distance | Target | Typical surfaces |
|---|---|---|---|
| T512 | 0-3 m | 512 px/m | anything within arm's reach of a seat or a walkway, the vehicle itself, door reveals |
| T256 | 3-6 m | 256 px/m | the far side of a room, upper walls, most ceilings |
| T128 | 6-12 m | 128 px/m | back walls of large halls, beds beyond a hedge, a facade seen across a garden |
| T64 | > 12 m | 64 px/m | skyline, treeline cards, the sky dome |

When viewers follow a fixed path (a ride), measure it: sample eye points along the path for every seat, take the
shortest distance from any of them to each placed instance, and assign its class automatically. In a walkable
world, use the nearest point a player can stand, at eye height. A prop used in several places takes the class
of its nearest instance.

## Shared trims and tiling materials

One density everywhere (512 px/m for a T512-led world), authored once: a 2048 trim sheet covers 4 m of strip; a
2048 tile repeats every 4 m. Far surfaces use the **same** material and sample lower mips. Do not make
lower-density copies: they cost a material and a texture, break batching and instancing, and save nothing. Raise
anisotropic filtering (4+) on floors seen at grazing angles. Trim UVs are best generated where the mesh is built
(exact strip coordinates); the `rizomuv-uv-pipeline` skill's Hotspot route can match irregular pieces to
trim rectangles.

## Unique textures: map size

    map_px = next_pow2(px_per_m x sqrt(area_m2 / coverage))      coverage about 0.65, capped by the platform

A piece that does not fit at its class on the capped map: split it into two texture sets or remove faces nobody
sees, rather than letting its density drop below about 0.8x its class.

## Lightmaps are a different density

Lightmaps run at a few to a few tens of texels per metre, set per scene and weighted per renderer with Scale In
Lightmap; the numbers and bake settings are the `vrchat-lighting-and-baking` skill's. Pack each mesh's UV2 for the
rectangle it will actually get (section 9 of SKILL.md).

## Checks

- Unique textures within 0.8-1.25x of their class; shared trims and tiling materials within 10% of the world density.
- Even density inside one piece (islands within about 15% of each other unless varied on purpose).
- A debug checker coloured by class shows mismatches at a glance before anyone signs off a scene.
