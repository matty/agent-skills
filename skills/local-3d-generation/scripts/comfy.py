#!/usr/bin/env python3
"""ComfyUI client for agents: convert UI workflows to API prompts, check and fetch
models, run a prompt and download what it saves.

Host: plain Python 3.10+, standard library only. Talks to a running ComfyUI server
over HTTP (default http://127.0.0.1:8188). Does not import anything from ComfyUI.

Commands
  status                         server version, GPU, VRAM free
  launch-cmd                     print the command that starts a Comfy Desktop install headless
  templates [WORD ...]           list the server's workflow templates (name, size, title)
  convert UI -o API.json         UI workflow -> API prompt; UI is a file or tpl:TEMPLATE_NAME
  models UI [--download]         models a workflow names: present on the server or not; fetch missing
  nodes API.json                 list node ids, class, title and widget inputs (--set targets)
  fetch PROMPT_ID [--out DIR]    download the saved files of a finished (or running) prompt
  run API.json [--set TARGET.input=VALUE ...] [--upload FILE ...] [--out DIR]
                                 queue, wait, download every output file; prints JSON summary.
                                 TARGET is a node id, or a class_type or title naming one node.

Conversion uses the server's /object_info for input order, so the server must be
running and must have every node the workflow uses. It flattens subgraphs, drops
notes, resolves Reroute and legacy PrimitiveNode, drops muted nodes and routes
bypassed ones through. The server validates the result when it is queued; a
validation error names the node and input to fix.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

DEFAULT_SERVER = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")

# Input types the frontend draws as widgets (their values live in widgets_values).
WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO", "COLOR", "LOAD_3D",
                "COMFY_DYNAMICCOMBO_V3"}
CONTROL_VALUES = {"fixed", "increment", "decrement", "randomize"}
UPLOAD_FLAGS = ("image_upload", "video_upload", "audio_upload", "file_upload", "upload")
UI_ONLY = {"MarkdownNote", "Note", "Reroute", "PrimitiveNode", "Label (rgthree)"}


# ---------------------------------------------------------------- HTTP

def _req(server: str, path: str, data: bytes | None = None, headers: dict | None = None,
         timeout: float = 60):
    req = urllib.request.Request(server.rstrip("/") + path, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def get_json(server: str, path: str, timeout: float = 60):
    return json.loads(_req(server, path, timeout=timeout))


def post_json(server: str, path: str, body: dict):
    data = json.dumps(body).encode()
    try:
        return json.loads(_req(server, path, data, {"Content-Type": "application/json"}))
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise SystemExit(f"HTTP {e.code} from {path}:\n{_pretty_error(detail)}")


def _pretty_error(detail: str) -> str:
    try:
        d = json.loads(detail)
    except json.JSONDecodeError:
        return detail
    lines = []
    err = d.get("error")
    if isinstance(err, dict):
        lines.append(f"{err.get('type')}: {err.get('message')} {err.get('details', '')}")
    for nid, ne in (d.get("node_errors") or {}).items():
        for e in ne.get("errors", []):
            lines.append(f"  node {nid} ({ne.get('class_type')}): {e.get('message')} - "
                         f"{e.get('details')}")
    return "\n".join(lines) or detail


def upload_file(server: str, path: Path, overwrite: bool = True) -> str:
    boundary = uuid.uuid4().hex
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; "
        f"filename=\"{path.name}\"\r\nContent-Type: {ctype}\r\n\r\n".encode(),
        path.read_bytes(),
        f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\n"
        f"{'true' if overwrite else 'false'}\r\n--{boundary}--\r\n".encode(),
    ]
    res = json.loads(_req(server, "/upload/image", b"".join(parts),
                          {"Content-Type": f"multipart/form-data; boundary={boundary}"}))
    name = res["name"]
    return f"{res['subfolder']}/{name}" if res.get("subfolder") else name


def load_ui(server: str, ref: str) -> dict:
    """A UI workflow from a file, or tpl:NAME from the server's bundled templates."""
    if ref.startswith("tpl:"):
        return get_json(server, f"/templates/{urllib.parse.quote(ref[4:])}.json")
    return json.loads(Path(ref).read_text(encoding="utf-8"))


