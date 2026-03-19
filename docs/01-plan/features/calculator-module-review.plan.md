# Plan: 전체 계산기 모듈 리뷰 및 코드 정돈

## Executive Summary

| 관점 | 설명 |
|------|------|
| **문제** | 프로젝트에 macOS 중복 파일(" 2.py") 378개 산재, wage_calculator 내 28개 — 일부는 최신 코드 대비 287줄 이상 누락된 구버전으로 잠재적 import 충돌·혼란 유발 |
| **해결** | 중복 파일 전수 삭제, import 정렬 통일, facade.py `_pop_*` 함수 docstring 추가, 코드 일관성 표준화 |
| **기능·UX 효과** | 개발자가 어떤 파일이 실제 코드인지 혼란 없이 작업 가능; IDE 자동완성·검색 정확도 향상 |
| **핵심 가치** | 23개 계산기 × 85개 테스트를 안정적으로 유지하면서 코드베이스 위생(hygiene)을 확보 |

---

## 1. 배경 및 문제 정의

### 1.1 현황
- **wage_calculator/** 패키지: 23개 계산기, 85개 테스트 케이스 전체 통과
- Facade 패턴(`WageCalculator`) + `_STANDARD_CALCS` dispatcher로 잘 구조화됨
- 코드 품질 자체는 양호하나 **환경 위생(hygiene) 문제**가 심각

### 1.2 발견된 문제

#### P0: 중복 파일 (CRITICAL)
- **wage_calculator/ 내 28개** `" 2.py"` 파일 존재 (macOS Finder 복사 부산물)
- **프로젝트 전체 378개** 중복 파일
- 위험도:
  - `constants 2.py`: 2024~2026년 최저임금 데이터 없음 (구버전)
  - `annual_leave 2.py`: 최신 287줄 업데이트 누락
  - `facade 2.py`, `models 2.py`: 최근 추가된 필드/메서드 미반영
  - Python import 시 공백 포함 파일명은 직접 import 불가하나 IDE 혼란 유발

#### P1: Import 정렬 비일관성
- 일부 파일: stdlib → 3rd-party → local 순서 (PEP 8 준수)
- 일부 파일: 정렬 없이 혼재
- 약 15개 calculator 파일에서 경미한 비일관성 발견

#### P2: `_pop_*` 함수 docstring 부재
- `facade.py` 내 21개 `_pop_*` 함수에 docstring 없음
- 각 함수가 result.summary에 어떤 키를 추가하는지 문서화 필요

#### P3: 프로젝트 루트 잡파일
- 루트에 `" 2.py"`, `" 2.json"`, `" 2.html"` 등 약 350개 중복 파일 산재
- `.gitignore 2`, `.env 2.example` 등 설정 파일 중복도 포함

---

## 2. 목표

| 우선순위 | 항목 | 완료 기준 |
|----------|------|-----------|
| **P0** | wage_calculator/ 내 28개 중복 파일 삭제 | 0개 `" 2"` 파일 |
| **P0** | 프로젝트 루트 ~350개 중복 파일 삭제 | 0개 `" 2"` 파일 |
| **P1** | import 정렬 통일 (stdlib → local) | 모든 .py 파일 PEP 8 import 순서 |
| **P2** | `_pop_*` 함수 docstring 추가 | 21개 함수 모두 1줄 docstring |
| **P3** | 85개 테스트 전체 통과 유지 | `wage_calculator_cli.py` 85/85 pass |

---

## 3. 범위

### In Scope
- wage_calculator/ 패키지 전체 (23개 계산기 + facade + models + constants + utils)
- 프로젝트 루트의 `" 2"` 중복 파일 전수 삭제
- Import 순서 정리
- `_pop_*` docstring 추가
- 기존 85개 테스트 무결성 확인

### Out of Scope
- 새로운 계산기 추가
- 계산 로직 변경
- 테스트 케이스 추가/수정
- chatbot/RAG 파이프라인 코드
- `wage_calculator_cli.py` 구조 변경

---

## 4. 구현 전략

### Phase 1: 중복 파일 삭제 (P0)
1. wage_calculator/ 내 28개 `" 2.py"` 파일 삭제
2. 프로젝트 루트 ~350개 `" 2"` 중복 파일 삭제
3. 삭제 후 테스트 실행하여 영향 없음 확인

### Phase 2: Import 정렬 (P1)
1. 모든 calculator 파일 import 블록 정리
   - 그룹 1: stdlib (datetime, math, dataclasses 등)
   - 그룹 2: local imports (from ..models, from ..constants 등)
   - 그룹 간 빈 줄 1개
2. 알파벳 순 정렬

### Phase 3: Docstring 추가 (P2)
1. `facade.py` 내 21개 `_pop_*` 함수에 1줄 docstring 추가
   - 형식: `"""result.summary에 {키이름} 추가."""`
2. 기존 로직 변경 없음

### Phase 4: 검증 (P3)
1. 전체 85개 테스트 실행 → 모두 통과 확인
2. Python import 검증 (각 모듈 import 가능 확인)

---

## 5. 위험 요소

| 위험 | 영향 | 대응 |
|------|------|------|
| 중복 파일 중 실제 사용 중인 것이 있을 수 있음 | 높음 | 삭제 전 git status 확인, `" 2"` 파일은 Python import 불가하므로 안전 |
| Import 정렬 시 순환 의존성 발견 가능 | 중간 | 정렬만 하고 구조 변경 안 함 |
| 대량 파일 삭제로 git diff 과다 | 낮음 | 단계별 커밋 |

---

## 6. 성공 지표

- [ ] wage_calculator/ 내 `" 2"` 파일 0개
- [ ] 프로젝트 전체 `" 2"` 파일 0개
- [ ] 85개 테스트 전체 통과
- [ ] Import 정렬 PEP 8 준수
- [ ] `_pop_*` 함수 docstring 100% 커버
