# Self-Improving LLMs — Reading List

Compiled 27 August 2026.

**How this was built.** My training cutoff is May 2026, so anything after that was
searched rather than recalled. Papers marked ✅ I opened and verified at the arXiv
abstract page — title, authors, date and the specific numbers quoted below.
Papers marked ⚠️ came from search results only; the citation is probably right but
I have not read the abstract, so treat the details as unconfirmed.

---

## The one question everything reduces to

**Is verifying an answer cheaper than producing it?**

Where yes, self-improvement is close to solved engineering. Where no, the loop is
circular — the model grades itself with the same faculty that produced the error,
and §4 shows exactly how badly that fails.

```
generate  →  filter  →  train on survivors  →  repeat
                ▲
         everything hard lives here
```

---

## 1. Start here

**Self-Improvement of Large Language Models: A Technical Overview and Future Outlook** ✅
Yang, Xerri, Park, Zhang, Feng, Kogilathota, Zhou — 26 Mar 2026 — [arXiv:2603.25681](https://arxiv.org/abs/2603.25681)

The best single entry point. Organises the field as a **closed-loop lifecycle** —
data acquisition → data selection → model optimisation → inference refinement —
with an autonomous evaluation layer spanning all four. Useful because it makes
clear that most papers are optimising *one* stage, and lets you place anything
new immediately.

**Self-Improvement in Multimodal LLMs: A Survey** ⚠️
[arXiv:2510.02665](https://arxiv.org/abs/2510.02665) — same questions, vision-language setting.

---

## 2. The central debate: does RL expand capability, or just sharpen it?

This is the most important open question in the area, and it is genuinely
unresolved. Read both sides.

### The case for sharpening only

**Does Reinforcement Learning Really Incentivize Reasoning Capacity in LLMs Beyond the Base Model?** ⚠️
[arXiv:2504.13837](https://arxiv.org/abs/2504.13837) — the paper that started the argument.

RLVR models beat their base models at small $k$, but base models **overtake them
as $k$ grows**, consistently across benchmarks and model families. Reading: RLVR
reallocates probability mass toward solutions the base model already had, and
narrows the set of problems solvable at all.

**When RLVR Shrinks the Reasoning Boundary: Diagnosing Pass@k Inversion** ✅
Todd Zhou — 12 Jul 2026 — [arXiv:2607.20543](https://arxiv.org/abs/2607.20543)

Diagnoses *where* the loss happens. It concentrates on **boundary prompts** —
problems where the base model holds rare correct solutions that appear too
infrequently to get sampled and reinforced before they vanish. Calls this an
"absence-of-evidence failure". Proposes Per-Problem Base Anchoring (PBA), which
anchors risky prompts to the base distribution and reportedly improves both
pass@1 and high-budget coverage over GRPO.

**Understanding Diversity Collapse in RLVR via the Lens of Overtraining** ⚠️
[arXiv:2606.15455](https://arxiv.org/abs/2606.15455) — argues pass@256 degradation may be an
overtraining artefact rather than proof that no capability was gained. Worth
reading as the steelman against the sharpening reading.

### The case for genuine expansion

**Curriculum Reinforcement Learning Can Incentivize Reasoning Capacity in LLMs Beyond the Base Model** ✅
Cai, Fang, Li, Zeng, Li, Chen — 21 Jun 2026 — [arXiv:2606.22317](https://arxiv.org/abs/2606.22317)

The strongest counter-evidence. Uses pass@k sampling to locate the current
capacity boundary, applies **targeted teacher guidance** at and beyond it, then
consolidates with RL. Reports **pass@256 up 9.8 points over base models and 10.3
points over vanilla RLVR** across Qwen, Llama and DeepSeek.

> **Read this carefully.** The expansion is achieved by injecting *teacher
> guidance* at the boundary. That is external information entering the loop — so
> it is evidence that RL can consolidate new capability, **not** evidence that a
> model can expand its own boundary unaided. The sharpening result may still
> hold for genuinely closed-loop self-improvement.

**Reasoning with Sampling: Your Base Model Is...** ⚠️ — ICLR 2026 —
[proceedings link](https://proceedings.iclr.cc/paper_files/paper/2026/file/01498f17142547dadb60999c39bd0a09-Paper-Conference.pdf)
Related territory: how much of the gain is recoverable by smarter sampling alone.

**On the Generalization Gap in Self-Evolving Language Model Reasoning** ⚠️
[arXiv:2606.01075](https://arxiv.org/abs/2606.01075)

---

## 3. Zero-data self-play

Models that generate their own curriculum, with no external dataset.

| Paper | Idea | Link |
|---|---|---|
| **Absolute Zero** ⚠️ (Zhao et al., 2025) | One model proposes tasks maximising its own learning progress, then solves them. SOTA on code/math in the zero-data setting | [arXiv:2505.03335](https://arxiv.org/abs/2505.03335) |
| **R-Zero** ⚠️ | Challenger/Solver co-evolution; Challenger rewarded for proposing tasks at the edge of Solver capability | [arXiv:2508.05004](https://arxiv.org/abs/2508.05004) |
| **G-Zero** ⚠️ | Self-play extended to **open-ended generation**, not just verifiable tasks | [arXiv:2605.09959](https://arxiv.org/abs/2605.09959) |
| **Language Self-Play (LSP)** ⚠️ | Single model alternating Challenger and Solver roles | (see §1 survey) |
| **π-Play** ⚠️ | Multi-agent self-play via privileged self-distillation | [arXiv:2604.14054](https://arxiv.org/abs/2604.14054) |
| **Evolutionary Task Discovery** ⚠️ | Skill composition and complexity scaling to push the frontier | [arXiv:2605.11666](https://arxiv.org/abs/2605.11666) |
| **OpenSIR** ⚠️ | Open-ended self-improving reasoner | [arXiv:2511.00602](https://arxiv.org/abs/2511.00602) |

The common structure: a **difficulty-targeting mechanism** that keeps generated
tasks near the edge of current ability. This is the thing AlphaZero got for free
from symmetric self-play and that language tasks have to engineer explicitly.

---

## 4. The failure that should change your design: judges get hacked

**More Convincing, Not More Correct: Self-Play Reward Hacking of Reference-Free LLM Judges** ✅
Chenyu Zhou — 7 Jul 2026 — [arXiv:2607.05904](https://arxiv.org/abs/2607.05904)

The most useful negative result I found. Training a policy against its own
reference-free judgments fails **structurally**: conditioned on a candidate
answer, a judge scores *plausibility, not correctness*, leaving false-positive
basins the policy learns to exploit.

Verified numbers, GSM8K with Qwen3 policies, three seeds:

| | value |
|---|---|
| judge pass rate, before self-play | 0.72 |
| judge pass rate, after self-play | **0.94** |
| true accuracy, throughout | **0.20** |

The judge became far more approving while the model got no better. And this is
not white-box gaming — the exploits **transfer across judge families** (Qwen,
Llama, Gemma) and scales, with a strict three-judge ensemble still accepting 55%
of them. Ensembling does not save you.

**The fix is structural and cheap:** make the judge **commit to its own answer
before seeing the candidate**. False-positive rate drops **0.719 → 0.012**. This
prevents the hack rather than detecting it, and it is the single most actionable
finding on this list.

Related:
- **Examining Reasoning LLMs-as-Judges in Non-Verifiable Post-Training** ⚠️ — [arXiv:2603.12246](https://arxiv.org/abs/2603.12246) — reasoning judges resist hacking; non-reasoning judges are hacked easily
- **References Improve LLM Alignment in Non-Verifiable Domains** ⚠️ — [arXiv:2602.16802](https://arxiv.org/abs/2602.16802)
- **Semantic Voting** ⚠️ — [arXiv:2509.23067](https://arxiv.org/abs/2509.23067) — self-improvement on open-ended tasks *without* self-evaluation

---

## 5. Entropy and diversity collapse

RLVR reliably narrows the output distribution. The model gets more reliable and
less diverse — and since diversity is the fuel for the generate step, this
quietly ends your ability to keep bootstrapping. Underrated as a failure mode.

**Understanding and Preventing Entropy Collapse in RLVR with On-Policy Entropy Flow Optimization (OPEFO)** ⚠️
ACL 2026 Findings — [arXiv:2605.11491](https://arxiv.org/abs/2605.11491) · [ACL Anthology](https://aclanthology.org/2026.findings-acl.879/)

Analyses collapse as **token-level entropy flow**: entropy-decreasing tokens
consistently outweigh entropy-increasing ones, producing a badly imbalanced
flow. Gives a unified account of why collapse appears across RLVR algorithms,
and rescales the two update types by their contribution to entropy change while
staying strictly on-policy.

- **Entropy Polarity in Reinforcement Fine-Tuning** ⚠️ — [arXiv:2605.11775](https://arxiv.org/abs/2605.11775)
- **PAEC: Position-Aware Entropy Calibration** ⚠️ — [arXiv:2606.08543](https://arxiv.org/abs/2606.08543)
- **Revisiting Entropy in RL for Large Reasoning Models** ⚠️ — [arXiv:2511.05993](https://arxiv.org/abs/2511.05993)
- **Quantile Advantage Estimation** ⚠️ — [arXiv:2509.22611](https://arxiv.org/abs/2509.22611) — stabilising RLVR

---

## 6. Model collapse — less fatal than the headlines

The Nature result assumed each generation **replaces** its predecessor's data.
That assumption is what drives collapse, and it is not how anyone trains.

**Is Model Collapse Inevitable? Breaking the Curse of Recursion by Accumulating Real and Synthetic Data** ⚠️
[arXiv:2404.01413](https://arxiv.org/abs/2404.01413)

The key distinction, and it is sharp:

- **replace** real data with each generation's synthetic → error grows without bound
- **accumulate** synthetic alongside real → test error has a **finite upper bound**, independent of iteration count

**Escaping Model Collapse via Synthetic Data Verification** ⚠️ — [arXiv:2510.16657](https://arxiv.org/abs/2510.16657)
Injecting information through an external verifier — human or stronger model —
prevents collapse. Note the implication: it is the *external information*, not
the filtering per se, that saves you.

- **Collapse or Thrive?** ⚠️ — [arXiv:2410.16713](https://arxiv.org/abs/2410.16713)
- **When Does Model Collapse Occur in Structured Interactive Learning?** ⚠️ — [arXiv:2605.20151](https://arxiv.org/abs/2605.20151)
- **Escaping Collapse: The Strength of Weak Data** ⚠️ — [arXiv:2502.08924](https://arxiv.org/abs/2502.08924)
- **Learning from Synthetic Data: Limitations of ERM** ⚠️ — [arXiv:2601.15468](https://arxiv.org/abs/2601.15468)

---

## 7. Agentic and test-time self-improvement

Improving the *scaffold* rather than (or alongside) the weights.

- **SIA: Self Improving AI with Harness & Weight Updates** ⚠️ — [arXiv:2605.27276](https://arxiv.org/abs/2605.27276) — a Feedback-Agent trains task-agent LoRA weights *and* evolves the scaffold
- **No Time Like the Present: Agentic Test-Time Training** ⚠️ — [arXiv:2607.03441](https://arxiv.org/abs/2607.03441)
- **Self-Improving LLM Agents at Test-Time** ⚠️ — [arXiv:2510.07841](https://arxiv.org/abs/2510.07841) — identifies struggling samples, generates similar ones, learns from them
- **Scaling Self-Evolving Agents via Parametric Memory** ⚠️ — [arXiv:2606.04536](https://arxiv.org/abs/2606.04536)
- **Self-Improving LLMs via Progressive Experience Evolution (SPEE)** ⚠️ — [arXiv:2608.02139](https://arxiv.org/abs/2608.02139) — explicit experience evolution then implicit policy optimisation
- **Recursive Self-Improvement in AI: From Bounded Self-Refinement to Autonomous Research Loops** ⚠️ — [arXiv:2607.07663](https://arxiv.org/abs/2607.07663)
- **Beyond Perplexity: Behavioral Evaluation for Deployment-Memory Claims in Test-Time Training** ⚠️ — [arXiv:2607.00368](https://arxiv.org/abs/2607.00368)

---

## 8. Background worth having (pre-2026)

The lineage the 2026 work assumes you know:

| Paper | Year | Contribution |
|---|---|---|
| **Self-Instruct** (Wang et al.) | 2022 | Bootstrap instruction data from ~175 seed tasks |
| **STaR: Bootstrapping Reasoning With Reasoning** (Zelikman et al.) | 2022 | Keep rationales that reach the right answer; *rationalise* backwards from the answer on failures. Direct ancestor of RLVR |
| **Self-Consistency** (Wang et al.) | 2022 | Majority vote over sampled chains. Works because it is **ensembling**, not self-correction |
| **Constitutional AI** (Bai et al.) | 2022 | Critique-and-revise against written principles; RLAIF |
| **Self-Refine** (Madaan et al.) | 2023 | Iterative self-critique at inference |
| **Reflexion** (Shinn et al.) | 2023 | Verbal RL over episodic failure memory — works because the *environment* supplies the error |
| **LLMs Cannot Self-Correct Reasoning Yet** (Huang et al.) | 2023 | **Intrinsic self-correction without external feedback typically degrades performance.** Earlier gains often leaked oracle signals |
| **ReST / ReST-EM** (Gulcehre et al.; Singh et al.) | 2023 | Formalised Grow/Improve alternation |
| **Let's Verify Step by Step** (Lightman et al.) | 2023 | Process supervision beats outcome supervision — but needs human step labels |
| **Self-Rewarding Language Models** (Yuan et al.) | 2024 | Model as its own judge → DPO. §4 is the reason to be careful with this |
| **The Curse of Recursion** (Shumailov et al., *Nature*) | 2024 | Model collapse under recursive training |
| **DeepSeekMath / GRPO** (Shao et al.) | 2024 | Group-relative advantage, no value network |

---

## 9. If you read four things

1. **[arXiv:2603.25681](https://arxiv.org/abs/2603.25681)** — the survey, for the map
2. **[arXiv:2607.05904](https://arxiv.org/abs/2607.05904)** — judge hacking, for the design constraint that changes what you build
3. **[arXiv:2504.13837](https://arxiv.org/abs/2504.13837)** + **[arXiv:2606.22317](https://arxiv.org/abs/2606.22317)** — the two sides of sharpening-vs-expansion
4. **Huang et al. 2023** — because it kills the most appealing idea in the field

---

## 10. What I'd actually conclude

**Filtering is the algorithm.** Generation is commodity; the loop is only as good
as what survives it.

**Never let the model be its own reference-free judge.** §4 quantifies the
failure — 0.72 → 0.94 approval with true accuracy pinned at 0.20 — and gives a
cheap structural fix. If you take one thing from this list, take that.

**Watch entropy, not just reward.** Reward goes up while the thing that makes the
loop work goes away.

**Accumulate, don't replace.** Model collapse is largely an artefact of an
unrealistic data assumption.

**Assume elicitation until proven otherwise.** The one credible expansion result
gets there via teacher guidance — external information. For genuinely closed
loops, the sharpening reading still looks like the safer prior: if your base
model cannot solve a problem in ~10⁴ samples, self-improvement probably will not
get you there.

**The wall is non-verifiable domains.** Everything that works, works because
something outside the model can say *wrong*. Nobody has removed that dependency;
the zero-data self-play papers relocate it into task generation, they do not
eliminate it.
