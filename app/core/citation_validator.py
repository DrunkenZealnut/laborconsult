"""판례·행정해석 인용 검증기

RAG 검색 결과에서 판례 번호를 추출하고,
LLM 응답에서 환각된 판례 번호를 감지한다.
"""

from __future__ import annotations

import re
import logging
import time

from app.config import ANSWER_MAX_TOKENS, CITATION_STAGE_BUDGET
from app.core import llm_gateway

logger = logging.getLogger(__name__)


# ── 교정 호출 타임아웃 (llm-fallback-hardening FR-07) ─────────────────────────

def _rewrite_timeout(text_len: int) -> float:
    """답변 전문 재생성에 필요한 타임아웃을 입력 길이로 추정.

    고정 5초는 실답변에서 100% 실패한다 — 2026-08-06 실측: claude-haiku-4-5가
    1,960자를 재생성하는 데 7.7초 걸렸다(약 250자/초). 교정 모델이 관리자 설정 모델로 바뀌며
    (unified-model-provider) 더 느린 모델이 기준이 됐다 — 2026-10-11 실측 1,596자 재생성에
    gemini-3.8-flash 11.1초(약 144자/초)·gpt-6-sol 6.3초. 안전계수 1.5로 100자/초를 잡고
    [15, 40]초로 클램프한다. 상한은 단계 예산(CITATION_STAGE_BUDGET 45초) 안이다.

    교정이 타임아웃되면 환각 판례가 답변에 그대로 남으므로 정확성 항목이다.
    """
    return min(40.0, max(15.0, text_len / 100))


def _remaining(deadline: float | None) -> float:
    """단계 데드라인까지 남은 초. deadline이 None이면 무제한 대신 단계 예산 전체."""
    if deadline is None:
        return CITATION_STAGE_BUDGET
    return deadline - time.monotonic()


def _is_valid_rewrite(text: str | None, original: str) -> bool:
    """교정/퇴고 결과를 채택해도 되는지 판정 — 전 제공자 공통 가드.

    빈 응답·공백만·과도하게 짧아진 결과를 **성공으로 처리하면 안 된다**. 이 결과는
    `replace` 이벤트로 사용자가 이미 받은 완성 답변을 통째로 덮어쓰기 때문에,
    통과시키면 답변이 사라진다. 실패로 판정해 다음 제공자로 넘기는 것이 옳다.

    0.7 하한은 원문 대비 길이 비율 — 교정은 판례 번호만 제거하므로 길이가 크게
    줄면 본문이 유실된 것이다.
    """
    return bool(text) and len(text) > len(original) * 0.7

# 대법원/헌재 판례 번호 정규식
# 예: "2023다302838", "대법원 2023다302838", "헌재 2021헌마1234"
# 사건부호 자리는 아무 한글 1~2자나 받으므로 날짜 단위(년·월·일)로 시작하는 것은 제외한다.
# 없으면 "2026년 9월"이 2026+년+9로 잡혀 **환각 판례로 판정되고 답변에서 지워졌다**
# (실측 2026-10-02: `판례 환각 감지: ['2026년9']` → citation_fixed).
# **목록을 넓히지 말 것** — 사건부호는 한글 한 글자가 매우 많다(차=독촉, 초=형사신청, 주·호 …).
# 처음에 수량 단위까지 넣었다가 '차'(독촉사건)를 막았다(CodeRabbit PR #91).
_NOT_CASE_CODE = "년월일"
# 20세기 두 자리 연도는 확인 가능한 사건부호에만 허용한다.
# 일반 한글을 허용하면 85만5000원이 85만5000 사건으로 잘못 검증된다.
_LEGACY_CASE_CODES = "다|마|두|누|나|도|가단|가합|카단|카합|고단|고합|구단|구합|헌마|헌바|카|라"
_PREC_PATTERN = re.compile(
    r"(?<!\d)(?:대법원|대법|헌법재판소|헌재)?\s*"
    rf"((?:19|20)\d{{2}}|[5-9]\d(?=\s*(?:{_LEGACY_CASE_CODES})\s*\d))\s*"
    rf"((?![{_NOT_CASE_CODE}])[가-힣]{{1,2}})\s*"
    r"(\d+)"
)

# 행정해석 문서번호 정규식
# 예: "근로기준정책과-579", "임금근로시간과-1234"
_ADMIN_PATTERN = re.compile(
    r"([가-힣]+과)-(\d+)"
)


