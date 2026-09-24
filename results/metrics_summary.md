# Source_id-disjoint 500-item replication summary

| Model | Policy | Correct / 500 | Accuracy | Paired p vs Direct | Total calls |
|---|---:|---:|---:|---:|---:|
| Qwen3.8-27B | Direct | 442 | 88.4% | — | 500 |
| Qwen3.8-27B | Always-Verify | 448 | 89.6% | 0.307 | 1,000 |
| Qwen3.8-27B | High-only | 446 | 89.2% | 0.597 | 532 |
| Qwen3.8-27B | Medium+High | 444 | 88.8% | 0.845 | 678 |
| Kimi K2.6 | Direct | 470 | 94.0% | — | 500 |
| Kimi K2.6 | Always-Verify | 471 | 94.2% | 1.000 | 1,000 |
| Kimi K2.6 | High-only | 470 | 94.0% | 1.000 | 532 |
| Kimi K2.6 | Medium+High | 468 | 93.6% | 0.500 | 678 |
| DeepSeek-V4-Flash-0731 | Direct | 448 | 89.6% | — | 500 |
| DeepSeek-V4-Flash-0731 | Always-Verify | 447 | 89.4% | 1.000 | 1,000 |
| DeepSeek-V4-Flash-0731 | High-only | 446 | 89.2% | 0.500 | 532 |
| DeepSeek-V4-Flash-0731 | Medium+High | 446 | 89.2% | 0.625 | 678 |

These are engineering benchmark outcomes. They do not establish clinical validity, safety, risk-routing accuracy, evidence relevance, or appropriateness of handoff.
