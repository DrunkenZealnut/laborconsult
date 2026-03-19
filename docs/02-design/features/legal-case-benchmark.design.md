# legal-case-benchmark Design Document

> **Summary**: output_legal_cases 114건 RAG 챗봇 정확도·응답시간 벤치마크 스크립트 설계
>
> **Project**: laborconsult (nodong.kr 노동법 Q&A + 임금계산기)
> **Date**: 2026-03-13
> **Status**: Draft
> **Planning Doc**: [legal-case-benchmark.plan.md](../../01-plan/features/legal-case-benchmark.plan.md)

---

## 1. Overview

### 1.1 Design Goals

1. 114건 법원판례/상담사례에 대해 전체 RAG 파이프라인 실행 → 답변 생성
2. LLM-as-Judge로 챗봇 답변 vs 전문가 답변 비교 채점 (5항목, 0~5점)
3. 케이스별 end-to-end + 단계별 응답시간 프로파일링
4. 카테고리별 집계 통계 + 약점 분석 리포트

### 1.2 Design Principles

- **기존 파이프라인 재사용**: `process_question()` 그대로 호출 — 실제 서비스와 동일한 결과
- **독립 실행**: 서버 기동 불필요, Supabase 저장 비활성화
- **중단/재개**: 케이스별 결과 즉시 저장, `--skip-to`로 이어서 실행
- **비용 통제**: `--limit`, `--dry-run` 옵션, 실행 전 비용 예측 출력

---

## 2. Architecture

### 2.1 파일 구조

```
benchmark_pipeline.py          # [신규] 메인 벤치마크 스크립트 (단일 파일)
benchmark_pipeline_results.json # [출력] 케이스별 상세 결과
```

### 2.2 Dependencies

| Component | Depends On | Purpose |
|-----------|-----------|---------|
| `benchmark_pipeline.py` | `app.config.AppConfig` | API 클라이언트 초기화 |
| | `app.core.pipeline.process_question` | 전체 파이프라인 실행 |
| | `app.models.session.Session` | 세션 생성 (케이스별 독립) |
| | `anthropic.Anthropic` | LLM-as-Judge 채점 |

### 2.3 데이터 흐름

```
output_legal_cases/*.md
        │
        ▼
┌─ parse_case_file() ─┐
│ question, answer,    │
│ metadata, chapter    │
└──────────┬───────────┘
           │
           ▼
┌─ run_single_case() ──────────────────────────┐
│                                               │
│  Session(id=f"bench_{case_id}")               │
│       │                                       │
│       ▼                                       │
│  process_question(question, session, config)  │
│       │ yield events...                       │
│       │                                       │
│  t0 ──┼── timing per event type              │
│       │                                       │
│  collect: answer, calc_result, sources,       │
│           timing breakdown                    │
└──────────┬───────────────────────────────────┘
           │
           ▼
┌─ judge_answer() ─────────────────────────────┐
│  Claude Haiku: chatbot_answer vs expert       │
│  → scores (5 items, 0~5 each)                │
│  → reasoning per item                        │
└──────────┬───────────────────────────────────┘
           │
           ▼
┌─ aggregate_results() ────────────────────────┐
│  카테고리별 평균 점수, 시간, 약점 식별        │
│  → JSON + console summary                    │
└──────────────────────────────────────────────┘
```

---

## 3. Data Model

### 3.1 케이스 파일 파싱 구조

```python
@dataclass
class ParsedCase:
    case_id: int              # 사례번호 (1~114)
    filename: str             # case_001_*.md
    title: str                # "사례1 채용 취소 시 구제방안 문의"
    chapter: str              # "Chapter 01 일하기 전 알아두기"
    topic: str                # "채용 취소 / 근로계약 작성하기"
    question: str             # ## 질문 섹션 전문
    expert_answer: str        # ## 답변 섹션 전문
    related_laws: list[str]   # 관련법령 목록
    has_precedent: bool       # ## 판례 섹션 존재 여부
    has_admin_interp: bool    # ## 행정해석 섹션 존재 여부
```

**파싱 규칙**:
- `## 질문` ~ `## 답변` 사이를 question으로 추출
- `## 답변` ~ 다음 `##` 사이를 expert_answer로 추출
- 메타데이터 테이블에서 사례번호, 챕터, 주제, 관련법령 추출
- 일부 케이스(case_101 등)에서 질문/답변 순서가 뒤바뀜 → 양방향 탐색

### 3.2 벤치마크 결과 구조

