# Cross-platform worlds: PC, Android (Quest) and iOS

One world, one blueprint ID, one upload per platform. Mobile means Android (Quest) and iOS: "Guidelines that refer to
'Android' or 'Quest' apply to iOS, too". Sources and check dates at the end.

VRChat's order is: install the modules, switch, validate, optimise, upload. A world that is cross-platform from the
start splits it in two phases, so later work is planned for the platform hardest to fit and nothing is redone after
PC publish prep:

- **Early, right after the scene setup, with no switch** (steps 1-2): modules, per-platform overrides, mobile
  materials and per-platform objects. The project stays on Windows.
- **Later** (steps 3-9): one bake in the lighting step; at build time, before the optimisation audit, the switch to
  each mobile target with its errors and a ClientSim pass; then mobile budgets and size, device tests, upload to one
  blueprint ID, and a switch back to Windows.

## Early: set the mobile side up, with no switch

1. **Install the build modules**: Android and iOS Build Support for Unity 2022.3.22f1 in the Unity Hub (both can be
   added at once). iOS also needs a VRChat account that supports it (step 3): ask the user before planning an iOS
   build.
2. **Per-platform setup** (overrides and materials work without switching):
   - Textures 1024 or below through per-platform import overrides, not separate files, set on **both** the Android
     and the iOS tab: Unity keeps them apart, and a platform without an override ships the default size
     (`vrchat-texture-and-vram`). Crunch is no help here: it works only with DXT/ETC formats, not ASTC, and never
     shrinks memory.
   - Mobile materials. Shaders are not restricted in mobile worlds (Android and iOS builds only warn about
     non-mobile ones), but be very careful with custom ones. The SDK's mobile world shaders, by their `Shader.Find`
     names:

     | Shader | Reads | GPU instancing | Use |
     |---|---|---|---|
     | `VRChat/Mobile/Standard Lite` | Albedo, metallic (R) and smoothness (A) map, normal, occlusion, emission, lightmap, light probes | Yes: tick Enable GPU Instancing on its materials | Lit world materials; also what an iOS fallback renders best |
     | `VRChat/Mobile/Lightmapped` | Albedo (`_MainTex`) and the lightmap only: no probes, so dynamic or toggled lighting does not show | No instancing variant | The cheapest baked surfaces |

     Realtime light: VRChat documents both shaders as not supporting real-time lighting (Content Limitations page,
     updated 2025-10-08); Standard Lite's shader source still keeps the main directional light in its base pass,
     without shadows. Either way, bake every light in a cross-platform world. Swap materials per platform where the
     PC shader is heavy.
   - Platform-specific objects: things that should exist on one platform only (a PC-only mirror quality,
     post-processing volumes, heavy props) are switched per build target; VRChat recommends the EasyQuestSwitch tool
     from the Creator Companion. Post-processing is disabled on mobile anyway, but keep PC-only volumes out of mobile
     builds.
## Later: switch, validate, optimise, test on devices, upload

The lighting step bakes once for every platform (every light Baked). Then, at build time and before the optimisation
audit:

