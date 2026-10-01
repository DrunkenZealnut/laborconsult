# anthropic-sdk-v1 Design Document

> **Summary**: Anthropic SDK 0.x/1.x 양립 코드 + 호출 기록 기반 SDK 계약 테스트 + CI 최신 메이저 job, 그 뒤 상한 `<2.0`
>
> **Project**: laborconsult
> **Author**: Claude (with DrunkenZealnut)
> **Date**: 2026-09-29
> **Status**: Cancelled (2026-09-29) — SDK 업그레이드 불요, `anthropic<1.0` 상한 유지로 종결
> **Planning Doc**: [anthropic-sdk-v1.plan.md](anthropic-sdk-v1.plan.md)

확정 결정(Plan §6.2): **D1-a** temperature 제거 · **D2-a** 한 칸 상한 + CI 최신 job · **D3-a** `anthropic.Timeout` · **D4-a** 2단계 전환

---

## 1. Overview

### 1.1 Design Goals

1. 같은 코드가 anthropic **0.120.x와 1.8.x 양쪽에서** 동작한다(G1)
2. SDK가 인자·타입·스트림 형태를 바꾸면 **오프라인 테스트가 실패**한다 — 폴백이 삼키기 전에(G2)
3. 타임아웃 예산(llm-fallback-hardening §3.4)은 한 값도 바뀌지 않는다(G3)

### 1.2 Design Principles

- **SDK가 재수출하는 타입만 쓴다.** `anthropic.Timeout`, `anthropic.lib.streaming.TextEvent`. 전송 계층(`httpx`/`httpx2`)을 직접 import하지 않는다 — 이번 장애가 정확히 그 결합에서 났다.
- **계약은 손으로 나열하지 않는다.** "우리가 넘기는 kwargs 목록"을 테스트에 적으면 호출부가 늘 때 목록이 어긋난다(CLAUDE.md의 반복 교훈 — `test_public_fetch.js`가 파일 목록을 디렉터리 발견으로 바꾼 것과 같은 이유). 실제 호출을 **기록**해 시그니처와 대조한다.

---

## 2. 변경 명세

### 2.1 B1 — 타임아웃 타입 (Anthropic 호출만)

| 위치 | 현재 | 변경 |
|---|---|---|
| `pipeline.py::_stream_claude` 397-401 | `import httpx` + `httpx.Timeout(connect=…, read=…, write=…, pool=…)` | `anthropic.Timeout(connect=CONNECT_TIMEOUT, read=ANSWER_READ_TIMEOUT, write=ANSWER_READ_TIMEOUT, pool=CONNECT_TIMEOUT)` — 값 동일(G3) |
| `citation_validator.py` 297-303 | `import httpx` + `httpx.Timeout(min(per_call, _remaining(deadline)))` | `min(per_call, _remaining(deadline))` **float** — 단일값 Timeout과 의미 동일(모든 단계에 같은 값). 같은 파일 마이크로 폴리시(433)가 이미 float를 쓴다 |

**건드리지 않는 곳**: `_stream_openai`(417-428)의 `httpx.Timeout` — OpenAI SDK용이고 openai 3.x는 프로덕션에서 이 값으로 정상 동작 중(9-28 로그). 범위 밖(Plan §2.2).

### 2.2 B2 — temperature 제거 (D1-a)

| 위치 | 제거 값 | 비고 |
|---|---|---|
| `query_decomposer.py:209` | 0.3 | 분해 다양성 목적이었으나 기본값(1.0)으로도 JSON 3~5개 생성 — 형식은 시스템 프롬프트가 강제 |
| `self_rag.py:55` | 0 | `max_tokens=10` 단답(`relevant`/`irrelevant`) |
| `citation_validator.py:310` | 0 | 교정 결과는 길이 가드(0.7)·`_is_valid_rewrite`가 검증 |
| `citation_validator.py:439` | 0 | 동상 |
| `pinecone_upload_contextual.py:342` | 0 | 오프라인 업로더 |

각 자리에 기존 `analyzer.py:201`·`pipeline.py:787`과 **같은 문구**의 한 줄 주석을 남긴다 — "temperature 미지정: SDK 1.x가 매개변수를 삭제했고 Sonnet 5는 400으로 거부한다". 다음 사람이 결정성을 위해 되살리지 않도록.

### 2.3 B3 — 스트림 순회

```python
# 변경 전 (0.x 전용 — 1.x에서 AttributeError)
for text in stream.text_stream:
    yield text

# 변경 후 (0.x·1.x 공통)
for event in stream:
    if event.type == "text" and event.text:
        yield event.text
```

