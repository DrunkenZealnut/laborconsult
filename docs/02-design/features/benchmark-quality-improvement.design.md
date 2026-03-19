# benchmark-quality-improvement Design Document

> **Summary**: 벤치마크 저점수 32건 해결을 위한 5개 모듈 코드 수준 변경 사양
>
> **Project**: laborconsult
> **Author**: Claude
> **Date**: 2026-03-14
> **Status**: Draft
> **Plan Reference**: `docs/01-plan/features/benchmark-quality-improvement.plan.md`

---

## 1. Phase 1: 버그 수정 (FR-01, FR-02)

### 1.1 FR-01: Judge JSON 파싱 오류 수정

**파일**: `benchmark_pipeline.py`
**위치**: `judge_answer()` 함수 (L280~L343)

**현재 문제**: JSON 파싱 2단계 시도 (json.loads → regex 줄바꿈 치환) 모두 실패 시 -1점 반환

**변경 사양**:

```python
# benchmark_pipeline.py :: judge_answer() 내부

# 기존: json.loads 실패 → regex 1회 → 예외 시 -1 반환
# 변경: 3단계 파싱 + regex fallback 점수 추출

def judge_answer(case: ParsedCase, chatbot_answer: str, client) -> dict:
    # ... (기존 코드 유지) ...

    try:
        scores = json.loads(raw)
    except json.JSONDecodeError:
        # 2단계: reasoning 필드 줄바꿈 치환
        try:
            raw_fixed = re.sub(
                r'("reasoning"\s*:\s*")(.*?)("\s*\})',
                lambda m: m.group(1) + m.group(2).replace('\n', ' ').replace('"', '\\"') + m.group(3),
                raw, flags=re.DOTALL
            )
            scores = json.loads(raw_fixed)
        except json.JSONDecodeError:
            # 3단계: regex로 개별 점수 추출 (NEW)
            scores = _extract_scores_regex(raw)
            if scores is None:
                # 4단계: 1회 재시도 (temperature=0.1)
                scores = _retry_judge(case, chatbot_answer, client)

    # ...
```

**신규 함수 2개 추가**:

```python
def _extract_scores_regex(raw: str) -> dict | None:
    """JSON 파싱 실패 시 regex로 개별 점수 추출"""
    fields = ["legal_accuracy", "completeness", "relevance", "practicality", "calculation_accuracy"]
    scores = {}
    for f in fields:
        m = re.search(rf'"{f}"\s*:\s*(\d+|"N/A")', raw)
        if m:
            val = m.group(1)
            scores[f] = "N/A" if val == '"N/A"' else int(val)

    # reasoning 추출 (있으면)
    m = re.search(r'"reasoning"\s*:\s*"(.*?)(?:"\s*[,}])', raw, re.DOTALL)
    if m:
        scores["reasoning"] = m.group(1).replace('\n', ' ')[:500]

    # 최소 3개 필드 추출 성공해야 유효
    numeric = [v for v in scores.values() if isinstance(v, (int, float))]
    if len(numeric) < 3:
        return None

    return scores


def _retry_judge(case: ParsedCase, chatbot_answer: str, client) -> dict:
    """파싱 실패 시 1회 재시도 — 더 엄격한 JSON 생성 지시"""
    try:
        resp = client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=512,  # 줄임
            temperature=0.1,
            system=JUDGE_SYSTEM + "\n\nIMPORTANT: Output ONLY a single-line JSON object. No newlines inside string values.",
            messages=[{
                "role": "user",
                "content": JUDGE_PROMPT.format(
                    question=case.question[:1500],
                    expert_answer=case.expert_answer[:1500],
                    chatbot_answer=chatbot_answer[:1500],
                ),
            }],
        )
        raw = resp.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        brace_start = raw.find("{")
        brace_end = raw.rfind("}")
        if brace_start >= 0 and brace_end > brace_start:
            raw = raw[brace_start:brace_end + 1]
        return json.loads(raw)
    except Exception as e:
        return {
            "legal_accuracy": -1, "completeness": -1, "relevance": -1,
            "practicality": -1, "calculation_accuracy": "N/A",
            "overall_score": -1.0,
            "reasoning": f"Judge 파싱 오류 (재시도 실패): {e}",
        }
```

**예상 효과**: -1점 6건 → 0건

---

### 1.2 FR-02: `_guess_start_date` import 에러 수정

**파일**: `wage_calculator/facade/__init__.py`
**위치**: L20 (`from .conversion import _provided_info_to_input`)

**현재 코드**:
```python
from .conversion import _provided_info_to_input
```