# ── 재결례 번호 (adjudication-corpus D12) ──────────────────────────────────────
#
# 두 기관의 표기: 고용보험심사위원회 `2019재결 제117호`(A), 산업재해보상보험재심사위원회 `2010-2071호`(B).
# **B는 기관 문맥이 있을 때만 검증한다.** `YYYY-N호`는 고시·공고 번호와 형태가 같다 — 문맥 없는 B를
# BM25 코퍼스(95,762문서)에 돌리면 438건이 맞았고 전부 고시·공고였다(`고용노동부고시 2015-77호`·
# `공고 2021-244호`). 실답변에도 `고시(2025-124호)`가 있어, 문맥 없이 검증하면 그 문장이 "확인되지 않은
# 번호"로 지워진다. 문맥 없는 `YYYY-N호` 환각은 **잡지 않는다**(의도된 미탐 — 고시 번호 오삭제보다 낫다).
# `_PREC_PATTERN`은 재결 구간을 가린 뒤 돌린다 — `…재심사위원회 2015-1987호 2015. 8. 27.`에서
# `1987호 2015`를 판례(연도 1987 + 부호 '호' + 번호 2015)로 잡았다(설계 검증 M6).
_RULING_EI_PATTERN = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*재결\s*제?\s*(\d{1,5})\s*호")
# 번호 뒤에 `-숫자`·`.숫자`가 이어지면 날짜다(`산재재심사위원회에 2026-11-08 재심사청구` — Codex 리뷰 #155).
# `호`가 없을 때는 번호 끝이 숫자로 이어지지 않아야 한다.
_RULING_IA_PATTERN = re.compile(
    r"(?:산업재해보상보험\s*재심사\s*위원회|산재\s*재심사\s*위원회|재심사\s*위원회)"
    r"[^.\n]{0,25}?((?:19|20)\d{2})\s*-\s*(\d{1,5})(?!\s*[-–.]\s*\d)(?:\s*호)?(?!\d)"
)
# 코어 — ruling hit의 `case_no` 메타 파싱과 _PREC_PATTERN 마스킹 전용. 답변 검증에는 쓰지 않는다.
_RULING_CORE_IA = re.compile(r"(?<![\d\-])((?:19|20)\d{2})\s*-\s*(\d{1,5})\s*호")
RULING_AGENCY_NAMES = {"eiac": "고용보험심사위원회", "iaciac": "산업재해보상보험재심사위원회"}
# 기관 판정 어휘 — 긴 이름 먼저(부분 문자열 포함 관계). "재심사위원회"는 iaciac 전용 표기다.
_RULING_AGENCY_WORDS = (
    ("iaciac", "산업재해보상보험재심사위원회"), ("iaciac", "산업재해보상보험 재심사위원회"),
    ("iaciac", "산재재심사위원회"), ("iaciac", "재심사위원회"),
    ("eiac", "고용보험심사위원회"), ("eiac", "고용보험 심사위원회"),
)
_RULING_AGENCY_LOOKBACK = 30


def _ruling_key_ei(year: str, number: str) -> str:
    return f"{year}재결제{int(number)}호"


def _ruling_key_ia(year: str, number: str) -> str:
    return f"{year}-{int(number)}호"


def _ruling_year_ok(year: str, number: str) -> bool:
    return 1950 <= int(year) <= 2030 and int(number) <= 99999


def _agency_near(text: str, pos: int) -> str | None:
    """`pos` 앞 30자 안에 적힌 기관(eiac|iaciac). 없으면 None."""
    window = text[max(0, pos - _RULING_AGENCY_LOOKBACK):pos]
    for agency, word in _RULING_AGENCY_WORDS:
        if word in window:
            return agency
    return None


def _agency_in(text: str) -> str | None:
    for agency, word in _RULING_AGENCY_WORDS:
        if word in (text or ""):
            return agency
    return None


