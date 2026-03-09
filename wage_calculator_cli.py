#!/usr/bin/env python3
"""
임금계산기 CLI — 테스트 및 독립 실행

사용법:
  python3 wage_calculator_cli.py                # 전체 테스트 케이스 실행
  python3 wage_calculator_cli.py --case 1       # 특정 케이스만 실행
  python3 wage_calculator_cli.py --interactive  # 대화형 입력 모드
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from wage_calculator import WageCalculator, WageInput, WageType, WorkType, BusinessSize, WorkSchedule, AllowanceCondition
from wage_calculator import WorkerType, WorkerEntry, BusinessSizeInput
from wage_calculator.calculators.business_size import calc_business_size
from wage_calculator.result import format_result


# ── 테스트 케이스 정의 ────────────────────────────────────────────────────────

TEST_CASES = [
    {
        "id": 1,
        "desc": "시급 근로자 — 연장·야간근무 + 최저임금 검증",
        "input": WageInput(
            wage_type=WageType.HOURLY,
            hourly_wage=12000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            schedule=WorkSchedule(
                daily_work_hours=8,
                weekly_work_days=5,
                weekly_overtime_hours=10,
                weekly_night_hours=4,
            ),
        ),
        "targets": ["overtime", "minimum_wage", "weekly_holiday"],
    },
    {
        "id": 2,
        "desc": "월급 근로자 — 최저임금 충족 여부 (5인 미만 사업장)",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=2090000,
            business_size=BusinessSize.UNDER_5,
            reference_year=2025,
            schedule=WorkSchedule(
                daily_work_hours=8,
                weekly_work_days=5,
                weekly_overtime_hours=8,
            ),
        ),
        "targets": ["minimum_wage", "overtime"],
    },
    {
        "id": 3,
        "desc": "포괄임금제 역산 — 월 300만원 (기본급 200만원, 연장수당 100만원 포함)",
        "input": WageInput(
            wage_type=WageType.COMPREHENSIVE,
            monthly_wage=3000000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            comprehensive_breakdown={
                "base": 2000000,
                "overtime_pay": 800000,
                "night_pay": 200000,
            },
            schedule=WorkSchedule(
                daily_work_hours=8,
                weekly_work_days=5,
                weekly_overtime_hours=20,
                weekly_night_hours=8,
            ),
        ),
        "targets": ["comprehensive", "minimum_wage"],
    },
    {
        "id": 4,
        "desc": "4조2교대 — 월 182.5h 기준 최저임금 검증",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=2500000,
            business_size=BusinessSize.OVER_5,
            work_type=WorkType.SHIFT_4_2,
            reference_year=2025,
            schedule=WorkSchedule(
                daily_work_hours=12,
                weekly_work_days=3.5,    # 평균 격일 근무
                weekly_night_hours=6,    # 야간조
            ),
        ),
        "targets": ["minimum_wage", "overtime"],
    },
    {
        "id": 5,
        "desc": "연차수당 — 3년 근속자 미사용 연차 10일",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3500000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            start_date="2022-01-01",
            end_date="2025-01-01",
            annual_leave_used=5,
        ),
        "targets": ["annual_leave"],
    },
    {
        "id": 6,
        "desc": "해고예고수당 — 10일 전 해고 통보",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=2800000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            notice_days_given=10,
            dismissal_date="2025-03-01",
        ),
        "targets": ["dismissal"],
    },
    {
        "id": 7,
        "desc": "파트타임 주 20시간 — 주휴수당 + 최저임금",
        "input": WageInput(
            wage_type=WageType.HOURLY,
            hourly_wage=10030,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            schedule=WorkSchedule(
                daily_work_hours=4,
                weekly_work_days=5,
                monthly_scheduled_hours=104.5,  # 20h/주 × 52/12
            ),
        ),
        "targets": ["weekly_holiday", "minimum_wage"],
    },
    {
        "id": 8,
        "desc": "수습기간 — 최저임금 90% 특례",
        "input": WageInput(
            wage_type=WageType.HOURLY,
            hourly_wage=9030,    # 최저임금 90% 수준
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            is_probation=True,
            probation_months=3,
        ),
        "targets": ["minimum_wage"],
    },
    {
        "id": 9,
        "desc": "중도입사 일할계산 — 3월 15일 입사, 월급 250만원",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=2500000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            join_date="2025-03-15",
        ),
        "targets": ["prorated", "minimum_wage"],
    },
    {
        "id": 10,
        "desc": "유급 공휴일 — 5인 이상, 광복절·추석 연휴 3일 비근무",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3000000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            public_holiday_days=3,
            schedule=WorkSchedule(daily_work_hours=8, weekly_work_days=5),
        ),
        "targets": ["public_holiday", "minimum_wage"],
    },
    {
        "id": 11,
        "desc": "대법원 2023다302838 — 재직조건부 분기상여금 통상임금 반영",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=2500000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            schedule=WorkSchedule(
                daily_work_hours=8,
                weekly_work_days=5,
                weekly_overtime_hours=8,
            ),
            fixed_allowances=[
                {
                    "name": "분기상여금",
                    "amount": 1500000,   # 분기당 150만원
                    "is_ordinary": False,  # 기존에는 재직조건부라 제외 처리
                    "condition": "재직조건",  # 대법원 판결로 자동 포함 처리
                    "payment_cycle": "분기",
                },
                {
                    "name": "식대",
                    "amount": 200000,
                    "is_ordinary": True,
                    "condition": "없음",
                },
            ],
        ),
        "targets": ["overtime", "minimum_wage", "legal_hints"],
    },
    {
        "id": 12,
        "desc": "연차 역월 기준 수정 — 1월 1일 입사, 7월 15일 기준 (완성 6개월)",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=2500000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            start_date="2025-01-01",
            end_date="2025-07-15",   # 211일 경과, 완성 6개월
            annual_leave_used=0,
        ),
        "targets": ["annual_leave"],
    },
    {
        "id": 15,
        "desc": "퇴직금 — 3년 근속, 월급 350만원 (3개월 vs 1년 평균임금 비교)",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3500000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            start_date="2022-01-01",
            end_date="2025-01-01",
            # 퇴직 직전 3개월 임금이 낮아진 사례 (대법원 2023다302579 판결 요건)
            last_3m_wages=[2_800_000, 2_900_000, 2_800_000],   # 퇴직 전 3개월 임금
            last_3m_days=92,
            last_1y_wages=[
                3_500_000, 3_500_000, 3_500_000, 3_500_000,
                3_500_000, 3_500_000, 3_500_000, 3_500_000,
                3_500_000, 2_800_000, 2_900_000, 2_800_000,
            ],  # 최근 1년 (마지막 3개월 감소)
        ),
        "targets": ["severance"],
    },
    {
        "id": 16,
        "desc": "퇴직금 — 일용직 근로자 4년 근속, 월 12일 근무 (대법원 2023다302579)",
        "input": WageInput(
            wage_type=WageType.DAILY,
            daily_wage=200000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            work_type=WorkType.DAILY_WORKER,
            start_date="2021-01-01",
            end_date="2025-01-01",
            daily_worker_monthly_days=12,  # 월 12일 근무
        ),
        "targets": ["severance"],
    },
    {
        "id": 13,
        "desc": "4대보험·소득세 — 월급 300만원, 부양가족 2인 (근로자)",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3000000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            schedule=WorkSchedule(daily_work_hours=8, weekly_work_days=5),
            tax_dependents=2,
            monthly_non_taxable=200000,
        ),
        "targets": ["insurance", "minimum_wage"],
    },
    {
        "id": 14,
        "desc": "3.3% 프리랜서 계약 — 월 250만원, 실질 근로자 여부 안내 포함",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=2500000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            is_freelancer=True,
        ),
        "targets": ["insurance"],
    },
    {
        "id": 17,
        "desc": "실업급여 — 3년 근속 35세, 월급 300만원 (하한액 적용)",
        # 평균임금 일액: 3,000,000×3÷92 ≈ 97,826원  → 60% = 58,696원
        # 하한액(2025): 10,030×0.8×8 = 64,192원  → 하한 적용
        # 소정급여일수: 36개월 × 50세미만 → 180일
        # 총 구직급여: 64,192 × 180 = 11,554,560원
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3_000_000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            start_date="2022-01-01",
            end_date="2025-01-01",
            age=35,
            is_involuntary_quit=True,
        ),
        "targets": ["unemployment"],
    },
    {
        "id": 18,
        "desc": "실업급여 — 11년 근속 55세, 월급 600만원 (상한액 적용)",
        # 평균임금 일액: 6,000,000×3÷92 ≈ 195,652원  → 60% = 117,391원
        # 상한액: 66,000원  → 상한 적용
        # 소정급여일수: 132개월 × 50세이상 → 270일
        # 총 구직급여: 66,000 × 270 = 17,820,000원
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=6_000_000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            insurance_months=132,   # 11년 피보험기간 직접 지정
            age=55,
            is_involuntary_quit=True,
        ),
        "targets": ["unemployment"],
    },
    {
        "id": 19,
        "desc": "실업급여 — 자발적 이직 + 임금체불 예외 사유",
        # 자발적 이직이라도 임금체불이면 수급 자격 인정 가능
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=2_500_000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            insurance_months=24,
            age=40,
            is_involuntary_quit=False,       # 자발적 이직
            voluntary_quit_reason="임금체불",  # 예외 사유
        ),
        "targets": ["unemployment"],
    },
    {
        "id": 20,
        "desc": "실업급여 — 피보험기간 5개월 (수급 자격 없음)",
        # 피보험단위기간 150일 < 180일  → 수급 불가
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=2_500_000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            insurance_months=5,
            age=30,
            is_involuntary_quit=True,
        ),
        "targets": ["unemployment"],
    },
    # ── 신규 계산기 테스트 케이스 ────────────────────────────────────────────────
    {
        "id": 24,
        "desc": "보상휴가 환산 — 연장 10h + 야간 4h + 휴일 8h (월급 300만원)",
        # 연장: 10h × 1.5 = 15h  야간: 4h × 0.5 = 2h  휴일(8h이내): 8h × 1.5 = 12h
        # 총 보상휴가: 29h/주, 미사용 수당: 통상시급 × 29h/주
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3_000_000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            schedule=WorkSchedule(
                daily_work_hours=8,
                weekly_work_days=5,
                weekly_overtime_hours=10,
                weekly_night_hours=4,
                weekly_holiday_hours=8,
            ),
        ),
        "targets": ["compensatory_leave"],
    },
    {
        "id": 25,
        "desc": "임금체불 지연이자 — 퇴직 후 2개월 미지급 (연 20%), 원금 200만원",
        # 지연이자: 2,000,000 × 20% × (60/365) = 65,753원
        # 총 청구액: 2,065,753원
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=2_000_000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            arrear_amount=2_000_000,
            arrear_due_date="2024-12-31",
            is_post_retirement_arrear=True,
            arrear_calc_date="2025-03-01",
        ),
        "targets": ["wage_arrears"],
    },
    {
        "id": 26,
        "desc": "육아휴직급여 — 월급 400만원, 6개월, 첫 번째 사용자",
        # 통상임금 4,000,000원 → 80% = 3,200,000원 → 상한 1,500,000원 적용
        # 매월: 1,500,000 × 75% = 1,125,000원 / 사후: 375,000원
        # 6개월 총: 1,125,000 × 6 = 6,750,000원 / 사후: 2,250,000원
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=4_000_000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            parental_leave_months=6,
            is_second_parent=False,
        ),
        "targets": ["parental_leave"],
    },
    {
        "id": 27,
        "desc": "육아휴직급여 — 아빠 보너스 (두 번째 사용자, 3개월)",
        # 통상임금 3,000,000원 → 100% = 3,000,000원 → 상한 2,500,000원 적용
        # 아빠 보너스 첫 3개월: 2,500,000 × 75% = 1,875,000원/월
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3_000_000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            parental_leave_months=3,
            is_second_parent=True,
        ),
        "targets": ["parental_leave"],
    },
    {
        "id": 28,
        "desc": "출산전후휴가급여 — 월급 350만원, 우선지원대상기업, 단태아",
        # 통상임금 3,500,000원 → 상한 2,094,270원 적용
        # 90일 전액 고용보험 지원 (우선지원대상기업)
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3_500_000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            is_priority_support_company=True,
            is_multiple_birth=False,
        ),
        "targets": ["maternity_leave"],
    },
    {
        "id": 29,
        "desc": "탄력적 근로시간제 — 2주 단위, 첫 주 50h + 둘째 주 30h",
        # 총 실근로: 80h  법정 기준: 40h × 2주 = 80h
        # 탄력제 연장근로: 0h  BUT 첫 주 50h > 한도 48h → 추가 가산 2h
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3_000_000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            flexible_work_unit="2주",
            weekly_hours_list=[50, 30],
        ),
        "targets": ["flexible_work"],
    },
    {
        "id": 30,
        "desc": "탄력적 근로시간제 — 3개월 단위, 성수기 편중 스케줄",
        # 13주: [52,52,52,52,48,48,48,48,32,32,32,32,32] = 560h
        # 법정 기준: 40h × 13 = 520h  탄력제 연장: 40h
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3_000_000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            flexible_work_unit="3개월",
            weekly_hours_list=[52, 52, 52, 52, 48, 48, 48, 48, 32, 32, 32, 32, 32],
        ),
        "targets": ["flexible_work"],
    },
    {
        "id": 31,
        "desc": "주 52시간 준수 체크 — 주 60시간 (위반)",
        # 소정 40h + 연장 15h + 휴일 5h = 60h → 8h 초과
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3_000_000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            schedule=WorkSchedule(
                daily_work_hours=8,
                weekly_work_days=5,
                weekly_overtime_hours=15,
                weekly_holiday_hours=5,
            ),
        ),
        "targets": ["weekly_hours_check", "overtime"],
    },
    {
        "id": 32,
        "desc": "사업주 4대보험 부담금 — 월급 300만원, 150인 미만 사업장",
        # 국민연금 4.5% + 건강보험 3.545% + 장기요양 + 고용보험 0.9%
        # + 직업능력개발 0.25% + 산재 0.7%
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3_000_000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            company_size_category="under_150",
            industry_accident_rate=0.007,
        ),
        "targets": ["employer_insurance", "insurance"],
    },
    # ── 최저임금 산입범위 테스트 케이스 (2019년 개정 최저임금법 제6조제4항) ───────
    {
        "id": 21,
        "desc": "최저임금 산입범위 — 2023년 기본급+분기상여+식대 (충족)",
        # 기본급 190만 + 분기상여 300만/분기(월100만) + 식대 10만
        # 2023년 최저임금: 9,620원  법정 최저 월액: 9,620 × 209 = 2,010,580원
        # 정기상여금 제외율 5%: 제외기준 100,529원 → 산입 899,471원
        # 복리후생비 제외율 1%: 제외기준 20,106원  → 산입  79,894원
        # 총 산입: 190만 + 899,471 + 79,894 = 2,879,365원
        # 실질시급: 2,879,365 ÷ 209 ≈ 13,778원  ✅
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=1_900_000,
            business_size=BusinessSize.OVER_5,
            reference_year=2023,
            fixed_allowances=[
                {
                    "name": "분기상여금",
                    "amount": 3_000_000,
                    "payment_cycle": "분기",
                    "min_wage_type": "regular_bonus",
                    "is_ordinary": True,
                },
                {
                    "name": "식대",
                    "amount": 100_000,
                    "min_wage_type": "welfare",
                    "is_ordinary": False,
                },
            ],
        ),
        "targets": ["minimum_wage"],
    },
    {
        "id": 22,
        "desc": "최저임금 산입범위 — 2025년 기본급+식대+월상여 (전액산입, 간신히 충족)",
        # 기본급 180만 + 식대 20만 + 월상여 10만
        # 2025년: bonus_excl_rate=0%, welfare_excl_rate=0% → 전액 산입
        # 총 산입: 180만 + 20만 + 10만 = 210만원
        # 실질시급: 2,100,000 ÷ 209 ≈ 10,048원 ≥ 10,030원  ✅
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=1_800_000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            fixed_allowances=[
                {
                    "name": "식대",
                    "amount": 200_000,
                    "min_wage_type": "welfare",
                    "is_ordinary": False,
                },
                {
                    "name": "월상여금",
                    "amount": 100_000,
                    "min_wage_type": "regular_bonus",
                    "is_ordinary": True,
                },
            ],
        ),
        "targets": ["minimum_wage"],
    },
    {
        "id": 23,
        "desc": "최저임금 산입범위 — 2023년 기본급+분기상여+식대 (미달)",
        # 기본급 160만 + 분기상여 60만/분기(월20만) + 식대 20만
        # 2023년: 정기상여 제외기준 100,529원 → 산입 max(0, 200,000-100,529)=99,471원
        #        복리후생 제외기준  20,106원  → 산입 max(0, 200,000-20,106)=179,894원
        # 총 산입: 160만 + 99,471 + 179,894 = 1,879,365원
        # 실질시급: 1,879,365 ÷ 209 ≈ 8,993원 < 9,620원  ❌
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=1_600_000,
            business_size=BusinessSize.OVER_5,
            reference_year=2023,
            fixed_allowances=[
                {
                    "name": "분기상여금",
                    "amount": 600_000,
                    "payment_cycle": "분기",
                    "min_wage_type": "regular_bonus",
                    "is_ordinary": True,
                },
                {
                    "name": "식대",
                    "amount": 200_000,
                    "min_wage_type": "welfare",
                    "is_ordinary": False,
                },
            ],
        ),
        "targets": ["minimum_wage"],
    },
    # ── 상시근로자 수 산정 테스트 케이스 (근로기준법 시행령 제7조의2) ─────────────
    {
        "id": 33,
        "desc": "상시근로자 수 — 기본 5인 이상 (통상 10명, 2025-03-01 기준)",
        # 10명 통상근로자, 가동일수 약 21~22일
        # 연인원 = 10 × 가동일수 → 상시근로자 수 = 10.0명 → 5인 이상
        "input": BusinessSizeInput(
            event_date="2025-03-01",
            workers=[
                WorkerEntry(name=f"직원{i+1}", worker_type=WorkerType.REGULAR, start_date="2024-01-02")
                for i in range(10)
            ],
        ),
        "targets": ["business_size"],
    },
    {
        "id": 34,
        "desc": "상시근로자 수 — 5인 미만 (3명 + 휴직자 포함, 휴직대체자 제외)",
        # 통상 3명 + 휴직자 1명(포함) + 휴직대체자 1명(제외) = 4명
        "input": BusinessSizeInput(
            event_date="2025-03-01",
            workers=[
                WorkerEntry(name="직원A", worker_type=WorkerType.REGULAR, start_date="2024-01-02"),
                WorkerEntry(name="직원B", worker_type=WorkerType.REGULAR, start_date="2024-01-02"),
                WorkerEntry(name="직원C", worker_type=WorkerType.REGULAR, start_date="2024-01-02"),
                WorkerEntry(name="직원D", worker_type=WorkerType.REGULAR, start_date="2024-01-02", is_on_leave=True),
                WorkerEntry(name="대체자E", worker_type=WorkerType.REGULAR, start_date="2024-06-01", is_leave_replacement=True),
            ],
        ),
        "targets": ["business_size"],
    },
    {
        "id": 35,
        "desc": "상시근로자 수 — 경계값 (3명 상시 + 2명 기간중 입사, 1/2 판정)",
        # 3명은 전체기간, 2명은 2025-02-15부터 → 후반 약 13일만 5인
        # 상시근로자 수 ≈ (3×가동일 + 2×후반가동일) / 가동일
        "input": BusinessSizeInput(
            event_date="2025-03-01",
            workers=[
                WorkerEntry(name="직원A", worker_type=WorkerType.REGULAR, start_date="2024-01-02"),
                WorkerEntry(name="직원B", worker_type=WorkerType.CONTRACT, start_date="2024-01-02"),
                WorkerEntry(name="직원C", worker_type=WorkerType.PART_TIME, start_date="2024-01-02"),
                WorkerEntry(name="직원D", worker_type=WorkerType.REGULAR, start_date="2025-02-15"),
                WorkerEntry(name="직원E", worker_type=WorkerType.REGULAR, start_date="2025-02-15"),
            ],
        ),
        "targets": ["business_size"],
    },
    {
        "id": 36,
        "desc": "상시근로자 수 — 혼합 유형 (교대·외국인·특정요일 근무자)",
        # 교대 2명(비번일 포함) + 외국인 1명 + 화목금 출근자 1명 + 해외법인 1명(제외)
        # 교대·외국인은 매일 포함, 특정요일 근무자는 화(1)·목(3)·금(4)만
        "input": BusinessSizeInput(
            event_date="2025-03-01",
            workers=[
                WorkerEntry(name="교대A", worker_type=WorkerType.SHIFT, start_date="2024-01-02"),
                WorkerEntry(name="교대B", worker_type=WorkerType.SHIFT, start_date="2024-01-02"),
                WorkerEntry(name="외국인C", worker_type=WorkerType.FOREIGN, start_date="2024-01-02"),
                WorkerEntry(name="화목금D", worker_type=WorkerType.PART_TIME, start_date="2024-01-02", specific_work_days=[1, 3, 4]),
                WorkerEntry(name="해외E", worker_type=WorkerType.OVERSEAS_LOCAL, start_date="2024-01-02"),
            ],
        ),
        "targets": ["business_size"],
    },
    # ── 근로장려금(EITC) 테스트 케이스 ─────────────────────────────────────────
    {
        "id": 37,
        "desc": "EITC — 단독 점증구간 (소득 300만, 재산 1억)",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=250_000,  # 참고용
            reference_year=2025,
            household_type="단독",
            annual_total_income=3_000_000,
            total_assets=100_000_000,
        ),
        "targets": ["eitc"],
    },
    {
        "id": 38,
        "desc": "EITC — 단독 평탄구간 (소득 600만, 재산 1억)",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=500_000,
            reference_year=2025,
            household_type="단독",
            annual_total_income=6_000_000,
            total_assets=100_000_000,
        ),
        "targets": ["eitc"],
    },
    {
        "id": 39,
        "desc": "EITC — 단독 소득초과 (소득 2,300만)",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=1_916_667,
            reference_year=2025,
            household_type="단독",
            annual_total_income=23_000_000,
            total_assets=100_000_000,
        ),
        "targets": ["eitc"],
    },
    {
        "id": 40,
        "desc": "EITC — 홑벌이 재산감액 (소득 1,000만, 재산 2억)",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=833_333,
            reference_year=2025,
            household_type="홑벌이",
            annual_total_income=10_000_000,
            total_assets=200_000_000,
            num_children_under_18=1,
        ),
        "targets": ["eitc"],
    },
    {
        "id": 41,
        "desc": "EITC — 맞벌이 점감구간 (소득 2,500만, 재산 1.5억)",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=2_083_333,
            reference_year=2025,
            household_type="맞벌이",
            annual_total_income=25_000_000,
            total_assets=150_000_000,
        ),
        "targets": ["eitc"],
    },
    {
        "id": 42,
        "desc": "EITC — 재산 초과 (홑벌이, 소득 500만, 재산 2.5억)",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=416_667,
            reference_year=2025,
            household_type="홑벌이",
            annual_total_income=5_000_000,
            total_assets=250_000_000,
        ),
        "targets": ["eitc"],
    },
    {
        "id": 43,
        "desc": "EITC — 자녀장려금 포함 (홑벌이, 소득 1,200만, 자녀 2명)",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=1_000_000,
            reference_year=2025,
            household_type="홑벌이",
            annual_total_income=12_000_000,
            total_assets=100_000_000,
            num_children_under_18=2,
        ),
        "targets": ["eitc"],
    },
    # ── 퇴직소득세 / 퇴직연금 테스트 케이스 ──────────────────────────────────────
    {
        "id": 44,
        "desc": "퇴직소득세 — 10년 근속, 퇴직금 3000만원 (IRP 없음)",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3_000_000,
            reference_year=2025,
            start_date="2015-01-02",
            end_date="2025-01-01",
        ),
        "targets": ["severance", "retirement_tax"],
    },
    {
        "id": 45,
        "desc": "퇴직소득세 — 5년 근속, 퇴직금 직접입력 + IRP 전액이체",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=2_500_000,
            reference_year=2025,
            start_date="2020-03-01",
            end_date="2025-02-28",
            retirement_pay_amount=15_000_000,
            irp_transfer_amount=15_000_000,
        ),
        "targets": ["retirement_tax"],
    },
    {
        "id": 46,
        "desc": "퇴직소득세 — 20년 근속, 상여금+연차수당 가산",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=4_000_000,
            reference_year=2025,
            start_date="2005-01-03",
            end_date="2025-01-02",
            annual_bonus_total=4_800_000,
            unused_annual_leave_pay=1_200_000,
        ),
        "targets": ["severance", "retirement_tax"],
    },
    {
        "id": 47,
        "desc": "퇴직연금 DB형 — 퇴직금 결과 연동 (10년 근속)",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3_000_000,
            reference_year=2025,
            start_date="2015-01-02",
            end_date="2025-01-01",
            pension_type="DB",
        ),
        "targets": ["severance", "retirement_pension"],
    },
    {
        "id": 48,
        "desc": "퇴직연금 DC형 — 5년, 운용수익률 3%",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3_000_000,
            reference_year=2025,
            start_date="2020-01-02",
            end_date="2025-01-01",
            pension_type="DC",
            dc_return_rate=0.03,
        ),
        "targets": ["retirement_pension"],
    },
    {
        "id": 49,
        "desc": "퇴직연금 DC형 — 연도별 임금이력 + 수익률 5%",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=4_000_000,
            reference_year=2025,
            pension_type="DC",
            annual_wage_history=[36_000_000, 38_000_000, 40_000_000, 42_000_000],
            dc_return_rate=0.05,
        ),
        "targets": ["retirement_pension"],
    },
    {
        "id": 50,
        "desc": "퇴직금+퇴직소득세+퇴직연금 통합 (3년 근속, DB형)",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3_500_000,
            reference_year=2025,
            start_date="2022-01-03",
            end_date="2025-01-02",
            pension_type="DB",
            irp_transfer_amount=5_000_000,
        ),
        "targets": ["severance", "retirement_tax", "retirement_pension"],
    },
    {
        "id": 51,
        "desc": "퇴직소득세 — 1년 미만 근속 (퇴직금 미발생, 직접입력 500만원)",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=2_500_000,
            reference_year=2025,
            start_date="2024-06-01",
            end_date="2025-01-01",
            retirement_pay_amount=5_000_000,
        ),
        "targets": ["retirement_tax"],
    },
    # ── 4대보험 절사·상한·자녀공제·산재구성요소 테스트 케이스 ──────────────────────
    {
        "id": 52,
        "desc": "4대보험 절사 규칙 — 월 3,000,000원, 비과세 200,000원",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3_000_000,
            reference_year=2025,
            monthly_non_taxable=200_000,
            tax_dependents=1,
        ),
        "targets": ["insurance"],
    },
    {
        "id": 53,
        "desc": "4대보험 국민연금 상한 — 월 6,170,000원",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=6_170_000,
            reference_year=2025,
            tax_dependents=3,
        ),
        "targets": ["insurance"],
    },
    {
        "id": 54,
        "desc": "4대보험 건강보험 상한 — 월 100,000,000원",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=100_000_000,
            reference_year=2025,
            tax_dependents=4,
        ),
        "targets": ["insurance"],
    },
    {
        "id": 55,
        "desc": "자녀세액공제 — 월 4,000,000원, 자녀 2명",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=4_000_000,
            reference_year=2025,
            tax_dependents=4,
            num_children_8_to_20=2,
        ),
        "targets": ["insurance"],
    },
    {
        "id": 56,
        "desc": "사업주 4대보험 — 산재보험 구성요소 (업종 1.5%)",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3_500_000,
            reference_year=2025,
            industry_accident_rate=0.015,
            company_size_category="150_999",
        ),
        "targets": ["employer_insurance"],
    },
    # ── 통상임금 리뷰 테스트 케이스 (nodong.kr 참조) ─────────────────────────
    {
        "id": 57,
        "desc": "최소보장 성과급 — 보장분만 통상임금 산입",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=2_500_000,
            reference_year=2025,
            fixed_allowances=[
                {
                    "name": "성과급",
                    "amount": 3_600_000,
                    "annual": True,
                    "condition": "최소보장성과",
                    "guaranteed_amount": 1_200_000,
                },
            ],
        ),
        "targets": ["minimum_wage"],
        # 기대: 월 통상임금 = 2,500,000 + (1,200,000/12) = 2,600,000
        #       통상시급 = 2,600,000 / 209 ≈ 12,440원
    },
    {
        "id": 58,
        "desc": "1일 통상임금 출력 검증 — 시급 근로자",
        "input": WageInput(
            wage_type=WageType.HOURLY,
            hourly_wage=10_030,
            reference_year=2025,
        ),
        "targets": ["minimum_wage"],
        # 기대: hourly=10,030, daily=80,240, monthly=2,096,270
    },
    {
        "id": 59,
        "desc": "일반 성과조건 제외 유지 — 보장분 없는 성과급",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3_000_000,
            reference_year=2025,
            fixed_allowances=[
                {
                    "name": "인센티브",
                    "amount": 5_000_000,
                    "annual": True,
                    "condition": "성과조건",
                },
            ],
        ),
        "targets": ["minimum_wage"],
        # 기대: 월 통상임금 = 3,000,000 (인센티브 제외)
        #       통상시급 = 3,000,000 / 209 ≈ 14,354원
    },

    # ────────────────────────────────────────────────────────────────────────────
    # #60~#64: 평균임금 독립 계산기 (average_wage)
    # ────────────────────────────────────────────────────────────────────────────

    {
        "id": 60,
        "desc": "평균임금 기본 산정 — 3개월 임금 float list",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3_000_000,
            reference_year=2025,
            last_3m_wages=[3_000_000, 3_000_000, 3_000_000],
            last_3m_days=92,
        ),
        "targets": ["average_wage"],
        # 기대: 3개월 총액 9,000,000 / 92일 = 97,826원/일
        #       통상임금 환산일급 = (3,000,000/209) × 8 = 114,832원/일
        #       → 통상임금이 더 높으므로 used_basis="통상임금"
    },
    {
        "id": 61,
        "desc": "평균임금 > 통상임금 — 3개월 기준 적용",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=2_500_000,
            reference_year=2025,
            last_3m_wages=[4_000_000, 4_000_000, 4_000_000],
            last_3m_days=92,
        ),
        "targets": ["average_wage"],
        # 기대: 3개월 총액 12,000,000 / 92일 = 130,435원/일
        #       통상임금 환산일급 = (2,500,000/209) × 8 = 95,694원/일
        #       → 평균임금이 더 높으므로 used_basis="3개월"
    },
    {
        "id": 62,
        "desc": "평균임금 상여금+연차수당 가산",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3_000_000,
            reference_year=2025,
            last_3m_wages=[3_000_000, 3_000_000, 3_000_000],
            last_3m_days=92,
            annual_bonus_total=2_400_000,
            unused_annual_leave_pay=600_000,
        ),
        "targets": ["average_wage"],
        # 기대: 임금총액 9,000,000
        #       상여금 가산: 2,400,000 × 3/12 = 600,000
        #       연차 가산: 600,000 × 3/12 = 150,000
        #       총액: 9,750,000 / 92일 = 105,978원/일
    },
    {
        "id": 63,
        "desc": "평균임금 산정기간 자동 계산 — end_date 기반 3개월 역산",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3_000_000,
            reference_year=2026,
            last_3m_wages=[3_000_000, 3_000_000, 3_000_000],
            end_date="2026-03-08",
        ),
        "targets": ["average_wage"],
        # 기대: 2026-03-08에서 3개월 역산 → 2025-12-08
        #       일수 = (2026-03-08) - (2025-12-08) = 90일
        #       3개월 총액 9,000,000 / 90일 = 100,000원/일
    },
    {
        "id": 64,
        "desc": "평균임금 dict 형태 월별 입력 — 기본급 + 기타수당",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=2_500_000,
            reference_year=2025,
            last_3m_wages=[
                {"base": 2_500_000, "allowance": 500_000},
                {"base": 2_500_000, "allowance": 500_000},
                {"base": 2_500_000, "allowance": 500_000},
            ],
            last_3m_days=92,
        ),
        "targets": ["average_wage"],
        # 기대: 월별 합산 3,000,000 × 3 = 9,000,000
        #       총액 9,000,000 / 92일 = 97,826원/일
    },

    # ── 포괄임금제 보완 테스트 ────────────────────────────────────────────────
    {
        "id": 65,
        "desc": "포괄임금 정액역산 — 월 300만, 연장10h, 야간4h (breakdown 없음)",
        "input": WageInput(
            wage_type=WageType.COMPREHENSIVE,
            monthly_wage=3_000_000,
            business_size=BusinessSize.OVER_5,
            reference_year=2026,
            schedule=WorkSchedule(
                daily_work_hours=8,
                weekly_work_days=5,
                weekly_overtime_hours=10,
                weekly_night_hours=4,
            ),
        ),
        "targets": ["comprehensive", "minimum_wage"],
        # 기본시간: (40+8) × 4.345 ≈ 208.6h
        # 연장계수: 10 × 1.5 × 4.345 ≈ 65.2h
        # 야간계수: 4 × 0.5 × 4.345 ≈ 8.7h
        # 총계수 ≈ 282.5h
        # 역산시급: 3,000,000 / 282.5 ≈ 10,619원 > 10,320원 → 최저임금 충족
    },
    {
        "id": 66,
        "desc": "포괄임금 5인 미만 역산 — 월 250만, 연장10h (가산수당 미적용)",
        "input": WageInput(
            wage_type=WageType.COMPREHENSIVE,
            monthly_wage=2_500_000,
            business_size=BusinessSize.UNDER_5,
            reference_year=2026,
            schedule=WorkSchedule(
                daily_work_hours=8,
                weekly_work_days=5,
                weekly_overtime_hours=10,
            ),
        ),
        "targets": ["comprehensive"],
        # 5인 미만: 연장 × 1.0 (가산 없음), 야간 × 0.0
        # 기본시간: 208.6h, 연장계수: 10 × 1.0 × 4.345 ≈ 43.5h
        # 총계수 ≈ 252.0h
        # 역산시급: 2,500,000 / 252.0 ≈ 9,921원
    },
    {
        "id": 67,
        "desc": "포괄임금 breakdown + 수당 부족 — 연장수당 포함액 < 적정액",
        "input": WageInput(
            wage_type=WageType.COMPREHENSIVE,
            monthly_wage=3_000_000,
            business_size=BusinessSize.OVER_5,
            reference_year=2026,
            comprehensive_breakdown={
                "base": 2_000_000,
                "overtime_pay": 300_000,
                "night_pay": 200_000,
            },
            schedule=WorkSchedule(
                daily_work_hours=8,
                weekly_work_days=5,
                weekly_overtime_hours=20,
                weekly_night_hours=8,
            ),
        ),
        "targets": ["comprehensive"],
        # 총액: 2,000,000 + 300,000 + 200,000 = 2,500,000
        # 총계수 = 209 + 20×1.5×4.345 + 8×0.5×4.345 ≈ 209 + 130.4 + 17.4 = 356.7h
        # 역산시급 ≈ 7,009원
        # 연장 적정액: 7,009 × 20 × 1.5 × 4.345 ≈ 913,470원 > 포함 300,000원 → 부족
    },
    {
        "id": 68,
        "desc": "포괄임금 유효성 실패 — 교대제 근로자",
        "input": WageInput(
            wage_type=WageType.COMPREHENSIVE,
            monthly_wage=3_000_000,
            business_size=BusinessSize.OVER_5,
            work_type=WorkType.SHIFT_3_2,
            reference_year=2026,
            schedule=WorkSchedule(
                daily_work_hours=8,
                weekly_work_days=5,
                weekly_overtime_hours=10,
            ),
        ),
        "targets": ["comprehensive"],
        # is_valid_comprehensive = False (교대제 적용 불가)
    },
    {
        "id": 69,
        "desc": "포괄임금 연간 상여금 월환산 — 연 240만 → 월 +20만",
        "input": WageInput(
            wage_type=WageType.COMPREHENSIVE,
            monthly_wage=3_000_000,
            business_size=BusinessSize.OVER_5,
            reference_year=2026,
            comprehensive_breakdown={
                "base": 2_200_000,
                "overtime_pay": 600_000,
                "annual_bonus": 2_400_000,
            },
            schedule=WorkSchedule(
                daily_work_hours=8,
                weekly_work_days=5,
                weekly_overtime_hours=10,
            ),
        ),
        "targets": ["comprehensive"],
        # 총액: 2,200,000 + 600,000 + (2,400,000/12) = 3,000,000
        # 총계수: 209 + 10×1.5×4.345 ≈ 209 + 65.2 = 274.2h
        # 역산시급: 3,000,000 / 274.2 ≈ 10,941원
    },
    {
        "id": 70,
        "desc": "포괄임금 휴일근로 8h 초과분 역산 — 휴일 8h + 초과 4h",
        "input": WageInput(
            wage_type=WageType.COMPREHENSIVE,
            monthly_wage=4_000_000,
            business_size=BusinessSize.OVER_5,
            reference_year=2026,
            schedule=WorkSchedule(
                daily_work_hours=8,
                weekly_work_days=5,
                weekly_overtime_hours=10,
                weekly_holiday_hours=8,
                weekly_holiday_overtime_hours=4,
            ),
        ),
        "targets": ["comprehensive"],
        # 기본시간: 208.6h
        # 연장계수: 10 × 1.5 × 4.345 = 65.2h
        # 휴일계수: 8 × 1.5 × 4.345 = 52.1h
        # 휴일OT계수: 4 × 2.0 × 4.345 = 34.8h
        # 총계수 ≈ 360.7h
        # 역산시급: 4,000,000 / 360.7 ≈ 11,089원
    },

    # ── 산재보상금 테스트 (#71~#78) ────────────────────────────────────
    {
        "id": 71,
        "desc": "산재 휴업급여 기본 — 평균임금 10만원/일, 30일",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3_000_000,
            reference_year=2026,
            sick_leave_days=30,
        ),
        "targets": ["industrial_accident"],
        # 평균임금 추정: 3,000,000/30 = 100,000원/일
        # 휴업급여: 100,000 × 0.70 = 70,000원/일
        # 총액: 70,000 × 30 = 2,100,000원
    },
    {
        "id": 72,
        "desc": "산재 휴업급여 최저보상기준 — 저임금 근로자",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=1_500_000,
            reference_year=2026,
            sick_leave_days=30,
        ),
        "targets": ["industrial_accident"],
        # 평균임금 추정: 1,500,000/30 = 50,000원/일
        # 70%: 50,000 × 0.70 = 35,000원 ≤ 최저보상기준 82,560 × 80% = 66,048
        # → 90% 적용: 50,000 × 0.90 = 45,000원 (≤ 66,048이므로 45,000 적용)
        # 총액: 45,000 × 30 = 1,350,000원
    },
    {
        "id": 73,
        "desc": "산재 상병보상연금 제1급 — 329일",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3_000_000,
            reference_year=2026,
            severe_illness_grade=1,
        ),
        "targets": ["industrial_accident"],
        # 평균임금: 100,000원/일
        # 상병보상연금: 100,000 × 329 = 32,900,000원/년
    },
    {
        "id": 74,
        "desc": "산재 장해급여 연금 제4급 — 224일",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3_000_000,
            reference_year=2026,
            disability_grade=4,
            disability_pension=True,
        ),
        "targets": ["industrial_accident"],
        # 평균임금: 100,000원/일
        # 장해급여(연금): 100,000 × 224 = 22,400,000원/년
    },
    {
        "id": 75,
        "desc": "산재 장해급여 일시금 제10급 — 297일",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3_000_000,
            reference_year=2026,
            disability_grade=10,
        ),
        "targets": ["industrial_accident"],
        # 평균임금: 100,000원/일
        # 장해급여(일시금): 100,000 × 297 = 29,700,000원
    },
    {
        "id": 76,
        "desc": "산재 유족보상연금 — 유족 3명, 62%",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3_000_000,
            reference_year=2026,
            is_deceased=True,
            num_survivors=3,
            survivor_pension=True,
        ),
        "targets": ["industrial_accident"],
        # 평균임금: 100,000원/일
        # 유족보상연금: 100,000 × 365 × 62% = 22,630,000원/년
        # 장례비: 100,000 × 120 = 12,000,000 (최저 13,943,000 적용)
    },
    {
        "id": 77,
        "desc": "산재 유족보상일시금 + 장례비",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3_000_000,
            reference_year=2026,
            is_deceased=True,
            num_survivors=1,
            survivor_pension=False,
        ),
        "targets": ["industrial_accident"],
        # 평균임금: 100,000원/일
        # 유족일시금: 100,000 × 1,300 = 130,000,000원
        # 장례비: 100,000 × 120 = 12,000,000 (최저 13,943,000 적용)
    },
    {
        "id": 78,
        "desc": "산재 사망 종합 — 월급 500만, 유족 2명 연금 + 장례비",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=5_000_000,
            reference_year=2026,
            is_deceased=True,
            num_survivors=2,
            survivor_pension=True,
        ),
        "targets": ["industrial_accident"],
        # 평균임금: 5,000,000/30 ≈ 166,667원/일
        # 유족연금: 166,667 × 365 × 57% = 34,675,015원/년
        # 장례비: 166,667 × 120 = 20,000,040 → 최고 19,279,760 적용
    },

    # ═══════════════════════════════════════════════════════════════════════
    # 연차수당 계산기 기능보완 테스트 (#79~#85)
    # ═══════════════════════════════════════════════════════════════════════

    # ── G1: 2년차 연차 차감 (제60조③) ────────────────────────────────────
    {
        "id": 79,
        "desc": "연차 2년차 차감 — 1년 미만 5일 사용 → 15-5=10일 (제60조③)",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3_000_000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            start_date="2024-01-01",
            end_date="2025-06-01",
            first_year_leave_used=5.0,
            annual_leave_used=0,
        ),
        "targets": ["annual_leave"],
        # 재직: 517일 (1.4년), 2년차(extra_years=0)
        # 기본 15일 - 차감 5일 = 10일 부여
        # 통상시급: 3,000,000/209 ≈ 14,354원
        # 수당: 14,354 × 8 × 10 = 1,148,320원
    },
    {
        "id": 80,
        "desc": "연차 2년차 미차감 — 1년 미만 미사용 시 15일 전체 부여",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3_000_000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            start_date="2024-01-01",
            end_date="2025-06-01",
            first_year_leave_used=0.0,
            annual_leave_used=0,
        ),
        "targets": ["annual_leave"],
        # 2년차, 차감 0일 → 15일 전체 부여
    },

    # ── G4: 단시간근로자 비례 ─────────────────────────────────────────────
    {
        "id": 81,
        "desc": "연차 단시간근로자 — 주 20시간(일4h×5일), 3년 근속 비례",
        "input": WageInput(
            wage_type=WageType.HOURLY,
            hourly_wage=10_030,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            start_date="2022-01-01",
            end_date="2025-01-01",
            schedule=WorkSchedule(daily_work_hours=4, weekly_work_days=5),
        ),
        "targets": ["annual_leave"],
        # 통상 3년 → 15일
        # 비례: 15 × (20/40) × (8/4) = 15 × 0.5 × 2.0 = 15.0일
    },
    {
        "id": 82,
        "desc": "연차 단시간 주 12시간 — 15시간 미만 연차 미발생",
        "input": WageInput(
            wage_type=WageType.HOURLY,
            hourly_wage=10_030,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            start_date="2023-01-01",
            end_date="2025-01-01",
            schedule=WorkSchedule(daily_work_hours=4, weekly_work_days=3),
        ),
        "targets": ["annual_leave"],
        # 주 12시간 < 15시간 → 연차 미발생
    },

    # ── G2: 회계기준일(1.1) 기준 ──────────────────────────────────────────
    {
        "id": 83,
        "desc": "연차 회계기준일 — 7월 입사 첫해 비례 부여",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3_000_000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            start_date="2025-07-01",
            end_date="2025-12-31",
            use_fiscal_year=True,
        ),
        "targets": ["annual_leave"],
        # 잔여 6개월 (12-7+1=6, 7~12월)
        # → ceil(15 × 6/12) = ceil(7.5) = 8일
    },
    {
        "id": 84,
        "desc": "연차 회계기준일 — 3년 근속 15일",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3_500_000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            start_date="2022-03-15",
            end_date="2025-06-01",
            use_fiscal_year=True,
            annual_leave_used=5,
        ),
        "targets": ["annual_leave"],
        # years_since_hire = 2025-2022 = 3 → extra=(3-1)//2=1 → 15+1=16일
        # 사용 5일 → 미사용 11일
    },

    # ── G5: 퇴직 시 비교 정산 ─────────────────────────────────────────────
    {
        "id": 85,
        "desc": "연차 퇴직 시 회계기준일 vs 입사일 비교 정산",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3_000_000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            start_date="2024-07-01",
            end_date="2025-06-30",
            use_fiscal_year=True,
            annual_leave_used=0,
        ),
        "targets": ["annual_leave"],
        # 회계기준일: 2025년, years_since=1 → 15일
        # 입사일 기준: 365일 = 1.0년, extra_years=0 → 15일
        # 동일하므로 gap=0 (비교 정산 불필요)
    },
    # ── 휴업수당 테스트 (3건) ─────────────────────────────────────────────────
    {
        "id": 86,
        "desc": "휴업수당 — 전일 휴업 30일 (사용자 귀책, 월급 300만원)",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3_000_000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            shutdown_days=30,
            is_employer_fault=True,
        ),
        "targets": ["shutdown_allowance"],
        # 평균임금 = 3,000,000 × 3 / 92 ≈ 97,826원/일
        # 70% ≈ 68,478원
        # 통상임금 = 3,000,000 / 209 × 8 ≈ 114,833원
        # 68,478 < 114,833 → 평균임금 70% 적용
        # 총액 ≈ 68,478 × 30 = 2,054,348원
    },
    {
        "id": 87,
        "desc": "휴업수당 — 부분 휴업 (1일 8h 중 4h 미근로, 20일)",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=2_500_000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            shutdown_days=20,
            shutdown_hours_per_day=4.0,
            is_employer_fault=True,
        ),
        "targets": ["shutdown_allowance"],
        # 부분 휴업: 4h/8h = 50% 적용
    },
    {
        "id": 88,
        "desc": "휴업수당 — 불가항력 (천재지변, 미발생)",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3_000_000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            shutdown_days=10,
            is_employer_fault=False,
        ),
        "targets": ["shutdown_allowance"],
        # 불가항력 → 0원
    },
    # ── 해고예고수당 보완 테스트 (2건) ────────────────────────────────────────
    {
        "id": 89,
        "desc": "해고예고수당 — 파트타임 6h 근무자 (daily_pay 수정 검증)",
        "input": WageInput(
            wage_type=WageType.HOURLY,
            hourly_wage=10030,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            notice_days_given=0,
            schedule=WorkSchedule(
                daily_work_hours=6,
                weekly_work_days=5,
            ),
        ),
        "targets": ["dismissal"],
        # daily_pay = 10,030 × 6h = 60,180원
        # 해고예고수당 = 60,180 × 30 = 1,805,400원
    },
    {
        "id": 90,
        "desc": "해고예고수당 — 3개월 미만 근속 면제",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=2_500_000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            notice_days_given=0,
            tenure_months=2,
        ),
        "targets": ["dismissal"],
        # 면제 (is_exempt=True, dismissal_pay=0)
    },
    # ── 주휴수당 안내 보강 테스트 (2건) ───────────────────────────────────────
    {
        "id": 91,
        "desc": "주휴수당 — 시급제 주휴 포함 여부 warning 확인",
        "input": WageInput(
            wage_type=WageType.HOURLY,
            hourly_wage=10030,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            schedule=WorkSchedule(
                daily_work_hours=8,
                weekly_work_days=5,
            ),
        ),
        "targets": ["weekly_holiday"],
        # warnings에 "시급제" 포함
    },
    {
        "id": 92,
        "desc": "주휴수당 — 월급제 주휴 포함 안내 breakdown 확인",
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=3_000_000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
        ),
        "targets": ["weekly_holiday"],
        # breakdown에 "월급 주휴 포함 여부" 존재
        # breakdown에 "주 소정근로일" 존재
    },
    # ── 실업급여 리뷰 신규 테스트 ─────────────────────────────────────────────
    {
        "id": 93,
        "desc": "실업급여 — 2026년 상한액 68,100원 적용 (10년 52세 월500만)",
        # 평균임금 일액: 5,000,000×3÷92 ≈ 163,043원 → 60% = 97,826원
        # 상한액(2026): 68,100원 → 상한 적용
        # 소정급여일수: 120개월 × 50세이상 → 270일
        # 총 구직급여: 68,100 × 270 = 18,387,000원
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=5_000_000,
            business_size=BusinessSize.OVER_5,
            reference_year=2026,
            insurance_months=120,
            age=52,
            is_involuntary_quit=True,
        ),
        "targets": ["unemployment"],
    },
    {
        "id": 94,
        "desc": "실업급여 — 상여금 600만 + 연차수당 포함 평균임금 (5년 40세 월250만)",
        # base_3m: 2,500,000×3 = 7,500,000원
        # 상여금 3개월분: 6,000,000÷12×3 = 1,500,000원
        # 연차수당 3개월분: 600,000÷12×3 = 150,000원
        # total_3m: 9,150,000원
        # 평균임금 일액: 9,150,000÷92 ≈ 99,457원 → 60% = 59,674원
        # 하한액(2025): 10,030×0.8×8 = 64,192원 → 하한 적용
        # 소정급여일수: 60개월 × 50세미만 → 210일
        # 총 구직급여: 64,192 × 210 = 13,480,320원
        "input": WageInput(
            wage_type=WageType.MONTHLY,
            monthly_wage=2_500_000,
            business_size=BusinessSize.OVER_5,
            reference_year=2025,
            insurance_months=60,
            age=40,
            is_involuntary_quit=True,
            annual_bonus_total=6_000_000,
            unused_annual_leave_pay=600_000,
        ),
        "targets": ["unemployment"],
    },
]


def run_test_case(case: dict, calc: WageCalculator) -> None:
    print(f"\n{'='*60}")
    print(f"테스트 #{case['id']}: {case['desc']}")
    print("=" * 60)
    inp = case["input"]
    if isinstance(inp, BusinessSizeInput):
        bs = calc_business_size(inp)
        for k, v in bs.breakdown.items():
            print(f"  {k}: {v}")
        for f in bs.formulas:
            print(f"  {f}")
        if bs.warnings:
            for w in bs.warnings:
                print(f"  ⚠️  {w}")
        print(f"  → 상시근로자 수: {bs.regular_worker_count}명 | {bs.business_size.value} | 법 적용: {'예' if bs.is_law_applicable else '아니오'}")
    else:
        result = calc.calculate(inp, targets=case["targets"])
        print(format_result(result))


def run_all(cases=None):
    calc = WageCalculator()
    target_cases = cases or TEST_CASES
    for case in target_cases:
        run_test_case(case, calc)
    print(f"\n✅ {len(target_cases)}개 테스트 완료")


def run_interactive():
    """대화형 입력 모드"""
    print("\n노동OK 임금계산기 (대화형 모드)")
    print("=" * 40)

    wage_type_map = {
        "1": WageType.HOURLY,
        "2": WageType.DAILY,
        "3": WageType.MONTHLY,
        "4": WageType.ANNUAL,
        "5": WageType.COMPREHENSIVE,
    }

    print("임금 형태 선택:")
    print("  1. 시급  2. 일급  3. 월급  4. 연봉  5. 포괄임금제")
    wt_choice = input("선택 (1-5): ").strip() or "3"
    wage_type = wage_type_map.get(wt_choice, WageType.MONTHLY)

    amount = float(input(f"{wage_type.value} 금액 (원): ").replace(",", "") or "0")

    size_input = input("사업장 규모 (1: 5인미만, 2: 5인이상) [2]: ").strip() or "2"
    biz_size = BusinessSize.UNDER_5 if size_input == "1" else BusinessSize.OVER_5

    ot_h = float(input("주 연장근로시간 [0]: ") or "0")
    night_h = float(input("주 야간근로시간 (22~06시) [0]: ") or "0")
    holiday_h = float(input("주 휴일근로시간 [0]: ") or "0")

    schedule = WorkSchedule(
        weekly_overtime_hours=ot_h,
        weekly_night_hours=night_h,
        weekly_holiday_hours=holiday_h,
    )

    inp = WageInput(
        wage_type=wage_type,
        business_size=biz_size,
        schedule=schedule,
    )
    if wage_type == WageType.HOURLY:
        inp.hourly_wage = amount
    elif wage_type == WageType.DAILY:
        inp.daily_wage = amount
    elif wage_type in (WageType.MONTHLY, WageType.COMPREHENSIVE):
        inp.monthly_wage = amount
    elif wage_type == WageType.ANNUAL:
        inp.annual_wage = amount

    calc = WageCalculator()
    result = calc.calculate(inp)
    print("\n" + format_result(result))


def main():
    parser = argparse.ArgumentParser(description="임금계산기 CLI")
    parser.add_argument("--case", type=int, help="실행할 테스트 케이스 번호")
    parser.add_argument("--interactive", action="store_true", help="대화형 입력 모드")
    args = parser.parse_args()

    if args.interactive:
        run_interactive()
    elif args.case:
        matched = [c for c in TEST_CASES if c["id"] == args.case]
        if not matched:
            print(f"케이스 #{args.case}를 찾을 수 없습니다. (1-{len(TEST_CASES)})")
            sys.exit(1)
        run_all(matched)
    else:
        run_all()


if __name__ == "__main__":
    main()
