# MedQA external verification evaluation

This is a candidate update to the earlier RAVA reproducibility release. It contains scripts and aggregate results only. Do not infer that the existing Zenodo archive already contains these files.

## Included and excluded material

Included: English experiment runner, shared compatible API helper, offline analysis and mocked tests, aggregate paired and review statistics. Excluded: source questions, answer keys, full manual annotations, raw response logs and credentials. Obtain MedQA from its original release and follow its terms: https://arxiv.org/abs/2009.13081

## Local setup

Install the requirements in a separate environment. Place the four experiment logs in a `medqa_external_v1` folder beside the scripts if privately reproducing the paired analysis. The analysis expects the filenames recorded in `analyze_medqa_external.py`; raw files are not distributed here. Running `python analyze_medqa_external.py` is offline. Running `python medqa_external.py run` without `--check-only` sends API requests and may incur charges.

Use `python medqa_external.py --help` and `python medqa_external.py run --help` for input and endpoint parameters. The runner expects a complete chat/completions URL, not only a provider root. API credentials are read from an environment variable, never embedded in the package. Provider identifiers are service names, not inspectable model weights. API availability and pricing must be checked separately before new runs.

## Reporting conventions

MedQA results use first non-transport-error responses per item for retrospective primary analysis; unparsed responses count as incorrect. Latest-response scoring is a sensitivity result and gives a different independent-answer count (1100 rather than 1099). The primary analysis convention was consolidated after outcomes and is not preregistered. Four paired comparisons form the exploratory Holm family. Bootstrap intervals in additional_local_analyses.json use 10000 paired item-level resamples and seed 20261011. They are not multiplicity-adjusted.

Self-verification includes 26 truncated outputs. Parseable-subset analysis is outcome-dependent and does not replace full operational scoring. Review labels are multilabel annotations of 94 selected correctness-changing cases, confirmed by one original reviewer after AI assistance; they are not independent clinical adjudication or hidden reasoning labels.

## Release checklist

Confirm the parent repository license applies to these scripts, inspect filenames and repository placement, and review aggregate disclosure before committing. This package does not grant rights to redistribute the underlying dataset. Publish a versioned release and verify the new Zenodo record before updating manuscript archive claims. Do not overwrite existing source files without reviewing overlapping changes.

## Retrospective random budget replay

The offline_budget_replay.json file reuses stored responses at seven call budgets and 20 fixed allocation seeds. It is not a new API experiment, learned selector, independent replication or end-to-end latency measurement. No statistically established superiority over independent verifier-model answering is claimed.
