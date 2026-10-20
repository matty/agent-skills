"""Tests for blender-unity-placement-sync's scripts/placement_merge.py (plain Python).

Each case writes Blender and Unity dumps (and a snapshot) to a temp folder, runs `merge`, checks the plans and the
exit code, then plays both appliers (a stand-in for export_placements.apply and PlacementSync.Apply that keeps their
rules: assigns checked against `was` and `asset`, then delete, update, create by id), runs `commit` and merges again
to prove the loop converges.

Host: plain Python 3.9+, standard library. Run from the repo root:
    python -B -m unittest discover -s tools/tests -p "test_placement_merge.py"
"""

import copy
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MERGE = ROOT / "skills" / "blender-unity-placement-sync" / "scripts" / "placement_merge.py"
S = "MASTER"
H = math.sqrt(0.5)
QI = [0.0, 0.0, 0.0, 1.0]
Q90Y = [0.0, H, 0.0, H]
QM90Y = [0.0, -H, 0.0, H]


def it(pid, asset, pos, rot=QI, scl=(1, 1, 1), key=None, name=None):
    out = {"id": pid, "asset": asset, "pos": list(pos), "rot": list(rot), "scl": list(scl), "key": key or pid}
    if name:
        out["name"] = name
    return out


def blender_layout():
    return [it("a1", "WALL_A", (0, 0, 0), key="Wall"), it("b2", "WALL_A", (-2, 0, 0), Q90Y, key="Wall.001"),
            it("c3", "DESK_A", (-3, 0, -4), key="Desk")]


def unity_layout():
    return [dict(i, key=str(n), name=i["asset"]) for n, i in enumerate(blender_layout())]


def snapshot_of(items, source=None):
    snap = {"scope": S, "version": 1, "items": {i["id"]: {k: i[k] for k in ("asset", "pos", "rot", "scl")}
                                                for i in items}}
    if source:
        snap["source"] = source
    return snap


def find(items, pid):
    return next(i for i in items if i.get("id") == pid)


def apply_side(items, plan, available=None, prefix="new"):
    """Both appliers' rules without the engines. Returns (items after, errors)."""
    names = any("label" in i for i in items)
    items = copy.deepcopy(items)
    errors = []
    by_key = {i["key"]: i for i in items}
    for a in plan["assign"]:
        cur = by_key.get(a["key"])
        if cur is None:
            errors.append("assign %s: no %s" % (a["id"], a["key"]))
        elif "was" in a and (cur.get("id") or "") != a["was"]:
            errors.append("assign %s: has %r, merge saw %r" % (a["id"], cur.get("id"), a["was"]))
        elif a.get("asset") and cur["asset"] != a["asset"]:
            errors.append("assign %s: asset %s, merge saw %s" % (a["id"], cur["asset"], a["asset"]))
        else:
            cur["id"] = a["id"]
    by_id = {}
    for i in items:
        by_id.setdefault(i.get("id") or "", i)
    for pid in plan["delete"]:
        cur = by_id.pop(pid, None)
        if cur is None:
            errors.append("delete: no %s" % pid)
        else:
            items = [i for i in items if i is not cur]
    for kind in ("update", "create"):
        for p in plan[kind]:
            if available is not None and p["asset"] not in available:
                errors.append("%s %s: no asset %s" % (kind, p["id"], p["asset"]))
                continue
            cur = by_id.get(p["id"])
            if cur is None:
                cur = {"id": p["id"], "key": "%s%d" % (prefix, len(items))}
                items.append(cur)
                by_id[p["id"]] = cur
            cur.update(asset=p["asset"], pos=list(p["pos"]), rot=list(p["rot"]), scl=list(p["scl"]))
            if names:               # an applier that syncs names and folders (a nested Unity placement keeps its folder)
                if p.get("label"):
                    cur["label"] = p["label"]
                if p.get("group") is not None and not cur.get("nested"):
                    cur["group"] = p["group"]
    return items, errors


