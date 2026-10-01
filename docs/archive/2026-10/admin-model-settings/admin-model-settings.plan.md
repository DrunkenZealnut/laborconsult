# admin-model-settings Planning Document

> **Summary**: 관리자 화면에서 LLM별(Claude·OpenAI·Gemini) 최신 모델 목록을 불러와 답변 모델과 1순위 제공자를 고르고, 테스트 호출 통과 시에만 저장해 재배포 없이 1분 안에 반영한다.
>
> **Project**: laborconsult
> **Author**: Claude (with DrunkenZealnut)
> **Date**: 2026-09-29
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 답변 모델이 코드 상수(`CLAUDE_MODEL`)·환경변수(`OPENAI_CHAT_MODEL`·`GEMINI_MODEL`·`ANSWER_PROVIDER`)에 흩어져 있어 새 모델이 나와도 바꾸려면 코드 수정·재배포가 필요하다. 실측: 어제(9-28) `claude-sonnet-5-5`가 출시됐지만 답변은 `claude-sonnet-5`로 고정돼 있다. 잘못 바꾸면 404 → 폴백이 조용히 삼키는 사고가 이미 두 번 있었다(`gemini-2.5-pro`, anthropic SDK 1.x). |
| **Solution** | 관리자 "답변 모델" 메뉴에서 벤더별 모델 목록 API를 조회해 후보를 보여주고, 선택한 모델로 **프로덕션과 같은 호출 경로의 테스트 호출**이 성공해야만 Supabase에 저장한다. 파이프라인은 설정을 60초 캐시로 읽고, 읽기 실패 시 코드 기본값으로 동작한다. |
| **Function/UX Effect** | 새 모델을 재배포 없이 몇 번의 클릭으로 적용하고, 장애 시 1순위를 즉시 다른 벤더로 돌린다(현재는 Vercel env 변경 + 재배포). 호출 불가능한 모델은 저장 단계에서 거절된다. |
| **Core Value** | 모델 교체를 "배포 작업"에서 "운영 설정"으로 바꾸되, 검증 게이트로 조용한 폴백 사고의 재발을 막는다. |

---

## 1. Overview

### 1.1 Purpose

답변 생성 모델과 제공자 우선순위를 운영자가 안전하게 바꿀 수 있게 한다.

### 1.2 Background — 실측 (2026-09-29)

| 벤더 | 목록 API | 결과 | 특징 |
|---|---|---|---|
| Anthropic | `client.models.list()` (SDK 0.120 지원) | 13개, 0.6초 | 최신순, `display_name` 제공. 최신 `claude-sonnet-5-5`(9-28) |
| OpenAI | `client.models.list()` | **132개**, 1.8초 | 임베딩·TTS·전사·이미지·검색·codex 혼재 → **필터 필수** |
| Gemini | `genai.list_models()` + `generateContent` 지원 필터 | 44개, 0.5초 | TTS·이미지 preview 혼재. **`gemini-2.5-pro`가 목록에 있지만 8월에 404였다** → 목록 ≠ 호출 가능 |

현재 답변 모델 설정 지점:

| 항목 | 위치 | 변경 방법 |
|---|---|---|
| Claude 답변 | `config.CLAUDE_MODEL = "claude-sonnet-5"` 상수 | 코드 수정 + 배포 |
| OpenAI 답변 | `OPENAI_CHAT_MODEL` env (기본 `o3`) | Vercel env + 재배포 |
| Gemini 답변 | `GEMINI_MODEL` env (기본 `gemini-pro-latest`) | Vercel env + 재배포 |
| 1순위 | `ANSWER_PROVIDER` env | Vercel env + 재배포 |

`CLAUDE_MODEL`이 env가 아닌 상수인 이유(config.py 주석): 셸 프로필의 낡은 `CLAUDE_MODEL`이 존재하지 않는 모델로 덮어 404가 났기 때문. 이 기능은 그 문제를 "검증된 값만 저장"으로 푼다.

### 1.3 Related Documents

- `docs/02-design/features/llm-fallback-hardening.design.md` — 폴백 순서·타임아웃 예산
- CLAUDE.md "LLM provider fallback 규약", Legal Rule Registry(service-role 저장소 패턴)

---

## 2. Scope

### 2.1 In Scope

