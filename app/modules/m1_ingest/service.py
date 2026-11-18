from app import rulebook
from app.modules.m1_ingest.reader import read

def execute(content, parameters=None, rule_version=None):
    version=rulebook.resolve(rule_version)
    state=read(content)
    state['parameters']=parameters or {}
    state['rule_version']=version
    state['rule_profile']=rulebook.profile(version).as_dict()
    for entry in state['quarantine']:entry.setdefault('rule_version',version)
    state['superseded']=state.get('superseded',[])
    return state
