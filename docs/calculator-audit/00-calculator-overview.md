# 계산기 개요표 (Calculator Overview)

> `wage_calculator/` 전체 24개 계산기 목록, 2026-03-08 기준 작성

---

## 계산기 전체 목록

| # | 계산기명 | 코드파일 | 함수명 | 적용 법조문 | 통상임금 의존 | 우선순위 |
|---|---------|---------|--------|-----------|:----------:|:------:|
| 01 | 통상임금 | `ordinary_wage.py` | `calc_ordinary_wage` | 근로기준법 제2조 제1항 제5호, 시행령 제6조 | - (기반) | High |
| 02 | 연장/야간/휴일수당 | `overtime.py` | `calc_overtime` | 근로기준법 제56조 | O | High |
| 03 | 최저임금 | `minimum_wage.py` | `calc_minimum_wage` | 최저임금법 제5조, 제6조 | O | High |
| 04 | 주휴수당 | `weekly_holiday.py` | `calc_weekly_holiday` | 근로기준법 제55조 | O | High |
| 05 | 연차수당 | `annual_leave.py` | `calc_annual_leave` | 근로기준법 제60조 | O | High |
| 06 | 해고예고수당 | `dismissal.py` | `calc_dismissal` | 근로기준법 제26조 | O | Medium |
| 07 | 퇴직금 | `severance.py` | `calc_severance` | 근로자퇴직급여보장법 제4조, 제8조 | O | High |
| 08 | 평균임금 | `average_wage.py` | `calc_average_wage` | 근로기준법 제2조 제1항 제6호 | O | High |
| 09 | 휴업수당 | `shutdown_allowance.py` | `calc_shutdown_allowance` | 근로기준법 제46조 | O | Medium |
| 10 | 포괄임금제 | `comprehensive.py` | `calc_comprehensive` | 대법원 2020다300299, 2014도8873 | O | Medium |
| 11 | 중도입사 일할계산 | `prorated.py` | `calc_prorated` | 근로기준법 (실무) | O | Low |
| 12 | 유급공휴일 | `public_holiday.py` | `calc_public_holiday` | 근로기준법 제55조 제2항 | O | Low |
| 13 | 4대보험/소득세 | `insurance.py` | `calc_insurance` | 국민연금법, 건강보험법, 고용보험법, 소득세법 | O | High |
| 14 | 실업급여 | `unemployment.py` | `calc_unemployment` | 고용보험법 제45조~제52조 | O | High |
| 15 | 보상휴가 | `compensatory_leave.py` | `calc_compensatory_leave` | 근로기준법 제57조 | O | Low |
| 16 | 임금체불 지연이자 | `wage_arrears.py` | `calc_wage_arrears` | 근로기준법 제37조, 시행령 제17조 | X (독립) | Medium |
| 17 | 육아휴직급여 | `parental_leave.py` | `calc_parental_leave` | 고용보험법 제70조 | O | Medium |
| 18 | 출산전후휴가급여 | `maternity_leave.py` | `calc_maternity_leave` | 고용보험법 제75조 | O | Medium |
| 19 | 탄력적 근로시간제 | `flexible_work.py` | `calc_flexible_work` | 근로기준법 제51조 | O | Medium |
| 20 | 산재보상금 | `industrial_accident.py` | `calc_industrial_accident` | 산업재해보상보험법 제52,57,62,66,71조 | O | High |
| 21 | 퇴직소득세 | `retirement_tax.py` | `calc_retirement_tax` | 소득세법 제48조, 시행령 제42조의2 | O | Medium |
| 22 | 퇴직연금 | `retirement_pension.py` | `calc_retirement_pension` | 근로자퇴직급여보장법 제15조, 제17조 | O | Medium |
| 23 | 상시근로자 수 | `business_size.py` | `calc_business_size` | 근로기준법 시행령 제7조의2 | X | Medium |
| 24 | 근로장려금 | `eitc.py` | `calc_eitc` | 조세특례제한법 제100조의2~12, 제100조의27 | O | Medium |

---

## 실행 순서 및 의존관계

```
calc_business_size (독립, 최우선)
    |
calc_ordinary_wage (기반 -- 모든 계산기의 선행 조건)
    |
    +-- calc_overtime, calc_minimum_wage, calc_weekly_holiday
    +-- calc_annual_leave, calc_dismissal, calc_comprehensive
    +-- calc_prorated, calc_public_holiday
    +-- calc_average_wage
    +-- calc_severance --> calc_retirement_tax (퇴직금 결과 참조)
    |                  +-> calc_retirement_pension (퇴직금 결과 참조)
    +-- calc_shutdown_allowance
    +-- calc_unemployment
    +-- calc_insurance, calc_employer_insurance
    +-- calc_compensatory_leave
    +-- calc_parental_leave, calc_maternity_leave
    +-- calc_flexible_work
    +-- calc_eitc
    +-- calc_industrial_accident
    |
calc_wage_arrears (독립 함수, WageInput 미사용)
check_weekly_hours_compliance (독립, ow 미사용)
generate_legal_hints (최후 실행, 다른 결과 참조)
```

