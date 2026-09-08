# 상담 평가셋·평가 하네스 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 60건의 비식별 상담 평가셋과 재현 가능한 오프라인·라이브 평가 하네스를 추가해 답변 파이프라인의 기준선과 자동 품질 지표를 만든다.

**Architecture:** 평가셋은 운영 코드와 분리된 JSON fixture로 저장한다. 평가기는 기존 `process_question()`을 라이브 모드에서 호출하고 이벤트·분석 결과·답변·출처·시간을 하나의 결과 레코드로 수집하며, 오프라인 모드에서는 fixture와 지표 계산 계약만 검증한다. 첫 단계에서는 사용자 답변 동작을 변경하지 않는다.

**Tech Stack:** Python 3.11, 표준 라이브러리(`json`, `argparse`, `dataclasses`, `statistics`, `time`), 기존 `app.core.pipeline`, `app.config.AppConfig`, 기존 프로젝트의 직접 실행형 테스트.

**Spec:** `docs/superpowers/specs/2026-09-08-consultation-answer-pdca-design.md`

## Global Constraints

- 평가 fixture에는 개인정보가 포함된 실제 상담 원문을 넣지 않고 비식별 합성 질문만 사용한다.
- 첫 단계에서는 `app/core/pipeline.py`의 사용자 답변 생성 동작과 이벤트 계약을 변경하지 않는다.
- `--offline` 실행은 외부 API 키, Pinecone, Supabase, LLM 호출 없이 성공해야 한다.
- `--live` 실행 결과 JSON은 `.gitignore`의 `*_results.json` 규칙에 따라 커밋하지 않는다.
- 기존 `test_wage_golden.py`, `test_pipeline_wiring.py`, `test_offline_units.py`, `test_llm_fallback.py`의 계약을 깨지 않는다.
- 라이브 평가에서 생성된 질문·답변·출처 원문은 저장소에 추가하지 않는다.

---

## Scope Check

승인된 설계에는 평가셋, 법조문 검증, 위험도 라우팅, 피드백 저장, 정기 실행이라는 독립 하위 시스템이 포함되어 있다. 이 계획은 첫 번째로 독립 실행 가능한 산출물인 평가셋·평가 하네스만 구현한다. 법조문 검증부터는 이 계획의 기준선 결과를 확인한 뒤 별도의 계획을 작성한다.

## File Map

- Create: `data/eval_consultation_queries.json` — 60건 fixture와 정답 라벨
- Create: `eval_consultation.py` — fixture 로드, 라이브 파이프라인 수집, 결정론적 지표 계산, CLI 출력·결과 저장
- Create: `test_consultation_eval.py` — fixture 계약·지표·결과 직렬화의 오프라인 회귀 테스트
- Modify: `.gitignore` — 평가 결과 파일이 이미 무시되는지 확인하고 필요한 경우 `eval_consultation_results.json` 명시
- Do not modify: `app/core/pipeline.py` — 첫 단계에서는 관측을 monkey-patch adapter로 수행

## Interfaces

`eval_consultation.py`는 다음 공개 가능한 내부 인터페이스를 제공한다.

```python
@dataclass(frozen=True)
class EvalCase:
    id: str
    category: str
    question: str
    expected_intent: str
    expected_topic: str | None
    required_laws: list[str]
    allowed_sources: list[str]
    expected_calculation: str | None
    expected_values: dict[str, float | int | str]
    required_notices: list[str]
    forbidden_claims: list[str]
    risk_level: str

def load_cases(path: Path) -> list[EvalCase]: ...
def validate_cases(cases: list[EvalCase]) -> list[str]: ...
def score_result(case: EvalCase, observed: dict) -> dict: ...
def aggregate_results(results: list[dict]) -> dict: ...
```

`observed`는 라이브 수집기가 만드는 다음 키를 갖는다.

```python
{
    "analysis": {
        "intent": str | None,
        "topic": str | None,
        "calculation_types": list[str],
        "missing_info": list[str],
    },
    "answer": str,
    "sources": list[dict],
    "calc_result": str | None,
    "assessment_result": str | None,
    "timing": {"total_ms": int, "ttft_ms": int},
    "pipeline_error": str | None,
}
```

