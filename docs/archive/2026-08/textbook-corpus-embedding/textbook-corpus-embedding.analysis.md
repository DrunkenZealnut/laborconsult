# textbook-corpus-embedding Gap Analysis

> Plan: `docs/01-plan/features/textbook-corpus-embedding.plan.md`
> Design: `docs/02-design/features/textbook-corpus-embedding.design.md`
> 분석일: 2026-08-10 | 수행: bkit gap-detector + 주 세션 실증

## 1. Match Rate

| 구분 | 건수 |
|------|-----:|
| 총 검증 항목 | **120** |
| ✅ MATCH | 115 |
| 🔵 CHANGED (실측 편차 — 설계 갱신 대상) | 1 |
| 🔴 GAP | 1 → **수정 완료** |
| ⬜ N/A (레포 밖 실증 필요) | 3 |

**Match Rate = 116 / 117 = 99.1 %** (N/A 3건 분모 제외)
GAP-01 수정 반영 후 **117 / 117 = 100 %**

설계에 없던 의도적 보강 5건은 분모에서 제외하고 §4에 별도 기재했다.

---

## 2. 설계 항목별 대조 요약

전 120항목의 상세 대조는 gap-detector 원본 분석에 있으며, 절별 결과는 다음과 같다.

| 설계 절 | 항목 수 | 결과 |
|---------|--------:|------|
| §1.1 모듈 구성 | 14 | 전량 MATCH |
| §1.2 확정 수치 (460 / 1,407 / 1,867) | 3 | 전량 MATCH — `_uploaded_ids.json` 실측 일치 |
| §2 서적 레지스트리·벡터 ID | 9 | 전량 MATCH |
| §3 헤딩 위생 처리 | 8 | 전량 MATCH |
| §4 인용 가드 G1~G5 | 15 | 전량 MATCH |
| §5 출처 라벨 | 2 | 전량 MATCH |
| §6 벡터 메타데이터 스키마 | 7 | 전량 MATCH (설계 외 필드 추가 0건) |
| §7 Track B | 16 | 15 MATCH / **1 GAP** / 1 CHANGED |
| §8 테스트 계획 | 16 | 전량 MATCH (구현 T17~T20으로 번호 이동, 검증 내용 기준 대응) |
| §8 수동 검증 | 3 | 1 MATCH / 2 N/A |
| §9 구현 순서 14단계 + 롤백 | 15 | 14 MATCH / 1 N/A |
| §10 확정 결정 8 + 비목표 4 | 12 | 전량 MATCH |

### 설계의 핵심 주장 검증 결과

| 주장 | 검증 |
|------|------|
| chunk_id `textbook_{book_id}_{section_idx:04d}_{chunk_idx}` | `pinecone_upload_textbook.py:311` ✅ |
| `book_id` 정규식 `^[a-z0-9]+$` 강제 | 동:58 + 424-425 게이트 ✅ |
| `section_idx`가 폐기 헤딩을 소비하지 않음 | 동:327 `enumerate(sections)` — `sections`는 폐기분 제외 ✅ |
| `sanitize_heading` 5단계 + 주의점 3가지 | 동:171-201, `_SIGNIF_RE` 분모 / 조문추출 선행 / 원문 키 매칭 전부 반영 ✅ |
| 명시 치환 4건 + 폐기율 10% `sys.exit` 게이트 | 동:87-97, 56 + 280-292 ✅ |
| G4가 `format_pinecone_hits()` 진입부(단일 초크포인트) | `rag.py:374`. 호출부 전수 확인 → `pipeline.py:1640` 1곳 ✅ |
| G4 상한 3 / 순서 보존 / 비해설서 무제한 / meta_list 동시 컷 | `rag.py:305, 344-351, 346-348, 374<377` ✅ |
| 화이트리스트 긴 부호 우선 + `\s*` + 경계 | `extract_textbook_cases.py:39-47` ✅ |
| `--input`이 `--cases`와 별개이고 L2 유지 | `fetch_court_precedents.py:417-420, 441` ✅ |
| 결정 #4 `--reset` 금지 / #7 `COMPOSER_SYSTEM` 미수정 | 플래그 부재 / 해설서 문구 0건 (전수 grep) ✅ |

**G4 전파 경로 무결성** — `search_hybrid` → `reciprocal_rank_fusion`(`bm25_search.py:248` `.copy()`) → `rerank_results`(`rag.py:290` `.copy()`) → `filter_by_relevance`(`self_rag.py:111`) 네 단계 모두 hit dict를 온전히 전달하므로 `book_id`가 중간에 소실되지 않는다.

---

