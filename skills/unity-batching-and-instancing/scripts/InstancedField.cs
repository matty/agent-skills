// InstancedField.cs: draw many copies of one mesh from Udon with VRCGraphics.DrawMeshInstanced, batched by grid cell
// (up to 1023 per call), with a per-instance tint, shadows off by default and a per-batch distance check.
//
// Host: Unity 2022.3.22f1 with the VRChat Worlds SDK 3.10.5 (UdonSharp ships inside the Worlds SDK since 3.4.0).
// Status: UdonSharp-compiled and ClientSim-tested 2026-10-17 in Unity 2022.3.22f1 with SDK 3.10.5: 10,000 copies in
// 144 cells, 131 batches drawn with the player at the centre, 0 at 200 m, no exceptions. Every type and Udon extern
// it calls is listed in references/udon-drawmeshinstanced.md.
//
// Setup: Assets > Create > U# Script named InstancedField, replace its contents with this file, and add the
// component to an empty GameObject at the centre of the field. Assign a low-poly mesh asset from the project (not a
// Unity built-in primitive: those read as null in Udon), drawn every frame for every copy in reach, and a material
// with Enable GPU Instancing ticked; Custom/InstancedUnlit (InstancedUnlit.shader, next to this file) reads the
// per-instance _Color and the _UdonWindParams sway.
// The layout comes from a fixed seed, so every player sees the same field without any network sync.

using UdonSharp;
using UnityEngine;
using UnityEngine.Rendering;
using VRC.SDKBase;

[UdonBehaviourSyncMode(BehaviourSyncMode.None)]
public class InstancedField : UdonSharpBehaviour
{
    [Tooltip("Low-poly mesh: every copy is drawn every frame.")]
    [SerializeField] private Mesh mesh;
    [Tooltip("Enable GPU Instancing must be ticked, or the draw call throws and Udon halts this behaviour.")]
    [SerializeField] private Material material;
    [SerializeField] private int count = 1000;
    [SerializeField] private float radius = 25f;
    [Tooltip("Same seed on every client = the same layout for every player.")]
    [SerializeField] private int seed = 12345;
    [Tooltip("Copies are batched by square cells of this size (m): culling and the distance check skip whole cells.")]
    [SerializeField] private float cellSize = 10f;
    [Tooltip("A batch is skipped while the local player is farther than this from its nearest copy.")]
    [SerializeField] private float drawDistance = 60f;
    [SerializeField] private bool castShadows = false;
    [SerializeField] private Color tintA = Color.white;
    [SerializeField] private Color tintB = Color.white;
    [Tooltip("xyz = sway direction x amplitude (m), w = speed; read by Custom/InstancedUnlit as _UdonWindParams.")]
    [SerializeField] private Vector4 wind = new Vector4(0.05f, 0f, 0.03f, 1.5f);

    private const int MaxPerCall = 1023;            // Graphics.DrawMeshInstanced draws at most 1023 per call

    private Matrix4x4[][] _matrices;
    private MaterialPropertyBlock[] _blocks;
    private Vector3[] _centres;
    private float[] _extents;
    private bool _ready;

