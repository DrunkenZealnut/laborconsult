"""실업급여 **이직사유 질문** 판정 — 단일 출처 (unemployment-separation-grounds D5).

`rule_facts`의 동반 블록 `separation_grounds`와 `law_catalog`의 2-1 키워드 규칙("이직사유·수급자격 제한" →
고용보험법 제58조)이 **같은 함수**를 쓴다. 판정이 두 벌이면 블록은 붙는데 조문은 안 실리는(또는 그 반대)
질문이 생긴다(테스트 U10이 `is` 동일성으로 고정).

이 모듈은 `re`·`unicodedata`와 `colloquial_map`(역시 `re`·`unicodedata`만 import)만 쓴다. `law_catalog`는
`pipeline`·`warm_law_cache`가 모듈 수준에서 import하므로, 여기서 `rule_facts`를 끌어오면 블록 쪽 import 오류가
전 요청 500과 예열 정지로 번진다(설계 M4 — U12가 AST로 고정). 억제자 정규식은 값을 복사하지 않고
`colloquial_map`에서 가져온다 — 사본이면 한쪽만 고쳐져 "기계에 손이 잘렸다"가 다시 해고가 된다.

감지는 세 층이다(설계 §3.2 · 2026-10-07 실측: 검증이 지적한 오탐 예문 12건 0, 양성 13건 13, 실사용 실업급여
32건 중 이직 질문 25건 발동·비실업급여 107건 0건):
- **실업 문맥**(`is_unemployment_context`): 실업급여·구직급여·실업인정·실업신고, 또는 '수급자격' + 실업·구직.
  '수급자격' 단독은 "육아휴직 급여 수급자격"에 걸린다.
- **강단서**(`has_strong_separation_cue`): 자진퇴사·권고사직·해고·계약 만료·이직확인서·폐업·체불·사직서 같은
  이직 사유 표현과 구어 해고("짤렸는데"·"나오지 말래요"). 단독으로 발동한다. 2-1 키워드 규칙은 강단서만
  쓴다(고신뢰 패턴 원칙).
- **약단서**(`_WEAK`): 퇴사·간병·육아·임신·질병·통근·전근·괴롭힘·정년·차별 … — 자격 질문 표현(`_ELIG`)이 함께
  있고 초점어(`_FOCUS`: 조기재취업·실업인정·구직활동·부정수급·금액·일수·계산)가 없을 때만. 초점어 질문은 이직
  사유가 배경 서술일 뿐이라 블록 약 2,000자를 붙일 이유가 없다("실업급여 받는 중 아파서 실업인정일" 등).

구어 사전이 `colloquial_map`·`law_catalog`·이 모듈 세 곳에 나뉘어 있는 것은 알려진 상태다(설계 §12 후속).
"""
from __future__ import annotations

import re
import unicodedata

from app.core.colloquial_map import _BODY_CONTEXT, _MOVE_CONTEXT

_CTX = re.compile(r"실업\s*(급여|수당)|구직\s*급여|실업\s*(인정|신고)")
_QUAL, _QUAL_CTX = re.compile(r"수급\s*자격"), re.compile(r"실업|구직")      # '육아휴직 급여 수급자격' 제외
_STRONG = re.compile(
    r"자진\s*(으로\s*)?(퇴사|퇴직|사직|그만)|자발적|권고\s*(사직|퇴직|해고)|권고(를|받)|해고"
    r"|계약\s*(기간\s*)?(이\s*|이\s*다\s*)?(만료|종료|끝)|이직\s*(사유|확인서)|상실\s*사유|정당한\s*(이직\s*)?사유"
    r"|폐업|도산|(희망|명예)\s*퇴직|임금\s*체불|체불|(월급|임금).{0,10}(안\s*줘|안\s*주|못\s*받|떼먹|떼였|밀렸|밀리)"
    r"|그만\s*(두|뒀|둔|둘|둬|뒤)|사직\s*(서|을|를|했|하|의사|처리)")   # '사직서를 냈어요'(n-transfer) — 측정 준비에서 추가
# 구어 해고 — 억제자는 colloquial_map과 같은 객체다(신체 절단 문맥 = 산재, 이동 지시 문맥 = 배치).
_FIRED = re.compile(r"잘렸|짤렸|잘린|짤린|잘려|짤려|잘릴|짤릴")
_GETOUT = re.compile(r"나오지\s*말|나가라(?:고|네|는|니)?|그만\s*나오")
_WEAK = re.compile(r"퇴사|퇴직(?!\s*(금|연금|소득))|간호|간병|육아|임신|출산|질병|아파서|건강|통근|출퇴근"
                   r"|이사\s*(가|를|해|하|했|때문)|(사업장|회사|공장|매장|사무실|근무지)\S{0,2}\s*.{0,10}이전|전근"
                   r"|괴롭힘|성희롱|정년|차별|최저\s*임금|연장\s*근로|휴업")
_ELIG = re.compile(r"받을\s*수\s*(있|없)|대상|자격(이|은)?\s*(되|있|없)|되나|돼요|될까|되는지|가능|못\s*받나|안\s*되나|제한")
_FOCUS = re.compile(r"조기\s*재취업|실업\s*인정|구직\s*활동|부정\s*수급|얼마|금액|일액|며칠|몇\s*일|소정\s*급여\s*일수|계산|지급\s*기간")


def _norm(text: str | None) -> str:
    """NFC + 공백 한 칸 — macOS 파일명·일부 입력은 NFD라 완성형 문자 클래스에 걸리지 않는다(colloquial_map과 같다)."""
    return " ".join(unicodedata.normalize("NFC", text or "").split())


def is_unemployment_context(text: str | None) -> bool:
    """실업급여 문맥인가 — '수급자격'은 실업·구직 표현이 함께 있을 때만 문맥으로 인정한다."""
    q = _norm(text)
    return bool(_CTX.search(q) or (_QUAL.search(q) and _QUAL_CTX.search(q)))


def has_strong_separation_cue(text: str | None) -> bool:
    """이직 사유의 강단서 — 명시 표현, 또는 억제자가 없는 구어 해고(잘렸다·나오지 말라)."""
    q = _norm(text)
    return bool(_STRONG.search(q)
                or (_FIRED.search(q) and not _BODY_CONTEXT.search(q))
                or (_GETOUT.search(q) and not _MOVE_CONTEXT.search(q)))


def is_separation_question(text: str | None) -> bool:
    """실업급여 **이직사유** 질문인가(블록 발동 조건, D3). 실업 문맥 + (강단서 | 약단서 ∧ 자격 질문 ∧ 초점어 없음)."""
    if not is_unemployment_context(text):
        return False
    q = _norm(text)
    return has_strong_separation_cue(q) or bool(_WEAK.search(q) and _ELIG.search(q) and not _FOCUS.search(q))


__all__ = ["is_unemployment_context", "has_strong_separation_cue", "is_separation_question"]
