# benchmark-quality-improvement Planning Document

> **Summary**: 벤치마크 파이프라인 저점수 케이스(32/104건, 3.0점 이하) 원인 분석 및 검색·계산기·법령모듈 체계적 보완
>
> **Project**: laborconsult (nodong.kr 노동법 RAG 챗봇)
> **Author**: Claude
> **Date**: 2026-03-13
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 벤치마크 104건 중 32건(30.8%)이 3.0점 이하. 저점수 케이스의 100%가 검색 결과 0건이며, 계산기 오류·Judge 파싱 버그·법률 해석 부정확이 복합적으로 작용 |
| **Solution** | 5개 영역 개선: (1) 검색 네임스페이스 라우팅 보완, (2) consultation 토픽별 default_laws 확충, (3) 계산기 특수 케이스 로직 추가, (4) LLM 프롬프트 할루시네이션 방지 강화, (5) Judge 파싱 오류 수정 |
| **Function/UX Effect** | 전체 평균 점수 3.88→4.3+ 상승, 3.0 이하 케이스 32건→10건 미만으로 감소. 사용자가 특수 노동법 질문에도 정확한 답변 수신 |
| **Core Value** | 노동법 상담 신뢰도 향상 — 행정해석·판례 기반 정확한 법률 조언으로 실질적 권리 보호 |

---

## 1. Overview

### 1.1 Purpose

벤치마크 파이프라인(benchmark_pipeline.py) 평가 결과에서 점수가 낮은 질문들을 분석하여, RAG 검색·계산기·법령검색 모듈의 구체적 개선점을 도출하고 체계적으로 보완한다.

### 1.2 Background

2026-03-13 벤치마크 실행 결과:
- **전체**: 104건, 평균 3.88점 (5점 만점)
- **점수 분포**: 5.x(11건), 4.x(54건), 3.x(12건), 2.x(18건), 1.x(2건), 0.x(1건), -1.x(6건)
- **3.0 이하**: 32건 (30.8%) — 개선 대상
- **핵심 발견**: 저점수 25건 전부 `search_hits: 0` (검색 실패 100%)

### 1.3 Related Documents

- 벤치마크 결과: `benchmark_pipeline_results.json`
- 벤치마크 스크립트: `benchmark_pipeline.py`
- 파이프라인: `app/core/pipeline.py`
- 검색: `app/core/rag.py`, `app/core/legal_consultation.py`
- 법령 API: `app/core/legal_api.py`
- 프롬프트: `app/templates/prompts.py`

---

## 2. 저점수 케이스 상세 분석

### 2.1 원인별 분류

| 원인 카테고리 | 건수 | 점수 범위 | 핵심 문제 |
|--------------|------|----------|----------|
| **A. Judge 파싱 오류** | 6건 | -1.0 | JSON 응답 파싱 실패 ("Unterminated string") |
| **B. 파이프라인 코드 버그** | 1건 | 0.0 | `_guess_start_date` import 에러 |
| **C. RAG 검색 실패** | 25건 | 1.2~3.0 | search_hits=0, 관련 문서 미검색 |
| **D. 계산기 로직 오류** | 4건 | 1.2~2.6 | calculation_accuracy ≤ 2 |
| **E. LLM 법률 해석 부정확** | ~20건 | 2.0~3.0 | 행정해석/판례 누락 또는 오인용 |

### 2.2 토픽별 저점수 분포 (≤3.0, 파싱오류 제외)

| 토픽 | 건수 | 주요 실패 패턴 |
|------|------|---------------|
| 임금 / 인사명령 / 4대보험 | 9건 | 특수직종(택시), 코로나 휴업, 간이대지급금, 투잡 보험, 평균임금 산정 |
| 근로시간 / 휴일 / 휴가 | 7건 | 초단시간 근로자, 주4일, 연장근로 가산율 중복, 보상휴가, 15시간 기준 |
| 실업급여 / 퇴사 / 해고 | 4건 | 65세 이상 고용보험, 실업급여 평균임금(고보법 제45조), 강요 권고사직 |
| 괴롭힘 / 성희롱 | 2건 | 원청 괴롭힘 적용범위, 성희롱 관련법 혼동 |
| 플랫폼 노동자 산재 | 2건 | 단독사고 산재, 불승인 재심의 |
| 모성보호 | 1건 | 육아기 단축근무 연차 환산 |

