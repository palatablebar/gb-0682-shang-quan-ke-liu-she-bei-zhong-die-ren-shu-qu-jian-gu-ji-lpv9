import importlib,base64
from flask import Flask,jsonify,request,redirect,Response
from app.config import MODULES
from app.errors import DomainError
from app.workflow import run,load
from app import rulebook,store
from app.web import payload
from app.modules.m7_archive.export_out import bundle

def create_app():
    app=Flask(__name__);app.config['MAX_CONTENT_LENGTH']=2_000_000
    for entry in MODULES:app.register_blueprint(importlib.import_module('app.modules.'+entry[0]+'.handler').bp)
    @app.errorhandler(DomainError)
    def domain_error(error):return jsonify(code=error.code,message=error.message),error.status
    @app.errorhandler(404)
    def missing(error):return jsonify(code='NOT_FOUND',message='入口不存在'),404
    @app.get('/')
    def index():return redirect('/'+MODULES[0][0])
    @app.get('/healthz')
    def health():return jsonify(status='ok',rule_version=rulebook.resolve())
    @app.get('/api/rules')
    def rules():return jsonify(rulebook.catalogue())
    @app.get('/api/schema')
    def schema():return jsonify(state=store.schema_state())
    @app.post('/api/runs')
    def submit():
        content,params,version=payload();state=run(content,params,7,version)
        return jsonify(store.save(state['run_id'],state))
    @app.get('/api/runs')
    def list_runs():return jsonify(store.history())
    @app.get('/api/runs/<run_id>')
    def get_run(run_id):return jsonify(store.get(run_id))
    @app.post('/api/runs/restate')
    def restate():
        data=request.get_json(silent=True) or {}
        old=store.get(data.get('run_id'))
        version=rulebook.resolve(data.get('rule_version'))
        content=base64.b64decode(old.get('source_b64') or '')
        if not content:raise DomainError('SOURCE','该批次未保存原始观测，无法重算')
        params=(old.get('manifest') or {}).get('parameters') or {}
        state=run(content,params,7,version)
        return jsonify(store.save(state['run_id'],state))
    @app.get('/api/runs/<run_id>/parallel')
    def parallel(run_id):return jsonify(store.restated_source(run_id))
    @app.post('/api/runs/combined')
    def combined():
        data=request.get_json(silent=True) or {}
        return jsonify(store.combined(data.get('run_ids')))
    @app.post('/api/runs/<run_id>/review')
    def review(run_id):
        data=request.get_json(silent=True) or {}
        if not isinstance(data.get('version'),int):raise DomainError('VERSION','请提交复核版本')
        return jsonify(store.review(run_id,data['version'],data.get('decision')))
    @app.get('/api/archive/<run_id>/export.csv')
    def download(run_id):
        state=store.get(run_id)
        if not state.get('reconcile',{}).get('balanced'):raise DomainError('UNBALANCED','对账未平')
        return Response(bundle(state),mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename=evidence.csv'})
    with app.app_context():
        store.migrate()
        if not store.history():
            state=run(load('dirty.csv'),{},7);store.save(state['run_id'],state)
    return app

app=create_app()
if __name__=='__main__':app.run(host='0.0.0.0',port=8000)
