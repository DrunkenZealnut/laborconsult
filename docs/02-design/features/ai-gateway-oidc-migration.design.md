# ai-gateway-oidc-migration — Design

> Plan: `docs/01-plan/features/ai-gateway-oidc-migration.plan.md`(v0.1) · 작성 2026-10-28 · 기준 코드 main `9529cf1`
> 범위: Plan §4의 전송 계층·인증·모델 매핑·경로별 변경·검증·배포·롤백. Plan §9의 Q1~Q6을 §0에서 결정한다.
> 검증 상태: 이 문서의 코드 사실(호출 지점·`with_options` 전수 사용·스레드 경로)은 2026-10-28 저장소 grep 실측이다. Gateway 쪽 사실은 공식 문서와 `GET /v1/models` 공개 응답에서 왔고, **인증이 필요한 항목(`/v1/credits`·카탈로그 필드명·Anthropic 호환 표면의 확장 필드 통과)은 아직 확인하지 못했다** — §12에 검증 항목 V-1~V-9로 모아 Do 단계 첫 작업으로 둔다.
> 토큰·키 값은 이 문서에도, 구현의 로그에도 나오지 않는다.
> **v0.3(2026-10-28, Check 반영)**: 구현과 어긋난 서술을 정정했다(§1·§2.1·§2.2·§2.4·§2.5·§2.6·§2.7·§3·§3.2·§4.1·§4.5·§4.7·§5·§6.1·§7.1·§12·§14), Q1(b) 옵트인 항목은 "미착수(조건부)"로 표기했고, Check에서 찾은 설계 사각 G-M1~G-M3·BS5~BS8의 조치를 적었다. Gap 분석: `docs/03-analysis/ai-gateway-oidc-migration.analysis.md`.

## 0. 설계 결정 요약

| # | 쟁점 | 결정 | 근거 |
|---|---|---|---|
| Q1 | Gemini 3순위 | **(a) 직접 호출 유지.** Gateway 모드에서도 `GEMINI_API_KEY`가 있을 때만 체인에 들어가고, 최종 보고에 "잔존 직접 호출"로 명시한다. (b) OpenAI 호환 경로 전환은 `GATEWAY_GEMINI_MODEL=<google/슬러그>` 옵트인으로 설계만 둔다(§4.6) — **사용자가 슬러그를 정하기 전에는 켜지 않는다.** v0.3: 사용자 결정 "권장대로"(a 유지)로 **(b)는 미착수**. | `gemini-pro-latest`에 대응하는 Gateway 슬러그가 없다(`/v1/models` 실측). 모델을 바꾸지 않고는 전환이 불가능하고, 임의 대체는 금지 제약이다. Gemini 선불이 소진돼 현재도 실질 비활성이라 전환 지연의 손실이 없다. |
| Q2 | 크레딧 0 | (a) **Preview까지만** 진행하고 프로덕션 스위치는 켜지 않는다. 잔액 확인·충전은 사용자 작업으로 보고한다. | 구매·자동 충전은 승인 범위 밖. 크레딧 없는 프로덕션 전환은 전 답변을 402로 만든다. |
| Q3 | 토큰 주입 지점 | (a) **미들웨어가 헤더를 contextvar에 두고, `get_config()`가 요청별로 바인딩된 `AppConfig`를 돌려준다.** 바인딩 시점에 토큰을 읽어 **객체에 고정**한다(contextvar는 요청 스레드에서 한 번만 읽는다). | `get_config()` 호출 8곳과 `config_factory` 주입(관리자 라우터)이 시그니처 변경 없이 모두 덮인다. `ThreadPoolExecutor`(Self-RAG·검색)와 raw `threading.Thread`(Gemini idle 감시)는 contextvar를 상속하지 않으므로, 토큰은 contextvar가 아니라 `config` 객체에 실려야 스레드로 따라간다. |
| Q4 | 슬러그 변환 지점 | (a) **SDK 경계 프록시.** 바인딩된 클라이언트가 `messages.create/stream`·`chat.completions.create`·`embeddings.create`의 `model=`만 슬러그로 바꾼다. 호출부 코드는 무변경. | 벤더 ID를 읽는 코드가 넷이다 — `_CLAUDE_VERSION_RE`(하이픈 표기), `_CLAUDE_TOOL_NO_FORCE`(모델별 기억), 관리자 저장값, `metadata.llm.model`. 상류에서 바꾸면 `supports_effort("anthropic/claude-opus-5.5")`가 거짓이 되어 effort가 빠지고 읽기 타임아웃 폴백이 재발한다. 호출부 10곳을 손보는 (b)는 관리자 테스트 호출이 "답변 경로 함수 그대로"여야 한다는 규칙과도 어긋날 여지가 있다. |
| Q5 | 관리자 모델 목록 | (a) **카탈로그 기반.** Gateway 모드의 `fetch_raw_models`는 `/v1/models/catalog`에서 벤더별 항목을 뽑아 **providerModelId(벤더 ID)** 로 보인다. 실패 시 정적 표. | 벤더 `models.list`는 OIDC 토큰으로 호출할 수 없다. 카탈로그에서만 고르면 미해결 슬러그(R4)가 저장되는 일이 없다. |
| Q6 | 로컬 토큰 파일 | `vercel env pull .env.vercel.local --environment development` → `config.py`가 그 파일을 **`override=False`로 추가 로드.** | `.env`를 덮으면 로컬 키·설정이 전부 Vercel development 값으로 바뀐다. `.gitignore`의 `.env*`가 이미 제외한다. |
| D7 | 인증 실패 동작 | Gateway 모드 + 토큰 없음 = `GatewayAuthError`(RuntimeError 하위)를 **호출 시점**에 올린다. `get_config()`·`/api/health`·관리자 로그인은 영향 없음. 제공자 키로 가는 분기는 없다. | 제약 3. 콜드 인스턴스의 health가 토큰 없이도 떠야 Vercel 배포 검사가 통과한다. |
| D8 | 전송 스위치 | `LLM_TRANSPORT` 환경변수, 값 `gateway`·`direct`, 기본 `direct`. **Vercel env에만 두고 로컬 `.env`에는 넣지 않는다**(로컬 Gateway 시험은 인라인 env). | 오프라인 스크립트가 `AppConfig.from_env()`를 import하는 경우가 있어 `.env`에 넣으면 수집·평가가 Gateway 토큰을 요구한다. |
| D9 | Cohere 경로 | `rag.rerank_results`가 `cohere_api_key`에 더해 `cohere_base_url`·`model`을 받는다. 바인딩이 `cohere_api_key=토큰`, `cohere_base_url=Gateway`를 채우고 모델은 `cohere/rerank-v3.5`. | Cohere SDK는 호출마다 `ClientV2`를 만드는 현행 구조라 프록시가 필요 없다. 재정렬은 Cohere 호환 표면(`/v2/rerank`)만 지원한다. |
| D10 | 관측 | `metadata.llm.transport`(`gateway`·`direct`) 추가, `llm_outcome` 로그에 `transport=` 추가. 폴백 감시(`check_llm_fallback.py`)는 무변경. | 증거 요구(Plan §8). 토큰·키는 어디에도 쓰지 않는다. |

## 1. 현황 요약과 변경 경계

