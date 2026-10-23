"""
디스패처 헬퍼 — 계산기 결과 병합 및 summary populate 함수

facade.py 에서 분리 (Phase D)
"""
import re

from ..result import WageResult
from ..utils import fmt_hours


def _merge(result, section, calc_result, all_warnings, all_legal):
    """계산기 결과를 WageResult에 병합 (공통 필드)"""
    result.breakdown[section] = calc_result.breakdown
    if hasattr(calc_result, "formulas"):
        result.formulas.extend(calc_result.formulas)
    all_warnings.extend(calc_result.warnings)
    all_legal.extend(calc_result.legal_basis)


# 금액 보류(`calculate(..., amount_hold=)`) — pipeline 월급 구성 가드가 넘긴다. 그 경로의 통상임금은 연장·야간·휴일·연차수당이
# 섞인 월급 총액이라 그 값으로 낸 금액이 부풀려진다. 계산은 그대로 하고 금액만 뺀다 — 대상을 통째로 빼면 연차 발생일수·
# '퇴직금 미발생' 같은 시급과 무관한 판정까지 사라진다(Act-2 코드 리뷰 M2).
_WON_AMOUNT_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*원")
_WON_ANY_RE = re.compile(r"\d\s*원")
_QUANTITY_RE = re.compile(r"\d[\d,.]*\s*(?:일|h|시간|개월|년|주)")


def _has_amount(text) -> bool:
    """0이 아닌 원화 금액이 들어 있는가."""
    return any(float(m.group(1).replace(",", "")) for m in _WON_AMOUNT_RE.finditer(str(text)))


def _basis_free(text) -> bool:
    """금액(0원 포함)도 통상임금 비교('적용 기준: 통상임금')도 없는 줄 — 부풀린 통상임금과 무관하다. 0원 줄도 빼는 것은
    '과세표준: 2,865,414 - 2,865,414 = 0원'처럼 결론만 0이고 중간값은 부풀린 줄이 있어서다(Act-2 재검토 N4)."""
    text = str(text)
    return not _WON_ANY_RE.search(text) and "통상" not in text


def _ineligible(calc_result) -> bool:
    """계산기가 자격 판정으로 0을 냈는가(퇴직금 미발생·주휴 미발생·해고예고 면제·공휴일 미적용)."""
    return (getattr(calc_result, "is_eligible", None) is False
            or getattr(calc_result, "eligible", None) is False
            or getattr(calc_result, "is_exempt", None) is True)


def _merge_amount_held(result, key, section, calc_result, populate, all_warnings, all_legal,
                       ineligible=None) -> bool:
    """계산기 결과에서 금액만 빼고 병합한다. 자격 판정으로 금액이 0이면 False — 호출부가 그대로 병합한다.

    0원을 통과시키는 것은 자격 판정(`ineligible`, 없으면 결과의 자격 플래그)일 때뿐이다. 입력이 없어 0인 결과(연장시간·입사일
    미기재)를 통과시키면 사용자가 '포함돼 있다'고 한 수당에 '0원'과 '이 수치를 사용하세요'가 붙는다(Act-2 재검토 N1).

    남기는 것: 요약은 수량 사실(연차 발생일수·계속근로일수·보상휴가 시간 등)만, 계산식·안내·법적 근거는 금액과 통상임금
    비교가 없는 줄만('평균임금이 통상임금보다 적으면 통상임금' 근거는 보류한 금액의 근거라 뺀다). 요약의 비교 결과('적용 기준:
    통상임금'·'평균임금 70%')도 부풀린 통상임금과 비교해 나온 것이라 수량이 아니면 버린다. 금액은 monthly_total에 더하지
    않는다(호출부).
    """
    probe = WageResult()
    populate(calc_result, probe)
    formulas = getattr(calc_result, "formulas", [])
    if ineligible is None:
        ineligible = _ineligible(calc_result)
    texts = (*probe.summary.values(), *formulas, *calc_result.warnings)
    if ineligible and not any(_has_amount(text) for text in texts):
        return False
    result.amount_held.append(key)
    result.summary.update({k: v for k, v in probe.summary.items()
                           if _basis_free(f"{k} {v}") and _QUANTITY_RE.search(str(v))})
    result.formulas.extend(f for f in formulas if _basis_free(f))
    all_warnings.extend(w for w in calc_result.warnings if _basis_free(w))
    all_legal.extend(line for line in calc_result.legal_basis if _basis_free(line))
    breakdown = calc_result.breakdown if isinstance(calc_result.breakdown, dict) else {}
    result.breakdown[section] = {k: v for k, v in breakdown.items() if _basis_free(f"{k} {v}")}
    return True


