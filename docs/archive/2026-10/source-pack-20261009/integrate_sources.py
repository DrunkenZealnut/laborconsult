# 기록 보관본(2026-10-09 실행본, 홈 디렉터리 절대경로만 ~로 치환) — 이 위치에서 실행하지 말 것.
# 입력 자료팩(PACK)·권리 검토(rights_review.json)·준비 산출물은 저장소 밖
# ~/DEV/laborconsult_eval/source-integration-20261009/ 에 있고, 경로가 하드코딩돼 있다.
# 적재분 검증·롤백은 저장소의 source_pack_ledger.py + data/vector_ledgers/qpack_20261009.json.
# 재적재가 필요하면 이 파일을 근거로 pinecone_upload_* 규약(원장 선기록·NS 명시)에 맞춰 새로 만든다.
"""Local data operation: prepare -> verify-only upsert -> incremental BM25.

Uses existing product schemas. Never resets, deletes, publishes or approves rules.
"""
from pathlib import Path
from collections import Counter
from urllib.parse import urlparse
import json,hashlib,re,html,sys,os,argparse,xml.etree.ElementTree as ET,gzip,time
from dotenv import load_dotenv
ROOT=Path(__file__).resolve().parent
PACK=Path('~/Downloads/laborconsult-source-pack-2026-10-09').expanduser()
REPO=Path('~/DEV/laborconsult-source-integration-20261009').expanduser()
sys.path.insert(0,str(REPO))
from pinecone_upload_official_rules import split_text
from vector_ledger import atomic_write_json
ASOF='2026-10-09';BATCH='sourcepack_20261009'
def sha(b):return hashlib.sha256(b).hexdigest()
def clean(text):
 text=html.unescape(text or '')
 text=re.sub(r'<br\s*/?>','\n',text,flags=re.I)
 text=re.sub(r'</?(?:p|span|div|b|strong|table|tr|td|tbody|ul|li|a|font)(?:\s[^>]*)?>','',text,flags=re.I)
 text=text.replace('\x00','').replace('\xa0',' ')
 return '\n'.join(re.sub(r'[ \t]+',' ',line).strip() for line in text.splitlines() if line.strip())
def effective(v):
 digits=re.sub(r'\D','',v or '')
 return f'{digits[:4]}-{digits[4:6]}-{digits[6:8]}' if len(digits)>=8 else None
def supplement_specs(source_id):
 path=ROOT/'operative_supplement_contexts.json'
 if not path.exists():return []
 return [s for s in json.loads(path.read_text()) if source_id in s['source_ids']]
def application_context(source_id,section):
 section=re.sub(r'(제\d+조의)0+(\d+)',r'\1\2',section)
 matching=[s for s in supplement_specs(source_id) if any(re.match(r'^'+re.escape(a)+r'(?:\s|$)',section) for a in s['affected_articles'])]
 return '\n'.join('[현재 적용 부칙 — '+s['application_note']+']\n'+s['body'] for s in matching)
