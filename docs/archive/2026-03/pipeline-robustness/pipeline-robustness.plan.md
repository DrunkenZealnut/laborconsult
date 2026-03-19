# Pipeline Robustness (파이프라인 견고성 강화) Planning Document

> **Summary**: 질문 처리 파이프라인의 엣지 케이스 방어 및 사용자 경험 향상을 위한 4가지 핵심 개선
>
> **Project**: laborconsult
> **Author**: Claude
> **Date**: 2026-03-19
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 병렬 검색 결과 간 정보 충돌 미처리, 특수 근로자 그룹(청소년·산재) 미식별, 인용 교정 후 문맥 단절, 시각화 흐름도의 수렴 표현 부재 |
| **Solution** | 4단계 개선: ① 정보 우선순위 규칙 엔진 ② 분석기 특수 그룹 파라미터 추가 ③ 인용 교정 후 마이크로 퇴고 ④ 시각화 수렴 흐름선 |
| **Function/UX Effect** | 법령 개정 시에도 최신 법령 우선 적용, 청소년·산재 등 특수 상황 자동 인지, 인용 교정 후에도 자연스러운 문장, 파이프라인 흐름 직관적 이해 |
| **Core Value** | 노동법 상담 정확도 향상 + 특수 대상자 보호 강화 + 답변 품질 일관성 확보 |

---

## 1. Overview

### 1.1 Purpose

현재 `process_question()` 파이프라인은 9단계의 정교한 처리 흐름을 갖추고 있으나, 다음 엣지 케이스에서 답변 품질이 저하될 수 있다:

1. **정보 충돌**: Pinecone 판례(과거 법령 기준) vs 법제처 API(현행 법령) vs GraphRAG 정보 간 충돌 시 해결 규칙 부재
2. **특수 근로자 미식별**: 청소년(18세 미만), 산재 근로자, 외국인 근로자 등 적용 기준이 상이한 대상의 자동 식별 부재
3. **인용 교정 문맥 단절**: 환각 판례 번호 제거 후 문장 앞뒤가 어색해지는 현상
4. **시각화 표현 한계**: 병렬 검색→수렴 흐름이 시각적으로 명확하지 않음

### 1.2 Background

- 파이프라인은 이미 Graceful Degradation 원칙을 적용하고 있어 개별 컴포넌트 실패에는 강건함
- 그러나 **정보 간 충돌**(모든 컴포넌트가 성공했지만 결과가 상이한 경우)에 대한 방어는 미비
- 노동법은 대상자 특성에 따라 적용 기준이 완전히 달라짐 (청소년: 근기법 제64~70조, 산재: 산재보험법)
- Citation Validator는 현재 정규식 기반 치환만 수행하여, 환각이 심한 경우 문맥이 끊길 수 있음

### 1.3 Related Documents

- 아키텍처: `CLAUDE.md` Pipeline Flow 섹션
- 의도 분석: `app/core/analyzer.py`, `app/templates/prompts.py`
- 인용 검증: `app/core/citation_validator.py`
- 시각화: `Downloads/pipeline-visualization.html`

---

## 2. Scope

### 2.1 In Scope

- [x] FR-01: 정보 충돌 해결 규칙 엔진 (`pipeline.py` 5단계 컨텍스트 조립)
- [x] FR-02: 특수 근로자 그룹 식별 파라미터 (`analyzer.py` + `prompts.py`)
- [x] FR-03: 인용 교정 후 마이크로 퇴고 (`citation_validator.py`)
- [x] FR-04: 시각화 수렴 흐름선 (`pipeline-visualization.html`)

### 2.2 Out of Scope