# ── populate 함수: 각 계산기의 summary/특수필드 설정 ──────────────────────────
# 반환값 = 그 섹션의 월 금액. facade 월 총액은 기준 월액(shared.monthly_wage_total)이고, 반환값은 연장수당(premium 판정)과
# 탄력적 근로시간제(가산)만 읽는다 — 나머지는 쓰지 않는다(monthly-base-unification)


def _pop_overtime(r, result):
    """result.summary에 연장/야간/휴일수당(월) 추가. 반환: monthly_overtime_pay."""
    result.summary["연장/야간/휴일수당(월)"] = f"{r.monthly_overtime_pay:,.0f}원"
    return r.monthly_overtime_pay


def _pop_minimum_wage(r, result):
    """result.summary에 최저임금 충족 여부·실질시급·부족분 추가. 반환: 0."""
    from ..result import MW_COMPLIANT, MW_HELD, MW_NOT_APPLICABLE, MW_VIOLATION
    if getattr(r, "not_applicable", False):
        # 노무제공자는 원칙적으로 최저임금법의 근로자가 아니다(제2조) — 판정하지 않고 근로자로 인정될 때의 참고값만 둔다(F4)
        result.summary["최저임금 충족"] = "➖ 해당 없음(노무제공자)"
        result.summary["실질시급"] = f"{r.effective_hourly:,.0f}원(근로자로 인정될 때 참고)"
        result.minimum_wage_ok = None
        result.minimum_wage_state = MW_NOT_APPLICABLE
        return 0
    if getattr(r, "undetermined", False):
        # 기준(주휴 판례 원칙 vs 시행령 별표 2, 연장 별도 vs 연장 포함 역산, 수습 감액 여부)에 따라 판정이 갈린다 — 판정은
        # 보류(None), 실질시급을 함께 싣는다. 수습 감액 여부만 갈리면 실질시급은 하나고 최저임금 기준이 둘이다
        alternatives = getattr(r, "alternative_hourlies", ()) or ((r.alternative_hourly,) if r.alternative_hourly else ())
        values = list(dict.fromkeys([r.effective_hourly, *alternatives]))
        result.summary["최저임금 충족"] = "⏸ 판정 보류"
        result.summary["실질시급"] = " 또는 ".join(f"{v:,.0f}원" for v in values)
        if getattr(r, "alternative_minimum", 0):
            # 고시 금액을 먼저 둔다 — 감액값이 라벨 없이 '최저임금: 9,288원'처럼 읽히면 답변이 그대로 옮긴다
            result.summary["최저임금 기준"] = (f"{r.legal_minimum:,.0f}원 또는 수습 감액 {r.alternative_minimum:,.0f}원"
                                          "(요건을 모두 갖춘 경우)")
        result.minimum_wage_ok = None
        result.minimum_wage_state = MW_HELD
        return 0
    result.minimum_wage_state = MW_COMPLIANT if r.is_compliant else MW_VIOLATION
    result.summary["최저임금 충족"] = "✅ 충족" if r.is_compliant else "❌ 미달"
    result.summary["실질시급"] = f"{r.effective_hourly:,.0f}원"
    if not r.is_compliant:
        result.summary["부족분(월)"] = f"{r.shortage_monthly:,.0f}원"
    result.minimum_wage_ok = r.is_compliant
    return 0


def _pop_weekly_holiday(r, result):
    """result.summary에 주휴수당(월) 추가. 반환: 0 (base_hours에 이미 포함)."""
    result.summary["주휴수당(월)"] = f"{r.monthly_holiday_pay:,.0f}원"
    return 0


