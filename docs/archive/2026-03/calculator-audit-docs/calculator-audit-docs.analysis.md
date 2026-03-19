# calculator-audit-docs Gap Analysis Report

> **Feature**: calculator-audit-docs
> **Design Document**: `docs/02-design/features/calculator-audit-docs.design.md`
> **Implementation**: `docs/calculator-audit/` (29 files)
> **Analysis Date**: 2026-03-08

---

## Overall Match Rate: 97%

| Category | Score | Status |
|----------|:-----:|:------:|
| 파일 완성도 | 29/29 (100%) | PASS |
| FR 커버리지 | 21/21 (100%) | PASS |
| 템플릿 준수 | 24/24 (100%) | PASS |
| 코드 위치 참조 | 24/24 (100%) | PASS |
| 법적 근거 매핑 | 24/24 (100%) | PASS |
| 계산 예시 포함 | 24/24 (100%) | PASS |
| 판례 참조 | 24/24 (100%) | PASS |
| 금액 콤마 표기 | 23/24 (96%) | PASS (예외 적절) |
| 코드 위치 형식 일관성 | 17/24 (71%) | Minor Gap |
| **종합** | **97%** | **PASS** |

---

## 1. 파일 완성도 검증

### 1.1 공통 참조 문서 (4/4)

| 파일 | FR | 상태 |
|------|-----|:----:|
| `00-constants-reference.md` | FR-01 | PASS |
| `00-calculator-overview.md` | FR-02 | PASS |
| `00-legal-case-mapping.md` | FR-20 | PASS |
| `00-annual-update-checklist.md` | FR-21 | PASS |

### 1.2 감사 시트 (24/24)

| # | 파일 | FR | 섹션 수 | 상태 |
|:-:|------|-----|:------:|:----:|
| 01 | `01-ordinary-wage.audit.md` | FR-03 | 8/8 | PASS |
| 02 | `02-overtime.audit.md` | FR-04 | 8/8 | PASS |
| 03 | `03-minimum-wage.audit.md` | FR-05 | 8/8 | PASS |
| 04 | `04-weekly-holiday.audit.md` | FR-09 | 8/8 | PASS |
| 05 | `05-annual-leave.audit.md` | FR-08 | 8/8 | PASS |
| 06 | `06-dismissal.audit.md` | FR-10 | 8/8 | PASS |
| 07 | `07-severance.audit.md` | FR-06 | 8/8 | PASS |
| 08 | `08-average-wage.audit.md` | — | 8/8 | PASS |
| 09 | `09-shutdown-allowance.audit.md` | — | 8/8 | PASS |
| 10 | `10-comprehensive.audit.md` | FR-12 | 8/8 | PASS |
| 11 | `11-prorated.audit.md` | FR-15 | 8/8 | PASS |
| 12 | `12-public-holiday.audit.md` | FR-15 | 8/8 | PASS |
| 13 | `13-insurance.audit.md` | FR-07 | 8/8 | PASS |
| 14 | `14-unemployment.audit.md` | FR-11 | 8/8 | PASS |
| 15 | `15-compensatory-leave.audit.md` | FR-15 | 8/8 | PASS |
| 16 | `16-wage-arrears.audit.md` | FR-14 | 8/8 | PASS |
| 17 | `17-parental-leave.audit.md` | FR-13 | 8/8 | PASS |
| 18 | `18-maternity-leave.audit.md` | FR-13 | 8/8 | PASS |
| 19 | `19-flexible-work.audit.md` | FR-15 | 8/8 | PASS |
| 20 | `20-industrial-accident.audit.md` | FR-16 | 8/8 | PASS |
| 21 | `21-retirement-tax.audit.md` | FR-17 | 8/8 | PASS |
| 22 | `22-retirement-pension.audit.md` | FR-17 | 8/8 | PASS |
| 23 | `23-business-size.audit.md` | FR-19 | 8/8 | PASS |
| 24 | `24-eitc.audit.md` | FR-18 | 8/8 | PASS |

### 1.3 README (1/1)

| 파일 | 상태 | 내용 |
|------|:----:|------|
| `README.md` | PASS | 리뷰 가이드, 우선순위, 공통 참조 링크, 24개 감사 시트 링크, 표준 구조 설명 |

