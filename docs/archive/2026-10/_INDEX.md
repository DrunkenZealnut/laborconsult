# Archive Index — 2026-10

| Feature | Match Rate | Archived Date | Documents |
|---------|:----------:|:-------------:|:---------:|
| admin-model-settings | 95% | 2026-10-01 | [Plan](admin-model-settings/admin-model-settings.plan.md), [Design](admin-model-settings/admin-model-settings.design.md), [Analysis](admin-model-settings/admin-model-settings.analysis.md), [Report](admin-model-settings/admin-model-settings.report.md) |
| llm-fallback-alert | — ※※ | 2026-10-02 | [Plan](llm-fallback-alert/llm-fallback-alert.plan.md), [Design](llm-fallback-alert/llm-fallback-alert.design.md) |
| anthropic-sdk-v1 | — (중단) ※ | 2026-10-01 | [Plan](anthropic-sdk-v1/anthropic-sdk-v1.plan.md), [Design](anthropic-sdk-v1/anthropic-sdk-v1.design.md) |

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
