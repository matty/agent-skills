"""Search and download free CC0 PBR materials from Poly Haven and ambientCG through their public JSON APIs.

Host: plain Python 3.9+, standard library only (urllib, zipfile, hashlib). Needs network access.

Command line (exit 0 on success, 1 when nothing was found or a download failed, 2 on bad arguments):
    python pbr_fetch.py search red brick wall                       # both sources, 10 results each
    python pbr_fetch.py search oak floor --source ambientcg --limit 20 --json hits.json
    python pbr_fetch.py info polyhaven:red_brick_03                 # maps, resolutions, formats, sizes
    python pbr_fetch.py get polyhaven:red_brick_03 --res 2k --out textures/library
    python pbr_fetch.py get ambientcg:Bricks076C --res 4k --format png --normal both --out textures/library
    python pbr_fetch.py get polyhaven:red_brick_03 --bundle gltf --out textures/library   # the site's own bundle

A reference is <source>:<id> as `search` prints it (polyhaven:red_brick_03, ambientcg:Bricks076C).

`get` writes <out>/<source>_<id>/<id>_<res>_<Map>.<ext> with these map names whatever the site calls them:
BaseColor, NormalGL (OpenGL, Y+), NormalDX (DirectX, Y-), Roughness, Metallic, AO, Height, Opacity, Emission, and
with --maps all also ARM (R AO, G roughness, B metallic), Bump, Specular and any map the site adds later (its own
name, title-cased). Beside them, source.json records the source, page URL, licence, credit line, physical size,
resolution and every file with its size and MD5. Poly Haven files are checked against the MD5 its API publishes;
ambientCG zips are checked for size and CRC before anything is extracted. Zip members and bundle paths that would
land outside the output folder are refused.

--bundle keeps the site's own file names so its scene files still find their textures: for Poly Haven one of
gltf, blend or mtlx (the file and the textures it includes); for ambientCG any value, which extracts the whole zip
(textures plus the .mtlx, .blend, .usdc and .tres it ships).

Searches cache Poly Haven's full texture list (one request, about 1 MB) for 24 hours in the temp folder
(--refresh skips the cache). Every request names this tool in its User-Agent, as Poly Haven's API terms require.

As a module: search(words, sources, limit) returns normalised hits; info(ref) returns one asset's maps and
downloads; get(ref, out_dir, res, fmt, maps, normal, bundle, max_mb) downloads and returns the source.json dict.
The pure helpers (match_polyhaven, plan_polyhaven, plan_ambientcg, extract_ambientcg, safe_join) take plain data,
so tests run them without the network.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

# Poly Haven API terms 2.4: every call carries a User-Agent or Referer unique to the software, and 2.5: content
# surfaced through the live API is credited ("Powered by Poly Haven" or a label naming Poly Haven).
# https://github.com/Poly-Haven/Public-API/blob/master/ToS.md (checked 2026-10-25)
USER_AGENT = "agent-skills-pbr-texture-sources/1.0 (+https://github.com/matty/agent-skills)"
POLYHAVEN_API = "https://api.polyhaven.com"
AMBIENTCG_API = "https://ambientcg.com/api/v3/assets"
CC0 = {"licence": "CC0-1.0", "licence_url": "https://creativecommons.org/publicdomain/zero/1.0/"}
CREDIT = {
    "polyhaven": "Powered by Poly Haven (https://polyhaven.com)",
    "ambientcg": "Created using {title} from ambientCG.com, licensed under CC0 1.0 (credit optional)",
}
SOURCES = ("polyhaven", "ambientcg")
RESOLUTIONS = ("1k", "2k", "4k", "8k", "16k")
CACHE_TTL_S = 24 * 3600
TIMEOUT_S = 60

# Canonical map names. CORE is what `get` downloads by default; the rest need --maps all or naming them.
CORE = ("BaseColor", "Normal", "Roughness", "Metallic", "AO", "Height", "Opacity", "Emission")
# Poly Haven /files keys (lower-cased) -> canonical. Measured on 14 textures 2026-10-25: Diffuse, nor_gl, nor_dx,
# Rough, Metal, AO, Displacement, arm, rough_ao, Bump, spec, spec_ior, anisotropy_*; blend/gltf/mtlx are bundles.
POLYHAVEN_MAPS = {
    "diffuse": "BaseColor", "diff": "BaseColor", "nor_gl": "NormalGL", "nor_dx": "NormalDX", "rough": "Roughness",
    "metal": "Metallic", "ao": "AO", "displacement": "Height", "disp": "Height", "arm": "ARM", "bump": "Bump",
    "spec": "Specular", "opacity": "Opacity", "alpha": "Opacity", "emission": "Emission", "emissive": "Emission",
}
POLYHAVEN_BUNDLES = ("gltf", "blend", "mtlx")
# ambientCG zip member suffixes (<id>_<res>-<FMT>_<Suffix>.<ext>) -> canonical. Measured on Ground111 2026-10-25:
# Color, NormalGL, NormalDX, Roughness, AmbientOcclusion, Displacement; Metalness, Opacity, Emission from the API's
# map list (metalness, opacity, emission).
AMBIENTCG_MAPS = {
    "color": "BaseColor", "normalgl": "NormalGL", "normaldx": "NormalDX", "roughness": "Roughness",
    "metalness": "Metallic", "ambientocclusion": "AO", "displacement": "Height", "opacity": "Opacity",
    "emission": "Emission", "normal": "Normal",
}
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".exr", ".tif", ".tiff")


class FetchError(Exception):
    pass


# ---- network (tests replace http_json and http_download) ------------------------------------------------------------

def _request(url):
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json, */*"})


def http_json(url, retries=2):
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(_request(url), timeout=TIMEOUT_S) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == retries:
                raise FetchError("%s: HTTP %d" % (url, e.code))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt == retries:
                raise FetchError("%s: %s" % (url, e))
        time.sleep(2 ** attempt)


def http_download(url, path, retries=2):
    """Stream url to path (through path + '.part'); returns the MD5 hex digest and the byte count."""
    part = path + ".part"
    for attempt in range(retries + 1):
        try:
            md5, n = hashlib.md5(), 0
            with urllib.request.urlopen(_request(url), timeout=TIMEOUT_S) as r, open(part, "wb") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    md5.update(chunk)
                    n += len(chunk)
                    f.write(chunk)
            os.replace(part, path)
            return md5.hexdigest(), n
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == retries:
                raise FetchError("%s: HTTP %d" % (url, e.code))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt == retries:
                raise FetchError("%s: %s" % (url, e))
        finally:
            if os.path.exists(part):
                os.remove(part)
        time.sleep(2 ** attempt)


def cache_dir():
    d = os.path.join(tempfile.gettempdir(), "pbr-texture-sources")
    os.makedirs(d, exist_ok=True)
    return d


def polyhaven_assets(refresh=False):
    path = os.path.join(cache_dir(), "polyhaven_textures.json")
    if not refresh and os.path.exists(path) and time.time() - os.path.getmtime(path) < CACHE_TTL_S:
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    data = http_json(POLYHAVEN_API + "/assets?type=textures")
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(path + ".tmp", path)
    return data


# ---- pure helpers -----------------------------------------------------------------------------------------------------

def parse_ref(ref):
    source, sep, asset_id = ref.partition(":")
    source = source.strip().lower()
    if not sep or source not in SOURCES or not re.fullmatch(r"[A-Za-z0-9_.-]+", asset_id or ""):
        raise FetchError("reference %r is not <source>:<id> with source one of %s" % (ref, ", ".join(SOURCES)))
    return source, asset_id


def res_key(res):
    """'2k', '2K', '2048' -> '2k'."""
    r = str(res).strip().lower()
    if r.isdigit():
        r = "%dk" % max(1, round(int(r) / 1024))
    if not re.fullmatch(r"\d+k", r):
        raise FetchError("resolution %r is not like 1k, 2k, 4k or 8k" % res)
    return r


def res_value(r):
    return int(r[:-1])


def pick_res(available, wanted):
    """The largest available resolution not above wanted, else the smallest available."""
    avail = sorted({res_key(a) for a in available}, key=res_value)
    if not avail:
        return None
    below = [a for a in avail if res_value(a) <= res_value(wanted)]
    return below[-1] if below else avail[0]


def _tokens(*values):
    out = []
    for v in values:
        if isinstance(v, dict):
            out += _tokens(*v.keys(), *v.values())
        elif isinstance(v, (list, tuple)):
            out += _tokens(*v)
        elif v is not None:
            out += re.findall(r"[a-z0-9]+", str(v).lower())
    return out


def _word_hits(word, tokens):
    stem = word[:-1] if len(word) > 3 and word.endswith("s") else word
    return any(t.startswith(stem) for t in tokens)


def match_polyhaven(words, assets, limit):
    """Rank Poly Haven texture assets: every word must prefix a token of the id, name, tags, categories,
    classification or description (ambientCG's search is AND as well); words in the id, name, tags or categories
    score 2, in the description 1; ties go to the more downloaded."""
    words = [w for w in _tokens(*words) if w]
    scored = []
    for asset_id, a in assets.items():
        strong = _tokens(asset_id, a.get("name"), a.get("tags"), a.get("categories"), a.get("category"),
                         a.get("attributes"))
        weak = _tokens(a.get("description"))
        score = 0
        for w in words:
            if _word_hits(w, strong):
                score += 2
            elif _word_hits(w, weak):
                score += 1
            else:
                break
        else:
            scored.append((score, a.get("download_count", 0), asset_id))
    scored.sort(key=lambda s: (-s[0], -s[1], s[2]))
    return [polyhaven_hit(i, assets[i]) for _, _, i in scored[:limit]]


def _size_m(w, h, per_m):
    try:
        w, h = float(w) / per_m, float(h) / per_m
    except (TypeError, ValueError):
        return None
    return [round(w, 3), round(h, 3)] if w > 0 and h > 0 else None


def polyhaven_hit(asset_id, a):
    dims = a.get("dimensions") or [None, None]
    mx = (a.get("max_resolution") or [0])[0]
    return {
        "ref": "polyhaven:" + asset_id, "source": "polyhaven", "id": asset_id, "title": a.get("name", asset_id),
        "tags": list(a.get("tags") or [])[:10], "categories": list(a.get("categories") or []),
        # Poly Haven dimensions are millimetres (2000 for a 2 m floor tile): inferred from the values, 2026-10-25.
        "size_m": _size_m(dims[0], dims[1] if len(dims) > 1 else None, 1000.0),
        "max_res": "%dk" % round(mx / 1024) if mx else None,
        "url": "https://polyhaven.com/a/" + asset_id, "downloads": a.get("download_count"),
    }


def ambientcg_hit(a):
    dims = a.get("dimensions") or {}
    res = [d.get("attributes", "").split("-")[0].lower() for d in a.get("downloads") or []]
    res = [r for r in res if re.fullmatch(r"\d+k", r)]
    return {
        "ref": "ambientcg:" + a["id"], "source": "ambientcg", "id": a["id"], "title": a.get("title", a["id"]),
        "tags": list(a.get("tags") or [])[:10], "maps": [AMBIENTCG_MAPS.get(m.replace("-", ""), m)
                                                          for m in a.get("maps") or []],
        # ambientCG dimensions are centimetres (200 for a 2 m brick wall; 0 when unknown): inferred, 2026-10-25.
        "size_m": _size_m(dims.get("width"), dims.get("height"), 100.0),
        "max_res": max(res, key=res_value) if res else None,
        "url": a.get("url") or "https://ambientcg.com/a/" + a["id"],
    }


def polyhaven_map_name(key):
    k = key.lower()
    if k in POLYHAVEN_MAPS:
        return POLYHAVEN_MAPS[k]
    return "".join(p[:1].upper() + p[1:] for p in re.split(r"[_\s-]+", key) if p)


def wanted_names(maps, normal):
    """--maps and --normal -> {lower-case name: name} of the canonical names to keep, or None for every map."""
    normals = {"gl": ["NormalGL"], "dx": ["NormalDX"], "both": ["NormalGL", "NormalDX"]}[normal]
    if maps == "all":
        return None
    names = CORE if maps == "core" else [m.strip() for m in maps.split(",") if m.strip()]
    out = set()
    for n in names:
        out.update(normals if n.lower() == "normal" else [n])
    return {n.lower(): n for n in out}


def _missing(keep, got):
    """Notes for requested maps the asset lacks; Metallic, Opacity and Emission are only expected where they apply."""
    got = {g.lower() for g in got}
    return ["%s: not offered for this asset" % keep[k] for k in sorted(keep)
            if k not in got and k not in ("metallic", "opacity", "emission")]


def plan_polyhaven(files, res, fmt, maps="core", normal="gl"):
    """Poly Haven /files JSON -> (plan, notes). plan items: name, url, md5, size, res, fmt, ext."""
    keep = wanted_names(maps, normal)
    plan, notes = [], []
    for key, by_res in sorted(files.items()):
        if key.lower() in POLYHAVEN_BUNDLES or not isinstance(by_res, dict):
            continue
        name = polyhaven_map_name(key)
        if keep is not None and name.lower() not in keep:
            continue
        valid = [r for r in by_res if re.fullmatch(r"\d+k", r) and isinstance(by_res[r], dict)]
        r = pick_res(valid, res)
        if r is None:
            continue
        formats = by_res[r]
        f = fmt if fmt in formats else next((x for x in ("png", "jpg", "exr") if x in formats), None)
        if f is None or not isinstance(formats[f], dict) or "url" not in formats[f]:
            continue
        if r != res:
            notes.append("%s: %s not offered, using %s" % (name, res, r))
        if f != fmt:
            notes.append("%s: %s not offered, using %s" % (name, fmt, f))
        e = formats[f]
        plan.append({"name": name, "url": e["url"], "md5": e.get("md5"), "size": e.get("size"), "res": r,
                     "fmt": f, "ext": "." + f})
    if keep is not None:
        notes += _missing(keep, [p["name"] for p in plan])
    return plan, notes


def plan_polyhaven_bundle(files, bundle, res):
    """The files of a Poly Haven gltf/blend/mtlx bundle -> list of (relative path, url, md5, size)."""
    by_res = files.get(bundle)
    if not isinstance(by_res, dict):
        raise FetchError("no %s bundle for this asset (it offers: %s)"
                         % (bundle, ", ".join(b for b in POLYHAVEN_BUNDLES if b in files) or "none"))
    r = pick_res(by_res.keys(), res)
    entry = by_res[r][bundle]
    name = entry["url"].rsplit("/", 1)[-1]
    out = [(name, entry["url"], entry.get("md5"), entry.get("size"))]
    for rel, e in sorted((entry.get("include") or {}).items()):
        out.append((rel, e["url"], e.get("md5"), e.get("size")))
    return r, out


def plan_ambientcg(asset, res, fmt):
    """ambientCG asset (with downloads) -> (download dict, res, fmt, notes). fmt is jpg or png."""
    offered = {}
    for d in asset.get("downloads") or []:
        m = re.fullmatch(r"(\d+)K-(JPG|PNG|EXR)", d.get("attributes", ""), re.I)
        if m and d.get("extension", "zip") == "zip":
            offered[("%sk" % m.group(1), m.group(2).lower())] = d
    if not offered:
        raise FetchError("ambientcg:%s offers no image zip downloads" % asset.get("id"))
    formats = sorted({f for _, f in offered})
    f = fmt if fmt in formats else ("jpg" if "jpg" in formats else formats[0])
    r = pick_res([rr for rr, ff in offered if ff == f], res)
    notes = []
    if f != fmt:
        notes.append("%s not offered, using %s" % (fmt, f))
    if r != res:
        notes.append("%s not offered, using %s" % (res, r))
    return offered[(r, f)], r, f, notes


def safe_join(root, rel):
    """root/rel, refusing absolute paths, drive letters and '..' so nothing lands outside root."""
    rel = rel.replace("\\", "/")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if not parts or rel.startswith("/") or re.match(r"^[A-Za-z]:", rel) or ".." in parts:
        raise FetchError("refusing unsafe path %r" % rel)
    path = os.path.normpath(os.path.join(root, *parts))
    if os.path.commonpath([os.path.abspath(root), os.path.abspath(path)]) != os.path.abspath(root):
        raise FetchError("refusing unsafe path %r" % rel)
    return path


def extract_ambientcg(zip_path, asset_id, attr, dest, prefix, maps="core", normal="gl", bundle=False):
    """Extract an ambientCG zip into dest. Normal mode: image members named <asset_id>_<attr>_<Suffix>.<ext>
    become <prefix>_<Map>.<ext>; everything else is skipped. Bundle mode: every member keeps its own name.
    Returns (written: list of (name, path, size, md5), notes)."""
    keep = wanted_names(maps, normal)
    written, notes = [], []
    pat = re.compile(r"^%s_%s_([A-Za-z0-9]+)(\.[A-Za-z0-9]+)$" % (re.escape(asset_id), re.escape(attr)), re.I)
    with zipfile.ZipFile(zip_path) as z:
        bad = z.testzip()
        if bad:
            raise FetchError("zip member %s is corrupt" % bad)
        for info in z.infolist():
            if info.is_dir():
                continue
            if bundle:
                name, target = info.filename, safe_join(dest, info.filename)
            else:
                base = info.filename.replace("\\", "/").rsplit("/", 1)[-1]
                m = pat.match(base)
                if not m or m.group(2).lower() not in IMAGE_EXT:
                    continue
                suffix = m.group(1)
                name = AMBIENTCG_MAPS.get(suffix.lower(), suffix[:1].upper() + suffix[1:])
                if keep is not None and name.lower() not in keep:
                    continue
                target = safe_join(dest, "%s_%s%s" % (prefix, name, m.group(2).lower()))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            md5 = hashlib.md5()
            with z.open(info) as src, open(target, "wb") as out:
                for chunk in iter(lambda: src.read(1 << 20), b""):
                    md5.update(chunk)
                    out.write(chunk)
            written.append((name, target, info.file_size, md5.hexdigest()))
    if not bundle and keep is not None:
        notes += _missing(keep, [w[0] for w in written])
    return written, notes


# ---- commands -------------------------------------------------------------------------------------------------------

def search(words, sources=SOURCES, limit=10, refresh=False):
    hits, errors = [], []
    if "polyhaven" in sources:
        try:
            hits += match_polyhaven(words, polyhaven_assets(refresh), limit)
        except FetchError as e:
            errors.append("polyhaven: %s" % e)
    if "ambientcg" in sources:
        q = urllib.parse.urlencode({"type": "material", "q": " ".join(words), "sort": "popular", "limit": limit,
                                    "include": "title,tags,maps,dimensions,url,downloads"})
        try:
            hits += [ambientcg_hit(a) for a in http_json(AMBIENTCG_API + "?" + q).get("assets") or []]
        except FetchError as e:
            errors.append("ambientcg: %s" % e)
    return hits, errors


def _ambientcg_asset(asset_id):
    q = urllib.parse.urlencode({"id": asset_id, "include": "title,tags,maps,dimensions,url,downloads"})
    assets = [a for a in http_json(AMBIENTCG_API + "?" + q).get("assets") or [] if a.get("id") == asset_id]
    if not assets:
        raise FetchError("ambientcg:%s not found" % asset_id)
    return assets[0]


def _polyhaven_info(asset_id):
    try:
        a = http_json(POLYHAVEN_API + "/info/" + urllib.parse.quote(asset_id))
    except FetchError as e:
        raise FetchError("polyhaven:%s not found (%s)" % (asset_id, e))
    if not isinstance(a, dict) or a.get("type") != 1:
        raise FetchError("polyhaven:%s is not a texture" % asset_id)
    return a


def info(ref):
    source, asset_id = parse_ref(ref)
    if source == "polyhaven":
        a = _polyhaven_info(asset_id)
        files = http_json(POLYHAVEN_API + "/files/" + urllib.parse.quote(asset_id))
        hit = polyhaven_hit(asset_id, a)
        hit["maps"] = {}
        for key, by_res in sorted(files.items()):
            if not isinstance(by_res, dict):
                continue
            if key.lower() in POLYHAVEN_BUNDLES:
                hit.setdefault("bundles", []).append(key)
                continue
            hit["maps"][polyhaven_map_name(key)] = {
                r: {f: (e or {}).get("size") for f, e in fmts.items()}
                for r, fmts in sorted(by_res.items(), key=lambda kv: res_value(kv[0]) if re.fullmatch(r"\d+k", kv[0]) else 0)
                if isinstance(fmts, dict)}
        return hit
    a = _ambientcg_asset(asset_id)
    hit = ambientcg_hit(a)
    hit["downloads_offered"] = {d["attributes"]: d.get("size") for d in a.get("downloads") or []}
    hit["bundles"] = ["zip (mtlx, blend, usdc, tres included)"]
    return hit


def _check_size(total, max_mb):
    if max_mb and total and total > max_mb * 1e6:
        raise FetchError("download would be %.0f MB, over --max-mb %d; pick a lower --res or raise --max-mb"
                         % (total / 1e6, max_mb))


def get(ref, out_dir, res="2k", fmt="jpg", maps="core", normal="gl", bundle=None, max_mb=500, log=print):
    source, asset_id = parse_ref(ref)
    res = res_key(res)
    dest = os.path.join(out_dir, "%s_%s" % (source, asset_id))
    os.makedirs(dest, exist_ok=True)
    record = dict({"source": source, "id": asset_id, "ref": ref, "downloaded": time.strftime("%Y-%m-%d")}, **CC0)
    files_out, notes = [], []

    if source == "polyhaven":
        a = _polyhaven_info(asset_id)
        files = http_json(POLYHAVEN_API + "/files/" + urllib.parse.quote(asset_id))
        hit = polyhaven_hit(asset_id, a)
        if bundle:
            if bundle not in POLYHAVEN_BUNDLES:
                raise FetchError("--bundle for Poly Haven is one of %s" % ", ".join(POLYHAVEN_BUNDLES))
            r, items = plan_polyhaven_bundle(files, bundle, res)
            _check_size(sum(i[3] or 0 for i in items), max_mb)
            jobs = [(rel, rel, url, md5, size) for rel, url, md5, size in items]
            record.update(res=r, bundle=bundle)
        else:
            plan, notes = plan_polyhaven(files, res, fmt, maps, normal)
            if not plan:
                raise FetchError("polyhaven:%s offers none of the requested maps" % asset_id)
            _check_size(sum(p["size"] or 0 for p in plan), max_mb)
            jobs = [(p["name"], "%s_%s_%s%s" % (asset_id, p["res"], p["name"], p["ext"]), p["url"], p["md5"],
                     p["size"]) for p in plan]
            record.update(res=res, format=fmt)
        for name, rel, url, md5, size in jobs:
            path = safe_join(dest, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            log("  %s <- %s" % (rel, url))
            got_md5, n = http_download(url, path)
            if md5 and got_md5 != md5:
                os.remove(path)
                raise FetchError("%s: MD5 %s does not match the API's %s" % (rel, got_md5, md5))
            files_out.append({"map": name, "file": rel.replace("\\", "/"), "bytes": n, "md5": got_md5,
                              "url": url})
        record.update(title=hit["title"], url=hit["url"], size_m=hit["size_m"], authors=a.get("authors"),
                      credit=CREDIT["polyhaven"])
    else:
        a = _ambientcg_asset(asset_id)
        hit = ambientcg_hit(a)
        d, r, f, notes = plan_ambientcg(a, res, fmt)
        _check_size(d.get("size"), max_mb)
        tmp = tempfile.mkdtemp(prefix="acg_")
        try:
            zpath = os.path.join(tmp, "asset.zip")
            log("  %s <- %s" % (d["attributes"], d["url"]))
            _, n = http_download(d["url"], zpath)
            if d.get("size") and n != d["size"]:
                raise FetchError("zip is %d bytes, the API says %d" % (n, d["size"]))
            written, more = extract_ambientcg(zpath, asset_id, d["attributes"], dest,
                                              "%s_%s" % (asset_id, r), maps, normal, bool(bundle))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        notes += more
        if not written:
            raise FetchError("ambientcg:%s zip held none of the requested maps" % asset_id)
        files_out = [{"map": name, "file": os.path.relpath(p, dest).replace("\\", "/"), "bytes": size, "md5": md5}
                     for name, p, size, md5 in written]
        record.update(res=r, format=f, title=hit["title"], url=hit["url"], size_m=hit["size_m"],
                      credit=CREDIT["ambientcg"].format(title=hit["title"]), zip=d["url"])
        if bundle:
            record["bundle"] = "zip"

    record["files"] = files_out
    record["notes"] = notes
    with open(os.path.join(dest, "source.json"), "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2)
    return record


# ---- command line ---------------------------------------------------------------------------------------------------

def _print_hits(hits):
    for h in hits:
        size = "%gx%g m" % tuple(h["size_m"]) if h.get("size_m") else "size ?"
        maps = h.get("maps")
        extra = (" maps: " + ",".join(maps)) if maps else ""
        print("%-34s %-28s %-6s %-12s %s%s" % (h["ref"], h["title"][:28], h.get("max_res") or "?", size,
                                              ", ".join(h["tags"][:6]), extra))
        print("    %s" % h["url"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search", help="search both libraries")
    s.add_argument("words", nargs="+")
    s.add_argument("--source", default=",".join(SOURCES), help="polyhaven, ambientcg or both (default)")
    s.add_argument("--limit", type=int, default=10, help="results per source (default 10)")
    s.add_argument("--json", help="also write the hits to this file")
    s.add_argument("--refresh", action="store_true", help="ignore the cached Poly Haven list")
    i = sub.add_parser("info", help="maps, resolutions and sizes of one asset")
    i.add_argument("ref")
    g = sub.add_parser("get", help="download one asset")
    g.add_argument("ref")
    g.add_argument("--out", required=True, help="folder that receives <source>_<id>/")
    g.add_argument("--res", default="2k", help="1k, 2k (default), 4k, 8k: the largest offered at or below it")
    g.add_argument("--format", default="jpg", choices=("jpg", "png", "exr"),
                   help="jpg (default), png, or exr (Poly Haven only)")
    g.add_argument("--maps", default="core", help="core (default), all, or a list like BaseColor,Normal,Roughness")
    g.add_argument("--normal", default="gl", choices=("gl", "dx", "both"), help="normal-map convention (default gl)")
    g.add_argument("--bundle", help="keep the site's own files: gltf, blend or mtlx (Poly Haven); any value "
                                    "for ambientCG's whole zip")
    g.add_argument("--max-mb", type=int, default=500, help="refuse downloads larger than this (default 500)")
    args = ap.parse_args(argv)

    try:
        if args.cmd == "search":
            sources = [x.strip().lower() for x in args.source.split(",") if x.strip()]
            unknown = [x for x in sources if x not in SOURCES]
            if unknown:
                ap.error("unknown source %s" % ", ".join(unknown))
            hits, errors = search(args.words, sources, max(1, min(args.limit, 500)), args.refresh)
            _print_hits(hits)
            for e in errors:
                print("ERROR %s" % e, file=sys.stderr)
            if any(h["source"] == "polyhaven" for h in hits):
                print("\nPoly Haven results: %s" % CREDIT["polyhaven"])
            if args.json:
                with open(args.json, "w", encoding="utf-8") as f:
                    json.dump(hits, f, indent=2)
            if not hits:
                print("no results")
                return 1
            return 0
        if args.cmd == "info":
            print(json.dumps(info(args.ref), indent=2))
            return 0
        rec = get(args.ref, args.out, args.res, args.format, args.maps, args.normal, args.bundle, args.max_mb)
        for n in rec["notes"]:
            print("NOTE %s" % n)
        print("wrote %d file(s) to %s (%s, %s)" % (len(rec["files"]), os.path.normpath(os.path.join(
            args.out, "%s_%s" % (rec["source"], rec["id"]))), rec["licence"], rec["credit"]))
        return 0
    except FetchError as e:
        print("ERROR %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
