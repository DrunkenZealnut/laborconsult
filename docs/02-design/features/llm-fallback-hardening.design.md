# LLM 폴백 경화 Design (llm-fallback-hardening)

> **Summary**: Plan의 FR 13종을 코드 수준으로 설계한다. `_stream_answer` 상태 머신 재구성(빈 응답·절단·전환 하트비트), 타임아웃/재시도 예산의 단일 출처화, 의도분석 교차벤더 어댑터, 인용 교정 단계 예산 상한, 폴백 계측·오프라인 테스트 하네스를 다룬다. **설계 중 3순위 폴백(Gemini)이 이미 404로 죽어 있음을 실측 확인**해 긴급 항목으로 승격했다.
>
> **Project**: laborconsult
> **Author**: DrunkenZealnut
> **Date**: 2026-08-06
> **Status**: Draft
> **Planning Doc**: [llm-fallback-hardening.plan.md](../../01-plan/features/llm-fallback-hardening.plan.md)

---

## 1. 설계 개요

### 1.1 설계 목표

Plan §1.4의 갭 G1~G9를 코드 변경으로 닫는다. 기준선은 **"조용히 나빠지는 것"은 허용, "조용히 틀리는 것"은 차단**이다. 빈 답변·잘린 답변이 완결된 상담 답변으로 사용자에게 전달되거나 게시판에 남는 경로를 제거하고, 벤더 하나가 죽어도 계산·게이트·교정이 함께 죽지 않게 한다.

### 1.2 설계 원칙

| # | 원칙 | 적용 |
|---|------|------|
| P1 | **정상 경로 무회귀** | 모든 경화는 실패 경로에서만 분기. 정상 응답의 청크 흐름·이벤트 순서 불변 |
| P2 | **재시도보다 전환** | 동일 벤더 재시도는 같은 장애를 다시 만난다. 답변 경로 `max_retries=0` + 즉시 벤더 전환 |
| P3 | **단일 출처** | 타임아웃·재시도·모델명은 `app/config.py` 한 곳. 예산표와 코드가 어긋나지 않게 |
| P4 | **호출 규약 보존** | `_stream_answer`의 `(provider, text)` 2-튜플 유지 → `test_abuse_guard.py:547` 스텁 무변경 |
| P5 | **무이벤트 구간 제거** | 프론트 idle 60초(`index.html:1621`)보다 긴 침묵을 만들지 않는다 |
| P6 | **fail-open 불변** | 가드·게이트 규약(`chatbot-security` FR-05)은 그대로. 폴백 추가가 차단을 늘리지 않는다 |

### 1.3 실측으로 확정한 설계 입력 (2026-08-06)

| 항목 | 실측 결과 | 설계 반영 |
|------|-----------|-----------|
| **3순위 Gemini 생존** | `gemini-2.5-pro` → **404 "no longer available to new users"** | **G7 확정 — 3순위는 이미 죽어 있음.** §4.1로 긴급 승격 |
| Gemini 대체 후보 | `gemini-pro-latest` TTFT 7.42s / `gemini-flash-latest` 5.02s / `gemini-3.5-flash` 3.82s (모두 스트리밍 정상) | `gemini-pro-latest` 채택(안정 별칭, pro 티어 동급) |
| Gemini 타임아웃 수단 | `request_options={'timeout': N}` → `DeadlineExceeded` 정상 발생 | §4.1에서 사용 |
| Haiku 전문 교정 소요 | 입력 1,960자 → 출력 1,671자 / **7.7초** | 5초 타임아웃은 **실답변에서 100% 실패**. §4.4 동적 타임아웃 근거 |
| OpenAI 교차벤더 tool-use | `ANALYZE_TOOL` 스키마 **무수정 변환** 성공. `gpt-4.1` 2.7s / `gpt-5.4-mini` 2.0s, `calculation_types=['severance']`·`monthly_wage=3000000`·`is_labor_related=True` 정상 추출 | FR-05 실현 가능성 확인. `gpt-4.1` 채택 |
| SDK 기본값 | `anthropic 0.120.2` / `openai 2.53.0` — `max_retries=2`, `read=600s` | §3.4 예산표 기준선 |

> **가장 큰 발견**: `CLAUDE.md`와 코드가 약속한 "Claude → OpenAI → Gemini 3단 폴백"은 실제로는 **2단**이다. Gemini 경로는 호출되는 즉시 404로 죽고, 이는 답변 생성(L3)과 인용 교정 2순위(L7b) 양쪽에 해당한다. 폴백 계측(FR-10)이 없었기 때문에 아무도 몰랐다 — G8이 G7을 가린 전형적 사례.

### 1.4 전후 흐름 (답변 생성 경로)