def current_sections(source):
 f=PACK/source['local_path'];sections=[];skips=[]
 if f.suffix!='.xml':
  t=PACK/source['text_path'];body=clean(t.read_text())
  if source['id']=='cap_amendment_hwp':
   start=body.index('Ⅰ. 체불 임금등 대지급금')
   end=body.index('신ㆍ구조문대비표',start)
   sections.append(('고시 현행 대체조문·금액표',body[start:end].strip(),source.get('effective_date')))
   skips.append({'section':'개정이유·신구조문대비표','reason':'historical wording and explanations excluded'})
  elif source['id']=='wage_decc245991':
   start=body.index('[국민권익위원회 2022-09280,');end=body.rindex('재결한다.')+len('재결한다.')
   sections.append(('행정심판 재결 원문',body[start:end],'2022-09-20'))
   skips.append({'section':'HTML navigation/dialogs','reason':'non-adjudication page chrome excluded'})
  else:sections.append(('별표·서식 원문',body,source.get('effective_date')))
  return sections,skips
 r=ET.parse(f).getroot()
 if r.tag=='법령':
  for j in r.iter('조문단위'):
   if (j.findtext('조문여부') or '').strip()!='조문':continue
   ef=effective(j.findtext('조문시행일자')) or source.get('effective_date')
   title='제'+(j.findtext('조문번호') or '')+'조'
   branch=j.findtext('조문가지번호')
   if branch and branch!='0':title+='의'+branch
   title+=' '+(j.findtext('조문제목') or '')
   body=clean('\n'.join(''.join(e.itertext()) for e in j.iter() if e.tag in ['조문내용','항내용','호내용','목내용']))
   if ef and ef>ASOF:skips.append({'section':title,'reason':'future article','effective':ef});continue
   if re.fullmatch(r'제\d+조(?:의\d+)?\s*삭제.*',body):skips.append({'section':title,'reason':'deleted article'});continue
   if body:sections.append((title.strip(),body,ef))
  # Never embed mixed amendment and supplementary historical bodies as current law.
  skips.append({'section':'부칙·개정문','reason':'mixed historical/future versions; original retained, not embedded as current law'})
  for spec in supplement_specs(source['id']):
   units=[b for b in r.iter('부칙단위') if b.attrib.get('부칙키')==spec['amendment_key']]
   assert len(units)==1,'reviewed supplementary clause missing'
   raw=clean(units[0].findtext('부칙내용'))
   assert all(line in raw for line in spec['body'].splitlines()),'supplement excerpt not verbatim'
   assert spec['formal_effective_date']<=ASOF
   sections.append((spec['section'],'[현재 적용 범위: '+spec['application_note']+']\n'+spec['body'],spec['formal_effective_date']))
  for by in r.iter('별표단위'):
   ef=effective(by.findtext('별표시행일자')) or source.get('effective_date')
   if ef and ef>ASOF:continue
   text=clean(by.findtext('별표내용'));title=clean(by.findtext('별표제목') or '별표')
   number=by.findtext('별표번호') or '';branch=by.findtext('별표가지번호') or ''
   identity=(by.findtext('별표구분') or '별표')+' '+number+('-'+branch if branch.strip('0') else '')
   title=identity+' '+title
   if len(text)>100 and '<img' not in text.lower() and not text.startswith(('http','[별표이미지')):sections.append((title,text,ef))
   elif text:skips.append({'section':title,'reason':'image/link annex; original retained'})
 elif r.tag=='PrecService':
  assert source['category']=='precedent'
  for tag in ['판시사항','판결요지','판례내용','참조조문']:
   text=clean(r.findtext(tag))
   if text:sections.append((tag,text,None))
 elif r.tag=='AdmRulService':
  assert r.findtext('.//현행여부') not in ['N','n']
  body=clean('\n'.join(e.text or '' for e in r.iter('조문내용')))
  if body:
   # Article boundaries preserve independent intact provisions when an image table
   # prevents recovering one provision. Never publish the incomplete provision.
   for part in re.split(r'(?m)(?=^제\d+조(?:의\d+)?(?:\(|\s))',body):
    if not part.strip():continue
    heading=re.match(r'제\d+조(?:의\d+)?(?:\([^\n]*?\))?',part)
    section=heading.group(0) if heading else '현행 행정규칙 본문'
    sections.append((section,part.strip(),source.get('effective_date')))
  for by in r.iter('별표단위'):
   text=clean(by.findtext('별표내용'));title=clean(by.findtext('별표제목') or '별표')
   number=by.findtext('별표번호') or '';branch=by.findtext('별표가지번호') or ''
   identity=(by.findtext('별표구분') or '별표')+' '+number+('-'+branch if branch.strip('0') else '')
   title=identity+' '+title
   if len(text)>100 and '<img' not in text.lower():sections.append((title,text,source.get('effective_date')))
  skips.append({'section':'부칙·개정문','reason':'mixed historical amendments excluded'})
 elif source['category']=='precedent':
  # Administrative decision XML has a different schema; preserve full adjudication body.
  text=clean((PACK/source['text_path']).read_text())
  if text:sections.append(('결정 원문',text,None))
 else:raise ValueError('unknown XML schema')
 intact=[]
 for section,text,ef in sections:
  if re.search(r'<img\b|<image\b',text,re.I):skips.append({'section':section,'reason':'substantive image/formula not recovered; whole provision held'})
  else:intact.append((section,text,ef))
 return intact,skips
