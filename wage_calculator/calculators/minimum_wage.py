"""
최저임금 검증 계산기 (최저임금법 제6조)

수요: 741건 (28.5%) — 두 번째로 많은 임금 관련 질문 유형

산입범위 규칙 (최저임금법 제6조제4항, 2019년 개정):
┌──────────────────────┬────────────────────────────────────────────────────┐
│ 항목                  │ 처리 방법                                           │
├──────────────────────┼────────────────────────────────────────────────────┤
│ 기본급               │ 전액 산입                                            │
│ 일반 고정수당         │ 전액 산입 (min_wage_type="standard" 또는 미설정)     │
│ 정기상여금            │ 법정 최저 월액의 N% 초과분만 산입 (2024+: 전액)      │
│ 복리후생비            │ 법정 최저 월액의 M% 초과분만 산입 (2024+: 전액)      │
│ 연장/야간/휴일수당     │ 비산입 (min_wage_type="excluded")                   │
└──────────────────────┴────────────────────────────────────────────────────┘

fixed_allowances 항목에 min_wage_type 키로 명시 가능:
  "standard"      → 전액 산입 (기본값)
  "regular_bonus" → 정기상여금 산입범위 적용
  "welfare"       → 복리후생비 산입범위 적용
  "excluded"      → 비산입 (연장/야간/휴일 등)
미설정 시 수당 이름으로 자동 추론.
"""

from dataclasses import dataclass

from ..base import BaseCalculatorResult
from ..models import WageInput, WageType
from .ordinary_wage import OrdinaryWageResult
from .shared import normalize_allowances, AllowanceClassifier, MultiplierContext, weekly_holiday_hours
from ..legal_rules import managed
from ..constants import get_minimum_hourly_wage
from ..utils import WEEKS_PER_MONTH, fmt_hours
from ..constants import (
    MINIMUM_HOURLY_WAGE,
    MONTHLY_STANDARD_HOURS,
    PROBATION_MIN_WAGE_RATE,
    PROBATION_MIN_CONTRACT_MONTHS,
    PROBATION_MAX_MONTHS,
    ELEMENTARY_OCCUPATION_CODES,
    ELEMENTARY_OCCUPATION_KEYWORDS,
    WEEKLY_FULL_HOURS,
    WEEKLY_HOLIDAY_MIN_HOURS,
    get_min_wage_inclusion_rates,
)


@dataclass
class MinimumWageResult(BaseCalculatorResult):
    is_compliant: bool = False         # 최저임금 충족 여부
    effective_hourly: float = 0.0      # 실질 시급 (원)
    legal_minimum: float = 0.0         # 법정 최저임금 (원)
    shortage_monthly: float = 0.0      # 부족분 월액 (충족 시 0)
    reference_year: int = 0            # 기준 연도
    monthly_hours_used: float = 0.0    # 적용된 월 근로시간
    undetermined: bool = False         # 다른 기준으로 보면 판정이 갈려 보류(별표 2 주휴·연장분 포함 역산·수습 감액 — 아래 대안)
    not_applicable: bool = False       # 노무제공자 — 최저임금법의 근로자가 아니라 판정하지 않음(근로자로 인정될 때의 참고값만)
    alternative_minimum: float = 0.0   # 수습 감액 요건을 모를 때 감액 기준(판정이 갈린 경우만)
    alternative_hourly: float = 0.0    # 판정이 갈린 첫 대안의 실질 시급 — undetermined일 때만(하위 호환)
    alternative_hourlies: tuple = ()   # 판정이 갈린 대안 실질 시급 전부(표기용)