```
[현행]
Claude 실패(무응답) ──30s×재시도3 = ~91초 침묵──▶ OpenAI 시도 ──▶ Gemini(404 즉사)
        │                                              │
        └ 0청크 정상종료 → "성공" 처리 → 빈 답변 전송   └ 첫청크 후 끊김 → 침묵 + 면책고지 + 저장 + 게시판 노출
                                                          (프론트는 60초에 이미 abort)

[설계]
Claude 시도(read 20s, retries 0)
   ├ 실질 청크 수신 ─▶ 정상 스트리밍 ─▶ outcome.provider="Claude"
   ├ 첫 청크 전 실패/타임아웃 ─▶ ("OpenAI","") 하트비트 yield ─▶ OpenAI 시도 ─▶ (실패 시) Gemini
   ├ 0청크·공백만 정상종료 ─▶ empty_providers 기록 ─▶ 동일하게 다음 벤더 전환   ← FR-01
   └ 실질 청크 후 실패 ─▶ outcome.truncated=True ─▶ 절단 고지 + metadata.truncated + 게시판 제외  ← FR-02
최악 25s마다 하트비트 → 무이벤트 구간 ≤ 25초 (프론트 60초 한계 대비 안전)          ← FR-03
```

---

## 2. 확정된 설계 결정 (Plan §8 대응)

| # | 결정 사항 | 확정 | 근거 |
|---|-----------|------|------|
| D1 | 3순위 Gemini 존치 여부 | **존치 + 모델 교체**(`gemini-pro-latest`) | 실측상 대체 모델이 정상 동작. 제거보다 복구가 싸고, 2단→3단 회복은 실질 가용성 이득 |
| D2 | Gemini SDK 마이그레이션 | **현행 `google-generativeai` 유지** | 신모델이 레거시 SDK에서 정상 동작 확인. 폴백 3순위를 위해 의존성 교체는 과투자. `google-genai` 이전은 후속 과제로 기록 |
| D3 | 답변 경로 재시도 정책 | **`max_retries=0` + 벤더 전환** | 원칙 P2. 3벤더 = 이미 3번의 기회 |
| D4 | 전환 하트비트 전달 방식 | **`(provider, "")` 빈 텍스트 센티널** | 2-튜플 규약 보존(P4) → `test_abuse_guard.py` 무변경. 3-튜플 변경은 기존 스텁을 깨뜨림 |
| D5 | 의도분석 폴백 모델 | **`gpt-4.1`** (env `INTENT_FALLBACK_MODEL`) | 비추론 모델 — reasoning 토큰이 한도를 잠식하는 함정 회피. 실측 2.7초로 12초 예산 내 |
| D6 | 교정 타임아웃 방식 | **입력 길이 비례 동적** + 단계 전체 예산 상한 | 고정값은 답변 길이 편차(1,000~8,000자)를 감당 못 함. 실측 7.7초/1,960자가 기울기 근거 |
| D7 | 절단 답변의 면책 고지 | **유지**(제거하지 않음) + 절단 고지 별도 부착 | 면책 고지는 법적 필요. 절단 사실은 별도 문구로 명시 |
| D8 | 절단 답변의 인용 교정 | **수행함** | 잘린 답변에도 환각 판례는 남는다. 정확성 > 지연. 단계 예산 상한(§4.4) 안에서 수행 |
| D9 | 계측 저장소 | `qa_conversations.metadata` 재사용 | 스키마 마이그레이션 0. `guard_flag` 선례 |
| D10 | 게시판 제외 방식 | `_apply_guard_filter`/`_drop_flagged` 확장 | 기존 이중 방어(PostgREST 필터 + Python 후처리) 구조 그대로 재사용 |

---

## 3. Wave A — 조용한 실패 제거 (FR-01 ~ FR-04)

### 3.1 FR-01 · FR-02 · FR-03: `_stream_answer` 상태 머신 재구성

**신규 결과 객체** (`app/core/pipeline.py`)

```python
@dataclass
class AnswerOutcome:
    """답변 생성 결과 메타 — 호출부가 저장·고지 판단에 사용 (FR-10 계측 원천)."""
    provider: str | None = None            # 실질 텍스트를 낸 제공자
    attempts: list[str] = field(default_factory=list)
    empty_providers: list[str] = field(default_factory=list)  # 0자 반환 제공자
    truncated: bool = False                # 실질 청크 후 스트림 중단
    error: str | None = None
```

**재구성된 제너레이터**

```python
def _stream_answer(messages, system, config, outcome: AnswerOutcome | None = None):
    """Claude → OpenAI → Gemini 폴백 스트리밍.

    Yields: (provider, text) — text가 빈 문자열이면 **전환 하트비트**(내용 없음).
            호출부는 빈 텍스트를 ping으로 변환해 프론트 idle 타이머를 리셋한다 (FR-03).
    Raises: RuntimeError — 모든 제공자가 실패하거나 전부 빈 응답일 때 (FR-01)
    """
    outcome = outcome if outcome is not None else AnswerOutcome()
    last_error = None

    for idx, (name, stream_fn) in enumerate(_answer_providers(config)):
        if idx:                                  # 2순위부터: 전환 하트비트 (FR-03)
            yield (name, "")
        outcome.attempts.append(name)
        chars = 0
        pending: list[str] = []                  # 첫 실질 청크 이전의 공백 청크 보류
        try:
            for text in stream_fn(messages, system, config):
                if not chars:
                    if not text.strip():
                        pending.append(text)     # 아직 실질 텍스트 없음 — 전송 보류
                        continue
                    outcome.provider = name
                    for p in pending:
                        yield (name, p)
                    pending.clear()
                chars += len(text.strip())
                yield (name, text)
        except Exception as e:
            if chars:                            # 실질 청크 후 실패 → 절단 (FR-02)
                outcome.truncated = True
                logger.warning("%s 스트리밍 중 절단 (부분 응답 유지): %s", name, e)
                return
            logger.warning("%s 답변 생성 실패, 다음 제공자로 전환: %s", name, e)
            last_error = e
            continue
        if chars:
            return                               # 정상 완료
        # FR-01: 예외 없이 0자 종료 → 실패로 승격하고 다음 제공자로
        outcome.empty_providers.append(name)
        logger.warning("%s 빈 응답(실질 0자) — 다음 제공자로 전환", name)
        last_error = last_error or RuntimeError(f"{name} returned empty response")

    outcome.error = str(last_error) if last_error else "no provider available"
    raise RuntimeError(f"모든 AI 서비스 연결 실패: {last_error}")
```

