# llm-fallback-alert-blindspot 갭 분석 (Check)

> **요약**: 설계 102개 항목 중 97건 일치, 5건 부분 불일치, 미구현 0건이다. **Match Rate 95.1%**. 결함으로 볼 만한 것은 Medium 2건이다. 하나는 SSE 경로에서 기록이 오류 안내보다 먼저 실행되는데 지연 상한이 보장되지 않는다는 점, 다른 하나는 stage=pipeline 실패를 "전 제공자 실패"로 표기한다는 점이다. 나머지는 Low다.
>
> **설계**: `docs/02-design/features/llm-fallback-alert-blindspot.design.md` (v0.1)
> **계획**: `docs/01-plan/features/llm-fallback-alert-blindspot.plan.md` (§8 U1~U4 확정)
> **구현**: 브랜치 `fix/fallback-alert-blindspot`, 미커밋 11개 파일 (+679 / −58)
> **분석일**: 2026-10-30 · **분석**: gap-detector(bkit) · **저장·전제 검증**: Claude — M-1의 전제 두 가지(`app/config.py`의 `make_supabase_client()` 무인자 호출 = supabase-py 기본 타임아웃 120초, SSE 두 경로가 기록 뒤 안내)를 코드로 다시 확인했다.

---

## 1. 분석 방법

- 설계 §2.3~§12를 조항 단위로 나눠 코드와 하나씩 대조했다. 판정은 모두 해당 코드를 읽은 뒤에 내렸다.
- `git diff`로 정상 경로 변경 범위를 확인했다(V-6). pipeline.py에서 정상 경로에 닿는 변경은 다음 셋뿐이다.
  - `_category_for`·`_synthetic_flag` 추출 — 바이트 단위로 같은 블록이다.
  - `_stream_answer`에 `failures.append` 2줄 추가.
  - `.sql` 변경 0건(DDL 없음).
- 아래는 Do 단계 기록을 그대로 사실로 받았다(재실행하지 않음). 테스트 함수의 존재와 단언 내용은 읽어서 확인했다.
  - 테스트 전부 통과(alert 25건).
  - 변이 검사 6/6.
  - 로컬 재현 행 1건.
  - 프로덕션 감시 exit 0.

## 2. 점수

| 구분 | ✅ | 판정 대상 | 비고 |
|---|:-:|:-:|---|
| §2.3 의존 · §3 데이터 모델 | 19 | 19 | |
| §4 기록 경로 | 13 | 13 | |
| §5 감시 | 17 | 19 | 출력 형식 2건 |
| §6 관리자 | 3 | 4 | 목록 표지는 N/A로 분모에서 제외 |
| §7 보안 | 5 | 5 | |
| §8 테스트 | 17 | 19 | T-F6·T-F7 단언이 약함. B5b는 ➕로 분모 제외 |
| §9 결정 D-1~D-9 | 9 | 9 | |
| §10 문서 | 5 | 5 | |
| §12 V-1~V-9 | 9 | 9 | |
| **합계** | **97** | **102** | **Match Rate = 97 ÷ 102 = 95.1%** |

- ⚠️ 5건, ❌ 0건이다.
- ➕(설계 밖 구현)와 N/A(선택·보류)는 분모에서 뺐다.

## 3. 항목별 대조표

경로 약칭: `P` = `app/core/pipeline.py`, `A` = `api/index.py`, `S` = `app/core/storage.py`, `C` = `check_llm_fallback.py`, `H` = `public/admin.html`, `TF` = `test_llm_fallback.py`, `TA` = `test_llm_fallback_alert.py`

