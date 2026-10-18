# Writing an instancing-compatible shader (Built-in RP)

GPU instancing needs the shader's cooperation: an instanced variant, an instance ID passed through, and every
per-instance value in the instancing buffer. A complete, commented example is `scripts/InstancedUnlit.shader`
(unlit, per-instance colour, fog, optional wind sway; compiled 2026-10-17 in Unity 2022.3.22f1, 14 of 14 variants on
D3D11, GLES3 and Vulkan). Unity's page:
https://docs.unity3d.com/2022.3/Documentation/Manual/gpu-instancing-shader.html (checked 2026-10-17).

## Vertex/fragment shaders: the macros

| Where | Macro | Why |
|---|---|---|
| Pass | `#pragma multi_compile_instancing` | Generates the instanced variant: required for vertex/fragment shaders |
| Vertex input struct | `UNITY_VERTEX_INPUT_INSTANCE_ID` | The instance ID |
| Vertex output struct | `UNITY_VERTEX_INPUT_INSTANCE_ID` | Only if the fragment stage reads per-instance properties |
| Top of the vertex shader | `UNITY_SETUP_INSTANCE_ID(v)` | Required: selects this instance's matrices and properties |
| Vertex shader | `UNITY_TRANSFER_INSTANCE_ID(v, o)` | Copies the ID to the fragment stage |
| Top of the fragment shader | `UNITY_SETUP_INSTANCE_ID(i)` | Without it, every instance reads instance 0's properties |
| Global scope | `UNITY_INSTANCING_BUFFER_START(Props)`, `UNITY_DEFINE_INSTANCED_PROP(float4, _Color)`, `UNITY_INSTANCING_BUFFER_END(Props)` | Per-instance properties |
| Wherever it is read | `UNITY_ACCESS_INSTANCED_PROP(Props, _Color)` | Reads this instance's value |

The stereo macros (`UNITY_VERTEX_OUTPUT_STEREO`, `UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO`) matter only under
single-pass instanced stereo. The VRChat client renders single-pass stereo, not single-pass instanced ("We're still
on a special build for Single-Pass-Stereo (not SPS-I)", developer update 2026-06-25:
https://ask.vrchat.com/t/developer-update-25-june-2026/48618), so in a VRChat world they are harmless and leaving
them out breaks no eye. Keep them: they cost nothing and keep the shader correct in a plain Unity project that
renders single-pass instanced.

## Surface shaders

Unity generates instancing variants for surface shaders by default (unless `#pragma surface ... noinstancing`) and
ignores `#pragma multi_compile_instancing` in them. Add only the buffer:

```hlsl
CGPROGRAM
#pragma surface surf Standard fullforwardshadows
#pragma target 3.0

sampler2D _MainTex;
struct Input { float2 uv_MainTex; };

UNITY_INSTANCING_BUFFER_START(Props)
    UNITY_DEFINE_INSTANCED_PROP(float4, _Color)
UNITY_INSTANCING_BUFFER_END(Props)

void surf (Input IN, inout SurfaceOutputStandard o)
{
    fixed4 c = tex2D(_MainTex, IN.uv_MainTex) * UNITY_ACCESS_INSTANCED_PROP(Props, _Color);
    o.Albedo = c.rgb;
    o.Alpha = c.a;
}
ENDCG
```

With `_MainTex` and `_Color` in the shader's Properties block. Add `addshadow` when per-instance vertex deformation
must show in shadows.

## Driving per-instance values

**On real renderers**, one MaterialPropertyBlock per renderer, touching only properties declared in the buffer
(works from C# and from UdonSharp: Udon exposes `MaterialPropertyBlock` and `Renderer.SetPropertyBlock`):

```csharp
var mpb = new MaterialPropertyBlock();
renderer.GetPropertyBlock(mpb);
mpb.SetColor("_Color", myColor);     // batches only on a shader that declares _Color per instance, as above
renderer.SetPropertyBlock(mpb);
```

Unity: "Don't put non-instanced properties in the MaterialPropertyBlock, because this disables instancing." This is
the most common cause of "instancing is on but nothing batches". Standard and Standard (Specular) instance "with no
per-instance properties other than the transform"
(https://docs.unity3d.com/2022.3/Documentation/Manual/gpu-instancing-shader.html), and VRChat's Standard Lite
(SDK 3.10.5) has an empty instancing buffer: all three declare `_Color` as a plain uniform (`half4 _Color;`), so
the snippet above breaks instancing on them. Give those copies one material per colour (each still instances), or
switch to an instancing shader.

**For DrawMeshInstanced**, one MaterialPropertyBlock for the whole call, with array setters indexed per instance:

```csharp
mpb.SetVectorArray("_Color", colorsPerInstance);   // one entry per matrix, at most 1023
```

## Gotchas

- Shader Graph has a Built-In Render Pipeline target in Unity 2022.3 (Shader Graph 14:
  https://docs.unity3d.com/Packages/com.unity.shadergraph@14.0/manual/Graph-Target.html); check that the generated
  shader instances (Frame Debugger) before relying on it. In VRChat the Shader Graph package has to be in the project;
  hand-written shaders or a maintained Built-in shader family are the usual route.
- Per-instance properties take constant-buffer space and lower the instances per batch (500 by default; Unity sizes
  the array from the device's constant buffer). Keep the buffer to what varies.
- Textures cannot vary per instance: vary a UV offset into an atlas instead.
- Realtime per-pixel lights: Standard's forward-add pass has no instancing variant (only its ForwardBase, ShadowCaster
  and Deferred passes do), so every object an extra pixel light touches gets its own draw. Measured 2026-10-16: one
  shadowless point light took a one-room world's view from 9 to 18 SetPass calls. Bake the lighting.
- Check in the Frame Debugger: the draw reads `Draw Mesh (instanced)` with a count above 1.
