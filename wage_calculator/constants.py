"""
상수 정의: 연도별 최저임금, 법적 가산율, 기준 근로시간
"""

# ── 통상임금 관련 대법원 판결 ─────────────────────────────────────────────
# 대법원 2023다302838 (2024.12.19) — 통상임금 고정성 요건 폐기
# "정기성 + 일률성"만으로 통상임금 판단
# 재직조건·소정근로일수 이내 조건부 상여금도 통상임금 인정
ORDINARY_WAGE_2024_RULING      = "대법원 2023다302838 (2024.12.19)"
ORDINARY_WAGE_2024_RULING_DATE = "2024-12-19"

# ── 연도별 최저임금 (시급, 원) ──────────────────────────────────────────────
MINIMUM_HOURLY_WAGE: dict[int, int] = {
    2020: 8590,
    2021: 8720,
    2022: 9160,
    2023: 9620,
    2024: 9860,
    2025: 10030,
    2026: 10320,
}

# ── 근로기준법 가산율 ────────────────────────────────────────────────────────
OVERTIME_RATE        = 0.5   # 연장근로 가산 → 총 1.5배
NIGHT_PREMIUM_RATE   = 0.5   # 야간근로 가산 (22~06시), 연장과 중복 적용
HOLIDAY_RATE         = 0.5   # 휴일근로 가산 (8h 이내) → 총 1.5배
HOLIDAY_OT_RATE      = 0.5   # 휴일근로 8h 초과 추가 가산 → 총 2.0배

# ── 월 통상임금 환산 기준시간 ────────────────────────────────────────────────
# (주 40h + 주휴 8h) × 52주 / 12월 ≈ 209h (실무 기준)
MONTHLY_STANDARD_HOURS = 209.0

# ── 야간근로 시간대 ──────────────────────────────────────────────────────────
NIGHT_START_HOUR = 22   # 22시 이후
NIGHT_END_HOUR   = 6    # 06시 이전

# ── 주휴수당 ─────────────────────────────────────────────────────────────────
WEEKLY_HOLIDAY_MIN_HOURS = 15.0    # 주 15시간 이상이어야 주휴수당 발생
WEEKLY_FULL_HOURS        = 40.0    # 주 만근 기준

# ── 퇴직금 ───────────────────────────────────────────────────────────────────
SEVERANCE_MIN_SERVICE_DAYS = 365   # 퇴직금 발생 최소 재직일수
AVG_WAGE_PERIOD_DAYS       = 92    # 평균임금 산정 3개월 기준 일수

# ── 해고예고 ─────────────────────────────────────────────────────────────────
DISMISSAL_NOTICE_DAYS = 30         # 해고예고 의무 일수

# ── 수습기간 최저임금 특례 ────────────────────────────────────────────────────
PROBATION_MIN_WAGE_RATE = 0.9      # 수습 3개월간 최저임금 90%
PROBATION_MAX_MONTHS    = 3

# ── 최저임금 산입범위 제외율 (최저임금법 제6조제4항, 2019년 개정) ─────────────
# 제외기준: 법정 최저임금 월액(최저임금 × 209h)의 일정 비율 이하는 산입 제외
# tuple: (정기상여금 제외율, 복리후생비 제외율)
# 2024년 이후 → 전액 산입 (0.0, 0.0)
MIN_WAGE_INCLUSION_RATES: dict[int, tuple[float, float]] = {
    2019: (0.25, 0.07),
    2020: (0.20, 0.05),
    2021: (0.15, 0.03),
    2022: (0.10, 0.02),
    2023: (0.05, 0.01),
}


def get_min_wage_inclusion_rates(year: int) -> tuple[float, float]:
    """연도별 최저임금 산입범위 제외율 반환
    Returns: (bonus_excl_rate, welfare_excl_rate)
    2024년 이후 (또는 데이터 없는 연도): (0.0, 0.0) — 전액 산입
    """
    return MIN_WAGE_INCLUSION_RATES.get(year, (0.0, 0.0))

# ── 교대근무 유형별 월 소정근로시간 ──────────────────────────────────────────
SHIFT_MONTHLY_HOURS: dict[str, float] = {
    "4조2교대": 182.5,   # 12h 격일제
    "3조2교대": 209.0,   # 8h 교대, 표준 기준
    "3교대":   195.5,   # 24/3 = 8h 교대, 월 평균
    "2교대":   209.0,   # 스케줄에 따라 별도 산정 가능
}

# ── 연차 ─────────────────────────────────────────────────────────────────────
ANNUAL_LEAVE_MAX_DAYS    = 25      # 최대 발생 연차 일수
ANNUAL_LEAVE_BASE_DAYS   = 15      # 1년 이상 기본 연차
ANNUAL_LEAVE_ADD_YEARS   = 2       # N년마다 1일 추가
ANNUAL_LEAVE_ADD_MAX     = 10      # 추가 연차 최대 10일
ANNUAL_LEAVE_FIRST_YEAR_MAX = 11   # 1년 미만 월 발생 최대 11일