변경이 닿는 파일과 닿지 않는 파일을 먼저 가른다.

| 구분 | 파일 | 변경 |
|---|---|---|
| 신규 | `app/core/gateway_auth.py` | 토큰 contextvar·헤더 상수·`GatewayAuthError`·`current_token()` |
| 신규 | `app/core/llm_transport.py` | 전송 모드 판정, 클라이언트 생성, 요청별 바인딩(`bind`), SDK 경계 프록시, 슬러그 매핑, 카탈로그, Cohere 클라이언트 |
| 수정 | `app/config.py` | `AppConfig` 필드 3개 추가, `from_env()`가 모드에 따라 클라이언트를 만든다, `.env.vercel.local` 추가 로드 |
| 수정 | `api/index.py` | `_security_headers` 미들웨어에서 OIDC 헤더 캡처, `get_config()`가 `llm_transport.bind()` 반환, `metadata.llm.transport` 전달 |
| 수정 | `app/core/rag.py` | `rerank_results(…, cohere_base_url=None, model=None)` 인자 추가와 호출부(`pipeline.py`) 전달 |
| 수정 | `app/core/model_settings.py` | `fetch_raw_models` Gateway 분기(카탈로그) |
| 수정 | `app/core/pipeline.py` | `conv_metadata["llm"]["transport"]`·로그 1줄, rerank 호출 인자 전달 |
| 수정 | `check_env.py`, `.env.example`, `CLAUDE.md` | 환경변수·운영 절차 |
| 수정(v0.3) | `app/core/llm_gateway.py` | 강제 tool_choice 자가치유 — Gateway의 200 + 도구 미호출 응답을 400과 같은 신호로(V-1 편차), 실측 모델 선등록 `_CLAUDE_TOOL_NO_FORCE_KNOWN`(Check G-M1). 호출 형태 자체는 무변경 |
| 수정(v0.3) | `eval_retrieval.py`, `eval_colloquial.py` | `rerank_results`에 `cohere_base_url` 전달(Check G-M2) |
| 신규 테스트 | `test_llm_transport.py` + `.github/workflows/tests.yml` 등록 | §7 |
| **무변경** | `pipeline.py::_stream_claude/_stream_openai/_stream_gemini`, `llm_gateway.py`의 SDK 호출 형태 10곳, `case_match.py`, `citation_relevance.py`, `legal_rule_store.py`, `api/model_settings.py::run_test_call`, `requirements.txt` | 호출 형태·SDK 버전 불변(제약 4·5) |

## 2. 전송 계층(`app/core/llm_transport.py`)

### 2.1 모드와 상수

```python
GATEWAY_URL = "https://ai-gateway.vercel.sh"          # Anthropic 호환·Cohere 호환
GATEWAY_OPENAI_URL = GATEWAY_URL + "/v1"              # OpenAI 호환(chat·embeddings·models)
MODES = {"gateway", "direct"}
def transport_mode() -> str:                           # v0.3 정정: 모듈 상수가 아니라 호출 시점 함수(테스트가 env로 바꾼다)
    mode = os.getenv("LLM_TRANSPORT", "direct").strip().lower()
    return mode if mode in MODES else "direct"
def is_gateway(config) -> bool: return getattr(config, "transport", "direct") == "gateway"
```

모듈 import 시 네트워크를 쓰지 않는다(카탈로그는 지연 로드). `from_env()`가 `transport_mode()`를 `AppConfig.transport`에 복사하고, 그 뒤로는 전부 `config.transport`(`is_gateway(config)`)를 본다 — `metadata.llm.transport`도 그 값이다.

### 2.2 클라이언트 생성(`make_gateway_clients()` — v0.3 명칭 정정)

| 모드 | OpenAI | Anthropic |
|---|---|---|
| direct | `OpenAI(api_key=OPENAI_API_KEY)` (현행) | `anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)` (현행) |
| gateway | `OpenAI(api_key=_PLACEHOLDER, base_url=GATEWAY_OPENAI_URL)` | `anthropic.Anthropic(api_key=_PLACEHOLDER, base_url=GATEWAY_URL)` |

`_PLACEHOLDER = "oidc-bound-per-request"` — 실제 요청에 절대 나가지 않는다(바인딩이 `with_options(api_key=token)`으로 덮고, 바인딩 없는 클라이언트는 프록시 밖으로 노출되지 않는다). Gateway 모드에서 `from_env()`는 `OPENAI_API_KEY`·`ANTHROPIC_API_KEY`를 **읽지 않는다**(클래스 상수 `_REQUIRED_KEYS`는 direct 목록으로 두고 gateway는 `from_env()` 안의 지역 분기 `required = ["PINECONE_API_KEY"]`로 간다 — 동작 동일, T2가 고정). `COHERE_API_KEY`도 읽지 않는다. direct 분기는 `from_env()` 안에 현행 그대로 남고 gateway 분기만 `llm_transport.make_gateway_clients()`가 만든다(v0.3 — 두 모드 공용 `make_clients()`는 구현하지 않았다).

SDK 인증 헤더: OpenAI SDK는 `api_key`를 `Authorization: Bearer`로, Anthropic SDK는 `x-api-key`로 보낸다. Gateway Anthropic 호환 표면은 둘 다 받는다(마이그레이션 문서). `anthropic` 0.x의 `auth_token=`(Bearer) 대안은 V-2에서 확인하고, 기본은 `api_key`로 간다.

### 2.3 요청별 바인딩(`bind(config) -> AppConfig`)

```python
def bind(config):
    if not is_gateway(config):
        return config                                   # direct: 그대로(바이트 동일 동작)
    token = gateway_auth.current_token()                # 헤더 contextvar → VERCEL_OIDC_TOKEN → AI_GATEWAY_API_KEY, 없으면 None
    return dataclasses.replace(
        config,
        claude_client=_Bound(config.claude_client, "anthropic", token),
        openai_client=_Bound(config.openai_client, "openai", token),
        cohere_api_key=token,                           # D9 — rerank_results가 ClientV2(api_key=…)
        cohere_base_url=GATEWAY_URL,
    )
```

- `dataclasses.replace`는 얕은 복사라 Pinecone·Supabase 핸들은 공유된다. 비용은 객체 하나.
- `with_options(api_key=…)`는 SDK의 `copy()`로, **httpx 연결 풀을 공유**하는 새 클라이언트를 만든다(두 SDK 모두 `http_client=self._client`를 넘긴다). 전역 연결·요청별 토큰이 동시에 성립하는 이유다. V-3에서 두 SDK 버전(실행본)으로 재확인한다.
- 토큰이 `None`이면 바인딩은 성공하되 프록시의 첫 사용에서 `GatewayAuthError`가 난다(D7).

### 2.4 SDK 경계 프록시(`_Bound`)

호출부가 쓰는 표면만 감싼다. 전수 조사에서 Anthropic·OpenAI 호출은 **전부 `.with_options(...)`를 먼저 부른다**(§Plan 2.2) — 그래서 프록시가 지켜야 할 계약은 다섯 메서드다.

