# calculator-refactor Planning Document

> **Summary**: 임금계산기 모듈 34개 파일의 코드 중복 제거, 공통 유틸 추출, 타입 안전성 강화
>
> **Project**: laborconsult (노동법 임금계산기)
> **Author**: Claude Code
> **Date**: 2026-03-12
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 24개 계산기 모듈에 날짜 파싱, 수당 분류, 배율 로직, breakdown 생성 등 동일 패턴이 10회 이상 반복되어 유지보수 비용 증가 |
| **Solution** | 공통 유틸(`shared.py`) 추출, `FixedAllowance` 데이터클래스 도입, facade.py 분리, 반올림 정책 통일 |
| **Function/UX Effect** | 외부 API 변경 없음. 내부 코드량 ~30% 감소, 신규 계산기 추가 시 보일러플레이트 절반으로 감소 |
| **Core Value** | 법률 변경 시 수정 포인트 최소화 → 연간 유지보수 비용 절감, 버그 발생 확률 감소 |

---

## 1. Overview

### 1.1 Purpose

`wage_calculator/` 패키지(34 파일, ~5,500줄)의 내부 코드 품질을 개선한다.
- 10개 이상의 반복 패턴을 공통 유틸로 추출
- 매직 스트링 딕셔너리 접근을 타입 안전한 데이터클래스로 전환
- 700줄 facade.py를 역할별로 분리
- 반올림 전략 불일치 해소

### 1.2 Background

- 19개 계산기가 순차적으로 추가되면서 자연스러운 코드 중복 누적
- `fixed_allowances`가 `list[dict]`로 15개+ 모듈에서 `.get()` 패턴 반복
- 날짜 계산 로직이 8개 모듈에서 각각 독립 구현 (일부 불일치: `365일` vs `30.44일/월`)
- 5인 미만 사업장 배율 분기가 5곳에서 반복
- `round()`, `int()`, 무처리가 혼재하여 연쇄 계산 시 미세 오차 가능성

### 1.3 Related Documents

- `CLAUDE.md` — 프로젝트 아키텍처 설명
- `wage_calculator_cli.py` — 32개 테스트 케이스 (회귀 테스트 기준)

---

## 2. Scope

### 2.1 In Scope

- [ ] **P1**: `calculators/shared.py` 신설 — DateRange, AllowanceClassifier, MultiplierContext 추출
- [ ] **P2**: `FixedAllowance` 데이터클래스 도입 (`models.py` 확장)
- [ ] **P3**: `facade.py` 분리 (registry, population_helpers, input_conversion)
- [ ] **P4**: 반올림 정책 통일 (`utils.py` 확장)
- [ ] **P5**: 수당 분류 키워드 패턴 통합 (3곳 → `shared.py`)
- [ ] **P6**: 각 계산기 모듈에서 공통 유틸 적용

### 2.2 Out of Scope

- 외부 API 변경 (`WageCalculator.calculate()`, `from_analysis()` 시그니처 유지)
- 새로운 계산기 추가
- `WageInput` 필드 추가/삭제
- chatbot.py, pinecone_upload.py 등 계산기 외부 모듈
- 성능 최적화 (현재 충분)
- 테스트 프레임워크 도입 (pytest 등) — 기존 CLI 테스트로 회귀 검증

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | `shared.py`에 DateRange 클래스 추출 — 8개 모듈의 날짜 파싱/근속연수 계산 통합 | High | Pending |
| FR-02 | `shared.py`에 AllowanceClassifier 추출 — minimum_wage, ordinary_wage, legal_hints 3곳 통합 | High | Pending |
| FR-03 | `shared.py`에 MultiplierContext 추출 — 5인 미만 배율 분기 5곳 통합 | High | Pending |
| FR-04 | `models.py`에 FixedAllowance 데이터클래스 추가, WageInput.fixed_allowances 타입 변경 | High | Pending |
| FR-05 | `facade.py` → 3~4개 모듈로 분리 (registry, helpers, conversion) | Medium | Pending |
| FR-06 | `utils.py`에 RoundingPolicy enum + apply_rounding() 함수 추가 | Medium | Pending |
| FR-07 | 각 계산기 모듈에서 새 유틸 적용 (단계별 마이그레이션) | Medium | Pending |
| FR-08 | 32개 CLI 테스트 전체 통과 확인 (회귀 테스트) | High | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| 호환성 | 기존 32개 테스트 케이스 100% 통과 | `python3 wage_calculator_cli.py` |
| 코드 감소 | 전체 코드줄 20%+ 감소 | `wc -l` 비교 |
| 중복 제거 | 날짜 파싱 패턴 8곳 → 1곳 | Grep 검색 |
| 타입 안전성 | `a.get("condition")` 패턴 0건 | Grep 검색 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] 모든 공통 유틸 (`shared.py`, `utils.py`) 구현 완료
- [ ] `FixedAllowance` 데이터클래스 적용 완료
- [ ] `facade.py` 분리 완료
- [ ] 24개 계산기 모듈 마이그레이션 완료
- [ ] 32개 CLI 테스트 전체 PASS
- [ ] `__init__.py` public API 변경 없음 확인

### 4.2 Quality Criteria

- [ ] `python3 wage_calculator_cli.py` — 32/32 PASS
- [ ] 금액 계산 결과 기존과 동일 (원 단위 일치)
- [ ] import 에러 없음

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| FixedAllowance 전환 시 기존 dict 호환성 깨짐 | High | Medium | dict → dataclass 변환 함수 제공, 점진적 마이그레이션 |
| facade.py 분리 시 순환 import | Medium | Medium | 의존성 방향 사전 분석, 단방향 import 원칙 |
| 반올림 정책 통일 시 기존 금액 미세 차이 | High | Low | 32개 테스트 결과 원 단위까지 비교 검증 |
| 대규모 리팩토링으로 인한 병합 충돌 | Medium | Low | feature branch에서 작업, 단계별 커밋 |
| DateRange 도입 시 edge case 누락 | Medium | Low | 기존 8개 모듈의 날짜 처리 패턴 전수조사 후 반영 |