def set_input(prompt: dict, nid: str, inp: str, value, info: dict | None) -> list[str]:
    """Set one input. Switching a dynamic combo (RemeshMesh.sign_mode=solid) also swaps its
    child inputs: the old option's 'name.child' keys go, the new option's defaults come in
    (set a child after its combo: --set X.sign_mode=solid --set X.sign_mode.fill=10)."""
    inputs = prompt[nid]["inputs"]
    inputs[inp] = value
    if not info:
        return []
    spec = dict(_input_order(info.get(prompt[nid]["class_type"], {}))).get(inp)
    if not spec or spec[0] != "COMFY_DYNAMICCOMBO_V3":
        return []
    opts = spec[1] if len(spec) > 1 else {}
    chosen = next((o for o in opts.get("options", []) if o.get("key") == value), None)
    if chosen is None:
        raise SystemExit(f"{inp}={value!r}: options are "
                         f"{[o.get('key') for o in opts.get('options', [])]}")
    for k in [k for k in inputs if k.startswith(inp + ".")]:
        del inputs[k]
    notes = []
    for name, sub in _input_order({"input": chosen.get("inputs", {})}):
        key = f"{inp}.{name}"
        if len(sub) > 1 and isinstance(sub[1], dict) and "default" in sub[1]:
            inputs[key] = sub[1]["default"]
            notes.append(f"{key} = default {sub[1]['default']!r}")
    return notes


def find_node(prompt: dict, target: str) -> str:
    if target in prompt:
        return target
    hits = [nid for nid, e in prompt.items()
            if e["class_type"] == target or (e.get("_meta") or {}).get("title") == target]
    if len(hits) != 1:
        raise SystemExit(f"--set target {target!r} matches {len(hits)} nodes "
                         f"({', '.join(hits[:6])}); use a node id from `nodes`")
    return hits[0]


# ---------------------------------------------------------------- conversion

def _input_order(spec: dict) -> list[tuple[str, list]]:
    """(name, spec) in the order the frontend creates widgets."""
    out = []
    order = spec.get("input_order") or {}
    for section in ("required", "optional"):
        group = spec.get("input", {}).get(section, {}) or {}
        names = order.get(section) or list(group)
        out += [(n, group[n]) for n in names if n in group]
    return out


def _is_widget(ispec: list) -> bool:
    t = ispec[0]
    opts = ispec[1] if len(ispec) > 1 and isinstance(ispec[1], dict) else {}
    if opts.get("forceInput"):
        return False
    if isinstance(t, list):          # legacy combo: list of choices
        return True
    if t in WIDGET_TYPES:
        return True
    # custom widgets (BOUNDING_BOX, CURVE, COLORS, ...): drawn in the node, so socketless or given a default;
    # plain sockets (MODEL, IMAGE, MESH) never carry a default
    return bool(opts.get("socketless")) or ("default" in opts and t != "*")


def _consume(name: str, ispec: list, vals: list, out: dict, warn: list, prefix: str = ""):
    t = ispec[0]
    opts = ispec[1] if len(ispec) > 1 and isinstance(ispec[1], dict) else {}
    if not vals:
        # the workflow was saved before this input existed: use the server's default
        if "default" in opts:
            v = opts["default"]
        elif isinstance(t, list) and t:
            v = t[0]
        elif opts.get("options"):
            o = opts["options"][0]
            v = o.get("key", o) if isinstance(o, dict) else o
        else:
            warn.append(f"no widget value and no default for {prefix}{name}")
            return
        warn.append(f"{prefix}{name} not saved in the workflow; using default {v!r}")
        vals.append(v)
    v = vals.pop(0)
    out[prefix + name] = v
    if t == "COMFY_DYNAMICCOMBO_V3":
        chosen = next((o for o in opts.get("options", []) if o.get("key") == v), None)
        if chosen is None:
            warn.append(f"{prefix}{name}: option {v!r} not offered by this server")
            return
        for sub_name, sub_spec in _input_order({"input": chosen.get("inputs", {})}):
            if _is_widget(sub_spec):
                _consume(sub_name, sub_spec, vals, out, warn, prefix + name + ".")
        return
    if opts.get("control_after_generate") and vals and vals[0] in CONTROL_VALUES:
        vals.pop(0)
    if any(opts.get(f) for f in UPLOAD_FLAGS) and vals and isinstance(vals[0], str) \
            and vals[0] in ("image", "video", "audio", "file", "upload"):
        vals.pop(0)


