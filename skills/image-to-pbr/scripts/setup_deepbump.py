"""Download DeepBump (https://github.com/HugoTini/DeepBump, GPL-3.0) at a pinned commit, check the files the converter
runs against pinned SHA-256 hashes, give it its own venv with numpy and onnxruntime, and smoke-test it, so that
image_to_pbr.py can use its machine-learning colour-to-normal model. DeepBump is never copied into this repo: it is
installed in a per-user folder and image_to_pbr.py runs it as a separate process.

Host: plain Python 3.9+, standard library (it builds the venv with the interpreter that runs it, or --python).
Needs internet access: about 45 MB from codeload.github.com and onnxruntime plus numpy from PyPI.

    python setup_deepbump.py                 # install or repair in the default folder
    python setup_deepbump.py --check         # report whether it is installed and working; exit 1 if not
    python setup_deepbump.py --root D:/tools/deepbump --python "C:/path/to/python.exe"

Default folder: %LOCALAPPDATA%/agent-skills/deepbump on Windows, ~/.cache/agent-skills/deepbump elsewhere, or the
IMAGE_TO_PBR_DEEPBUMP environment variable. Layout: <root>/DeepBump (the source), <root>/venv, <root>/deepbump.json
(what was installed and when). Exit 0 when DeepBump works, 1 when it does not, 2 on bad arguments.
"""

import argparse
import datetime
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

COMMIT = "fad19ba87daed12b1d0410a57e74f3d79e82f78d"     # DeepBump master, 2025-03-17 (add-on version 8.0.0)
URL = "https://codeload.github.com/HugoTini/DeepBump/zip/%s" % COMMIT
# SHA-256 of the files image_to_pbr.py runs; .py files hashed with LF line endings
PINNED = {
    "deepbump256.onnx": "3a2ababc5fa652b19040a0f3d639b71826368e52ad805cf70ffb0e7c96a54d67",
    "module_color_to_normals.py": "1e7fb220580fc6451468934cd4377bf9de7193321fad99fcb123018d546e9fe8",
    "utils_inference.py": "a238bf7eb21d43e785ba53b1e6024e5b36b65a66bdbd971d7790e65ee8744645",
}
PACKAGES = ["numpy", "onnxruntime"]


def default_root():
    env = os.environ.get("IMAGE_TO_PBR_DEEPBUMP")
    if env:
        return env
    base = os.environ.get("LOCALAPPDATA") if os.name == "nt" else None
    return os.path.join(base or os.path.join(os.path.expanduser("~"), ".cache"), "agent-skills", "deepbump")


def venv_python(root):
    return os.path.join(root, "venv", "Scripts" if os.name == "nt" else "bin",
                        "python.exe" if os.name == "nt" else "python")


def file_hash(path):
    with open(path, "rb") as f:
        data = f.read()
    if path.endswith(".py"):
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def verify(src):
    """[] when every pinned file is present with its pinned hash, else what is wrong."""
    bad = []
    for name, digest in PINNED.items():
        p = os.path.join(src, name)
        if not os.path.isfile(p):
            bad.append("%s missing" % name)
        elif file_hash(p) != digest:
            bad.append("%s has SHA-256 %s, pinned %s" % (name, file_hash(p), digest))
    return bad


def download(root):
    print("downloading DeepBump %s from %s" % (COMMIT[:12], URL), flush=True)
    with urllib.request.urlopen(URL, timeout=120) as r:
        data = r.read()
    print("  %.1f MB" % (len(data) / 1e6), flush=True)
    dest = os.path.join(root, "DeepBump")
    tmp = tempfile.mkdtemp(dir=root)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for info in z.infolist():
                parts = info.filename.split("/", 1)          # strip the DeepBump-<commit>/ folder
                if len(parts) < 2 or not parts[1] or ".." in parts[1].split("/"):
                    continue
                out = os.path.join(tmp, *parts[1].split("/"))
                if info.is_dir():
                    os.makedirs(out, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(out), exist_ok=True)
                with z.open(info) as s, open(out, "wb") as d:
                    shutil.copyfileobj(s, d)
        bad = verify(tmp)
        if bad:
            raise RuntimeError("downloaded files do not match the pinned hashes: %s" % "; ".join(bad))
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        os.replace(tmp, dest)
    finally:
        if os.path.isdir(tmp):
            shutil.rmtree(tmp, ignore_errors=True)


def make_venv(root, python):
    vpy = venv_python(root)
    if not os.path.isfile(vpy):
        print("creating venv with %s" % python, flush=True)
        subprocess.run([python, "-m", "venv", os.path.join(root, "venv")], check=True)
    print("installing %s" % " ".join(PACKAGES), flush=True)
    subprocess.run([vpy, "-m", "pip", "install", "--disable-pip-version-check", "-q", "--upgrade"] + PACKAGES,
                   check=True)


SMOKE = r"""
import sys, json
sys.path.insert(0, sys.argv[1])
import numpy as np, onnxruntime
import module_color_to_normals as c2n
img = np.random.default_rng(0).random((3, 256, 256)).astype(np.float32)
n = c2n.apply(img, "LARGE", None)
ok = n.shape == (3, 256, 256) and bool(np.isfinite(n).all())
print(json.dumps({"ok": ok, "numpy": np.__version__, "onnxruntime": onnxruntime.__version__,
                  "python": sys.version.split()[0]}))
"""


def smoke(root):
    """(ok, details or error text)."""
    vpy = venv_python(root)
    if not os.path.isfile(vpy):
        return False, "no venv at %s" % os.path.dirname(os.path.dirname(vpy))
    src = os.path.join(root, "DeepBump")
    bad = verify(src)
    if bad:
        return False, "; ".join(bad)
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")   # DeepBump prints U+2192 arrows
    try:
        p = subprocess.run([vpy, "-B", "-c", SMOKE, src], capture_output=True, text=True, timeout=300, env=env)
    except subprocess.TimeoutExpired:
        return False, "smoke test timed out"
    if p.returncode:
        return False, (p.stderr.strip().splitlines() or ["exit %d" % p.returncode])[-1]
    info = json.loads(p.stdout.strip().splitlines()[-1])
    return bool(info.pop("ok")), info


def main(argv):
    ap = argparse.ArgumentParser(prog="setup_deepbump.py", description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=default_root())
    ap.add_argument("--python", default=sys.executable, help="interpreter for the venv (default: this one)")
    ap.add_argument("--check", action="store_true", help="only report whether DeepBump is installed and works")
    a = ap.parse_args(argv)
    root = os.path.abspath(a.root)
    if a.check:
        ok, info = smoke(root)
        print("DeepBump %s at %s: %s" % ("works" if ok else "unavailable", root, info))
        return 0 if ok else 1
    os.makedirs(root, exist_ok=True)
    try:
        if verify(os.path.join(root, "DeepBump")):
            download(root)
        else:
            print("DeepBump %s already present" % COMMIT[:12])
        make_venv(root, a.python)
    except (OSError, RuntimeError, subprocess.CalledProcessError, zipfile.BadZipFile) as e:
        print("setup failed: %s" % e, file=sys.stderr)
        return 1
    ok, info = smoke(root)
    if not ok:
        print("DeepBump installed but the smoke test failed: %s" % info, file=sys.stderr)
        return 1
    record = {"commit": COMMIT, "source": URL, "licence": "GPL-3.0", "files": PINNED, "root": root,
              "installed": datetime.datetime.now().isoformat(timespec="seconds")}
    record.update(info)
    with open(os.path.join(root, "deepbump.json"), "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
    print("DeepBump works at %s (python %s, onnxruntime %s)" % (root, info["python"], info["onnxruntime"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
