# admin-model-settings Design Document

> **Summary**: 벤더별 모델 목록 조회 → 프로덕션 호출 경로로 테스트 → 통과 토큰으로만 저장 → 답변 경로가 60초 캐시로 읽고 실패 시 기본값
>
> **Project**: laborconsult
> **Author**: Claude (with DrunkenZealnut)
> **Date**: 2026-09-30
> **Status**: Implemented (Check 95% — `docs/03-analysis/admin-model-settings.analysis.md`)
> **Planning Doc**: [admin-model-settings.plan.md](../../01-plan/features/admin-model-settings.plan.md)

확정 결정(Plan): 범위 = **답변 모델 3종 + 1순위** · 검증 = **테스트 호출 통과 시 저장** · 반영 = **즉시(60초 캐시)**

---

## 1. Overview

### 1.1 Design Goals

| ID | 목표 |
|---|---|
| G1 | 설정이 없거나 읽기가 실패하면 **지금과 동일하게** 동작한다(기본값 경로 무회귀) |
| G2 | 저장된 모델은 반드시 **프로덕션과 같은 함수·인자**로 한 번 성공한 모델이다 |
| G3 | 설정 읽기가 답변 경로를 막지 않는다(짧은 타임아웃 + fail-open) |
| G4 | 화면·로그·대화 metadata 어디서든 "지금 어떤 모델이 왜(출처) 쓰였는지" 보인다 |

### 1.2 Design Principles

- **테스트 호출은 별도 코드가 아니다.** `_stream_claude/_openai/_gemini`에 `model`을 주입해 그대로 부른다. 테스트용 호출 코드를 따로 두면 실제 호출 방식과 어긋난다 — SDK 1.x 사고(9-27)가 "타임아웃 인자 하나"로 났다.
- **저장 게이트는 서버가 강제한다.** 화면의 버튼 비활성은 편의일 뿐이다. 저장 API는 테스트 통과 시 발급한 서명 토큰이 없으면 거절한다(CAPTCHA HMAC과 같은 방식).
- **출처를 숨기지 않는다.** 해석 결과는 항상 `(값, 출처)` 쌍이다. 출처는 `settings`·`env`·`default` 중 하나다.

---

## 2. Architecture

```
[admin.html "답변 모델"] ─fetch(JWT)─▶ api/model_settings.py (router)
                                       ├─ GET  state      ─▶ model_settings.admin_state()
                                       ├─ GET  models     ─▶ model_settings.list_models(provider)  ─▶ 벤더 API
                                       ├─ POST test       ─▶ pipeline._stream_<p>(…, model=X) → 서명 토큰
                                       ├─ PUT  save       ─▶ 토큰 검증 → RPC answer_model_settings_save (CAS)
                                       └─ POST reset      ─▶ RPC (settings = {})
[pipeline._answer_providers] ─▶ model_settings.resolve()  ─▶ 60초 캐시 ─miss─▶ Supabase(2초 타임아웃)
                                                              └ 실패 → env/상수 기본값
```

### 2.1 Dependencies

| 구성요소 | 의존 | 비고 |
|---|---|---|
| `app/core/model_settings.py` | `storage.make_supabase_client`, `config` 상수 | **pipeline을 import하지 않는다**(순환 방지 — `llm_fallback.py`와 같은 이유). 테스트 호출은 라우터가 pipeline 함수를 주입한다 |
| `api/model_settings.py` | `model_settings`, `pipeline._stream_*`, `require_admin` | `build_model_router(require_admin, config_factory, secret, stream_fns)` 팩토리 — 서명키와 스트리밍 함수를 **주입**받아 pipeline import를 라우터 모듈 밖(`api/index.py`)에 둔다 |

---

## 3. Data Model

### 3.1 설정 문서 (JSONB, 단일 행)

```json
{
  "primary": "claude",
  "models": {
    "claude": {"model": "claude-sonnet-5-5", "tested_at": "2026-09-30T10:00:00Z", "latency_ms": 1840},
    "openai": {"model": "o3", "tested_at": "…", "latency_ms": 3100}
  }
}
```

- 키가 없는 벤더·`primary`는 **기본값 경로**(env → 상수)를 쓴다. `{}` = 전부 기본값 = 리셋.
- 허용 provider: `claude`·`openai`·`gemini`(소문자). 모델 ID 형식 `^[A-Za-z0-9._:/-]{1,100}$`.

