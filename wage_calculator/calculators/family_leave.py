"""Requested subtype adapter for existing paid family-leave rules."""
from dataclasses import dataclass
from ..base import BaseCalculatorResult
from .pay_inputs import PayInputError, strict_date

FAMILY_INPUT_FIELDS = {
    'maternity_leave_type', 'family_leave_days', 'family_leave_used_days',
    'family_leave_insured_days', 'family_leave_eligible', 'is_priority_support_company',
    'family_leave_start_date', 'family_leave_end_date',
}
FAMILY_LABELS = {'infertility':'난임치료휴가', 'spouse_birth':'배우자 출산휴가',
                 'spouse_miscarriage':'배우자 유산·사산휴가'}


@dataclass
class FamilyLeaveResult(BaseCalculatorResult):
    selected_type: str = ''
    paid_days: int = 0
    employer_pay: float = 0.0
    insurance_benefit: float | None = None
    summary: dict = None


def _days(value, label, maximum):
    if type(value) is not int or not 0 <= value <= maximum:
        raise PayInputError(f'{label}를 0~{maximum}일 정수로 확인해주세요.')
    return value


def validate_maternity_request(inp):
    """The existing maternity formula covers a full leave, not arbitrary slices."""
    start = strict_date(inp.family_leave_start_date, '출산전후휴가 시작일')
    end = strict_date(inp.family_leave_end_date, '출산전후휴가 종료일')
    if inp.is_platform_worker:
        raise PayInputError('명시 출산휴가 입력은 근로자용입니다. 노무제공자는 별도 자격·보수 자료가 필요합니다.')
    if inp.family_leave_eligible is not True:
        raise PayInputError('출산전후휴가 법정 사용 요건 충족 여부를 확인해주세요.')
    insured = _days(inp.family_leave_insured_days, '휴가 종료 전 피보험 단위기간', 100_000)
    if insured < 180:
        raise PayInputError('고용보험 피보험 단위기간 180일 요건을 충족하지 않습니다. 보험 급여를 지급액으로 확정할 수 없으며 사업주 유급 의무는 별도 확인 대상입니다.')
    if type(inp.is_priority_support_company) is not bool:
        raise PayInputError('우선지원대상기업 여부를 확인해주세요.')
    if start.year != end.year:
        raise PayInputError('출산휴가가 연도 경계를 걸칩니다. 기간별 상한과 지급 내역 확인이 필요합니다.')
    days = 120 if inp.is_multiple_birth else (100 if inp.is_premature_birth and start.isoformat() >= '2025-02-23' else 90)
    if inp.family_leave_days != days or type(inp.family_leave_days) is not int or inp.family_leave_used_days != 0 or type(inp.family_leave_used_days) is not int or (end-start).days+1 != days:
        raise PayInputError(f'현재 출산전후휴가 산식은 전체 {days}일의 최초 사용을 계산합니다. 부분 사용·분할 사용은 실제 구간별 지급 내역을 확인해주세요.')
    if inp.reference_date and inp.reference_date[:4] != str(start.year):
        raise PayInputError('출산휴가 사용 연도와 계산 기준일의 연도가 다릅니다.')
    return start


def calc_family_leave(inp, ow):
    try:
        return _calculate(inp, ow)
    except PayInputError as exc:
        return FamilyLeaveResult(held_reason=str(exc), warnings=[str(exc)])


