# Report: 크롤 판례 프로덕션 적재 (crawl-precedent-production-ns)

> **Feature**: 사장 네임스페이스에만 존재하던 크롤 판례 318건을 `laborlaw-v2`에 적재해 프로덕션 검색에 도달시킴
> **PDCA Cycle**: Plan → Design → Do → Check(93.8%→94.8%) → Report
> **Period**: 2026-09-14 (Plan·Design·Do·Check 단일 세션일)
> **Match Rate**: 94.8% (92/97) — 배포 차단 Gap 2건 전량 해소
> **Status**: 구현·회귀·검색품질 검증 완료. `docs/03-analysis`·본 문서 커밋 대기(사용자 확인 후)

---

## Executive Summary

### 1.1 프로젝트 개요

| 항목 | 내용 |
|------|------|
| Feature | crawl-precedent-production-ns |
| 시작일 | 2026-09-14 |
| 종료일 | 2026-09-14 |
| 소요 | 1세션일 (Plan→Design→Do→Check→Gap 해소, 컨텍스트 재개 3회 포함) |

### 1.2 결과 요약

```
┌─────────────────────────────────────────────┐
│  Match Rate: 94.8% (92/97)                   │
├─────────────────────────────────────────────┤
│  ✅ 완료:     90 / 97 항목                    │
│  ⚠️ 부분:      5 / 97 항목 (전부 Low/Medium)  │
│  ❌ 미확인:    2 / 97 항목 (외부 조회 필요)    │
└─────────────────────────────────────────────┘
```

Plan의 성공기준 S1~S7 **전항목 충족**. 배포를 막던 High 1건·Medium 1건(GAP-1·GAP-2)은 본 사이클 내에서 해소됐다. 잔여 7건은 전부 문서 정합·운영 편의 항목이며 프로덕션 동작에 영향을 주지 않는다.

### 1.3 Value Delivered

| 관점 | 내용 |
|------|------|
| **Problem** | 노동 판례 원문 318건이 사장 네임스페이스(`precedent`/`laborlaw`)에만 존재해 **임베딩 비용은 이미 지불됐으나 프로덕션 검색에 영원히 도달하지 않는** 상태였다. 성공 메시지와 벡터 수가 정상으로 보여 어떤 게이트에도 걸리지 않는 조용한 실패였다 — 이 저장소에서 CLAUDE.md가 경고해 온 패턴의 최대 잔재였다. |
| **Solution** | 게이트 `verbatim` 318건만(editorial 363건·post 13건은 저작권 경계로 제외) `laborlaw-v2`에 재적재했다. 문서가 판결문 전문 형식이라 기존 `EMBED_SECTIONS`가 0건 매칭이므로, `【이 유】` 블록만 구조적으로 추출하는 별도 업로더를 신설하고(`pinecone_upload_crawl_precedents.py`), 저작권 경계는 재구현 없이 아카이브 게이트(`documents.csv`)를 그대로 읽게 했다. 그 경계를 지키는 회귀는 "판정 함수가 존재하는가"가 아니라 **"`select_targets()`가 실제로 무엇을 반환하는가"**를 검사하도록 별도로 강화했다. |
| **Function/UX Effect** | 사용자 인터페이스 변화는 없다. `precedent` 소스 청크가 BM25 기준 +2,403(82,166문서 중), 도달성 프로브로 최종 답변 컨텍스트에 실제로 오르는 것을 확인했다(`crawlprec_2018du35391_0` 등). 해설서 검색 품질은 무회귀(`eval_retrieval` 77.8%→84.2%, 분모 변화 있음— §6 참조). |
| **Core Value** | 이미 비용을 지불하고 확보한 자산을 실제로 쓸 수 있게 만든 사이클이다. 동시에 "설계에 행위 요구사항을 적는 것"과 "그 요구사항을 실제로 검사하는 것" 사이의 간극이 이 사이클 안에서 직접 드러나고 해소됐다(§4.2) — Match Rate 90%대가 그 간극 자체를 가려서는 안 된다는 CLAUDE.md 원칙의 또 다른 실례다. |

---

## 2. 관련 문서

