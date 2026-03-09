"""
WageCalculator 통합 퍼사드

모든 임금 계산기를 하나의 인터페이스로 통합합니다.
chatbot.py에서 from wage_calculator.facade import WageCalculator 형태로 사용합니다.
"""

from .calculators.annual_leave import calc_annual_leave
from .calculators.average_wage import calc_average_wage
from .calculators.business_size import calc_business_size
from .calculators.compensatory_leave import calc_compensatory_leave
from .calculators.comprehensive import calc_comprehensive
from .calculators.dismissal import calc_dismissal
from .calculators.eitc import calc_eitc
from .calculators.flexible_work import calc_flexible_work
from .calculators.industrial_accident import calc_industrial_accident
from .calculators.insurance import calc_insurance, calc_employer_insurance
from .calculators.maternity_leave import calc_maternity_leave
from .calculators.minimum_wage import calc_minimum_wage
from .calculators.ordinary_wage import calc_ordinary_wage
from .calculators.overtime import calc_overtime, check_weekly_hours_compliance
from .calculators.parental_leave import calc_parental_leave
from .calculators.prorated import calc_prorated
from .calculators.public_holiday import calc_public_holiday
from .calculators.retirement_pension import calc_retirement_pension
from .calculators.retirement_tax import calc_retirement_tax
from .calculators.severance import calc_severance
from .calculators.shutdown_allowance import calc_shutdown_allowance
from .calculators.unemployment import calc_unemployment
from .calculators.wage_arrears import calc_wage_arrears
from .calculators.weekly_holiday import calc_weekly_holiday
from .legal_hints import generate_legal_hints, format_hints, LegalHint
from .models import WageInput, WageType, BusinessSize
from .result import WageResult, format_result, format_result_json

# 지원 계산 유형
CALC_TYPES = {
    "overtime":            "연장/야간/휴일 수당",
    "minimum_wage":        "최저임금 검증",
    "weekly_holiday":      "주휴수당",
    "annual_leave":        "연차수당",
    "dismissal":           "해고예고수당",
    "comprehensive":       "포괄임금제 역산",
    "prorated":            "중도입사 일할계산",
    "public_holiday":      "유급 공휴일",
    "insurance":           "4대보험·소득세 (세전/세후, 근로자)",
    "employer_insurance":  "사업주 4대보험 부담금",
    "severance":           "퇴직금",
    "unemployment":        "실업급여(구직급여)",
    "compensatory_leave":  "보상휴가 환산",
    "wage_arrears":        "임금체불 지연이자",
    "parental_leave":      "육아휴직급여",
    "maternity_leave":     "출산전후휴가급여",
    "flexible_work":       "탄력적 근로시간제 연장수당",
    "weekly_hours_check":  "주 52시간 준수 여부 체크",
    "legal_hints":         "법률 판단 힌트",
    "business_size":       "상시근로자 수 판정",
    "eitc":                "근로장려금(EITC) 수급 판정 + 금액",
    "retirement_tax":      "퇴직소득세",
    "retirement_pension":  "퇴직연금(DB/DC)",
    "average_wage":        "평균임금",
    "shutdown_allowance":  "휴업수당(근기법 제46조)",
    "industrial_accident": "산재보상금(휴업·장해·유족·장례비)",
}