### 3.2 DDL — `supabase_model_settings.sql` (신규, 적용 순서 7번째)

```sql
CREATE TABLE IF NOT EXISTS laborconsult.answer_model_settings (
    id          SMALLINT PRIMARY KEY CHECK (id = 1),
    settings    JSONB NOT NULL DEFAULT '{}'::jsonb,
    revision    BIGINT NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by  TEXT
);
INSERT INTO laborconsult.answer_model_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS laborconsult.answer_model_setting_events (
    id          BIGSERIAL PRIMARY KEY,
    revision    BIGINT NOT NULL,
    actor       TEXT,
    before      JSONB NOT NULL,
    after       JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE laborconsult.answer_model_settings       ENABLE ROW LEVEL SECURITY;
ALTER TABLE laborconsult.answer_model_setting_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON laborconsult.answer_model_settings, laborconsult.answer_model_setting_events
    FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON laborconsult.answer_model_settings, laborconsult.answer_model_setting_events TO service_role;

CREATE OR REPLACE FUNCTION laborconsult.answer_model_settings_save(
    expected_revision BIGINT, new_settings JSONB, event_actor TEXT)
RETURNS BIGINT LANGUAGE plpgsql SECURITY DEFINER
SET search_path = laborconsult, pg_temp AS $$
DECLARE current_revision BIGINT; old_settings JSONB;
BEGIN
    IF new_settings IS NULL OR jsonb_typeof(new_settings) <> 'object' THEN
        RAISE EXCEPTION 'INVALID_MODEL_SETTINGS' USING ERRCODE = '22023';
    END IF;
    SELECT revision, settings INTO current_revision, old_settings
      FROM answer_model_settings WHERE id = 1 FOR UPDATE;
    IF current_revision IS NULL OR expected_revision IS DISTINCT FROM current_revision THEN
        RAISE EXCEPTION 'MODEL_SETTINGS_REVISION_CONFLICT' USING ERRCODE = 'PT409';  -- 40001은 PostgREST가 재시도해 멈춘다(Do 단계 실측)
    END IF;
    UPDATE answer_model_settings
       SET settings = new_settings, revision = revision + 1, updated_at = now(), updated_by = event_actor
     WHERE id = 1;
    INSERT INTO answer_model_setting_events (revision, actor, before, after)
    VALUES (current_revision + 1, event_actor, old_settings, new_settings);
    RETURN current_revision + 1;
END $$;
REVOKE ALL ON FUNCTION laborconsult.answer_model_settings_save(BIGINT, JSONB, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION laborconsult.answer_model_settings_save(BIGINT, JSONB, TEXT) TO service_role;
```

CLAUDE.md 공유 스키마 규칙 준수: `laborconsult` 스키마 명시, 큰따옴표 식별자 없음(D8), `search_path`에 `public` 없음(D7), 테이블·함수 GRANT 명시, 테이블명은 고유 접두사(`answer_model_`). 적용 전 `pg_policies`·`information_schema.tables`로 이름 충돌 확인.

---

## 4. 모듈 명세 — `app/core/model_settings.py`

### 4.1 해석 (`resolve()`)

```python
PROVIDERS = ("claude", "openai", "gemini")

@dataclass(frozen=True)
class Resolved:
    models: dict[str, tuple[str, str]]   # provider -> (model, source)
    primary: tuple[str | None, str]      # (provider|None, source)
    revision: int | None

def resolve() -> Resolved: ...
```

우선순위(벤더별 독립):

| provider | settings | env | default |
|---|---|---|---|
| claude | `models.claude.model` | — (상수 고정 유지 — config.py 주석의 낡은 셸 env 사고) | `config.CLAUDE_MODEL` |
| openai | `models.openai.model` | `OPENAI_CHAT_MODEL` | `"o3"` |
| gemini | `models.gemini.model` | `GEMINI_MODEL` | `"gemini-pro-latest"` |
| primary | `primary` | `ANSWER_PROVIDER` | `None`(기본 순서) |

env는 **매 호출 재조회**(현행 `_stream_openai`와 동일 — 무재시작 A/B 유지).

### 4.2 캐시·fail-open

