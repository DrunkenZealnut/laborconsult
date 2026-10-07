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

from harassment_assessor.grounding import is_sexual_harassment

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


# 뇌혈관·심장 질병 + 산재 문맥(law-article-coverage D11). '근무'·'일하' 같은 넓은 문맥은 실업급여·병가·퇴직
# 질문에 붙었다(코퍼스 표본). '장기요양급여'는 산재 요양급여가 아니다.
_CARDIO_RE = re.compile(r"뇌\s*(출혈|경색|졸중|혈관\s*(질환|질병))|지주막하|심근\s*경색|협심증"
                        r"|심장\s*(마비|질환|질병|돌연사)|급성\s*심장|대동맥\s*(박리|류)|돌연사|과로사")
_IACI_CONTEXT_RE = re.compile(r"산재|산업\s*재해|업무상\s*(재해|질병)|(?<!장기)요양\s*(급여|신청)|근로복지공단|과로")


def _cardio_detect(q: str, a) -> bool:
    return bool(_CARDIO_RE.search(q)) and (bool(_IACI_CONTEXT_RE.search(q)) or _topic(a) == "산재보상")


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
            "조기재취업 수당: 실업 신고일부터 14일이 지난 후 재취업하고, 재취업 전날 기준 소정급여일수를 "
            "2분의 1 이상 남겼으며, 12개월 이상 계속 고용(이직 당시 65세 이상은 6개월)될 것으로 인정되는 "
            "경우에 지급한다. 실업 신고일 이전에 채용을 약속한 사업주에게 고용되거나 최후 이직 사업주 등에게 "
            "재고용되면 제외된다(제64조, 시행령 제84조). 14일 기준은 대기기간 7일과 다르므로 섞지 않는다. "
            "입사일을 조정하라는 식의 날짜 조언은 하지 말고, 충족 여부는 고용센터에서 확정하도록 안내한다.",
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
        as_of="2026-10-05",
        anchors=(
            ("ei_act_40", "총 일수의 3분의 1 미만일 것"),
            ("ei_act_40", "14일간 연속하여 근로내역이 없을 것"),
            ("ei_act_49", "7일간은 대기기간"),
            ("ei_enf_84", "실업의 신고일부터 14일이 지난 후 재취업한"),
            ("ei_enf_84", "2분의 1 이상 남기고"),
            ("ei_enf_84", "실업의 신고일 이전에 채용을 약속한 사업주"),
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
        # 성희롱만 묻는 질문은 주제 enum에 성희롱이 없어 "직장내괴롭힘"으로 분류된다 — 그때 이 블록의
        # "사업장 규모를 먼저 확인" 문장이 붙으면 규모와 무관한 남녀고용평등법 사안에 5인 조건을 다는
        # 오답이 된다(topic30 4번, law-article-coverage D16). 본문에 '괴롭힘'이 있으면 그대로 붙는다.
        detect=lambda q, a: _has(q, _HARASSMENT_WORDS) or (
            _topic(a) == "직장내괴롭힘" and not is_sexual_harassment(q)),
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
        name="occupational_cardio",
        detect=_cardio_detect,
        lines=(
            "뇌혈관·심장 질병의 업무관련성은 고용노동부고시 제2026-14호로 판단한다. 만성 과로: 발병 전 12주 동안 "
            "업무시간이 1주 평균 60시간(발병 전 4주 동안 1주 평균 64시간)을 초과하면 관련성이 강하다. 52시간을 "
            "초과하면 길어질수록 관련성이 증가하고, 업무부담 가중요인(근무일정 예측이 어려운 업무·교대제·휴일 부족·"
            "유해 작업환경(한랭·온도변화·소음)·높은 육체적 강도·시차가 큰 잦은 출장·정신적 긴장)이 있으면 관련성이 "
            "강하다. 52시간을 넘지 않아도 가중요인에 복합적으로 노출되면 관련성이 증가한다.",
            "오후 10시부터 다음 날 6시까지의 야간근무는 주간근무의 30%를 가산(휴게시간 제외)해 업무시간을 산출한다. "
            "근로기준법 제63조 제3호의 감시·단속적 근로로 승인받은 경우와 이와 유사한 업무는 제외한다.",
            "단기 과로: 발병 전 1주일 이내 업무의 양이나 시간이 이전 12주(발병 전 1주일 제외)의 1주 평균보다 "
            "30퍼센트 이상 늘었거나, 업무 강도·책임·환경이 적응하기 어려운 정도로 바뀐 경우다.",
            "급성: 증상 발생 전 24시간 이내에 업무와 관련된 돌발적이고 예측 곤란한 사건의 발생과 급격한 업무 환경의 "
            "변화가 있고, 그로 인해 뇌혈관·심장혈관의 병변 등이 자연경과를 넘어 급격하고 뚜렷하게 악화된 경우다.",
            "보험급여를 받을 권리는 3년간 행사하지 않으면 시효로 소멸하고, 장해급여·유족급여·장례비·진폐보상연금·"
            "진폐유족연금은 5년이다(산업재해보상보험법 제112조 제1항). 오래된 사건이면 시효부터 확인하고, 발병 전 "
            "4주·12주 근무표와 출퇴근 기록을 확보하도록 안내한다.",
        ),
        sources="고용노동부고시 제2026-14호(뇌혈관 질병 또는 심장 질병 및 근골격계 질병의 업무상 질병 인정 여부 "
                "결정에 필요한 사항), 산업재해보상보험법 제112조",
        as_of="2026-10-07",
        anchors=(
            ("cardio_notice", "발병 전 12주 동안 업무시간이 1주 평균 60시간(발병 전 4주 동안 1주 평균 64시간)을 "
                              "초과하는 경우에는 업무와 질병과의 관련성이 강하다고 평가한다"),
            ("cardio_notice", "1주 평균 업무시간이 52시간을 초과하는 경우에는 업무시간이 길어질수록 업무와 질병과의 "
                              "관련성이 증가하는 것으로 평가한다"),
            ("cardio_notice", "① 근무일정 예측이 어려운 업무 ② 교대제 업무 ③ 휴일이 부족한 업무 ④ 유해한 작업환경 "
                              "(한랭, 온도변화, 소음)에 노출되는 업무 ⑤ 육체적 강도가 높은 업무 ⑥ 시차가 큰 출장이 "
                              "잦은 업무 ⑦ 정신적 긴장이 큰 업무"),
            ("cardio_notice", "업무부담 가중요인에 복합적으로 노출되는 업무의 경우에는 업무와 질병과의 관련성이 증가한다"),
            ("cardio_notice", "주간근무의 30%를 가산(휴게시간은 제외)하여 업무시간을 산출한다"),
            ("cardio_notice", "감시 또는 단속적으로 근로에 종사하는 자로서 사용자가 고용노동부장관의 승인을 받은 경우와 "
                              "이와 유사한 업무에 해당하는 경우는 제외한다"),
            ("cardio_notice", "이전 12주(발병 전 1주일 제외)간에 1주 평균보다 30퍼센트 이상 증가되거나 업무 강도ㆍ책임 및 "
                              "업무 환경 등이 적응하기 어려운 정도로 바뀐 경우"),
            ("cardio_notice", "증상 발생 전 24시간 이내에 업무와 관련된 돌발적이고 예측 곤란한 사건의 발생과 급격한 업무 "
                              "환경의 변화로 뇌혈관 또는 심장혈관의 병변 등이 그 자연경과를 넘어 급격하고 뚜렷하게 "
                              "악화된 경우"),
            ("iaci_act_112", "3년간 행사하지 아니하면 시효로 말미암아 소멸한다"),
            ("iaci_act_112", "장해급여, 유족급여, 장례비, 진폐보상연금 및 진폐유족연금을 받을 권리는 5년간"),
        ),
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


@dataclass(frozen=True)
class AnnexClaim:
    """별표의 '적용 규정' 목록에 대한 주장 — 있음(applies=True) 또는 없음(False).

    "별표에 **없다**"는 부재 주장은 구절 앵커로 검증할 수 없다. 그래서 `check_law_freshness --anchors`가 별표
    본문을 **적용 규정 목록으로 해석**해 대조한다(`annex_listing`, law-article-coverage D9). 부분문자열 검사로
    두면 안 된다 — 근로기준법 시행령 별표 1은 표 칸 줄바꿈으로 번호가 쪼개지고(`제 ┃ ┃ │35조부터`), 범위
    ("제35조부터 제42조까지") 안의 조문은 문자열로 나타나지 않아, 실린 조문도 '없음'으로 보였다(거짓 안심).
    ref가 장 단위("제6장의2")면 표 문자를 지운 본문 문자열로 본다.
    """
    group: str        # RuleFact.name 또는 "answer_rules"(prompts.ANSWER_ACCURACY_RULES)
    law: str          # 별표가 있는 법령명
    annex_title: str  # 별표 제목 부분일치
    ref: str          # "제24조" · "제23조제1항" · "제76조의2" · "제6장의2"
    applies: bool


_LSA_ENF = "근로기준법 시행령"
_FTA_ENF = "기간제 및 단시간근로자 보호 등에 관한 법률 시행령"
_SMALL = "4명 이하"

ANNEX_CLAIMS: tuple[AnnexClaim, ...] = (
    # 괴롭힘 블록: "상시 4명 이하 사업장에는 … 괴롭힘 규정(제76조의2·제76조의3)이 적용되지 않는다"
    AnnexClaim("harassment_retaliation", _LSA_ENF, _SMALL, "제6장의2", False),
    AnnexClaim("harassment_retaliation", _LSA_ENF, _SMALL, "제76조의2", False),
    AnnexClaim("harassment_retaliation", _LSA_ENF, _SMALL, "제76조의3", False),
    # 정확성 규칙의 '5명 이상 전용'(prompts.ANSWER_ACCURACY_RULES) — 4명 이하 별표에 없어야 한다
    *(AnnexClaim("answer_rules", _LSA_ENF, _SMALL, ref, False) for ref in (
        "제23조제1항", "제24조", "제27조", "제28조", "제46조", "제50조", "제53조", "제55조제2항", "제56조",
        "제60조", "제94조", "제95조")),
    # 정확성 규칙의 '규모와 무관' — 4명 이하 별표에 있어야 한다
    *(AnnexClaim("answer_rules", _LSA_ENF, _SMALL, ref, True) for ref in (
        "제23조제2항", "제26조", "제55조제1항", "제74조")),
    AnnexClaim("answer_rules", _FTA_ENF, _SMALL, "제4조", False),
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
