# calculator-audit-docs Planning Document

> **Summary**: 모든 임금계산기 모듈의 설정값·계산과정을 노무사가 검토할 수 있는 감사문서 생성
>
> **Project**: laborconsult (nodong.kr AI 노동상담 챗봇)
> **Author**: PDCA
> **Date**: 2026-03-08
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 24개 계산기 모듈의 계산 로직·상수·법적 근거가 코드 안에만 존재하여, 노무사(비개발자)가 정확성을 검증할 수 없음 |
| **Solution** | 각 계산기별 설정값 테이블 + 계산 흐름도 + 법적 근거를 한글 마크다운 문서로 자동 생성 |
| **Function/UX Effect** | 노무사가 코드 없이 "입력→공식→결과" 전 과정을 추적·검증 가능, 법령 변경 시 업데이트 포인트 즉시 식별 |
| **Core Value** | 계산기 신뢰성 확보 + 법적 리스크 사전 차단 + 연 1회 법령 개정 대응 비용 절감 |

---

## 1. Overview

### 1.1 Purpose

24개 임금계산기 모듈(통상임금, 연장수당, 퇴직금, 4대보험 등)의 **설정값(상수), 계산 공식, 판단 로직, 법적 근거**를 비개발자(노무사)가 검토할 수 있는 형태로 문서화한다.

### 1.2 Background

- 현재 계산 로직과 법적 상수가 Python 코드(`constants.py`, 각 `calculators/*.py`)에만 존재
- 노무사가 계산 정확성을 검증하려면 코드를 읽어야 하는 상황
- 법령 개정(최저임금, 보험요율 등) 시 어떤 상수를 어디서 수정해야 하는지 파악 곤란
- 대법원 판례(2023다302838 통상임금, 2023다302579 평균임금 등) 반영 여부 확인 필요

### 1.3 Related Documents

- 기존 CLAUDE.md: 프로젝트 아키텍처 개요
- `wage_calculator/constants.py`: 모든 법적 상수
- `wage_calculator/legal_hints.py`: 법률 검토 포인트
- `wage_calculator_cli.py`: 32개 테스트 케이스

---

## 2. Scope

### 2.1 In Scope

- [ ] **상수 총람**: `constants.py`의 모든 설정값을 연도별·항목별 테이블로 정리
- [ ] **계산기별 감사 시트**: 24개 계산기 각각에 대해 입력→공식→출력 문서화
- [ ] **법적 근거 매핑**: 각 계산 단계에 적용 법조문·판례 명시
- [ ] **엣지 케이스 목록**: 5인 미만 예외, 수습 특례, 일용직 기준 등 정리
- [ ] **연도별 변경 이력표**: 최저임금, 보험요율 등 연도별 변경 추적표
- [ ] **계산 예시**: 대표적 시나리오 1~2개씩 입력→계산과정→결과 포함

### 2.2 Out of Scope