| # | 설계 조항 | 구현 위치 | 판정 | 근거 |
|---|---|---|:-:|---|
| 1 | §2.3 감시 스크립트에 새 의존 없음 | C:43-48 | ✅ | import는 표준 라이브러리와 `app.core.storage`뿐이다 |
| 2 | §3.1 `answer_text=""` | P:874 | ✅ | 항상 빈 문자열 |
| 3 | §3.1 최상위 키 {has_attachments, failed, llm, synthetic(조건부)} | P:866-872 | ✅ | 로컬 재현 행의 키 집합과 같다 |
| 4 | §3.1 `failed`는 True일 때만 기록 | P:868 | ✅ | False를 쓰는 경로 없음 |
| 5 | §3.1 category·calculation_types를 성공 경로와 같은 함수로, 없으면 `[]` | P:865, 875 | ✅ | `_category_for`, `calc_types or []` |
| 6 | §3.1 질문 원문 저장(U2) | P:874 | ✅ | `question_text=query`, 성공 경로와 같은 변수 |
| 7 | §3.1 의도적 부재 키(fallback·model·truncated·error 등) | P:817-824 | ✅ | T-F1이 fallback·model 부재를 단언 |
| 8 | §3.2 `AnswerOutcome.failures` | P:430 | ✅ | `field(default_factory=list)` |
| 9 | §3.2 ① chars==0 예외 → `_failure_entry` | P:672 | ✅ | |
| 10 | §3.2 ② 빈 응답 → `EmptyResponse` | P:680 | ✅ | T-F8 |
| 11 | §3.2 절단은 기록하지 않음 | P:665-669 | ✅ | `chars`면 append 전에 return |
| 12 | §3.2 `outcome.error`를 metadata에 싣지 않음 | P:684, 803-825 | ✅ | `_failure_llm_meta`가 읽지 않음 |
| 13 | §3.3 `_status_of` 순서·정수만·메시지 미독 | P:785-796 | ✅ | status_code → response.status_code → code. bool 제외는 ➕ |
| 14 | §3.4 stage=answer는 outcome 기반, 포장 예외 클래스 미사용 | P:811-814 | ✅ | `stage != "answer"`일 때만 exc 사용 |
| 15 | §3.4 failures가 비면 `NoProvider` | P:815-816 | ✅ | T-F4 m3 |
| 16 | §3.4 stage=pipeline은 attempts=[], failures 1건 | P:811-814 | ✅ | T-F4 |
| 17 | §3.4 error_class·status를 failures[-1]에서, status 없으면 키 생략 | P:818, 821-822 | ✅ | T-F4 m2 |
| 18 | §3.4 transport | P:823-824, 869 | ✅ | `getattr(config,"transport",None)` |
| 19 | §3.4 키 화이트리스트 9종 | P:780-782 | ✅ | `FAILURE_META_KEYS`, T-F1·F4가 부분집합 단언 |
| 20 | §4.1 시그니처 | P:851-855 | ✅ | 키워드 전용 인자까지 같다 |
| 21 | §4.1 supabase None → None | P:861-863 | ✅ | T-F3 |
| 22 | §4.1 전체 try/except, 로그는 클래스명만 | P:864-883 | ✅ | `type(e).__name__` |
| 23 | §4.1 `_category_for` 추출 시 동작 동일 | P:828-843, 4531 | ✅ | diff상 기존 블록과 같다 |
| 24 | §4.1 `_synthetic_flag` 추출 | P:846-848, 4573 | ✅ | 기존 `guard_ctx is None or guard_ctx.synthetic`과 같다 |
| 25 | §4.1 세션 스냅숏·첨부는 저장하지 않음 | P:851-883 | ✅ | 호출 없음 |
| 26 | §4.2 error → ping → 기록 → done | P:4397-4408 | ✅ | T-F1~F3 |
| 27 | §4.2 RuntimeError 하위 예외는 NoProvider로 수용 | P:4397, 815 | ✅ | 구조상 그렇다 |
| 28 | §4.3 SSE GET 기록 | A:342-346 | ✅ | `stage="pipeline", exc=e` |
| 29 | §4.3 SSE POST 기록 + has_attachments | A:414-418 | ✅ | `bool(parsed_attachments)` |
| 30 | §4.3 동기 `/api/chat`: try → 기록 → re-raise | A:303-313 | ✅ | 500을 유지한다 |
| 31 | §4.3 초기화 실패는 기록하지 않음 | A:330-335, 371-376 | ✅ | |
| 32 | §4.4 한 요청 최대 1건 | P:4397-4408, A 각 except | ✅ | 4.2 분기는 정상 종료하므로 API except에 들어가지 않는다 |
| 33 | §5.1 `RECENT_FAIL_WINDOW` 12h | C:51 | ✅ | U1 |
| 34 | §5.1 `SUMMARY_FAIL_WINDOW` 24h | C:52 | ✅ | |
| 35 | §5.1 `--fail-window` 기본 12 | C:400-404 | ✅ | B10 |
| 36 | §5.2 `degraded`에서 failed는 단독 사유 | C:100-101 | ✅ | B7 |
| 37 | §5.2 `judge(rows, window, now, fail_window)` | C:117-118 | ✅ | |
| 38 | §5.2 R1 유지(failed 포함) | C:134-135 | ✅ | |
| 39 | §5.2 R2: 실사용만, 창 안, 표본 수 무관, 합성 제외 | C:137-151 | ✅ | B1·B3·B4 |
| 40 | §5.2 `_ts`의 Z 처리, 해석 불가는 요약에 집계 | C:76-85, 142-144, 378-379 | ✅ | naive 문자열은 UTC로 본다(➕). B9 |
| 41 | §5.2 Verdict(recent_failed·last_real·failed_24h) | C:64-73, 156-157 | ✅ | unparsed·fail_window·now 필드는 ➕ |
| 42 | §5.3 종료 조건: (실사용 ≥ window AND oldest < now−W), 기록 끝, MAX_PAGES | C:177-182 | ✅ | B5·B5b. 시각 해석 불가 시 동작은 Gap L-2 |
| 43 | §5.3 id 중복 제거, MAX_PAGES 20 유지 | C:54, 127-132 | ✅ | |
| 44 | §5.4 제목(R1·R2 동시 참이면 두 줄) | C:362-369 | ⚠️ | 한 줄에 " · "로 결합 |
| 45 | §5.4 요약 줄(마지막 실사용, 경과, 24h 실패) | C:371-375 | ✅ | B6 |
| 46 | §5.4 실사용 0건 줄 "기록 없음(조회 N행)" | C:377 | ⚠️ | "조회 범위 안 실사용 0건" — 조회 행 수 N이 없다 |
| 47 | §5.4 표(provider —, attempts, `failed:Class`) | C:380-387 | ✅ | `id()`로 R1·R2 중복 표시를 막는다 |
| 48 | §5.4 힌트 4종 분기, 중복 제거, 상수 문자열 | C:331-357 | ✅ | failures가 비면 최상위 error_class·status로 폴백 |
| 49 | §5.4 R2 `::error::` | C:431-432 | ✅ | R1 줄과 따로 출력 |
| 50 | §5.4 question_text 미조회, select 불변 | C:173 | ✅ | `id,created_at,metadata` |
| 51 | §5.4 종료 코드 규약·법령 감시 불변 | C:419-437 | ✅ | |
| 52 | §6 통계 무변경 | A:618-660 | ✅ | diff에 없음 |
| 53 | §6 상세 표지(위치, escapeHtml, 안내 문구) | H:643-652, 674 | ✅ | error_class·status 모두 `escapeHtml` |
| 54 | §6 표지 형식(stage·status 괄호) | H:647-649 | ⚠️ | "답변 실패 · Class 429" — 괄호도 stage도 없다 |
| 55 | §6 목록 표지(선택, Low) | A:741-744 | N/A | 보류. PostgREST 별칭 투영 실측이 없다 |
| 56 | §6 HTML 주석에 내부 경로 금지 | H:142-143, 643-652 | ✅ | 주석 없음 |
| 57 | §7 예외 메시지를 저장하지 않음 | P:799-825 | ✅ | T-F1 "SECRET" 부재 |
| 58 | §7 토큰: 화이트리스트 | P:780-782 | ✅ | |
| 59 | §7 질문 원문·보존기간(U2) | S:326-336 | ✅ | 같은 컬럼, 같은 purge |
| 60 | §7 감시 로그: 상수 힌트만 | C:349-356 | ✅ | |
| 61 | §7 권한: 새 GRANT·DDL 없음 | diff stat | ✅ | `.sql` 0건 |
| 62 | §8.1 T-F1 | TF:1162-1190 | ✅ | 순서, 1건, 키, 원문 부재 |
| 63 | §8.1 T-F2 | TF:1193-1209 | ✅ | |
| 64 | §8.1 T-F3 | TF:1212-1219 | ✅ | |
| 65 | §8.1 T-F4 | TF:1222-1238 | ✅ | 세 모양 + 문자열 code |
| 66 | §8.1 T-F5 | TF:1241-1255 | ✅ | |
| 67 | §8.1 T-F6(성공 경로 저장 행과 동일) | TF:1258-1270 | ⚠️ | 성공 경로 행이 아니라 수식 재구현과 비교한다(L-6) |
| 68 | §8.1 T-F7('답변 생성 실패' except 블록) | TF:1273-1288 | ⚠️ | 함수 안 아무 except에서나 호출하면 통과한다(L-6) |
| 69 | §8.1 T-F8 | TF:1291-1299 | ✅ | |
| 70 | §8.2 B1 | TA:177-180 | ✅ | |
| 71 | §8.2 B2 | TA:182-187 | ✅ | failed_24h=1도 단언 |
| 72 | §8.2 B3 | TA:189-192 | ✅ | |
| 73 | §8.2 B4 (10-14 재구성) | TA:194-202 | ✅ | KST 환산이 맞다 |
| 74 | §8.2 B5 | TA:204-212 | ✅ | 59행, 실패 행은 2페이지 |
| 75 | §8.2 B6 | TA:220-234 | ✅ | 402 단언이 no-op이다(L-4) |
| 76 | §8.2 B7 | TA:236-238 | ✅ | |
| 77 | §8.2 B8 | TA:240-243 | ✅ | |
| 78 | §8.2 B9 | TA:245-250 | ✅ | |
| 79 | §8.2 B10 | TA:252-260 | ✅ | |
| 80 | (설계 없음) B5b: 창을 덮으면 더 읽지 않음 | TA:214-218 | ➕ | 과다 조회 방지 회귀 |
| 81 | §8.3 failed 포함, True만 | test_offline_units.py:580-586 | ✅ | |
| 82~90 | §9 D-1~D-9 | P:851(D-1), 811-814(D-2), C:100(D-3), C:150(D-4), `FAILURE_RECORD` grep 0건(D-5), P:851-883(D-6), C:177-182(D-7), P:4531(D-8), A 통계 무변경(D-9) | ✅×9 | |
| 91 | §10 CLAUDE.md 폴백 감시 절 | CLAUDE.md:946-947 | ✅ | 실패 행, R1·R2, 지킬 것 다섯 |
| 92 | §10 제외 키 수 | CLAUDE.md:1030, S:269 | ✅ | 6종. 설계의 "5종"은 오기(§5) |
| 93 | §10 docstring | C:14-21 | ✅ | |
| 94 | §10 워크플로 주석 | `.github/workflows/llm-fallback-alert.yml`:7-9 | ✅ | |
| 95 | §10 memory | `project-llm-fallback-alert.md`:3, 15 | ✅ | 인덱스 줄은 미갱신(L-8) |
| 96~104 | §12 V-1~V-9 | 위 각 행 + diff + Do 기록 | ✅×9 | V-6은 diff로 확인. V-7·V-8은 Do 기록 채택 |