```python
@dataclass
class BenchmarkResult:
    case_id: int
    filename: str
    chapter: str
    topic: str

    # 파이프라인 결과
    chatbot_answer: str
    calc_result: str | None
    search_hits: list[dict]        # [{title, url, score}]
    pipeline_error: str | None

    # 타이밍 (밀리초)
    timing: dict                   # {total_ms, intent_ms, search_ms, calc_ms, llm_ms}

    # Judge 채점
    scores: dict                   # {legal_accuracy, completeness, relevance, practicality, calculation_accuracy}
    overall_score: float           # 5항목 가중평균
    judge_reasoning: str           # 채점 근거 요약
```

### 3.3 출력 JSON 구조

```json
{
  "run_metadata": {
    "date": "2026-03-13T15:30:00",
    "total_cases": 114,
    "completed": 110,
    "errors": 4,
    "total_time_sec": 2850,
    "total_cost_usd": 6.2,
    "pipeline_model": "claude-sonnet-4-6",
    "judge_model": "claude-haiku-4-5-20251001"
  },
  "summary": {
    "overall_avg_score": 3.8,
    "overall_avg_time_ms": 8500,
    "by_chapter": {
      "Chapter 01 일하기 전 알아두기": {"avg_score": 3.5, "avg_time_ms": 7200, "count": 15},
      ...
    },
    "by_topic": {
      "근로시간 / 휴일 / 휴가": {"avg_score": 4.1, ...},
      ...
    },
    "weak_areas": [
      {"topic": "산재보상", "avg_score": 2.8, "recommendation": "산재 관련 RAG 데이터 보강 필요"}
    ]
  },
  "results": [
    {
      "case_id": 1,
      "filename": "case_001_*.md",
      "chapter": "Chapter 01 ...",
      "topic": "채용 취소",
      "chatbot_answer": "...",
      "expert_answer": "...",
      "calc_result": null,
      "search_hits": [...],
      "timing": {"total_ms": 8200, "intent_ms": 1100, ...},
      "scores": {"legal_accuracy": 4, "completeness": 3, ...},
      "overall_score": 3.6,
      "judge_reasoning": "..."
    }
  ]
}
```

---

## 4. 핵심 함수 설계

### 4.1 parse_case_file(filepath) → ParsedCase

```python
def parse_case_file(filepath: Path) -> ParsedCase:
    """마크다운 케이스 파일을 파싱하여 구조화된 데이터로 변환"""
    text = filepath.read_text(encoding="utf-8")

    # 메타데이터 테이블 파싱
    case_id = int(re.search(r"사례번호\s*\|\s*(\d+)", text).group(1))
    chapter = re.search(r"챕터\s*\|\s*(.+)", text).group(1).strip()
    topic = re.search(r"주제\s*\|\s*(.+)", text).group(1).strip()

    # 섹션 분리
    sections = re.split(r"^##\s+", text, flags=re.MULTILINE)
    question = ""
    answer = ""
    for sec in sections:
        if sec.startswith("질문"):
            question = sec[2:].strip()   # "질문\n..." → 본문
        elif sec.startswith("답변"):
            answer = sec[2:].strip()

    return ParsedCase(case_id=case_id, ..., question=question, expert_answer=answer)
```

### 4.2 run_single_case(case, config) → BenchmarkResult

```python
def run_single_case(case: ParsedCase, config: AppConfig) -> BenchmarkResult:
    """단일 케이스에 대해 전체 파이프라인 실행 + 타이밍 측정"""
    session = Session(id=f"bench_{case.case_id}")

    t_start = time.perf_counter()
    t_phases = {}

    chatbot_answer = ""
    calc_result = None
    search_hits = []
    error = None

    try:
        for event in process_question(case.question, session, config):
            t_now = time.perf_counter()

            if event["type"] == "status":
                # 단계 전환 시점 기록
                status_text = event["text"]
                if "분석" in status_text:
                    t_phases["intent_start"] = t_now
                elif "계산기" in status_text:
                    t_phases["calc_start"] = t_now
                elif "검색" in status_text:
                    t_phases["search_start"] = t_now

            elif event["type"] == "meta":
                calc_result = event.get("calc_result")
                t_phases["calc_end"] = t_now

            elif event["type"] == "sources":
                search_hits = event.get("hits", [])
                t_phases["search_end"] = t_now

            elif event["type"] == "chunk":
                if "llm_start" not in t_phases:
                    t_phases["llm_start"] = t_now
                chatbot_answer += event["text"]

            elif event["type"] == "done":
                t_phases["llm_end"] = t_now

    except Exception as e:
        error = str(e)

    t_total = (time.perf_counter() - t_start) * 1000

    timing = {
        "total_ms": round(t_total),
        "intent_ms": _phase_duration(t_phases, "intent_start", "calc_start", "search_start"),
        "calc_ms": _phase_duration(t_phases, "calc_start", "calc_end"),
        "search_ms": _phase_duration(t_phases, "search_start", "search_end"),
        "llm_ms": _phase_duration(t_phases, "llm_start", "llm_end"),
    }

    return BenchmarkResult(
        case_id=case.case_id, ...,
        chatbot_answer=chatbot_answer,
        timing=timing, pipeline_error=error,
    )
```

