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
    python3 check_law_freshness.py --anchors  # + 규칙 블록 조문 앵커의 다음 판본 경고
"""
from __future__ import annotations

import argparse
import os
import re
import sys
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
    """한 법령의 판정. {"ok", "reason", "reference", "header", "diff", "upcoming"}."""
    res = {"name": name, "ok": False, "reason": "", "reference": None,
           "header": None, "diff": [], "upcoming": []}
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


def _anchor_warnings(key: str, today: str) -> list[str]:
    """규칙 블록·답변 규칙의 **조문** 앵커가 다음 시행 판본에서도 참인지(실패 코드 아님 — 경고).

    답변 규칙(`prompts.ANSWER_RULE_ANCHORS`)도 손으로 쓴 사실이라 같은 점검을 받는다
    (claim-authority-and-assessor-facts M11 — 규칙 블록만 돌면 새 등록부가 조용히 빠진다)."""
    import fetch_official_rules as fo
    from app.core.rule_facts import RULE_FACTS
    from app.templates.prompts import ANSWER_RULE_ANCHORS
    articles = {a[0]: a for a in fo.ARTICLES}
    norm = lambda t: re.sub(r"\s+", "", t)  # noqa: E731
    warnings, next_root = [], {}
    groups = [(f.name, f.anchors) for f in RULE_FACTS] + [("answer_rules", ANSWER_RULE_ANCHORS)]
    for group, anchors in groups:
        for doc_id, phrase in anchors:
            if doc_id not in articles:
                warnings.append(f"{group}: 앵커 문서 미등록 {doc_id}")
                continue
            _, law, no, sub, _k = articles[doc_id]
            try:
                if law not in next_root:
                    upcoming = sorted(v["date"] for v in law_versions(law, key) if v["date"] > today)
                    next_root[law] = ((upcoming[0], fetch_law_root(law, key, ef_yd=upcoming[0]))
                                      if upcoming else None)
            except Exception as e:  # 경고 단계 — 원인을 남기고 다음 앵커로
                warnings.append(f"{group}: {law} 다음 판본 확인 불가 ({e})")
                next_root[law] = None
                continue
            if not next_root[law]:
                continue
            ef, root = next_root[law]
            if root is None:   # 판본 본문을 못 받았으면 '거짓'이 아니라 '확인 불가'다
                warnings.append(f"{group}: {law} {ef} 판본 본문 확인 불가")
                continue
            text = _article_texts(root).get(f"{no}의{sub}" if sub else str(no), "")
            if norm(phrase) not in norm(text):
                warnings.append(f"{group}: {law} 제{no}조 앵커가 {ef}부터 거짓 — {phrase[:30]}")
    return warnings


def _annex_absence(root: ET.Element, title_part: str, absent: str) -> bool | None:
    """별표 제목에 title_part가 든 표의 본문에 absent가 **없으면** True. 표를 못 찾으면 None."""
    for annex in root.iter("별표단위"):
        if title_part in (annex.findtext("별표제목") or ""):
            return absent not in "".join(annex.itertext())
    return None


def _annex_checks(key: str, today: str) -> tuple[list[str], list[str]]:
    """규칙 블록의 '별표에 없다' 주장 점검. (현행 위반=실패, 다음 판본 위반=경고)."""
    from app.core.rule_facts import ANNEX_ABSENCE_CLAIMS
    failures, warnings = [], []
    for block, law, title_part, absent in ANNEX_ABSENCE_CLAIMS:
        try:
            current = _annex_absence(fetch_law_root(law, key) or ET.Element("x"), title_part, absent)
        except Exception as e:  # 현행판 확인 실패도 실패다(fail-closed)
            failures.append(f"{block}: {law} 별표 조회 실패 ({e})")
            continue
        if current is not True:
            failures.append(f"{block}: {law} 별표({title_part})에 '{absent}'가 "
                            f"{'생겼다' if current is False else '확인 불가(별표 없음)'} — 블록 문장 재검토")
        try:
            upcoming = sorted(v["date"] for v in law_versions(law, key) if v["date"] > today)
            if upcoming:
                nroot = fetch_law_root(law, key, ef_yd=upcoming[0])
                nxt = _annex_absence(nroot, title_part, absent) if nroot is not None else None
                if nxt is False:
                    warnings.append(f"{block}: {upcoming[0]}부터 {law} 별표에 '{absent}' 포함 — 블록 문장이 거짓이 됨")
                elif nxt is None:
                    warnings.append(f"{block}: {law} {upcoming[0]} 판본 별표 확인 불가")
        except Exception as e:
            warnings.append(f"{block}: {law} 다음 판본 별표 확인 불가 ({e})")
    return failures, warnings


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv  # import 시점이 아니라 실행 시에만(테스트 환경변수 보호)
    load_dotenv(override=True)

    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--anchors", action="store_true", help="규칙 블록 앵커의 다음 판본 경고")
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
    bad, upcoming = 0, []
    for name in watched:
        r = check_law(name, key, today)
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
        warnings = _anchor_warnings(key, today)
        annex_fail, annex_warn = _annex_checks(key, today)
        warnings += annex_warn
        print("규칙 블록 앵커(다음 판본)·별표 부재 주장:", "이상 없음" if not (warnings or annex_fail) else "")
        for w in warnings:
            print(f"  ⚠️ {w}")
        for f in annex_fail:
            print(f"  ❌ {f}")
        bad += len(annex_fail)
    if bad:
        print(f"❌ {bad}건 실패 — 조회 경로가 기준일 시행판을 반환하지 않거나 확인할 수 없습니다.")
        return 1
    print(f"✅ {len(watched)}종 전부 기준일 시행판 반환")
    return 0


if __name__ == "__main__":
    sys.exit(main())
