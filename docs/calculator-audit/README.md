# 임금계산기 감사 문서

> nodong.kr AI 노동상담 챗봇의 임금계산기 모듈(24개)을 노무사가 코드 없이 검토할 수 있도록 작성된 문서입니다.

---

## 리뷰 가이드

- 각 감사 시트는 **"입력 → 적용 상수 → 계산 과정 → 출력"** 순서로 구성됩니다
- 법적 근거(법조문/판례)는 각 계산 단계에 직접 표기됩니다
- 코드 위치는 `파일명:라인번호` 형식으로 명시되어 있습니다
- 모든 금액은 원 단위, 천단위 콤마 표기입니다

## 리뷰 우선순위

| 순위 | 구분 | 계산기 |
|:----:|------|--------|
| 1 | **핵심 (High)** | 통상임금, 연장수당, 최저임금, 퇴직금, 4대보험, 연차수당 |
| 2 | **중요 (Medium)** | 주휴수당, 해고예고, 평균임금, 휴업수당, 포괄임금, 실업급여, 육아휴직, 출산휴가, 임금체불 |
| 3 | **보조 (Low)** | 일할계산, 유급공휴일, 보상휴가, 탄력근로, 산재, 퇴직소득세, 퇴직연금, 상시근로자수, EITC |

---

## 공통 참조 문서

| 문서 | 설명 |
|------|------|
| [상수 총람](00-constants-reference.md) | `constants.py`의 모든 법적 상수 (최저임금, 보험요율, 세율 등) |
| [계산기 개요표](00-calculator-overview.md) | 24개 계산기 요약 (함수명, 적용 법조문, 통상임금 의존 여부) |
| [판례 반영 현황](00-legal-case-mapping.md) | 적용된 대법원 판례 목록과 코드 반영 위치 |
| [법령 개정 체크리스트](00-annual-update-checklist.md) | 연 1회 업데이트 시 확인할 상수·로직 목록 |

---

## 개별 감사 시트

### 핵심 계산기 (High Priority)

| # | 계산기명 | 감사 시트 | 적용 법조문 |
|:-:|---------|----------|------------|
| 01 | 통상임금 | [01-ordinary-wage.audit.md](01-ordinary-wage.audit.md) | 근기법 시행령 제6조, 대법원 2023다302838 |
| 02 | 연장·야간·휴일수당 | [02-overtime.audit.md](02-overtime.audit.md) | 근기법 제56조 |
| 03 | 최저임금 | [03-minimum-wage.audit.md](03-minimum-wage.audit.md) | 최저임금법 제5조, 제6조 |
| 05 | 연차수당 | [05-annual-leave.audit.md](05-annual-leave.audit.md) | 근기법 제60조 |
| 07 | 퇴직금 | [07-severance.audit.md](07-severance.audit.md) | 근퇴법 제4조, 제8조 |
| 13 | 4대보험·소득세 | [13-insurance.audit.md](13-insurance.audit.md) | 국민연금법 제88조 등 |

### 중요 계산기 (Medium Priority)

