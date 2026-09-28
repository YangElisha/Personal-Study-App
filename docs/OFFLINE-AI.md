# OFFLINE AI — Ollama + Qwen on Elisha's laptop

## Your hardware → your model

NVIDIA GeForce RTX with **8 GB** dedicated memory, **16 GB** system RAM (plus an AMD 780M
integrated GPU, which we don't use).

**Model: Qwen3.5 9B** (`qwen3.5:9b`). About 6 GB at its standard size, so it fits entirely on
the RTX. It reads images as well as text, so it covers picture slides too — one model.

Hermes is not needed.

## Memory settings (set once)

Two Windows environment variables halve the memory a long prompt needs, which lets a longer
context fit on the 8 GB card:

```
setx OLLAMA_FLASH_ATTENTION 1
setx OLLAMA_KV_CACHE_TYPE q8_0
```

Then quit Ollama from the system tray and start it again so it picks them up.

## Context size — the setting that decides whether content gets dropped

Ollama uses a small context by default and **silently cuts off** anything longer — the exact
failure that cost an exam. The AI router sends `options.num_ctx` on every request, from
`OLLAMA_NUM_CTX` in `.env`:

- start at **16384**
- ask something long, then run `ollama ps`: the PROCESSOR column must say **100% GPU**
- if it does, you can try **32768**; if it shows any CPU share, go back down

If a prompt is bigger than the context, the router must refuse it loudly, never let Ollama
truncate it. Drill's own chunking then takes smaller bites.

How (Phase 5): instead of estimating, the router sends `truncate:false` (and `shift:false`),
so Ollama itself counts the prompt's tokens exactly and refuses one that doesn't fit; the app
shows "Prompt is too long for Qwen: N tokens, limit 16384 (OLLAMA_NUM_CTX)…". Checked with
the real model on 2026-09-28: a 16,104-token prompt arrived whole (markers at both ends
echoed); 16,512- and 18,671-token prompts were refused. Without `truncate:false`, a 13,929-
token prompt at num_ctx 2048 was silently cut to 1,026 tokens — the failure this prevents.

Measured on this laptop, 2026-09-28 (flash attention on, KV cache q8_0, ~7 GB of the 8 GB
free when the model loaded): num_ctx **8192 → 100% GPU**; **12288 and 16384 → 12%/88%
CPU/GPU** (33 of 34 layers on the GPU). So 16384 does not fully fit today.

## Checks

```
ollama run qwen3.5:9b "Reply with the word ready"
ollama ps
```

## What to expect from Qwen

Good: teacher chat, study-guide explanations, reading picture slides, re-reading slides the
self-check flags. Weaker than Claude: essay marking and long extractions — which is why
Claude (via `claude -p`) is used when you're online.
