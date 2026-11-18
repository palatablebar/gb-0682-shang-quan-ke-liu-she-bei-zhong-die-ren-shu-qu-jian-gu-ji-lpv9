from collections import defaultdict
from decimal import Decimal
from datetime import datetime
from app import rulebook
ALIASES={'东门':'A','中庭':'B','西门':'C','A':'A','B':'B','C':'C'}

KIND_ORDER={'zone':0,'pair':1,'triple':2}

def _observation(row):
    return {'id':row['id'],'version':str(row['version']),'bucket':row['bucket'],'kind':row['kind'],
        'left':row['left'],'right':row['right'],'count':row['count'],'unit':row['unit'],
        'line':row['_line'],'_line':row['_line'],'_raw':row.get('_raw',{}),'rule_version':row['rule_version']}

def apply(state):
    profile=rulebook.profile(state.get('rule_version'))
    groups=defaultdict(list);bad=[]
    for r in state['rows']:
        r['bucket']=datetime.fromisoformat(r['bucket']).replace(minute=0,second=0,microsecond=0).isoformat()
        r['left']=ALIASES.get(r['left'],r['left']);r['right']=ALIASES.get(r['right'],r['right'])
        value=Decimal(str(r['count']))
        factor={'人':Decimal(1),'千人':Decimal(1000)}.get(r['unit'])
        if factor is None:bad.append((r,'UNIT'));continue
        value*=factor
        if value<0 or value!=value.to_integral_value() or value>1000000 or r['kind'] not in ('zone','pair','triple'):
            bad.append((r,'RANGE'));continue
        r['count']=int(value)
        if r['kind']=='pair':r['left'],r['right']=sorted([r['left'],r['right']])
        key=(r['bucket'],r['kind'],r['left'],r['right']);groups[key].append(r)
    selected=[];superseded=[]
    for key,rows in groups.items():
        high=max(Decimal(str(r['version'])) for r in rows)
        latest=[r for r in rows if Decimal(str(r['version']))==high]
        earlier=[r for r in rows if Decimal(str(r['version']))!=high]
        if len({r['count'] for r in latest})>1:
            bad.extend((r,'CONFLICT') for r in latest)
        else:
            chosen=sorted(latest,key=lambda r:r['id'])[0]
            selected.append(_observation(chosen))
        if profile.supersede_policy=='record':
            reason='更高版本观测被采纳' if not (len({r['count'] for r in latest})>1) else '更高版本观测冲突隔离，原值留档'
            for r in earlier:superseded.append({**_observation(r),'superseded_by':high.__str__(),
                'reason':reason,'rule_version':profile.version})
    badlines={r['_line'] for r,_ in bad}
    state['rows']=[r for r in state['rows'] if r['_line'] not in badlines]
    for r,c in bad:state['quarantine'].append({'line':r['_line'],'id':r['id'],'code':c,'raw':r['_raw'],'rule_version':profile.version})
    state['observations']=selection_sort(selected)
    state.setdefault('superseded',[]).extend(sorted(superseded,key=lambda r:(r['bucket'],KIND_ORDER.get(r['kind'],9),r['left'],r['right'],Decimal(str(r['version'])))))
    return state

def selection_sort(rows):
    return sorted(rows,key=lambda r:(r['bucket'],KIND_ORDER.get(r['kind'],9),r['left'],r['right']))