### 2.3 저점수 케이스 상세 목록

#### A. Judge 파싱 오류 (-1.0점, 6건)

| Case | 파일명 | 토픽 |
|------|--------|------|
| 6 | 정년퇴직_후_촉탁직_2년_근무시_정규직_전환여부 | 근로계약 |
| 27 | 공휴일_휴무일_지정 | 근로시간/휴일 |
| 52 | 고정_연장근로수당_통상임금_포함_여부 | 임금 |
| 57 | 사례_57 (퇴사처리 거부) | 임금 |
| 81 | 업무_중_코로나19_감염에_의한_사망 | 산재 |
| 104 | 원청_직원에_의한_괴롭힘 | 괴롭힘 |

> **원인**: Judge LLM 응답에서 JSON 파싱 실패. 챗봇 답변 자체는 정상 생성됨.
> **해결**: benchmark_pipeline.py의 judge 응답 파싱 로직 강화

#### B. 파이프라인 코드 버그 (0점, 1건)

| Case | 파일명 | 에러 |
|------|--------|------|
| 49 | 대학_졸업예정자_최저임금_삭감 | `cannot import name '_guess_start_date' from 'wage_calculator.facade'` |

> **원인**: facade 패키지 리팩토링 후 `_guess_start_date` 미이전
> **해결**: facade/__init__.py에서 해당 함수 export 확인/수정

#### C. 계산기 사용 + 저점수 (4건)

| Case | 점수 | calc_acc | 핵심 오류 |
|------|------|---------|----------|
| 86 | 1.20 | 0 | 실업급여 평균임금 산정 — 고보법 제45조 단서 누락 (3개월 내 2회 이상 취득 시 특별 산정) |
| 51 | 2.00 | 2 | 평균임금 산정 시 휴직기간 제외 로직 미구현 (근기법 시행령 제2조 제1항 제8호) |
| 16 | 2.60 | 2 | 토요일 특근 — 무급휴일 vs 유급휴일 구분 미반영, 가산율 중복 적용 오류 |
| 36 | 2.40 | 2 | 주4일 근무 비례연차 — 소정근로시간 비례 연차 계산 누락 |

#### D. RAG 검색 실패 + 법률 해석 부정확 (나머지 ~20건)

**공통 패턴**: search_hits=0 → LLM이 학습 데이터만으로 답변 → 행정해석/판례 누락 → 부정확한 법률 조언

**대표 실패 사례**:

| Case | 점수 | 핵심 누락 내용 |
|------|------|---------------|
| 82 | 1.50 | 65세 이상 고용보험 경과조치 (2019.1.15 시행 부칙 제5조) |
| 69 | 2.00 | 간이대지급금 요건 (통상임금 110% 미만, 재직 중 1회 등) |
| 67 | 2.50 | 코로나 확진자 발생 휴업 = 사용자 귀책 아님 (고용부 지침) |
| 48 | 2.50 | 택시기사 최저임금 특례 (최임법 제6조 제5항, 시행령 제5조의3) |
| 23 | 2.80 | 15시간 미만 반복 시 4주 평균 계산 (근기법 시행령) |
| 74 | 2.80 | 투잡 4대보험 이중취득 규정 (고용보험 이중 불가) |
| 43 | 2.75 | 육아기 단축근무 연차 시간단위 환산 (15일×4h=60h→7.5일) |
| 59 | 2.75 | 부제소 특약 — 퇴직 시점 vs 사전 포기 구분 (대법원 2006) |

---

## 3. Scope

### 3.1 In Scope

- [x] **S1**: Judge 파싱 오류 수정 (benchmark_pipeline.py)
- [x] **S2**: `_guess_start_date` import 에러 수정
- [x] **S3**: RAG 검색 네임스페이스 라우팅 개선 (rag.py, legal_consultation.py)
- [x] **S4**: consultation 토픽별 default_laws 확충
- [x] **S5**: 계산기 특수 케이스 4건 로직 보완
- [x] **S6**: LLM 프롬프트 할루시네이션 방지 강화 (prompts.py)
- [x] **S7**: 벤치마크 재실행 및 점수 비교

