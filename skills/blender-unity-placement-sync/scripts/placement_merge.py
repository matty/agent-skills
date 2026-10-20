"""Three-way merge of placements between Blender and Unity, against the last synced snapshot.

Host: plain Python 3.9+, standard library only. Reads the dumps written by export_placements.py (Blender) and
PlacementSync.cs (Unity); writes one plan per side and a pending file; never touches Blender or Unity itself.

    python placement_merge.py merge  --dir <placements> --scope MASTER [--take blender|unity] [--take-id ID=SIDE ...]
                                     [--allow-deletes] [--allow-renames] [--accept-source]
    python placement_merge.py commit --dir <placements> --scope MASTER

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

Exit codes. merge: 0 plans ready; 2 unresolved conflicts (decide them with --take-id / --take, the rest of the plan
is ready); 3 only BLOCKED items left (apply and commit anyway: they stay pending and the next merge retries them);
4 REFUSED for safety (more deletions or renames than the budget, an empty side, or a dump from another file or Unity
target than this scope's snapshot: empty plans are written); 1 bad input. commit: 0 committed; 2 refused.

Item (Unity space: left-handed, Y up, metres, relative to the scope root):
    {"id": "9f2c41d0a7b3", "asset": "EXT_Wall_2x3_A", "pos": [x, y, z], "rot": [x, y, z, w], "scl": [x, y, z],
     "label": "Shopfront wall", "group": "Street/Shops",
     "key": "<side-local handle: Blender object name / Unity sibling-index path>"}
"label" is the placement's name (Blender object, Unity GameObject) without the side's duplicate suffix (".001",
" (1)"); "group" is its folder path below the scope root, "/"-separated (Blender collections, Unity parent
GameObjects that are not placements; "" = directly under the root), not tracked where the side does not track it (a
Unity placement parented under another placement is dumped with "nested": true). Every side cleans them the same way ("/" in a name becomes "-",
ends trimmed). They merge three-way like the pose, each field on its own, so a rename on one side and a move on the
other is no conflict. A snapshot without them counts as label = the asset name and group = "", so after an upgrade
the side that renamed or organised wins. A dump without them (an older applier) leaves them as they are. Names are cut
to 255 UTF-8 bytes (Blender's limit). A dump's "folders" lists every folder path under the root (Blender
collections; Unity GameObjects that are not placements and not inside one): when every placement under a folder the
other side still has moved to one new path the other side lacks, and the old folder is gone on this side, it was
renamed or moved whole, and the other side renames that folder (taking its lights and other contents along) instead
of moving each placement.
Plans: "assign" [{"key", "id", "was", "asset"}] (an applier skips an assign whose object no longer has id `was` and
asset `asset`), "folders" [{"from", "to"}] (rename or move that folder first; when it is missing or "to" exists,
move the placements under it instead), "delete" [id], "update" and "create" [item with the id, label and group].
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
DELETE_SHARE = 0.2   # merge refuses plans that delete more than this share of the snapshot ...
DELETE_MIN = 3       # ... and more than this many placements, unless --allow-deletes
RENAME_SHARE = 0.2   # likewise for renames and folder moves (a folder renamed whole counts once) ...
RENAME_MIN = 10      # ... unless --allow-renames
NAME_BYTES = 255     # Blender's longest data-block name (measured in 5.2.2: 255 bytes)
SIDES = ("blender", "unity")


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


def clean(name):
    """A name as every side compares it: "/" (Unity's path separator) becomes "-", ends trimmed, cut to 255 UTF-8
    bytes without splitting a character."""
    name = str(name).replace("/", "-").strip()
    return name.encode("utf-8")[:NAME_BYTES].decode("utf-8", "ignore").strip()


def clean_group(group):
    return "/".join(c for c in (clean(part) for part in str(group).split("/")) if c)


def meta(item, field):
    """The item's cleaned label or group, or None when its side does not track it."""
    v = item.get(field)
    if v is None or (field == "group" and item.get("nested")):
        return None
    if field == "label":
        return clean(v) or None
    return clean_group(v)


def base_meta(item, field):
    """A snapshot's label or group; a snapshot from before names synced counts as the defaults."""
    v = meta(item, field)
    if v is not None:
        return v
    return clean(item["asset"]) if field == "label" else ""


META = (("label", "renamed"), ("group", "moved to folder"))


def meta_differences(cur, want):
    """Label and group differences of `cur` from `want`, skipping fields either does not track."""
    out = []
    for field, what in META:
        a, b = meta(cur, field), meta(want, field)
        if a is not None and b is not None and a != b:
            out.append("%s %r -> %r" % (what, a, b))
    return out


def all_differences(cur, want):
    return differences(cur, want) + meta_differences(cur, want)


def changes(cur, b):
    """What changed on one side since the snapshot `b` (its label and group compared with the snapshot's defaults)."""
    out = differences(cur, b)
    for field, what in META:
        v = meta(cur, field)
        if v is not None and v != base_meta(b, field):
            out.append("%s %r -> %r" % (what, base_meta(b, field), v))
    return out


def merge_fields(l, u, b):
    """Three-way merge of a placement both sides hold, field by field: the pose (asset, position, rotation, scale),
    the label and the group. Returns (merged state, clashes); a clash is (field, blender's change, unity's change)."""
    lp, up = differences(l, b), differences(u, b)
    clash = []
    if lp and up and differences(l, u):
        clash.append(("pose", "; ".join(lp), "; ".join(up)))
    merged = {k: (l if lp else (u if up else b))[k] for k in ("asset", "pos", "rot", "scl")}
    for field in ("label", "group"):
        bv, lv, uv = base_meta(b, field), meta(l, field), meta(u, field)
        lch, uch = lv is not None and lv != bv, uv is not None and uv != bv
        if lch and uch and lv != uv:
            clash.append((field, "%r" % lv, "%r" % uv))
        merged[field] = lv if lch else (uv if uch else bv)
    return merged, clash


def clash_text(clash):
    return "; ".join("%s: blender %s, unity %s" % c for c in clash)


def _state(item):
    out = {k: item[k] for k in ("asset", "pos", "rot", "scl")}
    for field, _what in META:
        v = meta(item, field)
        if v is not None:
            out[field] = v
    return out


def label(it):
    """How a report names an object: Unity's hierarchy path when the dump has one, else its key."""
    return it.get("name") or str(it.get("key", "?"))


def _source(bdump, udump):
    """What identifies a scope's two ends: the Blender file name and collection, and the Unity target."""
    f = (bdump.get("file") or "").replace("\\", "/")
    return {"blender_file": os.path.basename(f).lower() or None,
            "blender_collection": bdump.get("collection") or None,
            "unity_target": udump.get("target") or None}


def reconcile(bitems, uitems, base, plans, notes):
    """Before fresh ids are issued: an id-less placement takes back an id missing on its own side (in the snapshot, or
    new on the other side) when it is the same asset at the same pose, and id-less placements that match each other
    across the two sides become one placement. Edits the items in place and records the assigns."""
    items = {"blender": bitems, "unity": uitems}
    present = {side: {i["id"] for i in items[side] if i.get("id")} for side in SIDES}
    for side, other in (("blender", "unity"), ("unity", "blender")):
        refs = {pid: ref for pid, ref in base.items() if pid not in present[side]}
        for it in items[other]:
            pid = it.get("id")
            if pid and pid not in base and pid not in present[side]:
                refs.setdefault(pid, it)
        for it in sorted((i for i in items[side] if not i.get("id")), key=lambda i: str(i.get("key"))):
            for pid in sorted(refs):
                if pid in present[side] or refs[pid]["asset"] != it["asset"] or differences(it, refs[pid]):
                    continue
                present[side].add(pid)
                it["id"] = pid
                plans[side]["assign"].append({"key": it["key"], "id": pid, "was": "", "asset": it["asset"]})
                notes.append("%s: %s had no id; same piece and pose as %s, so it takes that id back"
                             % (side, label(it), pid))
                break
    used = set(base) | present["blender"] | present["unity"]
    for b in sorted((i for i in bitems if not i.get("id")), key=lambda i: str(i.get("key"))):
        for u in uitems:
            if u.get("id") or u["asset"] != b["asset"] or differences(b, u):
                continue
            nid = new_id()
            while nid in used:
                nid = new_id()
            used.add(nid)
            b["id"] = u["id"] = nid
            for side, it in (("blender", b), ("unity", u)):
                plans[side]["assign"].append({"key": it["key"], "id": nid, "was": "", "asset": it["asset"]})
            notes.append("%s (blender) and %s (unity) had no id and match each other: one placement %s"
                         % (label(b), label(u), nid))
            break


def same_pose_copies(items, side):
    """Warnings for placements of one asset at one pose: each syncs as its own placement, which is right for a copy
    made on purpose and wrong for Unity-only copies such as lighting-state duplicates (those belong under a root
    outside the scope, e.g. LIGHT_STATES)."""
    groups = {}
    for it in items:
        groups.setdefault((it["asset"],) + tuple(round(v, 3) for v in it["pos"]), []).append(it)
    out = []
    for group in groups.values():
        same = [it for it in group if not differences(it, group[0])]
        if len(same) > 1:
            out.append("%s: %d placements of %s at the same pose (%s): each syncs as its own placement. Unity-only "
                       "copies (lighting states) belong under a root outside the scope, such as LIGHT_STATES"
                       % (side, len(same), group[0]["asset"], ", ".join(label(it) for it in same)))
    return out


def resolve_ids(items, base, side, assigns, reserved):
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
                                           str(it["key"])))
            else:
                group.sort(key=lambda it: str(it["key"]))
            out[pid] = group[0]
            rest = group[1:]
            if rest:
                notes.append("%s: id %s on %d objects; kept on %s, re-issued for %s"
                             % (side, pid, len(group), label(group[0]), ", ".join(label(it) for it in rest)))
        else:
            rest = group
        for it in rest:
            nid = new_id()
            while nid in reserved or nid in out:
                nid = new_id()
            reserved.add(nid)
            assigns.append({"key": it["key"], "id": nid, "was": pid, "asset": it["asset"]})
            out[nid] = dict(it, id=nid)
    return out, notes