```python
class _Bound:
    __slots__ = ("_inner", "_vendor", "_token", "_authed")              # _authed: with_options를 거쳤는가(v0.3 기록)
    def __init__(self, inner, vendor, token, authed=False): ...
    def __repr__(self): return f"<GatewayBound {self._vendor} authed={self._authed}>"   # 토큰·키를 절대 포함하지 않는다
    def with_options(self, **kw):
        if not self._token: raise GatewayAuthError("Gateway 모드인데 OIDC 토큰이 없다 — x-vercel-oidc-token 헤더 또는 VERCEL_OIDC_TOKEN")
        kw.pop("api_key", None)                                         # 호출부가 넘긴 키는 버린다 — 우회 방지(v0.3 기록)
        return _Bound(self._inner.with_options(api_key=self._token, **kw), self._vendor, self._token, authed=True)
    @property
    def messages(self):   return _Methods(self._inner.messages, self._vendor, ("create", "stream"))
    @property
    def chat(self):       return _Namespace(completions=_Methods(self._inner.chat.completions, self._vendor, ("create",)))
    @property
    def embeddings(self): return _Methods(self._inner.embeddings, self._vendor, ("create",))
    @property
    def models(self):     raise GatewayUnsupportedError("Gateway 모드에서는 벤더 models.list를 쓰지 않는다 — llm_transport.catalog_models()")
                          # v0.3 정정: 인증 오류가 아니라 '미지원 표면'이라 별도 예외 클래스(RuntimeError 하위)
```

`_Methods.create/stream(**kw)`은 `kw["model"] = to_slug(vendor, kw["model"])`만 하고 inner로 넘긴다. `messages.stream`은 SDK의 컨텍스트 매니저를 **그대로 반환**한다(`with … as stream` 계약 유지). `with_options`를 거치지 않고 `messages`를 쓰면 토큰이 없는 inner로 가므로 — 현행 코드에는 그런 호출이 없고(T1), 프록시의 `messages/chat/embeddings`는 `with_options` 뒤에서만 의미가 있다. 안전을 위해 `_Bound`는 `with_options`를 거치지 않은 상태(`_token`만 있고 inner에 api_key가 안 들어간 상태)를 구분하는 플래그를 두고, 그 상태에서 메서드 접근 시 `with_options()`를 자동으로 한 번 끼운다. 구현은 `_authed` 플래그가 그것이다(테스트 "직접 접근 자동 삽입").

`_available(config, provider)`(`llm_gateway.py:84`)는 `claude_client is not None`만 보므로 프록시에서도 참이다.

### 2.5 슬러그 매핑(`to_slug(vendor, model)`)

> **Do에서 순서를 바꿨다(v0.2)**: 정적 표 → 카탈로그. 정적 표가 현역 모델을 전부 덮으므로 답변 경로 첫 호출에 카탈로그 왕복(최대 10초)을 더하지 않는다. 카탈로그는 관리자가 새로 고른 모델을 위한 폴백이다.

1. 입력에 이미 `/`가 있으면 슬러그로 보고 그대로 둔다(관리자가 카탈로그에서 고른 값·옵트인 Gemini 슬러그).
2. 정적 표 `STATIC_SLUGS`:
3. 카탈로그(`catalog()`, §2.6) — 실측 응답은 `{"models": [{"slug", "providers": [{"provider", "providerModelId", ...}]}]}`이고 `type`은 `GET /v1/models`(`id`·`type`·`name`)에 있어 둘을 합친다. `provider == vendor and providerModelId == model`인 항목의 `slug`.

정적 표:

| vendor | 벤더 ID → 슬러그 |
|---|---|
| anthropic | `claude-opus-5-5 → anthropic/claude-opus-5.5` · `claude-sonnet-5-5 → anthropic/claude-sonnet-5.5` · `claude-sonnet-5 → anthropic/claude-sonnet-5` · `claude-haiku-5-5 → anthropic/claude-haiku-5.5` · `claude-opus-5 → anthropic/claude-opus-5` |
| openai | `gpt-6-sol → openai/gpt-6-sol` · `o3 → openai/o3` · `text-embedding-3-small → openai/text-embedding-3-small` |
| cohere | `rerank-v3.5 → cohere/rerank-v3.5` |

4. 둘 다 실패하면 `UnsupportedModelError(vendor, model)`(RuntimeError 하위). **규칙 기반 추측(하이픈→점) 변환은 두지 않는다** — 제약 4. 오류는 호출부의 기존 예외 처리로 흘러 답변 경로는 다음 제공자, 보조 단계는 생략, 관리자 테스트는 실패 메시지로 끝난다.

~~`from_slug(slug) -> (vendor, model)`~~ — **v0.3 삭제.** 카탈로그가 providerModelId를 직접 주고 `metadata.llm.model`은 상류 벤더 ID라 역변환이 필요한 곳이 없다(Check F9).

### 2.6 카탈로그(`catalog()`)

- `GET {GATEWAY_URL}/v1/models/catalog`, 타임아웃 10초, `Authorization: Bearer <현재 토큰>`(V-4: 인증 없이도 200). 결과를 **프로세스 안 1시간 캐시**(Vercel 인스턴스 수명과 비슷하다). 실패는 WARNING 1줄 + 60초 실패 캐시(`CATALOG_FAIL_TTL`) + 빈 목록(정적 표로 동작).
- **v0.3**: 네트워크는 **잠금 밖**에서 탄다 — 잠금을 쥔 채 최대 20초를 기다리면 정적 표에 없는 모델을 해석하는 답변 경로의 다른 스레드가 그 뒤에 줄을 섰다(Check BS6, T15). `GET /v1/models`(type·name·`released`)는 실패해도 슬러그 표를 살린다(type 필터·출시일 정렬만 빠진다).
- 필드는 V-4 실측으로 고정: 카탈로그는 `slug`·`providers[].provider/providerModelId`, `/v1/models`는 `id`·`type`·`name`·`released`(출시일 epoch, `created`는 전 모델 동일 상수). HTTP는 `httpx`(두 SDK가 설치하는 간접 의존성, `pipeline.py`도 이미 쓴다 — v0.3 정정, `requests`가 아니다).
- 임베딩·재정렬 슬러그는 `type`이 `embedding`·`reranking`인 항목이라 텍스트 목록에서 걸러낸다. 관리자 목록의 `created`는 `/v1/models`의 `released`다(§4.5).

### 2.7 Cohere

```python
def rerank_client(api_key: str, base_url: str | None):
    import cohere
    return cohere.ClientV2(api_key=api_key, base_url=base_url) if base_url else cohere.ClientV2(api_key=api_key)
def rerank_model(base_url: str | None, model: str) -> str:
    return to_slug("cohere", model) if base_url else model
```

`rag.rerank_results(hits, query, cohere_api_key, top_n, …, cohere_base_url=None, model=None)` — 내부의 `cohere.ClientV2(api_key=cohere_api_key)`를 `rerank_client(cohere_api_key, cohere_base_url)`로, `model=RERANK_MODEL`을 `rerank_model(cohere_base_url, model or RERANK_MODEL)`로 바꾼다. 호출부(`pipeline.py`의 rerank 호출 **2지점** — 정상·wider. 무키 폴백은 rerank를 부르지 않는다, v0.3 정정)는 `cohere_base_url=config.cohere_base_url`을 추가로 넘긴다. Cohere SDK는 `Authorization: Bearer`로 보내고 `{base_url}/v2/rerank`를 친다(V-5).