# calculation_type 필드 → 계산기 매핑 (analyze_qna.py 분류값 기준)
CALC_TYPE_MAP = {
    "연장수당":    ["overtime", "minimum_wage"],
    "최저임금":    ["minimum_wage"],
    "주휴수당":    ["weekly_holiday", "minimum_wage"],
    "연차수당":    ["annual_leave"],
    "해고예고수당": ["dismissal"],
    "퇴직금":     ["severance", "minimum_wage"],
    "실업급여":   ["unemployment"],
    "임금계산":   ["overtime", "minimum_wage", "weekly_holiday"],
    "해당없음":   ["minimum_wage"],
    "육아휴직":   ["parental_leave"],
    "출산휴가":   ["maternity_leave"],
    "임금체불":   ["wage_arrears"],
    "보상휴가":   ["compensatory_leave", "overtime"],
    "탄력근무":   ["flexible_work"],
    "사업장규모": ["business_size"],
    "근로장려금": ["eitc"],
    "근로장려세제": ["eitc"],
    "EITC":       ["eitc"],
    "퇴직소득세":  ["severance", "retirement_tax"],
    "퇴직연금":    ["retirement_pension"],
    "퇴직":       ["severance", "retirement_tax"],
    "평균임금":   ["average_wage"],
    "산재보상":   ["industrial_accident", "average_wage"],
    "휴업급여":   ["industrial_accident", "average_wage"],
    "장해급여":   ["industrial_accident", "average_wage"],
    "유족급여":   ["industrial_accident", "average_wage"],
    "장례비":     ["industrial_accident", "average_wage"],
    "산재":       ["industrial_accident", "average_wage"],
    "휴업수당":   ["shutdown_allowance"],
}


# ── 디스패처 헬퍼 ──────────────────────────────────────────────────────────


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
    # 주휴시간은 이미 base_hours에 포함되어 monthly_total에 반영됨 → 이중 가산 방지
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
    return 0  # 연간 환급형 → monthly_total에 미반영


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
    return 0  # 산재보상금은 월급에 합산하지 않음


# ── 디스패처 레지스트리 ──────────────────────────────────────────────────────
# (key, func, section_name, populate_fn, precondition)
# precondition: None이면 targets에 key가 있으면 무조건 실행

_STANDARD_CALCS = [
    ("overtime",           calc_overtime,           "연장·야간·휴일수당",     _pop_overtime,           None),
    ("minimum_wage",       calc_minimum_wage,       "최저임금 검증",         _pop_minimum_wage,       None),
    ("weekly_holiday",     calc_weekly_holiday,      "주휴수당",             _pop_weekly_holiday,     None),
    ("annual_leave",       calc_annual_leave,        "연차수당",             _pop_annual_leave,       None),
    ("dismissal",          calc_dismissal,           "해고예고수당",         _pop_dismissal,          None),
    ("comprehensive",      calc_comprehensive,       "포괄임금제 역산",      _pop_comprehensive,
     lambda inp: inp.wage_type == WageType.COMPREHENSIVE),
    ("prorated",           calc_prorated,            "중도입사 일할계산",    _pop_prorated,
     lambda inp: inp.join_date),
    ("public_holiday",     calc_public_holiday,      "유급 공휴일",          _pop_public_holiday,
     lambda inp: inp.public_holiday_days > 0),
    ("average_wage",       calc_average_wage,        "평균임금",             _pop_average_wage,       None),
    ("severance",          calc_severance,           "퇴직금",              _pop_severance,          None),
    ("shutdown_allowance", calc_shutdown_allowance,   "휴업수당",            _pop_shutdown_allowance,
     lambda inp: inp.shutdown_days > 0),
    ("unemployment",       calc_unemployment,        "실업급여(구직급여)",    _pop_unemployment,       None),
    ("insurance",          calc_insurance,           "4대보험·소득세",       _pop_insurance,          None),
    ("employer_insurance", calc_employer_insurance,  "사업주 4대보험 부담금", _pop_employer_insurance,  None),
    ("compensatory_leave", calc_compensatory_leave,  "보상휴가 환산",        _pop_compensatory_leave,  None),
    ("parental_leave",     calc_parental_leave,      "육아휴직급여",         _pop_parental_leave,      None),
    ("maternity_leave",    calc_maternity_leave,     "출산전후휴가급여",     _pop_maternity_leave,     None),
    ("flexible_work",      calc_flexible_work,       "탄력적 근로시간제",    _pop_flexible_work,
     lambda inp: getattr(inp, "flexible_work_unit", "")),
    ("eitc",               calc_eitc,                "근로장려금(EITC)",     _pop_eitc,               None),
    ("industrial_accident", calc_industrial_accident, "산재보상금",           _pop_industrial_accident, None),
]


