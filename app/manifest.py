import hashlib,json
from datetime import datetime,timezone
from app import rulebook

def source_key(content, parameters):
    """同源键：输入字节 + 参数，不含规则版本。用于关联并列重述批次。"""
    raw = content + json.dumps(parameters,sort_keys=True,ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()[:20]

def identity(content, parameters, rule_version=None):
    # 幂等键保持原公式，并显式包含规则版本：同源同规则重跑得到同一批次。
    version = rulebook.resolve(rule_version)
    raw = content + json.dumps(parameters,sort_keys=True,ensure_ascii=False).encode() + version.encode()
    return hashlib.sha256(raw).hexdigest()[:20]

def manifest(content, parameters, elapsed, rule_version=None):
    version = rulebook.resolve(rule_version)
    return {'sha256':hashlib.sha256(content).hexdigest(),'rule_version':version,
        'rule_profile':rulebook.profile(version).label,
        'source_key':source_key(content,parameters),
        'parameters':parameters,'elapsed_ms':round(elapsed*1000),
        'generated_at':datetime.now(timezone.utc).isoformat(),'timezone':'Asia/Shanghai'}
