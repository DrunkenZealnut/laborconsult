# colloquial-legal-mapping Design

> Plan: `docs/01-plan/features/colloquial-legal-mapping.plan.md` (2026-08-20 실측 포함)
> 목표: G1 폴백 RAG 활성화+구어 사전 / G2 법률근거 승격(교체) / G3 변환 회귀 고정

## 1. 컴포넌트 개요

| ID | 컴포넌트 | 파일 | 신규/수정 |
|----|----------|------|:---:|
| C1 | 폴백 RAG 활성화 + 구어→법률용어 정적 사전 | `app/core/colloquial_map.py`(신규), `app/core/pipeline.py`(수정) | 신규+수정 |
| C2 | 법률근거 승격 — 승격 공용화 | `app/core/rag.py` | 수정 |
| C3 | 의도분석 변환 예시 계열 확장 + 구어 회귀 fixture | `app/templates/prompts.py`, `data/eval_colloquial_queries.json`(신규), `eval_colloquial.py`(신규) | 수정+신규 |

구현 순서: **C2 → C1 → C3** — C2가 코어(회귀 기반 확보), C1은 배선, C3은 프롬프트·계측.

---

## 2. C1 — 폴백 RAG 활성화 + 구어 사전

### 2.1 현재 동작 (실측 근거)

`pipeline.py:1566` `if analysis:` 조건이 판례·행정해석 검색 블록 전체를 감싼다. 의도분석 실패(`analysis=None`) 시:

- RAG 검색 0회 → 답변이 검색 근거 없이 생성 (V1)
- 스코프 게이트 skip(기존 fail-open, 유지)
- `_extract_params`(Sonnet)는 계산·괴롭힘 후보일 때만 별도 시도(기존, 유지)

### 2.2 변경

**G1a — 합성 분석 주입** *(Do에서 원안 "가드 완화" 대신 채택 — 우월 대체)*: `analysis is None`이면 RAG 블록 직전에 전 필드 기본값의 합성 `AnalysisResult(precedent_keywords=사전_매핑, intent_provider="synthetic")`를 주입한다. 가드만 풀면 블록 내 `analysis.calculation_types` 류 무방비 참조가 폴백에서 AttributeError였는데, 합성 객체는 이를 구조적으로 해소하고 하류(NLRC·상담 매핑·지식 모듈·저장)는 "빈 분석"으로 무해 통과한다. 주입 지점이 스코프 게이트·계산 라우팅 **뒤**라 그 둘은 기존 동작(게이트 skip·레거시 추출)을 유지한다.
- **부수 활성화(수용)**: RAG만이 아니라 NLRC 판정사례 검색(사전 매칭 시)·GraphRAG도 폴백에서 살아난다 — 검색 계열이 살아나는 방향이라 목적 정합, NLRC는 번들 우선이라 비용 제한적.
- **합성 경로는 complexity를 SIMPLE로 강제한다**(분석 P1-4) — 이 경로는 정의상 Claude·OpenAI가 모두 죽은 상태라, MODERATE 이상이 여는 decompose(Anthropic)·Self-RAG(Haiku)·wider는 죽은 벤더 재호출이다. 아울러 임베딩 호출(`rag.py::search_pinecone`)에 국소 타임아웃(`with_options(timeout=10, max_retries=0)`)을 둬 행(hang) 열화가 프론트 idle(60s)을 넘기지 않게 한다.
- **계측**: `intent_provider="synthetic"`이 `metadata.llm`에 저장돼 "의도분석 전멸 대화"를 사후 식별한다. 사전 발동·미매칭 모두 로그를 남긴다(분석 P2-6).

**G1b — 구어 사전 병기**: `analysis is None`일 때만 발동. **"병기"의 실제 구현은 `_merge_search_queries(always_fallback=True)`다**(분석 P1-2) — 기본 동작은 fallback(원문)을 merged가 비었을 때만 붙이므로, 사전이 매칭되면 원문이 탈락해 검색이 일반명사 나열만으로 돌게 된다. 합성 경로에서만 원문을 항상 병기하고, 정상 경로 기본값은 기존 설계(LLM 재진술 쿼리로 검색)를 유지한다.

