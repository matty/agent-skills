# Cross-platform worlds: PC, Android (Quest) and iOS

One world, one blueprint ID, one upload per platform. Sources and check date: end of `../SKILL.md`.

## Steps

1. **Install the platform modules** (Android, iOS) for the project's Unity version in the Unity Hub.
2. **Optimise for mobile before switching.** VRChat's own guide says this step cannot be skipped:
   - lighting baked (realtime lights are expensive enough to write off on Quest; use light probes or Light Volumes
     for dynamic objects);
   - geometry and draw calls within the Quest budgets (`vrchat-world-optimization`);
   - transparency avoided where possible (alpha fill rate is costly on mobile GPUs);
   - textures 1024 or below on Android, through per-platform import overrides rather than separate files
     (`vrchat-texture-and-vram`). Crunch shrinks the download only, not memory.
3. **Shaders.** Shaders are not restricted in Android worlds, but be very careful with custom ones. The recommended
   basic world shader is `Mobile/VRChat/Lightmapped` with baked lighting. Swap materials per platform where the PC
   shader is heavy.
4. **Platform-specific objects.** Things that should exist on one platform only (a PC-only mirror quality, post
   processing volumes, heavy props) are switched per build target. VRChat recommends the EasyQuestSwitch tool from
   the Creator Companion for this. Post-processing is disabled on Android anyway, so PC-only volumes cost nothing
   there but should still be excluded from the Android build to keep the scene clean.
5. **Switch the build target** in the Control Panel > Builder > platforms dropdown (uncheck Windows, check Android,
   Switch). The first switch reimports every asset and takes a long time; later switches are faster.
6. **Validate**: SDK validation messages, Unity console, and a Play-mode test with ClientSim on the Android target.
7. **Same blueprint ID**: the Pipeline Manager on the VRCWorld object holds it. For the second platform, Detach, paste
   the PC world's ID (also in the Control Panel's Content Manager), so both builds are the same world.
8. **Upload** each platform (or select several targets in the platforms dropdown). The build target decides which
   version an upload is.

## Hard limits and restrictions on Android

| Item | Rule |
|---|---|
| Download size | **100 MB** after build-time compression, or the world cannot be uploaded or joined |
| Post-processing | Disabled entirely |
| Cloth | Disabled |
| Audio sources | Restricted in Android worlds: test every audio feature on the Quest build |
| Cameras, rigidbodies, colliders, joints | Allowed; use sparingly |

## iOS

If a world has an Android version but no iOS version, VRChat tries to load the Android version on iOS. Upload an iOS
build for best results. A platform with no compatible version cannot join the world.

## One project or two

Switching the build target in one project keeps everything in one place but reimports on the first switch. Some
creators keep a separate Android copy of the project; then keep shared pieces (colliders, layout) in prefabs or a
placement sync so the copies do not drift, and copy them across after each change. Prefer one project with
per-platform overrides unless reimport time becomes a real problem.