- LLM 모델 변경 (현재 Claude Sonnet 4.6 유지)
- 새로운 계산기 모듈 추가
- Pinecone 인덱스 구조 변경
- 프론트엔드 채팅 UI 변경

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status | 변경 파일 |
|----|-------------|----------|--------|-----------|
| FR-01 | **정보 충돌 해결 (Conflict Resolution)**: 컨텍스트 조립 시 법령 > 대법원 판례 > 행정해석 > 상담사례 우선순위 적용. 동일 조항에 대해 법제처 최신 법령과 Pinecone 과거 판례가 충돌하면 최신 법령 기준으로 컨텍스트 구성하고, 판례는 "참고" 레이블로 강등 | High | Pending | `pipeline.py` |
| FR-02 | **특수 근로자 그룹 식별**: analyze_intent 도구에 `worker_group` 파라미터 추가 (enum: general, youth, foreign, disabled, industrial_accident). 청소년 감지 시 야간근로 제한·부모 동의서·근로시간 상한(주35시간) 컨텍스트 자동 주입 | High | Pending | `prompts.py`, `analyzer.py`, `pipeline.py` |
| FR-03 | **인용 교정 마이크로 퇴고**: 환각 인용 3건 이상 감지 시, 정규식 치환 후 Claude Haiku로 문맥 자연스러움 보정. 1건~2건은 기존 정규식 치환 유지 (비용 효율) | Medium | Pending | `citation_validator.py`, `pipeline.py` |
| FR-04 | **시각화 수렴 흐름선**: 4단계 병렬 노드들이 5단계로 모이는 수렴(Converge) 흐름을 SVG 연결선과 화살표로 시각화. 3단계 분기와 시각적으로 명확히 구분 | Medium | Pending | `pipeline-visualization.html` |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| Performance | FR-01: 컨텍스트 조립 추가 시간 < 10ms (규칙 엔진은 인메모리 연산) | 로깅 타이머 |
| Performance | FR-03: 마이크로 퇴고 지연 < 2초 (Haiku 호출, 사용자 체감 포함) | SSE replace 이벤트 타이밍 |
| Reliability | FR-02: 특수 그룹 미식별 → general 폴백 (기존 동작 유지) | 단위 테스트 |
| Cost | FR-03: Haiku 호출은 환각 3건 이상 시에만 트리거 → 전체 질문의 5% 미만 예상 | API 사용량 모니터링 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] FR-01: 법령 vs 판례 충돌 시나리오 테스트 3건 통과
- [ ] FR-02: 청소년 근로자 질문 시 자동 식별 + 특수 컨텍스트 주입 확인
- [ ] FR-03: 환각 3건 이상 시나리오에서 교정 전후 문맥 자연스러움 비교 확인
- [ ] FR-04: 시각화 HTML에서 병렬→수렴 흐름 시각적 확인
- [ ] 모든 기존 테스트 통과 (batch test 102건)
- [ ] Graceful Degradation 유지 (각 기능 실패 시 기존 동작 보장)

### 4.2 Quality Criteria

- [ ] 기존 파이프라인 응답 시간 증가 < 100ms (FR-01, FR-02)
- [ ] FR-03 마이크로 퇴고 발동 시 총 지연 < 3초
- [ ] 코드 변경 파일 수 ≤ 5개 (최소 변경 원칙)

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| FR-01: 우선순위 규칙이 오히려 관련 판례를 배제 | High | Low | 규칙은 "충돌 시"에만 적용. 비충돌 정보는 모두 포함 유지 |
| FR-02: LLM이 특수 그룹 파라미터를 잘못 추출 | Medium | Medium | `worker_group` 기본값 = "general" → 미식별 시 기존 동작과 동일 |
| FR-03: Haiku 마이크로 퇴고가 오히려 정보를 변질 | High | Low | 시스템 프롬프트에 "사실 정보 변경 금지, 문맥 연결어만 수정" 제약 명시 |
| FR-03: Haiku 호출 지연으로 사용자 체감 악화 | Medium | Medium | SSE status 이벤트로 "답변 보정 중..." 안내. 2초 타임아웃 설정 |
| FR-04: 복잡한 SVG가 모바일에서 깨짐 | Low | Medium | 768px 미만에서는 간소화된 세로 연결선으로 폴백 |

---

## 6. Architecture Considerations

### 6.1 변경 대상 모듈

```
app/
├── core/
│   ├── pipeline.py          ← FR-01: _resolve_conflicts() 추가
│   │                          FR-02: worker_group 컨텍스트 주입
│   │                          FR-03: 마이크로 퇴고 호출 추가
│   ├── analyzer.py           ← FR-02: worker_group 파라미터 처리
│   ├── citation_validator.py ← FR-03: micro_polish() 함수 추가
│   └── conflict_resolver.py  ← FR-01: 새 모듈 (정보 충돌 해결 규칙)
├── templates/
│   └── prompts.py            ← FR-02: ANALYZE_TOOL에 worker_group 추가
Downloads/
└── pipeline-visualization.html ← FR-04: SVG 수렴 흐름선
```

### 6.2 FR-01 설계 방향: 정보 충돌 해결