def _empty_plan(scope, side):
    return {"scope": scope, "side": side, "assign": [], "folders": [], "delete": [], "update": [], "create": []}


def _under(group, folder):
    return group == folder or group.startswith(folder + "/")


def folder_renames(items, base, sender, receiver):
    """[(from, to)]: folders the sending side renamed or moved whole. `items` is that side's id -> item; `sender` and
    `receiver` the folder paths each side's dump lists (None from an older applier: no detection). A folder counts
    when every snapshot placement under it is now under one new path, with the same path below it, and the old path
    is gone on the sender, the new one exists there and not on the receiver, which still has the old one."""
    if sender is None or receiver is None:
        return []
    sender, receiver = {clean_group(f) for f in sender}, {clean_group(f) for f in receiver}
    pairs = []
    for pid, it in items.items():
        b, new = base.get(pid), meta(it, "group")
        if b and not b.get("unity_only") and new is not None:
            pairs.append((base_meta(b, "group"), new))
    folders = {"/".join(old.split("/")[:n]) for old, _new in pairs if old for n in range(1, old.count("/") + 2)}
    out = []
    for f in sorted(folders, key=lambda x: (x.count("/"), x)):
        if any(_under(f, o) for o, _t in out) or f in sender or f not in receiver:
            continue
        targets = set()
        for old, new in pairs:
            if not _under(old, f):
                continue
            rest = old[len(f):]
            if not new.endswith(rest) or len(new) == len(rest):
                targets = None
                break
            targets.add(new[:len(new) - len(rest)])
        if not targets or len(targets) != 1:
            continue
        to = targets.pop()
        if to in sender and to not in receiver and not _under(to, f) and not _under(f, to):
            out.append((f, to))
    return out


