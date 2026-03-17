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

    # 수습기간 관련 (한국어 키 + analyzer 영문 키)
    if info.get("is_probation") is True:
        inp.is_probation = True
    else:
        수습 = info.get("수습", "") or info.get("수습기간", "") or ""
        if 수습 and ("수습" in 수습 or "예" in 수습 or "true" in 수습.lower()):
            inp.is_probation = True

    # 계약기간 (개월) — 수습 감액 적용 시 1년 이상 여부 판단
    if info.get("contract_months") is not None:
        try:
            inp.contract_months = int(info["contract_months"])
        except (ValueError, TypeError):
            pass
    else:
        계약기간 = info.get("계약기간", "") or ""
        if 계약기간:
            inp.contract_months = _parse_contract_months(계약기간)

    # 직종코드 — 단순노무종사자 판별 (analyzer 영문 키 우선)
    occ = info.get("occupation_code", "") or info.get("직종코드", "") or ""
    if occ:
        inp.occupation_code = str(occ).strip()
    else:
        직종명 = info.get("직종", "") or info.get("직업", "") or ""
        if 직종명:
            inp.occupation_code = _infer_occupation_code(직종명)

    # 특수고용직(노무제공자) 판별
    if info.get("is_platform_worker") is True:
        inp.is_platform_worker = True
        from ..models import WorkType
        inp.work_type = WorkType.PLATFORM_WORKER

    return inp


def _parse_contract_months(period_str: str) -> int | None:
    """'1년', '6개월', '2년 계약' 등에서 계약기간(개월) 추출."""
    import re
    years = re.search(r"(\d+)\s*년", period_str)
    months = re.search(r"(\d+)\s*개월", period_str)
    total = 0
    if years:
        total += int(years.group(1)) * 12
    if months:
        total += int(months.group(1))
    return total if total > 0 else None


def _infer_occupation_code(job_name: str) -> str | None:
    """직업명에서 단순노무종사자 여부 추론. 해당 시 "9" 반환."""
    from ..constants import ELEMENTARY_OCCUPATION_KEYWORDS
    for kw in ELEMENTARY_OCCUPATION_KEYWORDS:
        if kw in job_name:
            return "9"
    return None


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