Gateway 모드에서 토큰이 없으면 `config.cohere_api_key`가 `None` → 기존 `if not hits or not cohere_api_key: return _finalize(hits)` 경로로 **재정렬 없이** 진행한다. 이것은 "제공자 키로 몰래 우회"가 아니라 현행의 Cohere 미설정 폴백(코사인 순서)과 같은 동작이다. ~~`metadata.llm.transport_warnings=rerank_no_token`~~ — **v0.3 삭제**: 토큰이 없으면 임베딩·LLM이 먼저 `GatewayAuthError`로 실패해 기록할 대화 자체가 남지 않는다(Check H7).

**규칙(v0.3, Check G-M2)**: `config.cohere_api_key`를 넘기는 `rerank_results` 호출부는 **반드시 `cohere_base_url=config.cohere_base_url`도 넘긴다.** gateway 모드에서 그 키는 OIDC 토큰이라, base_url 없이 부르면 토큰이 Cohere 자체 호스트로 Bearer 송신된다(401 뒤 코사인 폴백 — 조용하다). `from_env()`가 환경 토큰으로 바인딩하므로(§3.2) 평가 스크립트도 해당된다 — `eval_retrieval.py`·`eval_colloquial.py`가 그랬고, T13(AST 검사)이 pipeline 2곳·eval 2곳을 고정한다.

## 3. 인증(`app/core/gateway_auth.py`)

```python
HEADER = "x-vercel-oidc-token"
_REQUEST_TOKEN: ContextVar[str | None] = ContextVar("vercel_oidc_token", default=None)
class GatewayAuthError(RuntimeError): ...
def capture(headers) -> Token:          # 미들웨어가 호출. 헤더가 없으면 None을 set한다(이전 요청 값이 남지 않게)
def release(token): _REQUEST_TOKEN.reset(token)
def current_token() -> str | None:
    return _REQUEST_TOKEN.get() or os.environ.get("VERCEL_OIDC_TOKEN") or os.environ.get("AI_GATEWAY_API_KEY") or None
```

우선순위와 용도:

| 순위 | 출처 | 어디서 | 비고 |
|---|---|---|---|
| 1 | 요청 헤더 `x-vercel-oidc-token` | Vercel 함수(Preview·Production) | 요청마다 새 토큰. 만료 걱정 없음 |
| 2 | `VERCEL_OIDC_TOKEN` | 로컬 개발(`vercel env pull`) | 12시간 유효. 만료 시 Gateway 401 → `GatewayAuthError`가 아니라 SDK 인증 오류로 그대로 드러난다. **v0.3**: 별도 안내 메시지는 두지 않는다 — 로컬 전용 상황이고 `check_env.py`·`GatewayAuthError` 문구가 재pull 절차를 이미 안내한다(Check I7) |
| 3 | `AI_GATEWAY_API_KEY` | CI 등 Vercel 밖(선택) | **프로덕션 Vercel env에는 두지 않는다**(장기 키 금지 요구). 있으면 우선한다는 Gateway 규약과 달리 여기서는 마지막 폴백으로 둔다 — 프로덕션에서 실수로 남은 키가 OIDC를 가리지 않게 |

### 3.1 미들웨어

`api/index.py::_security_headers`(기존 `@app.middleware("http")`)의 앞에 두 줄을 더한다 — `tok = gateway_auth.capture(request.headers)` / `try: response = await call_next(request) finally: gateway_auth.release(tok)`. Starlette `BaseHTTPMiddleware`는 `call_next`를 별도 태스크로 돌리는데 **태스크 생성 시 contextvar가 복사**되므로 엔드포인트와 `StreamingResponse` 반복자(스레드풀 `iterate_in_threadpool`은 anyio가 context를 복사)에서 보인다. 새 미들웨어를 추가하지 않고 기존 것에 붙이는 이유는 SSE 경로에서 이미 동작이 검증된 계층을 늘리지 않기 위해서다.

### 3.2 바인딩 시점

`api/index.py::get_config()`:

```python
def get_config() -> AppConfig:
    global _config
    if _config is None: _config = AppConfig.from_env()
    return llm_transport.bind(_config)
```

엔드포인트 본문(요청 스레드, contextvar 유효)에서 호출되므로 토큰이 그 시점에 객체로 고정된다. 이후 `process_question(…, config, …)`·Self-RAG `ThreadPoolExecutor`·Gemini idle 스레드·`PineconeEvidence(config.pinecone_index, config.openai_client, …)` 모두 바인딩된 객체를 받는다. `api/model_settings.py::build_model_router(config_factory=get_config)`도 자동으로 요청별 바인딩을 받는다.

**환경 토큰 바인딩(v0.3 추가 — 구현 X1)**: `from_env()`도 끝에서 `llm_transport.bind(config)`를 돌려준다. 요청 밖에서 쓰는 CLI·평가 스크립트가 로컬 `VERCEL_OIDC_TOKEN`·CI `AI_GATEWAY_API_KEY`로 동작하게 하기 위해서다. 요청 경로는 `get_config()`가 헤더 토큰으로 **다시** 바인딩하고(`_unwrap()`이 이중 바인딩을 푼다), 그래서 환경 토큰 만료는 프로덕션에 영향이 없다. 위험: 그 바인딩이 `cohere_api_key`에 토큰을 넣으므로 `rerank_results`를 `cohere_base_url` 없이 부르는 스크립트는 토큰을 Cohere로 보낸다(§2.7 규칙·T13). 토큰이 필요한 곳은 contextvar가 아니라 `llm_transport.bound_token(config)`로 바인딩 객체에서 꺼낸다(관리자 목록 §4.5, Check BS5·T14).

### 3.3 토큰 취급 규칙(테스트 T7·T8이 고정)

- 어떤 로그·예외 메시지·`metadata`·`repr`에도 토큰이 들어가지 않는다. SDK 예외는 응답 본문만 담지만, 우리가 만드는 메시지에는 길이조차 적지 않는다.
- `check_env.py`는 `VERCEL_OIDC_TOKEN`·`AI_GATEWAY_API_KEY`를 "설정됨/미설정"으로만 표시한다(현행 REQUIRED 출력의 `val[:8]` 접두 노출은 **이 키들에는 적용하지 않고**, 기존 키들의 접두 출력도 이번에 제거한다 — 제약 2).
- `.env.vercel.local`은 `.gitignore`의 `.env*`에 걸린다(확인 완료). 문서에는 파일 이름만 적는다. `config.py`와 `check_env.py`는 같은 파일을 **저장소 루트 절대경로**로 읽는다(cwd 상대경로면 다른 디렉터리에서 실행할 때 조용히 빠진다 — v0.3, Check BS8).
- `AppConfig`의 비밀 필드(`gemini_api_key`·`law_api_key`·`cohere_api_key`)는 `field(repr=False)`다 — `repr(config)`가 바인딩된 토큰을 테스트 실패 메시지에 찍은 것이 계기(v0.3 기록).

## 4. 경로별 변경

### 4.1 Claude(답변·보조 텍스트·도구)

호출 코드 무변경. Gateway 모드에서 흐름: `config.claude_client`(프록시) → `.with_options(timeout=…, max_retries=0)` → 토큰 주입 → `.messages.stream(model="claude-opus-5-5", output_config=…, thinking=…)` → 프록시가 `model="anthropic/claude-opus-5.5"` → Gateway `/v1/messages`.