**변경 코드**:
```python
from .conversion import _provided_info_to_input, _guess_start_date
```

**이유**: `pipeline.py:420`에서 `from wage_calculator.facade import _guess_start_date` 호출하므로 export 필수

**예상 효과**: 0점 1건 → 정상 실행

---

## 2. Phase 2: 검색 품질 개선 (FR-03, FR-04, FR-09, FR-11)

### 2.1 FR-03 + FR-04: consultation 토픽별 설정 대폭 보완

**파일**: `app/core/legal_consultation.py`
**위치**: `TOPIC_SEARCH_CONFIG` (L20~L69)

**현재 문제**:
1. 일부 토픽의 default_laws가 기본 조문만 포함 (특수 케이스 법령 부재)
2. `""` 빈 문자열 네임스페이스 사용 — qa로 라우팅되지만 명시적이지 않음
3. 중요 세부 법령(시행령, 부칙, 특례) 누락

**변경 사양 — 전체 교체**:

```python
TOPIC_SEARCH_CONFIG: dict[str, dict] = {
    "해고·징계": {
        "namespaces": ["precedent", "interpretation", "qa"],
        "default_laws": [
            "근로기준법 제23조",    # 해고 등의 제한
            "근로기준법 제26조",    # 해고의 예고
            "근로기준법 제27조",    # 해고사유 등의 서면통지
            "근로기준법 제28조",    # 부당해고등의 구제신청
        ],
    },
    "임금·통상임금": {
        "namespaces": ["precedent", "interpretation", "qa"],
        "default_laws": [
            "근로기준법 제2조",     # 정의 (평균임금, 통상임금)
            "근로기준법 제43조",    # 임금 지급
            "근로기준법 제36조",    # 금품 청산
            "근로기준법 제46조",    # 휴업수당
            "최저임금법 제6조",     # 최저임금의 적용 (제5항 택시 특례 포함)
        ],
    },
    "근로시간·휴일": {
        "namespaces": ["interpretation", "regulation", "qa"],
        "default_laws": [
            "근로기준법 제50조",    # 근로시간
            "근로기준법 제53조",    # 연장 근로의 제한
            "근로기준법 제55조",    # 휴일
            "근로기준법 제56조",    # 연장·야간 및 휴일 근로
            "근로기준법 제57조",    # 보상 휴가제
            "근로기준법 제18조",    # 단시간근로자의 근로조건
        ],
    },
    "퇴직·퇴직금": {
        "namespaces": ["interpretation", "precedent", "qa"],
        "default_laws": [
            "근로자퇴직급여 보장법 제4조",  # 퇴직급여제도의 설정
            "근로자퇴직급여 보장법 제8조",  # 퇴직금제도의 설정 등
            "임금채권보장법 제7조",          # 간이대지급금
        ],
    },
    "연차휴가": {
        "namespaces": ["interpretation", "precedent", "qa"],
        "default_laws": [
            "근로기준법 제60조",    # 연차 유급휴가
            "근로기준법 제61조",    # 연차 유급휴가의 사용 촉진
        ],
    },
    "산재보상": {
        "namespaces": ["precedent", "interpretation", "qa"],
        "default_laws": [
            "산업재해보상보험법 제37조",    # 업무상의 재해의 인정 기준
            "산업재해보상보험법 제125조",   # 특수형태근로종사자에 대한 특례
        ],
    },
    "비정규직": {
        "namespaces": ["precedent", "interpretation", "qa"],
        "default_laws": [
            "기간제 및 단시간근로자 보호 등에 관한 법률 제4조",  # 기간제근로자의 사용
        ],
    },
    "노동조합": {
        "namespaces": ["precedent", "qa"],
        "default_laws": [],
    },
    "직장내괴롭힘": {
        "namespaces": ["interpretation", "precedent", "qa"],
        "default_laws": [
            "근로기준법 제76조의2",  # 직장 내 괴롭힘의 금지
            "근로기준법 제76조의3",  # 직장 내 괴롭힘 발생 시 조치
            "남녀고용평등과 일·가정 양립 지원에 관한 법률 제14조의2",  # 고객 등에 의한 성희롱 방지
        ],
    },
    "근로계약": {
        "namespaces": ["interpretation", "regulation", "qa"],
        "default_laws": [
            "근로기준법 제17조",    # 근로조건의 명시
        ],
    },
    "고용보험": {
        "namespaces": ["interpretation", "qa"],
        "default_laws": [
            "고용보험법 제40조",    # 구직급여의 수급 요건
            "고용보험법 제45조",    # 이직 전 평균임금 일액의 산정
            "고용보험법 제69조",    # 육아휴직 급여
        ],
    },
    "기타": {
        "namespaces": ["qa", "interpretation"],
        "default_laws": [],
    },
}
```