def _widget_inputs(cls: str, node: dict, info: dict, warn: list) -> dict:
    spec = info[cls]
    wv = node.get("widgets_values")
    out: dict = {}
    if isinstance(wv, dict):      # some nodes save widgets by name
        for name, ispec in _input_order(spec):
            if name in wv and _is_widget(ispec):
                out[name] = wv[name]
        return out
    vals = list(wv or [])
    for name, ispec in _input_order(spec):
        if _is_widget(ispec):
            _consume(name, ispec, vals, out, warn)
    components = [n for n, sp in _input_order(spec)
                  if len(sp) > 1 and isinstance(sp[1], dict) and sp[1].get("component")]
    if vals and components:
        pass        # a component widget (ImageCrop's box) saves its own x/y/width/height boxes after its value
    elif vals:
        warn.append(f"{len(vals)} widget value(s) left over: {vals!r}")
    return out


def _flatten(graph: dict, subgraphs: dict, prefix: str = ""):
    """Yield (nodes, links) with subgraph instances expanded.

    nodes: {id: node}; links: {link_id: (src_id, src_slot, dst_id, dst_slot)}.
    Ids inside a subgraph become 'outer:inner', as ComfyUI does.
    """
    nodes: dict[str, dict] = {}
    links: dict[str, tuple] = {}

    def lid(x):
        return f"{prefix}{x}"

    for l in graph.get("links", []):
        if isinstance(l, dict):
            l = [l["id"], l["origin_id"], l["origin_slot"], l["target_id"], l["target_slot"]]
        links[lid(l[0])] = (lid(l[1]), l[2], lid(l[3]), l[4])
    for n in graph.get("nodes", []):
        nodes[lid(n["id"])] = n

    for nid, n in list(nodes.items()):
        sg = subgraphs.get(n["type"])
        if not sg:
            continue
        inner_prefix = nid + ":"
        inner_nodes, inner_links = _flatten(sg, subgraphs, inner_prefix)
        del nodes[nid]
        # wire subgraph inputs (-10) to whatever feeds the instance's input slots
        feed = {}
        for l_id, (s, ss, d, ds) in links.items():
            if d == nid:
                feed[ds] = (s, ss)
        sub_in = {i: inp for i, inp in enumerate(sg.get("inputs", []))}
        for l_id, (s, ss, d, ds) in list(inner_links.items()):
            if s == f"{inner_prefix}-10":
                inst_slot = _instance_slot(n, sub_in.get(ss, {}).get("name"))
                if inst_slot is not None and inst_slot in feed:
                    inner_links[l_id] = (*feed[inst_slot], d, ds)
                else:
                    del inner_links[l_id]   # unlinked: inner widget value stands
        # wire subgraph outputs (-20) to the instance's consumers
        out_src = {ds: (s, ss) for (s, ss, d, ds) in inner_links.values()
                   if d == f"{inner_prefix}-20"}
        inner_links = {k: v for k, v in inner_links.items() if v[2] != f"{inner_prefix}-20"}
        for l_id, (s, ss, d, ds) in list(links.items()):
            if d == nid:
                del links[l_id]
            elif s == nid and ss in out_src:
                links[l_id] = (*out_src[ss], d, ds)
        nodes.update(inner_nodes)
        links.update(inner_links)
    return nodes, links


def _instance_slot(node: dict, name: str | None):
    for i, inp in enumerate(node.get("inputs", [])):
        if inp.get("name") == name:
            return i
    return None


