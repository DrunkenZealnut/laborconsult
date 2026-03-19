# Plan: 노동상담 법령·판례 답변모듈

## Executive Summary

| 관점 | 내용 |
|------|------|
| **Problem** | 현재 시스템은 숫자 계산(19개 계산기)과 괴롭힘 판정에 특화되어 있으나, "해고 요건이 뭔가요?", "통상임금 관련 판례를 알려주세요" 같은 법률 해석·정보 제공형 상담에는 274개 BEST Q&A의 벡터 검색만으로 대응하며, 크롤링된 판례 351건·행정해석 1,439건·훈령예규 161건이 미활용 상태 |
| **Solution** | 법령/판례/행정해석 데이터를 Pinecone 별도 네임스페이스에 벡터화하고, Intent Analyzer에 "법률상담(consultation)" 유형을 추가하여 질문 주제별 최적 데이터소스를 자동 선택, legal_api.py의 실시간 법조문 조회와 결합한 구조화된 법률정보 답변모듈 구축 |
| **Function UX Effect** | "부당해고 판례 알려주세요" → 관련 대법원 판례 요지 + 현행 법조문 + 행정해석을 종합한 구조화된 답변 자동 생성 |
| **Core Value** | 2,000건+ 법적 데이터의 검색 가능화 → 계산 불필요 상담의 답변 정확도·근거 신뢰도 대폭 향상, 노동법 상담 전 영역 커버리지 확보 |

---

## 1. 문제 정의

### 1.1 현재 시스템의 응답 경로

```
사용자 질문
    ↓
Intent Analysis (analyzer.py)
    ├─ requires_calculation=true  → 임금계산기 실행 (19개 계산기) ✅ 잘 동작
    ├─ is_harassment=true        → 괴롭힘 판정기 실행 ✅ 잘 동작
    └─ 둘 다 아님 (일반 상담)    → RAG 검색(274개 BEST Q&A)만으로 답변 ⚠️ 부족
```

### 1.2 일반 법률상담의 한계

| 문제 | 상세 | 영향 |
|------|------|------|
| **데이터 미활용** | 판례 351건, 행정해석 1,439건, 훈령예규 161건이 마크다운 파일로만 존재 | 2,000건+ 법적 근거 활용 불가 |
| **의도 분류 부재** | `requires_calculation=false`면 계산/괴롭힘 외 모든 질문이 동일 경로 | 법률상담 특화 처리 불가 |
| **주제별 검색 불가** | 벡터 검색이 BEST Q&A 1개 인덱스에만 한정 | "통상임금 판례"를 검색해도 판례 데이터에 접근 불가 |
| **법적 근거 불충분** | 관련 법조문은 `relevant_laws` 추출 시에만 API 조회 | LLM이 법조문을 추출하지 않으면 근거 없는 답변 |

### 1.3 일반 상담 질문 유형 (미대응 영역)

Q&A 분석 결과에서 확인된 비계산형 질문 유형:

| 유형 | 예시 질문 | 필요 데이터소스 |
|------|----------|----------------|
| **법령 해석** | "5인 미만 사업장에서도 해고예고가 필요한가요?" | 법조문 + 행정해석 |
| **판례 조회** | "통상임금 관련 최근 판례가 있나요?" | 판례 + 법조문 |
| **절차 안내** | "부당해고 구제신청 절차가 어떻게 되나요?" | 행정해석 + 훈령/예규 |
| **권리 확인** | "수습기간 중에도 퇴직금을 받을 수 있나요?" | 법조문 + 행정해석 + 판례 |
| **제도 설명** | "탄력적 근로시간제가 뭔가요?" | 법조문 + 훈령/지침 |
| **비교·분석** | "경영해고와 징계해고의 차이가 뭔가요?" | 판례 + 법조문 |

---

## 2. 데이터소스 현황

### 2.1 기존 벡터화 데이터

