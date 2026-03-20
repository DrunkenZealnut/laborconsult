"""
계산기 레지스트리 — 지원 유형 및 디스패처 매핑

facade.py 에서 분리 (Phase D)
"""

from ..calculators.annual_leave import calc_annual_leave
from ..calculators.average_wage import calc_average_wage
from ..calculators.compensatory_leave import calc_compensatory_leave
from ..calculators.comprehensive import calc_comprehensive
from ..calculators.dismissal import calc_dismissal
from ..calculators.eitc import calc_eitc
from ..calculators.flexible_work import calc_flexible_work
from ..calculators.industrial_accident import calc_industrial_accident
from ..calculators.insurance import calc_insurance, calc_employer_insurance
from ..calculators.maternity_leave import calc_maternity_leave
from ..calculators.minimum_wage import calc_minimum_wage
from ..calculators.overtime import calc_overtime
from ..calculators.weekly_holiday import calc_weekly_holiday
from ..calculators.parental_leave import calc_parental_leave
from ..calculators.prorated import calc_prorated
from ..calculators.public_holiday import calc_public_holiday
from ..calculators.retirement_pension import calc_retirement_pension
from ..calculators.retirement_tax import calc_retirement_tax
from ..calculators.severance import calc_severance
from ..calculators.shutdown_allowance import calc_shutdown_allowance
from ..calculators.unemployment import calc_unemployment
from ..calculators.working_hours import calc_working_hours
from ..calculators.ordinary_wage import calc_ordinary_wage as _calc_ow_raw, OrdinaryWageResult
from ..base import BaseCalculatorResult
from ..models import WageType
from .helpers import (
    _pop_overtime, _pop_minimum_wage, _pop_weekly_holiday, _pop_annual_leave,
    _pop_dismissal, _pop_comprehensive, _pop_prorated, _pop_public_holiday,
    _pop_average_wage, _pop_severance, _pop_shutdown_allowance,
    _pop_unemployment, _pop_insurance, _pop_employer_insurance,
    _pop_compensatory_leave, _pop_parental_leave, _pop_maternity_leave,
    _pop_flexible_work, _pop_eitc, _pop_industrial_accident,
    _pop_ordinary_wage, _pop_working_hours,
)


def _calc_ordinary_wage_standalone(inp, ow: OrdinaryWageResult) -> BaseCalculatorResult:
    """통상임금을 독립 계산기로 노출하는 래퍼."""
    breakdown = {
        "통상시급": f"{ow.hourly_ordinary_wage:,.0f}원",
        "1일 통상임금": f"{ow.daily_ordinary_wage:,.0f}원",
        "월 통상임금": f"{ow.monthly_ordinary_wage:,.0f}원",
        "월 기준시간": f"{ow.monthly_base_hours}시간 ({ow.base_hours_detail})",
    }
    if ow.included_items:
        breakdown["포함 항목"] = ", ".join(ow.included_items)
    if ow.excluded_items:
        breakdown["제외 항목"] = ", ".join(ow.excluded_items)

    return BaseCalculatorResult(
        breakdown=breakdown,
        formulas=[ow.formula],
        warnings=[],
        legal_basis=[
            "대법원 2013다4174 (정기성·일률성)",
            "대법원 2023다302838 (고정성 요건 폐기)",
        ],
    )

# 지원 계산 유형
CALC_TYPES = {
    "overtime":            "연장/야간/휴일 수당",
    "minimum_wage":        "최저임금 검증",
    "weekly_holiday":      "주휴수당",
    "annual_leave":        "연차수당",
    "dismissal":           "해고예고수당",
    "comprehensive":       "포괄임금제 역산",
    "prorated":            "중도입사 일할계산",
    "public_holiday":      "유급 공휴일",
    "insurance":           "4대보험·소득세 (세전/세후, 근로자)",
    "employer_insurance":  "사업주 4대보험 부담금",
    "severance":           "퇴직금",
    "unemployment":        "실업급여(구직급여)",
    "compensatory_leave":  "보상휴가 환산",
    "wage_arrears":        "임금체불 지연이자",
    "parental_leave":      "육아휴직급여",
    "maternity_leave":     "출산전후휴가급여",
    "flexible_work":       "탄력적 근로시간제 연장수당",
    "weekly_hours_check":  "주 52시간 준수 여부 체크",
    "legal_hints":         "법률 판단 힌트",
    "business_size":       "상시근로자 수 판정",
    "eitc":                "근로장려금(EITC) 수급 판정 + 금액",
    "retirement_tax":      "퇴직소득세",
    "retirement_pension":  "퇴직연금(DB/DC)",
    "average_wage":        "평균임금",
    "shutdown_allowance":  "휴업수당(근기법 제46조)",
    "industrial_accident": "산재보상금(휴업·장해·유족·장례비)",
    "ordinary_wage":       "통상임금 산출",
    "working_hours":       "소정근로시간 산출",
}

