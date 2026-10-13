// Stable placement id for blender-unity-placement-sync. Host: Unity 2022.3+ (any render pipeline).
// Copy to Assets/World/PlacementSync/PlacementId.cs (a runtime folder, not Editor/: it is a component).
// In a VRChat project it implements VRC.SDKBase.IEditorOnly, so the SDK strips it from uploaded builds.
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