**핵심 변경 3가지**

1. `started` 불리언 → `chars`(실질 문자 수). "예외 없이 0자 종료"가 더 이상 성공이 아니다 (G1)
2. `pending` 버퍼 — 공백만 내다가 죽은 제공자의 공백이 프론트로 새지 않는다. 폴백 답변 앞에 빈 줄이 붙는 오염 제거
3. `yield (name, "")` — 전환 시점에 내용 없는 튜플을 흘려 호출부가 하트비트를 낼 수 있게 (G3)

> **P4 검증**: `test_abuse_guard.py:547`의 스텁 `lambda *a, **kw: iter([("Claude", "테스트 답변입니다.")])`은 ① 추가된 `outcome` 인자를 `**kw`가 흡수하고 ② 2-튜플·비어있지 않은 텍스트라 **무변경으로 계속 통과**한다.

**제공자 목록 분리** (기존 인라인 로직을 함수로)

```python
def _answer_providers(config) -> list[tuple[str, callable]]:
    providers = [("Claude", _stream_claude), ("OpenAI", _stream_openai)]
    if config.gemini_api_key:
        providers.append(("Gemini", _stream_gemini))
    primary = os.getenv("ANSWER_PROVIDER", "").strip().lower()
    if primary:
        providers.sort(key=lambda p: p[0].lower() != primary)
    return providers
```

### 3.2 FR-02: 호출부 — 절단의 정직한 처리

`pipeline.py:1766-1793` 교체:

```python
full_text = ""
used_provider = None
outcome = AnswerOutcome()
try:
    ...  # system_prompt 조립 (기존과 동일)
    for provider, text in _stream_answer(messages, system_prompt, config, outcome):
        if not text:                       # 전환 하트비트 — 내용 없음 (FR-03)
            yield {"type": "ping"}
            continue
        if not used_provider:
            used_provider = provider
            if provider != "Claude":
                yield {"type": "status", "text": fallback_note}   # 기존 문구 유지
        full_text += text
        yield {"type": "chunk", "text": text}
except RuntimeError:
    yield {"type": "error", "text": "모든 AI 서비스에 연결할 수 없습니다. 잠시 후 다시 시도해주세요."}
    yield {"type": "done"}
    return

# 6-0b. 절단 고지 (FR-02) — 면책 고지보다 먼저 붙여 순서를 고정
if outcome.truncated:
    _TRUNCATED = (
        "\n\n---\n\n"
        "⚠️ 답변 생성이 중간에 중단되었습니다. 위 내용은 완결된 답변이 아니므로, "
        "같은 질문을 다시 보내주시면 처음부터 다시 답변드리겠습니다."
    )
    full_text += _TRUNCATED
    yield {"type": "chunk", "text": _TRUNCATED}
```

**저장·노출 게이팅** (`pipeline.py:1882` 부근):

```python
conv_metadata: dict = {"has_attachments": has_attachments}
if guard_flag:
    conv_metadata["guard_flag"] = guard_flag
if outcome.truncated:
    conv_metadata["truncated"] = True          # 게시판 노출 제외 키 (FR-02)
conv_metadata["llm"] = _llm_meta(outcome)      # FR-10 계측 (§5.1)
```

> 면책 고지(`_DISCLAIMER`)는 **그대로 유지**한다(D7). 절단 고지가 그 앞에 붙어 "잘렸다"는 사실이 먼저 읽히고, 법적 면책은 변함없이 보장된다.

**게시판 제외** (`api/index.py`) — 기존 이중 방어 확장:

```python
_PUBLIC_EXCLUDE_KEYS = ("guard_flag", "truncated")   # metadata에 이 키가 있으면 공개 제외

def _apply_guard_filter(query, apply_filter: bool = True):
    """⚠️ qa_conversations 전용 — board_posts에는 metadata 컬럼이 없어 400이 난다."""
    if not apply_filter:
        return query
    for key in _PUBLIC_EXCLUDE_KEYS:
        query = query.is_(f"metadata->>{key}", "null")
    return query

def _drop_flagged(rows):
    out = []
    for row in rows or []:
        meta = row.get("metadata")
        if isinstance(meta, dict) and any(meta.get(k) for k in _PUBLIC_EXCLUDE_KEYS):
            continue
        out.append(row)
    return out
```

