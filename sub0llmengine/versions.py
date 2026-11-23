"""Backend version checker and updater.

Checks the installed backend versions against their update sources
(GitHub releases for Strata and llama.cpp, the website for Basalt)
and reports whether updates are available.

Usage:
    python -m sub0llmengine.versions              # check all
    python -m sub0llmengine.versions strata        # check strata only
    python -m sub0llmengine.versions basalt        # check basalt only
    python -m sub0llmengine.versions llamacpp      # check llamacpp only
    python -m sub0llmengine.versions --update      # apply pending updates (interactive)
"""
import argparse
import json
import os
import re
import subprocess
import urllib.request
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Backend definitions: source repo / URL, detection command, update URL
# ---------------------------------------------------------------------------

BACKENDS = {
    "llamacpp": {
        "label": "llama.cpp",
        "source": "github",
        "repo": "ggml-org/llama.cpp",
        "detection_cmd": None,  # detected via binDir from config
        "config_key": "binDir",
        "update_url": "https://github.com/ggml-org/llama.cpp/releases",
    },
    "strata": {
        "label": "Strata",
        "source": "github",
        "repo": "Niko1221/Strata",
        "detection_cmd": ["strata", "--version"],
        "config_key": "strataBin",
        "update_url": "https://github.com/Niko1221/Strata/releases",
    },
    "basalt": {
        "label": "Basalt",
        "source": "github",
        "repo": "GiantPrince/Basalt",
        "detection_cmd": ["basalt", "--version"],
        "config_key": "basaltBin",
        "update_url": "https://basalt.jgulfo.com/",
    },
}


def _fetch_json(url):
    """Fetch a JSON URL and return parsed data, or None on failure."""
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _github_latest(repo):
    """Return (tag_name, published_at, html_url) from GitHub latest release."""
    data = _fetch_json(f"https://api.github.com/repos/{repo}/releases/latest")
    if not data:
        return None
    return (
        data["tag_name"],
        data["published_at"],
        data["html_url"],
    )


# ---------------------------------------------------------------------------
# Version detection
# ---------------------------------------------------------------------------

def _detect_llamacpp_version(cfg):
    """Detect llama.cpp version via git describe or binary mtime."""
    bindir = cfg.get(BACKENDS["llamacpp"]["config_key"]) or ""
    if not bindir:
        return None, None
    d = bindir
    for _ in range(5):
        d = os.path.dirname(d)
        if os.path.exists(os.path.join(d, ".git")):
            try:
                out = subprocess.run(
                    ["git", "-C", d, "describe", "--tags", "--always"],
                    capture_output=True, text=True, timeout=10,
                ).stdout.strip()
                if out:
                    return out, "installed"
            except Exception:
                pass
            break
    return "binary (no git)", "installed"


