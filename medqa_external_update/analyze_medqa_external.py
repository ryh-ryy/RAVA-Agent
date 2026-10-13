"""Local paired analysis; keep first recorded attempts as primary outcomes."""
import json
import math
from pathlib import Path

ROOT = Path(__file__).parent / 'medqa_external_v1'

def read(name):
    first = {}; latest = {}
    for line in (ROOT / name).read_text(encoding='utf-8').splitlines():
        row = json.loads(line)
        first.setdefault(row['case_id'], row); latest[row['case_id']] = row
    return first, latest

def exact(b,c):
    n=b+c
    return min(1., 2*sum(math.comb(n,k) for k in range(min(b,c)+1))/(2**n)) if n else 1.

def main():
    names = {'direct':'test_direct_answeronly.jsonl','self':'test_self_answeronly.jsonl',
        'cross':'test_cross_answeronly.jsonl','independent':'test_cross_independent_answeronly.jsonl'}
    loaded={k:read(v) for k,v in names.items()}
    result={'policy':'Primary: first non-transport-error response per case; transport retries reported separately. Unparsed responses count as incorrect.', 'groups':{},'pairs':[]}
    groups={}
    for key, name in names.items():
        allrows=[json.loads(s) for s in (ROOT/name).read_text(encoding='utf-8').splitlines() if s.strip()]
        primary={}
        for row in allrows:
            if not row.get('error'): primary.setdefault(row['case_id'],row)
        assert len(primary)==1273, f'{key}: incomplete successful coverage'
        groups[key]=primary
        result['groups'][key]={'n':len(primary),'correct':sum(bool(r.get('correct')) for r in primary.values()),
            'unparsed':sum(not r.get('predicted_answer') for r in primary.values()),
            'recorded_attempts':len(allrows), 'transport_errors':sum(bool(r.get('error')) for r in allrows),
            'response_retries':sum(not r.get('error') for r in allrows)-len(primary),
            'observed_total_tokens':sum((r.get('usage') or {}).get('total_tokens',0) for r in allrows)}
    for a,b in [('direct','cross'),('independent','cross'),('direct','independent'),('direct','self')]:
        assert groups[a].keys()==groups[b].keys()
        gain=loss=changed=0
        for key,x in groups[a].items():
            y=groups[b][key]; assert x['item']==y['item']
            gain+=not bool(x.get('correct')) and bool(y.get('correct'))
            loss+=bool(x.get('correct')) and not bool(y.get('correct'))
            changed+=x.get('predicted_answer')!=y.get('predicted_answer')
        result['pairs'].append({'reference':a,'comparison':b,'n':1273,'corrected':gain,'degraded':loss,
            'changed_or_unparsed':changed,'accuracy_difference':(gain-loss)/1273,'mcnemar_exact_p':exact(gain,loss)})
    # Exploratory family includes all four comparisons, including format failures.
    family=result['pairs']; ordered=sorted(family,key=lambda r:r['mcnemar_exact_p']); running=0.
    for i,row in enumerate(ordered):
        running=max(running,min(1.,(len(ordered)-i)*row['mcnemar_exact_p'])); row['holm_p']=running
    (ROOT/'paired_results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))

if __name__=='__main__': main()