### 4.3 judge_answer(case, result, client) → dict

```python
JUDGE_SYSTEM = """당신은 한국 노동법 전문가이자 답변 품질 평가사입니다.
채팅봇 답변을 전문가 답변과 비교하여 5가지 항목을 0~5점으로 채점하세요.
반드시 유효한 JSON만 출력하세요."""

JUDGE_PROMPT = """## 질문
{question}

## 전문가 답변 (정답 기준)
{expert_answer}

## 챗봇 답변 (평가 대상)
{chatbot_answer}

## 채점 기준
1. legal_accuracy (법률 정확성): 인용된 법률·판례가 정확한가? 잘못된 법률 인용이 있는가?
2. completeness (완전성): 전문가 답변의 핵심 포인트가 모두 포함되어 있는가?
3. relevance (관련성): 질문에 정확히 대응하는 답변인가? 불필요한 내용이 없는가?
4. practicality (실용성): 구체적 절차·기관 안내·필요 서류 등 실행 가능한 조언을 포함하는가?
5. calculation_accuracy (계산 정확성): 수치 계산이 필요한 경우 정확한가? 계산이 불필요하면 "N/A"로 표기하고 나머지 4개 평균으로 대체.

점수 기준:
- 0: 완전히 잘못됨 / 무관한 답변
- 1: 심각한 오류 또는 핵심 누락
- 2: 부분적으로 맞지만 주요 오류 존재
- 3: 대체로 맞지만 세부 사항 부족/오류
- 4: 정확하고 충분하나 약간의 개선 여지
- 5: 전문가 답변 수준과 동등 이상

JSON 출력:
{{
  "legal_accuracy": 0~5,
  "completeness": 0~5,
  "relevance": 0~5,
  "practicality": 0~5,
  "calculation_accuracy": 0~5 또는 "N/A",
  "reasoning": "채점 근거 한 문단 요약"
}}"""

def judge_answer(case: ParsedCase, result: BenchmarkResult, client) -> dict:
    """LLM-as-Judge로 답변 품질 채점"""
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        temperature=0,
        system=JUDGE_SYSTEM,
        messages=[{
            "role": "user",
            "content": JUDGE_PROMPT.format(
                question=case.question[:2000],
                expert_answer=case.expert_answer[:2000],
                chatbot_answer=result.chatbot_answer[:2000],
            ),
        }],
    )
    # JSON 파싱 + overall_score 계산
    scores = json.loads(resp.content[0].text)

    # calculation_accuracy "N/A" 처리
    calc_score = scores.get("calculation_accuracy")
    if calc_score == "N/A" or calc_score is None:
        numeric_scores = [scores[k] for k in ["legal_accuracy", "completeness", "relevance", "practicality"]]
    else:
        numeric_scores = [scores[k] for k in ["legal_accuracy", "completeness", "relevance", "practicality", "calculation_accuracy"]]

    scores["overall_score"] = round(sum(numeric_scores) / len(numeric_scores), 2)
    return scores
```

### 4.4 aggregate_results(results) → dict

```python
def aggregate_results(results: list[dict]) -> dict:
    """카테고리별 집계 + 약점 분석"""
    by_chapter = defaultdict(list)
    by_topic = defaultdict(list)

    for r in results:
        if r.get("pipeline_error"):
            continue
        by_chapter[r["chapter"]].append(r)
        by_topic[r["topic"]].append(r)

    def _stats(group: list) -> dict:
        scores = [r["overall_score"] for r in group]
        times = [r["timing"]["total_ms"] for r in group]
        return {
            "count": len(group),
            "avg_score": round(sum(scores) / len(scores), 2),
            "min_score": min(scores),
            "max_score": max(scores),
            "avg_time_ms": round(sum(times) / len(times)),
        }

    chapter_stats = {ch: _stats(g) for ch, g in sorted(by_chapter.items())}
    topic_stats = {tp: _stats(g) for tp, g in sorted(by_topic.items())}

    # 약점 카테고리: 평균 3.0 미만
    weak_areas = [
        {"topic": tp, "avg_score": s["avg_score"],
         "recommendation": f"{tp} 관련 RAG 데이터 보강 또는 프롬프트 개선 필요"}
        for tp, s in topic_stats.items() if s["avg_score"] < 3.0
    ]

    return {
        "by_chapter": chapter_stats,
        "by_topic": topic_stats,
        "weak_areas": sorted(weak_areas, key=lambda x: x["avg_score"]),
    }
```