| 소스 | 건수 | Pinecone 인덱스 | 네임스페이스 | 상태 |
|------|------|-----------------|-------------|------|
| BEST Q&A | 274개 | `laborconsult-bestqna` | (default) | ✅ 운영 중 |

### 2.2 미활용 마크다운 데이터 (벡터화 대상)

| 소스 | 위치 | 건수 | 카테고리 | 예상 청크수 |
|------|------|------|----------|------------|
| **법원 판례** | `output_법원 노동판례/` | 351건 | 근로기준/노동조합/비정규직/산재보상/기타 | ~2,000 |
| **행정해석** | `output_노동부 행정해석/` | 1,439건 | 30개 주제별 분류 | ~5,000 |
| **훈령/예규/고시** | `output_훈령예규고시지침/` | 161건 | 훈령/예규/고시/지침 | ~800 |
| **법률 상담사례** | `output_legal_cases/` | 114건 | 주제별 상담 Q&A | ~500 |
| **합계** | | **2,065건** | | **~8,300** |

### 2.3 실시간 API 데이터

| 소스 | 상태 | 활용 방식 |
|------|------|----------|
| 법제처 DRF API (법조문) | ✅ `legal_api.py` 구현 완료 | 현행 법령 실시간 조회 |
| 법제처 DRF API (판례) | ✅ `search_precedent()` 구현 완료 | 판례 검색·요지 조회 |

### 2.4 데이터 파일 형식

**판례** (마크다운):
```markdown
# 정기상여금은 통상임금에 해당
| 항목 | 내용 |
| 분류 | 근로기준 |
| 작성일 | 2024.03.17 |
| 원문 | https://www.nodong.kr/case/2363346 |
---
## 판결요지
대법원 2022다252578, 2022.11.10
(본문...)
```

**행정해석** (마크다운):
```markdown
# 통상임금으로 퇴직금을 계산하는 특별한 사유 여부
| 항목 | 내용 |
| 분류 | 통상임금 |
| 작성일 | 2024.03.17 |
| 원문 | https://www.nodong.kr/interpretation/2385329 |
---
## 질의
(질의 내용)
### 회시 답변
(고용노동부 답변)
(근로기준정책과-579, 2023.2.22.)
```

---

## 3. 기능 범위

### 3.1 포함 (In Scope)

#### Phase 1: 법률 데이터 벡터화 (데이터 기반 구축)
- 판례·행정해석·훈령예규 마크다운 파일 → Pinecone 벡터 임베딩 업로드
- 기존 `pinecone_upload.py`의 청킹 로직 재활용
- Pinecone 네임스페이스 분리: `precedent`, `interpretation`, `regulation`
- 메타데이터: `source_type`, `category`, `title`, `url`, `date`

#### Phase 2: 상담 유형 분류 확장 (Intent Analyzer 개선)
- `AnalysisResult`에 `consultation_type` 필드 추가
- 상담 주제 분류: 해고/임금/근로시간/퇴직/산재/비정규/노조/괴롭힘/기타
- `requires_calculation=false`일 때 상담 주제 자동 감지
- 주제별 최적 데이터소스 자동 선택 (판례·행정해석·법조문 조합)

#### Phase 3: 법률상담 전용 응답 파이프라인 (핵심)
- `app/core/legal_consultation.py` — 법률상담 전용 모듈
- 주제별 멀티소스 벡터 검색 (BEST Q&A + 판례 + 행정해석)
- `legal_api.py` 연동: 관련 법조문 자동 조회
- 구조화된 답변 포맷: 법적 근거 → 판례 요지 → 행정해석 → 실무 안내
- `pipeline.py` 통합: consultation_type 감지 시 전용 경로 호출

#### Phase 4: 법률상담 전용 System Prompt
- 법률상담용 시스템 프롬프트 템플릿
- 답변 구조: 핵심 답변 → 관련 법조문 → 판례·행정해석 → 주의사항
- 출처 표기 규칙 (판례번호, 행정해석 번호, 법제처 조회 표기)

