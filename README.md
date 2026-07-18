# AI Entropy Engine — Information Density Diagnosis and Spontaneous Metabolism for AI Systems

> Extracted from a one-year production AI system deployment
> License: Apache 2.0

## What is this

AI knowledge bases and memories continuously expand, but not all expansion carries value. This project provides an **auditable information density diagnosis engine** that gives AI systems the ability for spontaneous metabolism — automatically identifying information entropy increase, closing hallucination loops, and maintaining knowledge system health.

**Core deliverables:**
- **v5 Density Diagnosis Model** — LOO r²=0.589, Spearman=0.767, 280 samples (59 human + 221 objective) ⚠️ *see metric correction below*
- **Hallucination Loop Closure Mechanism** — Five-layer protection system abstracted from production incidents
- **Spontaneous Metabolism Pipeline** — 6h auto-scan → scoring → residual recording → LLM validation → Fourier time-series analysis

> ## ⚠️ 2026-07-18 — Metric Correction & validation-v3
>
> A full-stack adversarial audit of the production system (see [ai-agent-incidents #002](https://github.com/Yun1976/ai-agent-incidents)) found two integrity issues that change how the numbers in this README should be read:
>
> **1. v5 headline metric is inflated by label leakage.** The 221 "objective" labels are deterministic functions of rule signals (F/R/C/I + filler + length) — and the same rule signals are v5 model features. Using only those label-generating signals, 5-fold CV on the objective labels alone reaches r²=0.767. The honest generalization evidence remains **v3 on 59 human-only labels: LOO r²=+0.207 / Spearman=+0.487** (weak but real). The v5 numbers are kept below for the record, not as the headline.
>
> **2. The production validation loop had a 14-day total evidence outage** (schema mismatch + swallowed TypeError), causing circular self-validation. Fixed in production as *validation-v3*: six-tier behavioral evidence grading, auto-generated-artifact registry (machine-rewritten files cannot self-validate), and explicit negative-evidence measurement (14-day untouched ⇒ low-utility record instead of censorship).
>
> **3. Theoretical framing corrected.** Pruning justification is grounded in **rate-distortion / MDL ("every retained block must pay rent for its slot")** — rate-distortion is Shannon's own 1959 framework, the correct chapter for "what may be discarded." Shannon entropy is used here only as a *text statistic feature*, never as a derivation of "density decay." Boltzmann/drift-collision vocabulary is heuristic analogy, demoted from "theory" to "motivation."
>
> **Status note:** `metabolism/density_cron_v5.py` is superseded in production by a rewritten loop (validation-v3, six-tier evidence) that is not yet ported here — the copy in this repo has known feature-pipeline inconsistencies. `entropy-pruner/` + `model/` + `docs/` remain the reliable parts of this repository.

## Key Contributions

### 1. Hallucination Loop — The Most Dangerous Failure Mode in AI Systems
Identified and closed a systemic failure pattern: an AI system's performance metrics validated by its own output, creating a self-referential closed loop where external appearance shows normal operation but internal reality is empty spinning.

### 2. Behavior-Consequence Objective Annotation Engine
Replaces subjective rubrics with objective metrics based on real operational consequences of the AI system (Failure F / Response R / Cognition C / Integrity I).

### 3. Spontaneous Metabolism Mechanism
Evolution from manual diagnosis (S·λ·R·C four-factor model) to automated pipeline (v5 regression model).

## Repository Structure

```
ai-entropy-engine/
├── README.md                      # This file
├── docs/                          # Paper-level documentation
│   ├── hallucination-loop.md       # Hallucination loop closure mechanism
│   └── feature-engineering.md      # Feature engineering iteration history (v1→v5)
├── data/                          # Datasets (auditable)
│   ├── lessons-causal-chain-v1.csv # 59 human gold-standard annotations
│   └── objective_annotated.csv   # 280 training samples (59 human + 221 objective)
├── model/                         # Models (reproducible)
│   ├── honest_model_v5.joblib      # v5 model (LOO r²=0.589)
│   ├── honest_model_v5_config.json
│   └── train_v5.py                # Training script
├── entropy-pruner/                # Pruning tool (standalone)
│   ├── entropy_pruner_v5.py       # Full-library scan pruner
│   ├── feature_engineering.py     # Feature extraction (23 dimensions)
│   └── objective_annotate.py     # Objective annotation engine
├── metabolism/                    # Metabolism pipeline
│   ├── density_cron_v5.py         # Cron entry (v5 scoring)
│   ├── llm_validation.py          # LLM validation module
│   └── density-corrector.py       # Density corrector model (≥100 residuals)
└── LICENSE                        # Apache 2.0
```

## Quick Start

### Dependencies
```bash
pip install numpy scikit-learn joblib
```

### Run Pruning Tool
```bash
cd entropy-pruner
python entropy_pruner_v5.py
```
Output: pruning report (CSV) with per-document score, decision, and behavior signals.

### Run Metabolism Pipeline
```bash
cd metabolism
python density_cron_v5.py
```
Output: residual series (JSONL), configurable for 6h cron.

## Model Metrics

| Metric | v3 Honest (headline) | v5 Behavior-Consequence ⚠️ | Legacy (v1) |
|--------|----------|------------------------|-------------|
| LOO r² | **+0.207** | +0.589 *(inflated, see correction above)* | -0.559 (claimed 0.778) |
| Spearman | **+0.487** | +0.767 *(inflated)* | — |
| Training samples | **59 (human only)** | 280 (59 human + 221 rule-derived) | 325 (self-generated) |
| Feature dimensions | 27 | 23 | 22 (surface features) |
| Validation | LOO | LOO | None |

> ⚠️ v5's 221 "objective" labels are deterministic functions of signals that are also model features (label leakage). Treat v3 as the credible metric; v5 is retained for reproducibility of the audit trail.

## Five-Layer Protection Mechanism

```
Score → Constitution layer (never prune SOUL/MEMORY/AGENTS)
     → Dependency layer (referenced docs protected)
     → Source layer (knowledge skeleton with URLs protected)
     → Observation layer (low-score + no filler signal → human review)
     → Pruning layer (low-score + high filler signal → suggest prune)
```

## Key Design Principles

1. **Independent validation is the only antidote** — r²=0.778 without independent validation = r²=unknown
2. **Honest weak model > Fake strong model** — r²=+0.207 (real) > r²=0.778 (fake)
3. **Anti-signals are more dangerous than useless features** — Core docs are shorter; chars is an anti-signal
4. **Circular reasoning is the stealthiest trap** — Using inlink to define labels then predicting labels = 100% accurate but meaningless
5. **Uncertainty must be labeled as uncertainty** — fft_reliable=0 is more valuable than pretending fft_reliable=1
6. **Auditability = Trustworthiness** — Every pruning suggestion must carry feature values + reasoning + traceability
7. **Protection rules don't enter the model** — Hard filters outside model to prevent shortcut learning
8. **Graph features have blind spots** — SOUL/MEMORY loaded not referenced, inlink=0 but most important

## Environment

- **System**: Python 3.x, scikit-learn
- **Knowledge base**: Obsidian vault, 2490 documents
- **Scan scope**: Full-machine (knowledge base + workspace + constitution layer)

## Citation

```bibtex
@software{entropy_engine_2026,
  title = {AI Entropy Engine: Information Density Diagnosis and Spontaneous Metabolism for AI Systems},
  year = {2026},
  url = {https://github.com/yun1976/ai-entropy-engine}
}
```

## License

Apache License 2.0