`score_result()`는 다음 지표를 반환한다.

```python
{
    "intent_match": bool | None,
    "topic_match": bool | None,
    "required_law_coverage": float,
    "allowed_source_only": bool,
    "required_notice_coverage": float,
    "forbidden_claims_found": list[str],
    "disclaimer_present": bool,
    "calculation_present": bool,
    "pipeline_ok": bool,
    "automatic_pass": bool,
}
```

`None`은 fixture에서 해당 판정을 요구하지 않는다는 뜻이다. 집계기는 `None`을 분모에서 제외하고, 실행 실패는 품질 성공으로 세지 않는다.

### Task 1: 평가 fixture 계약과 실패 테스트 작성

**Files:**
- Create: `data/eval_consultation_queries.json`
- Create: `test_consultation_eval.py`
- Create: `eval_consultation.py`

**Interfaces:**
- Consumes: 없음
- Produces: `EvalCase`, `load_cases()`, `validate_cases()`의 최소 계약

- [ ] **Step 1: fixture 스키마를 실패 테스트로 고정한다.**

`test_consultation_eval.py`에 다음 테스트를 작성한다. 프로젝트의 기존 오프라인 테스트 관례에 맞춰 각 `test_*` 함수를 `main()`에서 순서대로 호출하고, 실패 시 traceback과 함께 exit code 1을 반환한다.

```python
from pathlib import Path

from eval_consultation import REQUIRED_CASE_KEYS, load_cases, validate_cases


FIXTURE = Path("data/eval_consultation_queries.json")


def test_fixture_has_exactly_60_unique_cases():
    cases = load_cases(FIXTURE)
    assert len(cases) == 60
    assert len({case.id for case in cases}) == 60


def test_fixture_has_required_fields_and_valid_enums():
    cases = load_cases(FIXTURE)
    assert validate_cases(cases) == []
    for case in cases:
        assert case.risk_level in {"low", "medium", "high"}
        assert case.allowed_sources
        assert isinstance(case.required_laws, list)


def test_fixture_category_distribution_matches_design():
    cases = load_cases(FIXTURE)
    counts = {}
    for case in cases:
        counts[case.category] = counts.get(case.category, 0) + 1
    assert counts == {
        "임금·계산": 10,
        "해고·징계·구제절차": 10,
        "근로시간·휴일·연차": 10,
        "퇴직금·퇴직·고용보험": 8,
        "산재·괴롭힘·차별": 8,
        "판례·행정해석·법령 조회": 8,
        "정보 부족·복합·구어체 질문": 6,
    }
```

- [ ] **Step 2: 테스트를 실행해 fixture가 아직 없어 실패하는지 확인한다.**

Run: `./.venv/bin/python test_consultation_eval.py`

Expected: FAIL with `ModuleNotFoundError` or missing fixture failure. 테스트가 우연히 통과하면 fixture의 실제 파일 존재 여부와 테스트 수를 확인하고, 아직 구현하지 않은 계약을 검사하도록 수정한다.

- [ ] **Step 3: fixture 로더의 타입·필드 상수를 최소 구현한다.**

`eval_consultation.py`에 다음을 추가한다.

