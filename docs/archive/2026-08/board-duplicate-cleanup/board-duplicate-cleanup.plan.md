# 질문게시판 중복 정리 Planning Document

> **Summary**: 공개 질문게시판 463건 중 225건(48.6%)이 반복 게시된 중복 질문. 중복 그룹당 최신 1건만 남기고 하드 삭제하여 238건으로 정리하고, 근본 원인인 "벤치마크·테스트 실행이 프로덕션 게시판에 그대로 저장되는 구조"를 차단한다.
>
> **Project**: laborconsult
> **Author**: Claude
> **Date**: 2026-08-12
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 공개 게시판 463건 중 225건(48.6%)이 같은 질문의 반복. 원인은 사용자 오조작이 아니라 **`benchmark_pipeline.py`가 `bench_*` 세션으로 프로덕션 Supabase에 그대로 기록**하는 구조 — 합성/테스트 데이터가 323건(69.8%)을 차지한다. 벤치마크를 한 번 더 돌리면 즉시 원상 복귀한다. |
| **Solution** | ① 일회성 정리 스크립트(`dedupe_board.py`)로 질문 정규화 후 그룹당 **최신 1건만 유지**하고 나머지 225건을 하드 삭제(dry-run + 백업 JSON 의무). ② `save_conversation()` 단일 초크포인트에 **예약 접두사 가드**를 넣어 합성 세션이 공개 게시판에 노출되지 않게 구조적으로 차단. |
| **Function/UX Effect** | 게시판 첫 페이지에 같은 질문이 반복되던 현상 소멸. 463 → 238건, 14개 카테고리 전 영역 유지(임금·수당 40, 휴가·휴일 35, 퇴직금 24 …). 사용자는 매 페이지에서 새 사례를 보게 된다. |
| **Core Value** | 게시판이 "테스트 로그 덤프"에서 "읽을 만한 상담 사례집"으로 전환 — 체류·SEO 가치 회복. 동시에 재발 경로를 봉인해 정리 작업이 일회성으로 끝난다. |

---

## 1. Overview

### 1.1 Purpose

공개 질문게시판(`/api/board/*`, `public/index.html` 슬라이드 메뉴 → `#board-section`)에 노출되는 `qa_conversations` 463건에서 중복 질문을 제거하여 238건으로 정리한다. 아울러 중복을 만들어낸 저장 경로를 차단해 재발을 막는다.

### 1.2 Background — 실측 데이터 (2026-08-12 Supabase 직접 조회)

**전체 규모**

| 구분 | 건수 |
|------|------|
| `qa_conversations` 총 행 | 470 |
| 공개 제외(`metadata.textbook`) | 7 |
| **공개 게시판 노출** | **463** |
| `board_posts` (사용자 직접 작성) | 0 |

**출처별 분해** — `session_id` 접두사 기준

| 출처 | 건수 | 비율 | 생성 주체 |
|------|-----:|-----:|-----------|
| `bench_*` | 225 | 48.6% | `benchmark_pipeline.py:168` |
| hex12 (실사용 형태) | 140 | 30.2% | `session.py:130` — 웹 사용자 **또는** HTTP e2e 테스트 |
| `cmp_*` | 51 | 11.0% | 모델 비교 실행 |
| `test_*` | 9 | 1.9% | `test_legal_cases_e2e.py:101` |
| 기타(UUID형·`verify_*` 등) | 38 | 8.2% | 임시 검증 스크립트 |
| **합성/테스트 소계** | **323** | **69.8%** | |

**중복 실태**

| 지표 | 값 |
|------|-----|
| 고유 질문 수 (정규화 기준) | 238 |
| 중복 그룹 수 | 135 |
| 제거 가능 건수 | **225** |
| 최다 반복 질문 | 12회 ("본인은 2021년 10월28일 오후12:30분경 …" 산업재해 사례) |
| **답변까지 동일한 그룹** | **0 / 135** |
| 그룹 내 카테고리 불일치 | 3 / 135 |
| 답변 없음 / 100자 미만 | 0건 / 0건 |
| 중복 제거 후보 중 첨부 보유 | 0건 |

