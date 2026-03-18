# 계산기 플로우 메뉴 페이지 Plan

## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | calculator_flow HTML 시각화를 메뉴 형태로 제공 |
| 시작일 | 2026-03-18 |
| 예상 기간 | 0.5일 |
| Level | Dynamic |

### Value Delivered

| 관점 | 내용 |
|------|------|
| **Problem** | 25개 계산기 플로우 시각화 HTML이 `wage_calculator/calculator_flow/`에 개별 파일로 존재하여, 사용자가 어떤 계산기가 있는지 파악하기 어렵고 접근이 불편함 |
| **Solution** | 카테고리별로 분류된 메뉴 페이지(`public/calculators.html`)를 만들어, 한 페이지에서 모든 계산기 플로우를 탐색할 수 있도록 함 |
| **Function UX Effect** | 사용자가 "임금 계산은 어떻게 이루어지나?" 궁금할 때, 시각적 플로우차트로 단계별 계산 과정을 직관적으로 이해할 수 있음 |
| **Core Value** | 노동법 계산기의 투명성 확보 — "블랙박스가 아닌 설명 가능한 계산기"로 사용자 신뢰 향상 |

---

## 1. 현황 분석

### 1.1 기존 자산

`wage_calculator/calculator_flow/` 디렉토리에 **25개 HTML** + **3개 MD** + **1개 의존관계맵** 존재:

| 카테고리 | 파일명 | 한글명 |
|----------|--------|--------|
| **기본 임금** | `ordinary_wage_calculation_flow.html` | 통상임금 계산 (핵심 5단계) |
| | `average_wage_calculation_flow.html` | 평균임금 계산 |
| | `minimum_wage_verification_flow.html` | 최저임금 검증 |
| | `comprehensive_wage_reverse_calc.html` | 포괄임금제 역산 |
| **수당 계산** | `overtime_night_holiday_pay_calc.html` | 연장·야간·휴일수당 |
| | `weekly_holiday_pay_calc.html` | 주휴수당 |
| | `annual_leave_pay_calc.html` | 연차수당 |
| | `compensatory_leave_calc.html` | 보상휴가 |
| **퇴직·해고** | `severance_pay_calculation_flow.html` | 퇴직금 계산 |
| | `dismissal_notice_pay_calc.html` | 해고예고수당 |
| | `shutdown_allowance_calc.html` | 휴업수당 |
| **보험·세금** | `insurance_income_tax_calc.html` | 4대보험·소득세 |
| | `employer_insurance_burden_calc.html` | 사업주 보험부담금 |
| | `retirement_income_tax_calc.html` | 퇴직소득세 |
| | `eitc_calculation_flow.html` | 근로장려금(EITC) |
| **휴직·출산** | `maternity_leave_benefit_flow.html` | 출산휴가급여 |
| | `parental_leave_benefit_calculator.html` | 육아휴직급여 |
| | `unemployment_benefit_calc.html` | 실업급여 |
| **근로시간** | `flexible_work_hours_calc.html` | 탄력근무 시간 |
| | `mid_month_proration_calc.html` | 중도입퇴사 일할계산 |
| **연금·체불** | `retirement_pension_db_dc_calc.html` | 퇴직연금 DB/DC |
| | `wage_arrears_interest_calc.html` | 임금체불 지연이자 |
| **사업장** | `business_size_worker_count_v3.html` | 사업장 규모 판단 |
| **산재** | `industrial_accident_compensation_calc.html` | 산업재해 보상 |
| **전체 구조** | `wage_calculator_dependency_map.html` | 계산기 의존관계 맵 |

- 모든 HTML은 **standalone** (외부 의존성 없음, inline CSS/JS/SVG)
- 다크모드 지원 (`prefers-color-scheme: dark`)
- 탭 기반 단계별 설명 + SVG 플로우차트

### 1.2 배포 환경

- **Vercel**: `public/**` → `@vercel/static`
- 현재 `public/` 에는 `index.html` (챗봇), `admin.html` (관리자)만 존재
- `vercel.json` 라우팅: `/(.*\\..*)`→`/public/$1`

---

## 2. 구현 계획

### 접근 방식: 단일 메뉴 페이지 + iframe embed

**`public/calculators.html`** 1개 파일로 구현:

1. **좌측/상단 메뉴**: 카테고리별로 그룹화된 계산기 목록
2. **우측/하단 뷰어**: 선택한 계산기 HTML을 iframe으로 표시
3. **모바일 대응**: 메뉴 → 클릭 → 전체화면 뷰어 전환
4. **챗봇 연동**: 챗봇 헤더에 "계산기 플로우" 링크 추가

### 구현 상세

#### 2.1 파일 배치

```
public/
├── index.html              # 기존 챗봇
├── admin.html              # 기존 관리자
├── calculators.html         # [신규] 메뉴 페이지
└── calculator_flow/         # [이동] HTML 파일들
    ├── ordinary_wage_calculation_flow.html
    ├── ... (25개)
    └── wage_calculator_dependency_map.html
```

- `calculator_flow/` 디렉토리를 `public/` 하위로 복사/이동
- Vercel static 라우팅이 자동으로 서빙

#### 2.2 메뉴 구조 (카테고리 6개)

```
📊 전체 구조
  └── 계산기 의존관계 맵

💰 기본 임금 (4)
  ├── 통상임금 계산
  ├── 평균임금 계산
  ├── 최저임금 검증
  └── 포괄임금제 역산

⏰ 수당 계산 (4)
  ├── 연장·야간·휴일수당
  ├── 주휴수당
  ├── 연차수당
  └── 보상휴가

🏢 퇴직·해고 (3)
  ├── 퇴직금 계산
  ├── 해고예고수당
  └── 휴업수당

🛡️ 보험·세금·연금 (6)
  ├── 4대보험·소득세
  ├── 사업주 보험부담금
  ├── 퇴직소득세
  ├── 근로장려금(EITC)
  ├── 퇴직연금 DB/DC
  └── 임금체불 지연이자

👶 휴직·급여 (3)
  ├── 출산휴가급여
  ├── 육아휴직급여
  └── 실업급여

⚙️ 근로조건 (4)
  ├── 탄력근무 시간
  ├── 중도입퇴사 일할계산
  ├── 사업장 규모 판단
  └── 산업재해 보상
```

#### 2.3 UI 요구사항

- **데스크톱**: 2-column 레이아웃 (좌측 메뉴 250px + 우측 iframe 뷰어)
- **모바일**: 메뉴 목록 → 탭하면 전체화면 뷰어 (뒤로가기 지원)
- **디자인**: 챗봇(`index.html`)과 동일한 디자인 톤 (var(--primary), 같은 폰트)
- **다크모드**: 자동 대응
- **네비게이션**: 챗봇 헤더에 "📊 계산 흐름도" 링크 추가

#### 2.4 vercel.json 라우팅 추가

```json
{ "src": "/calculators", "dest": "/public/calculators.html" }
```

---

## 3. 일정

| 단계 | 내용 | 소요 |
|------|------|------|
| 1 | `calculator_flow/` → `public/calculator_flow/` 복사 | 5분 |
| 2 | `public/calculators.html` 메뉴 페이지 구현 | 2시간 |
| 3 | `public/index.html` 헤더에 링크 추가 | 10분 |
| 4 | `vercel.json` 라우팅 추가 | 5분 |
| 5 | 테스트 (데스크톱/모바일/다크모드) | 30분 |

### 성공 기준

- 25개 계산기 플로우를 카테고리별로 탐색 가능
- 모바일에서 원활한 사용 (터치, 스크롤, 뒤로가기)
- 챗봇에서 1클릭으로 접근 가능
- 다크모드 정상 동작

### 리스크

| 리스크 | 대응 |
|--------|------|
| HTML 파일 25개 (총 ~750KB) 배포 용량 | Vercel 무료 플랜 한도 내 (충분) |
| iframe 내 SVG 렌더링 성능 | standalone HTML이라 문제 없음 |
| 모바일에서 iframe 스크롤 충돌 | `overflow: auto` + touch-action 처리 |

---

## 4. 제외 사항 (YAGNI)

- **검색 기능**: 25개 항목이라 카테고리 탐색만으로 충분
- **즐겨찾기/최근 본 기능**: 과도
- **계산기 플로우 내 데이터 입력 연동**: 별도 기능
- **platform.md 3개 파일**: 개발 참고용이므로 메뉴에 포함하지 않음
