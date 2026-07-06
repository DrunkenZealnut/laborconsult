# 네이버 지식iN 테스트 보완 사항 Planning Document

> **Summary**: 지식iN 고용·노동 10건 테스트에서 발견된 면책 고지 누락·응답 시간 과다 문제 보완
>
> **Project**: laborconsult
> **Author**: Claude
> **Date**: 2026-03-20
> **Status**: Draft
> **Branch**: `feat/naver-kin-test-improvements`

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 10건 테스트 중 8건(80%)에서 면책 고지 누락, 1건 응답 시간 90초 과다, 환각 판례 1건 감지. 모든 답변이 정상 생성되었으나 법적 안전장치와 성능에 개선 필요 |
| **Solution** | 3개 FR: ① 시스템 프롬프트 면책 고지 강화 ② 응답 시간 최적화 (환각 교정 Gemini→Haiku 전환) ③ 테스트 자동화 스크립트 정비 |
| **Function/UX Effect** | 모든 답변에 면책 고지 100% 포함, 평균 응답 시간 59초→45초 이하 목표, 198건 전량 자동 테스트 가능 |
| **Core Value** | 법적 리스크 방어 강화 + 사용자 체감 속도 개선 + 지속적 품질 검증 체계 구축 |

---

## 1. Overview

### 1.1 테스트 결과 분석

네이버 지식iN 고용·노동 카테고리 198건 중 8개 분야별 대표 10건을 `process_question()` 파이프라인으로 테스트한 결과:

#### 성과

- **성공률 100%** — 10/10 전량 정상 답변 생성
- **답변 품질** — 평균 2,201자, 마크다운 구조(헤더·표·인용·볼드) 활용
- **기관 연락처** — 10/10 전량 관련 기관 연락처 포함
- **계산기 호출** — 1건 (퇴직금 민사소송) 정상 작동
- **환각 감지** — 1건 자동 감지 + 교정 완료

#### 발견된 문제

| # | 문제 | 영향 범위 | 심각도 |
|:-:|------|:--------:|:------:|
| 1 | **면책 고지 누락** — 10건 중 8건(80%)에서 "법적 효력이 없습니다" 면책 문구 미포함 | 8/10 | High |
| 2 | **응답 시간 과다** — 질문 1번 89.9초 (환각 교정 Gemini 호출로 인한 지연) | 1/10 | Medium |
| 3 | **테스트 자동화 미비** — 테스트 스크립트가 일회성, 198건 전량 테스트 불가 | 인프라 | Low |

### 1.2 문제 원인 분석

#### 면책 고지 누락 (8건)

시스템 프롬프트(`SYSTEM_PROMPT_TEMPLATE`)의 14번 규칙에 면책 고지를 명시했으나, LLM이 긴 답변 생성 시 면책 문구를 누락하는 경향이 있음.

- 면책 포함 2건: 질문 1(임금체불), 질문 3(직장 괴롭힘) — 둘 다 법적 분쟁 성격이 강한 질문
- 면책 누락 8건: 상담·안내 성격 질문에서 LLM이 면책을 생략

**근본 원인**: 시스템 프롬프트의 면책 규칙이 14번째(마지막)에 위치하여 LLM이 우선순위를 낮게 판단.

#### 응답 시간 과다 (1건)

질문 1(임금체불, 89.9초)의 시간 분해:
- 의도 분석: ~3초
- RAG 검색 + Rerank + Self-RAG: ~15초
- LLM 스트리밍: ~30초
- **환각 판례 교정 (Gemini 호출): ~40초** ← 병목

**근본 원인**: `correct_hallucinated_citations()`이 Gemini 2.5 Pro를 호출하며, 이 모델의 응답 시간이 30~40초.

---

## 2. Scope

### 2.1 In Scope

- [x] FR-01: 시스템 프롬프트 면책 고지 강화 — 규칙 위치 조정 + 강제 포함 지시
- [x] FR-02: 환각 교정 모델 최적화 — Gemini→Haiku 전환으로 교정 시간 단축
- [x] FR-03: 테스트 자동화 스크립트 — `test_naver_kin.py` 신규 생성

### 2.2 Out of Scope

