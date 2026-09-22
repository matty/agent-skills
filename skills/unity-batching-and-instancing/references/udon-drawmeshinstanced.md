# Instanced drawing from Udon (`VRCGraphics.DrawMeshInstanced`)

Unity's `Graphics.*` immediate-mode API is not whitelisted in Udon. VRChat exposes a small wrapper instead, in `VRC.SDK3.Rendering`:

- `VRCGraphics.DrawMeshInstanced(...)` — one draw call for up to **1023** copies of a mesh.
- `VRCGraphics.Blit(...)` — shader blit into a RenderTexture. **Destination must not be null.** On Quest the shader needs `ZTest Always`, or the target RenderTexture must have depth disabled, or the blit fails.
- `VRCShader.SetGlobal*` + `VRCShader.PropertyToID(...)` — push globals to shaders. The property name **must start with `_Udon`** (or be exactly `_AudioTexture`). Resolve the ID once in `Start()` and reuse it.

Overload lists change between SDK versions — confirm the exact signature with UdonSharp IntelliSense or the Udon node browser before relying on one. Reference: https://creators.vrchat.com/worlds/udon/vrc-graphics/

## When this is the right tool

Good for **many identical, purely decorative** objects: grass, debris, crowd fillers, stars, floating particles-as-geometry, LED arrays. It skips the per-GameObject transform, culling and component overhead entirely.

Bad for anything that needs colliders, interaction, individual culling or occlusion — the whole group is culled as one unit, and individual instances are **not** frustum- or occlusion-culled. A thousand instances behind a wall still cost vertex work.

## Pattern

```csharp
using UdonSharp;
using UnityEngine;
using VRC.SDK3.Rendering;

[UdonBehaviourSyncMode(BehaviourSyncMode.None)]
public class InstancedField : UdonSharpBehaviour
{
    [SerializeField] private Mesh mesh;              // low-poly: this is drawn every frame
    [SerializeField] private Material material;      // Enable GPU Instancing MUST be ticked
    [SerializeField] private int count = 1000;
    [SerializeField] private float radius = 25f;

    private const int BATCH = 1023;                  // hard cap per call
    private Matrix4x4[][] _batches;

    void Start()
    {
        int batchCount = (count + BATCH - 1) / BATCH;
        _batches = new Matrix4x4[batchCount][];

        int remaining = count;
        for (int b = 0; b < batchCount; b++)
        {
            int n = remaining > BATCH ? BATCH : remaining;
            remaining -= n;

            Matrix4x4[] m = new Matrix4x4[n];
            for (int i = 0; i < n; i++)
            {
                Vector3 pos = transform.position + new Vector3(
                    Random.Range(-radius, radius), 0f, Random.Range(-radius, radius));
                Quaternion rot = Quaternion.Euler(0f, Random.Range(0f, 360f), 0f);
                m[i] = Matrix4x4.TRS(pos, rot, Vector3.one);
            }
            _batches[b] = m;
        }
    }

    void Update()   // must be re-issued every frame; nothing persists
    {
        for (int b = 0; b < _batches.Length; b++)
        {
            VRCGraphics.DrawMeshInstanced(mesh, 0, material, _batches[b]);
        }
    }
}
```

## Cost notes

- The matrices are built **once** in `Start()`. Rebuilding transforms per frame in Udon costs far more than the draw call saved — Udon is 200×–1000× slower than C#.
- Animation should live in the **shader** (time-driven sway, scroll, audio-reactive), not in the Udon loop. Drive it with `VRCShader.SetGlobalVector("_UdonWindParams", ...)` once per frame, or just `_Time`.
- Use the cheapest possible mesh. 1000 instances × 500 triangles is 500k triangles with no culling.
- Consider distance gating: skip whole batches when the local player is far away (one distance check per batch per frame is cheap; per-instance checks are not).
- Shadow casting multiplies the cost — pass shadow flags off unless the shadows matter.

## Verifying

Frame Debugger shows one `Draw Mesh (instanced)` entry per call with the instance count. If you see 1000 separate draws, the material does not have GPU Instancing enabled or the shader lacks `#pragma multi_compile_instancing` — see `instanced-shader.md`.
