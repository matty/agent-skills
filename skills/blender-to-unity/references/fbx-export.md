# FBX settings for Unity: export and import, annotated

The single source for every setting: each exporter keyword `scripts/batch_export_fbx.py` sets has one row here, and
the Unity import table is what `scripts/unity/Editor/KitImport.cs` applies (two rows are left to you). Static world
geometry; rigged or animated assets differ where a row says so.

Sources, checked 2026-10-17: the Blender 5.2 API (https://docs.blender.org/api/current/bpy.ops.export_scene.html and
https://docs.blender.org/api/current/bpy.ops.import_scene.html), the FBX exporter shipped with Blender 5.2.2, and
Unity's Model tab reference (https://docs.unity3d.com/2022.3/Documentation/Manual/FBXImporter-Model.html). Measured
end to end on Blender 5.2.2 and Unity 2022.3.22f1 (dry run, 2026-10-16): pieces arrive at rotation 0, scale 1, with
the sizes they have in Blender.

## Blender export: what goes in

| Field | Value | Why |
|---|---|---|
| Limit to / Source Collection | kit pieces: the piece collection by name (`collection=<Piece>` with `use_selection=False`); interactive runs: Selected Objects (`use_selection=True`) | Exporting the collection takes every mesh in it, hidden or not: a selection silently drops hidden LODs and `_COL` shells, because Blender cannot select hidden objects |
| Visible Objects | off (`use_visible=False`) | Hidden LODs and `_COL` shells belong in the FBX |
| Object Types | Mesh only (`object_types={"MESH"}`); add Armature only for a rigged asset | Cameras, lights and empties would become GameObjects in the prefab. LOD meshes need no parent empty |
| Custom Properties | off (`use_custom_props=False`) | Noise |
| Path Mode | kit pieces: Strip (`path_mode="STRIP"`); a one-off asset that brings its own textures: Copy (`path_mode="COPY"`) | Copy writes a `<name>.fbm` folder with a copy of every texture beside each FBX. Strip copies nothing, but the FBX still names each texture: an absolute FileName (the export folder plus the file name, which does not exist), the bare RelativeFilename, and the source .blend path in the header. Harmless when Unity remaps materials by name (`unity-packaging.md`); it does record the machine's folder layout |
| Embed Textures | off (`embed_textures=False`) | Only meaningful with Copy, and it bloats the FBX |

## Transform

| Field | Value | Why |
|---|---|---|
| Scale | 1.0 (`global_scale=1.0`) | Do the conversion with Apply Scalings, not here |
| Apply Unit | on (`apply_unit_scale=True`) | Uses the scene's unit settings; keep the scene's Unit Scale at 1.0 |
| Apply Scalings | FBX All (`apply_scale_options="FBX_SCALE_ALL"`) | Unit conversion goes into the FBX's unit scale (UnitScaleFactor 100, coordinates in metres), so Unity's transform reads scale 1. The default, All Local (`FBX_SCALE_NONE`), writes UnitScaleFactor 1 and puts the 100x on each object's transform with Bake Space Transform off, or into the vertices with it on (measured, 5.2.2); FBX Units Scale also works with Unity's Convert Units, but FBX All is the predictable one |
| Forward | -Z Forward (`axis_forward="-Z"`, the default) | With Y Up, Blender's -Y (a piece's front) becomes Unity's +Z |
| Up | Y Up (`axis_up="Y"`, the default) | Unity is Y up |
| Use Space Transform | on (`use_space_transform=True`, the default) | Applies the axis conversion to the root objects' rotations; the next row moves it into the vertices |
| Bake Space Transform (labelled Apply Transform) | on (`bake_space_transform=True`; the default is off) | The axis change goes into the vertices, so every root arrives in Unity at rotation 0 and Unity = (-x, z, -y). With it off the root reads X -90 or 270, which breaks prefab roots at identity and placement sync, and Unity's Bake Axis Conversion does not undo it. Blender marks it experimental and broken with armatures and animation: for rigged or animated assets leave it off and accept the root rotation |

Apply rotation and scale in Blender (`Ctrl+A > Rotation & Scale`) regardless: exporter settings cannot fully
compensate for a dirty transform. A grid piece's bottom-left pivot becomes its +X/+Z corner in Unity, so its mesh
runs into -X and -Z (a 2 x 3 m wall 0.2 m thick spans x -2..0, z -0.2..0): that is the axis mapping, not an error.

## Geometry

