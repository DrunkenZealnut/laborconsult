# ai-gateway-oidc-migration — Vercel AI Gateway(OIDC 인증 + Gateway 크레딧) 전환 Plan

> 작성 2026-10-28 · 기준 코드 main `9529cf1` · 요청 출처: 사용자 지시문(2026-10-28, "Vercel 프로덕션에서 Vercel AI Gateway의 OIDC 인증 + Gateway 크레딧 결제 방식으로 전환")
> 상태: 사용자가 같은 날 "계획만 세워주세요"로 범위를 좁혀, 이 문서는 **구현 전 계획**이다. 코드·배포·결제는 아직 아무것도 하지 않았다.
> 조사 방법: 공식 문서 4종(OIDC·마이그레이션·요금·개요)과 Gateway 공개 모델 목록(`GET /v1/models`, 498개)을 읽고, `app/`·`api/`의 벤더 SDK 호출 지점을 전수 열거했다. Vercel 프로젝트(`prj_2Kr9TBjVVTPoT1igKF4U6TC7ZIDp`)의 OIDC 설정은 REST API로 확인했다(토큰 값은 출력하지 않았다).

## Executive Summary

| 관점 | 내용 |
|---|---|
| 문제 | 프로덕션 LLM 호출이 벤더 4곳(Anthropic·OpenAI·Cohere·Google)의 **장기 API 키**를 Vercel 환경변수에 두고, 선불 잔액도 벤더마다 따로 관리한다. 2026-10-27 Anthropic 크레딧이 하루 두 번 소진되고 Gemini 선불이 말라 답변이 폴백으로만 이어졌다 — 잔액 관리 지점이 넷이라 어느 하나가 비어도 알아채기 어렵다. |
| 해결 | 요청 경로(`api/`·`app/`)의 Claude·OpenAI·임베딩·Cohere 재정렬 호출을 **Vercel AI Gateway**로 보낸다. 인증은 요청마다 Vercel이 넣어 주는 **OIDC 토큰**(장기 키 없음), 결제는 **Gateway 크레딧 하나**. 전송 스위치(`LLM_TRANSPORT`)로 구 경로에 즉시 복귀할 수 있다. |
| 기능·UX 효과 | 답변·계산·검색 동작은 그대로다 — SDK 호출 형태·모델·임베딩 모델(1536차원)·Pinecone 데이터 불변. 운영자는 사용량·비용·오류를 Gateway 대시보드 한 곳에서 보고, 잔액을 한 곳에서 관리한다. |
| 핵심 가치 | 장기 키 제거(OIDC)와 결제 단일화. 인증 실패는 **조용한 우회 없이** 명시 오류로 드러나고, 지원되지 않는 경로(Gemini)는 숨기지 않고 보고한다. |

## 1. 요청과 제약

사용자 지시문의 제약을 그대로 옮긴다(설계·구현·보고가 모두 이 문장을 기준으로 판정된다).

- 추가 결제, 크레딧 구매, 자동 충전 설정은 별도 승인 없이 실행하지 않는다.
- 키 값이나 OIDC 토큰을 화면·로그·문서에 출력하지 않는다.
- 인증 실패 시 기존 제공자 키를 몰래 사용하는 경로를 만들지 않는다.
- 지원되지 않는 모델을 임의로 다른 모델로 바꾸지 않는다.
- 기존 SDK 버전 제한의 사유를 읽고 무조건 최신 버전으로 올리지 않는다.
- 임베딩은 기존 모델·차원·검색 호환성을 유지한다. Pinecone 데이터 삭제·재색인·전체 재임베딩은 하지 않는다.
- 지원되지 않는 경로는 남은 직접 호출과 이유를 명시하고, 전체 전환이 완료된 것처럼 보고하지 않는다.
- 사용하지 않게 된 제공자 키는 삭제 후보로 정리한다. 다른 프로젝트와 공유할 수 있으므로 제공자 측 키를 임의로 폐기하지 않는다.
- 계정 연결·크레딧 잔액 등 사용자 작업이 필요하면 가능한 코드 수정과 검증을 먼저 끝내고 필요한 작업만 구체적으로 알린다.
- 테스트 호출 수와 토큰 사용량은 최소화한다. 실패 시 기존 배포로 복구할 방법을 준비한다.

프로젝트 자체 제약(CLAUDE.md): Pinecone은 `laborlaw-v2`/`counsel`/`qa`만 읽고 `delete_index` 금지. `anthropic<1.0` 고정(1.x는 httpx2라 `pipeline.py`의 `httpx.Timeout`을 거부). 타임아웃·재시도 예산은 `app/config.py`가 단일 출처.

