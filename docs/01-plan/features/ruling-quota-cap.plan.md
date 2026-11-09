# ruling-quota-cap — 재결례 전용 상한·쿼터 분리·킬스위치 Plan

> 입력: adjudication-corpus 측정 기록 `~/DEV/laborconsult_eval/rul/runs/{before1,before2,after1,after2}`의 `rag_meta`(98문항 × 4회, 2026-11-08~09) 재집계(2026-11-09), `app/core/rag.py` 쿼터·승격·다양성 코드(main c4a5f1a), 직전 사이클 Analysis §4 B-1·Report §4.2(R4 관측).
> 범위: 재결례(`source_type="ruling"`, 11,415벡터·1,052건)가 판례·행정해석·훈령의 공공 쿼터·승격 슬롯을 잠식하는 문제를 **검색 시점 코드**로 고친다 — 데이터(Pinecone·BM25 gz)는 건드리지 않는다. 재배포만으로 재결례를 끄는 env 킬스위치를 함께 둔다.
> 선행: adjudication-corpus(PR #155~#159, 2026-11-09 종결). 그 Analysis B-1(Medium)·Report §6 후속 1번이 이 사이클이다.
> 작성 2026-11-09 · 단계: Plan → Design(2026-11-09, D1~D7 확정)

## Executive Summary

| 관점 | 내용 |
|---|---|
| **Problem** | 재결례 적재 뒤 심사 쟁점 질문(S+ 18문항)의 컨텍스트에서 재결례가 슬롯의 59~64%를 차지하고, 재결례를 뺀 공공 근거(판례·행정해석·훈령)는 42·53 → 20·16으로 줄었다. 공공 근거가 **한 건도 없는** 문항이 S+ 0 → 8·6/18, 실사용 R 1·2 → 12·12/52로 늘었다. 원인은 재결례가 공공 쿼터를 '충족'하고 법률근거 '존재'로 판정돼 판례·행정해석 주입·승격이 꺼지는 구조다. 되돌림 수단은 데이터 롤백(원장 rollback + BM25 재빌드 3.5시간)뿐이다. |
| **Solution** | ① 쿼터·법률근거 승격 집합에서 재결례를 분리한다 — 재결례는 쿼터를 채우지도, '법률근거 있음'을 만들지도 않는다(저작권 분류용 공공 집합은 파생으로 유지). ② 재결례를 자기 다양성 클래스로 두어 I-9가 마지막 1건을 보호한다. ③ rerank 최종 목록에 재결례 총량 상한(`max(1, top_n // 2)`)을 **교체형**으로 건다 — 초과 재결례를 랭크 창의 비재결 후보와 바꾼다. ④ `RULING_RETRIEVAL=off` 킬스위치로 검색 시점에 재결례를 제외한다(재배포 반영). |
| **Function UX Effect** | 실업급여·산재 심사 질문에 재결례(적용 사례)와 판례·행정해석(규칙)이 **함께** 실린다. 재결례만 보고 일반화하는 답변, 공공 근거 0건 답변이 줄어든다. 재결례 공급률(S+ 94·89%)은 유지한다. |
| **Core Value** | 새 공공 출처를 더할 때 기존 공공 출처를 밀어내지 않는 구조를 만든다 — 다음 출처(법령해석례 등)도 같은 규칙을 탄다. 코드 스위치로 되돌릴 수 있어 데이터 롤백에 기대지 않는다. |

**목표 지표**(측정은 저장소 밖 하네스 `~/DEV/laborconsult_eval/rul/`, 현재 상태 = after1·after2, 변경 후 = cap1·cap2, 같은 모델·`--law-mode cache`):

| 관문 | 목표 | 현재(after1·after2) |
|---|---|---|
| G1 재결례 공급 유지 | S+ `ruling` 포함 ≥ 0.80(각 실행), S− 0건 | 0.94·0.89, 0 |
| G2 공공 근거 회복(S+) | 재결례 뺀 공공 ≥ 34(before 평균 47.5의 70%) **그리고** 공공 0건 문항 ≤ 2/18 | 20·16, 8·6 |
| G3 실사용 비회귀(R) | 공공 0건 문항 ≤ 4/52, 재결례 뺀 공공 ≥ 68 | 12·12, 62·60(before 1·2, 72·72) |
| G4 인용 정확 유지 | 교정 후 잔여 환각 0·비재결 오판 0, 유효 재결 인용 ≥ 10건/실행 | 0·0, 26·29 |
| G5 K·금지 문구 | K 금지 0, `allowed_source` 거짓 0, S+ 일반화 금지 문구 0, 벤더 동일, spy 누락 0 | 전부 0 |
| G6 검색 전용 비회귀 | `eval_retrieval` 해설서 도달률 불변, `eval_corpus_mix`(기본 모드) 공공 비율 비감소 | — |
| G7 오프라인 | 기존 스위트(T23·T24·T26·RU10~RU25·offline_units) + 신규 테스트 통과, 킬스위치 off에서 컨텍스트 재결례 0건 | — |

---

## 1. 실측 (2026-11-09, after 기록 재집계)

### 1.1 컨텍스트 구성 — 재결례가 어디를 차지했나

`rag_meta`(format_pinecone_hits가 돌려준 최종 컨텍스트)를 문항별로 다시 셌다. 슬롯은 문항당 약 5.5~5.8건이다.

| S+ 18문항 | before1 | before2 | after1 | after2 |
|---|---|---|---|---|
| 재결례 청크 (서로 다른 재결 수) | 0 | 0 | **67** (56) | **59** (45) |
| 같은 재결의 추가 청크 | 0 | 0 | 11 | 14 |
| 공공(판례·행정해석·훈령) | 42 | 53 | **20** | **16** |
| 그중 판례 | 10 | 8 | 7 | 2 |
| 공공 0건 문항 | 0 | 0 | **8** | **6** |
| 판례 0건 문항 | 14 | 15 | 16 | 17 |
| 재결례 ≥ 2건 문항 | 0 | 0 | 13 | 14 |
| 재결례 ≥ 공공 문항 | 0 | 0 | 15 | 16 |

| R 52문항(실사용) | before1 | before2 | after1 | after2 |
|---|---|---|---|---|
| 재결례 청크 (서로 다른 재결 수) | 0 | 0 | 18 (17) | 20 (20) |
| 공공(판례·행정해석·훈령) | 72 | 72 | 62 | 60 |
| 공공 0건 문항 | 1 | 2 | **12** | **12** |
| 재결례 포함 문항 | 0 | 0 | 14 | 14 |
| 재결례 ≥ 공공 문항 | 0 | 0 | 12 | 12 |

읽는 법:
- **R에서는 재결례가 들어간 14문항 중 12문항에서 공공이 0건이다.** 재결례 청크는 문항당 1~2건뿐인데 공공이 사라졌다 — 재결례가 **쿼터를 충족**해 판례·행정해석 조회·주입이 멈춘 것이다. 자연 유입이 아니라 쿼터 산정 규칙이 원인이다. *(Design rev2 정정: R 문항은 MODERATE·COMPLEX뿐이라 충족 지점은 pool 쿼터(3·4건)와 2단 목표 2건이다 — 재결례가 pool 쿼터를 채우면 `_with_public_quota`가 공공 조회를 건너뛰고 2단은 주입분이 없다. 처음 쓴 "SIMPLE 2단 1건"은 틀렸다.)*
- **S+에서는 재결례가 문항당 3.3~3.7건(슬롯의 59~64%)**이고 대부분 서로 다른 재결이다(같은 재결의 추가 청크는 16~24%). 재결례 본문이 사실관계 서술이라 구어 질의와 가깝다 — 상담글이 판례를 밀어내던 것과 같은 성질이다. 여기서는 자연 유입(Dense 20.4%·BM25 10.6% 비중 + rerank)이 지배적이고, 그 위에 쿼터 충족·승격 억제가 겹친다.
- 판례는 before에도 적었다(S+ 10·8건, 판례 0건 문항 14·15). 이 사이클은 판례를 새로 공급하는 것이 아니라 **재결례 때문에 사라진 공공 근거를 되돌리는** 것이다. 목표도 before 수준 회복이다.

### 1.2 경로 분해 — 코드의 세 지점

| 경로 | 지점(`app/core/rag.py`, main c4a5f1a) | 동작 | 효과 |
|---|---|---|---|
| ① 쿼터 충족 | `POOL_PUBLIC_SOURCES`(109)에 `ruling` 포함 → `_is_public_source`(154)·`_with_public_quota`(398)·`_apply_public_quota`(182)·`_ensure_public_quota`(560) | 재결례를 공공으로 세어 `have ≥ quota`면 주입 생략. `_fetch_public_hits`(158)의 `$in`에도 `ruling`이 있어 주입 후보 자체가 재결례다 | R 12문항 공공 0건, S+ 쿼터 주입이 재결례로 채워짐 |
| ② 승격 억제 | `LEGAL_PROMOTE_SOURCES = POOL_PUBLIC_SOURCES`(457) → `_is_legal_source`(460) → `_ensure_source_presence(..., "legal")`(686) | 재결례가 있으면 '법률근거 있음'이라 판례·행정해석 승격 미발동. `_diversity_class_of`(464)가 재결례를 법률근거 클래스로 보아 I-9가 보호 | 판례 0건 문항 S+ 14·15 → 16·17 |
| ③ 자연 유입 | `search_hybrid`(353) Dense+BM25 RRF → `rerank_results` `_finalize`(661) 절단 | 재결례 11,415벡터가 상위 점수로 들어와 `rerank_top_n` 슬롯을 여럿 차지한다. 총량·문서당 상한이 없다(해설서는 G4 3·G4-T 6이 있다) | S+ 재결례 ≥ 2건 문항 13·14/18 |

집합 소비자(한 곳만 바꾸면 조용히 어긋나는 지점): `eval_corpus_mix.py:38-43`(`classify`가 `POOL_PUBLIC_SOURCES`로 '공공' 판정), `eval_colloquial.py:117`(`LEGAL_PROMOTE_SOURCES`로 법률 근거 수 집계), `test_rulings_ingest.py` RU10(366-375: `LEGAL_PROMOTE_SOURCES is POOL_PUBLIC_SOURCES`·집합 리터럴 단언), `test_precedent_ingest.py` T24-a4(1684)·T26(1342)·1470(동일성).

### 1.3 되돌림 수단 현황

| 수단 | 범위 | 비용 | 문제 |
|---|---|---|---|
| `source_pack_ledger.py rollback data/vector_ledgers/rulings_202611.json --apply` + `build_bm25_corpus.py` + gz 커밋 | 데이터 전체 | 약 3.5시간(BM25) + 재적재 시 임베딩 비용 | 되돌린 뒤 다시 올리려면 전체 재임베딩 — "임베딩 재실행 금지" 제약과 충돌 |
| `LEGAL_POOL_QUOTA=off` | 공공 쿼터 전체 | 재배포 | 판례·행정해석 쿼터까지 꺼진다 — 문제를 키운다 |
| 재결례 전용 스위치 | 없음 | — | 이 사이클이 만든다 |

---

## 2. 범위

### P0-1 킬스위치 `RULING_RETRIEVAL=off` (`app/core/rag.py`)

- `search_hybrid`의 Dense·BM25 결과에서 `source_type == "ruling"`을 제거하고, `_fetch_public_hits`의 `$in` 집합에서도 뺀다. 기본 `on`, 알 수 없는 값은 `on`(`LEGAL_POOL_QUOTA`·`TEXTBOOK_PROMOTE`와 같은 재배포-반영 의미론).
- 끄면 컨텍스트에 재결례가 0건이므로 `uses_ruling`이 거짓이 되어 `RULING_CITATION_RULES` 접미·`rag_sources.ruling`이 자연히 사라진다 — 별도 분기를 두지 않는다.
- 끄지 못하는 것(문서에 명시): BM25 코퍼스 메모리(gz에 재결례 11,415문서가 남는다 — CI RSS 490MB 불변), 인용 검증의 재결 패턴(컨텍스트에 재결례가 없으면 화이트리스트가 비어 재결 번호는 전부 환각으로 제거된다 — 의도된 동작).

### P0-2 쿼터·법률근거 승격 집합에서 재결례 분리 (`app/core/rag.py`)

- `POOL_PUBLIC_SOURCES = {"precedent", "interpretation", "regulation"}` — 쿼터 산정·주입 조회 `$in`·2단·법률근거 승격 대상·'법률근거 있음' 판정이 모두 이 집합을 본다(단일 객체 원칙 `LEGAL_PROMOTE_SOURCES = POOL_PUBLIC_SOURCES` 유지).
- `RULING_SOURCES = frozenset({"ruling"})`, `PUBLIC_DOMAIN_SOURCES = POOL_PUBLIC_SOURCES | RULING_SOURCES` — **저작권 분류**(비보호 공공저작물)용. `eval_corpus_mix.classify`는 이쪽을 쓴다(그대로 두면 재결례가 'other'로 떨어져 공공 비율이 조용히 내려간다).
- *(Design rev2 추가 D22: 1단 쿼터의 victim을 '상담(하한 2) → pool 상한(`top_k//2`) 초과 재결례'로 넓힌다. 산재 재심사 질문은 pool 15건 중 14~15건이 재결례라 victim이 상담뿐이면 공공 조회가 6건을 돌려줘도 주입 0건이었다 — 재생 v2 probe. 해설서는 여전히 victim이 아니다.)*
- 두 집합의 드리프트(직전 사이클 외부 리뷰 A-10이 경고한 실패 모드)는 **파생 정의 + 구조 테스트**로 막는다: `PUBLIC_DOMAIN_SOURCES == POOL_PUBLIC_SOURCES | RULING_SOURCES`, 리터럴 재선언 0건(AST), `_is_public_source(ruling)` 거짓·`_is_legal_source(ruling)` 거짓·`is_public_domain(ruling)` 참.
- 효과: 재결례가 있어도 쿼터는 판례·행정해석·훈령으로 채워지고, 재결례만 있으면 법률근거 승격이 발동한다. 코드 경로는 늘지 않는다. *(Design rev2 정정: 재결례가 쿼터를 채워 조회를 건너뛰던 문항은 공공 조회 1회(임베딩 + Pinecone)가 추가된다 — "조회 0회"는 틀렸다.)*

### P0-3 재결례 다양성 클래스 (`_diversity_class_of`)

- 재결례에 `_is_ruling_source` 술어를 돌려 I-9가 **마지막 재결례 1건**을 승격 victim에서 보호한다 — 해설서·법률근거 승격이 유일한 재결례를 지우면 G1(공급률)이 깎인다.
- 법률근거 클래스와는 분리된다(②의 '존재' 판정에 들어가지 않는다).

### P0-4 재결례 총량 상한 — 교체형 (`rerank_results._finalize`)

- `RULING_CAP(top_n) = max(1, top_n // 2)`: 3→1, 5→2, 7→3, wider(6·8·10)→3·4·5. 값은 Design에서 S+ 18문항 검색 전용 재생(임베딩+Pinecone+Cohere, LLM 없음)으로 1 vs 2(top_n 5)를 비교해 확정한다.
- **차감이 아니라 교체다.** 초과 재결례(rerank 하위부터)를 비재결 후보와 바꾼다. 후보가 없으면 그대로 둔다(강제 공백 없음). *(Design rev2 조정: 후보는 ① 전체 랭킹의 `quota_injected` 공공 → ② 창의 자연 공공 → ③ 창의 상담이고 **해설서는 후보가 아니다**(저작권 노출 증가). 처음 쓴 "창 안만·공공 → 해설서 → 상담"은 2단이 재결례 위주 컨텍스트에서 돌지 않는 구조를 놓쳤다 — Design D12·§12 H1·M4. **Act-2 A(2026-11-09): ②를 top_n 밖 전체 자연 공공으로 확장** — 분해 쿼리 pool의 자연 공공이 창 밖에 묻히면 후보가 없었다. **Act-2 C**: Self-RAG 복원을 2단 목표 건수까지(Analysis §3.2).)* 해설서 G4/G4-T는 저작권 **노출** 상한이라 차감이 맞지만, 여기는 **구성** 문제라 빈 슬롯을 남기면 안 된다.
- 적용 순서: 재결 상한 → 공공 쿼터 2단(`_ensure_public_quota`) → 해설서 승격 → 법률근거 승격. 상한이 먼저 자리를 비워야 2단이 `quota_injected` 공공으로 채운다. 세 exit(성공·무키·예외) 공통.
- 교체로 들어온 항목은 `promoted="ruling-cap"` 마커를 단다(계측 계약 — eval이 이 키로 발동을 센다, T23·T24와 같은 이유). I-7(승격분은 victim 금지)이 그대로 적용된다.
- 문서당 상한(같은 재결 청크 ≤ 2)은 **보류**(D5) — 같은 재결의 주문·이유 청크는 상보적일 수 있고, 추가 청크 비중이 16~24%로 2차 경로다. Design에서 after 기록의 같은-재결 쌍을 육안으로 보고 정한다.

### P0-5 테스트·문서

- `test_rulings_ingest.py` RU26~: 킬스위치(off → `search_hybrid` 결과·`_fetch_public_hits` 필터에 ruling 없음, on 불변), 집합 파생·구조(AST), 다양성 클래스, 상한 교체 불변식(길이 불변·공공 우선·후보 없으면 무변경·`cap ≥ 1`·순서·마커·세 exit), `eval_corpus_mix.classify`가 `PUBLIC_DOMAIN_SOURCES`를 쓴다.
- 기존 수정: RU10(동일성 단언 → 파생 단언), T24-a4(집합 리터럴), T26 쿼터 산정(재결례 비포함), `test_precedent_ingest.py:1470`.
- CLAUDE.md: 재결례 절의 "재배포만으로 되돌릴 킬스위치는 **없다**" 문장을 교체, 배선 지점에 집합 3종·상한·순서 추가, Environment Variables에 `RULING_RETRIEVAL`, 공공 쿼터 절에 "재결례는 쿼터를 충족하지 않는다", `laborlaw-v2` 수치 불변 명시.

### P1 측정 (저장소 밖 `~/DEV/laborconsult_eval/rul/`)

- 현재 상태 기준선은 **after1·after2 재사용**(11-09 00:05~01:17, main과 같은 코드·같은 데이터). 변경 후 cap1·cap2 = 98문항(S+ 18·S− 6·R 52·K 22) × 2 = **196답변**(gpt-6-sol, `--law-mode cache --primary openai`). 같은 실행 간 편차가 크다(before M1b 42 vs 53) — 관문은 두 실행 **각각**으로 판정한다.
- 선택: base 재측정 1회(+98)로 모델 드리프트 확인 — cap 결과가 관문 경계에 걸릴 때만.
- `compare_rul.py` 확장: M1c 공공 0건 문항 수(S+·R), M1d 판례 0건 문항 수, M5 `promoted` 마커 분포(`ruling-cap`·`public-quota`·`legal`·`textbook`), 문서 단위 재결례 수. 이를 위해 `run_eval.py` spy가 `format_pinecone_hits` **입력 hits**의 `id`·`promoted`·`quota_injected`를 함께 기록한다(현재는 `source_type`·`case_no`·`title`만).
- 검색 전용 보조 측정(LLM 비용 0): `eval_retrieval.py`(해설서 도달률, 고정 fixture), `eval_corpus_mix.py` 기본 모드(12주제 공공 비율), S+ 18문항 검색 재생(상한 값 비교·Design 입력).

---

## 3. 범위 밖

- 데이터 변경 — 재업로드·삭제·BM25 재빌드 없음. 검색 시점 변경이라 필요 없다(gz·원장 불변, 재결례 벡터 11,415 불변).
- `rerank_top_n`·`POOL_PUBLIC_QUOTA`·`MIN_COUNSEL_IN_POOL` 수치 변경 — 저작권 노출·상담 하한을 지배하는 값이라 이 사이클이 건드리지 않는다.
- B-5 `agency` 메타 운반 — 상한의 문서 키는 ID(`ruling_{agency}_{serial}_chunk_{idx}`)에서 파싱한다(`_book_id_of`와 같은 방식). 메타는 불필요.
- B-8 이미지 전용 152건 OCR, `stale_rules` 산재 구 기준, 노동위원회 판정문(nlrc), 고정 IP 예열 — 각자 별도 과제.
- 판례 공급 자체의 확대(판례 0건 문항 14·15는 before부터다) — 다른 사이클.

---

## 4. 위험

| 위험 | 영향 | 완화 |
|---|---|---|
| 상한이 S+ 재결례 공급률(G1)을 깎는다 | 재결례 사이클의 목표 지표 회귀 | `cap ≥ 1`, 교체형(재결례 자신이 victim), I-9 보호. G1을 관문으로 유지 |
| 집합 3종이 어긋난다(A-10 실패 모드 — 총량 불변이라 메트릭에 안 잡힌다) | 쿼터·승격·분류가 서로 다른 집합을 본다 | 파생 정의 하나 + AST 구조 테스트 + `eval_corpus_mix.classify` 전환을 체크리스트로 |
| 쿼터가 판례·행정해석을 더 주입해 상담이 하한(2건)까지 밀린다 | 상담 우위 질문 실용성 | 기존 하한·victim 규칙 불변. 교체형 상한은 상담을 victim 삼지 않는다(재결례 초과분만) |
| 교체 후보가 창에 없어 상한이 효과 없음 | S+ 일부 문항은 그대로 | 관측(마커 0건)으로 보이게 — Design 재생에서 창 크기 2×top_n의 충분성을 확인 |
| 측정 편차(동일 조건 42 vs 53)로 관문 판정이 흔들린다 | 오판 | 2회 각각 판정, 경계면 base 재측정 1회(D6) |
| Self-RAG(COMPLEX)가 rerank 뒤 재결례를 더 걸러 상한보다 적게 남는다 | 관측값 해석 | 설계된 동작 — 기록만 |
| 킬스위치가 BM25 메모리를 줄이지 못한다 | 메모리 관문과 무관함을 오해 | 문서에 명시(P0-1) |

---

## 5. 완료 조건

1. P0-1~P0-4 구현 + RU26~ 신규 테스트·기존 단언 수정, 오프라인 스위트 전부 통과(`.venv/bin/python`).
2. 검색 전용 비회귀(G6): `eval_retrieval` 불변, `eval_corpus_mix` 기본 모드 공공 비율 비감소.
3. P1 측정 cap1·cap2 — 관문 G1~G5 판정(미달이 있어도 정의를 바꾸지 않고 기록). **cap: G2 건수 조건 cap2 미달(28) → Act-2(A+C) 뒤 재측정 act1·act2(2026-11-09, 100답변)에서 G1~G5 전부 통과(S+ 공공 42·42, 공공 0건 0·0, R 공공 85·공공 0건 0) — Design §6.4 5항·§13.**
4. 킬스위치 양성 검증: 로컬 `RULING_RETRIEVAL=off`로 S+ 3문항 검색 재생 → 컨텍스트 재결례 0건.
5. CLAUDE.md·env 문서 갱신(P0-5), Design §13 실행 기록.
6. PR·CI·머지(요청 시). Vercel env 변경 없음(기본 `on`).

---

## 6. 결정이 필요한 것

> **확정(2026-11-09)** — 사용자 "권고안대로 진행": D1~D7 모두 권고안으로 확정. D7은 측정 **직전**에 비용(196답변, 경계면 +98)을 다시 보이고 실행한다.

| # | 결정 | 권고 | 대안 |
|---|---|---|---|
| D1 | 킬스위치 이름·범위 | **`RULING_RETRIEVAL=off`** — 검색 결과·쿼터 조회에서 재결례 제외(재배포 반영) | `RULING_SOURCE=off`; 또는 상한만 두고 스위치 없음(되돌림이 다시 데이터 롤백) |
| D2 | 쿼터·승격 집합 처리 | **분리** — `POOL_PUBLIC_SOURCES`에서 `ruling`을 빼고 `PUBLIC_DOMAIN_SOURCES`(파생)를 저작권 분류에 쓴다. 추가 조회 0회 | 집합은 두고 쿼터 주입 안에 재결례 비율 상한(두 번 조회·복잡) |
| D3 | 재결례 다양성 클래스 | **자기 클래스**(I-9 보호) | 클래스 없음 — 승격이 유일한 재결례를 지울 수 있다 |
| D4 | 총량 상한 값·방식 | **`max(1, top_n // 2)` 교체형**, 순서 '상한 → 2단 → 승격 2종' | 고정 2; `top_n − quota`; 차감형(빈 슬롯) |
| D5 | 문서당 상한(같은 재결 ≤ 2청크) | **보류** — Design에서 after 기록 육안 뒤 결정 | 함께 도입 |
| D6 | 측정 설계 | **after1·after2 재사용 + cap1·cap2(196답변)**, 경계면 base 1회 추가(+98) | base·cap 각 2회(392답변) |
| D7 | 측정 비용 승인 | 196답변(최대 294) — **Do의 측정 단계 전 승인** | S+·S−만(48답변) — R 비회귀(G3)를 못 본다 |

---

## 7. 관례·전제

- Do는 별도 worktree(`../laborconsult-rqc`, 브랜치 `feat/ruling-quota-cap`), base는 main c4a5f1a. 하네스는 `--repo`로 worktree를 가리킨다.
- 측정은 `--law-mode cache`(프로덕션 L2를 오염시키지 않는다), 프로덕션 화면으로 점검하지 않는다(쿼터·게시판 오염).
- 커밋은 요청 시, 결제·크레딧 구매 없음, 키·토큰·IP 값 비출력, Pinecone 삭제·재색인·재임베딩 없음.
- 변경 뒤 `metadata.rag_sources`(관측 키)로 프로덕션 분포를 사후 확인할 수 있다 — 배포 뒤 실사용 답변의 `ruling`·`precedent` 건수.

## 8. 다음 단계

1. 사용자 결정 D1~D7(권고안으로 진행해도 됨) → `/pdca design ruling-quota-cap`.
2. design-validator 검토 → Do(worktree): 코드·테스트 → 검색 전용 재생으로 상한 값 확정 → 측정 승인 → cap1·cap2 → Check → Report → PR.