def convert(ui: dict, info: dict) -> tuple[dict, list[str]]:
    subgraphs = {sg["id"]: sg for sg in (ui.get("definitions") or {}).get("subgraphs", [])}
    nodes, links = _flatten(ui, subgraphs)
    warnings: list[str] = []

    # incoming[(dst, slot_name)] = (src, slot) after resolving reroutes / bypass
    by_dst: dict[tuple, tuple] = {}
    for s, ss, d, ds in links.values():
        by_dst[(d, ds)] = (s, ss)

    def resolve(src, slot, seen=()):
        n = nodes.get(src)
        if n is None or src in seen:
            return None
        if n["type"] == "Reroute":
            up = by_dst.get((src, 0))
            return resolve(*up, seen + (src,)) if up else None
        if n["type"] == "PrimitiveNode":
            wv = n.get("widgets_values") or []
            return ("value", wv[0] if wv else None)
        if n.get("mode") == 4:       # bypassed: pass the first input of matching type
            out_type = (n.get("outputs") or [{}])[slot].get("type") \
                if slot < len(n.get("outputs") or []) else None
            for i, inp in enumerate(n.get("inputs", [])):
                if inp.get("type") == out_type and (src, i) in by_dst:
                    return resolve(*by_dst[(src, i)], seen + (src,))
            return None
        if n.get("mode") == 2:
            return None
        return (src, slot)

    prompt: dict = {}
    for nid, n in nodes.items():
        cls = n["type"]
        if cls in UI_ONLY or n.get("mode") in (2, 4):
            continue
        if cls not in info:
            warnings.append(f"node {nid}: class {cls} is not on this server (custom node "
                            f"missing?) - skipped")
            continue
        w: list[str] = []
        inputs = _widget_inputs(cls, n, info, w)
        for i, inp in enumerate(n.get("inputs", [])):
            if (nid, i) not in by_dst:
                continue
            r = resolve(*by_dst[(nid, i)])
            name = inp.get("name")
            if r is None:
                continue
            if r[0] == "value":
                inputs[name] = r[1]
            else:
                inputs[name] = [r[0], r[1]]
        warnings += [f"node {nid} ({cls}): {m}" for m in w]
        entry = {"class_type": cls, "inputs": inputs}
        if n.get("title"):
            entry["_meta"] = {"title": n["title"]}
        prompt[nid] = entry

    # drop inputs that point at nodes we skipped
    for nid, e in prompt.items():
        for k, v in list(e["inputs"].items()):
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) \
                    and v[0] not in prompt and v[0] in nodes:
                del e["inputs"][k]
                warnings.append(f"node {nid}: input {k} came from a skipped node")
    return prompt, warnings


# ---------------------------------------------------------------- models

def _models_named(ui: dict) -> list[dict]:
    found = {}
    def walk(nodes):
        for n in nodes:
            for m in (n.get("properties") or {}).get("models") or []:
                found[(m.get("directory"), m.get("name"))] = m
    walk(ui.get("nodes", []))
    for sg in (ui.get("definitions") or {}).get("subgraphs", []):
        walk(sg.get("nodes", []))
    for m in ui.get("models") or []:
        found.setdefault((m.get("directory"), m.get("name")), m)
    return list(found.values())


def _server_models(server: str, folder: str) -> set[str]:
    try:
        return set(get_json(server, f"/models/{urllib.parse.quote(folder)}"))
    except urllib.error.HTTPError:
        return set()


def _model_root(server: str) -> Path | None:
    """First base_path from the server's extra model paths, else <ComfyUI>/models."""
    stats = get_json(server, "/system_stats")
    argv = stats["system"].get("argv", [])
    if "--extra-model-paths-config" in argv:
        cfg = Path(argv[argv.index("--extra-model-paths-config") + 1])
        if cfg.exists():
            for line in cfg.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if s.startswith("base_path:"):
                    return Path(s.split(":", 1)[1].strip().strip("'\""))
    return None


