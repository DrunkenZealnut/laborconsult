"""
디스패처 헬퍼 — 계산기 결과 병합 및 summary populate 함수

facade.py 에서 분리 (Phase D)
"""


def _merge(result, section, calc_result, all_warnings, all_legal):
    """계산기 결과를 WageResult에 병합 (공통 필드)"""
    result.breakdown[section] = calc_result.breakdown
    if hasattr(calc_result, "formulas"):
        result.formulas.extend(calc_result.formulas)
    all_warnings.extend(calc_result.warnings)
    all_legal.extend(calc_result.legal_basis)


# ── populate 함수: 각 계산기의 summary/특수필드 설정 ──────────────────────────
# 반환값 = monthly_total에 더할 금액 (0이면 미반영)


def _pop_overtime(r, result):
    """result.summary에 연장/야간/휴일수당(월) 추가. 반환: monthly_overtime_pay."""
    result.summary["연장/야간/휴일수당(월)"] = f"{r.monthly_overtime_pay:,.0f}원"
    return r.monthly_overtime_pay


def _pop_minimum_wage(r, result):
    """result.summary에 최저임금 충족 여부·실질시급·부족분 추가. 반환: 0."""
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
    """result.summary에 연차수당·미사용일수·차감·비례·정산 추가. 반환: 0."""
    result.summary["연차수당"] = f"{r.annual_leave_pay:,.0f}원"
    result.summary["미사용 연차"] = f"{r.remaining_days:.1f}일"
    if r.deducted_days > 0:
        result.summary["2년차 차감"] = f"{r.deducted_days:.1f}일 (제60조③)"
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
    result.summary["총계수시간(월)"] = f"{r.total_coefficient_hours:.1f}h"
    result.summary["최저임금 충족"] = "✅" if r.is_minimum_wage_ok else "❌"
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
    """result.summary에 유급공휴일 수당·적용여부 추가. 반환: holiday_pay/12 or 0."""
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
    result.summary["배우자 출산휴가 급여"] = f"{r.spouse_leave_pay:,.0f}원"
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


def _pop_industrial_accident(r, result):
    """result.summary에 평균임금·휴업/장해/유족/장례비·산재합계 추가. 반환: 0."""
    result.summary["적용 평균임금"] = f"{r.avg_daily_wage:,.0f}원/일"
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
