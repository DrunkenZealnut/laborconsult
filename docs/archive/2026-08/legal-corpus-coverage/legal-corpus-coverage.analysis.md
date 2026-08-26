# legal-corpus-coverage 분석 (Check)

> Plan: `docs/01-plan/features/legal-corpus-coverage.plan.md`
> Design: `docs/02-design/features/legal-corpus-coverage.design.md`
> 분석일: 2026-08-23 / 방식: **이중 리뷰**(gap-detector + 설계 무관 경로 리뷰) + 프로덕션 경로 실측

## 1. 결론

**Match Rate 82%** (gap-detector, 70항목 대조). 90% 미달로 **Act 필요**.

지표는 목표를 전부 달성했으나, 그 달성을 **잘못된 조건으로 측정**하고 있었고(§2), 설계 문서가 구현보다 낡았으며(§3), 설계가 예측하지 못한 경로 결함이 다수 발견됐다(§4). 이 사이클은 CLAUDE.md의 경고 — *"Match Rate가 90%를 넘어도 그대로 배포하지 말 것"* — 를 한 번 더 실증했다: 갭 분석이 놓친 High 4건을 경로 리뷰가 찾았다.

---

## 2. 지표 재측정 — 측정 조건이 틀렸다

Do 단계에서 `eval_corpus_mix.py`로 잰 값은 **원문 쿼리 1개**를 넘긴 결과였다. 프로덕션은 의도분석이 만든 분해·규칙 쿼리 목록을 쓴다(`pipeline.py:1675` `_merge_search_queries`). 실제 `queries[0]`은 원문이 아니라 규칙 생성 키워드다 — 실측: `"연장근로수당 권고사직 강요 부당해고 임금체불"`.

`process_question`을 그대로 태워 재측정했다(12주제, `format_pinecone_hits` 캡처):

| 지표 | 기준선 | Design 목표 | eval(원문 1개) | **프로덕션 경로** | 판정 |
|---|---:|---:|---:|---:|:---:|
| 공공저작물 | 2 | ≥ 15 | 16 | **21** | ✅ |
| 법률 근거 도달 | 2/12 | ≥ 11/12 | 12/12 | **12/12** | ✅ |
| 상담 비중 | 89% | ≤ 62% | 64% | **58%** | ✅ |
| 저작물 비중 | 95% | ≤ 70% | 64% | **65%** | ✅ |
| 해설서 건수 | 3 | 3 ± 1 (증가 금지) | 0 | **4** | ⚠️ +1 |
| T3 `cases` 발신 | — | — | — | **11/12 질의** | ✅ |

**프로덕션 조건이 오히려 더 좋다**(공공 16→21, 상담 64%→58%). 규칙 쿼리가 법률 용어를 담고 있어 공공 조회에 유리한 것으로 보인다. 목표 미달이 아니라 초과 달성이다.

다만 **측정 도구가 프로덕션을 재지 않는다는 사실 자체가 결함**이다(A-4). 그리고 이 측정에서도 `fmt호출 1회`가 12/12 — **Self-RAG wider 경로는 한 번도 재지 못했다**(A-2·A-3이 그 구간의 결함이다).

해설서 4건은 기준선 3의 +1로 "3±1" 범위 안이지만, T1-b의 취지가 "늘리지 않는다"이므로 관찰 대상으로 남긴다.

---

## 3. 설계 문서 갭 (gap-detector, Match Rate 82%)

구현이 설계보다 **앞서 있다**. 구현 중 실측으로 3회 방향을 바꿨는데 CLAUDE.md에는 반영하고 Design 문서는 갱신하지 않았다.