```python
REQUIRED_CASE_KEYS = frozenset({
    "id", "category", "question", "expected_intent", "expected_topic",
    "required_laws", "allowed_sources", "expected_calculation",
    "expected_values", "required_notices", "forbidden_claims", "risk_level",
})
VALID_RISK_LEVELS = frozenset({"low", "medium", "high"})


@dataclass(frozen=True)
class EvalCase:
    id: str
    category: str
    question: str
    expected_intent: str
    expected_topic: str | None
    required_laws: list[str]
    allowed_sources: list[str]
    expected_calculation: str | None
    expected_values: dict[str, float | int | str]
    required_notices: list[str]
    forbidden_claims: list[str]
    risk_level: str


def load_cases(path: Path) -> list[EvalCase]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("evaluation fixture root must be a list")
    cases = []
    for index, item in enumerate(raw):
        if set(item) != REQUIRED_CASE_KEYS:
            raise ValueError(f"case {index} has invalid field set")
        cases.append(EvalCase(**item))
    return cases


def validate_cases(cases: list[EvalCase]) -> list[str]:
    errors = []
    seen = set()
    for case in cases:
        if case.id in seen:
            errors.append(f"duplicate id: {case.id}")
        seen.add(case.id)
        if not case.question.strip():
            errors.append(f"empty question: {case.id}")
        if case.risk_level not in VALID_RISK_LEVELS:
            errors.append(f"invalid risk level: {case.id}")
        if not case.allowed_sources:
            errors.append(f"missing allowed_sources: {case.id}")
    return errors
```

- [ ] **Step 4: fixture에 60건의 비식별 질문을 작성한다.**

각 record는 `EvalCase`의 12개 필드를 모두 포함한다. 질문 내용은 다음 기준을 따른다.

| ID 범위 | category | 작성 기준 |
|---|---|---|
| `wage-01`~`wage-10` | 임금·계산 | 최저임금, 주휴, 연장, 야간, 휴일, 퇴직금, 연차, 체불, 육아휴직, 복수 계산 |
| `dismissal-01`~`dismissal-10` | 해고·징계·구제절차 | 해고예고, 서면통지, 부당해고, 수습, 징계, 5인 미만, 구제신청 기한 |
| `hours-01`~`hours-10` | 근로시간·휴일·연차 | 근로시간, 연장한도, 휴게, 주휴, 연차, 단시간, 탄력근무 |
| `retirement-01`~`retirement-08` | 퇴직금·퇴직·고용보험 | 퇴직금 요건·평균임금·중간정산·실업급여·육아휴직급여 |
| `risk-01`~`risk-08` | 산재·괴롭힘·차별 | 업무상 재해, 괴롭힘 3요소, 신고·조사, 성희롱, 차별 |
| `law-01`~`law-08` | 판례·행정해석·법령 조회 | 판례번호·행정해석·현행 조문·절차 안내 |
| `missing-01`~`missing-06` | 정보 부족·복합·구어체 질문 | 금액·사업장 규모·근로자성·해고일 누락, 구어체, 복합 질문 |

`required_laws`와 `required_notices`는 질문의 정답을 판단하는 데 실제로 필요한 항목만 넣는다. 확인할 수 없는 정답을 fixture에 넣지 않는다. `forbidden_claims`는 오답으로 간주할 구체적 문자열만 넣고, 일반적인 표현 금지 목록으로 확장하지 않는다.

- [ ] **Step 5: fixture 계약 테스트를 실행한다.**

Run: `./.venv/bin/python test_consultation_eval.py`

Expected: PASS for all fixture schema and distribution tests.

- [ ] **Step 6: 커밋한다.**

```bash
git add data/eval_consultation_queries.json eval_consultation.py test_consultation_eval.py
git commit -m "test: add fixed consultation evaluation fixture"
```

### Task 2: 결정론적 답변 지표 구현

**Files:**
- Modify: `eval_consultation.py`
- Modify: `test_consultation_eval.py`

**Interfaces:**
- Consumes: `EvalCase`, 라이브 수집 결과 `observed`
- Produces: `score_result(case, observed) -> dict`, `aggregate_results(results) -> dict`

- [ ] **Step 1: 지표 계산 실패 테스트를 작성한다.**