보존을 확인할 것(V-1): `thinking={"type":"adaptive","display":"summarized"}`·`output_config.effort`·`tool_choice`(auto + `disable_parallel_tool_use`, 강제 `any`의 400 문구 "tool_choice … not supported"가 Gateway를 거쳐도 같은지 — `_is_forced_tool_choice_rejection`이 그 문구를 본다)·`stop_reason=max_tokens` 전달·`strict` 도구·SSE `thinking` 이벤트의 하트비트 간격(≤ 6.6초 실측 기준). 하나라도 깨지면 **그 경로는 전환 보류**하고 보고한다(모델·설정을 바꿔 맞추지 않는다).

**v0.3 — Gateway 편차와 대응(V-1)**: Gateway는 5.5 세대의 강제 `tool_choice`를 400이 아니라 **200 + 도구 미호출**(추론·텍스트, by-name은 `max_tokens`까지 생성)로 돌려준다. `_claude_tool`은 그 응답도 400과 같은 신호로 보고 auto+지시로 재시도·기억한다(`refusal`은 기억하지 않는다). 그런데 두 신호 모두 '한 번 보내 봐야' 배우므로 **콜드 인스턴스마다** 의도분석 1회를 버렸고(Check G-M1 — 프로덕션 콜드 TTFT 43.1초에 포함, `INTENT_TIMEOUT` 12초 안에 응답이 없으면 기억조차 못 한다), 실측된 모델(`claude-opus-5-5`·`claude-sonnet-5-5`·`claude-fable-5-1`)은 `_CLAUDE_TOOL_NO_FORCE_KNOWN`으로 **선등록**해 첫 호출부터 auto로 간다. 목록 밖 모델은 종전처럼 실측으로 배운다. 회귀 `test_llm_fallback.py::test_claude_known_no_force_models_skip_forced_attempt`.

### 4.2 OpenAI(답변·보조·도구)

무변경. `chat.completions.create(model="gpt-6-sol", max_completion_tokens=…, stream=True)` → `openai/gpt-6-sol`. `_openai_tool`의 gpt-6-sol 400 → `reasoning_effort="none"` 재시도 분기가 Gateway 400 문구에서도 같은 조건에 걸리는지 V-6. `_stream_openai`의 `model or os.getenv("OPENAI_CHAT_MODEL", …)` 폴백은 벤더 ID라 프록시가 변환한다.

### 4.3 임베딩(5곳)

무변경. `embeddings.create(model="text-embedding-3-small", input=…)` → `openai/text-embedding-3-small`. 같은 모델·1536차원이라 Pinecone 벡터 호환. L1에서 같은 문장 3개를 direct·gateway로 임베딩해 코사인 ≥ 0.999를 확인한다(제공자 측이 같은 모델이면 1.000에 가깝다. 0.999 미만이면 전환 보류). 응답 형식(`resp.data[0].embedding`)은 OpenAI 호환 규약.

### 4.4 Cohere 재정렬

§2.7. L2에서 같은 질의·문서 20건의 상위 5 순서와 점수(소수 셋째 자리)를 direct와 대조한다.

### 4.5 관리자 모델 목록·테스트

- `fetch_raw_models(provider, config)`: `if llm_transport.is_gateway(config) and provider in ("claude", "openai"): return llm_transport.catalog_models(provider, llm_transport.bound_token(config))` 분기를 **맨 앞**에 둔다. 반환 형식은 현행과 같은 `[{"id": 벤더ID, "label": …, "created": <출시일 epoch>}]`이고 `id`는 카탈로그의 providerModelId. **v0.3**: `created`는 `/v1/models`의 `released`다(같은 응답의 `created`는 전 모델이 같은 상수) — 날짜가 없으면 `select_latest`가 ID 역순으로 떨어져 Claude 목록이 sonnet 계열만 남고 "벤더별 최신 3개" 계약이 깨졌다(Check G-M3, T11). 토큰은 contextvar가 아니라 바인딩 객체에서 꺼낸다(Check BS5, T14). `_dedupe_snapshots`·`LIST_LIMIT`는 그대로 적용. Gemini는 Q1(a)라 현행 `genai.list_models` 분기 유지.
- 테스트 호출(`run_test_call` → `_stream_*`)은 프록시를 거쳐 Gateway로 간다. 코드 무변경이고, 그래서 "테스트는 통과, 답변은 폴백" 유형의 어긋남이 생기지 않는다.
- 저장 게이트(HMAC 토큰)는 벤더 ID 기준이라 무변경.

### 4.6 Gemini — 잔존 직접 호출(Q1 a) + 옵트인(b)

**기본(a)**: Gateway 모드에서도 `_stream_gemini`·`_gemini_text`·`_gemini_tool`·`fetch_raw_models("gemini")`는 `config.gemini_api_key`로 Google에 직접 간다. `provider_chain`은 `GEMINI_API_KEY`가 있을 때만 Gemini를 넣는 현행 규칙 유지. 최종 보고 "잔존 직접 호출" 표에 적는다. 프로덕션 Gemini 선불이 소진돼 지금도 실질 비활성이라, 이 결정으로 잃는 기능은 없다.

**옵트인(b) 설계 — 미착수(v0.3: 사용자가 슬러그를 정하지 않아 조건 미충족, 후속 §13 ⑤. 아래는 설계만 남긴다)**: `GATEWAY_GEMINI_MODEL=google/<모델>` 설정 시 — `_available(config,"gemini")`가 참, Gemini 모델 해석값은 그 슬러그, 그리고 세 Gemini 함수가 **OpenAI 형태 함수에 위임**한다(`_stream_gemini → _stream_openai(model=슬러그)`, `_gemini_text → _openai_text`, `_gemini_tool → _openai_tool`). 프록시는 `/`가 든 모델을 그대로 통과시킨다. 확인할 것: OpenAI 호환 표면의 Gemini가 `developer` 역할·`max_completion_tokens`·function calling을 받는지(V-7). `_coerce`(정수→실수 보정)는 OpenAI 경로에서는 불필요. 관리자 Gemini 목록은 카탈로그의 `google/*`(저장값도 슬러그).

### 4.7 관측

`pipeline.py`의 `conv_metadata["llm"]`에 `transport` 추가(값은 `config.transport` — v0.3 정정), `llm_outcome` 로그 포맷에 `transport=%s` 추가. `check_llm_fallback.py`는 `fallback·empty·intent_provider`만 보므로 무변경 — Gateway 장애는 전 제공자 실패(미저장)로 나타나 **기존 사각**(메모리 `project-llm-fallback-alert`)에 들어간다는 점을 보고에 적는다.

## 5. `AppConfig`·`from_env()`

```python
@dataclass
class AppConfig:
    ...                                   # 기존 필드 유지
    transport: str = "direct"             # from_env()가 llm_transport.transport_mode()를 복사(테스트가 직접 지정 가능)
    cohere_base_url: str | None = None    # gateway 바인딩이 채운다
    # gateway_gemini_model — Q1(b) 옵트인 필드는 미착수(v0.3). 비밀 필드 3개(gemini/law/cohere 키)는 field(repr=False).
```

`from_env()`:

