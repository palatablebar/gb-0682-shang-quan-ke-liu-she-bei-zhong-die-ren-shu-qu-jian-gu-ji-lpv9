import io,csv,json,hashlib
from app import config,rulebook

# v1 签发时的计算字段与列序；重下已签发证据必须逐字节复现原指纹。
LEGACY_CALC_FIELDS=('id','line','lower','upper','width','triple_lower','triple_upper','code')
LEGACY_HEADER=['记录类型','批次','来源行','业务ID','原因码','内容']

def _versions(state):
    values=[r.get('rule_version') for r in state.get('calculations',[])]
    values+=[r.get('rule_version') for r in state.get('quarantine',[])]
    values+=[r.get('rule_version') for r in state.get('superseded',[])]
    values+=[state.get('rule_version')]
    if state.get('manifest'):values.append(state['manifest'].get('rule_version'))
    return [value for value in values if value is not None]

def _legacy(state):
    out=io.StringIO(newline='');writer=csv.writer(out)
    writer.writerow(LEGACY_HEADER)
    rid=state.get('run_id','preview')
    writer.writerow(['运行清单',rid,'','','',json.dumps(state.get('manifest',{}),ensure_ascii=False,sort_keys=True)])
    writer.writerow(['对账',rid,'','','',json.dumps(state.get('reconcile',{}),ensure_ascii=False,sort_keys=True)])
    for row in state.get('calculations',[]):
        legacy={k:row[k] for k in LEGACY_CALC_FIELDS if k in row}
        writer.writerow(['计算',rid,row.get('line',''),row.get('id',''),row.get('code',''),json.dumps(legacy,ensure_ascii=False,sort_keys=True)])
    for row in state.get('quarantine',[]):
        writer.writerow(['隔离',rid,row.get('line',''),row.get('id',''),row.get('code',''),json.dumps(row.get('raw',{}),ensure_ascii=False,sort_keys=True)])
    return '﻿'+out.getvalue()

def _versioned(state,version):
    out=io.StringIO(newline='');writer=csv.writer(out)
    writer.writerow(['记录类型','批次','规则版本','来源行','业务ID','原因码','内容'])
    rid=state.get('run_id','preview')
    writer.writerow(['运行清单',rid,version,'','','',json.dumps(state.get('manifest',{}),ensure_ascii=False,sort_keys=True)])
    writer.writerow(['对账',rid,version,'','','',json.dumps(state.get('reconcile',{}),ensure_ascii=False,sort_keys=True)])
    for row in state.get('calculations',[]):writer.writerow(['计算',rid,version,row.get('line',''),row.get('id',''),row.get('code',''),json.dumps(row,ensure_ascii=False,sort_keys=True)])
    for row in state.get('superseded',[]):writer.writerow(['版本替代',rid,version,row.get('line',''),row.get('id',''),row.get('reason',''),json.dumps(row,ensure_ascii=False,sort_keys=True)])
    for row in state.get('quarantine',[]):writer.writerow(['隔离',rid,version,row.get('line',''),row.get('id',''),row.get('code',''),json.dumps(row.get('raw',{}),ensure_ascii=False,sort_keys=True)])
    return '﻿'+out.getvalue()

def evidence_version(state):
    """证据归属版本：优先批次标注；完全未标注的封存件按未版本化（v1）解释。"""
    values=_versions(state)
    batch=state.get('rule_version')
    if not values:return batch or config.LEGACY_RULE_VERSION
    if batch:
        rulebook.uniform(values,batch,allow_missing=True)
    else:
        rulebook.uniform(values,values[0],allow_missing=True)
    return batch or values[0]

def bundle(state):
    # 旧版证据可能没有逐条版本标注，按批次版本解释；真正的跨版本仍会被拒绝。
    version=evidence_version(state)
    if rulebook.profile(version).evidence_layout=='legacy':return _legacy(state)
    return _versioned(state,version)

def checksum(state):
    return hashlib.sha256(bundle(state).encode('utf-8')).hexdigest()