def _mask_ruling_spans(text: str) -> str:
    """재결 번호 구간을 같은 길이의 공백으로 가린다(_PREC_PATTERN 오탐 방지).

    가림은 삭제 권한이 없으므로 문맥 없는 코어 패턴으로 넓게 가려도 안전하다 — 고시 번호
    `2025-124호`를 가려도 판례 검증에 영향이 없다(그 뒤의 날짜가 판례로 잡히는 일만 막는다).
    """
    if not text:
        return text
    out = text
    for pattern in (_RULING_EI_PATTERN, _RULING_IA_PATTERN, _RULING_CORE_IA):
        # 번호 구간(연도 시작 ~ 끝)만 가린다 — 문맥 패턴의 기관명·사이 본문까지 가리면 그 사이의 판례
        # ("산재재심사위원회는 대법원 2020두12345 및 2010-2071호를")가 함께 사라진다(Codex 리뷰 #155).
        out = pattern.sub(lambda m: m.group(0)[:m.start(1) - m.start()] + " " * (m.end() - m.start(1)), out)
    return out


def extract_rulings_from_hits(hits: list[dict]) -> dict[str, dict]:
    """RAG 결과에서 재결 번호 화이트리스트를 만든다.

    세 경로(판례와 같다): ① `source_type == "ruling"`인 hit의 `case_no` 메타는 **문맥 없는 코어**로
    파싱한다(메타 필드에는 기관명이 없다) ② title·chunk_text는 문맥 패턴 A·B로 파싱한다 — 재결례
    title은 `{기관명} {사건번호} — …`(D8)이고 모든 청크 첫 줄이 `[{기관명} {사건번호} · 의결 …]`(D11)이라
    BM25 경로(case_no 없음)에서도 등록된다 ③ B 키마다 A 형태 **별칭**을 실키가 없을 때만 더한다 —
    iaciac 원문 제목이 `2010재결 제2071호 …`라 LLM이 그 형태로 쓸 수 있다. 별칭은 `alias_of`로 표시해
    인용 목록에는 싣지 않는다(두 표기를 보이면 섞어 쓴다).

    Returns:
        {"2019재결제117호": {"agencies": ["eiac"], "display": "2019재결 제117호", "title": "...",
                           "hit_index": 0, "source": "meta"}, "2010-2071호": {...},
         "2010재결제2071호": {..., "alias_of": "2010-2071호"}}
    """
    rulings: dict[str, dict] = {}

    def _add(key: str, display: str, agency: str | None, title: str, idx: int, source: str,
             alias_of: str | None = None) -> None:
        info = rulings.get(key)
        if info is None:
            info = {"agencies": [], "display": display, "title": title[:100],
                    "hit_index": idx, "source": source}
            if alias_of:
                info["alias_of"] = alias_of
            rulings[key] = info
        elif "alias_of" in info and not alias_of:
            # 실키가 나중에 왔다 — 별칭 표시를 지우고 실키로 승격(실키 우선, 설계 검증 M13)
            info.pop("alias_of", None)
            info.update({"title": title[:100], "hit_index": idx, "source": source})
        if agency and agency not in info["agencies"]:
            info["agencies"].append(agency)

    ia_keys: list[tuple[str, str, str, int]] = []
    for i, hit in enumerate(hits):
        title = hit.get("title", "") or ""
        chunk = hit.get("chunk_text", "") or ""
        if hit.get("source_type") == "ruling":
            case_no = hit.get("case_no", "") or ""
            agency = hit.get("agency") or _agency_in(title)
            for m in _RULING_EI_PATTERN.finditer(case_no):
                if _ruling_year_ok(m.group(1), m.group(2)):
                    _add(_ruling_key_ei(m.group(1), m.group(2)),
                         f"{m.group(1)}재결 제{int(m.group(2))}호", agency or "eiac", title, i, "meta")
            for m in _RULING_CORE_IA.finditer(case_no):
                if _ruling_year_ok(m.group(1), m.group(2)):
                    key = _ruling_key_ia(m.group(1), m.group(2))
                    _add(key, f"{m.group(1)}-{int(m.group(2))}호", agency or "iaciac", title, i, "meta")
                    ia_keys.append((key, m.group(1), m.group(2), i))
        for text_field, source in ((title, "title"), (chunk, "chunk")):
            for m in _RULING_EI_PATTERN.finditer(text_field):
                if _ruling_year_ok(m.group(1), m.group(2)):
                    _add(_ruling_key_ei(m.group(1), m.group(2)),
                         f"{m.group(1)}재결 제{int(m.group(2))}호",
                         _agency_near(text_field, m.start(1)), title, i, source)
            for m in _RULING_IA_PATTERN.finditer(text_field):
                if _ruling_year_ok(m.group(1), m.group(2)):
                    key = _ruling_key_ia(m.group(1), m.group(2))
                    _add(key, f"{m.group(1)}-{int(m.group(2))}호", "iaciac", title, i, source)
                    ia_keys.append((key, m.group(1), m.group(2), i))

    for key, year, number, idx in ia_keys:
        alias = _ruling_key_ei(year, number)
        if alias not in rulings:
            _add(alias, f"{year}재결 제{int(number)}호", "iaciac", rulings[key]["title"], idx,
                 "alias", alias_of=key)
    return rulings


