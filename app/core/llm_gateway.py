"""보조 LLM 단계의 단일 호출 경로 (unified-model-provider).

관리자 화면에서 정한 답변 모델·1순위(`model_settings.resolve()`)를 **답변 외 단계에도** 그대로
쓴다 — 의도분석·파라미터 추출·쿼리 분해·Self-RAG·인용 교정·마이크로 퇴고. 이전에는 이 단계들이
Claude(Sonnet·Haiku)에 고정돼 있어, 1순위를 바꿔도 Anthropic 한도·장애에 그대로 묶였다
(2026-10-11 실측: 1순위 Gemini인데 의도분석·판정기·Self-RAG가 전부 Claude 400).

순서는 `provider_chain()` 하나가 정하고 `pipeline._answer_providers`도 이것을 쓴다 — 두 곳이
따로 정렬하면 "답변은 Gemini, 보조 단계는 Claude"처럼 다시 갈라진다.

임베딩(OpenAI)·Cohere rerank는 대상이 아니다. 벡터 인덱스가 그 임베딩으로 만들어져 있다.

벤더별 함정(전부 실측 2026-10-11):
- **토큰 한도를 작게 두면 빈 응답이다.** gpt-6-sol(`max_completion_tokens=10` → finish=length, 본문 0자)과
  gemini-3.8-flash(`max_output_tokens=10` → MAX_TOKENS, text 없음)는 추론·사고 토큰이 한도를 함께 쓴다.
  그래서 하한(`_MIN_TOKENS`)을 둔다 — 생성한 만큼만 과금되므로 비용은 같다.
- **gpt-6-sol은 function tool과 추론을 함께 받지 않는다**(chat completions 400 "set reasoning_effort to
  'none'"). o3는 반대로 'none'을 받지 않는다. 그래서 먼저 그대로 보내고, 그 400이면 'none'으로
  한 번 더 보낸 뒤 모델별로 기억한다.
- **Gemini 함수 호출은 정수를 실수로 돌려준다**(2500000 → 2500000.0). 스키마의 integer 필드는 되돌린다.
- **Claude 5 계열은 temperature를 받지 않는다**(400). 어느 벤더에도 temperature를 보내지 않는다.
- **Claude 5.5 세대(opus·sonnet·fable 5.1)는 강제 tool_choice(`any`·`tool`)를 받지 않는다**(400 "tool_choice: type
  \"tool\" and \"any\" are not supported for this model", 2026-10-27 실측 — haiku-5-5만 받는다). **상태 코드 400 + 그 문구**면
  `auto` + 도구 호출 지시(+effort low)로 한 번 더 보내고 모델별로 기억한다(`_CLAUDE_TOOL_NO_FORCE`). 다른 400(잔액·한도)과
  400이 아닌 예외는 그대로 전파한다. 이 자가치유가 없으면 Claude 1순위에서 의도분석·파라미터 추출이 **매 질문** 다음 제공자로 폴백한다.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Callable

logger = logging.getLogger(__name__)

PROVIDER_LABEL = {"claude": "Claude", "openai": "OpenAI", "gemini": "Gemini"}
_DEFAULT_ORDER = ("claude", "openai", "gemini")
_MIN_TOKENS = {"claude": 1024, "openai": 4096, "gemini": 2048}
_MIN_REMAINING = 2.0      # 데드라인까지 이보다 적게 남으면 다음 제공자를 부르지 않는다

_CLAUDE_VERSION_RE = re.compile(r"claude-(opus|sonnet|fable|mythos)-(\d+)(?:-(\d{1,2}))?(?:-|$)")
_OPENAI_TOOL_NEEDS_NO_REASONING: set[str] = set()
# 강제 tool_choice를 400으로 거절한 Claude 모델 — 이후 호출은 실패 왕복 없이 바로 auto+지시로 간다.
_CLAUDE_TOOL_NO_FORCE: set[str] = set()
_FORCE_UNSUPPORTED_RE = re.compile(r"tool_choice.*not supported", re.S)


def _is_forced_tool_choice_rejection(exc: BaseException) -> bool:
    """강제 tool_choice를 받지 않는 모델의 400인가 — 상태 코드 400 + 그 문구 둘 다여야 한다.

    문구만 보면 5xx 본문이나 네트워크 오류 메시지에 같은 단어가 섞였을 때 auto로 전환하고 모델을 영구 기억한다
    (CodeRabbit #142). SDK의 BadRequestError는 `status_code`를 갖는다 — 모듈이 anthropic을 import하지 않도록 속성으로 본다.
    """
    if getattr(exc, "status_code", None) != 400:
        return False
    body = getattr(exc, "body", None)
    detail = ""
    if isinstance(body, dict):   # SDK는 str(exc)에 본문을 붙이지만, 프록시·래퍼가 메시지를 바꿔도 본문으로 판정되게
        err = body.get("error")
        detail = str(err.get("message", "")) if isinstance(err, dict) else str(body)
    return bool(_FORCE_UNSUPPORTED_RE.search(f"{exc} {detail}"))
_AUTO_TOOL_RULE = "[도구 호출 규칙] 답변 텍스트를 쓰지 말고 {target}를 정확히 한 번 호출해 결과만 돌려준다."


class LLMUnavailable(RuntimeError):
    """설정된 제공자 전부가 실패했거나 빈 응답을 냈다."""


def supports_effort(model: str) -> bool:
    """output_config.effort를 받는 모델인가 — Opus·Sonnet·Fable·Mythos 4.6 이상.

    Haiku와 Sonnet 4.5 이하는 400을 낸다. 판정할 수 없는 이름은 보내지 않는다(안전 쪽) —
    보내지 않아도 답변은 되고, 보내서 400이 나면 그 단계 전체가 폴백된다.
    """
    m = _CLAUDE_VERSION_RE.match(model or "")
    if not m:
        return False
    major, minor = int(m.group(2)), int(m.group(3) or 0)
    return (major, minor) >= (4, 6)


def _available(config, provider: str) -> bool:
    if provider == "claude":
        return getattr(config, "claude_client", None) is not None
    if provider == "openai":
        return getattr(config, "openai_client", None) is not None
    return bool(getattr(config, "gemini_api_key", None))


def provider_chain(config) -> list[tuple[str, str]]:
    """(provider, model)을 호출 순서대로 — 1순위가 맨 앞, 나머지는 기본 순서.

    Claude·OpenAI는 항상 목록에 둔다(답변 경로 규약). Gemini는 키가 있을 때만.
    클라이언트가 없는 제공자는 보조 단계 호출 시 `_available`로 건너뛴다.
    """
    from app.core import model_settings

    resolved = model_settings.resolve()
    model_of = {p: m for p, (m, _src) in resolved.models.items()}
    order = [p for p in _DEFAULT_ORDER if p != "gemini" or getattr(config, "gemini_api_key", None)]
    primary = resolved.primary[0]
    if primary:
        order.sort(key=lambda p: p != primary)
    return [(p, model_of[p]) for p in order]


def primary_label(config) -> str:
    return PROVIDER_LABEL[provider_chain(config)[0][0]]


def _plan(config, attempts: int | None) -> list[tuple[str, str]]:
    chain = [(p, m) for p, m in provider_chain(config) if _available(config, p)]
    return chain if attempts is None else chain[:attempts]


def _timeout_for(timeout, index: int) -> float:
    if isinstance(timeout, (list, tuple)):
        return float(timeout[min(index, len(timeout) - 1)])
    return float(timeout)


def _budget(timeout: float, deadline: float | None) -> float | None:
    if deadline is None:
        return timeout
    remaining = deadline - time.monotonic()
    if remaining < _MIN_REMAINING:
        return None
    return min(timeout, remaining)


# ── 텍스트 ────────────────────────────────────────────────────────────────────

def _claude_text(config, model, system, user, max_tokens, timeout):
    kw = {"model": model, "max_tokens": max(max_tokens, _MIN_TOKENS["claude"]),
          "messages": [{"role": "user", "content": user}]}
    if system:
        kw["system"] = system
    if supports_effort(model):
        # 보조 단계는 짧은 판정·재작성이라 추론이 필요 없다 — 지정하지 않으면 Claude 5가 답 전에 길게
        # 추론해 단계 타임아웃에 걸린다(답변 경로 ANSWER_EFFORT 주석과 같은 이유).
        kw["output_config"] = {"effort": "low"}
    resp = config.claude_client.with_options(timeout=timeout, max_retries=0).messages.create(**kw)
    return "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")


def _openai_text(config, model, system, user, max_tokens, timeout):
    msgs = ([{"role": "developer", "content": system}] if system else []) + [
        {"role": "user", "content": user}]
    resp = config.openai_client.with_options(timeout=timeout, max_retries=0).chat.completions.create(
        model=model, messages=msgs,
        max_completion_tokens=max(max_tokens, _MIN_TOKENS["openai"]),
    )
    return resp.choices[0].message.content or ""


def _gemini_model(config, model, system, **kw):
    import google.generativeai as genai
    genai.configure(api_key=config.gemini_api_key)
    return genai.GenerativeModel(model, system_instruction=system or None, **kw)


def _gemini_parts(resp) -> list:
    candidates = getattr(resp, "candidates", None) or []
    if not candidates or not getattr(candidates[0], "content", None):
        return []
    return list(candidates[0].content.parts)


def _gemini_text(config, model, system, user, max_tokens, timeout):
    resp = _gemini_model(config, model, system).generate_content(
        user, generation_config={"max_output_tokens": max(max_tokens, _MIN_TOKENS["gemini"])},
        request_options={"timeout": timeout},
    )
    # resp.text는 text 파트가 없으면(MAX_TOKENS·안전 차단) 예외다 — 파트를 직접 모은다.
    return "".join(getattr(p, "text", "") or "" for p in _gemini_parts(resp))


_TEXT = {"claude": _claude_text, "openai": _openai_text, "gemini": _gemini_text}


def text(config, *, system: str | None, user: str, purpose: str, max_tokens: int = 1024,
         timeout: float | tuple = 10.0, attempts: int | None = 1, deadline: float | None = None,
         accept: Callable[[str], bool] | None = None) -> tuple[str, str]:
    """설정 순서대로 텍스트를 받는다. (본문, 제공자 라벨). 전부 실패하면 LLMUnavailable.

    attempts: 시도할 제공자 수(None = 전부). 1이면 1순위만 — 실패 시 호출부가 생략 경로로 간다.
    accept: 본문 검증(예: 재작성 길이 가드). 거부되면 다음 제공자로 넘긴다.
    """
    errors = []
    for i, (provider, model) in enumerate(_plan(config, attempts)):
        budget = _budget(_timeout_for(timeout, i), deadline)
        if budget is None:
            errors.append("deadline")
            break
        label = PROVIDER_LABEL[provider]
        try:
            out = (_TEXT[provider](config, model, system, user, max_tokens, budget) or "").strip()
        except Exception as exc:
            logger.warning("%s %s(%s) 실패: %s", purpose, label, model, exc)
            errors.append(f"{label}: {type(exc).__name__}")
            continue
        if not out or (accept is not None and not accept(out)):
            logger.warning("%s %s(%s) 빈 응답 또는 검증 실패", purpose, label, model)
            errors.append(f"{label}: rejected")
            continue
        return out, label
    raise LLMUnavailable(f"{purpose} 실패 — {', '.join(errors) or '사용 가능한 제공자 없음'}")


# ── 도구 호출(구조화 추출) ────────────────────────────────────────────────────

def _messages_text(messages: list[dict]) -> list[tuple[str, str]]:
    from app.core.llm_fallback import flatten_content
    return [(m["role"], flatten_content(m.get("content", ""))) for m in messages]


def extraction_budget(context, default=1024):
    """Bounded ledger budget; exhausted responses fail over, never become partial complete ledgers."""
    text=context if isinstance(context,str) else '\n'.join(content for _,content in _messages_text(context))
    if not re.search(r'체불|미지급|원금|정산|wage_claim|arrears',text,re.I):return default
    return min(32768,max(8192,len(text)*4))


def _claude_auto_tool_kwargs(base: dict, model: str, choice: str | None) -> dict:
    """강제 tool_choice를 거절하는 모델용 — auto + 지시(+effort low).

    5.5 세대는 지시만으로 도구를 안정적으로 부른다(실측 12/12, 1.6~5.6초). 지시는 system 끝에 붙인다 —
    messages에 넣으면 사용자 턴이 바뀌어 캐시 접두사와 분석 프롬프트의 전제("마지막 user가 질문")가 흔들린다.
    """
    target = f"도구 `{choice}`" if choice else "목록의 도구 중 알맞은 하나"
    rule = _AUTO_TOOL_RULE.format(target=target)
    kw = dict(base, tool_choice={"type": "auto", "disable_parallel_tool_use": True},
              system=f"{base['system']}\n\n{rule}" if base.get("system") else rule)
    if supports_effort(model):
        kw["output_config"] = {"effort": "low"}   # 추론을 짧게 — 단계 타임아웃(의도분석 12초) 안에 들어오게
    return kw


def _has_tool_use(resp) -> bool:
    return any(getattr(b, "type", "") == "tool_use" for b in (getattr(resp, "content", None) or []))


def _claude_tool(config, model, system, messages, tools, choice, max_tokens, timeout):
    base = {"model": model, "max_tokens": max(max_tokens, _MIN_TOKENS["claude"]),
            "tools": tools, "messages": messages}
    if system:
        base["system"] = system
    client = config.claude_client.with_options(timeout=timeout, max_retries=0)
    resp = None
    if model not in _CLAUDE_TOOL_NO_FORCE:
        forced = dict(base, tool_choice={"type": "tool", "name": choice} if choice else {"type": "any"})
        try:
            resp = client.messages.create(**forced)
        except Exception as exc:
            if not _is_forced_tool_choice_rejection(exc):
                raise
            _CLAUDE_TOOL_NO_FORCE.add(model)
            logger.info("%s는 강제 tool_choice를 받지 않는다 — auto+지시로 전환해 기억한다", model)
        else:
            if not _has_tool_use(resp):
                # Vercel AI Gateway 경유 실측(2026-10-28, opus-5.5): 같은 강제 요청이 400 대신 **200**으로 오되 도구를
                # 부르지 않고 추론·텍스트만 돌려준다(stop_reason max_tokens 포함). 400과 같은 신호로 보고 auto+지시로
                # 전환한다 — 안 그러면 Gateway 모드에서 의도분석·추출이 매 질문 "도구 호출 없음"으로 OpenAI 폴백이다
                # (PR #142가 고친 증상의 재발). 강제가 통하는 모델은 tool_use가 있어 이 분기에 오지 않는다.
                # 이번 요청의 auto 재시도와 모델 특성 기억은 분리한다(CodeRabbit #145): 강제를 받는 모델도 `refusal`로
                # 도구 없이 끝날 수 있으므로 refusal은 기억하지 않고 이번 요청만 auto로 간다.
                stop = getattr(resp, "stop_reason", None)
                if stop != "refusal":
                    _CLAUDE_TOOL_NO_FORCE.add(model)
                    logger.info("%s는 강제 tool_choice에 도구를 부르지 않았다(stop=%s) — auto+지시로 전환해 기억한다",
                                model, stop)
                else:
                    logger.info("%s 강제 tool_choice 응답이 refusal — 기억 없이 이번 요청만 auto+지시로 재시도", model)
                resp = None
    if resp is None:
        resp = client.messages.create(**_claude_auto_tool_kwargs(base, model, choice))
    if getattr(resp,"stop_reason",None)=="max_tokens":
        raise ValueError("Truncated tool response: max_tokens")
    for block in resp.content:
        if getattr(block, "type", "") == "tool_use":
            return block.name, block.input
    return None, None


def _openai_tool(config, model, system, messages, tools, choice, max_tokens, timeout):
    from app.core.llm_fallback import anthropic_tool_to_openai
    msgs = ([{"role": "developer", "content": system}] if system else []) + [
        {"role": role, "content": content} for role, content in _messages_text(messages)]
    kw = {"model": model, "messages": msgs,
          "tools": [anthropic_tool_to_openai(t) for t in tools],
          "tool_choice": ({"type": "function", "function": {"name": choice}} if choice else "required"),
          "max_completion_tokens": max(max_tokens, _MIN_TOKENS["openai"])}
    client = config.openai_client.with_options(timeout=timeout, max_retries=0)
    if model in _OPENAI_TOOL_NEEDS_NO_REASONING:
        kw["reasoning_effort"] = "none"
    try:
        resp = client.chat.completions.create(**kw)
    except Exception as exc:
        if "reasoning_effort" in kw or "reasoning_effort" not in str(exc):
            raise
        _OPENAI_TOOL_NEEDS_NO_REASONING.add(model)
        resp = client.chat.completions.create(**kw, reasoning_effort="none")
    if getattr(resp.choices[0],"finish_reason",None)=="length":
        raise ValueError("Truncated tool response: length")
    calls = resp.choices[0].message.tool_calls
    if not calls:
        return None, None
    return calls[0].function.name, json.loads(calls[0].function.arguments)


def _coerce(value, schema: dict | None):
    """Gemini가 실수로 돌려준 정수를 스키마대로 되돌린다(재귀)."""
    if not isinstance(schema, dict):
        return value
    kind = schema.get("type")
    if kind == "integer" and isinstance(value, float) and value.is_integer():
        return int(value)
    if kind == "object" and isinstance(value, dict):
        props = schema.get("properties") or {}
        return {k: _coerce(v, props.get(k)) for k, v in value.items()}
    if kind == "array" and isinstance(value, list):
        return [_coerce(v, schema.get("items")) for v in value]
    return value


def _gemini_tool(config, model, system, messages, tools, choice, max_tokens, timeout):
    declarations = [{"name": t["name"], "description": t.get("description", ""),
                     "parameters": t["input_schema"]} for t in tools]
    names = [choice] if choice else [t["name"] for t in tools]
    gm = _gemini_model(config, model, system, tools=[{"function_declarations": declarations}],
                       tool_config={"function_calling_config": {
                           "mode": "ANY", "allowed_function_names": names}},
                       generation_config={"max_output_tokens":max(max_tokens,_MIN_TOKENS["gemini"])})
    contents = [{"role": "model" if role == "assistant" else "user", "parts": [content]}
                for role, content in _messages_text(messages)]
    resp = gm.generate_content(contents, request_options={"timeout": timeout})
    for candidate in getattr(resp,"candidates",[]) or []:
        reason=getattr(candidate,"finish_reason",None)
        if reason==2 or str(reason).endswith("MAX_TOKENS"):
            raise ValueError("Truncated tool response: MAX_TOKENS")
    schemas = {t["name"]: t["input_schema"] for t in tools}
    for part in _gemini_parts(resp):
        call = getattr(part, "function_call", None)
        if call and call.name:
            args = type(call).to_dict(call).get("args") or {}
            return call.name, _coerce(args, schemas.get(call.name))
    return None, None


_TOOL = {"claude": _claude_tool, "openai": _openai_tool, "gemini": _gemini_tool}


def tool(config, *, system: str | None, messages: list[dict], tools: list[dict], purpose: str,
         choice: str | None = None, max_tokens: int = 1024, timeout: float | tuple = 10.0,
         attempts: int | None = 1) -> tuple[str, str, dict]:
    """도구 호출을 강제해 (제공자 라벨, 도구 이름, 입력 dict)를 받는다.

    도구 스펙은 Anthropic 규약(name·description·input_schema) 하나만 둔다 — 벤더별로 복제하면
    필드가 추가될 때 한쪽만 갱신돼 추출 결과가 조용히 갈라진다.
    choice: 강제할 도구 이름. None이면 목록 중 아무거나(any/required/ANY).
    빈 입력·도구 미호출은 실패로 보고 다음 제공자로 넘긴다("빈 응답은 실패다" 규약).
    """
    errors = []
    for i, (provider, model) in enumerate(_plan(config, attempts)):
        label = PROVIDER_LABEL[provider]
        try:
            name, args = _TOOL[provider](config, model, system, messages, tools, choice,
                                         max_tokens, _timeout_for(timeout, i))
        except Exception as exc:
            logger.warning("%s %s(%s) 실패: %s", purpose, label, model, exc)
            errors.append(f"{label}: {type(exc).__name__}")
            continue
        if not name or not args:
            logger.warning("%s %s(%s) 도구 호출 없음(빈 응답)", purpose, label, model)
            errors.append(f"{label}: empty")
            continue
        return label, name, args
    raise LLMUnavailable(f"{purpose} 실패 — {', '.join(errors) or '사용 가능한 제공자 없음'}")
