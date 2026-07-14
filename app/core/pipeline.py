"""질문 처리 파이프라인 — RAG 검색 + 임금계산기 + Claude 답변 생성"""

from __future__ import annotations

import anthropic

import logging

from app.config import AppConfig, EMBED_MODEL, CLAUDE_MODEL, OPENAI_CHAT_MODEL, GEMINI_MODEL, EXTRACT_MODEL
from app.core.file_parser import ParsedAttachment
from app.core.analyzer import analyze_intent
# compose_follow_up은 더 이상 파이프라인에서 사용하지 않음
# (누락 정보가 있어도 답변을 생성하고 말미에 안내)
from app.core.storage import save_conversation, save_session_data, upload_attachment, classify_category, infer_calc_types, ConversationRecord
from app.models.session import Session
from wage_calculator.facade import WageCalculator, CALC_TYPE_MAP
from wage_calculator.facade.registry import resolve_calc_type_strict, CALC_TYPES
from wage_calculator.models import WageInput, WageType, WorkSchedule, BusinessSize
from wage_calculator.result import format_result
from harassment_assessor import assess_harassment, HarassmentInput, format_assessment
from app.core.labor_offices import find_commission, format_commission, format_all_commissions
from app.core.employment_centers import find_center, format_center, format_center_guide
from app.core.comwel_offices import find_office, format_office, format_office_guide
from app.core.legal_api import (
    fetch_relevant_articles, fetch_relevant_precedents,
    search_precedent_multi, fetch_precedent_details,
)
from app.core.precedent_query import build_precedent_queries
from app.core.query_decomposer import decompose_query, classify_complexity, COMPLEXITY_PARAMS
from app.core.nlrc_cases import search_nlrc_with_details
from app.core.rag import search_pinecone_multi, search_hybrid, format_pinecone_hits, rerank_results
from app.core.legal_consultation import process_consultation
from app.core.citation_validator import (
    build_available_citations_text,
    correct_hallucinated_citations,
    extract_precedents_from_hits,
    extract_admin_refs_from_hits,
    validate_response_citations,
    micro_polish,
)

logger = logging.getLogger(__name__)

# 괴롭힘 판정(_extract_params) 게이팅용 키워드 — 비계산·비괴롭힘 상담에서 Sonnet 재호출 회피(R-2a)
_HARASS_KEYWORDS = ("괴롭힘", "폭언", "폭행", "따돌림", "모욕", "갑질", "성희롱", "직장 내")


# ── 특수 근로자 그룹별 법적 컨텍스트 ──────────────────────────────────────────

_WORKER_GROUP_CONTEXTS: dict[str, str] = {
    "youth": (
        "[특수 적용: 청소년 근로자 (18세 미만)]\n"
        "이 질문은 청소년(18세 미만) 근로자에 관한 것입니다. 반드시 아래 특칙을 우선 적용하세요:\n"
        "- 근로기준법 제64조: 15세 미만 취업 원칙 금지 (취직인허증 예외)\n"
        "- 근로기준법 제66조: 18세 미만 야간근로(22시~06시) 및 휴일근로 원칙 금지 "
        "(본인 동의 + 고용노동부장관 인가 시 예외)\n"
        "- 근로기준법 제67조: 근로시간 상한 1일 7시간, 1주 35시간 "
        "(당사자 합의 시 1일 1시간, 1주 5시간 한도 연장 가능)\n"
        "- 근로기준법 제66조: 도덕·보건상 유해위험 사업장 사용 금지\n"
        "- 근로기준법 제67조: 친권자 또는 후견인의 근로계약 동의 필요\n"
        "- 근로기준법 제68조: 임금은 미성년자 본인에게 직접 지급\n"
        "⚠️ 일반 성인 기준(1일 8시간, 주 40시간)을 절대 적용하지 마세요."
    ),
    "foreign": (
        "[특수 적용: 외국인 근로자]\n"
        "이 질문은 외국인 근로자에 관한 것입니다. 참고 법령:\n"
        "- 외국인근로자의 고용 등에 관한 법률 (고용허가제)\n"
        "- 근로기준법은 국적과 무관하게 동일 적용 (제6조 균등처우)\n"
        "- 퇴직금·4대보험·최저임금 모두 내국인과 동일 기준 적용\n"
        "- 사업장 변경 제한 (원칙 3회), 체류기간 등 출입국관리법 관련 사항 안내\n"
        "- 불법체류 외국인도 근로기준법상 권리(임금청구 등) 보호됨"
    ),
    "disabled": (
        "[특수 적용: 장애인 근로자]\n"
        "이 질문은 장애인 근로자에 관한 것입니다. 참고:\n"
        "- 장애인고용촉진 및 직업재활법\n"
        "- 최저임금 적용 제외 인가제도 (최저임금법 제7조): "
        "고용노동부장관 인가 시 최저임금 감액 적용 가능\n"
        "- 장애인 의무고용률 (2026년: 민간 3.1%, 공공 3.6%)\n"
        "- 근로기준법은 장애 유무와 무관하게 동일 적용"
    ),
    "industrial_accident": (
        "[특수 적용: 산업재해]\n"
        "이 질문은 산업재해에 관한 것입니다. 참고 법령:\n"
        "- 산업재해보상보험법 (산재보험법)\n"
        "- 업무상 재해 인정 기준: 업무수행성 + 업무기인성\n"
        "- 급여 종류: 요양급여, 휴업급여(평균임금 70%), 장해급여, 유족급여, 상병보상연금\n"
        "- 요양급여 신청: 4일 이상 요양 시 근로복지공단(1588-0075)에 신청\n"
        "- 산재 인정 절차: 요양급여신청서 → 근로복지공단 심사 → 승인/불승인\n"
        "- 불승인 시 심사청구(90일 이내) → 재심사청구(90일 이내) → 행정소송\n"
        "- 산재보험은 근로자 수와 무관하게 1인 이상 사업장 당연가입"
    ),
}


def _build_worker_group_context(worker_group: str | None) -> str | None:
    """특수 근로자 그룹에 해당하는 법적 컨텍스트 반환."""
    if not worker_group or worker_group == "general":
        return None
    return _WORKER_GROUP_CONTEXTS.get(worker_group)


# ── 멀티쿼리 병합 헬퍼 ──────────────────────────────────────────────────────

def _merge_search_queries(
    decomposed: list[str],
    rule_based: list[str],
    fallback: str,
    max_total: int = 5,
) -> list[str]:
    """LLM 분해 + 규칙 기반 쿼리를 병합, 중복 제거.

    우선순위: decomposed > rule_based > fallback
    """
    seen: set[str] = set()
    merged: list[str] = []

    for q in decomposed + rule_based:
        normalized = q.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            merged.append(q.strip())

    # 결과가 없으면 폴백
    if not merged:
        merged.append(fallback)

    return merged[:max_total]


def _build_sources_payload(
    precedent_meta: list[dict] | None,
    consultation_hits: list[dict] | None,
    max_items: int = 5,
) -> list[dict]:
    """검색 결과를 sources SSE 이벤트용으로 정규화 (DB-2).

    본문(chunk_text)은 제외 — UI에는 제목·출처 메타만 표시한다.
    """
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for origin, hits in (("consultation", consultation_hits or []),
                         ("rag", precedent_meta or [])):
        for h in hits:
            title = h.get("title") or h.get("case_name") or ""
            key = (title, h.get("section") or "")
            if not title or key in seen:
                continue
            seen.add(key)
            try:
                score = round(float(h.get("rerank_score") or h.get("score") or 0), 3)
            except (TypeError, ValueError):
                score = 0.0
            out.append({
                "title": title[:120],
                "section": (h.get("section") or "")[:80],
                "source_type": h.get("source_type", "precedent"),
                "score": score,
                "origin": origin,
            })
    return out[:max_items]


def _citation_source_hits(
    consultation_hits: list[dict] | None,
    precedent_meta: list[dict] | None,
    legal_articles_text: str | None,
    nlrc_text: str | None,
    graph_context: str | None,
) -> list[dict]:
    """인용 가능 목록·검증 화이트리스트의 공통 원천 (DB-4).

    법령 API·NLRC·GraphRAG 텍스트에 실린 판례번호가 화이트리스트에서 빠져
    정당한 인용이 환각으로 오판·삭제되던 사각지대를 해소한다.
    텍스트 블록은 hits로 감싸기만 하며, 번호 추출은 citation_validator의
    정규식이 수행 — 소스에 실재하는 번호만 목록에 오른다.
    """
    hits = list(consultation_hits or [])
    for m in (precedent_meta or []):
        hits.append({
            "title": m.get("case_name", m.get("title", "")),
            "chunk_text": m.get("chunk_text", ""),
        })
    for label, text in (("법제처 법령 조문", legal_articles_text),
                        ("NLRC 판정사례", nlrc_text),
                        ("법령 지식그래프", graph_context)):
        if text:
            hits.append({"title": label, "chunk_text": text})
    return hits


def _cap(text: str | None, limit: int) -> str | None:
    """LLM 컨텍스트 소스별 길이 예산 (DB-5). 초과분은 뒤에서 절삭."""
    if text and len(text) > limit:
        return text[:limit] + "\n...(자료 일부 생략)"
    return text


# ── LLM 스트리밍 (Claude → OpenAI → Gemini 폴백) ────────────────────────────

def _flatten_content(content) -> str:
    """Anthropic content blocks에서 텍스트만 추출"""
    if isinstance(content, str):
        return content
    return "\n".join(b["text"] for b in content if isinstance(b, dict) and b.get("type") == "text")


