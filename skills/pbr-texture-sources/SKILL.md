---
name: pbr-texture-sources
description: Find and download free CC0 PBR textures and materials - a brick, wood, concrete, metal, ground or fabric texture, search Poly Haven or ambientCG, maps at 1k-8k. One script searches both, downloads with one naming scheme (BaseColor, NormalGL, Roughness), verifies the files and records source and licence. Authoring, values and engine packing (pbr-texturing).
---

# PBR texture sources

Search two CC0 libraries with public JSON APIs, download one material's maps under one naming scheme, and
record where they came from. Then hand the maps to texturing: a downloaded scan is a base to calibrate, not a
finished material (`pbr-texturing` owns values, packing and look-dev). Engine-neutral; what each engine reads is
in `references/engine-notes.md`.

## 0. Before downloading

- Library assets need the user's yes. If a project spec or brief says what is allowed (generated or library
  assets), follow it; otherwise ask once.
- Inside a live Blender with the Blender MCP, `search_assets` / `import_asset` already import Poly Haven
  materials into the scene. Use this skill for files on disk, for ambientCG, or when there is no Blender.

## 1. Search

```
python scripts/pbr_fetch.py search <words...> [--source polyhaven|ambientcg] [--limit 10] [--json hits.json]
```

- Every word must match (both sources AND the words). Start with two or three: the material and one quality
  ("brick red", "concrete rough", "oak floor"); add words only to narrow.
- Each hit prints `<source>:<id>`, title, the largest resolution, the physical size it covers, tags and the
  page URL. Show the user a short list with the page URLs (each has a preview), and credit Poly Haven when its
  results are shown: the script prints the line.
- Pick by:

  | Check | Why |
  |---|---|
  | Physical size near the surface's tile period (`size_m`) | A 0.5 m scan stretched over a 4 m wall shows bricks at the wrong scale; `size ?` means the site did not say, so read the page |
  | The maps you need (`info` lists them) | Metal needs a Metallic map; cutouts need Opacity |
  | Clean, evenly lit, no strong baked shadows | Baked shadows fight the scene's lighting |
  | Tiles without an obvious feature | One distinctive crack repeats on every tile |

## 2. Look closer (optional)

```
python scripts/pbr_fetch.py info polyhaven:red_brick_03
```

Prints every map with its resolutions, formats and byte sizes (ambientCG: each zip's size), and the bundles.

## 3. Download

```
python scripts/pbr_fetch.py get <source>:<id> --out <textures>/library [--res 2k] [--format jpg] [--normal gl]
```

| Option | Default | Choose |
|---|---|---|
| `--res` | `2k` | The family map size the texel density gives (`uv-unwrapping` owns that); never more than the map you will ship. Falls back to the largest offered at or below it |
| `--format` | `jpg` | `png` for Height and Normal when they feed a bake or displacement (8-bit JPG bands); `exr` (Poly Haven only) for 32-bit height |
| `--maps` | `core` | `core`: BaseColor, Normal, Roughness, Metallic, AO, Height, Opacity, Emission where offered. `all` adds ARM, Bump, Specular and the rest. Or a list: `BaseColor,Normal,Roughness` |
| `--normal` | `gl` | `gl` (OpenGL, Y+), `dx` (DirectX, Y-) or `both`: the target engine's convention (`references/engine-notes.md`) |
| `--bundle` | off | Poly Haven `gltf`, `blend` or `mtlx`; ambientCG any value for its whole zip (mtlx, blend, usdc, tres). Keeps the site's own file names so the scene file still finds its textures |
| `--max-mb` | `500` | Refuses larger downloads. An ambientCG 8K PNG zip passes 1 GB |

Output: `<out>/<source>_<id>/<id>_<res>_<Map>.<ext>` plus `source.json` (source, page URL, `CC0-1.0`, credit
line, physical size, resolution, every file with its size and MD5). Poly Haven files are checked against the
API's MD5; ambientCG zips against the API's size and their CRCs. A `NOTE` line names a fallback or a map the
asset lacks. Exit 1 means nothing usable was written: read the `ERROR` line.

| Map | Meaning |
|---|---|
| `BaseColor` | sRGB albedo (Poly Haven `diff`, ambientCG `Color`) |
| `NormalGL` / `NormalDX` | Tangent-space normal, OpenGL Y+ / DirectX Y- |
| `Roughness`, `Metallic`, `AO`, `Opacity`, `Emission` | Linear greyscale |
| `Height` | Displacement (Poly Haven `disp`, ambientCG `Displacement`) |
| `ARM` | Poly Haven packed map: R AO, G roughness, B metallic (glTF order; not Unity's Standard packing) |

## 4. Hand over

1. Keep `source.json` beside the maps and copy its source and licence into whatever the project records for
   library assets.
2. Load `pbr-texturing`: recalibrate the values (scans are often too dark or too contrasty for a PBR range), pack the
   channels the engine reads, rename to the project's map names and run its checks and look-dev render.
3. Tiling check: scans can carry a faint seam or a low-frequency gradient across the tile, so judge them in a 3 x 3
   view before using them on large surfaces.

## Sources and terms

| Source | API | Terms (checked 2026-10-25) |
|---|---|---|
| Poly Haven, about 870 textures, 1k-8k (some 16k), jpg / png / exr | `https://api.polyhaven.com` (`/assets?type=textures`, `/info/<id>`, `/files/<id>`); docs https://github.com/Poly-Haven/Public-API | Assets CC0. API free for any use, no key; every call must send a User-Agent naming the tool (the script does) and content shown through the API carries a light credit, "Powered by Poly Haven": https://github.com/Poly-Haven/Public-API/blob/master/ToS.md |
| ambientCG, 2,000+ materials, 1K-8K, JPG / PNG zips | `https://ambientcg.com/api/v3/assets` (`q`, `type`, `id`, `sort`, `limit`, `offset`, `include`): https://docs.ambientcg.com/api/v3/assets/ | CC0, credit appreciated but optional: https://docs.ambientcg.com/license/. Run by one person; the docs warn the API is not enterprise-grade |

- Neither publishes a rate limit. Download one asset at a time, only what the task uses; never mirror a library.
  The script caches Poly Haven's full list for 24 hours instead of calling it per search.
- Physical sizes: Poly Haven reports millimetres and ambientCG centimetres (inferred from the values,
  2026-10-25; 0 means unknown). Check the page when the scale matters.
- Left out on purpose: ShareTextures, TextureCan, cgbookcase and 3DTextures.me are free (CC0 or similar) but have
  no API (3DTextures.me hosts its files on Google Drive). Give their URLs for manual browsing. Fab / Megascans has
  not been free since 2024 and uses its own licence; Textures.com and FreePBR are not CC0. AMD's GPUOpen MaterialX
  Library has an API but many entries re-host Poly Haven, and its licence label ("MIT Public Domain") is unclear.

## Scripts

| Script | Host | Use |
|---|---|---|
| `scripts/pbr_fetch.py` | Plain Python 3.9+, standard library, network | `search`, `info`, `get` as above; as a module `search(words)`, `info(ref)`, `get(ref, out_dir, ...)` |
