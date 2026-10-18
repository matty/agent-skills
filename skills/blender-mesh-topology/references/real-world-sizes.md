# Real-world sizes

Typical sizes for modelling architecture, fixtures and furniture at a believable scale. In VR a wrong height is
noticed at once: a table at the wrong height makes the player feel like a child or a giant. Model at 1 Blender unit =
1 m. Sources inline, checked 2026-10-18; rows marked *practice* have no source and are working values (UK homes).
The regulations are England's (Wales, Scotland and Northern Ireland differ) and set safety minimums and ranges,
not design targets.

## VR first

- Avatars range from tiny to very tall, and VR players need room to turn. Worlds plan doors of at least 2.1 x 1 m and
  ceilings of at least 2.6 m for comfort (the `vrchat-world-qa` skill's S6 house guidance, with 1.6 m and 1.9 m scale
  figures at the greybox), which is more than the real sizes below: build openings and room heights to the world's
  plan, and keep fixtures and furniture at real size, so the world reads generous rather than giant.
- Review at an adult eye height of 1.6-1.7 m (`form-and-detail.md`, section 7).

## Stairs, handrails and guarding

Approved Document K, 2013 edition (England):
https://assets.publishing.service.gov.uk/media/60d5bdcde90e07716f516cfd/Approved_Document_K.pdf

| Item | Value | Where |
| --- | --- | --- |
| Private stair (in a dwelling): rise / going | 150-220 mm / 220-300 mm, pitch at most 42 deg | Table 1.1 and note 1 |
| Utility stair: rise / going | 150-190 mm / 250-400 mm | Table 1.1 |
| General access stair: rise / going | 150-170 mm / 250-400 mm | Table 1.1 |
| Rise and going together | 2 x rise + going = 550-700 mm | Table 1.1 note |
| Headroom over a stair | 2 m minimum | Para 1.11, Diagram 1.3 |
| Handrail | Top 900-1000 mm above the pitch line or floor; on both sides from 1000 mm wide | Para 1.34 |
| Guarding in dwellings: stairs, landings, ramps, internal floor edges | 900 mm | Para 3.2, Diagram 3.1 |
| Guarding: external balconies and roof edges | 1100 mm | Diagram 3.1 |
| Guarding at opening windows | 800 mm: a lower sill needs guarding up to it | Diagram 3.1 |
| Gaps in guarding where children under five may be | A 100 mm sphere must not pass | Para 3.3 |
| Comfortable steps in a world | 150-180 mm rise, 250-300 mm going; `vrchat-world-qa`'s S6 allows at most 0.2 m | *practice* |

## Doors, windows, fixtures and trim

Approved Document M, Volume 1, 2015 edition with 2016 amendments (England, new dwellings):
https://assets.publishing.service.gov.uk/media/5a7f8a82ed915d74e622b17b/BR_PDF_AD_M1_2015_with_2016_amendments_V3.pdf

| Item | Value | Source |
| --- | --- | --- |
| Internal door leaf, England and Wales | 1981 x 762 x 35 mm (also 686 and 838 wide) | Trade guides: https://www.doorsuperstore.co.uk/help-and-advice/product-guides/internal-doors/uk-door-sizes-and-conversion-chart/ , https://www.howarth-timber.co.uk/help-advice/uk-door-sizes |
| Metric door leaf (Scotland, much of Europe) | 2040 x 826 x 40 mm (526-926 wide) | Same trade guides |
| Front door clear opening | 775 mm minimum (an 826 mm leaf up to 44 mm thick counts) | ADM Vol 1 para 1.14, Table 1.1 note |
| Internal doorway clear opening | 750-800 mm, wider for a narrower corridor | ADM Vol 1 Table 1.1 |
| Switches and sockets | Centre line 450-1200 mm above the floor | ADM Vol 1 para 1.18 |
| Consumer unit switches | 1350-1450 mm above the floor | ADM Vol 1 para 1.18 |
| Door handle | 900-1050 mm above the floor | *practice* |
| Window sill (inside) | 800-1000 mm above the floor in homes; below 800 mm an opening window needs guarding | ADK Diagram 3.1 (800 mm); range *practice* |
| Ceiling, new homes | At least 2.3 m over at least 75% of the floor area | Nationally described space standard: https://www.gov.uk/government/publications/technical-housing-standards-nationally-described-space-standard |
| Ceiling, typical | 2.4-2.7 m in modern homes, 2.7-3.3 m in older houses | *practice* |
| Door lining and architrave | Lining 25-35 mm thick; architrave 45-70 mm wide, 15-20 mm thick, covering the lining joint | *practice* |
| Skirting | 70-170 mm high; 200-300 mm in older houses | *practice* |
| Dado rail | Centre 900-1000 mm above the floor | *practice* |
| Picture rail | 300-500 mm below the ceiling | *practice* |
| Walls | Stud partition 100-125 mm; internal masonry 100-150 mm; external cavity wall about 300 mm | *practice* |

## Furniture

| Item | Value | Source |
| --- | --- | --- |
| Kitchen worktop | 900 mm high (EN 1116 gives 850, 900 and 950 mm, +0/+50 mm); at least 600 mm deep | EN 1116:2018, summarised by CATAS: https://catas.com/uploads/media/unien1116-eng.pdf |
| Worktop to the bottom of wall units | 450 mm minimum; wall units 310-400 mm deep; plinth at least 80 mm | Same summary |
| Office chair seat | 400-520 mm, height-adjustable (type A) | EN 1335-1:2020 dimension table: https://www.bureaustoel.nl/wp-content/uploads/2022/01/NEN-EN-1335-1-april-2020.pdf |
| Desk top | 720-750 mm | *practice* |
| Dining table top / dining chair seat | 720-760 mm / 430-470 mm | *practice* |
| Coffee table | 400-450 mm | *practice* |
| Sofa seat | 400-450 mm high, 550-600 mm deep | *practice* |
| Bar counter / bar stool seat | 1050-1150 mm / 750-800 mm | *practice* |
| Stool at a 900 mm worktop | 600-650 mm seat | *practice* |
| Bed (top of the mattress) | 450-600 mm | *practice* |
| Bookshelf | 250-350 mm deep; top shelf at most 1800-2000 mm | *practice* |
| Wardrobe | About 600 mm deep, 2000-2100 mm high | *practice* |

Check a finished prop against this table from its bounds and its key surfaces (seat, top, counter) in Blender, and say
in the report which rows you used.