| # | 심각도 | 갭 | 근거 |
|---|:---:|---|---|
| D-1 | High | **Design §2에 T1 2단(`_ensure_public_quota`)이 통째로 없다** — 실측상 효과의 절반을 지는 계층("pool 3건 → 최종 0건") | `rag.py:523-569` / design §2 |
| D-2 | High | **Design §2.1·§7이 수술 지점을 `search_pinecone`으로 지목** — 실제는 `search_hybrid`. 설계를 근거로 되돌리면 효과가 1/3로 회귀 | design.md:59·202 vs `rag.py:359-388` |
| D-3 | Medium | §2.3의 "세 번째 future로 **병렬** 추가, 지연 증가 없음"이 사실과 다름 — 실제는 순차 호출 | design.md:84-86 vs `rag.py:384` |
| D-4 | Medium | §2.3에 `text`/`chunk_text` 이중 폴백 부재 — "이 폴백 없이는 쿼터를 넣어도 최종 0건"인 성립 전제 | `rag.py:77` / CLAUDE.md:302 |
| D-5 | Medium | §2.4의 "배분과 승격은 서로의 victim 규칙을 침범하지 않는다" 논거 무효 — 2단이 `rerank_results` 안으로 들어옴 | design.md:93 |
| D-6 | Low | 임계 0.75→0.45, 기록 키 `metadata.divergent`→`metadata.case_match.divergent`, 훈령 161→160, 상수명 등 미갱신 | design §4.2·§4.3·§5 |

**D-1·D-2는 Act에서 반드시 해소한다** — 설계 문서가 구현을 되돌리도록 유도하는 상태다.

---

## 4. 경로 리뷰 발견 — 설계가 예측하지 못한 것

gap-detector가 원리적으로 못 잡는 영역이다. **7건이 실제 코드 결함으로 확인됐다**(직접 재현 검증 완료).

### 🔴 High

| # | 결함 | 근거 | 실패 시나리오 |
|---|---|---|---|
| **A-1** | **`app/core/case_match.py` 미추적 → 배포 시 500 + 대화 유실** | `git status` `??`, `pipeline.py:2136`이 try/except 없이 import | CLAUDE.md 명시 규칙 위반. 상담이 실린 질문(사실상 전부)에서 답변 **직후** ImportError → 저장 단계 전이라 **대화가 저장되지 않는다.** `POST /api/chat`은 try/except가 없어 HTTP 500. 같은 클래스: `pinecone_upload_regulations.py`·`eval_corpus_mix.py`·`data/eval_corpus_mix.json`·`data/bm25_corpus.json.gz`(훈령 1,763건 미반영) |
| **A-2** | **Q6이 공개 게시판을 사실상 전면 중단시킨다** | `storage.py:259` + `pipeline.py:2196`. `uses_counsel`은 상담 1건만 있어도 True | 실측: 12주제 **전부** 상담 포함 → 신규 AI 대화의 ~100%가 게시판에서 제외된다. 설계 §3은 이를 해설서 G6와 "같은 메커니즘"으로 처리했으나 **도달 빈도가 다르다**(해설서 3~4건 vs 상담 35건). 예외도 로그도 없이 "요즘 질문이 안 올라오네"로만 보인다 |
| **A-3** | **Self-RAG wider에서 공공 쿼터가 20으로 폭증** | `POOL_PUBLIC_QUOTA`에 40 미등록 → 폴백 `max(2, top_k//2)`. wider는 `top_k=40`(`pipeline.py:1705`) | 등록값은 20~25%인데 폴백은 **50%**. pool 40건 중 20건이 주입 판례가 되고 상담은 2건만 남는다. wider는 Self-RAG를 재적용하지 않아 그대로 답변에 실린다. **이 구간은 한 번도 측정된 적이 없다** |
| **A-4** | **측정 도구가 프로덕션 조건을 재지 않는다** | `eval_corpus_mix.py:70`은 원문 1개, 프로덕션은 분해·규칙 쿼리 목록 | §2에서 재측정해 결론은 뒤집히지 않았으나(오히려 좋음), **Self-RAG·wider 구간은 여전히 미측정**이다. A-2·A-3이 그 구간에 있다 |

### 🟡 Medium

