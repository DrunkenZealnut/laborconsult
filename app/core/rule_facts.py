"""현행 법률 규칙(요건·기간·조문)의 결정적 사실 블록 (kin-answer-accuracy P0-2).

`pipeline._KNOWLEDGE_MODULES`(최저임금 금액·4대보험 요율)와 **별도 목록**이다.
그 목록은 `LEGAL_RULES_ENABLED=true`에서 통째로 꺼지는데(승인 저장소가 수치 11키를
대체하므로), 여기 있는 것은 **비수치 규칙**이라 대체 경로가 없다. 같은 목록에 두면
관리 모드를 켜는 순간 조용히 사라진다(Design D1).

지식iN 실질문 검증(2026-10-02)의 오답이 출발점이다 — 조기재취업수당에 7일 대기기간을
적용(12번), 일용직 구기준(3·18번), 주휴 '다음 주 근무 예정'(1번), 삭제된 근기법 제35조
(17번), 수습 80% 지급을 적법 가능으로 요약(8번). 이 영역에는 계산기도 사실 블록도 없어
LLM이 기억과 낡은 상담글로 답하고 있었다.

**문구는 손으로 쓴 것이다.** 각 블록의 `anchors`는 그 문장의 핵심 구절이고,
`test_kin_accuracy.py` K6이 `output_공식법령/`의 공식 원문에 그 구절이 있는지 대조한다
(파일이 없으면 skip — 로컬 관문). 법이 바뀌면 `as_of`와 함께 갱신할 것.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger(__name__)

MAX_BLOCKS = 2  # 실업급여 질문에 주휴 블록까지 붙으면 잡음이다

_HEADER = ("[현행 기준 — 아래 요건·기간·조문은 반드시 이 내용을 따르세요. "
           "학습 지식이나 참고 자료의 상담글이 다르면 이 내용이 우선합니다]")


def _types(analysis) -> set[str]:
    return set(getattr(analysis, "calculation_types", None) or []) if analysis else set()


def _topic(analysis) -> str:
    return (getattr(analysis, "consultation_topic", None) or "") if analysis else ""


def _has(query: str, words: tuple[str, ...]) -> bool:
    return any(w in query for w in words)


@dataclass(frozen=True)
class RuleFact:
    name: str
    detect: Callable[[str, object], bool]
    lines: tuple[str, ...]
    sources: str
    as_of: str
    # (doc_id, 구절) — doc_id는 fetch_official_rules.ARTICLES의 id. 공백 무시 부분일치.
    anchors: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def build(self, query: str, analysis) -> str | None:
        if not self.detect(query, analysis):
            return None
        body = "\n".join(f"- {line}" for line in self.lines)
        return f"{_HEADER}\n{body}\n(기준일 {self.as_of}, 근거: {self.sources})"


_UNEMPLOYMENT_WORDS = ("실업급여", "구직급여", "조기재취업", "실업인정", "수급자격", "일용직", "일용근로")
_DISMISSAL_WORDS = ("해고예고", "해고 예고", "예고수당", "30일 전", "30일전")
_WEEKLY_WORDS = ("주휴",)
_PROBATION_WORDS = ("수습",)
_HARASSMENT_WORDS = ("괴롭힘",)
_MINWAGE_WORDS = ("최저임금", "최저시급", "최저 임금")


RULE_FACTS: tuple[RuleFact, ...] = (
    RuleFact(
        name="unemployment",
        detect=lambda q, a: (_topic(a) == "고용보험" or "unemployment" in _types(a)
                             or _has(q, _UNEMPLOYMENT_WORDS)),
        lines=(
            "일용근로자 구직급여 요건: 수급자격 인정신청일이 속한 달의 직전 달 초일부터 신청일까지 "
            "근로일 수의 합이 같은 기간 총 일수의 3분의 1 미만이어야 한다. 건설일용근로자는 신청일 이전 "
            "14일간 연속하여 근로내역이 없는 경우에도 충족한다(고용보험법 제40조 제1항 제5호). "
            "'이전 1개월간 10일 미만'은 폐지된 구 기준이므로 쓰지 않는다.",
            "대기기간: 실업 신고일부터 계산하기 시작하여 7일간은 구직급여를 지급하지 않는다. "
            "최종 이직 당시 건설일용근로자는 대기기간 없이 신고일부터 지급한다(제49조 제1항).",
            "조기재취업 수당: 실업 신고일부터 14일이 지난 후 재취업하고, 재취업 전날 기준 소정급여일수를 "
            "2분의 1 이상 남겼으며, 12개월 이상 계속 고용(이직 당시 65세 이상은 6개월)될 것으로 인정되는 "
            "경우에 지급한다. 실업 신고일 이전에 채용을 약속한 사업주에게 고용되거나 최후 이직 사업주 등에게 "
            "재고용되면 제외된다(제64조, 시행령 제84조). 14일 기준은 대기기간 7일과 다르므로 섞지 않는다. "
            "입사일을 조정하라는 식의 날짜 조언은 하지 말고, 충족 여부는 고용센터에서 확정하도록 안내한다.",
            "마지막 이직 당시 일용근로자로서 피보험 단위기간이 1개월 미만인 사람이 수급자격을 갖추지 못한 "
            "경우에만, 일용근로자가 아닌 근로자로서 마지막으로 이직한 사업을 기준으로 수급자격을 결정한다"
            "(제43조 제3항 단서). 이 조건 없이 이전 사업 기준으로 바뀐다고 안내하지 않는다.",
        ),
        sources="고용보험법 제40조·제43조·제49조·제64조, 같은 법 시행령 제84조",
        as_of="2026-10-03",
        anchors=(
            ("ei_act_40", "총 일수의 3분의 1 미만일 것"),
            ("ei_act_40", "14일간 연속하여 근로내역이 없을 것"),
            ("ei_act_49", "7일간은 대기기간"),
            ("ei_enf_84", "실업의 신고일부터 14일이 지난 후 재취업한"),
            ("ei_enf_84", "2분의 1 이상 남기고"),
            ("ei_enf_84", "실업의 신고일 이전에 채용을 약속한 사업주"),
            ("ei_act_43", "피보험 단위기간이 1개월 미만인 사람이 수급자격을 갖추지 못한 경우"),
        ),
    ),
    RuleFact(
        name="dismissal_notice",
        detect=lambda q, a: (_has(q, _DISMISSAL_WORDS)
                             or (_topic(a) == "해고·징계" and "해고" in q)),
        lines=(
            "계속 근로한 기간이 3개월 미만인 근로자는 해고예고 의무의 예외다(근로기준법 제26조 단서 제1호).",
            "근로기준법 제35조(해고예고의 적용 예외)는 삭제된 조문이므로 근거로 인용하지 않는다.",
        ),
        sources="근로기준법 제26조",
        as_of="2026-10-03",
        anchors=(("lsa_act_26", "계속 근로한 기간이 3개월 미만인 경우"),),
    ),
    RuleFact(
        name="weekly_holiday",
        detect=lambda q, a: "weekly_holiday" in _types(a) or _has(q, _WEEKLY_WORDS),
        lines=(
            "주휴수당은 해당 1주 동안 근로관계가 존속하고 그 주의 소정근로일을 개근하면 발생한다. "
            "다음 주 근무 예정은 요건이 아니다(고용노동부 행정해석 변경, 2021. 8. 4.).",
            "1주 소정근로시간 15시간 미만 여부는 4주 동안(4주 미만 근로는 그 기간)을 평균하여 판단하고, "
            "15시간 미만이면 주휴(제55조)와 연차(제60조)가 적용되지 않는다(근로기준법 제18조 제3항).",
        ),
        sources="근로기준법 제18조·제55조, 고용노동부 임금근로시간과-1736(2021. 8. 4.)",
        as_of="2026-10-03",
        anchors=(("lsa_act_18", "4주 동안(4주 미만으로 근로하는 경우에는 그 기간)을 평균하여"),),
    ),
    RuleFact(
        name="harassment_retaliation",
        detect=lambda q, a: _topic(a) == "직장내괴롭힘" or _has(q, _HARASSMENT_WORDS),
        lines=(
            "사용자는 직장 내 괴롭힘 발생 사실을 신고한 근로자와 피해근로자등에게 해고나 그 밖의 "
            "불리한 처우를 해서는 안 된다(근로기준법 제76조의3 제6항). 위반하면 3년 이하의 징역 또는 "
            "3천만원 이하의 벌금이다(제109조 제1항).",
            "제109조 제2항은 이 벌칙의 근거가 아니다 — 다른 조항(임금 지급 등) 위반에 대한 반의사불벌 "
            "규정이며, 2026. 4. 7. 개정으로 2026. 10. 8.부터 삭제된다. 불리한 처우의 벌칙은 제1항으로 인용한다.",
        ),
        sources="근로기준법 제76조의3·제109조",
        as_of="2026-10-04",
        anchors=(("lsa_act_76_3", "신고한 근로자 및 피해근로자등에게 해고나 그 밖의 불리한 처우를 하여서는 아니 된다"),
                 # 제1항 문구 중 개정 전후(2026-10-08 시행) 공통 부분만 앵커로 둔다. ②의 삭제 여부는
                 # 기준일에 따라 달라 앵커가 될 수 없다 — 법제처 target=law 는 시행 예정 개정을
                 # 이미 반영한 본문을 돌려줘 "삭제"를 현행으로 오인했다(2차 외부 재평가 9번 지적).
                 ("lsa_act_109", "제76조의3제6항을 위반한 자는 3년 이하의 징역 또는 3천만원 이하의 벌금")),
    ),
    RuleFact(
        name="probation_wage",
        detect=lambda q, a: _has(q, _PROBATION_WORDS) and (
            "minimum_wage" in _types(a) or _has(q, _MINWAGE_WORDS)),
        lines=(
            "수습 감액은 1년 이상의 기간을 정한 근로계약 + 수습을 시작한 날부터 3개월 이내 + 고용노동부장관이 "
            "고시한 단순노무업무 직종이 아닐 때만 가능하고, 그때도 시간급 최저임금액에서 100분의 10을 뺀 "
            "금액(90%)까지다(최저임금법 제5조 제2항, 시행령 제3조).",
            "최저임금의 80%만 지급하는 것은 위 요건을 모두 충족해도 최저임금 위반이다 — 요약·표·결론 "
            "어디에서도 '적법할 수 있다'고 쓰지 않는다.",
        ),
        sources="최저임금법 제5조, 같은 법 시행령 제3조",
        as_of="2026-10-03",
        anchors=(("mw_act_5", "1년 이상의 기간을 정하여 근로계약을 체결하고 수습 중에 있는 근로자"),
                 ("mw_act_5", "수습을 시작한 날부터 3개월 이내"),
                 ("mw_act_5", "단순노무업무"),
                 ("mw_enf_3", "100분의 10을 뺀 금액")),
    ),
)


def build_rule_facts(query: str, analysis) -> list[tuple[str, str]]:
    """감지된 블록 (name, text)를 최대 MAX_BLOCKS개, RULE_FACTS 순서로 반환한다."""
    out: list[tuple[str, str]] = []
    for fact in RULE_FACTS:
        if len(out) >= MAX_BLOCKS:
            break
        # 블록마다 격리한다 — 한 블록의 감지 오류가 나머지 블록까지 빼면 안 된다.
        try:
            block = fact.build(query or "", analysis)
        except Exception as e:
            logger.warning("현행 규칙 블록 %s 실패 (무시): %s", fact.name, e)
            continue
        if block:
            out.append((fact.name, block))
    return out
