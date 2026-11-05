# Model options within the 96 GB budget

Research done Nov 5 2026. Question: which open-weight models fit the competition's model budget and could beat
our current `qwen3.8-27b` on Terminal-Bench, and what would it take to host one ourselves.
No benchmark jobs were run for this. All numbers below are published numbers, with the source next to them.

## Bottom line

- **No candidate within 96 GB has published evidence of scoring higher than Qwen3.8-27B on Terminal-Bench.**
  On the vendors' own numbers, Qwen3.8-27B (73.0 on TB 2.1) is still ahead of everything that fits.
- **The case for switching is speed, not smarts.** About half our failures are time limits, and 71% of task
  time is the model writing. MoE models with 5–12B active parameters should decode several times faster than a
  27B dense model on the same GPU.
- **Best bet to test:** Poolside **Laguna S 2.1** (118B total, 8B active, 70.2 on TB 2.1, official 4-bit
  checkpoints at 72 GB). Runner-up: **Nemotron 3.5 Super** (120B, 12B active, 60.7–62.8 on TB 2.1, official
  NVFP4).
- **Next step:** ask the organizers the questions at the end first. Then rent one H200 (about $3.60–5.30/hr)
  for an afternoon, serve Laguna S 2.1 INT4 with vLLM, and run `eval/slow_subset.txt` against the
  `full-all-v1` numbers. Expect about $20–40 for that test.

## Read this first: the scores don't line up

- Our 56/89 (63%) is **Terminal-Bench 2.0**, run with **our own mini-swe-agent harness**, with the tasks'
  normal time limits (15–60 min).