- 모듈 전역 `_cache = (fetched_monotonic, settings_dict, revision)`, TTL **60초**.
- 미스 시 service-role 클라이언트로 `select settings, revision where id=1`. 클라이언트는 **`postgrest_client_timeout=2`** 전용으로 1회 생성·재사용(supabase-py 기본 120초 — 답변 경로에서 그대로 쓰면 2분 정지).
- **읽기 실패·키 없음·행 없음 → `{}`를 캐시**(TTL 동일). 실패를 캐시하지 않으면 DB 장애 중 매 요청이 2초씩 기다린다. 첫 실패만 `warning`, 이후 같은 원인은 `debug`.
- `invalidate()` — 저장·리셋 직후 **그 인스턴스**의 캐시를 비운다(다른 인스턴스는 TTL로 수렴). **세대 번호를 함께 올린다** — 조회는 잠금 밖에서 돌기 때문에, 무효화 이전에 시작된 조회가 뒤늦게 끝나 옛 설정을 60초 되살리는 경합이 있다(갭 분석 R-1). 조회 시작 시점의 세대가 현재와 다르면 결과를 캐시에 쓰지 않는다.
- env `ANSWER_PROVIDER`가 허용 값(`claude`·`openai`·`gemini`)이 아니면 `(None, default)`로 해석한다 — 정렬에 효과가 없는 값을 "환경변수 적용 중"으로 표시하지 않기 위해서다(R-5).
- `make_supabase_client`에 `postgrest_timeout: float | None = None` 인자 추가(기존 호출부 무변경).

### 4.3 목록 필터 (`list_models(provider, config)`)

| provider | 호출 | 필터 | 정렬 |
|---|---|---|---|
| claude | `anthropic.models.list(limit=100)` | 없음 | `created_at` 내림차순 |
| openai | `openai.models.list()` | **제외 목록**: `embedding`,`tts`,`transcribe`,`whisper`,`dall-e`,`image`,`audio`,`realtime`,`search`,`moderation`,`codex`,`davinci`,`babbage`,`computer-use`,`live` | `created` 내림차순 |
| gemini | `genai.list_models()` + `"generateContent" in supported_generation_methods` | 제외: `tts`,`image`,`embedding`,`aqa`,`imagen`,`veo`,`lyria`,`banana`,`research`; `models/` 접두사 제거 | 이름 내림차순(`-latest` 별칭 상단 고정) |

- **벤더별 최신 3개만 반환한다**(사용자 결정 2026-09-30). 필터 → 중복 제거 → 정렬 → 상위 3.
  - **날짜 스냅샷 중복 제거**: `gpt-5-2025-08-07`처럼 별칭(`gpt-5`)과 끝의 `-YYYY-MM-DD`/`-YYYYMMDD`만 다른 ID는 별칭 하나만 남긴다(별칭이 없으면 스냅샷 유지 — 예: `claude-haiku-4-5-20251001`). 그대로 두면 최신 3개가 "같은 모델 2벌 + 1개"가 된다(실측: `gpt-4.1`·`gpt-4.1-2025-04-14`).
  - **Gemini는 날짜 필드가 없다** → 이름의 버전 숫자(`gemini-3.1-pro-preview` → 3.1)로 내림차순, 같은 버전이면 정식 > `-preview`. `gemini-*-latest` 별칭은 버전이 없으므로 3개와 **별도로 전부** 위에 둔다(`gemini-`로 시작하지 않는 별칭은 제외). 실측(09-30): 별칭 = flash·flash-lite·pro, 버전 상위 3 = `gemini-3.8/3.7/3.6-flash` — 버전 순위만 쓰면 **pro 계열이 통째로 빠진다**. 현재 기본값 `gemini-pro-latest`도 별칭이다.
  - **현재 사용 중인 모델은 3개 밖이어도 목록에 포함**하고 `current: true`로 표시한다 — 안 보이면 "지금 값 유지"를 선택할 수 없다.