def _stream_claude(messages: list, system: str, config: AppConfig):
    """Claude 스트리밍 — read 30s는 토큰 간 무진행 감지 (DB-6).

    첫 청크 전 실패 → _stream_answer가 OpenAI/Gemini로 폴백,
    스트림 도중 실패 → 부분 응답 유지(기존 규약, 재시도 없음).
    """
    import httpx
    timeout = httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0)
    with config.claude_client.with_options(timeout=timeout).messages.stream(
        model=CLAUDE_MODEL,
        max_tokens=2048,
        system=system,
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            yield text


def _stream_openai(messages: list, system: str, config: AppConfig):
    """OpenAI 스트리밍 (o3 등 reasoning 모델 호환)"""
    oai_msgs = [{"role": "developer", "content": system}]
    for m in messages:
        oai_msgs.append({"role": m["role"], "content": _flatten_content(m["content"])})

    stream = config.openai_client.chat.completions.create(
        model=OPENAI_CHAT_MODEL,
        messages=oai_msgs,
        max_completion_tokens=2048,
        stream=True,
    )
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


def _stream_gemini(messages: list, system: str, config: AppConfig):
    """Google Gemini 스트리밍"""
    import google.generativeai as genai
    genai.configure(api_key=config.gemini_api_key)
    model = genai.GenerativeModel(GEMINI_MODEL, system_instruction=system)

    contents = []
    for m in messages:
        role = "model" if m["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [_flatten_content(m["content"])]})

    response = model.generate_content(contents, stream=True)
    for chunk in response:
        if chunk.text:
            yield chunk.text


def _stream_answer(messages: list, system: str, config: AppConfig):
    """Claude → OpenAI → Gemini 순서로 폴백하며 스트리밍 답변 생성.

    Yields: (provider_name, text_chunk) 튜플
    Raises: RuntimeError if all providers fail
    """
    providers = [
        ("Claude", _stream_claude),
        ("OpenAI", _stream_openai),
    ]
    if config.gemini_api_key:
        providers.append(("Gemini", _stream_gemini))

    last_error = None
    for name, stream_fn in providers:
        try:
            started = False
            for text in stream_fn(messages, system, config):
                started = True
                yield (name, text)
            return  # 성공 — 종료
        except Exception as e:
            if started:
                # 부분 응답 수신 후 실패 — 재시도하지 않음
                logger.warning("%s 스트리밍 중 오류 (부분 응답 유지): %s", name, e)
                return
            logger.warning("%s 답변 생성 실패, 다음 제공자로 전환: %s", name, e)
            last_error = e
            continue

    raise RuntimeError(f"모든 AI 서비스 연결 실패: {last_error}")


# ── 임금계산기 ────────────────────────────────────────────────────────────────

WAGE_CALC_TOOL = {
    "name": "wage_params",
    "description": (
        "사용자의 노동법 질문에서 임금 계산에 필요한 파라미터를 추출합니다. "
        "주휴수당, 연장수당, 퇴직금 등 숫자 계산이 필요한 질문이면 "
        "needs_calculation=true로 설정하고 파라미터를 채우세요. "
        "법률 해석이나 일반 상담 질문이면 needs_calculation=false로 설정하세요."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "needs_calculation": {
                "type": "boolean",
                "description": "숫자 임금 계산이 필요한 질문인지 여부",
            },
            "calculation_type": {
                "type": "string",
                "description": "계산 유형: 주휴수당/연장수당/최저임금/퇴직금/실업급여/임금계산/연차수당/해고예고수당/육아휴직/출산휴가/임금체불/보상휴가/탄력근무",
            },
            "wage_type": {
                "type": "string",
                "description": "임금 형태: 시급/일급/월급/연봉/포괄임금제",
            },
            "wage_amount": {
                "type": "number",
                "description": "임금액 (원 단위 숫자)",
            },
            "weekly_work_days": {
                "type": "number",
                "description": "주 소정근로일수",
            },
            "weekly_total_hours": {
                "type": "number",
                "description": "주 소정근로시간 합계. 일별 다른 경우 합산",
            },
            "weekly_overtime_hours": {
                "type": "number",
                "description": "주 연장근로시간",
            },
            "weekly_night_hours": {
                "type": "number",
                "description": "주 야간근로시간 (22~06시)",
            },
            "weekly_holiday_work_hours": {
                "type": "number",
                "description": "주 휴일근로시간",
            },
            "business_size": {
                "type": "string",
                "description": "사업장 규모: 5인미만/5인이상/30인이상/300인이상",
            },
            "start_date": {
                "type": "string",
                "description": "입사일 (YYYY-MM-DD 또는 '2년', '1년 6개월' 등)",
            },
            "end_date": {
                "type": "string",
                "description": "퇴직일 (YYYY-MM-DD). 연도 미명시 시 오늘 날짜 기준 가장 가까운 과거/현재 날짜 사용",
            },
            "use_minimum_wage": {
                "type": "boolean",
                "description": "사용자가 '최저시급', '최저임금', '최저임금 기준'으로 임금을 지정할 때 반드시 true로 설정. true이면 wage_amount를 설정하지 마세요 — 시스템이 해당 연도 법정 최저시급을 자동 적용합니다. 주의: 최저임금 금액(10030, 10320 등)을 wage_amount에 직접 입력하면 연도 불일치 오류가 발생합니다.",
            },
            "reference_year": {
                "type": "number",
                "description": "계산 기준 연도 (예: 2026). 미지정 시 현재 연도 적용.",
            },
        },
        "required": ["needs_calculation"],
    },
}


HARASSMENT_TOOL = {
    "name": "harassment_params",
    "description": (
        "사용자의 질문이 직장 내 괴롭힘(직장 갑질, 폭언, 따돌림, 부당대우 등)에 관한 것이면 "
        "is_harassment_question=true로 설정하고 관련 파라미터를 추출하세요. "
        "임금 계산 질문이나 일반 법률 상담이면 이 도구를 사용하지 마세요."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "is_harassment_question": {
                "type": "boolean",
                "description": "직장 내 괴롭힘 판정이 필요한 질문인지 여부",
            },
            "perpetrator_role": {
                "type": "string",
                "description": "가해자 직위/역할 (예: 팀장, 사장, 선배, 동료, 고객)",
            },
            "victim_role": {
                "type": "string",
                "description": "피해자 직위/역할 (예: 사원, 인턴, 계약직)",
            },
            "relationship_type": {
                "type": "string",
                "description": "관계 유형: 상급자/사용자/정규직_비정규직/다수_소수/선임_후임/동료/하급자/고객",
            },
            "behavior_description": {
                "type": "string",
                "description": "괴롭힘 행위 상세 설명",
            },
            "behavior_types": {
                "type": "array",
                "items": {"type": "string"},
                "description": "행위 유형: 폭행_협박/폭언_모욕/따돌림_무시/부당업무/사적용무/감시_통제/부당인사",
            },
            "frequency": {
                "type": "string",
                "description": "빈도: 1회/수회/반복/매일/수개월간",
            },
            "duration": {
                "type": "string",
                "description": "기간: 1회성/1주/1개월/3개월/6개월/1년이상",
            },
            "witnesses": {
                "type": "boolean",
                "description": "목격자 유무",
            },
            "evidence": {
                "type": "array",
                "items": {"type": "string"},
                "description": "증거 목록 (예: 녹음, 문자, 진단서)",
            },
            "impact": {
                "type": "string",
                "description": "피해 결과 (예: 우울증, 퇴사, 불면 등)",
            },
            "company_response": {
                "type": "string",
                "description": "회사의 대응 (예: 미조치, 조사중, 불리한 처우)",
            },
            "business_size": {
                "type": "string",
                "description": "사업장 규모: 5인미만/5인이상/30인이상/300인이상",
            },
        },
        "required": ["is_harassment_question"],
    },
}


def _extract_params(query: str, client: anthropic.Anthropic) -> tuple[str, dict | None]:
    """질문을 분류하고 파라미터를 추출 (2-tool 방식)"""
    from datetime import date as _date
    from app.core.analyzer import _correct_date_year
    today = _date.today().isoformat()
    try:
        # 임계경로 타임아웃 (DB-6) — 지연 시 폴백 경로로 진행
        resp = client.with_options(timeout=10.0).messages.create(
            model=EXTRACT_MODEL,
            max_tokens=512,
            temperature=0,
            tools=[WAGE_CALC_TOOL, HARASSMENT_TOOL],
            tool_choice={"type": "any"},
            messages=[{
                "role": "user",
                "content": (
                    f"오늘 날짜: {today}\n\n"
                    "다음 질문을 분석하세요.\n"
                    "- 임금/수당/퇴직금 등 숫자 계산이 필요하면 wage_params 도구를 사용하세요. "
                    "일별 근로시간이 다르면 합산하여 weekly_total_hours에 넣으세요.\n"
                    "- 직장 내 괴롭힘/갑질/폭언/따돌림/부당대우 판정이 필요하면 harassment_params 도구를 사용하세요.\n"
                    "- 일반 법률 상담이면 wage_params에서 needs_calculation=false로 설정하세요.\n"
                    "- 연도가 명시되지 않은 날짜는 오늘 날짜를 기준으로 가장 가까운 과거/현재 날짜로 해석하세요.\n\n"
                    f"질문: {query}"
                ),
            }],
        )
        for block in resp.content:
            if block.type == "tool_use":
                if block.name == "harassment_params":
                    return ("harassment", block.input)
                # 날짜 보정
                params = block.input
                for dk in ("start_date", "end_date"):
                    if dk in params:
                        params[dk] = _correct_date_year(params[dk])
                return ("wage", params)
    except Exception as e:
        # 조용한 삼킴 제거 — 계산기 미실행 원인 관측 가능하게 (CALC-7)
        logger.warning("파라미터 추출 실패 (상담 경로로 진행): %s", e)
    return ("none", None)


def _ensure_minimum_wage_flag(params: dict, query: str) -> None:
    """최저시급 키워드 감지 시 use_minimum_wage 플래그 자동 보정.

    LLM이 '최저시급'을 인식하면서도 use_minimum_wage=true를 설정하지 않고
    과거 연도 최저임금 값을 wage_amount에 직접 입력하는 환각을 방지한다.
    """
    if params.get("use_minimum_wage"):
        return  # 이미 설정됨 — 수정 불필요
    if "최저시급" in query or "최저임금으로" in query or "최저임금 기준" in query:
        params["use_minimum_wage"] = True
        params.pop("wage_amount", None)


_UNIT_FLOORS = {  # wage_type: (하한, 배율) — 하한 미만이면 만원 단위 누락으로 판단
    "월급": (100_000, 10_000),
    "포괄임금제": (100_000, 10_000),
    "연봉": (1_200_000, 10_000),
}