| # | 결함 | 근거 | 내용 |
|---|---|---|---|
| **A-5** | **Q4(`_cap_counsel_total`)가 사실상 무력** | `rag.py:888`이 `top_n` 없이 호출 → `limit = len(hits)-1` | 상담이 컨텍스트를 **100% 채울 때만** 1건 제거. 비상담이 하나라도 있으면 발동하지 않는다. 회귀 T26-i/i2/i3는 전부 `top_n=`을 명시해 호출 — **프로덕션이 쓰지 않는 형태를 검증**하고 있었다 |
| **A-6** | **Self-RAG가 2단 쿼터를 조용히 되돌린다** | 2단 승격분은 말미에 붙고(`rag.py:563`), `filter_by_relevance`는 그 뒤에 돈다(`pipeline.py:1700`) | rerank 하위인 승격분을 Haiku가 irrelevant로 버리면 재적용 지점이 없다. COMPLEX 전용이라 측정에 안 잡힌다. CLAUDE.md가 G4-T에 대해 기록한 "rerank 직후 표 ≠ format_pinecone_hits 입력"과 같은 클래스 |
| **A-7** | **킬스위치가 변경의 일부만 되돌린다** | `_pool_quota_enabled()`는 1·2단 쿼터만 끈다 | `text or chunk_text` 폴백(legacy `ctx_*` 9,088벡터 신규 투입)·Q4·`COUNSEL_CITATION_RULES`·Q6에는 스위치가 없다. "코드 변경 없이 되돌린다"(설계 §2.5)가 성립하지 않는다. 또 baseline이 폴백 적용 전인지 후인지 기록이 없어 **개선폭이 쿼터의 효과인지 폴백의 효과인지 분리되지 않는다** |
| **A-8** | **`cases` 이벤트의 상담 제목이 비식별화를 거치지 않는다** | `case_match.py:110` → `pipeline.py:2141` | `_anonymize()`는 게시판 응답에서만 호출된다. nodong.kr 상담 제목은 사용자 문장이라 회사명·이름이 들어갈 수 있다. `sources`도 같은 문제(선행 결함)지만 `cases`는 제목을 "유사 사례"로 **승격**시키고 `title[:120]` 절단조차 없다 |
| **A-9** | **8,000자 절단이 인용 화이트리스트와 어긋난다** | `pipeline.py:1841` `_cap(precedent_text, 8000)` | content 폴백으로 `ctx_*` 청크가 0자→900자를 채우게 되어 절단이 현실화됐다. 절단된 청크도 `meta_list`에 남아 **본문이 잘린 판례를 LLM이 인용하도록 유도**되고 환각 검증이 그것을 통과시킨다 |
| **A-10** | **공공·상담 집합이 각각 이중 선언** | `POOL_PUBLIC_SOURCES`(97) vs `LEGAL_PROMOTE_SOURCES`(420); `COUNSEL_SOURCES`(812) vs 리터럴 `("qa","counsel")`(175·558) | CLAUDE.md가 I-9에 대해 반복 경고한 실패 모드를 재현했다. 특히 상담은 같은 diff가 `is_counsel_source`를 "단일 출처"라 선언(`pipeline.py:198`)하고도 두 곳에서 리터럴을 쓴다. **총량 불변이라 어떤 메트릭에도 안 잡힌다** |

### 🔵 Low (선별)

- **A-11** `_ensure_public_quota`의 상담 하한이 1단과 불일치 — 1단 `<= MIN_COUNSEL_IN_POOL`(2 보장) vs 2단 `< 2`(1까지 허용). docstring은 "최소 2건"이라 주장한다(`rag.py:560·577`)
- **A-12** `$in`은 `set`/`frozenset`만 인식 — `list`를 넘기면 `{"$eq": [...]}`가 되어 **예외 없이 0건**(`rag.py:52-57`). 시그니처는 아직 `str | None`
- **A-13** `ensure_textbook=False`가 공공 쿼터 2단까지 함께 끈다 → `eval_retrieval.py`의 A/B가 두 기능을 동시에 끈 상태를 잰다
- **A-14** 절단 답변(`outcome.truncated`)에도 T3가 돌아 `divergent`가 기록된다 → 품질 신호 오염
- **A-15** `renderCases`가 `renderSources`와 같은 클래스를 쓰고 같은 상담이 "근거 자료"·"유사 사례"에 **중복 표시**된다 → T3 취지(근거 아님)를 흐린다
- **A-16** `LEGAL_POOL_QUOTA`·`CASE_MATCH_THRESHOLD`가 `.env.example`에 없다
- **A-17** BM25 76,983건 — 마지막 실측 안전선 66,307건(로드 9.0초, Vercel 1024MB)을 크게 넘었고 재측정 기록이 없다

