# textbook-retrieval-balance Design

> Plan: `docs/01-plan/features/textbook-retrieval-balance.plan.md` (2026-08-19)
> 결정 승계: 목표 = **출처 다양성 보장**(rerank 탈락 3건 해소), 저작권 노출 = **현행 상한(G4 3·G4-T 6) 불변**, 검색 미도달 4건은 **범위 밖**.

## 1. 개요

### 1.1 목표

rerank 입력(pool)에 해설서가 있는데 결과 top_n에 0건인 경우, **pool의 최상위 해설서 1건을 결과 최하위 중복-출처 1건과 교체**한다. 총 건수 불변 · 승격 최대 1건 · 가드(G4/G4-T)는 그대로 뒤에서 적용된다.

### 1.2 비목표

- 검색 단계 확대(SIMPLE `top_k` 상향, 소스별 쿼터 검색) — 외부 전송량이 늘어 저작권 검토 범위가 달라짐. 별도 사이클.
- `rerank_top_n`·G4·G4-T 수치 변경 — 없음.
- qa·판례 랭킹 하향 — qa 상위 결과는 실측상 유효했다.

## 2. 현행 동작 확정 (코드 사실)

설계의 전제가 되는 사실을 코드에서 확정했다. **Plan §1.3의 전제 하나를 정정한다.**

### 2.1 절단 지점은 `rerank_results` 내부 3곳뿐이다

```text
rerank_results(query, hits, cohere_api_key, top_n)   # app/core/rag.py:243
├─ exit-A hits 없음/키 없음  → return hits[:top_n]      # 절단
├─ exit-B Cohere 성공        → top_n건 재구성 반환        # 절단
└─ exit-C 예외               → return hits[:top_n]      # 절단
```

- 호출부는 `pipeline.py:1622`(일반)·`1642`(wider) **두 곳뿐**이고, 둘 다 `config.cohere_api_key`가 있을 때만 호출한다.
- **정정(Plan FR-4)**: "Cohere 미설정 폴백에서도 동작"의 실제 의미 — 파이프라인 무키 경로는 rerank를 **호출하지 않아 절단이 없고**, hybrid 결과 전체(top_k 8~20)가 그대로 `format_pinecone_hits`로 간다. 해설서가 pool에 있으면 이미 포함되므로 **승격이 필요 없다**. 승격이 필요한 무키 경로는 `rerank_results`를 키 없이 직접 부르는 소비자(평가 스크립트·향후 호출부)와 Cohere 장애 시 exit-C다. 세 exit 모두에 승격을 걸면 이 구분을 호출부가 알 필요가 없다.

### 2.2 Cohere 호출은 현재 top_n만 받아온다

`co.rerank(..., top_n=min(top_n, len(hits)))` — 결과 밖 문서의 순위·점수를 모른다. 승격 후보(pool 내 최상위 해설서)를 알려면 **전체 랭킹**이 필요하다. Cohere 과금은 search 단위(쿼리+문서셋)라 `top_n`을 문서 전수로 올려도 **비용 불변**이다.

### 2.3 `score` 필드는 스케일이 섞여 있어 임계값 기준이 될 수 없다

hits의 `score`는 Dense(cosine 0.5~0.65)와 BM25(10~30)가 혼재한다(실측). `rerank_score`는 exit-B에만 붙는다. **절대 점수 하한은 세 exit에서 일관되게 정의할 수 없다** → D-3은 랭크 기준으로 푼다.

### 2.4 승격 이후 단계

- COMPLEX: Self-RAG(`filter_by_relevance`, Haiku)가 승격 **이후** 관련성 심사 — 무관한 승격 청크를 걸러내는 품질 백스톱이 이미 있다.
- 전 경로: `format_pinecone_hits` 진입부에서 G4→G4-T 차감 — 승격은 0→1건이라 상한(3/6)을 넘길 수 없다.

### 2.5 기존 상한 회귀 테스트 위치

