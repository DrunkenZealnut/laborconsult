"""
provided_info → WageInput 변환

facade.py 에서 분리 (Phase D)
"""

from ..models import WageInput, WageType, BusinessSize


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

    # 사업장 규모 (300인 → 30인 → 10인 순서로 체크하여 부분 매칭 방지)
    size_str = info.get("사업장규모", "") or ""
    if "5인 미만" in size_str or "5인미만" in size_str:
        biz_size = BusinessSize.UNDER_5
    elif "300인" in size_str:
        biz_size = BusinessSize.OVER_300
    elif "30인" in size_str:
        biz_size = BusinessSize.OVER_30
    elif "10인" in size_str:
        biz_size = BusinessSize.OVER_10
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