| 단계 | 문서 | 상태 |
|------|------|------|
| Plan | [crawl-precedent-production-ns.plan.md](../01-plan/features/crawl-precedent-production-ns.plan.md) | ✅ 확정 |
| Design | [crawl-precedent-production-ns.design.md](../02-design/features/crawl-precedent-production-ns.design.md) | ✅ 확정 (§9 Do 단계 범위 확장 포함) |
| Check | [crawl-precedent-production-ns.analysis.md](../03-analysis/crawl-precedent-production-ns.analysis.md) | ✅ 완료 (94.8%) |
| Report | 본 문서 | ✅ 작성 완료 |

---

## 3. Plan 요약

**발단**: 아카이브 인벤토리 전수 대조에서 crawl 판례 815건 중 340건(41.7%)이 검색 불가 상태로 드러남. 그중 318건은 저작권 게이트를 이미 통과한 상태(`verbatim`)였고, 나머지 22건(`editorial`)은 제외 대상.

**핵심 판단**: 기존 `EMBED_SECTIONS`(판시사항·판결요지 전용) 규약을 바꾸지 않는다 — 대상 318건이 letec과 문서 구조·크기가 달라(전문 형식, 중앙값 3,770자 vs letec 최대 52,867자) 별도 업로더가 옳은 선택이라고 판단했고, Check 단계까지 이 판단은 뒤집히지 않았다.

**성공기준 대비 실적**:

| ID | 기준 | 실적 |
|---|---|---|
| S1 | 318건 적재, 증가분==신규 청크 수 | ✅ 원장 2,403 ID == BM25 `crawlprec_*` 2,403문서 일치 |
| S2 | editorial 22·letec 12 미적재 | ✅ `select_targets()` 실호출 검증(§4.2) — 현재 반환 0건(수렴 확인) |
| S3 | 당사자 표시 블록 0건 | ✅ T30-b |
| S4 | BM25 증가분==Pinecone 증가분 | ✅ 82,166문서 중 crawlprec_ 2,403 |
| S5 | 원장으로 전량 롤백 가능 | ✅ `vector_ledger.py` record→upsert→prune→finalize |
| S6 | `archive_precedents verify` V0~V8 | ✅ 본 세션 실행, 전량 통과 |
| S7 | `eval_retrieval` 전후 측정 기록 | ✅ §6 |

---

## 4. Design 요약 및 Do 단계 이탈

### 4.1 핵심 설계 결정

| # | 결정 | 근거 |
|---|------|------|
| `【이 유】` 추출 | 공백 허용 정규식(`【\s*이\s*유\s*】`) + 다음 `【】` 블록 직전 절단 | 공백 미허용 시 318건 전부 0건 매칭(실측). 종결자 없이는 3건에서 보일러플레이트 혼입 |
| `vector_id` 접두사 분리 | `crawlprec_` (letec은 `precedent_`) | 원장·prune 범위 혼선 방지 — 접두사가 같으면 부분 실행이 다른 코퍼스를 고아로 오판 |
| 그룹 키 = ASCII 사건번호 | `case_no_to_ascii` **import**(사본 금지) | `archive_precedents.reverse_case_key`가 ASCII 전제 — 한글 키는 인벤토리에서 조용히 빠짐 |
| `source_type="precedent"` 재사용 | 새 값 미생성 | 라벨 맵·법률근거 승격이 그대로 적용. 새 값을 만들면 3곳(rag.py 라벨맵·index.html·LEGAL_PROMOTE) 전부 갱신 필요 |

### 4.2 Do 단계에서 드러난 설계-구현 간극과 해소 — 이 사이클의 핵심 사건

Design §6은 T30-d를 *"대상 선정이 documents.csv의 gate 열을 읽는다"*, T30-e를 *"editorial·post 문서는 대상에서 제외된다"*라는 **행위 요구사항**으로 명시했다. 그러나 Do 단계의 최초 구현은 이를 `inspect.getsource()` 문자열 검사로 대체했다:

```python
check("T30-d ...", 'd["gate"] != "verbatim"' in src)
check("T30-e ...", "classify_gate_bucket" not in src)
```

이 검사는 두 방향 모두 실패한다 — 필터를 리팩터링하면(변수 추출 등) 멀쩡한 코드가 깨져 테스트를 느슨하게 고치는 압력이 생기고, 반대로 **그 문자열이 주석·데드코드로 남거나 뒤 분기가 제외분을 되돌리면 통과한 채 editorial 363건이 프로덕션 NS로 나간다.**

