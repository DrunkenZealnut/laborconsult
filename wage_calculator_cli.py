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