- 적용: `pipeline.py:411`, `chatbot.py:485`
- `event.text`의 빈 문자열 필터: `_stream_answer`는 `(provider, "")`를 **하트비트 신호**로 쓴다(CLAUDE.md 폴백 규약). SDK가 빈 텍스트 델타를 흘리면 하트비트로 오인되므로 걸러낸다. 0.x `text_stream`도 빈 델타를 내지 않았으므로 동작 동일.
- 텍스트 외 이벤트(`message_start`·`content_block_stop`·`message_stop` 등)는 무시 — 종료는 컨텍스트 매니저가 처리.

### 2.4 requirements.txt (2단계, 별도 배포)

```
anthropic>=0.120.0,<2.0
```

- 하한 0.120.0: 양립 코드가 기대는 `anthropic.Timeout`·`TextEvent`를 **실측 확인한 최저 버전**. 그 아래는 미검증.
- 상한 `<2.0`: D2-a. 주석은 현재 문구를 "1.x 대응 완료 — 2.x는 CI `anthropic-latest` job이 먼저 본다"로 교체.

---

## 3. 계약 테스트 T-SDK (`test_anthropic_sdk_contract.py`, 신규)

네트워크·API 키 불요. 설치된 SDK를 **그대로** 기준으로 삼는다 — CI의 두 job이 서로 다른 버전을 설치하므로 같은 테스트가 두 버전을 모두 검사한다.

### 3.1 기록용 가짜 클라이언트

```python
class _Recorder:
    """with_options(**opts).messages.create/stream(**kwargs) 호출을 기록한다."""
    calls: list[tuple[str, dict, dict]]   # (method, options, kwargs)
```

- `create`는 `SimpleNamespace(content=[TextBlock-like])`를 반환(각 호출부가 `.content[0].text`를 읽음)
- `stream`은 컨텍스트 매니저를 반환하고, 순회 시 **설치된 SDK의 `TextEvent` 클래스로 만든 이벤트**를 낸다 — 클래스가 사라지거나 필드가 바뀌면 생성 단계에서 실패(B3 탐지)

### 3.2 검사 항목

| ID | 대상 | 방법 | 잡는 것 |
|---|---|---|---|
| T-SDK-1 | 5개 호출부(`_stream_claude`, `decompose_query`, `judge_relevance`, 인용 교정, 마이크로 폴리시) | 가짜 클라이언트로 실제 함수 실행 → 기록된 kwargs 키 ⊆ `inspect.signature(anthropic.resources.messages.Messages.create 또는 .stream).parameters` | B2 (temperature 등 삭제된 인자) |
| T-SDK-2 | 동일 | 기록된 `with_options(timeout=)` 값이 `float`/`int` 또는 `isinstance(t, anthropic.Timeout)` | B1 (`httpx.Timeout` 직접 사용) |
| T-SDK-3 | `_stream_claude` | 가짜 스트림(TextEvent 2개 + 비텍스트 이벤트 1개 + 빈 텍스트 1개) → 산출이 텍스트 2개와 정확히 일치 | B3 + 하트비트 오인(§2.3) |
| T-SDK-4 | `with_options` 인자 | 기록된 옵션 키 ⊆ `inspect.signature(anthropic.Anthropic.with_options)` 또는 `copy` 시그니처 | `max_retries`·`timeout` 옵션명 변경 |
| T-SDK-5 | 버전 표기 | 설치 버전을 출력(실패 아님) | 두 job이 실제로 다른 버전을 봤는지 로그로 확인 |

**FR-04 증명 절차**: 구현 **전** 현행 main + anthropic 1.8.0 venv에서 T-SDK-1·2·3이 각각 실패함을 먼저 확인하고 그 출력을 분석 문서에 남긴다. 실패하지 않는 테스트는 아무것도 지키지 않는다.

### 3.3 호출부 진입 방법

각 함수는 클라이언트를 인자나 `config`로 받는다(`_stream_claude(messages, system, config)`, `decompose_query(query, client, …)`, `judge_relevance(query, document, client)`, `correct_hallucinated_citations(…, anthropic_client=…)`, `micro_polish(…)`). 전역 패치 없이 가짜 객체 주입만으로 도달 가능 — Do 단계에서 실제 시그니처를 확인해 맞춘다. 인용 교정은 예산 가드(`_remaining(deadline) >= 5`)를 통과하도록 넉넉한 deadline을 준다.