## 3. Gap

### 🔴 GAP-01 — `OCR_FIXES` 적용 순서 역전으로 사전이 사문화 (**수정 완료**)

| 항목 | 내용 |
|------|------|
| 심각도 | **Low** (실피해 0, 잠재 결함 + 잘못된 안전 신호) |
| 위치 | `extract_textbook_cases.py:102-104` (수정 전) |
| 설계 | §7.1 처리순서 1 — "본문 로드 → `OCR_FIXES` **적용**" 후 2에서 사건번호 추출 |
| 구현 | 추출을 먼저 하고 **추출된 사건번호 키**에 사후 remap |

**왜 문제인가** — `OCR_FIXES`의 4개 키(`2000대8127`·`2006대381`·`2021대69`·`2020도다296321`)는
`CASE_CODES` 화이트리스트에 `대`가 없고 `도다`도 유효 부호가 아니므로 **`CASE_RE`가 애초에
매칭하지 못한다.** 사후 remap은 어떤 입력에도 발동할 수 없는 사문 코드였고, 주석("fetch와
동일 사전 재사용")이 사전이 작동한다는 잘못된 인상을 줬다. **화이트리스트가 오인식 부호를
걸러내는 바로 그 성질이 정정 경로를 차단한다** — 두 방어가 서로를 무력화한 사례다.

**실증 (주 세션에서 직접 확인)**

```text
OCR_FIXES 키 → extract_cases 결과
  '2000대8127'     → 추출 없음        (본문 선치환 시 → ['2000다8127'])
  '2006대381'      → 추출 없음        (            → ['2006다381'])
  '2021대69'       → 추출 없음        (            → ['2021다69'])
  '2020도다296321' → 추출 없음        (            → ['2020다296321'])

Win 본문 내 오인식 표기 실제 출현: 2000대8127 2회 / 2006대381 1회 /
                                  2021대69 1회 / 2020도다296321 2회  (총 6회)
```

**실피해 = 0** — 정정형 4건은 모두 이전 사이클에 처리돼 있다.
`2000다8127`·`2006다381`·`2021다69`는 `_미발견.csv`에, `2020다296321`은 `_progress.json`의
`fetched`에 있어 어느 쪽이든 차감 대상이었다.

**수정 내용** (`extract_textbook_cases.py`)

```python
body = load_body(book)
for wrong, right in OCR_FIXES.items():      # 설계 §7.1 처리순서 1
    body = body.replace(wrong, right)
cases = extract_cases(body)
```

**수정 검증** — Win 고유 사건번호 925 → **928건**(+3), 4건 전량 추출 확인.
회귀는 `test_precedent_ingest.py` **T20-j**(사후 remap으로는 정정 불가)와
**T20-k**(본문 선치환이면 정정됨) 8 assertion으로 고정했다.

---

## 4. 설계 문서 갱신 대상 (구현이 옳고 설계가 낡음)

Gap과 분리한다. 아래는 모두 **구현 중 발견된 결함을 보강한 것**이라 설계를 실물에 맞춰야 한다.

| # | 절 | 설계 서술 | 구현 실물 | 사유 |
|---|----|-----------|-----------|------|
| U-1 | §4.2 | `book = h.get("book_id")` — 메타데이터만 신뢰 | `rag.py:311-327` `_book_id_of()` — ①메타데이터 → ②벡터 ID 역파싱 → ③`source_type=="textbook"`이면 `"_unknown"`으로 상한 적용 | **BM25 경로에서 G4가 통째로 우회되던 결함.** BM25 코퍼스는 `{id,text,title,section,source_type}`만 담아 `book_id`가 없었다. 회귀 T19-e/f/g |
| U-2 | §4.2 / §6 | 언급 없음 | `build_bm25_corpus.py:69-72` + `bm25_search.py:177` `book_id` 보존 | U-1의 짝. 코퍼스가 정본, rag.py가 폴백인 **2중 구조**. 하나만 두면 구 코퍼스 또는 신규 소스에서 가드 무력화 |
| U-3 | §3.5 | "`load_body(book)`로 시그니처가 바뀌므로 호출부를 함께 수정" | `pinecone_upload_textbook.py:219-232` `load_body_normalized()` 신규 | enrich는 본문을 통째로 훑어 표제 경로를 뽑으므로 **위생 처리된 마크다운**이 필요하다. 인자 추가만으로는 위생 규칙을 두 곳에 복제하게 된다 |
| U-4 | §3.4 | 폐기율 분모 명시 없음 | `parse_sections()`가 `(sections, kept_headings, dropped)` 3튜플 반환 | 본문이 빈 섹션은 `sections`에서 빠지므로 `len(sections)`가 분모면 **폐기율이 부풀려져** 정상 서적이 10% 게이트에 걸린다 |
| U-5 | §8 T16-c 기대값 | `→ 제43조의5(업무위탁 등)` (괄호 내 공백 유지) | 테스트 기대값 `제43조의5(업무위탁등)` | **설계 내부 모순** — §3.2 코드의 `re.sub(r"\s+", "", m.group(1))`이 괄호 내부 공백까지 제거한다. §3.2가 정본 |
| U-6 | §7.4 | "실수집률 83% → 약 138건" | 실제 **120건** (72.3%) | 교재 인용 판례는 하급심·구판례 비중이 높아 법제처 DB 미수록률이 선행 사이클보다 높다. 후속 기준선은 **72%** |

추가로 §4.2 트레이드오프 문단에 "`book_id`가 식별되지 않는 해설서 hit는 `_unknown` 버킷으로
묶어 상한을 건다"를 명기할 것 — 설계 의사코드가 "`book_id` 없으면 무제한"으로 읽힌다.

---

## 5. 관찰 사항 (Gap 아님)

| ID | 내용 | 판단 |
|----|------|------|
| OBS-1 | `_cap_by_book`이 `content`가 빈 hit도 상한 카운트에 포함 | 가드가 **더 엄격해지는** 방향이라 저작권 통제상 무해. 실제 textbook 청크는 항상 본문을 가짐 |
| OBS-2 | `_BOOK_ID_RE` 검증이 `main()`에만 있어 `build_chunks()` 직접 호출 경로는 우회 | 업로드 경로는 반드시 `main()`을 거치므로 실피해 없음 |
| OBS-3 | **Do 단계 보고의 "7스위트 통과"는 부정확** — CI 정의는 **9스텝**(Python 6 + Node 3) | Node 2건(`test_answer_renderer.js`·`test_answer_glance.js`)을 빠뜨렸다. Check 단계에서 **9스텝 전량 재실행해 통과 확인** |
| OBS-4 | 하이브리드+rerank에서 해설서가 항상 상위는 아님 — "최저임금 산입범위와 상여금"은 Dense 단독 1위(juhae3 0.562)였으나 하이브리드에선 qa 8건에 밀림 | 결함 아님. 코퍼스 경쟁의 정상 결과이며 편중이 없다는 방증 |
| OBS-5 | 일부 섹션 라벨에 OCR 잡음 꼬리 잔존 (예: `2. 예외 사유 품 등 LIA 조지 법 법 보증소 19주입시원 지`) | 설계 §3.1이 수용한 잔여분. 본문 검색에는 영향 없고 출처 표시만 지저분 |

---

## 6. 실측 검증 결과

| 항목 | 목표/설계 | 실측 | 근거 | 판정 |
|------|-----------|------|------|:----:|
| textbook 벡터 | 1,867 | **1,867** (win 1,407 + juhae3 460) | `_uploaded_ids.json` | ✅ |
| `laborlaw-v2` 총계 | 11,229 → 13,096 | **13,096** (해설서 후) → **13,520** (판례 후) | `describe_index_stats` | ✅ |
| chunk_id 충돌 | 0 | **0** | 업로드 전 사전 게이트 통과 + ID 목록 중복 0 | ✅ |
| Track B 대상 | 166 | **166** | `누락_판례목록_교재통합.csv` | ✅ |
| 판례 저장 | 약 138 예상 | **120건** (72.3%) | 166 − 46 | 🔵 U-6 |
| 판례 미발견 | — | **46건** | `_미발견.csv` 110 → 156 | ✅ |
| BM25 코퍼스 | 갱신 | **64,606** (62,315 → +2,291 = textbook 1,867 + 판례 424, 산술 정합) | `bm25_corpus.json.gz` 16.8MB | ✅ |
| BM25 `book_id` 보존 | 필수 | **win 1,407 / juhae3 460** | 코퍼스 직접 조회 | ✅ |
| 오프라인 테스트 | 전량 통과 | **9스텝 전량 통과** (Python 6 + Node 3) | GAP-01 회귀 T20-j/k 8 assertion 포함 | ✅ |
| 인용 가드 | G1~G5 | **5/5 구현·동작 확인** | G4 종단 검증: "체불사업주 명단 공개" 질의에서 rerank 상위 8건 전부 juhae3 → **3건으로 컷**, 컨텍스트 헤더 `[노동법 해설서]` 확인 | ✅ |
| 검색 양성 | 3종 | **4종 양성** (최저임금 산입범위 / 임금 직접지급 예외 / 휴업수당 산정 / 체불사업주 명단공개), 대조군 2종은 판례·행정해석 우세 | Dense + BM25 양쪽 | ✅ |
| 답변 표본 G1/G3 | 3건 | 미실행 | LLM 실행 필요 — Report 전 수행 권장 | ⬜ |
| 롤백 경로 | ID 목록 | **확보** (1,867건, 중복 0) | `_uploaded_ids.json` | ✅ |

---

## 6-b. 후속 리뷰 결과 (/simplify + code-analyzer)

Check 이후 `/simplify`(4 에이전트)와 `code-analyzer`를 추가로 돌려 **설계·Gap 분석이 모두
놓친 결함 3건**을 잡았다. 셋 다 조용히 실패하는 유형이다.

| ID | 결함 | 심각도 | 조치 |
|----|------|--------|------|
| **P-1** | **G1~G3이 `SYSTEM_PROMPT_TEMPLATE` 분기에서 누락** — 답변 경로가 두 갈래인데 규칙을 `CONSULTATION_SYSTEM_PROMPT`에만 넣었다. 해설서 청크는 분기와 무관하게 컨텍스트에 실리므로 **임금계산·괴롭힘 판정·법제처 실패 경로에서 저작물이 무가드로 LLM에 들어갔다.** 설계 §4.3은 `COMPOSER_SYSTEM`만 확인했고, `pipeline.py` 인라인 템플릿은 `prompts.py` grep에 안 걸렸다 | High | `TEXTBOOK_CITATION_RULES` 상수 분리 → `INJECTION_RESISTANCE`와 같이 두 분기 모두에 접미. 회귀 T19b |
| **P-2** | **해설서 근거 답변이 공개 게시판에 재게시** — `/api/board/*`가 `qa_conversations.answer_text`를 전문 공개하는데 `_PUBLIC_EXCLUDE_KEYS`는 `guard_flag`/`truncated`뿐이었다. **Plan §3.2는 `chunk_text` 미노출만 근거로 삼고 답변 재게시를 다루지 않았다** — 설계 전제의 공백 | High | G6 추가 — `metadata.textbook` → `_PUBLIC_EXCLUDE_KEYS`. 회귀 T19b-k~m |
| **P-3** | **`sync_overlap_precedents.py` 파손** — `load_body` 시그니처 변경 시 소비자 스윕이 `enrich_court_precedents.py`에서 멈췄다. 함수 안 import라 실행 시점에야 `ImportError` | Medium | `BOOKS["win"]`으로 복구 |

부수 수정 — 롤백 기록을 upsert **이전**에 쓰고 합집합 처리(중간 실패 시 적재분 미추적 방지),
헤딩 0개일 때 폐기율 게이트 통과 차단, `extract_textbook_cases`의 NFC 선행, BM25 코퍼스의
빈 `book_id` 제거(상주 메모리 5.7MB), 프론트 라벨 3종 누락(`law_article`·`nlrc_case`·`graph`가
raw로 노출 중이던 선재 결함).

**교훈**: Gap 분석이 120항목을 설계와 대조해 100%를 냈지만, P-1·P-2는 **설계 자체의 공백**이라
대조로는 잡히지 않았다. 설계 대비 검증과 별개로 "이 변경이 닿는 경로 전부"를 훑는 리뷰가
필요하다.

---

## 7. 미결 조치

| # | 조치 | 상태 |
|---|------|------|
| 1 | GAP-01 수정 + 회귀 T20-j/k | ✅ 완료 |
| 2 | `data/bm25_corpus.json.gz` **커밋** (16.8MB, 이전 커밋본 16.1MB) | ✅ 완료 — `5b0bc03`에 포함(16,760,091 B). 커밋본을 직접 풀어 64,606건 / textbook 1,867(win 1,407·juhae3 460) / `book_id` 전량 보존 검증 |
| 3 | 설계 문서 U-1~U-6 반영 후 v1.1 | ✅ 완료 |
| 4 | 답변 표본 3건으로 G1(축자 인용 0건)·G3(서명 표기) 확인 | ⏳ Report 전 |
| 5 | 배포 후 1주간 `_cap_by_book` 드롭 로그 관측 — G4 발동 빈도와 컨텍스트 축소 영향 | ⏳ 운영 |

---

## 변경 이력

| 버전 | 일자 | 내용 |
|------|------|------|
| 1.0 | 2026-08-10 | Gap 분석 최초. 120항목 대조, Match Rate 99.1%, GAP 1건(Low) 수정 완료 → 100%, 설계 갱신 대상 6건 |