def calc_minimum_wage(inp: WageInput, ow: OrdinaryWageResult) -> MinimumWageResult:
    """
    최저임금 충족 여부 및 부족분 계산 (산입범위 정확 반영)

    Args:
        inp: 임금 입력 데이터
        ow:  통상임금 계산 결과 (월 기준시간 참조용)
    """
    year = inp.reference_year
    warnings: list = []
    formulas: list = []
    # 노무제공자(특수형태근로종사자)는 원칙적으로 최저임금법의 근로자가 아니다(제2조 — 근로기준법상 근로자). 판정 대신 근로자로
    # 인정될 때의 참고값을 낸다 — 예전 카드는 '❌ 미달·노동청 신고·3년 이하 징역'을 단정했다(calc-card-followups F4)
    platform = getattr(inp, "is_platform_worker", False)
    legal:    list = (["최저임금법 제2조 (근로자 — 근로기준법상 근로자)"] if platform
                      else ["최저임금법 제6조 (최저임금의 효력)"])

    # ── 기준 연도 최저임금 ────────────────────────────────────────────────────
    if not managed() and year not in MINIMUM_HOURLY_WAGE:
        year = max(MINIMUM_HOURLY_WAGE.keys())
        warnings.append(f"{inp.reference_year}년 최저임금 미확정 — {year}년 기준 적용")
    legal_minimum = float(get_minimum_hourly_wage(year))
    statutory_minimum = legal_minimum      # 수습 감액 전 — 고시 월 환산액 비교용

    # ── 수습 감액 (최저임금법 제5조 제2항·시행령 제3조) ─────────────────────────────
    # 요건 셋 — 1년 이상의 기간을 정한 근로계약, 수습을 시작한 날부터 3개월 이내, 단순노무업무로 고시한 직종이 아님. 질문에서
    # 확인된 것만 충족으로 본다(calc-card-followups D5). 예전에는 계약기간 미기재를 '기간 정함 없음'으로, 직종 미기재를 단순노무가
    # 아닌 것으로, 수습 기간을 기본 3개월로 읽어 수습 6개월 중 5개월째에도 90%로 '충족'을 냈다(R11). 감액값을 '최저임금'이라
    # 부르지 않는다 — 고시된 최저임금은 그대로고 감액 기준은 따로 적는다(F3)
    probation_reduced = statutory_minimum * PROBATION_MIN_WAGE_RATE
    probation_alt = None               # 요건 중 모르는 것이 있고 실패한 것은 없을 때 — 판정이 갈리면 보류
    probation_unknown: list[str] = []
    if inp.is_probation and not platform:
        reqs = _probation_requirements(inp)
        failed = [name for name, ok in reqs.items() if ok is False]
        probation_unknown = [name for name, ok in reqs.items() if ok is None]
        if failed:
            for name in failed:
                warnings.append(_PROBATION_FAIL_TEXT[name](inp))
            legal.append("최저임금법 제5조제2항 (수습 감액 요건)")
        elif not probation_unknown:
            formulas.append(f"수습 감액 최저임금: {statutory_minimum:,.0f}원 × 90% = {probation_reduced:,.0f}원/h "
                            "(최저임금법 제5조 제2항·시행령 제3조 — 요건 세 가지를 모두 확인)")
            legal.append("최저임금법 제5조제2항, 시행령 제3조 (수습 사용 중인 근로자)")
            legal_minimum = probation_reduced
        else:
            probation_alt = probation_reduced
            legal.append("최저임금법 제5조제2항, 시행령 제3조 (수습 감액 요건)")

    monthly_hours = ow.monthly_base_hours

    # ── 산입범위 제외율 조회 ──────────────────────────────────────────────────
    bonus_excl_rate, welfare_excl_rate = get_min_wage_inclusion_rates(year)

    # 법정 최저임금 월액 (제외기준 계산용 — 최저임금법 시행령 제5조의2)
    legal_monthly_ref = legal_minimum * MONTHLY_STANDARD_HOURS

    # ── 1. 기본급 월액 ────────────────────────────────────────────────────────
    base_monthly = _get_base_monthly(inp, monthly_hours)

    # ── 2. 고정수당 분류 ──────────────────────────────────────────────────────
    std_included   = 0.0
    bonus_total    = 0.0
    welfare_total  = 0.0
    allowance_rows: list[tuple[str, float, str]] = []   # (name, monthly, label)

    for a in normalize_allowances(inp.fixed_allowances):
        monthly_amt = _monthly_amount_fa(a)
        mwt         = AllowanceClassifier.classify_min_wage_type(a.name, a.min_wage_type)
        name        = a.name

        if mwt == "excluded":
            allowance_rows.append((name, monthly_amt, f"비산입({AllowanceClassifier.excluded_kind(name)})"))
        elif mwt == "regular_bonus":
            bonus_total += monthly_amt
            allowance_rows.append((name, monthly_amt, "정기상여금"))
        elif mwt == "welfare":
            welfare_total += monthly_amt
            allowance_rows.append((name, monthly_amt, "복리후생비"))
        else:
            std_included += monthly_amt
            allowance_rows.append((name, monthly_amt, "전액산입"))

    # ── 3. 정기상여금 산입 계산 ───────────────────────────────────────────────
    bonus_excl_threshold = legal_monthly_ref * bonus_excl_rate
    bonus_included       = max(0.0, bonus_total - bonus_excl_threshold)

    # ── 4. 복리후생비 산입 계산 ───────────────────────────────────────────────
    welfare_excl_threshold = legal_monthly_ref * welfare_excl_rate
    welfare_included       = max(0.0, welfare_total - welfare_excl_threshold)

    # ── 5. 총 산입 월 임금 및 실질 시급 ──────────────────────────────────────
    included_monthly = base_monthly + std_included + bonus_included + welfare_included
    # 소수 6자리에서 부동소수 오차를 걷어낸다 — 시급제는 (시급 × h) ÷ h라, h를 반올림하지 않게 되자 시급이 최저임금과
    # 같은데 10,319.999…로 '미달, 부족분 0원'이 났다(audit-50 Act-4 리뷰 H1: 2025년 주 6일 × 8시간 등)
    effective_hourly = round(included_monthly / monthly_hours, 6) if monthly_hours else 0.0

    is_compliant    = effective_hourly >= legal_minimum
    shortage_hourly = max(0.0, legal_minimum - effective_hourly)
    shortage_monthly = shortage_hourly * monthly_hours

    # ── 5-1. 주 5일 초과 단시간근로자 — 주휴 기준에 따라 판정이 갈리면 보류 ─────────────────────────
    # 주휴시간을 1일 평균 소정근로시간(대법원 2022다291153)으로 보면 월 기준시간이 짧고, 같은 업무 통상 근로자의 소정근로일 수
    # (주 5일)로 나누면(근로기준법 시행령 별표 2 제2호나목) 길다. 월급제는 그 차이로 '충족'과 '미달'이 갈린다(독립 리뷰 M4:
    # 월 190만 원, 주 6일 × 6시간 → 182.5h 충족 / 187.71h 미달). 갈리면 판정하지 않는다 — 틀린 판정보다 보류.
    annex_split, alt_hours, alt_included, alt_effective = False, None, 0.0, 0.0
    alt_hours = _annex_alternative_hours(inp, monthly_hours)
    if alt_hours:
        alt_included = (_get_base_monthly(inp, alt_hours) + std_included + bonus_included + welfare_included)
        alt_effective = round(alt_included / alt_hours, 6)
        annex_split = (alt_effective >= legal_minimum) != is_compliant

    # ── 5-2. 일급·월급·연봉 + 연장·야간·휴일 근로 + 임금 구성 미상 — 그 금액에 연장분이 들어 있다고 보는 역산(D4) ────────
    # 포괄 약정이 없으면 연장 임금은 따로 주는 것이 원칙이라 위 판정(금액 ÷ 소정 기준시간)이 기준이다. 그러나 연장분을 금액에
    # 넣는 약정이 흔하고, 그 경우 최저임금 산입에서 연장 임금이 빠진다(최저임금법 제6조 제4항 제1호) — 월급 270만 원·주 5일 ×
    # 10시간이면 12,945원 '충족'과 역산 9,863원 '미달'로 갈린다(calc-card-followups R6). 갈리면 판정하지 않는다.
    ot_split, ot_included_monthly, ot_effective = False, 0.0, 0.0
    ratio = _ot_included_ratio(inp, monthly_hours)
    if ratio is not None:
        ot_included_monthly = base_monthly * ratio + (included_monthly - base_monthly)
        ot_effective = round(ot_included_monthly / monthly_hours, 6) if monthly_hours else 0.0
        ot_split = (ot_effective >= legal_minimum) != is_compliant
    # ── 5-3. 수습 감액 요건을 모름 — 감액 기준(90%)과 고시 최저임금 중 어느 쪽인지에 따라 판정이 갈리면 보류(D5) ──────────
    probation_split = probation_alt is not None and (effective_hourly >= probation_alt) != is_compliant
    undetermined = (annex_split or ot_split or probation_split) and not platform

    # ── formulas ──────────────────────────────────────────────────────────────
    formulas.append(f"기본급 월액: {base_monthly:,.0f}원")
    if std_included:
        formulas.append(f"전액산입 수당 합계: {std_included:,.0f}원")

    if bonus_total:
        if bonus_excl_rate > 0:
            legal.append("최저임금법 제6조제4항 제1호 (정기상여금 산입범위)")
            formulas.append(
                f"정기상여금 산입: {bonus_total:,.0f}원 − 제외기준 {bonus_excl_threshold:,.0f}원 "
                f"(법정 최저월액 {legal_monthly_ref:,.0f}원 × {bonus_excl_rate:.0%}) "
                f"= {bonus_included:,.0f}원"
            )
        else:
            formulas.append(f"정기상여금 전액산입 ({year}년~): {bonus_total:,.0f}원")

    if welfare_total:
        if welfare_excl_rate > 0:
            legal.append("최저임금법 제6조제4항 제2호 (복리후생비 산입범위)")
            formulas.append(
                f"복리후생비 산입: {welfare_total:,.0f}원 − 제외기준 {welfare_excl_threshold:,.0f}원 "
                f"(법정 최저월액 × {welfare_excl_rate:.0%}) "
                f"= {welfare_included:,.0f}원"
            )
        else:
            formulas.append(f"복리후생비 전액산입 ({year}년~): {welfare_total:,.0f}원")

    formulas.append(
        f"실질시급: {included_monthly:,.0f}원 ÷ {fmt_hours(monthly_hours)}h = {effective_hourly:,.2f}원"
    )
    formulas.append(f"{year}년 최저임금: {statutory_minimum:,.0f}원/h")
    if probation_alt is not None:
        labels = ", ".join(_PROBATION_REQ_LABEL[name] for name in probation_unknown)
        if probation_split:
            warnings.append(
                f"수습 감액 요건 가운데 질문에서 확인하지 못한 것이 있습니다({labels}). 요건을 모두 갖추면 수습 감액 최저임금 "
                f"{probation_alt:,.0f}원({statutory_minimum:,.0f}원의 90%) 기준으로 충족이고, 하나라도 빠지면 "
                f"{statutory_minimum:,.0f}원 기준으로 미달이라 판정하지 않았습니다(최저임금법 제5조 제2항·시행령 제3조)."
            )
        else:
            formulas.append(f"수습 감액 요건({labels}) 확인 전 — 감액 최저임금 {probation_alt:,.0f}원으로 봐도 판정이 같습니다"
                            + ("" if is_compliant else
                               f"(요건을 모두 갖추면 부족분은 월 {(probation_alt - effective_hourly) * monthly_hours:,.0f}원)"))

    # 고시의 월 환산액은 주 40시간 근무자를 209시간 기준으로 적는다(고시 본문 '월 환산 기준시간 수 209시간'). 계산은
    # 시행령 산식(1주 48시간 × 365/7 ÷ 12 = 208.5714시간)이라 그 사이 금액은 시간급으로는 충족이지만 고시 환산액에는
    # 못 미친다 — 판정만 내면 사실 블록의 209시간 환산액과 한 답변 안에서 갈린다(Act-4 리뷰 M5)
    notice_monthly = legal_minimum * MONTHLY_STANDARD_HOURS
    if (is_compliant and legal_minimum == statutory_minimum
            and inp.wage_type in (WageType.MONTHLY, WageType.ANNUAL, WageType.COMPREHENSIVE)
            and abs(monthly_hours - 48 * WEEKS_PER_MONTH) < 1e-6 and included_monthly < notice_monthly):
        warnings.append(
            f"산입 월 임금 {included_monthly:,.0f}원은 최저임금 고시의 월 환산액 {notice_monthly:,.0f}원(주 40시간, "
            f"월 {MONTHLY_STANDARD_HOURS:.0f}시간 기준)보다 적습니다. 위 판정은 최저임금법 시행령 제5조 제1항 제3호의 "
            f"산식(1년 평균 주 수, 월 {fmt_hours(monthly_hours)}시간)으로 한 것이라 고시 환산액 기준으로는 미달로 볼 수 "
            f"있습니다 — 고용노동부(1350)에 확인하세요."
        )
    unit = {WageType.DAILY: "일급", WageType.ANNUAL: "연봉"}.get(inp.wage_type, "월급")
    # 감액 기준을 '최저임금'이라 부르지 않는다(F3) — 미달·갈림 안내에도 라벨을 단다(2차 리뷰 L5)
    min_name = "수습 감액 최저임금" if legal_minimum != statutory_minimum else "최저임금"
    if ratio is not None:
        formulas.append(f"실질시급(연장·야간·휴일 근로 임금이 {unit}에 포함된 경우, 역산): {ot_included_monthly:,.0f}원 ÷ "
                        f"{fmt_hours(monthly_hours)}h = {ot_effective:,.2f}원")
        if ot_split:
            warnings.append(
                f"{unit}에 연장·야간·휴일 근로 임금이 포함된다는 약정(포괄임금·고정연장수당)이 있으면 그 임금은 최저임금에 "
                f"산입하지 않아(최저임금법 제6조 제4항 제1호) 역산 실질시급이 {ot_effective:,.0f}원이므로 {min_name}"
                f"({legal_minimum:,.0f}원) 충족 여부가 갈립니다 — 판정하지 않았습니다. 근로계약서의 임금 구성을 확인하세요."
            )
            legal.append("최저임금법 제6조제4항 제1호 (소정근로 외 임금 불산입)")
    if annex_split:
        s_ = inp.schedule
        weekly = s_.daily_work_hours * s_.weekly_work_days
        formulas.append(f"실질시급(통상 근로자 주 5일 기준, 시행령 별표 2): {alt_included:,.0f}원 ÷ {fmt_hours(alt_hours)}h = "
                        f"{alt_effective:,.2f}원")
        warnings.append(
            f"주 {fmt_hours(s_.weekly_work_days)}일 근무하는 단시간근로자(1주 {fmt_hours(weekly)}h)는 주휴시간을 1일 평균 "
            f"소정근로시간({fmt_hours(weekly_holiday_hours(s_.weekly_work_days, s_.daily_work_hours)[0])}h, 대법원 2022다291153)으로 "
            f"보면 실질시급 {effective_hourly:,.0f}원, 같은 업무 통상 근로자가 주 5일 근무해 그 소정근로일 수로 나누면"
            f"({fmt_hours(min(weekly / 5, 8.0))}h, 근로기준법 시행령 별표 2 제2호나목) {alt_effective:,.0f}원이라 {min_name}"
            f"({legal_minimum:,.0f}원) 충족 여부가 갈립니다 — 판정하지 않았습니다. 통상 근로자의 근무 형태를 확인하세요."
        )
    if platform:
        warnings.append(
            "노무제공자(특수형태근로종사자)는 원칙적으로 최저임금법의 근로자가 아니어서 최저임금 판정을 하지 않았습니다"
            "(최저임금법 제2조 — 근로기준법상 근로자). 실제로 사용종속관계가 인정되면 최저임금이 적용되고, 그때는 실질시급 "
            f"{effective_hourly:,.0f}원 {'≥' if is_compliant else '<'} {statutory_minimum:,.0f}원"
            f"({'충족' if is_compliant else '미달'})입니다."
        )
    elif not undetermined and not is_compliant:
        warnings.append(
            f"최저임금 미달: 실질시급 {effective_hourly:,.0f}원 < {legal_minimum:,.0f}원"
            f"{'(수습 감액 최저임금)' if legal_minimum != statutory_minimum else ''} "
            f"(부족분 {shortage_hourly:,.0f}원/h, 월 {shortage_monthly:,.0f}원)"
        )
        legal.append("최저임금법 제6조제1항 위반 가능성 — 노동청 신고 가능")
    elif not undetermined:
        formulas.append(
            f"충족: {effective_hourly:,.0f}원 ≥ {legal_minimum:,.0f}원"
            + ("(수습 감액 최저임금) " if legal_minimum != statutory_minimum else " ") +
            f"(초과 {effective_hourly - legal_minimum:,.0f}원/h)"
        )

    # ── breakdown ─────────────────────────────────────────────────────────────
    breakdown: dict = {
        f"{year}년 법정 최저시급": f"{statutory_minimum:,.0f}원",
        "실질 시급":              f"{effective_hourly:,.0f}원",
        "충족 여부":              ("➖ 해당 없음(노무제공자)" if platform else "⏸ 판정 보류" if undetermined
                                  else "✅ 충족" if is_compliant else "❌ 미달"),
        "월 근로시간":            f"{fmt_hours(monthly_hours)}h",
        "기본급 월액":            f"{base_monthly:,.0f}원",
    }
    if legal_minimum != statutory_minimum or probation_alt is not None:
        breakdown["수습 감액 최저시급"] = (f"{probation_reduced:,.0f}원"
                                     + ("" if legal_minimum != statutory_minimum else "(요건을 모두 갖춘 경우)"))
    if std_included:
        breakdown["전액산입 수당"] = f"{std_included:,.0f}원"
    if bonus_total:
        breakdown["정기상여금 (월 환산)"] = f"{bonus_total:,.0f}원"
        if bonus_excl_rate > 0:
            breakdown["  ├ 제외 기준액"] = (
                f"{bonus_excl_threshold:,.0f}원 ({bonus_excl_rate:.0%})"
            )
        breakdown["  └ 실제 산입액"] = f"{bonus_included:,.0f}원"
    if welfare_total:
        breakdown["복리후생비 (월 환산)"] = f"{welfare_total:,.0f}원"
        if welfare_excl_rate > 0:
            breakdown["  ├ 제외 기준액 "] = (
                f"{welfare_excl_threshold:,.0f}원 ({welfare_excl_rate:.0%})"
            )
        breakdown["  └ 실제 산입액 "] = f"{welfare_included:,.0f}원"
    breakdown["산입 월 임금 합계"] = f"{included_monthly:,.0f}원"
    breakdown["부족분(월)"] = f"{shortage_monthly:,.0f}원" if shortage_monthly > 0 else "-"

    if allowance_rows:
        breakdown["── 수당 산입 내역 ──"] = ""
        for name, amt, label in allowance_rows:
            breakdown[f"  {name}"] = f"{amt:,.0f}원/월  [{label}]"

    return MinimumWageResult(
        is_compliant=is_compliant,
        effective_hourly=round(effective_hourly, 0),
        legal_minimum=round(legal_minimum, 0),
        shortage_monthly=round(shortage_monthly, 0),
        reference_year=year,
        monthly_hours_used=monthly_hours,
        undetermined=undetermined,
        not_applicable=platform,
        alternative_minimum=round(probation_alt, 0) if probation_split else 0.0,
        alternative_hourly=(round(alt_effective, 0) if annex_split else round(ot_effective, 0) if ot_split else 0.0),
        alternative_hourlies=tuple(round(v, 0) for v, split in ((alt_effective, annex_split), (ot_effective, ot_split))
                                   if split),
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=list(dict.fromkeys(legal)),
    )


