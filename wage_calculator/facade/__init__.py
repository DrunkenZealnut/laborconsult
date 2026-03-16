"""
WageCalculator 통합 퍼사드

모든 임금 계산기를 하나의 인터페이스로 통합합니다.
chatbot.py에서 from wage_calculator.facade import WageCalculator 형태로 사용합니다.

Phase D 분리: registry.py (유형·매핑), helpers.py (_pop_*), conversion.py (입력 변환)
"""

from ..calculators.business_size import calc_business_size
from ..calculators.ordinary_wage import calc_ordinary_wage
from ..calculators.overtime import check_weekly_hours_compliance
from ..calculators.retirement_pension import calc_retirement_pension
from ..calculators.retirement_tax import calc_retirement_tax
from ..calculators.wage_arrears import calc_wage_arrears
from ..legal_hints import generate_legal_hints, format_hints, LegalHint
from ..models import WageInput, WageType, BusinessSize
from ..result import WageResult, format_result, format_result_json

from .conversion import _provided_info_to_input, _guess_start_date
from .helpers import _merge, _pop_retirement_tax, _pop_retirement_pension
from .registry import (
    CALC_TYPES, CALC_TYPE_MAP, _STANDARD_CALCS, resolve_calc_type,
)


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
        has_conditions = any(
            (a.get("condition") if isinstance(a, dict) else getattr(a, "condition", "없음")) != "없음"
            for a in inp.fixed_allowances
        )
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
        if any(
            (a.get("condition") if isinstance(a, dict) else getattr(a, "condition", "없음")) != "없음"
            for a in inp.fixed_allowances
        ):
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