```python
from eval_consultation import aggregate_results, score_result


def test_score_result_detects_missing_law_notice_and_forbidden_claim():
    case = EvalCase(
        id="x", category="법령", question="질문", expected_intent="law",
        expected_topic="해고·징계", required_laws=["근로기준법 제26조"],
        allowed_sources=["law_article"], expected_calculation=None,
        expected_values={}, required_notices=["1350"],
        forbidden_claims=["무조건 해고할 수 있습니다"], risk_level="high",
    )
    result = score_result(case, {
        "analysis": {"intent": "law", "topic": "해고·징계"},
        "answer": "근로기준법 제23조에 따르면 무조건 해고할 수 있습니다.",
        "sources": [{"source_type": "law_article", "title": "근로기준법"}],
        "calc_result": None, "timing": {"total_ms": 10, "ttft_ms": 2},
        "pipeline_error": None,
    })
    assert result["required_law_coverage"] == 0.0
    assert result["required_notice_coverage"] == 0.0
    assert result["forbidden_claims_found"] == ["무조건 해고할 수 있습니다"]
    assert result["automatic_pass"] is False


def test_aggregate_results_excludes_optional_none_from_denominator():
    summary = aggregate_results([
        {"pipeline_ok": True, "intent_match": True, "topic_match": None,
         "required_law_coverage": 1.0, "required_notice_coverage": 1.0,
         "forbidden_claims_found": [], "disclaimer_present": True,
         "automatic_pass": True, "timing": {"total_ms": 100}},
        {"pipeline_ok": False, "intent_match": False, "topic_match": False,
         "required_law_coverage": 0.0, "required_notice_coverage": 0.0,
         "forbidden_claims_found": ["x"], "disclaimer_present": False,
         "automatic_pass": False, "timing": {"total_ms": 200}},
    ])
    assert summary["total_cases"] == 2
    assert summary["pipeline_success_rate"] == 0.5
    assert summary["intent_accuracy"] == 0.5
    assert summary["topic_accuracy"] == 0.0
    assert summary["average_total_ms"] == 150
```

- [ ] **Step 2: 테스트를 실행해 지표 함수가 없어 실패하는지 확인한다.**

Run: `./.venv/bin/python test_consultation_eval.py`

Expected: FAIL with missing `score_result` or `aggregate_results`.

- [ ] **Step 3: 안전한 문자열·출처·계산 판정을 구현한다.**

구현 규칙:

- 법령·고지·금지문은 답변 원문에 대한 단순 substring 검사를 사용한다.
- 출처는 `source_type`이 `allowed_sources`에 없는 결과가 하나라도 있으면 `allowed_source_only=False`로 한다.
- `required_laws`가 비어 있으면 법령 커버리지는 `None`이 아니라 `1.0`으로 기록한다.
- `required_notices`가 비어 있으면 고지 커버리지는 `None`이 아니라 `1.0`으로 기록한다.
- `expected_calculation`이 `None`이면 `calculation_present=None`으로 둔다.
- 계산 질문의 첫 단계 판정은 계산 결과 이벤트가 존재하는지로 한정한다. 숫자 값의 의미 검증은 기존 계산기 골든 테스트와 3단계 이후의 별도 검증에서 다룬다.
- 면책 마커는 현재 코드 계약인 `법적 효력`을 사용한다.
- `pipeline_error`가 있거나 답변이 비어 있으면 `pipeline_ok=False`, `automatic_pass=False`로 한다.

```python
DISCLAIMER_MARKER = "법적 효력"


def _coverage(text: str, required: list[str]) -> float:
    if not required:
        return 1.0
    return sum(item in text for item in required) / len(required)


def score_result(case: EvalCase, observed: dict) -> dict:
    answer = observed.get("answer", "") or ""
    analysis = observed.get("analysis") or {}
    source_types = {
        hit.get("source_type", "") for hit in observed.get("sources", [])
    }
    forbidden = [item for item in case.forbidden_claims if item in answer]
    intent_match = (
        analysis.get("intent") == case.expected_intent
        if case.expected_intent else None
    )
    topic_match = (
        analysis.get("topic") == case.expected_topic
        if case.expected_topic else None
    )
    calculation_present = (
        observed.get("calc_result") is not None
        if case.expected_calculation else None
    )
    required_law_coverage = _coverage(answer, case.required_laws)
    required_notice_coverage = _coverage(answer, case.required_notices)
    allowed_source_only = source_types.issubset(set(case.allowed_sources))
    disclaimer_present = DISCLAIMER_MARKER in answer
    pipeline_ok = bool(answer.strip()) and not observed.get("pipeline_error")
    automatic_pass = (
        pipeline_ok
        and not forbidden
        and allowed_source_only
        and required_law_coverage >= 1.0
        and required_notice_coverage >= 1.0
        and disclaimer_present
        and intent_match is not False
        and topic_match is not False
        and calculation_present is not False
    )
    return {
        "intent_match": intent_match,
        "topic_match": topic_match,
        "required_law_coverage": required_law_coverage,
        "allowed_source_only": allowed_source_only,
        "required_notice_coverage": required_notice_coverage,
        "forbidden_claims_found": forbidden,
        "disclaimer_present": disclaimer_present,
        "calculation_present": calculation_present,
        "pipeline_ok": pipeline_ok,
        "automatic_pass": automatic_pass,
    }
```

