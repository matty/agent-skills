"""Three-way merge of placements between Blender and Unity, against the last synced snapshot.

Host: plain Python 3.9+, standard library only. Reads the dumps written by export_placements.py (Blender) and
PlacementSync.cs (Unity); writes one plan per side and a pending file; never touches Blender or Unity itself.

    python placement_merge.py merge  --dir placements --scope MASTER [--take blender|unity] [--take-id ID=blender ...]
    python placement_merge.py commit --dir placements --scope MASTER

Files, all in --dir, all named after the scope:
    <scope>.blender.json   dump from Blender            (input)
    <scope>.unity.json     dump from Unity              (input)
    <scope>.synced.json    snapshot of the last sync    (input; absent on the first sync)
    <scope>.plan.blender.json, <scope>.plan.unity.json  what each side must apply  (merge output)
    <scope>.pending.json   the state both sides should reach, for commit           (merge output)
    <scope>.report.txt     human-readable diff, also printed                       (merge output)
    <scope>.synced.prev.json   the snapshot before the last commit                 (commit output)

merge is a dry run: it only writes plans and the report. commit re-reads fresh dumps after both sides applied
their plans, checks they agree with each other and with pending, and only then replaces the snapshot.
Exit codes: 0 ok, 2 conflicts or blocked items remain (merge) / sides disagree (commit), 1 bad input.

Item (Unity space: left-handed, Y up, metres, relative to the scope root):
    {"id": "9f2c41d0a7b3", "asset": "EXT_Wall_2x3_A", "pos": [x, y, z], "rot": [x, y, z, w], "scl": [x, y, z],
     "key": "<side-local handle: Blender object name / Unity sibling-index path>"}
"""

import argparse
import json
import math
import os
import shutil
import sys
import uuid

POS_TOL = 0.001      # metres
ROT_TOL = 0.01       # degrees
SCL_TOL = 1e-4       # relative


def new_id():
    return uuid.uuid4().hex[:12]


def _read(path, default=None):
    if not os.path.exists(path):
        if default is not None:
            return default
        sys.exit("missing %s" % path)
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def _write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def rot_angle(a, b):
    dot = abs(sum(x * y for x, y in zip(a, b)))
    na = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) or 1.0
    return math.degrees(2.0 * math.acos(min(1.0, dot / na)))


def differences(a, b):
    """Names of the fields that differ beyond tolerance (empty list = same placement)."""
    out = []
    if a["asset"] != b["asset"]:
        out.append("asset %s -> %s" % (a["asset"], b["asset"]))
    d = math.dist(a["pos"], b["pos"])
    if d > POS_TOL:
        out.append("moved %.3f m" % d)
    r = rot_angle(a["rot"], b["rot"])
    if r > ROT_TOL:
        out.append("rotated %.2f deg" % r)
    if any(abs(x - y) > SCL_TOL * max(1.0, abs(y)) for x, y in zip(a["scl"], b["scl"])):
        out.append("scaled %s -> %s" % ([round(v, 4) for v in a["scl"]], [round(v, 4) for v in b["scl"]]))
    return out


def _state(item):
    return {k: item[k] for k in ("asset", "pos", "rot", "scl")}


def label(it):
    """How a report names an object: Unity's hierarchy path when the dump has one, else its key."""
    return it.get("name") or it["key"]


def resolve_ids(items, base, side, assigns):
    """id -> item for one side. Duplicate ids (an object duplicated after it was synced) keep the id on the copy
    closest to the snapshot; the others, and items with no id yet, get fresh ids recorded in `assigns`."""
    groups = {}
    for it in items:
        groups.setdefault(it.get("id") or "", []).append(it)
    out = {}
    notes = []
    for pid, group in groups.items():
        if pid:
            ref = base.get(pid)
            if ref:
                group.sort(key=lambda it: (math.dist(it["pos"], ref["pos"]), rot_angle(it["rot"], ref["rot"]),
                                           it["key"]))
            else:
                group.sort(key=lambda it: it["key"])
            out[pid] = group[0]
            rest = group[1:]
            if rest:
                notes.append("%s: id %s on %d objects; kept on %s, re-issued for %s"
                             % (side, pid, len(group), label(group[0]), ", ".join(label(it) for it in rest)))
        else:
            rest = group
        for it in rest:
            nid = new_id()
            while nid in groups or nid in out or nid in base:
                nid = new_id()
            assigns.append({"key": it["key"], "id": nid})
            out[nid] = dict(it, id=nid)
    return out, notes


