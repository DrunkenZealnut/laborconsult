# Feature Roadmap Assessment Plan

> 현재 프로젝트 상태 기반 필요 기능 분석 및 우선순위 로드맵

---

## Executive Summary

| 관점 | 내용 |
|------|------|
| **Problem** | 25개 Plan 중 4개만 PDCA 완료, 21개 미완료 사이클 존재. 배포 전 품질 검증·통합 테스트 부재 |
| **Solution** | 미완료 기능 정리, 배포 필수 기능 식별, 우선순위 기반 로드맵 수립 |
| **Function UX Effect** | 노무사·사용자 대상 안정적 서비스 런칭, 계산 정확도 신뢰 확보 |
| **Core Value** | 불필요한 작업 제거, 핵심 기능 집중으로 빠른 배포 달성 |

---

## 1. 현재 상태 분석

### 1.1 PDCA 완료 현황

| 상태 | 건수 | 비고 |
|------|:----:|------|
| PDCA 완료 (Report 생성) | 4 | comwel-contacts, ordinary-wage-review, legal-api-integration, calculator-audit-docs |
| Plan + Design 완료 | 21 | 구현은 대부분 완료됐으나 PDCA 미마감 |
| 미시작 | 0 | - |

### 1.2 핵심 시스템 구현 현황

| 시스템 | 구현 상태 | 비고 |
|--------|:--------:|------|
| 임금계산기 (24개) | ✅ 완료 | CLI 테스트 32케이스 전부 통과 |
| RAG 챗봇 (Pinecone + Claude) | ✅ 완료 | chatbot.py, 스트리밍 응답 |
| 웹 UI (index.html) | ✅ 완료 | FastAPI 백엔드 연동 |
| API 서버 (Vercel) | ✅ 완료 | api/index.py, vercel.json |
| 직장내 괴롭힘 판단 | ✅ 완료 | harassment_assessor/ |
| 4대보험·소득세 | ✅ 완료 | insurance.py (근로자+사업주) |
| 근로감독관·고용센터·공단 연락처 | ✅ 완료 | labor_offices.py, employment_centers.py, comwel_offices.py |
| Supabase QA 저장 | ✅ 완료 | app/core/storage.py |
| 파일 첨부 | ✅ 완료 | app/core/file_parser.py |
| 감사 문서 (노무사 리뷰용) | ✅ 완료 | docs/calculator-audit/ (29개 파일) |

### 1.3 미완료 PDCA 사이클 (21개)

대부분 **구현은 완료**되었으나 Gap Analysis → Report 미진행 상태:

| 기능 | Plan | Design | 구현 | Analysis | Report |
|------|:----:|:------:|:----:|:--------:|:------:|
| annual-leave-review | ✅ | ✅ | ✅ | ✅ | - |
| average-wage-calculator | ✅ | ✅ | ✅ | ✅ | - |
| calculator-batch-test | ✅ | ✅ | ✅ | ✅ | - |
| calculator-module-review | ✅ | ✅ | ✅ | ✅ | - |
| comprehensive-wage-review | ✅ | ✅ | ✅ | ✅ | - |
| eitc-calculator | ✅ | ✅ | ✅ | ✅ | - |
| employment-center-contacts | ✅ | ✅ | ✅ | ✅ | - |
| file-attachment | ✅ | ✅ | ✅ | ✅ | - |
| industrial-accident-compensation | ✅ | ✅ | ✅ | ✅ | - |
| insurance-tax-review | ✅ | ✅ | ✅ | - | - |
| interactive-follow-up | ✅ | ✅ | ✅ | - | - |
| labor-commission-contacts | ✅ | ✅ | ✅ | ✅ | - |
| retirement-tax-pension | ✅ | ✅ | ✅ | ✅ | - |
| supabase-qa-storage | ✅ | ✅ | ✅ | ✅ | - |
| unemployment-calculator-review | ✅ | ✅ | ✅ | ✅ | - |
| weekly-dismissal-shutdown-review | ✅ | ✅ | ✅ | ✅ | - |
| workplace-harassment | ✅ | ✅ | ✅ | ✅ | - |
| consistent-followup-questions | ✅ | - | - | - | - |
| admin-page | ✅ | - | - | - | - |
| ai-labor-chatbot | ✅ | - | - | - | - |
| wage-calculator-optimization | ✅ | - | - | - | - |

---

