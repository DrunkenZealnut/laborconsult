# 챗봇 Network Error 수정 Planning Document

> **Summary**: 챗봇 질문 시 발생하는 "network error"의 근본 원인 분석 및 수정 — 무효 Pinecone 키가 SSE 에러 핸들러의 `NameError` 버그와 겹쳐 연결이 끊기던 문제
>
> **Project**: laborconsult
> **Author**: Claude
> **Date**: 2026-06-30
> **Status**: Implemented (코드 수정 완료, 키 재발급 대기)
> **Branch**: `main`

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 챗봇에 질문하면 답변 대신 "network error"가 표시됨. 서버는 200을 보내고도 첫 바이트조차 못 보낸 채 연결이 끊겨, 브라우저 `fetch`가 "Failed to fetch"로 실패 |
| **Solution** | ① SSE 초기화 에러 핸들러(`error_gen`)의 `NameError` 버그 수정 — except 블록을 벗어나면 삭제되는 `e`를 지연 실행 제너레이터가 참조하던 문제를 기본 인자 바인딩으로 해결 (GET/POST 2곳). ② 트리거였던 무효 `PINECONE_API_KEY` 재발급 (사용자 조치) |
| **Function/UX Effect** | 초기화 실패 시 연결이 끊기지 않고 "서버 초기화에 실패했습니다. 환경설정(API 키)을 확인해주세요." 라는 읽을 수 있는 메시지가 챗 화면에 표시됨. 키 재발급 후 정상 답변 |
| **Core Value** | 모든 초기화 오류가 불투명한 network error가 아닌 명확한 메시지로 노출 → 사용자 혼란 방지 + 운영 디버깅 가능 |

---

## 1. Overview

### 1.1 증상

`public/index.html`의 채팅에서 질문 전송 시 답변 대신 "network error"(브라우저 `fetch` 실패) 발생. `send()`의 `catch` 블록이 `e.message`("Failed to fetch" 등)를 그대로 표시.

### 1.2 근본 원인 (2계층)

**계층 1 — 트리거: 무효 Pinecone API 키**
- `AppConfig.from_env()`가 `pc.Index(index_name)`(`app/config.py:52`)에서 Pinecone에 네트워크 호출을 수행 → `401 Unauthorized: Invalid API key` 발생.
- `.env`의 `PINECONE_API_KEY`는 형식상 정상(`pcsk_` 접두, 75자, 공백/따옴표 없음)이나 Pinecone 서버가 거부 → **키가 revoke/만료되었거나 다른 프로젝트 소속**. (401=인증 실패이지 404=인덱스 없음이 아니므로 키 자체 문제로 확정)

**계층 2 — 핵심 코드 버그: 에러 핸들러가 또 다른 예외 발생**
- `api/index.py`의 `chat_stream`(GET)·`chat_stream_with_files`(POST)는 초기화 실패 시 `error_gen()` 제너레이터로 에러 SSE를 보내려 함.
- 그러나 `error_gen()`은 `except Exception as e:`의 `e`를 클로저로 참조. Python은 **except 블록을 벗어나면 `e`를 자동 삭제**(PEP 3110)하므로, 지연 실행되는 제너레이터가 `yield` 시점에 `NameError: cannot access free variable 'e'`를 던짐.
- 결과: `StreamingResponse`가 첫 청크도 못 보내고 ASGI 레벨에서 예외 → 연결이 끊김 → 브라우저는 **network error**로 인식. (정상이라면 사용자에게 보였어야 할 에러 메시지조차 전달 불가)

### 1.3 재현 근거

```
ERROR:root:SSE 초기화 실패: (401) ... HTTP response body: Invalid API key   ← 계층 1
...
File "api/index.py", line 113, in error_gen
  yield f"data: {... f'서버 초기화 오류: {e}'} ..."
NameError: cannot access free variable 'e' ...                              ← 계층 2
```
`curl`로 chat stream 호출 시 35초간 빈 응답 → 수정 후 정상 200 + `{"type":"error",...}` 이벤트 확인.

---

## 2. Requirements

| ID | 요구사항 | 우선순위 | 상태 |
|----|----------|:--------:|:----:|
| FR-01 | `error_gen`의 `NameError` 수정 (GET/POST 2곳) — 초기화 실패가 깔끔한 SSE error 이벤트로 노출 | P0 | ✅ 완료 |
| FR-02 | 무효 `PINECONE_API_KEY` 재발급 후 `.env`·Vercel 환경변수 갱신 | P0 | ⏳ 사용자 조치 |
| FR-03 | Pinecone 초기화를 graceful 처리해 단일 의존성 장애가 전체 챗을 막지 않도록 개선 | P2 | ✅ 완료 |

---

## 3. Implementation

