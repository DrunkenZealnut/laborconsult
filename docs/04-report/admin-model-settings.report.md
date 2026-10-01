# admin-model-settings 완료 보고서

> **Summary**: 관리자 화면에서 LLM별 최신 모델을 불러와 답변 모델·1순위를 설정 — 테스트 호출 통과 시에만 저장, 재배포 없이 60초 반영
>
> **Project**: laborconsult
> **Author**: Claude (with DrunkenZealnut)
> **Date**: 2026-09-30
> **Status**: Completed — §10-8 프로덕션 전환 확인 완료(2026-10-01)

---

## Executive Summary

### 1.1 Project Overview

| 항목 | 내용 |
|---|---|
| Feature | admin-model-settings |
| 기간 | 2026-09-29 ~ 2026-09-30 (Plan → Design → Do → Check → Act) |
| PR | #85 (머지 `e326891`, 프로덕션 `dpl_G4M4aJLF…`) |
| 선행 판단 | anthropic-sdk-v1 사이클 **중단** — SDK 업그레이드 불요, `<1.0` 상한 유지로 충분 |

### 1.2 Results Summary

| 지표 | 결과 |
|---|---|
| Match Rate | **95%** (62항목: 일치 55·의도적 변경 3·부분 3·누락 0·대기 1) |
| 변경 | 19파일 +1,926/−28 (PR #85, 커밋 2) |
| 테스트 | 오프라인 Python 24 · node 9(화면) · PostgreSQL 17 컨테이너 5 · 기존 스위트 전량 |
| 실 DB | `check_schema.py` 통과, 저장 200 / 낡은 revision 409 **0.3초** / 토큰 없음 422 / 복원 200 |
| 프로덕션 | 2026-10-01 06:23:49 UTC 관리자 화면에서 `claude-opus-5-5` 저장(rev 6) → 재배포 없이 06:25:08 답변이 `llm_outcome provider=Claude model=claude-opus-5-5 attempts=['Claude']` |

### 1.3 Value Delivered

| Perspective | Content |
|---|---|
| **Problem** | 답변 모델이 코드 상수·환경변수에 흩어져, 9-28 출시된 `claude-sonnet-5-5`를 적용하려면 코드 수정·재배포가 필요했다. 잘못 바꾸면 폴백이 조용히 삼키는 사고가 두 번 있었다(`gemini-2.5-pro` 404, SDK 1.x). |
| **Solution** | 관리자 "답변 모델" 메뉴 — 벤더별 **최신 3개**를 불러와, 답변 경로의 스트리밍 함수 그대로 테스트 호출해 통과한 모델만 서버 서명 토큰으로 저장. 파이프라인은 60초 캐시·2초 타임아웃·fail-open으로 읽는다. |
| **Function/UX Effect** | 모델 교체·1순위 전환이 **클릭 몇 번, 최대 60초**(기존: Vercel env + 재배포). 실측으로 `gemini-2.5-pro`(목록엔 있으나 404)가 저장 단계에서 거절됨. 대화 metadata·로그에 실제 답변 모델이 남는다. |
| **Core Value** | 모델 교체를 배포 작업에서 운영 설정으로 바꾸면서, "호출 가능한 모델만 저장"으로 조용한 폴백 사고의 재발을 구조적으로 막았다. |

---

## 2. Related Documents

- Plan: `docs/01-plan/features/admin-model-settings.plan.md`
- Design: `docs/02-design/features/admin-model-settings.design.md`
- Analysis: `docs/03-analysis/admin-model-settings.analysis.md`
- 중단 사이클(참고): `docs/01-plan/features/anthropic-sdk-v1.plan.md`, `docs/02-design/features/anthropic-sdk-v1.design.md` (미커밋)

---

## 3. Completed Items

### 3.1 Functional Requirements

| ID | 요구사항 | 결과 |
|---|---|---|
| FR-01 | 벤더별 모델 목록(최신순, 부적합 제외) | ✅ 최신 3개 + 현재값, Gemini는 `-latest` 별칭 추가 |
| FR-02 | 테스트 호출 통과 시에만 저장 | ✅ HMAC 토큰(15분), 서버 강제 |
| FR-03 | 재배포 없이 60초 반영 | ✅ 60초 TTL 캐시 + 저장 인스턴스 즉시 무효화 |
| FR-04 | 1순위 변경 | ✅ 저장값 > `ANSWER_PROVIDER` > 기본 순서 |
| FR-05 | 저장소 장애 시 기본값(fail-open) | ✅ 실패도 캐시, 읽기 2초 타임아웃 |
| FR-06 | 변경 이력 | ✅ `answer_model_setting_events`(before/after/actor) |
| FR-07 | 기본값으로 되돌리기 | ✅ reset |
| FR-08 | metadata에 실제 모델 | ✅ `metadata.llm.model`, `llm_outcome model=` |
| FR-09 | 목록에 없는 ID 저장 불가 | ✅ 벤더 원본 목록 대조(422) |

### 3.2 Non-Functional Requirements

| 항목 | 결과 |
|---|---|
| 성능 | 캐시 적중 시 0, 미스 시 1왕복(2초 상한) |
| 보안 | 관리자 JWT + service-role 전용, anon 차단(`check_schema.py` LOCKED_TABLES) |
| 무회귀 | `test_llm_fallback.py` **무수정 통과** — 기본값 경로 동작 동일 |

### 3.3 Deliverables

`supabase_model_settings.sql`, `app/core/model_settings.py`, `api/model_settings.py`, `public/admin_model_settings.js`, `pipeline.py`(모델 주입), `storage.py`(`postgrest_timeout`), `check_schema.py`, 테스트 3종, CI 단계, CLAUDE.md "Answer Model Settings" 절.

---

## 4. Incomplete Items

### 4.1 Carried Over

| 항목 | 사유 | 조치 |
|---|---|---|
| `legal_rules_save`의 `40001` | 이 사이클에서 발견한 **기존 결함**(범위 밖) | CLAUDE.md·메모리에 기록, 별도 처리 |

### 4.2 Cancelled

- anthropic-sdk-v1 — "API만 쓰는데 왜 SDK를 올리나"라는 지적이 맞았다. 장애 원인은 업그레이드 부재가 아니라 **버전 미고정**이었다.

---

## 5. Quality Metrics

### 5.1 Final Analysis

Match Rate 95%, High 갭 0. 설계 외 발견 R-1·R-2(Medium)와 R-5·R-6(Low)은 PR에서 반영.

### 5.2 Resolved Issues

| 발견 경로 | 이슈 | 해결 |
|---|---|---|
| Do 실측 | CAS 충돌 `40001` → PostgREST 재시도로 30~40초 타임아웃 | `PT409`(즉시 409) |
| 오프라인 테스트 | `models=[]`가 `or {}`로 통과 | `None`만 빈 dict로 |
| SQL 테스트 | 클래스 이름 import로 법률 기준 테스트 중복 수집 | 모듈 참조 |
| gap R-1 | 잠금 밖 조회가 무효화 뒤 옛 값을 60초 되살림 | 캐시 세대 번호 |
| gap R-2 | RPC 일반 예외 500 | 503 + reset 사전 확인 |
| gap R-5 | 빈 1순위 라벨·키 없는 Gemini·잘못된 env 표시 | 실제 값 라벨·비활성·검증 |
| gap R-6 | 저장 형식 손상 시 GET 500 | dict 방어 |
| CodeRabbit | 늦은 테스트 응답이 선택을 되돌려 옛 모델 저장 | `applyTestResult` — 요청 모델 = 현재 선택일 때만 반영 |
| CodeRabbit | `check_schema.py` 안내에 7번째 DDL 누락 | 추가 |

---

## 6. Lessons Learned

### 6.1 Keep

- **실측 먼저.** 모델 목록 API를 설계 전에 호출해 본 덕에 OpenAI 132개 잡음, Gemini 날짜 필드 부재, `gemini-2.5-pro`의 "목록 ≠ 호출 가능"이 설계에 들어갔다. 최신 3개 규칙도 실측 목록에 적용해 보고서야 "pro 계열 전부 누락"을 잡았다.
- **테스트 호출 = 프로덕션 함수 그대로.** 별도 테스트 코드였다면 SDK 1.x 같은 인자 불일치를 통과시켰을 것이다.
- **시그니처 보존.** `_answer_providers(config)`를 늘리지 않고 `partial`로 묶어 기존 폴백 테스트가 무수정 통과했다.

### 6.2 Problem

- **docker PostgreSQL 테스트는 PostgREST 동작을 못 본다.** `40001` 재시도 정지는 실 DB 왕복에서만 드러났다. 컨테이너 5/5 통과가 안전 신호가 아니었다.
- **gap 95%여도 설계 밖 결함이 남았다**(R-1 경합, CodeRabbit의 늦은 응답 경합). CLAUDE.md의 "Match Rate만으로 배포하지 말 것" 규칙이 이번에도 맞았다 — 두 경합 모두 **비동기 순서** 문제였고 설계서는 순서를 다루지 않았다.

### 6.3 Try

- 관리자 UI에서 "테스트 통과"를 "저장 완료"로 오인한 1회(10-01, 테스트 200 후 PUT 없음)가 있었다 — 통과 직후 "저장을 눌러야 반영됩니다" 안내를 검토.

- 새 Supabase RPC는 실 DB로 **충돌 경로까지** 한 번 왕복한다(정상 경로만으로는 부족).
- 비동기 UI 상태는 "요청 시점 식별자 = 현재 식별자"를 기본 패턴으로.

---

## 7. Process Improvement

- 서브에이전트(gap-detector)에 Write 권한이 없어 보고서를 부모가 저장했다 — 분석 에이전트 호출 시 산출물 저장 주체를 명시할 것.
- 운영 신호: 프로덕션 확인 중 **Anthropic 사용 한도**를 발견했다. 폴백이 흡수해 답변은 정상으로 보였다 — `llm_outcome attempts`의 폴백 비율 알림이 없으면 한도 도달도 조용하다.

---

## 8. Next Steps

### 8.1 Immediate

1. ~~프로덕션 전환 확인~~ — 완료(10-01, `claude-opus-5-5`). 9-30 Anthropic 사용 한도 도달로 하루 지연됐다
2. `ADMIN_JWT_SECRET` 설정 — 현재 6자 `ADMIN_PASSWORD`가 JWT·테스트 토큰 서명키(프로덕션 로그 `InsecureKeyLengthWarning`)
3. `claude-opus-5-5` 비용 관찰 — 원 계획은 sonnet-5-5

### 8.2 Next Cycle 후보

- `legal_rules_save` `40001` → `PT409`
- 폴백 비율 모니터링(연속 폴백 시 관리자 알림) — 한도 도달·모델 폐기를 조용히 넘기지 않도록
- 보조 모델(Haiku 4곳 날짜 고정 ID) 설정 단일화
- 구 Pinecone 인덱스 우리 NS 3개 정리(≈10-11)

---

## 9. Changelog

### v1.0.0 (2026-09-30)

- 관리자 "답변 모델" 메뉴, 설정 저장소(DDL 7번째), 답변 경로 모델 주입, metadata 모델 기록