### 3.2 Out of Scope

- Pinecone 인덱스 재구축 (데이터 추가 크롤링은 별도 작업)
- 새로운 계산기 모듈 추가 (기존 19개 로직 보완만)
- UI/프론트엔드 변경
- 모델 변경 (Claude Sonnet 4.6 유지)

---

## 4. Requirements

### 4.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | Judge JSON 파싱 실패 시 재시도 또는 fallback 로직 | High | Pending |
| FR-02 | facade 패키지 export 정상화 (`_guess_start_date`) | High | Pending |
| FR-03 | consultation_topic → namespace 매핑 보완 (11개 토픽 전부 검증) | High | Pending |
| FR-04 | consultation 토픽별 default_laws 확충 (코로나, 특수직종, 고보법 등) | High | Pending |
| FR-05 | 실업급여 평균임금 산정 로직 추가 (고보법 제45조 단서) | High | Pending |
| FR-06 | 평균임금 산정 시 휴직기간 제외 로직 (근기법 시행령 제2조) | Medium | Pending |
| FR-07 | 휴일근로 가산율 중복 적용 정확도 개선 | Medium | Pending |
| FR-08 | 비례연차 계산 (단시간 근로자, 주4일 등) 정확도 개선 | Medium | Pending |
| FR-09 | analyzer 프롬프트에 특수 케이스 인식 키워드 추가 | Medium | Pending |
| FR-10 | LLM 시스템 프롬프트에 할루시네이션 방지 규칙 강화 | Medium | Pending |
| FR-11 | 검색 threshold 및 top_k 파라미터 최적화 | Medium | Pending |
| FR-12 | 벤치마크 재실행으로 개선 효과 측정 (목표: 평균 4.0+, ≤3.0 건수 50% 감소) | High | Pending |

### 4.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| Performance | 파이프라인 응답 시간 평균 40초 이내 유지 | benchmark_pipeline.py timing |
| Accuracy | 전체 평균 점수 4.0+ (현재 3.88) | LLM-as-Judge 평가 |
| Reliability | -1점(파싱 오류) 0건 | benchmark 결과 JSON |
| Coverage | 3.0 이하 케이스 16건 미만 (현재 32건의 50%) | benchmark 결과 분석 |

---

## 5. 개선 상세 설계

### 5.1 Judge 파싱 오류 수정 (FR-01)

**현상**: Judge LLM 응답에서 `Unterminated string starting at: line 7 column 16` 에러
**원인 추정**: Judge 응답이 JSON 형식을 벗어남 (줄바꿈, 따옴표 이스케이프 미처리)
**해결 방안**:
1. Judge 응답 파싱 시 `json.loads()` 실패하면 regex fallback으로 점수 추출
2. Judge 프롬프트에 `"reasoning"` 필드 값을 한 줄로 제한하는 지시 추가
3. 파싱 실패 시 1회 재시도 (temperature 약간 변경)

### 5.2 Import 에러 수정 (FR-02)

**현상**: `cannot import name '_guess_start_date' from 'wage_calculator.facade'`
**원인**: facade 패키지 리팩토링(facade.py → facade/) 시 `_guess_start_date` 미이전
**해결**: `facade/__init__.py`에서 해당 함수 존재 여부 확인 → 없으면 추가

### 5.3 RAG 검색 개선 (FR-03, FR-04, FR-11)

**현 상태 분석**:
```python
# legal_consultation.py — 토픽별 설정
TOPIC_CONFIG = {
    "해고·징계": {
        "namespaces": ["precedent", "interpretation", ""],
        "default_laws": ["근기법 제23조", "근기법 제26조", "근기법 제27조"]
    },
    ...
}
```

**개선 포인트**:

#### 5.3.1 네임스페이스 라우팅 보완
- 현재 `""` (빈 문자열) 네임스페이스가 `qa`를 의미하는지 확인 필요
- 모든 consultation 토픽에 `qa` 네임스페이스 명시적 포함
- `regulation` 네임스페이스 활용도 확인 (훈령/예규 검색)

#### 5.3.2 토픽별 default_laws 확충

