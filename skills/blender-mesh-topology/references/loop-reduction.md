# Reducing an over-dense structured low

For a game mesh that is too dense but already laid out as loops: face grids joined by bands, swept shells, soft
boxes, lathe props. A remesher throws the layout and the UV seams away; designing a grid does not fit a mesh that was
not generated from sections. Keep a subset of its own loops instead.

## The tool

`scripts/loop_decimate.py`, in Blender:

```python
ns = {}; exec(open(r"<skill>/scripts/loop_decimate.py", encoding="utf-8").read(), ns)
dense = ob.copy(); dense.data = ob.data.copy()                  # the original, to measure against
r = ns["loop_decimate"](ob, tol=0.0025)                         # every UV map protected (the default)
dev = ns["deviation"](dense, ob, samples="faces")               # max, p95, mean in metres
bpy.data.objects.remove(dense)
```

- It removes, one at a time, the edge loop that leaves the least sag, while that sag plus the sag already removed next
  to it stays within `tol`. Sag: each loop vertex's distance to the segment between its two neighbours across the
  loop.
- Never removed: a loop with a marked seam, a UV seam on a protected map, a sharp edge, a material boundary or an open
  edge on it, a loop touching a triangle or an n-gon, or one ending at an interior vertex of 3 edges. A loop may end
  at the rim (that vertex goes, sag-checked) or at a pole of 5 or more edges (the pole stays).
- So the result is still clean quads, and every protected UV map keeps its corners on the vertices kept: existing
  bakes and lightmap UVs stay valid.
- Set `tol` from the viewing distance: about the relief that still reads there (`detail_scale.py`, 3.5 mm at 0.5 m),
  then measure with `deviation` and render before and after with `review_render.compare`. Run `topology_audit` after.
- Run it before custom normals (Weighted Normal, Harden Normals): dissolving faces does not carry them.
- It is pure Python over bmesh and recomputes the loops after every removal: seconds for a prop, minutes for
  hundreds of thousands of faces. Split a big set into its parts.

Measured on 2026-10-26 (from GitHub issue #11, Blender 5.2.2): upholstery 232,090 to 113,928 triangles at 2.5 mm
(max mostly 2-4 mm, p95 at most 1.8 mm); lounge upholstery 40,362 to 25,978 with every UV map protected; a ceiling
bezel 384 to 216 (0.9 mm); flat plates 108 to 12. `topology_audit` found nothing new on any. Repo test: an open tube
of 64 x 10 quads (r 0.3 m) at 2.5 mm keeps one row and 32-40 of its 64 segments, 1.44 mm measured.

## Traps

| Trap | What happens | Do instead |
|---|---|---|
| A probe-lit piece, every UV map protected | its lightmap UV often has one chart per face, so every loop carries a seam and nothing goes | `protect_uv=["UVMap"]` (the texture UV only), then redo the lightmap UV |
| A lathe prop already at the chord rule | no loop is under `tol`; that is the answer, not a failure | read it as the measurement: the prop is as light as its nearest viewing distance allows |
| Selected-to-active bake onto the reduced low | where parts sit millimetres apart (cushions beside arms and back), rays hit the neighbouring part first and whole islands bake flat | bake each loose part against only its own dense part |
| Re-quadding a triangulated grid before reducing it | `bmesh.ops.join_triangles` (60 deg thresholds) leaves mixed pairs; "the diagonal is the longest edge of both triangles" misses where a long side is within 2% of it (a 6 mm piping row); a greedy best-rectangle match still strands triangles (24 on an 864-triangle cushion, median corner error 21.5 deg) | read the lattice instead: from row 0 and column 0 of the border, `g[i][j]` is the one common neighbour of `g[i-1][j]` and `g[i][j-1]` other than `g[i-1][j-1]`. That is exact on a quad grid and on any triangulation of one, since a diagonal only joins vertices already one step apart. Then rebuild the quads and run `loop_decimate` |
| A bmesh layer added after faces are held | later use of those faces raises `ReferenceError: BMesh data of type BMFace has been removed` | create every layer (`bm.faces.layers.int.new`, `bm.verts.layers.float.new`) before taking any element reference |
