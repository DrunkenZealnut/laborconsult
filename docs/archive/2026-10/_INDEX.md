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
| calc-card-consistency | 98.4% ※※※※※ | 2026-10-21 | [Plan](calc-card-consistency/calc-card-consistency.plan.md), [Design](calc-card-consistency/calc-card-consistency.design.md), [Analysis](calc-card-consistency/calc-card-consistency.analysis.md), [Report](calc-card-consistency/calc-card-consistency.report.md) |
| chat-submission-lock | 99.4% ※※※※※※ | 2026-10-23 | [Plan](chat-submission-lock/chat-submission-lock.plan.md), [Design](chat-submission-lock/chat-submission-lock.design.md), [Analysis](chat-submission-lock/chat-submission-lock.analysis.md), [Report](chat-submission-lock/chat-submission-lock.report.md) |
| monthly-base-unification | 100% ※※※※※※※ | 2026-10-23 | [Plan](monthly-base-unification/monthly-base-unification.plan.md), [Design](monthly-base-unification/monthly-base-unification.design.md), [Analysis](monthly-base-unification/monthly-base-unification.analysis.md), [Report](monthly-base-unification/monthly-base-unification.report.md) |
| ai-gateway-oidc-migration | 99.7% ※※※※※※※※ | 2026-10-29 | [Plan](ai-gateway-oidc-migration/ai-gateway-oidc-migration.plan.md), [Design](ai-gateway-oidc-migration/ai-gateway-oidc-migration.design.md), [Analysis](ai-gateway-oidc-migration/ai-gateway-oidc-migration.analysis.md), [Report](ai-gateway-oidc-migration/ai-gateway-oidc-migration.report.md) |

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

※※※※※ **완료 조건 6개 중 충족 4, 단서 붙은 충족 1, 부분 1이다**(보고서 §6). 부분은 지식iN 20 필수 조문이다 — 핫픽스 코드 1회 실측에서 18(기준선 19)이었고,
빠진 kin-02는 계산 카드가 없는 문항이며 답변이 '제56조'를 법령명 없이 적어 매처에 걸리지 않았다. 단서는 휴업수당 시급제 기준 월액(격자 87카드)으로,
이 사이클 전부터의 결함이라 예상 실패 테스트로 분리했다. Check에서 찾은 설계 밖 Medium('총 N시간'이 하루 근무의 합계인데 1주 합계로 읽어 조건부
예시가 '미발생'을 냄)은 핫픽스 PR #119로 고쳤고, Match Rate는 그 뒤 재분석하지 않았다. 실측 답변 모델은 gpt-6-sol rev 12다. 후속 사이클 후보:
기준 월액 단일화(고정수당 f1·f2, 휴업수당 f4).

※※※※※※ **완료 조건 6개 모두 충족이다**(보고서 §5). 다만 1·5번은 실행 기록에 기대는데, 수정 전 실패 확인·브라우저 확인·CI 28단계가 그 기록이다. 브라우저 확인은 PR 리뷰 반영(`.trim()` 복원, 진행 중 FAQ 예약 전송) 이전 코드 기준이고, 두 수정은 행동 테스트 L8·L11이 고정한다. Check 뒤에는 테스트 사례만 더했고 전체 변이 재실행은 하지 않았다(저장소 밖 스크립트 유실, M9·M10만 사본에서 확인). 후속 후보: 진행 중 FAQ가 써 둔 초안을 덮는 문제(DG-1), 드래그앤드롭 첨부의 잠금 무시(DG-3), 한글 IME 조합 중 Enter, 답변 중지 버튼, `?q=` 외부 링크 자동 전송.

