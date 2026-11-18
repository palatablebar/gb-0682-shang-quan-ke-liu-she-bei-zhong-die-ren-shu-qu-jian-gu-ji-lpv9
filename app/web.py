import base64
from flask import request,render_template,jsonify
from app.errors import DomainError
from app.config import TITLE,MODULES,SHORT
from app import rulebook,store
from app.workflow import run,load

def payload():
    data=request.get_json(silent=True) or {}
    if not isinstance(data,dict):raise DomainError('PAYLOAD','请求必须是对象')
    if 'csv' in data and not isinstance(data['csv'],str):raise DomainError('CSV','CSV内容必须是文本')
    sample=data.get('sample',request.args.get('sample','dirty.csv'))
    content=data.get('csv')
    version=rulebook.resolve(data.get('rule_version',request.args.get('rule_version')))
    return (content.encode() if isinstance(content,str) else load(sample)),data.get('parameters',{}),version

def source_of(state):
    """返回已存批次的原样字节；缺失时不猜测、不重编码。"""
    raw=state.get('source_b64')
    if not raw:raise DomainError('SOURCE','该批次未保存原始观测，无法重算')
    return base64.b64decode(raw)

def replay(stage,state=None):
    """按批次自己的规则版本、用原样字节做同源同规则重跑。

    旧封存件若未保存原始字节，退回只读回放，绝不猜测或重编码来源。
    """
    state=state or current()
    if state is None:return run(load('dirty.csv'),{},stage)
    params=(state.get('manifest') or {}).get('parameters') or {}
    if not state.get('source_b64'):return state
    return run(source_of(state),params,stage,state['rule_version'])

def current():
    latest=store.history()
    if not latest:return None
    run_id=request.args.get('run') or latest[0]['id']
    return store.get(run_id)

def api(stage):
    explicit=bool(request.args.get('sample') or request.args.get('csv'))
    if request.method=='GET' and not explicit:
        # 归档接口回放已签发正文；其余阶段按批次规则版本重跑。
        if stage>=7:return jsonify(current() or run(load('dirty.csv'),{},stage))
        return jsonify(replay(stage))
    content,parameters,version=payload()
    return jsonify(run(content,parameters,stage,version))

def page(stage,template):
    history=store.history();stored=current()
    # 归档页必须回放已签发证据；其余模块页按批次规则版本重跑该阶段。
    state=stored if stage>=7 else replay(stage,stored)
    parallel=store.parallel(state.get('source_key')) if state.get('source_key') else []
    # 复核状态属于已存批次：页脚与归档操作始终指向存储记录，不指向临时重算结果。
    context=stored or state
    return render_template(template,title=TITLE,short=SHORT,modules=MODULES,current=stage,data=state,run=context,
        history=history,parallel=parallel,rules=rulebook.catalogue(),stored=stored)