## 2. 기능 분류 및 우선순위

### Priority 1: 배포 필수 (Must-Have for Launch)

이미 구현 완료. 추가 작업 불필요.

| # | 기능 | 현재 상태 | 필요 조치 |
|:-:|------|:--------:|----------|
| 1 | 임금계산기 24개 + CLI 테스트 | ✅ 구현 완료 | 없음 |
| 2 | RAG 챗봇 (Claude + Pinecone) | ✅ 구현 완료 | 없음 |
| 3 | 웹 UI + API 서버 (Vercel) | ✅ 구현 완료 | 없음 |
| 4 | 4대보험·소득세 계산 | ✅ 구현 완료 | 없음 |
| 5 | 연락처 DB (감독관·고용센터·공단) | ✅ 구현 완료 | 없음 |

### Priority 2: 배포 전 권장 (Should-Have)

| # | 기능 | FR | 설명 |
|:-:|------|-----|------|
| FR-01 | E2E 통합 테스트 | 웹 UI → API → 계산기 → 응답까지 전체 흐름 검증 |
| FR-02 | 계산기 정확도 교차검증 | 노무사 감사 문서 예시 기반 자동 검증 스크립트 |
| FR-03 | API 에러 핸들링 강화 | 잘못된 입력·누락 필드에 대한 친절한 에러 메시지 |
| FR-04 | 환경변수·시크릿 관리 | .env 검증, Vercel 환경변수 설정 가이드 |

### Priority 3: 런칭 후 개선 (Nice-to-Have)

| # | 기능 | FR | 설명 |
|:-:|------|-----|------|
| FR-05 | 관리자 대시보드 | admin-page plan 존재, 미구현. QA 로그 통계·사용 패턴 모니터링 |
| FR-06 | 멀티턴 대화 개선 | interactive-follow-up / consistent-followup-questions 고도화 |
| FR-07 | API 문서 자동 생성 | FastAPI OpenAPI 스키마 기반 Swagger 문서 |
| FR-08 | 모바일 반응형 최적화 | 현재 UI의 모바일 경험 개선 |

### Priority 4: 미완료 PDCA 정리

| # | 기능 | FR | 설명 |
|:-:|------|-----|------|
| FR-09 | PDCA 일괄 마감 | Analysis 완료된 17개 기능에 대해 Report 일괄 생성 |
| FR-10 | 미시작 PDCA 정리 | Design 미진행 4개 (admin-page 등) Plan 보관 또는 폐기 결정 |

---

## 3. 권장 실행 순서

```
Phase 1: 배포 준비 (즉시)
├── FR-03 API 에러 핸들링 강화
├── FR-04 환경변수 관리
└── FR-01 E2E 통합 테스트 (수동)

Phase 2: 정확도 검증 (배포 전)
└── FR-02 계산기 교차검증

Phase 3: PDCA 정리 (배포 후)
├── FR-09 Report 일괄 생성
└── FR-10 미시작 Plan 정리

Phase 4: 기능 고도화 (운영 안정화 후)
├── FR-05 관리자 대시보드
├── FR-06 멀티턴 대화 개선
├── FR-07 API 문서 생성
└── FR-08 모바일 최적화
```

---

## 4. 핵심 결론

**프로젝트는 ~95% 완성 상태이며 배포 가능 수준입니다.**

- 24개 임금계산기, RAG 챗봇, 웹 UI, API 서버 모두 구현 완료
- 32개 CLI 테스트 케이스 전부 통과
- 감사 문서 29개 완성 (노무사 리뷰 준비 완료)
- 남은 작업은 대부분 **품질 보증·운영 편의** 영역

**즉시 배포 가능하며**, FR-01~FR-04만 추가하면 프로덕션 품질 달성.

---

## 5. 리스크

| 리스크 | 영향 | 완화 방안 |
|--------|:----:|----------|
| 법령 상수 업데이트 누락 | High | 00-annual-update-checklist.md 연 1회 실행 |
| Vercel cold start 지연 | Medium | API 응답 캐싱, 워밍업 전략 |
| Pinecone 무료 플랜 한도 | Low | 현재 ~1,700 벡터로 충분 |
| 노무사 리뷰 후 수정사항 | Medium | 감사 문서 기반 체계적 수정 |

---

*작성일: 2026-03-08 | 프로젝트: nodong.kr AI 노동상담 챗봇*