---

## 5. 정상 확인 (고치지 말 것)

- `api/index.py` 무변경이 맞다 — `_apply_guard_filter`가 `PUBLIC_EXCLUDE_KEYS`를 순회해 `counsel`이 PostgREST 필터·Python 후처리·`dedupe_board.py` 검증 SQL에 **자동 반영**된다. 단일 출처 설계가 의도대로 작동한다.
- 가드 Q1~Q3 부착이 `if/else` 분기 **바깥**이라 두 답변 경로 공통 ✅. 부착 판정과 게시판 제외가 **동일 변수** `used_counsel` ✅ (T26-h가 구조적으로 고정).
- T5는 court 템플릿 4요소(NS 명시·ID 충돌 검사·zip 검증·`VectorLedger`)를 전부 갖췄고 적재 완료(160그룹/1,763벡터).
- 킬스위치가 1·2단 **양쪽**을 끈다 ✅ (범위는 A-7이 별개 문제).
- `cases` 이벤트는 구 프론트가 조용히 무시하고(unknown 타입 else 없음), HTML은 network-first라 캐시 문제 없음. `.sources` div는 말풍선 바깥이라 PDF·이메일 내보내기에 미포함 ✅.
- 회귀 T26 26건(설계 10건 대비) 전량 통과. "표식 없는 자연 유입 공공은 승격하지 않는다"(T26-a3) 등 설계에 없던 불변식도 고정.

---

## 6. Act 우선순위

**배포 차단 (커밋 전 필수)**
1. **A-1** — `case_match.py`·`pinecone_upload_regulations.py`·`eval_corpus_mix.py`·`data/eval_corpus_mix.json`·`data/bm25_corpus.json.gz` 커밋
2. **A-2** — Q6 범위 결정. 현 상태는 게시판 기능을 사실상 정지시킨다. 대안: ① 축자 인용 탐지 시에만 제외 ② 상담이 **주근거**일 때만(비중 임계) ③ `noindex` 처리
3. **A-3** — `POOL_PUBLIC_QUOTA` 폴백 상한(예: `min(max(2, top_k//4), 6)`) 또는 wider 값 등록

**기능 정합**
4. **A-5** — `format_pinecone_hits`가 `top_n`을 전달하도록 + 회귀를 프로덕션 호출 형태로 교정
5. **A-6** — Self-RAG 뒤 쿼터 재적용 또는 승격분 보호
6. **A-8** — `case_match`에서 `anonymize()` 적용 + `title[:120]` 절단
7. **A-10** — 공공·상담 집합 단일화
8. **A-11** — 2단 하한을 `MIN_COUNSEL_IN_POOL`로 통일

**문서**
9. **D-1·D-2** — Design §2에 2단 절 신설, 수술 지점 정정 (설계가 구현을 되돌리도록 유도하는 상태 해소)
10. **A-7** — 킬스위치 범위를 설계에 명시하거나 폴백까지 포함

**측정**
11. **A-4** — `eval_corpus_mix.py`를 프로덕션 쿼리 경로로 전환 + 지연 계측 추가 + COMPLEX/wider 질의 편입
12. **A-17** — BM25 메모리 재측정

---

## 7. 이 사이클의 교훈

**측정 도구가 프로덕션을 재지 않으면 목표 달성도 근거가 없다.** `eval_corpus_mix.py`는 원문 쿼리 1개를 넘겼고 프로덕션은 분해·규칙 쿼리 목록을 쓴다. 이번엔 재측정 결과가 더 좋아 결론이 유지됐지만, 반대였다면 "달성"이 허위였다. 그리고 **Self-RAG·wider 구간은 지금도 측정되지 않으며, High 2건이 정확히 그 구간에 있다.**

**이중 리뷰가 또 작동했다.** gap-detector는 82%를 냈고 "설계대로 만들었는가"에는 충실했다. 그러나 Q6이 게시판을 정지시킨다는 것(A-2), 측정이 프로덕션과 다르다는 것(A-4), Q4가 무력하다는 것(A-5)은 **설계 자체의 공백**이라 원리적으로 못 잡는다. CLAUDE.md의 규약이 5번째 사이클에서도 값을 했다.