- 반환: `[{"id", "label", "created", "current"}]` (최대 3 + 현재값 1, Gemini는 + 별칭).
- 실측 결과(09-30): Claude `sonnet-5-5`·`opus-5-5`·`fable-5-1` / OpenAI `gpt-6.1-sol`·`gpt-6-luna`·`gpt-6-sol`(제외 전 4위 `gpt-live-1` → `live` 제외 추가) / Gemini 별칭 3 + `3.8/3.7/3.6-flash`. 벤더 호출 타임아웃 10초.
- M-5 테스트에 추가: 스냅샷 중복 제거, 상위 3 절단, 현재값 강제 포함, Gemini 버전 정렬.
- 제외 목록 방식인 이유: 새 채팅 모델 계열이 나오면 **기본 노출**돼야 한다(포함 목록이면 조용히 안 보인다). 잘못 노출된 모델은 테스트 호출이 막는다.

### 4.4 테스트 토큰

- `issue_token(provider, model) -> str` — `HMAC-SHA256(JWT_SECRET, f"{provider}|{model}|{exp}")`, 유효 **15분**.
- `verify_token(token, provider, model) -> bool` — `hmac.compare_digest` + 만료 확인.
- 저장 시: 기존 저장값과 **다른** 모델에만 토큰 요구(바뀌지 않은 모델은 재테스트 불요). `primary`만 바꿀 때는 토큰 불요.
- `tested_at`에는 **저장 시각**을 기록한다(토큰 발급 후 최대 15분 차이) — 토큰에 테스트 시각을 싣지 않아 서버가 알 수 있는 가장 가까운 값이다.
- PUT의 `models`에서 **빠진 제공자는 저장값이 지워져** env·기본값으로 돌아간다. 화면은 저장값을 항상 함께 보낸다(`saveBody`). API를 직접 부를 때 주의.

---

## 5. pipeline 변경

### 5.1 스트리밍 함수에 `model` 주입

```python
def _stream_claude(messages, system, config, model: str | None = None): ...  # model or CLAUDE_MODEL
def _stream_openai(messages, system, config, model: str | None = None): ...  # model or env or 기본값
def _stream_gemini(messages, system, config, model: str | None = None): ...  # model or GEMINI_MODEL
```

`model=None`이면 현행과 바이트 동일(G1). `_stream_openai`의 매 호출 env 재조회는 `resolve()`로 흡수.

### 5.2 `_answer_providers(config)` — 시그니처 불변

```python
resolved = model_settings.resolve()
providers = [("Claude", partial(_stream_claude, model=resolved.models["claude"][0])), ...]
primary = resolved.primary[0]
if primary: providers.sort(key=lambda p: p[0].lower() != primary)
```

- 시그니처를 `(config)`로 유지하는 이유: `test_llm_fallback.py`가 `pipeline._answer_providers = lambda cfg: [...]`로 **1인자 교체**를 여러 곳에서 한다. 인자를 늘리면 기존 테스트가 전부 깨진다.
- `functools.partial`을 쓰는 이유: `_stream_answer`가 `stream_fn(messages, system, config)`로 부르는 계약을 그대로 두면서 모델을 묶는다.

### 5.3 metadata

- `AnswerOutcome.model: str | None` 추가. `_stream_answer`가 성공 제공자에 대해 `getattr(stream_fn, "keywords", {}).get("model")`을 기록(`partial.keywords`는 표준 속성 — 테스트 람다는 없으므로 `None`).
- `_llm_meta()`에 `"model"` 추가, `llm_outcome` 로그 줄에 `model=` 추가.

---

## 6. API — `api/model_settings.py`

모두 `Depends(require_admin)`. `SUPABASE_SERVICE_ROLE_KEY` 미설정 시 쓰기 API는 503(`"설정 저장소가 구성되지 않았습니다"`), 읽기 API는 기본값 상태를 반환.

| Method | Path | Request | Response | 오류 |
|---|---|---|---|---|
| GET | `/api/admin/model-settings` | — | `{revision, primary:{value,source}, providers:{claude:{model,source,available,tested_at}, …}, events:[최근 20]}` | — |
| GET | `/api/admin/model-settings/models?provider=` | — | `{provider, models:[{id,label,created}]}` | 400 provider, 502 벤더 조회 실패 |
| POST | `/api/admin/model-settings/test` | `{provider, model}` | `{ok:true, latency_ms, sample, token}` | 400 형식, 422 목록에 없는 모델, 422 호출 실패(`detail`에 벤더 오류 요약 200자), 429 |
| PUT | `/api/admin/model-settings` | `{revision, primary, models:{provider:{model, token?, latency_ms?}}}` | `{revision}` | 422 토큰 없음/불일치/만료, 409 revision 충돌 |
| POST | `/api/admin/model-settings/reset` | `{revision}` | `{revision}` | 409 |