※※※※※※※ **완료 조건 6개 모두 충족이다**(보고서 §5). 단 5번(Live)은 PR #123 기준 충족이고 #124 이후 Live는 미측정이다. 2번은 Design D11이 의도된 변경 축에 포괄임금 명세 총액·공휴일 수당 월 환산을 더한 뒤의 판정이고(Plan v0.2에 반영), 실업급여·산재 평균임금 분모 변경(3개월 총일수)도 의도된 변경이다. Live(계산 카드 금지 수치 5/5 → 0/0 두 회차, 지식iN 필수 조문 0.950 → 1.000)는 PR #123 최종 코드 기준이고 답변 모델은 gpt-6-sol rev 12다. Check(Match Rate 100%)가 설계 밖에서 찾은 PR #123의 회귀 둘 — '세금 포함'·'4대보험 포함' 앞의 수당을 월급 총액 안으로 보고 빼 세전 30만 원 과소(Medium), 연봉 2,200만 원 근로장려금 1원(월액 반올림 × 12) — 은 핫픽스 PR #124로 고쳤고, 핫픽스 뒤 Live는 다시 재지 않았다(바뀐 경로가 fixture에 없어 오프라인 회귀로 확인). 후속 후보: 의도분석이 연 상여를 월 수당으로 뽑는 문제(고정수당 주기 필드 부재 — 단일화로 평균임금 계열까지 번짐, 4회 중 2회)와 채팅 경로의 연 상여 미전달, DC형·근로장려금의 연 상여 미포함, 탄력 연장 임금의 월 총액 단독 반영, 공개 휴업수당 흐름도의 '월급 ÷ 30'.

※※※※※※※※ **완료 조건 7개 모두 충족이다**(보고서 §3.1). Check 93.0%(설계 사각 G-M1~G-M3·BS5~BS8)에서 Act 1회(PR #146)로 99.7%. 코드는 PR #145(74aa04d)·#146(1c4f9cf), 보고서는 PR #147(88f7f5b — Codex P2 1건·CodeRabbit Minor 3건 반영, 2건은 사유를 달아 미반영: Gateway 크레딧은 USD 정산값이라 원화 환산 안 함·타 사이클 문서 경로는 그 사이클 PR에서). 프로덕션은 `LLM_TRANSPORT=gateway`로 Claude·OpenAI·임베딩·Cohere 재정렬이 Vercel AI Gateway(OIDC 헤더·Gateway 크레딧)를 거치고, 임베딩 코사인 0.999999·재정렬 순서 동일·Claude 폴백 0을 확인했다. **Gemini 3순위는 Gateway로 가지 않는다** — `gemini-pro-latest` 별칭에 대응하는 슬러그가 없고 모델 임의 대체는 금지라 직접 호출이 남는다(F-6, 슬러그는 사용자가 정한다). 후속 7건(보고서 §4.1) 중 지킬 것 셋: F-1 V-9 토큰 만료 실측은 **재pull 없이** 12시간을 넘긴 뒤 호출 → SDK 401 확인(`GatewayAuthError`는 토큰 **부재** 전용이라 만료 경로에서는 나지 않는다) → 재pull 복구 순서다(`vercel env pull`이 토큰을 갱신하므로 순서가 바뀌면 검증이 안 된다 — Codex #147 정정) — **2026-10-30 완료**(보고서 v1.4 §9, 수명 12.0시간·전 표면 401·키 폴백·토큰 유출 0). F-2 Vercel env 제공자 키 3종(ANTHROPIC·OPENAI·COHERE) 삭제는 복귀 창 종료(≈2026-11-04) 뒤 **사용자 승인** 사항이고 제공자 측 키는 다른 프로젝트가 공유하므로 폐기하지 않는다. F-4 `check_llm_fallback.py`가 전 제공자 실패(미저장)와 '실사용 0건 + health 정상'을 ✅로 보는 사각은 High — Gateway 장애도 같은 경로로 숨는다. 결제·크레딧 구매·자동 충전은 하지 않았다. 토큰 값은 저장소·PR·로그·문서에 남기지 않았다 — 단 구현 중 `test_llm_transport.py` T2 실패 메시지가 로컬 토큰(12시간 만료)을 터미널에 한 번 출력했고, 단언을 값 비출력으로 고친 뒤 재발이 없다(보고서 §3.4 제약 2, 부분 위반 1건으로 기록).
