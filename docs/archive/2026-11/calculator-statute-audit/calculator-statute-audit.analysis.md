# calculator-statute-audit — Design-Implementation 갭 분석

> **기준 문서**: `docs/archive/2026-11/calculator-statute-audit/calculator-statute-audit.design.md` (v1.0) · Plan `docs/archive/2026-11/calculator-statute-audit/calculator-statute-audit.plan.md`
> **기준 커밋**: main `0c80a4a` (PR #162 `fix/calc-statute-audit-ei` + PR #163 `fix/calc-statute-audit-iaci` 머지 후)
> **대조 일자**: 2026-11-12 (gap-detector)
> **대조 항목**: 57 · ✅ 일치 47 · ⚠️ 부분/편차 9 · ❌ 미완 1
> **Match Rate: 90.4%** (가중: ✅ 1, ⚠️ 0.5, ❌ 0 → 51.5 / 57). 구현 존재율(⚠️도 존재로 셈)은 98.2%(56/57)입니다.
> 정적으로 확인할 수 없는 Plan §7-1(main 실패·PR 통과)과 §7-5(CodeRabbit·Codex·Vercel)는 대조에서 뺐습니다.

---

## 1. 요약

- D1~D12는 모두 구현돼 있습니다. 산식·고시 효력 기간·급여별 최고·최저 적용·61세 경로별 계수·통상근로계수·등록 15건이 설계와 맞습니다.
- 등록한 공식 원문 문서 15건(ARTICLES 10, ANNEXES 1, ADMRULS 4)은 모두 `output_공식법령/`에 로컬로 수집돼 있습니다(Plan §7-2 충족).
- 미완은 1건입니다. `check_law_freshness.py --anchors`를 실행하지 못했습니다(회선 IP 미등록 → LawApiAuthError, Plan §7-3).
- 편차 9건 중 코드 수정이 필요한 것은 2건(I5 '진폐' 문구 감지, 별표 1 제1호 단서 하한에 테스트·앵커 없음)이고, 나머지는 설계 문서 갱신 대상입니다.

---

## 2. 항목별 대조

### 2.1 설계 결정 D1~D12 (12항목: ✅ 9 · ⚠️ 3)

| ID | 설계 요구 | 구현 위치 | 판정 | 메모 |
|---|---|---|:-:|---|
| D1 | 조기재취업 = 일액 × 미지급일수 × 1/2, 하한 라벨, '최대' 삭제 | `unemployment.py` 7절(L343-354), breakdown L382 | ✅ | 문구 "조기재취업수당(절반 남긴 시점 기준): … × 미지급일수 N일 × 1/2 … (고용보험법 시행령 제85조 제1항)" |
| D2 | 요건은 안내만, 고시 임금은 효력 기간 표에서 기준일로 조회 | `constants.EARLY_REEMPLOYMENT_WAGE_CAPS`·`early_reemployment_wage_cap`, `unemployment._early_reemployment_note` | ✅ | 시그니처가 `(year, reference_date)` → `(reference_date)`로 줄었습니다(기능 동일). `reference_date`가 없으면 `kst_today()` |
| D3 | 18개월(초단시간 24개월) 문구, 일용근로자 제40조①5호·제49조① 단서 안내 | `unemployment.py` L155-171 | ✅ | |
| D4 | 요양 ≤ 3일이면 0원, 근로기준법 제78·79조 안내 | `industrial_accident._calc_sick_leave` L363-369 | ✅ | 설계는 경고 리스트에 넣는다고 했고 구현은 formulas에 넣었습니다(테스트가 formulas를 단언) |
| D5 | 최고는 장례비 외 전 급여, 최저는 장해·유족만, 최저 = max(고시, 최저임금×8) | `calc_industrial_accident` 1-2절(L187-214), `_compensation_limits` | ✅ | 최저 보상기준 formula 메시지는 `uses_floor`일 때만 냅니다(편차 b) |
| D6 | `COMPENSATION_LIMITS_DAILY` 한 표, `MIN_COMPENSATION_DAILY` 파생, 최고 None 해는 미적용 + 경고 | `constants.py` L622-628, `industrial_accident.py` L198-203 | ⚠️ | 표·파생은 일치합니다. 경고는 `avg_daily > 최저 × 3.6`일 때만 냅니다. 설계는 무조건(편차 f, CLAUDE.md에만 기록) |
| D7 | 61세 이후 경로별 계수(base70 n/70, low90·min_wage n/90, low_min80 = 최저보상×80%×n/90), age 0이면 없음 | `_SENIOR_FACTORS`·`_senior_factor`·`_calc_sick_leave` 5단계 | ✅ | 별표 1 제1호 단서 하한(`floor3`)이 설계 밖에서 추가됐습니다. 원문(fixture L16-20)과는 맞지만 테스트·앵커가 없습니다(편차 g) |
| D8 | 일당 × 0.73, 조건: `is_daily_worker and daily_wage and not 3개월 계속` | `industrial_accident.py` L154-183, `_continued_three_months` | ✅ | 3개월 판정이 `DateRange.months_approx`(30.44일 근사)라 달력상 3개월 경계에서 1~2일 어긋날 수 있습니다(Low) |
| D9 | 직업병 특례 안내(`injury_type` 질병·뇌심혈관 **또는 '진폐' 언급**) | `industrial_accident.py` L142-148 | ⚠️ | `injury_type`만 봅니다. '진폐' 문구 감지가 없습니다(편차 h) |
| D10 | 새 근거 문구마다 앵커 + 등록(앵커 전용, 고시는 law.go.kr 전용) | `legal_anchors.py` L48-84, `fetch_official_rules.py` | ⚠️ | 등록은 완전히 일치합니다. 앵커는 설계 §1.3 구절 중 2개가 빠졌습니다(편차 i) |
| D11 | 흐름도 두 사본 본문 동일, sw.js 상향 | 두 흐름도 사본, `sw.js` `v16-2026-11-12` | ✅ | PR-1 v15 → PR-2 v16(설계 §4 "PR-2는 다시 올린다"와 일치). 동일성은 `<svg>` 이후 본문 비교 테스트로 확인합니다 |
| D12 | 테스트 파일 하나 + CI 등록 | `test_calculator_statute_audit.py`, `tests.yml` L152 | ✅ | 테스트 26건(직접 셈) |

### 2.2 §3 PR-1 실업급여 세부 (11항목: ✅ 11)

| ID | 설계 요구 | 구현 위치 | 판정 | 메모 |
|---|---|---|:-:|---|
| U1-1 | 산식 문구 "미지급일수 × 1/2 … 시행령 제85조" | `unemployment.py` L348-351 | ✅ | |
| U1-2 | 요건 안내: 14일·1/2·12개월·65세 6개월·제외 5종·2년·청구 12개월 뒤 | `_early_reemployment_note` L442-453 | ✅ | 끝에 "(고용보험법 시행령 제84조·제86조)"를 덧붙였습니다 |
| U1-3 | `EARLY_REEMPLOYMENT_WAGE_CAPS` `("2026-11-01","2029-10-31",3_000_000,"…제2026-71호")`, 표 밖이면 일반 문구 | `constants.py` L51-63 | ✅ | 양 끝 날짜를 포함합니다 |
| U1-4 | breakdown "N원 (소정급여일수의 절반을 남기고 재취업한 경우 …)" | L382 | ✅ | |
| U1-5 | legal에 제64조·시행령 제84~86조 | L353-354 | ✅ | |
| U1-6 | 흐름도 공식 "× 미지급(잔여)일수 × 1/2", 예시 "68,100 × 150일 × 1/2 = 5,107,500원", 요건 한 줄 | `public/…/unemployment_benefit_calc.html` L355·L392·L401 | ✅ | 패키지 사본 JS의 `×0.5` 중복 곱도 고쳤습니다(CLAUDE.md L550) |
| U2 | "이직일 이전 18개월 이내(초단시간근로자는 24개월)…(제40조 제1·2항)", '일용직은 1년' 삭제 | L157-163 | ✅ | |
| U3 | `is_daily_worker`면 3분의 1·14일간·제49조① 단서 안내, legal 추가 | L164-171 | ✅ | 노무제공자 분기의 else 쪽(일반 근로자)에만 붙습니다 |
| 경과조치 | `end_year < year`이고 상한이 다르면 종전 상한·부칙 제35934호 제4조 경고, 계산값 불변 | L274-282, `_year_of` | ✅ | 문구는 "구직급여 상한액은 이직일 기준으로…"이고 기준연도 상한도 함께 밝힙니다 |
| 등록 | ARTICLES +`ei_enf_85`·`ei_enf_86`, ADMRULS +`ei_early_reemp_wage`, `ADMRUL_LAW_GO_KR_ONLY` | `fetch_official_rules.py` L129-130·L183-184·L194 | ✅ | |
| 앵커 | §1.1·§1.2 구절(설계 본문 셈 11, §3 표기 "10개") | `legal_anchors.py` L49-62 | ✅ | 실제 13개입니다. 설계 11개를 모두 포함하고, 추가 2개(`ei_act_64` 금액 위임, `ei_enf_84` "소정급여일수를 2분의 1 이상 남기고")는 바람직한 추가입니다 |

### 2.3 §4 PR-2 산재 세부 (16항목: ✅ 12 · ⚠️ 4)

| ID | 설계 요구 | 구현 위치 | 판정 | 메모 |
|---|---|---|:-:|---|
| I1-1 | `days <= 3` → 0원·제52조 단서·제78·79조 | `_calc_sick_leave` L363-369 | ✅ | breakdown "0원 (요양 N일 ≤ 3일 — 제52조 단서)" |
| I1-2 | 제79조 legal은 이 분기에서만 | 같은 곳 L368 | ✅ | "근로기준법 제78조·제79조 (사용자의 요양보상·휴업보상)" |
| I2-1 | 표 2024 `(None,78_880)`·2025 `(None,80_240)`·2026 `(268_299,82_560)`, 최저 열 파생 | `constants.py` L622-628 | ✅ | |
| I2-2 | 휴업·상병 `avg_capped`, 장해·유족 `avg_floor`, 장례비 `avg_daily` | L225·L240·L259·L273·L283 | ✅ | |
| I2-3 | 최고·최저 적용 formulas + 제36조⑦ legal | L193-197·L209-214 | ✅ | 최저 메시지는 `uses_floor`일 때만 냅니다(편차 b) |
| I2-4 | 최고 None이면 "{year}년 최고 보상기준 금액 미확인 …" 경고 | L198-203 | ⚠️ | `avg_daily > comp_low × 3.6` 조건이 붙었습니다(편차 f) |
| I2-5 | breakdown "적용 평균임금"에 급여별 값 | L217-219 | ✅ | 보상기준이 걸렸을 때만 괄호를 붙입니다 |
| I3-1 | 경로 `base70`·`low90`·`low_min80`·`min_wage` | L378-395 | ✅ | |
| I3-2 | `_SENIOR_FACTORS = {61:(66,86),62:(62,82),63:(58,78),64:(54,74)}`, 65세 이후 (50,70), age 0이면 없음 | L333-341 | ✅ | |
| I3-3 | 감액 경고(계수·연령 도달일·제55조 단서) + legal | L408-413 | ✅ | |
| I4-1 | 일당 × 0.73 formula·3개월 단서·제24조② 신청 안내 | L157-166 | ✅ | |
| I4-2 | 3개월 계속이면 미적용 + 안내, `daily_wage` 없으면 안내만 | L178-183 | ✅ | |
| I5 | 질병·뇌심혈관 **또는 '진폐'** → 제36조⑥·시행령 제25조 안내 | L142-148 | ⚠️ | '진폐' 감지가 없습니다(편차 h) |
| 흐름도 | 3일 미지급, "최고·최저 보상기준(2026: 268,299/82,560원 — 휴업·상병은 최고만)", 61세 감액 | `public/…/industrial_accident_compensation_calc.html` L221·L272 | ⚠️ | 3일·최고 268,299·61세는 있습니다. **최저 82,560원 보상기준과 '휴업·상병은 최고만' 문구가 없습니다**(L344의 82,560은 휴업급여 최저임금 하한 문구) |
| 등록 | ARTICLES +8(iaci_act_36·52·54·55, iaci_enf_23·24·25, lsa_act_79), ANNEXES +`iaci_annex1`, ADMRULS +3, LAW_GO_KR_ONLY | `fetch_official_rules.py` L133-140·L153·L187-189·L194 | ✅ | 수가 정확히 맞습니다 |
| 앵커 | §1.3 구절(설계 본문 셈 17, §4 표기 "14개") | `legal_anchors.py` L64-84 | ⚠️ | 실제 17개입니다. **빠진 것 2개**: `iaci_enf_23` 일용근로자 정의("1일 단위로 고용되거나…"), `iaci_enf_25` ②1호 "고용노동부장관이 매년 고시하는 금액". **추가 2개**: `iaci_act_36` "시간급 최저임금액에 8을 곱한 금액", `iaci_annex1` "최저 보상기준 금액 × 80/100 × 86/90" |

### 2.4 §5 테스트 표 (12행: ✅ 11 · ⚠️ 1)

| 그룹 | 설계 단언 | 실제 테스트 | 판정 | 메모 |
|---|---|---|:-:|---|
| U1 | "미지급일수"·"1/2", "(최대)" 없음, 값 = 일액×(days//2)×0.5, 경고에 14일·12개월·65세·2년, 11-12 포함 / 10-01·2029-11-01 미포함 | `EarlyReemploymentWageCapTests`(2) + `EarlyReemploymentTests`(4) | ✅ | 효력 기간 양 끝(11-01·2029-10-31)과 None 경계까지 봅니다 |
| U2 | "일용직은 1년" 없음, 18·24개월 | `test_reference_period_text_has_no_daily_worker_one_year` | ✅ | "1년" 부재로 더 강하게 단언합니다 |
| U3 | True면 3분의 1·14일간·제40조 제1항 제5호, False면 없음 | `test_daily_worker_gets_the_one_third_rule_note` | ✅ | 제49조 단서·legal까지 봅니다 |
| 경과조치 | 2025-12-15 → 66,000원·부칙, 2026 → 없음 | `test_upper_limit_note_when_separation_year_differs` | ✅ | `upper_limit == 68_100` 불변도 봅니다 |
| I1 | 3일 → 0·제52조 단서·제79조, 4일 → 70% | `test_three_days_or_less…`, `test_card_passes_age_and_days_through` | ✅ | |
| I2 | 고임금: 268,299×616·×70%·장례비 19,279,760 / 저임금: 82,560×55·휴업은 최저 미적용 / 2025 고임금: 미적용 + 경고 | `CompensationLimitTests`(4) | ✅ | 입력은 평균임금 직접값이 아니라 월급(12M·1.5M)입니다. 저임금 휴업은 최저임금 하한 82,560을 단언합니다 |
| I3 | 200,000·61 → ×66/70, 65 → ×50/70, **70,000·62 → 90% 경로 ×82/90**, 0 → 없음 | `SickLeaveTests` 3건 | ⚠️ | 저소득 사례를 93,000원 + 제54조② 최저임금 하한 경로(`82_560 × 82/90`)로 바꿨습니다(편차 d). 70·71세, 60세 경계와 63세 min_wage 경로를 더 봅니다. **base70 경로의 별표 1 제1호 단서 하한(`floor3`)은 어느 테스트도 실행하지 않습니다** |
| I4 | 150,000 → 109,500, 4개월 전이면 미적용 + 안내, daily_wage None이면 안내만 | `DailyWorkerAndDiseaseTests` 3건 | ✅ | 3개월 계속 사례는 입사 5개월 전(2025-10-01)입니다 |
| I5 | 질병 → 제36조 제6항, 사고 → 없음 | `test_occupational_disease_gets_the_special_average_note` | ✅ | '진폐' 사례는 없습니다(구현에도 없음) |
| 등록 | 새 doc_id가 ARTICLES∪ADMRULS∪ANNEXES에 있다 | `test_wage_update_2026.py::CalcBasisAnchorTests` L802(ANNEXES 포함으로 확장) | ✅ | 설계가 말한 "ADMRULS 3+1·ANNEXES 1 존재만" 별도 단언은 없지만, 앵커 doc_id 전수 검사가 이를 포함합니다 |
| 파생 | `MIN_COMPENSATION_DAILY == {y: lo}`, `[2026] == (268_299, 82_560)` | `CompensationConstantsTests` | ✅ | 2025 `(None, 80_240)`과 0.73도 봅니다 |
| 흐름도 | 두 사본 본문 동일, "÷ 2) × 50%" 없음 | `FlowchartTests`(2) + `AccidentFlowchartTests`(1) | ✅ | 2,553,750 부재와 5,107,500 존재까지 봅니다 |

### 2.5 문서·CI·완료 조건 (6항목: ✅ 4 · ⚠️ 1 · ❌ 1)

| ID | 요구 | 위치 | 판정 | 메모 |
|---|---|---|:-:|---|
| CI | `tests.yml` 모듈별 회귀 단계에 새 테스트 | `.github/workflows/tests.yml` L152 | ✅ | `test_unemployment_separation.py`(L98)·`test_wage_update_2026.py`(L139)도 실행 중입니다 |
| CLAUDE.md | Wage Calculator 절 bullet 2개 | `CLAUDE.md` L548-558·L559-569 | ✅ | 편차 d·f(3.6배 조건)를 여기에 기록했습니다 |
| Design §7 PR-1 | 바뀐 CLI 사례 기록 | Design L235-244 | ✅ | 금액 변화 0, 바뀐 줄 44, 사례 8건 |
| Design §7 PR-2 | 바뀐 CLI 사례 기록 + 스택 편차 | Design L246-250 | ⚠️ | 편차 a·b는 기록돼 있습니다. "SickLeave·CompensationLimit·DailyWorkerAndDisease **11건**"은 실제 **13건**(5+4+4)입니다 |
| Plan §7-2 | 새 등록 문서 로컬 수집 | `output_공식법령/` | ✅ | 15건 모두 있습니다(ei_enf_85·86, ei_early_reemp_wage, iaci_act_36·52·54·55, iaci_enf_23·24·25, lsa_act_79, iaci_annex1, iaci_comp_limits·funeral_limits·ordinary_coeff) |
| Plan §7-3 | `check_law_freshness.py --anchors` 실패 0 | — | ❌ | **미실행.** 회선 IP가 미등록이라 LawApiAuthError가 납니다. 현행판 대조와 다음 판본 앵커 확인이 비어 있습니다 |

Live 측정은 Plan §8에 따라 하지 않았으므로 대조 대상이 아닙니다.

---

## 3. 갭·편차 목록

| # | 내용 | 기록 여부 | 심각도 | 권고 |
|---|---|---|:-:|---|
| a | PR-2를 main이 아니라 PR-1 위에 쌓음(같은 새 테스트 파일의 add/add 충돌 회피) | Design §7 L250 ✅ | Low | **수용.** §2의 "PR-2는 main에서 따로"는 §7을 가리키는 주석으로 고칠 것 |
| b | 최저 보상기준 formula 메시지는 장해·유족급여를 계산할 때만(`uses_floor`) | Design §7 L248 ✅ / §4 I2 본문 ✕ | Low | **설계 갱신**(§4 I2 둘째 bullet에 조건 추가). 값(`avg_floor`)은 항상 계산되므로 동작 차이는 없습니다 |
| c | `test_unemployment_separation.py`: `ANNEX_FIXTURES`에 `iaci_annex1` 추가, U5 루프를 고용보험법 시행규칙 별표로 한정, U3 앵커 집합에 `CALC_BASIS_ANCHORS` 포함 | 미기록 | Low | **설계 갱신**(§5 표에 "기존 테스트 수정" 행 추가). U3 확장은 산재 별표 앵커를 CI에서 fixture로 실검증하게 하므로 긍정적입니다 |
| d | I3 저소득 기대값을 '제54조① 단서/90% 경로'에서 '제54조② 최저임금액 하한 경로'로 변경(2026년은 최저 보상기준 = 최저임금액이라 단서·90% 금액이 늘 그 아래) | CLAUDE.md L564-566 ✅ / Design §5 ✕ | Low | **설계 갱신**(§5 I3 행). 이 때문에 `low_min80`·`low90` 경로의 감액 계수는 2026년 입력으로 끝까지 확인되지 않습니다 — 2024·2025 입력으로 테스트를 하나 더하면 닿을 수 있는지 확인을 권합니다 |
| e | 산재 패키지 사본 흐름도의 `sendPrompt(`를 `window.parent?.sendPrompt?.(`로 통일 | 커밋 메시지만 | Low | **수용**(CLAUDE.md 규약 준수 수정). 설계 §4 흐름도 항에 한 줄 기록 |
| f | 최고 보상기준 미확인 연도 경고를 `avg_daily > 최저 × 3.6`일 때만 냄 | CLAUDE.md L561-562 ✅ / Design ✕ | Low | **설계 갱신**(D6·§4 I2). 설계의 무조건 경고는 2024·2025 모든 카드에 소음이 되므로 구현 쪽이 낫습니다 |
| g | 별표 1 제1호 단서 하한(`floor3 = 최저보상×80%×n/90`)을 base70 경로에 추가 | 코드 주석만 | **Medium** | **코드 수정**: ① 테스트 추가(예: 2026, 평균임금 100,000·age 65 → 70,000×50/70 = 50,000 < 82,560×0.8×70/90 = 51,370 → 51,370) ② `CALC_BASIS_ANCHORS`에 `("iaci_annex1", "제3호에 따라 산정한 금액보다 적으면")` 추가(fixture L18-20에 있음, 공백 무시 대조). 금액을 바꾸는 분기인데 회귀와 원문 앵커가 없어 조용히 깨질 수 있습니다. **설계 갱신**: D7에 단서 반영 |
| h | I5 직업병 안내가 `injury_type`만 보고 '진폐' 언급을 감지하지 않음 | 미기록 | Low | **코드 수정 또는 설계 갱신.** `WageInput`에 질문 원문 필드가 없다면 설계에서 '진폐' 조건을 지우고 "의도분석이 질병으로 분류할 때"로 바꾸는 쪽이 현실적입니다 |
| i | 앵커: 설계 §1.3의 `iaci_enf_23` 일용근로자 정의 구절과 `iaci_enf_25` ②1호 "고용노동부장관이 매년 고시하는 금액"이 빠짐(그 대신 2개 추가) | 미기록 | Low | **코드 수정**(두 구절 추가 — 둘 다 카드 문구 "1일 단위로 고용…"·"진폐는 매년 고시하는 금액"의 근거입니다). 설계의 개수 표기(§3 "10개", §4 "14개")는 본문 셈(11·17)과도 어긋나므로 실제 13·17(+보강분)로 고칠 것 |
| j | 산재 흐름도에 최저 보상기준 82,560원과 "휴업·상병은 최고만" 문구가 없음 | 미기록 | Low | **코드 수정**(L272 설명 줄에 "최저 82,560원은 장해·유족만" 추가 → 두 사본·`sw.js` VERSION 상향). `AccidentFlowchartTests`에 "82,560"을 넣으면 L344의 다른 82,560과 구분되지 않으니 "장해·유족" 같은 구절로 단언할 것 |
| k | Design §7 PR-2의 "11건"이 실제 13건 | — | Low | **설계 갱신** |
| l | `_continued_three_months`가 30.44일 근사(`months_approx`)라 달력상 3개월 경계에서 1~2일 오차(예: 01-01→04-01은 90일 → 2개월) | 미기록 | Low | **수용 또는 코드 수정.** 해고예고 계산처럼 달력 개월(민법 제160조)로 맞추려면 기존 달력 개월 유틸을 재사용하는 방법이 있습니다 |
| m | `_calc_sick_leave`의 최저 보상기준은 `MIN_COMPENSATION_DAILY.get(year, 최신연도)`라 `_compensation_limits`(표에 없는 해 → 최저임금×8)와 폴백이 다름 | 기존 코드 | Low | **수용**(2024~2026은 같은 값). 2027 행을 추가할 때 두 경로가 갈리지 않게 `_compensation_limits(year)[1]`을 넘기는 쪽으로 단일화를 권합니다 |
| n | `check_law_freshness.py --anchors` 미실행 | Plan §7-3 | **Medium** | 등록 회선(또는 등록 IP 호스트)에서 실행해 새 앵커 30개(EI 13 + 산재 17)의 현행판 실패 0을 확인하고, 결과를 보고서에 기록할 것 |

---

## 4. 권고 다음 단계

1. **Act-1(코드, 소규모)**: g(floor3 테스트 + 앵커), i(앵커 2개 추가), j(흐름도 최저 보상기준 한 줄 + sw VERSION). h는 설계 갱신 쪽을 권합니다.
2. **설계 문서 갱신**: b·c·d·f·h·k와 앵커 개수 표기, §2 PR 순서 문구, D7 단서 반영.
3. **Plan §7-3 실행**: 등록 IP 회선에서 `python3 check_law_freshness.py --anchors`를 돌려 실패 0을 확인합니다. 그 전까지는 이 사이클을 '부분 완료'로 둡니다.
4. 위 세 가지 뒤 재대조하면 Match Rate는 98% 이상이 됩니다(❌ 1과 ⚠️ 대부분 해소). 현재 90.4%로 90% 관문은 넘었지만, CLAUDE.md의 지적대로 Match Rate는 설계 자체의 공백을 보지 못합니다 — 특히 g는 설계에 없는 금액 분기라 독립 리뷰 대상으로 남깁니다.

---

## 관련 파일

- `docs/archive/2026-11/calculator-statute-audit/calculator-statute-audit.design.md`
- `docs/archive/2026-11/calculator-statute-audit/calculator-statute-audit.plan.md`
- `wage_calculator/calculators/unemployment.py`
- `wage_calculator/calculators/industrial_accident.py`
- `wage_calculator/constants.py`
- `wage_calculator/legal_anchors.py`
- `fetch_official_rules.py`
- `test_calculator_statute_audit.py`
- `test_unemployment_separation.py`
- `test_wage_update_2026.py`
- `data/annex_fixtures/iaci_annex1_20260701.txt`
- `public/calculator_flow/industrial_accident_compensation_calc.html`
- `public/calculator_flow/unemployment_benefit_calc.html`
- `public/sw.js`

---

## 5. 재대조(Act-1 후)

> **기준**: 브랜치 `fix/calc-statute-audit-act1`(PR #164), Design v1.1 · **대조 일자**: 2026-11-12 (gap-detector 2차)
> **대조 항목**: 57(1차와 같음) · 재대조 시점 ✅ 55 · ⚠️ 1 · ❌ 1 → **97.4%**. 재대조가 찾은 N1~N3을 같은 PR에서 고친 뒤 ⚠️ 0 → **98.2%**(56/57). 남은 ❌ 1은 Plan §7-3(`check_law_freshness --anchors`, 회선 IP 미등록).

### 5.1 편차 a~n 처리

| # | 1차 내용 | Act-1 후 | 판정 |
|---|---|---|:-:|
| a | PR-2를 PR-1 위에 쌓음 | 설계 §2에 스택 순서·재타깃 반영 | 설계 갱신 ✅ |
| b | 최저 보상기준 메시지가 `uses_floor`일 때만 | §4 I2에 조건·이유 반영 | 설계 갱신 ✅ |
| c | 기존 테스트 수정 3건 | §5 '기존 테스트 수정' 행 | 설계 갱신 ✅ |
| d | I3 저소득 기대값 경로 | §5 I3 행·D7 갱신 | 설계 갱신 ✅ |
| e | 패키지 사본 `sendPrompt` 통일 | §4 흐름도에 기록 | 설계 갱신 ✅ |
| f | 최고 미확인 경고 3.6배 조건 | D6·§4 I2 반영 | 설계 갱신 ✅ |
| g | `floor3` 테스트·앵커 없음 | 표 치환 테스트(137,500·61세 → 96,000×86/90 = 91,733) + 앵커 `("iaci_annex1", "제3호에 따라 산정한 금액보다 적으면")` + 산식 표시 + D7 | 해소 ✅ |
| h | '진폐' 감지 없음 | D9를 `injury_type` 기준으로 갱신. §4 I5 본문의 잔존 문구는 N2로 정정 | 해소 ✅ |
| i | 앵커 2개 누락 | `iaci_enf_23` 일용근로자 정의·`iaci_enf_25` ②1호 추가(원문 확인) → 산재 앵커 20 | 해소 ✅ |
| j | 흐름도 최저 보상기준·'휴업·상병은 최고만' 없음 | 두 사본 L272 문구 + `sw.js` v17 + 테스트 단언 | 해소 ✅ |
| k | §7 "11건" | 13건(Act-1 뒤 14건)으로 정정 | 설계 갱신 ✅ |
| l | `months_approx` 근사 | 수용(§8) | ✅ |
| m | 최저 보상기준 폴백 경로 2개 | 수용(§8) — 2027 행 추가 시 단일화 권고 | ✅ |
| n | `check_law_freshness --anchors` 미실행 | 회선 IP 미등록 | ❌ |

### 5.2 1차 ⚠️·❌ 10항목 재판정

D6·D9·D10(앵커 실업급여 13·산재 20 실측)·I2-4·흐름도·앵커·I3 테스트·Design §7 PR-2 → ✅. I5는 재대조 시점 ⚠️(§4 I5 본문에 '진폐' 문구 잔존)였고 N2로 정정해 ✅. Plan §7-3 → ❌ 유지.

### 5.3 재대조가 새로 찾은 것 (같은 PR에서 수정)

| # | 내용 | 조치 |
|---|---|---|
| N1 | 하한이 걸릴 때 산식 문구가 `× 66/70 = 91,733원`처럼 감액 **후** 값을 등식에 찍고, 경고의 계수도 실제 쓰인 제3호 계수와 달랐다(금액은 맞음). 카드는 "이 수치를 사용하세요"로 LLM에 들어가므로 틀린 등식이 인용될 수 있다 | 등식은 감액 전 값(`× 66/70 = 90,750원 → 하한 91,733원 적용`), 경고 계수는 `86/90(제1호 단서 → 제3호 하한)`. 테스트가 두 금액을 단언 |
| N2 | 설계 D9와 §4 I5 본문이 서로 달랐다('진폐' 감지) | §4 I5에서 '진폐' 조건 제거, D9를 가리킴 |
| N3 | D11이 `sw.js` v15로 남아 있었다 | "배포마다 상향(v15 → v16 → v17)" |

### 5.4 권고

- 보고서 단계로 갈 수 있다(98.2%). 보고서에는 Plan §7-3을 "부분 완료(현행판 앵커 대조 미실시 — 등록 IP 회선에서 `check_law_freshness --anchors` 실행 후 기록)"로 표시한다.
- Match Rate는 설계에 없는 것을 보지 못한다 — 금액 분기를 바꾼 `floor3`·`uses_floor` 경로는 보고서 전 독립 리뷰(CodeRabbit·Codex) 대상으로 남긴다.
