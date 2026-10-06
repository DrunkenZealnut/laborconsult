"""
괴롭힘 판정 입력의 근거 검증 — 판정 입력을 **사용자 질문 본문에서 도출**하고 판정 여부를 정한다.

도구 인자(LLM 추출, `tool_choice="any"`로 강제 생성)는 질문에 없는 기간·회사 대응·행위 유형을
채운다(실측 2026-10-05: risk-04 기간 "6개월", kin-09 회사 대응 "미조치"). 필드마다 "근거 단어가
있으면 도구 값 유지"로는 값과 무관한 단어 하나로 통과한다("조사" → 조사중, "동료 3명" → 5인 미만,
design-validator H4). 그래서 값 자체를 질문에서 도출하고, 도구 값은 판정에 쓰지 않는다 — 다르면
버린 필드명으로만 기록한다(관측). 모드는 첨부가 아니라 **질문 본문**으로 정한다(H7·D6).

모드(claim-authority-and-assessor-facts D7):
- skipped: 성희롱(남녀고용평등법 소관) · 사안 서술 없음(개념 질문·사용자 측 질문) — 판정하지 않는다
- held: 사안은 서술됐지만 행위 또는 행위자가 질문에서 확인되지 않음 — 판단 보류와 필요한 사실 안내
- assessed: 행위 유형과 행위자가 모두 질문에 있다
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .constants import (
    BEHAVIOR_TYPE_PATTERNS,
    IMPACT_PATTERNS,
    MAJORITY_RE,
    ROLE_KEYWORDS,
    SUPERIORITY_SCORES,
)
from .models import HarassmentInput

# 피해 주장 — 자기 사안을 서술하는가. "괴롭힘에해당하나요"(무공백)의 '해당'은 피해 동사가 아니다.
_VICTIM_CLAIM_RE = re.compile(
    r"(괴롭힘|갑질|따돌림|왕따|폭언|모욕|욕설|막말|폭행|성희롱)[을를이가도은는에]?\s*(계속\s*|매일\s*|자주\s*|너무\s*)?"
    r"(당하|당한|당해|당했|당함|받고|받았|받는|받아|겪고|겪었|겪는|듣고|들었|시달리|시달려|시달렸)"
    r"|(갑질|괴롭힘|폭언|막말)[이가]?\s*(너무\s*|정말\s*|계속\s*|점점\s*)?(심해|심하|심합|심했)"
    r"|(괴롭힘|갑질|따돌림|폭언|막말)\s*(때문에|탓에|(으)?로\s*인해)"
    r"|(?<![의식탐목성수물])욕(을|도)?\s*(계속\s*|매일\s*|자주\s*)?(들|듣|먹)")   # "욕을 들어요"(Check §3-9)
# 피해 주장 앞 20자에 제3자 주어가 있으면 자기 주장이 아니다("직원이 괴롭힘을 당했다고 신고했는데").
_THIRD_PARTY_RE = re.compile(
    r"(직원|근로자|팀원|부하|후배|동료|직원분|아르바이트생|알바생)\S{0,2}(이|가|들이|분이)\s*\S{0,10}$")
# 행위자만으로 '사안 서술'을 인정할 때, 제3자·사용자 측 서술이면 본인 사안이 아니다(Check §3-3):
# "팀장이 직원에게 욕을 했다는 신고가 들어왔는데 회사는…"·"제 친구 회사에서 사장이…". 자기 지칭이
# 함께 있으면("저와 다른 직원에게") 본인 사안으로 본다.
_THIRD_CASE_RE = re.compile(
    r"신고가\s*들어|신고를\s*받|(제|내)\s*(친구|지인|동생|언니|오빠|형|누나|가족)|다른\s*직원|"
    r"직원(들)?(에게|한테)|후배(에게|한테)|부하(에게|한테)|팀원(들)?(에게|한테)")
_SELF_REF_RE = re.compile(r"저는|저를|저한테|저에게|저와|저도|저만|제가|제게|나를|나한테|내가")
_SEXUAL_RE = re.compile(
    r"성희롱|성추행|추행|성적(인)?\s*(발언|농담|말|접촉|행동|요구|수치심)|음담패설|몸을?\s*만지|신체\s*접촉")
# 신고 뒤 불리한 조치 — 그 인사 조치는 괴롭힘 행위가 아니라 제76조의3⑥(불리한 처우) 영역이다.
# 조치 단어가 없으면 아니다(risk-04 "신고 후 조사 절차").
_RETALIATION_RE = re.compile(
    r"(신고|진정|제보|문제\s*제기|고충\s*제기)\S{0,4}\s*(했더니|했는데|하자|하고\s*나서|하고\s*나니|한\s*(뒤|후|다음)|이후|후)"
    r".{0,40}?(불리|전보|배치\s*전환|전환\s*배치|발령|좌천|해고|징계|보복|불이익|부서\s*이동)", re.S)

_FREQUENCY_RULES = (("매일", r"매일|날마다|하루도\s*빠짐없이|매번|맨날"),
                    ("반복", r"반복|계속|자주|툭하면|수시로|항상|여러\s*차례"),
                    ("수회", r"몇\s*번|여러\s*번|수차례|두세\s*번"),
                    ("1회", r"한\s*번|딱\s*한\s*번|1회"))
# 지속 표지가 붙은 기간만 — "입사 3년차"·"주 5일"은 기간이 아니다.
# 괴롭힘과 무관한 신고(산재·임금체불 등) 뒤의 해고는 제76조의3⑥의 '괴롭힘 신고'가 아니다 — 회사 대응을
# "불리한 처우"로 두면 "괴롭힘 신고를 이유로…" 경고가 붙는다(Check §3-8, "산재 신고 후 해고됐는데…").
_OTHER_REPORT_RE = re.compile(r"(산재|산업\s*재해|임금|체불|월급|급여|퇴직금|보험|세무|탈세)\s*(관련\s*)?$")
_DURATION_RE = re.compile(r"(\d+)\s*(년|해|개월|달|주)\s*(째|동안|간|넘게|이상|가까이|전부터|가량|정도)"
                          r"|몇\s*(년|달|주)\s*(째|동안|간)")
_INVESTIGATING_RE = re.compile(r"조사\s*중|조사하고\s*있|조사를\s*진행")
_NO_ACTION_RE = re.compile(r"조치(를|도)?\s*(안|하지\s*않|없)|아무\s*조치|묵살|모른\s*척")
_WITNESS_RE = re.compile(r"목격|증인|본\s*사람|다\s*봤|보고\s*있었")
_EVIDENCE_ITEMS = ("녹음", "녹취", "문자", "카톡", "메신저", "이메일", "메일", "진단서", "cctv", "사진", "메모", "일기")
# 규모 — 사업장 문맥의 인원수만("동료 3명이 저를"은 규모가 아니다).
_SIZE_RE = re.compile(r"(상시\s*(근로자)?|직원|근로자|사원|인원)\s*(수)?\s*(는|이|가|은)?\s*(약\s*)?\d[\d,]*\s*(명|인)"
                      r"|\d+\s*(인|명)\s*(미만|이하|이상|초과)?\s*(사업장|회사|업체|규모|사업)")
_VICTIM_ROLE_RE = re.compile(r"(저는|제가|저도)\s*\S{0,6}?(계약직|비정규직|파견직|파견|인턴|수습|신입)")
_ACTOR_WINDOW = 30   # 행위자 = 행위 표현과 같은 문장 30자 이내의 역할어(design-validator M8 근사)
# 역할어가 다른 낱말의 일부일 때(Check §3-3): "대표적으로"·"이사 온 뒤로"·"과장된 소문"·"동기부여"·"사장된"
_ROLE_FALSE_AFTER = {
    "대표": re.compile(r"적"),
    "이사": re.compile(r"\s+(온|간|갔|가|왔|와|오|했|하고|한\s)|를\s*(가|왔|했|한)|한\s*(뒤|후|지)|했"),
    "과장": re.compile(r"된|되|하|해|돼"),
    "사장": re.compile(r"된|되|돼"),
    "동기": re.compile(r"부여|가\s*(없|생|부족)"),
}
# 역할어 뒤 주격 조사 — 행위의 주어일 가능성이 높아 우선한다("동료가 팀장 앞에서 욕을 해요" → 동료)
_SUBJECT_AFTER = re.compile(r"(님)?(이|가|께서|은|는)(?![가-힣])|(님)?(이|가|께서|은|는)\s")

# 도구 값과 도출값을 비교해 버린 필드를 기록할 대상 — 범주형은 값 비교, 서술형(impact)은 존재 비교
_CATEGORICAL = ("perpetrator_role", "relationship_type", "victim_role", "frequency", "duration",
                "company_response", "business_size")
_LISTS = ("behavior_types", "evidence")


@dataclass
class GroundingResult:
    mode: str                      # "assessed" | "held" | "skipped"
    reason: str                    # held: no_behavior·no_actor / skipped: sexual·no_case·retaliation
    inp: HarassmentInput
    dropped: list[str] = field(default_factory=list)


def _norm(text: str) -> str:
    """공백은 한 칸으로 **축약**한다(제거 아님 — 지우면 "괴롭힘에해당"처럼 붙어 판정이 바뀐다, M5)."""
    return re.sub(r"\s+", " ", text or "").strip()


def _sentences(text: str) -> list[str]:
    """원문을 먼저 문장으로 나누고 나서 공백을 축약한다 — 축약부터 하면 줄바꿈 경계가 사라진다(Check §1-4)."""
    return [_norm(s) for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()]


def _behavior_types(q: str, retaliation: bool) -> list[str]:
    types = {t for t, rx in BEHAVIOR_TYPE_PATTERNS.items() if rx.search(q)}
    if retaliation:
        types.discard("부당인사")
    return sorted(types)


def _role_candidates(sent: str, hits: list[int]):
    """(주격 우선순위, 거리, -길이, 역할어) — 같은 위치는 긴 역할어만('부장'보다 '본부장')."""
    taken: list[tuple[int, int]] = []
    out = []
    for role in sorted(ROLE_KEYWORDS, key=len, reverse=True):
        for rm in re.finditer(re.escape(role), sent):
            if any(a <= rm.start() < b for a, b in taken):
                continue
            false = _ROLE_FALSE_AFTER.get(role)
            if false and false.match(sent, rm.end()):
                continue
            dist = min((abs(rm.start() - h) for h in hits), default=10**6)
            if dist > _ACTOR_WINDOW:
                continue
            taken.append((rm.start(), rm.end()))
            subject = 0 if _SUBJECT_AFTER.match(sent, rm.end()) else 1
            out.append((subject, dist, -len(role), role))
    return out


def _actor(raw: str, types: list[str]) -> str:
    """행위 표현과 같은 문장 30자 이내의 역할어 — 주격 조사가 붙은 것, 그다음 가까운 것."""
    for sent in _sentences(raw):
        hits = [m.start() for t in types for m in BEHAVIOR_TYPE_PATTERNS[t].finditer(sent)]
        if not hits:
            continue
        cands = _role_candidates(sent, hits)
        if cands:
            return min(cands)[3]
    return ""


def _frequency(raw: str, types: list[str]) -> str:
    """빈도는 행위가 나온 문장에서만 찾는다("욕을 했어요. 계속 다녀야 할까요?"의 '계속'은 빈도가 아니다)."""
    behavior_sents = [s for s in _sentences(raw) if any(BEHAVIOR_TYPE_PATTERNS[t].search(s) for t in types)]
    text = " ".join(behavior_sents)
    return next((v for v, p in _FREQUENCY_RULES if re.search(p, text)), "") if text else ""


def _duration(q: str) -> str:
    m = _DURATION_RE.search(q)
    if not m:
        return ""
    n = int(m.group(1)) if m.group(1) else 2
    unit = m.group(2) or m.group(4)
    if unit in ("년", "해"):
        return "1년이상"
    if unit in ("개월", "달"):
        return "6개월" if n >= 6 else "3개월" if n >= 3 else "1개월"
    return "1주"


def _victim_claim(q: str) -> bool:
    for m in _VICTIM_CLAIM_RE.finditer(q):
        if not _THIRD_PARTY_RE.search(q[max(0, m.start() - 20): m.start()]):
            return True
    return False


def _harassment_retaliation(q: str) -> bool:
    """괴롭힘 관련 신고 뒤의 불리한 조치인가 — 신고 대상이 다른 사안이면 아니다."""
    return any(not _OTHER_REPORT_RE.search(q[max(0, m.start() - 10): m.start()])
               for m in _RETALIATION_RE.finditer(q))


def _company_response(q: str) -> str:
    if _INVESTIGATING_RE.search(q):
        return "조사중"
    if _harassment_retaliation(q):
        return "불리한 처우"
    return "미조치" if _NO_ACTION_RE.search(q) else ""


def derive_input(query: str) -> HarassmentInput:
    """판정 입력을 질문 본문에서 도출한다(도구 값을 쓰지 않는다)."""
    q = _norm(query)
    retaliation = bool(_RETALIATION_RE.search(q))
    types = _behavior_types(q, retaliation)
    actor = _actor(query, types)
    majority = bool(MAJORITY_RE.search(q))
    rel_candidates = [r for r in (ROLE_KEYWORDS.get(actor, ""), "다수_소수" if majority else "") if r]
    relationship = max(rel_candidates, key=lambda r: SUPERIORITY_SCORES.get(r, 0)) if rel_candidates else ""
    victim = _VICTIM_ROLE_RE.search(q)
    size = _SIZE_RE.search(q)
    # 판정기는 impact에 같은 패턴을 다시 건다 — 라벨("복약")이 아니라 매칭된 원문을 넘겨야 가산이 남는다
    impact_terms = [m.group(0) for rx, _bonus, _label in IMPACT_PATTERNS if (m := rx.search(q))]
    return HarassmentInput(
        perpetrator_role=actor,
        victim_role=victim.group(2) if victim else "",
        relationship_type=relationship,
        behavior_types=types,
        frequency=_frequency(query, types),
        duration=_duration(q) if types else "",
        witnesses=bool(_WITNESS_RE.search(q)),
        evidence=[e for e in _EVIDENCE_ITEMS if e in q.lower()],
        impact=" ".join(impact_terms),
        company_response=_company_response(q),
        business_size=size.group(0) if size else "",
        grounded=True,
    )


def decide_mode(query: str) -> GroundingResult:
    q = _norm(query)
    inp = derive_input(query)   # 원문 그대로 — 행위자·빈도는 줄바꿈도 문장 경계로 본다
    if _SEXUAL_RE.search(q):
        return GroundingResult("skipped", "sexual", inp)
    actor_case = bool(inp.perpetrator_role) and (bool(_SELF_REF_RE.search(q)) or not _THIRD_CASE_RE.search(q))
    if not (_victim_claim(q) or actor_case):
        reason = "retaliation" if _RETALIATION_RE.search(q) else "no_case"
        return GroundingResult("skipped", reason, inp)
    if inp.behavior_types and inp.perpetrator_role:
        return GroundingResult("assessed", "", inp)
    return GroundingResult("held", "no_behavior" if not inp.behavior_types else "no_actor", inp)


def as_list(value) -> list:
    """도구 인자는 list 자리에 문자열을 줄 때가 있다(design-validator M12)."""
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [v.strip() for v in re.split(r"[,·/]", value) if v.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value]
    return [str(value)]


def ground(params: dict, query: str) -> GroundingResult:
    """모드를 정하고, 도구 값과 도출값이 다른 필드명을 dropped로 남긴다(값은 남기지 않는다)."""
    result = decide_mode(query)
    try:   # 관측용 계산이 판정을 버리면 안 된다 — 이상한 인자 타입은 이 안에서 흡수한다(Check §3-7)
        result.dropped = _dropped_fields(params or {}, result.inp)
    except Exception:
        result.dropped = ["(unparsed)"]
    return result


def _dropped_fields(params: dict, inp: HarassmentInput) -> list[str]:
    dropped = []
    for name in _CATEGORICAL:
        tool = str(params.get(name) or "").strip()
        if tool and tool != getattr(inp, name):
            dropped.append(name)
    for name in _LISTS:
        tool = set(as_list(params.get(name)))
        if tool and tool != set(getattr(inp, name)):
            dropped.append(name)
    if str(params.get("impact") or "").strip() and not inp.impact:
        dropped.append("impact")
    if params.get("witnesses") and not inp.witnesses:
        dropped.append("witnesses")
    return dropped