# ── 헬퍼 함수 ─────────────────────────────────────────────────────────────────

def _is_elementary_worker(occupation_code: str | None) -> bool:
    """한국표준직업분류 대분류 9(단순노무종사자) 해당 여부 판별.

    occupation_code가 "9", "91", "9100", "91001" 등 어느 단계든
    ELEMENTARY_OCCUPATION_CODES에 포함되거나 "9"로 시작하면 True.
    """
    if not occupation_code:
        return False
    code = occupation_code.strip()
    if code in ELEMENTARY_OCCUPATION_CODES:
        return True
    # 코드가 "9"로 시작하면 단순노무종사자 대분류
    if code.startswith("9"):
        return True
    return False


def _annex_alternative_hours(inp: WageInput, monthly_hours: float) -> float | None:
    """단시간근로자의 시행령 별표 2 기준(통상 근로자 주 5일) 월 기준시간. 해당하지 않으면 None.

    주 5일 이하면 원칙(÷ 소정근로일 수, 5일 미만은 5일)과 같은 값이라 판정이 갈리지 않는다 — 갈리는 것은 주 5일을 넘는
    경우뿐이다. 주 40시간 이상은 단시간근로자가 아니라 별표 2 대상이 아니다. 기준시간이 근무 형태에서 나온 경우만 본다 —
    월 소정근로시간 직접 입력·교대제 기준시간은 이 산식이 아니다."""
    s = inp.schedule
    weekly = s.daily_work_hours * s.weekly_work_days
    if not (WEEKLY_HOLIDAY_MIN_HOURS <= weekly < WEEKLY_FULL_HOURS):
        return None
    principle = (weekly + weekly_holiday_hours(s.weekly_work_days, s.daily_work_hours)[0]) * WEEKS_PER_MONTH
    if abs(monthly_hours - principle) > 1e-6:
        return None
    return (weekly + min(weekly / 5, 8.0)) * WEEKS_PER_MONTH