`test_precedent_ingest.py` T19(G4)·T22-a~c(G4-T). 신규 테스트는 같은 파일 T23 시리즈로 둔다(동일 import 관례, CI 오프라인 실행).

## 3. 설계 결정 (Plan D-1~D-5)

| ID | 쟁점 | 결정 | 근거 |
|----|------|------|------|
| **D-1** | 해설서 전용 vs 소수 출처 일반 규칙 | **해설서 전용** | 실측된 문제가 해설서뿐(최종 46건 중 precedent 7건은 자력 생존). 일반화하면 qa 슬롯이 다건 밀려 품질 위험. 판정을 `_book_id_of()` 재사용으로 좁혀 두면 향후 일반화 여지는 남는다 |
| **D-2** | 교체 대상(victim) | **아래에서부터 스캔해 처음 만나는 중복-출처 hit**(selected 내 같은 `source_type` ≥ 2). 없으면 최하위 | 단일 출처(예: precedent 1건)를 지키면서 다양성 목적에 부합. 최다-출처 최하위 방식보다 순위 교란이 작다 |
| **D-3** | 승격 임계 | 점수 하한 대신 **랭크 창** — 후보는 전체 랭킹의 `top_n ~ 2×top_n` 구간에서만 | §2.3(점수 스케일 혼재). 랭크는 세 exit 모두에서 동일하게 정의됨. COMPLEX는 Self-RAG가 2차 백스톱(§2.4) |
| **D-4** | 배치 | **`rerank_results` 내부**, 세 exit 공통 적용. Cohere 호출을 전체 랭킹으로 변경. `ensure_textbook: bool = True` 파라미터 + env `TEXTBOOK_PROMOTE=off` 킬스위치 | 호출부 2곳(일반·wider)+향후 호출부가 자동 커버. 파라미터는 평가 A/B용, env는 무배포 롤백 관례(`ANSWER_PROVIDER`와 동일 의미론) |
| **D-5** | 평가셋 커밋 | **커밋** — `data/eval_retrieval_queries.json`(합성 질의 24건 + freeze된 분해 쿼리). 실행 스크립트 `eval_retrieval.py`는 API 키 필요 → CI 밖, `check_schema.py`처럼 수동 실행 항목. 결과 JSON은 커밋하지 않고 analysis 문서에 표로 기록 | 질의는 손으로 쓴 합성문이라 개인정보 없음. fixture 커밋으로 재현성 확보 |

## 4. 상세 설계

### 4.1 `_ensure_textbook_presence()` — 순수 함수 (`app/core/rag.py`)

```python
TEXTBOOK_PROMOTE_WINDOW_FACTOR = 2   # 후보 탐색 창: ranked[top_n : 2*top_n]

def _ensure_textbook_presence(ranked: list[dict], top_n: int) -> list[dict]:
    """rerank 결과에 해설서가 0건이면 pool의 최상위 해설서 1건을 승격.

    다양성 보장이지 저작권 가드가 아니다 — 가드(G4/G4-T)는 이 함수 결과에
    format_pinecone_hits가 그대로 적용한다(승격 → 가드 순서 불변).
    """
    selected = ranked[:top_n]
    if len(selected) < 2:                       # I-6: 1건뿐이면 교체가 100% 치환
        return selected
    if any(_book_id_of(h) for h in selected):   # I-2: 이미 있으면 무변경
        return selected

    window = ranked[top_n : top_n * TEXTBOOK_PROMOTE_WINDOW_FACTOR]
    candidate = next((h for h in window if _book_id_of(h)), None)
    if candidate is None:                       # I-3: 창 밖 후보는 무시
        return selected

    victim_idx = _pick_swap_victim(selected)
    # 사본에 promoted=True 마킹 — 계측의 구조적 계약(§4.3). 사본인 이유:
    # exit-A/C에서 candidate는 호출자 hits의 원본이라 제자리 변이가 샌다.
    promoted = (selected[:victim_idx] + selected[victim_idx + 1:]
                + [dict(candidate, promoted=True)])
    logger.info("해설서 다양성 승격: %s (교체: %s, top_n=%d)",
                candidate.get("id"), selected[victim_idx].get("source_type"), top_n)
    return promoted


def _pick_swap_victim(selected: list[dict]) -> int:
    """아래에서부터, 같은 source_type이 2건 이상인 첫 hit. 없으면 최하위."""
    counts = Counter(h.get("source_type") for h in selected)
    for i in reversed(range(len(selected))):
        if counts[selected[i].get("source_type")] >= 2:
            return i
    return len(selected) - 1
```