> `board_posts` 미적용 원칙은 불변 — `_apply_guard_filter` docstring 경고를 그대로 승계한다. `api/index.py:1056` 부근의 상세 조회 경로(`metadata` select + 인라인 검사)도 `_PUBLIC_EXCLUDE_KEYS`를 쓰도록 통일한다.

### 3.3 FR-03: 전환 지연 상한

```python
def _stream_claude(messages, system, config):
    timeout = httpx.Timeout(connect=CONNECT_TIMEOUT, read=ANSWER_READ_TIMEOUT,
                            write=ANSWER_READ_TIMEOUT, pool=CONNECT_TIMEOUT)
    with config.claude_client.with_options(
        timeout=timeout, max_retries=ANSWER_MAX_RETRIES      # ← 0 (D3)
    ).messages.stream(model=CLAUDE_MODEL, max_tokens=ANSWER_MAX_TOKENS, ...) as stream:
        ...

def _stream_openai(messages, system, config):
    stream = config.openai_client.with_options(
        timeout=httpx.Timeout(connect=CONNECT_TIMEOUT, read=ANSWER_READ_TIMEOUT,
                              write=ANSWER_READ_TIMEOUT, pool=CONNECT_TIMEOUT),
        max_retries=ANSWER_MAX_RETRIES,
    ).chat.completions.create(..., max_completion_tokens=ANSWER_MAX_TOKENS, stream=True)
```

**범위 한계 (명시적 비목표)**: `read` 타임아웃은 "바이트가 오지 않는 상황"만 잡는다. 서버가 200 + SSE 하트비트만 계속 보내고 텍스트를 주지 않는 병리적 케이스는 wall-clock 데드라인이 필요하고, 이는 블로킹 제너레이터를 스레드로 감싸야 한다. 서버리스에서 버려진 스레드가 남는 위험이 이득보다 크다고 판단해 **본 사이클 범위에서 제외**한다(후속 과제 기록).

### 3.4 FR-04: 타임아웃·재시도 예산 단일 출처

`app/config.py`에 신설:

```python
# ── LLM 타임아웃·재시도 예산 (llm-fallback-hardening) ─────────────────────────
# 재시도보다 벤더 전환이 빠르고 안전하다(설계 원칙 P2) — 임계경로는 retries=0.
# 값 변경 시 design §3.4 예산표를 함께 갱신할 것: 최악 누적이 vercel.json
# maxDuration(300초)과 프론트 idle(60초)을 동시에 만족해야 한다.
CONNECT_TIMEOUT       = 5.0
ANSWER_READ_TIMEOUT   = float(os.getenv("ANSWER_READ_TIMEOUT", "20"))
ANSWER_MAX_RETRIES    = int(os.getenv("ANSWER_MAX_RETRIES", "0"))
ANSWER_MAX_TOKENS     = 8192          # 교정 한도(§4.4)와 묶여 있음 — 한쪽만 낮추지 말 것
INTENT_TIMEOUT        = 12.0          # 현행 유지
INTENT_FALLBACK_TIMEOUT = 10.0
EXTRACT_TIMEOUT       = 10.0          # 현행 유지
CRITICAL_MAX_RETRIES  = 0             # analyzer/extract/decomposer/self_rag 공통
CITATION_STAGE_BUDGET = float(os.getenv("CITATION_STAGE_BUDGET", "60"))  # 교정 단계 전체 상한
```

**예산표 — 현행 vs 설계**

| ID | 호출 | 현행 (실효) | 설계 | 최악 소요 |
|----|------|-------------|------|----------:|
| L1 | Claude 답변 | c5/r30 × retries 3 ≈ **105s** | c5/r20 × 1 | 25s |
| L2 | OpenAI 답변 | 미지정 → **600s** × 3 | c5/r20 × 1 | 25s |
| L3 | Gemini 답변 | **무제한**(+404 즉사) | `request_options` 25s × 1 | 25s |
| L4 | `analyze_intent` | 12s × 3 ≈ 36s | 12s × 1 | 12s |
| L4b | OpenAI 폴백 분석 (신규) | — | 10s × 1 (실측 2.7s) | 10s |
| L5 | `_extract_params` | 10s × 3 ≈ 30s | 10s × 1 | 10s |
| L6 | decomposer / self_rag | 3s × 3 ≈ 9s | 3s × 1 | 3s |
| L7 | 인용 교정 3벤더 | 5s / 무제한 / 600s | 동적(§4.4) + **단계 예산 60s** | 60s |
| L8 | micro_polish | **2s**(실측상 항상 실패) | 동적 + 잔여 예산 ≥ 15s일 때만 | 20s |

**최악 경로 누적** (전 벤더 실패 + 환각 3건 이상):