- 코드 리팩토링 (문서화만 수행, 로직 변경 없음)
- 새 계산기 추가
- UI/UX 변경
- 테스트 코드 작성 (기존 `wage_calculator_cli.py` 32개 테스트 별도 존재)

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | **상수 총람 문서** — `constants.py`의 모든 상수를 카테고리별 테이블로 정리 (최저임금, 보험요율, 가산율, 세율, 실업급여, 산재, EITC 등) | High | Pending |
| FR-02 | **계산기 개요표** — 24개 계산기의 이름, 함수명, 적용 법조문, 입력 필드, 출력 항목 요약 1페이지 | High | Pending |
| FR-03 | **통상임금 감사 시트** — calc_ordinary_wage 전체 로직 (기본 환산 + 수당 포함 판단 + 월 기준시간 산정) | High | Pending |
| FR-04 | **연장·야간·휴일수당 감사 시트** — 가산율, 5인 미만 예외, 주 52시간 체크 로직 | High | Pending |
| FR-05 | **최저임금 감사 시트** — 산입범위(정기상여·복리후생), 수습 특례, 위반 판단 로직 | High | Pending |
| FR-06 | **퇴직금 감사 시트** — 평균임금 산정(3개월 vs 1년 유리 원칙), 일용직 특례, 자격 요건 | High | Pending |
| FR-07 | **4대보험·소득세 감사 시트** — 근로자/사업주 부담 요율, 상·하한, 간이세액표, 프리랜서 3.3% | High | Pending |
| FR-08 | **연차수당 감사 시트** — 발생 로직(1년 미만/이상), G1 차감, 회계기준일, 단시간 비례, 사용촉진제도 | High | Pending |
| FR-09 | **주휴수당 감사 시트** — 발생 요건, 시간 산정(2022다291153), 퇴직 마지막 주 처리 | Medium | Pending |
| FR-10 | **해고예고수당 감사 시트** — 30일분 계산, 면제 사유 5가지 | Medium | Pending |
| FR-11 | **실업급여 감사 시트** — 수급 요건, 일액 산정(상한/하한), 소정급여일수 테이블, 조기재취업 | Medium | Pending |
| FR-12 | **포괄임금제 감사 시트** — 역산 공식, 총계수시간 산정, 유효성 판단 | Medium | Pending |
| FR-13 | **육아휴직·출산휴가 감사 시트** — 급여 산정, 아빠 보너스, 사후지급금, 상한액 | Medium | Pending |
| FR-14 | **임금체불 지연이자 감사 시트** — 연 20%/6% 구분, 소멸시효, 독립 함수 구조 | Medium | Pending |
| FR-15 | **탄력근로·보상휴가·일할계산·유급공휴일 감사 시트** — 각각 핵심 공식과 조건 | Medium | Pending |
| FR-16 | **산재보상금 감사 시트** — 휴업/장해/유족/장례비 4개 항목 산정 공식 | Medium | Pending |
| FR-17 | **퇴직소득세·퇴직연금 감사 시트** — 근속연수공제, 환산급여공제, DB/DC 구분 | Medium | Pending |
| FR-18 | **근로장려금(EITC) 감사 시트** — 가구유형별 점증·평탄·점감 구간, 재산 요건, 자녀장려금 | Low | Pending |
| FR-19 | **상시근로자 수 판정 감사 시트** — 시행령 제7조의2 기준 | Low | Pending |
| FR-20 | **판례 반영 현황표** — 적용된 대법원 판례 목록과 코드 반영 위치 | High | Pending |
| FR-21 | **법령 개정 체크리스트** — 연 1회 업데이트 시 확인할 상수·로직 목록 | Medium | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| 가독성 | 노무사가 코드 지식 없이 이해 가능한 한글 문서 | 비개발자 리뷰 |
| 정확성 | 코드 내 실제 상수·공식과 100% 일치 | 코드 대조 검증 |
| 추적성 | 모든 계산 단계에 법조문·판례 번호 명시 | 법적 근거 매핑 비율 100% |
| 유지보수성 | 법령 개정 시 수정할 위치가 문서에 명시 | 체크리스트 완성도 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] 상수 총람 문서 완성 (constants.py 전체 상수 커버)
- [ ] 24개 계산기 감사 시트 완성
- [ ] 모든 계산 공식에 법적 근거 매핑
- [ ] 판례 반영 현황표 완성
- [ ] 법령 개정 체크리스트 완성
- [ ] 노무사 리뷰용 단일 진입점 문서(목차) 완성

### 4.2 Quality Criteria

- [ ] 코드 내 상수와 문서 상수 100% 일치
- [ ] 모든 계산 공식에 법조문 or 판례 번호 포함
- [ ] 계산 예시 결과가 `wage_calculator_cli.py` 테스트 결과와 일치

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| 코드 상수와 문서 불일치 | High | Medium | 문서 생성 후 gap-detector로 코드 대조 검증 |
| 법조문 인용 오류 | High | Low | 법제처 API 또는 법률 DB 크로스체크 |
| 문서량 과다로 리뷰 부담 | Medium | Medium | 계산기 개요표(1p)로 전체 조감 + 필요한 시트만 선택 리뷰 가능하게 구성 |
| 법령 개정 후 문서 미갱신 | Medium | High | 연도별 변경 이력표 + 개정 체크리스트로 업데이트 포인트 명확화 |

---

## 6. Architecture Considerations

### 6.1 Project Level Selection

| Level | Characteristics | Recommended For | Selected |
|-------|-----------------|-----------------|:--------:|
| **Starter** | Simple structure | Static sites | ☐ |
| **Dynamic** | Feature-based modules, BaaS | Web apps, SaaS | ☑ |
| **Enterprise** | Strict layer separation | Complex systems | ☐ |

### 6.2 Key Architectural Decisions

| Decision | Options | Selected | Rationale |
|----------|---------|----------|-----------|
| 문서 형식 | HTML / PDF / Markdown | Markdown | Git 버전 관리, 변경 추적, 개발자-노무사 협업 용이 |
| 문서 구조 | 단일 파일 / 계산기별 분리 | 계산기별 분리 + 통합 목차 | 리뷰 범위 선택 가능, 병렬 업데이트 |
| 출력 위치 | `docs/` / `wage_calculator/docs/` | `docs/calculator-audit/` | PDCA 문서와 분리, 노무사 전달용 독립 디렉토리 |
| 상수 정리 방식 | 코드 주석 / 별도 문서 | 별도 문서 (코드와 독립) | 비개발자 접근성 |

### 6.3 문서 구조