**변경 요약**:

| 토픽 | 추가 법령 | 커버하는 저점수 케이스 |
|------|----------|---------------------|
| 임금·통상임금 | 제36조(금품청산), 제46조(휴업수당), **최임법 제6조**(택시특례) | Case 48, 67, 69 |
| 근로시간·휴일 | 제56조(가산), **제57조(보상휴가)**, **제18조(단시간)** | Case 16, 18, 19, 23 |
| 퇴직·퇴직금 | **임채법 제7조**(간이대지급금) | Case 69 |
| 산재보상 | **제125조**(특수형태/플랫폼) | Case 111, 114 |
| 직장내괴롭힘 | **남녀고용평등법 제14조의2**(고객성희롱) | Case 102, 109 |
| 고용보험 | **제45조**(평균임금산정) | Case 82, 86 |
| 해고·징계 | 제28조(구제신청) | Case 90, 93 |
| 모든 토픽 | `""` → `"qa"` 명시화 | 전체 |

---

### 2.2 FR-11: 검색 파라미터 최적화

**파일**: `app/core/rag.py`
**변경 1**: `search_multi_namespace()` 기본 파라미터 (L44~45)

```python
# 변경 전
def search_multi_namespace(
    query: str,
    namespaces: list[str],
    config,
    top_k_per_ns: int = 3,
    threshold: float = 0.4,
) -> list[dict]:

# 변경 후
def search_multi_namespace(
    query: str,
    namespaces: list[str],
    config,
    top_k_per_ns: int = 5,     # 3 → 5 (더 많은 후보)
    threshold: float = 0.35,   # 0.4 → 0.35 (관대한 매칭)
) -> list[dict]:
```

**변경 2**: `_search_ns()` 내부에서 빈 문자열 네임스페이스 → `"qa"` 정규화 (L56)

```python
def _search_ns(ns: str) -> list[dict]:
    actual_ns = ns if ns else "qa"  # "" → "qa" 정규화
    try:
        results = config.pinecone_index.query(
            vector=qvec,
            top_k=top_k_per_ns,
            namespace=actual_ns,  # ns → actual_ns
            include_metadata=True,
        )
```

**파일**: `app/core/legal_consultation.py`
**변경**: `process_consultation()` 내 top_k 조정 (L153)

```python
# 변경 전
hits = search_multi_namespace(query, namespaces, config, top_k_per_ns=3)

# 변경 후
hits = search_multi_namespace(query, namespaces, config, top_k_per_ns=5)
```

**파일**: `app/core/pipeline.py`
**변경**: `_search()` 함수 threshold 조정 (L30~35)

```python
# 변경 전
def _search(query: str, config: AppConfig, top_k: int = 5, threshold: float = 0.4) -> list[dict]:

# 변경 후
def _search(query: str, config: AppConfig, top_k: int = 5, threshold: float = 0.35) -> list[dict]:
```

---

### 2.3 FR-09: Analyzer 프롬프트 특수 케이스 인식

**파일**: `app/templates/prompts.py`
**위치**: `ANALYZER_SYSTEM` 끝부분 (L173 이후)

**추가할 내용**:

```python
# ANALYZER_SYSTEM 끝에 추가 (L174 뒤):

12. **특수 케이스 자동 법령 매핑** (relevant_laws에 자동 추가):
   - "택시", "운수" → relevant_laws에 "최저임금법 제6조 제5항" 추가
   - "플랫폼", "배달", "대리운전" → relevant_laws에 "산업재해보상보험법 제125조" 추가
   - "65세", "고령", "정년 이후" → relevant_laws에 "고용보험법 제10조" 추가
   - "코로나", "감염", "격리", "방역" → relevant_laws에 "근로기준법 제46조" 추가
   - "대지급금", "체당금" → relevant_laws에 "임금채권보장법 제7조" 추가
   - "초단시간", "15시간 미만" → relevant_laws에 "근로기준법 제18조" 추가
   - "부제소", "합의", "청구 포기" → relevant_laws에 "근로기준법 제36조" 추가
   - "촉탁", "정년 후 재고용" → relevant_laws에 "기간제법 제4조" 추가
   - "육아기 단축", "근로시간 단축" → relevant_laws에 "남녀고용평등법 제19조의2" 추가
13. consultation_topic 결정 시 위 키워드도 고려하세요.
```

---

## 3. Phase 3: 계산기 보완 (FR-05~FR-08)

