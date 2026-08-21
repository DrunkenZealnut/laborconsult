#!/usr/bin/env python3
"""법령 조문 조회가 현행판을 반환하는지 실측 (law-version-drift 수동 검증).

CI에서는 돌지 않는다(법제처 API 필요) — check_schema.py처럼 배포 전
수동 실행 항목이다. 오프라인 CI는 구조(MST 미사용)만 고정하고, "실제로
현행판이 오는가"는 이 스크립트만 확인할 수 있다.

검증 방식: 각 법령을 (a) 프로덕션 경로(fetch_article이 쓰는 LM 조회)와
(b) 법령 검색의 현행 시행일로 이중 조회해 시행일이 일치하는지 대조한다.
불일치가 하나라도 있으면 종료 코드 1 — 드리프트 재발이다.

대상 17종은 과거 MST 사전매핑에 있던 주요 노동법이다(실측에서 11종이
낡아 있던 바로 그 목록 — 재발 감시 대상으로 보존).
"""
from __future__ import annotations

import os
import re
import sys
from xml.etree import ElementTree as ET

from dotenv import load_dotenv

load_dotenv(override=True)

from app.core.legal_api import (  # noqa: E402
    _http, LAW_SEARCH_URL, LAW_SERVICE_URL,
)

# 기본 17종: 과거 _PRELOADED_MST 목록(실측에서 11종이 낡아 있던 재발 감시 대상).
_BASE_LAWS = [
    "근로기준법", "근로기준법 시행령", "근로기준법 시행규칙",
    "최저임금법", "최저임금법 시행령",
    "고용보험법", "고용보험법 시행령",
    "산업재해보상보험법", "산업재해보상보험법 시행령",
    "근로자퇴직급여 보장법",
    "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률",
    "소득세법", "조세특례제한법",
    "기간제 및 단시간근로자 보호 등에 관한 법률",
    "파견근로자 보호 등에 관한 법률",
    "임금채권보장법", "노동조합 및 노동관계조정법",
]

_LAW_NAME_RE = re.compile(r"^(.+?)\s*제\d+조")


def _watched_laws() -> list[str]:
    """검증 목록 = 기본 17종 + **프로덕션이 실제로 조회하는 이름들**.

    정식명 고정 목록만 검사하면 프로덕션 실입력의 표기 결함이 새어나간다 —
    실측: `legal_consultation.py`의 남녀고용평등법 인용이 가운뎃점 이형
    (U+00B7)으로 상시 실패 중이었는데, 이 스크립트는 정식 표기(U+318D)
    판본을 검사해 ✅를 냈다(분석 P1-4). 하드코딩 인용을 여기로 끌어와야
    같은 클래스가 다시 새지 않는다.
    """
    from app.core.legal_api import _resolve_law_name
    from app.core.legal_consultation import TOPIC_SEARCH_CONFIG

    names = dict.fromkeys(_BASE_LAWS)          # 순서 보존 집합
    for cfg in TOPIC_SEARCH_CONFIG.values():
        for ref in cfg.get("default_laws", []):
            m = _LAW_NAME_RE.match(ref)
            if m:
                names.setdefault(_resolve_law_name(m.group(1).strip()))
    return list(names)


# ⚠️ 대조 기준은 시행일자가 아니라 **공포일자+공포번호**다. 부칙 단계시행이
# 있는 법(세법 등)은 같은 공포본이라도 목록은 최신 단계 시행일(예: 7/1),
# 본문 조회는 본칙 시행일(예: 1/1)을 표기해 시행일 대조가 오탐을 낸다
# (실측 2026-08-20: 소득세법·조세특례제한법 — 공포본은 동일한데 시행일만
# 달라 '드리프트'로 잘못 판정). 공포일자+공포번호는 판본의 식별자라
# 표기 차이가 없다.

def lm_promulgation(name: str, key: str) -> tuple[str, str] | None:
    """프로덕션과 동일한 LM 요청을 재현해 (공포일자, 공포번호)를 얻는다.

    ⚠️ fetch_article 자체를 호출하는 것이 아니라 요청을 재현한다 — 조문
    텍스트가 아니라 판본 메타데이터가 필요해서다. 대신 프로덕션의 핵심
    가드(반환 법령명 대조)를 동일하게 적용한다: 대조 없이는 LM이 별칭·
    폐지판을 오해석해 **다른 법의 공포일**로 검증이 통과·실패할 수 있다
    (분석 P1-1과 같은 구멍이 검증 도구에 남는 것).
    """
    from app.core.legal_api import _norm_compact

    r = _http.get(LAW_SERVICE_URL, params={
        "OC": key, "target": "law", "type": "XML", "LM": name,
    }, timeout=20)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    if root.tag != "법령":
        return None
    returned = (root.findtext(".//기본정보/법령명_한글") or "").strip()
    if returned and _norm_compact(returned) != _norm_compact(name):
        print(f"    ⚠️ 법령명 오해석: {name!r} → {returned!r}")
        return None
    date = (root.findtext(".//기본정보/공포일자") or "").strip()
    no = (root.findtext(".//기본정보/공포번호") or "").strip()
    return (date, no) if date else None


def current_promulgation(name: str, key: str) -> tuple[str, str] | None:
    """법령 검색의 현행(현행연혁코드=현행) 판본의 (공포일자, 공포번호)."""
    r = _http.get(LAW_SEARCH_URL, params={
        "OC": key, "target": "law", "type": "XML", "query": name, "display": "5",
    }, timeout=20)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    for el in root.iter("law"):
        nm = (el.findtext("법령명한글") or el.findtext("법령명_한글") or "").strip()
        status = (el.findtext("현행연혁코드") or "").strip()
        if nm == name and status in ("현행", ""):
            date = (el.findtext("공포일자") or "").strip()
            no = (el.findtext("공포번호") or "").strip()
            return (date, no) if date else None
    return None


def main() -> int:
    key = os.getenv("LAW_API_KEY")
    if not key:
        print("LAW_API_KEY 미설정 — 이 검증은 법제처 API가 필요합니다.")
        return 1

    print(f"{'법령':<34} {'LM(공포일-호)':>16} {'현행(공포일-호)':>16}  판정")
    print("─" * 76)
    bad = 0
    watched = _watched_laws()
    for name in watched:
        try:
            lm = lm_promulgation(name, key)
            cur = current_promulgation(name, key)
        except Exception as e:
            bad += 1
            print(f"{name:<34} 조회 실패: {e}")
            continue
        ok = lm is not None and lm == cur
        bad += (not ok)
        fmt = lambda p: f"{p[0]}-{p[1]}" if p else "—"
        print(f"{name:<34} {fmt(lm):>16} {fmt(cur):>16}  "
              f"{'✅' if ok else '⚠️ 드리프트'}")

    print("─" * 68)
    if bad:
        print(f"❌ {bad}건 불일치 — 조회 경로가 현행판을 반환하지 않습니다.")
        return 1
    print(f"✅ {len(watched)}종 전부 현행판 반환")
    return 0


if __name__ == "__main__":
    sys.exit(main())
