"""Create non-clinical error and disagreement reports for CMB-Exam JSONL logs."""
import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


def load(path):
    rows = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            rows[row["case_id"]] = row
    return rows


def label(direct, other):
    d, o = bool(direct.get("correct")), bool(other.get("correct"))
    if not d and o:
        return "direct_wrong_other_correct"
    if d and not o:
        return "direct_correct_other_wrong"
    if not d and not o and direct.get("predicted_answer") != other.get("predicted_answer"):
        return "both_wrong_option_changed"
    if not d and not o:
        return "both_wrong_same_option"
    return "both_correct"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--direct", required=True)
    parser.add_argument("--comparison", required=True)
    parser.add_argument("--output-prefix", required=True)
    args = parser.parse_args()
    direct, comparison = load(args.direct), load(args.comparison)
    records, by_exam, by_route = [], Counter(), Counter()
    for case_id in sorted(set(direct) & set(comparison)):
        d, c = direct[case_id], comparison[case_id]
        item = d.get("item", {})
        row = {
            "case_id": case_id,
            "exam_type": item.get("exam_type", ""),
            "exam_subject": item.get("exam_subject", ""),
            "gold_answer": item.get("gold_answer", ""),
            "direct_answer": d.get("predicted_answer", ""),
            "comparison_answer": c.get("predicted_answer", ""),
            "direct_correct": d.get("correct", False),
            "comparison_correct": c.get("correct", False),
            "comparison_route": c.get("risk_route", "not_applicable"),
            "comparison_verified": c.get("verification_used", False),
            "outcome_type": label(d, c),
        }
        records.append(row)
        by_exam[(row["exam_type"], row["outcome_type"])] += 1
        by_route[(row["comparison_route"], row["outcome_type"])] += 1
    prefix = Path(args.output_prefix); prefix.parent.mkdir(parents=True, exist_ok=True)
    fields = list(records[0]) if records else []
    with prefix.with_suffix(".csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(records)
    lines = ["# CMB-Exam 分歧与错误类型报告", "", "本报告仅描述公开客观题的答案变化；不得解释为临床安全性或风险识别表现。", "", "## 按考试类别", "", "| 考试类别 | 结果类型 | 题数 |", "|---|---|---:|"]
    for (exam, outcome), count in sorted(by_exam.items()): lines.append(f"| {exam} | {outcome} | {count} |")
    lines += ["", "## 按规则路由", "", "| 路由 | 结果类型 | 题数 |", "|---|---|---:|"]
    for (route, outcome), count in sorted(by_route.items()): lines.append(f"| {route} | {outcome} | {count} |")
    lines += ["", "## 建议人工后续审查的题目", "", "优先审查 `direct_correct_other_wrong` 和 `direct_wrong_other_correct` 两类；它们分别表示核验可能造成的破坏与修正。审查时应保持盲法，不应依据本报告回调风险词或提示词后再在同一测试集上宣称新结果。"]
    prefix.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"paired_cases": len(records), "outcomes": Counter(r["outcome_type"] for r in records)}, ensure_ascii=False, indent=2, default=dict))


if __name__ == "__main__":
    main()