핵심 관찰 셋:

1. **완전일치와 느슨일치의 차이가 1건뿐**(239 vs 238). 사람이 비슷하게 다시 쓴 게 아니라 **같은 문자열이 그대로 재실행**된 것 — 사용자의 "테스트했던 질문을 몇 번씩 올린 것 같다"는 진단이 데이터와 정확히 일치한다.
2. **답변은 매번 다르다**(135그룹 전부). 매 실행이 LLM을 새로 호출했기 때문이며, 대체로 후기 답변이 더 길다(예: "주휴수당이 뭔가요?" 1,257자 → 1,997자). 따라서 "어느 것을 남기냐"가 실질적 품질 선택이 된다.
3. **실사용(hex12) 140건 중 32건이 합성 질문과 문구가 동일**하다. `test_e2e.py`가 로컬 서버에 HTTP로 붙으면 서버가 정상 hex12 세션을 발급하므로, **접두사만으로는 테스트 트래픽을 완벽히 분리할 수 없다**.

### 1.3 근본 원인

```
benchmark_pipeline.py:168   session = Session(id=f"bench_{case.case_id}")
        ↓
app/core/pipeline.py:2118   conv_id = save_conversation(config.supabase, record)   ← 무조건 저장
        ↓
Supabase qa_conversations
        ↓
api/index.py::board_recent / board_search                                        ← 공개 노출
```

`process_question()`은 호출 주체를 구분하지 않고 저장한다. 게시판은 `qa_conversations`를 직접 읽으므로 **벤치마크 1회 실행 = 게시글 수십 건 생성**이다. 2026-03-13 하루에만 벤치마크 213건이 적재됐다.

### 1.4 Related Documents / Files

- 게시판 API: `api/index.py:909-1104` (`board_recent`, `board_categories`, `board_search`, `board_detail`)
- 공개 제외 메커니즘: `api/index.py:353-386` (`_PUBLIC_EXCLUDE_KEYS`, `_apply_guard_filter`, `_is_public_excluded`)
- 저장 초크포인트: `app/core/storage.py:158` (`save_conversation`) ← **유일 호출부** `app/core/pipeline.py:2118`
- 스키마: `supabase_schema.sql` (`qa_conversations`, CASCADE 관계)
- 보존기간 정책: `supabase_retention_purge.sql` (대화 365일 — 최고령 2026-03-08이므로 아직 미도래)
- 기존 게시판 Plan: `docs/01-plan/features/qna-board-page.plan.md`, `board-write-security.plan.md`

---

## 2. Scope

### 2.1 In Scope

- [ ] FR-01: 중복 판정 정규화 규칙 정의 및 구현
- [ ] FR-02: 정리 스크립트 `dedupe_board.py` — dry-run 기본, 백업 JSON, 그룹당 최신 1건 유지
- [ ] FR-03: 하드 삭제 실행 (225건) 및 결과 검증
- [ ] FR-04: 고아 `qa_sessions` 정리
- [ ] FR-05: 재발 방지 — `save_conversation()` 예약 접두사 가드
- [ ] FR-06: `_PUBLIC_EXCLUDE_KEYS`에 합성 플래그 추가
- [ ] FR-07: HTTP 경유 테스트 트래픽 식별 레버 (Design에서 방식 확정)
- [ ] FR-08: 오프라인 회귀 테스트 (정규화·대표선정·가드)

### 2.2 Out of Scope

