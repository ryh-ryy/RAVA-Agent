"""English MedQA experiment; no API requests during prepare/check commands."""
import argparse
import csv
import hashlib
import json
import os
import sys
import re
import time
from pathlib import Path

# Also support runpy launchers whose sys.path does not include this directory.
SCRIPT_DIR = str(Path(__file__).resolve().parent)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

VERSION = 'medqa-en-v1'
SYSTEM = 'You answer medical examination questions for research evaluation, not patient care.'

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def load(path):
    return [json.loads(s) for s in Path(path).read_text(encoding='utf-8-sig').splitlines() if s.strip()]

def extract(text):
    matches = re.findall(r'FINAL\s*:\s*([A-D])\b', text.upper())
    return matches[-1] if matches else ''

def safe_diagnostic(exc):
    """Allowlisted clues only; never print response bodies, URLs or headers."""
    queue = [exc]; seen = set(); types = []; codes = []; clues = set()
    patterns = {'connection reset':'connection_reset', '10054':'connection_reset',
        'remote end closed':'remote_disconnected', 'timed out':'timeout',
        'certificate verify failed':'certificate_verification_failed',
        'name resolution':'dns_failure', 'getaddrinfo failed':'dns_failure',
        'eof':'unexpected_eof', 'connection refused':'connection_refused'}
    while queue:
        value = queue.pop()
        if not isinstance(value, BaseException) or id(value) in seen: continue
        seen.add(id(value)); types.append(type(value).__name__)
        for field in ('errno','winerror'):
            code = getattr(value, field, None)
            if isinstance(code, int): codes.append(code)
        message = str(value).lower()
        clues.update(label for text, label in patterns.items() if text in message)
        match = re.search(r'http (\d{3}) from provider', message)
        if match: codes.append(int(match.group(1)))
        queue.extend([value.__cause__, value.__context__] + list(value.args))
    return {'exception_chain': types, 'codes': sorted(set(codes)), 'clues': sorted(clues)}

def prepare(args):
    dest = Path(args.output); dest.mkdir(parents=True, exist_ok=True)
    manifest = {'version': VERSION, 'splits': {}}
    for split in ('test', 'dev'):
        source = Path(args.source) / f'phrases_no_exclude_{split}.jsonl'
        rows = load(source); converted = []; seen = set()
        for index, row in enumerate(rows):
            assert set(row['options']) == set('ABCD'), 'Expected four options'
            assert row['answer_idx'] in row['options'], 'Invalid gold label'
            assert row['options'][row['answer_idx']] == row['answer'], 'Gold text mismatch'
            question_hash = hashlib.sha256(row['question'].strip().encode()).hexdigest()
            assert question_hash not in seen, 'Duplicate question within split'
            seen.add(question_hash)
            converted.append({'case_id': f'medqa_us4_{split}_{index:05d}',
                'source_id': question_hash, 'case_prompt': row['question'] + '\n\n' +
                '\n'.join(f'{k}. {row["options"][k]}' for k in 'ABCD'),
                'gold_answer': row['answer_idx'], 'stratum': row.get('meta_info', '')})
        for name, subset in [(split, converted)] + ([('smoke', converted[:5])] if split == 'dev' else []):
            with (dest / f'{name}.csv').open('w', encoding='utf-8-sig', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=list(converted[0])); writer.writeheader(); writer.writerows(subset)
        manifest['splits'][split] = {'records': len(rows), 'source': str(source), 'sha256': digest(source), 'question_hashes': sorted(seen)}
    overlap = set(manifest['splits']['test']['question_hashes']) & set(manifest['splits']['dev']['question_hashes'])
    manifest['dev_test_question_overlap'] = len(overlap)
    (dest / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps({k: v['records'] for k,v in manifest['splits'].items()} | {'dev_test_overlap': len(overlap)}))

