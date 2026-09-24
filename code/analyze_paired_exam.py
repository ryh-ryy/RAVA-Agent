"""Paired analysis for Direct and Verify CMB-Exam JSONL audit logs.

Writes a machine-readable JSON summary and a Markdown report. It intentionally
does not infer clinical performance; input is limited to objective answer keys.
"""

import argparse
import json
import math
from pathlib import Path


def load(path):
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    return {str(row.get("case_id", row.get("question_id", row.get("id", row.get("index", i))))): row for i, row in enumerate(rows)}


def wilson(successes, total, z=1.959963984540054):
    if not total:
        return None, None
    p = successes / total
    den = 1 + z * z / total
    center = (p + z * z / (2 * total)) / den
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / den
    return center - half, center + half


def exact_mcnemar_pvalue(b, c):
    # Two-sided exact binomial test for discordant pairs; no scipy dependency.
    n = b + c
    if not n:
        return 1.0
    k = min(b, c)
    cumulative = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * cumulative)


def describe(rows):
    total = len(rows)
    correct = sum(bool(row.get("correct")) for row in rows)
    seconds = [float(row.get("elapsed_seconds", 0)) for row in rows]
    lo, hi = wilson(correct, total)
    return {
        "n": total, "correct": correct, "accuracy": correct / total if total else None,
        "wilson_95_ci": [lo, hi], "mean_seconds": sum(seconds) / total if total else None,
        "median_seconds": sorted(seconds)[total // 2] if total else None,
        "errors": sum("error" in r for r in rows),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--direct", required=True)
    parser.add_argument("--verify", required=True)
    parser.add_argument("--output-prefix", required=True)
    args = parser.parse_args()

    direct, verify = load(args.direct), load(args.verify)
    ids = sorted(set(direct) & set(verify))
    drows, vrows = [direct[i] for i in ids], [verify[i] for i in ids]
    b = sum((not bool(direct[i].get("correct"))) and bool(verify[i].get("correct")) for i in ids)
    c = sum(bool(direct[i].get("correct")) and (not bool(verify[i].get("correct"))) for i in ids)
    changed = sum(direct[i].get("predicted_answer") != verify[i].get("predicted_answer") for i in ids)
    dstat, vstat = describe(drows), describe(vrows)
    summary = {
        "paired_questions": len(ids), "direct": dstat, "verify": vstat,
        "accuracy_difference_verify_minus_direct": vstat["accuracy"] - dstat["accuracy"],
        "mean_latency_difference_seconds": vstat["mean_seconds"] - dstat["mean_seconds"],
        "discordant_direct_wrong_verify_correct": b,
        "discordant_direct_correct_verify_wrong": c,
        "changed_final_option": changed,
        "mcnemar_exact_two_sided_p": exact_mcnemar_pvalue(b, c),
    }
    prefix = Path(args.output_prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    prefix.with_suffix(".json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    report = """# 配对客观题统计报告\n\n- 配对题数：{n}\n- Direct：{dc}/{n}（{da:.1%}；Wilson 95% CI {dlo:.1%}–{dhi:.1%}）\n- Verify：{vc}/{n}（{va:.1%}；Wilson 95% CI {vlo:.1%}–{vhi:.1%}）\n- 配对准确率差（Verify − Direct）：{diff:.1%}\n- Direct 错→Verify 对：{b}\n- Direct 对→Verify 错：{c}\n- 最终选项改变：{changed}\n- McNemar 精确双侧 p 值：{p:.4f}\n- 平均延迟差：{lat:.2f} 秒\n\n说明：本报告针对具有公开标准答案的客观题；不得将其解释为临床安全性指标。\n""".format(
        n=len(ids), dc=dstat["correct"], da=dstat["accuracy"], dlo=dstat["wilson_95_ci"][0], dhi=dstat["wilson_95_ci"][1],
        vc=vstat["correct"], va=vstat["accuracy"], vlo=vstat["wilson_95_ci"][0], vhi=vstat["wilson_95_ci"][1],
        diff=summary["accuracy_difference_verify_minus_direct"], b=b, c=c, changed=changed,
        p=summary["mcnemar_exact_two_sided_p"], lat=summary["mean_latency_difference_seconds"])
    prefix.with_suffix(".md").write_text(report, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
