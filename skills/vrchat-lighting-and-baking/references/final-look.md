# The final look: directional lightmaps, a final-quality bake, lighting design, post-processing

Everything here comes after the plan in SKILL.md is met: these settings decide how the finished world looks, not
whether it fits. Measured facts carry their version and date; rows marked *practice* are this skill's working rules,
to be settled by looking at the result in the headset.

## Normal maps need directional baked light

A Non-Directional lightmap stores only the light's colour, so baked diffuse light ignores the surface's normal map:

| Shader | Non-Directional lightmap | Directional, or Bakery MonoSH |
|---|---|---|
| Standard (PC) | The normal map shows only in reflections (reflection probes, specular from realtime lights) | Baked light follows the normal map |
| `VRChat/Mobile/Standard Lite` | With a lightmap, no MonoSH, no directional map and Glossy Reflections off, the shader never samples the normal or detail normal map (the normal stays (0, 0, 1)) unless a realtime directional light is on | Reads Directional (`DIRLIGHTMAP_COMBINED`) and Bakery MonoSH, with lightmapped specular in the MonoSH "highlights" mode |
| `VRChat/Mobile/Lightmapped` | No normal maps at all | The same: it reads only the base colour and the lightmap |

Standard Lite's behaviour: VRChat Worlds SDK 3.10.5 source, `VRChat-Mobile-StandardLite.shader` lines 163-198 and
`VRChat.cginc` lines 273-348, read 2026-10-18.

Decide it with the texturing plan, not after it:

- The world's materials carry normal maps that matter (brick, boards, panelling, any trim bevel): bake Directional
  ("about twice as much video memory as non-directional mode",
  https://docs.unity3d.com/2022.3/Documentation/Manual/class-LightingSettings.html, checked 2026-10-18), or Bakery
  MonoSH (one extra texture; Standard Lite reads it), and count the extra lightmap memory in the budget.
- Lightmap memory is too tight for that: keep Non-Directional, and tell the texturing task to put the surface's shading
  into the base colour and its occlusion (baked AO, cavity) instead of a normal map that would not show; skip normal
  maps that only carry shading.

## A final-quality bake

Iterate with a draft bake, then bake once with final settings. Unity 2022.3.22f1's defaults (a new Lighting
Settings asset, read 2026-10-18): Direct Samples 32, Indirect Samples 512, Environment Samples 256, Max Bounces 2,
Filtering Auto (the OptiX denoiser with a Gaussian filter when OptiX is available, else OpenImageDenoise), Lightmap
Compression High Quality. Filtering and denoiser options:
https://docs.unity3d.com/2022.3/Documentation/Manual/progressive-lightmapper.html (checked 2026-10-18).

| Setting | Final bake (*practice*) | Why |
|---|---|---|
| Indirect Samples | 1024-2048 | Noise and splotches in dark corners come from too few indirect samples; raise these before the denoiser's strength |
| Direct Samples | 64-128 | Smooth penumbrae from area-like lights |
| Environment Samples | 512-1024 in rooms lit through windows or open to the sky | |
| Max Bounces | 3-4 in interiors | Two bounces leave enclosed rooms too dark and flat |
| Filtering | Advanced: OptiX on NVIDIA, else OpenImageDenoise, for indirect; Gaussian radius 1 on direct | Keeps contact shadows sharp |
| Lightmap Compression | High Quality | On Windows, Low, Normal and High Quality all store BC6H at the same size (measured Unity 2022.3.22f1, 2026-10-18): High costs only compression time |
| Scale In Lightmap | Above 1 on the floor around furniture and on walls players stand next to, where contact shadows read | Raise it before the world's Lightmap Resolution; it is the cheaper lever |

Judge the bake on brightened copies of dark renders (`vrchat-world-qa`'s image statistics) for noise and leaks,
from the spec's views.

Android and iOS default to Unity's low-quality lightmap encoding (Unity's defaults read by reflection in a fresh
2022.3.22f1 project on 2026-10-18: Standalone High, Android Low, iOS Low; not measured on a device). Low encoding is
Unity's dLDR, which keeps values up to 2: baked light brighter than that clips on mobile. Check the VRChat project's
Player Settings before relying on the brightest hotspots.

## Lighting design from the spec's look

