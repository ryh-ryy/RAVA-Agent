"""Run a lightweight, auditable evidence-verification medical-agent prototype.

This research tool is deliberately conservative. It does not use CMB gold answers
or case-template reference answers as retrieval evidence; doing so would leak
labels. Instead it retrieves only rows from a separately supplied, permitted
evidence corpus and records every action in JSONL.

It is not clinical software and must never receive identifiable patient data.
"""

import argparse
import csv
import json
import os
import re
import time
from pathlib import Path

import requests


SYSTEM = """You are a research-only medical information assistant, not a clinician.
Do not invent clinical facts or citations. Do not provide prescription, dosing, or
definitive diagnosis instructions. When evidence is insufficient, state the
limitation and recommend review by a qualified clinician. Return concise Chinese.
"""


def call_model(messages, model, max_tokens=1200):
    url, key = os.environ["DASHSCOPE_CHAT_URL"], os.environ["DASHSCOPE_API_KEY"]
    payload = {"model": model, "messages": messages, "temperature": 0, "max_tokens": max_tokens}
    last_error = None
    for attempt in range(3):
        try:
            response = requests.post(url, headers={"Content-Type": "application/json", "Authorization": "Bearer " + key}, json=payload, timeout=180)
            if response.status_code == 429 or response.status_code >= 500:
                response.raise_for_status()
            response.raise_for_status()
            raw = response.json()
            return raw["choices"][0]["message"]["content"], raw
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as error:
            last_error = error
        except requests.exceptions.HTTPError as error:
            if error.response is None or (error.response.status_code != 429 and error.response.status_code < 500):
                raise
            last_error = error
        if attempt < 2:
            time.sleep(2 ** attempt)
    raise last_error


def tokens(text):
    lowered = text.lower()
    words = re.findall(r"[a-z0-9_]+", lowered)
    chinese = re.findall(r"[\u4e00-\u9fff]", lowered)
    # Chinese unigrams caused unrelated records to match on common characters.
    # Bigrams retain more specificity without an external tokenizer.
    return set(words + ["".join(chinese[i:i + 2]) for i in range(max(0, len(chinese) - 1))])


def read_corpus(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    required = {"evidence_id", "title", "content", "source_url", "license_or_permission"}
    if not rows:
        return []
    missing = required - set(rows[0])
    if missing:
        raise ValueError("Evidence corpus missing columns: " + ", ".join(sorted(missing)))
    usable = []
    for row in rows:
        if not row.get("evidence_id", "").startswith("EXAMPLE_") and row.get("content", "").strip():
            usable.append(row)
    return usable


def retrieve(query, corpus, top_k, min_score, relevance_terms_by_id=None):
    query_tokens = tokens(query)
    scored = []
    for row in corpus:
        # A manually maintained relevance index is more conservative than using
        # all evidence prose, which contains generic medical words. If absent,
        # only title/topic (not content) are considered.
        indexed_terms = (relevance_terms_by_id or {}).get(row["evidence_id"])
        if indexed_terms:
            # Explicit phrases prevent a term like "呼吸" in a vital-sign field
            # from being treated as the clinical phrase "呼吸困难".
            score = sum(term.lower() in query.lower() for term in indexed_terms)
        else:
            document = " ".join(row.get(key, "") for key in ("topic", "title"))
            score = len(query_tokens & tokens(document))
        if score >= min_score:
            scored.append((score, row))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["evidence_id"]))
    return [{"evidence_id": row["evidence_id"], "title": row["title"], "content": row["content"], "source_url": row["source_url"], "score": score} for score, row in scored[:top_k]]


def route_risk(case_text, policy):
    lowered = case_text.lower()
    high = [term for term in policy["high_risk_terms"] if term.lower() in lowered]
    medium = [term for term in policy["medium_risk_terms"] if term.lower() in lowered]
    if high:
        return "high", high
    if medium:
        return "medium", medium
    return "low", []


def usage(raw):
    data = raw.get("usage", {}) if isinstance(raw, dict) else {}
    return {key: data.get(key) for key in ("prompt_tokens", "completion_tokens", "total_tokens") if key in data}


def conservative_handoff(risk, reason):
    return """该研究原型将此问题路由为 {risk} 风险，但 {reason}。为避免把不确定信息表述为临床结论，系统不输出诊断、处方、剂量或个体化处置建议；建议由临床医生复核。""".format(risk=risk, reason=reason)


def initial_answer(case_text, model):
    prompt = "病例或医学问题：\n{}\n\n给出研究用途的初步信息摘要，必须包括：可能结论、病例内依据、信息缺口和风险提示。".format(case_text)
    return call_model([{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}], model)


def verify_with_evidence(case_text, draft, evidence, risk, model):
    evidence_text = "\n\n".join("[{}] {}\n{}\n来源：{}".format(item["evidence_id"], item["title"], item["content"], item["source_url"]) for item in evidence)
    prompt = """病例或医学问题：
{case}

初步回答：
{draft}

允许使用的证据摘录：
{evidence}

风险等级：{risk}

请核验初步回答。只可引用以上证据 ID；若证据无法支持关键结论、病例信息不足或风险为高，请明确写“建议由临床医生复核”。输出：最终研究用途回答；证据 ID；信息缺口；风险处置。""".format(case=case_text, draft=draft, evidence=evidence_text, risk=risk)
    return call_model([{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}], model)


