# Form principles: hierarchy, silhouette, breaking blockiness

Scope: the design rules behind SKILL.md section 3, with sources. All sources checked 2026-10-19. *practice* marks
this skill's working rules, which have no published number: starting points, settled by the renders. Polycount forum
threads refuse automated fetches, so the critiques quoted from them were read in search summaries only; verify by
hand before quoting them further.

## 1. Hierarchy and composition

| Rule | Source |
| --- | --- |
| Every design needs big, medium and small shapes, each clearly different in size from the next; viewers read big first, then medium, then detail | https://mayabeginner.readthedocs.io/en/latest/Design/L3_DesignPrinicplesPrimer.html |
| 70/30 (or 80/20): split a form into sub-shapes of about 70% and 30%, and keep about 70% of the surface quiet with 30% detailed. The contrast matters more than the exact figure | Same page |
| Leave areas of rest. Busy small-scale detail "do[es] not read well at a distance"; to simplify, "eliminate the small details, or bring their values closer together" | https://80.lv/articles/comparing-team-fortress-2-and-overwatch-art-direction |
| A silhouette has primary, secondary and tertiary tiers; the primary feature is the identity and is never lost | https://www.leagueoflegends.com/en-gb/news/dev/clarity-in-league/ |
| Keep shape choices consistent across a set (TF2 repeats one nose-forehead angle) | The 80.lv TF2 and Overwatch article above |
| Avoid tangents: edges that just touch or line up by accident "flatten the depth out of an image" | https://ctrlpaint.com/videos/avoiding-visual-tangents |

Checkable versions (*practice*):
- Big, medium and small forms are all present, each clearly smaller than the last (judged from the renders;
  furniture members of similar length are normal, and `form_audit` only flags parts that are all one size).
- No major part or overall form with all three sides within 15% of each other unless the real object is cubic.
- Primary splits nearer 1:1.6 or 1:2 than 1:1 (the golden ratio is 1.618).
- At most about 40% of the visible surface carrying detail.

## 2. Silhouette tests

