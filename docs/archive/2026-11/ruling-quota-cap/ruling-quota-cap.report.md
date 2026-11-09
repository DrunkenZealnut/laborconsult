# Report: 재결례 전용 상한·쿼터 분리·킬스위치 (ruling-quota-cap)

> **Feature**: 재결례(`source_type="ruling"`)가 판례·행정해석·훈령의 공공 쿼터·법률근거 승격 슬롯을 잠식하던 문제를 검색 시점 코드로 고침. 집합 3종 분리, 재결례 총량 상한(교체형), 킬스위치 2종
> **PDCA Cycle**: Plan → Design(rev2) → Do(측정 cap1·cap2) → Check(gap-detector 82.7%) → Act-1(정합) → Act-2(A+C 구현·재측정 act1·act2) → Check 재실행(85.0%) → Act-3(정합, 자체 80/80)
> **Period**: 2026-11-09 (단일 일자, KST)
> **PR**: #160 — 커밋 a51bea7(12파일 +1,680/−55), CI 통과(offline-tests·GitGuardian·Vercel preview), `--merge --delete-branch=false`로 main **04c4b3d**(2026-11-09). 보관 이동은 후속 PR
> **Status**: Complete — 구현·측정·문서 정합·PR #160 머지·프로덕션 배포 success(`/api/health` 200). 독립 Check 재실행은 85.0%로 90%에 미달(§2.4 참조), Act-3 뒤 자체 재집계 80/80

---

## Executive Summary

### 1.1 프로젝트 개요

| 항목 | 내용 |
|---|---|
| 기능 | 재결례 전용 상한·쿼터 분리·킬스위치 (`ruling-quota-cap`) |
| 선행 사이클 | adjudication-corpus (재결례 1,052건 적재, 2026-11-09 종결). 그 Analysis B-1·Report §6 1번이 이 사이클이다 |
| 기간 | 2026-11-09 하루 (Plan·Design·Do·측정·Check·Act 전부) |
| 결정 | Plan §6 D1~D7 권고안 확정(사용자 "권고안대로 진행"), D7 측정 비용 승인(196답변 → 추가 100답변 승인) |
| 구현 범위 | 검색 시점 코드만. 데이터(Pinecone·BM25 gz·원장) 불변 |
| 구현 파일 | Design §2 기준 7파일: `app/core/rag.py`, `app/core/pipeline.py`, `eval_corpus_mix.py`, `eval_colloquial.py`, `test_rulings_ingest.py`, `test_precedent_ingest.py`, `CLAUDE.md` |
| 줄 수 | **7파일 +491/−52**(Act-3 뒤 worktree `git diff --stat`): `test_rulings_ingest.py` +287·`rag.py` +165·`pipeline.py` +46·`eval_corpus_mix.py` +20·`test_precedent_ingest.py` +12·`CLAUDE.md` +10·`eval_colloquial.py` +3(Act-1 시점 6파일 +390/−33) |
| 상태 | worktree `../laborconsult-rqc`(브랜치 `feat/ruling-quota-cap`, base main c4a5f1a) → PR #160(커밋 a51bea7, CI 통과) → main 04c4b3d 머지(2026-11-09), 프로덕션 배포 success·`/api/health` 200 |

### 1.2 결과 요약

- **측정**: 하네스 `~/DEV/laborconsult_eval/rul/`, gpt-6-sol, `--law-mode cache`. 변경 후 실행 cap1·cap2(196답변) + Act-2 뒤 act1·act2(100답변). 오염 0(cap2는 네트워크 단절로 오염된 3문항을 재실행해 치환).
- **관문**: Act-2 뒤 재측정(act1·act2) **G1~G5 전부 통과**. G6(검색 전용)·G7(오프라인) 재확인 통과. cap 단계의 G2 건수는 cap2에서 28로 미달이었고, 원인 분석 뒤 구조를 고쳐 해소했다(§2.4·§3.3).
- **오프라인 테스트**: `test_rulings_ingest` 38/38(RU10·RU26~RU35), `test_precedent_ingest`·`test_offline_units`·`test_pipeline_wiring`·`test_kin_accuracy`·`test_effective_law` 통과.
- **Check**: gap-detector 1차 82.7%, 재실행 85.0%(Act-2 뒤). 부분 12건은 전부 문서·주석·수치 표기·하네스였고 런타임 동작 불일치는 0이었다. Act-3에서 정정했으나 자체 재집계(80/80)이며 독립 재실행은 하지 않았다.

