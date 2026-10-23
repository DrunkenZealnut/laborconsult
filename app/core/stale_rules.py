"""폐기된 법률 기준이 담긴 검색 결과를 답변 컨텍스트에서 걸러낸다 (kin-answer-accuracy P0-3).

지식iN 실질문 검증(2026-10-02)에서 오답 4건이 같은 원인이었다 — 이미 바뀐 기준을
현행처럼 안내했다. 코퍼스를 세어 보면 LLM 기억이 아니라 **검색 결과**가 출처다:
일용직 구기준("10일 미만")은 qa에 있고 현행 기준("3분의 1")은 코퍼스 어디에도 없었다.
검색이 정상 작동해도 낡은 답만 나오는 구조라 프롬프트 문구로는 막을 수 없다.

처리는 출처에 따라 갈린다.
- qa·counsel(상담글)은 **제외**한다. "지금 이렇게 하라"는 조언 형식이라 낡으면 그대로 오답이다.
- 판례·행정해석·해설서는 남기고 `[구 기준 주의]`를 붙인다. 판례가 삭제 조문을 인용한 것은
  당시 유효한 법리라, 지우면 근거가 통째로 사라진다.

패턴은 **공기어 창**을 필수로 한다. "다음 주 근무 예정"은 교대제 상담에도 나오고
"10일 미만"은 연차 상담에도 나온다. 오억제(유효 근거 소실)가 미억제보다 비싸다.

`python3 -m app.core.stale_rules --scan` — BM25 코퍼스 전량에 적용해 규칙별·출처별 일치
건수와 표본을 출력한다. 패턴을 바꾸면 반드시 다시 돌려 표본을 눈으로 확인할 것.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# 제외 대상 출처 — rag.COUNSEL_SOURCES와 같은 집합이다(순환 import를 피하려고 지연 참조).
_EXCLUDE_SOURCES = frozenset({"qa", "counsel"})


@dataclass(frozen=True)
class StaleRule:
    id: str
    pattern: re.Pattern
    changed: str        # 변경 시행일 (YYYY-MM-DD)
    replacement: str    # 주석에 쓰는 현행 기준 한 줄
    # 현행 기준·변경 사실을 함께 언급하는 표지. 일치하면 상담글이라도 **제외하지 않고
    # 주석만** 단다 — 실측: "최근 행정해석(1736)에 따르면 다음 주 예정이 없어도 발생"처럼
    # 변경을 올바르게 설명한 상담글이 구 기준 문구를 인용한다는 이유로 지워지고 있었다.
    current: re.Pattern | None = None


STALE_RULES: tuple[StaleRule, ...] = (
    # 고용보험법 제40조①5호 개정(2019-08-27 공포, 2019-10-01 시행) 전 기준.
    StaleRule(
        "daily_10days",
        re.compile(r"일용.{0,60}10\s*일\s*미만|10\s*일\s*미만.{0,60}일용"),
        "2019-10-01",
        "일용근로자 구직급여 요건은 수급자격 인정신청일이 속한 달의 직전 달 초일부터 "
        "신청일까지 근로일수 합이 같은 기간 총일수의 3분의 1 미만",
        re.compile(r"3\s*분의\s*1|1\s*/\s*3|직전\s*달\s*초일"),
    ),
    # 고용노동부 행정해석 변경(2021-08-04, 임금근로시간과-1736).
    StaleRule(
        "weekly_next_week",
        # 세 번째 묶음을 "해야"류로 넓히지 말 것 — "다음주 소정근로일 중 1일을 쉬게 하여
        # 보상해야"(휴일대체 상담)가 걸렸다(실측 ctx_qa_2012090_c2).
        re.compile(r"주휴.{0,80}(다음\s*주|익주|그\s*다음\s*주|다음주)\S{0,3}\s?.{0,25}"
                   r"((근로|근무)\S{0,3}\s?.{0,10}(예정|계속)|출근\S{0,2}\s?(하여야|해야))"),
        "2021-08-04",
        "주휴수당은 해당 1주 근로관계가 존속하고 소정근로일을 개근하면 발생하며, "
        "다음 주 근무 예정은 요건이 아님",
        re.compile(r"1736|2021\.?\s*8\.?\s*4|(예정|계속)\S{0,4}\s*(있지|되지)\s*않(아|더라)도"
                   r"|변경된?\s*(행정)?\s*해석|기존\s*해석|구\s*해석"),
    ),
    # 근로기준법 제35조(해고예고 적용 예외) 삭제(2019-01-15, 헌재 2015헌바327 후속).
    StaleRule(
        "lsa_35",
        # "근로기준법 제26조·제35조"처럼 조문을 나열한 표기가 있다(실측 지식iN 17번 답변).
        re.compile(r"근로기준법[^.\n]{0,20}?제\s*35\s*조"),
        "2019-01-15",
        "해고예고 적용 예외(계속근로 3개월 미만 등)는 근로기준법 제26조 단서",
        re.compile(r"제\s*26\s*조\s*단서|구\s*근로기준법\s*제\s*35|삭제|위헌"),
    ),
    # 2025-01-01 지급기간부터. 고용보험법 시행령 제95조 및 제35100호 부칙.
    # https://moel.go.kr/policy/policydata/view.do?bbs_seq=20250100172
    StaleRule(
        "parental_old_cap",
        re.compile(r"육아휴직.{0,80}(상한.{0,15}150\s*만|사후지급.{0,25}25\s*[%％])"),
        "2025-01-01",
        "육아휴직 급여는 지급기간과 월차에 따른 현행 상한 및 특례를 확인하고, 2025년 이후 기간의 사후지급금 폐지를 구분",
        re.compile(r"250\s*만|200\s*만|160\s*만|사후지급.{0,20}(폐지|없)|종전|구\s*기준"),
    ),
    # 근로기준법 제37조 제1항 제2호, 법률 제20520호 부칙의 지급사유 적용례.
    # https://1350.moel.go.kr/rtmview.do?id=1000309035
    StaleRule(
        "arrears_in_service_old",
        re.compile(r"재직.{0,45}(체불|미지급).{0,45}(연\s*)?6\s*[%％]"),
        "2025-10-23",
        "재직 중 정기 임금은 2025-10-23 이후 지연이자 지급사유부터 근로기준법상 연 20% 적용 여부를 확인",
        re.compile(r"재직(?:(?!퇴직).){0,60}20\s*[%％]|종전|구\s*기준|2025[.년/-]\s*10[.월/-]\s*23"),
    ),
    # 근로기준법 제60조 제3항 삭제(법률 제15108호, 시행 2018-05-29).
    # https://www.law.go.kr/LSW/nwRvsLsInfoR.do?lsiSeq=199151
    StaleRule(
        "annual_old_deduction",
        re.compile(r"근로기준법.{0,15}제?\s*60\s*조\s*제?\s*3\s*항.{0,100}(차감|공제)"),
        "2018-05-29",
        "1년 미만 사용 연차를 다음해 발생 연차에서 공제하던 제60조 제3항은 삭제됨",
        re.compile(r"삭제|폐지|(차감|공제).{0,10}(않|아니|없|말)|종전|구\s*기준"),
    ),

)


def _enabled() -> bool:
    return os.getenv("STALE_FILTER", "on").strip().lower() != "off"


def match_rules(text: str) -> list[StaleRule]:
    if not text:
        return []
    return [r for r in STALE_RULES if r.pattern.search(text)]


def _mentions_current(text: str, rules: list[StaleRule]) -> bool:
    return any(r.current is not None and r.current.search(text) for r in rules)


def _annotate(hit: dict, rules: list[StaleRule]) -> dict:
    note = "\n".join(f"[구 기준 주의 — {r.changed} 이후 변경: {r.replacement}]" for r in rules)
    out = dict(hit)  # 원본 hit은 다른 경로가 참조한다 — 제자리 변경 금지
    out["content"] = f"{note}\n{hit.get('content', '')}"
    out["stale_rules"] = [r.id for r in rules]
    return out


def _event_window(query: str, reference_date: str | None) -> tuple[str | None, str | None]:
    years = [int(y) for y in re.findall(r"(?<!\d)((?:19|20)\d{2})(?=\s*(?:년|[./-]\d))", query)]
    if years:
        return f"{min(years)}-01-01", f"{max(years)}-12-31"
    if re.search(r"예전|과거|당시", query):
        return None, None
    try:
        current = date.fromisoformat(reference_date) if reference_date else datetime.now(ZoneInfo("Asia/Seoul")).date()
    except ValueError:
        return None, None
    return current.isoformat(), current.isoformat()


def filter_stale_hits(hits: list[dict], *, query: str = "",
                      reference_date: str | None = None) -> tuple[list[dict], list[str]]:
    """(처리된 hits, 적용된 규칙 id 목록). 순서는 보존한다.

    상담글 일치는 제외, 그 외 일치는 주석. 제외 후 남는 것이 없으면 제외를 취소하고
    주석으로 되돌린다 — 근거가 0이면 LLM이 기억으로 답하는데, 그것이 더 나쁘다.
    """
    if not hits or not _enabled():
        return hits, []

    try:
        window_start, window_end = _event_window(query, reference_date)
        matched = [(h, match_rules(h.get("content", ""))) for h in hits]
        if not any(rules for _, rules in matched):
            return hits, []

        kept, dropped, annotated = [], 0, 0
        for h, rules in matched:
            if not rules:
                kept.append(h)
            elif window_end and all(window_end < r.changed for r in rules):
                kept.append(h)  # All matched rules were valid before their amendments.
            elif not window_start or any(window_start < r.changed for r in rules):
                kept.append(_annotate(h, rules))  # Mixed/unknown period: keep with boundary notes.
                annotated += 1
            elif (h.get("source_type") in _EXCLUDE_SOURCES
                  and not _mentions_current(h.get("content", ""), rules)):
                dropped += 1
            else:
                kept.append(_annotate(h, rules))
                annotated += 1

        if not kept:
            kept = [_annotate(h, rules) if rules else h for h, rules in matched]
            annotated, dropped = sum(1 for _, r in matched if r), 0

        ids = sorted({r.id for _, rules in matched for r in rules})
        logger.info("폐기 기준 필터: 제외 %d · 주석 %d (%s)", dropped, annotated, ",".join(ids))
        return kept, ids
    except Exception as e:  # 필터 실패가 답변을 막지 않는다
        logger.warning("폐기 기준 필터 실패 (원본 유지): %s", e)
        return hits, []


def _scan(path: str = "data/bm25_corpus.jsonl.gz", samples: int = 5,
          output: str | None = None) -> None:
    import gzip
    import json
    from collections import Counter, defaultdict
    from contextlib import ExitStack

    counts: dict[str, Counter] = defaultdict(Counter)
    shown: dict[str, list[str]] = defaultdict(list)
    with ExitStack() as stack:
        f = stack.enter_context(gzip.open(path, "rt", encoding="utf-8"))
        export = stack.enter_context(open(output, "w", encoding="utf-8")) if output else None
        for line in f:
            d = json.loads(line)
            text = d.get("text", "")
            rules = match_rules(text)
            for r in rules:
                st = d.get("source_type", "?")
                if st in _EXCLUDE_SOURCES and not _mentions_current(text, [r]):
                    st += "(제외)"
                counts[r.id][st] += 1
                if export:
                    export.write(json.dumps({"id": d["id"], "rule": r.id,
                        "action": "exclude" if st.endswith("(제외)") else "annotate",
                        "source_type": d.get("source_type"), "text": text}, ensure_ascii=False)+"\n")
                if len(shown[r.id]) < samples:
                    m = r.pattern.search(text)
                    s = max(0, m.start() - 40)
                    shown[r.id].append(f"  [{st}] {d['id'][:40]}: …{text[s:m.end() + 40]!r}…")
    for r in STALE_RULES:
        c = counts[r.id]
        print(f"\n{r.id}  합계 {sum(c.values())}  {dict(c)}  ((제외) 표시 외는 주석)")
        print("\n".join(shown[r.id]) or "  (일치 없음)")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan", action="store_true")
    parser.add_argument("--path", default="data/bm25_corpus.jsonl.gz")
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--output", help="Export every match as private JSONL, independent of sample count")
    args = parser.parse_args()
    if args.scan:
        _scan(args.path, args.samples, args.output)
    else:
        parser.print_help()
