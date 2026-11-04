#!/usr/bin/env python3
"""Generate or edit one image through the Codex CLI without hangs, swapped files or dropped references.

Host: plain Python 3.9+, standard library. Needs the Codex CLI on PATH (or CODEX_BIN) after `codex login`.
ffmpeg on PATH is optional; it turns PNG references into JPG.

    python codex_image.py "<prompt or @prompt.txt>" out.png [--ref room.jpg] [--size 1536x1024] [--force]

Prints the absolute output path on stdout. Exit codes:
  0 saved | 1 usage | 2 no image | 3 reference not passed to the image tool | 124 timed out
"""

import argparse
import glob
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
PNG_END = b"IEND\xaeB`\x82"


def err(msg):
    print("codex_image: %s" % msg, file=sys.stderr, flush=True)


def codex_home():
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def complete_png(path):
    """True once the file is a whole PNG, so a half-written image is never copied."""
    try:
        with open(path, "rb") as f:
            if f.read(8) != PNG_MAGIC:
                return False
            f.seek(-8, os.SEEK_END)
            return f.read() == PNG_END
    except OSError:
        return False


def session_image(thread_id):
    """The oldest complete PNG in this run's own session folder. Never looks at another session."""
    folder = codex_home() / "generated_images" / thread_id
    found = sorted((p for p in folder.glob("*.png") if complete_png(p)), key=lambda p: p.stat().st_mtime)
    return found[0] if found else None


def reference_passed(thread_id, n_refs):
    """Read the session log: True or False for the image call, None if no call can be found."""
    pattern = str(codex_home() / "sessions" / "*" / "*" / "*" / ("rollout-*%s.jsonl" % glob.escape(thread_id)))
    seen = False
    for log in glob.glob(pattern):
        with open(log, encoding="utf-8", errors="ignore") as f:
            for line in f:
                try:
                    payload = json.loads(line).get("payload") or {}
                except (ValueError, AttributeError):
                    continue
                call = str(payload.get("input") or payload.get("arguments") or "")
                if "image_gen" not in call and "imagegen" not in str(payload.get("name") or ""):
                    continue
                seen = True
                m = re.search(r"num_last_images_to_include\D{0,4}(\d+)", call)
                if m and int(m.group(1)) >= n_refs:
                    return True
    return False if seen else None


def build_instruction(prompt, n_refs, size):
    parts = ["Use the $imagegen image generation tool exactly once."]
    if n_refs:
        parts.append(
            "This is an edit of the attached image(s), not a new image: pass num_last_images_to_include:%d in that "
            "call so they reach the tool, and preserve everything the change does not mention." % n_refs)
    parts.append(
        "Do not save, copy, move, list, search for or view any file, and do not call the tool again: the caller "
        "collects the image from your session. End your turn straight after the call.")
    if size:
        parts.append("Image size: %s." % size)
    parts.append(("Change to make: " if n_refs else "Image description: ") + prompt)
    return " ".join(parts)


def prepare_refs(refs, keep_png, workdir):
    """PNG references become JPG: every PNG-fed furniture pass in the 2026-11-04 run lost the room (correlation)."""
    out = []
    ffmpeg = shutil.which("ffmpeg")
    for i, path in enumerate(refs):
        if path.suffix.lower() == ".png" and not keep_png:
            if ffmpeg:
                jpg = Path(workdir) / ("ref_%d.jpg" % i)
                done = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(path), "-q:v", "2", str(jpg)],
                                      stdin=subprocess.DEVNULL, capture_output=True, text=True)
                if done.returncode == 0:
                    out.append(jpg)
                    continue
                err("ffmpeg could not convert %s, sending the PNG: %s" % (path.name, done.stderr.strip()))
            else:
                err("ffmpeg not found, sending %s as PNG; check the room survived" % path.name)
        out.append(path)
    return out