### 3.2 제외 (Out of Scope)
- 새로운 데이터 크롤링 (기존 크롤링 데이터만 활용)
- 판례/행정해석 요약 생성 (원문 그대로 제공)
- 사용자 맞춤형 법률 자문 (정보 제공만, 법적 조언 아님)
- 법령 개정 이력 비교
- 일반 Q&A 10,000건 벡터화 (별도 작업)

---

## 4. 기술 전략

### 4.1 아키텍처

```
사용자 질문
    ↓
의도 분석 (analyzer.py 확장)
    ├─ requires_calculation=true → 기존 임금계산기 경로 (변경 없음)
    ├─ is_harassment=true       → 기존 괴롭힘 판정 경로 (변경 없음)
    └─ consultation_type 감지   → [신규] 법률상담 경로
                                    ↓
                              ┌─────────────────────────────────┐
                              │ 법률상담 모듈                      │
                              │ (legal_consultation.py)           │
                              │                                   │
                              │ 1. 주제 기반 멀티소스 검색          │
                              │    ├─ BEST Q&A (기존 인덱스)       │
                              │    ├─ 판례 (precedent NS)         │
                              │    ├─ 행정해석 (interpretation NS) │
                              │    └─ 훈령/예규 (regulation NS)    │
                              │                                   │
                              │ 2. 법조문 API 자동 조회            │
                              │    └─ legal_api.py 활용           │
                              │                                   │
                              │ 3. 컨텍스트 조립                   │
                              │    └─ 주제별 가중치 + 소스별 포맷   │
                              └─────────────────────────────────┘
                                    ↓
                              LLM 답변 생성 (법률상담 전용 System Prompt)
```

### 4.2 Pinecone 네임스페이스 설계

```python
# 기존
INDEX = "laborconsult-bestqna"
NAMESPACE_DEFAULT = ""       # BEST Q&A 274개 (기존)

# 신규
NAMESPACE_PRECEDENT = "precedent"       # 판례 351건
NAMESPACE_INTERPRETATION = "interpretation"  # 행정해석 1,439건
NAMESPACE_REGULATION = "regulation"     # 훈령/예규/고시 161건
NAMESPACE_LEGAL_CASES = "legal_cases"   # 법률상담사례 114건
```

동일 인덱스, 네임스페이스로 분리 → 인덱스 추가 비용 없음, 선택적 검색 가능.

### 4.3 상담 주제 → 데이터소스 매핑

```python
CONSULTATION_SOURCES = {
    "해고·징계": {
        "namespaces": ["precedent", "interpretation", ""],
        "laws": ["근로기준법 제23조", "근로기준법 제26조", "근로기준법 제27조"],
        "keywords": ["해고", "징계", "부당해고", "해고예고", "감봉"],
    },
    "임금·통상임금": {
        "namespaces": ["precedent", "interpretation", ""],
        "laws": ["근로기준법 제2조", "근로기준법 제43조"],
        "keywords": ["통상임금", "평균임금", "임금체불", "임금지급"],
    },
    "근로시간·휴일": {
        "namespaces": ["interpretation", "regulation", ""],
        "laws": ["근로기준법 제50조", "근로기준법 제53조", "근로기준법 제55조"],
        "keywords": ["근로시간", "연장근로", "야간근로", "휴일", "주휴"],
    },
    "퇴직·퇴직금": {
        "namespaces": ["interpretation", "precedent", ""],
        "laws": ["근로자퇴직급여 보장법 제4조", "근로자퇴직급여 보장법 제8조"],
        "keywords": ["퇴직금", "퇴직연금", "퇴직", "중간정산"],
    },
    "연차휴가": {
        "namespaces": ["interpretation", "precedent", ""],
        "laws": ["근로기준법 제60조", "근로기준법 제61조"],
        "keywords": ["연차", "연차휴가", "연차수당", "사용촉진"],
    },
    "산재보상": {
        "namespaces": ["precedent", "interpretation", ""],
        "laws": ["산업재해보상보험법 제37조", "산업재해보상보험법 제52조"],
        "keywords": ["산재", "산업재해", "요양급여", "휴업급여", "장해급여"],
    },
    "비정규직": {
        "namespaces": ["precedent", "interpretation", ""],
        "laws": ["기간제법 제4조", "파견법 제6조"],
        "keywords": ["비정규직", "기간제", "파견", "계약직", "무기계약"],
    },
    "노동조합": {
        "namespaces": ["precedent", ""],
        "laws": ["노동조합법 제2조", "노동조합법 제81조"],
        "keywords": ["노조", "노동조합", "단체교섭", "부당노동행위", "파업"],
    },
    "직장내괴롭힘": {
        "namespaces": ["interpretation", "precedent", ""],
        "laws": ["근로기준법 제76조의2", "근로기준법 제76조의3"],
        "keywords": ["괴롭힘", "갑질", "폭언", "따돌림"],
    },
    "기타": {
        "namespaces": ["", "interpretation"],
        "laws": [],
        "keywords": [],
    },
}
```

