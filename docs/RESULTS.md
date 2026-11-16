# Results: reference machine

Intel Core Ultra 9 275HX (8 P + 16 E cores), RTX 5070 Laptop GPU (8 GB, PCIe 5), 64 GB DDR5, Windows 11; llama.cpp
b9413 (CUDA, MSVC); Qwen3.6-35B-A3B APEX I-Compact (16.1 GiB, 40 layers, MoE 256 experts / 8 active, hybrid attention:
one layer in four keeps a KV cache). Raw data: `bench/ultra-9-275hx_rtx-5070-laptop-gpu-8g_63g.jsonl`.

## Findings (2026-11-16)

1. **VRAM is a hard wall, not a soft one.** With this driver, an allocation past the 8 GB fails (`cudaMalloc failed:
   out of memory`) rather than spilling into shared system memory. The usable budget is about 7.3 to 7.4 GB of the
   8.15 GB and moves with what the desktop has on the GPU, so leave a margin: one configuration passed and then failed
   at the same settings on the next run.
2. **Each MoE layer's experts cost about 330 MiB of VRAM.** The non-expert part of the model is about 2.1 GiB; all 40
   expert layers would need about 13 GiB more.
3. **Experts on the GPU buy less than expected.** At 32k context, 8 sequences: all experts on the CPU (`nCpuMoe 40`)
   82 tok/s total, `nCpuMoe 34` 95, `nCpuMoe 29` 104. One sequence: 42.5, 45, 52. Spending VRAM on context and
   concurrency instead is usually the better trade.
4. **Threads: 16 is best** (of 24 cores: 8 P + 16 E). 58 / 115 tok/s (1 / 8 sequences) against 48 / 90 at 8 threads and
   50 / 98 at 24.
5. **ubatch buys prefill, not decode.** 512 / 1024 / 2048: prefill 880 / 1240 / 1520 to 1610 tok/s on a 4k prompt, for
   about 0.5 / 1.5 GB more VRAM. Decode is the bottleneck for agent work, so ubatch stays at 512 unless prompts dominate.
6. **Concurrency saturates near 8.** Decode for all sequences: about 58 (B=1), 100 (B=4), 110 to 115 (B=8), 106 (B=16).
   Per-sequence speed falls roughly as 1/B past 4.
7. **Context is fairly cheap** (one layer in four keeps a KV cache): about 10 to 20 KB per token at q8_0.

The triangle sweep (placement x total context x depth x concurrency) is in the history and the tuning page; the chosen
configuration and its reasons are below once the sweep is complete.