3. **Switch the build target** to each mobile target in Control Panel > Builder > platforms dropdown (uncheck Windows,
   check Android or iOS, then confirm: VRChat's page calls the button "Switch", the SDK 3.10.5 dialog "Build Target
   Switcher" says "Confirm"), or from a script (`unity-mcp.md`), and clear the errors it raises. The first switch
   reimports every asset for the new target and takes a long time; later switches are faster.
   - Android: the Builder blocks the build until Build Settings' Android texture compression is ASTC; apply its
     auto-fix (it reimports textures). The SDK sets ASTC itself while another platform is active, so this only
     appears when the setting was changed by hand, or the project was already on Android with another format.
   - iOS: always listed, greyed out until iOS Build Support is installed. Signed in to an account without iOS, an
     iOS target is the build-blocking error "iOS is not supported as a build target.", which has no auto-fix; signed
     out, nothing warns.
4. **Validate**: SDK validation messages, the Unity console, and a Play-mode test with ClientSim on the mobile target.
5. **Optimise for mobile.** VRChat's guide: "You cannot skip this."
   - One bake serves every platform: every light Baked; light probes for dynamic objects.
   - Geometry, draw calls and texture memory within the mobile budgets (`vrchat-world-optimization`); transparency
     avoided, alpha cutout included ("alpha cutout counts as transparency").
   - The download under the mobile limit (table below).
6. **Build & Test on each device:**
   - Android / Quest: Unity's ADB copies the build to a device on USB with developer mode and USB debugging on
     (Quest: switched to developer mode through Meta Quest Developer Hub). Before the first test, launch VRChat on the
     device once so it creates its folders, then close it: the app must be closed when the first test launches.
     Keep the device unlocked.
   - iOS (SDK 3.8.1 and later), in this order: switch the Builder to iOS and wait for `[VTP] Listening on port
     9002...` in the console; press Show Local IP Address in the SDK's Settings tab; on the iPhone or iPad, enter
     that address in the device's Settings app under Apps > VRChat > SDK IP Address; launch VRChat and enter a
     world; allow the local-network prompt on the device (and Windows' firewall prompt for Unity, Public networks
     too); wait for `[VTP] Client connected.`; then press Build & Test. Both devices on one Wi-Fi, VPN off.
7. **Same blueprint ID.** One project: nothing to do, the Pipeline Manager on the `VRCWorld` object keeps the ID
   across target switches. A separate copy of the project: on its Pipeline Manager press Detach and paste the first
   upload's ID (also shown in the Control Panel's Content Manager).
8. **Upload** each platform, or select several targets in the platforms dropdown. The build target decides which
   version an upload is.
9. **Switch back to Windows** when done, so the project is where the PC work and the next session expect it.

## Hard limits and restrictions on Android and iOS

| Item | Rule |
|---|---|
| Download size | **100 MB after build-time compression** (VRChat's MB is 2^20 bytes: 104,857,600 bytes). Larger worlds cannot be uploaded or joined on mobile |
| Uncompressed size | No SDK limit for worlds (SDK 3.10.5) |
| Post-processing | Disabled entirely |
| Cloth | Disabled |
| Audio sources | Disabled on mobile avatars (Content Limitations page, 2025-10-08); for worlds VRChat says only "restricted" (optimisation page, 2025-06-25), without detail. They cost CPU: keep them few and test on the device |
| Cameras, rigidbodies, colliders, joints | Allowed; use sparingly |

## iOS fallback

VRChat is testing a fallback: a world with an Android version but no iOS version may load the Android version on
iOS, which works best for content on Standard Lite. Upload an iOS build for best results; a platform with no
compatible version cannot enter the world.

## One project or two

Switching the build target in one project keeps everything in one place but reimports on the first switch. Some
creators keep a separate Android copy of the project; then keep shared pieces (colliders, layout) in prefabs or a
placement sync so the copies do not drift, and copy them across after each change. Prefer one project with
per-platform overrides unless reimport time becomes a real problem.

## Sources (checked 2026-10-17)

- Order, steps, the blueprint ID, the iOS fallback and cutout as transparency (updated 2026-09-15):
  https://creators.vrchat.com/platforms/android/cross-platform-setup/
- Mobile limits and optimisation (updated 2025-06-25): https://creators.vrchat.com/platforms/android/quest-content-optimization/
- Mobile shaders, GPU instancing, realtime lighting and audio (updated 2025-10-08): https://creators.vrchat.com/platforms/android/quest-content-limitations/
- Android guidelines apply to iOS: https://creators.vrchat.com/platforms/iOS/
- Build & Test on a device: https://creators.vrchat.com/platforms/android/build-test-mobile/ and
  https://creators.vrchat.com/platforms/iOS/build-test-mobile
- What the shaders read, the size constants, the unsupported-shader warning, the iOS and ASTC checks:
  `sdk-observed.md` (SDK 3.10.5)
