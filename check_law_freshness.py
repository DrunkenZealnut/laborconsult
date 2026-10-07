#!/usr/bin/env python3
"""법령 조문 조회가 **기준일 시행판**을 반환하는지 본문으로 실측한다 (수동 검증).

CI에서는 돌지 않는다 — 법제처 API 키가 등록 IP에서만 동작한다(Actions 불가).
`check_schema.py`처럼 **배포 전 수동 실행 항목**이고, 아래 "시행 예정 판본" 목록이
가리키는 **시행일 당일 오전**에도 돌린다.

검증 방식(effective-law-and-graph-precedents D3·D4):
1. 기준판 = 판본 목록(`lawSearch target=eflaw`)에서 `max(시행일자 ≤ KST 오늘)`.
   법제처의 '현행' 표지(nw=3)를 기준으로 삼지 않는다 — 법제처 반영이 늦으면 표지와
   본문이 같이 늦어 지연을 잡지 못한다.
2. 프로덕션 경로(`legal_api.fetch_law_root`, efYd 없음)와 `efYd=<기준판>` 본문을
   **조문 단위로** 프로덕션 포맷 함수(`_format_full_article`)로 만들어 대조한다.
   헤더(시행일자·공포번호)만 보면 안 된다 — `target=law`는 헤더가 현행판인데 본문에
   시행 예정 개정이 섞여 왔고(2026-10-04 실측), 헤더 대조였던 구 검증은 그동안 ✅를 냈다.
3. **fail-closed**: 한쪽에만 있는 조문도 차이, 판본 목록 미일치·빈 루트·예외는 실패.
   감시 도구가 실패를 삼키면 감시가 죽은 것도 조용해진다.

    python3 check_law_freshness.py            # 본문 대조 + 시행 예정 판본 목록
    python3 check_law_freshness.py --anchors  # + 앵커(다음 판본·현행 고시)·별표 주장·참조 조문 생존
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

from app.core import safe_xml
from app.core.legal_api import (  # noqa: E402
    LAW_SEARCH_URL, _format_full_article, _http, _norm_compact, _raise_if_error_root, fetch_law_root,
)


def _watched_laws() -> list[str]:
    """검증 목록 = 예열 대상과 같다(`law_catalog.warm_law_names()`, production-law-api-recovery D14).

    기본 17종 + **프로덕션이 실제로 조회하는 이름들**(주제 기본 조문·키워드 조문의 법령). 정식명 고정
    목록만 검사하면 프로덕션 실입력의 표기 결함이 새어나간다 — 실측: `legal_consultation.py`의
    남녀고용평등법 인용이 가운뎃점 이형(U+00B7)으로 상시 실패 중이었는데, 이 스크립트는 정식 표기
    (U+318D) 판본을 검사해 ✅를 냈다(분석 P1-4). 예열과 목록이 갈리면 "점검은 하는데 예열은 안 되는"
    사각이 생기므로 목록을 이 스크립트에 따로 두지 않는다.
    """
    from app.core.law_catalog import warm_law_names
    return warm_law_names()


def _today_kst() -> str:
    from wage_calculator.legal_rules import kst_today
    return kst_today().replace("-", "")


def law_versions(name: str, key: str) -> list[dict]:
    """판본 목록(시행일자 내림차순). 법령명은 compact 일치만 — 시행령·시행규칙이 섞인다."""
    r = _http.get(LAW_SEARCH_URL, params={
        "OC": key, "target": "eflaw", "type": "XML", "query": name,
        "sort": "efdes", "display": "100",
    }, timeout=20)
    r.raise_for_status()
    root = safe_xml.fromstring(r.content)
    # 인증 오류(등록 IP 아님 등)는 LawApiAuthError — '판본 없음'으로 읽으면 예열이 판본을 고르지 못한다.
    _raise_if_error_root(root)
    out = []
    for el in root.iter("law"):
        nm = (el.findtext("법령명한글") or "").strip()
        if _norm_compact(nm) != _norm_compact(name):
            continue
        out.append({
            "date": (el.findtext("시행일자") or "").strip(),
            "status": (el.findtext("현행연혁코드") or "").strip(),
            "promulgated": (el.findtext("공포일자") or "").strip(),
            "number": (el.findtext("공포번호") or "").strip(),
            "kind": (el.findtext("제개정구분명") or "").strip(),
        })
    return out


def reference_version(versions: list[dict], today: str) -> str | None:
    """기준판 = max(시행일자 ≤ today). 없으면 None(→ 실패)."""
    dates = [v["date"] for v in versions if v["date"] and v["date"] <= today]
    return max(dates) if dates else None


def _article_key(jo: ET.Element) -> str:
    no = (jo.findtext("조문번호") or "").strip()
    branch = (jo.findtext("조문가지번호") or "").strip().lstrip("0")   # "0"·"00" = 가지 없음
    return no + (f"의{branch}" if branch else "")


def _article_texts(root: ET.Element) -> dict[str, str]:
    """조문키 → 프로덕션 포맷 텍스트. 편·장·절 제목(조문여부=전문)은 제외."""
    out: dict[str, str] = {}
    for jo in root.iter("조문단위"):
        if (jo.findtext("조문여부") or "").strip() != "조문":
            continue
        out[_article_key(jo)] = _format_full_article(jo) or ""
    return out


def _sort_key(k: str) -> tuple[int, int]:
    m = re.match(r"(\d+)(?:의(\d+))?", k)
    return (int(m.group(1)), int(m.group(2) or 0)) if m else (10**9, 0)


def _diff_articles(a: dict[str, str], b: dict[str, str]) -> list[str]:
    """내용이 다르거나 **한쪽에만 있는** 조문 키(정렬). 공통 조문만 보면 판본이 통째로
    다른 경우(한쪽이 비어 있음)에도 '차이 0'으로 통과한다."""
    return sorted((k for k in set(a) | set(b) if a.get(k) != b.get(k)), key=_sort_key)


def check_law(name: str, key: str, today: str) -> dict:
    """한 법령의 판정. {"ok", "reason", "reference", "header", "diff", "upcoming", "root"}."""
    res = {"name": name, "ok": False, "reason": "", "reference": None,
           "header": None, "diff": [], "upcoming": [], "root": None}
    try:
        versions = law_versions(name, key)
    except Exception as e:  # 조회 실패도 실패다(fail-closed)
        res["reason"] = f"판본 목록 조회 실패: {e}"
        return res
    if not versions:
        res["reason"] = "판본 목록에 법령명 일치 없음"
        return res
    res["upcoming"] = sorted({(v["date"], v["kind"]) for v in versions if v["date"] > today})
    ref = reference_version(versions, today)
    res["reference"] = ref
    if not ref:
        res["reason"] = "기준일 이전 판본 없음"
        return res
    try:
        prod = fetch_law_root(name, key)
        base = fetch_law_root(name, key, ef_yd=ref)
    except Exception as e:
        res["reason"] = f"본문 조회 실패: {e}"
        return res
    if prod is None or base is None:
        res["reason"] = f"본문 미매칭(프로덕션 {'O' if prod is not None else 'X'}, 기준판 {'O' if base is not None else 'X'})"
        return res
    res["header"] = (prod.findtext(".//기본정보/시행일자") or "").strip()
    res["root"] = prod   # 생존 점검이 다시 받지 않도록(law-article-coverage D5 ③)
    a, b = _article_texts(prod), _article_texts(base)
    if not a or not b:
        res["reason"] = "조문 0개"
        return res
    res["diff"] = _diff_articles(a, b)
    if res["diff"]:
        res["reason"] = f"기준판과 다른 조문 {len(res['diff'])}개"
        return res
    res["ok"] = True
    return res


def _next_root(law: str, key: str, today: str, cache: dict) -> tuple[str, ET.Element | None] | None:
    """다음 시행 판본 (시행일, 루트). 없으면 None. 판본 목록 조회 실패는 예외로 올린다(호출자가 경고)."""
    if law not in cache:
        upcoming = sorted(v["date"] for v in law_versions(law, key) if v["date"] > today)
        cache[law] = (upcoming[0], fetch_law_root(law, key, ef_yd=upcoming[0])) if upcoming else None
    return cache[law]


def _anchor_checks(key: str, today: str) -> tuple[list[str], list[str]]:
    """규칙 블록·답변 규칙 앵커 점검 → (실패, 경고).

    - **조문 문서**(`fetch_official_rules.ARTICLES`): 다음 시행 판본에서도 구절이 참인지 본다(경고). 현행판의
      참은 저장본 대조(K6·C12)가 맡는다.
    - **고시 문서**(`ADMRULS`, law-article-coverage D11): 고시는 발령 즉시 시행되는 일이 많아 '다음 판본'을 미리
      볼 수 없다. 그래서 **현행** 고시를 받아 구절을 대조하고, 없으면 실패다. 조회 실패도 실패다(fail-closed).
      저장본의 시행일·발령번호와 현행이 다르면 경고(재수집·앵커 재대조).

    답변 규칙(`prompts.ANSWER_RULE_ANCHORS`)도 손으로 쓴 사실이라 같은 점검을 받는다
    (claim-authority-and-assessor-facts M11 — 규칙 블록만 돌면 새 등록부가 조용히 빠진다)."""
    import fetch_official_rules as fo
    from app.core.rule_facts import RULE_FACTS
    from app.templates.prompts import ANSWER_RULE_ANCHORS
    articles = {a[0]: a for a in fo.ARTICLES}
    admruls = {a[0]: a for a in fo.ADMRULS}
    norm = lambda t: re.sub(r"\s+", "", t)  # noqa: E731
    failures, warnings, next_cache = [], [], {}
    notice_phrases: dict[str, list[tuple[str, str]]] = {}
    groups = [(f.name, f.anchors) for f in RULE_FACTS] + [("answer_rules", ANSWER_RULE_ANCHORS)]
    for group, anchors in groups:
        for doc_id, phrase in anchors:
            if doc_id in admruls:
                notice_phrases.setdefault(doc_id, []).append((group, phrase))
                continue
            if doc_id not in articles:
                warnings.append(f"{group}: 앵커 문서 미등록 {doc_id}")
                continue
            _, law, no, sub, _k = articles[doc_id]
            try:
                nxt = _next_root(law, key, today, next_cache)
            except Exception as e:  # 경고 단계 — 원인을 남기고 다음 앵커로
                warnings.append(f"{group}: {law} 다음 판본 확인 불가 ({e})")
                next_cache[law] = None
                continue
            if not nxt:
                continue
            ef, root = nxt
            if root is None:   # 판본 본문을 못 받았으면 '거짓'이 아니라 '확인 불가'다
                warnings.append(f"{group}: {law} {ef} 판본 본문 확인 불가")
                continue
            text = _article_texts(root).get(f"{no}의{sub}" if sub else str(no), "")
            if norm(phrase) not in norm(text):
                warnings.append(f"{group}: {law} 제{no}조 앵커가 {ef}부터 거짓 — {phrase[:30]}")
    for doc_id, phrases in notice_phrases.items():
        _, query, exact, dept, _keys = admruls[doc_id]
        try:
            doc = fo.fetch_admrul(key, query, exact, dept)
        except Exception as e:
            failures.append(f"{doc_id}: 현행 고시 조회 실패 ({e})")
            continue
        if not doc or not doc.get("body"):
            failures.append(f"{doc_id}: 현행 고시 미수록 — {exact}")
            continue
        body = norm(doc["body"])
        for group, phrase in phrases:
            if norm(phrase) not in body:
                failures.append(f"{group}: 현행 고시({doc_id})에 앵커 구절 없음 — {phrase[:30]}")
        stored = fo.stored_notice(doc_id) or {}
        current = doc.get("effective") or doc.get("issued") or ""
        if stored.get("date") and current and stored["date"].replace("-", "") != current:
            warnings.append(f"{doc_id}: 고시 시행일 {stored['date']} → {current} — "
                            f"fetch_official_rules.py --doc {doc_id} 재수집 후 앵커 재대조")
    return failures, warnings


# ── 별표 '적용 규정' 목록 (law-article-coverage D9·D10) ───────────────────────
# 별표 본문은 표 칸 안에서 줄이 바뀌며 조문 번호가 쪼개진다(`제 ┃ ┃ │35조부터`). 범위("제35조부터 제42조까지")
# 안의 조문은 문자열로 나타나지 않는다. 그래서 부분문자열 검사는 실린 조문도 '없음'으로 본다(거짓 안심) —
# 표 문자·공백을 지우고, 범위를 펼치고, 항·호 한정과 괄호 한정("…로 한정한다")을 구분해 목록으로 읽는다.
ANNEX_ALL = "ALL"
ANNEX_PARTIAL = "PARTIAL"
_BOX_RE = re.compile(r"[┃│┠┼┨━┯┷┏┓┗┛─┌┐└┘├┤┬┴\s]")
_ART = r"제(\d+)조(?:의(\d+))?"
_RANGE_RE = re.compile(_ART + r"부터" + _ART + r"까지")
_ITEM_RE = re.compile(_ART + r"((?:제\d+항)(?:[·ㆍ,]제\d+항)*)?(제\d+호)?")
_PAREN_RE = re.compile(r"\(([^()]*)\)")
_QUALIFIER_RE = re.compile(r"한정|제외")
_CHAPTER_REF_RE = re.compile(r"제\d+장(?:의\d+)?$")
_ARTICLE_REF_RE = re.compile(r"제(\d+)조(?:의(\d+))?(?:제(\d+)항)?$")


@dataclass
class AnnexListing:
    """별표 본문을 해석한 적용 규정 목록.

    articles: {(조, 가지): ANNEX_ALL | frozenset(항) | ANNEX_PARTIAL}. PARTIAL = 호 한정·괄호 한정(…로 한정한다,
    …은 제외한다)이라 '있음'의 근거가 되지 못한다. unparsed: 해석을 확신하지 못한 조 번호(가지번호가 든 범위,
    괄호 안의 조문 언급). ranges: 펼친 일반 범위 — 그 안의 가지 조문(제76조의2 등)은 포함 여부를 알 수 없다.
    """
    articles: dict = field(default_factory=dict)
    unparsed: set = field(default_factory=set)
    ranges: list = field(default_factory=list)
    text: str = ""


def _merge_listing(arts: dict, key: tuple, value) -> None:
    cur = arts.get(key)
    if cur == ANNEX_ALL or value == ANNEX_ALL:
        arts[key] = ANNEX_ALL
    elif cur is None:
        arts[key] = value
    elif cur == ANNEX_PARTIAL or value == ANNEX_PARTIAL:
        arts[key] = ANNEX_PARTIAL
    else:
        arts[key] = frozenset(cur) | frozenset(value)


def annex_listing(text: str) -> AnnexListing:
    """별표 본문 → 적용 규정 목록(D9). 머리말(제목·"(제7조 관련)")은 '적용법규정' 칸 머리 뒤부터 읽어 뺀다."""
    t = _BOX_RE.sub("", text or "")
    listing = AnnexListing(text=t)
    body = t.split("적용법규정", 1)[-1]
    qualified_at: list[tuple[int, int]] = []        # (괄호 시작 위치, 끝) — 한정·제외 괄호
    for m in _PAREN_RE.finditer(body):
        inner = m.group(1)
        if re.search(_ART, inner):                   # 괄호 안의 조문 언급은 해석하지 않는다(fail-closed, D10)
            listing.unparsed.update(int(x.group(1)) for x in re.finditer(_ART, inner))
        if _QUALIFIER_RE.search(inner):
            qualified_at.append((m.start(), m.end()))
    body_wo_paren = _PAREN_RE.sub(lambda m: " " * len(m.group(0)), body)

    def qualified(end: int) -> bool:
        """항목 바로 뒤('의규정' 건너뛰고)에 한정·제외 괄호가 붙었는가."""
        rest = body[end:]
        skip = len(rest) - len(rest.lstrip("의규정"))
        return any(start == end + skip for start, _ in qualified_at)

    for m in _RANGE_RE.finditer(body_wo_paren):
        a, a_sub, b, b_sub = int(m.group(1)), m.group(2), int(m.group(3)), m.group(4)
        if a_sub or b_sub:
            listing.unparsed.update(range(a, b + 1))
            continue
        value = ANNEX_PARTIAL if qualified(m.end()) else ANNEX_ALL
        listing.ranges.append((a, b))
        for n in range(a, b + 1):
            _merge_listing(listing.articles, (n, None), value)
    singles = _RANGE_RE.sub(lambda m: " " * len(m.group(0)), body_wo_paren)
    for m in _ITEM_RE.finditer(singles):
        key = (int(m.group(1)), int(m.group(2)) if m.group(2) else None)
        if m.group(4) or qualified(m.end()):         # 호 한정·괄호 한정 → 부분
            value = ANNEX_PARTIAL
        elif m.group(3):
            value = frozenset(int(x) for x in re.findall(r"제(\d+)항", m.group(3)))
        else:
            value = ANNEX_ALL
        _merge_listing(listing.articles, key, value)
    return listing


def annex_claim_holds(listing: AnnexListing, ref: str, applies: bool) -> bool | None:
    """주장이 참인가. 해석을 확신할 수 없으면 None(→ 호출자가 실패로 본다, D10).

    조 단위 '없음'은 그 조가 목록에 **전혀** 없어야 참이다(항·부분으로라도 있으면 거짓). '있음'은 ALL(항 단위
    주장이면 그 항)이어야 참이고 PARTIAL은 근거가 되지 못한다.
    """
    if _CHAPTER_REF_RE.fullmatch(ref):
        return (ref in listing.text) == applies
    m = _ARTICLE_REF_RE.fullmatch(ref)
    if not m:
        return None
    no, sub, para = int(m.group(1)), (int(m.group(2)) if m.group(2) else None), (int(m.group(3)) if m.group(3) else None)
    if no in listing.unparsed:
        return None
    if sub is not None and any(a <= no <= b for a, b in listing.ranges):
        return None                                  # 일반 범위 안의 가지 조문 — 포함 여부를 알 수 없다
    entry = listing.articles.get((no, sub))
    if entry is None:
        status = "none"
    elif entry == ANNEX_ALL:
        status = "all"
    elif entry == ANNEX_PARTIAL:
        status = "partial"
    elif para is None:
        status = "partial"                           # 항 한정으로만 실린 조를 조 단위로 주장
    else:
        status = "all" if para in entry else "none"
    if status == "partial":
        return False
    return (status == "all") == applies


def annex_text(root: ET.Element, title_part: str) -> str | None:
    """별표 제목에 title_part가 든 표의 본문(`별표내용`, 없으면 전체 텍스트). 표가 없으면 None."""
    for annex in root.iter("별표단위"):
        if title_part in (annex.findtext("별표제목") or ""):
            return annex.findtext("별표내용") or "".join(annex.itertext())
    return None


def _annex_checks(key: str, today: str) -> tuple[list[str], list[str]]:
    """규칙 블록·답변 규칙의 별표 주장 점검(`rule_facts.ANNEX_CLAIMS`). (현행 위반=실패, 다음 판본 위반=경고)."""
    from app.core.rule_facts import ANNEX_CLAIMS
    failures, warnings, current, nxt, versions_cache = [], [], {}, {}, {}
    for claim in ANNEX_CLAIMS:
        label = f"{claim.group}: {claim.law} 별표({claim.annex_title}) {claim.ref} {'있음' if claim.applies else '없음'}"
        try:
            if claim.law not in current:
                current[claim.law] = fetch_law_root(claim.law, key)
        except Exception as e:  # 현행판 확인 실패도 실패다(fail-closed)
            failures.append(f"{label} — 별표 조회 실패 ({e})")
            continue
        text = annex_text(current[claim.law], claim.annex_title) if current[claim.law] is not None else None
        held = annex_claim_holds(annex_listing(text), claim.ref, claim.applies) if text is not None else None
        if held is not True:
            failures.append(f"{label} — {'거짓이 됐다' if held is False else '확인 불가(별표 없음·해석 불가)'}"
                            " — 문장 재검토")
        try:
            if claim.law not in nxt:
                nxt[claim.law] = _next_root(claim.law, key, today, versions_cache)
            if nxt[claim.law]:
                ef, nroot = nxt[claim.law]
                ntext = annex_text(nroot, claim.annex_title) if nroot is not None else None
                nheld = annex_claim_holds(annex_listing(ntext), claim.ref, claim.applies) if ntext else None
                if nheld is False:
                    warnings.append(f"{label} — {ef}부터 거짓")
                elif nheld is None:
                    warnings.append(f"{label} — {ef} 판본 별표 확인 불가")
        except Exception as e:
            warnings.append(f"{label} — 다음 판본 별표 확인 불가 ({e})")
    return failures, warnings


# ── 참조 조문 생존 점검 (law-article-coverage D5 ③) ──────────────────────────
# 구 산재보험법 제125조(2022.6.10 삭제)가 주제 기본 조문·분석 프롬프트 매핑·계산기 법적 근거 문자열의 세 경로로
# 4년 넘게 실리고 있었다. 키워드 규칙·주제 기본 조문에 더해 **코드 속 조문 표기**(문자열 리터럴)도 본다.
# 의도적으로 삭제 조문을 언급하는 곳(예: "…제35조는 삭제된 조문이므로 인용하지 않는다")은 허용 목록에 둔다.
CODE_REF_PATHS = ("app/templates/prompts.py", "app/core/rule_facts.py", "app/core/legal_consultation.py",
                  "app/core/law_catalog.py", "app/core/precedent_query.py", "app/core/pipeline.py",
                  "wage_calculator", "harassment_assessor")
KNOWN_DELETED_REFS = ("산업재해보상보험법 제125조", "근로기준법 제35조")
DELETED_REF_MENTIONS = {("app/core/rule_facts.py", "근로기준법 제35조")}


def _law_name_alternation() -> str:
    from app.core.law_catalog import warm_law_names
    from app.core.legal_api import _LAW_NAME_ALIASES
    names = set(warm_law_names()) | set(_LAW_NAME_ALIASES)
    names = {n.replace(" ", r"\s*") for n in names}
    return "|".join(sorted(names, key=len, reverse=True))


def code_law_refs(root_dir: str = ".") -> list[tuple[str, int, str]]:
    """CODE_REF_PATHS의 파이썬 문자열 리터럴에서 (파일, 줄, "법령명 제N조[의M]")를 뽑는다. 주석은 보지 않는다."""
    import ast
    from pathlib import Path
    from app.core.legal_api import _alias_name
    # 앞 글자가 한글이면 다른 법령명의 일부다("국세징수법"의 '징수법', "…근로기준법"의 '기준법' 따위)
    pattern = re.compile(rf"(?<![가-힣])({_law_name_alternation()})\s*(시행령|시행규칙)?\s*제(\d+)조(?:의(\d+))?")
    base = Path(root_dir)
    files: list[Path] = []
    for rel in CODE_REF_PATHS:
        p = base / rel
        files += sorted(p.rglob("*.py")) if p.is_dir() else [p]
    out = []
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for m in pattern.finditer(node.value):
                    law = _alias_name(re.sub(r"\s+", " ", m.group(1)))
                    if m.group(2):
                        law = f"{law} {m.group(2)}"
                    ref = f"{law} 제{m.group(3)}조" + (f"의{m.group(4)}" if m.group(4) else "")
                    out.append((path.relative_to(base).as_posix(), node.lineno, ref))
    return out


def _reference_targets() -> list[tuple[str, str]]:
    """(출처, 참조) — 키워드 규칙(주·보충)·주제 기본 조문·코드 속 표기(허용 목록 제외)."""
    from app.core.law_catalog import KEYWORD_LAWS
    from app.core.legal_consultation import TOPIC_SEARCH_CONFIG
    out = [(f"키워드:{r.name}", ref) for r in KEYWORD_LAWS for ref in r.refs + r.extra]
    out += [(f"주제:{t}", ref) for t, cfg in TOPIC_SEARCH_CONFIG.items() for ref in cfg.get("default_laws", [])]
    out += [(f"{path}:{line}", ref) for path, line, ref in code_law_refs()
            if (path, ref) not in DELETED_REF_MENTIONS]
    return out


def _liveness_checks(key: str, today: str, roots: dict[str, ET.Element]) -> tuple[list[str], list[str]]:
    """참조 조문이 현행판에 있고 삭제되지 않았는가(없음·삭제 = 실패, 다음 판본에서 삭제 = 경고).

    `roots`는 `check_law`가 받은 현행 루트(법령명 → 루트)다 — 법령마다 다시 받지 않는다(검증 L8). 예열 대상이
    아닌 법령의 표기는 대상에서 뺀다(`code_law_refs`가 예열 법령명만 뽑는다)."""
    from app.core.legal_api import _extract_article, canonical_law_name, is_deleted_article, parse_law_reference
    failures, warnings, next_cache, seen = [], [], {}, set()
    for origin, ref in _reference_targets():
        parsed = parse_law_reference(ref)
        if not parsed:
            continue
        law = canonical_law_name(parsed["law"])
        ident = (law, parsed["article"], parsed.get("sub"))
        root = roots.get(law)
        if root is None:
            try:
                root = roots[law] = fetch_law_root(law, key)
            except Exception as e:
                failures.append(f"{origin}: {ref} — 현행판 조회 실패 ({e})")
                continue
        text = _extract_article(root, parsed["article"], None, parsed.get("sub")) if root is not None else None
        label = f"{origin}: {ref}"
        if not text:
            failures.append(f"{label} — 현행판에 없는 조문")
            continue
        if is_deleted_article(text):
            failures.append(f"{label} — 삭제된 조문")
            continue
        if ident in seen:
            continue
        seen.add(ident)
        try:
            nxt = _next_root(law, key, today, next_cache)
        except Exception as e:
            warnings.append(f"{label} — 다음 판본 확인 불가 ({e})")
            continue
        if nxt and nxt[1] is not None:
            ntext = _extract_article(nxt[1], parsed["article"], None, parsed.get("sub"))
            if not ntext or is_deleted_article(ntext):
                warnings.append(f"{label} — {nxt[0]}부터 {'없는' if not ntext else '삭제된'} 조문")
    return failures, warnings


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv  # import 시점이 아니라 실행 시에만(테스트 환경변수 보호)
    load_dotenv(override=True)

    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--anchors", action="store_true",
                        help="앵커(다음 판본·현행 고시)·별표 주장·참조 조문 생존 점검")
    args = parser.parse_args(argv)

    key = os.getenv("LAW_API_KEY")
    if not key:
        print("LAW_API_KEY 미설정 — 이 검증은 법제처 API가 필요합니다.")
        return 1
    today = _today_kst()
    watched = _watched_laws()
    print(f"기준일 {today} (KST) · 대상 {len(watched)}종")
    print(f"{'법령':<34} {'기준판':>9} {'헤더':>9}  판정")
    print("─" * 76)
    bad, upcoming, roots = 0, [], {}
    for name in watched:
        r = check_law(name, key, today)
        if r.get("root") is not None:
            roots[name] = r["root"]
        bad += (not r["ok"])
        lag = r["header"] and r["reference"] and r["header"] != r["reference"]
        verdict = "✅" if r["ok"] else f"❌ {r['reason']}"
        if r["ok"] and lag:
            verdict += f"  ⚠️ 헤더 시행일자 {r['header']} ≠ 기준판(법제처 반영 지연?)"
        print(f"{name:<34} {r['reference'] or '—':>9} {r['header'] or '—':>9}  {verdict}")
        if r["diff"]:
            print(f"    차이 조문: {', '.join(r['diff'][:20])}{' …' if len(r['diff']) > 20 else ''}")
        if r["upcoming"]:
            upcoming.append((name, r["upcoming"]))

    print("─" * 76)
    if upcoming:
        print("시행 예정 판본 (그날 오전 이 스크립트를 다시 돌릴 것):")
        for name, items in upcoming:
            print(f"  {name}: " + ", ".join(f"{d}({k})" for d, k in items))
    if args.anchors:
        anchor_fail, warnings = _anchor_checks(key, today)
        annex_fail, annex_warn = _annex_checks(key, today)
        live_fail, live_warn = _liveness_checks(key, today, roots)
        warnings += annex_warn + live_warn
        fails = anchor_fail + annex_fail + live_fail
        print("앵커(다음 판본·현행 고시)·별표 주장·참조 조문 생존:", "이상 없음" if not (warnings or fails) else "")
        for w in warnings:
            print(f"  ⚠️ {w}")
        for f in fails:
            print(f"  ❌ {f}")
        bad += len(fails)
    if bad:
        print(f"❌ {bad}건 실패 — 조회 경로가 기준일 시행판을 반환하지 않거나 확인할 수 없습니다.")
        return 1
    print(f"✅ {len(watched)}종 전부 기준일 시행판 반환")
    return 0


if __name__ == "__main__":
    sys.exit(main())
