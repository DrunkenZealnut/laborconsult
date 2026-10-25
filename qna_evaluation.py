#!/usr/bin/env python3
"""Offline A/B/C answer generation with frozen law/model state and blocked DB access.

Automatic format/number-presence checks are not legal accuracy or user satisfaction.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager,ExitStack
from copy import deepcopy
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import time
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse
from vector_ledger import atomic_write_json


@contextmanager
def frozen_runtime(frozen,config):
    import httpx
    import requests
    from app.core import legal_api,legal_rule_store,model_settings,storage
    config.supabase=None
    audit={'blocked_writes':[],'drf_blocked':0,'law_hits':0,'law_misses':0}
    def blocked(*args,**kwargs):
        audit['blocked_writes'].append('database access or cache write')
        raise RuntimeError('production DB access blocked in Q&A evaluation')
    def cached(key,**kwargs):
        value=frozen['law_cache'].get(key)
        audit['law_hits' if value else 'law_misses']+=1
        return value
    real_get=legal_api._http.get
    def get(url,*args,**kwargs):
        if 'law.go.kr/DRF' in str(url):
            audit['drf_blocked']+=1
            response=requests.Response();response.status_code=200
            response._content=b'<Response><result>Offline frozen evaluation</result></Response>'
            response.url=str(url)
            return response
        return real_get(url,*args,**kwargs)
    db_hosts={urlparse(os.getenv(k,'')).hostname for k in ['SUPABASE_URL','NEXT_PUBLIC_SUPABASE_URL']}
    def is_db(url):
        host=urlparse(str(url)).hostname or ''
        return host in db_hosts or host.endswith('.supabase.co')
    real_send=httpx.Client.send
    real_async=httpx.AsyncClient.send
    def send(client,request,*args,**kwargs):
        if is_db(request.url):return blocked()
        return real_send(client,request,*args,**kwargs)
    async def async_send(client,request,*args,**kwargs):
        if is_db(request.url):return blocked()
        return await real_async(client,request,*args,**kwargs)
    real_request=requests.Session.request
    def request(client,method,url,*args,**kwargs):
        if is_db(url):return blocked()
        return real_request(client,method,url,*args,**kwargs)
    store=SimpleNamespace(load=lambda:(frozen['legal_rule_revision'],deepcopy(frozen['legal_rule_document'])),save=blocked)
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ,{**frozen.get('environment',{}),'LAW_API_LIVE':'off','QA_QUALITY_ENABLED':'false'}))
        for obj,name,value in [
            (legal_api,'_l2_cache_get',cached),(legal_api,'_l2_cache_set',blocked),
            (legal_api._http,'get',get),(storage,'make_supabase_client',blocked),
            (model_settings,'load',lambda force=False:(deepcopy(frozen['model_settings']),frozen['model_revision'],True)),
            (legal_rule_store,'configured_store',lambda:store),
            (httpx.Client,'send',send),(httpx.AsyncClient,'send',async_send),
            (requests.Session,'request',request),
        ]:stack.enter_context(patch.object(obj,name,value))
        yield audit


@contextmanager
def capture_api_usage():
    from openai.resources.chat.completions import Completions
    from openai.resources.embeddings import Embeddings
    from anthropic.resources.messages import Messages
    usage=[]
    def wrap(original,provider):
        def create(resource,*args,**kwargs):
            streaming=bool(kwargs.get("stream"))
            if streaming and provider=="openai-chat":
                kwargs["stream_options"]={**kwargs.get("stream_options",{}),"include_usage":True}
            response=original(resource,*args,**kwargs)
            def record(obj):
                value=getattr(obj,"usage",None)
                if value is not None:
                    usage.append({"provider":provider,"model":kwargs.get("model"),"usage":value.model_dump()})
            if not streaming:
                record(response)
                return response
            def iterate():
                try:
                    for chunk in response:
                        record(chunk)
                        yield chunk
                finally:
                    close=getattr(response,"close",None)
                    if close:close()
            return iterate()
        return create
    with ExitStack() as stack:
        for cls,provider in [(Completions,"openai-chat"),(Embeddings,"openai-embedding"),(Messages,"anthropic-message")]:
            stack.enter_context(patch.object(cls,"create",wrap(cls.create,provider)))
        yield usage


def numeric_mentions(expected,answer):
    """Unit-aware presence only; the human reviewer checks what each number means."""
    values=set()
    for match in re.finditer(r'(?<![\d.])([0-9][0-9,]*(?:\.[0-9]+)?)\s*(만|천)?\s*(원|일|시간|개월|년|%)?',answer):
        number=float(match[1].replace(',',''))
        number*=10000 if match[2]=='만' else 1000 if match[2]=='천' else 1
        values.add(number)
    return {key:(any(abs(float(value)-v)<0.01 for v in values) if isinstance(value,(int,float)) else str(value) in answer)
            for key,value in expected.items()}


def fingerprint():
    tracked=subprocess.check_output(['git','ls-files','-z']).decode().split('\0')
    hashes={path:hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in tracked if path and Path(path).is_file()}
    return {'commit':subprocess.check_output(['git','rev-parse','HEAD']).decode().strip(),
            'tree_sha256':hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--frozen',type=Path,required=True);p.add_argument('--fixture',type=Path,action='append',required=True)
    p.add_argument('--condition',choices=['A','B','C'],required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--cases',default='all');p.add_argument('--shard',type=int,default=0);p.add_argument('--shards',type=int,default=1)
    args=p.parse_args()
    from dotenv import load_dotenv
    load_dotenv(override=True)
    frozen=json.loads(args.frozen.read_text())
    # Apply frozen flags before importing model/config constants.
    os.environ.update(frozen.get('environment',{}));os.environ['LAW_API_LIVE']='off'
    expected_mode='without' if args.condition=='A' else 'with'
    if os.getenv('QNA_EVAL_MODE')!=expected_mode:raise ValueError('condition and retrieval mode differ')
    import eval_consultation as ev
    from app.config import AppConfig
    from app.core import pipeline
    cases=[];questions=set()
    for path in args.fixture:
        for case in ev.load_cases(path):
            key=re.sub(r'\s+','',case.question)
            if key not in questions:cases.append(case);questions.add(key)
    if len({c.id for c in cases})!=len(cases):raise ValueError('duplicate case IDs')
    if args.cases!='all':
        wanted=set(args.cases.split(','));cases=[c for c in cases if c.id in wanted]
        if {c.id for c in cases}!=wanted:raise ValueError('unknown case selection')
    cases=[c for i,c in enumerate(cases) if i%args.shards==args.shard]
    if not cases:raise ValueError('empty case shard')
    args.out.parent.mkdir(parents=True,exist_ok=True)
    logging.basicConfig(filename=str(args.out.with_suffix('.log')),level=logging.INFO,
                        format='%(asctime)s %(name)s %(levelname)s %(message)s')
    config=AppConfig.from_env();config.supabase=None
    source_hash=hashlib.sha256(args.frozen.read_bytes()).hexdigest()
    identity={'condition':args.condition,'code':fingerprint(),'frozen_sha256':source_hash,
              'cases':[c.id for c in cases],'namespace':os.getenv('QNA_EVAL_NAMESPACE'),
              'bm25_sha256':hashlib.sha256(Path(os.environ['QNA_EVAL_BM25_PATH']).read_bytes()).hexdigest(),
              'fixed_namespaces':json.loads(os.environ['QNA_EVAL_FIXED_NAMESPACES'])}
    result={'identity':identity,'started_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'results':[]}
    if args.out.exists():
        result=json.loads(args.out.read_text())
        if result['identity']!=identity:raise ValueError('resume experiment identity mismatch')
    done={r['case_id'] for r in result['results']}
    cap={};original=pipeline._stream_answer
    def stream(messages,system,config,outcome=None,*a,**kw):
        cap['context_messages']=messages;cap['system']=system
        yield from original(messages,system,config,outcome,*a,**kw)
        if outcome is not None:
            cap['outcome']={'provider':outcome.provider,'model':outcome.model,'attempts':outcome.attempts,
                            'truncated':outcome.truncated,'empty_providers':outcome.empty_providers}
    with frozen_runtime(frozen,config) as audit,patch.object(pipeline,'_stream_answer',stream),capture_api_usage() as usage:
        for case in cases:
            if case.id in done:continue
            cap.clear();traces=[];config.retrieval_observer=traces.append
            before=deepcopy(audit);usage_start=len(usage)
            observed=ev.run_case(case,config)
            record={'case_id':case.id,'category':case.category,'question':case.question,
                    'expected_values':case.expected_values,'observed':observed,'automatic_format_scores':ev.score_result(case,observed),
                    'numeric_mentions_only':numeric_mentions(case.expected_values,observed['answer']),
                    'trace':traces,'generation':deepcopy(cap),'api_usage':deepcopy(usage[usage_start:]),
                    'usage_note':'Returned API usage only; Anthropic/Gemini fallback streams and Cohere charges may be absent.',
                    'law_cache_hits':audit['law_hits']-before['law_hits'],'law_cache_misses':audit['law_misses']-before['law_misses']}
            result['results'].append(record);result['audit']=deepcopy(audit)
            atomic_write_json(str(args.out),result)
            print(f'{args.condition} {case.id}: answer_chars={len(observed["answer"])} pipeline_error={bool(observed["pipeline_error"])}',flush=True)
            if audit['blocked_writes']:raise RuntimeError('evaluation attempted DB access; results invalid')
    result['finished_at']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
    result['status']='complete';atomic_write_json(str(args.out),result)
    return 0

if __name__=='__main__':raise SystemExit(main())