- Fill the object with one flat colour: it must still be recognisable
  (https://allcorrectgames.com/insights/6-ways-to-make-game-art-cooler/, search summary).
- Test all round, not only the orthographic views: legibility is lost "at more obscure angles" (Polycount,
  https://polycount.com/discussion/comment/1393615/, search summary).
- Put the polygons where the silhouette is; detail inside the outline goes to the normal map or texture (Polycount,
  https://polycount.com/discussion/comment/977550, search summary). Floating detail baked into a normal map adds
  detail "that [doesn't] affect the silhouette" (https://80.lv/articles/001agt-tips-for-mech-design-in-blender).
- A silhouette can read alone and still blur beside others: readability needs value and material contrast too
  (the 80.lv TF2 and Overwatch article).

The set this skill renders (*practice*): front, side and top orthographic, two three-quarter views about 30 deg up,
one low view; at a small size (64-256 px) for the read, at full size for proportion. `form_audit`'s silhouette
numbers (rectangularity, solidity) are a first filter, the renders the judgement.

## 3. Breaking blockiness

| Technique | What to do | Source |
| --- | --- | --- |
| Crown big surfaces | Transportation designers avoid flat planes and dead-straight lines: straight lines "appear to droop or slump"; crowned surfaces "bow slightly in a positive direction", ideally in two directions | https://www.knackdesignstudio.com/post/transportation-design-tricks-no-straight-lines |
| Combine, subtract, subdivide | Build from combined and cut shapes, not primitives placed side by side | https://joepetersondesign.gumroad.com/l/kOzAf (course outline) |
| Angle and round | A retro jet critiqued as "too blocky" beside the real, rounder aircraft was fixed by rounding the fronts of its wing blocks; "more nuanced shapes" break up "cube/cylinder modeled blockiness" | Polycount, https://polycount.com/discussion/comment/2053712 , https://polycount.com/discussion/comment/2463194 (search summaries) |
| Design from function | "Think function over form"; model an asset "as it has been manufactured (but not always)"; mechanisms should look like they could work, with a mechanism at every joint | https://caveacademy.com/wiki/post-production-assets/modelling/modelling-training/modelling-exercises-hard-surface/ , the 80.lv mech tips above |
| Profile and section first | Build forms from orthographic side views and X-Y-Z sections (Scott Robertson, *How to Draw*, known here only second-hand) | https://link.deschuteslibrary.org/resource/73CMR5KQCUc (book record) |
| Imperfection | Real objects lack "perfect straight lines or 90 degree angles"; a reference's chairs all differed while the model's copies were identical | Polycount, https://polycount.com/discussion/comment/1589749/ (search summary) |
| Material contrast | Smooth metal against rough rubber and cloth, so parts read as separate | The 80.lv mech tips above |

Rules for a modelling agent (*practice*):
- Any box-derived part over about 0.3 m gets at least one non-parallel pair of faces (2-10 deg of taper or draft)
  unless it is a sawn board, a panel, or square by its job (a crate, a case, a carcass that stacks or sits flush):
  those break the box with lids, rails, bands, overhangs and corner pieces instead.
- A plane over about 0.25 m^2 that is not a floor, glass or a tiling surface gets a crown of 0.5-2% of its span, or is
  broken into facets or panels.
- Secondary forms sit on, wrap or interpenetrate their parent (a lip, a flange, a panel in a 5-20 mm recess) rather
  than touching it face to face at one plane.
- Never space three or more features evenly unless they are mechanically repeated (bolts on a flange, rungs, shelf
  pins); even then group them or let the spacing follow function.
- Every part answers: what holds it on, where it is handled, where it wears. Detail clusters there; the rest is rest.
- Jitter repeated instances 0.5-2 deg and a few mm; break exact mirror symmetry on one secondary feature; never noise
  on primary forms or joint faces.

## 4. Order of decisions

The order artists work in, from blockout to finish. In this skill the first three happen in the spec (sizes,
profiles and shape values written and validated) so the build makes each part once; the gates are checked on the
spec's profiles before modelling and on the renders after (sources: the 80.lv mech tips, "it's super easy to change
things" at blockout; Cave Academy, block primaries then secondaries and tertiaries, study real objects; Unity Learn,
https://learn.unity.com/course/high-fidelity-game-visuals-environment/tutorial/creating-a-prototype-blockout-from-concept-art):

1. Reference and the parts table with real sizes.
2. Proportion blockout; gate: the silhouette set.
3. Primary refinement (taper, crown, angles, splay); the silhouette set again. Skipping this step is where "a greybox
   with a material on it" comes from.
4. Secondary forms at functional points; check the 70/30 rest-to-detail split.
5. Edges (`bevels.md`), then tertiary detail in textures.

## 5. What reviewers say, and what it means

| Critique | Meaning | Fix |
| --- | --- | --- |
| "Small detail evenly distributed... without any medium/larger detail" | One size tier | Add medium and large forms; remove some small |
| "Didn't leave a lot of breathing room", "too noisy" | No rest areas | Fewer details, clustered |
| "It's blurring the overall shape" | Detail fighting the silhouette | Remove detail; strengthen the primary |
| "Some of the blocks are bigger or different in dimension" | Proportions off the reference | Measure the reference; fix the parts table |
| "Way too blocky" | Primitive forms, hard axis-aligned edges | Profiles, rounding, taper |
| "Bevels too tight" | Razor edges, no highlight | Bevel up to the material's real size and the 2 px floor |
| "Too uniform", "very symmetrical" (roughness, dirt) | No variation | Concentrate wear at edges, handles, openings |
| "All the chairs in the reference were different" | Identical copies | Variants and per-instance jitter |

Sources: Polycount threads https://polycount.com/discussion/comment/1622576 ,
https://polycount.com/discussion/comment/2119932 , https://polycount.com/discussion/comment/2472152 ,
https://polycount.com/discussion/comment/2149767 (search summaries; each quote not matched to one thread).