def _pop_annual_leave(r, result):
    """result.summary에 연차발생일수·연차수당·미사용일수·차감·비례·정산 추가. 반환: 0."""
    if r.accrual_basis == "company":
        result.summary["회사 부여 연차일수"] = f"{r.accrued_days:g}일"
    else:
        result.summary["법정 연차 발생일수"] = f"{r.accrued_days}일"
    result.summary["연차수당"] = f"{r.annual_leave_pay:,.0f}원"
    result.summary["미사용 연차"] = f"{r.remaining_days:.1f}일"
    if r.is_eligible:
        result.summary["연차 시간"] = f"발생 {r.accrued_hours:g}시간 · 사용 {r.used_hours:g}시간 · 잔여 {r.remaining_hours:g}시간"
        result.summary["연차수당 정산 상태"] = ("퇴직 시 현재 기간 잔여분 (당시 임금·기지급 확인 필요)" if r.pay_due
                                                else "입력 임금 기준 평가액 · 사용기간 만료/퇴직 전 확정 지급액 아님")
    if r.first_year_settlement_days is not None:
        result.summary["별도 첫해 미사용분"] = f"{r.first_year_settlement_days:g}일 (당해 발생분·수당에 합산하지 않음)"
    if r.deducted_days > 0:
        result.summary["개정 전 사건의 첫해 공제"] = f"{r.deducted_days:.1f}일 (2017-05-30 전 입사)"
    if r.is_part_time_ratio:
        result.summary["단시간 비례"] = f"×{r.part_time_ratio:.2f}"
    if r.fiscal_year_gap > 0:
        result.summary["퇴직 시 추가 지급"] = f"{r.fiscal_year_gap:.1f}일"
    return 0


def _pop_dismissal(r, result):
    """result.summary에 해고예고수당 추가. 반환: 0."""
    result.summary["해고예고수당"] = f"{r.dismissal_pay:,.0f}원"
    return 0


def _pop_comprehensive(r, result):
    """result.summary에 포괄임금 역산 시급·계수시간·최저임금 충족 추가. 반환: 0."""
    result.summary["포괄임금 역산 시급"] = f"{r.effective_hourly:,.0f}원"
    result.summary["총계수시간(월)"] = f"{fmt_hours(r.total_coefficient_hours)}h"
    result.summary["최저임금 충족"] = "✅" if r.is_minimum_wage_ok else "❌"
    result.minimum_wage_state = "compliant" if r.is_minimum_wage_ok else "violation"
    if not r.is_valid_comprehensive:
        result.summary["포괄임금 유효성"] = "⚠️ 문제 있음"
    result.minimum_wage_ok = r.is_minimum_wage_ok
    return 0


def _pop_prorated(r, result):
    """result.summary에 일할계산 임금·근무일수 추가. 반환: 0."""
    result.summary["일할계산 임금"] = f"{r.prorated_wage:,.0f}원"
    result.summary["근무 일수(역일)"] = f"{r.worked_days}일 / {r.total_days}일"
    return 0


def _pop_public_holiday(r, result):
    """result.summary에 유급공휴일 수당·적용여부 추가. 반환: holiday_pay/12 or 0(월 총액에는 더하지 않는다 — 월급에 이미 든 임금)."""
    result.summary["유급공휴일 수당"] = f"{r.total_holiday_pay:,.0f}원"
    result.summary["유급공휴일 적용"] = "✅" if r.eligible else "❌ 미적용"
    return (r.total_holiday_pay / 12) if r.eligible else 0


def _pop_average_wage(r, result):
    """result.summary에 1일 평균임금·적용기준·3개월 임금총액 추가. 반환: 0."""
    result.summary["1일 평균임금"] = f"{r.avg_daily_wage:,.0f}원/일"
    result.summary["적용 기준"] = f"{r.used_basis}"
    result.summary["3개월 임금총액"] = f"{r.grand_total:,.0f}원"
    result.summary["산정기간"] = f"{r.period_days}일"
    return 0


def _pop_severance(r, result):
    """result.summary에 퇴직금·평균임금·계속근로기간 추가. 반환: 0."""
    result.summary["퇴직금"] = f"{r.severance_pay:,.0f}원"
    result.summary["적용 평균임금"] = f"{r.avg_daily_wage:,.0f}원/일 ({r.used_basis} 기준)"
    result.summary["계속근로"] = f"{r.service_days}일 ({r.service_years:.2f}년)"
    return 0


def _pop_shutdown_allowance(r, result):
    """result.summary에 휴업수당 총액·적용기준·일수 추가. 반환: 0."""
    result.summary["휴업수당"] = f"{r.shutdown_allowance:,.0f}원"
    result.summary["적용 기준"] = "통상임금" if r.is_ordinary_wage_applied else "평균임금 70%"
    if r.is_partial_shutdown:
        result.summary["부분 휴업"] = f"비율 {r.partial_ratio:.0%}"
    return 0