### 4.5 main() — CLI 진입점

```python
def main():
    parser = argparse.ArgumentParser(description="RAG 파이프라인 벤치마크")
    parser.add_argument("--limit", type=int, help="최대 실행 건수")
    parser.add_argument("--skip-to", type=int, help="이 번호부터 실행 (이전 결과 유지)")
    parser.add_argument("--category", type=str, help="특정 챕터만 실행")
    parser.add_argument("--dry-run", action="store_true", help="파싱만 실행, API 미호출")
    parser.add_argument("--delay", type=float, default=1.0, help="케이스 간 딜레이(초)")
    args = parser.parse_args()

    # 기존 결과 로드 (resume 지원)
    existing = load_existing_results()

    config = AppConfig.from_env()
    cases = load_all_cases()

    # 필터링
    if args.skip_to:
        cases = [c for c in cases if c.case_id >= args.skip_to]
    if args.category:
        cases = [c for c in cases if args.category in c.chapter]
    if args.limit:
        cases = cases[:args.limit]

    # 비용 예측 출력
    print(f"실행 대상: {len(cases)}건")
    print(f"예상 비용: ~${len(cases) * 0.055:.2f}")
    print(f"예상 시간: ~{len(cases) * 25 / 60:.0f}분")

    if args.dry_run:
        for c in cases:
            print(f"  #{c.case_id}: {c.title} ({c.topic})")
        return

    # 실행
    results = existing.get("results", [])
    done_ids = {r["case_id"] for r in results}

    for i, case in enumerate(cases):
        if case.case_id in done_ids:
            continue

        print(f"[{i+1}/{len(cases)}] #{case.case_id}: {case.title}...", end=" ", flush=True)

        result = run_single_case(case, config)

        if not result.pipeline_error:
            scores = judge_answer(case, result, config.claude_client)
        else:
            scores = {"overall_score": 0, "reasoning": f"Error: {result.pipeline_error}"}

        result_dict = {
            "case_id": case.case_id,
            "filename": case.filename,
            "chapter": case.chapter,
            "topic": case.topic,
            "chatbot_answer": result.chatbot_answer,
            "expert_answer": case.expert_answer,
            "calc_result": result.calc_result,
            "search_hits": result.search_hits,
            "timing": result.timing,
            "pipeline_error": result.pipeline_error,
            **scores,
        }
        results.append(result_dict)

        # 즉시 저장 (중단 시에도 결과 보존)
        save_results(results)

        score = scores.get("overall_score", 0)
        time_s = result.timing["total_ms"] / 1000
        print(f"score={score:.1f}  time={time_s:.1f}s")

        time.sleep(args.delay)

    # 최종 집계
    summary = aggregate_results(results)
    save_final_report(results, summary)
    print_summary(summary)
```

---

## 5. 타이밍 측정 설계

### 5.1 단계별 시점 캡처

`process_question()`은 yield 기반 제너레이터이므로, 이벤트 타입별로 시점을 캡처:

| 이벤트 | 캡처 시점 | 단계 |
|--------|----------|------|
| `status: "질문 분석 중"` | `t_intent_start` | Intent 분석 시작 |
| `status: "임금계산기 실행 중"` | `t_calc_start` | 계산기 시작 |
| `meta: calc_result` | `t_calc_end` | 계산기 완료 |
| `status: "관련 문서 검색 중"` | `t_search_start` | RAG 검색 시작 |
| `sources: hits` | `t_search_end` | RAG 검색 완료 |
| first `chunk` | `t_llm_start` | LLM 생성 시작 (TTFT) |
| `done` | `t_llm_end` | LLM 생성 완료 |

### 5.2 파생 지표

```python
timing = {
    "total_ms":  t_done - t_start,
    "intent_ms": t_next_phase - t_intent_start,  # 의도 분석
    "calc_ms":   t_calc_end - t_calc_start,       # 계산기 (없으면 0)
    "search_ms": t_search_end - t_search_start,   # RAG 검색
    "llm_ms":    t_llm_end - t_llm_start,         # LLM 답변 생성
    "ttft_ms":   t_llm_start - t_start,           # Time to First Token
}
```

---

## 6. LLM-as-Judge 설계

### 6.1 채점 모델 선택

| 옵션 | 비용/건 | 품질 | 선택 |
|------|---------|------|------|
| Claude Haiku 4.5 | ~$0.003 | 충분 (구조화 채점) | ✅ |
| Claude Sonnet 4.6 | ~$0.05 | 높음 | ✗ (비용 과다) |