---

## 4. CI (`.github/workflows/tests.yml`)

기존 `offline-tests` job은 그대로(= requirements 기준 버전). 신규 job 추가:

```yaml
  anthropic-latest:
    # requirements 상한을 무시하고 최신 anthropic으로 SDK 접점만 다시 돈다.
    # 목적은 조기 경보 — 다음 메이저가 나오면 상한을 올리기 **전에** 여기서 먼저 깨진다.
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { persist-credentials: false }
      - uses: actions/setup-python@v5
        with: { python-version: "3.12", cache: pip }
      - run: pip install -r requirements.txt && pip install -U anthropic
      - run: python3 -c "import anthropic; print('anthropic', anthropic.__version__)"
      - run: python3 test_anthropic_sdk_contract.py
      - run: python3 test_llm_fallback.py
      - run: python3 test_pipeline_wiring.py
```

- 트리거에 `schedule: - cron: "0 0 * * 1"`(주 1회) 추가 — PR이 없어도 새 메이저를 감지하도록. 기존 `on:`에 병합한다.
- `offline-tests`에도 `test_anthropic_sdk_contract.py` 단계를 추가(requirements 기준 버전 검사).
- 단계 1(양립 코드) 시점: `offline-tests`=0.x, `anthropic-latest`=1.x → **양립을 CI가 직접 증명**한다. 단계 2(상한 `<2.0`) 이후: 둘 다 1.x, 2.x가 나오면 `anthropic-latest`만 붉어진다.

---

## 5. 전환 절차 (D4-a)

| 단계 | 내용 | 확인 | 롤백 |
|---|---|---|---|
| 0 | T-SDK 먼저 작성 → 현행 코드 + 1.8.0에서 실패 확인 | 실패 출력 기록 | — |
| 1 | §2.1~2.3 + CI job, **requirements는 `<1.0` 유지** | 두 CI job 녹색, 배포 후 프로덕션 1건 `provider=Claude`(여전히 0.x) | 코드 revert |
| 2 | requirements `>=0.120.0,<2.0` | CI 녹색, 배포 로그에서 `anthropic==1.x` 설치 확인, 프로덕션 1건 `provider=Claude attempts=['Claude']` + `쿼리 분해 완료` | requirements만 revert(코드는 0.x에서도 동작) |
| 3 | 품질 확인: `eval_retrieval.py` 도달률 기준선 대비 −2%p 이내(Plan §4.2) | 결과 기록 | 회귀 시 D1-b(`extra_body`)로 교체 |

단계 1과 2는 **별도 PR**. 단계 2 배포 전에 Vercel 빌드 로그의 설치 버전을 확인한다 — 이번 장애는 설치 버전을 아무도 보지 않아서 생겼다.

---

## 6. 영향 범위 밖 확인

| 항목 | 판단 |
|---|---|
| `analyzer.py` 의도분석 | `with_options(timeout=float)` + `create(model, max_tokens, system, tools, tool_choice, messages)` — 1.x 시그니처에 전부 존재. T-SDK-1에 포함해 고정 |
| `pipeline.py::_extract_params`(789) | 동일 패턴, temperature 이미 미지정. T-SDK-1에 포함 |
| `analyze_qna.py`·`benchmark_legal_cases.py` | `messages.create` 기본 인자만 — 1.x 호환. 오프라인 도구라 T-SDK 대상 외 |
| 예외 처리 `except anthropic.APITimeoutError` | 1.x에 존재, `APIConnectionError` 하위 유지 확인 |

---

## 7. Implementation Order

1. [ ] `test_anthropic_sdk_contract.py` 작성 (T-SDK-1~5)
2. [ ] 1.8.0 venv + 현행 코드에서 실패 확인·기록
3. [ ] §2.1 B1 (pipeline, citation_validator)
4. [ ] §2.2 B2 (5곳 + 주석)
5. [ ] §2.3 B3 (pipeline, chatbot)
6. [ ] 0.120.2(.venv)·1.8.0(scratch venv) 양쪽에서 T-SDK + 기존 오프라인 테스트 전량 통과
7. [ ] CI job 추가 → PR ① → 머지·배포 → 프로덕션 1건
8. [ ] PR ② requirements `<2.0` → 빌드 로그 버전 확인 → 프로덕션 1건
9. [ ] `eval_retrieval.py` 품질 확인
10. [ ] CLAUDE.md 폴백 규약 절에 SDK 계약 한 줄
