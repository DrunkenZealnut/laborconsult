"""Persist retrieval only after a real web answer was stored successfully."""
import json
import os
from pathlib import Path
from app.core.answer_feedback import issue_token

_RELEASE_PATH=Path(__file__).resolve().parents[2]/'data'/'qa_corpus_release.json'

_clients = {}

def quality_client():
    key=os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        return None
    identity=(os.getenv("SUPABASE_URL"),key)
    if identity not in _clients:
        from app.core.storage import make_supabase_client
        _clients.clear()
        _clients[identity]=make_supabase_client(key=key,postgrest_timeout=5.0)
    return _clients[identity]


def release_versions():
    if _RELEASE_PATH.is_file():
        release=json.loads(_RELEASE_PATH.read_text())
        return {'corpus_version':release['corpus_version'],
                'calculator_version':release['calculator_version'],
                'answer_code_version':release['answer_code_version']}
    # Explicitly unknown; never pretend a requested run has been deployed.
    return {'corpus_version':'unversioned','calculator_version':'unversioned','answer_code_version':'unversioned'}

def record_quality(client,conversation_id,session_id,trace,answer_model,*,synthetic):
    if os.getenv('QA_QUALITY_ENABLED','').lower()!='true' or synthetic or not client:
        return None
    secret=os.getenv('ADMIN_JWT_SECRET') or os.getenv('ADMIN_PASSWORD','')
    if not secret:
        return None
    versions={**release_versions(),'answer_model':answer_model}
    token=issue_token(secret,conversation_id,session_id,versions)
    client.schema('laborconsult').table('qa_retrieval_traces').insert({
        'conversation_id':conversation_id,'trace_id':trace['trace_id'],'items':trace['items'],
        'unidentified_selected':trace['unidentified_selected'],'versions':versions,
    }).execute()
    return {'type':'feedback','token':token}
