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

from .conversion import _guess_start_date
from .helpers import _merge, _pop_retirement_tax, _pop_retirement_pension
from .registry import (
    CALC_TYPES, CALC_TYPE_MAP, _STANDARD_CALCS, resolve_calc_type,
)


def _clamp_negative_inputs(inp: WageInput) -> None:
    """음수 임금/근로시간 입력을 0으로 보정 — 비현실적 결과·계산오류 방지."""
    for field in ("hourly_wage", "daily_wage", "monthly_wage", "annual_wage"):
        v = getattr(inp, field, None)
        if v is not None and v < 0:
            setattr(inp, field, 0.0)
    sch = getattr(inp, "schedule", None)
    if sch is not None:
        if getattr(sch, "daily_work_hours", 0) < 0:
            sch.daily_work_hours = 0.0
        if getattr(sch, "weekly_work_days", 0) < 0:
            sch.weekly_work_days = 0.0


class WageCalculator:
    """임금계산기 통합 퍼사드"""

    def __init__(self, rule_store=None):
        self.rule_store = rule_store

    def calculate(
        self, inp: WageInput, targets: list[str] | None = None,
    ) -> WageResult:
        from copy import deepcopy
        from ..legal_rules import (
            RuleSnapshot, RuleUnavailable, resolve_reference_date, rule_scope,
        )
        from app.core.legal_rule_store import rules_enabled, configured_store

        # A snapshot belongs to one call, not a process-global mutable constants table.
        if self.rule_store is None and not rules_enabled():
            with rule_scope(None):
                return self._calculate(inp, targets)
        reference_date = None
        try:
            # Resolve (and validate) before the store round trip: an unusable date
            # must not cost a query.
            reference_date = resolve_reference_date(inp.reference_date, inp.reference_year)
            store = self.rule_store if self.rule_store is not None else configured_store()
            _, document = store.load()
            snapshot = RuleSnapshot(document["records"], reference_date)
            managed_input = deepcopy(inp)
            managed_input.reference_year = snapshot.day.year
            # 해결된 기준일을 되돌려 넣는다 — 승인 기준이 없는 키는 내장표로 떨어지는데,
            # 그 내장표에도 연중 바뀌는 값(연금 기준소득월액)이 있어 날짜가 필요하다.
            managed_input.reference_date = snapshot.day.isoformat()
            if managed_input.use_minimum_wage:
                managed_input.wage_type = WageType.HOURLY
                managed_input.hourly_wage = snapshot.get("minimum_hourly_wage")
            with rule_scope(snapshot):
                result = self._calculate(managed_input, targets)
            # 시도한 계산이 **전부** 보류면 부분 결과가 아니라 보류다. 통상임금만 남은
            # 껍데기를 정상 결과로 내보내면 '계산 보류' 신호가 사라진다.
            if result.legal_rule_attempted and len(result.legal_rule_blocked) == result.legal_rule_attempted:
                raise RuleUnavailable(" / ".join(
                    item["reason"] for item in result.legal_rule_blocked))
            # 승인 기준이 한 건도 소비되지 않았으면 'managed'로 부르지 않는다 — 빈
            # provenance에 적용일만 붙으면 내장표 수치가 법적 검증을 받은 것처럼 읽힌다.
            result.legal_rule_versions = snapshot.provenance()
            result.legal_rule_status = ("managed_parameters" if result.legal_rule_versions
                                        else "managed_no_parameters")
            result.legal_reference_date = reference_date
            return result
        except RuleUnavailable as exc:
            reason = str(exc)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("관리 기준 계산 실패")
            reason = "법률 기준 저장소 또는 계산 검증에 실패했습니다. 관리자 확인이 필요합니다"
        return WageResult(minimum_wage_ok=None, legal_rule_status="blocked",
                          legal_reference_date=reference_date, warnings=[reason])

    def _calculate(
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
        _clamp_negative_inputs(inp)
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

        # 승인 기준 누락은 **그 섹션만** 제외한다. 기반 단계(통상임금·사업장 규모)는
        # 뒤따르는 모든 계산의 입력이라 여기서 감싸지 않는다 — 그쪽 실패는 요청 전체 보류다.
        from ..legal_rules import RuleUnavailable, used_scope
        blocked: list = []
        blocked_targets: set = set()

        def guarded(target, section, run):
            result.legal_rule_attempted += 1
            try:
                with used_scope():        # 보류된 섹션이 읽은 기준은 provenance에서 제외
                    return run()
            except RuleUnavailable as exc:
                blocked.append({"target": target, "section": section, "reason": str(exc)})
                blocked_targets.add(target)
                return None

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
            r = guarded(key, section, lambda: func(inp, ow))
            if r is None:
                continue
            if key == "severance":
                _severance_cache = r
            monthly_total += populate(r, result)
            _merge(result, section, r, all_w, all_l)

        # ── 특수 계산기: 임금체불 (독립 함수, WageInput 미사용) ───────────────
        if "wage_arrears" in targets and inp.arrear_amount > 0 and inp.arrear_due_date:
            wa = guarded("wage_arrears", "임금체불 지연이자", lambda: calc_wage_arrears(
                arrear_amount=inp.arrear_amount,
                arrear_due_date=inp.arrear_due_date,
                is_post_retirement_arrear=inp.is_post_retirement_arrear,
                arrear_calc_date=inp.arrear_calc_date or None,
            ))
            if wa is not None:
                result.summary["임금체불 지연이자"] = f"{wa.interest_amount:,.0f}원"
                result.summary["총 청구액"] = f"{wa.total_claim:,.0f}원"
                result.summary["지연일수"] = f"{wa.delay_days}일"
                _merge(result, "임금체불 지연이자", wa, all_w, all_l)

        # ── 특수 계산기: 주 52시간 체크 (ow 미사용) ──────────────────────────
        if "weekly_hours_check" in targets:
            wc = guarded("weekly_hours_check", "주 52시간 준수 체크",
                         lambda: check_weekly_hours_compliance(inp))
            if wc is not None:
                result.summary["주 총 근로시간"] = f"{wc.total_weekly_hours:.1f}h"
                result.summary["주 52시간 준수"] = ("✅ 준수" if wc.is_compliant
                                                else f"❌ {wc.excess_hours:.1f}h 초과")
                _merge(result, "주 52시간 준수 체크", wc, all_w, all_l)

        # ── 특수 계산기: 퇴직소득세·퇴직연금 (퇴직금 결과 참조) ─────────────
        # 퇴직금이 보류면 이 둘도 보류한다 — 자체 추정으로 채우면 없는 퇴직금에 대한
        # 세액·적립금이 산출돼 서로 어긋난 숫자가 한 답변에 실린다.
        for key, section, func, populate in (
            ("retirement_tax", "퇴직소득세", calc_retirement_tax, _pop_retirement_tax),
            ("retirement_pension", "퇴직연금(DB/DC)", calc_retirement_pension, _pop_retirement_pension),
        ):
            if key not in targets:
                continue
            if "severance" in blocked_targets:
                result.legal_rule_attempted += 1
                blocked.append({"target": key, "section": section,
                                "reason": "퇴직금 계산이 보류되어 함께 보류합니다"})
                blocked_targets.add(key)
                continue
            r = guarded(key, section, lambda f=func: f(inp, ow, _severance_cache))
            if r is None:
                continue
            populate(r, result)
            _merge(result, section, r, all_w, all_l)

        # ── 법률 힌트: 다른 계산 결과 참조 후 마지막에 실행 ──────────────────
        has_conditions = any(
            (a.get("condition") if isinstance(a, dict) else getattr(a, "condition", "없음")) != "없음"
            for a in inp.fixed_allowances
        )
        if {"minimum_wage", "comprehensive"} & blocked_targets:
            # 기본값 True 를 그대로 두면 '최저임금 충족 ✅'라는 없는 판정이 나간다.
            result.minimum_wage_ok = None
        if "legal_hints" in targets or has_conditions:
            # 판정 보류(None)를 falsy 로 넘기면 '미달' 힌트가 생긴다 — 모르는 것을
            # 위반으로 단정하게 되므로 보류일 때는 위반 힌트를 만들지 않는다.
            mw_ok = True if result.minimum_wage_ok is None else result.minimum_wage_ok
            hints = generate_legal_hints(inp, ow, mw_ok)
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
        result.legal_rule_blocked = blocked

        return result

    def _auto_detect_targets(self, inp: WageInput) -> list[str]:
        """입력 정보를 보고 필요한 계산 유형 자동 결정"""
        is_pw = getattr(inp, "is_platform_worker", False)

        targets = ["minimum_wage"]   # 항상 최저임금 검증

        # 상시근로자 수 산정 입력이 있으면 맨 앞에 삽입 (최우선 실행)
        if inp.business_size_input is not None:
            targets.insert(0, "business_size")

        # 특수고용직: 근로기준법상 근로자 아님 → overtime/weekly_holiday/annual_leave/
        #   dismissal/severance/comprehensive/prorated/public_holiday/shutdown 미적용
        if not is_pw:
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

        # 특수고용직: 법률 힌트 항상 포함 (노동3권, 산재, 프리랜서 구분 안내)
        if is_pw and "legal_hints" not in targets:
            targets.append("legal_hints")

        # 4대보험/소득세: 항상 자동 포함
        targets.append("insurance")

        # 신규 계산기 자동 감지
        if inp.parental_leave_months > 0:
            targets.append("parental_leave")

        # 출산전후휴가: 다태아 등 출산 관련 입력이 명시되면 자동 포함
        # (단태아 일반 케이스는 파이프라인의 '출산휴가' 라벨 명시 라우팅으로 처리)
        if getattr(inp, "is_multiple_birth", False) or getattr(inp, "is_premature_birth", False):
            targets.append("maternity_leave")

        if inp.arrear_amount > 0 and inp.arrear_due_date:
            targets.append("wage_arrears")

        if getattr(inp, "flexible_work_unit", ""):
            targets.append("flexible_work")

        if getattr(inp, "annual_total_income", 0) > 0 or getattr(inp, "household_type", ""):
            targets.append("eitc")

        # 퇴직소득세: 퇴직금 계산이 포함되면 자동 추가, 또는 직접 지정 시
        if not is_pw and ("severance" in targets or inp.retirement_pay_amount > 0):
            targets.append("retirement_tax")

        # 퇴직연금: pension_type 지정 시 자동 추가
        if not is_pw and inp.pension_type:
            targets.append("retirement_pension")

        # 산재보상금: 산재 관련 필드 존재 시 자동 감지 (특수고용직도 해당)
        if inp.sick_leave_days > 0 or inp.disability_grade > 0 or inp.is_deceased:
            targets.append("industrial_accident")
            if "average_wage" not in targets:
                targets.append("average_wage")

        # 연장근로 있으면 주 52시간 체크도 자동 포함 (근기법 대상만)
        if not is_pw:
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