---

## 6. Architecture Considerations

### 6.1 Project Level Selection

| Level | Characteristics | Recommended For | Selected |
|-------|-----------------|-----------------|:--------:|
| **Starter** | Simple structure | Static sites | ☐ |
| **Dynamic** | Feature-based modules | Web apps with backend | ☒ |
| **Enterprise** | Strict layer separation | High-traffic systems | ☐ |

> Python 패키지 리팩토링 — facade 패턴 유지, 내부 구조만 개선

### 6.2 Key Architectural Decisions

| Decision | Options | Selected | Rationale |
|----------|---------|----------|-----------|
| 공통 유틸 위치 | `utils.py` 확장 / `shared.py` 신설 | `calculators/shared.py` 신설 | 계산기 전용 헬퍼와 일반 유틸 분리 |
| FixedAllowance 타입 | TypedDict / dataclass / Pydantic | dataclass | 외부 의존성 없음, 기존 패턴과 일관 |
| facade 분리 전략 | 단일 파일 유지 / 3개 분리 / 서브패키지 | 3개 모듈로 분리 | 700줄 → ~250줄×3, 역할 명확화 |
| dict→dataclass 전환 | 일괄 전환 / 점진적 전환 | 점진적 전환 | 호환 함수로 기존 dict 입력도 수용 |
| 반올림 정책 | 전역 round() / calculator별 설정 | utils.py에 정책 enum | 일관성 확보, 법적 근거별 다른 정책 허용 |

### 6.3 리팩토링 후 구조 Preview

```
wage_calculator/
├── __init__.py              # Public API (변경 없음)
├── models.py                # + FixedAllowance dataclass
├── constants.py             # 변경 없음
├── result.py                # 변경 없음
├── base.py                  # 변경 없음
├── utils.py                 # + RoundingPolicy, apply_rounding
├── ordinary_wage.py         # shared.py 유틸 적용
├── legal_hints.py           # AllowanceClassifier 적용
├── shift_work.py            # 변경 없음
├── facade/                  # 기존 facade.py → 분리
│   ├── __init__.py          # WageCalculator 클래스 (메인 로직)
│   ├── registry.py          # _STANDARD_CALCS, CALC_TYPE_MAP
│   ├── helpers.py           # _pop_*() 함수들
│   └── conversion.py        # _provided_info_to_input()
└── calculators/
    ├── __init__.py
    ├── shared.py             # [신규] DateRange, AllowanceClassifier, MultiplierContext
    ├── overtime.py           # shared.py 적용
    ├── minimum_wage.py       # AllowanceClassifier 적용
    ├── severance.py          # DateRange 적용
    ├── annual_leave.py       # DateRange 적용
    ├── ... (나머지 20개)
    └── wage_arrears.py
```

---

## 7. Convention Prerequisites

### 7.1 Existing Project Conventions

- [x] `CLAUDE.md` has coding conventions section
- [ ] ESLint/Prettier — N/A (Python project)
- [x] 기존 코딩 컨벤션: facade 패턴, `calc_*()` 함수 네이밍, `WageInput` → `Result` 패턴

### 7.2 Conventions to Define/Verify

| Category | Current State | To Define | Priority |
|----------|---------------|-----------|:--------:|
| **Import 순서** | 비일관적 | stdlib → third-party → local 순서 통일 | Medium |
| **반올림 정책** | 혼재 (round/int/무처리) | RoundingPolicy enum 사용 원칙 | High |
| **헬퍼 함수 접근** | private `_func()` 남발 | shared.py public / 모듈 내 private 구분 | High |
| **dataclass 필드 기본값** | 0.0 vs None 혼재 | 숫자=0.0, 옵션=None 원칙 | Medium |

---

## 8. Implementation Order

단계별 마이그레이션으로 위험 최소화:

### Phase A — Foundation (공통 유틸 구축)
1. [ ] `calculators/shared.py` 생성 (DateRange, AllowanceClassifier, MultiplierContext)
2. [ ] `utils.py` 확장 (RoundingPolicy)
3. [ ] `models.py`에 FixedAllowance 추가 + dict 호환 함수
4. [ ] 테스트 통과 확인 (기존 코드 변경 없이 추가만)

### Phase B — Core Migration (핵심 모듈 전환)
5. [ ] `ordinary_wage.py` — shared.py 유틸 적용
6. [ ] `minimum_wage.py` — AllowanceClassifier 적용
7. [ ] `overtime.py` — MultiplierContext 적용
8. [ ] `severance.py`, `annual_leave.py` — DateRange 적용
9. [ ] 테스트 통과 확인

### Phase C — Broad Migration (전체 계산기 전환)
10. [ ] 나머지 19개 계산기 모듈 마이그레이션
11. [ ] `legal_hints.py` — AllowanceClassifier 적용
12. [ ] 테스트 통과 확인

### Phase D — Facade Split (구조 분리)
13. [ ] `facade.py` → `facade/` 서브패키지 분리
14. [ ] `__init__.py` import 경로 확인
15. [ ] 최종 테스트 통과 확인

---

## 9. Next Steps

1. [ ] Design 문서 작성 (`calculator-refactor.design.md`)
2. [ ] Phase A부터 구현 시작
3. [ ] 각 Phase 완료 시 32개 테스트 회귀 검증

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-12 | Initial draft | Claude Code |