- **`board_posts` 스키마 불일치 수정** — `api/index.py:854`가 존재하지 않는 `nickname` 컬럼을 select해 PostgREST 42703이 나고 `try/except`에 삼켜진다. 현재 행이 0건이라 무증상이지만 사용자 글이 등록되는 순간 **게시판에서 통째로 사라진다.** 별도 사이클로 처리 (§7.1)
- 게시판 UI/디자인 변경
- 중복 방지용 DB UNIQUE 제약 (같은 질문의 재상담은 정상 시나리오이므로 부적절)
- 답변 품질 재생성 / 오래된 답변 재작성
- 관리자 대시보드에 삭제 기능 추가
- Pinecone 코퍼스 (별개 저장소, 영향 없음)

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | **정규화 규칙**: `unicodedata.normalize("NFC", q).lower()` 후 `[^\w가-힣]` 제거(공백·구두점·이모지 무력화). 이 규칙으로 463건 → 고유 238개. macOS NFD 파일명 이슈와 동일한 이유로 **NFC 선행이 필수** | High | Pending |
| FR-02 | **정리 스크립트** `dedupe_board.py`: (1) `--dry-run` 기본값, 실제 삭제는 `--apply` 명시 필요 (2) 삭제 전 대상 전량을 `backup_board_dedupe_{YYYYMMDD}.json`으로 덤프 (3) 그룹당 `created_at` **최댓값 1건 유지**, 나머지 삭제 (4) 삭제 건수·유지 건수·카테고리 분포를 콘솔 출력 | High | Pending |
| FR-03 | **하드 삭제**: `qa_conversations`에서 225개 행 DELETE. 배치 크기 제한(PostgREST `in_` 한계 고려)으로 분할 실행, 실패 시 남은 배치 중단하고 진행분 리포트 | High | Pending |
| FR-04 | **고아 세션 정리**: 삭제 후 `qa_conversations`가 하나도 없는 `qa_sessions` 행 제거. `supabase_retention_purge.sql:166-168`의 기존 고아 판정 로직과 동일 조건 사용 | Medium | Pending |
| FR-05 | **예약 접두사 가드**: `save_conversation()`(단일 초크포인트)에서 `session_id`가 예약 접두사(`bench_`, `test_`, `cmp_`, `verify_`, `eval_`)로 시작하면 `metadata.synthetic = True` 스탬프. 저장 자체는 유지 — 벤치마크 결과 사후 대조 가능성을 남긴다 | High | Pending |
| FR-06 | **공개 제외 확장**: `_PUBLIC_EXCLUDE_KEYS`에 `"synthetic"` 추가. 기존 3종(`guard_flag`/`truncated`/`textbook`)과 동일 메커니즘이므로 새 개념 없음 | High | Pending |
| FR-07 | **HTTP 테스트 식별**: 접두사로 못 잡는 e2e 트래픽(hex12 발급) 대응 레버. 후보 — (a) 로컬호스트 요청 자동 `synthetic` (b) 배포환경 판별(`VERCEL_ENV != production`) (c) 테스트 전용 헤더 + 서버측 허용 조건. **외부에서 임의로 켤 수 없는 방식**이어야 함. Design에서 택일 | Medium | Pending |
| FR-08 | **회귀 테스트**: `test_offline_units.py`에 추가 — (1) 정규화가 NFD/공백/구두점 변형을 같은 키로 묶는지 (2) 대표 선정이 최신 1건인지 (3) 예약 접두사 세션에 `synthetic` 플래그가 붙는지 (4) 정상 hex12 세션에는 **붙지 않는지**(오탐 0) | High | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| Safety | 삭제 전 백업 JSON 생성 실패 시 삭제 중단 (백업 없는 삭제 0건) | 스크립트 코드 리뷰 + dry-run 로그 |
| Safety | `--apply` 없이는 어떤 쓰기도 발생하지 않음 | dry-run 실행 후 행 수 불변 확인 |
| Correctness | 삭제 후 공개 게시판 조회 시 중복 그룹 0개 | 삭제 후 재조사 스크립트 |
| Correctness | 유지된 238건이 모두 답변 보유(빈 답변 0건) | 검증 쿼리 |
| Compatibility | 첨부 CASCADE 영향 0건 (중복 후보 중 첨부 보유 0건 — 실측 확인) | 사전 조회 |
| Fail-open | FR-05 가드 예외가 상담 저장을 막지 않을 것 (기존 전 계층 fail-open 규약 준수) | 코드 리뷰 |
| Reversibility | 백업 JSON만으로 전량 재삽입 가능한 필드 구성(id 포함) | 백업 스키마 검토 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] `dedupe_board.py --dry-run` 이 삭제 225 / 유지 238 을 보고
- [ ] 백업 JSON 225건 생성 확인 (id·session_id·question·answer·category·metadata·created_at 포함)
- [ ] `--apply` 실행 후 `qa_conversations` 공개 대상 = 238건
- [ ] 재조사 스크립트에서 중복 그룹 0개
- [ ] 게시판 1~5페이지에 같은 질문 반복 없음 (육안)
- [ ] 14개 카테고리 전부 잔존 (임금·수당 40 / 휴가·휴일 35 / 퇴직금 24 / 해고 23 / 직장내 괴롭힘 23 / 산업재해 22 / 실업급여 16 / 일반상담 16 / 육아·출산 13 / 4대보험 8 / 근로조건 7 / 임금체불 5 / 비정규직 3 / 노동조합 3)
- [ ] `benchmark_pipeline.py` 재실행 후 게시판 건수 불변 (238 유지)
- [ ] `python3 test_offline_units.py` 통과