def merge(args):
    d, s = args.dir, args.scope
    path = lambda suffix: os.path.join(d, "%s.%s" % (s, suffix))
    bdump, udump = _read(path("blender.json")), _read(path("unity.json"))
    snap = _read(path("synced.json"), {"scope": s, "version": 1, "items": {}})
    base = snap["items"]
    take_all = args.take
    take_id = dict(t.split("=", 1) for t in args.take_id)

    plans = {side: {"scope": s, "side": side, "assign": [], "delete": [], "update": [], "create": []}
             for side in ("blender", "unity")}
    L, notes_l = resolve_ids(bdump["items"], base, "blender", plans["blender"]["assign"])
    U, notes_u = resolve_ids(udump["items"], base, "unity", plans["unity"]["assign"])
    blender_assets = set(bdump.get("assets") or [i["asset"] for i in bdump["items"]])
    unity_assets = set(udump.get("assets") or [i["asset"] for i in udump["items"]])

    state, skip, unity_only, conflicts, blocked, lines = {}, [], [], [], [], []
    counts = {"unchanged": 0}

    def push(side, kind, pid, item):
        plans[side][kind].append(dict(_state(item), id=pid, key=item.get("key", "")))
        src = "unity" if side == "blender" else "blender"
        lines.append("  %-7s -> %-7s %-6s %s %s" % (src, side, kind, pid, item["asset"]))

    def to_unity(kind, pid, item):
        if kind != "delete" and item["asset"] not in unity_assets:
            blocked.append(pid)
            lines.append("  BLOCKED %s %s: no Unity prefab for %s yet (export and package it, then sync again)"
                         % (kind, pid, item["asset"]))
            skip.append(pid)
            return
        if kind == "delete":
            plans["unity"]["delete"].append(pid)
            lines.append("  blender -> unity   delete %s" % pid)
        else:
            push("unity", kind, pid, item)
            state[pid] = _state(item)

    def to_blender(kind, pid, item):
        if kind == "delete":
            plans["blender"]["delete"].append(pid)
            lines.append("  unity   -> blender delete %s" % pid)
        else:
            push("blender", kind, pid, item)
            state[pid] = _state(item)

    for pid in sorted(set(base) | set(L) | set(U)):
        b, l, u = base.get(pid), L.get(pid), U.get(pid)
        if b and b.get("unity_only"):
            if u:
                state[pid] = dict(_state(u), unity_only=True)
                unity_only.append(pid)
            continue
        if not b:
            if l and u:
                diff = differences(l, u)
                if not diff:
                    state[pid] = _state(l)
                    counts["unchanged"] += 1
                else:
                    conflicts.append((pid, "added on both sides, different: " + "; ".join(diff), l, u, None))
            elif l:
                to_unity("create", pid, l)
            elif u["asset"] in blender_assets:
                to_blender("create", pid, u)
            else:
                state[pid] = dict(_state(u), unity_only=True)
                unity_only.append(pid)
                lines.append("  unity-only %s %s (no such collection in Blender; left to Unity)" % (pid, u["asset"]))
            continue
        lc = "gone" if not l else ("changed" if differences(l, b) else "same")
        uc = "gone" if not u else ("changed" if differences(u, b) else "same")
        if lc == uc == "same":
            state[pid] = _state(b)
            counts["unchanged"] += 1
        elif lc == "changed" and uc == "same":
            to_unity("update", pid, l)
        elif lc == "same" and uc == "changed":
            to_blender("update", pid, u)
        elif lc == uc == "gone":
            lines.append("  deleted on both sides %s" % pid)
        elif lc == "gone" and uc == "same":
            to_unity("delete", pid, None)
        elif lc == "same" and uc == "gone":
            to_blender("delete", pid, None)
        elif lc == uc == "changed" and not differences(l, u):
            state[pid] = _state(l)
            counts["unchanged"] += 1
        else:
            what = {"gone": "deleted", "changed": "changed"}
            why = "blender %s (%s), unity %s (%s)" % (
                what[lc], "; ".join(differences(l, b)) if l else "-",
                what[uc], "; ".join(differences(u, b)) if u else "-")
            conflicts.append((pid, why, l, u, b))

    unresolved = []
    for pid, why, l, u, b in conflicts:
        winner = take_id.get(pid, take_all)
        if winner == "blender":
            lines.append("  conflict %s resolved: blender wins (%s)" % (pid, why))
            if l is None:
                to_unity("delete", pid, None)
            else:
                to_unity("update" if u else "create", pid, l)
        elif winner == "unity":
            lines.append("  conflict %s resolved: unity wins (%s)" % (pid, why))
            if u is None:
                to_blender("delete", pid, None)
            else:
                to_blender("update" if l else "create", pid, u)
        else:
            unresolved.append({"id": pid, "why": why,
                               "blender": l and _state(l), "unity": u and _state(u), "synced": b and _state(b)})
            skip.append(pid)

    for side in plans:
        _write(path("plan.%s.json" % side), plans[side])
    _write(path("pending.json"), {"scope": s, "state": state, "skip": skip,
                                  "base_kept": {p: base[p] for p in skip if p in base}})

    report = ["placement sync %s: %d blender, %d unity, %d in snapshot" % (s, len(L), len(U), len(base))]
    report += notes_l + notes_u
    for side in ("blender", "unity"):
        p = plans[side]
        report.append("%s plan: %d assign, %d create, %d update, %d delete"
                      % (side, len(p["assign"]), len(p["create"]), len(p["update"]), len(p["delete"])))
    report.append("unchanged %d, unity-only %d, blocked %d, unresolved conflicts %d"
                  % (counts["unchanged"], len(unity_only), len(blocked), len(unresolved)))
    report += lines
    for c in unresolved:
        report.append("  CONFLICT %s: %s   (re-run with --take-id %s=blender or =unity)" % (c["id"], c["why"],
                                                                                         c["id"]))
    text = "\n".join(report)
    with open(path("report.txt"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
        if unresolved:
            f.write(json.dumps(unresolved, indent=2) + "\n")
    print(text)
    return 2 if unresolved or blocked else 0


def commit(args):
    d, s = args.dir, args.scope
    path = lambda suffix: os.path.join(d, "%s.%s" % (s, suffix))
    pending = _read(path("pending.json"))
    L = {i["id"]: i for i in _read(path("blender.json"))["items"] if i.get("id")}
    U = {i["id"]: i for i in _read(path("unity.json"))["items"] if i.get("id")}
    state, skip = pending["state"], set(pending["skip"])
    bad = []
    for pid, want in state.items():
        sides = (("unity", U),) if want.get("unity_only") else (("blender", L), ("unity", U))
        for name, side in sides:
            have = side.get(pid)
            if have is None:
                bad.append("%s missing in %s" % (pid, name))
            elif differences(have, want):
                bad.append("%s in %s: %s" % (pid, name, "; ".join(differences(have, want))))
    for name, side in (("blender", L), ("unity", U)):
        for pid in side:
            if pid not in state and pid not in skip:
                bad.append("%s still present in %s but the plan removed it" % (pid, name))
    if bad:
        print("commit refused, the sides do not match the plan (snapshot unchanged):")
        print("\n".join("  " + b for b in bad))
        return 2
    items = dict(state)
    items.update(pending.get("base_kept", {}))
    snap_path = path("synced.json")
    if os.path.exists(snap_path):
        shutil.copyfile(snap_path, path("synced.prev.json"))
    _write(snap_path, {"scope": s, "version": 1, "items": items})
    print("committed %s: %d placements in snapshot (%d conflict(s) left at their previous synced state)"
          % (s, len(items), len(pending.get("base_kept", {}))))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("merge")
    c = sub.add_parser("commit")
    for p in (m, c):
        p.add_argument("--dir", required=True)
        p.add_argument("--scope", required=True)
    m.add_argument("--take", choices=("blender", "unity"), help="resolve every conflict this way")
    m.add_argument("--take-id", action="append", default=[], metavar="ID=SIDE", help="resolve one conflict")
    args = ap.parse_args()
    sys.exit(merge(args) if args.cmd == "merge" else commit(args))


if __name__ == "__main__":
    main()