def prepare():
 catalog=json.loads((PACK/'catalog.json').read_text())
 rights=json.loads((ROOT/'rights_review.json').read_text())
 if isinstance(rights,dict):rights=rights.get('works') or rights.get('decisions') or rights.get('items')
 decisions={x['work_id']:x for x in rights}
 sources={x['id']:x for x in catalog['sources']};docs=[];vectors=[];blocked=[];seen=set();skips=[]
 for w in catalog['works']:
  decision=decisions.get(w['id']);assert decision,'missing rights review: '+w['id']
  if decision['decision']!='use_now':blocked.append({'work_id':w['id'],'title':w['title'],'review':decision});continue
  options=[sources[i] for i in w['source_ids'] if sources[i].get('local_path')]
  x=next((s for s in options if s['local_path'].endswith('.xml')),next((s for s in options if s['local_path'].endswith('.pdf')),options[0]))
  assert x['category'] in ['law','precedent'],'non-legal protected source requires a different treatment'
  assert sha((PACK/x['local_path']).read_bytes())==x['sha256'],'source hash changed'
  assert urlparse(x['source_url']).scheme=='https'
  if x.get('effective_date'):assert x['effective_date']<=ASOF
  parts,omit=current_sections(x);skips.extend({'work_id':w['id'],**o} for o in omit)
  key=sha(w['id'].encode())[:16];docdir=ROOT/'cleaned';docdir.mkdir(exist_ok=True)
  cleanparts=[];n=0
  for section,body,ef in parts:
   if len(body)<20:continue
   cleanparts.append({'section':section,'effective_date':ef,'body':body})
   for k,chunk in enumerate(split_text(body)):
    header=x['title']+' — '+section
    header+='\n공식기관: '+x['publisher']+'\n수집 기준일: '+ASOF
    if x['category']=='precedent':header+=' | 선고/결정일: '+str(ef or x.get('published_date') or '원문 참조')
    elif ef:header+=' | 조문/규칙 시행일: '+ef
    context=application_context(x['id'],section)
    if context:header+='\n'+context
    content=header+'\n\n'+chunk
    # Remove byte-for-byte duplicate material within the batch, retaining provenance for the kept source.
    dh=sha((x['title']+'\n'+section+'\n'+str(ef)+'\n'+chunk+('\n'+context if context else '')).encode())
    if dh in seen:continue
    seen.add(dh)
    vid=f'qpack_20261009_{key}_{sha(section.encode())[:10]}_{k}'
    meta={'source_type':'precedent' if x['category']=='precedent' else 'regulation',
      'title':x['title'][:200],'section':section[:160],'text':content,'chunk_text':content,
      'official_url':x['source_url'],'url':x['source_url'],'official':True,'issuer':x['publisher'],
      'date':ef or x.get('published_date') or ASOF,'effective_date':ef if x['category']=='law' and ef else '',
      'retrieved_on':ASOF,'source_batch':BATCH,'source_pack_id':w['id'],'source_sha256':x['sha256'],
      'chunk_sha256':dh,'chunk_index':n,'version_scope':'current_body' if x['category']=='law' else 'judgment_original',
      'rights_basis':decision.get('rights_evidence') if isinstance(decision.get('rights_evidence'),str) else '권리검토 보고서 참조'}
    if context or section.startswith('부칙 제'):
     meta['version_scope']='current_body_with_reviewed_supplement' if context else 'reviewed_applicable_supplement'
     meta['application_context_sha256']=sha((ROOT/'operative_supplement_contexts.json').read_bytes())
    if x['id']=='wage_decc245991':meta['case_no']='2022-09280';meta['court_name']='국민권익위원회 행정심판';meta['decision_kind']='administrative_adjudication'
    if x['category']=='precedent' and x['local_path'].endswith('.xml'):
     root=ET.parse(PACK/x['local_path']).getroot();case=root.findtext('사건번호')
     if case:meta['case_no']=case;meta['court_name']=root.findtext('법원명') or ''
    assert len(json.dumps(meta,ensure_ascii=False).encode())<35000
    vectors.append({'id':vid,'metadata':meta,'embed_text':content});n+=1
  if not cleanparts:blocked.append({'work_id':w['id'],'title':w['title'],'reason':'no verified substantive text'});continue
  path=docdir/(key+'.json');path.write_text(json.dumps({'source':x,'sections':cleanparts},ensure_ascii=False,indent=2)+'\n')
  docs.append({'work_id':w['id'],'title':x['title'],'source_id':x['id'],'cleaned_path':str(path),'section_count':len(cleanparts),'chunk_count':n,'source_sha256':x['sha256']})
 assert len({v['id'] for v in vectors})==len(vectors)
 assert all(v['id'].startswith('qpack_20261009_') for v in vectors)
 with (ROOT/'prepared_vectors.jsonl').open('w') as f:
  for v in vectors:f.write(json.dumps(v,ensure_ascii=False)+'\n')
 atomic_write_json(str(ROOT/'preparation.json'),{'as_of':ASOF,'documents':docs,'held':blocked,'excluded_sections':skips,'vector_count':len(vectors),'namespace':'laborlaw-v2','mode':'additive; no deletion; primary legal works only'})
 print(json.dumps({'documents':len(docs),'held':len(blocked),'vectors':len(vectors),'excluded_sections':len(skips)},ensure_ascii=False),flush=True)
