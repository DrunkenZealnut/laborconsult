"""
WageCalculator 통합 퍼사드

모든 임금 계산기를 하나의 인터페이스로 통합합니다.
chatbot.py에서 from wage_calculator.facade import WageCalculator 형태로 사용합니다.

Phase D 분리: registry.py (유형·매핑), helpers.py (_pop_*), conversion.py (입력 변환)
"""

from ..calculators.business_size import calc_business_size
from ..calculators.ordinary_wage import calc_ordinary_wage
from ..calculators.shared import apply_hour_split, fixed_overtime_monthly, monthly_wage_total
from ..calculators.overtime import check_weekly_hours_compliance
from ..calculators.retirement_pension import calc_retirement_pension
from ..calculators.retirement_tax import calc_retirement_tax
from ..calculators.wage_arrears import calc_wage_arrears
from ..legal_hints import generate_legal_hints, format_hints, LegalHint
from ..models import WageInput, WageType, BusinessSize
from ..result import WageResult, format_result, format_result_json
from ..utils import fmt_hours

from .conversion import _guess_start_date
from .helpers import _merge, _merge_amount_held, _pop_retirement_tax, _pop_retirement_pension
from .registry import (
    CALC_TYPES, CALC_TYPE_MAP, _STANDARD_CALCS, resolve_calc_type,
)


