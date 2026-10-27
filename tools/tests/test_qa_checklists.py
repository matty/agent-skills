"""Consistency of the vrchat-world-qa skill's documents with each other and with qa_measure.py: check ids unique, in
order and all mapped to a task; every cited id exists; every qa_measure flag and field the documents cite exists in
the script; the verdict block parses and carries the not-run and waived states.

Host: plain Python 3.9+, standard library (PyYAML optional: the verdict-block parse is skipped without it). Run from the
repo root: python -B -m unittest discover -s tools/tests -p "test_qa_*.py"
"""

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "vrchat-world-qa"
DOCS = {p.name: p.read_text(encoding="utf-8") for p in [SKILL / "SKILL.md", *sorted((SKILL / "references").glob("*.md"))]}
CHECKLISTS = DOCS["checklists.md"]
SCRIPT = (SKILL / "scripts" / "qa_measure.py").read_text(encoding="utf-8")

try:
    import yaml
except ImportError:
    yaml = None

# The ids this round fixed (A5 retired; M9, X6, N8 new; X8 and L7 added 2026-10-18): letter -> count.
EXPECTED = {"G": 5, "C": 4, "S": 7, "P": 4, "B": 7, "M": 10, "U": 7, "X": 10, "A": 5, "E": 4, "N": 8, "L": 7, "I": 4,
            "O": 5}
ID = r"[GCSPBMUXAENLIO][1-9]\d?"
# flags of other tools the documents quote (uv_audit, texture_seams, pbr_check, Blender itself, git, a Chromium
# screenshot)
OTHER_FLAGS = {"--objects", "--layer", "--lightmap", "--map", "--pad", "--td", "--baking", "--python",
               "--factory-startup", "--python-exit-code", "--porcelain", "--name-only", "--headless", "--screenshot",
               "--force-device-scale-factor", "--window-size", "--purpose", "--material", "--tile-m", "--steps",
               "--tile-offset", "--image", "--kind", "--joints", "--tiling", "--out", "--hard-deg", "--fold-deg"}


def table_ids(text):
    return re.findall(r"^\| (%s) \|" % ID, text, re.M)


def expand(cell):
    """'B2-B7, M9' -> ['B2', ..., 'B7', 'M9']."""
    out = []
    for a, b in re.findall(r"(%s)(?:-(%s))?" % (ID, ID), cell):
        if b:
            out += ["%s%d" % (a[0], n) for n in range(int(a[1:]), int(b[1:]) + 1)]
        else:
            out.append(a)
    return out


def section(text, heading):
    m = re.search(r"^## %s\n(.*?)(?=^## |\Z)" % re.escape(heading), text, re.M | re.S)
    return m.group(1) if m else ""


class CheckIds(unittest.TestCase):
    def test_ids_unique_and_complete(self):
        ids = table_ids(CHECKLISTS)
        self.assertEqual(len(ids), len(set(ids)), "duplicate check ids")
        want = ["%s%d" % (k, n) for k, c in EXPECTED.items() for n in range(1, c + 1)]
        self.assertEqual(sorted(ids), sorted(want))

    def test_ids_in_order_within_each_letter(self):
        seen = {}
        for i in table_ids(CHECKLISTS):
            self.assertEqual(int(i[1:]), seen.get(i[0], 0) + 1, "%s out of order" % i)
            seen[i[0]] = int(i[1:])

    def test_no_g_rows_left_in_skill_md(self):
        self.assertEqual(table_ids(DOCS["SKILL.md"]), [], "general checks belong in references/checklists.md")

    def test_every_cited_id_exists(self):
        known = set(table_ids(CHECKLISTS))
        for name, text in DOCS.items():
            for i in re.findall(r"(?<![\w-])(%s)(?!\w)" % ID, text):
                self.assertIn(i, known, "%s cites %s, which is not a check" % (name, i))

    def test_checks_per_task_covers_every_check(self):
        mapped = set()
        for line in section(CHECKLISTS, "Checks per task").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) == 3 and cells[0] not in ("Stage", "---"):
                mapped.update(expand(cells[2]))
        missing = sorted(set(table_ids(CHECKLISTS)) - mapped - {"G%d" % n for n in range(1, 6)})
        self.assertEqual(missing, [], "checks no task runs")


