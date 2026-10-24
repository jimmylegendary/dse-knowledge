"""Conservative point-metric policy; never converts a missing metric into a win."""
import math

POLICY_VERSION='point-pareto-v1'
UNITS={'ms':('time',.001),'s':('time',1),'us':('time',.000001),'W':('power',1),'kW':('power',1000),'J':('energy',1),'J/token':('energy_per_token',1),'tokens/s':('throughput',1),'token/s':('throughput',1),'req/s':('requests',1),'%':('percent',1),'GB':('bytes',1e9),'GiB':('bytes',2**30)}


def validate_metrics(metrics):
    seen=set()
    for m in metrics:
        if not m.get('name') or m['name'] in seen:raise ValueError('Metric names must be unique')
        seen.add(m['name'])
        v=m.get('value')
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):raise ValueError('Metric must be finite')
        if m.get('direction') not in ('min','max'):raise ValueError('Unsupported metric direction')
        if not isinstance(m.get('unit'),str) or not m['unit']:raise ValueError('Metric unit required')


def compare_experiments(baseline,candidate):
    result={'policy_version':POLICY_VERSION,'status':'comparable','dominance':'unknown','comparisons':[],'exclusions':[],
            'limitations':['Point values only; confidence intervals and physical feasibility are not established.']}
    validate_metrics(baseline['metrics']);validate_metrics(candidate['metrics'])
    for key in ('cohort','method'):
        if not baseline.get(key) or baseline.get(key)!=candidate.get(key):result['exclusions'].append(key+'_mismatch')
    if result['exclusions']:result['status']='not_comparable';return result
    b={m['name']:m for m in baseline['metrics']};c={m['name']:m for m in candidate['metrics']}
    names=set(b)|set(c)
    if not names or set(b)!=set(c):
        result['status']='incomplete';result['exclusions']=['missing_required_metric:'+n for n in sorted(names) if n not in b or n not in c];return result
    better=worse=0
    for name in sorted(names):
        x,y=b[name],c[name]
        ux=UNITS.get(x['unit'],(x['unit'],1));uy=UNITS.get(y['unit'],(y['unit'],1))
        if ux[0]!=uy[0] or x['direction']!=y['direction']:
            result['exclusions'].append('metric_definition_mismatch:'+name);continue
        bx=x['value']*ux[1];cy=y['value']*uy[1]
        delta=cy-bx
        good=delta<0 if x['direction']=='min' else delta>0
        state='equivalent' if delta==0 else ('improved' if good else 'regressed')
        better+=state=='improved';worse+=state=='regressed'
        result['comparisons'].append({'name':name,'baseline':x['value'],'candidate':y['value'],'baseline_unit':x['unit'],'candidate_unit':y['unit'],'direction':x['direction'],'status':state})
    if result['exclusions']:result['status']='not_comparable';return result
    result['dominance']='tradeoff' if better and worse else ('candidate_dominates' if better else ('baseline_dominates' if worse else 'equivalent'))
    return result


def evaluate_required_rules(rules):
    """Evaluate the complete user-declared arithmetic rule set, independent of retrieval.

    These checks certify only supplied operands, not source authority or physics.
    Unrecognised natural-language, malformed and unbound rules remain unknown.
    """
    if not isinstance(rules,list) or len(rules)>200:raise ValueError('Required rules must be a bounded list')
    checks=[]
    for i,rule in enumerate(rules):
        item={'rule':rule,'id':str(rule.get('id',i)) if isinstance(rule,dict) else str(i),'status':'unknown'}
        if isinstance(rule,dict) and all(k in rule for k in ('value','operator','limit','unit')):
            value,bound=rule['value'],rule['limit']
            if all(not isinstance(v,bool) and isinstance(v,(int,float)) and math.isfinite(v) for v in (value,bound)) and isinstance(rule['unit'],str) and rule['unit']:
                operations={'<=':lambda:value<=bound,'>=':lambda:value>=bound,'==':lambda:value==bound}
                if isinstance(rule['operator'],str) and rule['operator'] in operations:item['status']='pass' if operations[rule['operator']]() else 'fail'
        checks.append(item)
    status='reject' if any(x['status']=='fail' for x in checks) else ('incomplete' if any(x['status']=='unknown' for x in checks) or not checks else 'validated_within_declared_scope')
    return {'policy_version':'declared-arithmetic-v1','status':status,'scope':'user_declared_operands_only','rules':checks,'physical_feasibility':'not_assessed'}