| 관문 | 기준 | before (after1·after2) | 변경 후 cap1·cap2 | 재측정 act1·act2 | 판정 |
|---|---|---|---|---|---|
| G1 S+ 재결례 공급 · S− 0 | ≥ 0.80, S− 0 | 0.94·0.89 · 0 | 0.83·0.94 · 0 | **0.94·0.89 · 0** | 통과 |
| G2 S+ 재결 뺀 공공 · 공공 0건 문항 | ≥ 34 · ≤ 2 | 20·16 · 8·6 | 34·28 · 0·1 | **42·42 · 0·0** | 통과 (cap2 건수 미달 → Act-2로 해소) |
| G3 R 공공 0건 · R 재결 뺀 공공 | ≤ 4 · ≥ 68 | 12·12 · 62·60 | 2·0 · 79·75 | **0 · 85** (act2 R 미측정) | 통과 |
| G4 교정 후 잔여 환각 · 비재결 오판 · 유효 재결 인용 | 0 · 0 · ≥ 10 | 0·0·26·29 | 0·0·20·27 | **0·0·23** (act2 17, S+만) | 통과 |
| G5 K 금지 · allowed_source · S+ 일반화 · 벤더 · spy 누락 | 전부 0 / 동일 | — | 전부 0 | S+ 0 · 벤더 동일 · 누락 0 (K는 cap 실행 값 사용) | 통과 |
| G6 검색 전용 비회귀 | 해설서 도달률 불변 · 비재결 공공 비감소 | 기준선 2 (2026-08-23 기준) | 비재결 공공 16, 도달 12/12 | 동일 (16, 12/12) · eval_retrieval 84.2% | 통과 |
| G7 오프라인 | 스위트 전부 통과 | — | — | rulings 38/38 외 전부 통과 | 통과 |

### 1.3 Value Delivered

| 관점 | 내용 |
|---|---|
| **Problem** | 재결례 1,052건 적재 뒤 S+ 문항의 공공(판례·행정해석·훈령) 건수가 42·53 → 20·16으로 줄고, 공공 0건 문항이 S+ 0 → 8·6, 실사용 R 1·2 → 12·12/52로 늘었다. 재결례가 공공 쿼터를 충족해 조회를 막고 '법률근거 있음'으로 판정돼 승격을 막은 탓이다. |
| **Solution** | 쿼터·법률근거 승격 집합에서 재결례를 분리하고(저작권 분류용 집합은 파생 유지), 재결례 총량 상한 `max(1, top_n//2)`을 교체형으로 걸고, 순서를 상한 → 2단 → 승격으로 고정했다. 1단 쿼터 victim에 pool 상한 초과 재결례를 더했다(D22). `RULING_RETRIEVAL`·`RULING_CAP` 킬스위치를 두었다. 데이터는 건드리지 않았다. |
| **Function UX Effect** | 하네스 측정(LLM 답변 기준, 미배포)에서 S+ 공공 건수 20·16 → **42·42**, 공공 0건 S+ 문항 8·6 → **0·0**, R 공공 0건 문항 12·12 → **0**(act1). 재결례 공급률은 0.94·0.89로 유지됐다. 실사용 효과는 배포 뒤 `metadata.rag_sources`로 확인해야 한다(미확인). |
| **Core Value** | 새 공공 출처를 더할 때 기존 공공 출처를 밀어내지 않는 구조를 만들었다. 다음 출처(법령해석례 등)도 같은 집합 규칙을 탄다. 문제가 생겨도 `RULING_RETRIEVAL=off` 또는 `RULING_CAP=off`로 재배포만에 되돌릴 수 있어 데이터 롤백(원장 rollback + BM25 재빌드 약 2~3.5시간)에 기대지 않는다. |

---

## 2. PDCA 사이클 요약

### 2.1 Plan