### 4.2 Quality Criteria

- [ ] 백업 없는 삭제 0건
- [ ] 정상 사용자 대화 오삭제 0건 — 삭제분 225건 전부가 "동일 질문 그룹의 비최신 항목"임을 백업 JSON으로 대조
- [ ] FR-05 가드 오탐 0건 (hex12 세션에 `synthetic` 미부착)

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| **하드 삭제는 되돌릴 수 없다** | High | — | dry-run 기본값 + 백업 JSON 생성 성공을 삭제의 전제조건으로 강제. 백업에 `id` 포함해 원본 UUID까지 복원 가능하게 구성 |
| 관리자 대시보드 누적 통계가 225건 줄어든다 | Medium | 확실 | 의도된 결과. 다만 **삭제분 중 52건이 최근 30일 이내**(2026-07-13 이후)라 `/api/admin/stats`의 30일 일별 그래프가 눈에 띄게 변한다. 사전 고지 필요 |
| 같은 질문을 실제로 다시 물은 정상 상담까지 삭제 | Medium | Low | 답변은 남고 질문 1건만 사라지는 구조라 정보 손실은 제한적. 백업으로 개별 복구 가능. 실사용 중복 27건 중 최다는 동일 산재 사례 10회 반복으로, 사람이 재상담한 것으로 보기 어려움 |
| 삭제 도중 중단 → 부분 삭제 상태 | Medium | Low | 배치 단위 진행 로그 출력, 재실행 시 이미 삭제된 id는 무해하게 스킵(멱등). 백업은 실행 시작 시점 1회 생성 |
| 그룹 내 카테고리가 갈리는 3건에서 예상 밖 카테고리가 대표가 됨 | Low | Medium | "최신 유지" 규칙이 카테고리 선택도 결정한다. dry-run 출력에 카테고리 불일치 그룹을 별도 표시해 실행 전 확인 |
| FR-05 가드가 정상 상담 저장을 막음 | High | Low | 저장 차단이 아니라 **플래그 스탬프**만 하므로 저장 실패 경로가 없다. 가드 내부 예외는 try/except로 흡수(fail-open) |
| FR-07 헤더 방식 채택 시 외부에서 악용해 저장 회피 | Medium | Medium | 헤더 단독 신뢰 금지. 로컬호스트/배포환경 판별과 결합하거나 헤더 방식을 배제 — Design에서 결정 |
| 유지되는 238건 중 105건이 `bench_*` 세션 소속 | Low | 확실 | 게시판은 category/question/answer/created_at만 노출하고 `session_id`는 응답에 없으므로 **사용자에게 보이지 않는다**. 내용 자체는 정상 노동법 Q&A. FR-06 가드는 신규 저장분에만 적용되며 기존 잔존분은 §7.2 참조 |