def _pop_unemployment(r, result):
    """result.summary에 구직급여 일액·급여일수·총급여·조기재취업수당 추가. 반환: 0."""
    if r.is_eligible:
        result.summary["구직급여 일액"] = f"{r.daily_benefit:,.0f}원/일"
        result.summary["소정급여일수"]  = f"{r.benefit_days}일"
        result.summary["총 구직급여"]   = f"{r.total_benefit:,.0f}원"
        result.summary["조기재취업수당"] = f"{r.early_reemployment_bonus:,.0f}원 (최대)"
    else:
        result.summary["실업급여 수급"] = f"❌ 불가 — {r.ineligible_reason[:40]}..."
    return 0


def _pop_insurance(r, result):
    """result.summary에 세전급여·세후실수령액·공제액·4대보험합계 추가. 반환: 0."""
    result.monthly_net = r.monthly_net
    result.summary["세전 월 급여"] = f"{r.monthly_gross:,.0f}원"
    result.summary["세후 실수령액"] = f"{r.monthly_net:,.0f}원"
    result.summary["총 공제액"] = f"{r.total_deduction:,.0f}원"
    if not r.is_freelancer:
        result.summary["4대보험 합계"] = f"{r.total_insurance:,.0f}원"
    return 0


def _pop_employer_insurance(r, result):
    """result.summary에 사업주 4대보험 합계·총인건비 추가. 반환: 0."""
    result.summary["사업주 4대보험 합계"] = f"{r.total_employer_insurance:,.0f}원"
    result.summary["총 인건비(사업주)"] = f"{r.total_labor_cost:,.0f}원"
    return 0


def _pop_compensatory_leave(r, result):
    """result.summary에 보상휴가 시간·미사용수당(월) 추가. 반환: 0."""
    result.summary["보상휴가(주)"] = f"{r.compensatory_hours:.2f}h"
    result.summary["미사용 보상휴가 수당(월)"] = f"{r.monthly_unused_pay:,.0f}원"
    return 0


def _pop_parental_leave(r, result):
    """result.summary에 육아휴직 월수령액·총수령액·사후지급금 추가. 반환: 0."""
    result.summary["육아휴직 월 수령액"] = f"{r.monthly_benefit_actual:,.0f}원"
    result.summary["육아휴직 총 수령액"] = f"{r.total_benefit:,.0f}원"
    result.summary["사후지급금 합계"] = f"{r.total_deferred:,.0f}원"
    if r.has_bonus:
        result.summary["아빠 보너스(첫 3개월)"] = f"{r.monthly_bonus_benefit:,.0f}원/월"
    return 0


def _pop_maternity_leave(r, result):
    """result.summary에 출산전후휴가 급여·보험지급액·배우자휴가 추가. 반환: 0."""
    result.summary["출산전후휴가 월 급여"] = f"{r.monthly_benefit:,.0f}원"
    result.summary["고용보험 지급 총액"] = f"{r.total_insurance_benefit:,.0f}원"
    # 유급액(사업주 의무)과 고용보험 지원분은 다른 금액이다 — 하나로 뭉치면 대규모기업
    # 근로자에게 받지도 못할 보험 급여를 유급액으로 보여 주게 된다.
    result.summary[f"배우자 출산휴가 유급액({r.spouse_leave_days}일)"] = f"{r.spouse_leave_pay:,.0f}원"
    result.summary["배우자 출산휴가급여(고용보험)"] = (
        f"{r.spouse_insurance_benefit:,.0f}원 ({r.spouse_insurance_days}일분)"
        if r.spouse_insurance_days else "없음 (우선지원대상기업만 지원)")
    # 같은 고시가 정하는 휴가들 — 시행 전이면 표시하지 않는다(없는 제도를 안내하지 않기 위해).
    # 배우자 출산휴가와 같은 이유로 유급액·고용보험 지원분을 따로 보여 준다.
    for label, days, pay, benefit in (
            ("난임치료휴가", r.infertility_paid_days,
             r.infertility_pay, r.infertility_insurance_benefit),
            ("배우자 유산·사산휴가", r.spouse_miscarriage_paid_days,
             r.spouse_miscarriage_pay, r.spouse_miscarriage_insurance_benefit)):
        if not days:
            continue
        result.summary[f"{label} 유급액(유급 {days}일)"] = f"{pay:,.0f}원"
        result.summary[f"{label} 급여(고용보험)"] = (
            f"{benefit:,.0f}원" if r.is_priority_support else "없음 (우선지원대상기업만 지원)")
    return 0