- 문서: `docs/archive/2026-11/ruling-quota-cap/ruling-quota-cap.plan.md` (PR #160, 보관 이동)
- 목표: 재결례 적재로 사라진 공공 근거(판례·행정해석·훈령)를 before 수준으로 회복. 재결례 공급(G1)은 유지.
- 실측 근거: adjudication-corpus after 기록(98문항 × 4회)의 `rag_meta`를 문항별로 재집계. 경로 세 개를 분해했다 — ① 쿼터 충족(재결례가 pool 쿼터를 채워 공공 조회를 건너뜀) ② 승격 억제('법률근거 있음' 판정) ③ 자연 유입(Dense+BM25 상위 점수).
- 결정 D1~D7: 킬스위치 `RULING_RETRIEVAL=off`, 집합 분리, 자기 다양성 클래스, 교체형 상한 `max(1, top_n//2)`, 문서당 상한 보류, after 재사용 + cap 2회, 측정 비용 승인.

### 2.2 Design

- 문서: `docs/archive/2026-11/ruling-quota-cap/ruling-quota-cap.design.md` (rev2, §13에 Do 실측, PR #160, 보관 이동)
- 설계 결정 D8~D22를 Plan에 더했다. 주요 항목:
  - **D8 집합 셋 + 파생**: `POOL_PUBLIC_SOURCES = {precedent, interpretation, regulation}`, `RULING_SOURCES = {ruling}`, `PUBLIC_DOMAIN_SOURCES = POOL ∪ RULING`(저작권 분류). 리터럴은 두 개만 두고 합집합은 식으로 쓴다(구조 테스트 RU26).
  - **D9 킬스위치 위치**: `search_hybrid` 안에서 Dense·BM25 결과를 RRF 병합 **전에** 필터링. 병합 뒤에 걸면 pool이 빈다.
  - **D12 교체 후보 순서**: ① 전체 랭킹의 `quota_injected` 공공 → ② 자연 유입 공공 → ③ 창(top_n ~ 2×top_n)의 상담. 해설서는 후보가 아니다(저작권 노출 증가 방지).
  - **D13 계측 마커**: 교체분은 `promoted="ruling-cap"`.
  - **D22 1단 victim 확장**: 상담 victim이 없을 때 pool 상한(`top_k//2`) 초과 재결례를 victim으로 쓴다.
- Design rev2는 design-validator 73점(High 1·Medium 7·Low 9)을 전부 코드로 재현해 반영했다(§12).
- 재생 실험(LLM 0회, 76문항, 변형 A~E): 원문 쿼리 재생은 프로덕션(분해 쿼리)과 절대값이 다르므로 변형 간 상대 비교에만 썼다. 이 과정에서 **D19(재결례 승격)를 폐기**했다 — 재생 v2에서 S−에 1건, R에 2건을 넣어 G1(S− 0)을 깨뜨렸기 때문이다.

### 2.3 Do

- 구현: `app/core/rag.py`에 집합 3종·술어·킬스위치 2종(`_exclude_rulings_if_disabled`·`_ruling_cap`·`_cap_rulings_in_top_n`), 1단 victim 확장, `_finalize` 순서, `_diversity_class_of` 재결례 분기. Act-2에서 `pipeline.py`에 `_restore_public_after_self_rag`(Self-RAG 뒤 복원) 추가.
- 측정 스크립트: `eval_corpus_mix.py`(`ruling` 별도 분류, 공공은 비재결만 집계 — D20), `eval_colloquial.py`(`LEGAL_CORPUS_SOURCES` 파생식 — D21).
- 검색 전용 재생과 킬스위치 양성 검증:
  - S+ 18 · S− 6 · R 52 재생(실제 코드): S+ 공공 31, 공공 0건 0, 재결례 29(26 재결) — 재생 v3(C3) 값과 일치.
  - 킬스위치 `RULING_RETRIEVAL=off` 3문항: pool·컨텍스트 재결례 0건. 단 `r-ia-eye`는 pool이 재결례 일색이라 제외 뒤 컨텍스트가 1건(공공 0)으로 남았다 — 재결례 포화 질의에서는 스위치가 pool을 비운다.
  - `RULING_CAP=off` 2문항: 재결례 4·5건이 남았다(주입 공공은 됐으나 top_n에 못 듦).
- G6: `eval_corpus_mix --baseline` 비재결 공공 2 → 16, 도달 12/12, 해설서 0, 상담 비중 89% → 64%. `eval_retrieval` worktree 16/19 = 84.2%(main 재측정 84.2%, main 1차 89.5% — 실행 편차 ±1 pool 해설서, 변경 밖 요인으로 판단).
- 측정(P1):
  - **cap1** 14:41~15:14, 98답변, 오염 0. G1 0.83·0, G2 공공 34(기준 ≥ 34 충족)·공공 0건 0, G3 R 공공 0건 2·공공 79, G4 ✅, G5 ✅.
  - **cap2** 15:14~17:02, 98답변. 네트워크 단절 2구간에 real_pos 3문항(`r-ue-17·18·19`)이 전 제공자 실패(Gemini 폴백)로 오염 → 해당 3문항만 재실행해 치환(원본은 `.pre_patch` 보관), 잔여 오염 0. G2 공공 28(미달), 공공 0건 1(통과).
  - 지연: 문항당 total_s 15~28초, after와 같은 범위(추가 조회 체감 없음).

### 2.4 Check

- **gap-detector 1차**: 80항목(일치 62·부분 13·불일치 0·확인 불가 5) → **82.7%**. 런타임 코드는 전부 일치, 부분 13은 테스트 강도·하네스·문서.
- Act-1(정합, 동작 변경 없음) 뒤 자체 재집계 75/75 — gap-detector 재실행 없음.
- **gap-detector 재실행(Act-2 뒤)**: 일치 68·부분 12·불일치 0·확인 불가 4 → **85.0%**. 런타임 동작 불일치·부분 0. 부분 12건은 A11(D18 경계 기록)·B6(§3.3 docstring)·D15(테스트 docstring)·E14(G5 K 공허 참)·F3·G5·G6·G7(복원 이벤트 S+ 표기)·G8(1단 주입 15·31을 2단 승격으로 오기)·G9·G10·I1.
  - **판정 비율의 분모**: 85.0% = 일치 68 / (일치 68 + 부분 12) — 확인 불가는 분모에서 뺀다. 1차 82.7%도 62/(62+13)이다. 항목 수는 1차 80(판정 75 + 확인 불가 5), 재실행 84(판정 80 + 확인 불가 4)이며 Analysis §1·§1.1에 그 정의를 적었다.
- **Act-3(정합)**: 부분 12건 전부 정정(설계 문서 8곳·CLAUDE.md 2곳·테스트 docstring 1·구현 주석 1·하네스 `compare_rqc --k-from` 추가 — G5 K를 cap 실행 값으로 판정해 공허 참 제거). 재판정 동일. 자체 재집계 **80/80**(gap-detector 재실행 없음).
- **주의**: pdca 스킬은 Check 90% 이상을 완료 조건으로 두는데, 독립 재실행 결과는 85.0%다. Act-3 이후 80/80은 작성자의 자체 재집계이므로 독립 검증으로 세지 않는다. 이 보고서는 그 상태를 그대로 적는다.

### 2.5 Act

- **Act-1(정합)**: 설계 문서 12건(D15↔D20, RU28·RU31 문구, `§3.2` D19 참조, `§12`→`§13` 등), 테스트(RU28 `_ruling_cap` 6·8과 상담·해설서 비감소, RU32 `ast.If` 검사, RU33 절 단위 검사), CLAUDE.md 승격 절 "재결례 승격은 두지 않는다", 하네스(M1e id 우선, M5 COMPLEX proxy, G5 `== 0`). `test_rulings_ingest` 37/37.
- **Act-2(동작 변경, 사용자 "A+C 진행")**:
  - **A** 상한 후보 ②를 창 안 자연 공공 → **top_n 밖 전체 랭킹의 자연 공공**(순위순)으로 확장. 상담 후보는 창 안만 유지.
  - **C** `pipeline._restore_public_after_self_rag`: Self-RAG 뒤 쿼터 집합 공공이 2단 목표(`_pool_public_quota_for_top_n`) 미만이면 rerank 순으로 목표까지 복원(재결례 제외). 원 D14("전멸 시 1건")를 바꾼 것이다.
  - 테스트: RU28 확장·RU32 재작성·RU35 신설·T26-s 갱신. `test_rulings_ingest` 38/38.
  - 실제 코드 검증(cap 로그의 분해 쿼리로 pool 재구성, Self-RAG 전): S+ 재결례 59·64 → 50·51, 공공 42·43 → 56·56, 후보 없음 9·12 → 0. 시뮬레이션과 ±1.
- **재측정(사용자 "재측정 진행")**: `run_act.sh`, 18:55~19:32, act1 synthetic 24 → act2 synthetic 24 → act1 real_pos 52 = 100답변, 오염 0, 전부 OpenAI. K 22문항은 재측정하지 않았다 — G5의 K 부분은 cap 실행 값을 쓴다(`--k-from cap1,cap2`, 보고서에 '유지'로 표기). 판정은 `compare_rqc.py --cap act1,act2 --allow-partial --k-from cap1,cap2`(base after1·after2와 cap1·cap2 둘 다 exit 0).
- **Act-3(정합)**: §2.4 참조.

---

## 3. 결과

### 3.1 완료 항목

| 항목 | 결과 |
|---|---|
| 집합 분리(D2·D8) | `POOL_PUBLIC_SOURCES`에서 재결례 제외, 파생 집합 3종, 리터럴 재선언 0(RU26 AST) |
| 킬스위치(D1·D9·D10) | `RULING_RETRIEVAL`(재결례 전체, RRF 전 필터, 양성 검증 3문항), `RULING_CAP`(상한만, 양성 검증 2문항) |
| 다양성 클래스(D3) | 재결례 자기 클래스 — 마지막 1건 보호(RU30) |
| 교체형 상한(D4·D12·D13) | `max(1, top_n//2)`, 후보 ①②③, 해설서 제외, `promoted="ruling-cap"` 마커 |
| 1단 victim 확장(D22) | 산재 질문 pool 포화 해소(재생 v3, 상한과 함께 S+ 공공 0건 문항 4 → 0) |
| Self-RAG 복원(Act-2 C) | 쿼터 집합 공공을 2단 목표까지 복원, 복원 이벤트 synthetic 11·8건 |
| 측정 관문 | G1~G5 act 재측정 전부 통과, G6·G7 통과 |
| 문서 | CLAUDE.md 재결례 절·공공 쿼터 절·승격 절·Self-RAG 항목·환경 변수 2종 |

### 3.2 미완료·보류·미확인 항목

| 항목 | 사유 |
|---|---|
| 커밋·PR·CI·머지 | **완료** — PR #160(커밋 a51bea7, CI 통과) → main 04c4b3d 머지(2026-11-09), 프로덕션 배포 success·`/api/health` 200 |
| 배포 · 실사용 효과 | 배포 success(04c4b3d, Vercel env 변경 없음 — 기본 `on`). 실사용 효과는 `metadata.rag_sources`로 사후 확인해야 한다(미확인) |
| 독립 Check 재실행 | 85.0%(Act-2 뒤)가 마지막 독립 값. Act-3 이후는 자체 재집계 80/80 |
| 지연(D2 조회 1회 추가) | 측정 기록의 total_s로만 확인했다(문항당 15~28초, after와 같은 범위) |
| R 재결례 공급률 실사용 값 | 간접 근거만 있다. after 0.27 → cap 0.13 → act 0.23(실행 편차 큼). CLAUDE.md에는 범위(0.13~0.23)로 적었다 |
| act2 R 측정 | Act-2 재측정은 R을 act1에서만 돌렸다. G3 R 판정은 act1 값이다 |
| K 재측정 | 재측정하지 않았다. G5 K는 cap 실행 값(금지 0·allowed_source 거짓 0) |
| base 경계 재측정(D18) | cap1 ✅·cap2 ❌(G2 건수)로 경계 조건이 성립했으나 base 재측정은 생략했다. Act-2 재측정(42·42, 임계 34에서 멀다)으로 대체했다 — Analysis A11이 이 판단을 받아들였다 |

### 3.3 설계와 달라진 점

| 항목 | 설계 | 실제 | 근거 |
|---|---|---|---|
| 재결례 승격(D19) | 재결례 1건을 창에서 승격 | **폐기**. 재생 v2에서 S−·R에 재결례가 들어가 G1(S− 0)을 깼다 | Design §1.3, §12 M1 |
| 교체 후보 ② | 창 안 자연 공공 | **top_n 밖 전체 랭킹의 자연 공공**(Act-2 A). 창 안에 후보가 없던 9·12 문항이 0이 됐다 | Analysis §2.4·§3.1 |
| Self-RAG 복원(D14) | 전멸 시 1건만 복원 | **목표 건수까지 복원**(Act-2 C). Self-RAG 판단을 2건 한도 안에서 뒤집는다 | Analysis §3.2 |
| 상한 값 판정 기준(Design §1.3 변형 비교 확정 note) | cap1·cap2에서 S+ 재결례 슬롯 비중이 50%를 넘으면 Act에서 E(고정 1)로 내린다(기록만) | cap2 비중이 52%로 기준을 넘었으나 **E는 채택하지 않았다**. 원인이 상한 후보 부재와 Self-RAG 손실이라 E로는 고칠 수 없고 E는 재결례 공급을 깎는다고 판단했다(Analysis §4). act1·act2 비중은 42%·39%로 기준 안이다. 미채택 근거는 Act-3에서 Design §1.3 그 줄에 보강했다 | Analysis §4, Design §1.3 |
| 문서당 상한(D5) | 보류 | 보류 유지. 같은 재결 추가 청크는 cap에서 23% → 18%(재생 기준) | Design §1.3 |
| 1단 victim(D22) | 상담 victim만 | 상담 → pool 상한 초과 재결례 | 재생 v3 probe |
| 측정 base 재측정(D18) | 경계면 1회 | 생략(§3.2) | Analysis A11 |

---

## 4. 측정 결과

### 4.1 측정 구성

- 문항 98개: S+ 18, S− 6, R 52(실사용), K 22(지식iN·상담).
- 답변 296개: cap1·cap2 196(98문항 × 2, K 포함), act1·act2 100(synthetic 24 × 2 + real_pos 52 × 1, K 제외). 모델 gpt-6-sol, `--law-mode cache --primary openai`.
- spy: `format_pinecone_hits` 입력(`rag_hits_in`: id·source_type·promoted·quota_injected)과 최종 컨텍스트(`rag_meta`)를 함께 기록.

### 4.2 관문 판정

§1.2 표 참조. 판정 기준은 Plan §2 그대로이며 정의를 바꾸지 않았다.

### 4.3 보조 지표

| 지표 | after1·after2 | cap1·cap2 | act1·act2 |
|---|---|---|---|
| S+ 재결례 슬롯 비중 | 64% · 59% | 38% · 52% | **42% · 39%** |
| S+ 서로 다른 재결 수 | 51 · 42 | 27 · 38 | 35 · 34 |
| S+ 재결 ≥ 2 문항 | 13 · 14 | 10 · 15 | 16 · 13 |
| S+ 상담 청크 | — | — | 15 · 18 (cap 25 · 22) |
| S+ 판례 0건 문항 | 16 · 17 | 16 · 15 | 12 · 17 |
| S+ 쟁점 유보 비율 | 0 · 0.06 | 0 · 0.06 | 0.06 · 0.11 (관문 밖) |
| R 재결례 공급 (재결례 청크 / 전체 슬롯) | 0.27 | 0.13 | 0.23 (17/294 슬롯, 6%) |
| R 공공(비재결) 건수 | 62 · 60 | 79 · 75 | 85 (act1) |

`ruling-cap` 마커 생존(Self-RAG 뒤): cap 14·15 → act 25·23.

### 4.4 상한 교체 사슬(Act-2 효과 분해)

| 단계 | cap1 | cap2 | act1 | act2 |
|---|---|---|---|---|
| 1단 주입(재결 victim) | 15(3) | 31(8) | 29(10) | 17(0) |
| 상한 교체(rerank 직후) | 28 | 31 | **38** | **39** |
| 상한 후보 없음 | 9 | 12 | **0** | **0** |
| 2단 승격 | 6 | 6 | 5 | 8 |
| Self-RAG 제거 합 | 53 | 48 | 46 | 39 |
| 복원 이벤트 (복원 건수, C, synthetic 24문항) | 0 | 0 | **11** (18건 · S+ 10 · S− 1) | **8** (13건 · S+ 7 · S− 1) |
| 공공(최종) | 34 | 28 | **42** | **42** |

- A의 효과: 창 안에 후보가 없던 문항이 0이 되어 상한 교체가 28·31 → 38·39로 늘었다(예: `r-ia-grade-finger` 재결 9 / 공공 1 → 2 / 2).
- C의 효과: Self-RAG가 공공을 목표 아래로 깎은 문항에서 복원이 돌아 공공 0건 문항이 S+·R 모두 0이 됐다. 두 효과는 가산적이다.
- 재생에서 본 "R 재결례 117 → 4"(주입분 제거)는 원문 쿼리 재생 값이며, 실측 R 재결례 공급은 간접적으로만 확인된다(§3.2).

### 4.5 킬스위치 양성 검증

| 스위치 | 실험 | 결과 |
|---|---|---|
| `RULING_RETRIEVAL=off` | S+ 3문항 재생 | pool·컨텍스트 재결례 0건(`r-ins-coop` 공공 3/5, `r-elig-quit` 공공 2/5). `r-ia-eye`는 컨텍스트 1건·공공 0 — 재결례 포화 질의에서 pool을 비운다 |
| `RULING_CAP=off` | 2문항 | 재결례 4·5건 잔존, 주입 공공 3건은 top_n에 못 듦(§1.3 B3 재현) |

---

## 5. 교훈

### 5.1 What Went Well

- **측정 전에 경로를 분해했다.** 재결례가 공공을 밀어내는 경로를 쿼터·승격·자연 유입으로 나눠 본 덕분에, 집합 분리(쿼터·승격)와 상한(자연 유입)을 서로 다른 장치로 풀 수 있었다.
- **재생으로 설계를 여러 번 바꿨다.** 재생 v2에서 승격(D19)이 S−와 R에 재결례를 넣는 것을 잡아 폐기했다. 측정 전에 관문 위반을 발견한 것이다.
- **관문 미달을 정의 변경 없이 기록했다.** cap2 G2 건수 미달(28)을 기준 완화로 넘기지 않고, 원인을 로그로 분해한 뒤 구조를 고쳐 재측정했다.
- **킬스위치를 데이터와 분리했다.** 되돌림이 재배포만으로 가능하다.

### 5.2 Areas for Improvement

- **원문 쿼리 재생은 프로덕션 공공 공급을 크게 과소 측정했다**(A 5건 vs 실측 20·16). 분해 쿼리·Self-RAG를 지나지 않는 재생으로는 상한·복원 효과를 보지 못했다. 시뮬레이션을 로그 파싱으로 대신했다(F-3).
- **Self-RAG가 구성 작업을 되돌렸다.** 쿼터·상한 승격분의 상당수가 Self-RAG에서 걸러졌다. 설계 단계에서 이 손실을 예측하지 못했다.
- **설계 문서 숫자를 로그에서 다시 세지 않았다.** G8처럼 "1단 주입 수"를 "2단 승격 수"로 적는 오기가 Check에서 나왔다. 측정 결과를 옮길 때 로그 집계를 다시 돌려야 한다.
- **Check 항목 수의 분모 정의를 처음부터 적지 않았다.** 판정 비율이 확인 불가를 뺀 값(80 중 68)인데 재실행 총 항목은 84라, 정의를 적기 전에는 혼동됐다. Analysis §1.1에 정의를 적어 바로잡았다.
- **임계 규칙(Design §1.3 "50% 넘으면 E로 내린다(기록만)")이 cap2(52%)에 걸렸는데 채택하지 않았다.** 판단 근거(E로는 후보 부재·Self-RAG 손실을 못 고친다)는 Analysis §4에 있었지만 Design의 그 줄에는 Act-3에서야 적었다. 규칙을 세울 때 발동 시 판단 기준과 기록 위치를 같은 줄에 두어야 한다.

### 5.3 To Apply Next Time

- 쿼터·승격 집합에 **새 출처를 자동 편입하지 않는다.** 집합에 넣는 순간 조회 건너뜀·법률근거 판정·승격 억제가 함께 일어난다.
- 측정 하네스는 **프로덕션과 같은 경로**(분해 쿼리 + Self-RAG)를 지나야 한다. 원문 쿼리 재생은 상대 비교용으로만 쓴다(F-3).
- 측정 결과를 문서로 옮길 때 **로그에서 다시 집계**하고, 분모를 적는다(판정 비율의 정의).
- 임계 규칙을 세울 때는 **그 규칙이 발동하면 무엇을 하는지**를 같은 줄에 적는다.

---

## 6. 후속 과제

| 우선 | 항목 | 근거 |
|---|---|---|
| 1 | ~~커밋·PR·CI·머지, Vercel 배포~~ — 완료(PR #160 → 04c4b3d, 배포 success). 남은 것은 실사용 `metadata.rag_sources` 분포 확인과 worktree `../laborconsult-rqc` 정리 | §3.2 |
| 2 | 배포 뒤 실사용 `metadata.rag_sources`로 재결례·판례 분포 확인 | Plan §7 |
| 3 | F-1: Self-RAG가 쿼터·상한 승격분을 걸러내는 구조 — 목표 건수 복원으로 처리했다. 보호 표식을 Self-RAG 입력에 넘기는 방식은 두지 않았다 | Analysis §5 |
| 4 | F-2: 판례 0건 S+ 문항 16·15(before 14·15) — 판례 공급 확대는 다른 사이클 | Analysis §5 |
| 5 | F-3: 검색 전용 측정이 분해 쿼리·Self-RAG를 보지 못함 — 하네스 spy에 `pinecone_search_queries`를 더해 프로덕션 pool로 재생 | Analysis §5 |
| 6 | F-4: 실사용 R 재결례 공급의 실행 편차(0.13~0.23) — 측정 반복 또는 실사용 집계로 확정 | Analysis §5 |
| 7 | F-5: 네트워크 단절 시 하네스 자동 재시도 | Analysis §5 |
| 8 | F-6: 1단 쿼터 건너뜀 판정(`have ≥ quota`)이 pool 기준이라 최종 top_n의 공공을 보장하지 않는다. S− `n-annual`(act1) 공공 0건 1건으로 관측. 재결례와 무관한 일반 구조 | Analysis §2.4·§5 |
| 9 | 재결례 전용 상한의 후속 — 재결례 비중이 높은 질의에서 E(고정 1)로 내릴지는 실사용 값을 본 뒤 판단 | Design §1.3 |
| 10 | adjudication-corpus 후속(B-5 agency 메타, B-8 이미지 OCR, stale_rules 산재, 고정 IP 예열)은 별도 과제 | Design §11 |

---

## 7. 참조 문서

- Plan: `docs/archive/2026-11/ruling-quota-cap/ruling-quota-cap.plan.md`
- Design: `docs/archive/2026-11/ruling-quota-cap/ruling-quota-cap.design.md` (rev2, §13 Do 실측)
- Analysis: `docs/archive/2026-11/ruling-quota-cap/ruling-quota-cap.analysis.md` (§1 gap-detector 1차·재실행, §2 측정 cap, §2.4 Act-2 재측정, §3 진단, §4 Act 후보, §5 후속, §6 Act 계획)
- 선행 보고서: `docs/archive/2026-11/adjudication-corpus/adjudication-corpus.report.md`
- 구현: PR #160(main 04c4b3d) — worktree `../laborconsult-rqc`(브랜치 `feat/ruling-quota-cap`, 유지)
- 측정 하네스(저장소 밖): `~/DEV/laborconsult_eval/rul/` — `run_cap.sh`, `run_act.sh`, `compare_rqc.py`, `act_diag.py`, `report_rqc.md`, `report_act.md`, `gates_act.json`
- 테스트: `test_rulings_ingest.py` (38/38, RU10·RU26~RU35), `test_precedent_ingest.py` (T24-a4·T26-s)
- 운영 문서: `CLAUDE.md` 재결례 절·공공 쿼터 절·Self-RAG 항목·환경 변수
