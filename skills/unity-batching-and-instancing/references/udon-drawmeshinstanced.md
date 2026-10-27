# Instanced drawing from Udon (`VRCGraphics.DrawMeshInstanced`)

Udon cannot call Unity's `Graphics.*`. VRChat exposes a wrapper instead: `VRCGraphics` and `VRCShader` in the
**`VRC.SDKBase`** namespace (VRCSDKBase.dll, read from SDK 3.10.5 on 2026-10-17), so a script needs
`using VRC.SDKBase;`. Page: https://creators.vrchat.com/worlds/udon/vrc-graphics/ (checked 2026-10-17).

## The API (SDK 3.10.5)

| Call | Rules |
|---|---|
| `VRCGraphics.DrawMeshInstanced(Mesh mesh, int submeshIndex, Material material, Matrix4x4[] matrices, ...)` | The same overloads as Unity's `Graphics.DrawMeshInstanced`, after `matrices`: `int count`, `MaterialPropertyBlock properties`, `ShadowCastingMode castShadows`, `bool receiveShadows`, `int layer`, `Camera camera`, `LightProbeUsage lightProbeUsage`, `LightProbeProxyVolume lightProbeProxyVolume`. Arrays only (no `List<Matrix4x4>`). At most 1023 instances per call. Unspecified, `castShadows` is `ShadowCastingMode.On` and `receiveShadows` true |
| The material | **Enable GPU Instancing** ticked, or Unity throws `InvalidOperationException` ("InvalidOperationException will be thrown if the material doesn't have Material.enableInstancing set to true") and Udon halts the behaviour: nothing is drawn |
| `VRCShader.PropertyToID(string)` | Call once in `Start()` and keep the int; the global's name must start with `_Udon` (or be `_AudioTexture`) |
| `VRCShader.SetGlobalVector(int, Vector4)` and the other `SetGlobal*` | Take only the int ID (no string overloads); every shader in the world, avatars included, can read the value |
| `VRCGraphics.Blit(...)` | The destination must not be null. On Quest the shader needs `ZTest Always`, or the target RenderTexture must have no depth, or the blit fails |

Unity's side: https://docs.unity3d.com/2022.3/Documentation/ScriptReference/Graphics.DrawMeshInstanced.html
(checked 2026-10-17): "You can only draw a maximum of 1023 instances at once", and the instances are culled as one
group, never one by one.

## When this is the right tool

Good for many identical, purely decorative copies: grass, debris, crowd fillers, stars, particles-as-geometry, LED
arrays. It skips per-GameObject transforms, culling and components entirely. Grass on uneven or lit ground needs more
than the example script gives (section What the example does not do).

Wrong for anything that needs colliders, interaction or per-copy culling: a thousand copies behind a wall still cost
their vertex work, and occlusion culling never removes single copies.

## The pattern: `scripts/InstancedField.cs`

An UdonSharp behaviour (class `InstancedField`) that builds its matrices once in `Start()` from a fixed seed (every
player sees the same field, no sync), groups the copies by grid cell (`cellSize`, 10 m by default) into batches of up
to 1023, gives each batch a MaterialPropertyBlock with a per-instance `_Color` array, sets the `_UdonWindParams`
global once, and in `Update()` draws each batch with shadows off, skipping cells the local player is far from.
Each cell is one draw call, so `cellSize` trades draw calls against culling: Unity culls a batch as one group, and a
batch spread over the whole field is never culled. `scripts/InstancedUnlit.shader` is a matching material shader
(per-instance colour, height-weighted sway from `_UdonWindParams` and `_Time`). Tested 2026-10-17 in Unity
2022.3.22f1 with SDK 3.10.5: the shader compiled in every variant on D3D11, GLES3 and Vulkan; the script
UdonSharp-compiled and ClientSim-tested (10,000 copies in 144 cells: 131 batches drawn with the player at the
centre, 0 at 200 m, no exceptions). Give it a mesh asset from the project, not a Unity built-in primitive (such as
the Cube from `Resources.GetBuiltinResource`): those read as null in Udon.

Every Udon extern the script calls exists in SDK 3.10.5 (read from VRC.Udon.Wrapper.dll and
VRC.Udon.VRCWrapperModules.dll on 2026-10-17):