- Most vendor numbers are **TB 2.0 or 2.1**, run with **Terminus 2** (the Harbor reference harness), often
  with a **3-hour timeout and 32 CPU / 48 GB RAM** (Qwen's footnote). Those are not our conditions.
- **TB 2.1 is not TB 2.0.** 2.1 fixes 28 of the 89 tasks, and most agent-model pairs score 1–12 points
  higher on it ([tbench.ai: TB 2.1](https://www.tbench.ai/news/terminal-bench-2-1)).
- **Vendor and independent numbers differ a lot.** Qwen3.8-27B: 73.0 on TB 2.1 on its own model card, but
  58.43 on the independent Vals AI board (Terminus 2). Assume every vendor number is 10–15 points optimistic
  until someone else reproduces it.
- So none of the numbers below predicts what a model would score in `mini_agent`. They only rank models
  roughly. Only our own run on our own task list answers the question.

## Comparison table

Sorted by evidence strength for "could match or beat Qwen3.8-27B for us". Sizes are weights only unless noted.

| Model | Total / active | Weights at a precision that fits | Fits 96 GB? | Best TB score (version, harness, source type) | Thinking off switch | License |
|---|---|---|---|---|---|---|
| **Qwen3.8-27B (current)** | 28B dense | FP8 official (size not stated; about 30 GB est.) | Yes, easily | 73.0 TB 2.1 (vendor, row labelled "Terminus") · 58.43 TB 2.1 (Vals, Terminus 2) · **our 63% TB 2.0 (mini_agent)** | `enable_thinking: false` | Apache-2.0 |
| **Laguna S 2.1** (Poolside) | 118B / 8B | INT4 72 GB, NVFP4 72 GB (official) | Yes, about 20 GB spare | 70.2 TB 2.1 (Artificial Analysis, per Poolside's card) | `enable_thinking: false` | OpenMDW-1.1 |
| **Nemotron 3.5 Super VL** (NVIDIA) | 120B / 12B | NVFP4 official (size not stated; about 70–80 GB est.) | Probably | 60.67 (BF16) / 62.78 (NVFP4) TB 2.1 (vendor, NeMo Gym) · 66.7 on llm-stats (unverified) | `enable_thinking: false` | OpenMDW-1.1 |
| **Ling 3.0 Flash** (inclusionAI) | 124B / 5.1B | INT4 77 GB on disk, 70.3 GiB loaded | Yes, tight with KV cache | **50.19 TB 2.1 (Vals, Terminus 2, independent)** · 57.0 (self-reported, llm-stats) | `enable_thinking: false` | MIT |
| **Qwen3.6-35B-A3B** | 35B / 3B | BF16 about 70 GB; FP8 not confirmed | Yes | 51.5 TB 2.0 (vendor, Terminus 2, 3 h timeout) | `enable_thinking: false` | Apache-2.0 |
| **Qwen3.5-122B-A10B** | 122B / 10B | No official 4-bit; community quants only (about 65 GB est.) | Yes at 4-bit | 49.4 TB 2.0 (vendor, harness not stated) | `enable_thinking: false` | Apache-2.0 |

Considered and dropped (weaker on the same kind of evidence, or too big):

| Model | Why dropped |
|---|---|
| Qwen3-Coder-Next (80B / 3B) | 36.2 TB 2.0 (vendor). No thinking mode. |
| Devstral 2 (123B dense) | 32.6 TB 2 (vendor). Dense 123B would be slower than what we have. |
| gpt-oss-120b (117B / 5.1B, MXFP4) | 18.7 TB 2.0 (as listed on Qwen3.5-122B's card). Reasoning can't be turned off, only set to low. |
| Gemma 4 31B | 42.9 TB 2.0 (as listed on Qwen3.6's card). |
| Nemotron 3.5 Bolt (74B / 9B) | Ships as **2-bit** to fit 24 GB: breaks the "4-bit or higher" rule. 51.0 TB 2.1 self-reported. |
| GLM-5.3-Flash (320B / 18B), MiniMax-M3 (about 428B / 23B), MiMo-V2.6-Flash (309B / 15B) | Too big for 96 GB even at 4-bit. |

## Per-model notes

### Qwen3.8-27B (baseline)

- 28B dense, vision-language, 262K context, Apache-2.0
  ([model card](https://huggingface.co/Qwen/Qwen3.8-27B)).
- Thinking on by default; `chat_template_kwargs: {"enable_thinking": false}` turns it off. Also has
  `reasoning_effort` (`xhigh` default, `medium`, `low`) and `preserve_thinking`. **We don't use
  `reasoning_effort` yet.** It may be a cheap speed lever on our current model.
- TB 2.1: 73.0 on the model card (row labelled "Terminus"; no timeout or resource footnote), against 63.4 for
  Qwen3.6-27B. Independent: 58.43 on Vals AI, Terminus 2
  ([Vals TB 2.1](https://www.vals.ai/benchmarks/terminal-bench-2-1)).
- Official FP8 checkpoint `Qwen/Qwen3.8-27B-FP8`, block-128 FP8, "nearly identical" to BF16
  ([FP8 card](https://huggingface.co/Qwen/Qwen3.8-27B-FP8)). The card doesn't give a size in GB.
- vLLM and SGLang supported.

### Laguna S 2.1 (Poolside), the main candidate

- 118B MoE, about 8B active per token (256 routed experts, top-10, plus 1 shared), 1M context, OpenMDW-1.1
  ([model card](https://huggingface.co/poolside/Laguna-S-2.1)). Released July 2026 (some news items say
  August).
- TB 2.1: 70.2. The card says the TB 2.1 number is third-party, from Artificial Analysis. Harness and timeout
  not stated. It's not on the Vals board, so there's no head-to-head with Qwen3.8-27B under one harness.
  SWE-bench Pro 59.4 against Qwen3.8-27B's 61.7.
- Official checkpoints: BF16 (235 GB), FP8 (121 GB, too big), **INT4 and NVFP4 (72 GB each)**
  ([vLLM recipe](https://recipes.vllm.ai/poolside/Laguna-S-2.1),
  [INT4 card](https://huggingface.co/poolside/Laguna-S-2.1-INT4),
  [NVFP4 card](https://huggingface.co/poolside/Laguna-S-2.1-NVFP4)). The INT4 one mixes INT4 and INT8 experts.
  No accuracy comparison against BF16 is published.
- GPUs per the recipe: INT4 on a single H200 or B200; NVFP4 on a single B200/B300 (Blackwell only).
  **H100 80 GB and RTX PRO 6000 are not mentioned.** 72 GB of weights leave only about 6 GB of KV cache on an
  80 GB card, so H100 is likely too tight. RTX PRO 6000 (96 GB) should fit but is unvalidated.
- vLLM 0.25.0 or newer, with `--tool-call-parser poolside_v1 --reasoning-parser poolside_v1
  --enable-auto-tool-choice`. Optional DFlash speculative decoding (draft model `Laguna-S-2.1-DFlash-INT4`);
  mean accepted length about 3.1 tokens per step on text, higher on code.
- Thinking: same switch name as Qwen, `chat_template_kwargs: {"enable_thinking": ...}`. The recipe says
  reasoning is **off by default**; the card's command turns it on with
  `--default-chat-template-kwargs '{"enable_thinking": true}'`. We'd need that flag.
- The card says to keep `reasoning_content` from earlier assistant turns or the model may stop reasoning.
  `mini_agent` re-sends it by default (only `strip_reasoning` drops it), so that's fine.
- Speed: no single-GPU tok/s number published. One community W4A16 quant reports about 92 tok/s on
  8x RTX 3090 (secondary, different setup, not useful as an estimate).

### Nemotron 3.5 Super VL (NVIDIA)

- 120B total, 12B active, Mamba-2/Transformer hybrid MoE with a vision encoder, 1M context, OpenMDW-1.1.
  Released Oct 15 2026
  ([NVFP4 card](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4)).
- TB 2.1: 60.67 (BF16) and 62.78 (NVFP4) on the card, run through NeMo Gym, harness not named.
  SWE-bench Verified 71.1. llm-stats lists 66.7 on TB 2.1
  ([llm-stats TB 2.1](https://llm-stats.com/benchmarks/terminal-bench-2.1)); I couldn't trace that number to
  NVIDIA, so treat it as unverified. A third-party page notes the card and tech report disagree on some cells
  ([benchmarklist](https://benchmarklist.com/models/nvidia-nemotron-3.5-super-vl-120b-a12b/), secondary).
- NVFP4 is official. Weights run W4A4 on Blackwell and W4A16 on other GPUs. The card lists 2x H100, 1x H200,
  1x GB200, and "1x DGX Spark or RTX PRO 6000 (with a smaller configuration)". Size in GB not stated.
- vLLM 0.32.0 image; `--tool-call-parser qwen3_coder --reasoning-parser nemotron_v3`. Built-in MTP
  speculative decoding.
- Thinking: `enable_thinking` true/false in `chat_template_kwargs`, plus a medium-effort setting
  (`medium_effort: true`).
- Speed: about 630 output tok/s on a pre-release DeepInfra NVFP4 endpoint, and about 60% fewer output tokens
  per task than Nemotron 3 Super ([Artificial Analysis](https://artificialanalysis.ai/articles/nemotron-3-5-super-and-bolt)).
  Provider hardware isn't stated, so this is an upper bound, not what we'd see on one rented card.
- Weaker evidence on coding than Laguna, but the strongest speed evidence.

### Ling 3.0 Flash (inclusionAI)

- 124B total, 5.1B active (the vLLM recipe says 5.5B, plus a 3.1B MTP layer), 262K context, MIT
  ([model card](https://huggingface.co/inclusionAI/Ling-3.0-flash)).
- **The only candidate with an independent TB 2.1 score: 50.19 on Vals, Terminus 2.** Self-reported 57.0
  (llm-stats). Both are well below Qwen3.8-27B's 58.43 on the same Vals board.
- INT4 (routed experts only) is 77.0 GB on disk, 70.27 GiB loaded. FP8 and FP4 variants exist. INT4 and FP4
  run on one GPU ([vLLM recipe](https://recipes.vllm.ai/inclusionAI/Ling-3.0-flash)).
- **Measured speed:** INT4 on 1x H200, 159.5 tok/s single-stream, 973 tok/s total at 16 concurrent requests
  (same recipe). That's about 1.5x our 105 tok/s.
- Thinking on by default; `enable_thinking: false` turns it off. Parsers `ling3`.
- Fast, but the evidence says it's less capable than what we have.

### Qwen3.6-35B-A3B

- 35B / 3B active, 262K context, Apache-2.0, same thinking switch and `qwen3_coder` tool parser as our
  model ([model card](https://huggingface.co/Qwen/Qwen3.6-35B-A3B)).
- TB 2.0: 51.5 (Terminus 2, 3 h timeout, 5-run average) against 59.3 for Qwen3.6-27B on the same footnote
  ([Qwen3.6-27B card](https://huggingface.co/Qwen/Qwen3.6-27B)). Qwen3.8-27B is newer and stronger than
  Qwen3.6-27B.
- Fits easily even in BF16 (about 70 GB). 3B active should be very fast.
- Worth one test only if speed turns out to matter more than the 8-point gap.

### Qwen3.5-122B-A10B

- 122B / 10B active, Apache-2.0, same switch ([model card](https://huggingface.co/Qwen/Qwen3.5-122B-A10B)).
- TB 2.0: 49.4 (harness not stated on the card). Below Qwen3.6-27B's 59.3. No official 4-bit checkpoint.
- Older and weaker than Laguna at the same size. Not worth testing first.

## Hosting

### What changes in our agent

- Our agent talks to any OpenAI-compatible endpoint. Switching is a `.env.op` change: `LLM_BASE_URL`,
  `LLM_MODEL`, `LLM_API_KEY`. Start vLLM with `--api-key` and put the key in 1Password like the gateway key.
- Our thinking-off feature sends `chat_template_kwargs: {enable_thinking: false}`. **All five candidates
  accept that exact key** (Laguna, Nemotron 3.5 Super, Ling 3.0 Flash, Qwen3.6, Qwen3.5). gpt-oss doesn't.
- Each model needs its own vLLM `--tool-call-parser` and `--reasoning-parser` (listed above). Run
  `check_endpoint.sh` first to confirm tool calls and `reasoning_content` come back as expected.
- Sampling defaults in `.env` are tuned for Qwen. Use each card's recommended values.
- Laguna has reasoning off by default: start the server with
  `--default-chat-template-kwargs '{"enable_thinking": true}'`.

### GPUs that fit a 72–80 GB checkpoint

| GPU | VRAM | Fits Laguna INT4? | Price per hour (on-demand) |
|---|---|---|---|
| RTX PRO 6000 (Blackwell) | 96 GB | Likely, not validated by Poolside | RunPod $1.69 community / $2.49 secure; Modal $3.03 |
| H100 NVL | 94 GB | Likely | RunPod $2.59 / $3.19 |
| GH200 | 96 GB | Likely (ARM host CPU) | Lambda $2.29 |
| H100 SXM | 80 GB | Too tight for KV cache | RunPod $2.69 / $3.99; Lambda $4.29; Modal $3.95 |
| H200 | 141 GB | Yes (validated) | RunPod $3.59 / $5.29; Modal $4.54 |
| B200 | 180 GB | Yes (validated, also NVFP4) | RunPod $5.98 / $7.99; Lambda $6.99; Modal $6.25 |

Sources: [RunPod](https://www.runpod.io/pricing), [Lambda](https://lambda.com/pricing) (prices effective
Nov 16 2026), [Modal](https://modal.com/pricing) (converted from per-second). Vast.ai is a marketplace and
its pricing page showed no fixed prices ([Vast.ai](https://vast.ai/pricing)). Prices fetched Nov 5 2026.

### How speed changes the run time

- Decoding is limited by memory bandwidth: each token reads the active weights once. Rough bytes per token:
  Qwen3.8-27B FP8 about 28 GB; Laguna INT4 about 5 GB; Ling INT4 about 3 GB. So MoE candidates could decode
  roughly 3–6x faster than our model on the same card. This is a back-of-envelope estimate, not a measurement;
  attention, KV cache reads and kernel quality eat into it. The only measured number is Ling's 159.5 tok/s on
  an H200.
- **Self-hosting our current model is not a speed win on cheap cards.** 27B dense FP8 on an RTX PRO 6000
  (about 1.6–1.8 TB/s, secondary sources) tops out around 60 tok/s, below the gateway's 105. Only an H200 or
  B200 would beat the gateway for the same model.
- Today a full run takes about 10–12 h at `-n 2`, and 71% of task time is model writing
  ([timeouts-full-all-v1.md](timeouts-full-all-v1.md)). If a model writes k times faster, a task that
  finishes takes about `0.29 + 0.71/k` of today's time. At k = 2 that's about 65%, so 6.5–8 h. Tasks that
  used to time out will run longer instead, so the real saving is smaller than that.
- With our own GPU we can also raise `-n` (vLLM batches well; Ling does 973 tok/s at 16 requests). The
  limit then becomes RAM and CPU for the Docker containers on the Victus, not the model.

### Rough cost of one full 89-task run

Add about 1–2 h per session for downloading 72–80 GB of weights, starting vLLM and a smoke test.

| Setup | Hours (est.) | Cost per full run (est.) |
|---|---|---|
| Laguna INT4 on 1x RTX PRO 6000, RunPod | 8–12 h | $15–30 |
| Laguna INT4 on 1x H200, RunPod | 7–10 h | $25–55 |
| Laguna NVFP4 on 1x B200, RunPod | 6–9 h | $40–75 |
| Qwen3.8-27B FP8 on 1x RTX PRO 6000 (same model as now, slower) | 15+ h, more timeouts | $25–40, not worth it |

Storage for the weights is extra and not priced here. GPU rentals bill while idle: stop the pod the moment
the run ends, and set a billing alert (the FAQ warns about this too).

### Quantized checkpoints

- Published by the vendor: Laguna S 2.1 INT4 and NVFP4; Nemotron 3.5 Super NVFP4; Ling 3.0 Flash INT4/FP4/FP8
  (per the vLLM recipe; the HF card doesn't name the repos); Qwen3.8-27B FP8.
- Community only: Qwen3.5-122B-A10B 4-bit (GGUF and others). We'd rather not quantize anything ourselves.

## Questions for the organizers

1. **How is the 96 GB measured?** Weights only, on-disk checkpoint size, or the README's "reported VRAM"
   formula (weights + KV cache at 16K + about 2 GB)? Laguna INT4 (72 GB) and Ling INT4 (77 GB) fit under any
   of these, but it matters for anything near 90 GB.
2. **Is a model we host ourselves on a rented GPU fine for the submitted run?** The FAQ says renting a GPU
   and running vLLM is "just cloud compute", but please confirm, and say what proof of the checkpoint you want
   (HF repo id plus the vLLM command?).
3. **Do mixed-precision 4-bit checkpoints count as "4-bit or higher"?** Laguna INT4 mixes INT4 and INT8
   experts; NVFP4 keeps some layers in BF16. We assume yes.
4. **Does a vision-language model count** (Nemotron 3.5 Super VL, Qwen3.8-27B)? We only use text.
5. **Speculative decoding with a small draft model** (Laguna's DFlash, Nemotron's MTP): does the draft model
   count against the 96 GB, and does it count as a second model?
6. **Does the gateway's hardware or settings change before the deadline?** Our time-limit failures depend on
   its 105 tok/s.

## Sources

Competition rule (repo, `origin/main`): `README.md` "Approved models" section, `RULES.md`, `FAQ.md`. The rule
text: "your submitted run must use open weights within the 96 GB budget — any checkpoint, any vendor, 4-bit
or higher." The docs don't say how the 96 GB is measured. The README still has the older "reported VRAM"
formula and an older "~48 GB" line for additions. (The `feat/overrun-recovery` branch still has the old
approved-list text.)

- Terminal-Bench 2.1 release and 2.0 → 2.1 score changes: https://www.tbench.ai/news/terminal-bench-2-1
- Vals AI TB 2.1 leaderboard (Terminus 2): https://www.vals.ai/benchmarks/terminal-bench-2-1
- llm-stats TB 2.1 (all self-reported): https://llm-stats.com/benchmarks/terminal-bench-2.1
- Qwen3.8-27B: https://huggingface.co/Qwen/Qwen3.8-27B
- Qwen3.8-27B-FP8: https://huggingface.co/Qwen/Qwen3.8-27B-FP8
- Qwen model list: https://raw.githubusercontent.com/QwenLM/Qwen3.8/main/README.md
- Qwen3.6-27B: https://huggingface.co/Qwen/Qwen3.6-27B
- Qwen3.6-35B-A3B: https://huggingface.co/Qwen/Qwen3.6-35B-A3B
- Qwen3.5-122B-A10B: https://huggingface.co/Qwen/Qwen3.5-122B-A10B
- Qwen3-Coder-Next: https://huggingface.co/Qwen/Qwen3-Coder-Next
- Laguna S 2.1: https://huggingface.co/poolside/Laguna-S-2.1
- Laguna S 2.1 INT4: https://huggingface.co/poolside/Laguna-S-2.1-INT4
- Laguna S 2.1 NVFP4: https://huggingface.co/poolside/Laguna-S-2.1-NVFP4
- Laguna S 2.1 vLLM recipe: https://recipes.vllm.ai/poolside/Laguna-S-2.1
- Nemotron 3.5 Super VL NVFP4: https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4
- Nemotron 3.5 Super and Bolt (Artificial Analysis): https://artificialanalysis.ai/articles/nemotron-3-5-super-and-bolt
- Nemotron 3.5 launch blog: https://blogs.nvidia.com/blog/nemotron-3-5-super-vl/
- Nemotron 3.5 Super scores, secondary: https://benchmarklist.com/models/nvidia-nemotron-3.5-super-vl-120b-a12b/
- Ling 3.0 Flash: https://huggingface.co/inclusionAI/Ling-3.0-flash
- Ling 3.0 Flash vLLM recipe: https://recipes.vllm.ai/inclusionAI/Ling-3.0-flash
- Devstral 2: https://huggingface.co/mistralai/Devstral-2-123B-Instruct-2512
- gpt-oss-120b: https://huggingface.co/openai/gpt-oss-120b
- GLM-5.3-Flash: https://huggingface.co/zai-org/GLM-5.3-Flash
- MiniMax-M3 size, secondary: https://huggingface.co/unsloth/MiniMax-M3
- RunPod pricing: https://www.runpod.io/pricing
- Lambda pricing: https://lambda.com/pricing
- Modal pricing: https://modal.com/pricing
- Vast.ai pricing: https://vast.ai/pricing
- Our own numbers: [full-all-v1.md](full-all-v1.md), [timeouts-full-all-v1.md](timeouts-full-all-v1.md)
