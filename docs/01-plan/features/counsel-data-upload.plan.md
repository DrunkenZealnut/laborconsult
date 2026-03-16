# counsel-data-upload Plan

## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | 노동법 상담 데이터 Pinecone 업로드 |
| 시작일 | 2026-03-16 |
| 예상 기간 | 1일 |

### Value Delivered

| 관점 | 내용 |
|------|------|
| Problem | 20,000건 이상의 노동법 상담 Q&A가 파일로만 존재하여 챗봇 RAG에 활용되지 않음 |
| Solution | 3개 데이터 소스를 Pinecone에 업로드하여 RAG 검색 범위를 확대 |
| Function UX Effect | 사용자 질문에 대해 유사 상담 사례 기반의 더 정확하고 실용적인 답변 제공 |
| Core Value | 실제 노동상담 Q&A 20,000건으로 답변 품질과 범위를 대폭 향상 |

---

## 1. 현황 분석

### 1.1 데이터 소스

| 폴더 | 파일 수 | 형태 | 내용 |
|------|---------|------|------|
| `nodong_counsel/` | 14개 (434 Q&A) | 주제별 통합 .md | 민주노총 서울본부 노동법률지원센터 Q&A (전문 노무사 답변) |
| `output_qna/` | 9,809개 | 개별 .md | 노동OK 일반 Q&A (게시판 크롤링) |
| `output_qna_2/` | 9,807개 | 개별 .md | 노동OK 일반 Q&A (추가 크롤링분) |
| **합계** | **~20,050 Q&A** | | |

### 1.2 현재 Pinecone 상태

| 네임스페이스 | 벡터 수 | 데이터 소스 |
|-------------|---------|------------|
| `__default__` | 11,311 | BEST Q&A (274개, pinecone_upload.py) |
| `laborlaw-v2` | 9,088 | ← **현재 RAG가 검색하는 네임스페이스** |
| `precedent` | 6,540 | 법원 판례 836개 |
| `laborlaw` | 6,598 | (구버전) |

### 1.3 핵심 문제

- `nodong_counsel/` — **전문 노무사 답변**이 포함된 고품질 데이터이나 Pinecone에 없음
- `output_qna/` + `output_qna_2/` — **19,616건**이 Pinecone에 없음
- `pinecone_upload_contextual.py`에 `output_qna_2`만 등록되어 있고, `output_qna`와 `nodong_counsel`은 미등록
- RAG(`rag.py`)는 `laborlaw-v2` 네임스페이스만 검색 → Q&A가 올라가도 검색 안 될 수 있음

---

## 2. 구현 계획

### Phase 1: nodong_counsel 업로드 (고품질 우선)

**우선순위**: 높음 (전문 노무사 답변, 434건)

- 14개 통합 .md 파일을 Q&A 쌍 단위로 분리 → 청킹
- 네임스페이스: `counsel` (신규) 또는 기존 `laborlaw-v2`에 통합
- 메타데이터: `source_type=counsel`, `category=임금_퇴직금` 등
- `_pairs_cache.json`의 444건 매핑 활용 가능

### Phase 2: output_qna + output_qna_2 업로드 (대량)

**우선순위**: 중간 (일반 사용자 Q&A, ~19,616건)

- `pinecone_upload_contextual.py`에 `output_qna` 소스 추가
- 또는 `pinecone_upload_legal.py` 패턴으로 별도 업로드 스크립트
- 네임스페이스: `qa` (pinecone_upload_contextual.py에 이미 정의됨)
- 중복 검사: `output_qna`와 `output_qna_2`의 post_id 기준

### Phase 3: RAG 검색 확장

**우선순위**: 필수 (업로드해도 검색 안 하면 의미 없음)

- `rag.py`의 `search_pinecone()`이 `laborlaw-v2`만 검색
- 멀티 네임스페이스 검색 추가 또는 단일 네임스페이스 통합
- **방안 A**: 모든 데이터를 `laborlaw-v2`에 통합 (단순, 네임스페이스 1개)
- **방안 B**: 네임스페이스별 검색 후 병합 (분리 유지, 코드 수정 필요)

---

## 3. 의사결정 필요 사항

| # | 질문 | 선택지 | 권장 |
|---|------|--------|------|
| 1 | 네임스페이스 전략 | A: `laborlaw-v2` 통합 / B: 별도 `qa`, `counsel` | **A** (RAG 코드 수정 불필요) |
| 2 | output_qna 중복 처리 | qna와 qna_2의 중복 post_id 건너뛰기 | post_id 기준 중복 검사 |
| 3 | nodong_counsel 청킹 단위 | Q&A 쌍 단위 / 섹션 단위 | **Q&A 쌍 단위** (질문+답변 함께) |
| 4 | 예상 비용 | 임베딩 API 비용 | ~$3-5 (20,000건 × 5-10 청크) |

---

## 4. 예상 산출물

| 산출물 | 경로 |
|--------|------|
| 업로드 스크립트 | `pinecone_upload_counsel.py` (또는 기존 스크립트 확장) |
| RAG 검색 확장 | `app/core/rag.py` 수정 (방안 B 선택 시) |
| 검증 테스트 | 검색 품질 테스트 쿼리 |

---

## 5. 리스크

| 리스크 | 영향 | 대응 |
|--------|------|------|
| Pinecone 벡터 한도 초과 | 업로드 실패 | Serverless는 한도 없음 (비용 비례) |
| 대량 업로드 시간 | 19,616건 × 임베딩 = 수 시간 | 배치 처리 + 재개 기능 |
| Q&A 품질 편차 | 저품질 답변이 RAG에 노출 | counsel(전문 답변) 우선 가중치 |
