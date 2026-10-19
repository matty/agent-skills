# The review loop: what research on LLM-built 3D found, and the loop this skill runs

Scope: why SKILL.md works spec-first and verifies once. Papers read through their arXiv HTML or project pages on
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

## What this skill takes from it

The findings argue for deciding before building rather than iterating after: measurements up front helped most,
retrieval stopped the primitive default, critics are unreliable and fixes regress. So:

1. **Plan in parts with numbers**: the form spec (`form-spec.md`), validated before any geometry.
2. **Look up the API** for any operation you have not used in this Blender version (`blender-techniques.md`, the API
   docs) instead of falling back to primitives.
3. **Build each part once** from its spec line, saving after each part so a bad step can be undone.
4. **Verify once, with numbers first**: `check_build` and `form_audit`, then one render set. Write the visual check as
   yes/no questions from the spec ("do the back legs rake about 8 deg?"), in priority order: missing parts, floating
   or disconnected parts, proportions, alignment, detail.
5. **A failure is a spec line or a build step**: fix that, rebuild that part, re-run the check that failed and
   confirm it in a new render; never accept a critic's claim that a fix happened. Revert anything that made another
   check worse. Do not start open-ended critique rounds.
