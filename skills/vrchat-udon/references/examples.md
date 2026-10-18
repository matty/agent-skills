# Example UdonSharp classes

Each class follows the rules in `../SKILL.md`. Four compiled with no errors on 2026-10-17 in Unity 2022.3.22f1 with
the UdonSharp in Worlds SDK 3.10.5, exporting the expected entry points: `SyncedToggle` `_start`, `_interact`,
`_onDeserialization` (synced `_isOn`); `Chime` `_interact`, `Ring`; `ShaderDriver` `_start`, `__0_Push` (UdonSharp's
name for a public method with parameters); `SlowCheck` `_start`, `_Tick`. `HoopScore` was UdonSharp-compiled and
ClientSim-tested on 2026-10-17 (its section says what that test covers). Recompile after an SDK update.

## A manual-sync toggle

Anyone can press it; everyone, including late joiners, sees the same state.

```csharp
using UdonSharp;
using UnityEngine;
using VRC.SDKBase;

[UdonBehaviourSyncMode(BehaviourSyncMode.Manual)]
public class SyncedToggle : UdonSharpBehaviour
{
    public GameObject target;
    [UdonSynced] private bool _isOn;

    void Start()
    {
        _Apply();                          // default state; late joiners then get OnDeserialization
    }

    public override void Interact()
    {
        if (!Networking.IsOwner(gameObject))
            Networking.SetOwner(Networking.LocalPlayer, gameObject);
        _isOn = !_isOn;
        _Apply();
        RequestSerialization();            // send once, when the state changes
    }

    public override void OnDeserialization()
    {
        _Apply();
    }

    private void _Apply()                  // called directly, so private
    {
        target.SetActive(_isOn);
    }
}
```

## A network event with a parameter

A one-off effect for everyone present. Late joiners do not get it, so it must not carry lasting state.

```csharp
using UdonSharp;
using UnityEngine;
using VRC.SDK3.UdonNetworkCalling;
using VRC.Udon.Common.Interfaces;

[UdonBehaviourSyncMode(BehaviourSyncMode.NoVariableSync)]
public class Chime : UdonSharpBehaviour
{
    public AudioSource bell;

    public override void Interact()
    {
        SendCustomNetworkEvent(NetworkEventTarget.All, nameof(Ring), 0.8f);   // 0.8f: the type must match
    }

    [NetworkCallable(maxEventsPerSecond: 2)]
    public void Ring(float volume)
    {
        bell.volume = volume;
        bell.Play();
    }
}
```

## Counting a basket once

`OnTriggerEnter` fires on every client that sees the ball pass, so each would add a point. Only the ball's owner
reports it, and only the hoop's owner changes the score. UdonSharp-compiled and ClientSim-tested on 2026-10-17 in Unity
2022.3.22f1 with Worlds SDK 3.10.5: two balls with VRC Object Sync dropped through the trigger counted 1, then 2.
ClientSim runs `Owner`-targeted events locally whoever the owner is, so that test covers the counting, not the routing
to the owner: check that with two clients. The TextMeshPro label needs TMP Essential Resources in the project
(Window > TextMeshPro > Import TMP Essential Resources).

```csharp
using UdonSharp;
using UnityEngine;
using VRC.SDKBase;
using VRC.SDK3.UdonNetworkCalling;
using VRC.Udon.Common.Interfaces;

[UdonBehaviourSyncMode(BehaviourSyncMode.Manual)]
public class HoopScore : UdonSharpBehaviour
{
    public TMPro.TextMeshProUGUI label;
    [UdonSynced] private int _score;

    void Start() { _Apply(); }

    private void OnTriggerEnter(Collider other)
    {
        // every client sees the ball: only its owner reports the basket
        if (other == null || !Networking.IsOwner(other.gameObject)) return;
        SendCustomNetworkEvent(NetworkEventTarget.Owner, nameof(AddPoint));
    }

    [NetworkCallable(maxEventsPerSecond: 5)]
    public void AddPoint()                 // runs on the hoop's owner only
    {
        _score++;
        _Apply();
        RequestSerialization();
    }

    public override void OnDeserialization() { _Apply(); }

    private void _Apply() { label.text = _score.ToString(); }
}
```

## Driving a shader global

One global value per frame instead of moving hundreds of objects. Every shader in the world, avatars included, can
read it.

```csharp
using UdonSharp;
using UnityEngine;
using VRC.SDKBase;

[UdonBehaviourSyncMode(BehaviourSyncMode.None)]
public class ShaderDriver : UdonSharpBehaviour
{
    private int _udonThingId;

    void Start()
    {
        _udonThingId = VRCShader.PropertyToID("_UdonThing");   // global names start with _Udon
    }

    // Called by other scripts. With a parameter and no [NetworkCallable] it is never callable over the network.
    public void Push(Vector4 value)
    {
        VRCShader.SetGlobalVector(_udonThingId, value);        // the int ID: there is no string overload
    }
}
```

## A slow loop instead of `Update()`

```csharp
using UdonSharp;
using UnityEngine;

[UdonBehaviourSyncMode(BehaviourSyncMode.None)]
public class SlowCheck : UdonSharpBehaviour
{
    public float interval = 0.2f;

    void Start()
    {
        SendCustomEventDelayedSeconds(nameof(_Tick), interval);
    }

    public void _Tick()                    // public: called by name; "_": not callable over the network
    {
        // the slow work goes here
        SendCustomEventDelayedSeconds(nameof(_Tick), interval);
    }
}
```
