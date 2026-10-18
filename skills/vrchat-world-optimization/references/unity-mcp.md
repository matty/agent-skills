# Measuring from a script (Unity MCP)

For an agent measuring a world through Unity MCP. `execute_code` wraps the C# in a static method with only
`using System; System.Collections.Generic; System.Linq; System.Reflection; UnityEngine; UnityEditor;` (MCP for Unity,
read 2026-10-17), so write `UnityEngine.Object` rather than a bare `Object` (ambiguous) and give every other type its
full name. The method returns `object`: end every path with `return` (a string to report). Instead of `Tuple`
(Unity's ExCSS.Unity also defines `System.Tuple`: CS0433) use `KeyValuePair`, a value tuple or an anonymous type; a
class cannot be declared inside the body (CS1513). Measured 2026-10-16 in Unity 2022.3.22f1 with Worlds SDK 3.10.5
unless a line says otherwise; the snippets compiled under that exact wrapper on 2026-10-17.

## Draw calls at a view

1. Enter Play mode with the world scene open (ClientSim spawns the local player).
2. Place a temporary camera at the view (position, target, field of view), render it, and read
   `UnityEditor.UnityStats` (`batches`, `setPassCalls`, `triangles`).
3. First copy the culling mask of ClientSim's player camera (`GameObject.Find("PlayerCamera").GetComponent<Camera>()`)
   onto the temporary camera. With the default mask it also draws ClientSim's local avatar body, which sits on layer
   18 (MirrorReflection): measured 16 batches instead of 8 at one view.
4. Measure the worst view in each zone (the busiest corner, looking across the most geometry), not the average.
5. Destroy the camera, leave Play mode, and reopen the scene from disk with
   `UnityEditor.SceneManagement.EditorSceneManager.OpenScene(path)` rather than saving it: exiting Play leaves the
   scene flagged dirty with nothing changed.

## Texture memory

Read each texture's storage size, through the internal editor method `UnityEditor.TextureUtil.GetStorageMemorySizeLong`
(static, reached by reflection) or from the import inspector. Storage size is for the active build target's import:
measure on the mobile target, or, still on Windows, compute it from each importer's
`GetPlatformTextureSettings("Android")` / `("iPhone")` (size, format) and the bytes per pixel of that format. The
Profiler's `GetRuntimeMemorySizeLong` also counts any CPU copy the editor keeps of a loaded texture, so it can read up
to twice the GPU size: 2x in the 2026-10-16 dry run, 1.00-1.01x for nine textures on 2026-10-17. Measured: a
1024 x 1024 ASTC 6x6 texture with mipmaps stores 626,288 bytes.

## Download size without a build

A real size needs a signed-in build (the SDK Builder shows it afterwards). Without one (no build module, no sign-in),
estimate it and label it an estimate:

1. For each platform, the compressed texture data at that platform's import format (per-platform overrides included),
   deflated.
2. Plus meshes, the scene and lighting data, and an allowance of 1-2 MB for Standard shader variants.

Replace the estimate with the Builder's figure after the first signed-in build.

## Units

VRChat's MB is 2^20 bytes (1,048,576): the SDK checks the mobile world limit against 104,857,600 bytes and shows sizes
in that unit (Worlds SDK 3.10.5 `ValidationHelpers`, read 2026-10-17). Report MB the same way.
