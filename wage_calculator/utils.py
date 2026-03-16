"""
공통 유틸리티 — 중복 제거용
"""

from datetime import date
from enum import Enum

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


# ── 반올림 정책 ────────────────────────────────────────────────────────────────

class RoundingPolicy(Enum):
    """반올림 정책

    WON:       원 단위 반올림 round(x, 0) — 수당/퇴직금
    TRUNCATE:  원 미만 절삭 int(x) — 보험료/세금
    DECIMAL_2: 소수점 2자리 round(x, 2) — 시급/일급
    """
    WON = "won"
    TRUNCATE = "truncate"
    DECIMAL_2 = "decimal_2"


def apply_rounding(value: float, policy: RoundingPolicy) -> float:
    """정책에 따른 반올림 적용"""
    if policy == RoundingPolicy.WON:
        return round(value, 0)
    elif policy == RoundingPolicy.TRUNCATE:
        return float(int(value))
    elif policy == RoundingPolicy.DECIMAL_2:
        return round(value, 2)
    return value
