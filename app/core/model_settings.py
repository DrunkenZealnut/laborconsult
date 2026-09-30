"""답변 모델 설정 — 관리자 화면에서 고른 모델·1순위를 답변 경로에 반영한다 (admin-model-settings).

해석 우선순위(벤더별 독립): 저장값(Supabase) > 환경변수 > 코드 기본값.
Claude만 환경변수를 보지 않는다 — config.py 주석대로 셸 프로필의 낡은 CLAUDE_MODEL이
존재하지 않는 모델로 덮어 404가 났던 이력 때문이다.

지킬 것 셋(전부 조용히 실패한다):
- **읽기는 답변 경로 위에 있다.** supabase-py 기본 타임아웃은 120초라 그대로 쓰면 DB 장애 시
  답변이 2분 멈춘다. 전용 클라이언트를 2초 타임아웃으로 만든다.
- **실패도 캐시한다.** 안 그러면 DB 장애 동안 매 요청이 2초씩 기다린다. 실패는 기본값(`{}`)으로
  흡수한다(fail-open) — 설정 저장소가 상담을 막으면 안 된다.
- **이 모듈은 pipeline을 import하지 않는다.** pipeline이 이 모듈을 부르므로 순환이 된다
  (llm_fallback.py와 같은 이유). 테스트 호출은 라우터가 pipeline 함수를 주입해 수행한다.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import threading
import time
from dataclasses import dataclass

from app.config import CLAUDE_MODEL, GEMINI_MODEL_DEFAULT, OPENAI_CHAT_MODEL_DEFAULT

logger = logging.getLogger(__name__)

PROVIDERS = ("claude", "openai", "gemini")
PROVIDER_LABELS = {"claude": "Claude", "openai": "OpenAI", "gemini": "Gemini"}
MODEL_ID_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,100}$")

CACHE_TTL = 60.0
READ_TIMEOUT = 2.0
TOKEN_TTL = 15 * 60
LIST_LIMIT = 3            # 벤더별 최신 3개(사용자 결정 2026-09-30)
TABLE = "answer_model_settings"
EVENTS_TABLE = "answer_model_setting_events"
SAVE_RPC = "answer_model_settings_save"

# config.py가 import 시점에 env를 읽어 둔 값과 별개로, env는 **매 호출 재조회**한다 —
# 현행 _stream_openai가 무재시작 A/B를 위해 그렇게 해 왔다.
_ENV_KEYS = {"openai": "OPENAI_CHAT_MODEL", "gemini": "GEMINI_MODEL"}
_DEFAULTS = {"claude": CLAUDE_MODEL, "openai": OPENAI_CHAT_MODEL_DEFAULT, "gemini": GEMINI_MODEL_DEFAULT}


@dataclass(frozen=True)
class Resolved:
    models: dict          # provider -> (model, source)  source ∈ {"settings", "env", "default"}
    primary: tuple        # (provider | None, source)
    revision: int | None
    store_available: bool


class SettingsError(Exception):
    """관리자 요청의 형식·검증 오류(HTTP 4xx로 변환)."""


class RevisionConflict(Exception):
    """다른 곳에서 먼저 저장됨(HTTP 409)."""


# ── 저장소 ───────────────────────────────────────────────────────────────────

_lock = threading.Lock()
_cache: tuple[float, dict, int | None, bool] | None = None   # (monotonic, settings, revision, ok)
# 캐시 세대. invalidate()가 올린다 — 그 전에 시작된 조회는 결과를 캐시에 쓰지 못한다.
# 없으면 저장 직전에 시작된 조회가 invalidate() 뒤에 끝나 **옛 설정을 60초 되살린다**(갭 분석 R-1).
_generation = 0
_client = None
_warned = False


def _read_client():
    """2초 타임아웃 service-role 클라이언트(1회 생성·재사용). 키가 없으면 None."""
    global _client
    if _client is None:
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if not key:
            return None
        from app.core.storage import make_supabase_client
        _client = make_supabase_client(key=key, postgrest_timeout=READ_TIMEOUT)
    return _client


def _fetch() -> tuple[dict, int | None, bool]:
    global _warned
    try:
        client = _read_client()
        if client is None:
            raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY 미설정")
        rows = client.table(TABLE).select("settings,revision").eq("id", 1).execute().data or []
        if not rows:
            raise RuntimeError("설정 행 없음(DDL 미적용?)")
        settings = rows[0].get("settings") or {}
        _warned = False
        return (settings if isinstance(settings, dict) else {}), rows[0].get("revision"), True
    except Exception as e:  # noqa: BLE001 — fail-open: 어떤 실패도 기본값으로
        (logger.debug if _warned else logger.warning)(
            "답변 모델 설정 읽기 실패 — 코드 기본값 사용: %s", e)
        _warned = True
        return {}, None, False


def load(force: bool = False) -> tuple[dict, int | None, bool]:
    """(settings, revision, store_available) — 60초 캐시, 실패도 캐시."""
    global _cache
    now = time.monotonic()
    with _lock:
        if not force and _cache and now - _cache[0] < CACHE_TTL:
            return _cache[1], _cache[2], _cache[3]
        started = _generation
    settings, revision, ok = _fetch()
    with _lock:
        if started == _generation:
            _cache = (time.monotonic(), settings, revision, ok)
    return settings, revision, ok


def invalidate() -> None:
    """저장·리셋 직후 **이 인스턴스**의 캐시를 비운다(다른 인스턴스는 TTL로 수렴)."""
    global _cache, _generation
    with _lock:
        _cache = None
        _generation += 1


# ── 해석 ─────────────────────────────────────────────────────────────────────

def resolve(settings: dict | None = None) -> Resolved:
    """설정 → 벤더별 (모델, 출처) + 1순위. settings 미지정 시 캐시에서 읽는다."""
    revision, ok = None, True
    if settings is None:
        settings, revision, ok = load()
    stored = settings.get("models") if isinstance(settings.get("models"), dict) else {}

    models = {}
    for p in PROVIDERS:
        entry = stored.get(p) if isinstance(stored.get(p), dict) else {}
        value = entry.get("model")
        if isinstance(value, str) and MODEL_ID_RE.match(value):
            models[p] = (value, "settings")
            continue
        env_key = _ENV_KEYS.get(p)
        env_value = os.getenv(env_key, "").strip() if env_key else ""
        models[p] = (env_value, "env") if env_value else (_DEFAULTS[p], "default")

    primary = settings.get("primary")
    if primary in PROVIDERS:
        primary_pair = (primary, "settings")
    else:
        env_primary = os.getenv("ANSWER_PROVIDER", "").strip().lower()
        # 알 수 없는 값은 정렬에 아무 효과가 없다 — "환경변수 적용 중"으로 표시하면 거짓이다(R-5).
        primary_pair = (env_primary, "env") if env_primary in PROVIDERS else (None, "default")
    return Resolved(models, primary_pair, revision, ok)


# ── 목록 ─────────────────────────────────────────────────────────────────────

# 제외 목록 방식 — 새 채팅 모델 계열이 나오면 **기본 노출**돼야 한다(포함 목록이면 조용히
# 안 보인다). 잘못 노출된 모델은 테스트 호출이 막는다. 실측 2026-09-30.
OPENAI_EXCLUDE = ("embedding", "tts", "transcribe", "whisper", "dall-e", "image", "audio",
                  "realtime", "search", "moderation", "codex", "davinci", "babbage",
                  "computer-use", "live")
GEMINI_EXCLUDE = ("tts", "image", "embedding", "aqa", "imagen", "veo", "lyria", "banana",
                  "research")
_SNAPSHOT_RE = re.compile(r"-(\d{4}-\d{2}-\d{2}|\d{8})$")
_GEMINI_VERSION_RE = re.compile(r"gemini-(\d+(?:\.\d+)?)")


def _dedupe_snapshots(ids: list[str]) -> list[str]:
    """`gpt-4.1-2025-04-14`처럼 별칭과 날짜 접미사만 다른 ID는 별칭만 남긴다.
    별칭이 없으면 스냅샷을 유지한다(예: claude-haiku-4-5-20251001). 순서 보존."""
    present = set(ids)
    return [i for i in ids if not (_SNAPSHOT_RE.sub("", i) != i and _SNAPSHOT_RE.sub("", i) in present)]


def select_latest(provider: str, raw: list[dict], current: str | None) -> list[dict]:
    """벤더 원본 목록 → 답변 후보 최신 3개(+현재값, Gemini는 +별칭).

    raw: [{"id", "label", "created"(epoch|None)}] — 순서 무관.
    """
    if provider == "openai":
        raw = [m for m in raw if not any(k in m["id"] for k in OPENAI_EXCLUDE)]
    elif provider == "gemini":
        raw = [dict(m, id=m["id"].removeprefix("models/")) for m in raw]
        raw = [m for m in raw if not any(k in m["id"] for k in GEMINI_EXCLUDE)]
    by_id = {m["id"]: m for m in raw}

    extra: list[str] = []
    if provider == "gemini":
        # 날짜 필드가 없다 → 이름의 버전 숫자로 정렬, 같은 버전이면 정식 > preview.
        # -latest 별칭은 버전이 없으므로 3개와 별도로 전부 위에 둔다 — 버전 순위만 쓰면
        # 상위가 전부 flash라 pro 계열이 통째로 빠진다(실측 09-30).
        extra = sorted(i for i in by_id if i.startswith("gemini-") and i.endswith("-latest"))

        def key(i):
            m = _GEMINI_VERSION_RE.search(i)
            return (float(m.group(1)) if m else -1.0, "preview" not in i, i)
        ranked = sorted((i for i in by_id if not i.endswith("-latest")), key=key, reverse=True)
    else:
        ranked = sorted(by_id, key=lambda i: (by_id[i].get("created") or 0, i), reverse=True)

    picked = extra + _dedupe_snapshots(ranked)[:LIST_LIMIT]
    if current and current not in picked:
        picked.append(current)
    return [{"id": i, "label": (by_id.get(i) or {}).get("label") or i,
             "created": (by_id.get(i) or {}).get("created"), "current": i == current}
            for i in picked]


def fetch_raw_models(provider: str, config) -> list[dict]:
    """벤더 목록 API 호출(키는 서버에만). 실패는 호출부가 502로 변환."""
    if provider == "claude":
        page = config.claude_client.with_options(timeout=10.0, max_retries=0).models.list(limit=100)
        return [{"id": m.id, "label": getattr(m, "display_name", None) or m.id,
                 "created": m.created_at.timestamp() if getattr(m, "created_at", None) else None}
                for m in page.data]
    if provider == "openai":
        page = config.openai_client.with_options(timeout=10.0, max_retries=0).models.list()
        return [{"id": m.id, "label": m.id, "created": getattr(m, "created", None)} for m in page.data]
    if provider == "gemini":
        if not config.gemini_api_key:
            raise SettingsError("Gemini API 키가 설정되지 않았습니다")
        import google.generativeai as genai
        genai.configure(api_key=config.gemini_api_key)
        return [{"id": m.name, "label": getattr(m, "display_name", None) or m.name, "created": None}
                for m in genai.list_models(request_options={"timeout": 10})
                if "generateContent" in (m.supported_generation_methods or [])]
    raise SettingsError(f"알 수 없는 제공자: {provider}")


# ── 테스트 토큰 ──────────────────────────────────────────────────────────────

def _sign(secret: str, provider: str, model: str, exp: int) -> str:
    msg = f"{provider}|{model}|{exp}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def issue_token(secret: str, provider: str, model: str, now: float | None = None) -> str:
    exp = int((now if now is not None else time.time()) + TOKEN_TTL)
    return f"{exp}.{_sign(secret, provider, model, exp)}"


def verify_token(secret: str, token: str | None, provider: str, model: str,
                 now: float | None = None) -> bool:
    try:
        exp_s, sig = (token or "").split(".", 1)
        exp = int(exp_s)
    except ValueError:
        return False
    if exp < (now if now is not None else time.time()):
        return False
    return hmac.compare_digest(sig, _sign(secret, provider, model, exp))


# ── 저장 문서 검증 ───────────────────────────────────────────────────────────

def build_document(current: dict, payload: dict, secret: str) -> dict:
    """PUT 요청 → 저장할 설정 문서. 변경된 모델에만 테스트 토큰을 요구한다.

    payload: {"primary": provider|None, "models": {provider: {"model", "token"?, "latency_ms"?}}}
    """
    if not isinstance(payload, dict):
        raise SettingsError("요청 형식이 올바르지 않습니다")
    primary = payload.get("primary")
    if primary is not None and primary not in PROVIDERS:
        raise SettingsError(f"1순위 제공자가 올바르지 않습니다: {primary}")
    models_in = payload.get("models")
    if models_in is None:
        models_in = {}
    if not isinstance(models_in, dict) or set(models_in) - set(PROVIDERS):
        raise SettingsError("알 수 없는 제공자가 포함돼 있습니다")

    prev = current.get("models") if isinstance(current.get("models"), dict) else {}
    out_models = {}
    for p, entry in models_in.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("model"), str) \
                or not MODEL_ID_RE.match(entry["model"]):
            raise SettingsError(f"{PROVIDER_LABELS[p]} 모델 ID 형식이 올바르지 않습니다")
        model = entry["model"]
        old = prev.get(p) if isinstance(prev.get(p), dict) else {}
        if old.get("model") == model:
            out_models[p] = old                       # 미변경 — 재테스트 불요
            continue
        if not verify_token(secret, entry.get("token"), p, model):
            raise SettingsError(f"{PROVIDER_LABELS[p]} {model}: 테스트 호출을 먼저 통과해야 합니다")
        out_models[p] = {"model": model, "tested_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                         "latency_ms": entry.get("latency_ms")}
    doc: dict = {"models": out_models}
    if primary:
        doc["primary"] = primary
    return doc


def save(expected_revision: int, document: dict, actor: str = "admin") -> int:
    """RPC 저장(CAS). 쓰기 클라이언트는 기본 타임아웃(관리자 경로)."""
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        raise RuntimeError("설정 저장소가 구성되지 않았습니다(SUPABASE_SERVICE_ROLE_KEY)")
    from app.core.storage import make_supabase_client
    try:
        client = make_supabase_client(key=key, postgrest_timeout=10.0)
        res = client.rpc(SAVE_RPC, {"expected_revision": expected_revision,
                                    "new_settings": document, "event_actor": actor}).execute()
    except Exception as e:  # noqa: BLE001
        if "MODEL_SETTINGS_REVISION_CONFLICT" in str(e) or "PT409" in str(e):
            raise RevisionConflict() from e
        # 충돌 외 실패(DB 장애·타임아웃)는 503으로 — 500으로 새면 화면이 원인을 말하지 못한다(R-2).
        logger.warning("답변 모델 설정 저장 실패: %s", e)
        raise RuntimeError("설정 저장소에 연결할 수 없습니다") from e
    invalidate()
    revision = res.data if isinstance(res.data, int) else expected_revision + 1
    logger.info("답변 모델 설정 변경 rev=%s primary=%s models=%s", revision,
                document.get("primary"), {p: v.get("model") for p, v in document.get("models", {}).items()})
    return revision


def recent_events(limit: int = 20) -> list[dict]:
    client = _read_client()
    if client is None:
        return []
    try:
        return client.table(EVENTS_TABLE).select("revision,actor,before,after,created_at") \
            .order("revision", desc=True).limit(limit).execute().data or []
    except Exception as e:  # noqa: BLE001
        logger.warning("답변 모델 설정 이력 조회 실패: %s", e)
        return []