_PROBATION_REQ_LABEL = {"contract": "1년 이상의 기간을 정한 근로계약", "within": "수습을 시작한 날부터 3개월 이내",
                        "occupation": "단순노무업무로 고시한 직종이 아님"}
_PROBATION_FAIL_TEXT = {
    "contract": lambda inp: (f"근로계약기간이 {inp.contract_months}개월로 1년 미만이라 수습이어도 최저임금을 감액할 수 없습니다"
                             "(최저임금법 제5조 제2항)."),
    "within": lambda inp: ("수습을 시작한 날부터 3개월이 지나 최저임금을 감액할 수 없습니다(최저임금법 제5조 제2항 — 감액은 "
                           "3개월 이내만)."),
    "occupation": lambda inp: ("단순노무업무로 고용노동부장관이 고시한 직종(한국표준직업분류 대분류 9)은 수습이어도 최저임금을 "
                               "감액할 수 없습니다(최저임금법 제5조 제2항 단서)."),
}


def _probation_requirements(inp: WageInput) -> dict:
    """수습 감액 요건 셋의 확인 결과 — True 충족, False 불충족, None 질문에서 확인하지 못함."""
    # 계약기간이 숫자로 있으면 그것이 먼저다 — '정규직 전환 전 6개월 계약'처럼 '정규직'이 다른 뜻으로 함께 나온다
    if inp.contract_months is not None:
        contract = inp.contract_months >= PROBATION_MIN_CONTRACT_MONTHS
    elif inp.contract_open_ended:
        contract = True
    else:
        contract = None
    if inp.probation_elapsed_months is not None:
        within = inp.probation_elapsed_months <= PROBATION_MAX_MONTHS
    elif inp.probation_months is not None and inp.probation_months <= PROBATION_MAX_MONTHS:
        within = True              # 수습 기간이 3개월 이하면 수습 중인 지금은 3개월 이내다
    else:
        within = None
    occupation = None if not inp.occupation_code else not _is_elementary_worker(inp.occupation_code)
    return {"contract": contract, "within": within, "occupation": occupation}