def connect():
 load_dotenv(os.path.expanduser('~/DEV/laborconsult/.env'),override=True)
 from app.config import resolve_index_name
 from pinecone import Pinecone
 name=resolve_index_name();assert name=='laborconsult','unexpected index'
 index=Pinecone(api_key=os.environ['PINECONE_API_KEY']).Index(name)
 assert index.describe_index_stats().dimension==1536
 return index,name
def upload():
 # Freeze rights-review/prepared artifact hashes before the first write.
 p=ROOT/'prepared_vectors.jsonl';data=[json.loads(line) for line in p.read_text().splitlines()]
 index,name=connect();assert (ROOT/'before.json').exists(),'baseline must complete first'
 before=json.loads((ROOT/'before.json').read_text());assert len(before)==50 if isinstance(before,list) else True
 ids=[v['id'] for v in data];preexisting=[]
 for i in range(0,len(ids),100):
  got=index.fetch(ids=ids[i:i+100],namespace='laborlaw-v2');preexisting.extend(got.vectors.keys())
 assert not preexisting,'batch already exists; use verify, not blind overwrite'
 atomic_write_json(str(ROOT/'upload_ledger.json'),{'state':'prepared','index':name,'namespace':'laborlaw-v2','ids':ids,'prepared_sha256':sha(p.read_bytes()),'rights_review_sha256':sha((ROOT/'rights_review.json').read_bytes()),'uploaded_ids':[]})
 from openai import OpenAI
 from app.config import EMBED_MODEL
 client=OpenAI(api_key=os.environ['OPENAI_API_KEY']);uploaded=[];total_tokens=0
 for i in range(0,len(data),64):
  batch=data[i:i+64];response=client.embeddings.create(model=EMBED_MODEL,input=[x['embed_text'] for x in batch]);assert len(response.data)==len(batch)
  payload=[]
  for item,emb in zip(batch,sorted(response.data,key=lambda x:x.index)):
   assert len(emb.embedding)==1536
   payload.append({'id':item['id'],'values':emb.embedding,'metadata':item['metadata']})
  index.upsert(vectors=payload,namespace='laborlaw-v2');uploaded.extend(x['id'] for x in batch);total_tokens+=response.usage.total_tokens
  atomic_write_json(str(ROOT/'upload_ledger.json'),{'state':'uploading','index':name,'namespace':'laborlaw-v2','ids':ids,'uploaded_ids':uploaded,'prepared_sha256':sha(p.read_bytes()),'rights_review_sha256':sha((ROOT/'rights_review.json').read_bytes()),'embedding_tokens':total_tokens})
  print('uploaded',len(uploaded),'/',len(data),flush=True)
 verify()
