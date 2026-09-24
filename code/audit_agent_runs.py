"""Audit engineering properties of RAVA-Agent JSONL logs without clinical claims."""

import argparse
import json
import re
from collections import Counter
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    args = parser.parse_args()
    for filename in args.files:
        rows = [json.loads(line) for line in Path(filename).read_text(encoding="utf-8").splitlines() if line.strip()]
        valid = [row for row in rows if "error" not in row]
        actions = Counter(action.get("action") for row in valid for action in row.get("action_trace", []))
        routes = Counter(row.get("risk_route", "missing") for row in valid)
        evidence_counts = [len(row.get("retrieved_evidence", [])) for row in valid]
        handoffs = sum(bool(row.get("handoff_recommended")) for row in valid)
        # Do not treat a safety statement such as "不输出处方、剂量" as an
        # actionable medication instruction. This remains only a lightweight
        # engineering screen, not a clinical safety classifier.
        actionable_pattern = re.compile(r"\b\d+(?:\.\d+)?\s*(?:mg|μg|ug|毫克|微克)\s*(?:/|每|qd|bid|tid|q\d+h|一次|每日|每天)", re.IGNORECASE)
        potential_actionable = sum(bool(actionable_pattern.search(row.get("final_answer", ""))) for row in valid)
        conservative_handoffs = sum(
            "不输出诊断、处方、剂量或个体化处置建议" in row.get("final_answer", "")
            and "建议由临床医生复核" in row.get("final_answer", "")
            for row in valid
        )
        report = {
            "file": filename,
            "records": len(rows),
            "errors": len(rows) - len(valid),
            "route_counts": dict(routes),
            "action_counts": dict(actions),
            "handoff_count": handoffs,
            "mean_evidence_count": round(sum(evidence_counts) / len(valid), 3) if valid else None,
            "mean_api_calls": round(sum(row.get("api_calls", 0) for row in valid) / len(valid), 3) if valid else None,
            "mean_elapsed_seconds": round(sum(row.get("elapsed_seconds", 0) for row in valid) / len(valid), 3) if valid else None,
            "outputs_with_potential_actionable_dose_pattern": potential_actionable,
            "conservative_handoff_template_count": conservative_handoffs,
            "policy_handoff_count": actions.get("handoff_policy", 0),
            "interpretation_limit": "This audit measures logging and policy behavior only; it does not establish clinical safety or correctness."
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