- [ ] 관리자 "답변 모델" 메뉴: 벤더별 현재 모델·출처(설정/기본값) 표시, 모델 목록 불러오기(**벤더별 최신 3개** + 현재값), 선택, 테스트 호출, 저장
- [ ] 1순위 제공자 선택(Claude/OpenAI/Gemini)
- [ ] 벤더별 모델 목록 조회 API + 답변용 후보 필터(OpenAI·Gemini 잡음 제거)
- [ ] 테스트 호출 API — **프로덕션 스트리밍 함수 그대로** 짧은 프롬프트로 호출, 비어 있지 않은 텍스트가 오면 통과
- [ ] 설정 저장소: `laborconsult` 스키마 신규 테이블, service-role 전용, 변경 이력
- [ ] 파이프라인이 설정을 60초 캐시로 읽음, 실패 시 코드 기본값(fail-open)
- [ ] 되돌리기: "기본값으로" 버튼(설정 삭제 → 코드 기본값)
- [ ] `qa_conversations.metadata.llm`에 실제 사용 모델 기록(현재는 provider만)

### 2.2 Out of Scope

- 의도분석(Sonnet)·보조 작업(Haiku: 쿼리 분해·Self-RAG·인용 교정)·의도분석 폴백(gpt-4.1) 모델 — 코드 값 유지(사용자 결정)
- 모델별 파라미터(max_tokens·temperature) 편집
- A/B 비율 분배
- `google.generativeai` → `google.genai` 이전(실측 중 지원 종료 경고 확인 — 별도 과제)
- 임베딩 모델 — 바꾸면 전 코퍼스 재임베딩이 필요해 운영 설정이 될 수 없다

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-01 | 관리자는 벤더별 모델 목록을 조회할 수 있다(최신순, 답변 부적합 모델 제외) | High |
| FR-02 | 모델 선택 후 테스트 호출이 성공해야만 저장된다. 실패 시 벤더 오류 요약을 보여주고 저장하지 않는다 | High |
| FR-03 | 저장된 설정은 재배포 없이 최대 60초 안에 모든 인스턴스의 답변에 반영된다 | High |
| FR-04 | 1순위 제공자를 화면에서 바꿀 수 있고, 나머지는 기본 순서(Claude→OpenAI→Gemini)를 유지한다 | High |
| FR-05 | 설정 저장소 장애 시 답변은 코드 기본값으로 정상 동작한다(fail-open) | High |
| FR-06 | 모든 변경은 이력(누가·언제·무엇을 무엇으로)으로 남는다 | Medium |
| FR-07 | "기본값으로" 되돌리기 | Medium |
| FR-08 | 대화 metadata에 실제 답변 모델명 기록 | Medium |
| FR-09 | 목록에 없는 모델 ID는 저장할 수 없다(직접 입력 불가 — 오타·낡은 이름 차단) | Medium |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement |
|----------|----------|-------------|
| 성능 | 설정 읽기가 답변 지연에 더하는 시간 캐시 적중 시 0, 미스 시 1왕복(≤300ms) | 로그 |
| 보안 | 설정 쓰기는 관리자 JWT + service-role 서버 경로만. anon 접근 차단 | `check_schema.py` LOCKED_TABLES |
| 비용 | 테스트 호출은 짧은 프롬프트 1회(수십 토큰) | — |
| 관측 | 저장 시 로그, 답변 시 `llm_outcome`에 모델명 | Vercel 로그 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] 관리자 화면에서 Claude 답변 모델을 `claude-sonnet-5-5`로 바꾸고, 재배포 없이 60초 안에 프로덕션 답변 로그에 반영됨을 확인
- [ ] 존재하지 않거나 호출 불가한 모델(예: `gemini-2.5-pro`)이 테스트 단계에서 거절됨
- [ ] Supabase 설정 테이블을 비우거나 읽기 실패를 주입하면 코드 기본값으로 답변
- [ ] 오프라인 테스트: 캐시·fail-open·필터·저장 거절 경로
- [ ] `check_schema.py` 통과, DDL 적용 순서 문서 갱신

### 4.2 Quality Criteria

