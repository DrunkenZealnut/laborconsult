#!/usr/bin/env python3
"""
노동OK BEST Q&A 챗봇

사용법:
  python3 chatbot.py              # 기본 모드
  python3 chatbot.py --top 7     # 검색 결과 수 조정 (기본 5)
  python3 chatbot.py --threshold 0.5  # 유사도 임계값 조정 (기본 0.4)
  python3 chatbot.py --search-only    # Claude 답변 없이 검색 결과만 표시

종료: q / quit / 엔터 두 번
"""

import os
import sys
import argparse
import textwrap

from dotenv import load_dotenv
from openai import OpenAI
from pinecone import Pinecone
import anthropic

from wage_calculator.facade import WageCalculator, CALC_TYPE_MAP
from wage_calculator.models import WageInput, WageType, WorkSchedule, BusinessSize
from wage_calculator.result import format_result
from harassment_assessor import assess_harassment, HarassmentInput, format_assessment

load_dotenv()

# ── 설정 ──────────────────────────────────────────────────────────────────────
EMBED_MODEL   = "text-embedding-3-small"
CLAUDE_MODEL  = "claude-opus-4-6"
EXTRACT_MODEL = "claude-haiku-4-5-20251001"
INDEX_NAME    = os.getenv("PINECONE_INDEX_NAME", "nodongok-bestqna")
WRAP_WIDTH    = 80


# ── 검색 ──────────────────────────────────────────────────────────────────────

def embed_query(query: str, client: OpenAI) -> list[float]:
    resp = client.embeddings.create(model=EMBED_MODEL, input=[query])
    return resp.data[0].embedding


def search(query: str, index, openai_client: OpenAI,
           top_k: int = 5, threshold: float = 0.4) -> list[dict]:
    """Pinecone 벡터 검색 → 임계값 이상의 결과만 반환"""
    qvec = embed_query(query, openai_client)
    results = index.query(vector=qvec, top_k=top_k, include_metadata=True)

    hits = []
    for match in results.matches:
        if match.score < threshold:
            continue
        hits.append({
            "score":       round(match.score, 4),
            "post_id":     match.metadata.get("post_id", ""),
            "title":       match.metadata.get("title", ""),
            "date":        match.metadata.get("date", ""),
            "views":       match.metadata.get("views", 0),
            "url":         match.metadata.get("url", ""),
            "section":     match.metadata.get("section", ""),
            "chunk_text":  match.metadata.get("chunk_text", ""),
        })

    return hits


# ── RAG 컨텍스트 구성 ──────────────────────────────────────────────────────────

def build_context(hits: list[dict]) -> str:
    """검색 결과를 Claude에게 전달할 컨텍스트로 포맷"""
    parts = []
    seen_posts = {}  # 같은 게시글이 여러 청크로 나올 때 중복 제목 방지

    for i, h in enumerate(hits, 1):
        pid = h["post_id"]
        header = f"[문서 {i}] {h['title']}"
        if pid in seen_posts:
            header += f" (계속)"
        seen_posts[pid] = True

        section_info = f" > {h['section']}" if h["section"] not in ("질문", "본문", h["title"]) else ""
        parts.append(
            f"{header}{section_info}\n"
            f"출처: {h['url']}  |  작성일: {h['date']}\n\n"
            f"{h['chunk_text']}"
        )

    return "\n\n---\n\n".join(parts)