| Field | Value | Why |
|---|---|---|
| Smoothing | Face (`mesh_smooth_type="FACE"`) | Normals are always exported and Unity's default Normals: Import uses them, so smoothing survives with any option; Face adds smoothing groups for importers that calculate normals. "Normals Only" is the option named `OFF`; there is no separate Off. Faceted shading in Unity means flat-shaded faces in Blender, or Unity Normals set to Calculate |
| Apply Modifiers | on (`use_mesh_modifiers=True`) | What you see is what ships. Blender only evaluates modifiers on objects the view layer evaluates; the kit export makes hidden, disabled and excluded members evaluable while it writes them (measured on 5.2.2) |
| Export Subdivision Surface | off (`use_subsurf=False`) | Bake subdivision down yourself and control the count |
| Loose Edges | off (`use_mesh_edges=False`) | Not renderable |
| Triangulate Faces | on (`use_triangles=True`), for pieces that arrive triangulated where it matters | The exporter splits each face of 4+ corners its own way (Blender's triangulate defaults), so a quad's diagonal is the exporter's, not necessarily the one the viewport drew (measured on a non-planar quad), and custom normals change with the new diagonals (measured, 5.2.2: a weighted-normal panel 0.00 -> 10.42 deg off flat; Harden Normals chamfers up to 12.6 deg). Precondition: a piece with custom normals (Weighted Normal, Harden Normals) or non-planar faces arrives already triangulated in its modifier stack (stack: `blender-mesh-topology`), and then exports unchanged (0.00 deg). `batch_export_fbx.py` warns about custom normals on faces of 4+ corners; `mesh_audit.py` counts non-planar faces |
| Tangent Space | off (`use_tspace=False`) | Unity calculates MikkTSpace tangents on import (Tangents row below), the same algorithm Blender bakes normal maps with |
| Vertex Colors | None (`colors_type="NONE"`) | The default, sRGB, exports every colour attribute as an extra vertex stream. Use sRGB or Linear only when the Unity shader reads vertex colours, matching what it expects |
| Add Leaf Bones | off (`add_leaf_bones=False`) | Armatures only |

## Animation

| Field | Value | Why |
|---|---|---|
| Baked Animation | off (`bake_anim=False`) for static geometry | An animated prop: on, NLA strips off unless used on purpose |

## Unity import (Model tab)

`KitImport.cs` applies this to every FBX under `Assets/World/Kits/`, except the row marked "left to you"; set the
same by hand for anything else.

| Field (`ModelImporter` property) | Value |
|---|---|
| Scale Factor (`globalScale`), Convert Units (`useFileUnits`) | 1, on |
| Bake Axis Conversion (`bakeAxisConversion`) | off: the axis change is already in the vertices |
| Import BlendShapes, Visibility, Cameras, Lights | off |
| Mesh Compression (`meshCompression`) | Off for kit pieces. Unity quantises each mesh on its own range, so neighbours round differently: on two 2 and 3 m walls meeting at a joint, Medium stepped the tiling UV0 by up to 0.61 px at 1024 across the joint and cut 2-texel UV2 gaps to 1.81-1.85 texels; High opened the joint by up to 6.3 mm and cut the gaps to 1.3; Low moved nothing visibly (0.007 mm, 0.01 px). The editor holds the quantised data, so the bake sees it. Low at most on a unique prop that meets nothing, checked by eye. Measured in Unity 2022.3.22f1, 2026-10-18 |
| Read/Write (`isReadable`) | off |
| Optimize Mesh | left to you: Everything (the default) |
| Generate Colliders (`addCollider`) | off: collision is authored (`<Piece>_COL` or primitives) |
| Normals (`importNormals`) | Import |
| Tangents (`importTangents`) | Calculate Tangent Space (MikkTSpace, `CalculateMikk`) when the material has a normal map; None otherwise |
| Generate Lightmap UVs (`generateSecondaryUV`) | off for kit pieces (UV2 is authored in Blender). A one-off prop only: on, with Margin Method Calculate, Min Lightmap Resolution = the scene's texels per metre x the smallest Scale In Lightmap, Min Object Scale = the smallest scale (https://docs.unity3d.com/2022.3/Documentation/Manual/LightingGiUvs-GeneratingLightmappingUVs.html); a manual Pack Margin assumes the mesh fills a whole 1024 map |
| Rig > Animation Type (`animationType`) | None for static meshes |
| Animation > Import Animation (`importAnimation`) | off for static meshes |
| Materials > Material Creation Mode (`materialImportMode`), Location (`materialLocation`) | Import via MaterialDescription, Use Embedded Materials, then remapped by name to the project's materials (`unity-packaging.md`) |

## Sanity tests after an export

1. In Blender, into an empty scene: `bpy.ops.import_scene.fbx(filepath=..., bake_space_transform=True)`. One object
   per mesh in the piece (LODs and `_COL` included), rotation 0, scale 1, dimensions equal to the piece. Without
   `bake_space_transform` on import, Blender shows X 90 deg and swapped Y/Z sizes even for a correct file. For a piece
   with custom normals, compare the re-imported corner normals with the evaluated piece's at the same positions: they
   match (under 0.5 deg) when the piece arrived triangulated, and move by more than 0.5 deg (up to 37 deg measured)
   when the exporter split quads. The export's re-triangulation warning is the reliable signal; the size of the change
   varies with the piece. A match does not prove the stack itself is right: a Triangulate with Keep Normals off has
   already moved the normals before export (`blender-mesh-topology`'s `audit_stack` catches that).
2. In Unity, one instance per family at the origin: the root and every child read position 0, rotation 0,0,0, scale
   1,1,1. Bake Space Transform off at export shows as X -90 or 270 on the root of a single-mesh FBX, but on every
   child of a multi-mesh one, whose generated root stays at 0 (measured 2026-10-17, Unity 2022.3.22f1).
3. Size against a 1.6 m reference: Unity's default Capsule is 2 m tall
   (https://docs.unity3d.com/2022.3/Documentation/Manual/PrimitiveObjects.html), so scale it to Y 0.8. A 2 m door
   stands 2 m.
4. Mesh inspector: the expected triangle count, two UV channels on every render mesh (LODs too; not `_COL`), one
   submesh per material slot.
