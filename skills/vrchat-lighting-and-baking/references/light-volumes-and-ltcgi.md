# VRC Light Volumes and LTCGI

Both are community packages added through the Creator Companion. Plan only with what the project already has
(`Packages/vpm-manifest.json`); anything else is a user install. Checked 2026-10-17.

## VRC Light Volumes (REDSIM)

Version 3.x, MIT licence, VPM listing https://redsim.github.io/vpmlisting/index.json, docs in the `Documentation`
folder of https://github.com/REDSIM/VRCLightVolumes. Baked voxel lighting (Regular volumes), Additive volumes that
switch or move with their lamp, and Point, Spot and Area lights with runtime control. It lights only renderers whose
shader supports it; light probes stay required for everything else.

| Topic | Rule | Doc |
|---|---|---|
| Shaders | 3.x: Poiyomi Toon and Pro, Mochie, ORL (Orels), Graphlit (z3y), GeneLit and others; 2.x: lilToon, UnlitWF, Filamented, Xiexe and others. Not Unity Standard (the bundled "Light Volume PBR" is for a quick test). An Android world needs a world shader that supports both Light Volumes and Android; Quest avatars use VRChat's mobile shaders, which do not support it | CompatibleShaders.md |
| Probes | A volume's Generate Light Probes button places a probe set for the shaders that read only probes | HowToUse.md |
| Setup | Hierarchy > Light Volume (the Light Volume Manager is created automatically); Edit Bounds to fit the room; Voxels Per Unit 1 for large open spaces, higher where lighting detail matters; Baking Mode Progressive or Bakery | HowToUse.md |
| Naming | Give every baked volume a unique GameObject name: its textures take that name and overwrite each other | BestPractices.md |
| Overlap | Overlap neighbours at least as wide as their Smooth Blending (0.25 m overlap with a 0.25 m blend), at doorways and passages | BestPractices.md |
| Dynamic | Only for volumes whose position, rotation or scale changes in game; colour and intensity changes do not need it | BestPractices.md |
| Limits | Up to 32 active Regular and Additive volumes combined and 128 active lights; disable the volumes of zones the player has left | README, BestPractices.md |
| Bakery | Fix Light Probes L1 only if Bakery's ordinary probes look burned out or too dark (it reduces ringing and costs contrast); compressed Bakery volumes are not supported | BestPractices.md |
| Runtime | `LightVolumeInstance.SetIntensity(float)`, `SetColor(Color)`, `SetColorAndIntensity(Color, float)` from UdonSharp. A switched lamp: an Additive volume set to intensity 0 (off) or 1 (the baked brightness), never disabled ("Disabling the component or GameObject removes it from the Manager"). Changes are local: sync the state yourself, late joiners included | ScriptingAPI.md |
| Baking a switched lamp | Bake the switchable lamps alone in a copy of the scene into an Additive volume: "disable lights and emissive lighting that do not belong to the switchable group" and "Remove any unwanted environment lighting from this bake as well". Bring the volume (and its textures) back, then "Enable Additive and disable Bake on this volume" (Bake: "Include this volume in the next supported lightmapper bake. Disable it to preserve existing textures"), and "Bake the main scene with the switchable lamps' bake lights disabled. Otherwise their lighting will remain visible when the additive volume is off." Start the volume's Intensity at 1 for a lamp that starts on, 0 for one that starts off. Steps: references/lighting-states.md | HowToUse_RegularLightVolumes.md |
| Lightmapped surfaces | An Additive volume lights static lightmapped surfaces only where their shader supports additive volumes | HowToUse_RegularLightVolumes.md |

## LTCGI (PiMaker)

Realtime area lights from screens, strips and windows using linearly transformed cosines. https://ltcgi.dev/,
https://github.com/PiMaker/ltcgi.

| Topic | Rule | Source |
|---|---|---|
| Cost | "it still equates to real-time lighting": use it sparingly; reflection probes or a simple realtime light are often the better choice | https://ltcgi.dev/ |
| What it scales with | Screens per receiving object; transparent receivers double it; the slowest pixel sets the GPU time. Merge screens, limit Affected Renderers, try diffuse off first | https://ltcgi.dev/Advanced/Performance_Optimization |
| Shaders | Every receiver needs a compatible shader: ORL, Filamented, Mochie, Hekky, z3y, Poiyomi, VixForge Toon. The bundled shaders are for testing. Not Standard | https://github.com/PiMaker/ltcgi |
| Quest and iOS | Lights only receivers whose mobile material uses an LTCGI shader that builds for Android; on VRChat's Standard Lite or Lightmapped it lights nothing. One screen only, with faster settings forced on mobile | https://ltcgi.dev/Advanced/Performance_Optimization, https://github.com/PiMaker/ltcgi |
| Shadows | Shadowmaps baked with Unity's lightmapper or Bakery, for static receivers. They are a second lightmap set (`Assets/LTCGI-Generated/Lightmaps-<scene>`): count it in memory and download. The bake turns static batching off on its receivers on purpose: "By default, LTCGI disables static batching on LTCGI-enabled receivers during the bake", because Unity can bake `unity_LightmapST` into the mesh UVs and break LTCGI's lightmap offsets. Leave it off and count their draw calls. Re-tick the static flags only to try the Controller's experimental Allow Static Batching (1.7.0+): "If you want to test it on an existing scene, manually enable the relevant Static flags again before running a new bake". It "may lead to desynced lightmap UVs at runtime", so check in a build that the LTCGI light is not offset | https://ltcgi.dev/, https://ltcgi.dev/Advanced/Shadowmaps |
| Video | ProTV 3 or newer recommended; other players are supported | https://ltcgi.dev/ |
| Licence | Mixed MIT: free to use with attribution | https://ltcgi.dev/ |
| Light Volumes | Supported since LTCGI 1.7.0 | https://ltcgi.dev/ |

Add LTCGI last, after the world meets its budgets, and measure it on device.