### 3.1 적용된 수정 (FR-01)

`api/index.py` 두 엔드포인트의 에러 핸들러:

```python
except Exception as e:
    logging.error("SSE 초기화 실패: %s\n%s", e, traceback.format_exc())
    err_text = "서버 초기화에 실패했습니다. 환경설정(API 키)을 확인해주세요."

    # 'e'는 except 블록을 벗어나면 자동 삭제됨 → 지연 실행 제너레이터가
    # 직접 참조하면 NameError. 기본 인자로 메시지를 바인딩해 회피.
    def error_gen(msg=err_text):
        yield f"data: {json.dumps({'type': 'error', 'text': msg}, ensure_ascii=False)}\n\n"
    return StreamingResponse(error_gen(), media_type="text/event-stream", ...)
```

- 원본 메시지에 `{e}`(raw Pinecone 401 스택)를 노출하던 부분도 사용자 친화 메시지로 대체. 상세 원인은 로그로만 남김(정보 노출 방지).
- 전수 검색 결과 동일 패턴(except 후 지연 실행 클로저가 `e` 참조)은 이 2곳뿐. 다른 `except as e` 블록은 `e`를 블록 내에서 즉시 사용하므로 안전.

### 3.2 검증

| 항목 | 수정 전 | 수정 후 |
|------|---------|---------|
| chat stream 응답 | 빈 응답 / 연결 끊김 | `200 OK` + `data: {"type":"error","text":"서버 초기화에 실패했습니다..."}` |
| 프론트 동작 | "network error" (fetch 실패) | `readSSE()`가 error 이벤트를 챗 메시지로 표시 |

---

### 3.3 적용된 수정 (FR-03 — Pinecone graceful degradation)

`app/config.py`의 `from_env()`에서 eager `pc.Index()` 호출이 실패하면 config 초기화 전체가 죽어, Pinecone 무효/장애 시 계산기·법령·LLM 등 RAG와 무관한 기능까지 막혔다. 이를 try/except로 감싸 `pinecone_index = None`으로 degrade.

```python
index_name = os.getenv("PINECONE_INDEX_NAME", "semiconductor-lithography")
pinecone_index = None
try:
    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    pinecone_index = pc.Index(index_name)
except Exception as exc:
    logging.warning("Pinecone 초기화 실패 — 벡터 검색(RAG) 없이 동작합니다: %s", exc)
```

- **추가 수정 불필요**: `rag.py`는 이미 `pinecone_index=None`(→ `None.query()` → `AttributeError`)과 쿼리 실패를 try/except로 잡아 `[]`를 반환. `pipeline.py`의 RAG 블록도 전체가 try/except + "무시하고 진행"이라 `precedent_text=None`으로도 답변 생성. `config.pinecone_index` 사용처는 `rag.py` 한 곳뿐.
- **유효 키 경로 보존**: 기존 `pc.Index(index_name)` 호출을 그대로 try로 감싸기만 해, 키가 유효하면 동작은 동일(순수 superset).
- **한계**: 장기 실행 uvicorn에서 init 시 Pinecone가 죽어 있으면 `_config`에 `None`이 캐시되어, 복구돼도 프로세스 재시작 전까지 RAG 비활성. Vercel은 콜드스타트마다 재초기화되어 자가 복구됨.

**FR-03 검증** (무효 Pinecone 키 상태에서 실제 질문):

| 단계 | 결과 |
|------|------|
| config 초기화 | ✅ 성공 (로그: `Pinecone 초기화 실패 — 벡터 검색(RAG) 없이 동작합니다: (401)`) |
| 질문 분석 | ✅ 정상 (Anthropic) |
| RAG 검색 | ✅ `sources: hits:[]` — 크래시 없이 빈 결과 |
| 기관 연락처 | ✅ 고용노동부 1350 제공 |
| 답변 생성 | ✅ "⚠️ 일반 노동법 지식을 기반으로 작성…" 스트리밍 (200 OK) |

---

## 4. 남은 조치 (FR-02)

챗봇이 **실제 답변**을 하려면 유효한 Pinecone 키가 필요:

1. Pinecone 콘솔에서 새 API 키 발급 (또는 기존 키 활성 상태·프로젝트 확인)
2. `.env`의 `PINECONE_API_KEY` 갱신, 인덱스명(`PINECONE_INDEX_NAME=semiconductor-lithography`)이 해당 프로젝트에 존재하는지 확인
3. 배포 환경은 Vercel 프로젝트 환경변수도 동일 갱신
4. 서버 재시작 후 질문 → 정상 답변 확인

> 참고: FR-01 수정으로 키가 여전히 무효여도 더 이상 network error가 아닌 명확한 안내 메시지가 표시됨.
