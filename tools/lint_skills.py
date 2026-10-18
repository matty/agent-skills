"""Lint the skills' structure: frontmatter, README rows, ASCII, links between files, script headers.

tools/check_conventions.py checks that facts duplicated across skills agree; this checks that each skill is well
formed. Errors fail the run; warnings are budgets worth keeping (description length, SKILL.md length).

Host: plain Python 3.9+, standard library. Run from anywhere:
    python tools/lint_skills.py            # exit 1 on any error
"""

import ast
import os
import re
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SKILLS = os.path.join(ROOT, "skills")

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
DESC_MAX = 1024          # Agent Skills spec and the Claude platform: hard limit
DESC_SOFT = 500          # house budget: Codex and Claude Code shorten or drop descriptions past a shared budget
DESC_TOTAL_SOFT = 6500   # all of this repo's descriptions together (the shared listing fallback is 8,000 characters)
BODY_SOFT = 200          # SKILL.md body lines before it stops being skimmable (the spec's hard advice is 500)
BODY_MAX = 500
TEXT_EXT = (".md", ".py", ".cs", ".shader", ".cginc", ".hlsl", ".yaml", ".yml", ".json", ".txt", ".mmd")
SCRIPT_EXT = (".py", ".cs", ".shader")
HOST_LINES = 30          # a script states its host ("Host: ...") within its first lines
LOCAL_DIRS = ("references", "scripts", "templates")

ERRORS, WARNINGS = [], []


def rel(path):
    return os.path.relpath(path, ROOT).replace("\\", "/")


def err(path, msg):
    ERRORS.append("%s: %s" % (rel(path), msg))


def warn(path, msg):
    WARNINGS.append("%s: %s" % (rel(path), msg))


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def skill_dirs():
    return sorted(d for d in os.listdir(SKILLS)
                  if os.path.isfile(os.path.join(SKILLS, d, "SKILL.md")))


def files_under(top):
    for base, dirs, files in os.walk(top):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            yield os.path.join(base, f)


# ---- frontmatter --------------------------------------------------------------------------------------------------

try:
    import yaml                     # strict parse when available (CI installs PyYAML)
except ImportError:
    yaml = None

# Characters that end or change a plain (unquoted) YAML scalar: without PyYAML, refuse them in values.
PLAIN_BREAKERS = re.compile(r": |\s#|^[\-?:,\[\]{}#&*!|>'\"%@`]")


def frontmatter(path):
    raw = read(path)
    if "\r\n" in raw:
        warn(path, "CRLF line endings: use LF (a linked install reads the working tree, not git's normalised copy)")
    text = raw.replace("\r\n", "\n")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        err(path, "no YAML frontmatter between --- lines at the top")
        return None, text
    block, body = m.group(1), text[m.end():]
    if yaml is not None:
        try:
            data = yaml.safe_load(block)
        except yaml.YAMLError as e:
            err(path, "frontmatter is not valid YAML (%s); a plain value cannot hold ': ' or ' #'"
                % str(e).splitlines()[0])
            return None, body
        if not isinstance(data, dict):
            err(path, "frontmatter is not a YAML mapping")
            return None, body
        for k, v in data.items():
            if not isinstance(v, str):
                err(path, "frontmatter %s is not a single-line string" % k)
        return {str(k): str(v) for k, v in data.items()}, body
    fields = {}
    for line in block.split("\n"):
        k, sep, v = line.partition(":")
        v = v.strip()
        if not sep or line[:1] in " \t":
            err(path, "frontmatter line is not a single-line key: value (%r)" % line[:60])
            continue
        if not (v[:1] in "'\"" and v[-1:] == v[:1]) and PLAIN_BREAKERS.search(v):
            err(path, "frontmatter %s is not a valid plain YAML value (': ', ' #' or a leading indicator): "
                      "reword it or quote it" % k.strip())
        fields[k.strip()] = v
    return fields, body


def check_skill(name):
    path = os.path.join(SKILLS, name, "SKILL.md")
    fields, body = frontmatter(path)
    if fields is None:
        return 0
    extra = sorted(set(fields) - {"name", "description"})
    if extra:
        warn(path, "frontmatter keys other than name and description: %s (Codex and the spec may reject them)"
             % ", ".join(extra))
    n = fields.get("name", "")
    if n != name:
        err(path, "name %r does not match the folder %r" % (n, name))
    if not NAME_RE.match(n) or len(n) > 64:
        err(path, "name %r is not lowercase-hyphenated, 64 characters or fewer" % n)
    d = fields.get("description", "")
    if not d:
        err(path, "description is missing or empty")
    if len(d) > DESC_MAX:
        err(path, "description is %d characters (limit %d)" % (len(d), DESC_MAX))
    elif len(d) > DESC_SOFT:
        warn(path, "description is %d characters (house budget %d): front-load the triggers and trim the list"
             % (len(d), DESC_SOFT))
    if "<" in d or ">" in d:
        err(path, "description contains < or > (the Claude platform forbids XML-like tags; Claude Code escapes them)")
    lines = body.count("\n")
    if lines > BODY_MAX:
        err(path, "SKILL.md body is %d lines (keep it under %d; move detail to references/)" % (lines, BODY_MAX))
    elif lines > BODY_SOFT:
        warn(path, "SKILL.md body is %d lines (house budget %d): move narrow detail to references/" % (lines, BODY_SOFT))
    return len(d)


# ---- text files: ASCII, cross-skill paths, local references -----------------------------------------------------

def check_ascii(path, text):
    for i, line in enumerate(text.splitlines(), 1):
        for j, ch in enumerate(line, 1):
            if ord(ch) > 127:
                err(path, "line %d col %d: non-ASCII character U+%04X" % (i, j, ord(ch)))
                break