def _moved(group, renames):
    for f, to in renames:
        if _under(group, f):
            return to + group[len(f):]
    return group


def merge(args):
    d, s = args.dir, args.scope
    path = lambda suffix: os.path.join(d, "%s.%s" % (s, suffix))
    bdump, udump = _read(path("blender.json")), _read(path("unity.json"))
    if bdump.get("side", "blender") != "blender" or udump.get("side", "unity") != "unity":
        print("bad input: %s.blender.json and %s.unity.json hold the other side's dump" % (s, s))
        return 1
    snap = _read(path("synced.json"), {"scope": s, "version": 1, "items": {}})
    base = snap["items"]
    take_all = args.take
    take_id = {}
    for t in args.take_id:
        pid, sep, side = t.partition("=")
        if not sep or not pid.strip() or side.strip().lower() not in SIDES:
            print("bad --take-id %r: use --take-id ID=blender or --take-id ID=unity" % t)
            return 1
        take_id[pid.strip()] = side.strip().lower()

    plans = {side: _empty_plan(s, side) for side in SIDES}
    notes = same_pose_copies(bdump["items"], "blender") + same_pose_copies(udump["items"], "unity")
    bitems = [dict(i) for i in bdump["items"]]
    uitems = [dict(i) for i in udump["items"]]
    reconcile(bitems, uitems, base, plans, notes)
    reserved = set(base) | {i["id"] for i in bitems + uitems if i.get("id")}
    L, notes_l = resolve_ids(bitems, base, "blender", plans["blender"]["assign"], reserved)
    U, notes_u = resolve_ids(uitems, base, "unity", plans["unity"]["assign"], reserved)
    notes += notes_l + notes_u
    blender_assets = set(bdump.get("assets") or []) | {i["asset"] for i in bdump["items"]}
    unity_assets = set(udump.get("assets") or []) | {i["asset"] for i in udump["items"]}

    # Folders renamed or moved whole on one side: the other side renames the folder, so the snapshot and that side's
    # items are read as already renamed, and the placements under it need no move of their own.
    base = {pid: dict(b) for pid, b in base.items()}
    folder_lines = []
    for sender, items, receiver, other, rdump, sdump in (("blender", L, "unity", U, udump, bdump),
                                                         ("unity", U, "blender", L, bdump, udump)):
        renames = folder_renames(items, base, sdump.get("folders"), rdump.get("folders"))
        for f, to in renames:
            plans[receiver]["folders"].append({"from": f, "to": to})
            folder_lines.append("  %-7s -> %-7s folder %r -> %r (renamed whole: its other contents go along)"
                                % (sender, receiver, f, to))
        if renames:
            for b in base.values():
                if meta(b, "group") is not None:
                    b["group"] = _moved(b["group"], renames)
            for it in other.values():
                if meta(it, "group") is not None:
                    it["group"] = _moved(meta(it, "group"), renames)

    state, skip, unity_only, conflicts, blocked, lines, deletes = {}, [], [], [], [], [], []
    lines += folder_lines
    renamed = [None] * len(folder_lines)       # one per folder renamed whole, then one per placement renamed or moved
    counts = {"unchanged": 0}

    def push(side, kind, pid, item, current=None):
        plans[side][kind].append(dict(_state(item), id=pid, key=item.get("key", "")))
        if current and meta_differences(current, item):
            renamed.append(pid)
        src = "unity" if side == "blender" else "blender"
        what = "; ".join(all_differences(current, item)) if current else ""
        lines.append("  %-7s -> %-7s %-6s %s %s%s" % (src, side, kind, pid, item["asset"],
                                                      " (%s)" % what if what else ""))

    # Where each old asset's placements went, per receiving side: {"unity": {old: {new: count}}, "blender": ...}.
    # One new name the receiving side lacks is a rename; several are a split, which no single rename can finish.
    spread = {"unity": {}, "blender": {}}
    for pid, b in base.items():
        l, u = L.get(pid), U.get(pid)
        if l and u and l["asset"] != u["asset"]:
            for side, new_item, same in (("unity", l, u), ("blender", u, l)):
                if new_item["asset"] != b["asset"] and same["asset"] == b["asset"]:
                    counts_ = spread[side].setdefault(b["asset"], {})
                    counts_[new_item["asset"]] = counts_.get(new_item["asset"], 0) + 1

    def blocked_why(side, item, current):
        """Why `side` cannot take `item`, and what to do. A rename is told from a swap by the old asset: after a
        rename the sending side no longer has it; after a swap of some placements it still does. Only targets the
        receiving side lacks count: when the old asset's placements went to several of those, no rename is suggested.
        An assembly (ASM_) is never exported or added as a KIT piece: it has its own sync scope (its collection
        under ASM in a single MASTER, or its ASM file when split)."""
        name = item["asset"]
        sender, sender_has = ("Blender", blender_assets) if side == "unity" else ("Unity", unity_assets)
        receiver_has = unity_assets if side == "unity" else blender_assets
        lacking = lambda went: {k: v for k, v in went.items() if k not in receiver_has}
        old = current["asset"] if current and current["asset"] != name else None
        if old is None:                                     # a new placement of a piece renamed on the sending side
            old = next((was for was, went in sorted(spread[side].items())
                        if was not in sender_has and name in lacking(went) and len(lacking(went)) == 1), None)
        asm = name.startswith("ASM_")
        if old and old not in sender_has:
            went = lacking(spread[side].get(old, {}))
            if len(went) > 1:                               # renamed and split on the other side
                return ("%s has no %s called %s: %s no longer has %s, and its placements now use several pieces %s "
                        "lacks (%s), so this is not a plain rename. With the user, rename %s to one of them and add "
                        "the others as new pieces" % (side.capitalize(), "prefab" if side == "unity" else "collection",
                                                      name, sender, old, side.capitalize(),
                                                      ", ".join("%s x%d" % kv for kv in sorted(went.items())), old))
            if side == "unity":                             # renamed in Blender only
                how = ("renaming the assembly prefab to %s (it has no FBX), then syncing the assembly under its new "
                       "scope name (references/merge-rules.md, Renaming an assembly)" % name
                       if asm else "renaming the prefab and its FBX to %s" % name)
                return ("Unity has no prefab called %s (it has %s, which Blender no longer has): finish (or undo) the "
                        "rename on the Unity side, %s" % (name, old, how))
            how = ("renaming its collection (and, with split files, its ASM file, re-pointing its instances; "
                   "blender-kit-library, Naming)" if asm else "renaming its collection (with split files, in its KIT "
                   "file, then re-pointing its instances)")
            return ("Blender has no collection called %s (it has %s, which Unity no longer has): finish (or undo) the "
                    "rename on the Blender side, %s" % (name, old, how))
        if side == "unity":
            if old and asm:                                 # swapped in Blender to an assembly Unity lacks
                return ("no Unity prefab called %s: a placement was swapped from %s to an assembly whose scope has not "
                        "synced, so sync %s's own scope first; never rename %s, which Blender still has"
                        % (name, old, name, old))
            if old:                                         # swapped in Blender to a piece Unity lacks
                return ("no Unity prefab called %s: a placement was swapped from %s to a piece Unity lacks, so export "
                        "and package %s; never rename %s, which Blender still has" % (name, old, name, old))
            if asm:
                return "no Unity prefab called %s yet: sync that assembly's own ASM scope first" % name
            return "no Unity prefab called %s yet: a new piece, so export and package it" % name
        if old and asm:                                     # swapped in Unity to an assembly Blender lacks
            return ("no Blender collection called %s: a placement was swapped in Unity from %s to an assembly Blender "
                    "lacks, so build it (under ASM in MASTER, or in blender/asm/%s.blend with split files) and sync "
                    "its scope, or undo the swap in Unity; never rename %s, which Unity still has"
                    % (name, old, name, old))
        if old:                                             # swapped in Unity to a prefab Blender lacks
            return ("no Blender collection called %s: a placement was swapped in Unity from %s to a prefab Blender "
                    "lacks, so add %s as a KIT piece or undo the swap in Unity; never rename %s, which Unity still has"
                    % (name, old, name, old))
        if asm:
            return ("no Blender collection called %s: build it under ASM in MASTER (split files: in "
                    "blender/asm/%s.blend, and dump with --libraries naming that file)" % (name, name))
        return ("no Blender collection called %s: add it as a piece under KIT in MASTER (split files: to a KIT file, "
                "and dump with --libraries naming that file)" % name)

    def send(side, kind, pid, item, current=None):
        """Plan `kind` of `pid` on `side`; `item` is the new state (for a delete: the state being deleted) and
        `current` what `side` has now, if anything."""
        src = "unity" if side == "blender" else "blender"
        if kind == "delete":
            plans[side]["delete"].append(pid)
            deletes.append(pid)
            lines.append("  %-7s -> %-7s delete %s %s" % (src, side, pid, item["asset"] if item else ""))
            return
        have = unity_assets if side == "unity" else blender_assets
        if item["asset"] not in have:
            blocked.append(pid)
            skip.append(pid)
            lines.append("  BLOCKED %s %s -> %s: %s" % (kind, pid, side, blocked_why(side, item, current)))
            return
        push(side, kind, pid, item, current)
        state[pid] = _state(item)

    def settle(pid, merged, l, u):
        """Bring both sides to `merged`: a side that differs gets an update. When a side cannot take the asset,
        neither side is sent anything and the placement stays at its synced state until the next merge."""
        needs = [(side, cur) for side, cur in (("blender", l), ("unity", u)) if all_differences(cur, merged)]
        if not needs:
            state[pid] = _state(merged)
            counts["unchanged"] += 1
            return
        for side, cur in needs:
            if merged["asset"] not in (unity_assets if side == "unity" else blender_assets):
                blocked.append(pid)
                skip.append(pid)
                lines.append("  BLOCKED update %s -> %s: %s" % (pid, side, blocked_why(side, merged, cur)))
                return
        for side, cur in needs:
            push(side, "update", pid, merged, cur)
        state[pid] = _state(merged)

    for pid in sorted(set(base) | set(L) | set(U)):
        b, l, u = base.get(pid), L.get(pid), U.get(pid)
        if b and b.get("unity_only") and l is None:
            if u and u["asset"] in blender_assets:
                lines.append("  unity-only %s %s: Blender has that collection now" % (pid, u["asset"]))
                send("blender", "create", pid, u)
            elif u:
                state[pid] = dict(_state(u), unity_only=True)
                unity_only.append(pid)
            continue
        if not b:
            if l and u:
                diff = differences(l, u)
                merged, clash = merge_fields(l, u, {k: l[k] for k in ("asset", "pos", "rot", "scl")})
                if diff:
                    conflicts.append((pid, "added on both sides, different: " + "; ".join(diff), l, u, None, None))
                elif clash:
                    conflicts.append((pid, "added on both sides, different: " + clash_text(clash), l, u, None,
                                      (merged, clash)))
                else:
                    settle(pid, merged, l, u)
            elif l:
                send("unity", "create", pid, l)
            elif u["asset"] in blender_assets:
                send("blender", "create", pid, u)
            else:
                state[pid] = dict(_state(u), unity_only=True)
                unity_only.append(pid)
                lines.append("  unity-only %s %s (no such collection in Blender; left to Unity until it has one)"
                             % (pid, u["asset"]))
            continue
        if l and u:
            merged, clash = merge_fields(l, u, b)
            if clash:
                conflicts.append((pid, clash_text(clash), l, u, b, (merged, clash)))
            else:
                settle(pid, merged, l, u)
            continue
        lc = "gone" if not l else ("changed" if changes(l, b) else "same")
        uc = "gone" if not u else ("changed" if changes(u, b) else "same")
        if lc == uc == "gone":
            lines.append("  deleted on both sides %s %s" % (pid, b["asset"]))
        elif lc == "gone" and uc == "same":
            send("unity", "delete", pid, b)
        elif lc == "same" and uc == "gone":
            send("blender", "delete", pid, b)
        else:
            what = {"gone": "deleted", "changed": "changed"}
            why = "blender %s (%s), unity %s (%s)" % (
                what[lc], "; ".join(changes(l, b)) if l else "-",
                what[uc], "; ".join(changes(u, b)) if u else "-")
            conflicts.append((pid, why, l, u, b, None))

    unresolved = []
    for pid, why, l, u, b, partial in conflicts:
        winner = take_id.get(pid, take_all)
        if winner and partial:
            # Both sides hold it: the winner's values for the clashing fields, the merged values for the rest.
            merged, clash = dict(partial[0]), partial[1]
            src = l if winner == "blender" else u
            for field, _a, _b in clash:
                if field == "pose":
                    merged.update({k: src[k] for k in ("asset", "pos", "rot", "scl")})
                else:
                    merged[field] = meta(src, field)
            lines.append("  conflict %s resolved: %s wins (%s)" % (pid, winner, why))
            settle(pid, merged, l, u)
        elif winner == "blender":
            lines.append("  conflict %s resolved: blender wins (%s)" % (pid, why))
            if l is None:
                send("unity", "delete", pid, u)
            else:
                send("unity", "update" if u else "create", pid, l, u)
        elif winner == "unity":
            lines.append("  conflict %s resolved: unity wins (%s)" % (pid, why))
            if u is None:
                send("blender", "delete", pid, l)
            else:
                send("blender", "update" if l else "create", pid, u, l)
        else:
            unresolved.append({"id": pid, "why": why,
                               "blender": l and _state(l), "unity": u and _state(u), "synced": b and _state(b)})
            skip.append(pid)
    for pid in sorted(set(take_id) - {c[0] for c in conflicts}):
        notes.append("--take-id %s ignored: not a conflict in this merge" % pid)

    head = ["placement sync %s: %d blender, %d unity, %d in snapshot" % (s, len(L), len(U), len(base))]
    head += ["blender dump: " + w for w in bdump.get("warnings") or []]
    if udump.get("note"):
        head.append("unity dump: " + udump["note"])

    source = _source(bdump, udump)
    refusal = []
    if not args.allow_deletes:
        synced_b = [p for p in base if not base[p].get("unity_only")]
        if base and not U:
            refusal.append("the Unity dump has no placements, the snapshot has %d" % len(base))
        if synced_b and not L:
            refusal.append("the Blender dump has no placements, the snapshot has %d" % len(synced_b))
        limit = max(DELETE_MIN, int(math.ceil(DELETE_SHARE * len(base))))
        if len(deletes) > limit:
            refusal.append("the plans delete %d placements; the budget is %d (%d%% of %d synced, at least %d)"
                           % (len(deletes), limit, round(DELETE_SHARE * 100), len(base), DELETE_MIN))
    if not getattr(args, "allow_renames", False):
        limit = max(RENAME_MIN, int(math.ceil(RENAME_SHARE * len(base))))
        if len(renamed) > limit:
            refusal.append("the plans rename or move to another folder %d placements and folders; the budget is %d "
                           "(%d%% of %d synced, at least %d)"
                           % (len(renamed), limit, round(RENAME_SHARE * 100), len(base), RENAME_MIN))
    if not args.accept_source:
        for k, was in sorted((snap.get("source") or {}).items()):
            now = source.get(k)
            if was and now and was != now:
                refusal.append("%s is %s, but this scope was synced with %s" % (k, now, was))
    if refusal:
        for side in SIDES:
            _write(path("plan.%s.json" % side), _empty_plan(s, side))
        _write(path("pending.json"), {"scope": s, "refused": "; ".join(refusal), "state": {}, "skip": [],
                                      "base_kept": {}})
        report = ["placement sync %s: REFUSED, empty plans written, nothing to apply" % s]
        report += ["  REFUSED " + r for r in refusal]
        report += head[1:] + notes
        report.append("what the merge would have done:")
        report += lines + ["  CONFLICT %s: %s" % (c[0], c[1]) for c in conflicts if c[0] in skip]
        report.append("Check the dumps first: the right .blend file and collection, the right Unity scene or prefab, "
                      "the prefab roots (PlacementSync.json, PrefabRootsOverride). Only when the user confirms the "
                      "deletions are real, re-run with --allow-deletes; the renames (the first sync after names began "
                      "to sync renames many), --allow-renames; when the scope really moved, --accept-source.")
        _report(path("report.txt"), report, [])
        return 4

    for side in SIDES:
        _write(path("plan.%s.json" % side), plans[side])
    _write(path("pending.json"), {"scope": s, "state": state, "skip": skip,
                                  "base_kept": {p: base[p] for p in skip if p in base}})

    report = head + notes
    for side in SIDES:
        p = plans[side]
        report.append("%s plan: %d assign, %d folder, %d create, %d update, %d delete"
                      % (side, len(p["assign"]), len(p["folders"]), len(p["create"]), len(p["update"]),
                         len(p["delete"])))
    report.append("unchanged %d, unity-only %d, blocked %d, unresolved conflicts %d"
                  % (counts["unchanged"], len(unity_only), len(blocked), len(unresolved)))
    report += lines
    for c in unresolved:
        report.append("  CONFLICT %s: %s   (re-run with --take-id %s=blender or =unity)" % (c["id"], c["why"],
                                                                                         c["id"]))
    _report(path("report.txt"), report, unresolved)
    return 2 if unresolved else (3 if blocked else 0)


