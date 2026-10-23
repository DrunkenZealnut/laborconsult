"""Explicit pay facts shared by the analyzer and calculators (C4b)."""
import math
import re
from datetime import date

PAY_INPUT_FIELDS = {
    'monthly_total_pay', 'annual_bonus_total', 'last_3m_wages', 'last_3m_days', 'excluded_periods',
    'annual_bonus_allowance_ids', 'last_3m_bonus_included', 'monthly_total_bonus_included',
}


class PayInputError(ValueError):
    pass


def money(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1e12:
        raise PayInputError(f'{label}: 0 이상의 유한한 금액을 확인해주세요.')
    return float(value)


def strict_date(value, label):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise PayInputError(f'{label}: YYYY-MM-DD 날짜를 확인해주세요.')
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise PayInputError(f'{label}: 실제 달력 날짜를 확인해주세요.') from None


def validate_average_inputs(inp):
    if inp.end_date:
        strict_date(inp.end_date, '평균임금 사유 발생일')
    money(inp.annual_bonus_total, '연 상여금')
    money(inp.unused_annual_leave_pay, '평균임금 산입 연차수당')
    if inp.last_3m_days is not None:
        if type(inp.last_3m_days) is not int or not 1 <= inp.last_3m_days <= 92:
            raise PayInputError('산정기간 일수는 제외 전 달력일수(1~92일)로 확인해주세요.')
    if inp.last_3m_wages is not None:
        if not isinstance(inp.last_3m_wages, list) or not 1 <= len(inp.last_3m_wages) <= 93:
            raise PayInputError('실제 산정기간 임금 내역이 비어 있거나 형식이 잘못되었습니다.')
        for item in inp.last_3m_wages:
            if isinstance(item, dict):
                if not item or set(item) - {'base', 'allowance'}:
                    raise PayInputError('3개월 임금 내역의 기본급(base)·수당(allowance)을 확인해주세요.')
                for key, value in item.items():
                    money(value, f'3개월 임금 {key}')
            else:
                money(item, '3개월 실제 임금')
    if inp.annual_bonus_total > 0 and inp.start_date and inp.end_date:
        start = strict_date(inp.start_date, '입사일')
        end = strict_date(inp.end_date, '평균임금 사유 발생일')
        if (end-start).days < 365:
            raise PayInputError('1년 미만 근속의 상여금은 실제 지급 대상 개월 수를 확인해야 합니다.')


EXCLUSION_REASONS = {
    '사용자귀책휴업', 'employer_shutdown', '출산전후휴가', '출산휴가', 'maternity_leave',
    '유산사산휴가', '유산·사산휴가', '업무상재해요양', '산재요양', 'occupational_injury',
    '육아휴직', 'childcare_leave', '쟁의행위', 'industrial_action',
    '승인휴직', '사용자승인휴업', 'approved_leave', '수습3개월', 'probation_first_3m',
    '무급병역의무', 'unpaid_military_duty',
}


def validated_exclusions(inp, full_days):
    """No inferred wage allocation for partly clipped or overlapping periods."""
    from datetime import timedelta
    periods = inp.excluded_periods
    if periods is None:
        return 0, 0.0
    if not isinstance(periods, list):
        raise PayInputError('평균임금 제외 기간은 날짜·사유·지급액 목록으로 확인해주세요.')
    if not periods:
        return 0, 0.0
    end = strict_date(inp.end_date, '평균임금 사유 발생일')
    lo, hi = end-timedelta(days=full_days), end-timedelta(days=1)
    seen, intervals = set(), []
    days, paid = 0, 0.0
    for p in periods:
        if not isinstance(p, dict):
            raise PayInputError('평균임금 제외 기간의 날짜·사유·지급액을 확인해주세요.')
        start, stop = strict_date(p.get('start'), '제외 시작일'), strict_date(p.get('end'), '제외 종료일')
        if stop < start:
            raise PayInputError('평균임금 제외 종료일이 시작일보다 빠릅니다.')
        reason = p.get('reason')
        if reason not in EXCLUSION_REASONS:
            raise PayInputError('법정 평균임금 제외 사유인지 확인해주세요. 개인 결근을 자동 제외하지 않습니다.')
        if inp.last_3m_wages is not None and 'paid' not in p:
            raise PayInputError('제외 기간 중 실제 임금총액에 포함된 지급액(paid)을 확인해주세요.')
        value = money(p.get('paid', 0), '제외 기간 지급액')
        if stop < lo or start > hi:
            continue
        if start < lo or stop > hi:
            raise PayInputError('산정기간과 겹치는 제외 날짜 및 그 구간의 지급액을 나누어 확인해주세요.')
        key = (start, stop, reason, value)
        if key in seen:
            continue
        if any(start <= b and stop >= a for a, b in intervals):
            raise PayInputError('제외 기간이 겹칩니다. 같은 날의 임금이 중복 차감되지 않도록 내역을 확인해주세요.')
        seen.add(key); intervals.append((start,stop))
        days += (stop-start).days+1; paid += value
    if days >= full_days:
        raise PayInputError('산정기간 전부가 제외됩니다. 제외 시작 전 임금 등 평균임금 특례 자료를 확인해주세요.')
    if days and (inp.annual_bonus_total > 0 or inp.unused_annual_leave_pay > 0):
        raise PayInputError('제외 기간과 연 상여·연차수당이 함께 있어 연간 산입 기준 및 제외기간 귀속액 확인이 필요합니다.')
    return days, paid


def bonus_already_included(inp, ow):
    """Amount already represented in the 3-month wage base, with explicit identity."""
    from dataclasses import replace
    from .ordinary_wage import calc_ordinary_wage
    from .shared import normalize_allowances, monthly_wage_total
    from ..models import WageType
    if inp.annual_bonus_total == 0:
        return 0.0
    if inp.last_3m_wages is not None:
        if inp.last_3m_bonus_included is None:
            raise PayInputError('실제 3개월 임금총액에 연 상여가 포함됐는지와 그 금액을 확인해주세요. 별도이면 0원입니다.')
        value = money(inp.last_3m_bonus_included, '3개월 임금에 포함된 연 상여')
        if value > inp.annual_bonus_total:
            raise PayInputError('3개월에 포함된 상여가 연간 상여 총액보다 큽니다.')
        return value
    if inp.monthly_total_pay or inp.wage_type == WageType.ANNUAL:
        if inp.monthly_total_bonus_included is None:
            raise PayInputError('월 총액·연봉에 연 상여가 포함됐는지와 포함된 월 환산액을 확인해주세요. 별도이면 0원입니다.')
        value = money(inp.monthly_total_bonus_included, '월 총액에 포함된 연 상여')
        if value * 12 > inp.annual_bonus_total + 0.01:
            raise PayInputError('총액에 포함된 상여의 월 환산액과 연 상여 총액이 맞지 않습니다.')
        return value * 3
    allowances = normalize_allowances(inp.fixed_allowances)
    ids = inp.annual_bonus_allowance_ids
    if ids is None:
        if any(a.annual or a.payment_cycle != '매월' or '상여' in a.name for a in allowances):
            raise PayInputError('연 상여와 고정수당이 같은 항목인지 출처를 확인해주세요.')
        return 0.0
    if not isinstance(ids, list) or any(not isinstance(x,str) or not x for x in ids) or len(ids) != len(set(ids)):
        raise PayInputError('동일 상여의 고정수당 항목 식별자를 확인해주세요.')
    matched = [a for a in allowances if a.source_id in ids]
    if len(matched) != len(ids) or {a.source_id for a in matched} != set(ids):
        raise PayInputError('상여 출처 식별자가 고정수당 목록과 일치하지 않거나 중복됩니다.')
    reduced = replace(inp, fixed_allowances=[a for a in allowances if a.source_id not in ids])
    return max(0, monthly_wage_total(inp, ow)-monthly_wage_total(reduced,calc_ordinary_wage(reduced))) * 3