# ── 4대보험 요율 (연도별, 근로자 부담분) ────────────────────────────────────
# 국민연금: 전체 요율의 절반 (근로자 = 사업주 동일)
# 건강보험: 전체 요율의 절반
# 장기요양: 건강보험료(근로자 부담분) 대비 비율
# 고용보험: 실업급여 부분만 (근로자 = 사업주 동일)

INSURANCE_RATES: dict[int, dict] = {
    2025: {
        "national_pension":    0.045,     # 9.0% × 1/2
        "health_insurance":    0.03545,   # 7.09% × 1/2
        "long_term_care":      0.1295,    # 건강보험료 × 12.95%
        "employment_insurance": 0.009,    # 1.8% × 1/2
        "pension_income_max":  6_170_000,
        "pension_income_min":    390_000,
    },
    2026: {
        "national_pension":    0.0475,    # 9.5% × 1/2  (+0.25%p)
        "health_insurance":    0.03595,   # 7.19% × 1/2  (+0.05%p)
        "long_term_care":      0.1314,    # 건강보험료 × 13.14%  (+0.19%p)
        "employment_insurance": 0.009,    # 1.8% × 1/2  (동결)
        "pension_income_max":  6_170_000, # 2026년 7월 결정 예정 — 잠정 동일
        "pension_income_min":    390_000,
    },
}

# 연도별 요율 조회 헬퍼 (해당 연도 없으면 가장 최근 연도 반환)
def get_insurance_rates(year: int) -> dict:
    if year in INSURANCE_RATES:
        return INSURANCE_RATES[year]
    latest = max(INSURANCE_RATES.keys())
    return INSURANCE_RATES[latest]

# 하위 호환 상수 (2025년 기준 — 내부 참조용)
NATIONAL_PENSION_RATE       = INSURANCE_RATES[2025]["national_pension"]
NATIONAL_PENSION_INCOME_MAX = INSURANCE_RATES[2025]["pension_income_max"]
NATIONAL_PENSION_INCOME_MIN = INSURANCE_RATES[2025]["pension_income_min"]
HEALTH_INSURANCE_RATE       = INSURANCE_RATES[2025]["health_insurance"]
LONG_TERM_CARE_RATE         = INSURANCE_RATES[2025]["long_term_care"]
EMPLOYMENT_INSURANCE_RATE   = INSURANCE_RATES[2025]["employment_insurance"]

# 산재보험: 사업주 전액 부담 (근로자 0%)
INDUSTRIAL_ACCIDENT_RATE    = 0.0       # 근로자 부담 없음

# ── 3.3% 프리랜서(사업소득) 원천징수 ────────────────────────────────────────
FREELANCER_TAX_RATE         = 0.033     # 소득세 3% + 지방소득세 0.3%

# ── 근로소득세 간이세액표 (2025년 기준, 비과세 소득 200,000원 제외 후 적용) ─
# {(하한, 상한): {부양가족수: 세액}} — 주요 구간만 발췌, 1인 기준 간략화
# 실무에서는 국세청 간이세액표를 참고하며, 여기서는 근사 산출식 사용
# 근로소득세 = 과세표준 × 세율 - 누진공제
INCOME_TAX_BRACKETS = [
    # (과세표준 상한, 세율, 누진공제)
    (14_000_000,   0.06,           0),
    (50_000_000,   0.15,   1_260_000),
    (88_000_000,   0.24,   5_760_000),
    (150_000_000,  0.35,  15_440_000),
    (300_000_000,  0.38,  19_940_000),
    (500_000_000,  0.40,  25_940_000),
    (1_000_000_000, 0.42, 35_940_000),
    (float("inf"), 0.45,  65_940_000),
]

# 근로소득 공제 (연간 기준)
# 총급여 구간별 공제율 [(상한, 공제액, 초과분 공제율)]
EARNED_INCOME_DEDUCTION = [
    (5_000_000,       0.70, 0),
    (15_000_000,  3_500_000, 0.40),
    (45_000_000,  7_500_000, 0.15),
    (100_000_000, 12_000_000, 0.05),
    (float("inf"), 14_750_000, 0.02),
]

# 근로소득 기본공제 (인당 연 150만원)
PERSONAL_DEDUCTION_PER_PERSON = 1_500_000

# ── 상시근로자 수 산정 (근로기준법 시행령 제7조의2) ───────────────────────
CALCULATION_PERIOD_MONTHS = 1          # 산정기간 1개월
DEFAULT_NON_OPERATING_WEEKDAYS = [5, 6]  # 토(5), 일(6) — 기본 비가동일