```python
# conflict_resolver.py (신규)
SOURCE_PRIORITY = {
    "법제처_법령": 100,      # 현행 법령 (최우선)
    "대법원_판례": 80,       # 대법원 확정 판례
    "하급심_판례": 60,       # 고등·지방법원 판례
    "행정해석": 50,          # 고용노동부 행정해석
    "노동위원회_판정": 40,   # 중앙노동위 판정사례
    "상담사례": 20,          # nodong.kr 상담 Q&A
}

def resolve_conflicts(legal_articles, precedent_hits, nlrc_hits, graph_context):
    """동일 법 조항에 대해 상충 정보가 있으면 우선순위로 해결.

    Returns:
        resolved_context: 우선순위 적용된 컨텍스트 텍스트
        conflict_notes: LLM에 전달할 충돌 참고 메모
    """
```

**핵심 원칙**: 법령 > 대법원 > 행정해석. 충돌 감지 시 낮은 우선순위 정보에 `[참고: 과거 기준]` 레이블 부착.

### 6.3 FR-02 설계 방향: 특수 근로자 식별

```python
# prompts.py ANALYZE_TOOL 추가 필드
"worker_group": {
    "type": "string",
    "enum": ["general", "youth", "foreign", "disabled", "industrial_accident"],
    "description": (
        "근로자 그룹 분류. "
        "youth: 18세 미만 청소년 ('중학생', '고등학생', '미성년자', '15세', '16세', '17세' 등). "
        "foreign: 외국인 근로자 ('E-9 비자', '외국인', '이주노동자' 등). "
        "disabled: 장애인 근로자 ('장애인', '장애 등급' 등). "
        "industrial_accident: 산업재해 관련 ('산재', '업무상 재해', '산업재해' 등). "
        "general: 위 해당 없는 일반 근로자 (기본값)."
    ),
}
```

**청소년 감지 시 자동 주입 컨텍스트**:
- 근기법 제64~70조 (청소년 근로 특칙)
- 주 35시간 상한 (1일 7시간, 1주 35시간)
- 야간근로(22시~06시) 원칙 금지 (노동부 인가 예외)
- 유해위험사업 사용 금지
- 친권자/후견인 동의서 필요

### 6.4 FR-03 설계 방향: 마이크로 퇴고

```python
# citation_validator.py 추가
MICRO_POLISH_THRESHOLD = 3  # 환각 3건 이상 시 발동

def micro_polish(original: str, corrected: str, client) -> str:
    """정규식 교정 후 문맥 자연스러움 보정.

    - 모델: Claude Haiku (빠른 응답)
    - 제약: 사실 정보 변경 금지, 접속사/연결어만 수정
    - 타임아웃: 2초
    - 폴백: 실패 시 정규식 교정 결과 그대로 반환
    """
```

### 6.5 FR-04 설계 방향: 시각화 수렴 흐름

- 4단계 병렬 그리드 하단에 SVG 기반 수렴선 추가
- 각 노드 하단에서 중앙 하단으로 모이는 곡선 연결
- CSS animation으로 데이터 입자(particle)가 수렴점을 향해 흐르는 효과
- 768px 미만에서는 단순 세로 커넥터로 폴백

---

## 7. Implementation Order

| Phase | Task | 의존성 | 예상 변경량 |
|-------|------|--------|------------|
| 1 | FR-02: 특수 근로자 식별 | 없음 | `prompts.py` +10줄, `analyzer.py` +5줄, `pipeline.py` +30줄 |
| 2 | FR-01: 정보 충돌 해결 | 없음 | `conflict_resolver.py` 신규 ~80줄, `pipeline.py` +15줄 |
| 3 | FR-03: 마이크로 퇴고 | 없음 | `citation_validator.py` +40줄, `pipeline.py` +10줄 |
| 4 | FR-04: 시각화 수렴선 | 없음 | `pipeline-visualization.html` CSS/SVG +100줄 |

**총 변경**: 기존 파일 4개 수정 + 신규 파일 1개 (conflict_resolver.py)

---

## 8. Next Steps

1. [ ] Design 문서 작성 (`pipeline-robustness.design.md`)
2. [ ] FR-02 (특수 근로자 식별) 우선 구현 — 가장 독립적이고 효과 명확
3. [ ] FR-01 (정보 충돌 해결) 구현
4. [ ] FR-03 (마이크로 퇴고) 구현 + 비용 모니터링
5. [ ] FR-04 (시각화 수렴선) 구현

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-19 | Initial draft — 4 FRs defined | Claude |
