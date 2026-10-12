"""법령 카탈로그 — 예열·현행성 점검·런타임 분류가 함께 쓰는 법령 목록과 키워드 조문 규칙.

production-law-api-recovery D14. 대상 목록이 셋으로 갈리면 "점검은 하는데 예열은 안 되는" 사각이
생긴다. 그래서 `warm_law_cache.py`(예열)·`check_law_freshness._watched_laws()`(현행성 점검)·
`legal_api.fetch_article`(실호출 꺼짐 때 `miss`/`skipped_unwarmed` 분류)이 모두 이 모듈을 쓴다.

import 방향: 이 모듈 → legal_api(module 수준). `legal_consultation`은 legal_api를 import하므로 주제 기본
조문은 함수 안에서 늦게 import하고, legal_api도 이 모듈을 함수 안에서만 import한다(순환 회피).

키워드 조문(KEYWORD_LAWS)은 2-1(조문 조회)에 의도분석 조문보다 **먼저** 실린다(D8, 최대 3개).
의도분석의 주제 enum에 모성보호·외국인 고용·파견·성희롱이 없어, 육아휴직 질문에 연차 조문이 실리는
식으로 엉뚱한 기본 조문만 들어가던 문제의 처방이다(topic30 점검 2026-10-06). 주제 enum은 바꾸지
않는다(D9 — 분류가 흔들리고 fixture 기대값이 바뀐다).

규칙을 고칠 때 지킬 것:
- **고신뢰 패턴만** 둔다. 엉뚱한 조문이 근거로 실리는 오탐이, 조문이 안 실리는 미탐보다 비싸다.
  외국인 규칙은 사업장 변경 문맥을, 경영상 규칙은 해고·감원을 요구한다(외국인 퇴직금·경영상 임금
  삭감 질문은 대상이 아니다). 임신 규칙은 배우자의 임신·출산이면 빠진다.
- 구어 확장은 **두 단서가 가까이 함께 있을 때만** 발동한다(`_near`, law-article-coverage D3). 경영악화·
  원청 같은 낱말은 실업급여·임금체불 질문의 배경 서술로 흔히 나온다 — 단독 낱말로 발동시키면 그
  질문의 첫 근거가 무관한 조문이 된다(코퍼스 표본 실측 3분의 1 오탐).
- 조문은 **주 조문**(`refs`)과 **보충 조문**(`extra`, 시행령·시행규칙의 절차 조문)으로 나눈다. 보충 조문은
  발동한 규칙들의 주 조문이 상한을 채우고 남긴 자리에만 들어간다(D1) — 한 줄로 섞으면 "육아휴직 +
  가족돌봄" 질문에서 육아휴직 시행령이 가족돌봄 제22조의2를 밀어냈다(시뮬레이션 실측).
- 조문 번호는 원문으로 확인한 것만 쓴다 — 배우자 유산·사산휴가는 제18조의2가 아니라 **제18조의4**다
  (Design rev1 표가 틀렸다). 삭제된 조문이 섞이면 `check_law_freshness --anchors`의 생존 점검이 잡는다.
- 새 조문의 법령은 `warm_law_names()`에 자동으로 들어간다(`refs`·`extra` 모두). 예열 대상이 아니면
  프로덕션(실호출 꺼짐)에서 조회되지 않는다 — 테스트 R9·AC3이 "모든 조문이 해석되고 예열 대상에 있다"를
  고정한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

from app.core.legal_api import _alias_name, _law_key, law_ref_key, parse_law_reference, select_law_refs
from harassment_assessor.grounding import is_sexual_harassment

# 현행성 점검 기본 17종(check_law_freshness의 구 _BASE_LAWS) — 과거 _PRELOADED_MST 목록이다
# (실측에서 11종이 낡아 있던 재발 감시 대상). 세법 2종은 퇴직소득세·근로장려금 계산 질문이 조문을
# 요청하므로 예열에도 포함한다(두 법령이 예열 행의 45%).
BASE_LAWS: tuple[str, ...] = (
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
)

_LSA = "근로기준법"
_LSA_ENF = "근로기준법 시행령"
_LSA_RULE = "근로기준법 시행규칙"
_EQUAL = "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률"
_EQUAL_ENF = "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률 시행령"
_FOREIGN_ACT = "외국인근로자의 고용 등에 관한 법률"
_DISPATCH = "파견근로자 보호 등에 관한 법률"
_RETIRE = "근로자퇴직급여 보장법"
_EI = "고용보험법"

# 성희롱 질문은 원 주제를 유지하되 괴롭힘 조문만 뺀다(D10) — 2-1·2-2 양쪽에 적용한다.
# 제76조의2·3을 실으면 LLM이 성희롱을 괴롭힘 법리("5인 이상" 등)로 답했다(topic30 6번).
# 제116조(과태료)는 ①이 괴롭힘 행위자, ②가 성희롱과 무관한 조항 위반이라 함께 뺀다(law-article-coverage D4).
SEXUAL_HARASSMENT_DROP_REFS: tuple[str, ...] = (f"{_LSA} 제76조의2", f"{_LSA} 제76조의3", f"{_LSA} 제116조")

# 의도분석이 실제로 요청했지만 예열 밖이라 skipped_unwarmed였던 법령(Vercel 로그 2026-10-06: 형법 제298조,
# 민법 제750조, 국민연금법 제124조, 국민건강보험법 제109조 — law-article-coverage D7). 일반법은 조문 일부가
# 아니라 **법령 전체**를 예열한다 — 일부만 넣으면 '예열된 법령의 없는 조문'이 miss로 잡혀 감시 ②(조문
# 성공률)가 흐려진다.
INTENT_WARM_LAWS: tuple[str, ...] = (
    "형법", "민법", "성폭력범죄의 처벌 등에 관한 특례법", "국민연금법", "국민건강보험법",
    "고용보험 및 산업재해보상보험의 보험료징수 등에 관한 법률",
)


@dataclass(frozen=True)
class KeywordLaw:
    """질문 표현 → 근거 조문. ``match``는 공백을 한 칸으로 정리한 질문 본문을 받는다.

    ``refs``는 주 조문, ``extra``는 보충 조문(시행령·시행규칙의 절차 조문)이다 — 보충 조문은 발동한 규칙들의
    주 조문이 상한을 채우고 남긴 자리에만 들어간다(keyword_laws, D1).
    """
    name: str
    refs: tuple[str, ...]
    match: Callable[[str], bool]
    extra: tuple[str, ...] = ()


def _rx(pattern: str, *, exclude: str | None = None, context: str | None = None,
        flags: int = 0) -> Callable[[str], bool]:
    """``pattern``이 있고 ``exclude``가 없을 때. ``context``를 주면 그 표현도 질문 어딘가에 있어야 한다."""
    inc = re.compile(pattern, flags)
    exc = re.compile(exclude, flags) if exclude else None
    ctx = re.compile(context, flags) if context else None
    return lambda q: (bool(inc.search(q)) and not (exc and exc.search(q))
                      and (ctx is None or bool(ctx.search(q))))


def _near(a: str, b: str, window: int, *, context: str | None = None,
          exclude: str | None = None) -> Callable[[str], bool]:
    """두 단서의 일치 시작점이 window자 안에 있을 때만(순서 무관). ``context``는 질문 어딘가에 있어야 하는
    문맥, ``exclude``는 있으면 빠지는 표현이다(D3)."""
    ra, rb = re.compile(a), re.compile(b)
    rc = re.compile(context) if context else None
    rex = re.compile(exclude) if exclude else None

    def match(q: str) -> bool:
        if (rex and rex.search(q)) or (rc and not rc.search(q)):
            return False
        starts = [m.start() for m in rb.finditer(q)]
        return any(abs(m.start() - s) <= window for m in ra.finditer(q) for s in starts)
    return match


def _any(*matchers: Callable[[str], bool]) -> Callable[[str], bool]:
    return lambda q: any(m(q) for m in matchers)


# 배우자를 주어로 쓰는 구어("아내가 출산", "와이프 유산")도 같은 휴가다.
_SPOUSE = r"(배우자|아내|와이프|부인)\s*(가|이|의)?\s*"
_FOREIGN_PERMIT = re.compile(r"(?<![A-Za-z0-9])E\s*-?\s*9(?!\d)|고용\s*허가", re.I)
_FOREIGN = re.compile(r"외국인")
# "회사 변경"(topic30 8번)도 같은 뜻이다. '퇴사'는 넣지 않는다 — "외국인 퇴사 후 퇴직금"은 사업장 변경 질문이 아니다.
_WORKPLACE_CHANGE = re.compile(r"(사업장|근무처|회사|직장)\s*(을|를)?\s*(변경|바꾸|옮기|이동)")


def _foreign_workplace_change(q: str) -> bool:
    """외국인 고용 신호(E-9·고용허가·외국인) **와** 사업장 변경 문맥이 함께 있을 때만.

    E-9만으로 발동하면 "E-9 근로자 출국만기보험·퇴직금" 질문에 제25조(사업장 변경)가 첫 근거로 실린다
    (CodeRabbit PR #102)."""
    foreign = bool(_FOREIGN_PERMIT.search(q) or _FOREIGN.search(q))
    return foreign and bool(_WORKPLACE_CHANGE.search(q))


_SPOUSE_PREGNANCY = r"(아내|배우자|와이프|부인|여자\s*친구).{0,12}(임신|출산)"

# 경영상 해고 구어(D3) — "장사가 안 된다는 이유로 해고"(topic30 22번). 사정 악화와 해고 동사가 40자 안에
# 함께 있어야 한다. '권고사직'·'구조조정'은 동사로 넣지 않는다(합의해지이거나 일반 서술이라 제24조와 거리가
# 있다). 실업급여·조기재취업·연차수당 질문은 경영악화가 배경 서술로 흔히 나와 구어 경로에서 뺀다.
_LAYOFF_CAUSE = (r"(장사|매출|영업|일감|물량|일거리|손님|경영|회사\s*사정|가게\s*사정|적자)"
                 r"\s*(이|가|도)?\s*(안\s*(돼|되|된|좋)|어렵|어려|힘들|부진|악화|감소|줄|없|떨어|나빠)")
_LAYOFF_VERB = (r"(해고|자르|잘렸|잘린|짤렸|짤린|감원|인원\s*(을\s*)?감축"
                r"|그만\s*(두라|둬라|두래|나와|나오래|나오지\s*말)|나가\s*(라|달라))")
_LAYOFF_OTHER_TOPIC = r"실업\s*급여|구직\s*급여|조기\s*재취업|연차\s*수당"

# 표 순서가 우선순위다(주 조문으로 최대 3개, 남는 자리에만 보충 조문).
KEYWORD_LAWS: tuple[KeywordLaw, ...] = (
    KeywordLaw("직장 내 성희롱", (f"{_EQUAL} 제12조", f"{_EQUAL} 제14조"), is_sexual_harassment),
    # 시행령 제11조⑤⑥ — 신청일부터 14일 이내 허용 통지, 미통지 시 신청대로 허용한 것으로 본다(재채점 1번)
    KeywordLaw("육아휴직", (f"{_EQUAL} 제19조",), _rx(r"육아\s*휴직"), extra=(f"{_EQUAL_ENF} 제11조",)),
    # 구어 "육아 근로단축"·"육아단축"도 같은 제도다(topic30 3번 실측)
    KeywordLaw("육아기 근로시간 단축", (f"{_EQUAL} 제19조의2",), _rx(r"육아기?\s*(근로\s*(시간\s*)?)?단축")),
    KeywordLaw("배우자 출산휴가", (f"{_EQUAL} 제18조의2",), _rx(_SPOUSE + r"출산")),
    KeywordLaw("배우자 유산·사산휴가", (f"{_EQUAL} 제18조의4",), _rx(_SPOUSE + r"(유산|사산)")),
    # 시행령 제16조의3 — 가족돌봄휴직·휴가 허용 예외(재채점 3번)
    KeywordLaw("가족돌봄", (f"{_EQUAL} 제22조의2",), _rx(r"가(족|정)\s*돌봄"),   # 구어 "가정돌봄휴가"(topic30 3번)
               extra=(f"{_EQUAL_ENF} 제16조의3",)),
    KeywordLaw("임신 중 보호·출산전후휴가", (f"{_LSA} 제74조",),
               # "임신 초기 유산 위험으로 근무시간 단축"(topic30 6번)처럼 '근무시간'·긴 수식어도 같은 보호다
               _rx(r"임신.{0,20}(단축|(근로|근무)\s*시간|야간|연장|시간\s*외)|임신기|출산\s*(전후\s*)?휴가",
                   exclude=_SPOUSE_PREGNANCY)),
    # 시행령 제43조의2 — 단축 신청 절차(개시 예정일 3일 전, 의사 진단서). 제74조는 위 규칙이 싣는다(재채점 6번)
    KeywordLaw("임신기 단축 신청", (), _rx(r"임신.{0,20}(단축|(근로|근무)\s*시간)|임신기\s*(근로\s*(시간\s*)?)?단축",
                                         exclude=_SPOUSE_PREGNANCY),
               extra=(f"{_LSA_ENF} 제43조의2",)),
    KeywordLaw("외국인 사업장 변경", (f"{_FOREIGN_ACT} 제25조",), _foreign_workplace_change),
    # 구어(D3): "작업지시는 원청 현장관리자에게 … 도급 근로계약서"(topic30 25번). '감독'은 원청 안전 감독 질문에도
    # 걸려 넣지 않는다.
    KeywordLaw("파견", (f"{_DISPATCH} 제5조", f"{_DISPATCH} 제6조의2"),
               _any(_rx(r"불법\s*파견|파견\s*(근로|업체|직원|회사)|위장\s*도급|직접\s*고용\s*의무"),
                    # '중지시키다'의 '지시'는 지휘가 아니다("원청이 하청 작업을 중지시켰다")
                    _near(r"원청", r"(?<!중)지시|지휘|명령", 20, context=r"도급|하청|협력\s*업체|용역|파견"))),
    KeywordLaw("연소자", (f"{_LSA} 제69조", f"{_LSA} 제70조"), _rx(r"미성년|연소자|18세\s*미만|고등학생")),
    KeywordLaw("취업규칙 불이익 변경", (f"{_LSA} 제94조",), _rx(r"취업\s*규칙.{0,20}(변경|불이익)")),
    KeywordLaw("위약예정·의무재직", (f"{_LSA} 제20조",),
               _rx(r"위약금|의무\s*재직|손해\s*배상.{0,6}예정|교육비\s*반환")),
    # 제95조 — 감급 1회 평균임금 1일분의 2분의 1, 총액 1임금지급기 임금총액의 10분의 1(재채점 16번)
    KeywordLaw("감봉", (f"{_LSA} 제95조",), _rx(r"감봉|감급")),
    KeywordLaw("경영상 해고", (f"{_LSA} 제24조",),
               _any(_rx(r"경영상.{0,12}(해고|감원)|정리\s*해고"),
                    _near(_LAYOFF_CAUSE, _LAYOFF_VERB, 40, exclude=_LAYOFF_OTHER_TOPIC))),
    # 제30조③ — 원직복직을 원하지 않으면 임금 상당액 이상의 금품(재채점 23번). '원직복직'은 산재 요양·전보
    # 뒤 복귀 질문에도 나와 해고·구제 문맥을 요구한다(코퍼스 23건 중 문맥 없는 2건이 그 경우였다).
    KeywordLaw("부당해고 금전보상", (f"{_LSA} 제30조",),
               _any(_rx(r"금전\s*보상\s*(명령|신청|제도)|부당\s*해고[^.?!\n]{0,30}(보상|배상)"),
                    _rx(r"원직\s*복직", context=r"해고|구제|노동\s*위원회|지노위|중노위"))),
    # 시행규칙 제9조 — 특별연장근로 인가 사유 5개(재채점 26번). '특별 연장수당'은 회사 수당 명칭이다.
    KeywordLaw("특별연장근로", (f"{_LSA} 제53조",), _rx(r"특별\s*연장(?!\s*수당)"), extra=(f"{_LSA_RULE} 제9조",)),
    KeywordLaw("연장근로 한도", (f"{_LSA} 제53조",),
               _rx(r"52\s*시간[^.?!\n]{0,8}(초과|넘|이상)|주\s*12\s*시간[^.?!\n]{0,8}(초과|넘)"
                   r"|연장\s*근로\s*(의\s*)?(한도|제한)")),
    KeywordLaw("임금명세서", (f"{_LSA} 제48조",), _rx(r"(임금|급여)\s*명세서")),
    KeywordLaw("휴업수당", (f"{_LSA} 제46조",), _rx(r"휴업\s*수당")),
    # 제20조 — DC 부담금(연간 임금총액 12분의 1 이상)·퇴직 시 IRP 이전 요청. 'IRP' 단독은 퇴직금 IRP 이전(제9조)
    # 질문이라 넣지 않는다(재채점 15번).
    KeywordLaw("DC형 퇴직연금", (f"{_RETIRE} 제20조",), _rx(r"DC\s*형|확정\s*기여", flags=re.I)),
    KeywordLaw("퇴직연금 중도인출", (f"{_RETIRE} 제22조",), _rx(r"중도\s*인출")),
    # 제15조(피보험자격 신고)·제118조(제15조 위반 300만원 이하 과태료, 재채점 14번). 해고 질문의 배경 문장
    # ("4대보험 가입을 안 했다")만으로도 발동해 과태료 조문은 보충으로 둔다. 실업급여 질문은 확인청구(insured_status
    # 블록)가 핵심이라 뺀다. 산재·국민연금·건강보험 미가입은 고용보험법이 무관해 대상이 아니다(예열로 의도분석 조문).
    KeywordLaw("4대보험 미가입", (f"{_EI} 제15조",),
               _near(r"(4대|사대|고용)\s*보험",
                     r"미가입|미신고|가입\s*(이|을|를)?\s*(안|않|되어\s*있지\s*않)|신고\s*(를|가)?\s*(안|않)", 40,
                     exclude=r"실업\s*급여|구직\s*급여"),
               extra=(f"{_EI} 제118조",)),
)

KEYWORD_LAW_LIMIT = 3


def keyword_laws(query: str, limit: int = KEYWORD_LAW_LIMIT) -> list[str]:
    """질문 본문에 맞는 키워드 조문(표 순서, 정규화 키로 중복 제거, 최대 limit개).

    발동한 규칙들의 **주 조문**으로 먼저 채우고, 남는 자리에만 보충 조문을 넣는다(D1).
    """
    q = " ".join((query or "").split())
    if not q:
        return []
    fired = [rule for rule in KEYWORD_LAWS if rule.match(q)]
    out = select_law_refs([ref for rule in fired for ref in rule.refs], limit=limit)
    if len(out) < limit:
        out += select_law_refs([ref for rule in fired for ref in rule.extra],
                               exclude_keys={law_ref_key(r) for r in out}, limit=limit - len(out))
    return out


def warm_law_names() -> list[str]:
    """예열·현행성 점검 대상 법령(정식명, 순서 보존·중복 제거).

    = 기본 17종 + 주제 기본 조문의 법령 + 키워드 조문(주·보충)의 법령 + 의도분석 요청 법령(INTENT_WARM_LAWS).
    """
    from app.core.legal_consultation import TOPIC_SEARCH_CONFIG   # 순환 회피 — 늦은 import

    names = list(BASE_LAWS)
    refs = [r for cfg in TOPIC_SEARCH_CONFIG.values() for r in cfg.get("default_laws", [])]
    refs += [r for rule in KEYWORD_LAWS for r in rule.refs + rule.extra]
    for ref in refs:
        parsed = parse_law_reference(ref)
        if parsed:
            names.append(parsed["law"])
    names += INTENT_WARM_LAWS
    # 약칭만 정식명으로 바꾼다(_alias_name) — canonical_law_name은 아래 색인을 쓰므로 여기서 부르면 순환한다.
    out: list[str] = []
    seen: set[str] = set()
    for name in names:
        official = _alias_name(name)
        key = _law_key(official)
        if key not in seen:
            seen.add(key)
            out.append(official)
    return out


@lru_cache(maxsize=1)
def warm_law_keys() -> frozenset[str]:
    """예열 대상의 표기 키(_law_key) — 런타임 분류(D7)가 법령 하나마다 목록을 다시 만들지 않게."""
    return frozenset(official_name_index())


@lru_cache(maxsize=1)
def official_name_index() -> dict[str, str]:
    """표기 키 → 정식명(예열 대상). `legal_api.canonical_law_name`이 띄어쓰기·가운뎃점 변형을 정식명으로
    되돌리는 데 쓴다 — LM 조회명·조문 머리글이 LLM 표기가 아니라 정식명이 된다."""
    return {_law_key(n): n for n in warm_law_names()}
