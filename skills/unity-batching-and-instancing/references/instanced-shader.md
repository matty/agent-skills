# Writing an instancing-compatible shader (Built-in RP + VRChat stereo)

Two things share the same machinery in VRChat: **GPU instancing** and **Single Pass Instanced stereo rendering** (each eye is an instance). Get the macros wrong and you either lose instancing or get eye-swapped / one-eye rendering in the headset. Always test in VR, not just the Game view.

## Minimal unlit shader with a per-instance color

```hlsl
Shader "Custom/InstancedUnlit"
{
    Properties
    {
        _MainTex ("Texture", 2D) = "white" {}
        _Color   ("Color", Color) = (1,1,1,1)
    }
    SubShader
    {
        Tags { "RenderType"="Opaque" "Queue"="Geometry" }

        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_instancing      // required: generates the instanced variant
            #include "UnityCG.cginc"

            struct appdata
            {
                float4 vertex : POSITION;
                float2 uv     : TEXCOORD0;
                UNITY_VERTEX_INPUT_INSTANCE_ID
            };

            struct v2f
            {
                float2 uv  : TEXCOORD0;
                float4 pos : SV_POSITION;
                UNITY_VERTEX_INPUT_INSTANCE_ID     // carries the id to the fragment stage
                UNITY_VERTEX_OUTPUT_STEREO         // required for Single Pass Instanced
            };

            sampler2D _MainTex;
            float4 _MainTex_ST;

            // Per-instance properties MUST live in this buffer, or setting them
            // through a MaterialPropertyBlock breaks the instanced batch.
            UNITY_INSTANCING_BUFFER_START(Props)
                UNITY_DEFINE_INSTANCED_PROP(float4, _Color)
            UNITY_INSTANCING_BUFFER_END(Props)

            v2f vert (appdata v)
            {
                v2f o;
                UNITY_SETUP_INSTANCE_ID(v);
                UNITY_TRANSFER_INSTANCE_ID(v, o);
                UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
                o.pos = UnityObjectToClipPos(v.vertex);
                o.uv  = TRANSFORM_TEX(v.uv, _MainTex);
                return o;
            }

            fixed4 frag (v2f i) : SV_Target
            {
                UNITY_SETUP_INSTANCE_ID(i);
                UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(i);
                return tex2D(_MainTex, i.uv) * UNITY_ACCESS_INSTANCED_PROP(Props, _Color);
            }
            ENDCG
        }
    }
}
```

## Surface shader variant

```hlsl
#pragma surface surf Standard fullforwardshadows addshadow
#pragma multi_compile_instancing
#pragma target 3.0

UNITY_INSTANCING_BUFFER_START(Props)
    UNITY_DEFINE_INSTANCED_PROP(float4, _Color)
UNITY_INSTANCING_BUFFER_END(Props)

void surf (Input IN, inout SurfaceOutputStandard o)
{
    fixed4 c = tex2D(_MainTex, IN.uv_MainTex) * UNITY_ACCESS_INSTANCED_PROP(Props, _Color);
    o.Albedo = c.rgb;
    o.Alpha  = c.a;
}
```

Surface shaders insert the instancing plumbing automatically; you only add the pragma and the buffer. Add `addshadow` if per-instance vertex deformation must show in shadows.

## Driving per-instance values

**From C#/Udon on real renderers** — one MaterialPropertyBlock per renderer, only touching properties declared in the instancing buffer:

```csharp
var mpb = new MaterialPropertyBlock();
renderer.GetPropertyBlock(mpb);
mpb.SetColor("_Color", myColor);     // _Color is inside UNITY_INSTANCING_BUFFER → batch survives
renderer.SetPropertyBlock(mpb);
```

Setting a property that is *not* in the buffer (or any property on a non-instanced shader) turns the object into its own draw call. This is the single most common cause of "instancing is on but nothing batches".

**For `DrawMeshInstanced`** — one MaterialPropertyBlock for the whole call, with array setters indexed per instance:

```csharp
mpb.SetVectorArray("_Color", colorsPerInstance);   // length == matrices.Length, max 1023
```

## Gotchas

- **Shader Graph does not work in Built-in RP** — hand-write, or use a maintained BiRP shader family.
- `UNITY_ACCESS_INSTANCED_PROP` requires `UNITY_SETUP_INSTANCE_ID` to have run in that stage; skipping it in `frag` reads instance 0 for everything.
- Instanced properties cost constant-buffer space and thus reduce instances per batch. Keep the buffer to what varies.
- Textures cannot be per-instance. Vary a UV offset into an atlas instead.
- If the shader has multiple passes (extra forward-add passes from realtime lights), each pass is instanced separately and the lights eat the win — bake the lighting.
- Verify in the Frame Debugger: the draw should read `Draw Mesh (instanced)` with a count > 1.
