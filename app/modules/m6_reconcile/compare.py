from app import rulebook
from app.errors import DomainError

def _versions(state, expected):
    business=state.get('business') or {}
    sources=[('观测',[r.get('rule_version') for r in state.get('observations',[])]),
        ('约束',[r.get('rule_version') for r in state.get('models',[])]),
        ('估界',[r.get('rule_version') for r in state.get('calculations',[])]),
        ('业务汇总',[business.get('rule_version')] if business else [])]
    seen=[]
    for label,values in sources:
        for value in values:
            if value is None:raise DomainError('RULE_MIX','%s缺少规则版本，不能形成日汇总' % label)
            if value not in seen:seen.append(value)
    rulebook.uniform(seen,expected,allow_missing=True)
    return expected

def balance(state, rule_version=None):
    expected=rulebook.resolve(rule_version if rule_version is not None else state.get('rule_version'))
    _versions(state,expected)
    accepted=len(state['rows']);isolated=len(state['quarantine'])
    accounted=accepted+isolated+state['blank_count']+state['header_count']+state['duplicate_count']
    return {'input':state['input_count'],'accepted':accepted,'isolated':isolated,
        'blank':state['blank_count'],'headers':state['header_count'],'duplicates':state['duplicate_count'],
        'accounted':accounted,'balanced':accounted==state['input_count'],
        'rule_version':expected,'business':state.get('business',{})}
