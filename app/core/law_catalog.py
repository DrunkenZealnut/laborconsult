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
- 조문 번호는 원문으로 확인한 것만 쓴다 — 배우자 유산·사산휴가는 제18조의2가 아니라 **제18조의4**다
  (Design rev1 표가 틀렸다).
- 새 조문의 법령은 `warm_law_names()`에 자동으로 들어간다. 예열 대상이 아니면 프로덕션(실호출 꺼짐)에서
  조회되지 않는다 — 테스트 R9가 "모든 조문이 해석되고 예열 대상에 있다"를 고정한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

from app.core.legal_api import _alias_name, _law_key, parse_law_reference, select_law_refs
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
_EQUAL = "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률"
_FOREIGN_ACT = "외국인근로자의 고용 등에 관한 법률"
_DISPATCH = "파견근로자 보호 등에 관한 법률"

# 성희롱 질문은 원 주제를 유지하되 괴롭힘 조문만 뺀다(D10) — 2-1·2-2 양쪽에 적용한다.
# 제76조의2·3을 실으면 LLM이 성희롱을 괴롭힘 법리("5인 이상" 등)로 답했다(topic30 6번).
SEXUAL_HARASSMENT_DROP_REFS: tuple[str, ...] = (f"{_LSA} 제76조의2", f"{_LSA} 제76조의3")


@dataclass(frozen=True)
class KeywordLaw:
    """질문 표현 → 근거 조문. ``match``는 공백을 한 칸으로 정리한 질문 본문을 받는다."""
    name: str
    refs: tuple[str, ...]
    match: Callable[[str], bool]


def _rx(pattern: str, *, exclude: str | None = None, flags: int = 0) -> Callable[[str], bool]:
    inc = re.compile(pattern, flags)
    exc = re.compile(exclude, flags) if exclude else None
    return lambda q: bool(inc.search(q)) and not (exc and exc.search(q))


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


# 표 순서가 우선순위다(최대 3개만 남는다).
KEYWORD_LAWS: tuple[KeywordLaw, ...] = (
    KeywordLaw("직장 내 성희롱", (f"{_EQUAL} 제12조", f"{_EQUAL} 제14조"), is_sexual_harassment),
    KeywordLaw("육아휴직", (f"{_EQUAL} 제19조",), _rx(r"육아\s*휴직")),
    # 구어 "육아 근로단축"·"육아단축"도 같은 제도다(topic30 3번 실측)
    KeywordLaw("육아기 근로시간 단축", (f"{_EQUAL} 제19조의2",), _rx(r"육아기?\s*(근로\s*(시간\s*)?)?단축")),
    KeywordLaw("배우자 출산휴가", (f"{_EQUAL} 제18조의2",), _rx(_SPOUSE + r"출산")),
    KeywordLaw("배우자 유산·사산휴가", (f"{_EQUAL} 제18조의4",), _rx(_SPOUSE + r"(유산|사산)")),
    KeywordLaw("가족돌봄", (f"{_EQUAL} 제22조의2",), _rx(r"가(족|정)\s*돌봄")),   # 구어 "가정돌봄휴가"(topic30 3번)
    KeywordLaw("임신 중 보호·출산전후휴가", (f"{_LSA} 제74조",),
               # "임신 초기 유산 위험으로 근무시간 단축"(topic30 6번)처럼 '근무시간'·긴 수식어도 같은 보호다
               _rx(r"임신.{0,20}(단축|(근로|근무)\s*시간|야간|연장|시간\s*외)|임신기|출산\s*(전후\s*)?휴가",
                   exclude=r"(아내|배우자|와이프|부인|여자\s*친구).{0,12}(임신|출산)")),
    KeywordLaw("외국인 사업장 변경", (f"{_FOREIGN_ACT} 제25조",), _foreign_workplace_change),
    KeywordLaw("파견", (f"{_DISPATCH} 제5조", f"{_DISPATCH} 제6조의2"),
               _rx(r"불법\s*파견|파견\s*(근로|업체|직원|회사)|위장\s*도급|직접\s*고용\s*의무")),
    KeywordLaw("연소자", (f"{_LSA} 제69조", f"{_LSA} 제70조"), _rx(r"미성년|연소자|18세\s*미만|고등학생")),
    KeywordLaw("취업규칙 불이익 변경", (f"{_LSA} 제94조",), _rx(r"취업\s*규칙.{0,20}(변경|불이익)")),
    KeywordLaw("위약예정·의무재직", (f"{_LSA} 제20조",),
               _rx(r"위약금|의무\s*재직|손해\s*배상.{0,6}예정|교육비\s*반환")),
    KeywordLaw("경영상 해고", (f"{_LSA} 제24조",), _rx(r"경영상.{0,12}(해고|감원)|정리\s*해고")),
    KeywordLaw("임금명세서", (f"{_LSA} 제48조",), _rx(r"(임금|급여)\s*명세서")),
    KeywordLaw("휴업수당", (f"{_LSA} 제46조",), _rx(r"휴업\s*수당")),
)

KEYWORD_LAW_LIMIT = 3


def keyword_laws(query: str, limit: int = KEYWORD_LAW_LIMIT) -> list[str]:
    """질문 본문에 맞는 키워드 조문(표 순서, 정규화 키로 중복 제거, 최대 limit개)."""
    q = " ".join((query or "").split())
    if not q:
        return []
    refs: list[str] = []
    for rule in KEYWORD_LAWS:
        if rule.match(q):
            refs.extend(rule.refs)
    return select_law_refs(refs, limit=limit)


def warm_law_names() -> list[str]:
    """예열·현행성 점검 대상 법령(정식명, 순서 보존·중복 제거).

    = 기본 17종 + 주제 기본 조문의 법령 + 키워드 조문의 법령. 새로 들어오는 것은 외국인고용법뿐이다
    (파견법·남녀고용평등법은 기본 17종에 있다).
    """
    from app.core.legal_consultation import TOPIC_SEARCH_CONFIG   # 순환 회피 — 늦은 import

    names = list(BASE_LAWS)
    refs = [r for cfg in TOPIC_SEARCH_CONFIG.values() for r in cfg.get("default_laws", [])]
    refs += [r for rule in KEYWORD_LAWS for r in rule.refs]
    for ref in refs:
        parsed = parse_law_reference(ref)
        if parsed:
            names.append(parsed["law"])
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