def _ot_included_ratio(inp: WageInput, monthly_hours: float) -> float | None:
    """일급·월급·연봉에 연장·야간·휴일 근로 임금이 들어 있다고 볼 때 기본 임금 중 소정근로(+주휴) 몫의 비율. 해당 없으면 None.

    계수는 포괄임금 역산(comprehensive._calc_coefficient_hours, 대법원 2020다300299 방식)과 같다 — 연장·휴일은 (1 + 가산),
    야간은 가산분만. 일급은 그날의 소정근로 대가라 주휴를 빼고, 월급·연봉은 주휴를 포함한 1주 시간으로 나눈다.
    임금 구성을 질문으로 확인한 경로(pipeline — 구성 진술·포괄임금제)와 포괄임금 명세가 있으면 쓰지 않는다."""
    # 연장 등을 따로 받는다고 했으면 구성이 정해졌다(리뷰 M1). 노무제공자는 연장 가산이 적용되는 근로자가 아니다(리뷰 M3)
    if (inp.wage_composition_known or inp.comprehensive_breakdown or inp.premium_paid_separately
            or inp.is_platform_worker):
        return None
    if inp.wage_type not in (WageType.DAILY, WageType.MONTHLY, WageType.ANNUAL):
        return None
    s = inp.schedule
    mc = MultiplierContext(inp)
    coeff = (s.weekly_overtime_hours * (1 + mc.overtime) + s.weekly_night_hours * mc.night
             + s.weekly_holiday_hours * (1 + mc.holiday)
             + s.weekly_holiday_overtime_hours * (1 + mc.holiday + mc.holiday_ot))
    if coeff <= 0:
        return None
    if inp.wage_type == WageType.DAILY:
        base = (s.daily_work_hours or 8.0) * (s.weekly_work_days or 5.0)
    else:
        base = monthly_hours / WEEKS_PER_MONTH
    return base / (base + coeff) if base > 0 else None


def _get_base_monthly(inp: WageInput, monthly_hours: float) -> float:
    """기본급만 월 환산 (fixed_allowances 미포함)"""
    if inp.wage_type == WageType.HOURLY:
        return (inp.hourly_wage or 0.0) * monthly_hours
    elif inp.wage_type == WageType.DAILY:
        daily = inp.daily_wage or 0.0
        dh    = inp.schedule.daily_work_hours or 8.0
        return (daily / dh) * monthly_hours
    elif inp.wage_type in (WageType.MONTHLY, WageType.COMPREHENSIVE):
        if inp.wage_type == WageType.COMPREHENSIVE and inp.comprehensive_breakdown:
            return float(inp.comprehensive_breakdown.get("base", inp.monthly_wage or 0.0))
        return inp.monthly_wage or 0.0
    elif inp.wage_type == WageType.ANNUAL:
        return (inp.annual_wage or 0.0) / 12
    return 0.0


def _monthly_amount_fa(a) -> float:
    """수당 월 환산 금액 — FixedAllowance 속성 접근"""
    return a.monthly_amount
