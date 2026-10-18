// Stable placement id for blender-unity-placement-sync. Host: Unity 2022.3+ (any render pipeline).
// Copy to Assets/World/PlacementSync/PlacementId.cs (a runtime folder, not Editor/: it is a component).
// In a VRChat project it implements VRC.SDKBase.IEditorOnly, which makes the SDK's validation ignore it instead of
// flagging an incompatible script (https://creators.vrchat.com/sdk/build-pipeline-callbacks-and-interfaces, checked
// 2026-10-17; a PC build validated clean with these components in the scene, 2026-10-16).
// It is an added component on each placed prefab instance: never Apply or Revert it through the prefab Overrides menu
// (Apply pushes one id into the kit prefab for every instance, Revert deletes the id).
using UnityEngine;

namespace PlacementSync
{
    [DisallowMultipleComponent]
    [AddComponentMenu("Placement Sync/Placement Id")]
    public class PlacementId : MonoBehaviour
#if VRC_SDK_VRCSDK3
        , VRC.SDKBase.IEditorOnly
#endif
    {
        [Tooltip("Shared with the Blender placement's 'placement_id'. Do not edit by hand.")]
        public string id;
    }
}
