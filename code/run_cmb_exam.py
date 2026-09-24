"""Run Direct and Always-Verify on CMB-Exam single-choice items."""

import argparse
import csv
import json
import os
import re
import time
from pathlib import Path

import requests


SYSTEM = "你是研究用途的医学考试答题助手。仅根据题目作答，不输出诊疗建议。"


def call(messages, model, url, key, max_tokens, enable_thinking):
    last_error = None
    # Keep completed audit rows untouched on transient proxy/server failures.
    # Six attempts improve resume reliability without changing any prompt or
    # decoding setting used for the scientific comparison.
    for attempt in range(6):
        try:
            payload = {"model": model, "messages": messages, "temperature": 0, "max_tokens": max_tokens}
            if enable_thinking is not None:
                payload["enable_thinking"] = enable_thinking
            response = requests.post(url, headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"}, json=payload, timeout=180)
            if response.status_code == 429 or response.status_code >= 500:
                response.raise_for_status()
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"], data
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            last_error = exc
        except requests.exceptions.HTTPError as exc:
            if exc.response is None or (exc.response.status_code != 429 and exc.response.status_code < 500):
                # Preserve provider diagnostics (model availability, endpoint, or
                # parameter validation) in the local audit JSONL.  This changes
                # neither the prompt nor decoding configuration.
                if exc.response is not None:
                    body = exc.response.text[:2000]
                    request_id = (
                        exc.response.headers.get("x-dashscope-request-id")
                        or exc.response.headers.get("x-acs-request-id")
                        or exc.response.headers.get("x-request-id")
                        or "unavailable"
                    )
                    raise RuntimeError(
                        f"HTTP {exc.response.status_code} from provider "
                        f"(request_id={request_id}): {body}"
                    ) from exc
                raise
            last_error = exc
        if attempt < 5:
            time.sleep(min(2 ** attempt, 30))
    raise last_error


def choose(prompt, model, url, key, max_tokens, answer_only, enable_thinking):
    suffix = (
        "请选择唯一正确选项。不要展示推理、解释或其他文字；只输出一行：FINAL: X（X 为 A、B、C、D 或 E）。"
        if answer_only
        else "请选择唯一正确选项。可简要思考，但最后一行必须严格写为：FINAL: X（X 为 A、B、C、D 或 E）。"
    )
    user = f"{prompt}\n\n{suffix}"
    return call([{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}], model, url, key, max_tokens, enable_thinking)


def verify(prompt, draft, model, url, key, max_tokens, answer_only, enable_thinking):
    suffix = (
        "独立复核题干、选项和初始回答。不要展示推理、解释或其他文字；只输出一行：FINAL: X（X 为 A、B、C、D 或 E）。"
        if answer_only
        else "独立复核题干、选项和初始回答。最后一行必须严格写为：FINAL: X（X 为 A、B、C、D 或 E）。"
    )
    user = f"{prompt}\n\n初始回答：\n{draft}\n\n{suffix}"
    return call([{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}], model, url, key, max_tokens, enable_thinking)


def extract(text):
    matches = re.findall(r"FINAL\s*[:：]\s*([A-E])\b", text.upper())
    return matches[-1] if matches else ""


def route_risk(prompt, policy):
    lowered = prompt.lower()
    high = [term for term in policy["high_risk_terms"] if term.lower() in lowered]
    medium = [term for term in policy["medium_risk_terms"] if term.lower() in lowered]
    if high:
        return "high", high
    if medium:
        return "medium", medium
    return "low", []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--method", choices=["direct", "always_verify", "rule_gated"], required=True)
    parser.add_argument("--model", default="qwen3.8-27b")
    parser.add_argument("--policy", help="Required for rule_gated; use the frozen no-expert policy for engineering comparisons")
    parser.add_argument("--base-url", help="OpenAI-compatible /chat/completions URL; defaults to DASHSCOPE_CHAT_URL")
    parser.add_argument("--api-key-env", default="DASHSCOPE_API_KEY", help="Environment variable containing the API key; the key is never written to logs")
    parser.add_argument("--provider-label", default="dashscope", help="Non-secret provider label recorded in audit logs")
    parser.add_argument("--max-tokens", type=int, default=256, help="Maximum completion tokens; keep fixed within a model experiment")
    parser.add_argument("--answer-only", action="store_true", help="Require a one-line FINAL: X response; use only in a newly versioned experiment")
    parser.add_argument("--enable-thinking", choices=["true", "false"], help="Provider thinking-mode flag; record and keep fixed within a model experiment")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resume-from", help="Previous JSONL: reuse successful rows and rerun only missing/error rows")
    parser.add_argument("--rerun-unparsed", action="store_true", help="With --resume-from, also rerun rows whose final answer has no parsable FINAL: A-E")
    args = parser.parse_args()
    enable_thinking = None if args.enable_thinking is None else args.enable_thinking == "true"
    url = args.base_url or os.environ.get("DASHSCOPE_CHAT_URL")
    key = os.environ.get(args.api_key_env)
    if not url:
        raise EnvironmentError("Missing --base-url and DASHSCOPE_CHAT_URL")
    if not key:
        raise EnvironmentError(f"Missing API key environment variable: {args.api_key_env}")

    with open(args.input, encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if args.limit:
        rows = rows[:args.limit]
    if args.method == "rule_gated" and not args.policy:
        raise ValueError("--policy is required when --method rule_gated")
    policy = json.loads(Path(args.policy).read_text(encoding="utf-8")) if args.policy else None
    previous = {}
    if args.resume_from:
        with open(args.resume_from, encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    audit = json.loads(line)
                    if audit.get("method") != args.method:
                        raise ValueError("--resume-from method does not match --method")
                    previous[audit["case_id"]] = audit
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        for index, row in enumerate(rows, start=1):
            cached = previous.get(row["case_id"])
            if cached and "error" not in cached and (not args.rerun_unparsed or cached.get("predicted_answer")):
                print(f"[{index}/{len(rows)}] {row['case_id']} (reuse successful result)")
                handle.write(json.dumps(cached, ensure_ascii=False) + "\n")
                continue
            print(f"[{index}/{len(rows)}] {row['case_id']} ({args.method})")
            started = time.perf_counter()
            audit = {"case_id": row["case_id"], "method": args.method, "model": args.model, "provider_label": args.provider_label, "max_tokens": args.max_tokens, "answer_only": args.answer_only, "enable_thinking": enable_thinking, "item": row}
            try:
                draft, draft_raw = choose(row["case_prompt"], args.model, url, key, args.max_tokens, args.answer_only, enable_thinking)
                audit["initial_answer"], audit["initial_raw"] = draft, draft_raw
                if args.method == "always_verify":
                    final, final_raw = verify(row["case_prompt"], draft, args.model, url, key, args.max_tokens, args.answer_only, enable_thinking)
                    audit["verification_used"], audit["verification_raw"] = True, final_raw
                elif args.method == "rule_gated":
                    risk, matched_terms = route_risk(row["case_prompt"], policy)
                    audit["risk_route"], audit["matched_policy_terms"] = risk, matched_terms
                    if risk in {"medium", "high"}:
                        final, final_raw = verify(row["case_prompt"], draft, args.model, url, key, args.max_tokens, args.answer_only, enable_thinking)
                        audit["verification_used"], audit["verification_raw"] = True, final_raw
                    else:
                        final, audit["verification_used"] = draft, False
                else:
                    final, audit["verification_used"] = draft, False
                audit["final_answer"] = final
                audit["predicted_answer"] = extract(final)
                audit["correct"] = audit["predicted_answer"] == row["gold_answer"]
                audit["elapsed_seconds"] = round(time.perf_counter() - started, 3)
            except Exception as exc:
                audit["error"] = repr(exc)
            handle.write(json.dumps(audit, ensure_ascii=False) + "\n")
            handle.flush()


if __name__ == "__main__":
    main()