def _normalize_wage_units(params: dict) -> bool:
    """월급/연봉의 만원 단위 누락 보정 (CALC-5).

    "250만원"이 250으로 추출된 경우 ×10,000 보정. 시급·일급은 정상 저액이
    존재하므로 제외(시급은 최저임금 환각 가드가 별도 처리).
    보정 발생 시 True 반환 — 호출부가 missing_info에 확인 안내를 추가한다.
    """
    rule = _UNIT_FLOORS.get(params.get("wage_type", ""))
    amt = params.get("wage_amount")
    if rule and amt and 10 <= amt < rule[0]:
        params["wage_amount"] = amt * rule[1]
        logger.warning("임금 단위 보정: %s %s → %s",
                       params.get("wage_type"), amt, params["wage_amount"])
        return True
    return False


_MINWAGE_SIGNALS = ("최저임금", "최저시급", "최저 임금", "최저 시급")


def _build_minwage_facts(query: str, analysis) -> str | None:
    """최저임금 관련 질문 감지 시 법정 최저임금 사실 블록 생성.

    연도별 최저임금 '금액'은 고용노동부 고시 사항이라 법령 API·코퍼스 어디에도
    신뢰 가능한 최신 값이 없고, 계산기는 임금·근로시간 정보가 없는 조회성 질문에
    실행되지 않는다. LLM이 학습 시점의 과거 금액을 현재 값으로 환각하는 것을
    constants 값 직접 주입으로 차단한다.
    """
    topic_hit = bool(
        analysis and "최저임금" in (getattr(analysis, "calculation_types", None) or [])
    )
    if not (topic_hit or any(s in query for s in _MINWAGE_SIGNALS)):
        return None

    from datetime import date as _date
    from wage_calculator.constants import MINIMUM_HOURLY_WAGE, MONTHLY_STANDARD_HOURS

    cur = _date.today().year
    years = sorted((y for y in MINIMUM_HOURLY_WAGE if cur - 2 <= y <= cur + 1), reverse=True)
    if not years:
        return None

    lines = []
    for y in years:
        hw = MINIMUM_HOURLY_WAGE[y]
        lines.append(
            f"- {y}년: 시급 {hw:,.0f}원 / 일급(8시간) {hw * 8:,.0f}원"
            f" / 월급(주40시간, {MONTHLY_STANDARD_HOURS:.0f}시간) {hw * MONTHLY_STANDARD_HOURS:,.0f}원"
        )
    return (
        "[검증된 법정 최저임금 데이터 — 연도별 최저임금 금액은 반드시 아래 수치만 사용하세요. "
        "학습 지식의 최저임금 금액은 오래된 값일 수 있으므로 사용 금지]\n"
        + "\n".join(lines)
        + "\n위 목록에 없는 연도의 금액은 아직 고시되지 않은 것이므로 '미확정'으로 안내하세요."
        + "\n(출처: 고용노동부 고시, 최저임금위원회)"
    )


_INSURANCE_SIGNALS = ("4대보험", "국민연금", "건강보험", "고용보험", "장기요양",
                      "보험요율", "보험 요율", "보험료")


def _build_insurance_facts(query: str, analysis) -> str | None:
    """4대보험 요율 질문 감지 시 검증된 요율 블록 생성.

    요율·상하한은 매년 바뀌는 고시 사항이라 LLM 학습 지식이 낡기 쉬운 영역 —
    최저임금과 동일하게 constants 값 주입으로 환각을 차단한다.
    """
    if not any(s in query for s in _INSURANCE_SIGNALS):
        return None

    from datetime import date as _date
    from wage_calculator.constants import INSURANCE_RATES

    cur = _date.today().year
    year = cur if cur in INSURANCE_RATES else max(INSURANCE_RATES.keys())
    r = INSURANCE_RATES[year]

    def pct(v: float) -> str:
        return f"{v * 100:.4g}%"

    return (
        "[검증된 4대보험 요율 — 요율·상하한 수치는 반드시 아래 값만 사용하세요. "
        "학습 지식의 요율은 오래된 값일 수 있으므로 사용 금지]\n"
        f"- {year}년 근로자 부담 요율: 국민연금 {pct(r['national_pension'])}"
        f"(전체 {pct(r['national_pension'] * 2)}), "
        f"건강보험 {pct(r['health_insurance'])}(전체 {pct(r['health_insurance'] * 2)}), "
        f"장기요양 건강보험료의 {pct(r['long_term_care'])}, "
        f"고용보험(실업급여) {pct(r['employment_insurance'])}"
        f"(전체 {pct(r['employment_insurance'] * 2)})\n"
        "- 산재보험: 근로자 부담 없음 (전액 사업주 부담)\n"
        f"- 국민연금 기준소득월액: 상한 {r['pension_income_max']:,}원"
        f" / 하한 {r['pension_income_min']:,}원\n"
        "(출처: 시스템 내장 상수 — 관계 법령·고시 기준)"
    )


# ── 지식 모듈 등록제 ──────────────────────────────────────────────────────────
# (이름, 빌더) — 빌더 시그니처: (query, analysis) -> str | None
# 계산기가 아니어도 검증된 사실(고시 금액·요율 등)을 LLM 컨텍스트에 공급하는 모듈.
# 새 지식 모듈은 여기에 등록만 하면 파이프라인 수정 없이 주입된다.
_KNOWLEDGE_MODULES = [
    ("최저임금", _build_minwage_facts),
    ("4대보험요율", _build_insurance_facts),
]


# 임금 정보 없이도 의미 있는 산출이 가능한 계산기 (schedule 기반 + 독립 계산)
# wage_arrears: 체불 지연이자는 arrear_amount/arrear_due_date만 필요 (facade 독립 함수)
_WAGELESS_TARGETS = {"working_hours", "weekly_hours_check", "wage_arrears"}


def _resolve_targets(calc_types: list[str], query: str, has_wage: bool) -> list[str] | None:
    """계산기 타깃 라우팅: 라벨 엄격 매칭(전체 유형 union) → 질문 키워드 추론 → 명시적 폴백.

    기존의 묵시적 minimum_wage 기본값(오배치가 티 안 나던 원인)을 제거하고,
    단계별로 로그를 남겨 라우팅 실패를 관측 가능하게 한다.
    복수 계산 유형은 순서 보존 union으로 전부 계산 대상에 포함한다(CALC-2).
    """
    merged: list[str] = []
    for label in calc_types:
        for t in (resolve_calc_type_strict(label) or []):
            if t not in merged:
                merged.append(t)
    if merged:
        return merged

    inferred = [t for t in infer_calc_types(query) if t in CALC_TYPES]
    if inferred:
        logger.info("계산 유형 라벨 미매칭(%r) — 질문 키워드 추론 사용: %s",
                    calc_types, inferred)
        return inferred

    if has_wage:
        logger.info("계산 유형 미확정(labels=%r) — 임금 정보 존재, 최저임금 검증만 실행",
                    calc_types)
        return ["minimum_wage"]

    logger.info("계산 유형 미확정(labels=%r) — 계산기 미실행, 상담 경로로 진행", calc_types)
    return None