```
이해   L4(12) + L4b(10) + L5(10)          =  32s
검색   RAG·법령 API (기존 DB-6 예산)       ≈  30s
답변   L1(25) + L2(25) + L3(25)           =  75s
교정   L7 단계 예산(60) + L8(20)           =  80s
저장   Supabase + 첨부 (ping으로 보호)      ≈  20s
────────────────────────────────────────────────
합계                                        ≈ 237s  < 300s ✅
무이벤트 최대 구간 = 답변 벤더 1회분 25s     < 60s  ✅
```

---

## 4. Wave B — 벤더 단일 장애점 해소 (FR-05 ~ FR-08)

### 4.1 FR-08 (긴급): 죽은 3순위 복구

`app/config.py`:

```python
- GEMINI_MODEL = "gemini-2.5-pro"
+ # 2026-08-06 실측: gemini-2.5-pro는 404("no longer available to new users")로
+ # 3순위 폴백이 통째로 죽어 있었다. gemini-pro-latest는 스트리밍 정상(TTFT 7.4s).
+ GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-pro-latest")
```

`pipeline.py::_stream_gemini` — 타임아웃 부여:

```python
response = model.generate_content(
    contents, stream=True,
    request_options={"timeout": ANSWER_READ_TIMEOUT + CONNECT_TIMEOUT},   # 실측 검증됨
)
```

`citation_validator.py`의 교정 2순위 Gemini도 동일 모델 상수를 쓰도록 통일한다(현재 `"gemini-2.5-pro"` 하드코딩 — 같은 404를 맞고 있다).

> 이 항목은 **가장 작고 가장 효과가 큰 변경**이다. Wave A보다 먼저 착수해 단독 배포해도 좋다.

### 4.2 FR-05: 의도분석 교차벤더 폴백

**구조 — 후처리 로직을 단일 출처로 추출**

현재 `analyzer.py:155-197`의 후처리(extracted 구성 → 날짜 보정 → 숫자 범위 검증 → `AnalysisResult` 조립)는 Claude 응답 루프 안에 인라인으로 박혀 있다. 이를 벤더 중립 함수로 뽑아 **두 벤더가 같은 코드를 통과**하게 한다(스키마 드리프트 방지, Plan 리스크 대응).

```python
# app/core/analyzer.py
def _build_analysis_result(inp: dict) -> AnalysisResult:
    """tool 입력 dict → AnalysisResult. 벤더 무관 — Claude·OpenAI 양쪽이 공유."""
    # (기존 155-197 로직 그대로 이동: info_keys 필터 → _correct_date_year →
    #  _validate_numeric_params → AnalysisResult(...))

def analyze_intent(question, history, config, summary="") -> AnalysisResult:
    messages = _build_messages(question, history, summary)
    system_prompt = ANALYZER_SYSTEM.format(today=date.today().isoformat())
    try:
        inp = _analyze_claude(messages, system_prompt, config)
    except Exception as e:
        if not INTENT_FALLBACK_ENABLED:
            raise
        logger.warning("의도분석 Claude 실패 — OpenAI 폴백 시도: %s", e)
        inp = _analyze_openai(messages, system_prompt, config)   # 실패 시 예외 전파
    return _build_analysis_result(inp) if inp else AnalysisResult(question_summary=question)
```

**OpenAI 어댑터** — 신규 `app/core/llm_fallback.py`

> ⚠️ **순환 import 주의**: `pipeline.py`가 `analyzer.py`를 import하므로, analyzer가 pipeline의 `_flatten_content`를 가져오면 순환이 된다. 어댑터와 콘텐츠 평탄화 헬퍼는 **양쪽이 의존할 수 있는 신규 모듈**에 둔다.

```python
# app/core/llm_fallback.py
def anthropic_tool_to_openai(tool: dict) -> dict:
    """Anthropic tool 스펙 → OpenAI function 스펙. input_schema는 무수정 재사용."""
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool["input_schema"],
        },
    }

def flatten_content(content) -> str:
    """멀티모달 블록 리스트를 텍스트로 평탄화 (이미지 블록은 탈락)."""
    ...

def call_openai_tool(client, model, system, messages, tool, *, timeout, max_tokens) -> dict:
    resp = client.with_options(timeout=timeout, max_retries=0).chat.completions.create(
        model=model,
        messages=[{"role": "developer", "content": system}]
                 + [{"role": m["role"], "content": flatten_content(m["content"])} for m in messages],
        tools=[anthropic_tool_to_openai(tool)],
        tool_choice={"type": "function", "function": {"name": tool["name"]}},
        # 비추론 모델(gpt-4.1)이라 reasoning 토큰 잠식이 없다. 추론 모델로 교체 시
        # 이 한도를 크게 올려야 tool_call이 빈 채로 끊기지 않는다(project 메모리 참조).
        max_completion_tokens=max_tokens,
    )
    calls = resp.choices[0].message.tool_calls
    if not calls:
        raise RuntimeError("OpenAI tool_call 미반환")
    return json.loads(calls[0].function.arguments)
```

**설정** (`app/config.py`):

```python
INTENT_FALLBACK_ENABLED = os.getenv("INTENT_FALLBACK_ENABLED", "true").lower() != "false"
INTENT_FALLBACK_MODEL   = os.getenv("INTENT_FALLBACK_MODEL", "gpt-4.1")
```

