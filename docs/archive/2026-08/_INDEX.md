# Archive Index — 2026-08

| Feature | Match Rate | Archived Date | Documents |
|---------|:----------:|:-------------:|:---------:|
| chatbot-security | 98% | 2026-08-01 | [Plan](chatbot-security/chatbot-security.plan.md), [Design](chatbot-security/chatbot-security.design.md), [Analysis](chatbot-security/chatbot-security.analysis.md), [Report](chatbot-security/chatbot-security.report.md) |
| answer-renderer-test-harness | 100% | 2026-08-02 | [Plan](answer-renderer-test-harness/answer-renderer-test-harness.plan.md), [Report](answer-renderer-test-harness/answer-renderer-test-harness.report.md) |
| llm-fallback-hardening | 99% | 2026-08-06 | [Plan](llm-fallback-hardening/llm-fallback-hardening.plan.md), [Design](llm-fallback-hardening/llm-fallback-hardening.design.md), [Analysis](llm-fallback-hardening/llm-fallback-hardening.analysis.md), [Report](llm-fallback-hardening/llm-fallback-hardening.report.md) |
| answer-at-a-glance | 100% | 2026-08-07 | [Plan](answer-at-a-glance/answer-at-a-glance.plan.md), [Design](answer-at-a-glance/answer-at-a-glance.design.md), [Analysis](answer-at-a-glance/answer-at-a-glance.analysis.md), [Report](answer-at-a-glance/answer-at-a-glance.report.md) |
| captcha-fetch-error-handling | 100% | 2026-08-07 | [Plan](captcha-fetch-error-handling/captcha-fetch-error-handling.plan.md), [Design](captcha-fetch-error-handling/captcha-fetch-error-handling.design.md), [Analysis](captcha-fetch-error-handling/captcha-fetch-error-handling.analysis.md), [Report](captcha-fetch-error-handling/captcha-fetch-error-handling.report.md) |

> **Note**: `answer-renderer-test-harness`는 Design·Analysis 문서가 없다. 설계 결정은 Plan 문서의 "설계 결정" 절이 겸했고, Check 단계는 `node --test` 실행 결과(8/8 통과)로 갈음했다(사유는 Report의 Check 절에 기재). 선행 사이클은 [2026-07/answer-ui-readability](../2026-07/answer-ui-readability/).
>
> **Note**: `llm-fallback-hardening`은 설계 중 3순위 폴백(Gemini)이 이미 404로 죽어있음을 실측 발견해 Wave 0으로 긴급 승격한 사례. Check 91%→Act-1로 99%. PR #33(555ae12)·#34(ff37b28)로 `main` 머지 완료. CodeRabbit 1·2차 리뷰에서 실제 결함(교정 공백 응답이 완성 답변을 지우는 버그, 의도분석 빈 tool 응답 시 폴백 미발동, 고지 순서 역전)을 발견해 수정 — 상세는 Report §5.
>
> **Note**: `answer-at-a-glance`는 완성된 답변에 목차·접기·핵심요약 고정 레이어(`public/finalize.js`)를 얹는 순수 프론트엔드 후처리 사이클. Check 87%→Act-1로 100%(Gap 12건 전건 수정). PR #35(24d4b4e)로 `main` 머지 완료. 챗봇+게시판 양쪽에 동시 적용하기로 사용자가 범위를 확정(Plan §8). CodeRabbit 리뷰에서 공개 HTML 주석의 내부 경로 노출을 발견해 수정.
>
> **Note**: `captcha-fetch-error-handling`은 2026-08-07 실제 프로덕션 장애("이메일 발송 시 보안문자가 undefined") 신고를 계기로 시작된 사이클. 원인은 서버(환경변수 미설정 503, 운영 이슈)와 프론트(`fetch`가 4xx/5xx에 reject하지 않아 오류 본문을 정상 데이터로 파싱) 두 계층이 겹친 것 — 이 PDCA는 프론트 계층만 수정했고 **CAPTCHA를 발급되게 만들지는 않는다**(Report §4.2, §9.3). Check 95%→Act-1로 100%(429 rate-limit 잔여 타이머가 버튼 게이팅을 무력화하는 숨은 버그 추가 발견·수정). PR #36(93f7dc5)로 `main` 머지, 배포 후 `curl`로 503→200 전환 실측 확인.
