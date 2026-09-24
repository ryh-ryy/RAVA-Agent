# RAVA-Agent: Auditable Risk-Aware Evidence Verification

This repository accompanies the submission **“An Auditable Risk-Aware Verification Agent for Medical Question Answering: Selective Self-Verification and Resource Allocation Across Large Language Models.”**

RAVA-Agent represents risk routing, evidence retrieval, selective same-model verification, conservative handoff, and audit logging as explicit agent actions. This release supports **engineering reproducibility only**. It does not establish clinical correctness, safety, risk-recognition accuracy, evidence adequacy, or handoff appropriateness.

## What is included

- Frozen, versioned routing policies used for the no-expert engineering experiments.
- Runner, scoring, paired-comparison, disagreement-analysis, and audit scripts.
- A source_id-disjoint 500-item replication manifest (identifiers and strata only; no question text or labels).
- Aggregated paired-analysis outputs for Qwen3.8-27B, Kimi K2.6, and DeepSeek-V4-Flash-0731.
- The Figure 1 source (SVG) and insertion-ready PNG.

## What is deliberately excluded

- API keys, credentials, endpoints tied to accounts, and private paths.
- CMB-Exam question text, answer labels, and full per-item model logs. Obtain the benchmark from its official source and comply with its licence/terms before running the code.
- Any real patient data, private case material, or clinical expert annotations.

## Reproduction outline

1. Download CMB-Exam from the original public source and comply with its terms of use. The benchmark is described by Wang et al. (2024), DOI: `10.18653/v1/2024.naacl-long.343`.
2. Create an environment with Python 3.9+ and install dependencies: `pip install -r requirements.txt`.
3. Set your provider key only in the environment, for example PowerShell: `$env:DASHSCOPE_API_KEY = "..."`. Never commit this value.
4. Prepare a local CSV in the runner’s expected schema. Use `data/replication_manifest.csv` to reproduce the source_id-disjoint 500-item stratum after locally joining it to the officially obtained benchmark.
5. Run a policy, e.g.:
   ```powershell
   python code/run_cmb_exam.py --input <local_replication.csv> --output results/<run>.jsonl --method rule_gated --policy config/agent_policy_high_only_no_expert.json --model <provider-model> --base-url <provider-url> --api-key-env DASHSCOPE_API_KEY --provider-label <provider>
   ```
6. Score and compare paired runs with `code/score_cmb_exam.py` and `code/analyze_paired_exam.py`.

## Main engineering finding

On the source_id-disjoint 500-item replication set, full same-model verification was not associated with a statistically significant paired accuracy gain for Qwen3.8-27B, Kimi K2.6, or DeepSeek-V4-Flash-0731. Frozen High-only and Medium+High gates reproducibly allocated 532 and 678 calls, versus 1,000 calls for Always-Verify. See `results/`.

## Responsible-use boundary

The policies are researcher specified and were not independently approved by medical experts. They are frozen research artifacts for resource-allocation experiments, **not** clinical risk classifiers. Do not use them for diagnosis, treatment, prescription, triage, or patient-facing decision-making.

## Citation

Add the final paper citation and repository DOI here after acceptance/archive creation.