def _detect_strata_version(cfg):
    """Detect Strata version via strata --version or binary check."""
    strata_bin = cfg.get(BACKENDS["strata"]["config_key"])
    if not strata_bin:
        return None, None
    try:
        out = subprocess.run(
            [strata_bin, "--version"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        if out:
            return out, "installed"
    except Exception:
        pass
    return "binary present", "installed"


def _detect_basalt_version(cfg):
    """Detect Basalt version via basalt --version or config key."""
    basalt_bin = cfg.get(BACKENDS["basalt"]["config_key"])
    if not basalt_bin:
        return None, None
    try:
        out = subprocess.run(
            [basalt_bin, "--version"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        if out:
            return out, "installed"
    except Exception:
        pass
    # Fall back to config key if present
    version = cfg.get("basaltVersion")
    if version:
        return version, "installed"
    return "binary present", "installed"


# ---------------------------------------------------------------------------
# Version comparison
# ---------------------------------------------------------------------------

def _parse_version(v):
    """Parse a version string into a tuple of ints for comparison."""
    v = re.sub(r"^v", "", v or "")
    parts = re.findall(r"\d+", v)
    return tuple(int(p) for p in parts) if parts else (0,)


def _is_newer(latest, installed):
    """Return True if latest > installed."""
    return _parse_version(latest) > _parse_version(installed)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _load_cfg():
    """Load engine config layers."""
    from sub0llmengine import config
    return config.load()


# ---------------------------------------------------------------------------
# Check
# ---------------------------------------------------------------------------

def check(backend_names=None):
    """Check versions of specified backends (default: all).

    Returns a list of dicts: {name, label, installed, latest, available,
    published, update_url, repo}.
    """
    if backend_names is None:
        backend_names = list(BACKENDS.keys())
    cfg = _load_cfg()
    results = []
    for name in backend_names:
        info = BACKENDS.get(name)
        if not info:
            continue
        label = info["label"]
        installed_ver = None
        status = "installed"

        # Detect installed version
        if name == "llamacpp":
            installed_ver, status = _detect_llamacpp_version(cfg)
        elif name == "strata":
            installed_ver, status = _detect_strata_version(cfg)
        elif name == "basalt":
            installed_ver, status = _detect_basalt_version(cfg)

        # Get latest from source
        latest_ver = None
        published = None
        update_url = info.get("update_url", "")

        if info["source"] == "github":
            latest_data = _github_latest(info["repo"])
            if latest_data:
                latest_ver, published, update_url = latest_data

        available = latest_ver is not None and installed_ver is not None and _is_newer(latest_ver, installed_ver)

        results.append({
            "name": name,
            "label": label,
            "installed": installed_ver or "(not detected)",
            "latest": latest_ver or "(no release found)",
            "published": published,
            "available": available,
            "status": status,
            "update_url": update_url,
            "repo": info["repo"],
        })
    return results


def print_results(results):
    """Pretty-print version check results."""
    print()
    print("=" * 72)
    print("  Backend version check")
    print("=" * 72)
    for r in results:
        icon = "  " if r["available"] else "[OK]" if r["status"] == "installed" else "[?]"
        status_str = "UPDATE AVAILABLE" if r["available"] else "up to date" if r["status"] == "installed" else "not installed"
        pub = ""
        if r["published"]:
            dt = datetime.fromisoformat(r["published"].replace("Z", "+00:00"))
            pub = f"  (latest released {dt.strftime('%Y-%m-%d')})"
        print(f"\n  {icon} {r['label']}")
        print(f"     Installed : {r['installed']}")
        print(f"     Latest    : {r['latest']}{pub}")
        print(f"     Status    : {status_str}")
        if r["update_url"]:
            print(f"     Update    : {r['update_url']}")
    print()


# ---------------------------------------------------------------------------
# Update helpers
# ---------------------------------------------------------------------------

def _update_strata():
    """Attempt to update Strata via the strata CLI."""
    cfg = _load_cfg()
    strata_bin = cfg.get(BACKENDS["strata"]["config_key"])
    if not strata_bin:
        print("  Strata binary not configured (set 'strataBin' in engine config)")
        return False
    try:
        print(f"  Running: {strata_bin} update")
        subprocess.run([strata_bin, "update"], check=True, timeout=120)
        return True
    except subprocess.CalledProcessError as e:
        print(f"  Strata update failed with exit code {e.returncode}")
        return False
    except FileNotFoundError:
        print(f"  Strata binary not found at {strata_bin}")
        return False
    except Exception as e:
        print(f"  Strata update failed: {e}")
        return False


def _update_llamacpp():
    """Attempt to update llama.cpp via git pull."""
    cfg = _load_cfg()
    bindir = cfg.get(BACKENDS["llamacpp"]["config_key"])
    if not bindir:
        print("  llama.cpp binDir not configured (set 'binDir' in engine config)")
        return False
    # Walk up to find the git repo
    d = bindir
    repo_dir = None
    for _ in range(5):
        d = os.path.dirname(d)
        if os.path.exists(os.path.join(d, ".git")):
            repo_dir = d
            break
    if not repo_dir:
        print(f"  No git repo found near {bindir}")
        return False
    try:
        print(f"  Pulling in {repo_dir}")
        subprocess.run(["git", "-C", repo_dir, "pull"], check=True, timeout=120)
        return True
    except subprocess.CalledProcessError:
        print(f"  git pull failed in {repo_dir}")
        return False
    except Exception as e:
        print(f"  Update failed: {e}")
        return False


def _update_basalt():
    """Basalt updates are manual — direct the user to the website."""
    print("  Basalt updates are distributed via basalt.jgulfo.com")
    print("  Download the latest release and extract to your basaltBin path.")
    return False


def update(backend_names=None):
    """Apply updates for specified backends (interactive)."""
    if backend_names is None:
        backend_names = list(BACKENDS.keys())
    cfg = _load_cfg()
    updated = []
    for name in backend_names:
        info = BACKENDS.get(name)
        if not info:
            continue
        # Check if update is available
        if info["source"] == "github":
            latest = _github_latest(info["repo"])
            if not latest:
                continue
            installed = None
            if name == "llamacpp":
                installed, _ = _detect_llamacpp_version(cfg)
            elif name == "strata":
                installed, _ = _detect_strata_version(cfg)
            elif name == "basalt":
                installed, _ = _detect_basalt_version(cfg)
            if not installed or not _is_newer(latest[0], installed):
                continue
        print(f"\n  Updating {info['label']}...")
        if name == "strata":
            if _update_strata():
                updated.append(name)
        elif name == "llamacpp":
            if _update_llamacpp():
                updated.append(name)
        elif name == "basalt":
            _update_basalt()
    if updated:
        print(f"\n  Updated: {', '.join(BACKENDS[n]['label'] for n in updated)}")
    else:
        print("\n  No updates applied.")
    return updated


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Check/update backend versions")
    parser.add_argument(
        "backends",
        nargs="*",
        choices=list(BACKENDS.keys()),
        help="Backends to check (default: all)",
    )
    parser.add_argument("--update", action="store_true", help="Apply pending updates")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    names = args.backends if args.backends else None
    results = check(names)

    if args.json:
        print(json.dumps(results, indent=2))
        return

    if args.update:
        update(names)
    else:
        print_results(results)


if __name__ == "__main__":
    main()
