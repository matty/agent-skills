# The review loop: what research on LLM-built 3D found, and the loop this skill runs

Scope: why SKILL.md section 7 works the way it does. Papers read through their arXiv HTML or project pages on
2026-10-19; figures are as the papers report them, on their own benchmarks, and small samples.

## Findings

| Finding | Source |
| --- | --- |
| Without retrieved documentation, "the coding agent often defaults to using primitive shapes and simpler constructs"; with it, complex operations per object rose from 1.20 to 5.86 (17 objects) and errors fell about 26%. Without retrieval the coder sometimes "fixed" errors by deleting the failing lines | LL3M, https://arxiv.org/html/2508.08228v1 |
| LL3M's failures: a "bucket" that was a plain cylinder, chair legs and backrest not touching, a handle left detached; "VLMs may still struggle to accurately identify spatial artifacts". Its critic renders 5 views framed from the bounding box, and a separate verifier checks each critique, because one fix pass often covers only some | Same |
| VLMs are far behind people at geometry edits, "report differences that are not actually present", miss subtle continuous changes, and make edits that do not match the differences they named; spending more of the compute on verification helps | BlenderGym, https://arxiv.org/html/2504.01786v1 |
| Code that runs still produces "disconnected or floating 3D geometric components", "simplistic, floating primitives"; most failures are API drift between Blender versions; retrying with the traceback fixed execution but barely changed shape quality; a revert-on-break guard stopped regressions | 3DCodeBench, https://arxiv.org/html/2606.01057v1 |
| Explicit global and per-part measurements nearly halved shape error for the strongest model; letting the agent choose its own views and zoom helped strong models | 3DHarnessBench, https://arxiv.org/html/2609.06535 |
| Writing validation questions about the render, answering them, then fixing mismatches improved geometry about 7% | CADCodeVerify, https://arxiv.org/html/2410.05340v2 |
| Numeric feedback (silhouette IoU, aspect ratio, clearances) fixed structural errors in the first round, with little gain after; a VLM critic kept improving longer | LLMForge, https://www.alphaxiv.org/overview/2607.05573 |
| Working towards an image, generated first when only text is given, keeps edits directed | BlenderAlchemy, https://arxiv.org/html/2404.17672v1 |
| Splitting the object into a graph of parts, then refining each, beats one-shot generation | ShapeCraft, https://arxiv.org/abs/2510.17603 ; MeshCoder, https://arxiv.org/html/2508.14879v1 |

## The loop

1. **Plan in parts with numbers**: the parts table of SKILL.md section 1 (real sizes, material, attachment, contact).
2. **Look up the API** for any operation you have not used in this Blender version (`blender-techniques.md`, the API
   docs) instead of falling back to primitives.
3. **Build in milestones** (blockout, primaries, secondaries, edges), saving or snapshotting after each, so a bad
   round can be reverted.
4. **Measure**: `form_audit` and the parts table (every part's size within tolerance, every part touching what holds
   it).
5. **Look**: the silhouette set and a lit three-quarter close-up, beside the reference. Write the critique as
   questions with yes/no answers ("Do the back legs rake back about 10 deg?", "Is there a gap between the drawer
   fronts?"), in priority order: missing parts, floating or disconnected parts, proportions, alignment, detail.
6. **Fix one item at a time and check it on its own** in a new render; a critic can claim a fix that did not happen.
7. **Revert** a round that made anything worse. **Stop** after about three rounds and report the remaining items
   rather than looping.