---

## 2. 템플릿 준수 검증

### 2.1 8섹션 구조 (24/24 PASS)

모든 감사 시트가 설계 문서의 표준 템플릿을 준수:

| 섹션 | 내용 | 준수율 |
|------|------|:------:|
| 1. 개요 | 계산기명, 코드 파일, 함수명, 적용 법조문 | 24/24 |
| 2. 입력 항목 | WageInput 필드 테이블 | 24/24 |
| 3. 적용 상수 | 상수 테이블 (값, 법적 근거, 코드 위치) | 24/24 |
| 4. 계산 과정 | Step별 공식 + 법적 근거 | 24/24 |
| 5. 출력 항목 | 결과 필드 설명 | 24/24 |
| 6. 예외 처리 | 엣지 케이스 | 24/24 |
| 7. 계산 예시 | 1~2개 시나리오 | 24/24 |
| 8. 관련 판례 | 판례 번호, 요지, 반영 위치 | 24/24 |

---

## 3. 비기능 요구사항 검증

| 항목 | 설계 기준 | 결과 | 상태 |
|------|----------|------|:----:|
| 한글 문서 | 노무사가 코드 없이 이해 | 전체 한글 (코드 참조용 영문 병기) | PASS |
| 금액 표기 | 원 단위, 천단위 콤마 | 23/24 준수 (23-business-size 제외 — 인원수 취급, 적절) | PASS |
| 법조문 형식 | "근로기준법 제N조제M항" | 24/24 준수 | PASS |
| 판례 형식 | "대법원 YYYY다NNNN" | 24/24 준수 | PASS |
| 코드 위치 | "파일명:라인번호" | 17/24 `:` 형식, 7/24 `L` 형식 (동일 정보) | Minor Gap |

---

## 4. Gap List

### 4.1 Minor Gaps (비차단)

| # | 항목 | 설명 | 영향 | 심각도 |
|:-:|------|------|------|:------:|
| G-01 | 코드 위치 형식 불일치 | 17개 시트는 `constants.py:36` 형식, 7개 시트는 `` `constants.py` L36 `` 형식 사용 | 가독성 (기능 영향 없음) | Low |

**해당 시트**: 05-annual-leave, 07-severance, 11-prorated, 12-public-holiday, 16-wage-arrears, 17-parental-leave, 22-retirement-pension

### 4.2 Critical/High/Medium Gaps: 없음

---

## 5. Positive Deviations (설계 초과 구현)

| # | 항목 | 설명 |
|:-:|------|------|
| PD-01 | 판례 반영 현황 확장 | 설계 6건 → 구현 13건 판례 + 법령별 매핑 (근기법 20조문, 고보법 13개 등) |
| PD-02 | 사업주 부담금 상세화 | 13-insurance에 사업주 부담금(직업능력개발 규모별 차등, 산재 4개 구성요소) 별도 섹션 |
| PD-03 | 계산기 개요표 확장 | `_STANDARD_CALCS` 실행 순서, `CALC_TYPE_MAP` 29개 매핑, `_auto_detect_targets` 조건 수록 |
| PD-04 | 미구현 기능 지적 | 일부 감사 시트에서 코드의 미구현 사항 발견 및 문서화 (대체공휴일 자동 판별, 일용직 실업급여 등) |
| PD-05 | 법령 개정 체크리스트 구체화 | 현재 TODO 3건(EITC 2026, 연금 기준소득, 자녀장려금) 명시 |

---

## 6. Summary

### 검증 결과

```
[Plan] -> [Design] -> [Do] -> [Check] 97%
```

- **29개 파일 전체 생성** (README 1 + 공통 참조 4 + 감사 시트 24)
- **21개 FR 전체 충족** (FR-01 ~ FR-21)
- **24개 감사 시트 모두 8섹션 표준 템플릿 준수**
- **법적 근거, 계산 예시, 판례 참조 100% 커버**
- Minor Gap 1건 (코드 위치 표기 형식 불일치 — Low severity)
- Positive Deviation 5건 (설계 초과 구현)

### Recommendation

Match Rate **97%** >= 90% → **Check 통과**. `/pdca report calculator-audit-docs` 진행 가능.

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-03-08 | Initial gap analysis | PDCA |