def _run_calculator(params: dict, query: str = "") -> str | None:
    if not params or not params.get("needs_calculation"):
        return None

    wage_type_map = {
        "시급": WageType.HOURLY,
        "일급": WageType.DAILY,
        "월급": WageType.MONTHLY,
        "연봉": WageType.ANNUAL,
        "포괄임금제": WageType.COMPREHENSIVE,
    }
    wt = wage_type_map.get(params.get("wage_type", ""), WageType.MONTHLY)

    # use_minimum_wage 최우선: LLM이 wage_amount를 환각해도 법정 최저임금 강제 적용
    if params.get("use_minimum_wage"):
        from datetime import date as _date
        from wage_calculator.constants import MINIMUM_HOURLY_WAGE
        ref_year = int(params.get("reference_year") or _date.today().year)
        if ref_year not in MINIMUM_HOURLY_WAGE:
            ref_year = max(MINIMUM_HOURLY_WAGE.keys())
        amount = MINIMUM_HOURLY_WAGE[ref_year]
        wt = WageType.HOURLY
    else:
        amount = params.get("wage_amount")
        # 임금 정보가 없어도 즉시 포기하지 않는다 — 아래에서 임금이 필요 없는
        # 계산기(소정근로시간·주52시간 체크)만 부분 실행하는 경로로 이어간다.
        # 가드: LLM이 과거 연도 최저임금 값을 환각한 경우 보정
        # 예: 2026년인데 wage_amount=10030 (2025년 최저임금) → 10320으로 보정
        if amount and wt == WageType.HOURLY:
            from datetime import date as _date
            from wage_calculator.constants import MINIMUM_HOURLY_WAGE
            ref_year = int(params.get("reference_year") or _date.today().year)
            ref_min = MINIMUM_HOURLY_WAGE.get(ref_year)
            if ref_min and amount != ref_min and amount in MINIMUM_HOURLY_WAGE.values():
                amount = ref_min

    has_wage = bool(amount)

    weekly_days = params.get("weekly_work_days")
    weekly_total = params.get("weekly_total_hours")
    if weekly_total and weekly_days:
        daily_hours = weekly_total / weekly_days
    elif weekly_total:
        # 주당 총시간만 있고 근무일수 없음 → 기본 5일로 나누어 일일시간 산출
        # 가정 사실을 params에 기록 — 호출부가 답변 말미 확인 안내에 반영 (CALC-12)
        weekly_days = 5.0
        daily_hours = weekly_total / weekly_days
        params["assumed_weekly_days"] = True
    else:
        daily_hours = params.get("daily_work_hours")

    # None → WorkSchedule 모델 기본값 (8.0h, 5일) 사용
    # 핵심: LLM이 아닌 모델 레벨에서 기본값 관리
    schedule = WorkSchedule(
        daily_work_hours=daily_hours if daily_hours is not None else 8.0,
        weekly_work_days=weekly_days if weekly_days is not None else 5.0,
        weekly_overtime_hours=params.get("weekly_overtime_hours") or 0,
        weekly_night_hours=params.get("weekly_night_hours") or 0,
        weekly_holiday_hours=params.get("weekly_holiday_work_hours") or 0,
    )

    size_map = {
        "5인미만": BusinessSize.UNDER_5,
        "5인이상": BusinessSize.OVER_5,
        "30인이상": BusinessSize.OVER_30,
        "300인이상": BusinessSize.OVER_300,
    }
    biz_size = size_map.get(params.get("business_size", ""), BusinessSize.OVER_5)

    inp = WageInput(wage_type=wt, business_size=biz_size, schedule=schedule)

    # 기준 연도 설정
    if params.get("reference_year"):
        inp.reference_year = int(params["reference_year"])

    if has_wage:
        if wt == WageType.HOURLY:
            inp.hourly_wage = amount
        elif wt == WageType.DAILY:
            inp.daily_wage = amount
        elif wt in (WageType.MONTHLY, WageType.COMPREHENSIVE):
            inp.monthly_wage = amount
        elif wt == WageType.ANNUAL:
            inp.annual_wage = amount

    start = params.get("start_date", "")
    if start:
        if any(c in start for c in "년개월"):
            from wage_calculator.facade import _guess_start_date
            inp.start_date = _guess_start_date(start)
        else:
            inp.start_date = start
    if params.get("end_date"):
        inp.end_date = params["end_date"]

    # 특수고용직(노무제공자) 판별
    if params.get("is_platform_worker"):
        inp.is_platform_worker = True
        from wage_calculator.models import WorkType
        inp.work_type = WorkType.PLATFORM_WORKER

    # 수습·계약기간·직종 — 최저임금 수습 감액 판정에 소비 (CALC-1)
    if params.get("is_probation"):
        inp.is_probation = True
    if params.get("contract_months") is not None:
        inp.contract_months = int(params["contract_months"])
    if params.get("occupation_code"):
        inp.occupation_code = str(params["occupation_code"]).strip()

    # 해고예고·육아휴직·임금체불 — 배선 누락으로 계산이 조용히 skip되던 필드 (CALC-1)
    if params.get("notice_days_given") is not None:
        inp.notice_days_given = int(params["notice_days_given"])
    if params.get("parental_leave_months"):
        inp.parental_leave_months = int(params["parental_leave_months"])
    if params.get("arrear_amount"):
        inp.arrear_amount = float(params["arrear_amount"])
    if params.get("arrear_due_date"):
        inp.arrear_due_date = str(params["arrear_due_date"])

    # 고정수당 — facade가 dict 항목을 그대로 지원 (CALC-1)
    if params.get("fixed_allowances"):
        inp.fixed_allowances = [
            a for a in params["fixed_allowances"]
            if isinstance(a, dict) and a.get("amount")
        ]

    # 휴업수당·유급공휴일 (CALC-6 enum 확장분 배선)
    if params.get("shutdown_days"):
        inp.shutdown_days = int(params["shutdown_days"])
    if params.get("public_holiday_days"):
        inp.public_holiday_days = int(params["public_holiday_days"])

    calc_types = params.get("calculation_types_kr") or (
        [params["calculation_type"]] if params.get("calculation_type") else [])
    targets = _resolve_targets(calc_types, query, has_wage)
    if not targets:
        return None

    # 임금 정보 없음 → 임금이 필요 없는 계산기만 부분 실행 (0원 오검증 방지)
    if not has_wage:
        wageless = [t for t in targets if t in _WAGELESS_TARGETS]
        if not wageless:
            logger.info("임금 정보 없음 — 임금 필요 계산기(%s) 제외 후 실행 대상 없음, "
                        "계산기 미실행", targets)
            return None
        targets = wageless

    # 특수고용직: 근로기준법 미적용 계산기 제외 + insurance/legal_hints 자동 추가
    if inp.is_platform_worker:
        _pw_exclude = {
            "overtime", "weekly_holiday", "annual_leave", "dismissal",
            "severance", "comprehensive", "prorated", "public_holiday",
            "shutdown_allowance", "weekly_hours_check",
            "retirement_tax", "retirement_pension",
        }
        targets = [t for t in targets if t not in _pw_exclude]
        if "insurance" not in targets:
            targets.append("insurance")
        if "legal_hints" not in targets:
            targets.append("legal_hints")

    try:
        calc = WageCalculator()
        result = calc.calculate(inp, targets)
        if not has_wage:
            # 임금 미제공 부분 실행 — 0원 통상임금 계산식 노이즈 제거
            result.formulas = [f for f in result.formulas
                               if not f.startswith("[통상임금]")]
        return format_result(result)
    except Exception:
        # 오류 문자열이 '정확한 계산' 헤더로 LLM에 주입되던 경로 차단 (CALC-3)
        logger.exception("계산기 실행 실패 — 계산 없이 상담 경로로 진행 (targets=%s)", targets)
        return None


# ── 계산 유형별 필수 필드 정의 ────────────────────────────────────────────────
# 각 항목: (대체 가능 필드 집합, 사용자에게 보여줄 한국어 설명)
# 필드 집합 중 하나라도 extracted_info에 있으면 충족된 것으로 판정

# use_minimum_wage=true이면 임금 정보 충족으로 판정 (시스템이 법정 최저임금 자동 적용)
_WAGE_FIELDS = {"wage_amount", "monthly_wage", "annual_wage", "hourly_wage", "daily_wage", "use_minimum_wage"}
_WAGE_FIELDS_NO_HOURLY = {"wage_amount", "monthly_wage", "annual_wage", "use_minimum_wage"}

_REQUIRED_FIELDS: dict[str, list[tuple[set[str], str]]] = {
    "overtime": [
        (_WAGE_FIELDS, "임금 (시급/월급/연봉)"),
        ({"daily_work_hours", "weekly_total_hours"}, "1일 소정근로시간 또는 주 소정근로시간"),
        ({"weekly_overtime_hours"}, "주당 연장근로시간"),
    ],
    "minimum_wage": [
        (_WAGE_FIELDS, "현재 받는 임금 (시급/월급/연봉)"),
        ({"daily_work_hours", "weekly_total_hours"}, "1일 소정근로시간 또는 주 소정근로시간"),
    ],
    "weekly_holiday": [
        (_WAGE_FIELDS, "임금 (시급/월급/연봉)"),
        ({"weekly_work_days"}, "주당 근무일수"),
        ({"daily_work_hours", "weekly_total_hours"}, "1일 소정근로시간 또는 주 소정근로시간"),
    ],
    "severance": [
        (_WAGE_FIELDS_NO_HOURLY, "임금 (월급 또는 연봉)"),
        ({"start_date", "service_period_text"}, "입사일 또는 근무기간"),
    ],
    "annual_leave": [
        (_WAGE_FIELDS_NO_HOURLY, "임금 (월급 또는 연봉)"),
        ({"start_date", "service_period_text"}, "입사일 또는 근무기간"),
    ],
    "dismissal": [
        (_WAGE_FIELDS_NO_HOURLY, "임금 (월급 또는 연봉)"),
        ({"start_date", "service_period_text"}, "입사일 또는 근무기간"),
    ],
    "unemployment": [
        (_WAGE_FIELDS_NO_HOURLY, "퇴직 전 월 평균 임금"),
    ],
    "insurance": [
        (_WAGE_FIELDS_NO_HOURLY, "임금 (월급 또는 연봉)"),
    ],
    "parental_leave": [
        (_WAGE_FIELDS_NO_HOURLY, "임금 (월급 또는 연봉)"),
        ({"parental_leave_months"}, "육아휴직 예정 개월수"),
    ],
    "maternity_leave": [
        (_WAGE_FIELDS_NO_HOURLY, "임금 (월급 또는 연봉)"),
    ],
    "wage_arrears": [
        ({"arrear_amount"}, "체불 임금액"),
        ({"arrear_due_date"}, "체불 발생일 (원래 급여일)"),
    ],
    "compensatory_leave": [
        (_WAGE_FIELDS, "임금 (시급/월급)"),
        ({"weekly_overtime_hours"}, "주당 연장근로시간"),
    ],
    "flexible_work": [
        (_WAGE_FIELDS, "임금 (시급/월급)"),
    ],
    "comprehensive": [
        ({"monthly_wage"}, "포괄임금제 월급 총액"),
        ({"daily_work_hours", "weekly_total_hours"}, "1일 소정근로시간 또는 주 소정근로시간"),
        ({"weekly_overtime_hours"}, "월 고정 연장근로시간"),
    ],
    "eitc": [
        ({"annual_wage", "monthly_wage", "wage_amount"}, "연간 총 소득 (또는 월급)"),
    ],
    # enum 확장분 (CALC-6) — 누락 판정 공백 방지
    "average_wage": [
        (_WAGE_FIELDS_NO_HOURLY, "임금 (월급 또는 연봉)"),
    ],
    "shutdown_allowance": [
        (_WAGE_FIELDS_NO_HOURLY, "임금 (월급 또는 연봉)"),
        ({"shutdown_days"}, "휴업 일수"),
    ],
    "public_holiday": [
        (_WAGE_FIELDS, "임금 (시급/월급)"),
        ({"public_holiday_days"}, "유급 공휴일 일수"),
    ],
    "working_hours": [
        ({"daily_work_hours", "weekly_total_hours"}, "1일 소정근로시간 또는 주 소정근로시간"),
    ],
}


_CALC_TYPE_LABELS: dict[str, str] = {
    "overtime": "연장·야간·휴일수당",
    "minimum_wage": "최저임금 검증",
    "weekly_holiday": "주휴수당",
    "annual_leave": "연차수당",
    "severance": "퇴직금",
    "dismissal": "해고예고수당",
    "unemployment": "실업급여",
    "insurance": "4대보험·소득세",
    "parental_leave": "육아휴직급여",
    "maternity_leave": "출산전후휴가급여",
    "wage_arrears": "임금체불 지연이자",
    "compensatory_leave": "보상휴가",
    "flexible_work": "탄력근무 수당",
    "comprehensive": "포괄임금제 검증",
    "prorated": "일할계산",
    "eitc": "근로장려금",
}


def _code_based_summary(calc_types: list[str]) -> str:
    """calculation_types를 코드 기반 한국어 요약으로 변환 (LLM 비의존, 항상 일관)"""
    labels = [_CALC_TYPE_LABELS.get(t, t) for t in calc_types]
    return "·".join(labels) + " 계산"