class WageCalculator:
    """임금계산기 통합 퍼사드"""

    def calculate(
        self,
        inp: WageInput,
        targets: list[str] | None = None,
    ) -> WageResult:
        """
        지정된 계산 유형에 대해 통합 계산 수행

        Args:
            inp: 임금 입력 데이터
            targets: 계산할 유형 목록 (None이면 자동 결정)

        Returns:
            WageResult: 통합 계산 결과
        """
        if targets is None:
            targets = self._auto_detect_targets(inp)

        # 통상임금 계산 (모든 계산의 기반)
        ow = calc_ordinary_wage(inp)

        result = WageResult(ordinary_hourly=ow.hourly_ordinary_wage)
        result.formulas.append(f"[기준시간] {ow.base_hours_detail}")
        result.formulas.append(f"[통상임금] {ow.formula}")
        result.breakdown["통상임금"] = {
            "통상시급": f"{ow.hourly_ordinary_wage:,.0f}원",
            "1일 통상임금": f"{ow.daily_ordinary_wage:,.0f}원",
            "월 통상임금": f"{ow.monthly_ordinary_wage:,.0f}원",
            "기준시간": f"{ow.monthly_base_hours}h",
            "기준시간 산출": ow.base_hours_detail,
        }

        monthly_total = ow.monthly_ordinary_wage
        all_w, all_l = [], ["근로기준법 (통상임금)"]

        # ── 상시근로자 수 판정 (다른 계산기보다 먼저 실행) ────────────────────
        if "business_size" in targets and inp.business_size_input is not None:
            bs = calc_business_size(inp.business_size_input)
            inp.business_size = bs.business_size
            result.summary["상시근로자 수"] = f"{bs.regular_worker_count:.1f}명"
            result.summary["사업장 규모"] = bs.business_size.value
            result.summary["법 적용 여부"] = "적용" if bs.is_law_applicable else "미적용"
            _merge(result, "상시근로자 수 판정", bs, all_w, all_l)

        # ── 표준 계산기 디스패처 ─────────────────────────────────────────────
        _severance_cache = None
        for key, func, section, populate, precondition in _STANDARD_CALCS:
            if key not in targets:
                continue
            if precondition and not precondition(inp):
                continue
            r = func(inp, ow)
            if key == "severance":
                _severance_cache = r
            monthly_total += populate(r, result)
            _merge(result, section, r, all_w, all_l)

        # ── 특수 계산기: 임금체불 (독립 함수, WageInput 미사용) ───────────────
        if "wage_arrears" in targets and inp.arrear_amount > 0 and inp.arrear_due_date:
            wa = calc_wage_arrears(
                arrear_amount=inp.arrear_amount,
                arrear_due_date=inp.arrear_due_date,
                is_post_retirement_arrear=inp.is_post_retirement_arrear,
                arrear_calc_date=inp.arrear_calc_date or None,
            )
            result.summary["임금체불 지연이자"] = f"{wa.interest_amount:,.0f}원"
            result.summary["총 청구액"] = f"{wa.total_claim:,.0f}원"
            result.summary["지연일수"] = f"{wa.delay_days}일"
            _merge(result, "임금체불 지연이자", wa, all_w, all_l)

        # ── 특수 계산기: 주 52시간 체크 (ow 미사용) ──────────────────────────
        if "weekly_hours_check" in targets:
            wc = check_weekly_hours_compliance(inp)
            result.summary["주 총 근로시간"] = f"{wc.total_weekly_hours:.1f}h"
            result.summary["주 52시간 준수"] = "✅ 준수" if wc.is_compliant else f"❌ {wc.excess_hours:.1f}h 초과"
            _merge(result, "주 52시간 준수 체크", wc, all_w, all_l)

        # ── 특수 계산기: 퇴직소득세 (퇴직금 결과 참조) ─────────────────────
        if "retirement_tax" in targets:
            rt = calc_retirement_tax(inp, ow, _severance_cache)
            _pop_retirement_tax(rt, result)
            _merge(result, "퇴직소득세", rt, all_w, all_l)

        # ── 특수 계산기: 퇴직연금 (퇴직금 결과 참조) ─────────────────────
        if "retirement_pension" in targets:
            rp = calc_retirement_pension(inp, ow, _severance_cache)
            _pop_retirement_pension(rp, result)
            _merge(result, "퇴직연금(DB/DC)", rp, all_w, all_l)

        # ── 법률 힌트: 다른 계산 결과 참조 후 마지막에 실행 ──────────────────
        has_conditions = any(a.get("condition") for a in inp.fixed_allowances)
        if "legal_hints" in targets or has_conditions:
            hints = generate_legal_hints(inp, ow, result.minimum_wage_ok)
            if hints:
                result.breakdown["법률 검토 포인트"] = {
                    f"[{h.category}] #{i}": h.hint
                    for i, h in enumerate(hints, 1)
                }
                hint_text = format_hints(hints)
                if hint_text:
                    all_w.append(hint_text)

        result.monthly_total = round(monthly_total, 0)
        result.warnings = list(dict.fromkeys(all_w))
        result.legal_basis = list(dict.fromkeys(all_l))

        return result

    def from_analysis(self, calculation_type: str, provided_info: dict) -> "WageResult | None":
        """
        analyze_qna.py 분석 결과(calculation_type, provided_info)에서 자동 계산

        Args:
            calculation_type: "연장수당", "최저임금", "주휴수당" 등
            provided_info: {"임금형태": "시급", "임금액": "10030", ...}

        Returns:
            WageResult 또는 None (정보 불충분 시)
        """
        inp = _provided_info_to_input(provided_info)
        if inp is None:
            return None

        targets = CALC_TYPE_MAP.get(calculation_type, ["minimum_wage"])
        return self.calculate(inp, targets)

    def _auto_detect_targets(self, inp: WageInput) -> list[str]:
        """입력 정보를 보고 필요한 계산 유형 자동 결정"""
        targets = ["minimum_wage"]   # 항상 최저임금 검증

        # 상시근로자 수 산정 입력이 있으면 맨 앞에 삽입 (최우선 실행)
        if inp.business_size_input is not None:
            targets.insert(0, "business_size")

        if inp.wage_type == WageType.COMPREHENSIVE:
            targets.append("comprehensive")

        s = inp.schedule
        if s.weekly_overtime_hours > 0 or s.weekly_night_hours > 0 or s.weekly_holiday_hours > 0:
            targets.append("overtime")

        if s.weekly_work_days > 0:
            targets.append("weekly_holiday")

        if inp.start_date:
            targets.append("annual_leave")
            targets.append("severance")

        if inp.notice_days_given >= 0 and inp.dismissal_date:
            targets.append("dismissal")

        if inp.shutdown_days > 0:
            targets.append("shutdown_allowance")

        if inp.join_date:
            targets.append("prorated")

        if inp.public_holiday_days > 0:
            targets.append("public_holiday")

        # 조건부 수당이 있으면 자동으로 법률 힌트 생성
        if any(a.get("condition") for a in inp.fixed_allowances):
            targets.append("legal_hints")

        # 4대보험/소득세: 항상 자동 포함
        targets.append("insurance")

        # 신규 계산기 자동 감지
        if inp.parental_leave_months > 0:
            targets.append("parental_leave")

        if getattr(inp, "is_multiple_birth", False) or not getattr(inp, "is_priority_support_company", True) is None:
            pass

        if inp.arrear_amount > 0 and inp.arrear_due_date:
            targets.append("wage_arrears")

        if getattr(inp, "flexible_work_unit", ""):
            targets.append("flexible_work")

        if getattr(inp, "annual_total_income", 0) > 0 or getattr(inp, "household_type", ""):
            targets.append("eitc")

        # 퇴직소득세: 퇴직금 계산이 포함되면 자동 추가, 또는 직접 지정 시
        if "severance" in targets or inp.retirement_pay_amount > 0:
            targets.append("retirement_tax")

        # 퇴직연금: pension_type 지정 시 자동 추가
        if inp.pension_type:
            targets.append("retirement_pension")

        # 산재보상금: 산재 관련 필드 존재 시 자동 감지
        if inp.sick_leave_days > 0 or inp.disability_grade > 0 or inp.is_deceased:
            targets.append("industrial_accident")
            if "average_wage" not in targets:
                targets.append("average_wage")

        # 연장근로 있으면 주 52시간 체크도 자동 포함
        s = inp.schedule
        total_weekly = (s.daily_work_hours * s.weekly_work_days
                        + s.weekly_overtime_hours
                        + s.weekly_holiday_hours + s.weekly_holiday_overtime_hours)
        if total_weekly > 40:
            targets.append("weekly_hours_check")

        return targets

    def describe(self) -> str:
        """지원 계산 유형 설명"""
        lines = ["지원 계산 유형:"]
        for key, desc in CALC_TYPES.items():
            lines.append(f"  - {key}: {desc}")
        return "\n".join(lines)