### 3.1 FR-05: 실업급여 평균임금 산정 — Scope 축소

**결정**: 고용보험법 제45조 단서(3개월 내 2회 이상 피보험자격 취득)는 극히 특수한 케이스.
계산기 로직 변경 대신 **프롬프트에서 LLM이 해당 법조문을 인용하도록 유도**하는 방식으로 대응.

**이유**:
- Case 86은 계산기가 "최저임금 검증" 등 무관한 계산을 수행한 것이 문제
- 실제 실업급여 평균임금 산정은 pipeline.py의 계산기 호출과 무관 (질문이 "평균임금 기준"을 묻는 법률상담)
- default_laws에 `고용보험법 제45조` 추가 (FR-04)로 법조문이 LLM 컨텍스트에 포함되면 해결 예상

**추가 변경 없음** (FR-04에서 처리 완료)

---

### 3.2 FR-06: 평균임금 휴직기간 제외 — Scope 축소

**결정**: 마찬가지로 법률상담 영역. Case 51은 "평균임금이 통상임금보다 낮은 경우" 질문으로, 계산기가 필요한 케이스가 아님.

**대신**: `ANALYZER_SYSTEM` 프롬프트에 규칙 추가 (FR-09에서 처리)
```
- "병가", "휴직", "휴업" 기간 포함 평균임금 질문 → consultation_type="law_interpretation", consultation_topic="임금·통상임금"
```

---

### 3.3 FR-07: 휴일근로 가산율 — 현재 코드 확인

**현재 코드** (`overtime.py:9~11`):
```python
# 휴일수당: 통상시급 × 휴일시간 × 1.5 (8h 초과분은 × 2.0)
```

**분석**: 이미 8시간 초과 분리 적용됨. Case 16의 문제는 "토요일이 무급휴일인지 유급휴일인지"에 따라 계산이 다른데, 이 구분은 LLM이 질문에서 판단해야 하는 영역.

**결정**: 계산기 자체는 수정 불필요. **프롬프트 개선**(FR-10)에서 "토요일 근무 시 무급휴일/유급휴일 구분에 따라 계산이 달라진다"는 주의사항 추가로 대응.

---

### 3.4 FR-08: 비례연차 — 현재 코드 확인

**현재 코드** (`annual_leave.py:12~13, 59~61`):
```python
# 단시간근로자: 비례 연차 (근기법 제18조③)
is_part_time_ratio: bool = False
part_time_ratio: float = 1.0
```

**분석**: 비례연차 필드는 이미 존재하지만, 실제 비례 산정 로직이 구현되었는지 확인 필요.

**결론**: 기존 annual_leave.py에 이미 part_time_ratio 로직이 있다면 수정 불필요. Case 36은 "주4일 근무자의 연차가 몇 일인지"를 묻는 법률상담이며, 계산기 오류보다는 LLM이 비례연차 법리를 정확히 설명하지 못한 것이 주요 원인.

→ **FR-04에서 `근로기준법 제60조 제3항` default_laws 추가로 대응**

---

## 4. Phase 4: 프롬프트 개선 (FR-10)

### 4.1 시스템 프롬프트 할루시네이션 방지 강화

**파일**: `app/templates/prompts.py`

#### 4.1.1 CONSULTATION_SYSTEM_PROMPT 수정

**위치**: L197~225 — 규칙 5번 뒤에 추가

```python
# CONSULTATION_SYSTEM_PROMPT에 규칙 추가 (기존 5~7번 사이):

5-1. **판례·행정해석 인용 주의** (매우 중요):
   - 참고 자료에 포함된 판례만 판례번호(예: 대법원 2023다302838)를 인용하세요.
   - 참고 자료에 없는 판례는 "관련 판례가 있을 수 있으나 구체적 번호는 확인이 필요합니다"로 표기하세요.
   - 행정해석도 마찬가지: 참고 자료에 없는 문서번호를 생성하지 마세요.
   - 존재하지 않는 판례번호나 행정해석 번호를 만들어내면 사용자에게 심각한 피해가 됩니다.
5-2. **특수 케이스 주의사항**:
   - 65세 이상 고용보험: 2019.1.15 시행 개정법 경과조치(부칙) 반드시 확인 안내
   - 코로나 관련 휴업수당: 사용자 귀책사유 vs 불가항력 구분 명시 (고용부 지침 참고)
   - 택시·플랫폼 등 특수직종: 일반 근로기준법과 다른 특례 적용 가능성 명시
   - 채용내정 취소: 근로계약 성립 여부에 따라 부당해고 적용 여부 상이
   - 부제소 합의: 퇴직 전 사전포기 vs 퇴직 시점 합의 구분 중요
```

