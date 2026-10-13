# VRChat notes

The rest of this skill is plain Unity Built-in Render Pipeline. This is what differs in a VRChat world.

| Topic | In VRChat |
|---|---|
| Pipeline | Unity 2022.3, Built-in Render Pipeline: no SRP Batcher, no Shader Graph shaders |
| Procedural instancing | Udon cannot call `Graphics.*`. Use `VRCGraphics.DrawMeshInstanced` (same 1023 cap, called every frame); globals go through `VRCShader.SetGlobal*` with property names starting `_Udon`. Pattern and rules: `udon-drawmeshinstanced.md` |
| Stereo | VR clients render Single Pass Instanced: every shader must carry the stereo instancing macros or it breaks in one eye (`instanced-shader.md`) |
| Quest / Android | Static batching's combined mesh counts against the 100 MB download limit; check the build report with and without it. Budgets for draw calls and materials are much tighter (`vrchat-world-optimization`) |
| Per-object scripts | Udon behaviours on every copy cost more than the draw call saved; keep instanced props script-free (`vrchat-udon`) |

Source for the Udon graphics API: https://creators.vrchat.com/worlds/udon/vrc-graphics/