```python
# app/core/colloquial_map.py (신규, 외부 의존 0 — 오프라인 테스트 가능)
# (패턴, 법률용어들, 억제자) 3-튜플. 억제자가 함께 매칭되면 그 항목 무효 —
# "기계에 손이 잘렸다"(산재)가 해고로, "출장 나가라"(이동 지시)가 해고 통보로
# 오매핑되는 것을 막는다. abuse_guard _BENIGN_ACTOR와 같은 설계(분석 P2-5).
COLLOQUIAL_LEGAL_MAP: tuple[tuple[re.Pattern, tuple[str, ...], re.Pattern | None], ...] = (
    (re.compile(r"잘렸|짤렸|…"), ("부당해고", "해고예고수당"), _BODY_CONTEXT),
    (re.compile(r"나오지\s*말|나가라(?:고|네|는|니)|…"), ("부당해고", "해고 통보"), _MOVE_CONTEXT),
    (re.compile(r"퉁치|퉁쳐"), ("임금 상계 금지", "임금 전액 지급 원칙"), None),
    # '급여'는 고정폭 lookbehind로 실업·구직·휴직·요양급여를 제외 — 억제자로
    # 하면 "실업급여도 월급도 못 받았다" 복합 질의의 임금체불 매핑까지 죽는다.
    # ... 계열 7종·패턴 22건·고유 법률용어 33개 (해고·임금·괴롭힘·산재·4대보험·근로계약·비정규직)
)

def map_colloquial_terms(text: str, max_terms: int = 6) -> list[str]:
    """매칭된 법률용어(중복 제거, 최대 max_terms). 매칭 없으면 [].
    진입부에서 NFC 정규화 — guard_ctx=None 호출부(CLI·fixture)는 abuse_guard의
    정규화를 거치지 않아 NFD 입력이면 [가-힣]가 조용히 0매칭한다(분석 P2-7).
    max_terms 6 중 검색 rule 쿼리에는 상위 4개만 실리고(빌드 함수 [:4]),
    5·6번째는 NLRC·GraphRAG 시드로 쓰인다."""
```

- **수록 기준**: 오매핑은 무관한 판례를 근거로 만들므로 **활용형이 명확한 고신뢰 패턴만** 넣는다(미변환의 비용 = Q&A 도달로 강등, 오변환의 비용 = 오답 근거 — 비대칭이므로 보수 방향). 항목마다 근거 주석(어느 법률 개념, 왜 고신뢰). 같은 어간이 다른 쟁점과 어휘를 공유하면 억제자를 단다.
- 배선(`pipeline.py`, RAG 블록 진입부):

```python
if analysis is None:
    colloquial_terms = map_colloquial_terms(query)
    if colloquial_terms:
        logger.info("구어사전 발동: %s", colloquial_terms)   # 계측 — Vercel 로그 검색 키
    prec_queries = [" ".join(colloquial_terms[:4])] if colloquial_terms else []
```

- 원문은 **대체하지 않는다** — `_merge_search_queries(fallback=query[:80])` 경로 유지(Dense의 구어-Q&A 매칭 보존). 사전 쿼리는 `rule_based` 슬롯으로 병기.
- 정상 경로(`analysis` 존재)에서는 발동하지 않는다 — LLM 변환(실측 8/8)이 우선, 이중 발동은 쿼리 슬롯 낭비.

### 2.3 하지 않는 것

- 사전을 정상 경로 보강에 쓰지 않는다(LLM이 더 정확 — 실측 8/8).
- BM25 인덱스/토크나이저는 건드리지 않는다.

---

## 3. C2 — 법률근거 승격 (`rag.py`)

### 3.1 구조: 기존 해설서 승격의 공용화

`_ensure_textbook_presence`(rag.py)를 일반화한 `_ensure_source_presence(selected, ranked, top_n, is_target, label)`를 만들고, 해설서·법률근거 두 승격이 이를 공유한다(`selected` 선행 인자는 원안 4인자에서 확장 — 2차 승격이 1차 승격 반영분을 봐야 I-7/I-8이 성립한다). 불변식 번호는 **선행 사이클(textbook-retrieval-balance)의 체계를 따른다** — 코드 주석과 이 표가 같은 번호를 써야 한다:

| 불변식 | 내용 |
|--------|------|
| I-1 교체 | 추가가 아니라 교체 — 총 건수 불변, G4/G4-T 상한 무접촉 |
| I-3 랭크 창 | 후보는 전체 랭킹 `top_n×2` 이내(점수 임계값 금지 — cosine/BM25 혼재) |
| I-4 소수 보호 | victim은 same source_type ≥ 2인 최하위(`_pick_swap_victim`) |
| I-5 순서 | 승격 → `format_pinecone_hits`(가드) — `rerank_results._finalize` 내부라 우회 불가 |
| I-6 최소 크기 | `len(selected) < 2`면 미발동 |

### 3.2 법률근거 승격 정의

- **대상(is_target)**: `source_type ∈ {precedent, interpretation, regulation}` — **textbook은 절대 포함하지 않는다**(해설서 노출 증가는 저작권 재검토 대상, §6).
- **발동 조건**: `selected`에 대상 소스 0건 && 랭크 창에 존재.
- **킬스위치**: `LEGAL_PROMOTE=off` (`TEXTBOOK_PROMOTE`와 동일한 재배포-반영 의미론).
- **적용 순서**: 해설서 승격(기존) → 법률근거 승격(신규). 순서는 기존 회귀(T23) 안정성 기준으로 고정.
  - ⚠️ **"대상 집합이 배타적이라 앞 승격이 뒤 발동 조건을 바꾸지 않는다"는 원안 단정은 반증됐다**(분석 P1-3) — 대상 집합은 배타적이지만 **victim 집합이 배타적이 아니다**. 해설서 승격의 I-4 폴백이 selected 내 유일한 판례를 victim 삼으면 legal 승격의 발동 조건이 새로 생겨, rerank 상위 판례가 랭크 창의 하위 판례로 되메워지는 강등 순환이 생긴다(총량 불변이라 메트릭에 안 잡힘). 해소는 I-9.

### 3.3 동시 발동 시 상호 잠식 방지 (신규 불변식 3종)

top_n이 전부 qa/counsel이면 두 승격이 모두 발동한다(top_n=3에서 교체 2건). 추가 규칙:

- **I-7 승격분 보호**: `_pick_swap_victim`은 `promoted` 마커가 있는 항목을 victim 후보에서 제외한다 — 뒤 승격이 앞 승격분을 잡아먹으면 순서가 결과를 바꾸는 비결정 구조가 된다.
- **I-8 원본 잔존**: 교체 후 비승격 원본이 1건 미만이 되면 미발동 — `len(selected)=2`에서 두 승격이 연쇄하면 원본 0건(100% 승격 컨텍스트)이 되는 것을 막는다. 판정: victim 후보(비promoted) < 2면 skip.
- **I-9 다양성 클래스 보호**: 다양성 클래스(해설서·법률근거)의 selected 내 **마지막 1건**은 I-4 폴백에서도 victim이 되지 않는다 — §3.2의 강등 순환 차단. 자연 유입 해설서를 legal 승격이 지우는 역방향도 같은 규칙이 막는다. 판정 술어(`_diversity_class_of`)는 두 승격의 대상 집합과 정확히 같은 정의를 공유해야 한다. 회귀 T24-b7/b8.

### 3.4 promoted 마커

기존 `promoted=True`(bool)를 `promoted="textbook" | "legal"`(str)로 바꾼다 — eval·로그가 두 승격을 구분해 계측해야 발동률을 따로 볼 수 있다. 기존 소비자는 truthy 체크(`h.get("promoted")`)라 호환되지만, **T23 중 `promoted is True` 동일성 단언이 있으면 함께 갱신**한다(Do 단계 확인 항목). `eval_retrieval.py`는 truthy라 무수정 호환.

---

## 4. C3 — 프롬프트 예시 확장 + 회귀 fixture

### 4.1 프롬프트 (`app/templates/prompts.py`)