### 6.2 채점 일관성 보장

- `temperature=0` 고정
- 구체적 루브릭 (0~5 각 기준 명시)
- JSON 형식 강제 (자유 텍스트 없음)
- `calculation_accuracy: "N/A"` 허용 → 비계산 케이스에서 편향 방지

### 6.3 가중 평균

모든 항목 동일 가중치 (1/5 또는 1/4). `calculation_accuracy`가 "N/A"이면 나머지 4개 평균.

---

## 7. 에러 처리

### 7.1 파이프라인 에러

```python
try:
    result = run_single_case(case, config)
except Exception as e:
    result = BenchmarkResult(
        ..., pipeline_error=str(e), chatbot_answer="", timing={"total_ms": 0, ...}
    )
```

- 개별 케이스 에러는 `pipeline_error`에 기록하고 계속 진행
- Judge 채점은 skip (overall_score = 0)

### 7.2 Rate Limiting

```python
MAX_RETRIES = 3
RETRY_DELAY = [5, 15, 30]  # exponential backoff

for attempt in range(MAX_RETRIES):
    try:
        result = run_single_case(case, config)
        break
    except anthropic.RateLimitError:
        if attempt < MAX_RETRIES - 1:
            time.sleep(RETRY_DELAY[attempt])
        else:
            result = BenchmarkResult(..., pipeline_error="Rate limited")
```

### 7.3 JSON 파싱 에러 (Judge)

Judge 응답이 유효 JSON이 아닌 경우:
1. markdown 코드블록 제거 후 재파싱
2. 실패 시 `{"overall_score": -1, "reasoning": "Judge parse error"}`

---

## 8. CLI 옵션

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--limit N` | 전체 | N건만 실행 |
| `--skip-to N` | 1 | 케이스 N번부터 실행 |
| `--category STR` | 전체 | 특정 챕터만 (예: "Chapter 03") |
| `--delay SEC` | 1.0 | 케이스 간 딜레이 (rate limit 방지) |
| `--dry-run` | false | 파싱만 실행, API 미호출 |
| `--output PATH` | benchmark_pipeline_results.json | 결과 파일 경로 |

---

## 9. Console 출력 형식

### 9.1 실행 중

```
RAG 파이프라인 벤치마크
실행 대상: 114건 | 예상 비용: ~$6.27 | 예상 시간: ~47분

[  1/114] #1: 채용 취소 시 구제방안 문의... score=4.0  time=7.2s
[  2/114] #2: 입사예정일 통보 후 채용취소... score=3.5  time=8.1s
...
[ 16/114] #16: 토요일 특근 수당 계산방법... score=4.5  time=12.3s  [CALC]
...
[114/114] #114: 배달 중 사고 산재 판단... score=3.0  time=9.5s
```

### 9.2 최종 요약

```
══════════════════════════════════════════════
벤치마크 결과 요약
══════════════════════════════════════════════
전체 평균 점수: 3.82 / 5.0
전체 평균 시간: 8.5초
완료: 110건 | 에러: 4건

── 챕터별 ──
  Chapter 01 일하기 전 알아두기  (15건): 3.5점 | 7.2초
  Chapter 03 일하는 중           (42건): 4.1점 | 9.1초
  Chapter 04 퇴직                (28건): 3.7점 | 8.0초
  Chapter 05 해고                (18건): 3.4점 | 7.8초
  Chapter 06 괴롭힘/성희롱       (11건): 3.9점 | 6.5초

── 약점 영역 (3.0 미만) ──
  ⚠️ 산재보상: 2.8점 → RAG 데이터 보강 필요
  ⚠️ 채용취소: 2.9점 → 판례 색인 강화 필요

결과 저장: benchmark_pipeline_results.json
══════════════════════════════════════════════
```

---

## 10. Implementation Order

### 10.1 순서 (5단계)

1. [ ] `benchmark_pipeline.py` 기본 구조 — argparse, case 파싱, main loop
2. [ ] `run_single_case()` — process_question 호출 + 타이밍 캡처
3. [ ] `judge_answer()` — LLM-as-Judge 채점 함수
4. [ ] `aggregate_results()` + console 출력 + JSON 저장
5. [ ] 10건 pilot run → 검증 후 전체 실행

### 10.2 변경 규모 예상

| File | Added Lines | Modified Lines |
|------|-------------|----------------|
| `benchmark_pipeline.py` | ~350 | 0 (신규 파일) |
| **Total** | **~350** | **0** |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-13 | Initial draft | Claude |
