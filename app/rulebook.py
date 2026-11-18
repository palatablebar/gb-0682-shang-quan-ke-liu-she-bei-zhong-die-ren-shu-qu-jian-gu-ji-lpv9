"""规则版本登记表。

规则版本必须同时贯穿采信、观测取舍、人数估界与归档证据。
历史版本只读：需要按新规则重算时，创建并列的新批次，不修改旧批次正文。
"""
from dataclasses import dataclass, asdict

from app import config
from app.errors import DomainError


@dataclass(frozen=True)
class Profile:
    version: str
    label: str
    status: str
    # all: 整行比较；business: 仅业务字段比较（备注差异不算同版冲突）
    dedupe_fields: str
    ignore_fields: tuple
    # retain: 低版本记录留在采纳行；record: 低版本记录进入 superseded 台账
    supersede_policy: str
    # drop: 同版矛盾的最高版本观测整组不采信（两个版本一致的核心安全规则）
    conflict_policy: str
    bounds_label: str
    # legacy: 沿用签发当时的六列封存格式；versioned: 增加规则版本列与替代台账
    evidence_layout: str

    def as_dict(self):
        data = asdict(self)
        data['ignore_fields'] = list(self.ignore_fields)
        return data


PROFILES = {
    '2026.11.17-v1': Profile(
        version='2026.11.17-v1',
        label='基线采信',
        status='legacy',
        dedupe_fields='all',
        ignore_fields=(),
        supersede_policy='retain',
        conflict_policy='drop',
        bounds_label='两两交集界',
        evidence_layout='legacy',
    ),
    '2026.11.18-v2': Profile(
        version='2026.11.18-v2',
        label='业务字段采信（并列重述）',
        status='current',
        dedupe_fields='business',
        ignore_fields=('note',),
        supersede_policy='record',
        conflict_policy='drop',
        bounds_label='两两交集界（并列重述）',
        evidence_layout='versioned',
    ),
}

_FALLBACK = dict(
    label='自定义规则版本',
    status='custom',
    dedupe_fields='business',
    ignore_fields=('note',),
    supersede_policy='record',
    conflict_policy='drop',
    bounds_label='两两交集界',
    evidence_layout='versioned',
)


def known_versions():
    values = list(config.RULE_VERSION_HISTORY) + list(PROFILES) + [config.RULE_VERSION]
    out = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return tuple(out)


def resolve(value=None):
    version = value if value is not None else config.RULE_VERSION
    if not isinstance(version, str) or not version.strip():
        raise DomainError('RULE_VERSION', '规则版本不能为空')
    version = version.strip()
    if version not in known_versions():
        raise DomainError('RULE_VERSION', '规则版本未登记：%s' % version)
    return version


def profile(value=None):
    version = resolve(value)
    result = PROFILES.get(version)
    if result is not None:
        return result
    # 允许通过 config.RULE_VERSION 注入的测试/部署版本使用当前语义。
    return Profile(version=version, **dict(_FALLBACK))


def catalogue():
    return {
        'current': config.RULE_VERSION,
        'legacy': config.LEGACY_RULE_VERSION,
        'versions': [profile(item).as_dict() for item in known_versions()],
        'policy': 'parallel-restatement',
        'policy_label': '历史数据并列重述；已签发证据只读，不整批迁移改写',
    }


def uniform(values, expected=None, allow_missing=False):
    """拒绝把不同规则版本的观测/估界结果拼在一起。

    allow_missing 仅用于底层纯函数：调用方未标注版本时按期望版本解释；
    汇总与归档路径必须显式携带版本，缺失即拒绝。
    """
    expected = resolve(expected) if expected is not None else config.RULE_VERSION
    seen = []
    for value in values:
        if value is None or value == '':
            if allow_missing:
                continue
            raise DomainError('RULE_MIX', '缺少规则版本，不能合并或汇总')
        if value not in seen:
            seen.append(value)
    if len(seen) > 1:
        raise DomainError('RULE_MIX', '跨规则版本数据不能合并：%s' % '、'.join(seen))
    if seen and seen[0] != expected:
        raise DomainError('RULE_MIX', '规则版本与批次不一致：%s ≠ %s' % (seen[0], expected))
    return expected
