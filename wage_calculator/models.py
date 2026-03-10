"""
임금계산기 입력 데이터 스키마
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional
from enum import Enum


class WageType(Enum):
    """임금 지급 형태"""
    HOURLY        = "시급"
    DAILY         = "일급"
    MONTHLY       = "월급"
    ANNUAL        = "연봉"
    COMPREHENSIVE = "포괄임금제"   # 총액에 수당이 포함된 경우 역산 필요


class WorkType(Enum):
    """근무 형태"""
    REGULAR      = "정규직"
    CONTRACT     = "계약직"
    PART_TIME    = "파트타임"
    DAILY_WORKER = "일용직"
    SHIFT_4_2    = "4조2교대"
    SHIFT_3_2    = "3조2교대"
    SHIFT_3      = "3교대"
    SHIFT_2      = "2교대"
    ROTATING     = "교대근무"   # 기타 교대


class AllowanceCondition(Enum):
    """
    수당 지급 조건 유형 — fixed_allowances 각 항목의 "condition" 키에 사용
    대법원 2023다302838 (2024.12.19) 판결 반영

    사용 예:
        {"name": "분기상여금", "amount": 600000, "condition": "재직조건",
         "payment_cycle": "분기", "is_ordinary": False}
        → 새 판결에 따라 통상임금 포함 처리됨
    """
    NONE        = "없음"     # 조건 없음 — 통상임금 해당 (정기성·일률성 있으면)
    ATTENDANCE  = "근무일수"  # 소정근로일수 이내 조건 — 통상임금 인정 (2023다302838)
    EMPLOYMENT  = "재직조건"  # 재직자만 지급 — 통상임금 인정 (2023다302838)
    PERFORMANCE = "성과조건"  # 성과·목표 달성 조건 — 통상임금 제외
    GUARANTEED_PERFORMANCE = "최소보장성과"  # 최소지급분 보장 성과급 — 보장분만 통상임금 포함


class BusinessSize(Enum):
    """
    사업장 규모 — 근로기준법 적용 범위 결정
    5인 미만: 연장/야간/휴일 가산수당 미적용 (근로기준법 제56조 제외)
    """
    UNDER_5  = "5인미만"
    OVER_5   = "5인이상"
    OVER_10  = "10인이상"
    OVER_30  = "30인이상"
    OVER_300 = "300인이상"


class WorkerType(Enum):
    """근로자 유형 — 상시근로자 수 산정 시 포함/제외 판별"""
    REGULAR        = "통상"        # 통상근로자 → 포함
    CONTRACT       = "기간제"      # 기간제 → 포함
    PART_TIME      = "단시간"      # 단시간 → 포함
    DAILY          = "일용"        # 일용직 → 포함 (해당 가동일만)
    SHIFT          = "교대"        # 교대근무 → 포함 (비번일 포함)
    FOREIGN        = "외국인"      # 외국인 → 포함
    FAMILY         = "가족"        # 가족근로자 → 조건부 포함
    OVERSEAS_LOCAL = "해외현지법인"  # 해외 현지법인 소속 → 제외
    DISPATCHED     = "파견"        # 파견근로자 → 제외 (파견법 제2조)
    OUTSOURCED     = "용역"        # 외부용역 → 제외 (도급업체 소속)
    OWNER          = "대표자"      # 대표자/비근로자 → 제외


@dataclass
class WorkSchedule:
    """근무 스케줄 — 소정근로 및 초과근로 시간 정보"""
    # 소정근로
    daily_work_hours: float = 8.0           # 1일 소정근로시간
    weekly_work_days: float = 5.0           # 주 소정근로일수
    monthly_scheduled_hours: Optional[float] = None  # 월 소정근로시간 (None이면 자동 계산)

    # 연장/야간/휴일 근로 (주 평균 또는 해당 월 기준)
    weekly_overtime_hours: float = 0.0           # 주 연장근로시간
    weekly_night_hours: float = 0.0              # 주 야간근로시간 (22~06시)
    weekly_holiday_hours: float = 0.0            # 주 휴일근로시간 (8h 이내)
    weekly_holiday_overtime_hours: float = 0.0   # 휴일근로 8h 초과분

    # 교대근무 전용
    shift_monthly_hours: Optional[float] = None  # 교대근무 월 실근로시간 (None이면 자동 조회)


@dataclass
class WageInput:
    """
    임금계산기 통합 입력 스키마

    최소 필수 입력: wage_type + 해당 임금액 (hourly/daily/monthly/annual_wage 중 1개)
    나머지는 계산 목적에 따라 선택적으로 입력
    """

    # ── 필수: 임금 형태 및 금액 ──────────────────────────────────────────────
    wage_type: WageType = WageType.MONTHLY

    hourly_wage: Optional[float] = None    # 시급 (원)
    daily_wage: Optional[float] = None     # 일급 (원)
    monthly_wage: Optional[float] = None   # 월 기본급 또는 포괄임금 총액 (원)
    annual_wage: Optional[float] = None    # 연봉 (원)

    # ── 사업장/근무 정보 ─────────────────────────────────────────────────────
    business_size: BusinessSize = BusinessSize.OVER_5
    work_type: WorkType = WorkType.REGULAR
    reference_year: int = field(default_factory=lambda: date.today().year)  # 기준 연도 (최저임금 등)

    # ── 근무 스케줄 ──────────────────────────────────────────────────────────
    schedule: WorkSchedule = field(default_factory=WorkSchedule)

    # ── 통상임금 포함 고정수당 목록 ──────────────────────────────────────────
    # 예: [{"name": "직책수당", "amount": 100000, "is_ordinary": True},
    #      {"name": "상여금", "amount": 2400000, "is_ordinary": True, "annual": True}]
    # annual=True인 경우 amount를 12로 나누어 월 환산
    fixed_allowances: list = field(default_factory=list)

    # ── 포괄임금제 명세 ───────────────────────────────────────────────────────
    # 포괄임금제일 때 항목별 금액 명시 가능
    # 예: {"base": 2000000, "overtime_pay": 500000, "night_pay": 200000}
    comprehensive_breakdown: Optional[dict] = None

    # ── 재직기간 (퇴직금·연차 계산용) ───────────────────────────────────────
    start_date: Optional[str] = None       # 입사일 "YYYY-MM-DD"
    end_date: Optional[str] = None         # 퇴직일 (None이면 오늘)

    # ── 평균임금 산정용 최근 3개월 임금 ─────────────────────────────────────
    # 퇴직금 계산 시 사용. None이면 monthly_wage × 3으로 추정
    last_3m_wages: Optional[list] = None   # 최근 3개월 각 지급액 [m1, m2, m3]
    last_3m_days: Optional[int] = None     # 최근 3개월 총 일수 (기본 92일)

    # 퇴직금 평균임금 — 1년치 임금 (대법원 2023다302579 반영)
    # None이면 monthly_wage × 12 추정. 제공 시 3개월 vs 1년 중 유리한 쪽 선택
    last_1y_wages: Optional[list] = None   # 최근 1년 월별 지급액 [m1..m12]
    last_1y_days: Optional[int] = None     # 최근 1년 총 일수 (기본 365일)

    # 일용직 월 근무일수 (퇴직금 자격 판단용)
    daily_worker_monthly_days: Optional[int] = None  # 월 평균 근무일수 (4~15일 이상 시 퇴직금 인정)

    # ── 연차 계산용 ──────────────────────────────────────────────────────────
    annual_leave_used: float = 0.0         # 사용한 연차 일수
    attendance_rate: float = 1.0           # 출근율 (0.0~1.0, 기본 100%)
    use_fiscal_year: bool = False          # 회계연도(1/1) 기준 여부
    leave_use_promotion: bool = False      # 사용촉진제도 실시 여부 (근기법 제61조)
                                           # True면 미사용 연차수당 지급 의무 면제 가능
    first_year_leave_used: float = 0.0    # 1년 미만 기간 중 사용한 연차 (제60조③ 2년차 차감용)

    # ── 해고예고 계산용 ──────────────────────────────────────────────────────
    notice_days_given: int = 0             # 실제 해고예고일수
    dismissal_date: Optional[str] = None   # 해고 통보일
    tenure_months: Optional[int] = None    # 계속근로기간 (개월, None=미입력)
    is_seasonal_worker: bool = False       # 계절적 사업 4개월 이내 근로자
    is_force_majeure: bool = False         # 천재지변·근로자 귀책사유 해당

    # ── 주휴수당 계산용 ──────────────────────────────────────────────────────
    weekly_attendance_days: Optional[int] = None  # 주 실출근일수 (None이면 개근 가정)

    # ── 중도입사 일할계산용 ──────────────────────────────────────────────────
    join_date: Optional[str] = None                # 중도입사일
    first_month_worked_days: Optional[int] = None  # 입사 첫 달 근무일수

    # ── 수습기간 여부 ─────────────────────────────────────────────────────────
    is_probation: bool = False             # 수습기간 여부 (최저임금 90% 특례)
    probation_months: int = 3              # 수습기간 (개월)

    # ── 유급 공휴일 계산용 ────────────────────────────────────────────────────
    public_holiday_days: int = 0           # 비근무 유급 공휴일 일수

    # ── 4대보험·소득세 계산용 ─────────────────────────────────────────────────
    is_freelancer: bool = False            # 3.3% 사업소득 계약 여부 (True면 4대보험 미가입)
    tax_dependents: int = 1               # 부양가족 수 (본인 포함, 근로소득세 공제용)
    num_children_8_to_20: int = 0         # 8~20세 자녀 수 (자녀세액공제용, 소득세법 제59조의2)
    monthly_non_taxable: float = 200_000  # 월 비과세 소득 (식대 등, 기본 20만원)

    # ── 실업급여 계산용 ───────────────────────────────────────────────────────
    age: int = 0                           # 만 나이 (소정급여일수 50세 기준 구분)
    is_disabled: bool = False              # 장애인 여부 (50세 이상과 동일 급여일수)
    insurance_months: Optional[int] = None # 피보험기간 (개월). None이면 start/end_date 기반 계산
    is_involuntary_quit: bool = True       # 비자발적 이직 여부 (False면 예외 사유 필요)
    voluntary_quit_reason: str = ""        # 자발적 이직 예외 사유 (임금체불/통근불가/간호 등)

    # ── 육아휴직급여 계산용 ───────────────────────────────────────────────────
    parental_leave_months: int = 0              # 육아휴직 신청 개월 수 (최대 12개월)
    is_second_parent: bool = False              # 두 번째 육아휴직자 여부 (아빠 보너스 적용)
    reduced_work_hours_per_day: float = 0.0    # 육아기 근로시간 단축 시간/일 (0이면 미사용)

    # ── 출산전후휴가급여 계산용 ───────────────────────────────────────────────
    is_priority_support_company: bool = True    # 우선지원대상기업(중소기업) 여부
    is_multiple_birth: bool = False             # 다태아 여부 (True면 120일)

    # ── 근로장려금(EITC) 계산용 ─────────────────────────────────────────────
    household_type: str = ""              # "단독" / "홑벌이" / "맞벌이" (빈 문자열이면 자동 판정)
    annual_total_income: float = 0.0      # 연간 총소득 (원). 0이면 monthly_wage × 12로 추정
    spouse_income: float = 0.0            # 배우자 연간 총급여 (원). 가구유형 자동 판정용
    total_assets: float = 0.0             # 가구원 재산 합계 (원)
    num_children_under_18: int = 0        # 18세 미만 부양자녀 수
    has_elderly_parent: bool = False      # 70세 이상 직계존속 동거 여부

    # ── 임금체불 지연이자 계산용 ──────────────────────────────────────────────
    arrear_amount: float = 0.0                  # 미지급 임금 원금 (원)
    arrear_due_date: str = ""                   # 원래 지급예정일 "YYYY-MM-DD"
    arrear_calc_date: str = ""                  # 이자 계산 기준일 (빈 문자열이면 오늘)
    is_post_retirement_arrear: bool = False     # True이면 연 20% (퇴직 후 14일 초과)

    # ── 탄력적 근로시간제 계산용 ──────────────────────────────────────────────
    flexible_work_unit: str = ""               # "2주", "3개월", "6개월"
    weekly_hours_list: Optional[list] = None   # 단위기간 내 주별 실근로시간 리스트

    # ── 휴업수당 계산용 (근기법 제46조) ──────────────────────────────────────────
    shutdown_days: int = 0                         # 총 휴업일수
    shutdown_hours_per_day: Optional[float] = None # 부분 휴업: 1일 미근로 시간 (None=전일 휴업)
    is_employer_fault: bool = True                 # 사용자 귀책사유 (False=불가항력→미발생)
    shutdown_start_date: Optional[str] = None      # 휴업 시작일 (평균임금 산정 기준)

    # ── 산재보상금 계산용 ─────────────────────────────────────────────────────
    accident_date: Optional[str] = None          # 산재 발생일 "YYYY-MM-DD"
    disability_grade: int = 0                    # 장해등급 (1~14, 0=해당없음)
    disability_pension: bool = True              # 장해급여 연금 선택 (True=연금, False=일시금)
    severe_illness_grade: int = 0                # 중증요양상태 등급 (1~3, 0=해당없음)
    num_survivors: int = 0                       # 유족수 (1~4+, 0=해당없음)
    survivor_pension: bool = True                # 유족급여 연금 선택 (True=연금, False=일시금)
    sick_leave_days: int = 0                     # 요양(휴업) 일수
    is_deceased: bool = False                    # 사망 여부

    # ── 사업주 4대보험 계산용 ─────────────────────────────────────────────────
    company_size_category: str = "under_150"   # "under_150", "150_999", "over_1000"
    industry_accident_rate: float = 0.007      # 산재보험 업종별 요율 (기본 평균 0.7%)

    # ── 퇴직소득세 계산용 ──────────────────────────────────────────────────
    retirement_pay_amount: float = 0.0         # 퇴직급여 총액 (0이면 severance에서 자동)
    irp_transfer_amount: float = 0.0           # IRP 이체금액 (과세이연)
    retirement_exclude_months: int = 0         # 근속기간 제외월수
    retirement_add_months: int = 0             # 근속기간 가산월수

    # ── 퇴직연금 계산용 ──────────────────────────────────────────────────────
    pension_type: str = ""                     # "DB" / "DC" / "" (미입력)
    annual_wage_history: Optional[list] = None # DC: 연도별 연간임금총액 리스트
    dc_return_rate: float = 0.0               # DC: 연간 운용수익률 (0.0 = 0%)

    # ── 퇴직금 평균임금 가산용 ───────────────────────────────────────────────
    annual_bonus_total: float = 0.0            # 연간 상여금 총액
    unused_annual_leave_pay: float = 0.0       # 최종 미사용 연차수당

    # ── 상시근로자 수 산정용 (선택) ──────────────────────────────────────────
    business_size_input: Optional["BusinessSizeInput"] = None  # 제공 시 business_size 자동 산정


@dataclass
class WorkerEntry:
    """개별 근로자 정보 — 상시근로자 수 산정용"""
    worker_type: WorkerType = WorkerType.REGULAR
    start_date: str = ""              # 근로계약 효력발생일 "YYYY-MM-DD"
    end_date: Optional[str] = None    # 퇴직일 (None이면 재직중)
    is_on_leave: bool = False         # 휴직/휴가/결근/징계 중 여부 (포함 대상)
    is_leave_replacement: bool = False  # 휴직대체자 여부 (제외 대상)
    specific_work_days: Optional[list] = None  # 특정 요일만 출근 (0=월~6=일, None이면 상시)
    actual_work_dates: Optional[list] = None  # 일용직 실제 출근일 ["YYYY-MM-DD", ...]
    name: str = ""                    # 식별용 (선택)


@dataclass
class BusinessSizeInput:
    """상시근로자 수 산정 입력 (근로기준법 시행령 제7조의2)"""
    event_date: str = ""              # 법 적용 사유 발생일 "YYYY-MM-DD"
    workers: list = field(default_factory=list)  # list[WorkerEntry]
    non_operating_days: Optional[list] = None    # 비가동일 "YYYY-MM-DD" 목록 (None이면 토·일)
    is_family_only_business: bool = False        # 동거친족만 사용하는 사업장
    daily_headcount: Optional[dict] = None       # 간편 입력: {"YYYY-MM-DD": 인원수, ...}
