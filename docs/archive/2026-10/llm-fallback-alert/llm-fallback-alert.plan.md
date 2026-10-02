# llm-fallback-alert Planning Document

> **Summary**: 프로덕션 실사용 답변이 최근 3건 연속 폴백이면 GitHub Actions를 실패시켜 메일로 알린다(6시간 주기).
>
> **Project**: laborconsult · **Date**: 2026-10-02 · **Status**: Implemented (PR #89, 2026-10-02)

## Executive Summary

| Perspective | Content |
|---|---|
| **Problem** | 폴백이 장애를 흡수해 답변은 정상으로 보인다. 실측(2026-10-02): **8-21 ~ 9-28, 38일간 프로덕션 실사용 답변 17/17이 폴백**이었다(anthropic SDK 1.x 자동 설치) — 같은 기간 로컬·벤치마크(SDK 0.120)는 전부 Claude 성공이라 아무도 몰랐다. 9-30에는 Anthropic 사용 한도 도달도 같은 방식으로 숨었다. |
| **Solution** | `qa_conversations.metadata.llm`에 이미 쌓이는 폴백 기록을 6시간마다 읽어, 합성 대화를 뺀 **최근 3건이 모두 저하(폴백·빈 응답·의도분석 폴백)**면 워크플로를 실패시킨다. GitHub가 실패 메일을 자동 발송한다. |
| **Function/UX Effect** | 8월 사고 기준 **8-22에 감지**(실제 발견 9-28, 37일 단축). 새 인프라·비밀번호·발송 코드 없음. |
| **Core Value** | "폴백이 장애를 삼킨다"는 이 코드베이스의 반복 패턴(모델 폐기 404·reasoning 빈 응답·SDK 1.x·사용 한도)에 상시 감시를 붙인다. |

## 1. 실측 근거 (60일, `metadata.llm`)

| 기간 | 구분 | 결과 |
|---|---|---|
| 8-13 ~ 9-16 | 합성(로컬·벤치) | Claude 성공 대부분 |
| 8-21 ~ 9-28 | **실사용** | **폴백 17/17** |
| 9-28 이후 | 실사용 | 정상(9-30 1건 = 사용 한도) |

트래픽: 실사용 **하루 0~5건** → 비율 임계는 1건으로 100%가 되어 오탐. **연속 N건**이 적합.

## 2. Scope

**In**: 판정 스크립트(`check_llm_fallback.py`, 오프라인 테스트 가능한 순수 판정 함수), 워크플로(`llm-fallback-alert.yml`, cron 6시간 + 수동 실행), Job Summary에 최근 건 표, CLAUDE.md 운영 규칙.
**Out**: 메일·슬랙 발송 코드, 관리자 화면 배너, 비율 기반 판정, 알림 중복 억제(장애 지속 중 6시간마다 메일 — 수용).

## 3. Requirements

| ID | 요구 |
|---|---|
| FR-01 | 합성(`metadata.synthetic`)·`llm` 메타 없는 행 제외, 최근 실사용 3건 기준 |
| FR-02 | 저하 = `llm.fallback` 또는 `llm.empty` 또는 `llm.intent_provider` 존재 |
| FR-03 | 3건 모두 저하 → exit 1(알림), 아니면 exit 0. 표본 3건 미만이면 판정 불가 → exit 0 + 요약에 표시 |
| FR-04 | 조회 실패(키 없음·DB 장애)는 **exit 2로 실패** — 감시가 죽은 것도 알려야 한다(감시의 fail-open 금지) |
| FR-05 | 요약에 최근 건의 시각·provider·model·attempts 표 |

## 4. Risks

| Risk | 대응 |
|---|---|
| 의도적 1순위 변경(관리자 화면 OpenAI 1순위)을 폴백으로 오인 | 판정은 `fallback`(=시도 2개 이상)이지 "Claude가 아님"이 아니다 — 1순위가 바로 성공하면 저하 아님 |
| 트래픽 0인 기간 | 판정 불가로 통과. 표본 부족 자체는 장애 신호가 아님 |
| Secret 미등록 | FR-04로 실패 → 첫 실행에서 드러남 |

## 5. 사전 조치 (사용자)

GitHub repository Secrets: `SUPABASE_URL`, `SUPABASE_KEY`(anon — `qa_conversations` SELECT 정책, service-role에는 이 테이블 권한이 없다는 것을 실측).
