# Input images for image-to-3D

The generator rebuilds what it sees: shape from the silhouette and shading, texture from the pixels. Every flaw in
the image is in the model, and lighting in the image is painted into the base colour. Make the image for the
generator, not to look good.

*Measured* means run on ComfyUI 0.43.2 with Z-Image-Turbo int8 and TRELLIS.2 / Pixal3D on an RTX 3090 Ti
(2026-11-02).

## 1. What a good input looks like

| Property | Want | Why |
| --- | --- | --- |
| Subject | One object, whole, nothing touching it | A second object or a cropped edge becomes geometry |
| Framing | Centred, a 5-10% margin all round, square 1024 px | The template crops to the mask at pad 1.1 and resizes to 1024; a cut-off part is guessed |
| View | Three-quarter: about 30-45 degrees round from the front and 15-30 degrees above | Shows front, one side and the top at once, so less is guessed. Straight-on hides the depth |
| Lens | Long (product-shot) lens, little perspective | Wide-angle distortion is built into the shape |
| Background | Plain light grey or white, seamless | Background removal (BiRefNet) then cuts cleanly |
| Light | Flat, soft, from all round; no cast shadow, no rim light, no specular hot spots | Light and shadow end up painted into the base colour, and a shadow can become geometry |
| Materials | Matte-ish, true colour | Reflections and glass are rebuilt as painted texture or holes |
| Detail | What the low poly can show at the viewing distance | Fine detail goes to the bake anyway; see `blender-mesh-topology` |

Thin parts (rope, wire, fences, leaves, chair spindles) come out lumpy or missing at this resolution. Leave them
out of the image and model them afterwards, or accept that the generated part is a placeholder.

## 2. Prompt recipe (text-to-image)

One paragraph, in this order: the object with its materials and condition; the view; framing; background; light;
what is excluded.

```
A single <object, material, condition>, game prop reference photograph.
Three-quarter view from about 30 degrees above, looking down at it, the whole <object> centred and fully in frame
with a small margin. Plain light grey seamless studio background. Flat, even, overcast-style lighting from all
sides, no cast shadows, no rim light, no reflections. Sharp focus, true neutral colours, <surface detail>.
Nothing else in the scene, no text, no ground plane.
```

*Measured* with Z-Image-Turbo int8 (barrel, four seeds, 4 s each after the first):

- Counts are not followed: "two iron hoops" gave four or five. Do not rely on a number in the prompt; pick the seed
  that has it, or edit the image.
- "Slightly above" gave a near side-on view with the top barely visible. Say the angle and "looking down at it".
- "Soft, even, diffuse lighting... no cast shadows" still gave a soft key light from one side and a faint floor
  shadow. Name the light as flat or overcast, and check the image.
- Z-Image-Turbo runs at cfg 1: there is no negative prompt. Exclusions go in the positive prompt as plain words.

Generate four or more seeds and pick by the checklist in section 1, not by which looks best.

## 3. Checking the image before generating

Look at it (open the PNG). Reject and regenerate when:

- any part touches the frame edge, or a second object is in frame;
- one side is clearly darker than the other, or there is a visible cast shadow on the object;
- the view hides a side that matters (a straight-on view of a box-like object);
- a thin part is the point of the object.

## 4. From the user's own image or a reference

A photo or concept art works when it meets section 1. Common fixes, in an image-edit model or by hand: crop to one
object, paint out the background, even the lighting. Do not feed a turnaround sheet or a collage to the single-image
template: use `3d_pixal3d_multi_views` for separate views.

## 5. Turnaround sheets for multi-view

Prompt for one image with four views in a row (it keeps the object consistent; separate generations drift):

```
A turnaround reference sheet of <object>, four views side by side in one row, left to right: FRONT, LEFT SIDE
(turned 90 degrees), BACK, RIGHT SIDE. Every view: camera level at the object's mid-height, very long lens, almost
no perspective, the same scale in every view, the object filling about 90% of the height, nothing cropped. Plain
light-grey background, no borders, dividers, labels or text. Flat even overcast light, no cast shadows, no floor.
```

*Measured* with gpt-image-2 through Codex (2026-11-02, a cushion): the four views matched (colour, piping, shape),
level and shadow-free, but the sheet came back 2172 x 724 (the tool's widest ratio is 3:1, so four square panels
cannot be asked for) and the views did not sit on equal quarters (front 665 px wide, side 295). Split by outline
(`scripts/multiview.py split`), never into equal quarters. The two side views differed slightly in fullness; check
them against each other. Run image jobs one at a time: two in parallel saved the same picture under both names.

The split finds each view by its difference from the background colour, so ask for a plain background that
contrasts with the object (light grey for dark iron, mid grey for white plaster), or for separate images.

## 6. Licences

The image model's licence covers the image, and the image becomes the model's texture. Check the model card before
the first use and record it with the asset. As of 2026-11-02 (secondary sources, check the card):

| Model | Licence |
| --- | --- |
| Z-Image-Turbo | Apache 2.0: https://huggingface.co/Tongyi-MAI/Z-Image-Turbo |
| FLUX.2 Klein 4B | Apache 2.0; the 9B is the FLUX non-commercial licence |
| Qwen-Image, Qwen-Image-2512, Qwen-Image-Edit (2509) | Apache 2.0 |
| Qwen-Image 2.1 | Qwen Research licence, non-commercial (changed from the earlier Apache 2.0 line) |