- 기존 오프라인 테스트 전량 통과(특히 `test_llm_fallback.py`의 폴백 순서·하트비트)
- 기본값 경로(설정 없음)에서 현재와 바이트 동일한 동작

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| 테스트 호출은 통과했지만 실제 긴 답변에서 실패(토큰 한도·reasoning 빈 응답) | High | Medium | 테스트를 **프로덕션 스트리밍 함수 그대로** 호출(같은 인자·타임아웃). 기존 빈 응답=실패 규약이 폴백을 보장. 저장 후 대화 metadata의 모델·폴백 기록으로 관찰 |
| 캐시 60초 동안 인스턴스 간 설정 불일치 | Low | High | 허용(최대 60초). 화면에 "최대 1분 후 반영" 표시 |
| 설정 저장소 장애가 답변 경로를 막음 | High | Low | 읽기 예외는 전부 기본값으로 흡수 + 짧은 타임아웃. 가드와 같은 fail-open 원칙 |
| 공유 Supabase에서 이름 충돌·권한 누락 | High | Medium | CLAUDE.md 공유 스키마 규칙: `laborconsult` 스키마, 명시 GRANT, `pg_policies` 선확인, 고유 이름(`answer_model_settings`) |
| Claude 모델을 바꾸면 `ANSWER_MAX_TOKENS`·`temperature` 미지정 규약과 충돌하는 모델 | Medium | Low | 테스트 호출이 같은 인자로 부르므로 거부 모델은 저장 단계에서 걸린다 |
| OpenAI 필터가 새 명명 규칙(예: 신규 접두사)을 놓침 | Low | Medium | 필터는 "제외 목록" 방식(embedding·tts·transcribe·image·audio·realtime·search·moderation·codex)으로 두어 새 채팅 모델은 기본 노출 |

---

## 6. Architecture Considerations

### 6.1 Project Level Selection

Dynamic (기존 유지)

### 6.2 Key Architectural Decisions

| Decision | Selected | Rationale |
|----------|----------|-----------|
| 저장소 | Supabase `laborconsult.answer_model_settings`(단일 행 JSON + 이력 테이블), service-role 전용 | Legal Rule Registry와 같은 패턴. anon 차단 |
| 반영 | 모듈 전역 60초 TTL 캐시 | Vercel Fluid Compute 인스턴스 재사용. registry는 캐시 금지 규칙이 있지만(쓰기 직전 읽기 신선도) 이 설정은 1분 지연 허용이 명시 요구 |
| 우선순위 | 저장값 > env(`OPENAI_CHAT_MODEL`·`GEMINI_MODEL`·`ANSWER_PROVIDER`) > 코드 상수 | env를 비상 수단으로 남기되 화면 설정이 이긴다. 화면에 현재 값의 **출처**를 표시해 혼동 방지 |
| 테스트 호출 | 프로덕션 `_stream_*` 함수에 모델을 주입해 호출 | 별도 테스트 코드를 두면 실제 호출 방식과 어긋난다(SDK 1.x 사고의 교훈) |
| 목록 조회 | 서버가 벤더 API 직접 호출(키는 서버에만) | API 키 브라우저 노출 금지 |

### 6.3 변경 파일 (예상)

```
supabase_model_settings.sql      신규 DDL (테이블·RLS·GRANT·저장 RPC)
app/core/model_settings.py       신규 — 저장소·캐시·해석(저장값>env>상수)·목록 필터
app/core/pipeline.py             _stream_* 가 해석된 모델 사용, provider 순서, metadata 모델명
api/model_settings.py            신규 라우터 — 목록·테스트·저장·기본값·이력
api/index.py                     라우터 등록
public/admin.html + admin_model_settings.js  "답변 모델" 메뉴
check_schema.py / test_offline_units.py::_DDL_FILES  DDL 등록
test_model_settings.py           신규 오프라인 테스트
CLAUDE.md                        DDL 순서·운영 규칙
```

---

## 7. Convention Prerequisites

### 7.1 Existing Project Conventions

- [x] Supabase 객체는 `laborconsult` 스키마, `make_supabase_client()` 경유, SECURITY DEFINER `search_path`에 `public` 금지
- [x] 커스텀 스키마 GRANT 명시(테이블·함수 둘 다)
- [x] 프론트 `fetch`는 `resp.ok` 검사(`test_public_fetch.js`가 `public/*.js` 자동 발견)
- [x] 관리자 정적 JS는 `/admin` 접두사 파일명(서비스워커 캐시 제외 조건)
- [x] 모든 신규 기능은 폴백 경로 필수

### 7.2 Conventions to Define

| Category | Rule |
|----------|------|
| 모델 출처 표시 | 화면·로그에 `settings`/`env`/`default` 중 어디서 왔는지 항상 표기 |
| 저장 게이트 | 테스트 호출 통과 토큰(짧은 유효기간) 없이는 저장 API가 거절 — 화면 우회 방지 |

### 7.3 Environment Variables Needed

없음(기존 `SUPABASE_SERVICE_ROLE_KEY`·벤더 API 키 재사용)

---

## 8. Next Steps

1. [ ] `/pdca design admin-model-settings`
2. [ ] DDL 적용(SQL Editor) → `check_schema.py`
3. [ ] 구현 → gap 분석 → 프로덕션에서 `claude-sonnet-5-5` 전환 검증