| Call in the script | Udon extern |
|---|---|
| `VRCGraphics.DrawMeshInstanced(mesh, 0, material, batch, batch.Length, block, shadows, false)` | `VRCSDKBaseVRCGraphics.__DrawMeshInstanced__UnityEngineMesh_SystemInt32_UnityEngineMaterial_UnityEngineMatrix4x4Array_SystemInt32_UnityEngineMaterialPropertyBlock_UnityEngineRenderingShadowCastingMode_SystemBoolean__SystemVoid` |
| `VRCShader.PropertyToID("_UdonWindParams")` | `VRCSDKBaseVRCShader.__PropertyToID__SystemString__SystemInt32` |
| `VRCShader.SetGlobalVector(id, wind)` | `VRCSDKBaseVRCShader.__SetGlobalVector__SystemInt32_UnityEngineVector4__SystemVoid` |
| `new MaterialPropertyBlock()`, `block.SetVectorArray("_Color", tints)` | `UnityEngineMaterialPropertyBlock.__ctor____UnityEngineMaterialPropertyBlock`, `UnityEngineMaterialPropertyBlock.__SetVectorArray__SystemString_UnityEngineVector4Array__SystemVoid` |
| `material.enableInstancing` | `UnityEngineMaterial.__get_enableInstancing__SystemBoolean` |
| `Matrix4x4.TRS`, `Quaternion.Euler` | `UnityEngineMatrix4x4.__TRS__UnityEngineVector3_UnityEngineQuaternion_UnityEngineVector3__UnityEngineMatrix4x4`, `UnityEngineQuaternion.__Euler__SystemSingle_SystemSingle_SystemSingle__UnityEngineQuaternion` |
| `Random.InitState`, `Random.Range`, `Random.value` | `UnityEngineRandom.__InitState__SystemInt32__SystemVoid`, `__Range__SystemSingle_SystemSingle__SystemSingle`, `__get_value__SystemSingle` |
| `Color.Lerp`, `c.r` ... `c.a`, `new Vector4(...)` | `UnityEngineColor.__Lerp__UnityEngineColor_UnityEngineColor_SystemSingle__UnityEngineColor`, `__get_r__SystemSingle` (and g, b, a), `UnityEngineVector4.__ctor__SystemSingle_SystemSingle_SystemSingle_SystemSingle__UnityEngineVector4` |
| `Vector3.Distance`, `Vector3.zero`, `+`, `/` | `UnityEngineVector3.__Distance__UnityEngineVector3_UnityEngineVector3__SystemSingle`, `__get_zero__UnityEngineVector3`, `__op_Addition__...`, `__op_Division__UnityEngineVector3_SystemSingle__UnityEngineVector3` |
| `Networking.LocalPlayer`, `Utilities.IsValid`, `GetPosition()` | `VRCSDKBaseNetworking.__get_LocalPlayer__VRCSDKBaseVRCPlayerApi`, `VRCSDKBaseUtilities.__IsValid__SystemObject__SystemBoolean`, `VRCSDKBaseVRCPlayerApi.__GetPosition__UnityEngineVector3` |
| `Mathf.Min`, `Mathf.Max`, `Debug.LogError(msg, this)` | `UnityEngineMathf.__Min__SystemInt32_SystemInt32__SystemInt32`, `__Max__SystemSingle_SystemSingle__SystemSingle`, `__Max__SystemInt32_SystemInt32__SystemInt32`, `UnityEngineDebug.__LogError__SystemObject_UnityEngineObject__SystemVoid` |
| `Mathf.CeilToInt`, `Mathf.FloorToInt`, `Mathf.Clamp`, `int[]` | `UnityEngineMathf.__CeilToInt__SystemSingle__SystemInt32`, `__FloorToInt__SystemSingle__SystemInt32`, `__Clamp__SystemInt32_SystemInt32_SystemInt32__SystemInt32`, `SystemInt32Array.__ctor__SystemInt32__SystemInt32Array` (and `__Get__`, `__Set__`) |

`Matrix4x4[][]` is a jagged array, which UdonSharp stores as `object[]`; `ShadowCastingMode` is in Udon's type list.

## What the example does not do (grass on a terrain)

`InstancedField.cs` scatters on a flat plane at the GameObject's height (every copy at `origin + (x, 0, z)`), varies
only yaw and tint (scale is always 1), and `InstancedUnlit.shader` is unlit and opaque: no lightmap, no light probes,
no alpha test. That is enough for a flat lawn of solid blades in flat light, not for grass on a terrain, where it
floats or sinks, repeats visibly and does not take the ground's lighting. A terrain field needs, in this order:

1. Heights sampled at edit time: an editor script raycasts each copy down onto the ground collider and stores the
   positions (and the ground normal, to tilt each copy to the slope) in serialized arrays the behaviour only reads;
   never raycast per frame.
2. Per-copy scale jitter as well as yaw, so no clump reads as a repeated stamp.
3. A lit, alpha-tested instancing shader: a surface shader with `alphatest:_Cutoff` and the instancing buffer
   (instanced-shader.md); surface shaders get light probes and lightmaps. Drawn through `DrawMeshInstanced`, per-copy
   probe lighting needs `LightProbeUsage.CustomProvided` with the probe data in the MaterialPropertyBlock (Unity's
   DrawMeshInstanced page: "To render the instances with light probes, provide the light probe data via the
   MaterialPropertyBlock"); whether Udon exposes the calls that fill it is not checked here. Where the field's
   lighting changes (shade under trees, a building's shadow), real renderers with GPU instancing get probe lighting
   per renderer without that.
4. On Quest and iOS, cutout cards are expensive: VRChat says to "avoid transparency at all costs! It is quite
   expensive", and "alpha cutout" counts as transparency
   (https://creators.vrchat.com/platforms/android/cross-platform-setup/, checked 2026-10-27). Cards near paths
   only, with a short `drawDistance` measured on the device; opaque tufts or the ground texture beyond.

## Cost notes

- Build the matrices once. Rebuilding transforms per frame in Udon costs far more than the draw call saves: Udon
  runs 200x-1000x slower than compiled C#.
- Animate in the shader (time-driven sway, scroll, audio-reactive), not in the Udon loop. Set a global such as
  `_UdonWindParams` once through `VRCShader.SetGlobalVector(id, value)`; the shader adds `_Time`.
- Use the cheapest mesh: 1000 instances x 500 triangles is 500k triangles drawn with no culling.
- Gate by distance per batch, never per instance.
- Pass `ShadowCastingMode.Off` unless the shadows matter: the default casts them.

## Verifying

- Frame Debugger: one `Draw Mesh (instanced)` event per call, with its instance count.
- Nothing drawn and an Udon error with `InvalidOperationException`: the material's Enable GPU Instancing is off.
- Every copy the same colour: the shader reads `_Color` outside `UNITY_INSTANCING_BUFFER`, or the fragment stage
  lacks `UNITY_SETUP_INSTANCE_ID` (instanced-shader.md).