def verify_without_evidence(case_text, draft, risk, model):
    prompt = """病例或医学问题：
{case}

初步回答：
{draft}

风险等级：{risk}

请独立核验初步回答是否遗漏信息缺口、急症分流或不当确定性。不得编造病例事实或外部证据。若信息不足或风险为高，必须明确写“建议由临床医生复核”。输出最终研究用途回答、信息缺口和风险处置。""".format(case=case_text, draft=draft, risk=risk)
    return call_model([{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}], model)


def run_case(case, corpus, policy, model, mode):
    case_text = case.get("case_prompt", "").strip()
    if not case_text:
        raise ValueError("case_prompt is empty")
    started = time.perf_counter()
    audit = {"case_id": case.get("case_id"), "method": "rava_agent", "model": model, "case": case, "action_trace": [], "api_calls": 0}
    risk, matched_terms = route_risk(case_text, policy)
    audit.update({"risk_route": risk, "matched_policy_terms": matched_terms, "policy_version": policy.get("policy_version")})
    audit["action_trace"].append({"action": "risk_route", "risk": risk, "matched_terms": matched_terms})
    draft, raw = initial_answer(case_text, model)
    audit.update({"initial_answer": draft, "initial_usage": usage(raw)})
    audit["api_calls"] += 1
    if risk == "low":
        audit.update({"final_answer": draft, "verification_used": False, "handoff_recommended": False})
        audit["action_trace"].append({"action": "return_direct"})
    elif mode == "rule_gated":
        final, verification_raw = verify_without_evidence(case_text, draft, risk, model)
        audit.update({"final_answer": final, "verification_used": True, "verification_usage": usage(verification_raw), "handoff_recommended": risk == "high"})
        audit["api_calls"] += 1
        audit["action_trace"].append({"action": "verify_without_evidence"})
    else:
        # Retrieve only from the original input. Including model-generated drafts
        # made generic phrases (e.g. "临床医生") inflate relevance scores.
        evidence = retrieve(case_text, corpus, int(policy.get("retrieval_top_k", 3)), int(policy.get("retrieval_min_score", 1)), policy.get("evidence_relevance_terms"))
        audit["retrieved_evidence"] = evidence
        audit["action_trace"].append({"action": "retrieve_evidence", "count": len(evidence), "evidence_ids": [x["evidence_id"] for x in evidence]})
        if risk in policy.get("force_handoff_risks", []):
            audit.update({
                "final_answer": conservative_handoff(risk, "当前研究策略不允许该风险层级使用大模型生成证据核验结论"),
                "verification_used": False, "handoff_recommended": True,
            })
            audit["action_trace"].append({"action": "handoff_policy"})
        elif risk == "high" and not evidence and policy.get("handoff_if_no_evidence_for_high_risk", True):
            audit.update({
                "final_answer": conservative_handoff(risk, "当前证据库没有足够相关、可审计的支持性资料"),
                "verification_used": False, "handoff_recommended": True,
            })
            audit["action_trace"].append({"action": "handoff_no_evidence"})
        elif evidence:
            final, verification_raw = verify_with_evidence(case_text, draft, evidence, risk, model)
            audit.update({"final_answer": final, "verification_used": True, "verification_usage": usage(verification_raw), "handoff_recommended": risk == "high"})
            audit["api_calls"] += 1
            audit["action_trace"].append({"action": "verify_with_evidence"})
        else:
            audit.update({"final_answer": conservative_handoff(risk, "当前证据库没有足够相关、可审计的支持性资料"), "verification_used": False, "handoff_recommended": True})
            audit["action_trace"].append({"action": "handoff_no_evidence"})
    audit["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    return audit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="De-identified case CSV containing case_id and case_prompt")
    parser.add_argument("--evidence", help="Permitted evidence-corpus CSV; required only when --mode agent")
    parser.add_argument("--policy", required=True, help="Expert-reviewed policy JSON")
    parser.add_argument("--output", required=True)
    parser.add_argument("--mode", choices=["agent", "rule_gated"], default="agent")
    parser.add_argument("--model", default="qwen3.8-27b")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    for variable in ("DASHSCOPE_API_KEY", "DASHSCOPE_CHAT_URL"):
        if not os.environ.get(variable):
            raise EnvironmentError("Missing " + variable)
    with Path(args.input).open(encoding="utf-8-sig", newline="") as handle:
        cases = [row for row in csv.DictReader(handle) if row.get("case_prompt", "").strip()]
    if args.limit:
        cases = cases[:args.limit]
    if args.mode == "agent" and not args.evidence:
        raise ValueError("--evidence is required when --mode agent")
    corpus = read_corpus(args.evidence) if args.evidence else []
    if args.mode == "agent" and not corpus:
        raise ValueError("No usable evidence rows. Fill the corpus with permitted, reviewed evidence; do not use answer keys.")
    policy = json.loads(Path(args.policy).read_text(encoding="utf-8"))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for index, case in enumerate(cases, 1):
            print("[{}/{}] {}".format(index, len(cases), case.get("case_id", "unknown")))
            try:
                row = run_case(case, corpus, policy, args.model, args.mode)
                row["mode"] = args.mode
            except Exception as error:
                row = {"case_id": case.get("case_id"), "method": "rava_agent", "case": case, "error": repr(error)}
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()


if __name__ == "__main__":
    main()