class Scope:
    """One scope's placements folder in a temp dir."""

    def __init__(self, tc, blender, unity, snapshot=None, b_assets=None, u_assets=None, b_file="MASTER.blend",
                 b_collection=None, target="scene:MASTER"):
        self.tc = tc
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        tc.addCleanup(self.tmp.cleanup)
        self.bdump = {"scope": S, "side": "blender", "file": "C:/w/blender/" + b_file, "collection": b_collection,
                      "items": copy.deepcopy(blender), "assets": sorted(b_assets if b_assets is not None else
                                                                        {i["asset"] for i in blender}),
                      "warnings": []}
        self.udump = {"scope": S, "side": "unity", "target": target, "items": copy.deepcopy(unity),
                      "assets": sorted(u_assets if u_assets is not None else {i["asset"] for i in unity})}
        self.write()
        if snapshot is not None:
            self.save("synced.json", snapshot)

    def path(self, suffix):
        return os.path.join(self.dir, "%s.%s" % (S, suffix))

    def save(self, suffix, data):
        with open(self.path(suffix), "w", encoding="utf-8") as f:
            json.dump(data, f)

    def load(self, suffix):
        with open(self.path(suffix), encoding="utf-8") as f:
            return json.load(f)

    def write(self):
        self.save("blender.json", self.bdump)
        self.save("unity.json", self.udump)

    def run(self, cmd, *extra):
        p = subprocess.run([sys.executable, "-B", str(MERGE), cmd, "--dir", self.dir, "--scope", S, *extra],
                           capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr

    def merge(self, *extra):
        self.rc, self.out = self.run("merge", *extra)
        self.pb, self.pu = self.load("plan.blender.json"), self.load("plan.unity.json")
        return self.rc

    def apply_both(self, b_avail=None, u_avail=None):
        self.bdump["items"], eb = apply_side(self.bdump["items"], self.pb, b_avail, "b")
        self.udump["items"], eu = apply_side(self.udump["items"], self.pu, u_avail, "u")
        self.write()
        return eb + eu

    def loop(self, *extra, expect=0, b_avail=None, u_avail=None):
        """merge (expecting `expect`), apply both, commit, merge again; returns the re-merge's exit code."""
        rc = self.merge(*extra)
        self.tc.assertEqual(rc, expect, self.out)
        errors = self.apply_both(b_avail, u_avail)
        self.tc.assertEqual(errors, [], "appliers reported errors")
        crc, cout = self.run("commit")
        self.tc.assertEqual(crc, 0, cout)
        rc2, self.out2 = self.run("merge")
        return rc2

    def plan_counts(self):
        return {side: {k: len(p[k]) for k in ("assign", "delete", "update", "create") if p[k]}
                for side, p in (("blender", self.pb), ("unity", self.pu))}

    def converged(self):
        """Both sides hold the same placements (ids, assets, poses within the merge's tolerance)."""
        b = {i["id"]: i for i in self.bdump["items"]}
        u = {i["id"]: i for i in self.udump["items"]}
        self.tc.assertEqual(sorted(b), sorted(u))
        for pid in b:
            self.tc.assertEqual(b[pid]["asset"], u[pid]["asset"])
            self.tc.assertLess(math.dist(b[pid]["pos"], u[pid]["pos"]), 0.001)


def base():
    return snapshot_of(blender_layout())


class TwoWayEdits(unittest.TestCase):
    def test_move_in_blender_updates_unity(self):
        b = blender_layout()
        find(b, "a1")["pos"] = [0, 0, -1]
        sc = Scope(self, b, unity_layout(), base())
        self.assertEqual(sc.loop(), 0)
        self.assertEqual(sc.plan_counts(), {"blender": {}, "unity": {"update": 1}})
        self.assertEqual(find(sc.udump["items"], "a1")["pos"], [0, 0, -1])

    def test_move_in_unity_updates_blender(self):
        u = unity_layout()
        find(u, "a1")["pos"] = [0, 0, -1]
        sc = Scope(self, blender_layout(), u, base())
        self.assertEqual(sc.loop(), 0)
        self.assertEqual(sc.plan_counts(), {"blender": {"update": 1}, "unity": {}})
        sc.converged()

    def test_rotation_and_non_uniform_scale(self):
        b, u = blender_layout(), unity_layout()
        find(b, "a1")["rot"] = QM90Y
        find(u, "c3")["scl"] = [1, 1.5, 2]
        sc = Scope(self, b, u, base())
        self.assertEqual(sc.loop(), 0)
        self.assertEqual(sc.plan_counts(), {"blender": {"update": 1}, "unity": {"update": 1}})
        self.assertEqual(find(sc.bdump["items"], "c3")["scl"], [1, 1.5, 2])
        self.assertEqual(find(sc.udump["items"], "a1")["rot"], QM90Y)

    def test_same_move_on_both_sides_is_not_a_conflict(self):
        b, u = blender_layout(), unity_layout()
        find(b, "a1")["pos"] = [0, 0, -1]
        find(u, "a1")["pos"] = [0, 0, -1.0004]
        sc = Scope(self, b, u, base())
        self.assertEqual(sc.loop(), 0)
        self.assertEqual(sc.plan_counts(), {"blender": {}, "unity": {}})
        self.assertEqual(sc.load("synced.json")["items"]["a1"]["pos"], [0, 0, -1])

    def test_reparent_in_unity_is_not_an_edit(self):
        u = [dict(i, key="5/" + i["key"]) for i in unity_layout()]
        sc = Scope(self, blender_layout(), u, base())
        self.assertEqual(sc.loop(), 0)
        self.assertEqual(sc.plan_counts(), {"blender": {}, "unity": {}})

    def test_noise_within_tolerance_and_just_over(self):
        b, u = blender_layout(), unity_layout()
        find(b, "a1")["pos"] = [0.0009, 0, 0]
        find(b, "c3")["scl"] = [1.00009, 1, 1]
        find(u, "b2")["rot"] = [0.0, math.sin(math.radians(45.004)), 0.0, math.cos(math.radians(45.004))]
        sc = Scope(self, b, u, base())
        self.assertEqual(sc.merge(), 0)
        self.assertEqual(sc.plan_counts(), {"blender": {}, "unity": {}})
        find(sc.bdump["items"], "a1")["pos"] = [0.0011, 0, 0]
        sc.write()
        self.assertEqual(sc.merge(), 0)
        self.assertEqual(sc.plan_counts(), {"blender": {}, "unity": {"update": 1}})

    def test_quaternion_sign_flip_is_the_same_rotation(self):
        u = unity_layout()
        find(u, "b2")["rot"] = [-v for v in Q90Y]
        sc = Scope(self, blender_layout(), u, base())
        self.assertEqual(sc.merge(), 0)
        self.assertEqual(sc.plan_counts(), {"blender": {}, "unity": {}})

    def test_float32_values_from_the_dry_run(self):
        """Real dump values (Blender 5.2.2 / Unity 2022.3.22f1, 2026-10-16): a 180 deg wall and a floor at -0.1 m."""
        b = [it("w", "INT_Wall_2x3_A", (-5.0, 0.0, -5.0), [-0.0, -1.0, -0.0, 7.549790126404332e-08], key="W"),
             it("f", "STR_Floor_2x2_A", (-3.0, -0.1, -3.0), key="F")]
        u = [it("w", "INT_Wall_2x3_A", (-5.0, 0.0, -5.0), [0.0, -1.0, 0.0, 7.549790126404332e-8], key="2"),
             it("f", "STR_Floor_2x2_A", (-3.0, -0.10000000149011612, -3.0), key="0")]
        sc = Scope(self, b, u, snapshot_of(u))
        self.assertEqual(sc.merge(), 0)
        self.assertIn("unchanged 2", sc.out)


class Conflicts(unittest.TestCase):
    def setUp(self):
        b, u = blender_layout(), unity_layout()
        find(b, "a1")["pos"] = [0, 0, -1]
        find(u, "a1")["pos"] = [0, 0, -2]
        self.b, self.u = b, u

    def test_different_moves_conflict_until_decided(self):
        sc = Scope(self, self.b, self.u, base())
        self.assertEqual(sc.loop(expect=2), 2)
        self.assertIn("CONFLICT a1", sc.out)
        self.assertEqual(sc.load("synced.json")["items"]["a1"]["pos"], [0, 0, 0])   # kept at its synced state
        self.assertEqual(sc.loop("--take-id", "a1=unity"), 0)
        self.assertEqual(find(sc.bdump["items"], "a1")["pos"], [0, 0, -2])

    def test_take_all_blender(self):
        sc = Scope(self, self.b, self.u, base())
        self.assertEqual(sc.loop("--take", "blender"), 0)
        self.assertEqual(find(sc.udump["items"], "a1")["pos"], [0, 0, -1])

    def test_take_id_side_is_case_insensitive(self):
        sc = Scope(self, self.b, self.u, base())
        self.assertEqual(sc.merge("--take-id", "a1=Unity"), 0)
        self.assertIn("unity wins", sc.out)

    def test_take_id_bad_side_is_an_error(self):
        sc = Scope(self, self.b, self.u, base())
        rc, out = sc.run("merge", "--take-id", "a1=both")
        self.assertEqual(rc, 1)
        self.assertIn("bad --take-id", out)
        rc, out = sc.run("merge", "--take-id", "a1")
        self.assertEqual(rc, 1)

    def test_take_id_that_is_not_a_conflict_is_reported(self):
        sc = Scope(self, self.b, self.u, base())
        self.assertEqual(sc.merge("--take-id", "a1=unity", "--take-id", "zz=blender"), 0)
        self.assertIn("--take-id zz ignored", sc.out)

    def test_delete_versus_move_conflicts(self):
        b = [i for i in blender_layout() if i["id"] != "c3"]
        u = unity_layout()
        find(u, "c3")["pos"] = [-3, 0, -3]
        sc = Scope(self, b, u, base(), b_assets={"WALL_A", "DESK_A"})     # DESK_A still linked / in --libraries
        self.assertEqual(sc.merge(), 2)
        self.assertIn("blender deleted", sc.out)
        self.assertEqual(sc.loop("--take-id", "c3=unity"), 0)
        self.assertEqual(sc.plan_counts(), {"blender": {"create": 1}, "unity": {}})
        sc.converged()

    def test_added_on_both_sides_with_one_id_differently(self):
        b = blender_layout() + [it("z9", "DESK_A", (-1, 0, -1), key="Desk.001")]
        u = unity_layout() + [it("z9", "DESK_A", (-1, 0, -2), key="3")]
        sc = Scope(self, b, u, base())
        self.assertEqual(sc.merge(), 2)
        self.assertIn("added on both sides", sc.out)


class DeletesAndAdditions(unittest.TestCase):
    def test_delete_in_blender_deletes_in_unity(self):
        sc = Scope(self, [i for i in blender_layout() if i["id"] != "c3"], unity_layout(), base())
        self.assertEqual(sc.loop(), 0)
        self.assertEqual(sc.pu["delete"], ["c3"])
        sc.converged()

    def test_delete_in_unity_deletes_in_blender(self):
        sc = Scope(self, blender_layout(), [i for i in unity_layout() if i["id"] != "c3"], base())
        self.assertEqual(sc.loop(), 0)
        self.assertEqual(sc.pb["delete"], ["c3"])

    def test_unity_addition_that_blender_can_take(self):
        u = unity_layout() + [it("", "DESK_A", (-1, 0, -1), key="3")]
        sc = Scope(self, blender_layout(), u, base())
        self.assertEqual(sc.loop(), 0)
        self.assertEqual(sc.plan_counts(), {"blender": {"create": 1}, "unity": {"assign": 1}})
        sc.converged()

    def test_unity_addition_that_blender_cannot_take_stays_unity_only(self):
        u = unity_layout() + [it("", "LAMP_A", (-1, 2, -1), key="3")]
        sc = Scope(self, blender_layout(), u, base(), u_assets={"WALL_A", "DESK_A", "LAMP_A"})
        self.assertEqual(sc.loop(), 0)
        self.assertIn("unity-only 1", sc.out2)
        lamp = [v for v in sc.load("synced.json")["items"].values() if v["asset"] == "LAMP_A"]
        self.assertTrue(lamp and lamp[0].get("unity_only"))

    def test_unity_only_moves_to_blender_once_blender_has_the_collection(self):
        snap = base()
        snap["items"]["L1"] = {"asset": "LAMP_A", "pos": [-1, 2, -1], "rot": QI, "scl": [1, 1, 1], "unity_only": True}
        u = unity_layout() + [it("L1", "LAMP_A", (-1, 2, -1), key="3")]
        sc = Scope(self, blender_layout(), u, snap, b_assets={"WALL_A", "DESK_A", "LAMP_A"})
        self.assertEqual(sc.loop(), 0)
        self.assertEqual(sc.plan_counts(), {"blender": {"create": 1}, "unity": {}})
        self.assertNotIn("unity_only", sc.load("synced.json")["items"]["L1"])
        sc.converged()

    def test_unity_only_deleted_in_unity_is_dropped(self):
        snap = base()
        snap["items"]["L1"] = {"asset": "LAMP_A", "pos": [-1, 2, -1], "rot": QI, "scl": [1, 1, 1], "unity_only": True}
        sc = Scope(self, blender_layout(), unity_layout(), snap)
        self.assertEqual(sc.loop(), 0)
        self.assertNotIn("L1", sc.load("synced.json")["items"])

    def test_first_sync_issues_ids(self):
        b = [dict(i, id="") for i in blender_layout()]
        sc = Scope(self, b, [], None, u_assets={"WALL_A", "DESK_A"})
        self.assertEqual(sc.loop(), 0)
        self.assertEqual(sc.plan_counts(), {"blender": {"assign": 3}, "unity": {"create": 3}})
        self.assertTrue(all(a["was"] == "" and a["asset"] for a in sc.pb["assign"]))
        sc.converged()


class Duplicates(unittest.TestCase):
    def test_duplicate_in_blender_becomes_a_new_placement(self):
        b = blender_layout() + [dict(blender_layout()[0], key="Wall.002", pos=[4, 0, 0])]
        sc = Scope(self, b, unity_layout(), base())
        self.assertEqual(sc.loop(), 0)
        self.assertEqual(sc.plan_counts(), {"blender": {"assign": 1}, "unity": {"create": 1}})
        self.assertEqual(sc.pb["assign"][0]["key"], "Wall.002")
        self.assertEqual(sc.pb["assign"][0]["was"], "a1")
        self.assertEqual(find(sc.bdump["items"], "a1")["key"], "Wall")
        sc.converged()

    def test_duplicate_in_unity_becomes_a_new_placement(self):
        u = unity_layout() + [dict(unity_layout()[0], key="3", name="WALL_A (1)", pos=[4, 0, 0])]
        sc = Scope(self, blender_layout(), u, base())
        self.assertEqual(sc.loop(), 0)
        self.assertEqual(sc.plan_counts(), {"blender": {"create": 1}, "unity": {"assign": 1}})
        sc.converged()

    def test_copy_left_in_place_keeps_the_id(self):
        b = blender_layout()
        find(b, "a1")["pos"] = [5, 0, 0]                                  # the original moved away
        b.append(dict(blender_layout()[0], key="Wall.002"))                # the copy at the synced pose
        sc = Scope(self, b, unity_layout(), base())
        self.assertEqual(sc.loop(), 0)
        self.assertEqual(find(sc.bdump["items"], "a1")["key"], "Wall.002")
        sc.converged()


class Blocked(unittest.TestCase):
    def test_create_without_a_unity_prefab_is_blocked_then_retried(self):
        b = blender_layout() + [it("", "NEW_PIECE", (-5, 0, 0), key="New")]
        sc = Scope(self, b, unity_layout(), base())
        self.assertEqual(sc.loop(expect=3), 3)                             # apply and commit still go through
        self.assertIn("BLOCKED create", sc.out)
        self.assertIn("a new piece, so export and package it", sc.out)
        new_id = sc.pb["assign"][0]["id"]
        sc.udump["assets"] = sorted(set(sc.udump["assets"]) | {"NEW_PIECE"})  # the prefab now exists
        sc.write()
        self.assertEqual(sc.loop(), 0)
        self.assertEqual(sc.pu["create"][0]["id"], new_id)
        sc.converged()

    def test_unity_asset_blender_does_not_have_is_blocked(self):
        u = unity_layout()
        for i in u:
            if i["asset"] == "WALL_A":
                i["asset"] = "WALL_RENAMED"                                # the prefab renamed in Unity: every instance
        sc = Scope(self, blender_layout(), u, base(), u_assets={"WALL_RENAMED", "DESK_A"})
        self.assertEqual(sc.loop(expect=3), 3)
        self.assertEqual(sc.pb["update"], [])
        self.assertIn("Blender has no collection called WALL_RENAMED (it has WALL_A, which Unity no longer has): "
                      "finish (or undo) the rename on the Blender side", sc.out)
        self.assertNotIn("export and package", sc.out)
        self.assertEqual(sc.load("synced.json")["items"]["a1"]["asset"], "WALL_A")

    def test_rename_finished_in_blender_only_points_at_unity(self):
        b = blender_layout()
        for i in b:
            if i["asset"] == "WALL_A":
                i["asset"] = "WALL_B"                                      # renamed in Blender and re-pointed
        sc = Scope(self, b, unity_layout(), base())
        self.assertEqual(sc.merge(), 3)
        self.assertEqual(sc.pu["update"], [])
        self.assertIn("Unity has no prefab called WALL_B (it has WALL_A, which Blender no longer has): finish (or "
                      "undo) the rename on the Unity side", sc.out)
        self.assertNotIn("export and package", sc.out)

    def test_rename_done_on_both_sides_keeps_the_ids(self):
        """The kit skill's rename: re-point instances in Blender, rename the prefab in Unity. Nothing to sync."""
        b, u = blender_layout(), unity_layout()
        for i in b + u:
            if i["asset"] == "WALL_A":
                i["asset"] = "WALL_B"
        sc = Scope(self, b, u, base())
        self.assertEqual(sc.loop(), 0)
        self.assertEqual(sc.plan_counts(), {"blender": {}, "unity": {}})
        snap = sc.load("synced.json")["items"]
        self.assertEqual(sorted(snap), ["a1", "b2", "c3"])
        self.assertEqual(snap["a1"]["asset"], "WALL_B")

    def test_one_placement_swapped_in_blender_is_not_called_a_rename(self):
        """One wall re-pointed to WALL_C, which Unity has no prefab for; the other walls still use WALL_A."""
        b = blender_layout()
        find(b, "a1")["asset"] = "WALL_C"
        sc = Scope(self, b, unity_layout(), base())
        self.assertEqual(sc.merge(), 3)
        self.assertIn("a placement was swapped from WALL_A to a piece Unity lacks, so export and package WALL_C; "
                      "never rename WALL_A", sc.out)
        self.assertNotIn("finish (or undo) the rename", sc.out)

    def test_one_instance_swapped_in_unity_is_not_called_a_rename(self):
        """One Unity instance replaced by a Unity-only prefab LAMP_X; WALL_A is still a Unity prefab."""
        u = unity_layout()
        find(u, "a1")["asset"] = "LAMP_X"
        sc = Scope(self, blender_layout(), u, base(), u_assets={"WALL_A", "DESK_A", "LAMP_X"})
        self.assertEqual(sc.merge(), 3)
        self.assertIn("swapped in Unity from WALL_A to a prefab Blender lacks, so add LAMP_X as a KIT piece or undo "
                      "the swap in Unity; never rename WALL_A", sc.out)
        self.assertNotIn("finish (or undo) the rename", sc.out)

    def test_rename_and_swap_from_one_piece_is_not_a_rename(self):
        """Blender renamed WALL_A to WALL_R for three walls and swapped the fourth to WALL_C (WALL_A is gone from
        Blender): no line may suggest renaming the prefab, since either rename would break the other placements."""
        walls = [it("w%d" % n, "WALL_A", (2 * n, 0, 0), key="W%d" % n) for n in range(4)]
        b = copy.deepcopy(walls)
        for i in b[:3]:
            i["asset"] = "WALL_R"
        b[3]["asset"] = "WALL_C"
        u = [dict(i, key=str(n)) for n, i in enumerate(walls)]
        sc = Scope(self, b, u, snapshot_of(walls))
        self.assertEqual(sc.merge(), 3)
        self.assertEqual(sc.out.count("its placements now use several pieces Unity lacks (WALL_C x1, WALL_R x3)"), 4,
                         sc.out)
        self.assertNotIn("finish (or undo) the rename", sc.out)

    def test_rename_plus_a_swap_to_a_piece_unity_has_is_a_plain_rename(self):
        """WALL_A renamed WALL_R in Blender (3 walls) and the 4th swapped to WALL_B, which Unity already has: only
        WALL_R is missing in Unity, so the lines suggest the rename, and the swap to WALL_B goes through."""
        walls = [it("w%d" % n, "WALL_A", (2 * n, 0, 0), key="W%d" % n) for n in range(4)]
        b = copy.deepcopy(walls)
        for i in b[:3]:
            i["asset"] = "WALL_R"
        b[3]["asset"] = "WALL_B"
        u = [dict(i, key=str(n)) for n, i in enumerate(walls)]
        sc = Scope(self, b, u, snapshot_of(walls), u_assets={"WALL_A", "WALL_B"})
        self.assertEqual(sc.merge(), 3)
        self.assertEqual(sc.out.count("finish (or undo) the rename on the Unity side, renaming the prefab and its FBX "
                                      "to WALL_R"), 3, sc.out)
        self.assertNotIn("several pieces", sc.out)
        self.assertEqual([i["id"] for i in sc.pu["update"]], ["w3"])

    def test_new_placements_of_a_renamed_piece_get_the_rename_text(self):
        """WALL_A renamed WALL_R in Blender, plus two new WALL_R walls: one instruction for the one prefab."""
        walls = [it("w%d" % n, "WALL_A", (2 * n, 0, 0), key="W%d" % n) for n in range(3)]
        b = copy.deepcopy(walls)
        for i in b:
            i["asset"] = "WALL_R"
        b += [it("", "WALL_R", (10, 0, 0), key="N1"), it("", "WALL_R", (12, 0, 0), key="N2")]
        u = [dict(i, key=str(n)) for n, i in enumerate(walls)]
        sc = Scope(self, b, u, snapshot_of(walls))
        self.assertEqual(sc.merge(), 3)
        self.assertEqual(sc.out.count("finish (or undo) the rename on the Unity side"), 5, sc.out)
        self.assertNotIn("export and package", sc.out)

    def test_assembly_swapped_in_blender_points_at_its_scope(self):
        """A MASTER stall swapped to ASM_Stall_B before B's own scope synced: never 'export and package' an assembly."""
        b = [it("s%d" % n, "ASM_Stall_A", (4 * n, 0, 0), key="S%d" % n) for n in range(3)]
        base_items = copy.deepcopy(b)
        b[2]["asset"] = "ASM_Stall_B"
        u = [dict(i, key=str(n)) for n, i in enumerate(base_items)]
        sc = Scope(self, b, u, snapshot_of(base_items))
        self.assertEqual(sc.merge(), 3)
        self.assertIn("so sync ASM_Stall_B's own scope first; never rename ASM_Stall_A", sc.out)
        self.assertNotIn("export and package", sc.out)

    def test_assembly_swapped_in_unity_points_at_an_asm_file(self):
        base_items = [it("s%d" % n, "ASM_Stall_A", (4 * n, 0, 0), key="S%d" % n) for n in range(2)]
        u = [dict(i, key=str(n)) for n, i in enumerate(base_items)]
        u[1]["asset"] = "ASM_Stall_B"
        sc = Scope(self, copy.deepcopy(base_items), u, snapshot_of(base_items),
                   u_assets={"ASM_Stall_A", "ASM_Stall_B"})
        self.assertEqual(sc.merge(), 3)
        self.assertIn("so build it (under ASM in MASTER, or in blender/asm/ASM_Stall_B.blend with split files) and "
                      "sync its scope, or undo the swap in Unity", sc.out)
        self.assertNotIn("KIT piece", sc.out)

    def test_renamed_assembly_points_at_the_prefab_not_an_fbx(self):
        b = blender_layout() + [it("s1", "ASM_Booth_A", (-8, 0, 0), key="Shop")]
        u = unity_layout() + [it("s1", "ASM_Shop_A", (-8, 0, 0), key="3")]
        snap = snapshot_of(blender_layout() + [it("s1", "ASM_Shop_A", (-8, 0, 0))])
        sc = Scope(self, b, u, snap)
        self.assertEqual(sc.merge(), 3)
        self.assertIn("renaming the assembly prefab to ASM_Booth_A (it has no FBX)", sc.out)
        self.assertNotIn("its FBX", sc.out)

    def test_assembly_without_a_prefab_points_at_its_scope(self):
        b = blender_layout() + [it("", "ASM_Shop_A", (-8, 0, 0), key="Shop")]
        sc = Scope(self, b, unity_layout(), base())
        self.assertEqual(sc.merge(), 3)
        self.assertIn("sync that assembly's own ASM scope first", sc.out)

    def test_conflict_won_by_unity_with_an_asset_blender_lacks_is_blocked(self):
        b, u = blender_layout(), unity_layout()
        find(b, "a1")["pos"] = [0, 0, -1]
        find(u, "a1")["asset"] = "WALL_RENAMED"
        sc = Scope(self, b, u, base(), u_assets={"WALL_RENAMED", "DESK_A"})
        self.assertEqual(sc.merge("--take-id", "a1=unity"), 3)
        self.assertEqual(sc.pb["update"], [])


class SafetyRefusals(unittest.TestCase):
    def assertRefused(self, sc, text):
        self.assertEqual(sc.rc, 4, sc.out)
        self.assertIn("REFUSED", sc.out)
        self.assertIn(text, sc.out)
        self.assertEqual(sc.plan_counts(), {"blender": {}, "unity": {}})
        rc, out = sc.run("commit")
        self.assertEqual(rc, 2, out)
        self.assertIn("last merge was refused", out)

    def test_empty_unity_dump_is_refused(self):
        sc = Scope(self, blender_layout(), [], base(), u_assets=[])
        sc.merge()
        self.assertRefused(sc, "the Unity dump has no placements")
        self.assertEqual(sc.merge("--allow-deletes"), 0)                   # the user confirmed: delete them
        self.assertEqual(len(sc.pb["delete"]), 3)

    def test_empty_blender_dump_is_refused(self):
        sc = Scope(self, [], unity_layout(), base(), b_assets=[])
        sc.merge()
        self.assertRefused(sc, "the Blender dump has no placements")

    def test_deletions_over_the_budget_are_refused(self):
        many = [it("p%d" % n, "WALL_A", (2 * n, 0, 0), key="P%d" % n) for n in range(6)]
        sc = Scope(self, many[:1], many[:6], snapshot_of(many))           # five deleted in Blender
        sc.merge()
        self.assertRefused(sc, "the plans delete 5 placements; the budget is 3")
        within = [it("p%d" % n, "WALL_A", (2 * n, 0, 0), key="P%d" % n) for n in range(18)]
        sc = Scope(self, within[3:], within, snapshot_of(within))         # three of eighteen: within budget
        self.assertEqual(sc.merge(), 0)
        self.assertEqual(len(sc.pu["delete"]), 3)

    def test_dump_from_another_blender_file_is_refused(self):
        src = {"blender_file": "master.blend", "blender_collection": None, "unity_target": "scene:MASTER"}
        sc = Scope(self, blender_layout(), unity_layout(), snapshot_of(blender_layout(), src),
                   b_file="ASM_Shop_A.blend")
        sc.merge()
        self.assertRefused(sc, "blender_file is asm_shop_a.blend, but this scope was synced with master.blend")
        self.assertEqual(sc.merge("--accept-source"), 0)

    def test_dump_from_another_unity_target_is_refused(self):
        src = {"blender_file": "master.blend", "blender_collection": None, "unity_target": "scene:MASTER"}
        sc = Scope(self, blender_layout(), unity_layout(), snapshot_of(blender_layout(), src),
                   target="prefab:Assets/World/Assemblies/ASM_Shop_A.prefab")
        sc.merge()
        self.assertRefused(sc, "unity_target is prefab:")

    def test_commit_records_the_source(self):
        sc = Scope(self, blender_layout(), unity_layout(), base())
        self.assertEqual(sc.loop(), 0)
        self.assertEqual(sc.load("synced.json")["source"],
                         {"blender_file": "master.blend", "blender_collection": None, "unity_target": "scene:MASTER"})


class LostIdsAndRecovery(unittest.TestCase):
    def test_half_applied_loop_does_not_duplicate(self):
        """Blender applied a create for a Unity addition (n1); Unity refused before its assign. Re-run from the dumps."""
        b = blender_layout() + [it("n1", "DESK_A", (-1, 0, -1), key="DESK_A")]
        u = unity_layout() + [it("", "DESK_A", (-1, 0, -1), key="3")]
        sc = Scope(self, b, u, base())
        self.assertEqual(sc.loop(), 0)
        self.assertEqual(sc.plan_counts(), {"blender": {}, "unity": {"assign": 1}})
        self.assertEqual(len(sc.bdump["items"]), 4)
        self.assertEqual(len(sc.udump["items"]), 4)
        sc.converged()

    def test_id_lost_in_unity_is_taken_back(self):
        """Overrides > Revert All removed a1's PlacementId; the instance did not move."""
        u = unity_layout()
        find(u, "a1")["id"] = ""
        sc = Scope(self, blender_layout(), u, base())
        self.assertEqual(sc.loop(), 0)
        self.assertEqual(sc.plan_counts(), {"blender": {}, "unity": {"assign": 1}})
        self.assertEqual(sc.pu["assign"][0]["id"], "a1")

    def test_id_lost_in_unity_while_blender_moved_it(self):
        b, u = blender_layout(), unity_layout()
        find(b, "a1")["pos"] = [0, 0, -1]
        find(u, "a1")["id"] = ""
        sc = Scope(self, b, u, base())
        self.assertEqual(sc.loop(), 0)
        self.assertEqual(sc.plan_counts(), {"blender": {}, "unity": {"assign": 1, "update": 1}})
        self.assertEqual(find(sc.udump["items"], "a1")["pos"], [0, 0, -1])

    def test_matching_layouts_without_ids_pair_up(self):
        """A first sync where Unity already holds the same layout, built by hand: nothing is doubled."""
        b = [dict(i, id="") for i in blender_layout()]
        u = [dict(i, id="") for i in unity_layout()] + [it("", "DESK_A", (-9, 0, -9), key="3")]
        sc = Scope(self, b, u, None)
        self.assertEqual(sc.loop(), 0)
        self.assertEqual(sc.plan_counts(), {"blender": {"assign": 3, "create": 1}, "unity": {"assign": 4}})
        self.assertEqual(len(sc.bdump["items"]), 4)
        sc.converged()


class SamePoseCopies(unittest.TestCase):
    def test_copies_at_one_pose_are_reported(self):
        """A lighting-state copy of the desk made inside MASTER: the merge says where such copies belong."""
        u = unity_layout() + [dict(unity_layout()[2], id="", key="3", name="DESK_A (lights on)")]
        sc = Scope(self, blender_layout(), u, base())
        sc.merge()
        self.assertIn("unity: 2 placements of DESK_A at the same pose", sc.out)
        self.assertIn("LIGHT_STATES", sc.out)

    def test_no_report_without_copies(self):
        sc = Scope(self, blender_layout(), unity_layout(), base())
        self.assertEqual(sc.merge(), 0)
        self.assertNotIn("same pose", sc.out)


def named(items, side):
    """A layout as the current appliers dump it: labels and folder groups (Blender's .001 already dropped)."""
    labels = {"a1": ("Wall", "Street"), "b2": ("Wall", "Street"), "c3": ("Desk", "")}
    out = []
    for n, i in enumerate(items):
        label, group = labels.get(i["id"], (i["asset"], ""))
        out.append(dict(i, label=label, group=group, **({"key": str(n)} if side == "unity" else {})))
    return out


def named_snapshot():
    snap = snapshot_of(blender_layout())
    for i in named(blender_layout(), "blender"):
        snap["items"][i["id"]].update(label=i["label"], group=i["group"])
    return snap


class NamesAndFolders(unittest.TestCase):
    def test_rename_in_unity_and_move_in_blender_both_land(self):
        b, u = named(blender_layout(), "blender"), named(blender_layout(), "unity")
        find(b, "a1")["pos"] = [0, 0, -1]
        find(u, "a1")["label"] = "Shop wall"
        sc = Scope(self, b, u, named_snapshot())
        self.assertEqual(sc.loop(), 0)
        self.assertEqual(sc.plan_counts(), {"blender": {"update": 1}, "unity": {"update": 1}})
        self.assertIn("renamed 'Wall' -> 'Shop wall'", sc.out)
        self.assertEqual(find(sc.bdump["items"], "a1")["label"], "Shop wall")
        self.assertEqual(find(sc.udump["items"], "a1")["pos"], [0, 0, -1])
        self.assertIn("unchanged 3", sc.out2)

    def test_folder_change_in_blender_reaches_unity(self):
        b = named(blender_layout(), "blender")
        find(b, "c3")["group"] = "Office/Desks"
        sc = Scope(self, b, named(blender_layout(), "unity"), named_snapshot())
        self.assertEqual(sc.loop(), 0)
        self.assertEqual(sc.plan_counts(), {"blender": {}, "unity": {"update": 1}})
        self.assertEqual(find(sc.udump["items"], "c3")["group"], "Office/Desks")
        self.assertEqual(sc.load("synced.json")["items"]["c3"]["group"], "Office/Desks")

    def test_renamed_differently_on_both_sides_conflicts_on_the_name_only(self):
        b, u = named(blender_layout(), "blender"), named(blender_layout(), "unity")
        find(b, "a1")["label"] = "North wall"
        find(u, "a1")["label"] = "Shop wall"
        find(u, "a1")["pos"] = [0, 0, -2]
        sc = Scope(self, b, u, named_snapshot())
        self.assertEqual(sc.merge(), 2)
        self.assertIn("CONFLICT a1: label: blender 'North wall', unity 'Shop wall'", sc.out)
        self.assertEqual(sc.loop("--take-id", "a1=blender"), 0)
        for side in (sc.bdump, sc.udump):
            self.assertEqual(find(side["items"], "a1")["label"], "North wall")
            self.assertEqual(find(side["items"], "a1")["pos"], [0, 0, -2])     # Unity's move was no conflict

    def test_first_sync_after_the_upgrade_keeps_whichever_side_renamed(self):
        """An old snapshot has no names: the asset name and the root count as the starting point."""
        b = named(blender_layout(), "blender")
        u = [dict(i, label=i["asset"], group="", key=str(n)) for n, i in enumerate(blender_layout())]
        find(b, "c3")["label"] = "DESK_A"
        find(u, "c3")["label"] = "Lobby desk"
        sc = Scope(self, b, u, base())
        self.assertEqual(sc.loop(), 0)
        self.assertEqual(sc.plan_counts(), {"blender": {"update": 1}, "unity": {"update": 2}})
        self.assertEqual(find(sc.udump["items"], "a1")["label"], "Wall")
        self.assertEqual(find(sc.udump["items"], "b2")["group"], "Street")
        self.assertEqual(find(sc.bdump["items"], "c3")["label"], "Lobby desk")

    def test_nested_unity_placement_keeps_its_parent_as_folder(self):
        b, u = named(blender_layout(), "blender"), named(blender_layout(), "unity")
        find(b, "c3")["group"] = "Office"
        find(u, "c3").update(group="", nested=True)
        sc = Scope(self, b, u, named_snapshot())
        self.assertEqual(sc.loop(), 0)
        self.assertEqual(sc.plan_counts(), {"blender": {}, "unity": {}})
        self.assertIn("unchanged 3", sc.out2)

    def test_slash_in_a_name_is_cleaned_once(self):
        b = named(blender_layout(), "blender")
        find(b, "a1")["label"] = "Shop/Front "
        sc = Scope(self, b, named(blender_layout(), "unity"), named_snapshot())
        self.assertEqual(sc.loop(), 0)
        self.assertEqual(find(sc.udump["items"], "a1")["label"], "Shop-Front")
        self.assertIn("unchanged 3", sc.out2)

    def test_an_older_applier_without_names_gets_no_renames(self):
        b = named(blender_layout(), "blender")
        find(b, "a1")["label"] = "Shop wall"
        sc = Scope(self, b, unity_layout(), base())
        self.assertEqual(sc.loop(), 0)
        self.assertEqual(sc.plan_counts(), {"blender": {}, "unity": {}})

    def test_a_create_carries_its_name_and_folder(self):
        b = named(blender_layout(), "blender") + [dict(it("", "DESK_A", (-1, 0, -1), key="Desk.002"),
                                                       label="Reception desk", group="Lobby")]
        sc = Scope(self, b, named(blender_layout(), "unity"), named_snapshot())
        self.assertEqual(sc.loop(), 0)
        made = sc.pu["create"][0]
        self.assertEqual((made["label"], made["group"]), ("Reception desk", "Lobby"))
        sc.converged()


class BadInput(unittest.TestCase):
    def test_missing_dump(self):
        sc = Scope(self, blender_layout(), unity_layout(), base())
        os.remove(sc.path("unity.json"))
        rc, out = sc.run("merge")
        self.assertEqual(rc, 1, out)
        self.assertIn("missing", out)

    def test_swapped_dumps(self):
        sc = Scope(self, blender_layout(), unity_layout(), base())
        sc.save("blender.json", sc.udump)
        rc, out = sc.run("merge")
        self.assertEqual(rc, 1, out)

    def test_commit_refuses_an_id_on_two_objects(self):
        sc = Scope(self, blender_layout(), unity_layout(), base())
        self.assertEqual(sc.merge(), 0)
        sc.udump["items"].append(dict(unity_layout()[0], key="9"))         # duplicated after the merge
        sc.write()
        rc, out = sc.run("commit")
        self.assertEqual(rc, 2, out)
        self.assertIn("on more than one object", out)


if __name__ == "__main__":
    unittest.main()
