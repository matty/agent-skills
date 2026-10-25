# Engine notes: which normal map to download

Both libraries ship OpenGL (Y+) and DirectX (Y-) normal maps; they differ only in the green channel. Download the one
the target reads (`--normal gl|dx`); `--normal both` when unsure, or when the maps serve more than one engine.

| Target | Convention | Source |
|---|---|---|
| Unity (Built-in, URP, HDRP) | OpenGL, Y+ (`--normal gl`) | "Unity uses Y+ normal maps", "sometimes known as OpenGL format": https://docs.unity3d.com/2022.3/Documentation/Manual/StandardShaderMaterialParameterNormalMap.html (checked 2026-10-18) |
| Blender | OpenGL, Y+ (`--normal gl`) | Measured 2026-10-25: Poly Haven's own `blend` bundle for red_brick_03 includes `nor_gl`, not `nor_dx` |
| glTF | OpenGL, Y+ (`--normal gl`) | Measured 2026-10-25: Poly Haven's `gltf` bundle includes `nor_gl` |
| Unreal Engine | DirectX, Y- (`--normal dx`) | Third-party sources only, not checked against Epic's docs: https://www.strayspark.studio/blog/directx-vs-opengl-normal-maps-explained, https://cgaxis.com/which-normal-map-should-i-use-opengl-or-directx/ |
| Godot | OpenGL, Y+ (`--normal gl`); its importer can invert Y | Third-party sources only: https://godotforums.org/d/29629-with-materials-in-godot-do-normal-maps-need-to-have-the-green-channel-flipped |

Channel packing (Unity's metallic-smoothness, glTF's ORM) is texturing work, not part of downloading. Poly Haven's
`ARM` map uses glTF's order (R occlusion, G roughness, B metallic), which Unity's Standard shader does not read.