**실측 검증 결과** (설계 시점): `ANALYZE_TOOL`(37개 property, required 3개)을 무수정 변환해 `gpt-4.1`로 강제 호출 → 2.7초에 `requires_calculation=True`, `calculation_types=['severance']`, `monthly_wage=3000000`, `is_labor_related=True` 정상 반환. 12초 예산 내에서 여유롭다.

### 4.3 FR-06: 스코프 게이트 생존 확인

`pipeline.py:1317`의 `if guard_ctx and analysis is not None:` 조건은 **변경하지 않는다**. FR-05로 `analysis`가 OpenAI 경유로도 채워지므로, Anthropic 장애 중에도 `is_labor_related`가 살아 게이트가 동작한다. 양쪽 벤더가 모두 실패하면 `analysis is None` → 기존대로 게이트 skip(fail-open) — `chatbot-security` FR-05 규약 불변(원칙 P6).

**검증 방법**: §5.2 테스트에서 Claude 클라이언트만 예외를 던지도록 주입하고, ① `calculation_types`가 채워지는지 ② `scope_gate_decision`이 호출되는지를 확인한다.

### 4.4 FR-07: 인용 교정 타임아웃 정합 + 단계 예산

**동적 타임아웃** — 실측 기울기(1,960자 / 7.7초)에 안전계수 1.5를 적용:

```python
# app/core/citation_validator.py
def _rewrite_timeout(text_len: int) -> float:
    """전문 재생성 소요는 입력 길이에 비례한다.
    실측(2026-08-06): 1,960자 입력 → 출력 1,671자 / 7.7초 (claude-haiku-4-5).
    → 약 250자/초. 안전계수 1.5 적용 후 [12, 40]초로 클램프.
    """
    return min(40.0, max(12.0, text_len / 165))
```

| 답변 길이 | 현행 타임아웃 | 실측 소요(추정) | 설계 타임아웃 |
|----------:|-------------:|---------------:|-------------:|
| 2,000자 | 5s ❌ | ~7.9s | 12s ✅ |
| 4,000자 | 5s ❌ | ~15.7s | 24s ✅ |
| 6,000자 | 5s ❌ | ~23.6s | 36s ✅ |
| 8,000자 | 5s ❌ | ~31.4s | 40s ✅ |

**단계 예산 상한** — 3벤더 × 40초가 누적되면 300초 한계를 위협하므로 데드라인을 둔다:

```python
def correct_hallucinated_citations(..., deadline: float | None = None) -> str | None:
    deadline = deadline or (time.monotonic() + CITATION_STAGE_BUDGET)
    per_call = _rewrite_timeout(len(response_text))
    for vendor in (_try_haiku, _try_gemini, _try_openai):
        remaining = deadline - time.monotonic()
        if remaining < 5:                       # 남은 예산으로는 의미 있는 시도 불가
            logger.warning("인용 교정 예산 소진 — 남은 벤더 생략")
            break
        result = vendor(prompt, timeout=min(per_call, remaining))
        if result:
            return result
    return None
```

`micro_polish`도 동일 함수를 쓰되, **잔여 예산 15초 이상일 때만** 발동한다(퇴고는 품질 보정이지 정확성 항목이 아니므로 예산 경쟁에서 후순위).

**하트비트 추가** — 교정은 최대 40초가 걸리는데 그동안 SSE 이벤트가 없다. `citation_check["hallucinated"]`가 참일 때 교정 호출 **직전에** `yield {"type": "ping"}`을 넣어 프론트 idle 타이머를 리셋한다.

> **커플링 경고 유지**: `ANSWER_MAX_TOKENS`(8192)와 교정 호출의 `max_tokens`는 묶여 있다. 교정 한도를 낮추면 `len(text) > len(response_text) * 0.7` 가드에 걸려 교정이 통째로 폐기되고 환각 판례가 그대로 남는다. 두 값은 항상 함께 바꾼다.

---

## 5. Wave C — 관측·검증 (FR-10 ~ FR-13)

### 5.1 FR-10: 폴백 계측

```python
def _llm_meta(outcome: AnswerOutcome, citation: dict | None = None) -> dict:
    """qa_conversations.metadata.llm — 스키마 변경 없음(D9)."""
    meta = {"provider": outcome.provider, "attempts": outcome.attempts}
    if outcome.empty_providers:
        meta["empty"] = outcome.empty_providers        # 빈 응답을 낸 제공자
    if len(outcome.attempts) > 1:
        meta["fallback"] = True
    if outcome.truncated:
        meta["truncated"] = True
    if citation:
        meta["citation_fixed"] = citation.get("fixed")  # 교정 성공/실패
    return meta
```

저장 형태 예시:
```json
{"has_attachments": false,
 "llm": {"provider": "OpenAI", "attempts": ["Claude", "OpenAI"], "fallback": true,
         "empty": ["Claude"], "citation_fixed": false}}
```

구조화 로그도 함께 남긴다(Vercel 로그 검색용):
```python
logger.info("llm_outcome provider=%s attempts=%s empty=%s truncated=%s",
            outcome.provider, outcome.attempts, outcome.empty_providers, outcome.truncated)
```

