from app import rulebook
from app.modules.m6_reconcile.compare import balance

def execute(state):
    state['reconcile']=balance(state,rulebook.resolve(state.get('rule_version')));return state