- 변환 지시 두 곳(188행 precedent_keywords 예시, 287-288행 일상어 변환)에 계열별 예시를 1줄씩 추가 — 현행 해고 편중 → 임금·괴롭힘·산재·4대보험 추가:
  - `"월급이랑 퉁치자" → ['임금 상계 금지', '임금 전액 지급 원칙']`
  - `"계속 갈구고 따돌려요" → ['직장 내 괴롭힘', '괴롭힘 신고']`
  - `"일하다 다쳤는데 공상 처리하재요" → ['산재보상', '요양급여', '공상 처리']`
  - `"4대보험을 안 들어줬어요" → ['4대보험 가입의무', '고용보험 미가입']`
- 토큰 증가 ~4줄 — 의도분석 12s 예산 대비 무시 가능(Plan §5).

### 4.2 회귀 fixture

- `data/eval_colloquial_queries.json`: 계열 6종 × 2~3건 = 16건. 필드 `{id, category, query, expect_terms[]}` — `expect_terms`는 "추출 키워드에 이 개념 중 하나 이상 포함" 판정용(정확 일치 강제 금지 — LLM 표현 흔들림 허용).
- `eval_colloquial.py`(루트, `eval_retrieval.py`와 같은 수동 실행 관례): **3층 측정** — [1] 의도분석 LLM 변환, [2] 정적 사전(`--dict-only`, API 키 불요 — 오프라인), [3] 폴백/정상 검색 A/B(법률 코퍼스 도달). CI 제외([3]은 API 키 필요). [3a] 폴백 재현은 파이프라인의 합성 주입 구성(사전 rule 쿼리 + 원문 병기)과 일치해야 한다 — 어긋나면 기준선이 프로덕션이 달성 못 하는 수치가 된다(분석 P2-8).

---

## 5. 테스트 계획

| 테스트 | 파일 | 종류 |
|--------|------|------|
| 사전 매핑 정확성(각 항목 양성 1·음성 1) + 비매칭 시 빈 리스트 | `test_offline_units.py` | 오프라인 CI |
| 사전이 정상 경로에서 미발동(analysis 존재 시) | `test_offline_units.py` | 오프라인 CI |
| T24a 법률근거 승격 발동/미발동/랭크 창/킬스위치 (T23 미러) | `test_precedent_ingest.py` | 오프라인 CI |
| T24b 동시 발동: I-7 승격분 보호, I-8 원본 잔존 | `test_precedent_ingest.py` | 오프라인 CI |
| T24c 승격 결과가 가드(G4/G4-T) 통과 + textbook 미포함 | `test_precedent_ingest.py` | 오프라인 CI |
| 프롬프트 변경 후 스코프 게이트 무회귀(공격 차단율·오차단 0) | `test_abuse_guard.py` | 오프라인 CI |
| 폴백/정상 도달률 (성공 지표 대조) | `eval_colloquial.py` | 수동 |
| 해설서 승격 기준선 무회귀 | `eval_retrieval.py` | 수동 |

## 6. 저작권·가드 영향 검토

- 법률근거 승격의 대상은 판례·행정해석·훈령예규 — **공공 저작물**(저작권법 제7조 비보호)이라 노출 제약이 없다.
- 해설서 노출 변화 없음: ① textbook은 승격 대상이 아니고, ② 교체라 총량 불변으로 G4(권당 3)/G4-T(총량 6) 무접촉, ③ Cohere 전송(전체 랭킹)·Self-RAG 흐름 불변. **Plan 비목표의 `top_k`/`rerank_top_n` 상향과 이 설계는 무관하다** — 그쪽은 여전히 저작권 재검토 대상으로 남는다.
- G1a로 의도분석 실패 시에도 해설서가 컨텍스트에 실릴 수 있게 되나, 이는 정상 경로와 동일한 가드 체인(G4/G4-T → G1~G3 프롬프트 접미 → G6 게시판 제외)을 지나므로 신규 노출 경로가 아니다. `used_textbook` 판정은 `uses_textbook()` 공용 함수라 폴백 경로에서도 동일 적용됨을 T24c에서 확인.

## 7. 롤백

- C1: `analysis is None` 분기 내 신규 코드 — 분기 제거로 원상복구, 데이터 마이그레이션 없음.
- C2: `LEGAL_PROMOTE=off`(무배포) 또는 헬퍼 호출 제거(배포).
- C3: 프롬프트 예시 줄 삭제. fixture는 데이터 파일이라 잔존 무해.