**불변식** (T23이 고정):

| ID | 불변식 |
|----|--------|
| I-1 | 출력 길이 = `min(top_n, len(ranked))` — 승격은 **교체**이지 추가가 아니다 |
| I-2 | selected에 해설서 ≥ 1이면 입력 그대로(원소 동일) 반환 |
| I-3 | 후보는 전체 랭킹 `2×top_n` 이내에서만 — 창 밖 해설서를 끌어올리지 않는다 |
| I-4 | 중복-출처가 존재하는 한 단일-출처 hit은 victim이 되지 않는다 |
| I-5 | 승격은 G4·G4-T **이전**(rerank 내부 ⊂ `format_pinecone_hits` 이전) — 승격이 상한을 우회하는 경로는 구조적으로 없다. 또한 승격은 0→1건이므로 비해설서가 `top_n-1 ≥ 1`건 남는다(승격이 만드는 100% 해설서 컨텍스트는 없음) |
| I-6 | `len(selected) < 2`면 승격하지 않는다 |

승격된 후보는 **말미에 붙인다** — 재랭커 기준 selected 전원보다 약한 문서이므로 순위를 속이지 않는다. victim 제거 외 기존 순서는 불변.

예외 처리를 두지 않는다(순수 리스트 연산). NFR-2(fail-open)는 `rerank_results`의 기존 except가 담당한다.

### 4.2 `rerank_results()` 변경

```python
def rerank_results(query, hits, cohere_api_key, top_n=RERANK_TOP_N,
                   ensure_textbook: bool = True) -> list[dict]:
    def _finalize(ranked):
        if ensure_textbook and _textbook_promote_enabled():
            return _ensure_textbook_presence(ranked, top_n)
        return ranked[:top_n]

    if not hits or not cohere_api_key:
        return _finalize(hits)                       # exit-A: RRF 순서가 랭킹 대행
    try:
        ...
        result = co.rerank(..., top_n=len(documents))  # ★ 전체 랭킹 요청 (비용 불변, §2.2)
        ranked = [... hits[item.index].copy() + rerank_score ...]  # 전 문서에 점수 부착
        return _finalize(ranked)                     # exit-B
    except Exception as e:
        logger.warning(...)
        return _finalize(hits)                       # exit-C: RRF 순서 대행
```

- **전체 랭킹 요청**이 이 설계의 유일한 외부 호출 변경이다. 문서 수는 그대로라 과금·전송량 불변, 응답 크기만 소폭 증가.
- `_textbook_promote_enabled()`: `os.getenv("TEXTBOOK_PROMOTE", "on").strip().lower() != "off"`. Vercel에서 env 변경은 재배포 시 반영 — `ANSWER_PROVIDER`와 같은 "무배포(코드 변경 없는) 롤백" 의미론.
- `ensure_textbook=False`는 평가 스크립트의 기준선(A/B) 측정 전용. 파이프라인은 기본값을 쓴다(호출부 무변경).

### 4.3 계측 (FR-5)