`expected_calculation=None`, `expected_intent=None`, `expected_topic=None`인 경우 해당 조건은 자동 통과 조건에서 제외한다.

```python
automatic_pass = (
    pipeline_ok
    and not forbidden
    and allowed_source_only
    and required_law_coverage >= 1.0
    and required_notice_coverage >= 1.0
    and disclaimer_present
    and intent_match is not False
    and topic_match is not False
    and calculation_present is not False
)
```

- [ ] **Step 4: 집계 함수를 구현한다.**

집계 결과는 최소한 다음 키를 포함한다.

```python
{
    "total_cases": int,
    "pipeline_success_rate": float,
    "automatic_pass_rate": float,
    "intent_accuracy": float | None,
    "topic_accuracy": float | None,
    "required_law_coverage": float,
    "required_notice_coverage": float,
    "disclaimer_rate": float,
    "forbidden_claim_count": int,
    "average_total_ms": int,
    "p95_total_ms": int,
}
```

정확도 분모에서 `None` 판정은 제외한다. 결과가 0건이면 비율은 `0.0`으로 반환하고 예외를 발생시키지 않는다.

- [ ] **Step 5: 지표 테스트를 실행한다.**

Run: `./.venv/bin/python test_consultation_eval.py`

Expected: PASS for fixture and metric tests.

- [ ] **Step 6: 커밋한다.**

```bash
git add eval_consultation.py test_consultation_eval.py
git commit -m "feat: add deterministic consultation evaluation metrics"
```

### Task 3: 라이브 파이프라인 수집 adapter 구현

**Files:**
- Modify: `eval_consultation.py`
- Modify: `test_consultation_eval.py`

**Interfaces:**
- Consumes: `EvalCase`, `AppConfig.from_env()`, `process_question()` 이벤트
- Produces: `run_case(case, config) -> dict` with the `observed` schema

- [ ] **Step 1: 이벤트 수집 테스트용 fake generator를 작성한다.**

```python
def test_collect_events_builds_observed_shape():
    observed = collect_events([
        {"type": "sources", "hits": [{"source_type": "law_article"}]},
        {"type": "meta", "calc_result": "계산 결과"},
        {"type": "chunk", "text": "법적 효력이 없습니다."},
        {"type": "done"},
    ])
    assert observed["answer"] == "법적 효력이 없습니다."
    assert observed["calc_result"] == "계산 결과"
    assert observed["sources"] == [{"source_type": "law_article"}]
    assert observed["pipeline_error"] is None
```

- [ ] **Step 2: 테스트를 실행해 수집 함수가 없어 실패하는지 확인한다.**

Run: `./.venv/bin/python test_consultation_eval.py`

Expected: FAIL with missing `collect_events`.

- [ ] **Step 3: 이벤트 수집기를 구현한다.**

`collect_events(events)`는 `chunk`를 순서대로 합치고, `sources`, `meta`, `error`, `done`을 수집한다. `ping`과 `status`는 결과 본문에 넣지 않는다. 첫 `chunk` 시점을 TTFT로 기록하고 첫 이벤트부터 `done`까지 `total_ms`를 측정하는 시간 주입 인자를 제공해 테스트가 `time.sleep()` 없이 결정론적으로 동작하게 한다.