### 6.1 테스트 호출 상세

- 프롬프트: system `"연결 확인용 호출입니다."`, user `"'정상'이라고만 답하세요."`
- `stream_fn = {claude:_stream_claude, openai:_stream_openai, gemini:_stream_gemini}[p]`를 `model=`로 호출해 **실질 텍스트 1자 이상**이 올 때까지 소비 후 중단(`_stream_answer`의 빈 응답=실패 규약과 동일 기준). 타임아웃은 각 함수 내부 값 그대로.
- 목록 소속 확인(FR-09): 같은 요청에서 벤더 **원본** 목록(`fetch_raw_models`, 필터 전)을 조회해 ID가 없으면 422 — 호출 전 차단이라 비용 없음. 필터된 최신 3개가 아니라 원본과 대조하는 이유: 화면 목록은 표시용 요약이고, 3개 밖의 호출 가능한 모델까지 막을 이유가 없다. 호출 불가 모델은 테스트 호출이 막는다.
- 인메모리 레이트리밋: 라우터 전역 10회/분(인스턴스별 베스트에포트). 관리자 계정이 하나라 관리자 구분은 두지 않는다.
- gemini 키가 없으면 `available:false`. test는 400, `primary="gemini"` 저장도 400(키가 없으면 `_answer_providers`가 Gemini를 넣지 않아 무효과), 모델 변경은 토큰을 받을 수 없어 422. 화면은 1순위 라디오를 비활성화한다.

### 6.2 저장 검증 순서

1. 형식(provider 집합·ID 정규식·primary 값)
2. 변경된 모델마다 `verify_token`
3. RPC `answer_model_settings_save(revision, settings, actor="admin-session:<jti>")` — `PT409` → 409 (40001은 PostgREST 재시도로 타임아웃까지 멈춤 — Do 단계 실측)
4. `model_settings.invalidate()` → 로그 `답변 모델 설정 변경 rev=N primary=… claude=…`
5. 충돌 외 RPC 실패(DB 장애·타임아웃)는 `RuntimeError` → **503**(R-2). reset도 먼저 `load(force=True)`로 저장소 연결을 확인해 끊겨 있으면 503.

---

## 7. UI — `public/admin.html` + `public/admin_model_settings.js`

- nav에 `답변 모델` 버튼(`nav-models`), `showView('models')`.
- 파일명은 `admin_` 접두사 유지 — `sw.js` 캐시 제외가 `/admin` 접두사 조건이다(CLAUDE.md).
- `admin_legal_rules.js`의 `createClient(fetcher)` 패턴 재사용(모든 응답 `!response.ok` 검사 — `test_public_fetch.js` 자동 발견 대상).

```
┌ 답변 모델 ─────────────────────────────── 최대 1분 후 모든 서버에 반영 ┐
│ 1순위: (●) Claude  ( ) OpenAI  ( ) Gemini        출처: 기본값          │
│                                                                        │
│ Claude   현재 claude-sonnet-5     [기본값]                              │
│          [목록 불러오기] [claude-sonnet-5-5 ▼] [테스트]  ✅ 1.8초 통과   │
│ OpenAI   현재 o3                  [환경변수]                            │
│          [목록 불러오기] [ ▼ ]              [테스트]                     │
│ Gemini   현재 gemini-pro-latest   [기본값]                              │
│                                                                        │
│ [저장]  (변경된 모델이 모두 테스트를 통과해야 활성)   [기본값으로]       │
│                                                                        │
│ 변경 이력: rev 3 · 09-30 10:02 · claude: sonnet-5 → sonnet-5-5 …        │
└────────────────────────────────────────────────────────────────────────┘
```

