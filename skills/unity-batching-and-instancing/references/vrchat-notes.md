# VRChat notes

The rest of this skill is plain Unity Built-in Render Pipeline. This is what differs in a VRChat world (checked
2026-10-17).

| Topic | In VRChat |
|---|---|
| Pipeline | Unity 2022.3.22f1, Built-in Render Pipeline: no SRP Batcher. Shader Graph has a Built-In target in 2022.3 but needs its package in the project; most worlds use hand-written shaders or a maintained Built-in shader family |
| Procedural instancing | Udon cannot call `Graphics.*`: use `VRCGraphics.DrawMeshInstanced` from `VRC.SDKBase` (same 1023 cap, issued every frame, Enable GPU Instancing required or Udon halts). Globals go through `VRCShader.SetGlobal*` with an int ID from `VRCShader.PropertyToID`, names starting `_Udon`. Rules: udon-drawmeshinstanced.md; working script: `scripts/InstancedField.cs` |
| Stereo | The client renders single-pass stereo, not single-pass instanced ("We're still on a special build for Single-Pass-Stereo (not SPS-I)", https://ask.vrchat.com/t/developer-update-25-june-2026/48618). The stereo-instancing macros are harmless and missing ones break no eye; GPU instancing still needs the instancing macros |
| Quest and iOS materials | `VRChat/Mobile/Standard Lite` instances: tick Enable GPU Instancing on the mobile materials too (VRChat's Android guide: "You should be enabling GPU Instancing on all of your materials", https://creators.vrchat.com/platforms/android/quest-content-optimization/). It instances only the transform: a per-copy `_Color` in a MaterialPropertyBlock breaks instancing, so give each colour its own material (each still instances). Only `VRChat/Mobile/Lightmapped` has no instancing variant |
| Quest and iOS budgets | Static batching's combined mesh counts against the 100 MB mobile download limit: check the build size with and without it. Draw-call and material budgets are much tighter (the `vrchat-world-optimization` skill) |
| Per-object scripts | An Udon behaviour on every copy costs more than the draw call saved: keep instanced props script-free (the `vrchat-udon` skill) |

Evidence for Standard Lite: in SDK 3.10.5 it is a surface shader without `noinstancing`, declares an instancing
buffer ("Add instancing support for this shader. You need to check 'Enable Instancing' on materials that use the
shader"), and its material inspector draws the Enable GPU Instancing field. That buffer is empty ("put more
per-instance properties here") and `_Color` is declared outside it (`half4 _Color;`), so only the transform is per
instance.
