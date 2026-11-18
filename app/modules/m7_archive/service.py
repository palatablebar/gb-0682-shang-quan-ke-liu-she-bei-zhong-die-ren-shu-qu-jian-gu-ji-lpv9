from app import rulebook
from app.modules.m7_archive.export_out import checksum

def execute(state):
    version=rulebook.resolve(state.get('rule_version'))
    state['archive']={'sha256':checksum(state),'evidence_count':len(state.get('calculations',[]))+len(state['quarantine']),
        'superseded_count':len(state.get('superseded',[])),
        'ready':state.get('reconcile',{}).get('balanced',False),'rule_version':version}
    return state
