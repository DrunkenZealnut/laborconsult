"""Intent Analyzer — Claude tool_use로 노동상담 질문 분석 (실패 시 OpenAI 폴백)"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import AppConfig

from app.config import (
    CRITICAL_MAX_RETRIES, INTENT_FALLBACK_ENABLED, INTENT_FALLBACK_MAX_TOKENS,
    INTENT_FALLBACK_MODEL, INTENT_FALLBACK_TIMEOUT, INTENT_TIMEOUT,
)
from app.core.llm_fallback import call_openai_tool
from app.models.schemas import AnalysisResult
from app.templates.prompts import ANALYZE_TOOL, ANALYZER_SYSTEM

logger = logging.getLogger(__name__)


def _correct_date_year(date_str: str | None) -> str | None:
    """연도가 잘못 추정된 날짜를 현재 기준으로 보정.

    LLM이 연도 미명시 날짜를 과거 연도로 추정하는 경우,
    오늘 기준 가장 가까운 과거/현재 날짜로 보정한다.
    예: 오늘=2026-03-08, LLM 추출="2025-02-28" → "2026-02-28"
    """
    if not date_str or not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return date_str

    try:
        extracted = date.fromisoformat(date_str)
        today = date.today()

        # 1년 넘게 과거이면 보정 대상
        if (today - extracted).days > 365:
            # 같은 월/일을 올해로 설정
            try:
                candidate = extracted.replace(year=today.year)
            except ValueError:
                # 2월 29일 등 예외 → 2월 28일로
                candidate = date(today.year, extracted.month, 28)

            # 후보가 미래이면 작년으로 (예: 오늘 1월인데 "12월 퇴사")
            if candidate > today + timedelta(days=30):
                candidate = candidate.replace(year=today.year - 1)

            return candidate.isoformat()
    except (ValueError, TypeError):
        pass

    return date_str


# ── 숫자 범위 검증 ────────────────────────────────────────────────────────────

NUMERIC_RANGES: dict[str, tuple[float, float]] = {
    "wage_amount":            (1, 100_000_000),
    "monthly_wage":           (1, 100_000_000),
    "annual_wage":            (1, 1_200_000_000),
    "daily_work_hours":       (1, 24),
    "weekly_total_hours":     (1, 168),
    "weekly_work_days":       (1, 7),
    "weekly_overtime_hours":  (0, 52),
    "weekly_night_hours":     (0, 56),
    "weekly_holiday_hours":   (0, 16),
    "notice_days_given":      (0, 365),
    "parental_leave_months":  (1, 24),
    "arrear_amount":          (1, 10_000_000_000),
    "shutdown_days":          (1, 366),
    "public_holiday_days":    (1, 31),
    "reference_year":         (2020, 2030),
}

_FIELD_LABELS: dict[str, str] = {
    "wage_amount": "임금액",
    "monthly_wage": "월급",
    "annual_wage": "연봉",
    "daily_work_hours": "1일 소정근로시간",
    "weekly_total_hours": "주당 소정근로시간",
    "weekly_work_days": "주당 근무일수",
    "weekly_overtime_hours": "주당 연장근로시간",
    "weekly_night_hours": "주당 야간근로시간",
    "weekly_holiday_hours": "주당 휴일근로시간",
    "notice_days_given": "해고예고 일수",
    "parental_leave_months": "육아휴직 개월수",
    "arrear_amount": "체불임금액",
    "shutdown_days": "휴업 일수",
    "public_holiday_days": "유급 공휴일 일수",
    "reference_year": "기준연도",
}


def _validate_numeric_params(
    extracted: dict,
    missing_info: list[str],
) -> list[str]:
    """LLM이 추출한 숫자 파라미터의 범위를 검증.

    범위 밖 값은 extracted에서 제거하고 missing_info에 사유를 추가한다.
    extracted와 missing_info를 직접 변경(mutate)하며, 제거한 라벨 목록을
    반환한다 — 파이프라인이 missing_info를 코드 판정으로 교체해도
    검증 경고가 유실되지 않도록 별도 보존(CALC-13).
    """
    removed: list[str] = []
    for key, (lo, hi) in NUMERIC_RANGES.items():
        val = extracted.get(key)
        if val is None:
            continue
        try:
            num = float(val)
        except (TypeError, ValueError):
            del extracted[key]
            removed.append(_FIELD_LABELS.get(key, key))
            continue

        if num < lo or num > hi:
            del extracted[key]
            removed.append(_FIELD_LABELS.get(key, key))

    missing_info.extend(removed)
    return removed


# extracted_info 구성: 계산기 입력용 필드만 분리
_INFO_KEYS = {
    "wage_type", "wage_amount", "business_size",
    "weekly_work_days", "daily_work_hours", "weekly_total_hours",
    "weekly_overtime_hours", "weekly_night_hours", "weekly_holiday_hours",
    "start_date", "end_date", "service_period_text",
    "fixed_allowances", "monthly_wage", "annual_wage",
    "notice_days_given", "parental_leave_months",
    "arrear_amount", "arrear_due_date",
    "shutdown_days", "public_holiday_days",
    "use_minimum_wage", "reference_year",
    "is_probation", "contract_months", "occupation_code",
    "is_platform_worker",
}


def _build_analysis_result(inp: dict) -> AnalysisResult:
    """도구 입력 dict → AnalysisResult.

    **벤더 무관** — Claude tool_use와 OpenAI function calling이 같은 스키마로
    같은 dict를 만들어 이 함수를 통과한다. 후처리를 한 곳에 모아야 두 벤더의
    추출 결과가 조용히 갈라지지 않는다 (llm-fallback-hardening FR-05).
    """
    extracted = {k: v for k, v in inp.items() if k in _INFO_KEYS and v is not None}

    # 날짜 보정: LLM이 연도를 잘못 추정한 경우 현재 기준으로 수정
    for date_key in ("start_date", "end_date", "arrear_due_date"):
        if date_key in extracted:
            extracted[date_key] = _correct_date_year(extracted[date_key])

    # 숫자 범위 검증: 비현실적 값 제거 → missing_info에 추가
    missing_from_llm = inp.get("missing_info", [])
    validation_warnings = _validate_numeric_params(extracted, missing_from_llm)

    return AnalysisResult(
        requires_calculation=inp.get("requires_calculation", False),
        calculation_types=inp.get("calculation_types", []),
        extracted_info=extracted,
        relevant_laws=inp.get("relevant_laws", []),
        missing_info=missing_from_llm,
        validation_warnings=validation_warnings,
        question_summary=inp.get("question_summary", ""),
        consultation_type=inp.get("consultation_type"),
        consultation_topic=inp.get("consultation_topic"),
        precedent_keywords=inp.get("precedent_keywords", []),
        worker_group=inp.get("worker_group"),
        # 필드 누락 시 True — 스코프 게이트 fail-open (chatbot-security FR-05)
        is_labor_related=inp.get("is_labor_related", True),
    )


def _build_messages(question: str, history: list[dict], summary: str) -> list[dict]:
    messages: list[dict] = []
    # 이전 대화 요약이 있으면 맨 앞에 컨텍스트로 추가
    if summary:
        messages.append({
            "role": "user",
            "content": f"[이전 대화 요약] {summary}",
        })
        messages.append({
            "role": "assistant",
            "content": "네, 이전 대화 내용을 참고하겠습니다.",
        })
    # 최근 대화 컨텍스트 (최대 4턴)
    for turn in history[-8:]:
        messages.append(turn)
    messages.append({"role": "user", "content": question})
    return messages


def _analyze_claude(messages: list[dict], system_prompt: str, config) -> dict | None:
    """1순위 — Claude tool_use. 도구 입력 dict를 반환(미반환 시 None)."""
    # temperature 미지정 — Sonnet 5 이후 모델은 이 파라미터를 거부(400)한다.
    # tool_choice 강제 + 스키마 제약으로 추출 결정성은 유지된다.
    # 임계경로 타임아웃 (DB-6) — 항상 실행되는 호출이라 지연 시 전체가 행(hang)하던 지점
    response = config.anthropic_client.with_options(
        timeout=INTENT_TIMEOUT, max_retries=CRITICAL_MAX_RETRIES,
    ).messages.create(
        model=config.analyzer_model,
        max_tokens=1024,
        system=system_prompt,
        tools=[ANALYZE_TOOL],
        tool_choice={"type": "tool", "name": "analyze_labor_question"},
        messages=messages,
    )
    for block in response.content:
        if block.type == "tool_use":
            if not block.input:
                break          # 빈 입력도 실패로 취급 (아래 raise)
            return block.input
    # tool_use 없이 종료 = 빈 응답. 예외 없이 None을 돌려주면 호출부의 except를
    # 타지 못해 OpenAI 폴백이 통째로 생략된다 — _stream_answer의 FR-01과 같은
    # 규약("빈 응답은 실패다")을 여기에도 적용한다.
    raise RuntimeError("Claude 의도분석이 tool_use를 반환하지 않음(빈 응답)")


def analyze_intent(
    question: str,
    history: list[dict],
    config: AppConfig,
    summary: str = "",
) -> AnalysisResult:
    """사용자 질문을 분석하여 계산 유형, 추출 정보, 누락 정보를 반환.

    Claude(1순위) → OpenAI(2순위) 교차벤더 폴백 (FR-05). Anthropic 장애 시
    이 함수가 실패하면 계산기 라우팅과 스코프 게이트가 함께 죽어 "숫자 없는
    일반론"이 정상 답변처럼 나가므로, 벤더 하나에 걸어두지 않는다.
    """
    messages = _build_messages(question, history, summary)
    system_prompt = ANALYZER_SYSTEM.format(today=date.today().isoformat())
    used_fallback = False

    try:
        inp = _analyze_claude(messages, system_prompt, config)
    except Exception as e:
        if not INTENT_FALLBACK_ENABLED:
            raise
        logger.warning("의도분석 Claude 실패 — OpenAI 폴백 시도: %s", e)
        # 폴백도 실패하면 예외를 그대로 전파한다 — 호출부(pipeline)가 이를 받아
        # 레거시 추출 경로로 강등하는 기존 동작이 유지된다.
        inp = call_openai_tool(
            config.openai_client,
            model=INTENT_FALLBACK_MODEL,
            system=system_prompt,
            messages=messages,
            tool=ANALYZE_TOOL,
            timeout=INTENT_FALLBACK_TIMEOUT,
            max_tokens=INTENT_FALLBACK_MAX_TOKENS,
        )
        if not inp:
            # 폴백도 빈 응답 — 예외로 전파해 호출부가 레거시 경로로 강등하게 한다
            raise RuntimeError(f"OpenAI({INTENT_FALLBACK_MODEL}) 의도분석이 빈 응답 반환")
        logger.info("의도분석 OpenAI 폴백 성공 (model=%s)", INTENT_FALLBACK_MODEL)
        used_fallback = True

    result = _build_analysis_result(inp)
    result.intent_provider = "OpenAI" if used_fallback else "Claude"
    return result
