// InstancedUnlit.shader: a minimal Built-in Render Pipeline unlit shader with GPU instancing, a per-instance
// colour and an optional wind sway.
//
// Host: Unity 2022.3.22f1, Built-in Render Pipeline (the VRChat world pipeline). Compiled 2026-10-17: 14 of 14
// variants on D3D11, GLES3 and Vulkan, the instanced vertex program distinct from the plain one. In a scene, check
// that the Frame Debugger shows "Draw Mesh (instanced)".
//
// Use: put it in Assets/, make a material from it and tick Enable GPU Instancing. Per-instance _Color comes from a
// MaterialPropertyBlock: renderer.SetPropertyBlock with SetColor("_Color", ...) on real renderers, or
// SetVectorArray("_Color", colours) for Graphics/VRCGraphics.DrawMeshInstanced (see InstancedField.cs).
// Wind: a global _UdonWindParams (xyz = sway direction x amplitude in metres, w = speed). From Udon it is set with
// VRCShader.SetGlobalVector(VRCShader.PropertyToID("_UdonWindParams"), ...); unset, it is zero and nothing sways.
// The stereo macros cost nothing: they matter under single-pass instanced stereo and are harmless otherwise.

Shader "Custom/InstancedUnlit"
{
    Properties
    {
        _MainTex ("Texture", 2D) = "white" {}
        _Color ("Color", Color) = (1, 1, 1, 1)
    }
    SubShader
    {
        Tags { "RenderType" = "Opaque" "Queue" = "Geometry" }

        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_instancing      // generates the instanced variant (required)
            #pragma multi_compile_fog
            #include "UnityCG.cginc"

            struct appdata
            {
                float4 vertex : POSITION;
                float2 uv : TEXCOORD0;
                UNITY_VERTEX_INPUT_INSTANCE_ID
            };

            struct v2f
            {
                float4 pos : SV_POSITION;
                float2 uv : TEXCOORD0;
                UNITY_FOG_COORDS(1)
                UNITY_VERTEX_INPUT_INSTANCE_ID      // carries the instance id to the fragment stage
                UNITY_VERTEX_OUTPUT_STEREO
            };

            sampler2D _MainTex;
            float4 _MainTex_ST;
            float4 _UdonWindParams;                 // global, not a material property

            // Per-instance properties live in this buffer; setting any other property through a
            // MaterialPropertyBlock disables instancing for that renderer.
            UNITY_INSTANCING_BUFFER_START(Props)
                UNITY_DEFINE_INSTANCED_PROP(float4, _Color)
            UNITY_INSTANCING_BUFFER_END(Props)

            v2f vert (appdata v)
            {
                v2f o;
                UNITY_SETUP_INSTANCE_ID(v);
                UNITY_INITIALIZE_OUTPUT(v2f, o);
                UNITY_TRANSFER_INSTANCE_ID(v, o);
                UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);

                float3 worldPos = mul(unity_ObjectToWorld, float4(v.vertex.xyz, 1.0)).xyz;
                float sway = sin(_Time.y * _UdonWindParams.w + worldPos.x + worldPos.z) * saturate(v.vertex.y);
                worldPos += _UdonWindParams.xyz * sway;    // weighted by height above the pivot: the base stays put

                o.pos = UnityWorldToClipPos(worldPos);
                o.uv = TRANSFORM_TEX(v.uv, _MainTex);
                UNITY_TRANSFER_FOG(o, o.pos);
                return o;
            }

            fixed4 frag (v2f i) : SV_Target
            {
                UNITY_SETUP_INSTANCE_ID(i);         // without it every instance reads instance 0's colour
                fixed4 col = tex2D(_MainTex, i.uv) * UNITY_ACCESS_INSTANCED_PROP(Props, _Color);
                UNITY_APPLY_FOG(i.fogCoord, col);
                return col;
            }
            ENDCG
        }
    }
}
