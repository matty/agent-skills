# Quest, iOS and cross-platform lighting: what the SDK actually does

VRChat applies its Android rules to iOS: "Guidelines that refer to 'Android' or 'Quest' apply to iOS, too"
(https://creators.vrchat.com/platforms/iOS/). A cross-platform world is one scene with one bake, switched per build
target, so its lighting has to work on the weakest platform. Everything below was read from the VRChat Worlds SDK
3.10.5 source on 2026-10-17; re-read it after an SDK update.

## The mobile world shaders

Source files: `Packages/com.vrchat.base/Runtime/VRCSDK/Sample Assets/Shaders/Mobile/VRChat-Mobile-StandardLite.shader`
and `VRChat-Mobile-Lightmapped.shader` in a VRChat project.

| | `VRChat/Mobile/Standard Lite` | `VRChat/Mobile/Lightmapped` |
|---|---|---|
| Kind | Surface shader: `#pragma surface surf StandardVRC vertex:vert exclude_path:prepass exclude_path:deferred noforwardadd noshadow nodynlightmap nolppv noshadowmask` | Legacy `Vertex` and `VertexLM` passes, "no lighting" |
| Reads | Albedo, metallic (R) + smoothness (A) map, normal, occlusion, emission, detail; lightmaps, including Bakery MonoSH | Albedo and the lightmap |
| Light probes | Yes | No: a dynamic object on it is unlit |
| Realtime lights | The main directional light only, unshadowed: `noforwardadd` gives "one full directional light" in the base pass, and `VRChat.cginc` adds `light.color * nl`. Other lights are per-vertex or SH, which lightmapped surfaces skip, so point and spot lights do not show on them | No |
| Realtime shadows received | No (`noshadow`) | No |
| Shadowmask | No (`noshadowmask`) | No |
| GPU instancing | Yes: it declares an instancing buffer and its material inspector shows Enable GPU Instancing: tick it | No instancing variant |

VRChat documents Standard Lite and Lightmapped as not supporting real-time lighting: Standard Lite is "Not
recommended on PC because it does not support real-time lighting", Lightmapped is "only meant for use on worlds"
and "does not support real-time lighting" (https://creators.vrchat.com/platforms/android/quest-content-limitations/,
updated 2025-10-08, checked 2026-10-17). Standard Lite's shader source still adds the main directional light in its
base pass, without shadows, so a realtime sun leaks light through walls on Quest; point and spot lights do not show
on lightmapped surfaces.
Either way, bake every light in a cross-platform world.

## The quality presets the SDK enforces

`Packages/com.vrchat.base/Editor/VRCSDK/Dependencies/VRChat/EnvConfig.cs` resets the project's quality levels to
VRChat's presets; PC defaults to "High", Android and iOS to "Mobile". The client's graphics settings can lower them.

| Setting | PC "High" | "Mobile" |
|---|---|---|
| Realtime shadows | All | Disable |
| Shadow distance | 150 | 50 |
| Pixel light count | 8 | 4 |
| Shadowmask mode | Shadowmask | Shadowmask |
| Realtime reflection probes | on | off |

Distance Shadowmask became opt-in on PC in SDK 3.10.5 (https://creators.vrchat.com/releases/release-3-10-5/): Udon sets
`VRCQualitySettings.ShadowmaskMode`. Udon can also turn realtime reflection probes back on, on every platform, with
`VRCQualitySettings.RealtimeReflectionProbes` (both in `VRC.SDK3.Rendering`, SDK 3.10.5).

## Consequences

- **Keep every light Baked in a cross-platform world.** A Mixed light's direct light is realtime in Shadowmask and
  Baked Indirect mode: on Quest a Mixed or Realtime sun lights Standard Lite surfaces with no shadows (light through
  walls), Lightmapped surfaces not at all, and Mixed point and spot lights lose their direct light. Subtractive's one
  realtime directional shadow cannot show either: the Mobile preset turns shadows off and Standard Lite receives none.
- **Max Lightmap Size 1024** whenever the world ships to Quest or iOS: the one bake serves every platform.
- **Mixed + Shadowmask only in a PC-only world** that needs realtime sun shadows on avatars.
- **Light probes light every Quest and iOS avatar.** VRChat restricts mobile avatars to its own mobile shaders,
  which read probes, not VRC Light Volumes (Light Volumes support in Toon Standard is an open feature request:
  https://feedback.vrchat.com/open-beta/p/sdk-381-beta4-support-vrc-light-volumes-in-toon-standard).
- **VRC Light Volumes on mobile** need a world shader that supports both Light Volumes and Android: the VRChat mobile
  world shaders do not. **LTCGI on mobile** lights only receivers whose mobile material uses an LTCGI shader that
  builds for Android, with one screen: on Standard Lite or Lightmapped it lights nothing (no SDK 3.10.5 file mentions
  LTCGI, and LTCGI's compatible-shader list names no Android shader).
- **Reflection probes**: baked. Realtime reflection probes are off in the Mobile preset unless Udon turns them on.
- **Lightmaps on mobile** import as ASTC (about 0.45 bytes per pixel): Non-Directional halves them again.
- **Switchable lights on Quest and iOS**: lighting states, or a Light Volumes additive volume where the shaders
  support it. A realtime point or spot light is a PC-only extra.