def extract_precedents_from_hits(hits: list[dict]) -> dict[str, dict]:
    """RAG 검색 결과에서 판례 번호를 구조화하여 추출.

    Returns:
        {"2023다302838": {"year": 2023, "type": "다", "number": 302838,
                          "source": "title", "title": "..."}, ...}
    """
    precedents: dict[str, dict] = {}

    for i, hit in enumerate(hits):
        title = hit.get("title", "")
        chunk = hit.get("chunk_text", "")
        # 메타의 사건번호를 **본문·제목과 동등한 원천으로** 본다.
        # 판시사항·판결요지는 자기 사건번호를 적지 않는 것이 보통이라, 본문
        # 파싱만으로는 검색된 판례의 94%가 인용 목록에 오르지 못했다(실측
        # letec 6,440청크 중 6,060). 그러면 LLM이 그 판례를 근거로 써도
        # 환각으로 판정돼 replace로 지워진다 — 검색은 됐는데 인용은 못 하는 상태.
        # 이 값은 법제처 API·아카이브가 확인한 번호라 본문 정규식보다 신뢰도가 높다.
        case_no = hit.get("case_no", "")

        for text_field, context_source in [
            (title, "title"),
            (chunk, "chunk"),
            (case_no, "meta"),
        ]:
            # 재결 번호 구간을 가린다 — `2015-1987호 2015. 8.`의 `1987호 2015`가 판례 키가 되지 않게(D12)
            for match in _PREC_PATTERN.finditer(_mask_ruling_spans(text_field)):
                year_text = match.group(1)
                year = int(year_text) + (1900 if len(year_text) == 2 else 0)
                case_type = match.group(2)
                number = int(match.group(3))

                # 범위 검증 (합리적 범위)
                if not (1950 <= year <= 2030 and number <= 999999):
                    continue

                prec_key = f"{year_text}{case_type}{number}"
                if prec_key not in precedents:
                    precedents[prec_key] = {
                        "year": year,
                        "type": case_type,
                        "number": number,
                        "source": context_source,
                        "hit_index": i,
                        "title": title[:100],
                    }

    return precedents


def extract_admin_refs_from_hits(hits: list[dict]) -> dict[str, dict]:
    """RAG 검색 결과에서 행정해석 문서번호 추출."""
    admin_refs: dict[str, dict] = {}

    for i, hit in enumerate(hits):
        title = hit.get("title", "")
        chunk = hit.get("chunk_text", "")

        for text_field, context_source in [
            (title, "title"),
            (chunk, "chunk"),
        ]:
            for match in _ADMIN_PATTERN.finditer(text_field):
                ref_key = f"{match.group(1)}-{match.group(2)}"
                if ref_key not in admin_refs:
                    admin_refs[ref_key] = {
                        "department": match.group(1),
                        "number": match.group(2),
                        "source": context_source,
                        "hit_index": i,
                        "title": title[:100],
                    }

    return admin_refs