**➕ 설계 밖 구현(점수 제외)**

| 항목 | 위치 |
|---|---|
| `_status_of`에서 bool 제외 | P:794 |
| Verdict의 `unparsed`·`fail_window`·`now` 필드 | C:71-73 |
| 저장 성공 INFO 로그 "실패 행 저장" | P:878 |
| 관리자 문구 "공개 게시판에는 실리지 않습니다" | H:651 |
| `_hours`·`_r1_alert` 헬퍼 | C:322-328 |
| B5b | TA:214 |

**계획 FR 대응(점수 제외)**

| FR | 결과 |
|---|---|
| FR-01~FR-08 | ✅ |
| FR-09 | ✅ (402는 미검증, L-4) |
| FR-10 | ✅ |
| FR-11 | N/A — D-5로 도입하지 않음 |
| 게시판 미노출(DoD) | `_apply_guard_filter` 키 순회(A:447)와 `_drop_flagged`(A:470), detail(A:1329)이 구조적으로 보장 |

## 4. Gap 목록 (심각도 순)

### Medium

**M-1 SSE 경로 기록 지연 상한이 보장되지 않는다(FR-03, §4.3)**
- **위치**
  - A:345-346, 416-418 — 기록 → `_sse_error_events`(error+done)
  - P:4401-4406 — ping 1회 → 기록
  - S:183-193, 326-336 — `ensure_session`(select + update/insert) + insert = PostgREST 3왕복
  - `app/config.py`:186 — `make_supabase_client()`가 타임아웃을 지정하지 않아 supabase-py 기본 120초(S:37)