- RAG 검색 품질 개선 (별도 feature)
- LLM 스트리밍 속도 자체 개선 (모델 의존)
- 198건 전량 테스트 실행 (스크립트 준비만, 실행은 별도)

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | **면책 고지 강제**: 시스템 프롬프트에서 면책 규칙을 1~2번 위치로 이동하고, "모든 답변의 마지막에 반드시 포함하세요"로 강화. 면책 문구 미포함 비율 80% → 10% 이하 목표 | High | Pending |
| FR-02 | **환각 교정 모델 최적화**: `citation_validator.py`의 `correct_hallucinated_citations()`에서 Gemini 대신 Claude Haiku를 1순위로 시도. 교정 시간 40초 → 5초 이내 목표 | Medium | Pending |
| FR-03 | **테스트 자동화 스크립트**: `test_naver_kin.py` — JSON 입력 → 파이프라인 실행 → 마크다운 보고서 자동 생성. 면책 포함률·응답 시간·계산기 호출 등 품질 지표 자동 검증 | Low | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement |
|----------|----------|-------------|
| Performance | 평균 응답 시간 59초 → 50초 이하 | 10건 테스트 재실행 |
| Quality | 면책 고지 포함률 20% → 90% 이상 | 자동화 스크립트 검증 |
| Reliability | 기존 102건 배치 테스트 + 10건 지식iN 테스트 전량 통과 | CI 테스트 |

---

## 4. Success Criteria

- [ ] 면책 고지 포함률 90% 이상 (10건 재테스트)
- [ ] 환각 교정 시 응답 시간 < 60초 (89.9초 → 60초 이하)
- [ ] `test_naver_kin.py` 실행 시 자동 보고서 생성
- [ ] 기존 기능 회귀 없음

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| FR-01: 면책 강조가 답변 자연스러움 저해 | Medium | Low | "자연스럽게 포함" 지시 + 위치만 답변 말미로 고정 |
| FR-02: Haiku 교정 품질이 Gemini보다 낮음 | Medium | Medium | Haiku 실패 시 Gemini 폴백 유지 |

---

## 6. Architecture Considerations

### 6.1 변경 대상

```
app/core/
├── pipeline.py              ← FR-01: SYSTEM_PROMPT_TEMPLATE 면책 규칙 위치 조정
├── citation_validator.py    ← FR-02: correct_hallucinated_citations() 모델 순서 변경
test_naver_kin.py            ← FR-03: 신규 테스트 자동화 스크립트
```

### 6.2 FR-01 면책 고지 강화 방향

현재 `SYSTEM_PROMPT_TEMPLATE`의 14번 규칙:
```
14. **면책 고지** (반드시 포함):
   "본 답변은 참고용 정보 제공이며 법적 효력이 없습니다.
   구체적인 사안은 관할 고용노동부(☎ 1350) 또는 공인노무사에게 상담하시기 바랍니다."
```

**변경 방향**:
1. 면책 규칙을 1번 규칙 바로 뒤(2번)로 이동
2. "**모든 답변의 마지막 문단에 반드시** 아래 면책 문구를 포함하세요" 강조
3. 면책 문구를 `---` 구분선 아래 별도 블록으로 분리하도록 지시

### 6.3 FR-02 교정 모델 최적화 방향

현재 순서: Gemini(1순위) → OpenAI(2순위)
**변경**: Haiku(1순위) → Gemini(2순위) → OpenAI(3순위)

Haiku는 이미 `micro_polish()`에서 사용 중이므로 인프라 추가 없음. 교정 프롬프트도 동일하게 적용.

---

## 7. Implementation Order

| Phase | Task | 변경량 |
|-------|------|--------|
| 1 | FR-01: 시스템 프롬프트 면책 강화 | `pipeline.py` ~10줄 수정 |
| 2 | FR-02: 환각 교정 모델 순서 변경 | `citation_validator.py` ~20줄 수정 |
| 3 | FR-03: 테스트 자동화 스크립트 | `test_naver_kin.py` 신규 ~150줄 |
| 4 | 10건 재테스트 + 결과 비교 | 실행만 |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-20 | Initial draft — 테스트 10건 분석 기반 3 FRs | Claude |