def run(args):
    with open(args.input, encoding='utf-8-sig', newline='') as handle:
        items = list(csv.DictReader(handle))
    assert len({r['case_id'] for r in items}) == len(items), 'Duplicate case IDs'
    bases = {r['case_id']: r for r in load(args.baseline)} if args.baseline else {}
    if args.mode != 'direct':
        assert args.baseline, 'A fixed Direct baseline is required'
        for item in items:
            base = bases[item['case_id']]
            assert base['method'] == 'direct' and not base.get('error') and base.get('predicted_answer'), 'Complete parsed Direct baseline first'
            assert base['item'] == item, 'Baseline and input differ'
    config = {'version': VERSION, 'mode': args.mode, 'model': args.model,
        'url': args.base_url, 'max_tokens': args.max_tokens,
        'input_sha256': digest(args.input), 'baseline_sha256': digest(args.baseline) if args.baseline else None}
    thinking = getattr(args, 'enable_thinking', None)
    thinking = None if thinking is None else thinking == 'true'
    if thinking is not None:
        config['enable_thinking'] = thinking
    if getattr(args, 'answer_only', False):
        config['answer_only'] = True
    fingerprint = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    target = Path(args.output); target.parent.mkdir(parents=True, exist_ok=True)
    completed = {}
    if target.exists():
        for row in load(target):
            assert row['config_hash'] == fingerprint, 'Output belongs to a different configuration; use a new file'
            completed[row['case_id']] = row
    pending = [r for r in items if r['case_id'] not in completed or completed[r['case_id']].get('error') or not completed[r['case_id']].get('predicted_answer')]
    print(f'{len(items)} items; {len(pending)} pending requests', flush=True)
    if args.check_only:
        print('Validated locally; no API requests made.'); return
    from run_cmb_exam import call
    key = os.environ.get(args.api_key_env)
    assert key, f'Missing environment variable {args.api_key_env}'
    import requests
    transport = requests.Session()
    transport.trust_env = not getattr(args, 'direct_connection', False)
    with target.open('a', encoding='utf-8') as handle:
        for index, item in enumerate(pending, 1):
            print(f'[{index}/{len(pending)}] {item["case_id"]}', flush=True)
            base = bases.get(item['case_id'])
            instruction = 'Choose the single best answer. You may give a brief explanation. End with exactly FINAL: X, where X is A, B, C, or D.'
            if getattr(args, 'answer_only', False):
                instruction = 'Choose the single best answer. Do not output explanations or reasoning. Output exactly one line: FINAL: X, where X is A, B, C, or D.'
            prompt = item['case_prompt'] + '\n\n' + instruction
            if args.mode == 'verify':
                prompt = item['case_prompt'] + '\n\nInitial answer:\n' + base['initial_answer'] + '\n\nIndependently check the question, options, and initial answer. ' + instruction
            # independent mode intentionally does NOT expose the initial answer.
            row = {'case_id': item['case_id'], 'item': item, 'method': args.mode,
                'model': args.model, 'config': config, 'config_hash': fingerprint}
            row['transport'] = {'trust_env': transport.trust_env, 'attempts': getattr(args, 'attempts', 6)}
            began = time.perf_counter()
            try:
                answer, raw = call([{'role':'system','content':SYSTEM}, {'role':'user','content':prompt}], args.model, args.base_url, key, args.max_tokens, thinking, transport=transport, attempts=getattr(args, 'attempts', 6))
                row.update(final_answer=answer, predicted_answer=extract(answer), usage=raw.get('usage'), finish_reason=raw['choices'][0].get('finish_reason'))
                row['correct'] = row['predicted_answer'] == item['gold_answer']
                row['request_seconds'] = time.perf_counter() - began
                if args.mode == 'direct': row['initial_answer'] = answer
                else:
                    row['initial_answer'] = base['initial_answer']
                    row['initial_predicted_answer'] = base['predicted_answer']
                    row['baseline_request_seconds'] = base['request_seconds']
            except Exception as exc:
                # Do not log provider response bodies or secrets.
                row['error'] = type(exc).__name__
                row['error_diagnostic'] = safe_diagnostic(exc)
                print(json.dumps(row['error_diagnostic']), flush=True)
            handle.write(json.dumps(row, ensure_ascii=False) + '\n'); handle.flush()
            if row.get('error'):
                raise RuntimeError('Request failed; stopped to avoid repeated paid failures. Rerun the same command to resume.')

def score(args):
    for path in args.files:
        latest = {r['case_id']: r for r in load(path)}; rows = list(latest.values())
        print(json.dumps({'file': path, 'records': len(rows), 'errors': sum(bool(r.get('error')) for r in rows),
            'parsed': sum(bool(r.get('predicted_answer')) for r in rows),
            'correct': sum(bool(r.get('correct')) and not r.get('error') for r in rows),
            'accuracy_all': sum(bool(r.get('correct')) and not r.get('error') for r in rows)/len(rows) if rows else None,
            'note': 'Latest attempt per case; independent is a separate answer, not an ensemble. Full coverage must be checked against input.'}))

if __name__ == '__main__':
    p = argparse.ArgumentParser(); sub = p.add_subparsers(dest='command', required=True)
    q = sub.add_parser('prepare'); q.add_argument('--source', required=True); q.add_argument('--output', required=True)
    q = sub.add_parser('run')
    for name in ('input','output','model','base-url','api-key-env'): q.add_argument('--'+name, required=True)
    q.add_argument('--mode', choices=['direct','verify','independent'], required=True)
    q.add_argument('--baseline'); q.add_argument('--max-tokens', type=int, default=512); q.add_argument('--check-only', action='store_true')
    q.add_argument('--direct-connection', action='store_true', help='Ignore environment/system proxy discovery for this run only')
    q.add_argument('--enable-thinking', choices=['true','false'], help='Explicit thinking mode; use a new output file when changing it')
    q.add_argument('--answer-only', action='store_true', help='Require only FINAL: X; a separately versioned experimental condition')
    q.add_argument('--attempts', type=int, choices=range(1,7), default=6, help='Use 1 when diagnosing failures to avoid repeated requests')
    q = sub.add_parser('score'); q.add_argument('files', nargs='+')
    args = p.parse_args(); {'prepare':prepare,'run':run,'score':score}[args.command](args)