def _pop_flexible_work(r, result):
    """result.summary에 탄력제 연장수당(월)·연장근로시간 추가. 반환: monthly_overtime_pay."""
    result.summary["탄력제 연장수당(월)"] = f"{r.monthly_overtime_pay:,.0f}원"
    result.summary["탄력제 연장근로시간"] = f"{r.overtime_hours:.1f}h/{r.unit_period}"
    return r.monthly_overtime_pay


def _pop_retirement_tax(r, result):
    """result.summary에 퇴직소득세·지방소득세·실수령퇴직금 추가. 반환: 0."""
    result.summary["퇴직소득세"] = f"{r.retirement_income_tax:,.0f}원"
    result.summary["지방소득세"] = f"{r.local_income_tax:,.0f}원"
    result.summary["실수령 퇴직금"] = f"{r.net_retirement_pay:,.0f}원"
    if r.irp_amount > 0:
        result.summary["IRP 이연세액"] = f"{r.deferred_tax:,.0f}원"
    return 0


def _pop_retirement_pension(r, result):
    """result.summary에 퇴직연금 유형·수령액·운용수익 추가. 반환: 0."""
    result.summary["퇴직연금 유형"] = f"{'확정급여형(DB)' if r.pension_type == 'DB' else '확정기여형(DC)'}"
    result.summary["퇴직연금 수령액"] = f"{r.total_pension:,.0f}원"
    if r.pension_type == "DC" and r.investment_return > 0:
        result.summary["운용수익"] = f"{r.investment_return:,.0f}원"
    return 0


def _pop_eitc(r, result):
    """result.summary에 근로장려금·자녀장려금·합계·소득구간 추가. 반환: 0."""
    if r.is_eligible:
        result.summary["근로장려금"] = f"{r.eitc_final:,.0f}원"
        if r.child_credit_total > 0:
            result.summary["자녀장려금"] = f"{r.child_credit_total:,.0f}원"
        result.summary["합계(EITC+자녀)"] = f"{r.total_credit:,.0f}원"
        result.summary["소득구간"] = r.income_zone
        if r.asset_reduction:
            result.summary["재산감액"] = "50% 감액 적용"
    else:
        result.summary["근로장려금"] = f"수급 불가 — {r.ineligible_reason[:50]}"
    return 0


def _pop_ordinary_wage(r, result):
    """result.summary에 통상시급·월 통상임금 추가. 반환: 0."""
    result.summary["통상시급"] = r.breakdown.get("통상시급", "계산 불가")
    result.summary["월 통상임금"] = r.breakdown.get("월 통상임금", "계산 불가")
    return 0


def _pop_working_hours(r, result):
    """result.summary에 월 소정근로시간·시급·월급 환산 추가. 반환: 0."""
    result.summary["월 소정근로시간"] = f"{fmt_hours(r.monthly_hours)}시간"
    if r.hourly_wage:
        result.summary["시급"] = f"{r.hourly_wage:,.0f}원"
    if r.monthly_wage:
        result.summary["월급 환산"] = f"{r.monthly_wage:,.0f}원"
    return 0


def _pop_industrial_accident(r, result):
    """result.summary에 평균임금·휴업/장해/유족/장례비·산재합계 추가. 반환: 0."""
    # 퇴직금 요약과 같은 키를 쓰면 함께 물었을 때 퇴직금 옆에 산재 값이 찍힌다(Act-3 리뷰 L2)
    result.summary["산재 적용 평균임금"] = f"{r.avg_daily_wage:,.0f}원/일"
    if r.sick_leave_total > 0:
        result.summary["휴업급여"] = f"{r.sick_leave_total:,.0f}원 ({r.sick_leave_days}일)"
    if r.illness_pension_annual > 0:
        result.summary["상병보상연금"] = f"{r.illness_pension_annual:,.0f}원/년"
    if r.disability_amount > 0:
        result.summary["장해급여"] = f"{r.disability_amount:,.0f}원 ({r.disability_type})"
    if r.survivor_amount > 0:
        result.summary["유족급여"] = f"{r.survivor_amount:,.0f}원 ({r.survivor_type})"
    if r.funeral_amount > 0:
        result.summary["장례비"] = f"{r.funeral_amount:,.0f}원"
    result.summary["산재보상금 합계"] = f"{r.total_compensation:,.0f}원"
    return 0