def build_available_citations_text(
    hits: list[dict],
    legal_precedents: list[dict] | None = None,
) -> str:
    """LLM에 제공할 '인용 가능한 판례 목록' 텍스트 생성.

    이 목록을 시스템 프롬프트와 함께 제공하여
    Claude가 이 목록에 없는 판례 번호를 생성하지 않도록 유도한다.
    """
    precs = extract_precedents_from_hits(hits)
    admin_refs = extract_admin_refs_from_hits(hits)
    rulings = extract_rulings_from_hits(hits)

    lines = ["[인용 가능한 판례·행정해석·재결례 목록]"]
    lines.append("아래 목록에 있는 것만 번호를 인용하세요. 목록에 없는 번호는 절대 생성하지 마세요.\n")

    if precs:
        lines.append("판례:")
        for key, info in precs.items():
            lines.append(f"  - {key} (출처: {info['title']})")
    else:
        lines.append("판례: (검색 결과에서 판례를 찾지 못했습니다)")

    # 법령 API에서 조회한 판례 (case_name 있는 항목만 — Pinecone 판례는 hits 경로로 파싱됨)
    if legal_precedents:
        api_lines = []
        for prec in legal_precedents:
            case_name = prec.get("case_name", "")
            if not case_name:
                continue
            date = prec.get("date", "")
            api_lines.append(f"  - {case_name} ({date})")
        if api_lines:
            lines.append("\n법령 API 조회 판례:")
            lines.extend(api_lines)

    if admin_refs:
        lines.append("\n행정해석:")
        for key, info in admin_refs.items():
            lines.append(f"  - {key} (출처: {info['title']})")
    else:
        lines.append("\n행정해석: (검색 결과에서 행정해석을 찾지 못했습니다)")

    # 재결례 — 별칭(alias_of)은 싣지 않는다. 기관명을 함께 적어 그 형식으로 인용하게 한다(D18 — 산재 재결의
    # 검증 패턴은 "재심사위원회" 문맥이 있을 때만 동작한다).
    real_rulings = {k: v for k, v in rulings.items() if not v.get("alias_of")}
    if real_rulings:
        lines.append("\n재결례(기관명과 함께 인용):")
        for key, info in real_rulings.items():
            agency = RULING_AGENCY_NAMES.get(info["agencies"][0], "") if info["agencies"] else ""
            lines.append(f"  - {agency} {info['display']} (출처: {info['title']})".replace("  -  ", "  - "))

    return "\n".join(lines)


def validate_response_citations(
    response_text: str,
    available_precedents: dict[str, dict],
    available_admin_refs: dict[str, dict] | None = None,
    available_rulings: dict[str, dict] | None = None,
) -> dict:
    """생성된 답변에서 인용된 판례·행정해석·재결 번호를 검증.

    available_rulings가 None이면 재결 검증은 건너뛴다(기존 3인자 호출 호환). 재결 구간 마스킹은 항상 한다.
    재결은 번호가 화이트리스트에 있어도 **번호 앞 30자의 기관명이 등록 기관과 다르면** hallucinated다
    (iaciac 별칭이 eiac 번호와 겹칠 수 있다 — D12).

    Returns:
        {
            "total_cited": int,
            "valid": ["2023다302838", ...],
            "hallucinated": ["2006다49372", ...],
            "warnings": ["..."],
        }
    """
    result = {
        "total_cited": 0,
        "valid": [],
        "hallucinated": [],
        "warnings": [],
    }

    # 재결 번호 검증(문맥 패턴만 — 문맥 없는 `YYYY-N호`는 고시·공고 번호일 수 있어 보지 않는다)
    if available_rulings is not None:
        for pattern, key_fn in ((_RULING_EI_PATTERN, _ruling_key_ei), (_RULING_IA_PATTERN, _ruling_key_ia)):
            for match in pattern.finditer(response_text):
                if not _ruling_year_ok(match.group(1), match.group(2)):
                    continue
                key = key_fn(match.group(1), match.group(2))
                result["total_cited"] += 1
                info = available_rulings.get(key)
                mentioned = _agency_near(response_text, match.start(1))
                if info is None or (mentioned and info["agencies"] and mentioned not in info["agencies"]):
                    result["hallucinated"].append(key)
                else:
                    result["valid"].append(key)

    # 판례 번호 검증 — 재결 구간을 가린 뒤
    for match in _PREC_PATTERN.finditer(_mask_ruling_spans(response_text)):
        year_text = match.group(1)
        year = int(year_text) + (1900 if len(year_text) == 2 else 0)
        case_type = match.group(2)
        number = int(match.group(3))

        if not (1950 <= year <= 2030 and number <= 999999):
            continue

        prec_key = f"{year_text}{case_type}{number}"
        result["total_cited"] += 1

        if prec_key in available_precedents:
            result["valid"].append(prec_key)
        else:
            result["hallucinated"].append(prec_key)

    # 행정해석 검증
    if available_admin_refs is not None:
        for match in _ADMIN_PATTERN.finditer(response_text):
            ref_key = f"{match.group(1)}-{match.group(2)}"
            result["total_cited"] += 1

            if ref_key in available_admin_refs:
                result["valid"].append(ref_key)
            else:
                result["hallucinated"].append(ref_key)

    if result["hallucinated"]:
        result["warnings"].append(
            f"⚠️ {len(result['hallucinated'])}개의 판례/행정해석이 "
            f"검색 결과에서 확인되지 않았습니다: {', '.join(result['hallucinated'])}"
        )
        logger.warning(
            "판례 환각 감지: %s (유효: %s)",
            result["hallucinated"], result["valid"],
        )

    return result


