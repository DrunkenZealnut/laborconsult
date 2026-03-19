#!/usr/bin/env python3
"""잔여 56개 파일 처리: 중복 삭제 + 신규 업로드 + 카테고리 이동."""

import os, re, time
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
from pinecone import Pinecone

load_dotenv()

base = str(Path(__file__).parent / 'output_법원 노동판례')

CASE_NO = re.compile(r'(\d{4}[다두도가누마재추허][A-Za-z가-힣]*\d+)')

KR_TO_ASCII = {
    "다":"da","두":"du","도":"do","가":"ga","누":"nu",
    "나":"na","마":"ma","추":"chu","재":"jae","허":"heo",
}

def to_ascii(s):
    for k, v in KR_TO_ASCII.items():
        s = s.replace(k, v)
    return re.sub(r'[^\x00-\x7F]', '', s)

CATEGORY_KEYWORDS = {
    "노동조합": ["노동조합","노조","단체교섭","쟁의","파업","교섭창구","부당노동행위","단체협약","조합원","쟁의행위","교섭대표","복수노조","공정대표의무","조례"],
    "산재보상": ["산재","산업재해","업무상 재해","업무상재해","요양급여","장해급여","유족급여","진폐","출퇴근 재해","산재보험","업무상 질병","재해위로금","장해등급","중대재해"],
    "비정규직": ["파견근로","기간제","비정규","차별시정","고용간주","직접고용 간주","고용의무","고용승계","파견법","기간제법","사내하도급","불법파견","갱신기대권"],
}

def classify(title, content):
    scores = {}
    for cat, kws in CATEGORY_KEYWORDS.items():
        s = sum(3 for kw in kws if kw in title) + sum(1 for kw in kws if kw in content[:2000])
        if s > 0:
            scores[cat] = s
    if not scores:
        return "근로기준"
    best = max(scores, key=scores.get)
    if not any(kw in title for kw in CATEGORY_KEYWORDS.get(best, [])) and scores[best] < 3:
        return "근로기준"
    return best