## 2. 현재 구조 (2026-10-28 실측)

### 2.1 클라이언트 생성

`app/config.py::AppConfig.from_env()`가 **전역 1회** 만든다 — `OpenAI(api_key=OPENAI_API_KEY)`(145행), `anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)`(162행). Gemini는 호출부 3곳에서 `genai.configure(api_key=config.gemini_api_key)`를 매번 부르고, Cohere는 `rag.py:683`에서 `cohere.ClientV2(api_key=...)`를 호출마다 만든다. `api/index.py::get_config()`가 그 전역을 돌려주고, 요청 경로 8곳이 그것을 받아 `process_question(..., config, ...)`에 넘긴다.

### 2.2 프로덕션 LLM 호출 지점(전수, 9개 파일)

| 경로 | 파일:위치 | 현재 모델 | 호출 형태 |
|---|---|---|---|
| 답변 스트리밍(Claude) | `pipeline.py::_stream_claude` 436 | 관리자 설정(rev 13: `claude-opus-5-5`) / 기본 `claude-sonnet-5` | `claude_client.with_options(timeout, max_retries).messages.stream(model, output_config.effort, thinking adaptive+summarized, …)` |
| 답변 스트리밍(OpenAI) | `pipeline.py::_stream_openai` 488 | 설정 `gpt-6-sol` / 기본 `o3` | `openai_client.with_options(…).chat.completions.create(stream=True, max_completion_tokens)` |
| 답변 스트리밍(Gemini) | `pipeline.py::_stream_gemini` 568 | `gemini-pro-latest`(별칭) | `genai.GenerativeModel(...).generate_content(stream=True)` + 스레드 idle 감시 |
| 보조 단계 텍스트(의도분석 폴백·분해·Self-RAG·교정·퇴고) | `llm_gateway.py::_claude_text/_openai_text/_gemini_text` 135~180 | 설정 1순위 모델 | `with_options(timeout, max_retries=0).messages.create` / `chat.completions.create` |
| 보조 단계 도구 호출(의도분석·파라미터 추출) | `llm_gateway.py::_claude_tool/_openai_tool/_gemini_tool` 241~332 | 설정 1순위 모델 | tool_use(강제 거절 시 auto 자가치유) / function calling(gpt-6-sol은 reasoning_effort none 재시도) / function_declarations |
| 임베딩(검색·공공 쿼터) | `rag.py` 167·248 | `text-embedding-3-small` 1536 | `openai_client.with_options(10s, 0).embeddings.create` |
| 임베딩(사례 대조·인용 관련성·법률 기준 근거) | `case_match.py` 90 · `citation_relevance.py` 101 · `legal_rule_store.py` 179(`api/index.py:577`이 주입) | 같음 | 같음 |
| Cohere 재정렬 | `rag.py::rerank_results` 683·700 | `rerank-v3.5` | `cohere.ClientV2(api_key).rerank(model, query, documents, top_n=전체)` |
| 관리자 모델 목록 | `model_settings.py::fetch_raw_models` 241~254 | — | `claude_client.models.list` / `openai_client.models.list` / `genai.list_models` |
| 관리자 테스트 호출 | `api/model_settings.py::run_test_call` | 선택 모델 | 답변 경로의 `_stream_*` 함수 그대로(테스트 전용 호출 코드 금지 규칙) |

모든 Anthropic·OpenAI 호출이 **`with_options(...)`를 먼저 거친다**(예외 0건) — 전송 계층을 끼워 넣을 자리가 하나로 정해져 있다는 뜻이다. 모델 ID는 `_CLAUDE_VERSION_RE`(`claude-opus-5-5` 하이픈 표기)·`_CLAUDE_TOOL_NO_FORCE`·`supports_effort`·관리자 저장값·`metadata.llm.model`이 **벤더 표기**로 읽는다.

### 2.3 오프라인·배치 경로(전환 대상 아님)

수집·업로드(`pinecone_upload_*`)·BM25 빌드·평가(`eval_*`)·GitHub Actions 감시(`check_llm_fallback.py`는 Supabase만, `legal-rule-scan.yml`은 임베딩)·launchd 예열은 저장소 밖 또는 로컬에서 제공자 키로 돈다. Vercel 함수가 아니라 OIDC 토큰이 없다.

### 2.4 Vercel 프로젝트