    private void Start()
    {
        if (mesh == null || material == null || !material.enableInstancing)
        {
            Debug.LogError("[InstancedField] needs a mesh and a material with Enable GPU Instancing ticked", this);
            return;
        }

        // Global shader values take an int ID, and their names must start with _Udon.
        VRCShader.SetGlobalVector(VRCShader.PropertyToID("_UdonWindParams"), wind);

        // 1. Every copy's position, yaw, tint and grid cell, from the seed.
        Random.InitState(seed);
        Vector3 origin = transform.position;
        int cellsPerSide = Mathf.Max(1, Mathf.CeilToInt(2f * radius / cellSize));
        int cells = cellsPerSide * cellsPerSide;
        Vector3[] positions = new Vector3[count];
        float[] yaws = new float[count];
        Vector4[] tints = new Vector4[count];
        int[] cellOf = new int[count];
        int[] cellCount = new int[cells];
        for (int i = 0; i < count; i++)
        {
            float x = Random.Range(-radius, radius);
            float z = Random.Range(-radius, radius);
            positions[i] = origin + new Vector3(x, 0f, z);
            yaws[i] = Random.Range(0f, 360f);
            Color tint = Color.Lerp(tintA, tintB, Random.value);
            tints[i] = new Vector4(tint.r, tint.g, tint.b, tint.a);
            int cx = Mathf.Clamp(Mathf.FloorToInt((x + radius) / cellSize), 0, cellsPerSide - 1);
            int cz = Mathf.Clamp(Mathf.FloorToInt((z + radius) / cellSize), 0, cellsPerSide - 1);
            int cell = cz * cellsPerSide + cx;
            cellOf[i] = cell;
            cellCount[cell] = cellCount[cell] + 1;
        }

        // 2. Order the copies by cell (a counting sort), so each cell's copies sit together.
        int[] cellStart = new int[cells];
        int batchCount = 0;
        int running = 0;
        for (int cell = 0; cell < cells; cell++)
        {
            cellStart[cell] = running;
            running += cellCount[cell];
            batchCount += (cellCount[cell] + MaxPerCall - 1) / MaxPerCall;
        }
        int[] order = new int[count];
        int[] placed = new int[cells];
        for (int i = 0; i < count; i++)
        {
            int cell = cellOf[i];
            order[cellStart[cell] + placed[cell]] = i;
            placed[cell] = placed[cell] + 1;
        }

        // 3. One batch per cell (more when a cell holds over 1023 copies), so Unity's group culling and the
        //    distance check in Update skip whole cells.
        _matrices = new Matrix4x4[batchCount][];
        _blocks = new MaterialPropertyBlock[batchCount];
        _centres = new Vector3[batchCount];
        _extents = new float[batchCount];
        int b = 0;
        for (int cell = 0; cell < cells; cell++)
        {
            int start = cellStart[cell];
            int remaining = cellCount[cell];
            while (remaining > 0)
            {
                int n = Mathf.Min(remaining, MaxPerCall);
                Matrix4x4[] batch = new Matrix4x4[n];
                Vector4[] batchTints = new Vector4[n];
                Vector3 sum = Vector3.zero;
                for (int k = 0; k < n; k++)
                {
                    int i = order[start + k];
                    batch[k] = Matrix4x4.TRS(positions[i], Quaternion.Euler(0f, yaws[i], 0f), Vector3.one);
                    batchTints[k] = tints[i];
                    sum += positions[i];
                }

                Vector3 centre = sum / n;
                float extent = 0f;
                for (int k = 0; k < n; k++)
                {
                    extent = Mathf.Max(extent, Vector3.Distance(centre, positions[order[start + k]]));
                }

                MaterialPropertyBlock block = new MaterialPropertyBlock();
                block.SetVectorArray("_Color", batchTints);   // one value per instance, same order as the matrices

                _matrices[b] = batch;
                _blocks[b] = block;
                _centres[b] = centre;
                _extents[b] = extent;
                b++;
                start += n;
                remaining -= n;
            }
        }
        _ready = true;
    }

    private void Update()                           // re-issued every frame: nothing persists between frames
    {
        if (!_ready) return;

        VRCPlayerApi local = Networking.LocalPlayer;
        Vector3 eye = Utilities.IsValid(local) ? local.GetPosition() : transform.position;
        ShadowCastingMode shadows = castShadows ? ShadowCastingMode.On : ShadowCastingMode.Off;

        for (int b = 0; b < _matrices.Length; b++)
        {
            if (Vector3.Distance(eye, _centres[b]) > drawDistance + _extents[b]) continue;
            Matrix4x4[] batch = _matrices[b];
            VRCGraphics.DrawMeshInstanced(mesh, 0, material, batch, batch.Length, _blocks[b], shadows, false);
        }
    }
}