---

## 8. Act 처리 결과 (2026-08-25)

| ID | 조치 | 회귀 |
|---|---|:---:|
| A-2 | Q6을 `counsel_dominant`(비중 > 2/3)로 좁힘 — 게시판 제외 **12/12 → 2/12** | T26-h4~h9 |
| A-3 | 쿼터 폴백 `top_k//4` + 상한 6 — wider(40) 쿼터 **20 → 6** | T26-o, o2 |
| A-5 | `format_pinecone_hits`에 `top_n` 전달 — Q4가 의도한 상한으로 동작 | T26-r |
| A-6 | Self-RAG가 공공을 **전멸**시킬 때만 1건 복원 | T26-s |
| A-7 | 킬스위치가 되돌리지 못하는 범위를 docstring에 명시(문서 조치) | — |
| A-8 | `cases` 제목 `anonymize()` + `[:120]` 절단 | T26-t |
| A-9 | 길이 예산을 **청크 단위**로 — 텍스트와 meta가 항상 정합 | T26-u~u4 |
| A-10 | `LEGAL_PROMOTE_SOURCES = POOL_PUBLIC_SOURCES`(동일 객체), 리터럴 제거 | T26-q, q2 |
| A-11 | 2단 상담 하한을 `MIN_COUNSEL_IN_POOL`로 통일 | T26-p |
| A-12 | 필터가 list/tuple도 `$in`으로 — str만 `$eq` | 실측 4종 확인 |
| A-13 | `ensure_textbook=False`가 공공 쿼터까지 끄던 것 분리 | — |
| A-14 | 절단 답변에는 T3를 돌리지 않음(품질 신호 오염 방지) | — |
| A-15 | `cases`에 표시된 상담을 `sources`에서 제외(중복 해소) | — |
| A-16 | `LEGAL_POOL_QUOTA`·`CASE_MATCH_THRESHOLD`를 `.env.example`에 문서화 | — |
| A-4 | `eval_corpus_mix.py --production` 모드 + p50/p95 지연 계측 | — |
| D-1~D-5 | Design §2.1을 2단 구조로 재작성, 병렬·무침범 논거 정정, 임계·키·건수 갱신 | — |

### 최종 지표 (`eval_corpus_mix.py --production`)

| 지표 | 기준선 | 목표 | 최종 |
|---|---:|---:|---:|
| 공공저작물 | 2 | ≥ 15 | **21** |
| 법률 근거 도달 | 2/12 | ≥ 11/12 | **12/12** |
| 상담 비중 | 89% | ≤ 62% | 63% |
| 저작물 비중 | 95% | ≤ 70% | **65%** |
| 지연 p50 / p95 | — | 기록 | 36.7s / 44.3s (답변 LLM 포함) |

상담 63%는 목표를 1%p 초과한다. Q4가 실제 동작하게 되면서(A-5) 상한 적용 방식이 바뀐 영향이고, 저작물 비중·법률 도달은 목표 안이다.

### 미해소 — 별도 판단 필요

**A-17 (BM25 메모리)**: 실측 결과 **Vercel 한도 1024MB의 119%**다.

| 단계 | RSS |
|---|---:|
| 인터프리터 | 13MB |
| 모듈 import | 16MB |
| gz 파싱(76,983문서) | **427MB** |
| BM25 인덱스 구축 | **1,218MB** |

이번 사이클이 만든 문제가 아니라 코퍼스 누적(직전 이론판례 3,468 + 이번 훈령 1,763)의 결과지만, gz가 이번 커밋에 실린다. 소프트 `MemoryError`는 `search_hybrid`가 Dense-only로 흡수하지만 **하이브리드 검색이 조용히 반쪽**이 되고, 하드 OOM-kill은 방어 불가다. 완화 후보(코퍼스 축소·스트리밍 파싱·샤딩·외부 서비스)는 전부 별도 사이클 규모다. 실측은 `bm25_search.py` 주석에 기록했다.

**A-1 (미커밋)**: 커밋 시 해소. `app/core/case_match.py`가 빠지면 배포 즉시 500이다.