def _download(url: str, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    have = part.stat().st_size if part.exists() else 0
    req = urllib.request.Request(url, headers={"Range": f"bytes={have}-"} if have else {})
    with urllib.request.urlopen(req, timeout=60) as r, open(part, "ab" if have else "wb") as f:
        total = int(r.headers.get("Content-Length") or 0) + have
        done, last = have, 0.0
        while chunk := r.read(1 << 22):
            f.write(chunk)
            done += len(chunk)
            if time.time() - last > 10:
                print(f"  {dest.name}: {done / 2**30:.2f} / {total / 2**30:.2f} GiB",
                      file=sys.stderr)
                last = time.time()
    part.replace(dest)


# ---------------------------------------------------------------- run

def _coerce(v: str):
    for f in (json.loads,):
        try:
            return f(v)
        except (ValueError, json.JSONDecodeError):
            pass
    return v


def run(server: str, prompt: dict, out_dir: Path, timeout: float) -> dict:
    client_id = uuid.uuid4().hex
    res = post_json(server, "/prompt", {"prompt": prompt, "client_id": client_id})
    pid = res["prompt_id"]
    print(f"queued {pid} (if this process dies, `fetch {pid}` collects the outputs)",
          file=sys.stderr, flush=True)
    return collect(server, pid, out_dir, timeout)


def collect(server: str, pid: str, out_dir: Path, timeout: float = 0) -> dict:
    """Wait for prompt pid to finish (up to timeout s), then download its saved files."""
    t0 = time.time()
    while True:
        h = get_json(server, f"/history/{pid}")
        if pid in h:
            entry = h[pid]
            break
        if time.time() - t0 > timeout:
            raise SystemExit(f"timed out after {timeout:.0f}s waiting for {pid} "
                             f"(still queued or running; check /queue)")
        time.sleep(2)
    status = entry.get("status", {})
    msgs = {m[0]: m[1] for m in status.get("messages", []) if len(m) == 2}
    t_start = (msgs.get("execution_start") or {}).get("timestamp")
    t_end = max((m.get("timestamp") or 0) for m in msgs.values()) if msgs else None
    summary = {"prompt_id": pid, "status": status.get("status_str"),
               "seconds": round((t_end - t_start) / 1000, 1) if t_start and t_end else None,
               "files": [], "errors": []}
    for msg in status.get("messages", []):
        if msg[0] == "execution_error":
            d = msg[1]
            summary["errors"].append(f"node {d.get('node_id')} ({d.get('node_type')}): "
                                     f"{d.get('exception_message', '').strip()}")
    out_dir.mkdir(parents=True, exist_ok=True)
    for nid, outputs in (entry.get("outputs") or {}).items():
        for key, items in outputs.items():
            if not isinstance(items, list):
                continue
            for it in items:
                if isinstance(it, str):
                    # text outputs (GetMeshInfo, ShowText): report, never fetch as a file
                    summary.setdefault("text", {})[nid] = it
                    continue
                if not isinstance(it, dict) or "filename" not in it:
                    continue
                if it.get("type") == "temp":
                    continue            # previews
                q = urllib.parse.urlencode({"filename": it["filename"],
                                            "subfolder": it.get("subfolder", ""),
                                            "type": it.get("type", "output")})
                dest = out_dir / Path(it["filename"]).name
                try:
                    dest.write_bytes(_req(server, f"/view?{q}", timeout=600))
                except urllib.error.HTTPError as e:
                    summary["errors"].append(f"node {nid}: could not fetch {it['filename']} "
                                             f"(HTTP {e.code})")
                    continue
                summary["files"].append({"node": nid, "kind": key, "path": str(dest),
                                         "bytes": dest.stat().st_size})
    return summary


# ---------------------------------------------------------------- CLI

def _launch_cmd() -> str:
    appdata = Path(os.environ.get("APPDATA", ""))
    inst_file = appdata / "Comfy Desktop" / "installations.json"
    if not inst_file.exists():
        return "No Comfy Desktop installations.json found; start ComfyUI the way it was installed."
    lines = []
    for inst in json.loads(inst_file.read_text(encoding="utf-8")):
        root = inst.get("installPath")
        if not root:
            continue
        root = Path(root)
        py = root / "ComfyUI" / ".venv" / "Scripts" / "python.exe"
        cfg = appdata / "Comfy Desktop" / "instance-model-paths" / f"{inst['id']}.yaml"
        shared = root.parent.parent / "ComfyUI-Shared"
        lines.append(f"# {inst.get('name')} ({inst.get('comfyVersionTag') or inst.get('version')})\n"
                     f"cd \"{root}\"\n"
                     f"& \"{py}\" -s ComfyUI\\main.py --listen 127.0.0.1 --port 8188 "
                     f"--extra-model-paths-config \"{cfg}\" "
                     f"--input-directory \"{shared / 'input'}\" "
                     f"--output-directory \"{shared / 'output'}\"")
    return "\n".join(lines) or "No local installations listed."


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--server", default=DEFAULT_SERVER)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("launch-cmd")
    t = sub.add_parser("templates"); t.add_argument("words", nargs="*")
    c = sub.add_parser("convert"); c.add_argument("ui"); c.add_argument("-o", "--out", required=True)
    m = sub.add_parser("models"); m.add_argument("ui"); m.add_argument("--download", action="store_true")
    n = sub.add_parser("nodes"); n.add_argument("api")
    f = sub.add_parser("fetch"); f.add_argument("prompt_id"); f.add_argument("--out", default="comfy_out")
    f.add_argument("--timeout", type=float, default=0)
    r = sub.add_parser("run")
    r.add_argument("api")
    r.add_argument("--set", action="append", default=[], metavar="TARGET.INPUT=VALUE",
                   help="override an input; VALUE is parsed as JSON when it can be")
    r.add_argument("--upload", action="append", default=[], metavar="FILE",
                   help="upload to the server's input folder first")
    r.add_argument("--out", default="comfy_out")
    r.add_argument("--timeout", type=float, default=1800)
    a = ap.parse_args(argv)

    if a.cmd == "launch-cmd":
        print(_launch_cmd()); return 0
    if a.cmd == "templates":
        for cat in get_json(a.server, "/templates/index.json"):
            for tp in cat.get("templates", []):
                text = f"{tp['name']} {tp.get('title', '')} {tp.get('description', '')}".lower()
                if all(w.lower() in text for w in a.words) and not tp["name"].startswith("api_"):
                    print(f"{tp['name']:<52} {tp.get('size', 0) / 2**30:6.1f} GB  "
                          f"{cat.get('title', '')}: {tp.get('title', '')}")
        return 0
    if a.cmd == "status":
        s = get_json(a.server, "/system_stats", timeout=5)
        d = s["devices"][0] if s.get("devices") else {}
        print(json.dumps({"comfyui": s["system"].get("comfyui_version"),
                          "device": d.get("name"),
                          "vram_free_gb": round(d.get("vram_free", 0) / 2**30, 1)}, indent=1))
        return 0
    if a.cmd == "convert":
        ui = load_ui(a.server, a.ui)
        prompt, warns = convert(ui, get_json(a.server, "/object_info"))
        Path(a.out).write_text(json.dumps(prompt, indent=1), encoding="utf-8")
        for w in warns:
            print("WARN", w, file=sys.stderr)
        print(f"{len(prompt)} nodes -> {a.out}")
        return 0
    if a.cmd == "models":
        ui = load_ui(a.server, a.ui)
        root = _model_root(a.server) if a.download else None
        missing = 0
        for mdl in _models_named(ui):
            have = mdl["name"] in _server_models(a.server, mdl["directory"])
            print(f"{'ok     ' if have else 'MISSING'} {mdl['directory']}/{mdl['name']}  {mdl.get('url', '')}")
            if not have:
                missing += 1
                if a.download:
                    if not root:
                        raise SystemExit("cannot tell where models live; download by hand")
                    _download(mdl["url"], root / mdl["directory"] / mdl["name"])
                    print(f"  saved {root / mdl['directory'] / mdl['name']}")
        return 1 if missing and not a.download else 0
    if a.cmd == "nodes":
        p = json.loads(Path(a.api).read_text(encoding="utf-8"))
        for nid, e in p.items():
            ws = {k: v for k, v in e["inputs"].items() if not isinstance(v, list)}
            title = (e.get("_meta") or {}).get("title", "")
            print(f"{nid:>8} {e['class_type']:<28} {title:<28} {json.dumps(ws)[:160]}")
        return 0
    if a.cmd == "fetch":
        summary = collect(a.server, a.prompt_id, Path(a.out), a.timeout)
        print(json.dumps(summary, indent=1))
        return 0 if summary["status"] == "success" and not summary["errors"] else 1
    if a.cmd == "run":
        p = json.loads(Path(a.api).read_text(encoding="utf-8"))
        for f in a.upload:
            print(f"uploaded {upload_file(a.server, Path(f))}", file=sys.stderr)
        info = None
        for s in a.set:
            key, _, val = s.partition("=")
            target, _, inp = key.partition(".")
            nid = find_node(p, target)
            if info is None:
                info = get_json(a.server, "/object_info")
            for note in set_input(p, nid, inp, _coerce(val), info):
                print(f"set {nid}: {note}", file=sys.stderr)
        summary = run(a.server, p, Path(a.out), a.timeout)
        print(json.dumps(summary, indent=1))
        return 0 if summary["status"] == "success" and not summary["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