# ── 임금계산기 통합 ──────────────────────────────────────────────────────────────

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
                "description": "계산 유형: 주휴수당/연장수당/최저임금/퇴직금/실업급여/임금계산/연차수당/해고예고수당/육아휴직/출산휴가/임금체불/보상휴가/탄력근무/근로장려금",
            },
            "household_type": {
                "type": "string",
                "description": "가구유형: 단독/홑벌이/맞벌이 (근로장려금 계산 시)",
            },
            "annual_total_income": {
                "type": "number",
                "description": "연간 총소득 (원). 근로장려금 계산 시 사용.",
            },
            "total_assets": {
                "type": "number",
                "description": "가구원 재산 합계 (원). 근로장려금 계산 시 사용.",
            },
            "num_children_under_18": {
                "type": "number",
                "description": "18세 미만 부양자녀 수. 자녀장려금 계산 시 사용.",
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
                "description": "주 소정근로일수 (예: 5)",
            },
            "weekly_total_hours": {
                "type": "number",
                "description": "주 소정근로시간 합계. 일별 다른 경우 합산 (예: 3+5+5+4=17)",
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
                "description": "퇴직일 (YYYY-MM-DD)",
            },
            "use_minimum_wage": {
                "type": "boolean",
                "description": "사용자가 '최저시급', '최저임금 기준'으로 계산을 요청할 때 true로 설정. wage_amount 미입력 시 해당 연도 법정 최저시급이 자동 적용됩니다.",
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


def extract_params(query: str, claude_client: anthropic.Anthropic) -> tuple[str, dict | None]:
    """질문을 분류하고 파라미터를 추출 (2-tool 방식: wage_params / harassment_params)

    Returns:
        ("wage", params) — 임금 계산 질문
        ("harassment", params) — 괴롭힘 판정 질문
        ("none", None) — 해당 없음
    """
    try:
        resp = claude_client.messages.create(
            model=EXTRACT_MODEL,
            max_tokens=512,
            tools=[WAGE_CALC_TOOL, HARASSMENT_TOOL],
            tool_choice={"type": "any"},
            messages=[{
                "role": "user",
                "content": (
                    "다음 질문을 분석하세요.\n"
                    "- 임금/수당/퇴직금 등 숫자 계산이 필요하면 wage_params 도구를 사용하세요. "
                    "일별 근로시간이 다르면 합산하여 weekly_total_hours에 넣으세요. "
                    "근로장려금/EITC/장려금 관련이면 calculation_type='근로장려금'으로 설정하세요.\n"
                    "- 직장 내 괴롭힘/갑질/폭언/따돌림/부당대우 판정이 필요하면 harassment_params 도구를 사용하세요.\n"
                    "- 일반 법률 상담이면 wage_params에서 needs_calculation=false로 설정하세요.\n\n"
                    f"질문: {query}"
                ),
            }],
        )
        for block in resp.content:
            if block.type == "tool_use":
                if block.name == "harassment_params":
                    return ("harassment", block.input)
                return ("wage", block.input)
    except Exception as e:
        print(f"  [파라미터 추출 실패: {e}]")
    return ("none", None)


def run_calculator(params: dict) -> str | None:
    """추출된 파라미터로 임금계산기를 실행하고, 결과 텍스트를 반환"""
    if not params or not params.get("needs_calculation"):
        return None

    # EITC 전용 경로
    calc_type = params.get("calculation_type", "")
    if calc_type in ("근로장려금", "근로장려세제", "EITC"):
        inp = WageInput()
        inp.household_type = params.get("household_type", "")
        inp.annual_total_income = params.get("annual_total_income", 0)
        inp.total_assets = params.get("total_assets", 0)
        inp.num_children_under_18 = int(params.get("num_children_under_18", 0))
        if params.get("wage_amount"):
            inp.monthly_wage = params["wage_amount"]
        if params.get("reference_year"):
            inp.reference_year = int(params["reference_year"])
        try:
            calc = WageCalculator()
            result = calc.calculate(inp, ["eitc"])
            return format_result(result)
        except Exception as e:
            return f"[계산기 오류: {e}]"

    wage_type_map = {
        "시급": WageType.HOURLY,
        "일급": WageType.DAILY,
        "월급": WageType.MONTHLY,
        "연봉": WageType.ANNUAL,
        "포괄임금제": WageType.COMPREHENSIVE,
    }
    wt = wage_type_map.get(params.get("wage_type", ""), WageType.MONTHLY)
    amount = params.get("wage_amount")
    if not amount:
        if params.get("use_minimum_wage"):
            from datetime import date as _date
            from wage_calculator.constants import MINIMUM_HOURLY_WAGE
            ref_year = int(params.get("reference_year") or _date.today().year)
            if ref_year not in MINIMUM_HOURLY_WAGE:
                ref_year = max(MINIMUM_HOURLY_WAGE.keys())
            amount = MINIMUM_HOURLY_WAGE[ref_year]
            wt = WageType.HOURLY
        else:
            return None

    # WorkSchedule 구성
    weekly_days = params.get("weekly_work_days")
    weekly_total = params.get("weekly_total_hours")

    # 일별 근로시간이 다른 경우: weekly_total / weekly_days 로 평균 산출
    if weekly_total and weekly_days:
        daily_hours = weekly_total / weekly_days
    else:
        daily_hours = params.get("daily_work_hours")

    # None → WorkSchedule 모델 기본값 (8.0h, 5일) 사용
    schedule = WorkSchedule(
        daily_work_hours=daily_hours if daily_hours is not None else 8.0,
        weekly_work_days=weekly_days if weekly_days is not None else 5.0,
        weekly_overtime_hours=params.get("weekly_overtime_hours") or 0,
        weekly_night_hours=params.get("weekly_night_hours") or 0,
        weekly_holiday_hours=params.get("weekly_holiday_work_hours") or 0,
    )

    # 사업장 규모
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

    # 임금액 설정
    if wt == WageType.HOURLY:
        inp.hourly_wage = amount
    elif wt == WageType.DAILY:
        inp.daily_wage = amount
    elif wt in (WageType.MONTHLY, WageType.COMPREHENSIVE):
        inp.monthly_wage = amount
    elif wt == WageType.ANNUAL:
        inp.annual_wage = amount

    # 재직기간
    start = params.get("start_date", "")
    if start:
        if any(c in start for c in "년개월"):
            from wage_calculator.facade import _guess_start_date
            inp.start_date = _guess_start_date(start)
        else:
            inp.start_date = start
    if params.get("end_date"):
        inp.end_date = params["end_date"]

    # targets 결정
    calc_type = params.get("calculation_type", "임금계산")
    targets = CALC_TYPE_MAP.get(calc_type, ["minimum_wage"])

    try:
        calc = WageCalculator()
        result = calc.calculate(inp, targets)
        return format_result(result)
    except Exception as e:
        return f"[계산기 오류: {e}]"


def run_assessor(params: dict) -> str | None:
    """추출된 파라미터로 괴롭힘 판정기를 실행하고, 결과 텍스트를 반환"""
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


# ── Claude 답변 생성 ───────────────────────────────────────────────────────────

SYSTEM_PROMPT_TEMPLATE = """당신은 한국 노동법 전문 상담사입니다.
아래 '참고 문서'는 노동OK(www.nodong.kr)의 BEST Q&A에서 가져온 실제 상담 사례입니다.

오늘 날짜: {today}
※ 사용자가 연도를 명시하지 않은 날짜(예: "2월28일")는 오늘 날짜 기준으로 해석하세요. 과거 시제이면 가장 최근의 해당 날짜입니다.

답변 원칙:
1. **임금계산기 결과가 포함된 경우** (가장 중요):
   - 계산기 결과의 수치를 그대로 사용하세요. 절대로 직접 계산하거나 다른 수치를 제시하지 마세요.
   - 계산기의 계산 과정(formulas)과 법적 근거를 자연스럽게 풀어서 설명하세요.
   - 계산기의 주의사항(warnings)이 있으면 반드시 포함하세요.
2. 참고 문서에 있는 내용을 바탕으로 정확하게 답변하세요.
3. 관련 법 조문이나 행정해석이 있으면 함께 언급하세요.
4. **참고 문서가 없는 경우** ("관련 문서 없음"):
   - 한국 노동법 지식을 바탕으로 답변하되, 답변 서두에 "⚠️ 참고 문서 없이 일반 노동법 지식을 기반으로 작성된 답변입니다. 정확한 사항은 노동청(1350) 또는 노무사에게 확인하시기 바랍니다."를 명시하세요.
   - 관련 법 조문(근로기준법, 시행령 등)을 반드시 인용하세요.
5. 참고 문서가 있지만 질문과 직접 관련 없는 경우, "해당 내용은 참고 문서에서 확인되지 않습니다"라고 명시하세요.
6. 답변 마지막에 참고 출처 URL을 표시하세요. (문서 없는 경우 생략)
7. **괴롭힘 판정 결과가 포함된 경우**:
   - 판정기의 3요소 판정 결과와 종합 가능성을 그대로 사용하세요.
   - 판정 근거, 법적 조문, 대응 절차, 주의사항을 자연스럽게 설명하세요.
   - 면책 문구(법적 효력 없는 참고 정보)를 반드시 포함하세요.
8. 법적 조언이 아닌 정보 제공임을 명심하세요.
9. 질문에 이미 계산에 필요한 정보가 포함되어 있으면 추가 질문 없이 바로 답변하세요."""


def generate_answer(query: str, context: str, claude_client: anthropic.Anthropic,
                    calc_result: str | None = None,
                    assessment_result: str | None = None) -> str:
    """Claude로 RAG 답변 생성 (스트리밍)"""
    parts = [f"참고 문서:\n\n{context}"]
    if calc_result:
        parts.append(f"임금계산기 결과 (정확한 계산 — 이 수치를 사용하세요):\n\n{calc_result}")
    if assessment_result:
        parts.append(f"괴롭힘 판정 결과 (판정기 분석 — 이 결과를 사용하세요):\n\n{assessment_result}")
    parts.append(f"질문: {query}")
    user_message = "\n\n---\n\n".join(parts)

    print("\n💬 답변:\n")

    full_text = ""
    with claude_client.messages.stream(
        model=CLAUDE_MODEL,
        max_tokens=2048,
        system=SYSTEM_PROMPT_TEMPLATE.format(today=__import__('datetime').date.today().isoformat()),
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
            full_text += text

    print("\n")
    return full_text


# ── 출력 헬퍼 ─────────────────────────────────────────────────────────────────

def print_search_results(hits: list[dict]):
    """검색 결과 목록 출력"""
    if not hits:
        print("\n  관련 문서를 찾지 못했습니다.\n")
        return

    print(f"\n📚 관련 문서 ({len(hits)}개):\n")
    seen = {}
    rank = 1
    for h in hits:
        pid = h["post_id"]
        label = f"  {rank}. [{h['score']:.3f}] {h['title']}"
        sub   = f"      섹션: {h['section']}  |  {h['date']}  |  조회 {int(h['views']):,}"
        url   = f"      {h['url']}"

        if pid not in seen:
            print(label)
            print(sub)
            print(url)
            seen[pid] = rank
            rank += 1
        else:
            print(f"  {'':>2}  └ 추가 섹션: {h['section']} (유사도 {h['score']:.3f})")


def print_chunk_previews(hits: list[dict]):
    """각 청크의 내용 미리보기 출력"""
    print("\n📄 관련 내용 미리보기:\n")
    for i, h in enumerate(hits, 1):
        preview = h["chunk_text"][:200].replace("\n", " ")
        print(f"  [{i}] {h['title']} > {h['section']}")
        print(f"       {preview}{'...' if len(h['chunk_text']) > 200 else ''}")
        print()


def separator():
    print("─" * WRAP_WIDTH)


# ── 메인 챗봇 루프 ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="노동OK 챗봇")
    parser.add_argument("--top",         type=int,   default=5,   help="검색 결과 수 (기본 5)")
    parser.add_argument("--threshold",   type=float, default=0.4, help="유사도 임계값 (기본 0.4)")
    parser.add_argument("--search-only", action="store_true",     help="Claude 답변 없이 검색만")
    args = parser.parse_args()

    # API 키 확인
    openai_key   = os.getenv("OPENAI_API_KEY")
    pinecone_key = os.getenv("PINECONE_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")

    missing = []
    if not openai_key:   missing.append("OPENAI_API_KEY")
    if not pinecone_key: missing.append("PINECONE_API_KEY")
    if not args.search_only and not anthropic_key:
        missing.append("ANTHROPIC_API_KEY (--search-only 옵션으로 우회 가능)")
    if missing:
        sys.exit(f"[오류] .env에 설정 필요: {', '.join(missing)}")

    # 클라이언트 초기화
    openai_client = OpenAI(api_key=openai_key)
    pc = Pinecone(api_key=pinecone_key)
    claude_client = anthropic.Anthropic(api_key=anthropic_key) if not args.search_only else None

    # Pinecone 인덱스 연결
    try:
        index = pc.Index(INDEX_NAME)
        stats = index.describe_index_stats()
        total_vecs = stats.total_vector_count
    except Exception as e:
        sys.exit(f"[오류] Pinecone 인덱스 연결 실패: {e}\npinecone_upload.py를 먼저 실행하세요.")

    # 시작 메시지
    separator()
    print("  노동OK BEST Q&A 챗봇")
    print(f"  벡터 수: {total_vecs:,}  |  검색 결과: top {args.top}  |  임계값: {args.threshold}")
    if args.search_only:
        print("  모드: 검색 전용 (Claude 답변 없음)")
    separator()
    print("  노동 관련 질문을 입력하세요. 종료: q\n")

    empty_count = 0

    while True:
        try:
            query = input("질문 › ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n종료합니다.")
            break

        if not query:
            empty_count += 1
            if empty_count >= 2:
                print("종료합니다.")
                break
            continue
        empty_count = 0

        if query.lower() in ("q", "quit", "exit", "종료"):
            print("종료합니다.")
            break

        separator()

        # 1. 질문 분류 + 파라미터 추출 (검색 전)
        calc_result = None
        assessment_result = None
        if claude_client:
            tool_type, params = extract_params(query, claude_client)
            if tool_type == "wage" and params and params.get("needs_calculation"):
                print("🧮 임금계산기 실행 중...")
                calc_result = run_calculator(params)
            elif tool_type == "harassment" and params and params.get("is_harassment_question"):
                print("⚖️ 괴롭힘 판정 중...")
                assessment_result = run_assessor(params)

        # 2. 벡터 검색
        print(f"🔍 '{query}' 검색 중...")
        try:
            hits = search(query, index, openai_client, args.top, args.threshold)
        except Exception as e:
            print(f"[오류] 검색 실패: {e}")
            continue

        # 3. 검색 결과 없으면 안내 (Claude 호출은 계속)
        if not hits and not calc_result and not assessment_result:
            print(f"\n  ℹ️ 관련 문서가 없어 일반 법률 지식으로 답변합니다.\n")

        # 4. 검색 결과 출력 (있을 때만)
        if hits:
            print_search_results(hits)

        if args.search_only:
            if hits:
                print_chunk_previews(hits)
            separator()
            continue

        # 5. RAG 답변 생성
        context = build_context(hits) if hits else "(관련 문서 없음)"
        try:
            generate_answer(query, context, claude_client, calc_result, assessment_result)
        except Exception as e:
            print(f"\n[오류] 답변 생성 실패: {e}")

        separator()


if __name__ == "__main__":
    main()