# 교정 사유별 (머리말, 번호 목록 라벨, 1번 규칙). hallucinated는 기존 문구 그대로다.
_CORRECTION_TEXT = {
    "hallucinated": (
        "아래 노동법 상담 답변에서 판례·재결 번호가 잘못 인용되었습니다.",
        "확인되지 않은 판례 번호",
        "1. 위 판례 번호가 포함된 문장에서 번호만 제거하고, "
        "내용은 유지하되 출처를 다음과 같이 변경하세요:\n"
        '   "관련 판례가 있을 수 있으나 구체적 번호는 '
        'law.go.kr에서 확인이 필요합니다"\n',
    ),
    "low_relevance": (
        "아래 노동법 상담 답변에서 질문의 쟁점과 다른 판례가 근거로 인용되었습니다.",
        "쟁점이 다른 판례 번호",
        "1. 위 판례 번호와 그 판례를 근거로 든 구절만 제거하세요. "
        "법령 조문에 근거한 설명은 유지하세요.\n",
    ),
    "secondhand": (
        "아래 노동법 상담 답변에서 원문을 확인하지 못한 판례 번호가 인용되었습니다.",
        "원문 미확인 판례 번호",
        "1. 위 판례 번호가 포함된 문장에서 번호만 제거하고 "
        '"관련 판례는 원문 확인이 필요합니다"로 바꾸세요. 내용은 유지하세요.\n',
    ),
}


def correct_hallucinated_citations(
    response_text: str,
    hallucinated: list[str],
    config=None,
    deadline: float | None = None,
    reason: str = "hallucinated",
) -> str | None:
    """다른 LLM을 사용해 환각 판례 번호를 제거한 수정 답변을 생성.

    reason: "hallucinated"(기본 — 기존 문구 그대로) | "low_relevance"(쟁점이 다른 판례) |
        "secondhand"(다른 글이 언급한 번호, 원문 미확인). 머리말과 1번 규칙만 달라진다.

    관리자 설정 순서(1순위 → 나머지)로 시도한다(llm_gateway). 재작성 길이 가드에 걸리면 다음 순위.

    Args:
        config: AppConfig. None이면 교정하지 않는다.
        deadline: `time.monotonic()` 기준 단계 데드라인 (FR-07). 벤더 3곳이 각자
            타임아웃을 소진하면 maxDuration(300초)을 위협하므로 단계 전체를 자른다.
            None이면 CITATION_STAGE_BUDGET을 지금부터 적용한다.

    Returns:
        수정된 답변 텍스트. 실패 시 None.
    """
    if not hallucinated or config is None:
        return None

    if deadline is None:
        deadline = time.monotonic() + CITATION_STAGE_BUDGET
    per_call = _rewrite_timeout(len(response_text))

    hallucinated_str = ", ".join(hallucinated)

    head, label, rule = _CORRECTION_TEXT.get(reason, _CORRECTION_TEXT["hallucinated"])
    prompt = (
        f"{head}\n"
        f"{label}: {hallucinated_str}\n\n"
        "규칙:\n"
        f"{rule}"
        "2. 나머지 답변 내용은 절대 수정하지 마세요.\n"
        "3. 마크다운 형식을 유지하세요.\n"
        "4. 수정된 전체 답변만 출력하세요. 설명이나 부가 텍스트를 추가하지 마세요.\n\n"
        "원본 답변:\n"
        f"{response_text}"
    )

    # ⚠️ 제공자별 timeout은 **시도당**이고 재시도는 0이다 — 재시도가 살아 있으면 한 벤더가 단계
    #    예산을 통째로 삼킨다(실측: timeout=0.001에 1.37초 = 3회 시도). 토큰 한도는 답변 생성 한도와
    #    맞춘다 — 부족하면 0.7 길이 가드에 걸려 교정이 통째로 폐기된다.
    try:
        text, provider = llm_gateway.text(
            config, system="당신은 텍스트 교정 도우미입니다.", user=prompt,
            purpose="판례 교정", max_tokens=ANSWER_MAX_TOKENS, timeout=per_call,
            attempts=None, deadline=deadline,
            accept=lambda out: _is_valid_rewrite(out, response_text),
        )
    except llm_gateway.LLMUnavailable as e:
        logger.warning("판례 교정 실패: %s", e)
        return None
    logger.info("%s 판례 교정 완료: %d개 환각 제거", provider, len(hallucinated))
    return text