관리자 대시보드 노출은 **선택 항목**으로 남긴다(Plan FR-10 "노출은 선택"). 초기에는 Supabase 쿼리로 충분하다:
```sql
select metadata->'llm'->>'provider' p, count(*)
from qa_conversations where created_at > now() - interval '7 days' group by 1;
```

### 5.2 FR-11: 오프라인 회귀 테스트 — 신규 `test_llm_fallback.py`

**API 키 불요** 원칙(기존 오프라인 스위트 관례)을 지키기 위해 가짜 스트림 함수를 주입한다. `_answer_providers`를 함수로 분리한 덕에 monkeypatch 지점이 명확하다.

| # | 시나리오 | 주입 | 기대 |
|---|----------|------|------|
| T1 | 1순위 0청크 정상종료 | Claude=빈 이터레이터, OpenAI=정상 | OpenAI 텍스트 수신, `empty_providers==["Claude"]`, `provider=="OpenAI"` |
| T2 | 1순위 공백만 반환 | Claude=`["  ", "\n"]`, OpenAI=정상 | 프론트로 공백 미전송(청크 오염 0), OpenAI 텍스트만 |
| T3 | 첫 청크 전 예외 | Claude=즉시 raise | 전환 하트비트 `("OpenAI","")` 1회 관측, OpenAI 결과 |
| T4 | 실질 청크 후 예외 | Claude=`["안녕"]` 후 raise | `truncated==True`, 폴백 **미시도**(부분 응답 유지 규약), 절단 고지 부착 |
| T5 | 전 제공자 실패 | 전부 raise | `RuntimeError` 발생 → 파이프라인이 `error` 이벤트 방출 |
| T6 | 전 제공자 빈 응답 | 전부 빈 이터레이터 | `RuntimeError`(FR-01 — 조용한 성공 금지) |
| T7 | 절단 대화 게시판 제외 | `metadata={"truncated": True}` 행 | `_drop_flagged`가 제외 |
| T8 | tool 스키마 변환 | `ANALYZE_TOOL` | `anthropic_tool_to_openai` 결과가 `function.parameters == input_schema`, required 보존 |

T1~T6은 `_stream_answer`를 직접 호출해 검증하고, T4의 절단 고지·저장 게이팅은 `process_question`을 가짜 config로 돌려 이벤트 시퀀스를 검사한다(`test_abuse_guard.py`의 파이프라인 스텁 패턴 재사용).

`.github/workflows/tests.yml`에 등록:
```yaml
- run: python3 test_llm_fallback.py
```

### 5.3 FR-12: 장애 주입 양성 검증 체크리스트

`chatbot-security`의 "fail-open은 조용하다 → 배포 후 양성 검증 필수" 교훈을 승계한다. 코드가 아니라 **절차** 산출물이다.

| # | 주입 방법 | 기대 관측 |
|---|-----------|-----------|
| V1 | `ANTHROPIC_API_KEY`를 무효값으로 두고 로컬 파이프라인 1회 실행 | 답변이 OpenAI로 생성됨 + `계산기 실행` 로그 존재(FR-05 동작) + `metadata.llm.fallback==true` |
| V2 | `ANSWER_PROVIDER=gemini`로 고정 실행 | Gemini 경로로 실제 답변 수신(FR-08 복구 확인) |
| V3 | `ANSWER_READ_TIMEOUT=0.1` 설정 후 실행 | 전환 하트비트(ping) 관측 + 최종적으로 어느 벤더든 응답 or 명시적 error |
| V4 | 프로덕션 배포 후 임의 질문 1건 → Supabase 조회 | `metadata.llm.provider`가 실제로 기록되는지(계측 양성 확인) |

> V1~V3은 로컬에서 `benchmark_pipeline.py` 또는 `compare_llm_models.py` 하네스를 재사용한다.

### 5.4 FR-13: 문서 정합

| 파일 | 변경 |
|------|------|
| `.env.example` | `ANSWER_PROVIDER`(1순위 고정 — 장애 시 무배포 롤백), `OPENAI_CHAT_MODEL`, `GEMINI_MODEL`, `INTENT_FALLBACK_ENABLED`/`_MODEL`, `ANSWER_READ_TIMEOUT`, `CITATION_STAGE_BUDGET` 추가 + 용도 주석 |
| `CLAUDE.md` | "Claude Sonnet 4.6 (primary)" → 실제 `claude-sonnet-5` / Gemini 모델명 정정 / **폴백 규약 신설**: 빈 응답=실패, 절단=metadata 기록+게시판 제외, 타임아웃 단일 출처가 `app/config.py`임을 명시 |
| `docs/` | 본 설계 §3.4 예산표를 값 변경 시 함께 갱신한다는 주석을 `config.py`에 인라인 기재 |

---

## 6. 변경 대상 파일