# calculation_type 필드 → 계산기 매핑 (analyze_qna.py 분류값 기준)
CALC_TYPE_MAP = {
    "연장수당":    ["overtime", "minimum_wage"],
    "최저임금":    ["minimum_wage"],
    "주휴수당":    ["weekly_holiday", "minimum_wage"],
    "연차수당":    ["annual_leave"],
    "해고예고수당": ["dismissal"],
    "퇴직금":     ["severance", "minimum_wage"],
    "실업급여":   ["unemployment"],
    "임금계산":   ["overtime", "minimum_wage", "weekly_holiday"],
    "해당없음":   ["minimum_wage"],
    "육아휴직":   ["parental_leave"],
    "출산휴가":   ["maternity_leave"],
    "임금체불":   ["wage_arrears"],
    "보상휴가":   ["compensatory_leave", "overtime"],
    "탄력근무":   ["flexible_work"],
    "사업장규모": ["business_size"],
    "근로장려금": ["eitc"],
    "근로장려세제": ["eitc"],
    "EITC":       ["eitc"],
    "퇴직소득세":  ["severance", "retirement_tax"],
    "퇴직연금":    ["retirement_pension"],
    "퇴직":       ["severance", "retirement_tax"],
    "평균임금":   ["average_wage"],
    "산재보상":   ["industrial_accident", "average_wage"],
    "휴업급여":   ["industrial_accident", "average_wage"],
    "장해급여":   ["industrial_accident", "average_wage"],
    "유족급여":   ["industrial_accident", "average_wage"],
    "장례비":     ["industrial_accident", "average_wage"],
    "산재":       ["industrial_accident", "average_wage"],
    "휴업수당":   ["shutdown_allowance"],
    # ── 벤치마크에서 Claude가 생성하는 복합형 키 ──────────────────────────────
    "연장수당/야간수당/휴일근로수당": ["overtime", "minimum_wage"],
    "연장수당/야간수당/휴일수당":    ["overtime", "minimum_wage"],
    "야간수당":                      ["overtime", "minimum_wage"],
    "휴일수당":                      ["overtime", "minimum_wage"],
    "휴일근로수당":                   ["overtime", "minimum_wage"],
    "야간근로수당":                   ["overtime", "minimum_wage"],
    "연장근로수당":                   ["overtime", "minimum_wage"],
    "통상임금":                      ["ordinary_wage"],
    "통상시급":                      ["ordinary_wage"],
    # ── Q&A 분석 기반 미매핑 유형 추가 ──────────────────────────────────────
    "임금":              ["minimum_wage", "overtime"],
    "임금 계산":          ["minimum_wage", "overtime"],
    "임금계산 검증":       ["minimum_wage"],
    "공휴일수당":          ["public_holiday"],
    "시급환산":            ["ordinary_wage"],
    "임금체불액":          ["wage_arrears"],
    "미지급 임금 계산":     ["wage_arrears"],
    "부당임금삭감액":       ["wage_arrears"],
    "중도입사 급여":        ["prorated"],
    "일할계산급여":         ["prorated"],
    "소정근로시간":         ["working_hours"],
    "근로시간":             ["working_hours"],
    "근로시간 계산":        ["working_hours"],
    "근로시간계산":         ["working_hours"],
    "근로시간 산정":        ["working_hours"],
    "근로시간산정":         ["working_hours"],
    "근로시간산출":         ["working_hours"],
    "월근로시간":           ["working_hours"],
    "연차발생":             ["annual_leave"],
    "연차 발생일수 계산":    ["annual_leave"],
    "연말정산":             ["insurance"],
    "휴일근무수당":         ["overtime", "minimum_wage"],
}