| 항목 | direct | gateway |
|---|---|---|
| `_REQUIRED_KEYS` | `OPENAI_API_KEY`·`PINECONE_API_KEY`·`ANTHROPIC_API_KEY` | **`PINECONE_API_KEY`만** |
| 클라이언트 | 현행(`from_env` 안) | `llm_transport.make_gateway_clients()` (placeholder + base_url) |
| `cohere_api_key` | `COHERE_API_KEY` | `None`(바인딩이 토큰으로 채움) |
| `gemini_api_key` | `GEMINI_API_KEY` | 같음(Q1 a) |
| 추가 로드 | — | `load_dotenv(<저장소 루트>/.env.vercel.local, override=False)`(파일이 있을 때만, 로컬 전용) |
| 반환(v0.3) | `config` | `llm_transport.bind(config)` — 환경 토큰 바인딩(§3.2) |

`load_dotenv()` 호출은 현행 `config.py:13` 뒤에 한 줄 추가. `override=False`라 `.env`의 모든 값이 우선하고, 토큰만 보강된다.

## 6. 환경변수·문서

### 6.1 환경변수(`.env.example`에 블록 추가, 값은 적지 않는다)

| 변수 | 어디 | 값 | 설명 |
|---|---|---|---|
| `LLM_TRANSPORT` | Vercel Preview → Production | `gateway` | 기본 `direct`. **다음 배포부터 적용** — 설정 뒤 반드시 재배포 |
| `VERCEL_OIDC_TOKEN` | 로컬 `.env.vercel.local` | `vercel env pull`이 기록 | 12시간. 만료 시 재pull. 커밋 금지(`.env*`) |
| `AI_GATEWAY_API_KEY` | CI 등 선택 | — | 프로덕션 Vercel env에는 두지 않는다 |
| ~~`GATEWAY_GEMINI_MODEL`~~ | (Q1 b, 미착수) | — | v0.3: 구현하지 않았다. Gemini는 직접 호출 |
| 기존 `ANTHROPIC_API_KEY`·`OPENAI_API_KEY`·`COHERE_API_KEY` | Vercel env | 유지 | Gateway 모드에서 읽지 않음. 복귀 창(§9) 뒤 **삭제 후보** |

### 6.2 `check_env.py`

`LLM_TRANSPORT`를 읽어 모드별 REQUIRED를 바꾼다. Gateway 모드에서 제공자 키가 설정돼 있으면 "Gateway 모드에서는 쓰이지 않음 — 삭제 후보"로 표시. 모든 키·토큰은 설정 여부만 출력(접두 노출 제거).

### 6.3 CLAUDE.md 갱신안(§14)과 로컬 실행 절차

```bash
vercel link --yes --project laborconsult --scope team_17WaHViTPIKk4lm2qjf3ZvOc   # 1회, .vercel/ 생성(무시됨)
vercel env pull .env.vercel.local --environment development                     # VERCEL_OIDC_TOKEN 포함, 12시간
LLM_TRANSPORT=gateway uvicorn api.index:app --reload --port 5555                 # 로컬 Gateway 시험(인라인 env)
```

## 7. 테스트

### 7.1 오프라인(`test_llm_transport.py`, 네트워크·키 없음, CI 등록)

| # | 단언 |
|---|---|
| T1 | `LLM_TRANSPORT` 미설정·`direct`: `bind(config) is config`, 클라이언트가 SDK 원형, `base_url`이 기본값. 기존 스위트 전부 통과(동작 동일). v0.3: 원형·기본 base_url 단언 추가(Check M1) |
| T2 | gateway: 환경에 `OPENAI_API_KEY=SENTINEL-…`·`ANTHROPIC_API_KEY=SENTINEL-…`를 넣어도 생성된 클라이언트의 `api_key`가 SENTINEL이 아니고, `base_url`이 Gateway. `_REQUIRED_KEYS`에 두 키가 없다 |
| T3 | 프록시: 가짜 inner에 `with_options(timeout=1, max_retries=0).messages.create(model="claude-opus-5-5", …)` → inner가 받은 `api_key`가 토큰, `model`이 `anthropic/claude-opus-5.5`, 그 외 kwargs(`output_config`·`thinking`·`tools`·`tool_choice`) 바이트 동일. `messages.stream`은 inner가 준 객체를 **그대로** 반환 |
| T4 | 토큰 없음: `bind` 성공, `with_options` 호출에서 `GatewayAuthError`. `get_config()`는 예외 없이 반환 |
| T5 | 미해결 모델 `claude-new-7` → `UnsupportedModelError`. 하이픈→점 추측 변환이 없다(`claude-opus-5-5`를 정적 표에서 지운 뒤 호출하면 오류) |
| T6 | 상류 벤더 표기 유지: `_answer_providers(config)`의 `partial.keywords["model"]`에 `/`가 없다. `supports_effort`가 그 값으로 참 |
| T7 | 미들웨어: 헤더 있는 요청에서 `current_token()`이 그 값, 없는 요청에서 `None`(앞 요청 값이 남지 않음). `TestClient`로 `/api/health` 200 |
| T8 | 토큰 비노출: `repr(_Bound)`·`GatewayAuthError` 메시지·캡처한 로그에 토큰 문자열이 없다 |
| T9 | Cohere: gateway 바인딩에서 `rerank_results`가 가짜 `ClientV2`에 `base_url=Gateway`·`api_key=토큰`·`model="cohere/rerank-v3.5"`를 넘긴다. direct에서는 `base_url` 인자 없음·모델 `rerank-v3.5` |
| T10 | 스레드 전달: `ThreadPoolExecutor` 안에서 바인딩된 `config.openai_client.with_options(…)`가 토큰을 쓴다(contextvar 미상속 환경 재현) |
| T11 | 관리자 목록: gateway 모드 `fetch_raw_models("claude")`가 카탈로그(가짜) → providerModelId 목록, 벤더 `models.list` 미호출 |
| T12 | Gemini(Q1 a): gateway 모드에서 `GEMINI_API_KEY` 있으면 체인에 포함·직접 호출, 없으면 제외. (옵트인 위임 단언은 미착수) |
| T13 | (v0.3, Check G-M2) AST: `config.cohere_api_key`를 넘기는 `rerank_results` 호출부는 전부 `cohere_base_url=`을 넘긴다 — pipeline 2곳·eval 2곳 |
| T14 | (v0.3, Check BS5) 관리자 목록 토큰은 바인딩 객체(`bound_token`)에서 — contextvar에 다른 값이 있어도 바인딩 토큰이 간다 |
| T15 | (v0.3, Check BS6) 카탈로그 조회는 잠금 밖에서 돈다 · `/v1/models` 실패 시 슬러그 표 유지 + WARNING |
| T11+ | (v0.3, Check G-M3) `created`가 `released`에서 오고 `select_latest`가 출시일 역순 3개를 고른다 |

기존 스위트 재실행(+ v0.3 추가 회귀 `test_llm_fallback.py::test_claude_known_no_force_models_skip_forced_attempt` — 선등록 모델은 강제 시도 0): `test_llm_fallback.py`(`_cfg()`가 `AppConfig(...)`를 직접 만들므로 새 필드 기본값으로 호환), `test_offline_units.py`, `test_pipeline_wiring.py`, `test_model_settings.py`, `test_abuse_guard.py`, `test_law_api_recovery.py`, `test_kin_accuracy.py`.