- **현상**
  - 설계는 "INSERT 1회(≤ 수 초)"를 전제한다. 실제로는 직렬 3왕복이고 각 왕복이 최대 120초다.
  - Supabase가 느려지면 SSE 두 경로는 **error 이벤트가 나가기 전에** 대기한다. 프런트 idle(60초)이 먼저 끊으므로 사용자는 서버 안내 대신 타임아웃을 본다. maxDuration 300초를 넘기면 error와 done이 모두 유실된다.
  - 파이프라인 경로는 error가 먼저 나가지만, ping 1회는 60초만 덮는다.
- **권장**
  - SSE 두 경로에서 error 줄을 먼저 yield하고, 기록한 뒤 done을 yield한다(`gen = _sse_error_events(...); yield next(gen); record(...); yield from gen`). 설계 §4.3이 원래 의도한 "안내 먼저"와 맞다.
  - 또는 실패 기록에만 짧은 타임아웃 클라이언트를 쓴다(model_settings의 `postgrest_timeout=2` 선례).

**M-2 stage=pipeline 실패를 "전 제공자 실패"로 표기한다(§5.4·§6 설계 자체의 공백)**
- **위치**
  - C:363 — R2 제목
  - C:432 — `::error::`
  - H:651 — "모든 AI 제공자 호출이 실패해 답변이 생성되지 않았습니다"
  - A:339-346, 409-418 — `process_question` 안의 모든 예외와 SSE `json.dumps` 예외가 이 범위에 든다