def check_cross_skill(path, text, own, names):
    flat = text.replace("\\", "/")
    for other in names:
        if other == own:
            continue
        pat = r"(skills/%s/|\.\./%s/|(?<![\w-])%s/(scripts|references|templates)/)" % (
            re.escape(other), re.escape(other), re.escape(other))
        for m in re.finditer(pat, flat):
            line = flat.count("\n", 0, m.start()) + 1
            err(path, "line %d points into skill %s by path: name the skill instead" % (line, other))


LOCAL_REF = re.compile(r"(?<![\w./-])(?:\.\./)?((?:%s)/[A-Za-z0-9_./-]+)" % "|".join(LOCAL_DIRS))
SKILL_REF = re.compile(r"<skill>/((?:%s)/[A-Za-z0-9_./-]+)" % "|".join(LOCAL_DIRS))   # "<skill>/scripts/x.py"
MD_LINK = re.compile(r"\]\(([^)\s]+)\)")
CODE_SPAN = re.compile(r"(`+).*?\1")      # inline code: `ns["new_piece"](...)` is code, not a link to "..."
FENCE = re.compile(r"^\s*(```|~~~)")

_LISTINGS = {}


def exists_exact(p):
    """os.path.exists with the Linux CI's semantics on every OS: inside the repo, each path component must exist
    under exactly that name. Windows also accepts a wrong case and drops trailing dots and spaces ("..." reads as the
    folder itself), so a path only Windows accepts would pass a Windows run and fail CI. Lexical only: abspath and
    relpath would apply Windows' trimming first."""
    p = os.path.normpath(p)
    root = os.path.normpath(ROOT)
    if os.path.normcase(p[:len(root) + 1]) != os.path.normcase(root + os.sep):
        return os.path.exists(p)                      # outside the repo: nothing in a skill should point there
    cur = root
    for part in p[len(root) + 1:].split(os.sep):
        if part in ("", os.curdir):
            continue
        names = _LISTINGS.get(cur)
        if names is None:
            try:
                names = _LISTINGS[cur] = set(os.listdir(cur))
            except OSError:
                return False
        if part not in names:
            return False
        cur = os.path.join(cur, part)
    return True


def check_local_refs(path, text, skill_root):
    """Every references/, scripts/ or templates/ path a skill's markdown names must exist in that skill, and every
    relative Markdown link outside code must resolve (exact names, as on the Linux CI)."""
    here = os.path.dirname(path)
    fenced = False
    for i, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line):
            fenced = not fenced
        for m in SKILL_REF.finditer(line):
            target = m.group(1).rstrip(".,;:)").rstrip("/")
            if not any(c in target for c in "*{") and not exists_exact(os.path.join(skill_root, target)):
                err(path, "line %d names <skill>/%s, which does not exist in this skill" % (i, target))
        for m in LOCAL_REF.finditer(line):
            target = m.group(1).rstrip(".,;:)")
            if target.endswith("/"):
                target = target[:-1]
            if any(c in target for c in "*{"):
                continue
            if not exists_exact(os.path.join(skill_root, target)):
                err(path, "line %d names %s, which does not exist in this skill" % (i, target))
        if fenced or FENCE.match(line):
            continue                                  # a fenced code block holds code, not links
        for m in MD_LINK.finditer(CODE_SPAN.sub("", line)):
            target = m.group(1).split("#")[0]
            if not target or re.match(r"^[a-z]+:", target):
                continue
            if not exists_exact(os.path.join(here, target)):
                err(path, "line %d links to %s, which does not exist" % (i, target))


# ---- scripts --------------------------------------------------------------------------------------------------------

def check_script(path, text):
    head = "\n".join(text.splitlines()[:HOST_LINES])
    if "Host:" not in head:
        err(path, "no 'Host: ...' line in the first %d lines saying what the script runs in" % HOST_LINES)
    if path.endswith(".py"):
        try:
            ast.parse(text, filename=path)
        except SyntaxError as e:
            err(path, "Python syntax error: %s" % e)


# ---- README -----------------------------------------------------------------------------------------------------------

def check_readme(names):
    path = os.path.join(ROOT, "README.md")
    rows = re.findall(r"^\|\s*`([a-z0-9-]+)`\s*\|", read(path), re.M)
    for n in names:
        if n not in rows:
            err(path, "no table row for skill %s" % n)
    for r in rows:
        if r not in names:
            err(path, "table row for %s, which has no skills/%s/SKILL.md" % (r, r))
    if len(rows) != len(set(rows)):
        err(path, "a skill has more than one table row")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")     # a Windows console is often cp1252
    names = skill_dirs()
    total = 0
    for name in names:
        total += check_skill(name)
        root = os.path.join(SKILLS, name)
        for f in files_under(root):
            if not f.endswith(TEXT_EXT):
                continue
            text = read(f)
            check_ascii(f, text)
            check_cross_skill(f, text, name, names)
            if f.endswith(".md"):
                check_local_refs(f, text, root)
            if f.endswith(SCRIPT_EXT) and os.sep + "scripts" + os.sep in f:
                check_script(f, text)
    if total > DESC_TOTAL_SOFT:
        WARNINGS.append("descriptions total %d characters (house budget %d)" % (total, DESC_TOTAL_SOFT))
    check_readme(names)

    for w in WARNINGS:
        print("WARN  " + w)
    for e in ERRORS:
        print("ERROR " + e)
    print("%d skill(s), %d error(s), %d warning(s), descriptions %d characters"
          % (len(names), len(ERRORS), len(WARNINGS), total))
    sys.exit(1 if ERRORS else 0)


if __name__ == "__main__":
    main()