def clean_text(t):
    t = t.replace("\xa0", " ")
    t = re.sub(r"\\\n", "\n", t)
    t = re.sub(r"\\([*_\[\]()#!])", r"\1", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()

def split_by_size(text, mx=700, ov=80):
    text = text.strip()
    if not text:
        return []
    if len(text) <= mx:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        end = min(start + mx, len(text))
        if end < len(text):
            for d in ["\n\n", "\n", ". ", ", "]:
                p = text.rfind(d, start + max(ov, 50), end)
                if p > start:
                    end = p + len(d)
                    break
        c = text[start:end].strip()
        if c:
            chunks.append(c)
        if end >= len(text):
            break
        start = end - ov
    return chunks


# 기존 사건번호 수집
existing = set()
for cat in ['근로기준', '노동조합', '산재보상', '비정규직', '기타']:
    cd = os.path.join(base, cat)
    if not os.path.isdir(cd):
        continue
    for f in os.listdir(cd):
        if not f.endswith('.md'):
            continue
        with open(os.path.join(cd, f), 'r', encoding='utf-8') as fh:
            for m in CASE_NO.finditer(fh.read()):
                existing.add(m.group(1))

print(f"기존 사건번호: {len(existing)}개\n")

# Pinecone + OpenAI
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
index = pc.Index(os.getenv("PINECONE_INDEX_NAME", "laborconsult-bestqna"))

deleted_dups = 0
uploaded = 0
total_chunks = 0
error_list = []
all_vectors = []

for year in range(2020, 2027):
    yr_dir = os.path.join(base, f'대법원_{year}')
    if not os.path.isdir(yr_dir):
        continue
    for fname in sorted(os.listdir(yr_dir)):
        if not fname.endswith('.txt'):
            continue
        fp = os.path.join(yr_dir, fname)

        # 파일 읽기
        try:
            with open(fp, 'r', encoding='utf-8') as fh:
                content = fh.read()
        except Exception as e:
            error_list.append(f"{fname}: {e}")
            continue

        # 사건번호: 파일명 → 본문 fallback
        m = CASE_NO.search(fname)
        if not m:
            m = CASE_NO.search(content[:500])
        if not m:
            error_list.append(f"{fname}: 사건번호 추출 불가")
            continue
        case_no = m.group(1)

        # 중복검사
        if case_no in existing:
            os.remove(fp)
            deleted_dups += 1
            print(f"  🗑️ 중복 삭제: {case_no} ({fname[:50]})")
            continue

        # 제목 추출
        date_match = re.search(r'(20\d{6})', fname)
        date_str = ""
        if date_match:
            d = date_match.group(1)
            date_str = f"{d[:4]}.{d[4:6]}.{d[6:8]}"

        case_pos = fname.find(case_no)
        if case_pos >= 0:
            title = fname[case_pos + len(case_no) + 1:].replace('.txt', '').replace('_', ' ').strip()
        else:
            parts = fname.replace('.txt', '').split('_')
            title = ' '.join(parts[4:]) if len(parts) > 4 else case_no
        if not title:
            title = case_no

        # 분류
        category = classify(title, content)

        # md 변환
        lines = content.strip().split('\n')
        if lines and '연구소' in lines[0]:
            lines = lines[1:]
        body_text = '\n'.join(lines).strip()

        md = f"""# {title}

| 항목 | 내용 |
| --- | --- |
| 분류 | {category} |
| 작성일 | {date_str} |
| 사건번호 | {case_no} |

---

{body_text}
"""
        # md 저장
        safe_title = re.sub(r'[/\\:*?"<>|]', '', title)[:60]
        md_fname = f"{case_no}_{safe_title}.md"
        cat_dir = os.path.join(base, category)
        os.makedirs(cat_dir, exist_ok=True)
        md_dest = os.path.join(cat_dir, md_fname)

        with open(md_dest, 'w', encoding='utf-8') as f:
            f.write(md)

        # 청킹
        body_clean = clean_text(body_text)
        if len(body_clean) < 20:
            os.remove(fp)
            continue

        chunks = []
        idx = 0
        for sub in split_by_size(body_clean):
            if not sub.strip():
                continue
            embed_text = f"제목: {title}\n분류: {category}\n\n{sub}"
            chunks.append({
                "chunk_id": f"precedent_{to_ascii(case_no)}_chunk_{idx}",
                "embed_text": embed_text,
                "chunk_text": sub,
                "section": "본문",
                "chunk_index": idx,
            })
            idx += 1

        if not chunks:
            os.remove(fp)
            continue

        total_chunks += len(chunks)

        # 임베딩
        texts = [c["embed_text"] for c in chunks]
        embs = []
        for bs in range(0, len(texts), 50):
            batch = texts[bs:bs + 50]
            for attempt in range(3):
                try:
                    resp = openai_client.embeddings.create(model="text-embedding-3-small", input=batch)
                    embs.extend([d.embedding for d in sorted(resp.data, key=lambda x: x.index)])
                    break
                except Exception as e:
                    if attempt == 2:
                        raise
                    time.sleep(2 ** attempt)
            time.sleep(0.3)

        for chunk, emb in zip(chunks, embs):
            all_vectors.append({
                "id": chunk["chunk_id"],
                "values": emb,
                "metadata": {
                    "source_type": "precedent",
                    "title": title[:200],
                    "category": category[:50],
                    "date": date_str,
                    "url": "",
                    "section": chunk["section"][:100],
                    "chunk_index": chunk["chunk_index"],
                    "chunk_text": chunk["chunk_text"][:900],
                },
            })

        if len(all_vectors) >= 100:
            index.upsert(vectors=all_vectors, namespace="precedent")
            all_vectors = []
            time.sleep(0.1)

        # 원본 삭제
        os.remove(fp)
        existing.add(case_no)
        uploaded += 1
        print(f"  ✅ {case_no} → {category} | {title[:50]} ({len(chunks)} 청크)")

# 남은 벡터 upsert
if all_vectors:
    index.upsert(vectors=all_vectors, namespace="precedent")

print(f"\n{'=' * 60}")
print(f"중복 삭제: {deleted_dups}개")
print(f"신규 업로드: {uploaded}개 ({total_chunks} 청크)")
if error_list:
    print(f"오류: {len(error_list)}개")
    for e in error_list:
        print(f"  ❌ {e}")

# 빈 대법원 폴더 삭제
for year in range(2020, 2027):
    yr_dir = os.path.join(base, f'대법원_{year}')
    if os.path.isdir(yr_dir) and not os.listdir(yr_dir):
        os.rmdir(yr_dir)
        print(f"  빈 폴더 삭제: 대법원_{year}/")

time.sleep(2)
stats = index.describe_index_stats()
ns = stats.namespaces.get('precedent')
print(f"\nPinecone precedent: {ns.vector_count:,}개 벡터" if ns else "\nPinecone precedent: 없음")
print(f"{'=' * 60}")