class ScriptAgreement(unittest.TestCase):
    def test_script_parses_and_names_its_host(self):
        ast.parse(SCRIPT)
        self.assertIn("Host:", "\n".join(SCRIPT.splitlines()[:10]))

    def test_cited_flags_exist(self):
        flags = set(re.findall(r'add_argument\(\s*"(--[a-z-]+)"', SCRIPT))
        self.assertIn("--expect-status", flags)
        for name, text in DOCS.items():
            for flag in set(re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", text)) - OTHER_FLAGS:
                self.assertIn(flag, flags, "%s cites %s, which qa_measure.py does not take" % (name, flag))

    def test_documented_fields_exist(self):
        rows = section(CHECKLISTS, "Tools")
        table = rows[rows.index("| Field | Means | Checks |"):]
        fields = set()
        for line in table.splitlines()[2:]:
            if not line.startswith("|"):
                break
            for tok in re.findall(r"`([^`]+)`", line.split("|")[1]):
                # objects.<obj>.tris: <obj> stands for a key (objects is a dict keyed by object name)
                fields.update(t for t in re.split(r"[\[\].]+", tok) if t and not t.startswith("<"))
        self.assertGreater(len(fields), 30)
        for f in sorted(fields):
            self.assertIn('"%s"' % f, SCRIPT, "checklists.md documents field %s, which qa_measure.py never writes" % f)

    def test_status_order_matches_g1(self):
        order = ast.literal_eval(re.search(r"STATUS_ORDER = (\([^)]*\))", SCRIPT).group(1))
        self.assertEqual(order, ("grey", "modelled", "uv", "textured", "exported"))
        g1 = re.search(r"^\| G1 \|.*$", CHECKLISTS, re.M).group(0)
        for s in order:
            self.assertIn("`%s`" % s, g1)

    def test_probe_lit_families(self):
        # canon: only a Free-sized PROP or FOL piece is a Free prop; ZONE shells follow the grid-piece rule
        self.assertIn('PROBE_LIT_FAMILIES = ("PROP", "FOL")', SCRIPT)
        self.assertIn("PROP or FOL", re.search(r"^\| U4 \|.*$", CHECKLISTS, re.M).group(0))
        self.assertIn("PROP or FOL", re.search(r"^\| L6 \|.*$", CHECKLISTS, re.M).group(0))


class Rules(unittest.TestCase):
    OWNER = ("declined: not-run, owner user, passes with notes; missing but not declined: incomplete (owner qa) "
             "until the user installs or declines it")

    def test_skill_owner_rule_has_one_wording(self):
        for name in ("SKILL.md", "checklists.md"):
            self.assertIn(self.OWNER, DOCS[name], "%s lacks the owner rule's exact wording" % name)

    def test_rename_task_mapped(self):
        # orchestration's T-RENAME brief cites the same: B2-B3, M9, and N4-N5 after stage 10
        row = re.search(r"^\|[^|]*\| `T-RENAME-<PIECE>`[^|]*\|([^|]*)\|", CHECKLISTS, re.M)
        self.assertIsNotNone(row, "no Checks per task row for T-RENAME-<PIECE>")
        self.assertEqual(row.group(1).strip(), "M9 (B2-B3 within it), N4-N5 after stage 10")
        self.assertEqual(sorted(expand(row.group(1))), ["B2", "B3", "M9", "N4", "N5"])
        m9 = re.search(r"^\| M9 \|.*$", CHECKLISTS, re.M).group(0)
        self.assertIn("T-RENAME-<PIECE>", m9, "M9 must say which swap lines a rename may print")
        self.assertIn("placement id first", m9)

    def test_stage_13_may_switch_the_build_target(self):
        rule = re.search(r"\*\*Read-only Unity\*\*.*?(?=\n- \*\*|\n\n)", DOCS["SKILL.md"], re.S).group(0)
        for cid in ("O1", "O5"):
            self.assertIn(cid, rule, "SKILL.md forbids the build-target switch %s needs" % cid)
        self.assertIn("back to the target it found", rule)

    def test_lods_follow_their_piece(self):
        # the 64 px rule is judged on LOD0; LOD1+ follow it unless the spec sets lod_lightmap: false
        for cid in ("U4", "L6"):
            row = re.search(r"^\| %s \|.*$" % cid, CHECKLISTS, re.M).group(0)
            self.assertIn("LOD1+ follow their piece (lightmapped at 0.5^n), unless the spec sets `lod_lightmap: false`",
                          row, cid)
            self.assertIn("Under 64 px at LOD0", row, cid)
        self.assertIn('"<Piece>_LOD[1-9]"', re.search(r"^\| U4 \|.*$", CHECKLISTS, re.M).group(0))

    def test_u6_notes_uv2_box_fill(self):
        u6 = re.search(r"^\| U6 \|.*$", CHECKLISTS, re.M).group(0)
        self.assertIn("box fill", u6)
        self.assertNotIn("UV2 below 40%", u6)
        self.assertIn("UV2_BOX_FILL_NOTE = 0.5", SCRIPT)

    def test_n7_checks_mirror_slots(self):
        n7 = re.search(r"^\| N7 \|.*$", CHECKLISTS, re.M).group(0)
        for part in ("zones[].mirrors", "(-x, z, -y)", "180 - rot"):
            self.assertIn(part, n7)

    def test_g2_ignores_the_approved_spec(self):
        self.assertIn("`world/spec.approved.yaml`", section(CHECKLISTS, "General checks (every task)"))

    def test_u4_checks_every_lod_at_its_own_scale(self):
        # measured 2026-10-17: Progressive gives LOD1+ their own atlas space at 0.5^n
        u4 = re.search(r"^\| U4 \|.*$", CHECKLISTS, re.M).group(0)
        self.assertIn("LODs included", u4)
        self.assertIn("0.5^n", u4)
        self.assertIn("UV2_LAYOUT_ALL_LODS = True", SCRIPT)
        self.assertIn("LOD_LIGHTMAP_SCALE = 0.5", SCRIPT)

    def test_lighting_states_in_u4_l6(self):
        for cid in ("U4", "L6"):
            self.assertIn("lighting_states", re.search(r"^\| %s \|.*$" % cid, CHECKLISTS, re.M).group(0), cid)
        self.assertIn("LIGHT_STATES", section(CHECKLISTS, "Stage 11 - Lighting and bake"))


class LookAndPbr(unittest.TestCase):
    """X5 judges materials under look-dev light, X8 runs the shared PBR check, L7 judges the lit Unity views."""

    def row(self, cid):
        return re.search(r"^\| %s \|.*$" % cid, CHECKLISTS, re.M).group(0)

    def test_x5_needs_lookdev(self):
        x5 = self.row("X5")
        self.assertIn("--light lookdev", x5)
        self.assertIn("ignores roughness, metallic and normal maps", x5)
        for field in ("look.references", "look.materials.<M>.ref", "look.wear"):
            self.assertIn(field, x5)
        self.assertIn('LIGHTS = {"studio": "STUDIO", "flat": "FLAT", "lookdev": None}', SCRIPT)

    def test_x8_runs_the_shared_pbr_check(self):
        x8 = self.row("X8")
        for part in ("--pbr", "--map-px", "--pbr-targets", "30-240", "180", "look.materials", "OpenGL"):
            self.assertIn(part, x8)
        self.assertTrue((SKILL / "scripts" / "pbr_check.py").is_file(), "pbr_check.py must ship beside qa_measure.py")
        self.assertIn('"pbr_check.py"', SCRIPT)
        mapped = re.search(r"^\|[^|]*\| `T-TEX-<FAMILY>` \|([^|]*)\|", CHECKLISTS, re.M).group(1)
        self.assertIn("X8", expand(mapped))

    def test_l7_renders_every_state_in_unity(self):
        l7 = self.row("L7")
        for part in ("lighting state", "look.lighting_mood", "RenderTexture", "--image-stats", "clipped", "crushed"):
            self.assertIn(part, l7)
        self.assertIn("L7", section(CHECKLISTS, "Stage 11 - Lighting and bake").split("| Id |")[0])
        mapped = re.search(r"^\|[^|]*\| `T-LIGHT` \|([^|]*)\|", CHECKLISTS, re.M).group(1)
        self.assertEqual(expand(mapped), ["L%d" % n for n in range(1, 8)])

    def test_g4_judges_piece_detail(self):
        g4 = self.row("G4")
        for part in ("`ref` images", "`detail` list", "eye height"):
            self.assertIn(part, g4)


class VerdictContract(unittest.TestCase):
    def blocks(self):
        return re.findall(r"```yaml\n(.*?)```", DOCS["SKILL.md"].replace("\r\n", "\n"), re.S)

    def block(self):
        return self.blocks()[0]

    def test_result_states_documented(self):
        text = DOCS["SKILL.md"]
        for state in ("pass", "fail", "n/a", "not-run", "waived"):
            self.assertRegex(text, r"\| `%s` \|" % re.escape(state))
        self.assertIn("pass | fail | n/a | not-run | waived", self.block())

    def test_verdict_values_include_incomplete(self):
        text = DOCS["SKILL.md"]
        self.assertIn("pass | pass-with-notes | incomplete | fail", self.block())
        for verdict in ("fail", "incomplete", "pass-with-notes", "pass"):
            self.assertRegex(text, r"\| `%s` \|" % re.escape(verdict))
        self.assertIn("owner: qa", text)
        self.assertIn("owner: user", text)

    @unittest.skipUnless(yaml, "PyYAML not installed")
    def test_not_run_entries_name_need_and_owner(self):
        check = yaml.safe_load(self.blocks()[1])[0]
        self.assertEqual(check["result"], "not-run")
        for entry in check["not_run"]:
            self.assertEqual(set(entry), {"part", "needs", "owner"})
            self.assertIn(entry["owner"], ("qa", "user"))

    def test_verdict_file_locations(self):
        text = DOCS["SKILL.md"]
        for where in ("world/reports/qa/<task>/", "world/reports/qa/stage-<n>/", "verdict.yaml", "attempt<n>/"):
            self.assertIn(where, text)

    @unittest.skipUnless(yaml, "PyYAML not installed")
    def test_block_parses_with_every_field(self):
        qa = yaml.safe_load(self.block())["qa"]
        self.assertEqual(set(qa), {"task", "stage", "attempt", "verdict", "checks", "fixes", "notes"})
        self.assertEqual(set(qa["checks"][0]),
                         {"id", "result", "measured", "expected", "evidence", "not_run", "waived_by"})
        self.assertIn(qa["checks"][0]["id"], set(table_ids(CHECKLISTS)))


if __name__ == "__main__":
    unittest.main()
