"""Model lookup: an alias, registry id or plain file path -> (absolute file path, registry id or None).

Models live in a Sub0LlmModelRegistry folder (https://github.com/CraigHutchinson/Sub0LlmModelRegistry). When its Python
package is importable (installed, or a sibling checkout ../Sub0LlmModelRegistry) it resolves ids and supplies the GGUF
facts; otherwise the folder's generated registry.json is read directly, so the package is optional. A plain file path in
the "model" key is used as-is, so the registry itself is optional.
"""
import os
import re
import sys

from . import config

_SIBLING = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "Sub0LlmModelRegistry")


def package():
    """The sub0llmregistry module, or None."""
    try:
        import sub0llmregistry
        return sub0llmregistry
    except ImportError:
        if os.path.isdir(os.path.join(_SIBLING, "sub0llmregistry")) and _SIBLING not in sys.path:
            sys.path.append(_SIBLING)
            try:
                import sub0llmregistry
                return sub0llmregistry
            except ImportError:
                pass
    return None


def root(cfg):
    r = os.environ.get("SUB0_MODEL_REGISTRY") or cfg.get("registry") or ""
    if not config.IS_WINDOWS and re.match(r"^[A-Za-z]:[\\/]", r):  # a Windows path seen from WSL
        r = "/mnt/" + r[0].lower() + "/" + r[3:].replace("\\", "/")
    return r


def resolve(cfg, ref=None):
    """Returns (path, registry id or None)."""
    ref = ref or cfg.get("model") or ""
    if os.path.isfile(ref):
        return ref, None
    r = root(cfg)
    pkg = package()
    if pkg and r:
        try:
            return pkg.Registry(r).resolve(ref)
        except (KeyError, ValueError) as e:
            raise SystemExit("model '%s': %s" % (ref, e))
    reg = config.loadJson(os.path.join(r, "registry.json")) if r else None
    if not reg:
        raise SystemExit("model '%s' is not a file and no registry.json was found under '%s' (set 'registry' or SUB0_MODEL_REGISTRY)" % (ref, r))
    rid = reg.get("aliases", {}).get(ref, ref)
    base, _, fname = rid.partition("#")
    entry = reg.get("entries", {}).get(base)
    if not entry:
        raise SystemExit("no registry entry for '%s'" % rid)
    rel = entry.get("dir") or (os.path.relpath(entry["path"], reg["root"]) if config.IS_WINDOWS else entry["path"][len(reg["root"]):].lstrip("\\/"))
    folder = os.path.normpath(os.path.join(r, rel.replace("\\", "/")))
    if not fname:
        ggufs = sorted(f["name"] for f in entry["files"]
                       if f["name"].endswith(".gguf") and "mmproj" not in f["name"] and not re.search(r"-0000[2-9]-of-", f["name"]))
        fname = ggufs[0] if ggufs else ""
    return os.path.join(folder, fname.replace("\\", "/")) if fname else folder, rid


def facts(cfg, ref=None):
    """The registry's facts for the model (GGUF header facts: layer and expert bytes, KV bytes per token, ...), or {}."""
    try:
        _, rid = resolve(cfg, ref)
    except SystemExit:
        return {}
    if not rid:
        return {}
    base = rid.partition("#")[0]
    pkg = package()
    if pkg:
        try:
            f = pkg.Registry(root(cfg)).get(base).get("facts") or {}
        except KeyError:
            return {}
    else:
        reg = config.loadJson(os.path.join(root(cfg), "registry.json")) or {}
        f = (reg.get("entries", {}).get(base) or {}).get("facts") or {}
    if "byFile" in f:
        f = f["byFile"].get(rid.partition("#")[2]) or next(iter(f["byFile"].values()), {})
    return f