```
docs/calculator-audit/
├── README.md                          # 목차 + 리뷰 가이드
├── 00-constants-reference.md          # 상수 총람 (최저임금, 보험요율, 세율 등)
├── 00-calculator-overview.md          # 24개 계산기 개요표
├── 00-legal-case-mapping.md           # 판례 반영 현황표
├── 00-annual-update-checklist.md      # 법령 개정 체크리스트
├── 01-ordinary-wage.audit.md          # 통상임금
├── 02-overtime.audit.md               # 연장·야간·휴일수당
├── 03-minimum-wage.audit.md           # 최저임금
├── 04-weekly-holiday.audit.md         # 주휴수당
├── 05-annual-leave.audit.md           # 연차수당
├── 06-dismissal.audit.md              # 해고예고수당
├── 07-severance.audit.md              # 퇴직금
├── 08-average-wage.audit.md           # 평균임금
├── 09-shutdown-allowance.audit.md     # 휴업수당
├── 10-comprehensive.audit.md          # 포괄임금제
├── 11-prorated.audit.md               # 일할계산
├── 12-public-holiday.audit.md         # 유급공휴일
├── 13-insurance.audit.md              # 4대보험 + 소득세
├── 14-unemployment.audit.md           # 실업급여
├── 15-compensatory-leave.audit.md     # 보상휴가
├── 16-wage-arrears.audit.md           # 임금체불 지연이자
├── 17-parental-leave.audit.md         # 육아휴직급여
├── 18-maternity-leave.audit.md        # 출산전후휴가급여
├── 19-flexible-work.audit.md          # 탄력근로시간제
├── 20-industrial-accident.audit.md    # 산재보상금
├── 21-retirement-tax.audit.md         # 퇴직소득세
├── 22-retirement-pension.audit.md     # 퇴직연금
├── 23-business-size.audit.md          # 상시근로자 수
└── 24-eitc.audit.md                   # 근로장려금
```

### 6.4 감사 시트 표준 구조

각 계산기 감사 시트는 다음 섹션을 포함:

```markdown
# {계산기명} 감사 시트

## 1. 개요
- 계산기 이름 / 코드 파일 / 함수명
- 적용 법조문

## 2. 입력 항목
| 필드명 | 설명 | 타입 | 기본값 | 필수 |

## 3. 적용 상수
| 상수명 | 값 | 단위 | 근거 법조문 | 코드 위치 |

## 4. 계산 과정
### Step 1: ...
- 공식: ...
- 법적 근거: ...
### Step 2: ...

## 5. 출력 항목
| 항목 | 설명 | 단위 |

## 6. 예외 처리 / 엣지 케이스
| 조건 | 처리 | 법적 근거 |

## 7. 계산 예시
### 예시 1: [시나리오명]
- 입력: ...
- 계산 과정: ...
- 결과: ...

## 8. 관련 판례
| 판례 번호 | 요지 | 코드 반영 위치 |
```

---

## 7. Convention Prerequisites

### 7.1 Existing Project Conventions

- [x] `CLAUDE.md` has coding conventions section
- [x] 금액 표시: 원 단위, `{:,.0f}` 포맷
- [x] 법적 참조: "근로기준법 제N조" / "대법원 YYYY다NNNN"
- [x] 변수명: 한글 키 사용 (facade.py `_provided_info_to_input()`)

### 7.2 문서 작성 규칙

| Category | Rule | Priority |
|----------|------|:--------:|
| 금액 | 원 단위, 천 단위 콤마 구분 (예: 2,500,000원) | High |
| 비율 | 퍼센트 표기 (예: 4.5%, 0.5배) | High |
| 법조문 | "근로기준법 제N조제M항" 형식 | High |
| 판례 | "대법원 YYYY.M.D. 선고 YYYY다NNNN 판결" 형식 | High |
| 공식 | 한글 변수명 사용 (예: 통상시급 × 연장시간 × 1.5) | High |
| 연도 | 2025년/2026년 기준 명시 | Medium |

---

## 8. 구현 전략

### 8.1 단계별 접근

| 단계 | 산출물 | 계산기 수 | 예상 분량 |
|------|--------|:---------:|:---------:|
| 1단계 | 상수 총람 + 개요표 + 판례 현황표 | - | ~3 문서 |
| 2단계 | 핵심 계산기 감사 시트 (통상임금, 연장수당, 최저임금, 퇴직금, 4대보험, 연차) | 6개 | ~6 문서 |
| 3단계 | 중요 계산기 감사 시트 (주휴, 해고예고, 실업급여, 포괄임금, 육아/출산, 임금체불) | 7개 | ~7 문서 |
| 4단계 | 나머지 계산기 감사 시트 + 법령 개정 체크리스트 | 11개 + 1 | ~12 문서 |
| 5단계 | 통합 목차(README) + 최종 검수 | - | 1 문서 |

### 8.2 문서 생성 원칙

1. **코드에서 직접 추출**: 문서의 모든 상수·공식은 실제 코드와 1:1 대응
2. **법조문 필수**: 계산 단계마다 적용 법조문 또는 판례 명시
3. **계산 예시 필수**: 최소 1개 시나리오의 전체 계산 과정 서술
4. **엣지 케이스 명시**: 5인 미만, 수습, 일용직, 단시간 등 예외 상황 별도 정리

---

## 9. Next Steps

1. [ ] Design 문서 작성 (`calculator-audit-docs.design.md`)
2. [ ] 상수 총람 + 개요표 작성 (1단계)
3. [ ] 핵심 계산기 6개 감사 시트 작성 (2단계)
4. [ ] 전체 감사 시트 완성 (3~4단계)
5. [ ] 통합 목차 + Gap Analysis

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-08 | Initial draft | PDCA |