| 토픽 | 현재 default_laws | 추가 필요 법령 |
|------|------------------|---------------|
| 임금·통상임금 | (확인 필요) | 근기법 시행령 제2조 (평균임금 제외기간), 최임법 제6조 제5항 (택시 특례) |
| 고용보험 | (확인 필요) | 고보법 제45조 (구직급여 산정), 고보법 제10조 제2항 (65세 이상), 고보법 부칙 제5조 |
| 근로시간·휴일 | (확인 필요) | 근기법 시행령 제30조 (주휴 개근요건), 근기법 제18조 (단시간), 근기법 제57조 (보상휴가) |
| 퇴직·퇴직금 | (확인 필요) | 근퇴법 제8조 (퇴직금), 임체법 제7조 (간이대지급금) |
| 괴롭힘 | (확인 필요) | 근기법 제76조의2~3, 남녀고용평등법 제14조의2 (고객 성희롱) |
| 산재보상 | (확인 필요) | 산재법 제125조 (특수형태), 산재법 제37조 (업무상 재해) |
| 모성보호 | (확인 필요) | 남녀고용평등법 제19조의2 (육아기 단축), 근기법 제60조 제3항 (비례연차) |

#### 5.3.3 검색 파라미터 조정
- `threshold`: 0.4 → 0.35 (더 관대한 매칭, 검색 결과 0건 방지)
- `top_k_per_ns`: 3 → 5 (더 많은 후보 확보)
- 쿼리 리라이팅: intent analysis의 `question_summary`와 원문을 결합한 확장 쿼리

### 5.4 계산기 로직 보완 (FR-05~FR-08)

#### FR-05: 실업급여 평균임금 산정 (고보법 제45조 단서)
```
[현재] 단순 평균임금 산정 (3개월 임금 / 일수)
[보완] "최종이직일 이전 3개월 내 피보험자격 취득 2회 이상" 시
       → 마지막 취득일부터 이직일까지의 임금으로 산정
[영향] unemployment.py, models.py (필드 추가: prior_employment_periods)
```

#### FR-06: 평균임금 휴직기간 제외 (근기법 시행령 제2조 제1항 제8호)
```
[현재] 3개월 전체 기간으로 산정
[보완] 휴직/휴업 기간이 포함된 경우 해당 기간과 임금을 제외 후 재산정
[영향] average_wage.py 또는 ordinary_wage.py (leave_periods 파라미터)
```

#### FR-07: 휴일근로 가산율 중복 적용
```
[현재] 각 가산율 단순 합산
[보완] 근기법 제56조 기준 — 휴일연장(2.0배), 휴일야간연장(2.5배) 정확 산정
[영향] overtime.py (holiday_overtime/night 분리 계산)
```

#### FR-08: 비례연차 계산
```
[현재] 주5일 기준 연차만 산정
[보완] 단시간 근로자 비례연차 (근기법 제60조 제3항)
       통상근로자 소정근로시간 대비 비례 적용
[영향] annual_leave.py (proportional_leave 로직)
```

### 5.5 프롬프트 개선 (FR-09, FR-10)

#### FR-09: Analyzer 프롬프트 특수 케이스 인식

추가할 키워드 매핑:
```
"택시" → consultation_topic: "임금·통상임금", relevant_laws += ["최임법 제6조 제5항"]
"플랫폼", "배달" → consultation_topic: "산재보상", relevant_laws += ["산재법 제125조"]
"65세", "고령" → relevant_laws += ["고보법 제10조 제2항"]
"코로나", "격리", "휴업" → relevant_laws += ["근기법 제46조"]
"부제소", "합의" → relevant_laws += ["근기법 제36조"]
"대지급금" → relevant_laws += ["임체법 제7조"]
"초단시간" → relevant_laws += ["근기법 제18조"]
```

#### FR-10: 시스템 프롬프트 할루시네이션 방지 강화

추가 규칙:
```
1. 판례번호를 인용할 때 검색 결과에 없는 판례는 "관련 판례가 있을 수 있으나 확인 필요"로 표기
2. 행정해석 번호를 인용할 때 검색 결과에 없는 해석은 번호 없이 내용만 서술
3. 코로나 관련 질문은 고용부 지침 변경 가능성 명시
4. 65세 이상 고용보험은 경과조치(부칙) 반드시 확인 안내
5. 특수직종(택시, 플랫폼 등)은 일반 규정과 다를 수 있음 명시
```