### 4.4 벡터 임베딩 업로드 전략

```python
# pinecone_upload_legal.py — 신규 스크립트
# 기존 pinecone_upload.py의 청킹 로직 재활용

def upload_legal_data():
    sources = [
        ("output_법원 노동판례/", "precedent"),
        ("output_노동부 행정해석/", "interpretation"),
        ("output_훈령예규고시지침/", "regulation"),
        ("output_legal_cases/", "legal_cases"),
    ]
    for directory, namespace in sources:
        files = glob(f"{directory}/**/*.md", recursive=True)
        for file in files:
            # 1. 메타데이터 추출 (제목, 분류, 날짜, URL)
            metadata = extract_metadata_from_md(file)
            # 2. 섹션 기반 청킹 (기존 split_by_section + split_by_size)
            chunks = chunk_markdown(file, max_chars=700, overlap=80)
            # 3. 임베딩 + Pinecone 업로드 (namespace 지정)
            embed_and_upsert(chunks, metadata, namespace=namespace)
```

### 4.5 멀티소스 검색 전략

```python
def search_multi_namespace(query: str, namespaces: list[str],
                           top_k_per_ns: int = 3) -> list[dict]:
    """여러 네임스페이스에서 병렬 검색 → 점수 기준 정렬 → 통합 반환"""
    qvec = embed(query)
    all_hits = []
    for ns in namespaces:
        results = index.query(
            vector=qvec, top_k=top_k_per_ns,
            namespace=ns, include_metadata=True,
        )
        for m in results.matches:
            if m.score >= 0.4:
                all_hits.append({
                    "score": m.score,
                    "source_type": ns or "qa",
                    **m.metadata,
                })
    # 점수 기준 정렬, 최대 8개
    return sorted(all_hits, key=lambda x: x["score"], reverse=True)[:8]
```

### 4.6 답변 포맷 설계

```markdown
## 핵심 답변
(1-2문장 요약)

## 관련 법조문
> 근로기준법 제23조(해고 등의 제한)
> ① 사용자는 근로자에게 정당한 이유 없이 해고...
> (법제처 국가법령정보센터 조회)

## 관련 판례
> **대법원 2022다252578 (2022.11.10)**
> 정기상여금은 소정근로를 제공하기만 하면 그 지급이 확정된 것이라고 볼 수 있어...
> [출처: nodong.kr/case/2363346]

## 행정해석
> **근로기준정책과-579 (2023.2.22.)**
> 평균임금이 통상임금보다 적은 경우에는...
> [출처: nodong.kr/interpretation/2385329]

## 유사 상담사례
(BEST Q&A에서 관련 사례 인용)

## 주의사항
- 본 답변은 참고용 정보 제공이며 법적 효력이 없습니다.
- 구체적인 사안은 관할 고용노동부(☎ 1350) 또는 공인노무사에게 상담하시기 바랍니다.
```

