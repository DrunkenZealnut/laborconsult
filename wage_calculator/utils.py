"""
공통 유틸리티 — 중복 제거용
"""

from datetime import date

# 주/월 환산 상수 (매직넘버 4.345 제거)
WEEKS_PER_MONTH = 365 / 7 / 12  # ≈ 4.345


def parse_date(date_str: str | None) -> date | None:
    """YYYY-MM-DD 문자열 → date, 실패 시 None"""
    if not date_str:
        return None
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        return None