---

## 6. Success Criteria

### 6.1 Definition of Done

- [ ] -1점 케이스 0건 (Judge 파싱 오류 해결)
- [ ] 0점 케이스 0건 (import 에러 해결)
- [ ] 전체 평균 점수 4.0 이상 (현재 3.88)
- [ ] 3.0 이하 케이스 16건 미만 (현재 32건의 50% 감소)
- [ ] 계산기 사용 케이스 중 calc_accuracy ≤ 2 케이스 0건

### 6.2 Quality Criteria

- [ ] 기존 고점수(4.0+) 케이스의 점수 하락 없음
- [ ] 파이프라인 평균 응답시간 40초 이내 유지
- [ ] 벤치마크 전체 104건 오류 없이 완료

---

## 7. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| 검색 threshold 낮추면 노이즈 증가 | Medium | Medium | top_k 후 relevance 재정렬로 품질 유지 |
| default_laws 추가로 API 호출 증가 → 응답 지연 | Medium | High | L1/L2 캐시 활용, 병렬 호출 |
| 프롬프트 변경이 기존 고점수 케이스에 역효과 | High | Low | 변경 전후 전체 벤치마크 비교 |
| 계산기 로직 변경이 기존 32개 CLI 테스트에 영향 | High | Medium | 기존 테스트 먼저 통과 확인 후 배포 |
| law.go.kr API 불안정으로 법령 조회 실패 | Medium | Low | 3-layer 캐시 + 에러 시 graceful fallback |

---

## 8. 구현 우선순위 및 단계

### Phase 1: 버그 수정 (즉시, ~30분)
1. **FR-01**: Judge 파싱 오류 수정 (benchmark_pipeline.py)
2. **FR-02**: `_guess_start_date` import 에러 수정 (facade/__init__.py)

### Phase 2: 검색 품질 개선 (핵심, ~2시간)
3. **FR-03**: consultation 토픽 → namespace 매핑 검증/보완 (legal_consultation.py)
4. **FR-04**: 토픽별 default_laws 대폭 확충 (legal_consultation.py)
5. **FR-11**: 검색 threshold/top_k 최적화 (rag.py)
6. **FR-09**: analyzer 프롬프트 특수 키워드 인식 (prompts.py)

### Phase 3: 계산기 보완 (~1.5시간)
7. **FR-05**: 실업급여 평균임금 산정 로직 (unemployment.py)
8. **FR-06**: 평균임금 휴직기간 제외 (average_wage.py 또는 ordinary_wage.py)
9. **FR-07**: 휴일근로 가산율 중복 적용 (overtime.py)
10. **FR-08**: 비례연차 계산 (annual_leave.py)

### Phase 4: 프롬프트 개선 (~30분)
11. **FR-10**: LLM 시스템 프롬프트 할루시네이션 방지 강화 (prompts.py)

### Phase 5: 검증 (~1시간)
12. **FR-12**: 전체 벤치마크 재실행 및 before/after 비교

---

## 9. 영향 받는 파일 목록

| 파일 | 변경 유형 | FR |
|------|----------|-----|
| `benchmark_pipeline.py` | Judge 파싱 로직 강화 | FR-01 |
| `wage_calculator/facade/__init__.py` | export 수정 | FR-02 |
| `app/core/legal_consultation.py` | 토픽 설정 보완 | FR-03, FR-04 |
| `app/core/rag.py` | threshold/top_k 조정 | FR-11 |
| `app/templates/prompts.py` | analyzer + system 프롬프트 | FR-09, FR-10 |
| `wage_calculator/calculators/unemployment.py` | 평균임금 산정 로직 | FR-05 |
| `wage_calculator/calculators/average_wage.py` | 휴직기간 제외 | FR-06 |
| `wage_calculator/calculators/overtime.py` | 가산율 중복 | FR-07 |
| `wage_calculator/calculators/annual_leave.py` | 비례연차 | FR-08 |
| `wage_calculator/models.py` | 새 필드 추가 가능 | FR-05, FR-06 |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-13 | Initial draft — 벤치마크 분석 기반 개선 계획 수립 | Claude |