def _compute_missing_info(calc_types: list[str], extracted_info: dict) -> list[str]:
    """계산 유형별 필수 필드를 코드 레벨에서 판정하여 누락 항목 목록 반환.

    LLM의 자유형 missing_info 대신 사용 → 매번 동일한 결과 보장.
    """
    missing = []
    seen_descriptions = set()

    for calc_type in calc_types:
        requirements = _REQUIRED_FIELDS.get(calc_type, [])
        for field_group, description in requirements:
            if description in seen_descriptions:
                continue
            # 필드 그룹 중 하나라도 있으면 충족
            if not any(extracted_info.get(f) for f in field_group):
                missing.append(description)
                seen_descriptions.add(description)

    return missing


def _analysis_to_extract_params(analysis) -> dict:
    """AnalysisResult.extracted_info를 기존 _extract_params 반환 형식으로 변환"""
    info = analysis.extracted_info
    # weekly_total_hours 우선: LLM이 직접 주당 총시간을 제공한 경우 사용
    # daily_work_hours × weekly_work_days는 weekly_total_hours가 없을 때만 계산
    weekly_total = info.get("weekly_total_hours")
    daily = info.get("daily_work_hours")
    days = info.get("weekly_work_days")
    if not weekly_total and daily and days:
        weekly_total = daily * days

    REVERSE_CALC_MAP = {
        "overtime": "연장수당", "weekly_holiday": "주휴수당",
        "minimum_wage": "최저임금", "severance": "퇴직금",
        "annual_leave": "연차수당", "dismissal": "해고예고수당",
        "unemployment": "실업급여", "insurance": "4대보험",
        "parental_leave": "육아휴직", "maternity_leave": "출산휴가",
        "wage_arrears": "임금체불", "compensatory_leave": "보상휴가",
        "flexible_work": "탄력근무", "comprehensive": "포괄임금제",
        "eitc": "근로장려금",
        # enum 확장분 (CALC-6) — 전부 CALC_TYPE_MAP 기존/신규 키로 연결
        "average_wage": "평균임금", "industrial_accident": "산재보상",
        "shutdown_allowance": "휴업수당", "working_hours": "근로시간산정",
        "public_holiday": "유급공휴일", "ordinary_wage": "통상임금",
        "retirement_tax": "퇴직소득세", "retirement_pension": "퇴직연금",
        "business_size": "사업장규모",
    }
    # 전체 계산 유형을 라벨로 변환 — 첫 유형만 계산되던 결함 수정 (CALC-2)
    labels = [REVERSE_CALC_MAP[ct] for ct in (analysis.calculation_types or [])
              if ct in REVERSE_CALC_MAP]
    calc_type = labels[0] if labels else "임금계산"

    params = {
        "needs_calculation": analysis.requires_calculation,
        "calculation_type": calc_type,
        "calculation_types_kr": labels or None,
        "wage_type": info.get("wage_type"),
        "wage_amount": info.get("wage_amount") or info.get("monthly_wage") or info.get("annual_wage"),
        "weekly_work_days": info.get("weekly_work_days"),
        "daily_work_hours": info.get("daily_work_hours"),
        "weekly_total_hours": weekly_total,
        "weekly_overtime_hours": info.get("weekly_overtime_hours"),
        "weekly_night_hours": info.get("weekly_night_hours"),
        "weekly_holiday_work_hours": info.get("weekly_holiday_hours"),
        "business_size": info.get("business_size"),
        "start_date": info.get("start_date") or info.get("service_period_text"),
        "end_date": info.get("end_date"),
        "use_minimum_wage": info.get("use_minimum_wage"),
        "reference_year": info.get("reference_year"),
        "is_platform_worker": info.get("is_platform_worker"),
        "is_probation": info.get("is_probation"),
        "contract_months": info.get("contract_months"),
        # 계산기 소비처가 있는데 배선이 끊겨 있던 필드들 (CALC-1)
        "occupation_code": info.get("occupation_code"),
        "notice_days_given": info.get("notice_days_given"),
        "parental_leave_months": info.get("parental_leave_months"),
        "arrear_amount": info.get("arrear_amount"),
        "arrear_due_date": info.get("arrear_due_date"),
        "fixed_allowances": info.get("fixed_allowances"),
        "shutdown_days": info.get("shutdown_days"),
        "public_holiday_days": info.get("public_holiday_days"),
    }
    return {k: v for k, v in params.items() if v is not None}


def _run_assessor(params: dict) -> str | None:
    if not params or not params.get("is_harassment_question"):
        return None
    inp = HarassmentInput(
        perpetrator_role=params.get("perpetrator_role", ""),
        victim_role=params.get("victim_role", ""),
        relationship_type=params.get("relationship_type", ""),
        behavior_description=params.get("behavior_description", ""),
        behavior_types=params.get("behavior_types", []),
        frequency=params.get("frequency", ""),
        duration=params.get("duration", ""),
        witnesses=params.get("witnesses", False),
        evidence=params.get("evidence", []),
        impact=params.get("impact", ""),
        company_response=params.get("company_response", ""),
        business_size=params.get("business_size", ""),
    )
    try:
        result = assess_harassment(inp)
        return format_assessment(result)
    except Exception as e:
        return f"[괴롭힘 판정 오류: {e}]"


# ── 답변 생성 ─────────────────────────────────────────────────────────────────

SYSTEM_PROMPT_TEMPLATE = """당신은 한국 노동법 전문 상담사입니다.

오늘 날짜: {today}
※ 사용자가 연도를 명시하지 않은 날짜(예: "2월28일")는 오늘 날짜 기준으로 해석하세요. 과거 시제이면 가장 최근의 해당 날짜입니다.

답변 원칙:
1. **임금계산기 결과가 포함된 경우** (가장 중요):
   - 계산기 결과의 수치를 그대로 사용하세요. 절대로 직접 계산하거나 다른 수치를 제시하지 마세요.
   - 계산기의 계산 과정(formulas)과 법적 근거를 자연스럽게 풀어서 설명하세요.
   - 계산기의 주의사항(warnings)이 있으면 반드시 포함하세요.
2. **면책 고지** (절대 규칙 — 예외 없이 모든 답변 마지막에 포함):
   답변 본문을 모두 작성한 후, 반드시 마지막 줄에 아래 문장을 그대로 출력하세요.
   이 규칙을 지키지 않으면 답변이 불완전한 것으로 간주됩니다.
   출력할 문장: "⚠️ 본 답변은 참고용 정보 제공이며 법적 효력이 없습니다. 구체적인 사안은 관할 고용노동부(☎ 1350) 또는 공인노무사에게 상담하시기 바랍니다."
3. 참고 자료(판례·행정해석·법조문)가 제공된 경우, 해당 내용을 바탕으로 정확하게 답변하세요.
4. 관련 법 조문이나 행정해석이 있으면 함께 언급하세요.
5. 참고 자료가 없는 경우:
   - 한국 노동법 지식을 바탕으로 답변하되, 답변 서두에 "⚠️ 일반 노동법 지식을 기반으로 작성된 답변입니다. 정확한 사항은 고용노동부(☎ 1350) 또는 공인노무사에게 확인하시기 바랍니다."를 명시하세요.
   - 관련 법 조문(근로기준법, 시행령 등)을 반드시 인용하세요.
6. **판례·행정해석 인용 규칙** (절대 규칙):
   - [인용 가능한 판례·행정해석 목록]에 있는 것만 번호를 표기하세요.
   - 목록에 없는 판례·해석은 번호 없이 내용만 서술하고,
     "관련 판례가 있을 수 있으나 구체적 번호는 law.go.kr에서 확인이 필요합니다"로 안내하세요.
   - 절대로 기억이나 추측으로 판례 번호를 생성하지 마세요.
7. **괴롭힘 판정 결과가 포함된 경우**:
   - 판정기의 3요소 판정 결과와 종합 가능성을 그대로 사용하세요.
   - 판정 근거, 법적 조문, 대응 절차, 주의사항을 자연스럽게 설명하세요.
   - 면책 문구(법적 효력 없는 참고 정보)를 반드시 포함하세요.
8. 법적 조언이 아닌 정보 제공임을 명심하세요.
9. 질문에 이미 계산에 필요한 정보가 포함되어 있으면 추가 질문 없이 바로 답변하세요.
   **사용자가 일부 정보만 제공한 경우**:
   - 제공된 정보만으로 가능한 범위 내에서 답변하세요. 추가 정보가 없다고 답변을 거부하지 마세요.
   - 계산기 결과가 없더라도 일반적인 기준(법정 기준 등)으로 설명하세요.
   - 답변 말미에 "더 정확한 계산을 위해 아래 정보를 추가로 알려주시면 맞춤 계산이 가능합니다:" 형태로 자연스럽게 안내하세요.
   - [사용자에게 안내할 추가 정보 요청]이 컨텍스트에 포함된 경우, 해당 항목을 답변 말미에 포함하세요.
10. **답변 시각화 규칙** (마크다운 적극 활용):
   - **구조**: `##` 소제목으로 섹션을 나누세요 (예: ## 계산 결과, ## 법적 근거, ## 주의사항).
   - **표**: 금액 비교, 계산 결과, 보험료 내역 등 숫자 데이터는 반드시 표로 정리하세요.
     예시: | 항목 | 금액 | 산출 근거 |
   - **강조**: 핵심 금액·결론은 **볼드**로, 법조문명은 **볼드**로 표시하세요.
   - **목록**: 절차·조건·요건 나열은 번호 목록(1. 2. 3.)이나 글머리 기호(-)를 사용하세요.
   - **인용문**: 법조문 원문이나 판례 요지는 `>` 인용문으로 표시하세요.
   - **구분선**: 주요 섹션 사이에 `---`를 사용하세요.
   - **계산 과정**: 단계별 계산은 번호 목록 + 볼드로 핵심 수치를 강조하세요.
     예시:
     1. 시간급 통상임금: **12,500원**
     2. 주휴수당: 12,500원 × 8h = **100,000원**
   - **요약 → 상세 순서**: 핵심 결론을 먼저 1~2문장으로 제시한 후 상세 설명을 이어가세요.
11. **노동위원회 연락처가 포함된 경우**:
   - 부당해고 구제신청, 부당노동행위, 차별시정, 노동쟁의 조정 등 노동위원회 소관 사안이면
     제공된 노동위원회 연락처를 답변에 포함하세요.
   - 임금체불, 근로기준법 위반 등 고용노동부(근로감독관) 소관 사안은 기존대로 1350을 안내하세요.
   - 해고를 당한 근로자에게는 노동위원회 구제신청(30일 이내)을 반드시 안내하세요.
12. **고용센터 연락처가 포함된 경우**:
   - 실업급여(구직급여) 신청, 구직활동 지원, 직업훈련(내일배움카드), 고용보험, 취업지원 등
     고용센터 소관 사안이면 제공된 고용센터 연락처를 답변에 포함하세요.
   - 고용센터 연락처에 홈페이지 URL이 있으면 함께 안내하세요.
   - 지역 정보가 없으면 1350 전화 + 고용24(work24.go.kr) 검색을 안내하세요.
13. **근로복지공단 연락처가 포함된 경우**:
   - 산재보험(요양·휴업·장해급여), 체당금(체불임금보장), 근로복지대부(생활·주거안정자금),
     퇴직연금, 직업재활 등 근로복지공단 소관 사안이면 제공된 근로복지공단 연락처를 답변에 포함하세요.
   - 근로복지공단 대표전화 1588-0075도 함께 안내하세요.
   - 지역 정보가 없으면 1588-0075 + 지사 찾기 링크를 안내하세요.
14. **중앙노동위원회 판정사례가 포함된 경우**:
   - 사용자 질문과 관련된 중앙노동위원회 주요판정사례가 제공됩니다.
   - 판정 제목과 자료구분(징계해고, 부당노동행위 등)을 참고하여 유사 사례를 안내하세요.
   - 관련 판례가 함께 제공된 경우 해당 판례도 인용하세요.
   - 출처를 "(중앙노동위원회 주요판정사례)"로 명시하세요.
15. **현행 법조문이 포함된 경우**:
   - 법제처 국가법령정보센터에서 조회한 최신 법조문이 제공됩니다.
   - 이 법조문을 우선 참조하여 답변하세요.
   - 법조문 출처를 "(법제처 국가법령정보센터 조회)"로 명시하세요.
16. **면책 고지 재확인**: 답변의 마지막 줄에 "⚠️ 본 답변은 참고용 정보 제공이며 법적 효력이 없습니다. 구체적인 사안은 관할 고용노동부(☎ 1350) 또는 공인노무사에게 상담하시기 바랍니다."가 반드시 있어야 합니다. 없으면 추가하세요.
"""