| # | 계산기명 | 감사 시트 | 적용 법조문 |
|:-:|---------|----------|------------|
| 04 | 주휴수당 | [04-weekly-holiday.audit.md](04-weekly-holiday.audit.md) | 근기법 제55조, 대법원 2022다291153 |
| 06 | 해고예고수당 | [06-dismissal.audit.md](06-dismissal.audit.md) | 근기법 제26조 |
| 08 | 평균임금 | [08-average-wage.audit.md](08-average-wage.audit.md) | 근기법 제2조제1항제6호 |
| 09 | 휴업수당 | [09-shutdown-allowance.audit.md](09-shutdown-allowance.audit.md) | 근기법 제46조 |
| 10 | 포괄임금제 | [10-comprehensive.audit.md](10-comprehensive.audit.md) | 판례법 |
| 14 | 실업급여 | [14-unemployment.audit.md](14-unemployment.audit.md) | 고용보험법 제68조 |
| 16 | 임금체불 지연이자 | [16-wage-arrears.audit.md](16-wage-arrears.audit.md) | 근기법 제37조 |
| 17 | 육아휴직급여 | [17-parental-leave.audit.md](17-parental-leave.audit.md) | 고용보험법 제70조 |
| 18 | 출산전후휴가급여 | [18-maternity-leave.audit.md](18-maternity-leave.audit.md) | 고용보험법 제75조 |
| 20 | 산재보상금 | [20-industrial-accident.audit.md](20-industrial-accident.audit.md) | 산재보험법 |
| 21 | 퇴직소득세 | [21-retirement-tax.audit.md](21-retirement-tax.audit.md) | 소득세법 제48조 |
| 22 | 퇴직연금 | [22-retirement-pension.audit.md](22-retirement-pension.audit.md) | 근퇴법 제13조 |

### 보조 계산기 (Low Priority)

| # | 계산기명 | 감사 시트 | 적용 법조문 |
|:-:|---------|----------|------------|
| 11 | 중도입사 일할계산 | [11-prorated.audit.md](11-prorated.audit.md) | 근기법 제43조 |
| 12 | 유급공휴일 | [12-public-holiday.audit.md](12-public-holiday.audit.md) | 근기법 제55조제2항 |
| 15 | 보상휴가 | [15-compensatory-leave.audit.md](15-compensatory-leave.audit.md) | 근기법 제57조 |
| 19 | 탄력적 근로시간제 | [19-flexible-work.audit.md](19-flexible-work.audit.md) | 근기법 제51조 |
| 23 | 상시근로자 수 | [23-business-size.audit.md](23-business-size.audit.md) | 근기법 시행령 제7조의2 |
| 24 | 근로장려금 | [24-eitc.audit.md](24-eitc.audit.md) | 조특법 제100조의5 |

---

## 감사 시트 표준 구조

모든 감사 시트는 다음 8개 섹션으로 구성됩니다:

| 섹션 | 내용 |
|------|------|
| **1. 개요** | 계산기명, 코드 파일, 함수명, 적용 법조문 |
| **2. 입력 항목** | WageInput 중 해당 필드 (한/영, 타입, 기본값, 필수) |
| **3. 적용 상수** | 사용 상수 테이블 (값, 단위, 법적 근거, 코드 위치) |
| **4. 계산 과정** | Step별 공식 + 법적 근거 + 코드 참조 |
| **5. 출력 항목** | 결과 필드 설명 |
| **6. 예외 처리** | 엣지 케이스 (5인 미만, 수습, 일용직 등) |
| **7. 계산 예시** | 1~2개 시나리오의 전체 계산 과정 |
| **8. 관련 판례** | 적용된 대법원 판례와 코드 반영 위치 |

---

## 기준 시점

| 항목 | 기준 |
|------|------|
| 상수 기준 | 2025년 / 2026년 (코드 내 연도별 상수 반영) |
| 판례 기준 | 대법원 2023다302838 (2024.12.19 선고) 포함 |
| 문서 작성일 | 2026-03-08 |

---

## 노무사 리뷰 체크포인트

- [ ] 통상임금 포함 기준이 2023다302838 판결을 정확히 반영하는가?
- [ ] 4대보험 요율이 최신 연도 기준과 일치하는가?
- [ ] 퇴직금 평균임금 유리 원칙(3개월 vs 1년)이 정확한가?
- [ ] 연차 발생 로직(1년 미만/이상, 차감, 비례)이 법 조문과 일치하는가?
- [ ] 최저임금 산입범위 계산이 정확한가?
- [ ] 실업급여 소정급여일수 테이블이 최신 기준인가?
- [ ] 산재보상금 장해등급별 보상일수가 정확한가?
- [ ] 근로소득세 세율표와 누진공제가 최신 기준인가?
