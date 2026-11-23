"""Installed versus latest backend versions: `python -m sub0llmengine.versions [llamacpp|strata|basalt ...] [--json]`.

Check only. Updates change the owner's installed runtimes, so they stay explicit and manual: `strata update` for
Strata (signed feed, switches only after a test start), the release page for Basalt, a deliberate pull and build for
llama.cpp. Basalt has no `--version` and no verified release feed, so its installed version is the `basaltVersion` key.
"""
import argparse
import json
import os
import re
import subprocess
import urllib.request

# Latest-release sources; the llama.cpp latest is shown but not compared. Basalt has none.
SOURCES = {"llamacpp": "ggml-org/llama.cpp", "strata": "Niko1221/Strata", "basalt": None}


def _run(argv, cwd=None):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=15, cwd=cwd).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _latest(repo):
    """The newest GitHub release tag, or None when unreachable."""
    try:
        req = urllib.request.Request("https://api.github.com/repos/%s/releases/latest" % repo,
                                     headers={"Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)["tag_name"]
    except (OSError, ValueError, KeyError):
        return None


def _gitRoot(path):
    d = path or ""
    for _ in range(6):
        d = os.path.dirname(d)
        if d and os.path.exists(os.path.join(d, ".git")):
            return d
    return None


def installed(name, cfg):
    """(version, note) of the configured backend, or (None, why)."""
    if name == "llamacpp":
        root = _gitRoot(cfg.get("binDir"))
        out = _run(["git", "-C", root, "describe", "--tags", "--always"]) if root else ""
        return (out, "git describe") if out else (None, "no binDir or not a git checkout")
    if name == "strata":
        binary = cfg.get("strataBin")
        out = _run([binary, "--version"]) if binary else ""
        # "strata 0.2.20 (build 0.1.66; ...)": the control app version, then the engine build.
        m = re.match(r"strata (\S+)(?: \(build ([\d.]+))?", out)
        return (m.group(1), "engine build " + (m.group(2) or "unknown")) if m else (None, "strataBin not set or unreadable")
    version = cfg.get("basaltVersion")
    return (version, "basaltVersion config key") if version else (None, "set basaltVersion")


def _parts(v):
    return tuple(int(p) for p in re.findall(r"\d+", v or "")) or (0,)


def check(names=None):
    from . import config
    cfg = config.load()
    rows = []
    for name in names or SOURCES:
        have, note = installed(name, cfg)
        latest = _latest(SOURCES[name]) if SOURCES[name] else None
        # llama.cpp checkouts are pinned to a build commit, so only the semver backends are compared.
        newer = name != "llamacpp" and bool(have and latest and _parts(latest) > _parts(have))
        rows.append(dict(name=name, installed=have, latest=latest, updateAvailable=newer, note=note))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("backends", nargs="*", choices=list(SOURCES))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rows = check(args.backends or None)
    if args.json:
        print(json.dumps(rows, indent=2))
        return
    for r in rows:
        flag = "UPDATE" if r["updateAvailable"] else "ok" if r["installed"] else "?"
        print("%-9s %-7s installed %-24s latest %-10s (%s)" % (r["name"], flag, r["installed"] or "-", r["latest"] or "-", r["note"]))


if __name__ == "__main__":
    main()