- [ ] **Step 4: 분석 결과 캡처 adapter를 구현한다.**

`run_case()`는 기존 모듈을 수정하지 않고 다음 방식으로 분석 결과를 캡처한다.

1. `app.core.pipeline.analyze_intent`의 원본을 보관한다.
2. wrapper가 원본을 호출하고 `AnalysisResult`의 `consultation_type`, `consultation_topic`, `calculation_types`, `missing_info`를 dict로 저장한다.
3. `process_question()` 실행 후 `finally`에서 원본을 복원한다.
4. `_compute_missing_info`를 monkey-patch하지 않는다. 평가셋은 실제 운영 누락정보 정책을 측정해야 한다.

```python
def _analysis_snapshot(analysis) -> dict:
    return {
        "intent": getattr(analysis, "consultation_type", None),
        "topic": getattr(analysis, "consultation_topic", None),
        "calculation_types": list(getattr(analysis, "calculation_types", []) or []),
        "missing_info": list(getattr(analysis, "missing_info", []) or []),
    }
```

- [ ] **Step 5: live adapter 테스트를 실행한다.**

Run: `./.venv/bin/python test_consultation_eval.py`

Expected: PASS without API calls. Fake event collection and monkey-patch restoration tests must pass.

- [ ] **Step 6: 커밋한다.**

```bash
git add eval_consultation.py test_consultation_eval.py
git commit -m "feat: collect consultation pipeline evaluation events"
```

### Task 4: CLI, 결과 스키마, dry-run 기준선 실행

**Files:**
- Modify: `eval_consultation.py`
- Modify: `test_consultation_eval.py`
- Modify: `.gitignore` only if the existing `*_results.json` rule is insufficient

**Interfaces:**
- Consumes: fixture, `score_result()`, `aggregate_results()`, `run_case()`
- Produces: `python3 eval_consultation.py --offline`, `python3 eval_consultation.py --live --limit N`

- [ ] **Step 1: CLI 계약 테스트를 작성한다.**

```python
def test_offline_cli_validates_fixture_without_external_clients(capsys):
    exit_code = main(["--offline"])
    assert exit_code == 0
    assert "60건" in capsys.readouterr().out


def test_limit_must_be_positive():
    assert main(["--offline", "--limit", "0"]) == 2
```

- [ ] **Step 2: CLI 테스트를 실행해 실패를 확인한다.**

Run: `./.venv/bin/python test_consultation_eval.py`

Expected: FAIL until `main(argv)` and argument validation exist.

- [ ] **Step 3: `--offline`, `--live`, `--limit`, `--case`, `--output`을 구현한다.**

동작 규칙:

- 기본 실행은 `--offline`과 동일하게 외부 호출 없이 fixture만 검증한다.
- `--offline`은 fixture 오류가 있으면 exit code 1, 정상이면 0을 반환한다.
- `--live`는 `AppConfig.from_env()`를 한 번 호출하고, 선택된 case를 순서대로 처리한다.
- `--limit N`은 fixture 앞에서부터 N건만 선택한다.
- `--case ID`는 지정 ID 하나만 선택하며 존재하지 않으면 exit code 2다.
- `--output PATH`가 없으면 `eval_consultation_results.json`에 저장한다.
- 라이브 결과 파일에는 `run_metadata`, `summary`, `results`를 저장한다.
- `run_metadata`에는 ISO 실행 시각, fixture 경로, fixture case 수, Python 버전, git commit hash를 기록한다.
- 답변 원문은 결과 파일에 최대 3,000자까지만 저장한다. 운영 DB나 저장소에는 업로드하지 않는다.

결과 레코드는 다음 구조를 사용한다.

```json
{
  "case_id": "law-01",
  "category": "판례·행정해석·법령 조회",
  "question": "...",
  "observed": {"analysis": {}, "answer": "...", "sources": [], "timing": {}},
  "scores": {"automatic_pass": false},
  "pipeline_error": null
}
```

