import sqlite3,json,os,base64
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path
from app import config, rulebook
from app.errors import DomainError
from app.manifest import source_key as derive_source_key

_NEW_COLUMNS=(('rule_version','TEXT'),('source_key','TEXT'))

def _path():
    path=Path(os.environ.get('DB_PATH','data/records.db'));path.parent.mkdir(parents=True,exist_ok=True);return path

def _connect():
    db=sqlite3.connect(_path(),timeout=10);db.row_factory=sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL');return db

def _columns(db):
    return {r['name'] for r in db.execute('PRAGMA table_info(runs)')}

def _base_tables(db):
    """新库直接带版本列；旧库由 migrate() 以加法方式补齐。"""
    db.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, body TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, decision TEXT NOT NULL DEFAULT "待复核", rule_version TEXT, source_key TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL, detail TEXT)')

def _body_meta(body):
    """从旧批次正文恢复规则版本与同源键；只读推导，不改正文。"""
    rule_version=body.get('rule_version') or body.get('manifest',{}).get('rule_version') or config.LEGACY_RULE_VERSION
    key=body.get('manifest',{}).get('source_key')
    if not key:
        try:
            raw=base64.b64decode(body.get('source_b64') or '')
            if not raw:raise ValueError('无原始字节')
            params=body.get('manifest',{}).get('parameters') or body.get('parameters') or {}
            key=derive_source_key(raw,params)
        except Exception:
            # 无法从字节推导时给出确定性占位键：仍能识别“同源”，但不会误判为可重算。
            key='unavailable:'+str(body.get('manifest',{}).get('sha256') or body.get('run_id') or '')
    return rule_version,key