### 7.2 Live(로컬, OIDC 토큰, 호출 최소)

| # | 내용 | 호출 수 |
|---|---|---|
| L0 | `GET /v1/credits`(잔액 숫자만 기록)·`GET /v1/models/catalog`(필드명 고정, V-4) | 2 |
| L1 | 임베딩 동일성: 문장 3개 × direct·gateway → 코사인 ≥ 0.999 | 6 |
| L2 | 재정렬 동일성: 질의 1 + 문서 20 × direct·gateway → 상위 5 순서·점수 | 2 |
| L3 | Claude 스트리밍 1회(`run_test_call`와 같은 프롬프트, `claude-opus-5-5`): thinking 하트비트·effort·첫 글자 시간 | 1 |
| L4 | 도구 호출 1회: `analyze_intent` 경로(강제 거절 → auto 자가치유가 Gateway 400 문구에서도 동작) | 1~2 |
| L5 | 전 경로 1질문: `eval_consultation.py --live --case wage-01 --limit 1 --law-mode cache`를 `LLM_TRANSPORT=gateway`로(의도분석·추출·분해·임베딩·재정렬·답변) | 6~8 |

합계 20회 안쪽. 결과는 저장소 밖(`~/DEV/laborconsult_eval/gw/`)에 두고 숫자만 보고에 옮긴다.

## 8. 배포 절차와 증거

| 단계 | 작업 | 확인 |
|---|---|---|
| P0 | 사용자: 크레딧 잔액·BYOK 미등록·팀 AI Gateway 활성 확인(§10). 나: `vercel link`·`env pull`·L0 | 잔액 > 0, 카탈로그 200 |
| P1 | PR(worktree `laborconsult-gw`, 브랜치 `feat/ai-gateway-oidc`), `@codex review`·CodeRabbit, CI 통과 | 오프라인 T1~T12 + 기존 스위트 |
| P2 | Preview env에 `LLM_TRANSPORT=gateway` 추가 → PR 브랜치 재배포(빈 커밋 또는 `vercel redeploy`) → Preview URL에 상담 1·계산 연계 1·SSE 1 | 응답 정상, Gateway 대시보드에 요청 3~5건, `metadata.llm.transport=gateway` |
| P3 | **롤백 리허설**: Preview env를 `direct`로 → 재배포 → 같은 질문 1 → `transport=direct` | 복귀 경로 검증 |
| P4 | 머지(merge commit, 브랜치 보존) → main 자동 배포(아직 Production env는 `direct`라 동작 불변) | 프로덕션 health·1질문 정상 |
| P5 | Production env `LLM_TRANSPORT=gateway` → **재배포**(`vercel redeploy` 또는 빈 커밋) → `vercel inspect --wait` READY | 배포 ID 기록 |
| P6 | 프로덕션 질문 2건(개인정보 없음: 상담 1·계산 1, 같은 IP라 쿼터 2 소모) | SSE 정상, `metadata.llm.transport=gateway`, 폴백 0 |
| P7 | 증거 수집: Gateway 대시보드 요청 로그(모델·토큰·비용), `GET /v1/credits` 전후 차액, Supabase metadata, `check_llm_fallback.py` ✅, 배포 ID | 보고서 §증거 |

## 9. 롤백

| 수단 | 시간 | 조건 |
|---|---|---|
| A. Vercel env `LLM_TRANSPORT=direct` + 재배포 | 3~5분 | 제공자 키가 Vercel env에 남아 있어야 한다 → **복귀 창(배포 후 7일) 동안 키를 지우지 않는다** |
| B. 이전 배포 승격(`vercel promote <이전 배포>` / 대시보드) | 즉시 | 이전 배포(구 코드)는 `LLM_TRANSPORT`를 모르므로 direct로 동작 |
| C. 관리자 화면 | — | 모델·1순위는 벤더 ID 그대로라 무관 |

복귀 창이 끝난 뒤 `ANTHROPIC_API_KEY`·`OPENAI_API_KEY`·`COHERE_API_KEY`의 Vercel env 삭제를 **사용자 승인 하에** 별도 진행(제공자 측 키는 폐기하지 않는다 — 다른 프로젝트·로컬·Actions가 쓴다).

## 10. 사용자 작업·미결

| # | 항목 | 왜 사용자인가 |
|---|---|---|
| U1 | AI Gateway 크레딧 잔액 확인(대시보드 → AI Gateway → Credits). 0이면 충전 여부 결정 | 결제 승인 범위 밖 |
| U2 | BYOK 키가 Gateway에 등록돼 있지 않은지 확인(등록돼 있으면 크레딧 대신 그 키로 과금된다) | 대시보드 설정 |
| U3 | Gemini 3순위 결정 — 직접 호출 유지(기본) / `google/gemini-2.5-pro` 등 슬러그 지정 | 모델 변경은 임의로 못 한다 |
| U4 | Preview 배포에 Deployment Protection이 걸려 있으면 바이패스 토큰 제공 또는 일시 해제 | 프로젝트 설정 |
| U5 | 프로덕션 스위치(P5) 켜는 시점 승인 — Preview 결과 보고 뒤 | 요청문이 승인했지만 R1·R2 결과에 따라 보류될 수 있어 재확인 |

## 11. 비용

토큰 단가는 제공자 정가와 같다(무마크업). 지불처가 Anthropic·OpenAI·Cohere 선불 3곳에서 Vercel 크레딧 1곳으로 바뀐다. Gemini는 (a)면 불변. 임베딩·Pinecone 비용 구조 불변. 무료 $5/월은 해당 모델에만 적용되므로 기대하지 않는다. 테스트 비용은 §7.2 20회·§8 7건 — 상담 1건 평균 입력 30k 토큰 안쪽이라 1달러 미만 수준(정확한 값은 `/v1/credits` 차액으로 보고).

## 12. 검증 항목(Do 첫 작업, 하나라도 실패하면 해당 경로 전환 보류)

**2026-10-28 결과(로컬, OIDC 토큰, 호출 13회·크레딧 잔액 $13.97에서 미세 차감)**

