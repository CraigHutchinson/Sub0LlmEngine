"""Sanity-check a model: plain prompts at temperature 0 at several GPU offloads.

  python tools/sanity.py MODEL BINDIR NGL[,NGL...] [KEY=VALUE ...]

Starts llama-server (127.0.0.1, the spike port) with the engine config, the model and each -ngl; KEY=VALUE overrides config keys."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sub0llmengine import config, registry, spike  # noqa: E402

model, bindir, ngls = sys.argv[1], sys.argv[2], [int(x) for x in sys.argv[3].split(",")]
extra = dict(kv.split("=", 1) for kv in sys.argv[4:])
cfg = dict(config.load(), model=model, binDir=bindir, ctx=4096, slots=1, **{k: (int(v) if v.lstrip("-").isdigit() else v) for k, v in extra.items()})
path, _ = registry.resolve(cfg)
os.makedirs(spike.axes.SPIKE_DIR, exist_ok=True)
for ngl in ngls:
    c = dict(cfg, gpuLayers=ngl)
    with spike.Server(c, path, spike.axes.SPIKE_DIR, os.path.join(spike.axes.SPIKE_DIR, "sanity.log")) as srv:
        if srv.loadSeconds is None:
            print(ngl, "did not start:", srv.failure())
            continue
        for prompt in ["The capital of France is", "<|im_start|>user\nWhat is 2+2? Answer in one word.<|im_end|>\n<|im_start|>assistant\n"]:
            r = spike.post(srv.base, "/completion", {"prompt": prompt, "n_predict": 24, "temperature": 0, "top_k": 1})
            print("ngl", ngl, "|", repr(prompt[:30]), "->", repr((r.get("content") or str(r.get("error")))[:120]).encode("ascii", "backslashreplace").decode())
