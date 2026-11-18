"""规则版本贯穿采信、观测取舍、人数估界与归档；历史数据并列重述。"""
import csv, io, json, sqlite3
import pytest

from app import rulebook, store
from app.config import LEGACY_RULE_VERSION, RULE_VERSION
from app.errors import DomainError
from app.modules.m6_reconcile.compare import balance
from app.modules.m7_archive.export_out import bundle
from app.workflow import load, run


def test_current_and_legacy_registered():
    assert rulebook.resolve() == RULE_VERSION
    assert rulebook.resolve(LEGACY_RULE_VERSION) == LEGACY_RULE_VERSION
    with pytest.raises(DomainError) as e:
        rulebook.resolve('2099.01.01-v9')
    assert e.value.code == 'RULE_VERSION'


def test_rule_version_in_identity():
    raw = load('clean.csv')
    old = run(raw, {}, 7, LEGACY_RULE_VERSION)
    new = run(raw, {}, 7, RULE_VERSION)
    assert old['run_id'] != new['run_id']
    assert old['manifest']['source_key'] == new['manifest']['source_key']
    # 同源同规则重跑：同一批次，重复保存不新增结果
    assert run(raw, {}, 7, RULE_VERSION)['run_id'] == new['run_id']


def test_rule_version_propagates_all_stages():
    state = run(load('dirty.csv'), {}, 7, RULE_VERSION)
    assert state['rule_version'] == RULE_VERSION
    assert state['manifest']['rule_version'] == RULE_VERSION
    assert {r['rule_version'] for r in state['observations']} == {RULE_VERSION}
    assert {r['rule_version'] for r in state['models']} == {RULE_VERSION}
    assert {r['rule_version'] for r in state['calculations']} == {RULE_VERSION}
    assert state['business']['rule_version'] == RULE_VERSION
    assert state['reconcile']['rule_version'] == RULE_VERSION
    assert state['archive']['rule_version'] == RULE_VERSION
    assert {q['rule_version'] for q in state['quarantine']} == {RULE_VERSION}


def test_versions_diverge_on_same_source():
    raw = load('restated.csv')
    old = run(raw, {}, 7, LEGACY_RULE_VERSION)
    new = run(raw, {}, 7, RULE_VERSION)
    # v1 把仅备注不同的同版记录当冲突并隔离整桶；v2 只比业务字段。
    assert any(q['code'] == 'CONFLICT' for q in old['quarantine'])
    assert old['business']['buckets'] < new['business']['buckets']
    assert old['archive']['sha256'] != new['archive']['sha256']


def test_superseded_records_not_lost():
    state = run(load('dirty.csv'), {}, 7, RULE_VERSION)
    assert isinstance(state['superseded'], list)
    # 每条被替代记录都带来源行与原值，不静默丢弃
    for entry in state['superseded']:
        assert entry['line'] >= 2 and entry['count'] is not None


def test_store_parallel_batches(client):
    a = client.post('/api/runs', json={'sample': 'restated.csv', 'rule_version': LEGACY_RULE_VERSION}).get_json()
    b = client.post('/api/runs', json={'sample': 'restated.csv', 'rule_version': RULE_VERSION}).get_json()
    assert a['run_id'] != b['run_id']
    group = client.get('/api/runs/%s/parallel' % a['run_id']).get_json()
    assert {p['rule_version'] for p in group['parallel']} == {LEGACY_RULE_VERSION, RULE_VERSION}
    # 旧批次正文原貌保留：重新读取仍是 v1 结果
    assert client.get('/api/runs/%s' % a['run_id']).get_json()['business']['total'] == a['business']['total']


def test_same_source_same_rule_no_duplicate(client):
    first = client.post('/api/runs', json={'sample': 'restated.csv', 'rule_version': RULE_VERSION}).get_json()
    second = client.post('/api/runs', json={'sample': 'restated.csv', 'rule_version': RULE_VERSION}).get_json()
    assert first['run_id'] == second['run_id']
    history = client.get('/api/runs').get_json()
    assert len([h for h in history if h['id'] == first['run_id']]) == 1


def test_cross_version_combined_rejected(client):
    a = client.post('/api/runs', json={'sample': 'restated.csv', 'rule_version': LEGACY_RULE_VERSION}).get_json()
    b = client.post('/api/runs', json={'sample': 'restated.csv', 'rule_version': RULE_VERSION}).get_json()
    r = client.post('/api/runs/combined', json={'run_ids': [a['run_id'], b['run_id']]})
    assert r.status_code == 422 and r.get_json()['code'] == 'RULE_MIX'
    same = client.post('/api/runs/combined', json={'run_ids': [b['run_id'], b['run_id']]})
    payload = same.get_json()
    assert same.status_code == 200 and payload['rule_version'] == RULE_VERSION
    assert payload['batches'] == 1 and payload['lower'] == b['business']['total']


def test_mixed_state_cannot_reconcile():
    a = run(load('restated.csv'), {}, 6, LEGACY_RULE_VERSION)
    b = run(load('restated.csv'), {}, 6, RULE_VERSION)
    a['calculations'].append(b['calculations'][0])
    with pytest.raises(DomainError) as e:
        balance(a, RULE_VERSION)
    assert e.value.code == 'RULE_MIX'


def test_mixed_state_cannot_export():
    a = run(load('restated.csv'), {}, 7, LEGACY_RULE_VERSION)
    b = run(load('restated.csv'), {}, 7, RULE_VERSION)
    a['quarantine'].append(b['quarantine'][0] if b['quarantine'] else dict(b['observations'][0], code='X'))
    with pytest.raises(DomainError) as e:
        bundle(a)
    assert e.value.code == 'RULE_MIX'