def _set_meta(db,key,value):
    db.execute("INSERT INTO meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(key,value))

def _get_meta(db,key):
    row=db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone();return row['value'] if row else None

def migrate():
    """加法式迁移：只补旁列与索引，不重写批次正文。

    - 迁移前把 runs 复制到 runs_backup_v2（独立事务，失败仍在）。
    - 回填逐行用 COALESCE，已有版本信息不覆盖。
    - 任何一步失败整体回滚，保留旧表结构与旧证据，并留下失败记录。
    - 成功判据：列已补齐、行数不变、标记写入。
    """
    db=_connect()
    try:
        _base_tables(db)
        if db.execute("SELECT 1 FROM migrations WHERE name='runs-rule-version'").fetchone():
            _set_meta(db,'schema_state','ready');db.commit()
            return {'state':'ready','migrated':False}
        if {'rule_version','source_key'}<=_columns(db):
            db.execute("INSERT OR IGNORE INTO migrations(name,applied_at,detail) VALUES ('runs-rule-version',?,?)",
                (datetime.now(timezone.utc).isoformat(),'columns present'))
            _set_meta(db,'schema_state','ready');db.commit()
            return {'state':'ready','migrated':False}
        try:
            db.execute('CREATE TABLE IF NOT EXISTS runs_backup_v2 AS SELECT * FROM runs')
            db.commit()
        except Exception as error:
            db.rollback();_set_meta(db,'schema_state','legacy')
            db.execute("INSERT OR IGNORE INTO migrations(name,applied_at,detail) VALUES ('runs-rule-version-failed',?,?)",(datetime.now(timezone.utc).isoformat(),'备份失败：%s' % error))
            db.commit()
            return {'state':'legacy','migrated':False,'error':str(error)}
        before=db.execute('SELECT COUNT(*) AS n FROM runs').fetchone()['n']
        try:
            db.execute('BEGIN IMMEDIATE')
            for name,kind in _NEW_COLUMNS:
                if name not in _columns(db):db.execute('ALTER TABLE runs ADD COLUMN %s %s' % (name,kind))
            for row in db.execute('SELECT id,body FROM runs').fetchall():
                version,key=_body_meta(json.loads(row['body']))
                # 只回填旁列，正文原样保留：已签发证据不因迁移而改写。
                db.execute('UPDATE runs SET rule_version=COALESCE(rule_version,?),source_key=COALESCE(source_key,?) WHERE id=?',(version,key,row['id']))
            after=db.execute('SELECT COUNT(*) AS n FROM runs').fetchone()['n']
            if after!=before:raise RuntimeError('迁移前后行数不一致')
            missing=db.execute('SELECT COUNT(*) AS n FROM runs WHERE rule_version IS NULL').fetchone()['n']
            if missing:raise RuntimeError('%d 条批次缺少规则版本' % missing)
            db.execute("INSERT OR IGNORE INTO migrations(name,applied_at,detail) VALUES ('runs-rule-version',?,?)",
                (datetime.now(timezone.utc).isoformat(),'migrated %d rows' % after))
            db.execute("CREATE INDEX IF NOT EXISTS runs_source ON runs(source_key)")
            _set_meta(db,'schema_state','ready')
            db.commit()
        except Exception as error:
            db.rollback()
            db.execute("INSERT OR IGNORE INTO migrations(name,applied_at,detail) VALUES ('runs-rule-version-failed',?,?)",(datetime.now(timezone.utc).isoformat(),str(error)))
            _set_meta(db,'schema_state','legacy')
            db.commit()
            return {'state':'legacy','migrated':False,'error':str(error)}
        return {'state':'ready','migrated':True,'rows':after}
    finally:
        db.close()

@contextmanager
def connection():
    db=_connect();_base_tables(db)
    try:yield db;db.commit()
    except Exception:db.rollback();raise
    finally:db.close()

def schema_state():
    db=_connect()
    try:
        _base_tables(db);return _get_meta(db,'schema_state') or 'ready'
    finally:
        db.close()

def _versioned(db):
    return {'rule_version','source_key'}<=_columns(db)

def _row_version(r):
    try:
        body=json.loads(r['body'])
    except Exception:
        body={}
    explicit=body.get('rule_version') or (body.get('manifest') or {}).get('rule_version')
    if explicit:return explicit
    if 'rule_version' in r.keys() and r['rule_version']:return r['rule_version']
    return _body_meta(body)[0]

def _row_source(r):
    if 'source_key' in r.keys() and r['source_key']:
        return r['source_key']
    try:return _body_meta(json.loads(r['body']))[1]
    except Exception:return None

def save(run_id, body):
    # 正文自带版本时以其为准；完全未标注的历史封存件按 v1 解释，绝不冒充当前版本。
    explicit=body.get('rule_version') or (body.get('manifest') or {}).get('rule_version')
    version=rulebook.resolve(explicit) if explicit else _body_meta(body)[0]
    key=(body.get('manifest') or {}).get('source_key')
    with connection() as db:
        if _versioned(db):
            db.execute('INSERT OR IGNORE INTO runs(id,body,version,decision,rule_version,source_key) VALUES (?,?,1,"待复核",?,?)',(run_id,json.dumps(body,ensure_ascii=False),version,key))
        else:
            # 迁移失败时仍可记录新批次：版本信息保存在正文中，旧结构不扩列。
            db.execute('INSERT OR IGNORE INTO runs(id,body) VALUES (?,?)',(run_id,json.dumps(body,ensure_ascii=False)))
        # 已存在的同键批次不被覆盖：只移动 latest 指针，保证已签发证据原貌。
        _set_meta(db,'latest',run_id)
    return get(run_id)

def _stamp_missing(body, version):
    """只给旧版证据中“未标注”的条目补上批次版本；已标注的其他版本保持原样。"""
    for key in ('observations','calculations','superseded','quarantine'):
        for entry in body.get(key) or []:
            if isinstance(entry,dict) and not entry.get('rule_version'):
                entry['rule_version']=version
    return body

def get(run_id):
    with connection() as db:r=db.execute('SELECT * FROM runs WHERE id=?',(run_id,)).fetchone()
    if not r:raise DomainError('NOT_FOUND','批次不存在',404)
    body=json.loads(r['body'])
    body.update(run_id=r['id'],review_version=r['version'],decision=r['decision'])
    body['rule_version']=body.get('rule_version') or _row_version(r)
    # 不动 manifest 内的任何字段：封存证据必须按原样字节重现。
    body.setdefault('manifest',{})
    body.setdefault('rule_profile',rulebook.profile(body['rule_version']).as_dict())
    body['source_key']=body.get('source_key') or _row_source(r)
    return _stamp_missing(body,body['rule_version'])

def _summaries(rows):
    return [{'id':r['id'],'version':r['version'],'decision':r['decision'],
        'rule_version':_row_version(r),'source_key':_row_source(r)} for r in rows]

def _select(db,columns,tail,params=()):
    # 迁移失败的旧库没有版本旁列；此时仍可读取，版本从正文恢复。
    extra=',rule_version,source_key' if _versioned(db) else ',NULL AS rule_version,NULL AS source_key'
    return db.execute('SELECT '+columns+extra+' FROM runs '+tail,params).fetchall()

def history(limit=100):
    with connection() as db:
        rows=_select(db,'id,version,decision,body',
            "ORDER BY CASE WHEN id=(SELECT value FROM meta WHERE key='latest') THEN 0 ELSE 1 END,rowid DESC LIMIT ?",(int(limit),))
    return _summaries(rows)

def parallel(source_key, limit=100):
    """同一来源在各规则版本下的并列批次；并列展示，不合并、不覆盖。"""
    if not source_key:return []
    with connection() as db:
        if _versioned(db):
            rows=db.execute('SELECT id,version,decision,body,rule_version,source_key FROM runs WHERE source_key=? ORDER BY rule_version,rowid LIMIT ?',(source_key,limit)).fetchall()
        else:
            rows=[r for r in _select(db,'id,version,decision,body','ORDER BY rowid') if _row_source(r)==source_key][:limit]
    return _summaries(rows)

def restated_source(run_id):
    state=get(run_id)
    return {'source_key':state.get('source_key'),'rule_version':state['rule_version'],
        'parameters':(state.get('manifest') or {}).get('parameters',{}),
        'parallel':parallel(state.get('source_key')) if state.get('source_key') else []}

def combined(run_ids):
    """跨批次日汇总入口：版本不一致直接拒绝，绝不拼成一个日汇总。

    同一批次重复提交只计一次，避免重复累加虚增人数。
    """
    if not isinstance(run_ids,list) or not run_ids:raise DomainError('RULE_MIX','需要至少一个批次')
    unique=[]
    for run_id in run_ids:
        if run_id not in unique:unique.append(run_id)
    states=[get(run_id) for run_id in unique]
    versions=[s.get('rule_version') for s in states]
    # 以首个批次的版本为基准：跨版本仍拒绝，但旧版本批次之间可以同版汇总。
    version=rulebook.uniform(versions,versions[0])
    return {'rule_version':version,'batches':len(states),
        'buckets':sum(len(s.get('calculations',[])) for s in states),
        'lower':sum((s.get('business') or {}).get('total',0) for s in states),
        'upper':sum((s.get('business') or {}).get('upper_total',0) for s in states)}

def review(run_id, version, decision):
    if decision not in ('通过','退回'):raise DomainError('DECISION','复核状态无效')
    with connection() as db:
        cur=db.execute('UPDATE runs SET version=version+1,decision=? WHERE id=? AND version=?',(decision,run_id,version))
        if cur.rowcount!=1:
            if not db.execute('SELECT 1 FROM runs WHERE id=?',(run_id,)).fetchone():raise DomainError('NOT_FOUND','批次不存在',404)
            raise DomainError('STALE','复核版本已更新，请刷新',409)
    return get(run_id)
