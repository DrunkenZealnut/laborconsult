"""
계산기 입력 파싱 유틸

웹 파이프라인의 인라인 변환기(app/core/pipeline.py::_run_calculator)가 정식
변환 경로다. 과거의 한국어 라벨 변환기 _provided_info_to_input()과
facade.from_analysis()는 호출처가 없어 제거됨(calc-db-integration-review D1)
— 아래 파싱 유틸만 남긴다.
"""


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