### 4.7 에러 처리

| 상황 | 처리 |
|------|------|
| 특정 네임스페이스 검색 실패 | 해당 소스 생략, 나머지로 진행 |
| 법조문 API 조회 실패 | `relevant_laws` 텍스트만 표시, API 결과 없이 진행 |
| 모든 법률 데이터 검색 결과 없음 | 기존 BEST Q&A 결과 + LLM 지식으로 fallback |
| Pinecone 네임스페이스 미생성 | 기존 default 네임스페이스만으로 동작 |

---

## 5. 변경 대상 파일

| # | 파일 | 변경 유형 | 설명 |
|---|------|----------|------|
| 1 | `pinecone_upload_legal.py` | **신규** | 판례·행정해석·훈령예규 벡터 임베딩 업로드 스크립트 |
| 2 | `app/core/legal_consultation.py` | **신규** | 법률상담 전용 모듈 (멀티소스 검색 + 컨텍스트 조립) |
| 3 | `app/models/schemas.py` | 수정 | `AnalysisResult`에 `consultation_type` 필드 추가 |
| 4 | `app/templates/prompts.py` | 수정 | `ANALYZE_TOOL`에 상담 주제 분류 필드 추가 + 법률상담 System Prompt 추가 |
| 5 | `app/core/analyzer.py` | 수정 | `consultation_type` 추출 로직 추가 |
| 6 | `app/core/pipeline.py` | 수정 | 법률상담 경로 분기 추가 (consultation_type 감지 시) |

### 변경하지 않는 것

| 항목 | 이유 |
|------|------|
| `wage_calculator/` | 계산기는 기존대로 유지 (변경 불필요) |
| `chatbot.py` | CLI 전용, API 통합은 pipeline.py만 |
| `app/core/legal_api.py` | 이미 법조문·판례 조회 기능 구현 완료 (재활용) |
| `pinecone_upload.py` | 기존 BEST Q&A 업로드 스크립트 유지 |
| `harassment_assessor.py` | 괴롭힘 판정 경로 독립 유지 |

---

## 6. 구현 순서

```
Step 1: pinecone_upload_legal.py
        — 판례·행정해석·훈령예규 마크다운 → Pinecone 네임스페이스별 업로드
        — 기존 pinecone_upload.py 청킹 로직 재활용
        — 예상 청크: ~8,300개, 예상 비용: ~$0.5 (OpenAI 임베딩)

Step 2: app/models/schemas.py + app/templates/prompts.py
        — AnalysisResult에 consultation_type 추가
        — ANALYZE_TOOL에 consultation_type / consultation_topic 필드 추가
        — CONSULTATION_SYSTEM_PROMPT 추가

Step 3: app/core/analyzer.py
        — consultation_type 추출 로직 (requires_calculation=false일 때 활성화)

Step 4: app/core/legal_consultation.py
        — 주제별 멀티소스 검색 + 법조문 API 조회 + 컨텍스트 조립
        — CONSULTATION_SOURCES 매핑 테이블

Step 5: app/core/pipeline.py
        — consultation_type 감지 시 법률상담 경로 분기
        — 법률상담 전용 System Prompt 사용

Step 6: 통합 테스트
        — 다양한 법률상담 질문으로 E2E 검증
        — 계산 질문/괴롭힘 질문의 기존 동작 회귀 확인
```

---

## 7. 검증 시나리오

