# counsel-data-upload Design

## 1. 개요

`nodong_counsel/` 폴더의 전문 노무사 상담 Q&A 434건(14개 파일)을 Pinecone `counsel` 네임스페이스에 업로드하고, RAG 파이프라인에서 검색되도록 `rag.py`를 수정한다.

## 2. 데이터 분석

### 2.1 소스 파일 구조

```
nodong_counsel/
├── 임금_퇴직금.md          (115 Q&A)
├── 기타.md                 (60 Q&A)
├── 근로시간_휴일_휴게.md   (46 Q&A)
├── 해고_구조조정.md        (46 Q&A)
├── 근로계약_채용.md        (36 Q&A)
├── 징계_인사이동.md        (30 Q&A)
├── 부당노동행위.md         (25 Q&A)
├── 4대보험실업급여등.md    (21 Q&A)
├── 노동조합운영.md         (18 Q&A)
├── 여성.md                 (14 Q&A)
├── 비정규직.md             (10 Q&A)
├── 산업재해.md             (5 Q&A)
├── 노동조합가입.md         (4 Q&A)
├── 쟁의행위.md             (4 Q&A)
└── _pairs_cache.json       (444건 매핑 — q_seq, a_seq, category, title)
```

### 2.2 마크다운 파싱 규칙

각 .md 파일은 동일한 구조:
```markdown
# {카테고리} - 노동상담 Q&A

> 출처: 민주노총 서울본부 노동법률지원센터
> 총 N건

---

## {번호}. {제목}

### 질문

{질문 본문}

### 답변

{답변 본문}

---

## {번호}. {제목}
...
```

**파싱 단위**: `## N. 제목` ~ 다음 `---` 또는 다음 `## ` 까지가 1 Q&A 쌍.

### 2.3 _pairs_cache.json 활용

```json
{"q_seq": 185328, "a_seq": 185330, "category": "임금ㆍ퇴직금", "title": "학원강사 퇴직금및 부당대우 문의"}
```

- `q_seq`를 chunk_id 고유키로 사용
- `category`를 메타데이터에 포함
- cache에 없는 Q&A는 파일명 + 순번으로 ID 생성

## 3. 구현 설계

### 3.1 업로드 스크립트: `pinecone_upload_counsel.py`

```
입력: nodong_counsel/*.md + _pairs_cache.json
출력: Pinecone counsel 네임스페이스에 벡터 업로드
```

#### 처리 흐름

```
1. _pairs_cache.json 로드 → {title: {q_seq, category}} 매핑
2. 각 .md 파일 순회:
   a. ## 단위로 Q&A 쌍 분리
   b. 제목으로 cache 매핑 → q_seq, category 결정
   c. 질문+답변을 결합한 텍스트 생성
   d. split_by_size()로 청킹 (max 700자, overlap 80자)
   e. embed_text = f"카테고리: {category}\n제목: {title}\n\n{chunk_text}"
3. 임베딩 (text-embedding-3-small)
4. Pinecone upsert (namespace="counsel")
```

#### 벡터 메타데이터

```python
{
    "id": f"counsel_{q_seq}_chunk_{idx}",   # ASCII, 고유
    "values": embedding,
    "metadata": {
        "source_type": "counsel",            # counsel로 구분
        "title": title[:200],
        "category": category[:50],           # 임금ㆍ퇴직금, 해고ㆍ구조조정 등
        "section": "질문" | "답변" | "전체",
        "chunk_index": idx,
        "chunk_text": chunk_text[:900],      # Pinecone 메타 크기 제한
    },
}
```

#### chunk_id 생성 규칙

- cache 매핑 성공: `counsel_{q_seq}_chunk_{idx}` (예: `counsel_185328_chunk_0`)
- cache 매핑 실패: `counsel_{파일명hash}_{순번}_chunk_{idx}`

### 3.2 RAG 검색 확장: `app/core/rag.py`

현재 `laborlaw-v2`만 검색 → `counsel` 네임스페이스 추가 검색.

#### 변경 방안: 멀티 네임스페이스 검색

```python
# 기존
NAMESPACE = "laborlaw-v2"

# 변경
NAMESPACES = ["laborlaw-v2", "counsel"]
```

`search_pinecone()` 수정:
- 각 네임스페이스에 동일 쿼리로 검색
- 결과를 score 기준 병합 + 중복 제거
- 기존 `search_pinecone_multi()`의 병렬 패턴 활용

#### format_pinecone_hits() 라벨 추가

```python
source_label = {
    "precedent": "판례",
    "interpretation": "행정해석",
    "regulation": "훈령/예규",
    "counsel": "노무사 상담",    # 추가
}.get(h["source_type"], h["source_type"])
```

### 3.3 예상 청크 수

| 항목 | 수량 |
|------|------|
| Q&A 쌍 | 434건 |
| 평균 질문+답변 길이 | ~800자 |
| 평균 청크/Q&A | ~1.5개 |
| **예상 총 청크** | **~650개** |

## 4. 파일 변경 목록

| 파일 | 변경 | 내용 |
|------|------|------|
| `pinecone_upload_counsel.py` | NEW | 업로드 스크립트 |
| `app/core/rag.py` | MODIFY | 멀티 네임스페이스 검색, counsel 라벨 |

## 5. CLI 사용법

```bash
# 청킹만 확인 (업로드 안 함)
python3 pinecone_upload_counsel.py --dry-run

# 업로드
python3 pinecone_upload_counsel.py

# 초기화 후 재업로드
python3 pinecone_upload_counsel.py --reset
```

## 6. 검증 계획

1. `--dry-run`으로 청크 수/ID 충돌 확인
2. 업로드 후 Pinecone 통계 확인 (`counsel` 네임스페이스 벡터 수)
3. 검색 테스트: 7개 쿼리로 counsel 데이터 검색 확인
4. 기존 `laborlaw-v2` 검색이 정상 작동하는지 회귀 테스트