- [ ] **Step 4: 오프라인 기준선을 실행한다.**

Run: `./.venv/bin/python eval_consultation.py --offline`

Expected:

```text
fixture: 60건
schema: PASS
distribution: PASS
offline evaluation contract: PASS
```

- [ ] **Step 5: 기존 회귀 테스트를 실행한다.**

Run:

```bash
./.venv/bin/python test_wage_golden.py
./.venv/bin/python test_pipeline_wiring.py
./.venv/bin/python test_offline_units.py
./.venv/bin/python test_llm_fallback.py
node test_answer_renderer.js
node test_answer_glance.js
```

Expected: 모든 명령 exit code 0.

- [ ] **Step 6: 커밋한다.**

```bash
git add eval_consultation.py test_consultation_eval.py .gitignore
git commit -m "feat: add consultation evaluation CLI and baseline contract"
```

### Task 5: 기준선 보고와 다음 단계 게이트 기록

**Files:**
- Create: `docs/04-report/consultation-eval-baseline.md`
- Modify: `eval_consultation.py` only if report metadata is missing

**Interfaces:**
- Consumes: `eval_consultation.py --offline` 결과와, 키가 있는 경우 `--live --limit 60` 결과
- Produces: 사람이 검토할 기준선 보고서와 2단계 진입 조건

- [ ] **Step 1: 보고서 템플릿 검증 테스트를 작성한다.**

보고서는 다음 섹션을 반드시 포함해야 한다.

```text
실행 정보 / 평가셋 분포 / 자동 지표 / 실패 케이스 / 전문가 검토 큐 / 다음 게이트
```

- [ ] **Step 2: 오프라인 실행 결과를 기록한다.**

오프라인 결과에는 외부 답변 품질 점수를 기록하지 않는다. fixture 계약, 분포, 지표 계산 계약만 통과했다고 명시한다.

- [ ] **Step 3: 라이브 기준선을 실행한다.**

Run: `./.venv/bin/python eval_consultation.py --live --limit 60`

필수 환경변수가 없거나 외부 서비스가 unavailable이면 실패를 숨기지 않고 보고서에 `미실행` 사유를 기록한다. 추정 점수나 임의의 통과 판정을 쓰지 않는다.

- [ ] **Step 4: 보고서에 2단계 진입 게이트를 기록한다.**

2단계 법조문 검증으로 넘어가기 위한 조건:

- 평가 fixture 60건이 모두 유효하다.
- 오프라인 실행이 재현 가능하다.
- 라이브 기준선 실행 결과의 성공·실패·미실행 상태가 구분된다.
- 법조문 검증 대상 질문과 현재 검증되지 않는 법조문 사례가 목록화되어 있다.

- [ ] **Step 5: 커밋한다.**

```bash
git add docs/04-report/consultation-eval-baseline.md
git commit -m "docs: record consultation evaluation baseline"
```

## Verification Checklist

구현 완료 전 다음을 모두 확인한다.

- [ ] fixture가 정확히 60건이고 ID가 중복되지 않는다.
- [ ] 7개 category 분포가 설계와 일치한다.
- [ ] `--offline`이 API 키 없이 통과한다.
- [ ] 지표의 `None` 선택 필드가 분모에 포함되지 않는다.
- [ ] pipeline wrapper가 예외가 나도 원래 `analyze_intent`를 복원한다.
- [ ] 라이브 결과 파일은 저장소에 추적되지 않는다.
- [ ] 기존 회귀 테스트가 모두 통과한다.
- [ ] 라이브 실행을 하지 못했을 때 성공으로 보고하지 않는다.

## Handoff to Next Plan

이 계획의 기준선 보고서가 작성되면 다음 계획은 설계서 6.2에 따라 법조문 검증기로 분리한다. 다음 계획은 `app/core/citation_validator.py`의 법조문 패턴·허용 목록·교정 실패 처리만 대상으로 하며, 평가 하네스의 결과 스키마를 소비하고 fixture나 평가 CLI의 인터페이스를 임의로 변경하지 않는다.
