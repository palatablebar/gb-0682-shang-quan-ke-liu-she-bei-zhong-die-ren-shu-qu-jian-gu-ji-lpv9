"""已签发证据保真：并列重述不改写旧批次，重下导出逐字节一致。"""
import json, sqlite3
import pytest

from app import rulebook, store
from app.config import LEGACY_RULE_VERSION, RULE_VERSION
from app.modules.m7_archive.export_out import bundle, checksum
from app.workflow import load, run


def _signed_legacy_body():
    """模拟规则升级前签发的 v1 批次：无版本旁注、六列封存格式。"""
    state = run(load('dirty.csv'), {}, 7, LEGACY_RULE_VERSION)
    body = json.loads(json.dumps(state, ensure_ascii=False, default=str))
    # 与旧版签发格式一致：仅运行清单记录规则版本，逐条证据无版本列。
    body.pop('rule_version', None); body.pop('rule_profile', None); body.pop('source_key', None)
    body.pop('superseded', None)
    body['manifest'].pop('rule_profile', None); body['manifest'].pop('source_key', None)
    for row in body['calculations']: row.pop('rule_version', None)
    for row in body['quarantine']: row.pop('rule_version', None)
    body['business'].pop('rule_version', None); body['business'].pop('bounds', None)
    body['reconcile'].pop('rule_version', None)
    body['archive'].pop('rule_version', None)
    body['archive']['sha256'] = checksum(body)
    return body


def test_legacy_signed_bytes_reproduced(tmp_path, monkeypatch):
    body = _signed_legacy_body()
    original = bundle(body)
    monkeypatch.setenv('DB_PATH', str(tmp_path / 'r.db'))
    store.save(body['run_id'], body)
    reread = store.get(body['run_id'])
    assert bundle(reread) == original
    assert checksum(reread) == checksum(body) == body['archive']['sha256']


def test_new_rule_does_not_touch_stored_legacy(tmp_path, monkeypatch):
    body = _signed_legacy_body()
    monkeypatch.setenv('DB_PATH', str(tmp_path / 'r.db'))
    store.save(body['run_id'], body)
    before = store.get(body['run_id'])
    raw = load('dirty.csv')
    newer = run(raw, {}, 7, RULE_VERSION)
    store.save(newer['run_id'], newer)
    after = store.get(body['run_id'])
    assert after == before
    assert after['rule_version'] == LEGACY_RULE_VERSION
    assert bundle(after) == bundle(before)


def test_legacy_export_has_no_version_column():
    body = _signed_legacy_body()
    first = bundle(body).splitlines()[0]
    assert first.lstrip('﻿').split(',')[0:2] == ['记录类型', '批次']
    assert '规则版本' not in first


def test_store_save_never_overwrites_signed_batch(tmp_path, monkeypatch):
    monkeypatch.setenv('DB_PATH', str(tmp_path / 'r.db'))
    state = run(load('clean.csv'), {}, 7, RULE_VERSION)
    store.save(state['run_id'], state)
    store.review(state['run_id'], 1, '通过')
    signed = store.get(state['run_id'])
    # 同键重跑（例如重算）不得把复核结论或正文打回
    store.save(state['run_id'], dict(state, business={'total': 0, 'upper_total': 0}))
    again = store.get(state['run_id'])
    assert again['review_version'] == signed['review_version']
    assert again['business'] == signed['business']