def resolve_calc_type(calc_type_str: str) -> list[str]:
    """
    CALC_TYPE_MAP 정확 매칭 → 키워드 기반 fallback.
    벤치마크·chatbot 양쪽에서 사용.
    """
    if calc_type_str in CALC_TYPE_MAP:
        return CALC_TYPE_MAP[calc_type_str]

    # 슬래시/콤마로 분리 후 개별 매칭 시도
    for sep in ["/", ",", "·", "、"]:
        if sep in calc_type_str:
            parts = [p.strip() for p in calc_type_str.split(sep)]
            for part in parts:
                if part in CALC_TYPE_MAP:
                    return CALC_TYPE_MAP[part]

    # 키워드 우선순위 fallback (구체적 키워드가 앞, generic이 뒤)
    _keyword_map = [
        # ── 구체적 키워드 (generic 규칙보다 우선) ──
        (["공휴일"],               ["public_holiday"]),
        (["소정근로시간", "월근로시간", "월 소정"], ["working_hours"]),
        (["통상임금", "통상시급"],  ["ordinary_wage"]),
        (["연차발생", "발생일수"],  ["annual_leave"]),
        (["일할계산", "중도입사"],  ["prorated"]),
        (["임금체불"],             ["wage_arrears"]),
        # ── 일반 키워드 ──
        (["연장", "야간", "휴일"], ["overtime", "minimum_wage"]),
        (["주휴"],                 ["weekly_holiday", "minimum_wage"]),
        (["퇴직"],                 ["severance", "minimum_wage"]),
        (["최저"],                 ["minimum_wage"]),
        (["연차"],                 ["annual_leave"]),
        (["평균"],                 ["average_wage"]),
        (["실업", "구직"],          ["unemployment"]),
        (["육아"],                 ["parental_leave"]),
        (["출산"],                 ["maternity_leave"]),
        (["휴업"],                 ["shutdown_allowance"]),
        (["산재"],                 ["industrial_accident", "average_wage"]),
        (["근로시간"],             ["working_hours"]),
    ]
    for keywords, targets in _keyword_map:
        if any(kw in calc_type_str for kw in keywords):
            return targets

    return ["minimum_wage"]


# ── 디스패처 레지스트리 ──────────────────────────────────────────────────────
# (key, func, section_name, populate_fn, precondition)

_STANDARD_CALCS = [
    ("ordinary_wage",      _calc_ordinary_wage_standalone, "통상임금",        _pop_ordinary_wage,      None),
    ("working_hours",      calc_working_hours,      "소정근로시간",           _pop_working_hours,      None),
    ("overtime",           calc_overtime,           "연장·야간·휴일수당",     _pop_overtime,           None),
    ("minimum_wage",       calc_minimum_wage,       "최저임금 검증",         _pop_minimum_wage,       None),
    ("weekly_holiday",     calc_weekly_holiday,      "주휴수당",             _pop_weekly_holiday,     None),
    ("annual_leave",       calc_annual_leave,        "연차수당",             _pop_annual_leave,       None),
    ("dismissal",          calc_dismissal,           "해고예고수당",         _pop_dismissal,          None),
    ("comprehensive",      calc_comprehensive,       "포괄임금제 역산",      _pop_comprehensive,
     lambda inp: inp.wage_type == WageType.COMPREHENSIVE),
    ("prorated",           calc_prorated,            "중도입사 일할계산",    _pop_prorated,
     lambda inp: inp.join_date),
    ("public_holiday",     calc_public_holiday,      "유급 공휴일",          _pop_public_holiday,
     lambda inp: inp.public_holiday_days > 0),
    ("average_wage",       calc_average_wage,        "평균임금",             _pop_average_wage,       None),
    ("severance",          calc_severance,           "퇴직금",              _pop_severance,          None),
    ("shutdown_allowance", calc_shutdown_allowance,   "휴업수당",            _pop_shutdown_allowance,
     lambda inp: inp.shutdown_days > 0),
    ("unemployment",       calc_unemployment,        "실업급여(구직급여)",    _pop_unemployment,       None),
    ("insurance",          calc_insurance,           "4대보험·소득세",       _pop_insurance,          None),
    ("employer_insurance", calc_employer_insurance,  "사업주 4대보험 부담금", _pop_employer_insurance,  None),
    ("compensatory_leave", calc_compensatory_leave,  "보상휴가 환산",        _pop_compensatory_leave,  None),
    ("parental_leave",     calc_parental_leave,      "육아휴직급여",         _pop_parental_leave,      None),
    ("maternity_leave",    calc_maternity_leave,     "출산전후휴가급여",     _pop_maternity_leave,     None),
    ("flexible_work",      calc_flexible_work,       "탄력적 근로시간제",    _pop_flexible_work,
     lambda inp: getattr(inp, "flexible_work_unit", "")),
    ("eitc",               calc_eitc,                "근로장려금(EITC)",     _pop_eitc,               None),
    ("industrial_accident", calc_industrial_accident, "산재보상금",           _pop_industrial_accident, None),
]
