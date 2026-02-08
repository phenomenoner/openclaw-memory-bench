# openclaw-memory-bench Spec v0.1 (Draft)

## Objective

Provide reproducible benchmark numbers for OpenClaw memory-layer plugins using a common CLI and run manifest.

## Tracks

## 1) Retrieval Track (deterministic)

Inputs:
- benchmark dataset
- plugin adapter
- search parameters (`top_k`, threshold)

Outputs:
- Hit@K
- Precision@K
- Recall@K
- MRR
- nDCG
- search latency (p50/p95)

## 2) E2E Track (optional)

Pipeline:
retrieval -> context assembly -> answer model -> judge model

Outputs:
- answer accuracy
- explanation logs
- cost/latency metadata

## Run Manifest (required)

Each run must include:
- toolkit version / git commit
- dataset version
- provider adapter version
- runtime info (python, OS)
- parameter config (top_k, limits, thresholds)

## Fairness rules

1. Same benchmark subset across compared plugins.
2. Same answer/judge models for E2E comparisons.
3. No plugin-specific hidden prompt hacks in "official" reports.
4. Publish raw run artifacts for reproducibility.
