# admin-model-settings 갭 분석 보고서

- 설계: `admin-model-settings.design.md` (Plan: `admin-model-settings.plan.md`)
- 구현: `feat/admin-model-settings` 브랜치(미커밋)
- 분석일: 2026-09-30 · 분석: gap-detector

## 종합 점수 — Match Rate 95%

| 구분 | 항목 | 일치 | 의도적 변경 | 부분 일치 | 누락 | 대기 |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| §2 아키텍처·의존 | 5 | 4 | 1 | 0 | 0 | 0 |
| §3 데이터 모델·DDL | 10 | 10 | 0 | 0 | 0 | 0 |
| §4 모듈(resolve·캐시·목록·토큰) | 16 | 15 | 0 | 1 | 0 | 0 |
| §5 pipeline | 7 | 7 | 0 | 0 | 0 | 0 |
| §6 API·오류코드 | 11 | 8 | 2 | 1 | 0 | 0 |
| §7 UI | 6 | 5 | 0 | 1 | 0 | 0 |
| §9 테스트 M-1~M-9 + 기존 회귀 | 5 | 5 | 0 | 0 | 0 | 0 |
| §10 구현 순서 1~8 | 2 | 1 | 0 | 0 | 0 | 1 |
| **합계** | **62** | **55** | **3** | **3** | **0** | **1** |

계산: (일치 55 + 의도적 변경 3 + 부분 일치 3×0.5) / 대기를 뺀 61 = 97.5%. 설계 밖 위험을 감안해 **95%**로 보고한다.

Do 단계에서 설계서를 갱신한 두 변경(충돌 오류코드 40001 → `PT409`, 모델 목록 최신 3개 + 현재값 + Gemini 별칭)은 설계 §3.2·§4.3·§6.2와 CLAUDE.md에 반영돼 있어 갭으로 세지 않았다.

## 의도적 변경 (구현이 더 합리적)

| 설계 | 구현 |
|---|---|
| `build_model_router(require_admin, config_factory)` | `(require_admin, config_factory, secret, stream_fns)` — 스트리밍 함수 주입으로 순환 import 회피 |
| 저장 `actor="admin"` | `"admin-session:<jti>"` — 세션 추적 가능 |
| test 오류코드 표 | 목록 조회 실패 시 502 추가 |

## 갭 목록 (전부 Low)

| ID | 위치 | 설계 | 구현 |
|---|---|---|---|
| G-1 | `api/model_settings.py:67,112-118` | 관리자별 10회/분, `_check_rate_limit` 재사용 | 라우터 전역 deque(관리자 구분 없음). 목록 조회 실패도 1회로 셈. 관리자 계정이 하나라 영향 없음 |
| G-2 | `api/model_settings.py:120-126` | 소속 확인에 필터된 `list_models(p)` | 필터 전 원본 목록과 대조 — 최신 3개 밖 모델도 테스트 가능. 문서화 필요 |
| G-3 | `public/admin_model_settings.js:88` | 변경 모델이 전부 테스트 통과해야 저장 활성 | 변경만 있으면 활성, 토큰 누락은 클릭 시 오류로 차단 |
| G-4 | `app/core/model_settings.py:282` | `tested_at` = 테스트 시각 | 저장 시각(최대 15분 차이) |
| G-5 | `api/model_settings.py:134-148` | Gemini 키 없으면 save 400 | 모델 변경은 토큰 불가로 422, `primary="gemini"`는 키 없이도 저장됨(R-5) |

## 설계 외 발견

| ID | 심각도 | 위치 | 내용 |
|---|:-:|---|---|
| R-1 | Medium | `model_settings.py:103-113` | **캐시가 낡은 값으로 되돌아갈 수 있음.** `_fetch()`가 잠금 밖이라 저장 직전 시작된 조회가 `invalidate()` 뒤에 끝나면 옛 설정을 60초 캐시한다. 저장한 인스턴스의 즉시 반영이 깨짐. 대안: 세대 카운터 |
| R-2 | Medium | `api/model_settings.py:141,153`, `model_settings.py:297-303` | **RPC의 충돌 외 예외(DB 장애·타임아웃)가 500.** reset에는 `store_available` 사전 확인도 없음. 설계 §6의 503 규약과 어긋남 |
| R-3 | Low | `model_settings.py:253-287` | PUT에서 빠진 제공자는 저장값이 조용히 지워짐. 화면은 항상 함께 보내 문제없으나 API 계약 미문서화 |
| R-4 | Low | `model_settings.py:283` | 클라이언트 `latency_ms`를 검증 없이 저장 |
| R-5 | Low | `js:82`, `pipeline.py:490-492` | 빈 1순위 라벨이 "기본 순서(Claude)" 고정 — env `ANSWER_PROVIDER`가 있으면 화면과 실제가 다름. Gemini 키 없이 Gemini 1순위 저장 가능(무효과). 잘못된 env 값이 검증 없이 표시 |
| R-6 | Low | `api/model_settings.py:81` | 저장된 `models`가 dict가 아니면 GET state 500 |
| R-7 | Low | `test_admin_model_settings.js:56-63` | `mount()`의 409 자동 재조회 흐름은 테스트 없음 |
| R-8 | 정보 | `api/model_settings.py:106-132` | 테스트 호출이 답변과 같은 토큰 한도·타임아웃 — 느린 모델이면 수십 초. 관리자 경로라 수용 |
| R-9 | 정보 | `model_settings.py:229-248` | 토큰 서명키 `JWT_SECRET` 공유, 메시지 형식이 달라 교차 위조 없음 |

## 권장 조치

1. 배포 전: R-1(세대 카운터), R-2(일반 예외 503 + reset 사전 확인)
2. 설계 문서 갱신: G-1·G-2·G-4, 라우터 시그니처, actor 형식
3. 선택: R-5(라벨·Gemini 비활성), R-6(dict 방어)
4. §10-8: 배포 후 프로덕션 `llm_outcome model=claude-sonnet-5-5` 확인