- 선택을 바꾸면 그 벤더의 테스트 결과·토큰을 초기화(다른 모델 토큰 재사용 방지 — 서버도 모델명으로 검증).
- 저장 버튼은 **변경이 있으면** 활성화한다. 테스트하지 않은 변경 모델은 클릭 시 `saveBody`가 어느 모델인지 알려주며 막는다(서버도 422로 거절).
- 1순위의 빈 값 라벨은 실제로 쓰이는 값을 말한다 — env `ANSWER_PROVIDER`가 있으면 "환경변수 따름(OpenAI)", 없으면 "기본 순서(Claude)"(R-5).
- 출처 배지 문구: `settings`=저장값, `env`=환경변수, `default`=기본값. env 출처일 때 "저장하면 환경변수보다 우선합니다" 안내.
- 409 시 "다른 곳에서 먼저 변경됐습니다 — 새로고침 후 다시 시도" + 자동 재조회.

---

## 8. Error Handling & 폴백

| 상황 | 동작 |
|---|---|
| 설정 DB 장애·키 없음 | `resolve()`가 기본값 반환, 답변 정상(G3). 관리자 화면 GET은 기본값 + `store_available:false` 표시 |
| 저장된 모델이 이후 폐기(404) | 기존 폴백 규약대로 다음 제공자로 전환 → `metadata.llm.attempts`·`model`에 기록. 화면 GET에 최근 24시간 해당 모델 실패 여부 표시는 **범위 밖**(후속) |
| 벤더 목록 API 실패 | 502, 화면은 "목록을 불러오지 못했습니다" — 저장된 값 유지 |

---

## 9. Test Plan — `test_model_settings.py` (오프라인, API 키 불요)

| ID | 검사 |
|---|---|
| M-1 | 설정 `{}` → `_answer_providers`가 현행과 같은 순서·모델(`CLAUDE_MODEL`, env/`o3`, env/`gemini-pro-latest`) |
| M-2 | 우선순위: settings > env > default (벤더별 독립, claude는 env 무시) |
| M-3 | 캐시: TTL 내 재조회 0회, TTL 후 1회, `invalidate()` 후 1회 |
| M-4 | fail-open: 읽기 예외·키 없음 → 기본값, 실패도 TTL 캐시(연속 호출 시 DB 호출 1회) |
| M-5 | 목록 필터: OpenAI 실측 ID 표본(embedding·tts·codex 등) 제외, 새 가상 채팅 모델 `gpt-9` 노출 / Gemini `models/` 제거·tts/image 제외 / **최신 3개 절단·스냅샷 중복 제거·현재값 강제 포함·Gemini 버전 정렬** |
| M-6 | 토큰: 발급→검증 통과, 모델 다르면 실패, 만료 실패, 변조 실패 |
| M-7 | 저장 검증: 변경 모델 토큰 없으면 422, primary만 변경은 토큰 불요, 미변경 모델은 토큰 불요 |
| M-8 | `partial` 주입: `_stream_answer` 성공 시 `outcome.model`에 모델명, 테스트 람다(비 partial)는 `None` |
| M-9 | 테스트 호출 판정: 공백만 내는 가짜 스트림 = 실패, 1자 이상 = 성공 |

기존 회귀: `test_llm_fallback.py`(순서·하트비트·`ANSWER_PROVIDER` 재정렬 — env 경로가 `resolve()`로 바뀌므로 해당 테스트가 통과해야 G1), `test_offline_units.py` D5~D9(DDL 등록), `node --test test_admin_model_settings.js`(렌더·요청 계약·409 처리), `test_public_fetch.js`.

---

## 10. Implementation Order

1. [ ] `supabase_model_settings.sql` + `_DDL_FILES`·`check_schema.py` 등록 → (사용자) SQL Editor 적용 → `check_schema.py`
2. [ ] `storage.make_supabase_client(postgrest_timeout=)` 인자
3. [ ] `app/core/model_settings.py` (resolve·캐시·목록 필터·토큰) + M-1~M-7
4. [ ] `pipeline.py` 모델 주입·`_answer_providers`·`AnswerOutcome.model`·`_llm_meta` + M-8, `test_llm_fallback.py` 통과
5. [ ] `api/model_settings.py` + `api/index.py` 등록 + M-9
6. [ ] `admin.html` nav/view + `admin_model_settings.js` + `test_admin_model_settings.js` (CI node 단계에 추가)
7. [ ] CLAUDE.md: DDL 순서 7번째, 모델 설정 우선순위·fail-open·출처 규칙
8. [ ] 배포 → 화면에서 Claude를 `claude-sonnet-5-5`로 테스트·저장 → 60초 내 프로덕션 `llm_outcome model=claude-sonnet-5-5` 확인