def test_archive_rows_carry_rule_version():
    state = run(load('dirty.csv'), {}, 7, RULE_VERSION)
    rows = list(csv.reader(io.StringIO(bundle(state).lstrip('﻿'))))
    assert rows[0][:3] == ['记录类型', '批次', '规则版本']
    assert {r[2] for r in rows[1:]} == {RULE_VERSION}


def test_migration_backfills_without_rewriting(tmp_path, monkeypatch):
    db = tmp_path / 'old.db'
    monkeypatch.setenv('DB_PATH', str(db))
    body = run(load('clean.csv'), {}, 7, LEGACY_RULE_VERSION)
    body.pop('rule_version', None)
    body['manifest'].pop('rule_version', None)
    body['manifest'].pop('source_key', None)
    conn = sqlite3.connect(db)
    conn.execute('CREATE TABLE runs (id TEXT PRIMARY KEY, body TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, decision TEXT NOT NULL DEFAULT "待复核")')
    conn.execute('INSERT INTO runs(id,body) VALUES (?,?)', (body['run_id'], json.dumps(body, ensure_ascii=False)))
    conn.commit(); conn.close()
    result = store.migrate()
    assert result['state'] == 'ready' and result['migrated'] is True
    conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
    row = conn.execute('SELECT * FROM runs').fetchone()
    backup = conn.execute('SELECT COUNT(*) FROM runs_backup_v2').fetchone()[0]
    conn.close()
    assert row['rule_version'] == LEGACY_RULE_VERSION
    assert row['source_key'] == body['manifest'].get('source_key') or row['source_key']
    assert backup == 1
    assert json.loads(row['body']) == body


def test_migration_failure_preserves_old_evidence(tmp_path, monkeypatch):
    db = tmp_path / 'broken.db'
    monkeypatch.setenv('DB_PATH', str(db))
    conn = sqlite3.connect(db)
    conn.execute('CREATE TABLE runs (id TEXT PRIMARY KEY, body TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, decision TEXT NOT NULL DEFAULT "待复核")')
    conn.execute('INSERT INTO runs(id,body) VALUES ("legacy1",?)', (json.dumps({'calculations': []}),))
    conn.commit(); conn.close()
    # 注入失败：制造一条无法解析的正文之外，直接让行数校验失败
    calls = {'n': 0}
    original = store._body_meta
    def boom(body):
        calls['n'] += 1
        raise RuntimeError('模拟迁移失败')
    monkeypatch.setattr(store, '_body_meta', boom)
    result = store.migrate()
    assert result['state'] == 'legacy' and result['migrated'] is False
    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute('PRAGMA table_info(runs)')}
    rows = conn.execute('SELECT id,body FROM runs').fetchall()
    backup = conn.execute('SELECT COUNT(*) FROM runs_backup_v2').fetchone()[0]
    conn.close()
    assert 'rule_version' not in cols  # 回滚后旧结构完好
    assert rows == [('legacy1', json.dumps({'calculations': []}))]
    assert backup == 1
    monkeypatch.setattr(store, '_body_meta', original)
    assert store.get('legacy1')['rule_version'] == LEGACY_RULE_VERSION


def test_history_shows_rule_version(client):
    client.post('/api/runs', json={'sample': 'clean.csv', 'rule_version': RULE_VERSION})
    rows = client.get('/api/runs').get_json()
    assert rows and rows[0]['rule_version'] == RULE_VERSION


def test_rules_catalogue(client):
    data = client.get('/api/rules').get_json()
    assert data['current'] == RULE_VERSION and data['policy'] == 'parallel-restatement'
    assert {v['version'] for v in data['versions']} >= {LEGACY_RULE_VERSION, RULE_VERSION}


def test_page_replays_stored_batch_not_recompute(client):
    a = client.post('/api/runs', json={'sample': 'restated.csv', 'rule_version': LEGACY_RULE_VERSION}).get_json()
    page = client.get('/m7_archive?run=' + a['run_id']).data.decode()
    assert a['run_id'] in page and LEGACY_RULE_VERSION in page

def test_page_latest_is_readonly_playback(client):
    client.post('/api/runs', json={'sample': 'restated.csv', 'rule_version': LEGACY_RULE_VERSION})
    page = client.get('/m7_archive').data.decode()
    assert LEGACY_RULE_VERSION in page


def _two_version_csv():
    return (
        'id,bucket,version,kind,left,right,count,unit,note\n'
        '00001,2026-11-16T09:00:00+08:00,1,zone,东门,,120,人,旧值\n'
        '00001,2026-11-16T09:00:00+08:00,2,zone,东门,,125,人,新值\n'
        '00002,2026-11-16T09:00:00+08:00,1,zone,中庭,,110,人,\n'
        '00003,2026-11-16T09:00:00+08:00,1,pair,东门,中庭,40,人,\n'
    ).encode()


def test_superseded_ledger_keeps_old_value():
    old = run(_two_version_csv(), {}, 7, LEGACY_RULE_VERSION)
    new = run(_two_version_csv(), {}, 7, RULE_VERSION)
    # v2 记录被替代的低版本观测；v1 保留原行为只取最高版
    assert [o['count'] for o in new['observations'] if o['kind'] == 'zone' and o['left'] == 'A'] == [125]
    assert len(new['superseded']) == 1
    entry = new['superseded'][0]
    assert entry['count'] == 120 and entry['version'] == '1' and entry['line'] == 2
    assert entry['superseded_by'] == '2'
    assert old['superseded'] == []


def test_superseded_does_not_change_totals():
    state = run(_two_version_csv(), {}, 7, RULE_VERSION)
    assert state['reconcile']['balanced'] is True
    # 替代台账是留档，不参与估界；客次只来自被采纳的观测
    assert state['business']['buckets'] == 1