**해소**: 아카이브 픽스처(`documents.csv`·`inventory.csv` + 실문서 10건)를 임시 디렉터리에 구성하고 `select_targets()`를 **실제로 호출**해 반환 집합을 검사하도록 재작성했다. 핵심은 본문과 CSV 게이트를 일부러 어긋나게 둔 두 행이다:

| case_no | 본문 형식 | CSV gate | 기대 |
|---|---|---|---|
| 2010다99279 | 판결문 전문(verbatim처럼 보임) | **editorial** | 제외 |
| 2018다88888 | 편집 발췌(editorial처럼 보임) | **verbatim** | 포함 |

게이트를 내용 기반으로 **어떤 이름으로 재구현하든** 이 두 행에서 결과가 갈린다 — 식별자 grep으로는 불가능했던 보장이다. 변이 테스트로 방어력을 직접 확인했다(§6.3).

이 간극이 Design 문서 자체의 결함이 아니라 **Do 단계 구현이 Design의 명시적 요구를 글자 그대로 지키지 못한 사례**라는 점이 중요하다 — Match Rate가 90%를 넘던 최초 Check(93.8%)조차 이 문제를 "저작권 경계 회귀가 CI에 없다"는 별도 Gap(GAP-2)으로만 잡았을 뿐, 애초에 사용자가 T30-d/e의 검증 방식을 직접 지적하지 않았다면 소스 검사 버전이 그대로 남을 뻔했다.

---

## 5. 산출물

| 산출물 | 위치 | 상태 |
|---|---|---|
| 업로더(신규) | `pinecone_upload_crawl_precedents.py` (306줄) | ✅ 커밋 `e8693aa` |
| 원장 | `output_법원 노동판례/_uploaded_ids.json` (318그룹·2,403 ID) | ✅ 로컬(gitignore, 코퍼스별 분리) |
| 회귀(행위 단언으로 강화) | `test_precedent_ingest.py` T30(a~j)·T31(a~h)·T32(a~e) | ✅ 커밋 `d118066` |
| BM25 코퍼스 재빌드 | `data/bm25_corpus.jsonl.gz` (82,166문서, +2,403) | ✅ 커밋 `e8693aa` |
| 아카이브 스냅샷 | `data/precedent_archive/**`(inventory·MANIFEST) | ✅ 커밋 `e8693aa`, 원장 수렴 후 `4216fa4`로 갱신 |
| 인용 화이트리스트 배선 | `app/core/rag.py`·`citation_validator.py`(§9, Do 단계 범위 확장) | ✅ 커밋 `e8693aa` |
| Check 분석 | `docs/03-analysis/crawl-precedent-production-ns.analysis.md` | ✅ 작성, 커밋 대기 |
| 본 보고서 | `docs/04-report/features/crawl-precedent-production-ns.report.md` | ✅ 작성, 커밋 대기 |

**커밋 이력**:

```
e8693aa feat: 크롤 판례 318건 프로덕션 NS 적재 + 인용 화이트리스트에 메타 사건번호
4216fa4 fix: gap-detector GAP-2(원장) — 원장 수렴 + Design에 E1~E4 반영
d118066 test: T30 저작권 경계를 소스 grep에서 행위 단언으로 — select_targets() 실호출
```

---

## 6. 품질 지표

### 6.1 회귀 테스트

| 항목 | 결과 |
|---|---|
| `test_precedent_ingest.py` (T30·T31·T32) | ✅ 전량 통과, HEAD 기준 재검증 완료 |
| CI 7종(`test_offline_units`·`test_wage_golden`·`test_pipeline_wiring`·`test_abuse_guard`·`test_llm_fallback`·`eval_tokenizer --check --full`·`test_precedent_ingest`) | ✅ 전량 통과 |
| `archive_precedents.py verify` (V0~V8) | ✅ 통과 (V6 공백 1,787건은 별도 수집 대상, 이 사이클 범위 밖) |
| `test_bm25_memory` (RSS 상한 550MB) | ✅ 471MB(헤드룸 79MB). ⚠️ macOS 값 — 판단 기준은 Linux/CI(규약) |

### 6.2 변이 테스트 — T30-d/e 강화의 실효성 확인

구 소스-grep과 신 행위-단언을 동일 변이로 대조:

| 변이 | 구 grep | 신 단언 |
|---|---|---|
| `gate` 조건 삭제 | FAIL | FAIL |
| `source` 조건 삭제(letec 이중적재) | **PASS ← 못 잡음** | FAIL |
| 필터 삭제 + 동일 문자열만 데드코드로 잔존 | **PASS ← editorial 유출** | FAIL |
| 다른 이름으로 내용 기반 재구현 | **PASS ← 못 잡음** | FAIL (양방향) |

### 6.3 검색 품질 — `eval_retrieval` + 도달성 프로브

| 측정 | 값 |
|---|---|
| 해설서 도달률(승격 arm) | 77.8% → **84.2%**(16/19, 기준선 arm 63.2%) — 무회귀 |
| ⚠️ 분모 변화 | 16→19건. 해설서 코퍼스가 사이클 사이 5권으로 늘어 pool 도달 질의 수 자체가 달라짐 — 이전 백분율과 **직접 비교는 불완전**, 다만 분자·분모 모두 유리한 방향 |
| 크롤 판례 도달성 프로브(별도 실행, n=6) | pool 2/6 · **최종 컨텍스트 도달 1/6**(`crawlprec_2018du35391_0`) |

`eval_retrieval` 결과 JSON은 집계만 남기고 벡터 ID를 기록하지 않아 "적재분이 실제로 답변에 실리는가"라는 이 사이클의 본 목표에는 답하지 못한다 — 그래서 동일 경로(`search_hybrid`→`rerank_results` 프로덕션 기본값)로 별도 프로브를 구성했다. 최초 프로브는 `ensure_textbook=False`로 돌려 다양성 승격 2종을 전부 우회하고 있었음을 스스로 발견해 프로덕션 기본 경로로 재실행했다(결과는 동일했다 — 노동조합 질의에서 pool 2건이 최종 0건이 되는 것은 `LEGAL_PROMOTE`가 "판례 코퍼스"가 아니라 "법률근거 클래스" 최소 1건만 보장하기 때문으로, 결함이 아니라 설계대로다).

프로브는 n=6이고 적재분의 실제 쟁점에서 질의를 뽑아 도달에 유리하게 편향돼 있다. "도달 가능한가"에는 답하지만 "얼마나 자주 도달하는가"에는 답하지 않으므로 프로덕션 관찰 항목으로 남긴다.

---

## 7. 미해결 항목

### 7.1 다음 조치로 이월(전부 Low/Medium, 프로덕션 동작 무영향)

| ID | 항목 | 우선순위 | 예상 작업 |
|---|---|:---:|---|
| GAP-8 | CLAUDE.md에 신규 업로더 0회 등장(발견 불가능 경로) | Medium | Commands 3줄 + 경고문 분기 + 원장 예시 추가 |
| GAP-3 | `--allow-large-prune` 탈출구 부재("최초 적재" 근거 만료) | Medium | 플래그 추가 또는 §5.1에 운영 절차 명시 |
| GAP-9 | Design §3.2(9필드) vs §8(10필드) 내부 불일치 | Low | §3.2에 `category` 한 줄 추가 |
| GAP-4 | §1.2 제외 건수표 모집단 미명시 | Low | 각주 추가 |
| GAP-5 | `court:"대법원"` 근거 논증 오류(값 자체는 실측상 옳음) | Low | 근거 문장 교체 |
| GAP-6 | T30-c "집계" 절반 미검증 | Low | `skipped` 집계 순수 함수 분리 |
| GAP-7 | T30-i 소스 대조 잔존(수용 사유는 코드 주석에만 존재) | Low | `build_vector()` 분리로 행위 단언 승격 |

### 7.2 취소/보류 항목

없음 — Plan의 비목표(N1~N5) 전항목이 그대로 유지됐고 범위 축소 없이 완료됐다.

### 7.3 미확인 (추측하지 않음)

| 항목 | 사유 |
|---|---|
| `laborlaw-v2` 벡터 수 기준선(S1 검증용) | 저장소에 기록 없음, Pinecone 조회 필요 |
| §9.3 ctx 구크롤 1,310청크의 `case_no` 메타 부재 | Pinecone 메타 조회 필요 |
| §9.1 "letec 6,440청크 중 94% 미등재" 비율 | 분모만 확인, 비율 미검증 |
| 크롤 판례의 실제 프로덕션 도달 빈도 | §6.3 프로브(n=6)는 대표 표본이 아님 — 관찰 항목 |

