"""Offline tests: mock the transport so no credentials or API calls are used."""
import csv
import json
import os
import tempfile
import sys
import types
from pathlib import Path
from types import SimpleNamespace
import medqa_external as experiment
try:
    import requests
except ImportError:
    sys.modules['requests'] = types.ModuleType('requests')
    sys.modules['requests'].Session = lambda: SimpleNamespace(trust_env=True)
import run_cmb_exam

def main():
    assert experiment.extract('Explanation\nFINAL: B') == 'B'
    assert experiment.extract('FINAL: E') == ''
    assert experiment.extract('B is possible') == ''
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder); source = root / 'items.csv'
        item = {'case_id':'test1','case_prompt':'Question\nA. one\nB. two\nC. three\nD. four','gold_answer':'B'}
        with source.open('w', newline='', encoding='utf-8-sig') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(item)); writer.writeheader(); writer.writerow(item)
        requests = []
        def fake(messages, *args, **kwargs):
            requests.append(messages)
            assert 'gold_answer' not in messages[1]['content']
            return 'FINAL: B', {'choices':[{'finish_reason':'stop'}], 'usage':{'total_tokens':10}}
        run_cmb_exam.call = fake; os.environ['MEDQA_OFFLINE_TEST_KEY'] = 'not-a-real-key'
        args = SimpleNamespace(input=str(source), output=str(root/'direct.jsonl'), mode='direct', model='mock', base_url='https://example.invalid', api_key_env='MEDQA_OFFLINE_TEST_KEY', max_tokens=512, baseline=None, check_only=False)
        experiment.run(args); experiment.run(args)
        assert len(requests) == 1, 'Resume should skip completed rows'
        args.baseline = args.output; args.mode = 'verify'; args.output = str(root/'verify.jsonl')
        experiment.run(args)
        assert 'Initial answer:' in requests[-1][1]['content']
        args.mode = 'independent'; args.output = str(root/'independent.jsonl'); experiment.run(args)
        assert 'Initial answer:' not in requests[-1][1]['content']
        args.max_tokens = 256
        try: experiment.run(args)
        except AssertionError: pass
        else: raise AssertionError('Changed settings must reject resume')
    print('PASS: parsing, fixed baseline, independent control, resume, configuration guard; zero real API calls')

if __name__ == '__main__': main()