def process_question(query: str, session: Session, config: AppConfig,
                     attachments: list[ParsedAttachment] | None = None):
    """
    질문 처리 제너레이터 — yield하는 이벤트 타입:
      {"type": "status", "text": "..."}       — 진행 상태
      {"type": "meta",   "calc_result": ...}  — 계산기 결과 (있을 때만)
      {"type": "sources", "hits": [...]}      — 검색 출처
      {"type": "chunk",  "text": "..."}       — 스트리밍 답변 텍스트
      {"type": "done"}                        — 완료
    """
    # 0. 첨부파일에서 추출된 텍스트 병합
    attachment_text = ""
    if attachments:
        text_parts = []
        for att in attachments:
            if att.extracted_text:
                text_parts.append(f"[첨부: {att.filename}]\n{att.extracted_text}")
        attachment_text = "\n\n".join(text_parts)

    combined_query = query
    if attachment_text:
        combined_query = f"{query}\n\n첨부된 문서 내용:\n{_cap(attachment_text, 4000)}"

    # 1. 의도 분석 + 추가 질문 판단
    yield {"type": "status", "text": "질문 분석 중..."}

    use_analysis_params = False
    analysis = None
    prefilled_keys: list[str] = []

    try:
        if session.has_pending_info():
            # 추가 정보 제공됨 → 기존 pending과 병합
            new_analysis = analyze_intent(
                combined_query, session.recent(), config,
                summary=session.summary,
            )
            analysis = session.merge_with_pending(new_analysis, query)
            use_analysis_params = True
        else:
            # 새 질문 → 분석
            analysis = analyze_intent(
                combined_query, session.recent(), config,
                summary=session.summary,
            )

            # 캐시 기반 extracted_info 프리필 — 동일 계산 유형의 캐시만 사용해
            # 무관한 이전 질문 파라미터의 교차오염을 차단 (CALC-4)
            if analysis.calculation_types:
                cached = session.get_cached_info(analysis.calculation_types)
                for key, val in cached.items():
                    if key not in analysis.extracted_info or analysis.extracted_info[key] is None:
                        analysis.extracted_info[key] = val
                        prefilled_keys.append(key)
                if prefilled_keys:
                    logger.info("calc_cache 프리필(%s): %s",
                                analysis.calculation_types, prefilled_keys)

            # 코드 기반 누락 정보 판정 (LLM의 자유형 missing_info 대체)
            if analysis.requires_calculation and analysis.calculation_types:
                code_missing = _compute_missing_info(
                    analysis.calculation_types, analysis.extracted_info
                )
                # LLM missing_info를 코드 판정 결과로 교체하되,
                # 숫자 범위 검증이 제거한 라벨은 보존 (CALC-13)
                analysis.missing_info = code_missing + [
                    w for w in analysis.validation_warnings
                    if w not in code_missing
                ]

            # 분석에서 계산이 필요하면 (누락 정보 유무와 관계없이) 진행
            # 누락 정보가 있어도 가능한 범위 내에서 답변하고, 추가정보 안내를 포함
            if analysis.requires_calculation and analysis.extracted_info:
                use_analysis_params = True
    except Exception:
        # 분석 실패 시 기존 로직으로 fallback — 원인은 로그로 관측 (CALC-7)
        logger.exception("의도분석 실패 — 레거시 추출 경로로 폴백")
        session.clear_pending()
        use_analysis_params = False

    # 2. 질문 분류 + 파라미터 추출
    calc_result = None
    assessment_result = None
    params = None

    if use_analysis_params and analysis:
        # analyze_intent 결과를 기존 파라미터 형식으로 변환
        params = _analysis_to_extract_params(analysis)
        if params.get("needs_calculation"):
            _ensure_minimum_wage_flag(params, query)
            if _normalize_wage_units(params):
                analysis.missing_info.append("임금액 단위(만원으로 해석함) 확인")
            yield {"type": "status", "text": "임금계산기 실행 중..."}
            calc_result = _run_calculator(params, query)
            if calc_result:
                if params.get("assumed_weekly_days"):
                    analysis.missing_info.append("주 근무일수 (5일로 가정하고 계산함)")
                # 계산 결과 캐싱
                for ct in (analysis.calculation_types or []):
                    session.cache_calculation(ct, analysis.extracted_info)
                yield {"type": "meta", "calc_result": calc_result}
    else:
        # 계산/괴롭힘 가능성이 있을 때만 _extract_params(Sonnet) 호출 — 순수 상담 트래픽의
        # 불필요한 2차 LLM 호출을 회피해 지연·비용 절감(R-2a).
        analysis_calc = bool(analysis and getattr(analysis, "requires_calculation", False))
        topic = getattr(analysis, "consultation_topic", "") if analysis else ""
        harass_likely = (topic == "직장내괴롭힘") or any(kw in query for kw in _HARASS_KEYWORDS)
        if analysis is None or analysis_calc or harass_likely:
            tool_type, params = _extract_params(combined_query, config.claude_client)

            if tool_type == "wage" and params and params.get("needs_calculation"):
                _ensure_minimum_wage_flag(params, query)
                _normalize_wage_units(params)
                yield {"type": "status", "text": "임금계산기 실행 중..."}
                calc_result = _run_calculator(params, query)
                if calc_result:
                    yield {"type": "meta", "calc_result": calc_result}
            elif tool_type == "harassment" and params and params.get("is_harassment_question"):
                yield {"type": "status", "text": "괴롭힘 판정 중..."}
                assessment_result = _run_assessor(params)
                if assessment_result:
                    yield {"type": "meta", "assessment_result": assessment_result}
        # else: 순수 비계산·비괴롭힘 상담 → _extract_params 생략, RAG/상담 경로로 진행

    # 2-1. 법령 API 조문 조회 (선택적 — API 키 있고 relevant_laws 추출 시)
    legal_articles_text = None
    if analysis and analysis.relevant_laws and config.law_api_key:
        try:
            legal_articles_text = fetch_relevant_articles(
                analysis.relevant_laws, config.law_api_key
            )
            if legal_articles_text:
                logger.info("법령 API 조문 %d건 조회 완료", len(analysis.relevant_laws))
        except Exception as e:
            logger.warning("법령 API 조회 실패 (무시하고 진행): %s", e)

    # 2-1b. 판례·행정해석 검색 (Pinecone 우선 → 법제처 API 폴백)
    precedent_text = None
    precedent_meta: list[dict] = []
    if analysis:
        try:
            yield {"type": "status", "text": "관련 판례 검색 중..."}

            # ── Adaptive Retrieval: 복잡도 분류 → 파라미터 동적 조정 ──
            try:
                complexity = classify_complexity(
                    query,
                    relevant_laws=getattr(analysis, "relevant_laws", None),
                    calculation_types=analysis.calculation_types if analysis.requires_calculation else None,
                )
            except Exception:
                from app.core.query_decomposer import QueryComplexity
                complexity = QueryComplexity.MODERATE
            adaptive_params = COMPLEXITY_PARAMS[complexity]
            logger.info("Adaptive: %s → top_k=%d, rerank_n=%d, self_rag=%s",
                        complexity.value,
                        adaptive_params["search_top_k"],
                        adaptive_params["rerank_top_n"],
                        adaptive_params["self_rag"])

            # 맥락 기반 쿼리 확장 (규칙 기반)
            prec_queries = []
            if getattr(analysis, "precedent_keywords", None):
                prec_queries = build_precedent_queries(
                    precedent_keywords=analysis.precedent_keywords,
                    relevant_laws=analysis.relevant_laws or None,
                    consultation_topic=analysis.consultation_topic,
                )

            # LLM 멀티쿼리 분해 — Adaptive: SIMPLE은 건너뜀, COMPLEX는 강제 분해
            if adaptive_params["max_queries"] <= 1:
                decomposed = []
            else:
                decomposed = decompose_query(
                    query,
                    config.claude_client,
                    consultation_topic=getattr(analysis, "consultation_topic", None),
                    question_summary=getattr(analysis, "question_summary", None),
                    force=adaptive_params.get("force_decompose", False),
                )

            # 쿼리 병합: LLM 분해 + 규칙 기반 + 폴백(원본)
            pinecone_search_queries = _merge_search_queries(
                decomposed=decomposed,
                rule_based=prec_queries,
                fallback=getattr(analysis, "question_summary", None) or query[:80],
                max_total=adaptive_params["max_queries"] + 2,
            )

            # ① Hybrid Search (Dense + BM25 RRF) — Adaptive top_k
            search_top_k = adaptive_params["search_top_k"] if config.cohere_api_key else 5
            pinecone_hits = search_hybrid(
                pinecone_search_queries, config, top_k=search_top_k,
            )

            # ② Cohere Rerank — Adaptive top_n
            if pinecone_hits and config.cohere_api_key:
                pinecone_hits = rerank_results(
                    query, pinecone_hits, config.cohere_api_key,
                    top_n=adaptive_params["rerank_top_n"],
                )

            # ③ Self-RAG 관련성 필터 (COMPLEX만)
            if adaptive_params["self_rag"] and pinecone_hits and len(pinecone_hits) > 2:
                try:
                    from app.core.self_rag import filter_by_relevance
                    pinecone_hits, needs_wider = filter_by_relevance(
                        query, pinecone_hits, config.claude_client,
                    )
                    if needs_wider:
                        logger.info("Self-RAG wider search: top_k %d → %d",
                                    search_top_k, search_top_k * 2)
                        wider_hits = search_hybrid(
                            pinecone_search_queries, config,
                            top_k=search_top_k * 2,
                        )
                        if wider_hits and config.cohere_api_key:
                            wider_hits = rerank_results(
                                query, wider_hits, config.cohere_api_key,
                                top_n=adaptive_params["rerank_top_n"] + 3,
                            )
                        if wider_hits:
                            pinecone_hits = wider_hits
                except Exception as e:
                    logger.warning("Self-RAG 실패 (rerank 결과 유지): %s", e)

            if pinecone_hits:
                precedent_text, precedent_meta = format_pinecone_hits(pinecone_hits)
                logger.info("Pinecone 판례·행정해석 %d건 사용", len(pinecone_hits))

            # ② Pinecone 결과 부족 시 법제처 API 폴백
            if not precedent_text and config.law_api_key:
                if prec_queries:
                    prec_results = search_precedent_multi(
                        prec_queries, config.law_api_key, max_total=5,
                    )
                    if prec_results:
                        precedent_text, precedent_meta = fetch_precedent_details(
                            prec_results, config.law_api_key,
                        )
                if not precedent_text:
                    prec_query = getattr(analysis, "question_summary", None) or query[:80]
                    precedent_text, precedent_meta = fetch_relevant_precedents(
                        prec_query, config.law_api_key, max_results=3,
                    )
                if precedent_text:
                    logger.info("법제처 API 판례 폴백 사용")
        except Exception as e:
            logger.warning("판례 검색 실패 (무시하고 진행): %s", e)

    # 2-1c. 중앙노동위원회 주요판정사례 검색 (odcloud API + 법제처 보강)
    nlrc_text = None
    if analysis and config.odcloud_api_key:
        try:
            nlrc_keywords = getattr(analysis, "precedent_keywords", None) or []
            # consultation_topic에서 추가 키워드 추출
            topic = getattr(analysis, "consultation_topic", None)
            if topic:
                nlrc_keywords = list(nlrc_keywords) + [topic.replace("·", " ")]
            if nlrc_keywords:
                nlrc_text = search_nlrc_with_details(
                    nlrc_keywords,
                    odcloud_api_key=config.odcloud_api_key,
                    law_api_key=config.law_api_key,
                    max_results=3,
                )
                if nlrc_text:
                    logger.info("NLRC 판정사례 검색 완료")
        except Exception as e:
            logger.warning("NLRC 판정사례 검색 실패 (무시): %s", e)

    # 2-2. 법률상담 전용 경로 (consultation_type 감지 시)
    consultation_context = None
    consultation_hits = []
    if (analysis
            and analysis.consultation_type
            and not calc_result
            and not assessment_result):
        yield {"type": "status", "text": "법률 자료 검색 중..."}
        try:
            consultation_context, consultation_hits = process_consultation(
                query=query,
                consultation_topic=analysis.consultation_topic,
                relevant_laws=analysis.relevant_laws,
                config=config,
            )
        except Exception as e:
            logger.warning("법률상담 처리 실패 (RAG fallback): %s", e)

    yield {"type": "sources",
           "hits": _build_sources_payload(precedent_meta, consultation_hits)}

    # ── GraphRAG 검색 ─────────────────────────────────────────────────
    graph_context = ""
    if analysis:
        try:
            from app.core.graph import graph_search
            graph_context, _graph_results = graph_search(
                relevant_laws=analysis.relevant_laws,
                precedent_keywords=getattr(analysis, "precedent_keywords", None),
                consultation_topic=getattr(analysis, "consultation_topic", None),
                calculation_types=analysis.calculation_types if analysis.requires_calculation else None,
            )
        except Exception as e:
            logger.warning("GraphRAG 검색 실패 (fallback): %s", e)

    has_attachments = attachments and len(attachments) > 0

    # ── 정보 충돌 해결: 동일 법 조항 소스 간 우선순위 안내 ──
    conflict_note = None
    try:
        from app.core.conflict_resolver import annotate_source_priority
        conflict_note = annotate_source_priority(
            precedent_text=precedent_text,
            legal_articles_text=legal_articles_text,
            nlrc_text=nlrc_text,
        )
    except Exception as e:
        logger.debug("충돌 해결 모듈 실패 (무시): %s", e)

    # 3. 컨텍스트 구성
    # 인용 가능 목록·사후 검증이 같은 원천을 쓰도록 화이트리스트 hits를 한 번 구성 (DB-4)
    whitelist_hits = _citation_source_hits(
        consultation_hits if consultation_context else None,
        precedent_meta, legal_articles_text, nlrc_text, graph_context,
    )
    if consultation_context:
        # 법률상담 경로: 전용 컨텍스트 사용
        parts = [f"참고 자료:\n\n{_cap(consultation_context, 8000)}"]
        # 인용 가능한 판례 목록 명시 (환각 방지)
        parts.append(build_available_citations_text(
            whitelist_hits, legal_precedents=precedent_meta,
        ))
    else:
        parts = []
        # 비 consultation 경로에서도 인용 가능 목록 주입 (환각 방지)
        if whitelist_hits:
            parts.append(build_available_citations_text(
                whitelist_hits, legal_precedents=precedent_meta,
            ))
    if graph_context:
        parts.append(f"법령 관계 분석 (지식 그래프):\n\n{graph_context}")
    if precedent_text:
        parts.append(f"관련 판례 (법제처 국가법령정보센터 검색):\n\n{_cap(precedent_text, 8000)}")
    if calc_result:
        parts.append(f"임금계산기 결과 (정확한 계산 — 이 수치를 사용하세요):\n\n{calc_result}")
    # 지식 모듈: 트리거되는 모듈의 검증된 사실 블록을 순서대로 주입
    for _km_name, _km_builder in _KNOWLEDGE_MODULES:
        try:
            _km_block = _km_builder(query, analysis)
            if _km_block:
                parts.append(_km_block)
        except Exception as e:
            logger.warning("지식 모듈 %s 실패 (무시): %s", _km_name, e)
    if assessment_result:
        parts.append(f"괴롭힘 판정 결과 (판정기 분석 — 이 결과를 사용하세요):\n\n{assessment_result}")
    if nlrc_text:
        parts.append(f"중앙노동위원회 주요판정사례 (공공데이터포털 조회):\n\n{_cap(nlrc_text, 4000)}")
    if legal_articles_text:
        parts.append(f"현행 법조문 (법제처 국가법령정보센터 조회):\n\n{_cap(legal_articles_text, 5000)}")
    # 이미지 첨부는 Vision 블록으로 전달되므로 텍스트 프롬프트에서 제외 — 이중 주입 방지 (DB-5)
    non_vision_attachment_text = "\n\n".join(
        f"[첨부: {att.filename}]\n{att.extracted_text}"
        for att in (attachments or [])
        if att.extracted_text and not att.vision_block
    )
    if non_vision_attachment_text:
        parts.append(f"첨부된 문서 내용:\n\n{_cap(non_vision_attachment_text, 6000)}")

    # ── FR-01: 정보 충돌 우선순위 안내 (최상단 배치) ──
    if conflict_note:
        parts.insert(0, conflict_note)

    # ── FR-02: 특수 근로자 그룹 법적 컨텍스트 주입 ──
    worker_ctx = _build_worker_group_context(
        getattr(analysis, "worker_group", None) if analysis else None
    )
    if worker_ctx:
        # 충돌 메모 다음, 나머지 컨텍스트 앞에 배치
        insert_pos = 1 if conflict_note else 0
        parts.insert(insert_pos, worker_ctx)

    # 이전 대화 값 재사용 안내 — 프리필이 조용히 계산에 스며드는 것을 표면화 (CALC-4)
    if prefilled_keys and calc_result:
        parts.append(
            "[이전 대화에서 재사용한 정보] " + ", ".join(prefilled_keys) + "\n"
            "→ 새 사업장·다른 조건에 대한 질문이라면 위 값이 다를 수 있음을 "
            "답변에서 자연스럽게 짚어주세요."
        )

    # 누락 정보 안내 (계산 시도 후에도 부족한 정보가 있을 때)
    if analysis and analysis.missing_info:
        deterministic_summary = _code_based_summary(analysis.calculation_types)
        missing_lines = [f"  {i}. {info}" for i, info in enumerate(analysis.missing_info, 1)]
        parts.append(
            f"[사용자에게 안내할 추가 정보 요청]\n"
            f"'{deterministic_summary}'에 대해 아래 정보가 제공되지 않았습니다:\n"
            + "\n".join(missing_lines) + "\n"
            f"답변 시 제공된 정보 범위 내에서 최대한 답변하되, "
            f"답변 말미에 더 정확한 계산을 위해 필요한 정보를 자연스럽게 안내하세요."
        )

    # 노동위원회 연락처 (해고·차별·쟁의 관련 시)
    _COMMISSION_KEYWORDS = ["해고", "부당해고", "구제신청", "부당노동행위", "차별시정",
                            "노동쟁의", "조정신청", "노동위원회", "교섭대표"]
    if any(kw in query for kw in _COMMISSION_KEYWORDS):
        comm = find_commission(query)
        if comm:
            parts.append(f"관할 노동위원회 연락처:\n\n{format_commission(comm)}")
        else:
            parts.append(f"노동위원회 연락처:\n\n{format_all_commissions()}")

    # 고용센터 연락처 (실업급여·구직·직업훈련 관련 시)
    _CENTER_KEYWORDS = ["실업급여", "구직급여", "구직활동", "구직등록", "실업",
                        "직업훈련", "내일배움카드", "국비훈련", "취업지원", "취업성공패키지",
                        "고용센터", "고용보험", "피보험자격", "고용유지지원금",
                        "출산전후휴가급여", "육아휴직급여", "고용복지"]
    if any(kw in query for kw in _CENTER_KEYWORDS):
        center = find_center(query)
        if center:
            parts.append(f"관할 고용센터 연락처:\n\n{format_center(center)}")
        else:
            parts.append(f"고용센터 안내:\n\n{format_center_guide()}")

    # 근로복지공단 연락처 (산재·체당금·복지대부 관련 시)
    _COMWEL_KEYWORDS = ["산재보험", "산업재해", "산재신청", "산재",
                        "요양급여", "휴업급여", "장해급여", "유족급여",
                        "장의비", "간병급여",
                        "체당금", "체불임금보장",
                        "생활안정자금", "주거안정자금", "근로복지대부",
                        "퇴직연금", "직업재활", "근로자건강센터", "근로복지공단"]
    if any(kw in query for kw in _COMWEL_KEYWORDS):
        office = find_office(query)
        if office:
            parts.append(f"관할 근로복지공단 연락처:\n\n{format_office(office)}")
        else:
            parts.append(f"근로복지공단 안내:\n\n{format_office_guide()}")

    # 질문 성격에 따른 관련 기관 연락처 결정
    relevant_contacts = []

    _HARASSMENT_KEYWORDS = ["괴롭힘", "갑질", "폭언", "따돌림", "부당대우", "직장 내 괴롭힘"]
    _WAGE_KEYWORDS = ["임금체불", "체불", "밀린 임금", "임금 미지급", "급여 미지급"]

    if any(kw in query for kw in _COMMISSION_KEYWORDS):
        relevant_contacts.append({
            "name": "노동위원회", "phone": "해당 지역 노동위원회",
            "desc": "부당해고 구제신청(30일 이내)·부당노동행위·차별시정",
        })
    if any(kw in query for kw in _CENTER_KEYWORDS):
        relevant_contacts.append({
            "name": "고용센터", "phone": "1350",
            "url": "work24.go.kr", "desc": "실업급여·구직활동·직업훈련(내일배움카드)",
        })
    if any(kw in query for kw in _COMWEL_KEYWORDS):
        relevant_contacts.append({
            "name": "근로복지공단", "phone": "1588-0075",
            "url": "comwel.or.kr", "desc": "산재보험·체당금·근로복지대부",
        })
    if any(kw in query for kw in _HARASSMENT_KEYWORDS):
        relevant_contacts.append({
            "name": "고용노동부", "phone": "1350",
            "desc": "직장 내 괴롭힘 신고·근로감독 요청",
        })
    if any(kw in query for kw in _WAGE_KEYWORDS):
        relevant_contacts.append({
            "name": "고용노동부", "phone": "1350",
            "desc": "임금체불 진정·근로감독 요청",
        })
        if not any(c["name"] == "근로복지공단" for c in relevant_contacts):
            relevant_contacts.append({
                "name": "근로복지공단", "phone": "1588-0075",
                "desc": "체당금(체불임금보장) 신청",
            })

    # 기본값: 고용노동부
    if not relevant_contacts:
        relevant_contacts.append({
            "name": "고용노동부", "phone": "1350",
            "desc": "근로기준법 상담·노동조건 문의",
        })

    yield {"type": "contacts", "agencies": relevant_contacts}

    parts.append(f"질문: {query}")
    user_message = "\n\n---\n\n".join(parts)
    logger.info("LLM 컨텍스트 %d자 (parts=%d)", len(user_message), len(parts))

    # 4. 대화 이력 포함
    messages = session.recent()

    # 5. 메시지 구성: 이미지 첨부 시 Vision content blocks 사용
    vision_blocks = []
    if attachments:
        for att in attachments:
            if att.vision_block:
                vision_blocks.append(att.vision_block)

    if vision_blocks:
        content_blocks = list(vision_blocks)
        content_blocks.append({"type": "text", "text": user_message})
        messages.append({"role": "user", "content": content_blocks})
    else:
        messages.append({"role": "user", "content": user_message})

    # 6. 스트리밍 답변 (Claude → OpenAI → Gemini 순차 폴백)
    full_text = ""
    used_provider = None
    try:
        from datetime import date as _date
        if consultation_context:
            from app.templates.prompts import CONSULTATION_SYSTEM_PROMPT
            system_prompt = CONSULTATION_SYSTEM_PROMPT.format(today=_date.today().isoformat())
        else:
            system_prompt = SYSTEM_PROMPT_TEMPLATE.format(today=_date.today().isoformat())
        for provider, text in _stream_answer(messages, system_prompt, config):
            if not used_provider:
                used_provider = provider
                if provider != "Claude":
                    yield {"type": "status", "text": f"{provider}로 답변 생성 중..."}
            full_text += text
            yield {"type": "chunk", "text": text}
    except RuntimeError:
        yield {"type": "error", "text": "모든 AI 서비스에 연결할 수 없습니다. 잠시 후 다시 시도해주세요."}
        yield {"type": "done"}
        return

    # 6-0. 면책 고지 강제 추가 — LLM이 누락해도 코드에서 보장
    _DISCLAIMER = (
        "\n\n---\n\n"
        "⚠️ 본 답변은 참고용 정보 제공이며 법적 효력이 없습니다. "
        "구체적인 사안은 관할 고용노동부(☎ 1350) 또는 공인노무사에게 상담하시기 바랍니다."
    )
    if full_text and "법적 효력" not in full_text:
        full_text += _DISCLAIMER
        yield {"type": "chunk", "text": _DISCLAIMER}

    # 6-1. 판례 인용 검증 (환각 감지 + 사용자 경고)
    # 화이트리스트는 컨텍스트 조립과 동일 원천(whitelist_hits) 사용 —
    # 법령 API·NLRC·graph 소스의 정당한 인용이 삭제되던 사각지대 해소 (DB-4)
    available_precs = extract_precedents_from_hits(whitelist_hits)
    available_admins = extract_admin_refs_from_hits(whitelist_hits)
    citation_check = validate_response_citations(
        full_text, available_precs, available_admins,
    )
    if citation_check["hallucinated"]:
        logger.warning(
            "⚠️ 환각 판례 감지 — query=%r, hallucinated=%s, valid=%s",
            query[:80], citation_check["hallucinated"], citation_check["valid"],
        )
        # 다른 LLM으로 환각 판례 교정
        corrected = correct_hallucinated_citations(
            response_text=full_text,
            hallucinated=citation_check["hallucinated"],
            anthropic_client=config.claude_client,
            gemini_api_key=config.gemini_api_key,
            openai_client=config.openai_client,
        )
        if corrected:
            # FR-03: 환각 3건+ 시 마이크로 퇴고로 문맥 자연스러움 보정
            polished = micro_polish(
                corrected_text=corrected,
                hallucinated_count=len(citation_check["hallucinated"]),
                anthropic_client=config.claude_client,
            )
            full_text = polished or corrected
            yield {"type": "replace", "text": full_text}
            logger.info("환각 판례 교정 완료 — replace 이벤트 전송")

    # 7. 세션에 이력 저장
    session.add_user(query)
    session.add_assistant(full_text)
    session.condense_if_needed()

    # 8. Supabase에 영구 저장 (fire-and-forget — 실패해도 답변에 영향 없음)
    if not config.supabase:
        yield {"type": "done"}
        return
    try:
        # 카테고리 결정
        calc_types = None
        tool_type_for_category = "none"
        if use_analysis_params and analysis:
            calc_types = analysis.calculation_types
        elif params:
            ct = params.get("calculation_type", "")
            if ct:
                calc_types = list(CALC_TYPE_MAP.get(ct, []))
            if params.get("is_harassment_question"):
                tool_type_for_category = "harassment"

        # LLM 추출 실패 시 키워드 기반 폴백
        if not calc_types:
            calc_types = infer_calc_types(query) or None

        category = classify_category(calc_types, tool_type_for_category, query)

        record = ConversationRecord(
            session_id=session.id,
            category=category,
            question_text=query,
            answer_text=full_text,
            calculation_types=calc_types,
            metadata={"has_attachments": has_attachments},
        )
        conv_id = save_conversation(config.supabase, record)

        # 첨부파일 업로드
        if conv_id and attachments:
            for att in attachments:
                if att.raw_data:
                    upload_attachment(
                        config.supabase, conv_id, session.id,
                        att.filename, att.content_type, att.raw_data,
                    )
        # 세션 데이터(summary + calc_cache) 영속 저장
        save_session_data(config.supabase, session.id, session.to_snapshot())
    except Exception as e:
        logger.warning("Supabase 저장 실패 (답변은 정상 전송됨): %s", e)

    yield {"type": "done"}