def _provided_info_to_input(info: dict) -> "WageInput | None":
    """provided_info dict → WageInput 변환"""
    wage_type_map = {
        "시급": WageType.HOURLY,
        "일급": WageType.DAILY,
        "월급": WageType.MONTHLY,
        "연봉": WageType.ANNUAL,
        "포괄임금": WageType.COMPREHENSIVE,
        "포괄임금제": WageType.COMPREHENSIVE,
    }

    임금형태 = info.get("임금형태", "")
    wage_type = wage_type_map.get(임금형태, WageType.MONTHLY)

    # 임금액 파싱
    임금액_str = info.get("임금액", "") or ""
    임금액 = None
    try:
        cleaned = 임금액_str.replace(",", "").replace("원", "").replace(" ", "")
        if cleaned:
            임금액 = float(cleaned)
    except (ValueError, AttributeError):
        pass

    if 임금액 is None:
        return None   # 임금액 없으면 계산 불가

    # 사업장 규모
    size_str = info.get("사업장규모", "") or ""
    if "5인 미만" in size_str or "5인미만" in size_str:
        biz_size = BusinessSize.UNDER_5
    else:
        biz_size = BusinessSize.OVER_5

    inp = WageInput(
        wage_type=wage_type,
        business_size=biz_size,
    )

    if wage_type == WageType.HOURLY:
        inp.hourly_wage = 임금액
    elif wage_type == WageType.DAILY:
        inp.daily_wage = 임금액
    elif wage_type in (WageType.MONTHLY, WageType.COMPREHENSIVE):
        inp.monthly_wage = 임금액
    elif wage_type == WageType.ANNUAL:
        inp.annual_wage = 임금액

    # 재직기간
    근무기간 = info.get("근무기간", "") or ""
    if 근무기간:
        inp.start_date = _guess_start_date(근무기간)

    return inp


def _guess_start_date(period_str: str) -> str | None:
    """'2년', '1년 6개월' 등 문자열에서 시작일 추정"""
    import re
    from datetime import date, timedelta

    today = date.today()
    years = re.search(r"(\d+)\s*년", period_str)
    months = re.search(r"(\d+)\s*개월", period_str)

    total_days = 0
    if years:
        total_days += int(years.group(1)) * 365
    if months:
        total_days += int(months.group(1)) * 30

    if total_days > 0:
        start = today - timedelta(days=total_days)
        return start.isoformat()
    return None
