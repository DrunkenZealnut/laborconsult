# output-qna-upload Plan

## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | output_qna + output_qna_2 노동 상담 Q&A Pinecone 업로드 |
| 시작일 | 2026-03-16 |
| 예상 기간 | 1일 |

### Value Delivered

| 관점 | 내용 |
|------|------|
| Problem | 19,616건의 노동OK Q&A가 벡터 DB에 없어 RAG 검색에 활용 불가 |
| Solution | output_qna(9,809) + output_qna_2(9,807)를 Pinecone qa 네임스페이스에 업로드 |
| Function UX Effect | 실제 상담 사례 기반의 더 구체적이고 실용적인 답변 제공 |
| Core Value | 19,616건 실전 Q&A로 RAG 검색 범위와 답변 품질 대폭 확대 |

---

## 1. 현황 분석

### 1.1 데이터 소스

| 폴더 | 파일 수 | 평균 크기 | 예상 청크 | 내용 |
|------|---------|----------|----------|------|
| `output_qna/` | 9,809 | ~1,128자 | ~17,849 | 노동OK 일반 Q&A |
| `output_qna_2/` | 9,807 | ~1,152자 | ~18,222 | 노동OK 일반 Q&A (추가분) |
| **합계** | **19,616** | | **~36,070** | |

- 중복 파일명: 12건 (post_id 기준 중복 검사 필요)
- `pinecone_upload_contextual.py`에 `output_qna_2`만 등록 상태

### 1.2 Pinecone 현황

- `qa` 네임스페이스: **0 벡터** (아직 업로드 안 됨)
- 현재 총 벡터: 46,233개

### 1.3 비용·시간 비교

| 방식 | 비용 | 시간 | 검색 품질 |
|------|------|------|----------|
| **일반 임베딩** | ~$0.22 | ~6분 | 보통 |
| **Contextual Retrieval** | ~$55 | ~60분 | 높음 |
| **일반 + skip-context** | ~$0.22 | ~6분 | 보통 (기존 스크립트 활용) |

---

## 2. 의사결정 사항

### 2.1 업로드 방식

| # | 선택지 | 비용 | 권장 |
|---|--------|------|------|
| A | Contextual Retrieval (Haiku로 맥락 생성) | ~$55 | 품질 최우선 시 |
| B | 일반 임베딩 (skip-context) | ~$0.22 | **권장** — 대량 Q&A는 질문+답변 자체가 맥락 |
| C | 단계적: 일반 먼저 → 나중에 Contextual 업그레이드 | ~$0.22 → $55 | 유연 |

**권장: B (skip-context)** — Q&A 데이터는 질문+답변이 함께 있어 맥락이 자명. $55 추가 투자 대비 효과 미미.

### 2.2 네임스페이스

- `qa` 네임스페이스 사용 (pinecone_upload_contextual.py에 이미 정의)
- `rag.py`의 `NAMESPACES`에 `qa` 추가 필요

### 2.3 중복 처리

- output_qna와 output_qna_2의 post_id(파일명 앞 숫자) 기준 중복 검사
- 12건 중복 → 먼저 업로드된 것 유지, 나중 것 스킵

---

## 3. 구현 계획

### Phase 1: pinecone_upload_contextual.py에 output_qna 소스 추가

```python
SOURCES에 추가:
{
    "directory": "output_qna",
    "namespace": "qa",
    "source_type": "qa",
    "label": "Q&A 상담 (1차)",
}
```

### Phase 2: 업로드 실행

```bash
# 일반 임베딩 (skip-context) — 약 6분
python3 pinecone_upload_contextual.py --source "Q&A" --skip-context

# 또는 개별 실행
python3 pinecone_upload_contextual.py --source "Q&A 상담 (1차)" --skip-context
python3 pinecone_upload_contextual.py --source "Q&A 상담" --skip-context
```

### Phase 3: RAG 검색 확장

`rag.py`의 `NAMESPACES`에 `qa` 추가:
```python
NAMESPACES = ["laborlaw-v2", "counsel", "qa"]
```

### Phase 4: 검증

- Pinecone `qa` 네임스페이스 벡터 수 확인 (~36,070)
- 검색 테스트 (Q&A 데이터가 검색되는지)
- 기존 검색 품질 회귀 테스트

---

## 4. 리스크

| 리스크 | 영향 | 대응 |
|--------|------|------|
| 대량 업로드 시간 (~6분) | 낮음 | --resume로 재개 가능 |
| Pinecone 벡터 수 급증 (+36K) | 비용 증가 | Serverless 종량제 |
| Q&A 품질 편차 | 저품질 답변 노출 | counsel(전문)이 score 높으면 우선 |
| 중복 post_id | 벡터 덮어쓰기 | ID에 소스 prefix 포함 |

---

## 5. 예상 산출물

| 산출물 | 내용 |
|--------|------|
| `pinecone_upload_contextual.py` 수정 | output_qna 소스 추가 |
| `app/core/rag.py` 수정 | NAMESPACES에 qa 추가 |
| Pinecone qa 네임스페이스 | ~36,070 벡터 |