def kill_tree(proc):
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def run(args):
    if not args.prompt:
        err("prompt is empty")
        return 1
    prompt = args.prompt
    if prompt.startswith("@"):
        prompt = Path(prompt[1:]).read_text(encoding="utf-8").strip()
    output = Path(args.output).resolve()
    if output.suffix.lower() != ".png":
        err("output must be a .png")
        return 1
    refs = [Path(r).resolve() for r in args.ref]
    if len(refs) > 4:
        err("at most 4 --ref images")
        return 1
    for ref in refs:
        if not ref.is_file():
            err("reference not found: %s" % ref)
            return 1
        if ref == output:
            err("output would overwrite its own reference: %s" % ref)
            return 1
    if output.exists() and not args.force:
        err("output exists, pass --force to replace it: %s" % output)
        return 1
    codex = shutil.which(os.environ.get("CODEX_BIN") or "codex")
    if not codex:
        err("codex CLI not found on PATH")
        return 1

    with tempfile.TemporaryDirectory(prefix="codex_image_") as work:
        # A scratch working root and a read-only sandbox: nothing to save into, and the project stays untouched.
        cmd = [codex, "exec", "--json", "-C", work, "-s", "read-only", "--skip-git-repo-check",
               "-m", args.model, "-c", 'model_reasoning_effort="%s"' % args.effort, "-c", 'service_tier="default"']
        for ref in prepare_refs(refs, args.keep_png_refs, work):
            cmd += ["-i", str(ref)]
        # The prompt goes on stdin, which is then closed, so Codex can never wait for more input.
        cmd += ["--", "-"]
        kwargs = {} if os.name == "nt" else {"start_new_session": True}
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                encoding="utf-8", errors="replace", **kwargs)
        state = {"thread": None, "tail": []}

        def read_events():
            for line in proc.stdout:
                state["tail"] = (state["tail"] + [line.rstrip()])[-20:]
                if state["thread"] is None:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(event, dict) and event.get("type") == "thread.started":
                        state["thread"] = event.get("thread_id")

        threading.Thread(target=read_events, daemon=True).start()
        try:
            proc.stdin.write(build_instruction(prompt, len(refs), args.size))
            proc.stdin.close()
        except OSError:
            pass  # Codex already exited; the loop below reports it

        start = time.monotonic()
        image = None
        exited_at = None
        try:
            while True:
                elapsed = time.monotonic() - start
                if state["thread"]:
                    image = session_image(state["thread"])
                    if image:
                        break
                elif elapsed > args.start_timeout:
                    err("no Codex session after %gs. Last output: %s" % (args.start_timeout, state["tail"][-5:]))
                    return 124
                if elapsed > args.timeout:
                    err("timed out after %gs" % args.timeout)
                    return 124
                if proc.poll() is not None:
                    exited_at = exited_at or time.monotonic()
                    if time.monotonic() - exited_at > 2:  # let a last image reach the disk
                        err("no image in this session (codex exit %s). Last output:" % proc.returncode)
                        for line in state["tail"]:
                            print(line, file=sys.stderr)
                        return 2
                time.sleep(args.poll)
        finally:
            kill_tree(proc)  # the first image is the result, so a retry cannot spend more quota

        thread = state["thread"]
        if refs:
            passed = reference_passed(thread, len(refs))
            if passed is False:
                err("the image call did not include the reference, so the result ignores it. Not saved. "
                    "Session image: %s" % image)
                return 3
            if passed is None:
                err("could not find the image call in the session log; check the reference was used")
        output.parent.mkdir(parents=True, exist_ok=True)
        partial = output.with_name(output.name + ".part")
        shutil.copyfile(image, partial)
        os.replace(partial, output)
    err("session %s, %.0fs" % (thread, time.monotonic() - start))
    print(output)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prompt", help="the prompt, or @file to read it from a UTF-8 text file")
    ap.add_argument("output", help="output .png path")
    ap.add_argument("--ref", action="append", default=[], help="reference to edit or match; repeatable, at most 4")
    ap.add_argument("--size", default="", help="for example 1536x1024")
    ap.add_argument("--force", action="store_true", help="replace an existing output")
    ap.add_argument("--keep-png-refs", action="store_true", help="send PNG references as they are, e.g. for alpha")
    ap.add_argument("--model", default="gpt-6-luna", help="model driving the tool (default checked 2026-11-04)")
    ap.add_argument("--effort", default="low")
    ap.add_argument("--timeout", type=float, default=420, help="seconds for the whole run")
    ap.add_argument("--start-timeout", type=float, default=60, help="seconds for Codex to open a session")
    ap.add_argument("--poll", type=float, default=0.5, help=argparse.SUPPRESS)
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