# ── 마이크로 퇴고: 환각 교정 후 문맥 자연스러움 보정 ─────────────────────────

# 타임아웃은 _rewrite_timeout()으로 입력 길이에 비례해 계산한다 — 고정 2초는
# 답변 전문(최대 8192토큰) 재생성에 턱없이 부족해 사실상 항상 실패했다 (FR-07).
MICRO_POLISH_MIN_BUDGET = 15.0  # 잔여 예산이 이보다 적으면 퇴고를 건너뛴다
MICRO_POLISH_THRESHOLD = 3  # 환각 N건 이상 시 발동

_MICRO_POLISH_SYSTEM = (
    "당신은 한국어 문장 교정 도우미입니다. "
    "판례 번호가 제거된 문장의 문맥을 자연스럽게 다듬어주세요.\n\n"
    "절대 규칙:\n"
    "1. 사실 정보(법조문, 금액, 날짜, 기준)를 절대 변경하지 마세요.\n"
    "2. 접속사, 연결어, 지시어만 수정하여 문맥을 매끄럽게 하세요.\n"
    "3. 마크다운 형식을 유지하세요.\n"
    "4. 새로운 판례 번호나 출처를 추가하지 마세요.\n"
    "5. 수정된 전체 텍스트만 출력하세요."
)


def micro_polish(
    corrected_text: str,
    hallucinated_count: int,
    config=None,
    deadline: float | None = None,
) -> str | None:
    """환각 교정 후 문맥 자연스러움 보정.

    환각이 MICRO_POLISH_THRESHOLD건 이상일 때만 발동한다.
    설정 1순위 모델로 접속사/연결어만 수정하여 문맥을 매끄럽게 보정(다음 순위로 넘기지 않음).

    Args:
        corrected_text: 환각 판례 제거 후 텍스트
        hallucinated_count: 제거된 환각 인용 수
        config: AppConfig. None이면 퇴고하지 않는다.
        deadline: 인용 교정 단계 데드라인 (FR-07). 퇴고는 정확성이 아니라 품질
            보정이므로 예산 경쟁에서 후순위 — 잔여가 부족하면 건너뛴다.

    Returns:
        퇴고된 텍스트. 실패 또는 불필요 시 None.
    """
    if hallucinated_count < MICRO_POLISH_THRESHOLD:
        return None

    if config is None:
        return None

    # deadline 미지정 시 예산을 지금부터 새로 부여한다 — correct_hallucinated_citations와
    # 동일한 정규화. 이게 없으면 None이 "단계 예산 전액"으로 해석돼 교정 단계가
    # 이미 쓴 시간을 무시하게 된다.
    if deadline is None:
        deadline = time.monotonic() + CITATION_STAGE_BUDGET
    budget = _remaining(deadline)
    if budget < MICRO_POLISH_MIN_BUDGET:
        logger.info("마이크로 퇴고 생략 — 잔여 예산 %.1f초", budget)
        return None

    try:
        # 재시도 차단·토큰 한도 이유는 correct_hallucinated_citations 주석 참고.
        polished, _provider = llm_gateway.text(
            config, system=_MICRO_POLISH_SYSTEM, purpose="마이크로 퇴고",
            max_tokens=ANSWER_MAX_TOKENS,
            timeout=min(_rewrite_timeout(len(corrected_text)), budget), attempts=1,
            user=(
                f"{hallucinated_count}개의 판례 번호가 제거되어 "
                "문맥이 어색할 수 있는 텍스트입니다. "
                "접속사와 연결어만 수정하여 자연스럽게 다듬어주세요.\n\n"
                f"{corrected_text}"
            ),
        )
        if _is_valid_rewrite(polished, corrected_text):
            logger.info(
                "마이크로 퇴고 완료: %d건 환각 교정 후 문맥 보정",
                hallucinated_count,
            )
            return polished
        logger.warning("마이크로 퇴고 결과 길이 이상 — 원본 유지")
        return None

    except Exception as e:
        logger.warning("마이크로 퇴고 실패 (정규식 교정 결과 유지): %s", e)
        return None