---

## 디스패처 레지스트리 (_STANDARD_CALCS)

`facade.py`의 `_STANDARD_CALCS` 리스트 순서대로 실행. 코드 위치: `facade.py:326-352`

| 순서 | key | section 이름 | precondition |
|------|-----|-------------|-------------|
| 1 | overtime | 연장/야간/휴일수당 | 없음 |
| 2 | minimum_wage | 최저임금 검증 | 없음 |
| 3 | weekly_holiday | 주휴수당 | 없음 |
| 4 | annual_leave | 연차수당 | 없음 |
| 5 | dismissal | 해고예고수당 | 없음 |
| 6 | comprehensive | 포괄임금제 역산 | `inp.wage_type == COMPREHENSIVE` |
| 7 | prorated | 중도입사 일할계산 | `inp.join_date` 존재 |
| 8 | public_holiday | 유급 공휴일 | `inp.public_holiday_days > 0` |
| 9 | average_wage | 평균임금 | 없음 |
| 10 | severance | 퇴직금 | 없음 |
| 11 | shutdown_allowance | 휴업수당 | `inp.shutdown_days > 0` |
| 12 | unemployment | 실업급여(구직급여) | 없음 |
| 13 | insurance | 4대보험/소득세 | 없음 |
| 14 | employer_insurance | 사업주 4대보험 부담금 | 없음 |
| 15 | compensatory_leave | 보상휴가 환산 | 없음 |
| 16 | parental_leave | 육아휴직급여 | 없음 |
| 17 | maternity_leave | 출산전후휴가급여 | 없음 |
| 18 | flexible_work | 탄력적 근로시간제 | `inp.flexible_work_unit` 존재 |
| 19 | eitc | 근로장려금(EITC) | 없음 |
| 20 | industrial_accident | 산재보상금 | 없음 |

---

## 특수 계산기 (디스패처 외)

| 계산기 | 위치 | 특이사항 |
|--------|------|---------|
| `business_size` | `facade.py:392-398` | `_STANDARD_CALCS` 이전, 최우선 실행. `inp.business_size` 자동 설정 |
| `wage_arrears` | `facade.py:414-424` | 독립 함수, `WageInput` 미사용. `arrear_amount > 0` 조건 |
| `weekly_hours_check` | `facade.py:427-431` | `check_weekly_hours_compliance()` 호출, `ow` 미사용 |
| `retirement_tax` | `facade.py:434-437` | `_severance_cache` 참조 (퇴직금 결과 필요) |
| `retirement_pension` | `facade.py:440-443` | `_severance_cache` 참조 (퇴직금 결과 필요) |
| `legal_hints` | `facade.py:446-456` | 최후 실행, 다른 계산 결과 참조 후 법률 힌트 생성 |

---

## CALC_TYPE_MAP (분석 분류값 -> 계산기 매핑)

`facade.py:67-97`에 정의. `from_analysis()` 메서드에서 사용.

| 분류값 (calculation_type) | 매핑 targets |
|--------------------------|-------------|
| 연장수당 | overtime, minimum_wage |
| 최저임금 | minimum_wage |
| 주휴수당 | weekly_holiday, minimum_wage |
| 연차수당 | annual_leave |
| 해고예고수당 | dismissal |
| 퇴직금 | severance, minimum_wage |
| 실업급여 | unemployment |
| 임금계산 | overtime, minimum_wage, weekly_holiday |
| 해당없음 | minimum_wage |
| 육아휴직 | parental_leave |
| 출산휴가 | maternity_leave |
| 임금체불 | wage_arrears |
| 보상휴가 | compensatory_leave, overtime |
| 탄력근무 | flexible_work |
| 사업장규모 | business_size |
| 근로장려금 / 근로장려세제 / EITC | eitc |
| 퇴직소득세 | severance, retirement_tax |
| 퇴직연금 | retirement_pension |
| 퇴직 | severance, retirement_tax |
| 평균임금 | average_wage |
| 산재보상 / 휴업급여 / 장해급여 / 유족급여 / 장례비 / 산재 | industrial_accident, average_wage |
| 휴업수당 | shutdown_allowance |