`laborconsult`(team `team_17WaHViTPIKk4lm2qjf3ZvOc`), framework fastapi, GitHub `DrunkenZealnut/laborconsult` main 자동 배포, **OIDC 이미 활성**(`oidcTokenConfig.enabled=true, issuerMode=team`). 로컬 저장소는 `vercel link`가 안 돼 있다(`.vercel/` 없음, `.gitignore`가 `.vercel/`·`.env*`를 제외).

## 3. Gateway 조사 결과

| 항목 | 확인 내용 | 출처 |
|---|---|---|
| 엔드포인트 | OpenAI 호환 `https://ai-gateway.vercel.sh/v1`(`/chat/completions`·`/responses`·`/embeddings`), Anthropic Messages 호환 `https://ai-gateway.vercel.sh/v1/messages`(`x-api-key`도 허용), Cohere 호환 `/v1/rerank`·`/v2/rerank`. **재정렬은 OpenAI·Anthropic 표면에 없다.** | 마이그레이션 문서 |
| 모델 ID | `creator/model`, 버전은 점(`anthropic/claude-opus-5.5`). 공개 목록 `GET /v1/models`(498개), 카탈로그 `GET /v1/models/catalog`가 슬러그 ↔ providerModelId를 준다(필드명은 Do에서 재확인). | 문서 + 실측 |
| 프로젝트 모델의 슬러그 | `anthropic/claude-opus-5.5`·`claude-sonnet-5.5`·`claude-sonnet-5`·`claude-haiku-5.5`·`claude-opus-5`, `openai/gpt-6-sol`·`o3`·`text-embedding-3-small`(type embedding), `cohere/rerank-v3.5`(type reranking), `google/gemini-2.5-pro`·`gemini-3.1-pro-preview`. **`gemini-pro-latest`에 해당하는 슬러그는 없다.** | `/v1/models` 실측 |
| OIDC | Vercel 함수에서는 요청마다 헤더 `x-vercel-oidc-token`으로 들어온다. 로컬은 `vercel link` + `vercel env pull`이 `VERCEL_OIDC_TOKEN`(12시간)을 파일에 쓴다. Gateway는 `Authorization: Bearer <token>`(SDK의 api_key 자리)를 받는다. `AI_GATEWAY_API_KEY`가 있으면 그것이 우선한다. | OIDC 문서 |
| 공식 Python 예제의 한계 | env의 토큰을 전역 클라이언트 생성 시 한 번 넣는 형태다 — 사용자가 금지한 패턴(만료 토큰을 전역에 고정). 매 요청 헤더에서 읽어야 한다. PyPI `vercel` 패키지의 `vercel.oidc`는 미들웨어 전제라 FastAPI 경로에서 검증이 필요하다(필수 의존성은 아니다). | OIDC 문서 |
| 요금 | 무마크업(제공자 정가), 선불 **AI Gateway Credits**. 무료 $5/월은 일부 모델만(opus 5.5 해당 여부 미확인). BYOK는 유료 티어 전용이고 실패 시 시스템 크레딧으로 폴백한다. 크레딧 소진 → HTTP 402. 예산 상한은 대시보드에서 설정. | 요금 문서 |
| 잔액·BYOK 상태 | 토큰이 있어야 `GET /v1/credits`로 조회 가능. **아직 미확인.** | — |

## 4. 해결 방향

### 4.1 설계 원칙

1. **전송 스위치 하나.** `LLM_TRANSPORT=gateway|direct`(기본 `direct`). 켜면 요청 경로 전부가 Gateway, 끄면 구 경로 그대로. Preview 검증·점진 전환·롤백의 단일 손잡이.
2. **요청별 토큰, 전역 연결.** 전역 SDK 클라이언트(연결 풀)는 유지하고, 요청 진입 시 헤더의 OIDC 토큰을 읽어 그 요청의 `config`에 묶는다(`with_options(api_key=token)`은 연결 풀을 공유하는 복사라 비용이 없다). 토큰은 contextvar에 잠깐 머물고 객체로 명시 전달된다 — 스레드풀(Self-RAG 병렬·Gemini idle 감시)에도 그대로 따라간다.
3. **우회 없음.** Gateway 모드에서 토큰이 없으면 `GatewayAuthError`로 **실패**한다. 제공자 키 폴백 분기는 코드에 존재하지 않고, 테스트가 "gateway 모드에서 `OPENAI_API_KEY`·`ANTHROPIC_API_KEY`를 읽지 않는다"를 고정한다.
4. **벤더 표기 유지, 경계에서만 변환.** 저장값·로그·`supports_effort`·자가치유 기억은 벤더 ID(`claude-opus-5-5`)를 쓴다. 슬러그 변환은 SDK 호출 직전 한 지점에서만 한다. 매핑은 카탈로그 1차 + 정적 표 2차, **미해결은 오류**(임의 대체 금지).
5. **호출 형태 불변.** `_stream_*`·`llm_gateway`·`rag.py`의 호출 코드는 바꾸지 않는다(관리자 테스트가 같은 함수를 쓰는 규칙이 그대로 성립). 바뀌는 것은 `AppConfig`가 쥐는 클라이언트 객체와 그 생성·바인딩이다.
6. **오프라인 경로는 그대로.** 수집·평가·Actions는 제공자 키 직접 호출을 유지한다.