```
신설: app/core/llm_fallback.py        (tool 스펙 변환 · 콘텐츠 평탄화 · OpenAI tool 호출 — 순환 import 회피)
      test_llm_fallback.py            (T1~T8 오프라인 회귀)
수정: app/config.py                   (타임아웃·재시도·모델 상수 단일 출처, GEMINI_MODEL 교체)
      app/core/pipeline.py            (AnswerOutcome, _answer_providers, _stream_answer 재구성,
                                       _stream_openai/_stream_gemini 타임아웃, 절단 고지·계측·ping)
      app/core/analyzer.py            (_build_analysis_result 추출 + OpenAI 폴백 분기)
      app/core/citation_validator.py  (동적 타임아웃, 단계 예산, Gemini 모델 상수화)
      api/index.py                    (_PUBLIC_EXCLUDE_KEYS로 truncated 제외 확장)
      .env.example, CLAUDE.md         (FR-13)
      .github/workflows/tests.yml     (신규 스위트 등록)
```

> `app/core/*.py` 신설 파일은 **반드시 git 커밋**할 것 — 미추적 시 Vercel import 500(CLAUDE.md 규약).

---

## 7. 구현 순서 (Do 단계 체크리스트)

**Wave 0 — 긴급 단독 배포 가능** (가장 작고 효과 큼)
- [ ] `GEMINI_MODEL` → `gemini-pro-latest`, `citation_validator`의 하드코딩 모델도 상수화 (FR-08)
- [ ] `_stream_gemini`에 `request_options` 타임아웃 부여 (FR-04 일부)

**Wave A — 조용한 실패 제거**
- [ ] `app/config.py` 타임아웃·재시도 상수 신설 (FR-04)
- [ ] `AnswerOutcome` + `_answer_providers` + `_stream_answer` 재구성 (FR-01·02·03)
- [ ] `_stream_claude`/`_stream_openai` 타임아웃·재시도 적용 (FR-03·04)
- [ ] 호출부: 빈 텍스트 → ping, 절단 고지, `metadata.truncated` (FR-02·03)
- [ ] `api/index.py` `_PUBLIC_EXCLUDE_KEYS` 확장 (FR-02)
- [ ] `test_llm_fallback.py` T1~T7 작성·통과 (FR-11)

**Wave B — 벤더 단일 장애점 해소**
- [ ] `app/core/llm_fallback.py` 신설 + T8 통과 (FR-05)
- [ ] `analyzer.py` `_build_analysis_result` 추출 → 두 벤더 공유 (FR-05)
- [ ] OpenAI 폴백 분기 + `INTENT_FALLBACK_*` 설정 (FR-05)
- [ ] 스코프 게이트 생존 테스트 (FR-06)
- [ ] 교정 동적 타임아웃 + 단계 예산 + 교정 전 ping (FR-07)

**Wave C — 관측·문서**
- [ ] `_llm_meta` 계측 + 구조화 로그 (FR-10)
- [ ] `.env.example` · `CLAUDE.md` 갱신 (FR-13)
- [ ] 장애 주입 V1~V4 실행 및 결과 기록 (FR-12)
- [ ] 회귀 확인: `test_wage_golden` / `test_pipeline_wiring` / `test_offline_units` / `test_abuse_guard`

---

## 8. 리스크와 롤백

| 리스크 | 완화 | 즉시 롤백 수단 |
|--------|------|----------------|
| `max_retries=0`이 일시적 429/5xx에 취약 | 3벤더 전환이 재시도를 대체. 전환이 재시도보다 빠름 | `ANSWER_MAX_RETRIES=1` |
| `read=20s`가 대형 컨텍스트의 TTFT를 끊음 | RAG 컨텍스트 포함 실측 TTFT는 LLM 단독 기준 수 초. 20초는 충분한 여유 | `ANSWER_READ_TIMEOUT=30` |
| 빈 응답 판정이 짧은 정상 답변을 오탐 | `strip()` 후 0자만 판정 — 1자라도 있으면 성공 | — |
| OpenAI 폴백 분석 품질이 Claude보다 낮음 | 폴백 전용(정상 경로 무변경). `test_pipeline_wiring` 골든 케이스로 회귀 확인 | `INTENT_FALLBACK_ENABLED=false` |
| 교정 타임아웃 상향이 응답 지연 증가 | 환각 감지 시에만 발동 + 단계 예산 60초 상한 + ping | `CITATION_STAGE_BUDGET=20` |
| `gemini-pro-latest` 별칭이 향후 또 교체됨 | 별칭이라 모델 EOL에 자동 추종. 그래도 FR-10 계측이 있으면 다음엔 즉시 안다 | `GEMINI_MODEL` env |
| `_PUBLIC_EXCLUDE_KEYS` 확장이 `board_posts`에 잘못 적용 | `_apply_guard_filter` docstring 경고 유지 + 호출부는 `qa_conversations` 전용 그대로 | — |
| 절단 고지가 프론트 렌더러와 충돌 | 신규 SSE 타입 없이 기존 `chunk`로만 전달 | — |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-08-06 | 초안 — `_stream_answer` 상태 머신, 타임아웃 예산표, 교차벤더 어댑터, 교정 단계 예산, 계측·테스트 설계. **설계 중 Gemini 3순위 404 사망 실측 확인**해 Wave 0으로 승격 | DrunkenZealnut |