---

## 6. Architecture Considerations

### 6.1 파일 구조

```
dedupe_board.py                ← FR-01~04: 신규 정리 스크립트 (루트, 기존 운영 스크립트 관례)
app/core/storage.py            ← FR-05: save_conversation()에 예약 접두사 가드
api/index.py                   ← FR-06: _PUBLIC_EXCLUDE_KEYS에 "synthetic" 추가
                                  FR-07: HTTP 테스트 식별 레버 (방식 미정)
test_offline_units.py          ← FR-08: 회귀 4종
```

### 6.2 정리 스크립트 흐름

```
python3 dedupe_board.py                 # dry-run (기본)
python3 dedupe_board.py --apply         # 실제 삭제

  ① 전량 페이징 조회 (range 1000 단위)
  ② 공개 제외 키 필터 → 463건
  ③ 정규화 키로 그룹핑 → 238 그룹
  ④ 그룹당 created_at 최댓값 1건 유지, 나머지 drop 목록
  ⑤ [dry-run] 요약 출력 후 종료
     [apply]   백업 JSON 저장 → 성공 확인 → 배치 DELETE → 고아 세션 정리 → 검증 재조회
```

**동률 처리**: `created_at`이 같은 경우 `id` 사전순으로 결정론적 선택 (재실행 시 같은 결과 보장).

### 6.3 재발 방지 — 저장 초크포인트 가드

`save_conversation()`은 `pipeline.py:2118` **단일 호출부**를 갖는다. 해설서 인용 가드 G4(`_cap_by_book`)를 `format_pinecone_hits()` 진입부에 둔 것과 같은 이유로, 가드를 이 지점에 두면 호출부가 늘어나도 새지 않는다.

```
save_conversation(sb, record)
  └─ record.session_id 가 예약 접두사로 시작?
       ├─ 예 → metadata["synthetic"] = True  (저장은 그대로 수행)
       └─ 아니오 → 변경 없음

api/index.py::_PUBLIC_EXCLUDE_KEYS = ("guard_flag", "truncated", "textbook", "synthetic")
  └─ 게시판 조회에서 자동 제외 (_apply_guard_filter + _drop_flagged 이중 방어 기존 구조 재사용)
```

**왜 저장 차단이 아니라 플래그인가**: (1) 벤치마크 결과를 나중에 대조할 여지를 남긴다 (2) 기존 3종 제외 키와 동일한 메커니즘이라 새 개념·새 실패 모드가 없다 (3) `_apply_guard_filter` 실패 시 Python 후처리(`_drop_flagged`)가 받아주는 이중 방어를 그대로 물려받는다.

**한계 명시**: 접두사 가드는 `Session(id=...)`를 직접 만드는 호출부만 잡는다. `test_e2e.py`처럼 HTTP로 서버를 때리는 테스트는 서버가 hex12를 발급하므로 걸리지 않는다 → FR-07이 이 구멍을 담당한다.

### 6.4 정규화 규칙 상세

```python
def _norm_question(t: str) -> str:
    t = unicodedata.normalize("NFC", t or "").lower()
    return re.sub(r"[^\w가-힣]", "", t)
```

| 단계 | 이유 |
|------|------|
| NFC 정규화 | 한글 자모 분해(NFD) 문자열이 완성형과 다른 키가 되는 것 방지 — `pinecone_upload_legal.py`에서 474벡터 유실을 낸 것과 같은 실패 모드 |
| lower() | 영문 혼용 질문 대응 |
| `[^\w가-힣]` 제거 | 공백·줄바꿈·구두점·이모지 차이 무력화. 실측상 완전일치 대비 1건만 추가 병합되므로 **과병합 위험이 낮음이 확인됨** |