| # | 질문 유형 | 입력 예시 | 기대 결과 |
|---|----------|----------|----------|
| 1 | 법령 해석 | "5인 미만 사업장에서 부당해고 구제신청이 가능한가요?" | 근기법 제11조·제23조 법조문 + 행정해석 + BEST Q&A 인용 |
| 2 | 판례 조회 | "통상임금 관련 최근 대법원 판례를 알려주세요" | 판례 벡터 검색 결과(요지) + 법제처 API 판례 조회 |
| 3 | 절차 안내 | "부당해고 구제신청 절차와 기한이 어떻게 되나요?" | 행정해석 + 훈령/예규 + 노동위원회 연락처 |
| 4 | 권리 확인 | "수습기간에도 퇴직금을 받을 수 있나요?" | 법조문 + 행정해석 + 관련 Q&A |
| 5 | 제도 설명 | "탄력적 근로시간제가 뭔가요? 요건은?" | 법조문(제51조) + 행정해석 + 훈령/지침 |
| 6 | 계산 질문 (회귀) | "월급 250만원, 주5일 8시간, 연장 2시간 수당 계산" | 기존대로 계산기 실행 (법률상담 경로 아님) |
| 7 | 괴롭힘 (회귀) | "팀장이 매일 폭언을 합니다" | 기존대로 괴롭힘 판정기 실행 |
| 8 | 복합 질문 | "퇴직금 계산해주시고, 퇴직금 중간정산 요건도 알려주세요" | 계산기 실행 + 법률상담 보충 정보 |
| 9 | 데이터 미존재 | "외국인 근로자 체류자격 변경 절차" | BEST Q&A + LLM 지식으로 fallback, 참고문서 없음 명시 |
| 10 | 행정해석 특화 | "연차 사용촉진 절차를 안 했으면 연차수당 줘야 하나요?" | 행정해석(연차 사용촉진) + 법조문(제61조) |

---

## 8. 리스크 및 대응

| 리스크 | 영향도 | 대응 |
|--------|--------|------|
| Pinecone 무료 플랜 용량 초과 (기존 ~1,722 + 신규 ~8,300 = ~10,000 벡터) | 중 | Pinecone 무료 플랜은 ~100K 벡터 → 충분. 초과 시 Starter 플랜($70/월) 또는 주요 데이터만 선별 |
| 임베딩 비용 증가 | 하 | ~8,300청크 × 1536dim → OpenAI text-embedding-3-small 비용 ~$0.5 (1회성) |
| 의도 분류 정확도 | 중 | consultation_type 추가 시 기존 계산/괴롭힘 분류에 영향 없도록 우선순위 유지 |
| 판례/행정해석 데이터 최신성 | 하 | 크롤링 시점(2024.03) 이후 데이터 없음 → 법제처 API로 보완 |
| 검색 결과 품질 | 중 | 네임스페이스 분리 + 주제별 가중 검색으로 정밀도 확보 |

---

## 9. 성공 지표

| 지표 | 목표 | 측정 방법 |
|------|------|----------|
| 법률상담 답변에 법적 근거 포함율 | ≥ 80% | 판례·법조문·행정해석 중 1개 이상 인용 |
| 기존 계산/괴롭힘 질문 회귀 실패 | 0건 | 기존 테스트 케이스 #1~#32 전부 통과 |
| 벡터 검색 Hit율 (score ≥ 0.4) | ≥ 70% | 법률상담 질문 시 관련 데이터 검색 성공 |
| 답변 생성 시간 | < 10초 | 법령 API + 멀티소스 검색 포함 전체 응답 시간 |

---

## 10. 참고 자료

- 기존 Plan: `docs/01-plan/features/legal-api-integration.plan.md` (법제처 API 연동 — 완료)
- 기존 Report: `docs/04-report/features/legal-api-integration.report.md`
- 법제처 API 클라이언트: `app/core/legal_api.py` (3단계 캐시, 병렬 조회 구현 완료)
- 현재 파이프라인: `app/core/pipeline.py` (RAG + 계산기 + 괴롭힘 + 법조문)
- 의도 분석기: `app/core/analyzer.py` + `app/templates/prompts.py`
- 벡터 업로드: `pinecone_upload.py` (청킹 로직 재활용 대상)
