"""Run every repo check: conventions, structure lint, plain-Python tests and (optionally) Blender-hosted tests.

Host: plain Python 3.9+, standard library. numpy and PyYAML widen the plain test coverage (tests that need them
skip when they are missing). Blender-hosted tests run only when a Blender executable is given.

    python tools/run_checks.py                                   # conventions, lint, plain tests
    python tools/run_checks.py --blender "C:/path/to/blender.exe"    # plus tools/tests/blender/test_*.py
    BLENDER=/path/to/blender python tools/run_checks.py              # same, from the environment

Exit 1 if anything failed. Blender tests build their fixtures in temp folders and never touch the repo.
"""

import argparse
import glob
import os
import subprocess
import sys
import time

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
TESTS = os.path.join(ROOT, "tools", "tests")


def run(title, cmd, timeout=None):
    print("=== %s" % title, flush=True)
    t0 = time.time()
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        p = subprocess.run(cmd, cwd=ROOT, env=env, timeout=timeout)
        code = p.returncode
    except subprocess.TimeoutExpired:
        print("TIMEOUT after %d s" % timeout)
        code = -1
    print("=== %s: %s (%.1f s)\n" % (title, "ok" if code == 0 else "FAILED (exit %s)" % code, time.time() - t0),
          flush=True)
    return code == 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--blender", default=os.environ.get("BLENDER"), help="Blender executable for tools/tests/blender")
    ap.add_argument("--only", help="run only tests whose file name contains this text")
    ap.add_argument("--timeout", type=int, default=600, help="seconds per Blender test (default 600)")
    args = ap.parse_args()

    py = [sys.executable, "-B"]
    results = {}
    if not args.only:
        results["conventions"] = run("conventions", py + [os.path.join("tools", "check_conventions.py")])
        results["lint"] = run("lint", py + [os.path.join("tools", "lint_skills.py")])
    pattern = "test_*%s*.py" % args.only if args.only else "test_*.py"
    if glob.glob(os.path.join(TESTS, pattern)):
        results["plain tests"] = run("plain tests", py + ["-m", "unittest", "discover", "-s", TESTS, "-p", pattern])
    blender_tests = sorted(glob.glob(os.path.join(TESTS, "blender", pattern)))
    if args.blender:
        for t in blender_tests:
            name = "blender " + os.path.basename(t)
            results[name] = run(name, [args.blender, "-b", "--factory-startup", "--python-exit-code", "1",
                                       "--python", t], timeout=args.timeout)
    elif blender_tests:
        print("=== %d Blender test(s) skipped: pass --blender or set BLENDER\n" % len(blender_tests))

    failed = [k for k, ok in results.items() if not ok]
    if not results:
        print("no check matched%s" % (" --only %r" % args.only if args.only else ""))
        sys.exit(1)
    print("%d check(s) run, %d failed%s" % (len(results), len(failed), (": " + ", ".join(failed)) if failed else ""))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