- **구조적 마커가 1차 계약이다**: 승격 hit 사본에 `promoted: True`를 마킹하고, 평가 스크립트는 반환값에서 이 키로 발동을 센다. ~~로그 캡처~~로 설계했다가 /simplify에서 정정 — 로그 문자열·레벨 2중 암묵 계약은 문구 수정만으로 계측이 조용히 0이 되고, 그 0은 "승격이 효과 없음"이라는 그럴듯한 오답으로 읽힌다(로거 기본 레벨 WARNING 때문에 실제로 한 번 발생). 회귀는 T23-a4(마커 존재)·a5(원본 비변이).
- 운영 관찰: `logger.info("해설서 다양성 승격: ...")` — G4 로그와 같은 관례. Vercel 로그에서 `다양성 승격` 검색으로 빈도 확인(로그는 보조 채널이지 계측 계약이 아니다).
- 대화 메타데이터에는 넣지 않는다 — 승격 여부는 답변 내용이 아니라 근거 구성의 문제고, 게시판 제외 판정(`used_textbook`)은 기존대로 `format_pinecone_hits` 결과 기준이라 승격분도 자동 포함된다(§9 리스크 참조).

## 5. 평가 하네스 (FR-1)

### 5.1 구성

| 산출물 | 경로 | 커밋 |
|--------|------|:---:|
| 질의 fixture | `data/eval_retrieval_queries.json` | O |
| 실행 스크립트 | `eval_retrieval.py` (저장소 루트) | O |
| 측정 결과 | analysis 문서에 표로 기록 (`--out` JSON은 로컬 전용) | X |

### 5.2 fixture 스키마

```json
{
  "frozen_at": "2026-08-19",
  "note": "decomposed는 --freeze가 1회 생성. 재생성하면 기준선과 비교 불가 — 갱신 시 기준선 재측정 필수.",
  "queries": [
    {
      "id": "q01",
      "topic": "휴게시간 일괄 부여",
      "expect": "new",
      "query": "휴게시간을 근로시간 중간에 주지 않고 퇴근 시각에 몰아서 부여해도 되나요?",
      "decomposed": ["휴게시간 근로시간 도중 부여 원칙", "휴게시간 몰아서 부여 가능 여부"]
    }
  ]
}
```

`expect` 태그: `new`(실무테마 36~60 — part4/5) / `old`(1~35) / `wage`(juhae3·win 임금 영역) / `weak`(해설서가 약한 주제 — 산재 장해등급·실업급여 절차·4대보험 정산 등). `weak` 4건은 **랭크 창이 무관 승격을 막는지 보는 음성 대조군**이다 — 승격 발동 자체를 금지하는 단언은 두지 않는다(pool에 정당하게 올라온 해설서면 승격이 맞다). 총 **24건**(new 10 / old 6 / wage 4 / weak 4).

### 5.3 실행 모드

```bash
python3 eval_retrieval.py --freeze        # decompose_query 1회 호출 → fixture에 고정 (ANTHROPIC 키)
python3 eval_retrieval.py                 # 기준선·승격 동시 측정 (1 pass A/B)
python3 eval_retrieval.py --out r.json    # 결과 JSON 저장 (로컬)
```

재현 경로: fixture의 `[query] + decomposed` → `search_hybrid` → **전체 랭킹 1회**(`rerank_results(top_n=len(hits), ensure_textbook=False)`) → 같은 pool에서 기준선(`ranked[:top_n]`)과 승격(`_ensure_textbook_presence(ranked, top_n)`)을 **한 pass에 파생** → 각각 `format_pinecone_hits`. `classify_complexity`는 규칙 기반이라 실행 시 계산(결정적).

> ~~`--no-promote` 별도 실행~~으로 설계했다가 /simplify에서 정정 — 분기점이 rerank 이후의 결정적 인프로세스 단계라, 2회 실행은 외부 API 비용이 2배이고 두 실행이 서로 다른 pool을 샘플링하는 잡음까지 만든다. 같은 pool 파생은 비용 절반에 그 잡음이 원리적으로 없다. (2회 실행 구조는 "구현 전 기준선 선측정"을 같은 스크립트로 하려던 과도기 요구의 산물이었고, 그 요구는 구현 완료로 소멸했다.)