`look.lighting_mood` in the orchestration spec (or the user's brief) sets the intent; turn it into lights before the
first bake:

- **Key, fill and practicals.** One main source per space (the sun, a window, the brightest lamp), a dimmer fill of the
  opposite colour temperature (sky or moonlight against warm lamps), and practicals: every visible lamp, screen or
  window has a light where it is, or its emission lights the bake.
- **Emissive practicals light the bake** when the material's Global Illumination is Baked (the material inspector's
  Emission > Global Illumination). Standard Lite has emission and, as a surface shader without `nometa`, a meta pass
  for it (SDK 3.10.5 source, inferred from the pragma; not baked here to confirm).
- **Colour temperature.** Warm interiors about 2700-3000 K, daylight about 5500-6500 K, overcast sky and moonlight
  cooler (*practice*). Built-in lights take a temperature only when Graphics Settings has `lightsUseLinearIntensity`
  and `lightsUseColorTemperature` on; otherwise set the colour directly.
- **Contrast.** Keep shadows readable: an ambient (sky) contribution that lifts every shadow flattens the room; a
  room with no fill at all reads black in a headset. Judge exposure by the numbers on renders (QA L7), not by eye
  on a monitor.

## Post-processing (PC only)

VRChat disables post-processing in Android and iOS worlds; on PC it is the last colour step, applied to the whole
view. Unity's Post Processing package (Post Processing Stack v2, `com.unity.postprocessing`) is not in a new VRChat
world project: it is a user install, asked at intake.

- Setup: a Post-process Layer on the scene descriptor's Reference Camera (the player camera copies it) and a global
  Post-process Volume on a layer that layer includes; never the volume on the Reference Camera itself (the SDK warns
  that camera is disabled at runtime: `vrchat-world-sdk-setup`). Keep PC-only volumes out of mobile builds.
- Use: Color Grading with a tonemapper (Neutral, or ACES for a filmic look), white balance, contrast and saturation
  matched to `look.lighting_mood` (or a LUT); Bloom with Threshold 1 or more and a low intensity, so only HDR emissives
  glow. Bloom on emissives only works where the camera renders HDR: check it in the client.
- Leave out in VR (*practice*): Motion Blur, Depth of Field, Chromatic Aberration, Lens Distortion, Grain, heavy
  Vignette and Auto Exposure (eye adaptation pumps as the head turns). Ambient Occlusion and Screen Space Reflections
  are full-screen passes for both eyes every frame, and the baked lighting already carries occlusion.
- Give players a toggle. VRChat has no client-side switch for world post-processing (an open feature request:
  https://feedback.vrchat.com/feature-requests/p/option-to-disable-postprocessing-clientside, checked 2026-10-18),
  and creators provide an in-world one by convention: a local toggle that disables the volume (`vrchat-udon`).
- Package docs: https://docs.unity3d.com/Packages/com.unity.postprocessing@3.4/manual/index.html (checked 2026-10-18).

## PC and mobile lightmaps of different sizes (untested route)

One bake serves every platform (SKILL.md). A lightmap texture's platform override does not survive a re-bake: an
Android override (half size, ASTC 6x6) read back after it was set and was gone after the next bake (Unity 2022.3.22f1,
2026-10-18). A PC-lead world that wants 2048 lightmaps on PC and 1024 on mobile therefore needs a post-bake step that
re-applies the Android and iOS overrides to every lightmap after each bake, and UV2 gaps packed for the mobile
footprint (half the PC one: 4 texels at the PC footprint). Not run end to end here: try it on a copy, and check on a
device that the halved lightmaps keep their 2-texel gaps.

## Shaders with more than Standard (PC)

Standard has no geometric specular anti-aliasing (fine normal detail sparkles in a headset) and reads neither Bakery
MonoSH nor lightmapped specular. Options, each a choice to test on the world:

- `VRChat/Mobile/Standard Lite` has geometric specular anti-aliasing (on by default in its inspector), detail maps,
  Directional and MonoSH lightmaps (SDK 3.10.5 source). VRChat does not recommend it on PC because it ignores realtime
  lighting; a fully baked world uses none on its static surfaces. It is opaque only. Its shader features are switched
  on only by its inspector, so a material made by script sets the keywords too (`vrchat-world-sdk-setup`).
- Community PC world shaders (for example z3y's, whose ShaderGraph target lists Bakery MonoSH, lightmapped specular,
  geometric specular anti-aliasing and bicubic lightmaps: https://github.com/z3y/ShaderGraph, checked 2026-10-18) are
  user installs: check their current feature lists and VRChat compatibility before planning on one.
