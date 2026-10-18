# Lighting states: a light players can switch, baked

VRChat gives Udon no way to swap lightmaps ("VRChat does not allow you access to change Lightmaps directly"), and a
second bake replaces the first. So each lighting state is its own copy of the static geometry, baked once together
with the other states, and Udon shows one copy at a time. Method from the VRChat wiki
(https://wiki.vrchat.com/wiki/How_to_swap_out_Baked_Lightmaps, edited 2026-04-16), with the placement and probe
rules this skill adds. Checked 2026-10-17.

## Layout in the scene

| Object | Where | Renders | Notes |
|---|---|---|---|
| Placed originals of the switched pieces | Under MASTER, as placement sync made them | No: Mesh Renderers off | They keep their colliders and their place in placement sync |
| State copies | Under a root of their own (for example `LIGHT_STATES`), outside MASTER | Yes | Render-only: Mesh Renderers on, colliders removed. Copies duplicated from the originals arrive the other way round (renderers off, colliders on): fix both. Placement sync never sees them |
| Per state | Two parents: the static geometry, and that state's lights and reflection probes | | Build the first state's pair, then duplicate it once per further state |

A piece that must change with the switch is lightmapped in every copy, even a small prop that would otherwise be
probe-lit (`lightmap_budget.py` KIND `lightmap`), and every copy counts in the capacity. `--states N` multiplies
every piece: use it only when everything lightmapped switches. For one switched room in a larger world, give only
that room's pieces `"states": N` in `--json`. After a placement sync changes a switched piece, rebuild the copies
from the originals and re-bake.

## Where each copy sits during the bake

Baked light probes do not move afterwards. Unity: "You can't move Light Probes by updating the Transform component
of the Light Probe Group object, because the Transform only affects baking"
(https://docs.unity3d.com/Manual/LightProbes-Moving.html); in 2022.3, `LightProbes.positions` are the "Positions of
the baked light probes (Read Only)" (https://docs.unity3d.com/2022.3/Documentation/ScriptReference/LightProbes-positions.html).
And "it is not possible to bake 2 or more different versions of Lightprobes" (wiki). So:

1. The copy whose state avatars should match sits at the origin, inside the probe group.
2. The other copies sit far away. A copy that must not get the sun goes far below a large plane, and a sunlit copy
   far above it: a directional light reaches every copy at any distance, and the wiki uses the plane "to block the
   directional light used for the day version creeping into the night version".
3. The plane: Contribute GI on, Cast Shadows Shadows Only ("This Renderer casts shadows, but the Renderer itself
   isn't visible"), Scale In Lightmap 0 ("the Renderer not being lightmapped, but it still contributes to lighting
   other Renderers") (https://docs.unity3d.com/2022.3/Documentation/Manual/class-MeshRenderer.html).
4. One directional light at most; a distant spot light stands in for a second sun.

## Bake and switch

1. "Leave the skybox in your Lighting tab blank": one bake has one environment, and a day sky would light every copy.
2. "Make sure your Reflection Probes have full coverage of your world", because "the fallback Reflection Probe is
   derived from the skybox set in the Lighting tab", which is now empty. Each state's reflection probes sit in its
   lights parent and move with it.
3. Bake once, then set every state's parents back to the origin.
4. "Please have all your baked variants enabled by default when loading in!": Unity batches them at load. In Udon's
   `OnEnable`, disable every state but the starting one and set its sky; a variant disabled in the editor renders
   unbatched.
5. To switch, enable one state's parents, disable the others, and set `RenderSettings.skybox` (and
   `RenderSettings.customReflectionTexture`, if the world uses one). Both setters are Udon externs in SDK 3.10.5
   (`UnityEngineRenderSettings.__set_skybox__UnityEngineMaterial__SystemVoid`,
   `__set_customReflectionTexture__UnityEngineTexture__SystemVoid`). Sync the state for late joiners (the
   `vrchat-udon` skill).

## The Light Volumes alternative

With VRC Light Volumes installed and world shaders that read additive volumes, one baked copy is enough
(https://github.com/REDSIM/VRCLightVolumes, Documentation/HowToUse_RegularLightVolumes.md and ScriptingAPI.md,
checked 2026-10-17). Standard and Standard Lite do not read them: on those the switch changes nothing.

1. "Save a copy of the scene for the additive bake. Open it on its own." Keep the room geometry, "disable lights
   and emissive lighting that do not belong to the switchable group", and "Remove any unwanted environment lighting
   from this bake as well" (Lighting window > Environment > Environment Lighting: Source Color, black), or the sky's
   light is baked into the volume and added a second time when the lamp turns on. Place the volume around the
   lamps' light, with the light fading before its edge, and bake it.
2. "Preserve the baked volume as a prefab, or copy its GameObject, and bring it into the main scene. Keep the
   generated texture assets."
3. "Enable **Additive** and disable **Bake** on this volume." Bake means "Include this volume in the next supported
   lightmapper bake. Disable it to preserve existing textures": left on, the main bake overwrites the lamp-only
   light with the room's own.
4. "Bake the main scene with the switchable lamps' bake lights disabled. Otherwise their lighting will remain visible
   when the additive volume is off." If the main scene is not baked again, click Pack Light Volumes.
5. Intensity 1 is the baked brightness ("Restore the original bake") and 0 is off. Set the volume's Inspector
   Intensity to the lamp's starting state (1 on, 0 off), and switch with `LightVolumeInstance.SetIntensity`, never
   by disabling it: "Disabling the component or GameObject removes it from the Manager." The change is local: sync
   the state and apply it on start and for late joiners (the `vrchat-udon` skill).
