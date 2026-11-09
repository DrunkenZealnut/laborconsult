# ruling-quota-cap — Design rev2

> Plan: `docs/01-plan/features/ruling-quota-cap.plan.md`
>
> **결정**(2026-11-09, 사용자 "권고안대로 진행" — Plan §6 D1~D7 확정):
> - D1: 킬스위치 **`RULING_RETRIEVAL=off`** — 검색 결과·쿼터 조회에서 재결례 제외(재배포 반영).
> - D2: 쿼터·법률근거 승격 집합에서 **재결례 분리** — `POOL_PUBLIC_SOURCES`에서 `ruling`을 빼고, 저작권 분류용 `PUBLIC_DOMAIN_SOURCES`는 파생. 코드 경로는 늘지 않지만 **재결례가 쿼터를 채워 공공 조회를 건너뛰던 문항은 조회 1회(임베딩 + Pinecone, 타임아웃 10초)가 추가된다**(`rag.py:414~416` 조기 반환, rev2 L2 — 재생 S+ 1단 주입 7 → 30이 그 신호).
> - D3: 재결례 **자기 다양성 클래스**(I-9 보호).
> - D4: 총량 상한 **`max(1, top_n // 2)` 교체형**, 순서 '상한 → 2단 → 승격 2종'.
> - D5: 문서당 상한 **보류**(§1.3 재생에서 같은 재결 추가 청크 비중을 보고 판단).
> - D6: 측정은 after1·after2 재사용 + cap1·cap2.
> - D7: 측정 비용 196답변(경계면 +98) — **측정 직전 승인**. 2026-11-09 사용자 "측정 진행" → cap1·cap2 실행.
>
> **기준 코드:** `main` c4a5f1a(PR #159 머지 뒤). 파일·함수·줄 번호는 그 코드 기준이다.
>
> **rev2(2026-11-09):** design-validator 73점(High 1·Medium 7·Low 9). 지적 전부를 코드로 재현해 반영했다(§12). 바뀐 것 —
> - **상한의 교체 후보 1순위는 전체 랭킹의 `quota_injected` 공공이다**(H1). rev1은 "상한이 자리를 비우면 2단이 채운다"고 썼지만, 상한은 빈자리를 남기지 않고 즉시 교체하며 그 교체분은 `promoted`라 2단의 victim이 아니고, 2단은 비승격 상담이 3건 이상이어야 돈다(`rag.py:594~600`). 재결례 위주 S+에서는 2단이 막혀 공공 0건 문항이 B~E 모두 5건이었다. 후보에서 **해설서를 뺀다**(M4 — 노출 증가는 저작권 재검토 대상).
> - **재결례 승격(D19)은 폐기한다.** 재생 v2에서 S+ 재결 포함 15 → 17을 얻는 대신 S−에 1건·R에 2건을 넣어 관문 G1(S− 0)을 깼다(M1이 지적한 S− 위험이 실측됐다, §1.3). 스위치는 2종(`RULING_RETRIEVAL`·`RULING_CAP`)으로 돌아간다.
> - **1단 쿼터의 victim을 '상담 → pool 상한(`top_k//2`) 초과 재결례'로 넓힌다**(D22, 신규). 재생 v2에서 공공 0건으로 남은 S+ 4문항은 전부 산재 재심사 질문이고 pool 15건 중 14~15건이 재결례·상담 0~2건이라, 공공 전용 조회가 판례·훈령 6건을 돌려줘도 1단이 **주입 0건**이었다(victim이 상담뿐). 재결례 포화 pool에서는 쿼터 1단 자체가 막힌다 — 2단·상한이 뒤에서 할 일이 없다. 해설서는 여전히 victim이 아니다.
> - `eval_corpus_mix.classify`가 **`ruling`을 별도 분류**하고 G6는 비재결 공공으로 판정한다(M5 — 직전 사이클 M11 "재결례 섞인 공공 상승은 지표가 아니다"). 서로 다른 재결 수의 키는 `case_no`가 아니라 **머리글 제목·id**다(M6 — BM25 경로 hit은 `case_no`가 빈 문자열).
> - "R의 재결례 27%는 쿼터 조회 산물"은 **재생 결과**로 표기를 낮추고(M7), CLAUDE.md에는 cap1·cap2의 `rag_hits_in`으로 확인한 뒤 적는다. D11의 `eval_retrieval` 근거를 고쳤다(M2 — 그 스크립트는 `top_n=len(hits)`라 상한·2단이 무발동). RU30 fixture를 현행·신규를 가르는 전원 단일 출처로 바꿨다(M3). Low 9건은 §12.
>
> **설계 단계 실측(2026-11-09):** ① adjudication-corpus 측정 기록(after1·after2)의 `rag_meta`를 문항별로 재집계해 경로를 분해했다(Plan §1, 여기 §1.1). ② 76문항을 검색 전용으로 세 번 재생(v1·v2·v3 — 임베딩·Pinecone·Cohere만, LLM 없음)해 변형의 컨텍스트 구성을 비교했다(§1.3) — 상한 값(D4 유지)·문서당 상한(D5 보류 확정)을 확정했고, 재결례 승격(D19)은 시도 뒤 폐기했으며, 1단 victim 확장(D22)을 더했다. ③ 재생에서 드러난 것: **R의 재결례는 자연 유입이 아니라 공공 쿼터 조회가 주입한 것**이었고(pool 117 → 4건, 실사용 비율은 cap1·cap2로 확인), **산재 질문의 pool은 재결례로 포화**돼 쿼터 1단이 막힌다.

## 0. 설계 결정

Plan 확정분(D1~D7)에 설계에서 더한 결정이다. 번호는 Plan에 이어 붙인다.

| # | 결정 | 근거 |
|---|---|---|
| D8 | **집합은 셋이고 파생 하나로 묶는다.** `POOL_PUBLIC_SOURCES = {precedent, interpretation, regulation}`(쿼터 산정·주입 조회·2단·법률근거 승격·'법률근거 있음' 판정), `RULING_SOURCES = {ruling}`, `PUBLIC_DOMAIN_SOURCES = POOL_PUBLIC_SOURCES \| RULING_SOURCES`(저작권 분류 — 비보호 공공저작물). `LEGAL_PROMOTE_SOURCES = POOL_PUBLIC_SOURCES`(같은 객체)는 유지한다. 술어 `_is_public_source`(쿼터)·`_is_legal_source`(승격)·`_is_ruling_source`·`is_public_domain`(분류, 공개 이름) | 직전 사이클 외부 리뷰 A-10 — 집합을 두 벌로 두면 소스 추가 때 한쪽만 갱신돼 총량 불변인 채 어긋난다. 리터럴은 두 개(`POOL_PUBLIC_SOURCES`·`RULING_SOURCES`)만 두고 합집합은 식으로 쓴다. RU26이 AST로 리터럴 재선언 0건을 고정 |
| D9 | **킬스위치는 `search_hybrid` 안의 후처리 필터다.** `_ruling_retrieval_enabled()`가 거짓이면 Dense 결과(`search_pinecone_multi` 반환)와 BM25 쿼리별 결과에서 `ruling`을 **RRF 병합 전**에 제거한다. 쿼터 조회 `_fetch_public_hits`의 `$in`은 D8로 이미 `ruling`이 없다. `_query_namespaces`에 `$nin`을 넣지 않는다 | 한 지점(`search_hybrid`)이 Dense·BM25 두 경로의 합류점이고 파이프라인·평가 스크립트가 모두 이 함수를 부른다. `_query_namespaces`에 필터를 넣으면 `source_type` 지정 조회의 필터 조립과 얽히고 BM25는 어차피 후처리다. 병합 **전**에 걸어야 RRF `top_k` 절단이 남은 후보로 채운다(병합 뒤 걸면 pool이 그만큼 빈다). pool이 약간 줄 수 있는 것은 비상 복귀 수단의 허용 범위다 |
| D10 | **상한은 자기 스위치 `RULING_CAP=off`를 따로 둔다.** `RULING_RETRIEVAL`(재결례 전체)과 독립 | 상한 코드에 결함이 있을 때 재결례 전체를 끄는 것은 과잉이다. `TEXTBOOK_PROMOTE`·`LEGAL_PROMOTE`가 기능별 스위치인 것과 같은 결. 알 수 없는 값은 `on` |
| D11 | **상한은 `_finalize`의 첫 단계이고 `ensure_textbook=False`에서도 적용한다.** 순서: 재결 상한 → 공공 쿼터 2단 → (여기서 `ensure_textbook` 분기) → 해설서 승격 → 법률근거 승격 | 상한이 먼저여야 2단이 **상한이 넣은 공공을 `have`로 세어** 중복 주입을 않는다(rev1의 "상한이 자리를 비워 2단이 채운다"는 틀렸다 — 상한은 즉시 교체하고 교체분은 2단의 victim이 아니다, rev2 H1). `ensure_textbook=False`는 "다양성 승격 2종만 끈 A/B 기준선"(Check 리뷰 A-13)이고 상한은 쿼터와 같은 구조 가드라 같은 쪽에 둔다 — 다만 `eval_retrieval`은 `top_n=len(hits)`로 불러 창이 비므로 상한·2단 모두 무발동이고, 그 측정에 영향을 주는 것은 D2(pool 구성)·D3(victim 선택)뿐이다(rev2 M2) |
| D12 | **교체 후보는 ① 전체 랭킹의 `quota_injected` 공공(순위순) → ② top_n 밖 전체 랭킹의 자연 유입 공공(순위순, Act-2 A에서 '창 안'에서 확장) → ③ 창(`top_n ~ 2×top_n`)의 상담** 순이다. **해설서는 후보가 아니다.** 후보가 없으면 남은 재결례를 그대로 둔다(강제 공백 없음). 제거는 rerank 하위 재결례부터, 유지되는 재결례는 상위 `cap`건 | ①이 창 밖이어도 되는 근거는 2단과 같다(`rag.py:571~574` — 공공 전용 조회의 상위라 품질 근거가 이미 있다). 이것이 없으면 재결례 자리에 공공이 들어갈 길이 없다: 2단은 비승격 상담 ≥ 3건일 때만 돌고 재결례·승격분을 victim 삼지 않는다(rev2 H1 — 재생에서 공공 0건 문항이 B~E 모두 5). 해설서 제외는 CLAUDE.md "승격 대상에 textbook을 넣지 말 것"(노출 증가는 저작권 재검토 대상, rev2 M4). 차감형(G4)이 아닌 이유는 Plan P0-4 |
| D13 | **교체로 들어온 항목은 `promoted="ruling-cap"`.** I-7(승격분 victim 금지)이 자동 적용된다 | 계측 계약 — eval이 마커로 발동을 센다(T23·T24와 같은 이유). 뒤따르는 2단·승격이 이 항목을 다시 밀어내지 않는다 |
| D14 | **Self-RAG 뒤 복원은 쿼터 집합(`_is_public_source`)만 대상이고 재결례는 복원하지 않는다.** rev2까지는 '전멸 시 1건 복원'을 그대로 두기로 했으나 **Act-2 C에서 '2단 목표(`_pool_public_quota_for_top_n`) 미만이면 목표까지 복원'으로 넓혔다**(`pipeline._restore_public_after_self_rag`) | 복원의 목적은 "법률 근거 0건" 방지이고 이 사이클의 정의로 법률 근거는 판례·행정해석·훈령이다. 재결례는 rerank 단계에서 I-9가 보호하고, Self-RAG가 그 뒤에 지우는 것은 판정 모델의 판단이라 존중한다(관측만) |
| D15 | **`eval_corpus_mix.classify`가 재결례를 'other'로 떨어뜨리지 않는다** — `RULING_SOURCES`로 `ruling`을 따로 분류하고 `POOL_PUBLIC_SOURCES`로 '공공'을 가른다(세부는 D20, rev2에서 "PUBLIC_DOMAIN으로 public 분류"에서 바뀜 — M5). `eval_colloquial.py:117`의 법률 근거 수는 `LEGAL_PROMOTE_SOURCES`라 재결례를 세지 않게 바뀐다 — 그 스크립트의 정의("법률근거 승격 대상")와 일치하므로 그대로 둔다 | 그대로 두면 재결례가 `other`로 떨어져 공공 비율이 조용히 내려간다(Plan P0-2). RU31이 `classify`의 `ruling` 분기·두 집합 참조를 고정 |
| D16 | **문서 키는 ID 파싱으로 충분하다 — rag에 `_ruling_doc_of`를 추가하지 않는다.** 하네스는 **`rag_hits_in`의 `id`(`ruling_{agency}_{serial}`) 또는 `rag_meta`의 `title`(머리글에 기관·번호)**로 서로 다른 재결 수를 센다. `case_no`는 쓰지 않는다. B-5(`agency` 메타 운반)는 이 사이클에 불필요 | BM25 경로로 들어온 재결례는 `case_no`가 빈 문자열이라(`bm25_search.py:643~652`, `build_bm25_corpus.py`가 보관하지 않음) `case_no` 키는 서로 다른 재결을 하나로 뭉친다(rev2 M6). §1.1의 "(서로 다른 재결)"은 `case_no or title`, §1.3은 `id` 접두사로 셌다 — 둘 다 문서를 가른다. 필요해지면 `_book_id_of`와 같은 꼴로 더한다 |
| D17 | **spy는 `format_pinecone_hits` 입력 hits의 `id`·`source_type`·`promoted`·`quota_injected`를 `rag_hits_in`으로 함께 기록한다.** `rag_meta`(최종 컨텍스트)는 그대로 | 마커는 `_finalize`의 결정 기록이고 `format_pinecone_hits` 출력(`meta_list`)에는 없다. 프로덕션 `meta_list`에 `id`를 더하지 않는다 — 인용 화이트리스트·`sources`·`rag_sources`가 그 dict를 쓰고 테스트가 키를 고정할 수 있다. 측정 전용 변경은 저장소 밖에 둔다 |
| D18 | **측정 base는 after1·after2를 재사용하고 cap1·cap2만 새로 돈다**(D6). base 재측정은 cap 두 실행이 관문 **경계**(한쪽 통과·한쪽 미달)일 때만 1회 | 같은 조건 두 실행의 편차가 크다(before M1b 42 vs 53). 두 실행 각각으로 판정하고, 경계면 모델 드리프트를 의심한다. **실측: cap1 ✅/cap2 ❌(G2 건수)로 경계가 성립했으나 base 재측정은 생략하고 Act-2 뒤 재측정 act1·act2(42·42 — 임계 34에서 멀어 경계 아님, 벤더 동일)로 대체했다(§13)** |
| D19 | **폐기 — 재결례 다양성 승격을 두지 않는다.** rev1·rev2 초안은 top_n 재결례 0건일 때 창의 재결례 1건을 승격하려 했다(S+ 재결 포함 15 → 17) | 재생 v2(§1.3): 승격이 **S−에 1건·R에 2건** 재결례를 넣었다 — G1 "S− 0"이 깨진다(M1이 지적한 위험의 실측). pool의 재결례가 창에 있다는 것만으로는 그 질문이 심사 쟁점인지 알 수 없고, 점수 기준은 설계 원칙(랭크 창)과 맞지 않는다. 분리 뒤 S+ M1 0.83은 G1(0.80) 안이고 프로덕션 분해 쿼리는 원문 쿼리보다 재결례를 더 높이 올린다(after M1 0.94·0.89) — 승격 없이 G1로 관측한다 |
| D20 | **`eval_corpus_mix.classify`는 `ruling`을 별도 분류로 돌려주고, 공공 비율·"법률 근거 도달"은 비재결 공공만 센다.** `counts`에 `"ruling"` 키 추가, 출력 줄에 재결례 건수 병기 | 직전 사이클 M11 — 재결례가 섞인 공공 상승은 지표가 아니다(rev2 M5). 기준선(2026-08-23)은 재결례가 없던 때라 **비재결 공공이 기준선과 같은 정의**다. "법률 근거 도달"을 재결례만 실린 답변까지 세면 rag의 새 '법률근거' 정의와 갈린다 |
| D21 | **`eval_colloquial.py:55`의 `LEGAL_CORPUS_SOURCES` 리터럴을 `PUBLIC_DOMAIN_SOURCES \| {"textbook"}`로 바꾼다** | 그 파일 주석이 "집합은 재선언하지 않고 rag의 단일 출처를 쓴다"고 해 놓고 리터럴로 `ruling`을 담고 있다(rev2 L8). RU26의 AST 검사는 `rag.py`만 보므로 여기는 파생식으로 바꿔 둔다 |
| D22 | **1단 쿼터(`_apply_public_quota`)의 victim을 '상담(하한 `MIN_COUNSEL_IN_POOL`) → pool 상한 초과 재결례(점수 하위부터, 하한 `max(1, top_k // 2)`)'로 넓힌다.** 해설서는 여전히 victim이 아니다. 2단(`_ensure_public_quota`)의 victim 규칙은 **바꾸지 않는다** — 재결례 위주 top_n에서는 상한 ①(`quota_injected` 공공)이 그 몫을 한다 | 재생 v2의 공공 0건 S+ 4문항(`r-ia-eye`·`r-ia-msk`·`r-ia-grade-finger`·`r-ia-grade-brain`)은 pool 15건 중 재결례 14~15·상담 0~2이고, `_fetch_public_hits`가 판례·훈령 6건을 돌려줬는데도 victim이 상담뿐이라 **주입 0건**이었다(§1.3 probe). 산재 재결례는 iaciac 934건·약 9,000벡터라 산재 질문의 Dense·BM25 상위를 채운다 — "pool 구성이 병목"(T1 설계)이 재결례에서 재현된 것이다. 하한 `top_k//2`(15 → 7, 20 → 10)는 상한과 같은 비율이라 pool의 재결례 다수를 남긴다(재생 v3: S+ pool 재결례 111 → 100, 주입 30 → 41, 공공 0건 S+ 4 → 0 — C3). `RULING_CAP=off`면 ①이 닫혀 주입 공공이 top_n에 못 들 수 있다(v3 B3: 공공 0건 3) — 스위치 조합을 CLAUDE.md에 적는다 |

## 1. 실측 근거

### 1.1 after 기록 재집계(2026-11-09, Plan §1.1 요약)

| S+ 18문항 | before1 | before2 | after1 | after2 |
|---|---|---|---|---|
| 재결례 청크 (서로 다른 재결) | 0 | 0 | 67 (56) | 59 (45) |
| 같은 재결의 추가 청크 | 0 | 0 | 11 | 14 |
| 공공(판례·행정해석·훈령) | 42 | 53 | 20 | 16 |
| 공공 0건 문항 / 판례 0건 문항 | 0 / 14 | 0 / 15 | 8 / 16 | 6 / 17 |

| R 52문항 | before1 | before2 | after1 | after2 |
|---|---|---|---|---|
| 재결례 청크 / 재결례 포함 문항 | 0 / 0 | 0 / 0 | 18 / 14 | 20 / 14 |
| 공공 / 공공 0건 문항 | 72 / 1 | 72 / 2 | 62 / 12 | 60 / 12 |

키: 재결례 문서는 `case_no or title`(머리글 제목에 기관·번호)로 갈랐다 — BM25 경로 hit은 `case_no`가 비어 있어 `case_no`만으로는 뭉친다(rev2 M6).

경로 3종 — ① 쿼터 충족(R: 재결례 포함 14문항 중 12문항 공공 0건 — 재결례가 공공으로 세어져 pool 쿼터(top_k 15·20 → 3·4)를 채우면 `_with_public_quota`가 공공 조회를 **건너뛰고**(`rag.py:414~416`) 2단은 주입분이 없어 할 일이 없다. R은 재생에서 MODERATE 23·COMPLEX 29로 SIMPLE이 없어 2단 목표는 2건이다 — rev1·Plan의 "SIMPLE 1건" 서술은 틀렸다, rev2 L1) ② 승격 억제('법률근거 있음' → 판례 승격 미발동, I-9가 재결례 보호) ③ 자연 유입(S+: 문항당 재결례 3.3~3.7건, 슬롯 59~64%, 대부분 서로 다른 재결).

### 1.2 코드 지점 현황(main c4a5f1a)

| 지점 | 현재 | 변경 |
|---|---|---|
| `app/core/rag.py:109` `POOL_PUBLIC_SOURCES` | `{precedent, interpretation, regulation, ruling}` | `ruling` 제외 + `RULING_SOURCES`·`PUBLIC_DOMAIN_SOURCES` 신설(D8) |
| `:154` `_is_public_source` | 집합 포함 여부 | 그대로(집합이 바뀜) + `_is_ruling_source`·`is_public_domain` 추가 |
| `:158~180` `_fetch_public_hits` | `$in POOL_PUBLIC_SOURCES` | 그대로(집합이 바뀜 → 주입 후보에서 재결례 자동 제외) |
| `:182~222` `_apply_public_quota` | victim 상담만(하한 2) | victim 상담 → **pool 상한 초과 재결례**(D22) |
| `:353~397` `search_hybrid` | Dense·BM25 → RRF → `_with_public_quota` | RRF **전** `_exclude_rulings_if_disabled` 적용(D9) |
| `:457` `LEGAL_PROMOTE_SOURCES = POOL_PUBLIC_SOURCES` | 동일 객체 | 그대로 |
| `:464~474` `_diversity_class_of` | 해설서 / 법률근거 / None | 재결례 → `_is_ruling_source` 추가(D3) |
| `:661~683` `rerank_results._finalize` | 2단 → (ensure_textbook) → 해설서 → 법률근거 | **재결 상한** → 2단 → (ensure_textbook) → 해설서 → 법률근거(D11) |
| `:612` `_pool_public_quota_for_top_n` | 1 (top_n ≤ 3) / 2 | 그대로 |
| `app/core/pipeline.py:4027·4037~4043` Self-RAG 복원 | `_is_public_source`, 전멸 시 1건 | Act-2 C: `_restore_public_after_self_rag(before, after, top_n)` — 쿼터 집합 공공이 2단 목표 미만이면 목표까지(D14) |
| `eval_colloquial.py:55` `LEGAL_CORPUS_SOURCES` | 리터럴(`ruling` 포함) | `PUBLIC_DOMAIN_SOURCES \| {"textbook"}`(D21) |
| `eval_corpus_mix.py:38~43` `classify`·`:133~141` 집계 | `POOL_PUBLIC_SOURCES`, 공공/해설서/상담/기타 | `ruling` 별도 분류, 공공은 비재결(D15·D20) |
| `eval_colloquial.py:117` | `LEGAL_PROMOTE_SOURCES` 집계 | 그대로(D15) |
| `test_rulings_ingest.py:366~375` RU10 | `ruling in POOL_PUBLIC_SOURCES`, 동일성, 리터럴 | 파생 단언으로 개정(§5) |
| `test_precedent_ingest.py:1684` T24-a4, `:1470` | 집합 리터럴에 `ruling`, 동일성 | 리터럴 수정, 동일성 유지 |

### 1.3 검색 전용 재생(2026-11-09) — 변형 비교

76문항(S+ 18·S− 6·R 52)마다 pool을 두 번 만들고(현행 집합 / 분리 집합) Cohere 전체 랭킹 뒤 `_finalize` 변형을 오프라인으로 적용해 `format_pinecone_hits` 통과 구성을 셌다(스크립트 `rqc_replay.py`, 272초, LLM 0회). **원문 쿼리 1개**라 프로덕션(의도분석 분해 쿼리)과 절대값이 다르다 — 현행 A의 S+ 공공이 5건으로 실제 after(20·16)보다 훨씬 낮은 것이 그 차이다. **변형 간 상대 비교용**이다. 복잡도: S+ moderate 16·complex 2, R moderate 23·complex 29.

변형: A 현행 / B 집합 분리(D2·D3)만 / C = B + 상한 `max(1, top_n//2)` / D = B + 고정 2 / E = B + 고정 1.

| S+ 18문항(슬롯 94) | 재결례 (서로 다른 재결) | 공공(비재결) | 판례 | 상담 | 공공 0건 | 재결 포함 | 재결 ≥ 2 | 교체 / 후보 없음 |
|---|---|---|---|---|---|---|---|---|
| A 현행 | 52 (40) | 5 | 3 | 37 | 14 | 18 | 14 | — |
| B 분리 | 44 (36) | 20 | 6 | 30 | 5 | 15 | 13 | — |
| C 분리+half | 39 (32) | 20 | 6 | 35 | 5 | 15 | 13 | 7 / 11 |
| D 분리+고정2 | 39 (32) | 20 | 6 | 35 | 5 | 15 | 13 | 7 / 11 |
| E 분리+고정1 | 31 (24) | 25 | 6 | 38 | 5 | 15 | 5 | 15 / 16 |

| R 52문항(슬롯 318) | 재결례 | 공공(비재결) | 판례 | 공공 0건 | 재결 포함 |
|---|---|---|---|---|---|
| A 현행 | 65 (59) | 37 | 4 | 28 | 38 |
| B~E 분리 | **0** | 103 | 14 | 0 | 0 |

| pool(1단 뒤) | 주입 공공 cur→new | 재결례 cur→new |
|---|---|---|
| S+ | 7 → 30 | 117 → 111 |
| S− | 17 → 18 | 4 → 1 |
| R | 172 → 176 | **117 → 4** |

읽는 법과 결정:
- **재생에서는 R의 재결례가 자연 유입이 아니라 쿼터 조회의 산물이었다.** 집합을 분리하자 pool 재결례 117 → 4, 컨텍스트 0건 — 1단의 victim은 상담뿐이라(`rag.py:207`) 자연 유입 재결례는 집합이 바뀌어도 빠지지 않으므로, 사라진 113건은 `_fetch_public_hits`(`$in`에 `ruling`)가 주입한 것이다. **단, 이것은 원문 쿼리 재생의 결과다**(rev2 M7): 실사용 R은 분해 쿼리를 쓰고 after 기록의 R은 재결례 18~20건·14문항으로 재생(65건·38문항)과 규모가 다르며, 현행 코드에서는 자연 유입 재결례도 쿼터를 채워 조회를 막으므로 after 기록만으로는 자연 유입과 주입을 가를 수 없다. 실사용에서 그 비율을 `quota_injected`로 확인할 수는 없다 — cap 코드(D8)에서는 `_fetch_public_hits`의 `$in`에 `ruling`이 없어 재결례에 `quota_injected`가 붙지 않고, after 기록에는 `rag_hits_in`이 없다. 간접 근거는 after → cap·act의 R 재결례 공급 **0.27 → 0.13·0.23**(쿼터 집합에서 재결례를 뺀 뒤 자연 유입만 남은 값, 실행 편차 큼)이고 CLAUDE.md에는 이 범위로 적는다(M7, Check 재실행 G10).
- **S+의 재결례는 자연 유입이다**(pool 117 → 111). 분리만으로 공공 5 → 20, 공공 0건 14 → 5, 판례 3 → 6이 된다 — 쿼터 2단이 재결례 대신 판례·행정해석을 채우기 때문이다(1단 주입 7 → 30).
- **rev1 상한(C, 창 후보)은 공공을 늘리지 못했다** — 재결례 44 → 39, 공공은 B와 같은 20, 공공 0건 문항도 5 그대로. 이유는 rev1이 쓴 "창의 공공은 2단이 이미 쓴다"가 아니라(rev2 H1) **구조**다: 상한은 즉시 교체하므로 빈자리가 없고, 교체분은 `promoted`라 2단의 victim이 아니며, 2단은 비승격 상담 ≥ 3건에서만 돈다(`rag.py:594~600`) — 재결례 위주 S+(상담 1.7건/문항)에서 2단은 막힌다. 창(`ranked[5:10]`)의 비재결 후보는 대부분 상담이라 교체분도 상담이었다. 그래서 **rev2는 후보 1순위를 전체 랭킹의 `quota_injected` 공공으로 바꿨다**(D12) — 재생 v2(아래)로 효과를 확인한다. 교체 수(7)와 재결례 감소(5)가 다른 것은 교체는 `_finalize` 안에서, 재결례 수는 `format_pinecone_hits` 통과 뒤(길이 예산·stale)에 센 값이기 때문이다(rev2 L3 — v2에서는 두 값을 함께 적는다).
- **D5(문서당 상한) 보류 확정.** 같은 재결의 추가 청크는 A 12건(23%) → C 7건(18%)으로 상한 뒤에도 남지만 문서당 보통 1건이고, 쟁점·주문·이유 청크는 상보적이다. 별도 상한을 두지 않는다. Plan은 "after 기록 육안"으로 정한다고 했으나 **재생 집계**로 판단했다(편차 기록 — 육안은 Do에서 cap1 S+ 표본 5문항으로 보완).
- **분리로 S+ 3문항이 재결례를 잃는다**(18 → 15, M1 0.83 — G1 0.80 안). 쿼터 주입으로만 재결례가 실리던 문항이다(`r-ins-retro`·`r-fraud-abroad`·`r-early-related` — pool 재결례 1~3건).

#### 재생 v2(validator H1·M1·M4 반영) — 상한 후보 규칙 개정·재결례 승격 시험

| S+ 18문항(슬롯 94) | 재결례 | 공공 | 판례 | 상담 | 공공 0건 | 재결 포함 | 교체 / 후보 없음 / 승격 |
|---|---|---|---|---|---|---|---|
| B 분리 | 44 | 20 | 6 | 30 | 5 | 15 | — |
| C 분리+half, 창 후보(rev1) | 39 | 20 | 6 | 35 | 5 | 15 | 7 / 11 / — |
| C2 분리+half, **`quota_injected` 우선·해설서 제외**(rev2) | 39 | 21 | 7 | 34 | 4 | 15 | 7 / 11 / — |
| C2P = C2 + 재결례 승격(victim 상담만) | 41 | 21 | 7 | 32 | 4 | **17** | 7 / 11 / 2 |

S−: C2P가 재결례 **1건**(B~C2는 0), R: C2P 재결례 **2건**(B~C2는 0) — 승격이 S−·R에 재결례를 넣는다. → **D19 폐기.** C2의 개선이 작은(공공 0건 5 → 4) 이유는 아래 probe.

#### probe — 공공 0건으로 남은 S+ 4문항의 pool

| 문항 | pool 15건 구성(점수순) | 상담 | 공공 전용 조회 반환 | 1단 주입 |
|---|---|---|---|---|
| `r-ia-eye` 요양 불승인(약품) | R×14 T×1 | 0 | 판례 6 | **0** |
| `r-ia-msk` 업무상 질병(허리) | R×13 C×2 | 2 | 훈령 1·판례 5 | **0** |
| `r-ia-grade-finger` 장해등급 | C R R P T R×10 | 1 | 훈령 3·판례 3 | **0** |
| `r-ia-grade-brain` 장해등급(뇌) | R×15 | 0 | 판례 6 | **0** |

네 문항 모두 산재 재심사 질문이다. pool이 재결례로 포화돼(iaciac 934건·약 9,000벡터가 산재 질의의 Dense·BM25 상위를 채운다) 1단 `_apply_public_quota`의 victim(상담, 하한 2)이 없어 **공공 조회가 후보를 돌려줘도 주입 0건**이다. 2단·상한은 뒤에서 가져올 주입분이 없다. "pool 구성이 병목"(T1 설계)이 재결례에서 재현된 것 → **D22(1단 victim에 pool 상한 초과 재결례 추가)**.

#### 재생 v3(D22 반영)

| S+ 18문항(슬롯 94) | 재결례 (서로 다른 재결) | 공공 | 판례 | 상담 | 공공 0건 | 판례 0건 | 재결 포함 | 재결 ≥ 2 | 교체 / 후보 없음 |
|---|---|---|---|---|---|---|---|---|---|
| A 현행 | 52 (40) | 5 | 3 | 37 | 14 | 16 | 18 | 14 | — |
| B 분리 | 44 (36) | 20 | 6 | 30 | 5 | 14 | 15 | 13 | — |
| C2 분리+half(1단 그대로) | 39 (32) | 21 | 7 | 34 | 4 | 13 | 15 | 13 | 7 / 11 |
| B3 분리+**D22**(상한 없음) | 40 (34) | 22 | 7 | 32 | 3 | 13 | 15 | 13 | — |
| **C3 분리+D22+half** | **29 (26)** | **31** | **15** | 34 | **0** | **9** | 15 | 13 | 15 / 1 |
| E3 분리+D22+고정 1 | 20 (17) | 38 | 17 | 36 | 0 | 9 | 15 | 4 | 24 / 5 |

| pool(1단 뒤) | 재결례 cur / new / new2(D22) | 주입 공공 cur / new / new2 |
|---|---|---|
| S+ (pool 280) | 117 / 111 / **100** | 7 / 30 / **41** |
| S− (pool 90) | 4 / 1 / 1 | 17 / 18 / 18 |
| R (pool 925) | 117 / 4 / 4 | 172 / 176 / 176 |

S−·R은 B~E3 전부 재결례 0·공공 12 / 103으로 같다(D22는 pool 재결례가 하한 이하라 무영향). 산재 4문항은 C3에서 `5/0/0 → 2/3/0`(eye·brain), `5/0/0 → 2/2/1`(msk·finger)이 됐다 — 예: `r-ia-grade-brain` top_n = 재결 2(iaciac 7145·12973) + 판례 3(2005두12992·2008두2088·2010두1743).

**확정:**
- **D22 채택.** D22만으로는(B3) 공공 0건 3이 남고, 상한 ①이 주입 공공을 top_n으로 끌어와야 0이 된다(C3). 세 단계(D22 → 상한 ① → 2단)가 한 줄이다. pool 재결례는 111 → 100(−11, 18문항)으로 다수가 남는다.
- **D4는 `max(1, top_n // 2)`(C3) 유지.** E3(고정 1)은 공공 38·판례 17로 더 좋지만 재결례가 슬롯 21%·재결 ≥ 2 문항 4로 재결례 사이클의 목적(적용 사례 공급)을 깎는다. cap1·cap2에서 S+ 재결례 슬롯 비중이 50%를 넘으면 Act에서 E로 내린다(기록만). **실측: cap2 52%(cap1 38%)로 걸렸으나 E는 채택하지 않았다** — cap2 공공 28의 원인은 상한 후보 부재(창 밖 자연 공공)와 Self-RAG 손실이라 E(고정 1)로는 고칠 수 없고, E는 재결례 공급(G1)을 깎는다(Analysis §4). Act-2(A+C) 뒤 act1·act2 비중 42%·39%로 기준 안(§13).
- **D19 폐기**(위). **D5 보류 확정**(C3 같은 재결 추가 청크 3건/29).
- G2(S+ 공공 ≥ 34·공공 0건 ≤ 2)는 재생 C3 31·0 — 원문 쿼리 재생이 프로덕션(분해 쿼리)보다 공공에 비관적이므로(A 5 vs 실측 20·16) 관문은 그대로 둔다.

## 2. 변경 파일

| 파일 | 변경 | 비고 |
|---|---|---|
| `app/core/rag.py` | 집합 3종·술어·스위치 2종(`RULING_RETRIEVAL`·`RULING_CAP`)·`_exclude_rulings_if_disabled`·`_ruling_cap`·`_cap_rulings_in_top_n`(후보 ② 전체 자연 공공 — Act-2 A)·`_apply_public_quota` victim 확장(D22)·`_finalize` 순서·`_diversity_class_of`·로그 | 런타임 |
| `app/core/pipeline.py` | `_restore_public_after_self_rag` 헬퍼 + Self-RAG 블록 호출(Act-2 C) | 런타임 — Act-2에서 추가 |
| `eval_corpus_mix.py` | `classify`에 `ruling` 분류, 집계·출력에 재결례 병기(D20) | 측정 스크립트 |
| `eval_colloquial.py` | `LEGAL_CORPUS_SOURCES` → `PUBLIC_DOMAIN_SOURCES \| {"textbook"}`(D21) | 측정 스크립트 |
| `test_rulings_ingest.py` | RU10 개정, RU26~RU35 신설(RU35는 Act-2 C 복원 사례) | CI |
| `test_precedent_ingest.py` | T24-a4 집합 리터럴 | CI |
| `CLAUDE.md` | 재결례 절 R4 문단 교체, env 2종, 공공 쿼터(victim 규칙)·다양성 승격 절 보강 | §7 |
| `docs/02-design/features/ruling-quota-cap.design.md` | §13 Do 실측 기록(main 작업 트리의 미추적 파일 — Plan·Analysis와 함께 커밋 때 worktree로 복사) | — |
| `~/DEV/laborconsult_eval/rul/run_act.sh`·`act_diag.py`·`compare_rqc.py --allow-partial/--k-from`(저장소 밖) | Act-2 재측정 실행·진단·부분 측정 판정(§6.4 5항) | — |
| (저장소 밖) `~/DEV/laborconsult_eval/kin/run_eval.py` | spy `rag_hits_in`(D17) | 측정 전용 |
| (저장소 밖) `~/DEV/laborconsult_eval/rul/compare_rqc.py`(신규, `compare_rul.metrics` 재사용)·`run_cap.sh`·`patch_run.py` | M1c·M1d·M1e·M5, 관문 G1~G5, 오염 문항 치환 | 측정 전용 — 출력 `report_rqc.md`·`gates_rqc.json` |

데이터(Pinecone `laborlaw-v2` 56,091·BM25 gz 107,177·원장)는 바뀌지 않는다. Vercel env는 기본값(`on`)이라 변경하지 않는다.

## 3. `app/core/rag.py` 설계

### 3.1 집합 3종·술어(D8)

```python
# 쿼터·법률근거 승격·'법률근거 있음' 판정의 대상 — 재결례는 **아니다**(ruling-quota-cap D2).
POOL_PUBLIC_SOURCES = frozenset({"precedent", "interpretation", "regulation"})
# 재결례 — 공공저작물이지만 쿼터를 채우지도, 법률근거 존재를 만들지도 않는다. 자기 다양성 클래스(I-9).
RULING_SOURCES = frozenset({"ruling"})
# 저작권 분류용(비보호 공공저작물). 리터럴을 다시 쓰지 않는다 — 식으로만(RU26 AST).
PUBLIC_DOMAIN_SOURCES = POOL_PUBLIC_SOURCES | RULING_SOURCES
LEGAL_PROMOTE_SOURCES = POOL_PUBLIC_SOURCES          # 같은 객체(기존)

def _is_public_source(hit): return hit.get("source_type") in POOL_PUBLIC_SOURCES   # 쿼터
def _is_legal_source(hit):  return hit.get("source_type") in LEGAL_PROMOTE_SOURCES  # 승격(기존)
def _is_ruling_source(hit): return hit.get("source_type") in RULING_SOURCES
def is_public_domain(hit_or_meta): return hit_or_meta.get("source_type") in PUBLIC_DOMAIN_SOURCES
```

`_is_public_source`의 의미가 "공공저작물"에서 "쿼터 집합"으로 좁아진다 — 이름은 그대로 둔다(호출부 `pipeline.py:4036`·T26·`_apply_public_quota`·`_ensure_public_quota`가 전부 쿼터 의미로 쓴다). 공공저작물 판정 술어 `is_public_domain`은 저작권 분류용으로 두되 **현재 런타임·평가 스크립트 소비자는 없다**(`eval_corpus_mix.classify`는 D20대로 `RULING_SOURCES`·`POOL_PUBLIC_SOURCES`를 직접 읽는다) — 회귀는 RU10.

### 3.2 킬스위치(D1·D9·D10)

```python
def _ruling_retrieval_enabled() -> bool:
    """RULING_RETRIEVAL=off → 검색 결과에서 재결례 제외(재배포 반영, 데이터 불변). BM25 메모리는 줄지 않는다."""
    return os.getenv("RULING_RETRIEVAL", "on").strip().lower() != "off"

def _ruling_cap_enabled() -> bool:
    """RULING_CAP=off → 총량 상한만 끈다(재결례 자체는 유지)."""
    return os.getenv("RULING_CAP", "on").strip().lower() != "off"

def _exclude_rulings_if_disabled(hits: list[dict]) -> list[dict]:
    if _ruling_retrieval_enabled():
        return hits
    kept = [h for h in hits if not _is_ruling_source(h)]
    if len(kept) != len(hits):
        logger.info("RULING_RETRIEVAL=off: 재결례 %d건 제외", len(hits) - len(kept))
    return kept
```

`search_hybrid`에서 — `dense_hits = _exclude_rulings_if_disabled(search_pinecone_multi(...))`, `per_query = [_exclude_rulings_if_disabled(search_bm25(q, top_k=top_k)) for q in queries[:3]]`. RRF·`_with_public_quota`는 그 뒤다. 끄면 컨텍스트에 재결례가 0건이라 `uses_ruling`이 거짓이 되고 `RULING_CITATION_RULES` 접미·`rag_sources.ruling`이 자연히 사라진다. 인용 검증은 화이트리스트가 비어 재결 번호를 전부 환각으로 제거한다(의도된 동작).

끄지 못하는 것(CLAUDE.md에 명시): BM25 코퍼스 메모리(gz에 11,415문서 — CI RSS 490MB 불변). 필터는 `search_pinecone_multi` 반환값에 걸리므로 `search_hybrid` 안에서는 `source_type` 지정 여부와 무관하게 적용된다 — 빠져나가는 것은 `search_pinecone*`를 직접 부르는 호출부뿐이고 그런 호출부는 없다(rev2 L6). **Cohere 키가 없는 경로는 `rerank_results`를 부르지 않아 상한(D4)이 적용되지 않는다**(`pipeline.py:4016`, rev2 L5) — 킬스위치는 그 경로에도 걸린다.

### 3.3 재결례 총량 상한 — 교체형(D4·D12·D13)

```python
RULING_CAP_DIVISOR = 2

def _ruling_cap(top_n: int) -> int:
    """최종 top_n에 남길 재결례 최대 건수 — 3→1, 5→2, 7→3, wider 10→5(wider는 COMPLEX에서만 돌아 7+3). 0이 되지 않는다(G1 공급률)."""
    return max(1, top_n // RULING_CAP_DIVISOR)

def _cap_rulings_in_top_n(selected: list[dict], ranked: list[dict], top_n: int) -> list[dict]:
    """top_n의 재결례가 상한을 넘으면 초과분(rerank 하위부터)을 비재결 후보와 **교체**한다.

    차감이 아니다 — 총 건수 불변(I-1). 후보 순서(D12): ① 전체 ranked의 quota_injected 공공(순위순 — 공공 전용
    조회의 상위라 품질 근거가 있다, 2단과 같은 이유) → ② top_n 밖 전체 ranked의 자연 유입 공공(Act-2 A — 창에 묶지 않는다) → ③ 창(top_n ~ FACTOR×top_n)의 상담.
    해설서는 후보가 아니다(노출 증가는 저작권 재검토 대상). 후보가 없으면 남은 재결례를 그대로 둔다(강제 공백
    없음). 교체분은 promoted="ruling-cap"(I-7 적용·계측 마커). 유지되는 재결례는 rerank 상위 cap건.

    ①이 필요한 이유: 2단(_ensure_public_quota)은 비승격 상담 ≥ 3건에서만 돌고 재결례·승격분을 victim 삼지 않아,
    재결례 위주 top_n에서는 quota_injected 공공이 들어갈 길이 없었다(rev2 H1 — 재생 공공 0건 문항 5/18 불변).
    """
    if not _ruling_cap_enabled():
        return selected
    cap = _ruling_cap(top_n)
    ruling_idx = [i for i, h in enumerate(selected) if _is_ruling_source(h)]
    if len(ruling_idx) <= cap:
        return selected
    chosen = {h["id"] for h in selected}
    injected = [h for h in ranked
                if h.get("quota_injected") and not _is_ruling_source(h) and h["id"] not in chosen]
    window = ranked[top_n: top_n * TEXTBOOK_PROMOTE_WINDOW_FACTOR]
    natural_public = [h for h in ranked[top_n:]                                 # Act-2 A — 창에 묶지 않는다
                      if h["id"] not in chosen and _is_public_source(h) and not h.get("quota_injected")]
    counsel = [h for h in window if h["id"] not in chosen and is_counsel_source(h)]   # 상담은 창 안만
    candidates = injected + natural_public + counsel     # 각 부류 안은 rerank 순
    result = list(selected)
    swapped = 0
    for i in reversed(ruling_idx[cap:]):          # 하위 재결례부터, 인덱스 보존을 위해 역순
        if not candidates:
            break
        cand = candidates.pop(0)
        result.pop(i)
        result.append(dict(cand, promoted="ruling-cap"))
        swapped += 1
    if swapped:
        logger.info("재결례 총량 상한: %d건 교체 (%d → %d/%d, top_n=%d)",
                    swapped, len(ruling_idx), len(ruling_idx) - swapped, cap, top_n)
    return result
```

불변식: 길이 불변 · 재결례 ≥ 1(상한이 0을 만들지 않는다) · 교체분은 말미(승격과 같은 규약 — 재랭커 기준 더 약한 문서라 순위를 속이지 않는다) · 후보 없으면 무변경 · 원본 dict 비변이(사본에만 마커) · 해설서 건수 불변(후보 아님) · 상담은 줄지 않는다(victim은 재결례뿐). ①로 들어온 항목은 `quota_injected`와 `promoted`를 함께 가지므로 2단의 `have`에 공공으로 세어지고 후보(`chosen` 밖)에서는 빠진다 — 중복 주입이 없다.

### 3.4 `_finalize` 순서(D11)

```python
def _finalize(ranked):
    selected = ranked[:top_n]
    selected = _cap_rulings_in_top_n(selected, ranked, top_n)        # ① 재결 상한 — 초과 재결례를 후보와 즉시 교체(빈자리 없음)
    if _pool_quota_enabled():
        selected = _ensure_public_quota(selected, ranked, top_n)     # ② 2단 — quota_injected 공공을 상담 victim과 교체(①의 공공은 have에 센다)
    if not ensure_textbook:
        return selected                                              # A/B 기준선 arm(승격 2종만 끈다)
    if _textbook_promote_enabled():
        selected = _ensure_source_presence(selected, ranked, top_n, lambda h: bool(_book_id_of(h)), "textbook")
    if _legal_promote_enabled():
        selected = _ensure_source_presence(selected, ranked, top_n, _is_legal_source, "legal")
    return selected
```

세 exit(성공·무키·예외) 공통(파이프라인의 Cohere 무키 경로는 이 함수를 부르지 않는다 — §3.2). ②가 ①의 교체분을 다시 바꾸지 않는 이유는 ②의 victim이 **상담이면서 `promoted`·`quota_injected`가 없는** 항목으로 한정되기 때문이고, ①이 넣은 공공은 ②의 `have`에 세어진다. ③·④는 I-7(`promoted` 제외)이 막는다. 재결례 위주 top_n(비승격 상담 < 3)에서 ②는 돌지 않는다 — 그 자리는 ①이 `quota_injected` 공공으로 메우며, 그 공공이 pool에 있으려면 1단(D22)이 재결례를 victim 삼아 주입해야 한다. 세 단계(D22 → ① → ②)가 한 줄로 이어진다. 

### 3.5 다양성 클래스(D3)

```python
def _diversity_class_of(hit):
    if _book_id_of(hit):        return _book_id_of
    if _is_legal_source(hit):   return _is_legal_source
    if _is_ruling_source(hit):  return _is_ruling_source
    return None
```

I-9: 재결례가 1건만 남으면 ③·④의 victim이 되지 않는다. 법률근거 클래스의 마지막 1건(판례 등)도 재결례와 **별개로** 보호된다 — 현행은 재결례가 법률근거 클래스에 들어가 "재결례 1 + 판례 1"이 같은 클래스 2건으로 세어져 어느 쪽도 보호받지 못했다.

### 3.6 1단 쿼터 victim 확장(D22)

```python
POOL_RULING_FLOOR_DIVISOR = RULING_CAP_DIVISOR      # pool에 남길 재결례 최소 = max(1, top_k // 2) — 상한과 같은 비율

def _pool_ruling_floor(top_k: int) -> int:
    return max(1, top_k // POOL_RULING_FLOOR_DIVISOR)

def _apply_public_quota(hits, public_hits, top_k):
    ...
    for cand in public_hits:
        if have + added >= quota: break
        if cand["id"] in seen: continue
        counsel = [i for i, h in enumerate(merged) if is_counsel_source(h)]
        if len(counsel) > MIN_COUNSEL_IN_POOL:
            merged.pop(counsel[-1])                       # ① 점수 최하위 상담부터(기존)
        else:
            rulings = [i for i, h in enumerate(merged) if _is_ruling_source(h)]
            if len(rulings) <= _pool_ruling_floor(top_k):
                break                                     # ③ 둘 다 하한이면 중단(강제 공백 없음)
            merged.pop(rulings[-1])                       # ② pool 상한 초과 재결례, 점수 최하위부터
        merged.append(dict(cand, quota_injected=True)); seen.add(cand["id"]); added += 1
```

지킬 것: `hits`는 `search_hybrid`가 점수 내림차순으로 넘기므로 `[-1]`이 최하위다(기존 상담 victim과 같은 전제). 해설서는 어느 단계에서도 victim이 아니다(T26-b·b2 불변). 상담 하한(T26-d)·pool 크기 불변(T26-c)·부족분만 채움(T26-a)·후보 없으면 무발동(T26-e)은 그대로다. 재결례 하한 `top_k//2`는 S+의 재결례 공급을 지키기 위한 것이고(pool 15에 7 이상 남는다), 재결례가 하한 이하인 pool에서는 기존과 완전히 같다 — R(pool 재결례 4건 이하)·S−·adjudication 이전 fixture 전부 무영향. 재결례 victim이 들어간 pool은 그 자체로 "재결례가 쿼터를 밀어낸" pool이라 로그에 `재결례 victim N건`을 남긴다.

## 4. 소비자 정합

| 소비자 | 영향 | 조치 |
|---|---|---|
| `pipeline.py` Self-RAG 복원 | 쿼터 집합 공공만 복원(재결례 아님) | Act-2 C: 헬퍼 `_restore_public_after_self_rag`로 목표 건수까지 복원(D14 rev3, RU32·RU35·T26-s) |
| `pipeline.uses_ruling`·`RULING_CITATION_RULES`·`rag_sources` | 컨텍스트 기준이라 불변 | 없음 |
| `conflict_resolver` 3항·`citation_validator` 재결 패턴 | 무관 | 없음 |
| `eval_corpus_mix.classify`·집계 | 재결례가 'other'로 떨어질 위험, 재결례 섞인 공공 비율은 무효 지표 | `ruling` 별도 분류, 공공·도달은 비재결(D15·D20) |
| `eval_colloquial.py:55·117` | `LEGAL_CORPUS_SOURCES` 리터럴에 `ruling`, 법률 근거 수(`LEGAL_PROMOTE_SOURCES`)에서 재결례 제외 | 리터럴 → 파생식(D21). 집계 의미 변화는 Report에 기록 |
| `eval_retrieval.py` | `top_n=len(hits)` 호출이라 상한·2단 무발동 — 영향은 D2(pool 구성)·D3(승격 arm의 victim 선택)뿐 | 기준선 재측정으로 비회귀 확인(G6, rev2 M2) |
| `pinecone_upload_regulations.py:7` docstring | 서술만 | 없음 |

## 5. 테스트 — `test_rulings_ingest.py`(오프라인, CI)

| ID | 검사 |
|---|---|
| RU10(개정) | `"ruling" not in POOL_PUBLIC_SOURCES`, `PUBLIC_DOMAIN_SOURCES == POOL_PUBLIC_SOURCES \| RULING_SOURCES`, `LEGAL_PROMOTE_SOURCES is POOL_PUBLIC_SOURCES`, `_is_public_source(ruling)`·`_is_legal_source(ruling)` 거짓, `is_public_domain(ruling)` 참, `_diversity_class_of(ruling) is _is_ruling_source` |
| RU26 | AST: `rag.py`의 집합 리터럴(`frozenset({...})`·`set(...)`·`{...}` `ast.Set` 모두) 중 `"precedent"`를 담은 것은 **하나**, `"ruling"`을 담은 것은 **하나**, `PUBLIC_DOMAIN_SOURCES`는 `BinOp(\|)`로 정의(rev2 L4) |
| RU27 | 킬스위치: `RULING_RETRIEVAL=off`에서 `search_hybrid`가 재결례 0건을 돌려주고 비재결 건수는 보존, `on`·알 수 없는 값은 불변. mock은 `rag.search_pinecone_multi`·`bm25_search.load_bm25_corpus`(True)·`bm25_search.search_bm25`·`rag._fetch_public_hits` — `load_bm25_corpus`를 막지 않으면 실제 gz(29MB, RSS 490MB)를 읽는다(rev2 L4). Dense-only 경로(`load_bm25_corpus` 예외)도 같은 결과. `$in` 집합 검사는 `_fetch_public_hits`를 가짜 openai 클라이언트·`_query_namespaces` mock으로 따로 불러 넘어온 집합에 `ruling`이 없음을 본다 |
| RU28 | 상한 값 `_ruling_cap`: 1·2·3·3·4·5(top_n 3·5·7·6·8·10 — 6·8은 함수값 검증용, 실제 경로는 3·5·7·10). `_cap_rulings_in_top_n` 불변식: 길이 불변, 재결례 수 = cap, 유지분은 rerank 상위, 교체분 말미 + `promoted="ruling-cap"`, 후보 ① 창 밖 주입 공공 → ② top_n 밖 자연 공공(창 밖 포함 — Act-2 A 사례 `prec_far`) → ③ 창 안 상담(창 밖 상담은 후보 아님), 해설서 제외, 후보 없음 → 무변경, 원본 비변이, **상담·해설서 건수 비감소**, `RULING_CAP=off` → 무변경 |
| RU29 | 순서(통합, 무키 exit): ranked = 재결례 4 + 상담 1 + **창 밖(순위 ≥ 2×top_n)에 `quota_injected` 판례** → `rerank_results(..., cohere_api_key="")` 결과에 재결례 = cap, 그 판례가 `promoted="ruling-cap"`으로 들어옴(2단으로는 못 들어오는 배치 — rev2 H1), 길이 top_n, 해설서 0건 유지. 예외 exit(mock cohere raise)·성공 exit(`test_llm_transport.py:334~352` 패턴의 mock rerank)도 같은 결과 |
| RU30 | I-9 재결례 보호 — **전원 단일 출처** fixture `[qa, ruling, precedent]`: 현행(재결례가 법률근거 클래스)은 precedent(인덱스 2)를 고르고, 신규는 재결례·판례가 각자 클래스의 마지막 1건이라 qa(0)를 고른다(rev2 M3 — `[ruling, qa, qa, precedent]`는 중복 qa 규칙이 먼저 걸려 현행도 통과한다). 재결례 2건이면 하위 재결례가 victim 후보 |
| RU31 | `eval_corpus_mix.py`·`eval_colloquial.py`를 **AST로**(import하면 `load_dotenv(override=True)`가 돈다 — RU25와 같은 이유): `classify`가 `"ruling"` 분기를 갖고 `RULING_SOURCES`·`POOL_PUBLIC_SOURCES`를 모두 참조하며, `totals`·`counts`에 `"ruling"` 키가 있고, `LEGAL_CORPUS_SOURCES`가 리터럴이 아니라 `PUBLIC_DOMAIN_SOURCES`에서 파생(D20·D21) |
| RU32 | `pipeline.py` Self-RAG 복원 배선(AST): `_restore_public_after_self_rag` 호출 1곳(첫 인자 `_before_self_rag`), 헬퍼가 `_is_public_source`·`_pool_public_quota_for_top_n`을 쓰고 `is_public_domain`·`_is_ruling_source`는 쓰지 않으며, 옛 '전멸 시 1건' if 분기가 없다 |
| RU35 | `_restore_public_after_self_rag`: 전부 제거 → 목표(top_n 7 → 2)까지 rerank 순 복원·말미, 1건 남으면 1건만, 목표 충족 시 무변경, SIMPLE(top_n 3) 목표 1, 재결례만 제거면 복원 없음, before에 공공 없으면 무변경 |
| RU33 | CLAUDE.md: "킬스위치는 **없다**" 문자열 부재, `RULING_RETRIEVAL`·`RULING_CAP` 언급 존재, **공공 쿼터 절("공공저작물 쿼터는 2단이고" 글머리부터 다음 글머리 전까지) 안에** '초과 재결례' victim 서술, 다양성 승격 절에 재결례 승격 부재 서술 |
| RU34 | 1단 victim 확장(D22): pool `[R×13, C×2]` + 공공 후보 4 → 주입 = quota(top_k 15 → 3), 상담 2 유지, 재결례 13 → 10(최하위 점수부터 제거), 해설서 없음 유지, pool 크기 불변; pool `[R×7, C×2]`(하한)·`[R×3, T×5, C×2]`는 주입 0(기존 동작과 동일); `[C×8]`은 기존대로 상담 victim; `[R×13, C×5]`는 상담 3건을 victim으로 써서 quota 3을 채우고 재결례는 0건 victim(상담 5 → 2, 재결례 13 유지); `[R×13, C×3]`은 상담 1건(3 → 2, 하한) 뒤 재결례 2건 |
| T24-a4(수정) | `LEGAL_PROMOTE_SOURCES == {"precedent", "interpretation", "regulation"}` |

T26-s는 새 배선(`_restore_public_after_self_rag(` 호출)으로 고친다. 그 밖의 T23·T24·T26·RU11~RU25는 그대로 통과해야 한다(상한·D22는 재결례가 없는 fixture에서 무발동 — T26-d `[qa, qa, tb]`는 상담 하한 뒤 재결례 0건이라 그대로 중단).

## 6. 측정 (저장소 밖 `~/DEV/laborconsult_eval/rul/`)

### 6.1 spy 확장(D17) — `run_eval.py`

`format_hits(*a, **k)`에서 입력 `a[0]`의 `[{"id", "source_type", "promoted", "quota_injected"}]`를 `cap["rag_hits_in"]`에 기록하고 `run` 기록 키에 추가한다. `rag_meta`는 그대로(최종 컨텍스트 — 지표의 기준).

### 6.2 지표(`compare_rqc.py` — `compare_rul.metrics` 재사용 + 확장)

| 지표 | 정의 |
|---|---|
| M1 | S+·R 중 `ruling` 포함 문항 비율, S− 포함 문항 목록(기존) |
| M1b | 재결례 뺀 공공 건수 합(S+·R, 기존) |
| **M1c** | 공공(비재결) 0건 문항 수(S+·R) |
| **M1d** | 판례 0건 문항 수(S+·R, 참고) |
| **M1e** | 재결례 ≥ 2건 문항 수, 서로 다른 재결 수(**`rag_hits_in.id` 접두사 `ruling_{agency}_{serial}` 우선, 없으면(after 기록) `rag_meta.title` 앞 60자** — `case_no`는 BM25 경로에서 비어 있다, rev2 M6) |
| M2 | 인용 정확(기존 — 교정 전 환각·교정 후 잔여·비재결 오판·유효 재결 인용) |
| M3·M4 | 쟁점 한정 유보·K 금지(기존) |
| **M5** | `rag_hits_in`의 `promoted` 마커 분포(`ruling-cap`·`public-quota`·`legal`·`textbook`), `quota_injected` 건수 — **cap1·cap2에만** 있고(after에는 필드 없음) COMPLEX는 Self-RAG·wider 뒤 목록이라 따로 집계한다(rev2 L7 — 복잡도가 기록에 없어 **슬롯 ≥ 7을 COMPLEX proxy**로 쓴다). `rag_meta_missing` 판정에 신규 필드는 넣지 않는다 |

### 6.3 관문(`gates_rqc.json` — G1~G5는 두 실행 각각 자동 판정, G6·G7은 §13 수기)

| 관문 | 판정 |
|---|---|
| G1 | S+ M1 ≥ 0.80, S− 0 |
| G2 | S+ M1b ≥ 34 **그리고** S+ M1c ≤ 2 |
| G3 | R M1c ≤ 4 **그리고** R M1b ≥ 68 |
| G4 | M2 교정 후 잔여 0·비재결 오판 0, 유효 재결 인용 ≥ 10 |
| G5 | K 금지 0·`allowed_source` 거짓 0·S+ 일반화 금지 0·벤더 동일·spy 누락 0 |
| G6(검색 전용) | `eval_retrieval` 도달률 불변(기준선 재측정 대비), `eval_corpus_mix` 기본 모드 **비재결** 공공 ≥ 기준선 2026-08-23(재결례 없던 때라 같은 정의, D20) |
| G7(오프라인) | 스위트 전부 + RU10·RU26~RU35·T24-a4·T26-s |

### 6.4 절차·비용(D7·D18)

1. worktree 코드로 `run_cap.sh`(run_after.sh 복제, `--repo ../laborconsult-rqc`, runs/cap1·cap2) — 98문항 × 2 = **196답변**, gpt-6-sol, `--law-mode cache --primary openai`. **실행 직전 사용자 승인.**
2. `compare_rqc.py --base after1,after2 --cap cap1,cap2` → `gates_rqc.json`·`report_rqc.md`.
3. 경계면 base 재측정 1회(+98) — 승인 별도.
4. 검색 전용(비용 미미): `eval_retrieval.py`(기준선 arm 포함 재측정), `eval_corpus_mix.py` 기본 모드, §1.3 재생 스크립트를 **실제 코드**로 재실행(시뮬레이션과 일치 확인).
5. **Act-2 재측정**(사용자 승인 2026-11-09 "재측정 진행"): `run_act.sh` — S+·S−(synthetic 24) ×2 → `runs/act1·act2`, R(real_pos 52) ×1 → `runs/act1`, 합계 **100답변**(같은 모델·모드). K 22문항은 재측정하지 않는다 — Act-2는 K 경로의 재결례 구성에 영향이 작고, G5의 K 부분은 cap1·cap2 결과를 유지한다(보고서에 '유지'로 적는다). 판정은 `compare_rqc.py --cap act1,act2 --allow-partial`(base after1·after2) + `--base cap1,cap2`(Act-1까지와 직접 대조). `--allow-partial`은 R·K 집합이 없는 실행에서 **G3·G4 인용 임계·G5 K를 그 집합이 있는 실행만으로 판정하고 '미측정'을 관문 내용에 적는다** — 없는 집합을 0으로 세어 관문을 통과·실패시키지 않으며, 플래그 없이 집합이 빠지면 exit 2다. **K가 cap 실행 전부에 없으면 `--k-from cap1,cap2`로 K 판정에 쓸 실행을 지정한다** — 지정하지 않으면 G5의 K 부분은 '미판정'으로 표기되고 G5는 통과하지 못한다(공허 참으로 통과시키지 않는다, Check 재실행 E14)(기본 모드는 cap1·cap2 보고의 관문 판정·내용·지표를 동일하게 재현 — G4 라벨에 '(R 포함 실행)'이 붙은 것만 다르다, 회귀 확인함). 문항별 진단은 `act_diag.py`(로그의 Self-RAG 제거 합·'공공 근거 N건 복원' 이벤트(C 발동)·wider 횟수, S+ 문항별 R/P/C/T 구성과 마커, R 공공 변화 문항).

## 7. CLAUDE.md 변경

- 재결례 절 R4 문단(현 415행): "재결례는 쿼터·승격 **집합 밖**이다(집합 3종 `POOL_PUBLIC`·`RULING`·`PUBLIC_DOMAIN`, 파생 하나) — 재결례가 있어도 판례·행정해석 쿼터·승격이 돈다. 최종 top_n의 재결례는 `max(1, top_n//2)`까지, 초과분은 ① 전체 랭킹의 `quota_injected` 공공 → ② top_n 밖 전체 자연 공공 → ③ 창 안 상담과 **교체**(차감 아님·해설서 제외, 순서 상한 → 2단 → 승격). 킬스위치 `RULING_RETRIEVAL=off`(검색 제외, BM25 메모리는 불변)·`RULING_CAP=off`(상한만). Cohere 키 없는 경로에는 상한이 없다. 데이터 롤백은 최후 수단." — 재생의 "R 재결례는 쿼터 조회 산물"(pool 117 → 4)은 실사용에서 `quota_injected`로 확인할 수 없다(D8 뒤 재결례는 주입되지 않는다). 간접 근거 after → cap·act R 재결례 공급 0.27 → 0.13·0.23을 **범위로** 적는다(M7).
- RAG Pipeline의 Self-RAG 항목: "필터 뒤 `pipeline._restore_public_after_self_rag`가 쿼터 집합 공공(판례·행정해석·훈령)을 2단 목표 건수까지 되살린다 — 승격·교체분은 rerank 하위라 판정 모델이 자주 걸러낸다"(Act-2 C).
- Environment Variables(Optional): `RULING_RETRIEVAL`·`RULING_CAP` 두 줄(`LAW_API_LIVE` 뒤). `RULING_CAP=off`는 재결례 포화 pool에서 주입 공공이 top_n에 못 드는 조합임을 적는다.
- 공공 쿼터 절(476행): "재결례는 쿼터를 **충족하지 않는다**(쿼터 집합 밖). 1단 victim은 **상담(하한 2) → pool 상한(`top_k//2`) 초과 재결례**다 — 산재 질문은 pool이 재결례로 포화돼(15건 중 14~15) 상담 victim만으로는 주입 0건이었다(ruling-quota-cap 재생). 2단은 상담 victim 그대로이고 재결례 위주 top_n에서는 상한이 주입 공공을 끌어온다. 공공저작물 분류는 `is_public_domain`."
- 다양성 승격 절(482행): I-9 클래스 **3종**(해설서·법률근거·재결례). 재결례 승격은 두지 않는다(S−·R 유입 — ruling-quota-cap D19 폐기).

## 8. 실행 순서(Do)

1. worktree `../laborconsult-rqc`(브랜치 `feat/ruling-quota-cap`, base main c4a5f1a), `.env` 링크.
2. `rag.py` §3 구현(3.1~3.6) → `eval_corpus_mix.classify`·`eval_colloquial` 리터럴 → RU10·T24-a4 개정·RU26~RU34 → `.venv/bin/python test_rulings_ingest.py`·`test_precedent_ingest.py`·`test_offline_units.py`·`test_kin_accuracy.py`.
3. 검색 전용 재생을 실제 코드로 재실행(§1.3 대조) → 상한 값 확정 유지 여부.
4. `eval_retrieval.py`·`eval_corpus_mix.py` 기준선 재측정(G6).
5. 킬스위치 양성 검증: `RULING_RETRIEVAL=off`로 S+ 3문항 재생 → 재결례 0건.
6. **측정 승인(D7)** → cap1·cap2 → `compare_rul.py` → 관문.
7. CLAUDE.md §7, Design §13 실측 기록.
8. 커밋·PR(요청 시) → CI → 리뷰 반영 → 머지 → 배포 → 실사용 `metadata.rag_sources`로 사후 분포 확인.
9. `/pdca analyze` → Report → Archive.

## 9. 위험·완화

| 위험 | 완화 |
|---|---|
| 상한이 G1(재결 공급률)을 깎는다 | `cap ≥ 1`, 교체 대상은 재결례 초과분만, I-9 보호. G1 관문 유지 |
| 집합 드리프트(A-10) | 리터럴 2개 + 파생 1개, RU26 AST, RU10·T24-a4 |
| `eval_corpus_mix` 공공 비율이 조용히 하락 | D15·RU31 |
| 교체 후보 부재로 상한 무효 | 마커 0건·M5로 보인다. rev2는 후보 1순위를 창 밖 `quota_injected`까지 넓혔다(D12) — 재생 v2로 확인 |
| 2단이 재결례 위주 top_n에서 돌지 않는다(비승격 상담 ≥ 3 조건) | 설계된 한계 — 그 자리는 상한 ①이 메운다. 재결례가 cap 이하라 상한이 돌지 않으면서 상담 < 3인 top_n은 공공이 자연 유입분뿐이다(관측 M1c) |
| 2단이 상담을 하한(2건)까지 밀어낸다 | 기존 하한·victim 규칙 불변. 상한은 상담을 victim 삼지 않는다 |
| 측정 편차(동일 조건 42 vs 53) | 두 실행 각각 판정, 경계면 base 1회(D18) |
| Self-RAG가 재결례를 전부 걸러도 복원 없음(D14) | 설계된 동작 — M1·마커로 관측 |
| 킬스위치 후처리로 pool이 줄어든다 | 비상 복귀 수단. CLAUDE.md에 명시 |
| 킬스위치가 BM25 메모리를 줄이지 않는다 | CLAUDE.md에 명시 |
| 분리로 S+ 재결례 공급이 G1(0.80) 아래로 떨어진다(재생 0.83, 승격은 폐기) | 프로덕션 분해 쿼리는 원문 쿼리보다 재결례를 높이 올린다(after M1 0.94·0.89). G1 관문으로 보고, 미달이면 Act에서 다룬다(정의 변경 아님) |
| 1단 재결례 victim(D22)이 S+ pool의 재결례를 과하게 줄인다 | 하한 `top_k//2`(15 → 7)·부족분(quota − have ≤ 3)만 교체. 재생 v3 pool 재결례 수로 확인 |
| 상한의 교체분이 상담이라 공공 구성이 늘지 않는다 | 설계된 한계 — 공공 건수는 쿼터가 정한다(§1.3). 상한의 목적은 재결례 일색 방지 |
| 집합 분리가 S−·R에서 재결례를 전부 없앤다(27% → 자연 유입분) | 의도된 결과 — 그 공급은 관련성이 아니라 쿼터 조회 산물이었다. Report에 adjudication-corpus G1 참고치 재해석을 기록 |

## 10. 완료 조건(DoD)

1. §3 구현 + §5 테스트 통과(`.venv/bin/python`), 기존 스위트 비회귀.
2. §1.3 재생을 실제 코드로 재확인(변형 C3과 일치 — S+ 공공 0건 문항 수·주입 건수).
3. G6 검색 전용 비회귀 기록.
4. P1 측정 cap1·cap2 — G1~G5 판정·기록(미달이 있어도 정의를 바꾸지 않는다).
5. 킬스위치 양성 검증 기록.
6. CLAUDE.md §7, Design §13.
7. PR·CI·머지(요청 시), Vercel env 변경 없음.
8. Act-2(A+C) 뒤 재측정 act1·act2(§6.4 5항) — G1~G5 재판정·G6·G7 재확인 기록(§13). **2026-11-09 충족.**

## 11. 범위 밖·후속

- 데이터 변경·BM25 재빌드·`rerank_top_n`·쿼터 수치·`MIN_COUNSEL_IN_POOL`.
- D5 문서당 상한(보류 — §1.3 판단), B-5 `agency` 메타, B-8 OCR, `stale_rules` 산재, nlrc, 고정 IP.
- 판례 공급 확대(판례 0건 문항은 before부터 14·15).

## 12. 검증(design-validator rev1) 처리표

73점(High 1·Medium 7·Low 9). 전부 코드로 재현했다.

| ID | 지적 | 처리 |
|---|---|---|
| H1 | "상한이 자리를 비우면 2단이 채운다"는 틀렸다 — 상한은 즉시 교체, 교체분은 2단 victim 아님, 2단은 비승격 상담 ≥ 3에서만. 공공 0건 S+ 5건 불변 | **반영** — D12 후보 1순위를 전체 랭킹의 `quota_injected` 공공으로, D11 근거 교정, RU29에 창 밖 주입 판례 fixture, 재생 v2로 효과 확인(§1.3) |
| M1 | D19 공용 몸체의 victim 규칙이 자연 유입 판례를 지운다; S− pool 재결례 1건 | **반영 → D19 폐기** — victim을 상담으로 한정한 판으로 재생 v2를 돌렸더니 S−에 1건·R에 2건이 들어가 G1(S− 0)이 깨졌다(§1.3) |
| M2 | `eval_retrieval`은 `top_n=len(hits)`라 상한 무발동 — D11 근거 오류, §4에 D3 영향 누락 | **반영** — D11·§4 교정 |
| M3 | RU30 fixture가 현행 코드도 통과 | **반영** — 전원 단일 출처 `[qa, ruling, precedent]` |
| M4 | 상한 후보에 해설서 — 저작권 검토 없는 노출 증가 | **반영** — 후보에서 해설서 제외(D12·§3.3·RU28) |
| M5 | `eval_corpus_mix` 재결례 섞인 공공 비율은 무효 지표(직전 M11), 도달 정의 불일치 | **반영** — D20 `ruling` 별도 분류, G6 비재결 공공 |
| M6 | BM25 경로 `case_no` 빈 문자열 — 서로 다른 재결 수 과소 | **반영** — D16·M1e 키를 `id`·`title`로, §1.1·§1.3 키 명시 |
| M7 | "R 재결례 27%는 쿼터 산물"은 재생 추론 — 실사용과 규모 다름 | **반영** — 표기 낮춤. CLAUDE.md에는 after → cap·act R 재결례 공급 0.27 → 0.13·0.23 범위로 적음(`quota_injected`로는 확인 불가 — D8 뒤 재결례 미주입, Check 재실행 G10) |
| L1 | R은 SIMPLE 0(MODERATE·COMPLEX) — 2단 목표 2건 | **반영** — §1.1 경로 ① 서술을 pool 쿼터 충족·조회 생략으로 교정, Plan §1.1 정정 주석 |
| L2 | "추가 조회 0회" — 조기 반환이 사라지는 문항은 조회 1회 추가 | **반영** — 결정 D2 문구, Do 지연 기록 |
| L3 | 교체 수와 재결례 감소량 불일치 | **반영** — 집계 기준(finalize 안 vs format 뒤) 명시, v2는 둘 다 기록 |
| L4 | RU27 gz 로드·`$in` 캡처 방법, RU31 import 부작용, RU26 `ast.Set` | **반영** — §5 |
| L5 | Cohere 무키 경로에는 상한·승격 없음 | **반영** — §3.2·§7 |
| L6 | 킬스위치 "명시 조회" 문구 부정확 | **반영** — §3.2 |
| L7 | spy 입력은 Self-RAG·wider 뒤, base에 신규 필드 없음 | **반영** — M5 범위·누락 판정 |
| L8 | `eval_colloquial` `LEGAL_CORPUS_SOURCES` 리터럴, §3.6 마커 집계 서술 오류, docstring | **반영** — D21, §3.6 재작성 |
| L9 | 내부 불일치(RU 번호·env 수·D4/D11 D19 누락·줄 번호·Plan §13 참조·wider 6·8·D19 과장·D5 근거) | **반영** — 전부 정리(wider는 COMPLEX만 돌아 7+3=10 → cap 5) |

재생 v2·v3(§1.3)로 더 바뀐 것: **D19 폐기**(S−·R 유입), **D22 신설**(1단 victim 확장 — 공공 0건 S+ 4문항의 pool이 재결례 포화라 주입 0건이던 원인).

## 13. Do 실측 기록 (2026-11-09)

| 단계 | 결과 |
|---|---|
| 구현(worktree `../laborconsult-rqc`, feat/ruling-quota-cap, base c4a5f1a) | `app/core/rag.py` +142/−15(집합 3종·술어·스위치 2종·`_exclude_rulings_if_disabled`·`_pool_ruling_floor`·1단 victim 확장·`_cap_rulings_in_top_n`·`_finalize` 순서·`_diversity_class_of`·로그), `eval_corpus_mix.py`(ruling 분류·집계), `eval_colloquial.py`(파생 집합), `test_rulings_ingest.py`(RU10 개정·RU26~RU34), `test_precedent_ingest.py`(T24-a4), `CLAUDE.md` 4곳. 6파일 +390/−33. **미커밋** |
| 오프라인 스위트(`.venv/bin/python`) | `test_rulings_ingest` **37/37 OK** · `test_precedent_ingest` 전체 통과 · `test_offline_units` 통과 · `test_kin_accuracy` 39 OK(skip 1) · `test_pipeline_wiring` 통과(Traceback 출력은 테스트의 의도된 `intentional` 예외 — main 동일) |
| 실제 코드 재생(76문항, 151초, LLM 0회) — §1.3 C3 대조 | **S+ 18**: 슬롯 94·재결례 **29**(26 재결)·공공 **31**·판례 15·상담 34·공공 0건 **0**·판례 0건 9·재결 포함 15·재결 ≥ 2 13·마커 `public-quota` 12 / `ruling-cap` 15·pool 재결례 100·주입 41 — **C3와 전 항목 일치**. **S− 6**: 재결례 0·공공 12. **R 52**: 재결례 0·공공 103·공공 0건 0. 산재 4문항: `r-ia-eye` 재결 2·공공 3(pool R 14 → 11, 주입 3, 교체 3), `r-ia-msk` 2·2(13 → 10), `r-ia-grade-finger` 2·2(12 → 10), `r-ia-grade-brain` 2·3(15 → 12) |
| 킬스위치 양성 검증 | `RULING_RETRIEVAL=off` 3문항 → pool·컨텍스트 재결례 **0**(`r-ins-coop` 공공 3/5, `r-elig-quit` 공공 2/5). `r-ia-eye`는 pool이 재결례 일색이라 제외 뒤 컨텍스트 **1건**(공공 0) — 재결례 포화 질의에서 스위치는 pool을 비운다(비상 복귀 수단의 한계, CLAUDE.md에 적음). `RULING_CAP=off` 2문항 → 재결례 4·5, 공공 1·0(주입 3은 됐으나 top_n에 못 듦 — §1.3 B3 재현) |
| G6 `eval_corpus_mix --baseline`(worktree, 기본 모드) | 비재결 공공 **16**(기준선 2) · 재결례 0 · 해설서 0(기준선 3) · 상담 28 · 법률 근거 도달 12/12 · 상담 비중 89% → 64% · 지연 p50 1.3s·p95 8.9s. ✅ |
| G6 `eval_retrieval`(고정 fixture 24, 분모 19) | main **17/19 = 89.5%**(기준선 arm 13) vs worktree **16/19 = 84.2%**(기준선 arm 11), 승격 발동 4 vs 5. 차이 3문항(q06·q07·q15) **전부 pool의 해설서 수가 −1**(6→5·5→4·2→1) — D22의 victim은 상담·재결례뿐이고 상한은 해설서를 건드리지 않으므로 pool 차이는 변경 밖 요인(임베딩·RRF 경계)으로 보인다. 변경 전후 출처 분포에 `ruling` 3 동일. **main 재측정: 16/19 = 84.2%(기준선 arm 11, 승격 5건) — worktree와 동일.** main 두 실행 사이에도 5문항(q07·q11·q14·q15·q16)의 pool 해설서 수가 ±1로 흔들렸다 → 차이는 실행 편차(임베딩·RRF 경계)다. **G6 비회귀 ✅**(worktree 84.2%는 main 밴드 84.2~89.5% 안) |
| 지연 | 미측정(D2 L2 — 재결례가 쿼터를 채워 조회를 건너뛰던 문항의 임베딩+Pinecone 1회 추가). cap1·cap2 `total_s`로 본다 |
| 측정(P1) | D7 승인 2026-11-09 "측정 진행" → `run_cap.sh` 14:41 시작. **cap1 완료**(synthetic 7.6분·real_pos 18분·kin 5분·risk 2.4분, 98답변 오류 0) → `compare_rqc.py --cap cap1`: **G1~G5 전부 ✅** — G1 S+ 0.83·S− 0(base 0.94·0.89), G2 S+ 공공 **34**(base 20·16)·공공 0건 **0**(base 8·6), G3 R 공공 0건 **2**(base 12·12)·공공 **79**(base 62·60), G4 교정 후 잔여 0·비재결 오판 0·유효 재결 인용 20, G5 K 금지 0·allowed_source 거짓 0·S+ 일반화 0·벤더 OpenAI 76/76·spy 누락 0. M1 R 0.27 → **0.13**(쿼터 주입 재결례가 사라져 자연 유입 7/52만), M1d 판례 0건 S+ 16(불변 — 판례 공급 자체는 범위 밖), M1e S+ 재결 청크 38(27 재결)/슬롯 99 = **38%**(base 64%·59%; D4 half 유지 기준 50% 이하), 재결 ≥ 2 문항 10, M3 S+ 유보 0·R 0.02, M5 마커 `ruling-cap` 14·`public-quota` 16·`legal` 16·`textbook` 3·`quota_injected` 19 |
| 측정(P1) cap2 | 15:14~17:02. **네트워크 단절 2구간**(15:29~15:46·15:46~16:39 — OpenAI·Claude·Pinecone·Cohere 전부 `Connection error`)에 걸린 real_pos `r-ue-17·18·19`가 전 제공자 실패(Gemini 폴백)로 오염 → 그 3문항만 `--cases` 재실행(3답변, 전부 OpenAI 정상)해 `patch_run.py merge`로 치환(원본 `.pre_patch` 보관), 잔여 오염 0. `compare_rqc.py`(base after1·after2, cap cap1·cap2): **G1 ✅**(S+ 0.83·0.94, S− 0) · **G2 ❌(부분)** — S+ 공공 **34·28**(기준 ≥ 34, base 20·16), 공공 0건 **0·1**(≤ 2 ✅) · **G3 ✅**(R 공공 0건 2·0, 공공 79·75 — before 72·72를 넘는다) · **G4 ✅**(잔여 0·오판 0·유효 재결 인용 20·27) · **G5 ✅**. cap2 M1e S+ 재결 57청크(38 재결)/슬롯 109 = **52%**(cap1 38%) — cap2는 COMPLEX·wider 문항이 많아 슬롯이 99 → 109. M3 S+ 유보 0·0.06, R 0.02·0.02. 지연 `total_s` 문항당 15~28초(after와 같은 범위 — D2 추가 조회의 체감 지연 없음) |
| **종합 판정** | 5관문 중 4 통과, G2는 공공 0건 조건 통과·건수 조건 한쪽(cap2 28) 미달. 공공 0건 문항은 S+ 8·6 → 0·1, R 12·12 → 2·0으로 이 사이클의 핵심 목표(재결례 때문에 공공 근거가 사라지는 문항 제거)는 두 실행 모두 달성. 재결례 공급(G1)·인용 정확(G4)·K(G5)는 유지. **정의를 바꾸지 않고 기록한다**(Plan §5) |
| **진단 — cap2 공공 28의 구조적 원인** | 문항별 `rag_hits_in`: `r-ia-grade-finger`는 cap1·cap2 모두 wider(슬롯 10) 경로에서 **재결례 9·공공 1·`ruling-cap` 1·`quota_injected` 0** — 분해 쿼리 pool에 자연 공공이 쿼터 이상 있어 **1단이 조회를 건너뛰었고**(`have ≥ quota`), 그 자연 공공은 rerank에서 **창(`2×top_n`) 밖**으로 묻혀 상한 후보 ②(창 안 자연 공공)에 걸리지 않았다 — 교체 가능 후보 1건뿐. `r-ia-family`(cap2, 7슬롯: `PRRRRRPc`, 주입 0)도 같은 꼴(cap 3에 교체 1). 반대로 `r-ia-msk`(cap2 10슬롯, 주입 5)는 `RRRRR + P*c×5`로 설계대로 작동했다. 원문 쿼리 재생(§1.3)은 pool에 자연 공공이 거의 없어 이 경로를 보지 못했다(주입 경로만 관측). **사전 등록한 대안 E(상한 1)는 이것을 고치지 못한다** — 후보가 없으면 상한은 교체할 수 없다. 처방 후보: 상한 후보 ②를 '창 안'에서 **'top_n 밖 전체 ranked의 자연 공공(순위순)'** 으로 넓힌다 — pool 단계 RRF `top_k`를 통과한 공공이라 2단이 주입분을 창 없이 받는 것과 같은 근거이고, 구성 회복이 목적이라 rank-25 판례가 rank-8 재결례를 대체하는 것이 의도다. Check/Act에서 결정 |
| **진단 2 — Self-RAG가 구성 작업을 되돌린다** | 프로덕션 S+ 24문항은 **전부 COMPLEX**다(의도분석의 `relevant_laws`·`calculation_types`가 복잡도 점수를 올려 — 원문 쿼리 재생의 MODERATE 16과 다르다) → Self-RAG가 매 문항 돈다. 로그 집계(synthetic 24문항): 상한 교체 **28·31건**(rerank 직후) → Self-RAG 뒤 `ruling-cap` 생존 **14·15건**; 1단 주입 **15·31건**(`quota_injected`) → S+ 생존 4·9건; 2단 `public-quota` 승격 **6·6건**(synthetic 24) → S+ 생존 **1·0건**(S− 2·4) — 1차 기록은 1단 주입 수를 2단 승격으로 적었다(Check 재실행 G8 정정). "공공 전멸 → 1건 복원"(`pipeline.py:4037~4043`)은 cap1 7회·cap2 5회(after 1·2회). Self-RAG 결과 분포(cap2): 7 → 7 5문항, 7 → 6 6문항, 7 → 5 4문항, 7 → 4 5문항, 7 → 3 1문항, 7 → 2 3문항(wider 3). **쿼터·상한은 Self-RAG 앞에서 돌고, Self-RAG는 하위 순위 공공(주입·교체분)을 irrelevant로 걸러내는 경향이 강하다** — 그래서 G2 공공 건수는 rerank 직후가 아니라 Self-RAG 뒤 값이고, 두 실행 차이(34·28)는 판정 모델의 판단 편차다. 원문 쿼리 재생(§1.3)은 Self-RAG가 없어 이 경로를 보지 못했다. 처방 후보 C: Self-RAG 복원을 '전멸 시 1건'에서 **'쿼터 집합 공공이 2단 목표(`_pool_public_quota_for_top_n`) 미만이면 목표까지'** 로 — 제거된 공공을 rerank 순위대로 되살린다. 2단의 보장("컨텍스트에 실린다")을 Self-RAG 뒤까지 연장하는 것이고 D14의 복원 지점을 그대로 쓴다. 판정 모델의 판단을 2건 한도로만 뒤집는다. Check/Act에서 결정 |
| Check(gap-detector) | 80항목: 일치 62·부분 13·불일치 0·확인 불가 5 → **82.7%**(설계 내부 충돌 3건 일치 시 86.7%). 런타임 코드 불일치·부분 0. 분석 `docs/03-analysis/ruling-quota-cap.analysis.md` |
| Act-1(정합) | 설계 문서 불일치 12건·테스트 RU28/RU32/RU33 보강·CLAUDE.md 승격 절·하네스 M1e/M5/G5 정합. 스위트 통과(37/37). 자체 재집계 75/75. 동작 변경 없음 |
| Act-2(사용자 "A+C 진행", 2026-11-09) | **A** `_cap_rulings_in_top_n` 후보 ② = top_n 밖 전체 자연 공공(상담은 창 안 유지) · **C** `pipeline._restore_public_after_self_rag`(Self-RAG 뒤 쿼터 집합 공공이 2단 목표 미만이면 목표까지 rerank 순 복원, 재결례 제외) + Self-RAG 블록 호출. 테스트 RU28 확장(`prec_far`·창 밖 상담 비후보)·RU32 재작성·RU35 신설·T26-s 갱신 → rulings **38/38**, precedent·pipeline_wiring·offline_units 통과. **실제 코드 검증**(cap1·cap2 로그의 분해 쿼리로 pool 재구성, Self-RAG 전): S+ 재결례 59·64 → **50·51**, 공공 42·43 → **56·56**, 후보 없음 9·12 → **0**, 교체 26·28 → 34·40 — 시뮬레이션 A(50·52 / 55·56)와 ±1. C는 LLM 판정이 필요해 재측정으로 확인. **재측정 승인 대기**: S+ ×2(48) + R ×1(52) |
| **Act-2 재측정(P1-2)** — 사용자 "재측정 진행"(2026-11-09) | `run_act.sh` 18:55~19:32(37.5분): act1 synthetic 24 → act2 synthetic 24 → act1 real_pos 52 = **100답변, 오염 0**(전부 OpenAI/gpt-6-sol, 폴백 0, spy 누락 0). `compare_rqc.py --cap act1,act2 --allow-partial`(base after1·after2 / base cap1·cap2 둘 다 exit 0): **G1 ✅** S+ 0.94·0.89(cap 0.83·0.94)·S− 0 · **G2 ✅** 재결 뺀 공공 **42·42**(≥34; cap 34·28, after 20·16)·공공 0건 **0·0**(cap 0·1, after 8·6) · **G3 ✅** R 공공 0건 **0**(cap 2·0, after 12·12)·공공 **85**(≥68; cap 79·75, after 62·60; act2는 R 미측정) · **G4 ✅** 교정 후 잔여 0·비재결 오판 0·유효 재결 인용 23(act2 17 — S+만이라 임계 미적용) · **G5 ✅** S+ 일반화 금지 0·벤더 동일·누락 0(K는 재측정하지 않고 `--k-from cap1,cap2`로 cap 실행의 K 금지 0·allowed_source 거짓 0을 판정에 사용). 결과 `rul/report_act.md`·`gates_act.json`·`report_act_vs_cap.md`·`gates_act_vs_cap.json` |
| Act-2 재측정 — 보조 지표·진단(`act_diag.py`) | S+ 재결례 슬롯 **44/104(42%)·40/102(39%)**(cap 38%·52%, after 59~64%), 서로 다른 재결 35·34, 재결 ≥ 2 문항 16·13, 상담 15·18(cap 25·22), 해설서 3·2, 판례 0건 12·17(cap 16·15), 쟁점 유보 M3 0.06·0.11(cap 0·0.06 — 1~2문장, 관문 밖). R: 재결례 17/294(6%)·공급 0.23(after 0.27, cap 0.13 — 쿼터 주입분이 사라진 뒤 자연 유입만 남아 실행 편차가 크다), 상담 186, 해설서 6, 마커 `public-quota` 30·`legal` 17. **사슬(로그)**: 1단 주입 29·17(재결 victim 10·0) → 상한 교체 **38·39**(cap 28·31 — A가 후보를 늘렸다; 후보 없음 0) → 2단 승격 5·8 → Self-RAG 제거 46·39(cap 53·48) → **복원 이벤트 synthetic 24문항 11·8건(복원 18·13건 — S+ 10·7건/16·11건, S− 1·1건/2·2건)**·R 52문항 27건(36건); cap 0 → 마커 생존 `ruling-cap` **25·23**(cap 14·15). G6 재확인(Act-2 뒤 worktree): `eval_corpus_mix --baseline` 비재결 공공 16·재결례 0·해설서 0·상담 28·도달 12/12·상담 비중 64%(이전과 동일) · `eval_retrieval` **16/19 = 84.2%**(승격 5, 차감 0 — main 재측정과 동일) ✅. G7 재확인: rulings **38/38**·precedent·offline_units·pipeline_wiring·kin 39(skip 1)·effective_law 31 전부 통과 ✅ |
| Act-2 재측정 — 관문 밖 관찰 | S− `n-annual`(act1)이 공공 0건(cap1·cap2 1건, after 0건·S− 전체 after는 slots 미기록). 로그: COMPLEX, 1단 주입·2단 승격·상한 교체·복원 이벤트 **전부 없음**, 해설서 승격 1 → Self-RAG 7→6. 복원이 돌지 않았으므로 Self-RAG 전부터 공공 0(복원은 '제거된 공공'만 되살린다) = 1단이 pool의 자연 공공으로 `have ≥ quota`를 판정해 조회를 건너뛰었는데 그 공공이 rerank에서 창 밖으로 묻힌 기존 패턴(진단 1과 같은 구멍, 재결례와 무관 — 상한·A가 발동할 재결례가 없다). 이 사이클 범위 밖, Analysis F-6 |
| Check 재실행(gap-detector, Act-2 뒤) → Act-3(정합) | **85.0%**(일치 68·부분 12·불일치 0·확인 불가 4) — 런타임 동작 불일치 0, 부분 12는 전부 문서·주석·수치 표기·하네스: A11 D18 경계 처리 미기록 · B6 §3.3 docstring ② '창' · D15 RU28·클래스 docstring · E14 G5 K 공허 참 · F3 §2 표(RU35·하네스 파일) · G5 §7 '창의 비재결 후보' · G6 §7 Self-RAG bullet 부재 · G7 복원 이벤트를 S+로 표기 · **G8 1단 주입 15·31을 2단 승격으로 오기**(§13·pipeline docstring·CLAUDE.md 3곳) · G9 회귀 범위 RU35 누락 · G10 M7 확인 방법 불성립 · I1 rag.py 주석 2곳. Act-3: 전부 정정(설계 8·CLAUDE.md 2·테스트 docstring 1·구현 주석 1), 하네스 `--k-from` 추가 후 compare 재실행(G5 K를 cap1·cap2 값으로 판정). 자체 재집계 80/80. 동작 변경 없음 |