**의도적 근사 4가지**(문서화로 고정 — 이 목록 밖의 파이프라인 복제는 드리프트다):
- `analyze_intent` 기반 rule 쿼리(`build_precedent_queries`)는 재현하지 않는다 — LLM 의도분석이 비결정적이고, 측정 대상(rerank 절단)에 닿는 경로는 동일하다.
- Self-RAG는 돌리지 않는다 — Haiku 판정이 비결정적. 승격→Self-RAG 상호작용은 프리뷰 실측(§8 완료 조건)으로 본다.
- `classify_complexity`를 질의 원문만으로 호출한다 — 프로덕션은 의도분석의 `relevant_laws`·`calculation_types`를 함께 넘기므로 같은 질의가 다른 복잡도로 측정될 수 있다.
- Cohere 무키면 프로덕션은 rerank 호출 자체를 생략한다 — 무키 측정은 프로덕션이 타지 않는 경로이므로 참고치로만.

쿼리 병합 절단은 `query_decomposer.QUERY_MERGE_HEADROOM`을 pipeline과 공유한다 — `+2` 리터럴이 두 곳에 살면 pipeline 조정 시 고정 평가셋의 기준선이 조용히 어긋난다.

**결정성 한계**: OpenAI 임베딩·Pinecone ANN·Cohere는 준결정적이다. 판정은 개별 질의가 아니라 **집계 지표**(도달률·발동률)로 한다. ±1건 수준의 흔들림은 회귀가 아니다.

### 5.4 지표 정의

| 지표 | 정의 | 기대 |
|------|------|------|
| **도달률** | 최종 컨텍스트에 해설서 ≥ 1건인 질의 수 ÷ **rerank pool에 해설서가 있던** 질의 수 | 기준선(실측 예정) → 승격 ON에서 창 내 후보 존재 시 100% |
| 발동률 | 승격 발동 질의 수 ÷ 전체 (건수·% 병기) | 기록용 (게시판 제외 증가의 근사치, §9) |
| 출처 분포 | 최종 컨텍스트 source_type 합계 | qa 일변도 완화 확인, 총 건수 불변 확인 |
| 상한 발동 | 가드 차감이 발생한 **질의 수**(`가드 전 해설서 수 > 가드 후`) | 승격 전후 동일. ~~로그 건수~~로 정의했다가 구현 시 정정 — 반환값 비교가 로그 파싱보다 견고하고, 계측 버그(로거 레벨) 실측 후 로그 의존을 지표에서 뺐다 |

## 6. 테스트 계획 (FR-4) — `test_precedent_ingest.py` T23

전부 오프라인(순수 함수 + 합성 hit dict). CI 실행.

| ID | 검증 | 고정하는 불변식 |
|----|------|:---:|
| T23-a | 해설서 0건 + 창 내 후보 → 승격, 길이 불변, 해설서 정확히 1건 | I-1 |
| T23-b | 후보가 창 밖(rank ≥ 2×top_n) → 무승격 | I-3 |
| T23-c | selected에 해설서 이미 존재 → 입력 원소 그대로 | I-2 |
| T23-d | pool 전체에 해설서 없음 → 무승격 | — |
| T23-e | `[qa,qa,precedent,qa,counsel]` → victim은 idx3의 qa (counsel·precedent 생존) | I-4 |
| T23-f | 전원 단일 출처 → 최하위 제거 | I-4 폴백 |
| T23-g | `top_n=1` → 무승격 | I-6 |
| T23-h | `rerank_results(key="")` 직접 호출(exit-A)에서 승격 동작 | §2.1 |
| T23-i | 승격 결과 → `format_pinecone_hits` 통과 시 G4/G4-T 정상 + 비해설서 ≥ 1 유지 | I-5 |
| T23-j | env `TEXTBOOK_PROMOTE=off` → 무승격 | D-4 |
| T23-k | `ensure_textbook=False` → 무승격 (기준선 경로) | D-4 |

기존 스위트 5종(`test_wage_golden` / `test_pipeline_wiring` / `test_offline_units` / `test_abuse_guard` / `test_llm_fallback`) + `test_precedent_ingest` 전체 통과가 완료 조건.

