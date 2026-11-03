# llm-fallback-alert-blindspot Design Document

> **Summary**: 전 제공자 실패(파이프라인)·답변 중 예외(API)에서 **답변 없는 실패 행**을 `qa_conversations`에 남기고, `check_llm_fallback.py`에 "최근 12시간 내 실패 행 1건 → 알림" 규칙(R2)과 마지막 실사용 경과 표시를 더한다. DDL·Secret·새 테이블 없음.
>
> **Project**: laborconsult · **Author**: Claude(Fable 5.1) + 사용자 · **Date**: 2026-10-30 · **Status**: v0.3 (2026-11-03 PR #150 CodeRabbit 반영 — §4.2 ping 표현·§5.3 24h 창·§5.4 `last_ok`/'연속 실패'·§10 롤백)
> **Planning Doc**: `docs/01-plan/features/llm-fallback-alert-blindspot.plan.md`(§8 확정: U1 12h · U2 동일 저장 · U3 포함+표지 · U4 범위 밖)
> **Parent**: `docs/archive/2026-10/llm-fallback-alert/llm-fallback-alert.design.md`(R1·fail-closed·본문 비조회) · `docs/archive/2026-08/llm-fallback-hardening/`(`metadata.llm`·`AnswerOutcome`)

---

## 0. 설계 핵심(요약)

| 항목 | 결정 |
|---|---|
| 실패 행의 정체 | `qa_conversations` 행. `answer_text=""`, `metadata.failed=True`, `metadata.llm`은 **실패 전용 페이로드**(§3). 카테고리·세션·질문은 성공 시와 같은 함수로 만든다 |
| 기록 지점 | ① `pipeline.process_question`의 `except RuntimeError`(전 제공자 실패) ② `api/index.py` SSE GET·POST의 `except Exception`("답변 생성 실패") ③ 동기 `POST /api/chat`의 미처리 예외 — 셋 다 **`pipeline.record_failed_conversation()` 하나**를 부른다 |
| 비밀·본문 | 예외 **클래스명·HTTP 상태만**. 메시지 원문·토큰·키·URL 저장 금지. 감시는 `question_text`를 조회하지 않는다 |
| fail-open | 기록 실패는 WARNING 로그로 끝난다. 사용자에게 가는 `error`·`done`은 기록 성공 여부와 무관하게 그대로. **세 경로 모두 안내(`error`) → 기록 → `done`** — 기록은 PostgREST 3왕복(세션 조회·갱신/삽입·행 삽입)이고 설정 클라이언트 타임아웃이 기본 120초라 안내를 먼저 보낸다(Check M-1) |
| 게시판 | `storage.PUBLIC_EXCLUDE_KEYS += ("failed",)` — 필터·후처리·`dedupe_board` 검증 SQL이 자동 반영 |
| 감시 | `degraded()`에 `failed`; **R2** 실사용 `failed` 행이 `now − 12h` 이후 ≥ 1 → alert; R1(최근 3건 연속 저하) 유지; 요약에 마지막 실사용 경과·24h 실패 수; 상태 코드별 점검 힌트 |
| 관리자 | 통계 쿼리 무변경(포함). 상세 화면에 `metadata.failed`면 "답변 실패 · {error_class}" 표지. 목록 표지는 선택(§6) |
| 범위 밖 | 카나리·초기화 실패 기록·새 RPC/테이블·킬스위치(§9 D-5) |

---

## 1. Overview

### 1.1 Design Goals

1. 전면 장애(전 제공자 실패)가 **저장된 기록으로 남아** 기존 감시가 읽을 수 있게 한다.
2. 정상 경로(답변 성공)의 코드와 동작은 **한 줄도 바꾸지 않는다** — 실패 분기·API 예외 분기·감시 스크립트·제외 키만 바뀐다.
3. 저장소 변경 0(DDL·RPC·Secret 없음). 기존 anon INSERT 정책과 `metadata` JSONB를 그대로 쓴다.
4. 사용자 제약 유지: 토큰·키 비출력, 결제 없음, 제공자 키 폴백 경로 없음.

### 1.2 Design Principles

- **단일 초크포인트 재사용** — 저장은 `storage.save_conversation`(세션 보장·G-C 백스톱 포함)만 거친다. 실패 행도 같은 문을 지난다.
- **같은 사실은 같은 함수로** — 카테고리·synthetic 판정은 성공 경로와 실패 경로가 **같은 헬퍼**를 쓴다(복제하면 어긋난다 — 이 저장소의 반복 교훈).
- **감시 판정은 순수 함수** — `judge()`는 `now`를 인자로 받아 오프라인 테스트가 시각을 고정할 수 있게 한다.
- **감시는 fail-closed, 기록은 fail-open** — 선행 사이클 규약 그대로.

---

## 2. Architecture

### 2.1 데이터 흐름

```
사용자 질문 ─▶ _guard_chat_request ─▶ process_question
                                        │
                      ┌─────────────────┴──────────────────┐
                      │ 답변 성공                           │ 전 제공자 실패 (RuntimeError)
                      ▼                                     ▼
            save_conversation(정상 행)            yield error ─▶ yield ping
            metadata.llm = _llm_meta(...)         ─▶ record_failed_conversation(stage="answer")
                                                   ─▶ yield done
api/index.py event_generator ── except Exception ─▶ record_failed_conversation(stage="pipeline")
                                                   ─▶ _sse_error_events(...)
POST /api/chat ───────────────── except Exception ─▶ record_failed_conversation(stage="pipeline") ─▶ re-raise(500)

qa_conversations ◀── anon INSERT (기존 정책) ── 실패 행: answer_text="", metadata.failed=True

check_llm_fallback.py (6h cron) ── fetch_recent(…W 구간까지) ─▶ judge(now)
   R1: 최근 실사용 3건 연속 저하(failed 포함)  R2: now−12h 이후 실사용 failed ≥ 1  ─▶ exit 1 + 힌트
   요약: 마지막 실사용 경과 · 24h 실패 수 (알림 아님)

공개 게시판 ── _apply_guard_filter / _drop_flagged ── PUBLIC_EXCLUDE_KEYS(…,"failed") ─▶ 미노출
관리자 상세 ── select("*") ─▶ metadata.failed ─▶ "답변 실패 · error_class" 표지
```

### 2.2 변경 파일

| 파일 | 변경 | 비고 |
|---|---|---|
| `app/core/pipeline.py` | `AnswerOutcome.failures` 필드 · `_stream_answer`가 실패마다 `failures` 기록 · `_failure_llm_meta()` · `_category_for()`(기존 블록 추출) · `_synthetic_flag()`(기존 2줄 추출) · `record_failed_conversation()` · `except RuntimeError` 분기 배선 | 정상 경로 코드는 추출만(동작 동일) |
| `api/index.py` | SSE GET·POST `except Exception`와 동기 `/api/chat`에 헬퍼 호출(동기 경로에도 "답변 생성 실패(동기)" ERROR 로그) · `admin_conversations` 목록 표지 투영은 **보류**(PostgREST 별칭 투영 실측 없음) | import는 `from app.core.pipeline import record_failed_conversation` |
| `app/core/storage.py` | `PUBLIC_EXCLUDE_KEYS`에 `"failed"`(5종 → **6종**, `counsel`은 이미 있었다) | 단일 출처 |
| `check_llm_fallback.py` | `degraded()` · `judge(rows, window, now, fail_window)` · `fetch_recent` W 커버리지 · `render` R2·요약·힌트 · `--fail-window` | docstring 갱신 |
| `public/admin.html` | `openDetail`에 실패 표지(+ 목록 표지 선택) | HTML 주석에 내부 경로 금지(CLAUDE.md) |
| 테스트 | `test_llm_fallback.py`(T-F1~F8) · `test_llm_fallback_alert.py`(B1~B12, +B5b) · `test_offline_units.py`(키 6종) | 전부 오프라인 |
| 문서 | `CLAUDE.md`(폴백 감시 절·제외 키 "4종"→5종) · 워크플로 주석 · memory | — |

### 2.3 의존

| 구성 | 의존 | 용도 |
|---|---|---|
| `record_failed_conversation` | `save_conversation`·`ConversationRecord`·`classify_category`·`infer_calc_types`(이미 `pipeline.py`가 import) | 저장·분류 |
| `api/index.py` | `app.core.pipeline`(이미 `process_question` import) | 헬퍼 호출 — 순환 import 없음 |
| `check_llm_fallback.py` | `app.core.storage.make_supabase_client`만(Actions는 `supabase python-dotenv`만 설치) | 새 import 금지 — `datetime`·`json` 표준 라이브러리만 추가 |

---

## 3. Data Model — 실패 행

### 3.1 행 모양

```jsonc
// qa_conversations 한 행 (실패)
{
  "id": "<uuid>", "session_id": "<hex12>", "created_at": "…",
  "category": "<성공 시와 같은 classify_category 결과>",
  "question_text": "<질문 원문 — U2: 정상 대화와 동일 저장>",
  "answer_text": "",                       // 항상 빈 문자열
  "calculation_types": [],                  // 성공 시와 같은 calc_types (없으면 [])
  "metadata": {
    "has_attachments": false,
    "failed": true,                         // 게시판 제외 키 — True일 때만 기록(명시적 False 금지)
    "synthetic": true,                      // guard_ctx None·synthetic 요청·예약 접두사일 때만(기존 규약)
    "llm": {                                // 실패 전용 페이로드 (_failure_llm_meta)
      "failed": true,
      "stage": "answer",                    // "answer" = 전 제공자 실패 | "pipeline" = 답변 중 예외
      "provider": null,
      "attempts": ["Claude", "OpenAI", "Gemini"],   // stage=pipeline이면 [] 가능
      "empty": ["OpenAI"],                  // 있을 때만
      "failures": [                         // 제공자별 실패 — 클래스명·상태만
        {"provider": "Claude", "error_class": "AuthenticationError", "status": 401},
        {"provider": "OpenAI", "error_class": "AuthenticationError", "status": 401},
        {"provider": "Gemini", "error_class": "ResourceExhausted", "status": 429}
      ],
      "error_class": "ResourceExhausted",   // = failures[-1].error_class (감시·표지용 요약)
      "status": 429,                        // = failures[-1].status (없으면 키 생략)
      "transport": "gateway"                // direct | gateway (기존 _llm_meta와 같은 출처)
    }
  }
}
```

**없는 것(의도적):** `fallback`(성공이 없다), `model`, `truncated`, `citation_fixed`, `intent_provider`, `error`(메시지 원문), `law_api`(실패 시 집계 불완전), `rule_facts` 등 성공 전용 관측.

### 3.2 `AnswerOutcome` 확장

```python
@dataclass
class AnswerOutcome:
    ...  # 기존 필드 불변
    failures: list[dict] = field(default_factory=list)   # [{"provider","error_class","status"}]
```

`_stream_answer`는 두 지점에서 추가한다 — ① `except Exception as e` 중 `chars == 0`(실패 → 다음 제공자)에서 `_failure_entry(name, e)`, ② 빈 응답 승격에서 `{"provider": name, "error_class": "EmptyResponse", "status": None}`. 절단(`chars > 0`)은 실패가 아니라 기록하지 않는다(기존 `truncated`가 담당). `outcome.error`(메시지 문자열)는 기존 로그 용도로 남기되 **metadata에는 싣지 않는다**.

### 3.3 상태 코드 추출 `_status_of(exc) -> int | None`

순서: `exc.status_code`(anthropic·openai·cohere SDK 공통) → `exc.response.status_code`(httpx 계열) → `exc.code`가 `int`이면 그 값(google.api_core: `ResourceExhausted.code == 429`) → 없으면 `None`. 정수가 아니면 버린다(grpc enum 등, `bool`도 제외). 이 함수는 예외 **메시지를 읽지 않는다**. 본문 전체를 `try/except Exception → None`으로 감싼다 — `_stream_answer`의 폴백 전환 except 블록 안에서 불리므로 속성 접근 예외가 전환을 끊어서는 안 된다(Check L-1).

### 3.4 `_failure_llm_meta(outcome, exc, stage, transport) -> dict`

- `stage="answer"`: `attempts`·`empty`·`failures`는 `outcome`에서. `exc`(최종 RuntimeError)는 **클래스명도 쓰지 않는다** — 그 예외는 `_stream_answer`가 만든 포장이고 실제 원인은 `failures`에 있다. `failures`가 비어 있으면(제공자 목록이 비었던 경우) `error_class="NoProvider"`.
- `stage="pipeline"`: `attempts=[]`, `failures=[{"provider": None, "error_class": type(exc).__name__, "status": _status_of(exc)}]`.
- `error_class`/`status`는 `failures[-1]`에서 복사. `transport`는 `getattr(config, "transport", None)`.
- **키 화이트리스트**(`failed, stage, provider, attempts, empty, failures, error_class, status, transport`) 밖의 키를 만들지 않는다 — 테스트 T-F1이 집합을 고정한다.

---

## 4. 기록 경로

### 4.1 `record_failed_conversation(config, session, query, guard_ctx, *, stage, outcome=None, exc=None, has_attachments=False, analysis=None, params=None, use_analysis_params=False) -> str | None`

```
if config.supabase is None: return None            # 저장할 곳이 없다 — 정상 경로의 `if not config.supabase` 와 동치
try:
    calc_types, category = _category_for(query, analysis, params, use_analysis_params)
    metadata = {"has_attachments": bool(has_attachments), "failed": True,
                "llm": _failure_llm_meta(outcome, exc, stage, getattr(config, "transport", None))}
    if _synthetic_flag(guard_ctx): metadata["synthetic"] = True
    record = ConversationRecord(session_id=session.id, category=category, question_text=query,
                                answer_text="", calculation_types=calc_types or [], metadata=metadata)
    return save_conversation(config.supabase, record)   # 내부 try/except — 실패 시 None
except Exception as e:
    logger.warning("실패 행 기록 실패(stage=%s): %s", stage, type(e).__name__)   # 메시지 원문도 로그에 안 쓴다
    return None
```

- `_category_for()`는 기존 저장 구간의 "카테고리 결정" 블록(`calc_types`·`tool_type_for_category`·`infer_calc_types` 폴백·`classify_category`)을 **그대로 함수로 옮긴 것**이다. 성공 경로도 이 함수를 부른다(동작 동일, 회귀 T-F6). `analysis`가 `None`이면 `infer_calc_types(query)` 폴백으로 간다 — API 예외 경로가 그 경우다.
- `_synthetic_flag(guard_ctx)`는 기존 `guard_ctx is None or guard_ctx.synthetic` 2줄의 추출이다(G-A·G-B). G-C(예약 접두사)는 `save_conversation` 안에 이미 있다.
- 세션 스냅숏(`save_session_data`)은 **저장하지 않는다** — 답변이 없어 이력에 더할 것이 없다.
- 첨부 업로드는 하지 않는다(실패 행에 파일을 묶지 않는다).

### 4.2 파이프라인 — 전 제공자 실패 분기

```python
except RuntimeError:
    yield {"type": "error", "text": "모든 AI 서비스에 연결할 수 없습니다. 잠시 후 다시 시도해주세요."}
    yield {"type": "ping"}                                   # 저장 지연 동안 idle 타이머 리셋(정상 저장과 같은 관례)
    record_failed_conversation(config, session, query, guard_ctx, stage="answer", outcome=outcome,
                               has_attachments=has_attachments, analysis=analysis, params=params,
                               use_analysis_params=use_analysis_params)
    yield {"type": "done"}
    return
```

- 순서 `error → ping → 기록 → done`: 사용자 안내가 먼저 나가고, `done`은 저장(PostgREST 3왕복)만큼 늦어진다(정상 경로의 저장 지연과 같은 크기). 프런트는 `error`를 안내 요소로 그리고 `done`에서 전송 잠금을 푼다. `ping`은 idle(60초) 타이머를 **한 번 리셋**해 저장에 60초 여유를 줄 뿐이다 — 그 이상 걸리면 프런트가 시간 초과 안내를 덧붙이고 끊는데, 이것은 정상 경로의 `save_conversation`(역시 `done` 앞)과 같은 노출이라 이 사이클은 따로 막지 않는다(CodeRabbit #150 — 저장 타임아웃 단축은 정상 경로와 함께 후속).
- 이 분기는 `GatewayAuthError`·`UnsupportedModelError`(둘 다 `RuntimeError` 하위)가 `_stream_answer` 밖에서 났을 때도 잡는다 — 그때 `outcome.failures`가 비어 `error_class="NoProvider"`가 된다(원인은 Vercel 로그). 설계상 허용하되 요약 힌트가 "로그 확인"으로 안내한다.

### 4.3 API — 답변 중 예외·동기 경로

- SSE GET/POST `event_generator`의 `except Exception as e`: **`error` → 기록 → `done`**. `_sse_error_events`는 `error`+`done` 두 이벤트를 내는 제너레이터라 `gen = _sse_error_events(...); yield next(gen); record_failed_conversation(config, session, message, guard_ctx, stage="pipeline", exc=e, has_attachments=bool(parsed_attachments)); yield from gen`으로 쪼갠다. 기록은 PostgREST 3왕복(`ensure_session` 조회·갱신/삽입 + 행 삽입)이고 `AppConfig.from_env()`의 Supabase 클라이언트는 타임아웃이 기본 120초다 — 기록을 먼저 하면 DB가 느릴 때 사용자가 안내 대신 프런트 idle(60초) 타임아웃을 본다(Check M-1). `done`만 저장 시간만큼 늦어진다. 회귀 T-F7이 AST로 세 문장의 순서를 고정한다.
- 동기 `POST /api/chat`: `for event in process_question(...)`를 `try/except Exception as e`로 감싸 "답변 생성 실패(동기)" ERROR 로그 → 헬퍼 호출 → **원 예외를 다시 올린다**(FastAPI 500 — 현재 동작 불변). 파이프라인 안에서 난 전 제공자 실패는 4.2가 이미 기록하므로 동기 경로에서 중복 기록되지 않는다(그 경우 예외가 아니라 `error` 이벤트다).
- 초기화 실패(`get_config`·세션 복원 `except`)는 기록하지 않는다 — `config`가 없을 수 있다. Plan (d) 한계.

### 4.4 중복 기록 방지

한 요청에서 실패 행은 **최대 1건**이다. 4.2(파이프라인 내부)와 4.3(API 외부)은 서로 배타다 — 4.2가 돌면 `process_question`은 정상 종료(`done`)하므로 4.3의 `except`에 들어가지 않는다. 테스트 T-F2가 "전 제공자 실패 시 저장 호출 정확히 1회"를 고정한다.

---

## 5. 감시 — `check_llm_fallback.py`

### 5.1 상수·인자

```python
RECENT_FAIL_WINDOW = timedelta(hours=12)      # U1 — cron 2주기. 한 실행을 놓쳐도 다음이 잡고, 단일 blip은 메일 ≤ 2통
SUMMARY_FAIL_WINDOW = timedelta(hours=24)     # 요약 "최근 24시간 실패 n건"(알림 아님)
--fail-window <hours>                          # 기본 12
```

### 5.2 판정

```python
def degraded(llm):                       # 실패 행이면 그것만 사유다 — fallback·empty를 함께 세지 않는다
    if llm.get("failed"):
        return [f"failed:{llm.get('error_class') or '?'}"]
    ...기존...

def judge(rows, window=3, now=None, fail_window=RECENT_FAIL_WINDOW) -> Verdict:
    now = now or datetime.now(timezone.utc)
    real = 중복 제거 + 합성 제외 + created_at 내림차순        # 기존
    picked = real[:window]                                   # R1
    r1 = len(picked) >= window and all(degraded(...) for ...)
    recent_failed = [r for r in real if _is_failed(r) and _ts(r) is not None and _ts(r) >= now - fail_window]   # R2
    status = "alert" if (r1 or recent_failed) else ("insufficient" if len(picked) < window else "ok")
    return Verdict(status, picked, recent_failed=recent_failed, last_real=real[0] if real else None,
                   failed_24h=sum(1 for r in real if _is_failed(r) and _ts(r) >= now - SUMMARY_FAIL_WINDOW))
```

- `_ts(row)`: `created_at` ISO 문자열 → aware `datetime`(`Z` → `+00:00`). 해석 불가면 `None` → R2에서 제외하고 요약에 "시각 해석 불가 n건"으로 적는다(조용히 버리지 않는다).
- R2는 **표본 수와 무관**하다 — `insufficient`(실사용 3건 미만)여도 실패 행 1건이면 alert. 이것이 10-14 사례를 잡는 핵심이다(그때 실사용은 10-11 1건 + 실패들이었다).
- "Claude가 아님"으로 판정하지 않는다는 기존 원칙은 그대로다 — `failed`는 제공자 이름과 무관한 결과 상태다.

### 5.3 조회 — W 구간 커버리지

`fetch_recent(db, window, now, fail_window)`는 종료 조건을 바꾼다: **(실사용 ≥ window) AND (가장 오래된 조회 행의 `created_at` < now − max(fail_window, 24h 요약 창))** 또는 기록 끝·`MAX_PAGES`. 요약의 '최근 24시간 실패 n건'도 같은 행으로 세므로 창은 둘 중 긴 쪽을 덮는다(CodeRabbit #150, B5c). 기존 조건(실사용 window건)만 두면 최근 12시간 안에 성공 3건 뒤의 실패 행이 **페이지 밖에 남아** R2가 보지 못한다(테스트 B5). 페이지 사이 중복은 기존처럼 `id`로 제거한다. 마지막 행의 `created_at`을 해석할 수 없으면 '창을 덮음'으로 보고 멈춘다(무한 조회 방지 — fail-open, `MAX_PAGES`가 상한). `MAX_PAGES=20`(1,000행)은 유지 — 12시간에 1,000행을 넘는 트래픽은 이 서비스에 없다(하루 0~5건 + 벤치 수십 건).

### 5.4 출력

```
## LLM 폴백 감시: 🚨 최근 12시간 내 전 제공자 실패 2건 · 답변 처리 예외 1건   ← R2 제목. stage별로 센다(Check M-2). R1도 참이면 " · 🚨 최근 실사용 3건 연속 폴백"을 한 줄에 이어 붙인다(표본이 전부 실패 행이면 '연속 실패' — 폴백은 성공한 전환이다, CodeRabbit #150·L-5)
- 마지막 성공 답변: 10-11 17:22 KST (69.6시간 전) · 최근 24시간 실패 2건      ← 실패 행은 제외(`last_ok`, CodeRabbit #150)
- created_at 해석 불가로 R2에서 제외한 실패 행 n건                 ← 있을 때만
| 시각(KST) | provider | model | attempts | 저하 사유 |
| 10-14 09:12 | — | — | Claude → OpenAI → Gemini | failed:ResourceExhausted |
...
점검 힌트(실패 행의 stage·status·error_class로 분기, 중복 제거; `failures`가 비면 최상위 error_class·status로 폴백):
- stage=pipeline → "답변 처리 중 예외(코드 결함일 수 있다) → `답변 생성 실패` ERROR 줄 traceback 확인, 수정·revert 검토" (Check M-2 — LLM 장애로 읽히지 않게 따로 말한다)
- 401·AuthenticationError·GatewayAuthError → "Gateway OIDC 토큰(프로덕션은 요청 헤더·로컬은 재pull)·Vercel env LLM_TRANSPORT 확인"
- 402·PaymentRequired·credit → "Gateway 크레딧 잔액 확인(GET /v1/credits) — 충전은 사용자 승인 사항"
- 429·ResourceExhausted·RateLimit → "제공자 한도·Gemini 선불 잔액"
- 그 외 → "Vercel 런타임 로그의 `답변 생성 실패, 다음 제공자로 전환` 원문"
::error::최근 12시간 안에 실사용 답변 실패 — 전 제공자 실패 2건 · 답변 처리 예외 1건
```

- 성공 답변이 하나도 없으면 "마지막 성공 답변: 기록 없음(조회 범위 안 성공 답변 0건) · 최근 24시간 실패 n건".
- `render`는 여전히 `question_text`를 읽지 않는다(행 select도 `id,created_at,metadata` 그대로). 힌트는 상수 문자열만 — 예외 메시지·토큰 값이 끼어들 경로가 없다.
- 종료 코드 규약 불변: alert → 1, 조회 실패 → 2, 그 외 0. 법령 조회 감시(①②③)는 그대로.

---

## 6. 관리자 화면(U3)

- 통계(`admin_stats`) 네 집계 **무변경** — 실패 행 포함(총 요청 수 의미). 합성 행도 이미 포함되는 "저장된 행 수" 지표다.
- 상세(`admin_conversation_detail`은 `select("*")`라 `metadata`가 온다): `openDetail`에서 `data.metadata && data.metadata.failed`면 답변 영역 위에 표지 + 한 줄 안내. **stage별로 말이 다르다**(Check M-2): `stage=answer` → `답변 실패 · {error_class} {status}` + "모든 AI 제공자 호출이 실패해 답변이 생성되지 않았습니다." / `stage=pipeline` → `처리 예외 · {error_class}` + "답변 처리 중 예외가 발생해 저장되지 않았습니다(코드 결함일 수 있고, 사용자에게 일부 답변이 전송됐을 수 있습니다)." 둘 다 "공개 게시판에는 실리지 않습니다."를 붙인다. 값은 전부 `escapeHtml`. `md("")`는 빈 영역이라 표지가 없으면 '답변이 비었다'로 오해된다.
- 목록 표지(선택, Low): **보류** — `admin_conversations` select에 `failed:metadata->>failed` 별칭 투영이 필요한데 실측 없이 넣으면 목록이 통째로 멈출 위험이 있다. 후속 후보.
- HTML 주석에 내부 파일 경로·함수명을 쓰지 않는다(CLAUDE.md).

---

## 7. 보안·개인정보

| 항목 | 설계 |
|---|---|
| 예외 메시지 | **이번에 추가한 코드**에서는 어디에도 저장·출력하지 않는다. `_failure_llm_meta`는 `type(exc).__name__`·`_status_of(exc)`만 읽는다. 헬퍼의 실패 로그도 클래스명만. 기존 WARNING·ERROR 로그(`답변 생성 실패…: %s`)는 원문을 출력하고, 힌트 'other'가 바로 그 줄을 보라고 안내한다 — 기존 동작이고 범위 밖 |
| 토큰 | 실패 페이로드 키 화이트리스트 9종(§3.4) — 문자열 필드는 `error_class`(식별자)·`stage`·`transport`·`provider`만 |
| 질문 원문 | U2: 정상 대화와 같은 컬럼·권한·보존(방침 제5항 1년, `purge_expired_data`). 공개 게시판은 `failed` 키로 제외 |
| 감시 로그 | `question_text` 미조회 유지. 힌트는 상수 문자열 |
| 권한 | anon INSERT(기존). 새 GRANT·정책 없음 |

---

## 8. Test Plan(전부 오프라인, CI `tests.yml` 기존 단계)

### 8.1 `test_llm_fallback.py`

| ID | 내용 | 고정하는 것 |
|---|---|---|
| T-F1 | 제공자 3개 전부 즉시 실패(메시지에 `SECRET-sk-test-123` 포함) → 이벤트 `error`→`ping`→`done` 순서, `saved[0].answer_text == ""`, `metadata.failed is True`, `llm.failed`·`stage=="answer"`·`attempts == 3개`·`failures` 3건의 `error_class`, `set(llm.keys()) ⊆ 화이트리스트`, **`"SECRET" not in json.dumps(saved[0].metadata)`** | FR-01·FR-03·FR-04 |
| T-F2 | 같은 조건에서 `save_conversation` 호출 **정확히 1회**(API 외부 중복 없음) · `save_conversation`이 예외를 던져도 이벤트 동일 | 4.4·FR-03 |
| T-F3 | `config.supabase=None` → 저장 시도 0회, 이벤트 동일 | 4.1 |
| T-F4 | `_failure_llm_meta(None, exc, "pipeline", "gateway")` → `attempts==[]`, `failures` 1건, `status`는 `status_code`·`response.status_code`·`code(int)` 세 모양 모두에서 추출, 문자열 `code`는 무시 | §3.3·3.4 |
| T-F5 | `guard_ctx=None` → `metadata.synthetic True`; `GuardContext(synthetic=False)` → 키 없음; `GuardContext(synthetic=True)` → True | FR-06 |
| T-F6 | 같은 질문·analysis로 `_category_for`가 성공 경로 저장 행의 `category`·`calculation_types`와 동일 | 1.2 |
| T-F7 | `api/index.py` AST: 세 경로의 **"답변 생성 실패" 로그를 가진 `except` 핸들러**가 `record_failed_conversation`을 호출하고(초기화 핸들러로 옮기면 실패), SSE 두 경로는 문장 순서가 `yield next(gen)` → 기록 → `yield from gen`(Check M-1) | FR-02·FR-03 |
| T-F8 | 빈 응답 승격 시 `failures`에 `EmptyResponse` 기록, 절단은 기록하지 않음 | §3.2 |

### 8.2 `test_llm_fallback_alert.py`

| ID | 내용 |
|---|---|
| B1 | 실사용 `failed` 행 1건이 `now−11h` → `alert`(표본 1건이라도) |
| B2 | `failed` 행이 `now−13h`, 최근 3건이 전부 저하는 아님 → `ok`(R2 미발동, R1 미발동) |
| B3 | 합성 `failed` 행만 → R2 제외 → `insufficient`/`ok` |
| B4 | **10-14 재구성**: 10-11 17:22 OK(실사용) + 10-14 09:12 failed(실사용) + 사이 합성 OK들, `now=10-14 15:00Z` → `alert`; 같은 행을 `failed` 없이 넣으면(구 동작) `insufficient` |
| B5 | `FakeDb` 59행: 최근 12h 안에 실사용 OK 3건이 **앞**에, 합성 55건 뒤 페이지에 실패 1건 → `fetch_recent`가 W 구간을 덮어 `alert`(구 종료 조건이면 못 봄) |
| B5b | 실사용 3건 + 창 밖 행이 첫 페이지에 있으면 더 읽지 않는다(과다 조회 방지) |
| B6 | `render`: R2 제목·마지막 실사용 경과 줄·401 힌트 포함, `question_text` 미포함, 토큰 모양 문자열(`eyJ…`) 미포함 |
| B7 | `degraded({"failed": True, "error_class": "X", "attempts": [a,b]})` → `["failed:X"]`(fallback 중복 없음) |
| B8 | 실사용 0건 → "기록 없음" 줄, exit 0 경로 |
| B9 | `created_at` 해석 불가 행 → R2 제외 + 요약에 "해석 불가 1건" |
| B10 | `--fail-window 6`이 `judge(fail_window=6h)`로 전달(`main` 인자 배선) |
| B11 | 402 → 크레딧 힌트, 상태 없는 `GatewayAuthError` → 토큰 힌트, `NoProvider` → 로그 힌트, 같은 힌트는 1회, `failures`가 빈 옛 모양은 최상위 status로 폴백(Check L-4) |
| B12 | `stage=pipeline` 행은 제목 "답변 처리 예외 n건"·코드 결함 힌트, "전 제공자 실패"·토큰 힌트 없음; 혼합이면 "전 제공자 실패 1건 · 답변 처리 예외 1건"(Check M-2) |

### 8.3 `test_offline_units.py`

- `test_public_exclude_keys`의 필수 키에 `"failed"` 추가(6종 중 5종 단언 — `counsel`은 기존 미단언), `is_public_excluded({"failed": True})` 참, `{"failed": False}` 거짓(True만 기록 계약).

### 8.4 변이 검사(Do 완료 조건)

기록 호출 제거 / `"failed"` 키 누락 / `fetch_recent` W 조건 제거 / `degraded`의 failed 분기 제거 / `_status_of`의 `code` 분기 제거 / API except 블록 중 하나에서 호출 제거 → 각각 최소 1개 테스트가 깨진다(6/6).

### 8.5 로컬 재현(V-9 절차, 비용 $0)

1. `.env.vercel.local`의 토큰이 만료된 상태(2026-10-30 18:43 KST 이후, **재pull 금지**)에서 `LLM_TRANSPORT=gateway ./.venv/bin/uvicorn api.index:app --port 5555`.
2. `GET /api/chat/stream?message=…` 1건 → `error`·`ping`·`done` 확인.
3. Supabase(anon)에서 그 세션의 행 1건: `answer_text==""`, `metadata.failed`, `metadata.synthetic`(로컬=loopback), `llm.failures` 전부 401 — **출력은 키·불리언·상태 코드만**.
4. `python3 check_llm_fallback.py` 로컬 실행 → 합성이라 R2 미발동(exit 0) — 감시가 합성을 거르는 것까지 확인. R2 양성은 B1·B4 오프라인 테스트가 담당한다(프로덕션에서 장애를 유발하지 않는다).

---

## 9. 결정 기록

| ID | 결정 | 이유 |
|---|---|---|
| D-1 | 헬퍼를 `pipeline.py`에 둔다 | `_llm_meta`·`AnswerOutcome`·`classify_category`가 거기 있고 `api/index.py`가 이미 pipeline을 import한다. storage에 두면 outcome 모양을 storage가 알아야 한다 |
| D-2 | `_stream_answer`가 `failures`를 기록하고 최종 RuntimeError의 클래스는 쓰지 않는다 | 포장 예외의 클래스명(`RuntimeError`)은 정보가 없다. 원인은 제공자별 예외다 |
| D-3 | `degraded()`에서 `failed`는 단독 사유 | "fallback"은 성공한 폴백을 뜻하는 기존 어휘라 실패 행에 함께 붙이면 표가 거짓이 된다 |
| D-4 | R2는 표본 수와 무관 | 10-14 사례(실사용 1건 + 실패)를 잡으려면 `insufficient`에서도 울려야 한다 |
| D-5 | 킬스위치(Plan FR-11) **도입 안 함** | 기록은 실패 경로에서만 돌고 fail-open이라 사용자 영향이 없다. 환경변수를 늘리면 재배포 반영 의미론을 또 설명해야 한다. 되돌리기는 기록 호출부 revert(§10 — `PUBLIC_EXCLUDE_KEYS`의 `failed`는 남긴다) |
| D-6 | 세션 스냅숏·첨부는 실패 행에 저장하지 않는다 | 답변이 없어 이력 가치가 없고, 첨부 업로드는 비용·지연만 더한다 |
| D-7 | `fetch_recent` 종료 조건을 "W 구간까지"로 확장 | 최근 성공 3건 뒤의 실패가 페이지 밖에 남는 사각(B5) |
| D-8 | 카테고리 블록을 `_category_for`로 추출해 양쪽이 공유 | 복제하면 실패 행의 카테고리가 성공 시와 달라진다 — 관리자 분포가 어긋나는 조용한 결함 |
| D-9 | 관리자 통계 무변경, 상세 표지만 | U3. 별도 집계는 후속 후보 |

---

## 10. 운영·롤백

- 배포: PR 머지 → Vercel 자동 배포 → `workflow_dispatch` 1회(exit 0, 요약에 "마지막 성공 답변" 줄) → 정상.
- 롤백: **기록 호출부(pipeline·api)만 revert**하고 `storage.PUBLIC_EXCLUDE_KEYS`의 `failed`와 감시의 `failed` 처리는 남긴다. 전체 PR revert는 제외 키까지 지워 이미 쌓인 실패 행(질문 원문 + 빈 답변)이 공개 게시판 `board_recent`·`board_search`에 노출된다(CodeRabbit #150 — v0.2의 "revert 뒤 무해"는 틀렸다). 전체 revert가 꼭 필요하면 먼저 SQL Editor에서 `metadata->>'failed' = 'true'` 행을 삭제한다(anon DELETE 불가). 남긴 행은 365일 purge.
- 알림 수신 시: 요약의 힌트 → Vercel 런타임 로그 → (401) OIDC/`LLM_TRANSPORT` → (402) 크레딧 잔액 — **충전·결제는 사용자 승인**.
- 문서: `CLAUDE.md` "폴백 결과는 `qa_conversations.metadata.llm`에 기록한다" 절에 실패 행·R2를 덧붙이고, `_PUBLIC_EXCLUDE_KEYS` "현재 4종" → **6종**(`counsel`은 있었으나 미기재, `failed` 설명). `check_llm_fallback.py` docstring·`llm-fallback-alert.yml` 주석에 R2. memory `project-llm-fallback-alert`의 "사각" 문단을 해소 기록으로.

---

## 11. Implementation Order

1. `app/core/storage.py` — `PUBLIC_EXCLUDE_KEYS += ("failed",)` + `test_offline_units` 갱신(가장 작은 단위, 먼저 초록).
2. `pipeline.py` — `AnswerOutcome.failures`·`_stream_answer` 기록·`_status_of`·`_failure_llm_meta`(T-F4·T-F8 먼저 작성 → 구현).
3. `pipeline.py` — `_category_for`·`_synthetic_flag` 추출(기존 테스트 전부 통과 확인 — 추출만).
4. `pipeline.py` — `record_failed_conversation` + `except RuntimeError` 배선(T-F1~F3·F5·F6).
5. `api/index.py` — 세 경로 배선(T-F7 AST).
6. `check_llm_fallback.py` — `degraded`·`judge(now, fail_window)`·`fetch_recent` 커버리지·`render`·`--fail-window`(B1~B10).
7. `public/admin.html` — 상세 표지(+ 목록 선택).
8. 전체 테스트·변이 6종 → 로컬 재현(§8.5) → 문서(`CLAUDE.md`·docstring·워크플로 주석) → PR `fix/fallback-alert-blindspot`.

---

## 12. Check 항목(gap-detector용)

| ID | 확인 |
|---|---|
| V-1 | 실패 행 페이로드 키 집합 == §3.4 화이트리스트, 메시지 원문 부재(T-F1) |
| V-2 | 이벤트 순서 `error→ping→done`, 저장 1회, fail-open(T-F1~F3) |
| V-3 | API 세 경로 헬퍼 호출(T-F7) |
| V-4 | `PUBLIC_EXCLUDE_KEYS` 6종·게시판 필터/후처리/`dedupe_board` 자동 반영 |
| V-5 | R2·W 커버리지·힌트·요약(B1~B10), 종료 코드 규약 불변 |
| V-6 | 정상 경로 diff = 함수 추출만(동작 동일) — `test_llm_fallback.py` 기존 테스트 전부 통과 |
| V-7 | 로컬 재현 행 1건(§8.5), 토큰·메시지 출력 0 |
| V-8 | 변이 6/6 |
| V-9 | CLAUDE.md·docstring·워크플로 주석·memory 갱신 |

---

## Version History

| Version | Date | Changes | Author |
|---|---|---|---|
| 0.1 | 2026-10-30 | 초안 — 실패 행 모델·헬퍼·세 기록 경로·R2/W 커버리지·관리자 표지·테스트 18건·결정 D-1~D-9 | Claude |
| 0.2 | 2026-11-02 | Check(95.1%) 반영 — M-1 SSE 순서 `error → 기록 → done`(3왕복·120초 전제 정정), M-2 stage별 제목·힌트·관리자 문구, L-1 `_status_of` 예외 보호, L-4 힌트 단언(B11), B12·B5b·T-F7 강화, 제외 키 6종, 목록 표지 보류, §5.3 해석 불가 동작, §7 범위 한정 | Claude |
| 0.3 | 2026-11-03 | PR #150 CodeRabbit 반영 — §4.2 ping은 60초 여유(덮지 않음)·정상 경로와 같은 노출, §5.3 조회 창 = max(R2, 24h), §5.4 요약은 성공 답변(`last_ok`)·전부 실패면 '연속 실패', §9 D-5·§10 롤백은 호출부만(전체 revert는 실패 행 노출). 동기 로그 원문 제거는 §7 그대로(구현 수정). 테스트 B2b·B5c·B13·T-F7 stage/로그 검사 | Claude |
