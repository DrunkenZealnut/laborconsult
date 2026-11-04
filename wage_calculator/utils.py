"""
공통 유틸리티 — 중복 제거용
"""

from datetime import date
from enum import Enum

# 주/월 환산 상수 (매직넘버 4.345 제거) — 1년 평균 주 수 ÷ 12(근로기준법 시행령 제6조②4호·최저임금법 시행령 제5조①3호)
WEEKS_PER_MONTH = 365 / 7 / 12  # ≈ 4.345
# 계산식에 적는 주→월 환산 계수. 소수로 줄여 적으면(4.345) 표시값으로 다시 계산한 금액이 카드 금액과 어긋난다
# (외부 점검 #45: 33,024원 × 4.345 = 143,489원 vs 카드 143,497원)
WEEKS_PER_MONTH_LABEL = "365÷7÷12"


def fmt_won(amount: float) -> str:
    """계산식 속 중간 금액 표시. 원 단위로 떨어지면 정수, 아니면 소수 둘째 자리까지 — 원 단위로 줄여 적으면 그 값으로 다시
    계산한 다음 단계 금액이 카드와 어긋난다(주휴수당 95,890원 × 365÷7÷12 = 416,665원 vs 카드 416,667원, Act-4 리뷰 L2)."""
    return f"{amount:,.2f}".rstrip("0").rstrip(".")


def fmt_hours(hours: float) -> str:
    """시간 표시. 계산은 반올림하지 않고 표시만 소수 넷째 자리까지 줄인다(정수면 정수로 — 209).

    둘째 자리로 줄이면 표시값으로 다시 계산한 금액이 카드 금액과 어긋난다(83.43h × 10,320원 = 860,998원 vs 정확한 값
    860,983원). 중간에 반올림해 계산하던 때는 83.4h로 860,688원을 냈다(외부 점검 #45, audit-50 Act-4).
    """
    return f"{hours:.4f}".rstrip("0").rstrip(".")


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
