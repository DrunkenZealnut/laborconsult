"""Intent Analyzer — 설정 1순위 모델의 도구 호출로 노동상담 질문 분석 (실패 시 다음 순위)"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import AppConfig

from app.config import INTENT_FALLBACK_ENABLED, INTENT_FALLBACK_TIMEOUT, INTENT_TIMEOUT
from app.core import llm_gateway
from app.models.schemas import AnalysisResult
from app.templates.prompts import ANALYZE_TOOL, ANALYZER_SYSTEM
from wage_calculator.calculators.annual_leave import ANNUAL_INPUT_FIELDS
from wage_calculator.calculators.childcare_shared import CHILDCARE_INPUT_FIELDS

logger = logging.getLogger(__name__)


# 질문(또는 대화 맥락)에 연도 단서가 있으면 LLM이 정한 연도를 그대로 둔다. 보정은 "연도를 말하지 않았는데
# LLM이 과거 연도를 지어낸" 경우만 대상이다. 단서는 셋이다 — 명시 연도(2023·2023년·23.3.2), 기간("2년"·
# "18개월"·"3달"·"730일"·"60주 동안" — LLM이 오늘에서 거슬러 시작일을 계산한다), 상대 연도(작년·재작년·지난해).
# 일 단위는 세 자리 이상만 본다 — 날짜의 일(1~31)은 두 자리라 "3월 2일"과 겹치지 않는다. 주 단위는
# "주 5일"처럼 숫자가 뒤에 오는 근무형태와 구분하려고 두 자리 이상 + 기간 접미어를 요구한다.
# 실측(2026-10-11): 보정이 조건 없이 돌아 "2023년 3월 2일 입사, 2025년 3월 1일 퇴사"가
# 2026-03-02 입사·2026-03-01 퇴사(입사보다 퇴사가 앞선 날짜)로 계산기에 들어갔다. 벤더와 무관한 후처리다.
_YEAR_CONTEXT_RE = re.compile(
    r"(?<!\d)(?:19|20)\d{2}(?!\d)"
    r"|(?<!\d)\d{2}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{1,2}"
    r"|\d+(?:\.\d+)?\s*(?:년|개월|달)"
    r"|(?<!\d)\d{3,}\s*일"
    r"|(?<!\d)\d{2,}\s*주\s*(?:전|동안|간|째|이상|넘게|정도|근무)"
    r"|작년|재작년|지난\s*해|전년도?|이듬해|다음\s*해"
)


def _has_year_context(text: str | None) -> bool:
    return bool(text) and _YEAR_CONTEXT_RE.search(text) is not None


def _correct_date_year(date_str: str | None, context: str | None = None) -> str | None:
    """연도가 잘못 추정된 날짜를 현재 기준으로 보정.

    LLM이 연도 미명시 날짜를 과거 연도로 추정하는 경우,
    오늘 기준 가장 가까운 과거/현재 날짜로 보정한다.
    예: 오늘=2026-03-08, 질문 "2월 28일 퇴사", LLM 추출="2025-02-28" → "2026-02-28"

    context: LLM이 본 질문·대화 텍스트. 연도 단서(_YEAR_CONTEXT_RE)가 있으면 보정하지 않는다.
        None이면 판단 근거가 없으므로 예전처럼 보정한다(맥락을 넘기지 않는 호출부 호환).
    """
    if not date_str or not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return date_str
    if _has_year_context(context):
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
    "use_minimum_wage", "reference_year", "reference_date",
    "is_probation", "contract_months", "occupation_code",
    "is_platform_worker",
}
_INFO_KEYS.update(set(ANNUAL_INPUT_FIELDS) | CHILDCARE_INPUT_FIELDS)
from wage_calculator.calculators.wage_arrears import ARREARS_INPUT_FIELDS
from wage_calculator.calculators.pay_inputs import PAY_INPUT_FIELDS
from wage_calculator.calculators.family_leave import FAMILY_INPUT_FIELDS
from wage_calculator.calculators.prorated import PRORATION_INPUT_FIELDS
from wage_calculator.calculators.wage_claims import CLAIM_INPUT_FIELDS, CLAIM_DEPENDENCY_FIELDS
_INFO_KEYS.update(ARREARS_INPUT_FIELDS | PAY_INPUT_FIELDS | FAMILY_INPUT_FIELDS | PRORATION_INPUT_FIELDS | CLAIM_INPUT_FIELDS | CLAIM_DEPENDENCY_FIELDS)


# 지급 주기가 회사마다 갈리는 수당(상여·성과급·명절 등) — 질문에 주기가 없으면 '미확인'으로 두고 그 수당에 기대는 계산을 보류한다
_CYCLE_VARIES_RE = re.compile(r"상여|보너스|성과|인센티브|격려|포상|장려금|명절|설날|구정|추석|선물|귀성|김장|생일|경조|휴가비|하계|동계|"
                              r"연말|연초|체력단련|분기|반기|연간|연차")
# 주기 표현이 없어도 매월 지급으로 보는 월정 수당 — 허용 목록이다. 목록 밖 이름은 '미확인'으로 남긴다(거부 목록만 두면 '설날
# 선물비'처럼 목록에 없는 연 1회 지급액이 월액으로 들어갔다 — PR #134 리뷰). 이름이 '…수당'이면 월정 수당으로 본다
_MONTHLY_ALLOWANCE_RE = re.compile(r"식대|식비|중식|석식|교통|차량|유류|통신|직책|직급|직무|자격|면허|가족|자녀|부양|보육|육아|근속|위험|"
                                   r"기술|연구|숙소|주거|주택|출장|야간|교대|당직|특수|벽지|현장|조정|팀장|반장|조장|관리|만근|개근|어학|"
                                   r"업무|활동|복리|기본|고정")


def _default_payment_cycle(allowance: dict) -> str:
    """고정수당의 지급 주기. 명시된 주기는 그대로 두고, 생략·'미확인'이면 이름으로 정한다.

    상여·성과급·명절처럼 주기가 갈리는 항목과 월정 수당으로 알아볼 수 없는 이름은 '미확인'으로 남긴다. 식대·직책·교통·가족수당
    같은 월정 수당(허용 목록, 또는 이름이 '…수당')은 주기 표현이 없어도 매월 지급이다 — 모든 생략을 '미확인'으로 두면 수당 하나 때문에 최저임금·퇴직금·4대보험 카드 전체가 보류됐다(Codex 리뷰
    High 1: "월급 250만 + 식대 20만, 최저임금 위반인가요?"가 판정 없이 끝남. 상담 코퍼스에서 수당을 금액과 함께 적은 질문의
    93%가 주기를 적지 않는다)."""
    if allowance.get("annual") is True:
        return allowance.get("payment_cycle") or "연"
    cycle = allowance.get("payment_cycle")
    if cycle and cycle != "미확인":
        return cycle
    name = re.sub(r"\s+", "", str(allowance.get("name") or ""))
    if _CYCLE_VARIES_RE.search(name):
        return "미확인"
    return "매월" if (_MONTHLY_ALLOWANCE_RE.search(name) or name.endswith("수당")) else "미확인"


def _build_analysis_result(inp: dict, context: str | None = None) -> AnalysisResult:
    """도구 입력 dict → AnalysisResult.

    **벤더 무관** — Claude tool_use와 OpenAI function calling이 같은 스키마로
    같은 dict를 만들어 이 함수를 통과한다. 후처리를 한 곳에 모아야 두 벤더의
    추출 결과가 조용히 갈라지지 않는다 (llm-fallback-hardening FR-05).

    context: LLM이 본 질문·대화 텍스트 — 날짜 연도 보정 여부를 정한다(_correct_date_year).
    """
    extracted = {k: v for k, v in inp.items() if k in _INFO_KEYS and v is not None}

    if isinstance(extracted.get("fixed_allowances"), list):
        extracted["fixed_allowances"] = [
            dict(a, payment_cycle=_default_payment_cycle(a)) if isinstance(a, dict) else a
            for a in extracted["fixed_allowances"]]

    # 날짜 보정: LLM이 연도를 잘못 추정한 경우 현재 기준으로 수정
    for date_key in ("start_date", "end_date", "arrear_due_date"):
        if date_key in extracted:
            extracted[date_key] = _correct_date_year(extracted[date_key], context)

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


def analyze_intent(
    question: str,
    history: list[dict],
    config: AppConfig,
    summary: str = "",
) -> AnalysisResult:
    """사용자 질문을 분석하여 계산 유형, 추출 정보, 누락 정보를 반환.

    관리자 설정 1순위 → 2순위 교차벤더 폴백 (FR-05, unified-model-provider). 1순위 장애 시
    이 함수가 실패하면 계산기 라우팅과 스코프 게이트가 함께 죽어 "숫자 없는
    일반론"이 정상 답변처럼 나가므로, 벤더 하나에 걸어두지 않는다.
    """
    messages = _build_messages(question, history, summary)
    system_prompt = ANALYZER_SYSTEM.format(today=date.today().isoformat())

    # 1순위 → 다음 순위(설정 순서). 둘 다 실패하면 예외를 그대로 전파한다 — 호출부(pipeline)가
    # 레거시 추출 경로로 강등하는 기존 동작이 유지된다. 빈 tool 입력도 실패다(_stream_answer FR-01).
    # temperature는 보내지 않는다 — Sonnet 5 이후는 거부(400). tool 강제 + 스키마로 결정성 유지.
    provider, _name, inp = llm_gateway.tool(
        config, system=system_prompt, messages=messages, tools=[ANALYZE_TOOL],
        choice=ANALYZE_TOOL["name"], purpose="의도분석", max_tokens=llm_gateway.extraction_budget(messages),
        timeout=(INTENT_TIMEOUT, INTENT_FALLBACK_TIMEOUT),
        attempts=2 if INTENT_FALLBACK_ENABLED else 1,
    )

    # 연도 단서는 LLM이 본 전부(요약·이전 턴·질문)에서 찾는다 — 앞 턴에서 "2023년 입사"를 말하고
    # 후속 질문에 연도가 없어도 LLM은 앞 턴의 연도를 쓴다.
    from app.core.llm_fallback import flatten_content
    context = "\n".join([summary or ""] + [flatten_content(t.get("content", "")) for t in history[-8:]]
                         + [question])
    result = _build_analysis_result(inp, context)
    result.intent_provider = provider
    return result