## 7. 문서 갱신 (NFR-3)

| 대상 | 내용 |
|------|------|
| `CLAUDE.md` 해설서 항목 | 승격 규칙 1불릿: 최대 1건 교체·창 2×top_n·승격→가드 순서 불변(I-5)·`TEXTBOOK_PROMOTE=off` 킬스위치·회귀 T23. G4-T 절의 "비해설서 최소 1건 보장 없음" 서술에 "역방향(해설서 최소 1건)은 다양성 승격이 담당" 상호참조 |
| `rag.py::MAX_TEXTBOOK_CHUNKS` docstring 말미 | "그런 보장이 필요하면 별도 설계 항목" → 승격과의 관계 1줄 추가 |
| `.env.example` | `TEXTBOOK_PROMOTE` 주석 1줄 (optional) |
| `eval_retrieval.py` docstring | freeze 갱신 시 기준선 재측정 필수 경고 |

## 8. 구현 순서 (완료 조건 매핑)

| 순서 | 작업 | Plan 완료 조건 |
|:---:|------|------|
| 1 | fixture 질의 24건 작성 + `eval_retrieval.py` + `--freeze`로 분해 고정 | — |
| 2 | **기준선 측정** → 수치 기록 *(당시엔 `--no-promote` 별도 실행 — /simplify의 1 pass 통합으로 플래그는 제거됐고, 현재는 단일 실행이 기준선·승격을 함께 파생한다. §5.3)* | 조건 1 |
| 3 | `rag.py` 구현(§4.1~4.3) | — |
| 4 | T23 작성·통과 + 기존 스위트 전체 | 조건 3·4·5 |
| 5 | 승격 ON 재측정 → 도달률 상승·총 건수 불변·상한 동작 동일 확인 | 조건 2·4 |
| 6 | 문서 갱신(§7) | 조건 6 |
| 7 | 프리뷰 배포 → 실질의 1건으로 출처 카드 「노동법 해설서」 확인 | 조건 7 |

## 9. 리스크·트레이드오프

| 리스크 | 심각도 | 대응 |
|--------|:---:|------|
| **승격 → `used_textbook` → G6 게시판 제외 증가.** 해설서 근거 답변은 공개 게시판에서 빠지므로, 승격 발동만큼 게시판 유입이 준다 | 중 | 설계상 감수(저작권 우선). 발동률을 기록해 규모를 수치로 확인(§5.4). 게시판 유입이 유의미하게 줄면 창 축소(2×→1.5×)가 완화 수단 |
| 승격 청크가 질의와 무관 | 중 | 랭크 창(I-3) + COMPLEX는 Self-RAG 2차 심사(§2.4). weak 대조군 4건으로 관측 |
| Self-RAG가 승격 청크를 걸러 COMPLEX 최종이 다시 0건 | 낮 | **허용** — 품질 판정이 다양성보다 우선. 도달률 정의가 rerank 단계 기준임을 명시 |
| Cohere 전체 랭킹 요청의 응답 지연 증가 | 낮 | 문서 수 불변이라 추론량 동일. 응답 직렬화만 증가 — 프리뷰에서 체감 확인 |
| env 킬스위치가 Vercel에서 재배포 전 미반영 | 낮 | `ANSWER_PROVIDER`와 동일 의미론임을 CLAUDE.md에 명시 |
| fixture `--freeze` 재실행으로 기준선 무효화 | 중 | fixture `note`와 스크립트 docstring에 경고 고정(§5.2·§7) |

## 10. 롤백

1. **운영**: `TEXTBOOK_PROMOTE=off` 설정 후 재배포 — 코드 변경 없이 승격만 비활성(exit 동작은 기존과 동일한 `ranked[:top_n]`).
2. **코드**: `_finalize` 도입부만 되돌리면 됨 — 데이터·스키마·코퍼스 변경이 없는 순수 코드 기능이라 벡터 롤백류 절차 불요.
