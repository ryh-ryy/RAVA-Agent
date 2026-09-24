"""Score one or more JSONL files created by run_cmb_exam.py."""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    args = parser.parse_args()
    for filename in args.files:
        rows = [json.loads(line) for line in Path(filename).read_text(encoding="utf-8").splitlines() if line.strip()]
        valid = [row for row in rows if "error" not in row]
        parsed = [row for row in valid if row.get("predicted_answer")]
        correct = sum(bool(row.get("correct")) for row in valid)
        total_time = sum(row.get("elapsed_seconds", 0) for row in valid)
        print(json.dumps({
            "file": filename, "records": len(rows), "errors": len(rows) - len(valid),
            "parsed": len(parsed), "accuracy_all": round(correct / len(rows), 4) if rows else None,
            "accuracy_valid": round(correct / len(valid), 4) if valid else None,
            "mean_seconds_valid": round(total_time / len(valid), 2) if valid else None,
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