def _calculate(inp, ow):
    from .maternity_leave import (
        INFERTILITY_LEAVE_PERIODS, SPOUSE_MISCARRIAGE_PERIODS, SPOUSE_LEAVE_PERIODS,
        DAILY_LEAVE_UPPER_PERIODS, SPOUSE_LEAVE_UPPER_PERIODS, _effective, _employer_and_insurance,
    )
    kind = inp.maternity_leave_type
    if kind == 'multiple':
        raise PayInputError('여러 휴가를 요청했습니다. 휴가 유형별 사용 구간·일수·기사용 내역을 각각 확인해주세요.')
    if kind not in FAMILY_LABELS:
        raise PayInputError('요청한 휴가 유형의 급여 계산을 지원하지 않습니다. 본인 유산·사산은 출산 90일로 대체하지 않습니다.')
    label = FAMILY_LABELS[kind]
    if inp.is_platform_worker:
        raise PayInputError(f'{label}는 근로자 적용 여부를 먼저 확인해야 합니다.')
    start = strict_date(inp.family_leave_start_date, '휴가 사용 시작일')
    end = strict_date(inp.family_leave_end_date, '휴가 사용 종료일')
    if end < start:
        raise PayInputError('휴가 종료일이 시작일보다 빠릅니다.')
    if inp.family_leave_eligible is not True:
        raise PayInputError(f'{label} 법정 사용 요건·신청 가능 기간 충족 여부를 확인해주세요.')
    table = {'infertility':INFERTILITY_LEAVE_PERIODS,'spouse_birth':SPOUSE_LEAVE_PERIODS,
             'spouse_miscarriage':SPOUSE_MISCARRIAGE_PERIODS}[kind]
    rule = _effective(table, start.isoformat(), start.year)
    if rule is None:
        raise PayInputError(f'{label} 해당 사용일의 법률 기준이 등록되지 않았거나 시행 전입니다.')
    if rule != _effective(table, end.isoformat(), end.year) or start.year != end.year:
        raise PayInputError('휴가가 법률 변경일 또는 연도 경계를 걸칩니다. 구간별 사용일과 기존 사용 내역을 확인해주세요.')
    total, paid_limit = rule
    if kind == 'spouse_birth':
        insurance_limit = paid_limit
        paid_limit = total
    else:
        insurance_limit = paid_limit
    used = _days(inp.family_leave_used_days, '같은 휴가 한도의 기사용 일수', total)
    requested = _days(inp.family_leave_days, '이번 실제 사용 일수', total)
    if used + requested > total or requested > (end-start).days+1:
        raise PayInputError('이번 사용 일수·기사용 일수와 법정 한도 또는 사용 날짜가 맞지 않습니다.')
    paid_days = min(requested, max(0,paid_limit-used))
    insurance_days = min(requested,max(0,insurance_limit-used))
    daily = ow.hourly_ordinary_wage * ow.daily_hours_used
    # Existing source tables contain confirmed 2025/2026 caps only.
    upper = None
    if start.year in (2025,2026):
        if kind == 'spouse_birth':
            total_cap = _effective(SPOUSE_LEAVE_UPPER_PERIODS,start.isoformat(),start.year)
            upper = total_cap / insurance_limit * insurance_days if total_cap is not None else None
        else:
            daily_cap = _effective(DAILY_LEAVE_UPPER_PERIODS,start.isoformat(),start.year)
            upper = daily_cap * insurance_days if daily_cap is not None else None
    pay, candidate = _employer_and_insurance(daily, paid_days, insurance_days, True, upper)
    insured = inp.family_leave_insured_days
    if insured is not None:
        _days(insured, '휴가 종료 전 피보험 단위기간', 100_000)
    priority = inp.is_priority_support_company
    if priority is not None and type(priority) is not bool:
        raise PayInputError('우선지원대상기업 여부를 확인해주세요.')
    warnings = []
    if insurance_days == 0 or priority is False or (insured is not None and insured < 180):
        benefit = 0.0
        insurance_text = '0원 (지원 대상 일수 또는 기업·피보험 단위기간 요건 미충족)'
    elif priority is True and insured is not None and upper is not None:
        benefit = round(candidate)
        insurance_text = f'{benefit:,.0f}원'
    else:
        benefit = None
        insurance_text = '미확정 (우선지원대상기업·피보험 단위기간 180일·해당 연도 상한 확인 필요)'
        warnings.append(insurance_text)
    summary = {f'{label} 이번 사용 일수':f'{requested}일 (기사용 {used}일, 이번 유급 {paid_days}일)',
               f'{label} 사업주 유급액':f'{pay:,.0f}원', f'{label} 급여(고용보험)':insurance_text}
    effective_from = max(day for day in table if day <= start.isoformat())
    summary['적용 법률 기준'] = f"{effective_from} 시행: 총 {total}일, 최초 {paid_limit}일 유급. 사용 구간 {start}~{end}"
    formulas = [f'{label}: 이번 유급 {paid_days}일 × 1일 통상임금 {daily:,.2f}원 = {pay:,.0f}원']
    if benefit is not None:
        formulas.append(f'고용보험 지원분 {benefit:,.0f}원은 위 유급액에 포함되며 별도 합산하지 않습니다.')
        summary[f'{label} 사업주 잔여 부담'] = f'{pay-benefit:,.0f}원'
    if kind == 'infertility' and start.isoformat() >= '2026-11-27':
        formulas.append('난임치료휴가 유급 기간은 2026-11-27 시행 개정으로 최초 2일에서 4일로 확대됩니다. 이 사용 구간에는 4일 한도를 적용했습니다.')
        warnings.append('시행 근거: 정부 이렇게 달라집니다 — https://whatsnew.mofe.go.kr/mec/ots/dif/view.do?comBaseCd=DIFTYPCD&difField1=DIFFIELD26&difSer=5e74bf92-50c2-419c-9b43-745406c5e51c')
    warnings.append('근로자가 진술한 법정 휴가 요건 충족을 전제로 산정했습니다. 실제 지원은 신청·심사를 거칩니다.')
    return FamilyLeaveResult(selected_type=kind,paid_days=paid_days,employer_pay=round(pay),
        insurance_benefit=benefit,summary=summary,breakdown=summary.copy(),formulas=formulas,warnings=warnings,
        legal_basis=[{'infertility':'남녀고용평등법 제18조의3','spouse_birth':'남녀고용평등법 제18조의2',
                      'spouse_miscarriage':'남녀고용평등법 제18조의4'}[kind],
                     '고용보험법 출산전후휴가 급여등 규정', '고용노동부 출산전후휴가 급여등 상한액 고시'])
