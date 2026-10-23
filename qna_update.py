#!/usr/bin/env python3
"""Prepare/embed/apply/build a document-scoped Q&A release. Raw artifacts stay private."""
from __future__ import annotations
import argparse
import gzip
import json
from pathlib import Path
import tiktoken
from qna_corpus import prepare_document,make_vectors,EMBED_MODEL,EMBED_DIM,CHUNK_VERSION,REDACTION_VERSION
from qna_ingestion import digest
from vector_ledger import atomic_write_json


def read(path): return json.loads(Path(path).read_text())
def save(path,obj): atomic_write_json(str(path),obj)


def prepare(crawl:Path,candidate:Path):
    report=read(crawl/'report.json')
    if not report.get('complete') or report.get('date_unknown'):
        raise ValueError('incomplete collection or unknown dates')
    baseline=read(crawl/'baseline-manifest.json')
    state=read(crawl/'state.json')
    selected={}
    for pid,result in state['posts'].items():
        if result['status']!='ok':continue
        record=read(crawl/'records'/f'{pid}.json')
        if record.get('change') in {'new','changed'} or baseline.get(pid,{}).get('status')=='unanswered':
            selected[pid]=record
    candidate.mkdir(parents=True,exist_ok=True)
    identity={'documents':{pid:digest(record) for pid,record in selected.items()},
              'embedding_model':EMBED_MODEL,'embedding_dimensions':EMBED_DIM,
              'chunking_version':CHUNK_VERSION,'redaction_version':REDACTION_VERSION}
    identity['candidate_version']=digest(identity)
    if (candidate/'manifest.json').exists() and read(candidate/'manifest.json')['candidate_version']!=identity['candidate_version']:
        raise ValueError('candidate directory belongs to different input')
    folder=candidate/'prepared';folder.mkdir(exist_ok=True)
    encoder=tiktoken.encoding_for_model(EMBED_MODEL)
    tokens=chunks_count=0
    for pid,record in selected.items():
        chunks,texts=prepare_document(record)
        sizes=[len(encoder.encode(text)) for text in texts]
        if any(n>8191 for n in sizes):raise ValueError('embedding input exceeds token limit')
        tokens+=sum(sizes);chunks_count+=len(chunks)
        save(folder/f'{pid}.json',{'record':record,'chunks':chunks,'texts':texts,'input_hash':digest(texts)})
    output={**identity,'embedding_tokens':tokens,'chunks':chunks_count,'contextualization_tokens':0,
            'collection_report':report}
    save(candidate/'manifest.json',output)
    return output


def _read_vectors(path):
    with gzip.open(path,'rt',encoding='utf-8') as f:return json.load(f)


def embed(candidate:Path,embed_fn):
    manifest=read(candidate/'manifest.json')
    complete=candidate/'embedding-complete.json';complete.unlink(missing_ok=True)
    folder=candidate/'vectors';folder.mkdir(exist_ok=True)
    count=0
    for pid in sorted(manifest['documents']):
        prepared=read(candidate/'prepared'/f'{pid}.json')
        out=folder/f'{pid}.json.gz'
        if out.exists():
            cached=_read_vectors(out)
            if cached['input_hash']!=prepared['input_hash'] or cached['candidate_version']!=manifest['candidate_version']:
                raise ValueError('embedding cache input mismatch')
            # Validate cardinality, dimensions, metadata and text against current prepared input.
            expected=make_vectors(prepared['record'],prepared['chunks'],[r['values'] for r in cached['vectors']])
            if cached['vectors']!=expected:raise ValueError('embedding cache metadata mismatch')
        else:
            values=embed_fn(prepared['texts'])
            rows=make_vectors(prepared['record'],prepared['chunks'],values)
            tmp=out.with_suffix('.tmp')
            with gzip.open(tmp,'wt',encoding='utf-8') as f:
                json.dump({'input_hash':prepared['input_hash'],'candidate_version':manifest['candidate_version'],'vectors':rows},f,ensure_ascii=False)
            tmp.replace(out)
        count+=1
        if count%50==0:print(f'embedded {count}/{len(manifest["documents"])}',flush=True)
    result={'candidate_version':manifest['candidate_version'],'documents':count,'status':'complete'}
    save(complete,result)
    return result


def replacements(candidate):
    manifest=read(candidate/'manifest.json')
    done=read(candidate/'embedding-complete.json')
    if done['candidate_version']!=manifest['candidate_version'] or done['documents']!=len(manifest['documents']):
        raise ValueError('incomplete embedding manifest')
    return {pid:_read_vectors(candidate/'vectors'/f'{pid}.json.gz')['vectors'] for pid in manifest['documents']}


def apply(candidate,index,namespace,ledger,*,production=False,gate=None):
    from qna_vectors import replace_document
    manifest=read(candidate/'manifest.json')
    if namespace=='qa':
        if not production or not gate or gate.get('candidate_version')!=manifest['candidate_version'] or gate.get('passed') is not True:
            raise ValueError('production requires matching quality gate and explicit apply flag')
    rows=replacements(candidate)
    done=ledger/'apply-complete.json';done.unlink(missing_ok=True)
    for number,(pid,vectors) in enumerate(rows.items(),1):
        replace_document(index,namespace,pid,vectors,ledger,production=production)
        if number%50==0:print(f'applied {number}/{len(rows)}',flush=True)
    result={'namespace':namespace,'candidate_version':manifest['candidate_version'],'documents':len(rows),'status':'complete'}
    save(done,result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare');p.add_argument('--crawl',type=Path,required=True);p.add_argument('--candidate',type=Path,required=True)
    p=sub.add_parser('embed');p.add_argument('--candidate',type=Path,required=True)
    p=sub.add_parser('apply');p.add_argument('--candidate',type=Path,required=True);p.add_argument('--namespace',required=True);p.add_argument('--ledger',type=Path,required=True);p.add_argument('--production',action='store_true');p.add_argument('--gate',type=Path)
    p=sub.add_parser('build');p.add_argument('--candidate',type=Path,required=True);p.add_argument('--snapshot',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('restore');p.add_argument('--namespace',required=True);p.add_argument('--ledger',type=Path,required=True);p.add_argument('--post-id',required=True);p.add_argument('--production',action='store_true')
    args=parser.parse_args()
    if args.command=='prepare':result=prepare(args.crawl,args.candidate)
    elif args.command=='build':
        from qna_snapshot import build_sparse
        result=build_sparse(args.snapshot,replacements(args.candidate),args.output)
        save(args.output.with_suffix('.report.json'),result)
    else:
        from dotenv import load_dotenv
        load_dotenv()
        if args.command=='embed':
            from openai import OpenAI
            client=OpenAI(timeout=60,max_retries=3)
            def embedding(texts):
                vectors=[]
                for offset in range(0,len(texts),64):
                    batch=texts[offset:offset+64]
                    response=client.embeddings.create(model=EMBED_MODEL,input=batch)
                    ordered=sorted(response.data,key=lambda row:row.index)
                    if [row.index for row in ordered]!=list(range(len(batch))):raise ValueError('embedding indices mismatch')
                    vectors.extend(row.embedding for row in ordered)
                return vectors
            result=embed(args.candidate,embedding)
        else:
            from app.config import open_offline_index,resolve_index_name
            if resolve_index_name()!='laborconsult':raise ValueError('index must be laborconsult')
            index=open_offline_index()
            if args.command=='apply':
                result=apply(args.candidate,index,args.namespace,args.ledger,production=args.production,gate=read(args.gate) if args.gate else None)
            else:
                from qna_vectors import restore_document
                result=restore_document(index,args.namespace,args.post_id,args.ledger,production=args.production)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