### 4.2 경로별 방침

| 경로 | 방침 |
|---|---|
| Claude(답변·보조·도구) | Gateway Anthropic 호환 엔드포인트. `anthropic<1.0` 그대로(`base_url`·`with_options(api_key=)` 지원). `thinking adaptive/summarized`·`output_config.effort`·`tool_choice` 거절 400 문구 통과 여부는 Live 검증 항목. |
| OpenAI(답변·보조·도구) | Gateway OpenAI 호환 `/v1`. `max_completion_tokens`·`reasoning_effort` 통과 여부 검증. |
| 임베딩 5곳 | Gateway `/v1/embeddings`에 `openai/text-embedding-3-small`. 같은 모델·차원이라 Pinecone 벡터 호환. 표본 코사인 ≥ 0.999로 동일성 확인. |
| Cohere 재정렬 | `cohere.ClientV2(api_key=token, base_url=Gateway)` → `/v2/rerank`, 모델 `cohere/rerank-v3.5`. 점수·순서 동일성 표본 확인. |
| Gemini 3순위 | **기본은 직접 호출 유지**(보고 대상 잔존 경로). 이유: google SDK가 Gateway를 가리킬 수 없고, `gemini-pro-latest` 별칭 슬러그가 없어 모델을 바꾸지 않고는 전환이 불가능하다. 사용자가 슬러그(예: `google/gemini-2.5-pro`)를 정하면 OpenAI 호환 경로로 전환하는 옵션을 설계에 둔다(Design Q1). |
| 관리자 모델 목록 | Gateway 모드에서는 카탈로그에서 벤더별 목록을 만든다(벤더 `models.list`는 Gateway 토큰으로 호출할 수 없다). |
| 관측 | `metadata.llm.transport`에 `gateway|direct` 기록. 폴백 감시(`check_llm_fallback.py`)는 무변경. |

### 4.3 단계

0. **사전 확인**(일부 사용자 작업) — 크레딧 잔액·BYOK 등록 여부, 팀 AI Gateway 활성. 로컬 `vercel link` + `vercel env pull`로 토큰을 받아 `/v1/credits`·`/v1/models/catalog` 인증 확인(값 비출력).
1. **구현**(새 브랜치·worktree) — 전송 모듈·인증 모듈·`AppConfig` 바인딩·미들웨어·슬러그 매핑·Cohere 경로·관리자 목록·`check_env.py`·`.env.example`·CLAUDE.md.
2. **오프라인 테스트** — 신규 `test_llm_transport.py` + 기존 스위트(`test_llm_fallback`·`test_offline_units`·`test_pipeline_wiring`·`test_model_settings`·`test_abuse_guard`·`test_law_api_recovery`). 네트워크 없음.
3. **로컬 Live 소검증** — OIDC 토큰으로 임베딩 동일성·재정렬 동일성·Claude 스트리밍(thinking)·도구 호출 각 1~2회.
4. **Preview** — Preview 환경에만 `LLM_TRANSPORT=gateway` → 상담 1·계산 1·SSE 확인 → Gateway 로그에 찍히는지.
5. **프로덕션** — Production env 설정 → 재배포 → 개인정보 없는 질문 2건 → 증거 수집.
6. **정리** — 삭제 후보 키 목록, 문서, Report.

## 5. 범위 밖

- Pinecone 데이터·인덱스·네임스페이스 변경, 재임베딩 — 하지 않는다.
- 오프라인 스크립트·GitHub Actions·launchd 예열의 인증 변경.
- 제공자 측 키 폐기(다른 프로젝트 공유 가능). Vercel env의 키 **삭제도 이 사이클에서는 하지 않고** 후보 목록만 낸다 — 이전 배포로의 즉시 복귀가 그 키를 쓴다.
- 크레딧 구매·자동 충전·예산 설정(사용자 승인 사항).
- SDK 메이저 업그레이드(`anthropic` 1.x 등).
- Gateway의 캐시·페일오버·태그 등 부가 기능 도입.

## 6. 위험