def _clamp_negative_inputs(inp: WageInput) -> None:
    """음수 임금/근로시간 입력을 0으로 보정 — 비현실적 결과·계산오류 방지."""
    for field in ("hourly_wage", "daily_wage", "monthly_wage", "annual_wage", "monthly_total_pay"):
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
        self, inp: WageInput, targets: list[str] | None = None, *, amount_hold=(), hold_compliant=(), auxiliary=(),
    ) -> WageResult:
        """amount_hold: 계산은 하되 금액만 빼고 실을 계산 유형(통상임금이 총액이라 금액이 부풀려지는 경우 — pipeline이 넘긴다).
        hold_compliant: 계산은 하되 '충족' 판정이면 싣지 않을 판정 유형(현재 minimum_wage — 수당이 섞인 총액은 시급을
        부풀리기만 하므로 미달만 확정이다).
        auxiliary: 묻지 않았지만 호출자가 카드 금액을 맞추려고 더한 계산 유형(pipeline의 연장수당 — 파생 연장·G2). '시도한
        계산이 전부 보류면 요청 보류' 판정에서 세지 않는다 — 세면 물은 계산이 전부 보류돼도 더한 섹션이 성공해 보류 신호가
        사라지고 세전 총액과 '이 수치를 사용하세요'가 나갔다(calc-card-consistency 독립 리뷰 M2)."""
        from copy import deepcopy
        from ..legal_rules import (
            RuleSnapshot, RuleUnavailable, resolve_reference_date, rule_scope,
        )
        from app.core.legal_rule_store import rules_enabled, configured_store

        # A snapshot belongs to one call, not a process-global mutable constants table.
        if self.rule_store is None and not rules_enabled():
            with rule_scope(None):
                return self._calculate(inp, targets, amount_hold, hold_compliant, auxiliary)
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
                result = self._calculate(managed_input, targets, amount_hold, hold_compliant, auxiliary)
            # 시도한 계산이 **전부** 보류면 부분 결과가 아니라 보류다. 통상임금만 남은
            # 껍데기를 정상 결과로 내보내면 '계산 보류' 신호가 사라진다. 호출자가 더한 섹션(auxiliary)은 세지 않는다.
            asked_blocked = [b for b in result.legal_rule_blocked if b["target"] not in auxiliary]
            if result.legal_rule_attempted and len(asked_blocked) == result.legal_rule_attempted:
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
        amount_hold=(),
        hold_compliant=(),
        auxiliary=(),
    ) -> WageResult:
        """
        지정된 계산 유형에 대해 통합 계산 수행

        Args:
            inp: 임금 입력 데이터
            targets: 계산할 유형 목록 (None이면 자동 결정)

        Returns:
            WageResult: 통합 계산 결과
        """
        # 아직 나누지 않은 입력(CLI·직접 호출)은 사본에서 계산한다 — 호출자의 일정을 바꾸지 않고, 같은 입력을 일정만 고쳐 다시 넘기면
        # 새로 나눈다(apply_hour_split은 이미 나눈 입력을 그대로 돌려준다, CodeRabbit PR #115). 파이프라인처럼 먼저 나눈 입력은 그대로 쓴다
        if inp.hour_split is None:
            from copy import deepcopy
            inp = deepcopy(inp)
        _clamp_negative_inputs(inp)
        # 1일 8시간·1주 40시간을 넘는 시간은 연장근로로 나눈다(calc-card-followups D9). 파이프라인이 먼저 나눴으면 그대로다 —
        # 모든 계산기가 정규화된 같은 일정을 읽는다. 자동 대상 결정(연장 유무)보다 앞이어야 한다
        apply_hour_split(inp)
        if targets is None:
            targets = self._auto_detect_targets(inp)
        # 초기 CLI·골든 소비자가 쓰던 이름도 실제 독립 계산기로 연결한다.
        targets = ["ordinary_wage" if target == "ordinary" else target for target in targets]

        # 지급 주기가 불명확한 수당을 월액으로 확정하지 않는다. 임금 기반과
        # 무관한 명시 체불 원금 이자·시간 계산은 그대로 실행할 수 있다.
        from ..calculators.shared import normalize_allowances
        from ..calculators.pay_inputs import PayInputError
        try:
            for allowance in normalize_allowances(inp.fixed_allowances):
                allowance.monthly_amount
        except PayInputError as exc:
            from dataclasses import replace
            independent = {"wage_arrears", "working_hours", "weekly_hours_check", "business_size"}
            remaining = [t for t in targets if t in independent]
            result = (self._calculate(replace(inp, fixed_allowances=[]), remaining)
                      if remaining else WageResult(minimum_wage_ok=None))
            result.calculation_skipped.extend({"target": t, "section": CALC_TYPES.get(t,t), "reason": str(exc)}
                                              for t in targets if t not in independent)
            result.monthly_total = result.monthly_net = result.ordinary_hourly = 0.0
            result.warnings.append(str(exc))
            result.calculation_status = "partial" if result.calculation_executed else "not_run"
            return result

        # 통상임금 계산 (모든 계산의 기반)
        ow = calc_ordinary_wage(inp)

        result = WageResult(ordinary_hourly=ow.hourly_ordinary_wage)
        result.formulas.append(f"[기준시간] {ow.base_hours_detail}")
        result.formulas.append(f"[통상임금] {ow.formula}")
        result.breakdown["통상임금"] = {
            "통상시급": f"{ow.hourly_ordinary_wage:,.0f}원",
            "1일 통상임금": f"{ow.daily_ordinary_wage:,.0f}원",
            "월 통상임금": f"{ow.monthly_ordinary_wage:,.0f}원",
            "기준시간": f"{fmt_hours(ow.monthly_base_hours)}h",
            "기준시간 산출": ow.base_hours_detail,
        }

        # 월 총액은 기준 월액(shared.monthly_wage_total)이다 — 보험 세전·평균임금과 같은 함수. 예전에는 여기서 섹션 금액을 따로
        # 더해 포괄임금 명세 총액이 기본급으로 나오고 공휴일 수당 ÷ 12가 월급에 이중으로 들어갔다(monthly-base-unification)
        flexible_added = 0.0
        all_w, all_l = [], ["근로기준법 (통상임금)"]

        # 승인 기준 누락은 **그 섹션만** 제외한다. 기반 단계(통상임금·사업장 규모)는
        # 뒤따르는 모든 계산의 입력이라 여기서 감싸지 않는다 — 그쪽 실패는 요청 전체 보류다.
        from ..legal_rules import RuleUnavailable, forget_used_since, used_mark, used_scope
        blocked: list = []
        blocked_targets: set = set()

        def guarded(target, section, run):
            if target not in auxiliary:
                result.legal_rule_attempted += 1
            try:
                with used_scope():        # 보류된 섹션이 읽은 기준은 provenance에서 제외
                    value = run()
                    if getattr(value, "held_reason", ""):
                        result.calculation_skipped.append({
                            "target": target, "section": section, "reason": value.held_reason})
                        blocked_targets.add(target)
                        return None
                    result.calculation_executed.append(target)
                    return value
            except RuleUnavailable as exc:
                blocked.append({"target": target, "section": section, "reason": str(exc)})
                blocked_targets.add(target)
                return None

        # ── 상시근로자 수 판정 (다른 계산기보다 먼저 실행) ────────────────────
        if "business_size" in targets and inp.business_size_input is not None:
            bs = calc_business_size(inp.business_size_input)
            result.calculation_executed.append("business_size")
            inp.business_size = bs.business_size
            result.summary["상시근로자 수"] = f"{bs.regular_worker_count:.1f}명"
            result.summary["사업장 규모"] = bs.business_size.value
            result.summary["법 적용 여부"] = "적용" if bs.is_law_applicable else "미적용"
            _merge(result, "상시근로자 수 판정", bs, all_w, all_l)

        # ── 표준 계산기 디스패처 ─────────────────────────────────────────────
        _severance_cache = None
        overtime_monthly = 0.0
        for key, func, section, populate, precondition in _STANDARD_CALCS:
            if key not in targets:
                continue
            if precondition and not precondition(inp):
                continue
            if key == "maternity_leave" and inp.maternity_leave_type:
                from ..calculators.family_leave import FAMILY_LABELS
                section = FAMILY_LABELS.get(inp.maternity_leave_type, section)
            mark = used_mark()
            r = guarded(key, section, lambda: func(inp, ow))
            if r is None:
                continue
            if key == "severance":
                _severance_cache = r
            # 금액 보류 대상은 금액만 빼고 싣는다(자격 판정으로 0이면 그대로 — 미발생·면제는 통상임금과 무관하다).
            # 버린 금액이 읽은 승인 기준은 적용 버전으로 보고하지 않는다.
            if key in amount_hold and _merge_amount_held(result, key, section, r, populate, all_w, all_l):
                forget_used_since(mark)
                continue
            # 믿을 수 없는 '충족'은 싣지 않는다 — 판정은 None(보류)으로 남고, 읽은 승인 기준도 적용 버전으로 보고하지 않는다
            if key in hold_compliant and getattr(r, "is_compliant", False):
                forget_used_since(mark)
                result.minimum_wage_state = "held"
                continue
            added = populate(r, result)
            if key == "overtime":
                overtime_monthly = added
            elif key == "flexible_work":
                flexible_added = added   # 탄력적 근로시간제의 연장 근로 임금 — 기준 월액의 연장 등과 따로 계산한다
            _merge(result, section, r, all_w, all_l)

        # 월 총액 = 기준 월액(연장 등은 연장수당 섹션을 계산한 카드만) + 탄력적 근로시간제 연장 임금. 공휴일 수당 ÷ 12는 더하지 않는다 —
        # 월급제는 공휴일 임금이 월급에 들어 있고(이중 계산), 시급제는 질문의 공휴일 일수를 12로 나눈 값이라 월 임금이 아니다
        monthly_total = monthly_wage_total(inp, ow, premium=overtime_monthly > 0.5) + flexible_added

        # 고정연장수당(통상임금에서 빼고 월 총액에 넣은 고정수당)과 계산한 연장·야간·휴일 근로 임금은 같은 근로의 대가다 — 둘 다
        # 더하면 같은 근로를 두 번 센다(독립 리뷰 M2). 금액은 monthly_wage_total이 큰 쪽만 센다 — 여기서는 그 사실을 알린다
        fixed_ot = fixed_overtime_monthly(inp) if overtime_monthly > 0.5 else 0.0
        if fixed_ot:
            gap = (f" 계산한 금액이 고정연장수당보다 월 {overtime_monthly - fixed_ot:,.0f}원 많습니다."
                   if overtime_monthly > fixed_ot + 0.5 else "")
            all_w.append(f"고정연장수당 등 월 {fixed_ot:,.0f}원과 계산한 연장·야간·휴일 근로 임금 월 {overtime_monthly:,.0f}원(매주 "
                         f"같은 시간으로 봄)은 같은 근로의 대가라 합치지 않았습니다.{gap}")

        # ── 특수 계산기: 임금체불 (독립 함수, WageInput 미사용) ───────────────
        if "wage_arrears" in targets:
            wa = guarded("wage_arrears", "임금체불 지연이자", lambda: calc_wage_arrears(
                arrear_amount=inp.arrear_amount,
                arrear_due_date=inp.arrear_due_date,
                is_post_retirement_arrear=inp.is_post_retirement_arrear,
                arrear_calc_date=inp.arrear_calc_date,
                claim_kind=inp.arrear_claim_kind,
                retirement_effective_date=inp.arrear_retirement_effective_date,
                last_employed_date=inp.arrear_last_employed_date,
                debtor_is_merchant=inp.debtor_is_merchant,
                payments=inp.arrear_payments, exclusions=inp.arrear_exclusions,
                claims=inp.arrear_claims, deadline_holidays=inp.arrear_deadline_holidays,
                reference_date=inp.reference_date, reference_year=inp.reference_year,
                is_employee=not inp.is_platform_worker,
            ))
            if wa is not None:
                result.summary["남은 체불 원금"] = f"{wa.arrear_amount:,.0f}원"
                if wa.conditional_scenarios:
                    for scenario in wa.conditional_scenarios:
                        label = "상사채무" if scenario["debtor_is_merchant"] else "민사채무"
                        result.summary[f"{label} 조건 지연이자"] = f'{scenario["interest_amount"]:,.0f}원'
                        if scenario["total_claim"] is not None:
                            result.summary[f"{label} 조건 남은 이자"] = f'{scenario["remaining_interest"]:,.0f}원'
                            result.summary[f"{label} 조건 원금·이자 합계"] = f'{scenario["total_claim"]:,.0f}원'
                else:
                    result.summary["임금체불 누적 지연이자"] = f"{wa.interest_amount:,.0f}원"
                    if wa.total_claim is not None:
                        result.summary["남은 지연이자"] = f"{wa.remaining_interest:,.0f}원"
                        result.summary["남은 원금·이자 합계"] = f"{wa.total_claim:,.0f}원"
                if wa.interest_paid is None:
                    result.summary["청구 합계"] = "보류 — 이미 지급한 이자 충당액 확인 필요"
                elif wa.interest_paid:
                    result.summary["이미 지급한 이자"] = f"{wa.interest_paid:,.0f}원"
                if len(wa.claims)==1:
                    result.summary["지연일수"] = f"{wa.delay_days}일"
                else:
                    result.summary["이자 계산 채권 수"] = f"{len(wa.claims)}건"
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
            mark = used_mark()
            r = guarded(key, section, lambda f=func: f(inp, ow, _severance_cache))
            if r is None:
                continue
            # 이 둘의 자격은 퇴직금 결과가 정한다(결과에 자격 플래그가 없다)
            severance_ineligible = _severance_cache is not None and not _severance_cache.is_eligible
            if key in amount_hold and _merge_amount_held(result, key, section, r, populate, all_w, all_l,
                                                         ineligible=severance_ineligible):
                forget_used_since(mark)
                continue
            populate(r, result)
            _merge(result, section, r, all_w, all_l)

        # ── 법률 힌트: 다른 계산 결과 참조 후 마지막에 실행 ──────────────────
        has_conditions = any(
            (a.get("condition") if isinstance(a, dict) else getattr(a, "condition", "없음")) != "없음"
            for a in inp.fixed_allowances
        )
        if {"minimum_wage", "comprehensive"} & blocked_targets:
            # 보류된 계산은 판정을 남기지 않는다 — 값이 남아 있으면 '최저임금 충족 ✅'라는 없는 판정이 나간다
            # (필드 기본값은 None).
            result.minimum_wage_ok = None
            result.minimum_wage_state = "held"
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

        if not inp.monthly_total_pay and any(a.annual or a.payment_cycle != "매월" for a in normalize_allowances(inp.fixed_allowances)):
            result.monthly_total_is_equivalent = True
            all_w.append("연·분기·반기 수당은 월 환산액입니다. 실제 매월 지급액과 지급기일별 채권은 지급 내역을 별도로 확인해야 합니다.")
        result.monthly_total = round(monthly_total, 0)
        result.warnings = list(dict.fromkeys(all_w))
        result.legal_basis = list(dict.fromkeys(all_l))
        result.legal_rule_blocked = blocked

        # 선행조건 때문에 조용히 건너뛴 계산도 결과로 보고한다. 통상임금 기반 계산이나
        # 호출자가 추가한 연장수당만으로 요청 계산이 완료된 것으로 간주하지 않는다.
        requested = set(targets) - set(auxiliary) - {"legal_hints"}
        if requested and requested <= {"parental_leave", "reduced_work_benefit", "wage_arrears", "maternity_leave"}:
            # 휴직/단축 전 통상임금은 보험 급여의 기초액이다. 회사가 실제로
            # 지급하는 임금 또는 휴직 중 월 총수령액으로 표시하지 않는다.
            result.monthly_total = result.monthly_net = 0.0
        if not targets:
            result.calculation_skipped.append({"target": "", "section": "계산 유형",
                "reason": "실행할 계산 유형이 없습니다. 지원하는 계산 유형을 지정해주세요."})
        for target in dict.fromkeys(targets):
            if target in requested and target not in result.calculation_executed and target not in blocked_targets:
                reasons = {
                    "prorated": ("현재 일할계산은 중도입사월만 지원합니다. 중도퇴사·휴복직 정산은 아직 지원하지 않아 계산하지 않았습니다."
                                 if inp.end_date else
                                 "중도입사 일할계산에 유효한 입사일이 필요합니다. 중도퇴사·휴복직 정산은 아직 지원하지 않습니다."),
                    "wage_arrears": "확정된 체불 원금과 원래 지급기일이 필요합니다. 이 계산은 원금 산정이 아닌 지연이자 계산입니다.",
                    "comprehensive": "포괄임금제 입력이 필요합니다.",
                    "public_holiday": "계산할 유급 공휴일 수가 필요합니다.",
                    "shutdown_allowance": "계산할 휴업일 수가 필요합니다.",
                    "flexible_work": "탄력적 근로시간제의 단위기간 입력이 필요합니다.",
                    "business_size": "상시근로자 수 판정을 위한 사업장 인원 자료가 필요합니다.",
                }
                result.calculation_skipped.append({
                    "target": target, "section": CALC_TYPES.get(target, target),
                    "reason": reasons.get(target, "지원하지 않는 계산 유형입니다."),
                })
        if not targets or (requested and not requested.intersection(result.calculation_executed)):
            result.calculation_status = "not_run"
            result.ordinary_hourly = result.monthly_total = result.monthly_net = 0.0
            result.minimum_wage_ok = None
            result.minimum_wage_state = ""
            result.summary.clear()
            result.breakdown.clear()
            result.formulas.clear()
        elif result.calculation_skipped:
            result.calculation_status = "partial"

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

        if (inp.arrear_claims is not None or inp.arrear_amount != 0 or inp.arrear_due_date
                or inp.arrear_calc_date is not None or inp.is_post_retirement_arrear
                or inp.arrear_claim_kind != "regular_wage"
                or inp.arrear_retirement_effective_date is not None or inp.arrear_last_employed_date is not None
                or inp.arrear_payments is not None or inp.arrear_exclusions is not None):
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
