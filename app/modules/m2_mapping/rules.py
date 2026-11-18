from copy import deepcopy
from app import rulebook
from app.config import REQUIRED,NUMERIC,DATES,TIMES,BUSINESS_FIELDS
from app.errors import DomainError
from app.modules.m2_mapping.coerce import number,day,instant,SENTINELS

def _identity_key(item, profile):
    if profile.dedupe_fields == 'business':
        fields = [f for f in BUSINESS_FIELDS if f not in profile.ignore_fields]
    else:
        fields = sorted(k for k in item if not k.startswith('_'))
    return str(sorted((k,str(item.get(k,''))) for k in fields))

def normalize(state):
    state=deepcopy(state)
    profile=rulebook.profile(state.get('rule_version'))
    good=[];groups={}
    for row in state['rows']:
        try:
            for field in REQUIRED:
                if str(row.get(field,'')).strip().upper() in SENTINELS:raise DomainError('MISSING','必填值缺失')
            item=dict(row)
            for field in NUMERIC:
                if field in item and item[field] != '':item[field]=number(item[field])
            for field in DATES:
                if field in item and item[field] != '':item[field]=day(item[field])
            for field in TIMES:
                if field in item and item[field] != '':item[field]=instant(item[field])
            key=(item['id'],str(item.get('version','1')))
            groups.setdefault(key,[]).append(item)
        except DomainError as error:
            state['quarantine'].append({'line':row['_line'],'id':row.get('id',''),'code':error.code,'raw':row['_raw'],'rule_version':profile.version})
    for key,rows in groups.items():
        unique={_identity_key(r,profile) for r in rows}
        if len(unique)>1:
            for r in rows:state['quarantine'].append({'line':r['_line'],'id':r['id'],'code':'CONFLICT','raw':r['_raw'],'rule_version':profile.version})
        else:
            chosen=dict(rows[0]);chosen['rule_version']=profile.version
            good.append(chosen);state['duplicate_count']+=len(rows)-1
    state['rows']=good
    return state