### 6.5 삭제가 건드리는 것 / 안 건드리는 것

| 대상 | 영향 |
|------|------|
| `qa_conversations` | 225행 삭제 |
| `qa_attachments` | CASCADE — 실측 연결 0건이므로 실제 삭제 0 |
| `qa_sessions` | 고아 세션만 정리 (FR-04) |
| `/api/admin/stats` | 총계·카테고리·30일 일별 모두 감소 (최근 30일분 52건) |
| `board_posts` | 무관 (0행) |
| Pinecone 코퍼스 | 무관 — 별개 저장소 |
| `data/bm25_corpus.json.gz` | 무관 |

---

## 7. Follow-up / Notes

### 7.1 발견된 별건 결함 — `board_posts.nickname` 부재 (Out of Scope)

조사 중 확인: `api/index.py:854`·`886`·`1091`이 `board_posts`에서 `nickname` 컬럼을 select하지만 실제 테이블에 해당 컬럼이 없다(PostgREST `42703`). 세 지점 모두 `try/except`로 감싸여 있어 **오류가 조용히 삼켜지고 사용자 글이 목록·상세에서 전부 사라진다.** 현재 `board_posts` 행이 0건이라 무증상이지만, 게시판 글쓰기가 사용되기 시작하면 즉시 실장애가 된다. CLAUDE.md가 경고한 "`board_posts`에 metadata 필터 걸면 400이 try/except에 삼켜져 사용자 게시글이 통째로 사라진다"와 **정확히 같은 실패 모드**이며, 이번엔 원인이 필터가 아니라 스키마 드리프트다.

→ 별도 사이클 권장. 즉시 조치가 필요하면 `board-write-security.plan.md` FR-06의 스키마를 실제 DB에 반영(`ALTER TABLE board_posts ADD COLUMN nickname TEXT`)하거나, select 목록에서 `nickname`을 제거하는 둘 중 하나.

### 7.2 잔존 합성 데이터에 대한 판단

이번 범위(중복만 제거) 선택에 따라 유지 238건 중 105건이 `bench_*`, 13건이 기타 합성 세션 소속으로 남는다. 이는 의도된 수용이다 — 내용상 정상 노동법 Q&A이고, `session_id`는 공개 응답에 포함되지 않아 사용자에게 보이지 않는다. FR-05/FR-06 가드는 **신규 저장분에만** 적용되므로 기존 잔존분을 소급 제외하지 않는다. 향후 "합성 데이터 전량 제외(→140건)"로 방침을 바꾸려면 백필 스크립트가 별도로 필요하다.

### 7.3 실행 순서 권고

재발 방지(FR-05~07)를 **정리(FR-02~04)보다 먼저** 배포한다. 순서가 바뀌면 정리 완료 후 배포 전까지의 벤치마크 실행이 다시 오염을 만든다.

---

## 8. Approvals

| Role | Name | Date | Status |
|------|------|------|--------|
| Author | Claude | 2026-08-12 | Draft |
| Reviewer | — | — | Pending |

---

## 9. 결정 기록 (2026-08-12)

| 항목 | 결정 | 대안 |
|------|------|------|
| 제거 범위 | **중복만 제거 → 238건** | 합성 전량 제외(140건), 합성+실사용중복 제거(113건) |
| 제거 방식 | **DB 행 하드 삭제** | metadata 플래그 숨김(가역), 하드삭제+백업 |
| 대표 선정 | **가장 최근 1건** | 답변 최장, 가장 오래된 것 |
| 재발 방지 | **이번 범위에 포함** | 별도 사이클 |

※ "하드 삭제" 결정에도 불구하고 백업 JSON은 FR-02에서 필수로 둔다 — 되돌릴 수 없는 작업의 최소 안전장치이며, DB를 깨끗하게 유지한다는 결정 취지와 상충하지 않는다.