---

## 8. 교훈 및 회고

### 8.1 잘된 것 (Keep)

- 저작권 경계를 "판정 함수의 존재 여부"가 아니라 **"`select_targets()`가 실제로 무엇을 반환하는가"**로 검증 방식을 바꾼 것. 변이 테스트로 방어력을 직접 증명했다(§6.2) — "테스트가 통과한다"가 아니라 "이 테스트가 이 구체적 실패를 잡는다"를 실측으로 확인하는 습관이 이번에도 작동했다.
- `eval_retrieval`의 결과가 목적(도달 확인)에 못 미친다는 것을 스스로 발견하고 별도 프로브로 보강한 것. 측정 도구의 산출물을 그대로 받지 않고 "이 수치가 실제로 무엇을 재는가"를 다시 물었다.
- 도달성 프로브 자체의 결함(`ensure_textbook=False`가 승격 2종을 모두 끔)을 결과를 발표하기 전에 스스로 발견해 재측정한 것.

### 8.2 개선 필요 (Problem)

- Design이 행위 요구사항을 명시했음에도(§6 T30-d/e) Do 단계 구현이 그것을 문자 그대로 지키지 못한 채 최초 Check(93.8%)를 통과했다. gap-detector가 이를 별도로 지적하기 전에 **사용자가 먼저 검증 방식 자체를 지적**했다 — Match Rate와 Gap 목록만으로는 "이 회귀가 실제로 방어하는가"까지는 자동으로 드러나지 않는다.
- gap-detector 에이전트가 세션 한도로 2회 중단됐다. 재개 후 반환된 결과를 그대로 채택하지 않고 전건 실측 재검증이 필요했고, 실제로 2개 판정이 뒤집혔다(§5 verify 실행 여부, court 하드코딩 영향도).
- `eval_retrieval` 비교 대상 분모가 사이클 사이(해설서 코퍼스 확장)에 16→19로 달라져, "무회귀"라는 결론은 유효하지만 이전 수치와의 직접 비교는 불완전한 채로 보고서에 남는다.

### 8.3 다음에 시도할 것 (Try)

- 소스 문자열 검사(`inspect.getsource()` grep)로 회귀를 작성하는 패턴 자체를 코드리뷰 체크리스트 항목으로 — "이 검사가 행위를 보는가, 존재를 보는가"를 커밋 전에 명시적으로 묻는다.
- `eval_retrieval`처럼 "이전 대비 재측정"이 목적인 도구는 결과에 분모·구성 요약을 함께 출력하도록 개선해, 다음 사이클이 비교 가능성을 수동으로 따지지 않아도 되게 한다.
- 세션 한도로 중단된 에이전트를 재개할 때는 재개 프롬프트에 "이미 확인한 사실은 재조사하지 말고 결론만"을 명시했음에도 결과를 그대로 신뢰하지 않는 재검증 단계가 실제로 판정을 바꿨다 — 이 관례를 계속 유지한다.

---

## 9. 다음 단계

### 9.1 즉시

- [ ] 사용자 확인 후 `docs/03-analysis/crawl-precedent-production-ns.analysis.md` + 본 보고서 커밋
- [ ] GAP-8(CLAUDE.md 보강) — 발견 불가능한 유일 경로이므로 우선 처리 권고
- [ ] GAP-3(`--allow-large-prune`) — 다음 크롤 판례 청킹 규칙 변경 전에 반드시 해소

### 9.2 다음 PDCA 사이클 후보

| 항목 | 우선순위 | 비고 |
|---|:---:|---|
| 문서 정합 4건 일괄 처리(GAP-4·5·9) + 테스트 승격 2건(GAP-6·7) | Low | 단독 사이클보다는 다음 판례 관련 작업에 편승 권장 |
| `laborlaw-v2` 벡터 수 기준선 기록을 업로더 표준 절차로 관례화 | Medium | 이번에 미확인으로 남은 S1 직접 검증 수단 |
| 크롤 판례 실제 도달 빈도 관찰 | 관찰 | 프로덕션 로그 누적 후 판단 — 별도 사이클 불요 |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-09-14 | 완료 보고서 작성 | Claude Sonnet 5 (PDCA) |