| # | 결과 |
|---|---|
| V-1 | ✅ 스트리밍 + `output_config.effort` + `thinking adaptive/summarized` 통과(첫 글자 1.85초, 모델 에코 `anthropic/claude-opus-5.5`). ✅ `tool_choice auto + disable_parallel_tool_use + 지시` → tool_use 반환. ⚠️ **편차**: 강제 `tool_choice any/tool`이 직접 API에서는 400인데 Gateway에서는 **200 + 도구 미호출**(thinking·text, by-name은 stop `max_tokens`)로 온다 → `_claude_tool`의 자가치유 트리거(400 문구)가 불발하고 매 질문 OpenAI 폴백이 된다. **대응**: 강제 응답에 tool_use가 없으면 400과 같은 신호로 `_CLAUDE_TOOL_NO_FORCE`에 기억하고 auto+지시로 재시도(비용: **인스턴스별** 첫 1회 — v0.3: 실측 모델 선등록으로 0회, §4.1). 회귀 `test_llm_fallback.py::test_claude_forced_tool_choice_accepted_without_tool_use_falls_back_to_auto` |
| V-2 | ✅ anthropic 0.120.2 `copy()`가 `api_key`·`auth_token`·`base_url`을 받는다 |
| V-3 | ✅ anthropic 0.120.2·openai 2.53.0 `copy()`가 `http_client=self._client`로 연결 풀 공유 |
| V-4 | ✅ `/v1/models/catalog` 인증 없이 200(469개). 필드는 `slug`·`providers[].provider/providerModelId`; `type`은 `/v1/models`(498개: language 320·embedding 28·reranking 9 …). `cohere/rerank-v3.5`의 providers에는 `cohere`가 없고 `bedrock`만 있어 정적 표가 담당 |
| V-5 | ✅ cohere 7.0.8 `ClientV2(api_key, base_url)` → `v2/rerank`, `Authorization: Bearer`. 재정렬 상위 5 순서 동일, 점수 차 ≤ 0.0003 |
| V-6 | ✅ `openai/gpt-6-sol` 스트리밍(`developer` 역할·`max_completion_tokens`) 첫 글자 1.31초. 함수 호출 강제가 **첫 시도에 성공**(직접 API의 `reasoning_effort` 400 분기는 Gateway에서 발동하지 않음 — 기존 코드가 두 경우 모두 처리) |
| V-7 | — (Q1 a·옵트인 미착수, 미실시) |
| V-8 | T7(TestClient) 통과 + **실배포에서 확인**(Preview P2·프로덕션 P6: 헤더 토큰으로 Claude 답변·`metadata.llm.transport=gateway` 저장). 로컬 uvicorn 단독 실행은 생략 — 실배포가 더 강한 증거(v0.3 기록) |
| V-9 | ✅ `vercel env pull .env.vercel.local`이 `VERCEL_OIDC_TOKEN` 1개만 쓴다(development env에 다른 변수 없음). 만료 동작은 **미확인**(v0.3 시점) — 만료 시 SDK 401이 그대로 드러나는 설계(§3)이고 로컬 전용이라 Report 전 1회 확인으로 둔다 |
| L1 | ✅ 임베딩 3문장 코사인 0.999999 ×3, 1536차원, 모델 에코 `openai/text-embedding-3-small` |
| L5 | ✅(v0.3 기록) `eval_consultation.py --live --case wage-01 --limit 1`을 `LLM_TRANSPORT=gateway`로 1건: pipeline 성공 1.0·필수 조문 1.0·금지 문구 0(결과는 저장소 밖 `l5.json`). 프로덕션 P6 2건(transport=gateway, Claude opus-5-5, 폴백 0)이 전 경로를 재확인 |


| # | 확인 | 방법 |
|---|---|---|
| V-1 | Anthropic 호환 표면이 `thinking adaptive/summarized`·`output_config.effort`·`tool_choice auto/any`·`disable_parallel_tool_use`·`strict`를 통과시키고 400 문구를 그대로 전달한다 | L3·L4 |
| V-2 | `anthropic` 0.x(실행본 0.120): `with_options(api_key=…)`·`base_url` 동작, `auth_token` 대안 | 로컬 import 확인 + L3 |
| V-3 | 두 SDK의 `with_options`가 httpx 클라이언트를 공유한다(연결 풀) | 소스 확인(`_base_client.copy`) |
| V-4 | `/v1/models/catalog` 인증 요구 여부·필드명 | L0 |
| V-5 | Cohere SDK `ClientV2(base_url=…)`가 `/v2/rerank`를 치고 Gateway가 받는다 | L2 |
| V-6 | OpenAI 호환 표면의 `max_completion_tokens`·`reasoning_effort`·stream·`developer` 역할 | L5 |
| V-7 | (Q1 b일 때만) Gemini OpenAI 호환 경로의 역할·function calling | — |
| V-8 | Starlette 미들웨어 contextvar가 엔드포인트·SSE 반복자에서 보인다 | T7 + 로컬 uvicorn 1회 |
| V-9 | `vercel env pull`이 `VERCEL_OIDC_TOKEN`을 쓰고 12시간 뒤 만료 동작(401 메시지 안내) | L0 |

## 13. 범위 밖·후속

Plan §5 그대로. 후속 후보: ① 복귀 창 뒤 Vercel env 키 삭제(승인 필요) ② Gateway 예산 상한·태그(`feature:chat`) 도입 ③ `check_llm_fallback.py`에 "최근 실사용 0건 + health 정상" 사각 보강 ④ `anthropic` 1.x 대응 ⑤ Gemini 슬러그 전환(U3 결정 시) ⑥ V-9 토큰 만료 실측(v0.3).

## 14. CLAUDE.md 갱신안

- **Environment Variables**: `LLM_TRANSPORT`(기본 direct, gateway는 Vercel env 전용·재배포 필요), `VERCEL_OIDC_TOKEN`(로컬 `vercel env pull`, 12시간), `AI_GATEWAY_API_KEY`(프로덕션 금지). 옵트인 `GATEWAY_GEMINI_MODEL`은 미착수라 적지 않는다(v0.3). Gateway 모드의 필수 키는 `PINECONE_API_KEY`만.
- **Key Conventions**에 항목 하나: "LLM 전송은 `llm_transport.bind()`가 요청별로 묶는다 — `get_config()` 밖에서 전역 `_config`를 직접 쓰지 말 것(토큰이 없는 클라이언트다). 슬러그 변환은 SDK 경계 프록시 한 곳이고 상류는 벤더 ID를 유지한다(`supports_effort`·자가치유 기억·관리자 저장값이 그 표기를 읽는다). 미해결 모델은 임의 대체 없이 오류다. Gateway 모드에서 제공자 키로 가는 분기는 존재하지 않는다(테스트 T2). 재정렬은 Cohere 호환 표면만 지원한다. Gemini는 직접 호출로 남아 있다(별칭 슬러그 없음)."
- **Deployment**: Vercel env 변경 → 재배포 순서, 롤백 A/B, 복귀 창 동안 키 유지. 증거 목록에 `check_llm_fallback.py` 결과·배포 ID(v0.3, Check N2). **Commands**에 로컬 Gateway 인라인 실행(`LLM_TRANSPORT=gateway uvicorn …`, Check L6). **Key Conventions**에 ⑥ rerank 호출부 `cohere_base_url` 규칙·⑦ 관리자 목록 `released`·선등록(v0.3).

## Version History

| 버전 | 날짜 | 변경 |
|---|---|---|
| v0.1 | 2026-10-28 | 최초 작성(Q1~Q6 결정, D7~D10, 검증 V-1~V-9) |
| v0.2 | 2026-10-28 | Do 착수 — §12 검증 결과 기록(V-1 강제 tool_choice 편차와 대응), §2.5 매핑 순서 정적→카탈로그로 변경, 카탈로그 실측 스키마 반영 |
| v0.3 | 2026-10-28 | Check(Gap 93.0%) 반영 — 구현과 어긋난 서술 정정(§1·§2·§3·§4.5·§4.7·§5), `from_slug`·`transport_warnings`·401 안내 삭제, Q1(b) 옵트인 미착수 표기, 사각 조치(G-M1 선등록·G-M2 eval base_url·G-M3 released 정렬·BS5~BS8), §12에 V-8·V-9·L5 기록 |
