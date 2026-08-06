# Archive Index — 2026-08

| Feature | Match Rate | Archived Date | Documents |
|---------|:----------:|:-------------:|:---------:|
| chatbot-security | 98% | 2026-08-01 | [Plan](chatbot-security/chatbot-security.plan.md), [Design](chatbot-security/chatbot-security.design.md), [Analysis](chatbot-security/chatbot-security.analysis.md), [Report](chatbot-security/chatbot-security.report.md) |
| answer-renderer-test-harness | 100% | 2026-08-02 | [Plan](answer-renderer-test-harness/answer-renderer-test-harness.plan.md), [Report](answer-renderer-test-harness/answer-renderer-test-harness.report.md) |
| llm-fallback-hardening | 99% | 2026-08-06 | [Plan](llm-fallback-hardening/llm-fallback-hardening.plan.md), [Design](llm-fallback-hardening/llm-fallback-hardening.design.md), [Analysis](llm-fallback-hardening/llm-fallback-hardening.analysis.md), [Report](llm-fallback-hardening/llm-fallback-hardening.report.md) |

> **Note**: `answer-renderer-test-harness`는 Design·Analysis 문서가 없다. 설계 결정은 Plan 문서의 "설계 결정" 절이 겸했고, Check 단계는 `node --test` 실행 결과(8/8 통과)로 갈음했다(사유는 Report의 Check 절에 기재). 선행 사이클은 [2026-07/answer-ui-readability](../2026-07/answer-ui-readability/).
>
> **Note**: `llm-fallback-hardening`은 설계 중 3순위 폴백(Gemini)이 이미 404로 죽어있음을 실측 발견해 Wave 0으로 긴급 승격한 사례. Check 91%→Act-1로 99%. PR #33(555ae12)·#34(ff37b28)로 `main` 머지 완료. CodeRabbit 1·2차 리뷰에서 실제 결함(교정 공백 응답이 완성 답변을 지우는 버그, 의도분석 빈 tool 응답 시 폴백 미발동, 고지 순서 역전)을 발견해 수정 — 상세는 Report §5.