| # | 위험 | 대응 |
|---|---|---|
| R1 | Anthropic 호환 표면이 `thinking display summarized`·`output_config.effort`·`disable_parallel_tool_use`·강제 `tool_choice` 400 문구를 그대로 통과시키지 않을 수 있다 → 하트비트 공백·자가치유 불발 | 로컬 Live L3·L4에서 먼저 확인. 통과하지 않으면 **전환 보류**(모델·설정을 바꿔 맞추지 않는다). |
| R2 | 크레딧 0 또는 BYOK가 등록돼 있어 결제 경로가 요구와 다르다 | 단계 0에서 확인. 0이면 Preview까지만 하고 프로덕션 전환은 사용자 결정 뒤. |
| R3 | 토큰이 요청 경계 밖에서 필요해지는 경로(스레드·백그라운드) | 토큰을 요청 진입 시 객체에 묶어 명시 전달(contextvar 의존 최소화). 신규 테스트가 스레드풀 경로를 포함. |
| R4 | 슬러그 미해결 모델(관리자가 저장한 신모델) | 오류로 올려 다음 제공자로 전환. 관리자 목록이 카탈로그 기반이라 미해결 모델을 고를 수 없다. |
| R5 | `vercel env pull`이 로컬 `.env`를 덮는다 | 별도 파일(`.env.vercel.local`)에만 받고 `override=False`로 추가 로드. |
| R6 | Vercel env 변경은 다음 배포부터 적용(CLAUDE.md 교훈) | 스위치 설정 → 명시 재배포 → 확인 순서를 체크리스트로 고정. |
| R7 | Gateway 지연(<20ms)·오류 유형(402·429) | 타임아웃 예산 불변. 402/429는 제공자 실패로 분류되어 기존 폴백·거절 규약을 따른다. |

## 7. 완료 조건

1. `LLM_TRANSPORT=gateway`에서 Claude·OpenAI·임베딩·Cohere 호출이 전부 Gateway로 가고, 제공자 키를 읽는 코드 경로가 없다(테스트 고정).
2. `LLM_TRANSPORT` 미설정·`direct`에서 현재 동작과 바이트 동일(기존 스위트 전부 통과).
3. 임베딩 표본 코사인 ≥ 0.999, 재정렬 상위 순서 동일.
4. Preview에서 상담·계산·SSE 1회씩 정상, Gateway 대시보드에 요청 기록.
5. 프로덕션에서 개인정보 없는 질문 2건 정상 + `metadata.llm.transport=gateway` + `/v1/credits` 전후 차액 또는 대시보드 사용량.
6. 롤백 절차가 문서화되고 1회 리허설(Preview에서 `direct`로 되돌려 확인).
7. 최종 보고에 잔존 직접 호출(Gemini 등)·필요한 키·삭제 후보·비용 변화·사용자 작업이 명시.

## 8. 측정·증거 계획

- 호출 수 최소화: 로컬 Live 5~6회, Preview 2~3 질문, 프로덕션 2 질문. 전부 개인정보 없는 고정 질문.
- 증거: Gateway 대시보드 요청 로그(모델·토큰·비용), `GET /v1/credits` 전후, Supabase `qa_conversations.metadata.llm.transport`, `check_llm_fallback.py` 결과, Vercel 배포 ID.
- 프로덕션 점검 질문은 2건으로 제한(IP 쿼터 50/일과 게시판 오염 — CLAUDE.md).

## 9. Design에서 정할 것

| Q | 쟁점 | 후보 |
|---|---|---|
| Q1 | Gemini 3순위 | (a) 직접 호출 유지·보고 (b) 사용자가 정한 슬러그로 OpenAI 호환 경로 전환 |
| Q2 | 크레딧 잔액 0일 때 | (a) Preview까지만 (b) 사용자 충전 후 프로덕션 |
| Q3 | 토큰 주입 지점 | (a) 미들웨어 contextvar → `get_config()`가 요청별 바인딩 (b) 각 엔드포인트가 명시 전달 |
| Q4 | 슬러그 변환 지점 | (a) SDK 경계 프록시(호출부 무변경) (b) 호출부마다 변환 함수 |
| Q5 | 관리자 모델 목록 | (a) 카탈로그 기반 (b) 벤더 목록 유지(Gateway 토큰으로 불가) |
| Q6 | 로컬 토큰 파일 | `.env.vercel.local` + `override=False` 추가 로드 |

## Version History

| 버전 | 날짜 | 변경 |
|---|---|---|
| v0.1 | 2026-10-28 | 최초 작성(채팅으로 보고한 계획을 문서화) |
