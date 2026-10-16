# Archive Index — 2026-10

| Feature | Match Rate | Archived Date | Documents |
|---------|:----------:|:-------------:|:---------:|
| admin-model-settings | 95% | 2026-10-01 | [Plan](admin-model-settings/admin-model-settings.plan.md), [Design](admin-model-settings/admin-model-settings.design.md), [Analysis](admin-model-settings/admin-model-settings.analysis.md), [Report](admin-model-settings/admin-model-settings.report.md) |
| llm-fallback-alert | — ※※ | 2026-10-02 | [Plan](llm-fallback-alert/llm-fallback-alert.plan.md), [Design](llm-fallback-alert/llm-fallback-alert.design.md) |
| anthropic-sdk-v1 | — (중단) ※ | 2026-10-01 | [Plan](anthropic-sdk-v1/anthropic-sdk-v1.plan.md), [Design](anthropic-sdk-v1/anthropic-sdk-v1.design.md) |
| kin-answer-accuracy | 98% | 2026-10-05 | [Plan](kin-answer-accuracy/kin-answer-accuracy.plan.md), [Design](kin-answer-accuracy/kin-answer-accuracy.design.md), [Analysis](kin-answer-accuracy/kin-answer-accuracy.analysis.md), [Report](kin-answer-accuracy/kin-answer-accuracy.report.md) |
| effective-law-and-graph-precedents | 98.2% | 2026-10-05 | [Plan](effective-law-and-graph-precedents/effective-law-and-graph-precedents.plan.md), [Design](effective-law-and-graph-precedents/effective-law-and-graph-precedents.design.md), [Analysis](effective-law-and-graph-precedents/effective-law-and-graph-precedents.analysis.md), [Report](effective-law-and-graph-precedents/effective-law-and-graph-precedents.report.md) |
| audit-50-legal-accuracy | 99.7% ※※※ | 2026-10-14 | [Plan](audit-50-legal-accuracy/audit-50-legal-accuracy.plan.md), [Design](audit-50-legal-accuracy/audit-50-legal-accuracy.design.md), [Analysis](audit-50-legal-accuracy/audit-50-legal-accuracy.analysis.md), [Report](audit-50-legal-accuracy/audit-50-legal-accuracy.report.md) |
| calc-card-followups | 95.6% ※※※※ | 2026-10-16 | [Plan](calc-card-followups/calc-card-followups.plan.md), [Design](calc-card-followups/calc-card-followups.design.md), [Analysis](calc-card-followups/calc-card-followups.analysis.md), [Report](calc-card-followups/calc-card-followups.report.md) |

※ **Design 후 중단.** 9-27 재빌드가 anthropic SDK 1.8.0을 받아 Claude 답변이 전량 폴백된 사고의
후속으로 SDK 1.x 대응을 설계했으나, "API만 쓰는데 SDK를 왜 올리나"라는 판단으로 중단했다 —
원인은 업그레이드 부재가 아니라 버전 미고정이었고 `anthropic<1.0` 상한(PR #83)으로 충분하다.
문서는 **나중에 SDK를 올려야 할 때의 참고**로 남긴다: 1.x 비호환 3종(httpx2 타임아웃 타입·
`temperature` 삭제·`text_stream` 삭제)과 0.x/1.x 양립 경로를 실측으로 정리해 두었다.

※※ **Plan·Design만 있다.** 판정 스크립트 1개 + 워크플로 1개 규모라 Check(gap 분석)·Report를 생략한
소규모 사이클이다 — 누락이 아니다. 검증은 PR #89에 있다: 오프라인 테스트 14건(8월 장애 재현 —
8-22에 감지됐을 것), CodeRabbit 지적 2건 반영(합성 행 폭주 시 페이지 조회, 페이지 경계 중복 제거),
머지 후 GitHub Actions 수동 실행 성공(2026-10-02, 판정 정상·exit 0). 계기가 된 실측 — 8-21~9-28
38일간 프로덕션 실사용 답변 17/17 폴백 — 은 Plan §1에 있다.

※※※ **완료 조건 2(대상 14문항 금지 주장 0)는 답변 모델 gpt-6-sol 기준이다.** Gemini 선불 크레딧 소진·Claude 사용 한도로
답변 1순위가 OpenAI(rev 12)였던 10-14 실측(96답변, 원문 판독 실제 오답 0)이다. Act-4·5(gemini-3.8-flash)와 모델이 달라
'주휴' 블록 결론 먼저(C52)만의 효과는 분리되지 않았다 — 1순위를 Gemini·Claude로 되돌리면 그 모델로 다시 확인한다(보고서 §9.2).

※※※※ **완료 조건 6개 중 충족 2, 부분 충족 4다**(보고서 §6). 계산 카드 금지 수치 0/11은 C27 반영 뒤 **1회 실행**(답변 모델 gpt-6-sol rev 12)이고,
계획한 2회 반복은 하지 않았다. '8시간·40시간 이하 입력 불변' 목표는 F5(고용보험법 제45조②)가 월급만 있는 실업급여 카드를 **의도적으로**
바꿔 깨졌다(CLI #17 11,554,560 → 11,880,000원). Check에서 찾은 설계 밖 High(공개 해고예고 흐름도가 옛 면제로 계산)는 핫픽스 PR #116으로
고쳤고, Match Rate는 그 뒤 재분석하지 않았다. 후속 사이클 후보: 미확인 모드 '추정 금지'와 조건부 산식 충돌(kin-01), 연장시간을 따로 적은
질문의 세전 < 세후(G2 재현).