def _report(path, report, unresolved):
    text = "\n".join(report)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text + "\n")
        if unresolved:
            f.write(json.dumps(unresolved, indent=2) + "\n")
    print(text)


def commit(args):
    d, s = args.dir, args.scope
    path = lambda suffix: os.path.join(d, "%s.%s" % (s, suffix))
    pending = _read(path("pending.json"))
    if pending.get("refused"):
        print("commit refused: the last merge was refused (%s). Fix the dumps and merge again." % pending["refused"])
        return 2
    bdump, udump = _read(path("blender.json")), _read(path("unity.json"))
    bad = []
    sides = {}
    for name, dump in (("blender", bdump), ("unity", udump)):
        sides[name] = {}
        for i in dump["items"]:
            pid = i.get("id")
            if not pid:
                continue
            if pid in sides[name]:
                bad.append("%s is on more than one object in %s (duplicated since the merge): merge again" % (pid, name))
            sides[name][pid] = i
    L, U = sides["blender"], sides["unity"]
    state, skip = pending["state"], set(pending["skip"])
    for pid, want in state.items():
        check = (("unity", U),) if want.get("unity_only") else (("blender", L), ("unity", U))
        for name, side in check:
            have = side.get(pid)
            if have is None:
                bad.append("%s missing in %s" % (pid, name))
            elif all_differences(have, want):
                bad.append("%s in %s: %s" % (pid, name, "; ".join(all_differences(have, want))))
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
    _write(snap_path, {"scope": s, "version": 1, "source": _source(bdump, udump), "items": items})
    print("committed %s: %d placements in snapshot (%d left at their previous synced state)"
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
    m.add_argument("--take", choices=SIDES, help="resolve every conflict this way")
    m.add_argument("--take-id", action="append", default=[], metavar="ID=SIDE", help="resolve one conflict")
    m.add_argument("--allow-deletes", action="store_true",
                   help="the deletions are real: skip the deletion budget and the empty-side check")
    m.add_argument("--allow-renames", action="store_true",
                   help="the renames and folder moves are real: skip the rename budget")
    m.add_argument("--accept-source", action="store_true",
                   help="this scope's Blender file, collection or Unity target really changed")
    args = ap.parse_args()
    sys.exit(merge(args) if args.cmd == "merge" else commit(args))


if __name__ == "__main__":
    main()