- **현상**
  - stage=pipeline은 LLM 장애가 아니라 코드 예외일 수 있다.
  - 답변 스트리밍이 끝난 뒤(인용 검증·사례 대조·메타 조립)의 예외도 포함된다. 그때 사용자는 답변을 이미 받았는데, 행은 `answer_text=""`이고 "답변이 생성되지 않았습니다"로 표시된다.
  - 운영자가 메일 제목만 보고 토큰·크레딧을 의심하게 된다. 표의 `failed:KeyError`와 'other' 힌트가 일부 상쇄한다.
- **권장**
  - 제목, `::error::`, 관리자 문구를 `llm.stage`로 분기한다("전 제공자 실패" / "답변 처리 중 예외").
  - 선택: API 핸들러가 전달한 chunk 수를 세어 답변 송출 뒤 예외를 구분한다(화이트리스트 안에서 stage 값을 추가).

### Low

| ID | 위치 | 현상 | 권장 |
|---|---|---|---|
| L-1 | P:672 → 785-800 | `_failure_entry`가 **폴백 성공 경로의 except 블록 안**에서 보호 없이 실행된다. `getattr` 기본값은 AttributeError만 흡수하므로, property가 다른 예외를 던지면 다음 제공자로의 전환이 끊긴다. 현행 SDK 기준 확률은 낮다. 설계 1.1 "정상 경로 불변"과 긴장 관계다 | `_status_of` 본문을 `try/except Exception: return None`으로 감싼다 |
| L-2 | C:179-180, 172 | 마지막 행 `created_at`을 해석할 수 없으면 '창을 덮음'으로 간주한다(감시가 fail-open 쪽을 택한 것이고 설계에는 언급이 없다). MAX_PAGES를 소진해 창을 다 덮지 못해도 표시가 없다. 페이지가 PAGE_SIZE보다 짧을 때 종료하는 것은 정상이다. Python 3.12에서는 현실 확률이 낮다 | None은 '덮지 못함'으로 본다. 덮지 못했을 때 요약에 "R2 창 미확인" 줄을 추가한다 |
| L-3 | C:355, P:878 | 힌트 'other'가 `실패 행 저장` INFO 줄의 "오류 원문"을 보라고 안내한다. 그런데 루트 로깅 설정이 없어(`basicConfig` 0건) INFO가 출력되지 않을 가능성이 높고, 그 줄에는 클래스명만 있다 | 안내 대상을 `답변 생성 실패, 다음 제공자로 전환`(WARNING)과 `답변 생성 실패:`(ERROR) 줄로 바꾼다 |
| L-4 | TA:230, C:341 | B6의 402 단언은 픽스처에 402가 없어 항상 no-op이다. credit 분기를 지워도 테스트가 통과한다(FR-09 미검증) | 402 픽스처 → credit 문구, GatewayAuthError(상태 없음) → auth, NoProvider → other를 단언한다 |
| L-5 | C:365, 391-392, 434 | 최근 3건이 모두 failed면 R1도 참이 되어 "3건 연속 폴백", "폴백으로 생성됐습니다"가 출력된다. 실제로는 답변이 생성되지 않았다 | 표본이 전부 failed면 R1 문구를 "연속 저하"로 일반화하거나 생략한다 |
| L-6 | TF:1258-1270, 1273-1288 | T-F6은 성공 경로 행이 아니라 수식 재구현과 비교한다(공유 자체는 P:4531과 diff로 확인됨). T-F7은 호출을 초기화 except(A:333)로 옮겨도 통과한다 | T-F7을 `답변 생성 실패` 로그 Call을 가진 handler로 특정한다 |
| L-7 | C:366-369, 377 / H:647-649 | 출력 형식이 설계와 다르다: 제목 결합, 조회 행 수 N 없음, 괄호·stage 없음. 기능 영향은 없다 | 설계를 정정한다(§5). stage 표기는 M-2와 함께 처리한다 |
| L-8 | CLAUDE.md:946, C:1, C:23, `~/.claude/projects/-Users-zealnutkim-DEV-laborconsult/memory/MEMORY.md`(llm-fallback-alert 인덱스 줄) | 문서 불일치 넷: ① CLAUDE.md의 llm 키 열거에 `provider`가 없다(코드는 9종) ② docstring 첫 줄이 R1만 설명한다 ③ docstring은 "지킬 것 셋", CLAUDE.md는 "다섯" ④ 메모리 인덱스 줄이 아직 "사각: … ✅로 보임"이다(본문은 갱신됨) | 문구 동기화 |
| L-9 | C:400-404 | `--fail-window`에 0이나 음수를 주면 R2가 조용히 꺼진다 | 0보다 큰지 검증한다 |
| L-10 | C:181, C:135 및 327-328, test_offline_units.py:580 | 기존 결함인데 이번 변경으로 노출 범위가 넓어졌다: ① `sum(map(is_real, rows))`가 페이지 경계 중복을 센다(같은 결함을 `fetch_recent_law`는 PR #102에서 고쳤다) ② R1 판정이 두 곳에 중복돼 있다 ③ `counsel` 키를 단언하지 않는다 | 중복은 id 집합으로 센다. R1 결과는 Verdict에 보관한다 |

## 5. 설계 문서 정정 필요

1. **§6, §2.2**: 목록 표지와 `admin_conversations` 별칭 투영을 "보류"로 명시한다(PostgREST 별칭 투영 실측 없음).
2. **§8.2**: B5b(창을 덮으면 추가로 읽지 않음)를 추가한다. B5의 "60행"을 59행으로 고친다. §2.2 테스트 행의 "T-F1~F7·B1~B9"를 "T-F1~F8·B1~B10(+B5b)"로 고친다.
3. **제외 키 수**: §2.2 "4종→5종", §8.3 "5종", §10 "현재 4종 → 5종", V-4 "5종"을 모두 **6종**으로 고친다. `counsel`은 이미 있었다.
4. **§4.3 첫 항목**: "안내 먼저를 유지한다 … 헬퍼를 먼저 부른다"는 자기모순이다. 둘 중 하나를 확정한다. M-1을 반영한다면 "error → 기록 → done"이다. "INSERT 1회"는 "PostgREST 3왕복, 기본 타임아웃 120초"로 바로잡는다.
5. **§5.3**: 마지막 행 시각을 해석할 수 없을 때 어떻게 할지 명시한다(현 구현은 '덮음'으로 간주).
6. **§5.4**: 제목 형식(" · " 한 줄 결합)과 실사용 0건 문구를 구현에 맞춘다. M-2를 반영하면 stage별 제목도 추가한다.
7. **§6**: 표지 형식을 구현("답변 실패 · Class Status")에 맞추거나 stage 표기를 구현한다. 안내 문구를 stage별로 나눈다(M-2).
8. **§3.3, §5.2**: bool 제외와 Verdict 추가 필드를 반영한다.
9. **§7 "예외 메시지 — 어디에도 … 출력하지 않는다"**: 적용 범위를 신규 코드로 한정한다. 기존 WARNING·ERROR 로그(`답변 생성 실패…: %s`)는 원문을 출력하고, 힌트 'other'가 바로 그 줄을 보라고 안내한다.

## 6. 설계가 놓친 위험 (설계와 무관하게 변경이 닿는 경로를 훑은 결과)

**R-1 프로세스가 죽는 장애는 여전히 사각이다**
- 실패 행은 except 분기에 도달해야 남는다. 다음 경우는 행이 0건이고, R1과 R2가 모두 침묵한다.
  - 배포 손상(import 실패 → 모든 요청 500 — CLAUDE.md의 "untracked app/core → 500" 이력)
  - maxDuration 300초 초과로 인한 강제 종료
  - OOM
- 이때 요약의 '마지막 실사용 경과'만 늘어나며, 이것은 알림 사유가 아니다. 계획 (d)는 초기화 실패만 한계로 적었다.
- 권장: 비용 $0인 보완으로 워크플로에서 프로덕션 `GET /api/health`를 1회 호출하는 방안(LLM 미사용)을 후속 후보로 Report에 기록한다.

**R-2 "1건이면 알림"이 코드 결함까지 같은 채널로 올린다**
- 결정적 버그(특정 질문·첨부 모양)는 사용자가 재시도할 때마다 행을 쌓는다. 그러면 12시간 창 동안 cron마다 실패 메일이 나간다.
- M-2처럼 LLM 장애와 구분되지 않으면 알림 피로가 쌓여, 진짜 전면 장애 메일이 묻힐 수 있다.
- 권장: stage별 제목에 더해, §10 운영 절차에 stage=pipeline 대응(코드 수정·revert)을 추가한다.

**R-3 게이트 판정 전 예외는 원문을 남긴다**
- 의도분석 단계에서 예외가 나면 스코프 게이트가 판정하기 전이다. 그 질문은 block 모드에서 '저장 생략'이 원칙인 범주였을 수 있는데, 실패 행으로 저장된다.
- 게시판에는 `failed`로 제외되지만 관리자에게는 보인다. U2(정상 대화와 동일 저장)의 범위를 약간 넘는다.
- 권장: Report에 한계로 기록하고, 수용할지 결정을 남긴다.

## 7. 결론(Check 시점)

- **Match Rate 95.1% (97/102)로 90% 이상이다.** Act 반복(iterate)은 필요 없다.
- CLAUDE.md 규칙("90%를 넘어도 그대로 배포하지 말 것")에 따라, 머지 전에 같은 PR에서 고칠 것을 권한다(작은 수정).
  - **M-1**: SSE 경로를 error → 기록 → done 순서로.
  - **M-2**: stage별 문구.
  - **L-4**: 402·NoProvider 힌트 단언 추가.
  - **L-1**: `_status_of` try/except.
- L-2·L-3·L-5~L-10과 §5 정정은 Report 단계에서 문서 수정이나 후속 항목으로 처리한다.
- 다음 단계: 위 수정을 반영한 뒤 `/pdca report llm-fallback-alert-blindspot`. R-1(배포 손상 사각)은 Report의 후속 후보로 올린다.

## 8. Act 반영 (2026-11-02, 사용자 "M-1·M-2·L-1·L-4 Act 반영")

| ID | 조치 | 위치 | 회귀 |
|---|---|---|---|
| M-1 | SSE GET·POST 핸들러를 `gen = _sse_error_events(...); yield next(gen); 기록; yield from gen`으로 — `error` 먼저, `done`만 저장 시간만큼 지연. 동기 경로에 "답변 생성 실패(동기)" ERROR 로그 추가 | `api/index.py` 세 핸들러 | T-F7 강화(AST 문장 순서 `yield next` < 기록 < `yield from`, "답변 생성 실패" 로그를 가진 핸들러로 특정 — L-6 일부). 변이: GET 순서를 되돌리면 T-F7 실패 확인 |
| M-2 | 감시 제목·`::error::`를 stage별로(`_stage_counts`·`_failure_label`: "전 제공자 실패 n건 · 답변 처리 예외 m건"), `_hints`에 `pipeline` 힌트(코드 결함·traceback·수정/revert), 관리자 표지를 stage별 라벨·문구로 | `check_llm_fallback.py`, `public/admin.html` | B12 |
| L-1 | `_status_of` 본문을 `try/except Exception → None` | `app/core/pipeline.py` | T-F4에 속성 접근이 예외를 던지는 예외 추가 |
| L-4 | B6의 no-op 402 단언 제거(402 없으면 "크레딧" 부재 단언), B11 추가(402·GatewayAuthError·NoProvider·중복 1회·`failures` 빈 옛 모양 폴백) | `test_llm_fallback_alert.py` | B11 |
| 설계 정정 | §0·§2.2·§3.3·§4.3·§5.3·§5.4·§6·§7·§8·§10·V-4 — 분석 §5의 1~9번 전부 반영(v0.2) | 설계 문서 | — |

재검증: `test_llm_fallback.py` 통과(T-F1~F8), `test_llm_fallback_alert.py` 27건 OK, `test_abuse_guard.py`·`test_offline_units.py` 통과. **재계산 Match Rate**: ⚠️였던 #44(제목 형식)·#46(0건 문구)·#54(표지 stage)·#68(T-F7)이 설계 정정·구현으로 ✅, #67(T-F6 수식 비교)만 ⚠️ 잔존 → **101/102 = 99.0%**. 미반영 Low: L-2(해석 불가 시 '덮음' — 설계에 명시로 수용)·L-3·L-5·L-7(정정 완료)·L-8(아래)·L-9·L-10과 위험 R-1~R-3은 Report의 후속 항목.