def verify():
 index,name=connect();data=[json.loads(line) for line in (ROOT/'prepared_vectors.jsonl').read_text().splitlines()];verified=[]
 for attempt in range(5):
  missing=[];verified=[]
  for i in range(0,len(data),100):
   batch=data[i:i+100];got=index.fetch(ids=[v['id'] for v in batch],namespace='laborlaw-v2')
   for want in batch:
    actual=got.vectors.get(want['id'])
    if actual is None:missing.append(want['id']);continue
    assert actual.metadata.get('source_batch')==BATCH
    assert actual.metadata.get('chunk_sha256')==want['metadata']['chunk_sha256']
    assert actual.metadata.get('text')==want['metadata']['text']
    assert len(actual.values)==1536
    verified.append({'id':want['id'],'metadata':actual.metadata})
  if not missing:break
  print('eventual consistency missing',len(missing),flush=True);time.sleep(5)
 assert not missing,'missing uploaded IDs'
 atomic_write_json(str(ROOT/'verified_vectors.json'),verified)
 ledger=json.loads((ROOT/'upload_ledger.json').read_text());ledger.update(state='verified',verified_count=len(verified));atomic_write_json(str(ROOT/'upload_ledger.json'),ledger)
 print('verified',len(verified),name,'laborlaw-v2',flush=True)
def bm25():
 verified=json.loads((ROOT/'verified_vectors.json').read_text());path=REPO/'data/bm25_corpus.jsonl.gz';assert path.exists()
 backup=ROOT/'bm25_before.jsonl.gz'
 if not backup.exists():backup.write_bytes(path.read_bytes())
 new={v['id']:{'id':v['id'],'text':v['metadata']['text'],'title':v['metadata']['title'],'section':v['metadata']['section'],'source_type':v['metadata']['source_type']} for v in verified}
 tmp=path.with_suffix('.gz.tmp');old_count=0;replaced=0
 with gzip.open(backup,'rt',encoding='utf-8') as src,gzip.open(tmp,'wt',encoding='utf-8') as dst:
  for line in src:
   if not line.strip():continue
   d=json.loads(line);old_count+=1
   if d['id'] in new:replaced+=1;continue
   dst.write(json.dumps(d,ensure_ascii=False,separators=(',',':'))+'\n')
  for d in new.values():dst.write(json.dumps(d,ensure_ascii=False,separators=(',',':'))+'\n')
 with gzip.open(tmp,'rt',encoding='utf-8') as src:updated=[json.loads(line) for line in src if line.strip()]
 assert len(updated)==old_count-replaced+len(new)
 assert len({d['id'] for d in updated})==len(updated),'duplicate IDs in BM25 baseline or update'
 assert all(any(d['id']==v['id'] and d['text']==v['text'] for d in updated) for v in list(new.values())[:5])
 tmp.replace(path)
 atomic_write_json(str(ROOT/'bm25_merge.json'),{'baseline_count':old_count,'added':len(new),'replaced_only_batch':replaced,'result_count':len(updated),'preserved_other_entries':old_count-replaced,'sha256':sha(path.read_bytes()),'path':str(path),'backup':str(backup),'method':'incremental from all remotely fetched and verified batch vectors; existing other namespaces retained'})
 print('BM25',old_count,'->',len(updated),'new',len(new),flush=True)
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['prepare','upload','verify','bm25']);args=parser.parse_args();globals()[args.phase]()