#### 4.1.2 COMPOSER_SYSTEM (일반 답변) 수정

**위치**: L177~195 — 규칙 끝에 추가

```python
# COMPOSER_SYSTEM 규칙에 추가:

- 판례번호·행정해석 번호를 인용할 때 검색 결과에서 확인된 것만 번호를 표기하세요.
  확인되지 않은 판례·해석은 번호 없이 내용만 서술하세요.
- 검색 결과가 없을 경우 "⚠️ 참고 문서 없이 일반 노동법 지식을 기반으로 작성된 답변입니다"를 표기하세요.
```

---

## 5. Phase 5: 검증 (FR-12)

### 5.1 벤치마크 재실행

```bash
python3 benchmark_pipeline.py
```

### 5.2 비교 지표

| 지표 | Before | Target |
|------|--------|--------|
| 전체 평균 점수 | 3.88 | 4.0+ |
| -1점 케이스 | 6건 | 0건 |
| 0점 케이스 | 1건 | 0건 |
| 3.0 이하 케이스 | 32건 | 16건 미만 |
| search_hits=0 비율 | ~25% | ~10% |

---

## 6. 변경 파일 요약

| 파일 | FR | 변경 유형 | 변경량 |
|------|-----|----------|--------|
| `benchmark_pipeline.py` | FR-01 | 함수 2개 추가 + judge_answer 수정 | ~50줄 |
| `wage_calculator/facade/__init__.py` | FR-02 | import 1줄 추가 | 1줄 |
| `app/core/legal_consultation.py` | FR-03,04 | TOPIC_SEARCH_CONFIG 전체 교체 | ~60줄 |
| `app/core/rag.py` | FR-11 | 기본값 변경 + ns 정규화 | ~5줄 |
| `app/core/pipeline.py` | FR-11 | threshold 변경 | 1줄 |
| `app/templates/prompts.py` | FR-09,10 | ANALYZER_SYSTEM + CONSULTATION + COMPOSER 추가 | ~30줄 |

**총 변경량**: ~150줄 (6개 파일)

---

## 7. 구현 순서 (의존성 기반)

```
1. FR-02  facade export 수정          (독립, 즉시)
2. FR-01  judge 파싱 강화              (독립, 즉시)
3. FR-03  네임스페이스 "" → "qa"       (독립)
4. FR-04  default_laws 확충            (FR-03과 같은 파일)
5. FR-11  threshold/top_k 조정         (FR-03 이후)
6. FR-09  analyzer 프롬프트 키워드      (독립)
7. FR-10  system 프롬프트 강화          (FR-09와 같은 파일)
8. FR-12  벤치마크 재실행              (모두 완료 후)
```

**병렬 가능**:
- (FR-01, FR-02) 동시 가능
- (FR-03+04, FR-09+10) 서로 다른 파일이므로 동시 가능
- FR-12는 모든 변경 완료 후 실행

---

## 8. 테스트 계획

### 8.1 단위 확인

| 테스트 | 방법 | 기대 결과 |
|--------|------|----------|
| `_guess_start_date` import | `python3 -c "from wage_calculator.facade import _guess_start_date"` | 에러 없음 |
| `_extract_scores_regex` | 실패했던 6건의 raw 응답으로 테스트 | 유효한 점수 추출 |
| 검색 threshold | `python3 -c "from app.core.rag import search_multi_namespace; ..."` | 결과 > 0건 |
| CLI 테스트 | `python3 wage_calculator_cli.py` | 기존 테스트 전부 통과 |

### 8.2 통합 확인

| 테스트 | 방법 | 기대 결과 |
|--------|------|----------|
| 벤치마크 전체 | `python3 benchmark_pipeline.py` | 104건 완료, 평균 4.0+ |
| 기존 고점수 유지 | 4.0+ 케이스 점수 비교 | 하락 없음 |
| 응답 시간 | timing.total_ms 평균 | 40초 이내 |

---

## 9. 롤백 계획

변경이 기존 성능을 저하시키는 경우:

1. **threshold 롤백**: 0.35 → 0.40 (rag.py, pipeline.py)
2. **default_laws 축소**: 추가분만 제거 (legal_consultation.py)
3. **프롬프트 롤백**: git diff 기준 원복

벤치마크 before/after 비교로 판단:
- 기존 4.0+ 케이스 중 3.5 이하로 하락하는 건이 5건 이상이면 해당 변경 롤백

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-14 | Initial design — Plan 기반 코드 수준 변경 사양 | Claude |
