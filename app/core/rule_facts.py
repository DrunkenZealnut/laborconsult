"""현행 법률 규칙(요건·기간·조문)의 결정적 사실 블록 (kin-answer-accuracy P0-2).

`pipeline._KNOWLEDGE_MODULES`(최저임금 금액·4대보험 요율)와 **별도 목록**이다.
그 목록은 `LEGAL_RULES_ENABLED=true`에서 통째로 꺼지는데(승인 저장소가 수치 11키를
대체하므로), 여기 있는 것은 **비수치 규칙**이라 대체 경로가 없다. 같은 목록에 두면
관리 모드를 켜는 순간 조용히 사라진다(Design D1).

지식iN 실질문 검증(2026-10-02)의 오답이 출발점이다 — 조기재취업수당에 7일 대기기간을
적용(12번), 일용직 구기준(3·18번), 주휴 '다음 주 근무 예정'(1번), 삭제된 근기법 제35조
(17번), 수습 80% 지급을 적법 가능으로 요약(8번). 이 영역에는 계산기도 사실 블록도 없어
LLM이 기억과 낡은 상담글로 답하고 있었다.

**문구는 손으로 쓴 것이다.** 근거 대조는 두 갈래다.
- `anchors`(조문): `test_kin_accuracy.py` K6이 `output_공식법령/`의 공식 원문(eflaw 현행판)에
  그 구절이 있는지 대조한다(파일 없으면 skip — 로컬 관문).
- `prec_anchors`(판례): `data/graph_precedents.json`(법제처 판시사항·판결요지, 커밋)에서 해석한다
  — **CI에서 실검증**된다(`test_effective_law.py` E11). 조문 앵커와 필드를 나눈 이유는 K6의
  문서 등록 검사(`fetch_official_rules.ARTICLES`)가 판례 id를 모르기 때문이다.
블록이 제시한 판례는 인용 화이트리스트에도 들어간다(`prec_anchor_hits` — effective-law D10).
그러지 않으면 블록이 "따르라"고 준 판례를 LLM이 인용하는 순간 환각으로 판정돼 지워진다.
법이 바뀌면 `as_of`와 함께 갱신할 것.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# 2차 재평가 3·7·18번은 실업급여+피보험자격 확인, 17번은 실업급여+해고예고가 동시에 필요했다.
# 3을 넘기면 무관 블록이 섞이는 잡음이 커진다. 블록은 약 200~1,200자이고 실업급여가 가장 길어
# 3개면 최대 약 2,400자다(2026-10-05 실측 — 확인청구 역할 구분 줄이 들어가며 늘었다).
MAX_BLOCKS = 3

_HEADER = ("[현행 기준 — 아래 요건·기간·조문은 반드시 이 내용을 따르세요. "
           "학습 지식이나 참고 자료의 상담글이 다르면 이 내용이 우선합니다]")

_PRECEDENT_RECORDS = Path(__file__).resolve().parent.parent.parent / "data" / "graph_precedents.json"


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
    # (사건번호, 구절) — data/graph_precedents.json의 판시사항·판결요지에서 공백 무시 부분일치.
    prec_anchors: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def build(self, query: str, analysis) -> str | None:
        if not self.detect(query, analysis):
            return None
        body = "\n".join(f"- {line}" for line in self.lines)
        return f"{_HEADER}\n{body}\n(기준일 {self.as_of}, 근거: {self.sources})"


_UNEMPLOYMENT_WORDS = ("실업급여", "구직급여", "조기재취업", "실업인정", "수급자격", "일용직", "일용근로")
# "피보험자격"만 단독으로 감지한다. 나머지는 일반 표현이라 **고용보험 맥락**이 함께 있을 때만 —
# "휴업 신고 안 했다"·"근로자지위확인 청구"(지위확인 소송)·"노조 미가입"에 붙으면 안 된다
# (CodeRabbit PR #98).
_INSURED_STATUS_SPECIFIC = ("피보험자격",)
_INSURED_STATUS_WORDS = ("미가입", "미신고", "확인청구", "확인 청구",
                         "가입 안", "가입이 안", "가입안", "신고 안", "신고를 안", "신고가 안")
_INSURANCE_CONTEXT = ("고용보험", "4대보험", "4대 보험", "사대보험", "실업급여", "구직급여", "피보험")
# "3.3" 부분문자열은 "13.3"·"주 23.3시간"에도 걸린다 — 원천징수 표현(3.3%·3.3프로)만.
_WITHHOLDING_33_RE = re.compile(r"(?<![\d.])3\.3\s*(%|％|프로|퍼센트|퍼)")
_DISMISSAL_WORDS = ("해고예고", "해고 예고", "예고수당", "30일 전", "30일전")
# "해고" 단독은 부당해고·징계 상담 전반에 걸린다 — 단기 근속 단서가 함께 있을 때만 해고예고
# 블록을 붙인다(3개월 미만 예외가 쟁점이 되는 경우). 날짜("7월 27일")의 '일'은 단서가 아니다.
_SHORT_TENURE_RE = re.compile(
    r"\d+\s*(주|개월|달)\s*(만에|정도|동안|근무|일하|다니|째|밖에|만)"
    r"|\d+\s*일\s*(만에|동안|근무|일하|밖에|째)"
    r"|수습|며칠|이틀|사흘|입사\s*(직후|하자마자)")
_WEEKLY_WORDS = ("주휴",)
_PROBATION_WORDS = ("수습",)
_HARASSMENT_WORDS = ("괴롭힘",)
_MINWAGE_WORDS = ("최저임금", "최저시급", "최저 임금")


def _dismissal_detect(q: str, a) -> bool:
    if _has(q, _DISMISSAL_WORDS):
        return True
    if "해고" not in q:
        return False
    return _topic(a) == "해고·징계" or bool(_SHORT_TENURE_RE.search(q))


# 순서 = 상한(MAX_BLOCKS)을 넘칠 때의 우선순위. 실측 오류 클래스가 무거운 것부터.
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
            # 일반 요건은 '12개월 이상 계속하여 고용된 경우'(실제 고용)이고, '고용될 것으로 인정'은 65세 이상
            # 6개월 특례에만 붙는다(시행령 제84조①1호, 2024년 판부터 같은 문구). 처음 문안이 둘을 섞어 "12개월 이상
            # 계속 고용될 것으로 인정"이라고 적었고, 앵커가 그 구절을 덮지 않아 원문 대조를 통과했다(외부 점검
            # 2026-10-07 10번). 수량마다 앵커를 단다(test_claim_assessor_facts C18).
            "조기재취업 수당: 실업 신고일부터 14일이 지난 후 재취업하고, 재취업 전날 기준 소정급여일수를 "
            "2분의 1 이상 남긴 경우로서 다음에 해당하면 지급한다(제64조, 시행령 제84조 제1항). "
            "고용(제1호): 12개월 이상 계속하여 고용된 경우 — 앞으로 12개월 고용될 예정이라는 것만으로는 충족되지 "
            "않는다. 이직일 당시 65세 이상인 사람(65세 전부터 피보험자격을 유지한 경우)만 6개월 이상 계속하여 "
            "고용될 것으로 직업안정기관의 장이 인정하면 된다. 다만 최후 이직 사업주 등에게 재고용된 경우, 실업 신고일 "
            "이전에 채용을 약속한 사업주에게 고용된 경우, 공무원으로 채용된 경우(가입대상 공무원은 제외), "
            "고용노동부장관이 고시하는 임금액 이상을 받는 경우, 승선근무예비역·전문연구요원·산업기능요원으로 복무하는 "
            "경우는 제외된다(제1호 단서). 자영업(제2호): 12개월 이상 계속하여 사업을 영위한 경우다. 이직일 당시 "
            "65세 이상인 사람(위와 같은 조건)은 6개월 이상 계속하여 사업을 영위할 것으로 직업안정기관의 장이 인정하면 "
            "된다. "
            "14일 기준은 대기기간 7일과 다르므로 섞지 않는다. 입사일을 조정하라는 식의 날짜 조언은 하지 말고, "
            "충족 여부는 고용센터에서 확정하도록 안내한다.",
            "마지막 이직 당시 일용근로자로서 피보험 단위기간이 1개월 미만인 사람이 수급자격을 갖추지 못한 "
            "경우에만, 일용근로자가 아닌 근로자로서 마지막으로 이직한 사업을 기준으로 수급자격을 결정한다"
            "(제43조 제3항 단서). 이 조건 없이 이전 사업 기준으로 바뀐다고 안내하지 않는다.",
            "이직확인서: 근로자가 이직확인서 발급요청서를 사업주에게 내면 사업주는 받은 날부터 10일 이내에 "
            "발급해야 한다(같은 법 시행규칙 제82조의2 제2항).",
            # 역할 구분 — 3차 재평가 7·18번이 피보험자격 정정 창구를 고용센터로 안내하거나 빠뜨렸다.
            # 사실은 insured_status와 같은 원문이지만 그 블록은 20문항 중 1개에만 붙는다
            # (claim-authority-and-assessor-facts D1).
            "이직사유나 피보험자격이 사실과 다르게 신고됐다면 담당이 다르다. 이직사유가 수급자격 제한 사유에 "
            "해당하는지는 직업안정기관(고용센터)이 인정하고(고용보험법 제58조), 수급자격 인정 여부도 "
            "직업안정기관이 결정한다(같은 법 제43조 제2항). 피보험자격 취득·상실 신고 자체는 근로복지공단에 "
            "확인을 청구해 바로잡으며, 확인청구는 언제든지 할 수 있다(같은 법 제17조 제1항, 확인 업무 위탁 — "
            "같은 법 시행령 제145조 제2항).",
        ),
        sources="고용보험법 제17조·제40조·제43조·제49조·제58조·제64조, 같은 법 시행령 제84조·제145조, "
                "시행규칙 제82조의2",
        as_of="2026-10-07",
        anchors=(
            ("ei_act_40", "총 일수의 3분의 1 미만일 것"),
            ("ei_act_40", "14일간 연속하여 근로내역이 없을 것"),
            ("ei_act_49", "7일간은 대기기간"),
            ("ei_enf_84", "실업의 신고일부터 14일이 지난 후 재취업한"),
            ("ei_enf_84", "2분의 1 이상 남기고"),
            ("ei_enf_84", "12개월 이상 계속하여 고용된 경우이거나"),
            ("ei_enf_84", "12개월 이상 계속하여 사업을 영위한 경우"),
            ("ei_enf_84", "65세 전부터 65세가 될 때까지 피보험자격을 유지한 사람만 해당한다"),
            ("ei_enf_84", "6개월 이상 계속하여 고용될 것으로"),
            ("ei_enf_84", "6개월 이상 계속하여 사업을 영위할 것으로"),
            # 제외 사유는 제1호(고용) 단서다 — 제2호(사업 영위)에는 붙지 않는다(CodeRabbit PR #105)
            ("ei_enf_84", "다만, 수급자격자가 다음 각 목의 어느 하나에 해당하는 경우는 제외한다"),
            ("ei_enf_84", "최후에 이직한 사업의 사업주나 그와 관련된 사업주로서 고용노동부령으로 정하는 사업주에게 "
                          "재고용된 경우"),
            ("ei_enf_84", "실업의 신고일 이전에 채용을 약속한 사업주"),
            ("ei_enf_84", "공무원으로 채용된 경우. 다만, 가입대상 공무원으로 채용된 경우는 제외한다"),
            ("ei_enf_84", "고용노동부장관이 정하여 고시하는 임금액 이상을 받는 경우"),
            ("ei_enf_84", "승선근무예비역, 전문연구요원 또는 산업기능요원으로 근무 또는 복무하는 경우"),
            ("ei_act_43", "피보험 단위기간이 1개월 미만인 사람이 수급자격을 갖추지 못한 경우"),
            ("ei_rule_82_2", "제출받은 날부터 10일 이내에"),
            ("ei_act_58", "해당한다고 직업안정기관의 장이 인정하는 경우에는 수급자격이 없는 것으로 본다"),
            ("ei_act_43", "그 신청인에 대한 수급자격의 인정 여부를 결정"),
            ("ei_act_17", "언제든지 고용노동부장관에게 피보험자격의 취득 또는 상실에 관한 확인을 청구할 수 있다"),
            ("ei_enf_145", "제17조(법 제77조의5제1항 및 제77조의10제1항에서 준용하는 경우를 포함한다)에 따른 "
                           "피보험자격의 확인"),
            ("ei_enf_145", "권한을 근로복지공단에 위탁한다"),
        ),
    ),
    RuleFact(
        name="insured_status",
        detect=lambda q, a: _has(q, _INSURED_STATUS_SPECIFIC) or (
            _has(q, _INSURANCE_CONTEXT)
            and (_has(q, _INSURED_STATUS_WORDS) or bool(_WITHHOLDING_33_RE.search(q)))),
        lines=(
            "실제로 근로자로 일했다면 고용보험 미신고·미가입 기간도 피보험자격의 취득 확인을 청구해 "
            "인정받을 수 있다. 확인청구는 언제든지 할 수 있다(고용보험법 제17조 제1항) — 다른 제도의 "
            "기간 제한(보험료 징수 등)을 섞어 '최대 3년' 같은 청구 기한으로 일반화하지 않는다.",
            "피보험자격 확인 업무는 근로복지공단에 위탁돼 있다(같은 법 시행령 제145조 제2항). "
            "구직급여 수급자격 인정 여부는 고용센터(직업안정기관)가 결정한다(제43조 제2항) — "
            "두 기관의 역할을 섞어 안내하지 않는다.",
            # 금지 문장만 두면 빈자리를 추측이 채운다 — "3년"이라는 숫자가 실제로 있는 조항을 정확히 적는다(D4).
            "신고가 안 됐던 기간도 피보험기간에 들어가지만, 취득신고일 또는 확인일부터 소급하여 3년이 되는 날이 "
            "속하는 보험연도의 첫날보다 앞선 기간은 원칙적으로 계산하지 않는다. 사업주가 그 전부터 고용보험료를 "
            "계속 낸 사실이 증명되면 낸 기간으로 계산한다(고용보험법 제50조 제5항). 이것은 피보험기간 계산 "
            "규정이지 확인청구의 기한이 아니다.",
        ),
        sources="고용보험법 제17조·제43조·제50조, 같은 법 시행령 제145조",
        as_of="2026-10-05",
        anchors=(
            ("ei_act_17", "언제든지 고용노동부장관에게 피보험자격의 취득 또는 상실에 관한 확인을 청구할 수 있다"),
            ("ei_enf_145", "권한을 근로복지공단에 위탁한다"),
            ("ei_enf_145", "에 따른 피보험자격의 확인"),
            ("ei_act_43", "그 신청인에 대한 수급자격의 인정 여부를 결정"),
            ("ei_act_50", "소급하여 3년이 되는 날이 속하는 보험연도의 첫 날에 그 피보험자격을 취득한 것으로 보아"),
            ("ei_act_50", "사업주가 다음 각 호의 어느 하나에 해당하는 날부터 소급하여 3년이 되는 해의 1월 1일 "
                          "전부터 해당 피보험자에 대한 고용보험료를 계속 납부한 사실이 증명된 경우"),
        ),
    ),
    RuleFact(
        name="harassment_retaliation",
        detect=lambda q, a: _topic(a) == "직장내괴롭힘" or _has(q, _HARASSMENT_WORDS),
        lines=(
            "사용자는 직장 내 괴롭힘 발생 사실을 신고한 근로자와 피해근로자등에게 해고나 그 밖의 "
            "불리한 처우를 해서는 안 된다(근로기준법 제76조의3 제6항). 위반하면 3년 이하의 징역 또는 "
            "3천만원 이하의 벌금이다(제109조 제1항).",
            # 시제 중립 — "…부터 삭제된다"는 10-08 이후 거짓이 되고 그 문장에는 앵커도 없다(gap 위험 2).
            "제109조 제2항(다른 조항 위반에 대한 반의사불벌 규정 — 2026. 4. 7. 개정, 2026. 10. 8. 시행 시 삭제)은 "
            "이 벌칙의 근거가 아니다. 불리한 처우의 벌칙은 제1항으로 인용한다.",
            "상시 4명 이하 사업장에는 근로기준법의 직장 내 괴롭힘 규정(제76조의2·제76조의3)과 그 벌칙·과태료가 "
            "적용되지 않는다(시행령 제7조 별표 1에 해당 장이 없다) — 사업장 규모를 먼저 확인하고 안내한다. "
            "다른 법률(예: 남녀고용평등법의 직장 내 성희롱 규정)의 적용 여부는 이 문장과 별개다.",
        ),
        sources="근로기준법 제76조의3·제109조, 같은 법 시행령 제7조 별표 1",
        as_of="2026-10-04",
        anchors=(("lsa_act_76_3", "신고한 근로자 및 피해근로자등에게 해고나 그 밖의 불리한 처우를 하여서는 아니 된다"),
                 # 제1항 문구 중 개정 전후(2026-10-08 시행) 공통 부분만 앵커로 둔다. ②의 삭제 여부는
                 # 기준일에 따라 달라 앵커가 될 수 없다 — 법제처 target=law 는 시행 예정 개정을
                 # 이미 반영한 본문을 돌려줘 "삭제"를 현행으로 오인했다(2차 외부 재평가 9번 지적).
                 ("lsa_act_109", "제76조의3제6항을 위반한 자는 3년 이하의 징역 또는 3천만원 이하의 벌금"),
                 ("lsa_enf_7", "상시 4명 이하의 근로자를 사용하는 사업 또는 사업장에 적용하는 법 규정은 별표 1과 같다")),
    ),
    RuleFact(
        name="dismissal_notice",
        detect=_dismissal_detect,
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
            "1주 소정근로일이 5일 미만이고 근로자와 사용자가 소정근로시간만 정했다면 주휴시간은 "
            "1주 소정근로시간을 5로 나눈 값이다(대법원 2025. 8. 14. 선고 2022다291153 판결). "
            "같은 업무의 통상근로자가 있으면 그 근로시간에 비례해 정하는 것이 출발점이다(제18조 제1항) — "
            "어느 경우인지 밝히고 계산한다.",
        ),
        sources="근로기준법 제18조·제55조, 고용노동부 임금근로시간과-1736(2021. 8. 4.), "
                "대법원 2022다291153",
        as_of="2026-10-04",
        anchors=(("lsa_act_18", "4주 동안(4주 미만으로 근로하는 경우에는 그 기간)을 평균하여"),
                 ("lsa_act_18", "같은 종류의 업무에 종사하는 통상 근로자의 근로시간을 기준으로 산정한 비율")),
        prec_anchors=(("2022다291153", "1주간 소정근로시간 수를 5일로 나누는 방법으로 산정하는 것이 타당하다"),),
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


# "별표에 **없다**"는 주장은 구절 앵커로 검증할 수 없다(부재 주장). 대신 현행성 점검이 별표 본문에
# 그 표지가 나타나는지 본다 — 나타나면 블록 문장이 거짓이 된 것이다(`check_law_freshness --anchors`).
# (블록 이름, 법령명, 별표 제목에 포함될 문구, 별표 본문에 없어야 할 문구)
ANNEX_ABSENCE_CLAIMS: tuple[tuple[str, str, str, str], ...] = (
    ("harassment_retaliation", "근로기준법 시행령", "4명 이하", "제6장의2"),
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


@lru_cache(maxsize=1)
def precedent_records() -> dict:
    """그래프 판례 원문 기록(법제처). 파일이 없거나 깨졌으면 빈 dict — 판례 hit만 빠진다."""
    try:
        with open(_PRECEDENT_RECORDS, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("판례 원문 기록 로드 실패 (판례 앵커 hit 생략): %s", e)
        return {}


def prec_anchor_hits(names: list[str]) -> list[dict]:
    """감지된 블록이 제시한 판례를 **primary 인용 hit**으로(case_no 보유).

    블록이 판례를 "따르라"며 제시해도 화이트리스트에 없으면 그 인용이 환각으로 판정돼
    지워진다(effective-law D10). 원문 기록에 없는 번호는 hit을 만들지 않는다 — 존재는
    E11이 CI에서 보장한다.
    """
    records = precedent_records()
    wanted = set(names)
    hits = []
    for fact in RULE_FACTS:
        if fact.name not in wanted:
            continue
        for case_no, phrase in fact.prec_anchors:
            rec = records.get(case_no)
            if not rec:
                continue
            hits.append({
                "title": f"{rec.get('court', '')} {case_no}".strip(),
                "case_no": case_no,
                "chunk_text": phrase,
                "source_type": "precedent",
            })
    return hits
