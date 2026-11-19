# Qwen3.6-35B-A3B generation and template settings

Qwen recommends the following request parameters. Set repeat_penalty (the llama.cpp name for repetition_penalty) to 1.0, top_k to 20 and min_p to 0.0 in all three modes.

| Intended use | enable_thinking | temperature | top_p | presence_penalty |
|---|---|---:|---:|---:|
| General thinking | true | 1.0 | 0.95 | 1.5 |
| Precise coding with thinking | true | 0.6 | 0.95 | 0.0 |
| Direct instruction | false | 0.7 | 0.80 | 1.5 |

Qwen says presence penalties can reduce endless repetition. Higher values can harm quality or mix languages. In Sub0Squad's coding repair, compare presence=0 and presence=1.5 in the engine specification with other parameters held fixed. Squad maps presence to presence_penalty on the request. Prompt plus generation must fit the available context. [Qwen model card](https://huggingface.co/Qwen/Qwen3.6-35B-A3B)

For a precise-coding thinking turn, merge these parameters into the request body alongside the model, messages and reply limit.

```json
{
  "temperature": 0.6,
  "top_p": 0.95,
  "top_k": 20,
  "min_p": 0.0,
  "presence_penalty": 0.0,
  "repeat_penalty": 1.0,
  "chat_template_kwargs": {"enable_thinking": true}
}
```

## Windows template behavior

On 2026-11-19 the shared qwen35 endpoint served the Mudler APEX I-Compact GGUF, with four slots and an n_ctx value of 65,536 in /v1/models. The engine status separately reported a 106,496-token shared pool. The server identified its build as b0-unknown. The template returned by /props and the upstream Qwen template use enable_thinking and preserve_thinking. Qwen3.6 uses these settings in place of text commands such as /nothink. The installed template has no reasoning_effort variable. [Quantized model](https://huggingface.co/mudler/Qwen3.6-35B-A3B-APEX-GGUF) · [Upstream template](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/raw/main/chat_template.jinja)

Send chat_template_kwargs with enable_thinking=true for planning or false for a direct act turn. Four /apply-template probes with a historical assistant reasoning marker confirmed that true produced an open think block and false produced an empty closed block. The marker appeared only with preserve_thinking=true, in either mode. These probes exercised rendering without generation.

Use the embedded template for these controls. For a harness-specific template, compare generation suffixes, tool round trips, historical reasoning and special tokens against the active GGUF before measuring workflow quality. Current upstream llama.cpp exposes a reasoning budget and a message before the closing tag. On the shared Windows qwen35 server, Sub0Squad replayed an actual planning request with max_tokens=768. An uncapped request hit that limit entirely in reasoning. Adding the request-level thinking_budget_tokens=160 returned a complete visible plan in 311 completion tokens. Thinking off returned a complete plan in 241 tokens. These results establish the behavior on this running build as a request-level experiment. Check support on other builds before using it and validate the act turn through the workflow gate. [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
