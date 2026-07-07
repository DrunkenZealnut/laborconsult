"""공개 게시판/대화 응답용 개인정보 비식별화.

`api/index.py`의 공개 엔드포인트(board_recent/search/detail 등)가 import해
질문·답변 텍스트를 마스킹한다.

이 로직을 별도 경량 모듈로 분리한 이유: 회귀 테스트(`test_anonymize.py`)가
`re`에만 의존하는 이 모듈만 import하면 되도록 하기 위함. `api.index`는
jwt·fastapi 등 무거운 의존성 때문에 로컬 테스트 환경에서 import되지 않는다.
"""
from __future__ import annotations

import re

# "씨/님/직책" 앞에 붙어도 사람 이름이 아닌 일반 호칭·대명사·명사.
# 과거 `[가-힣]{2,4}(?=…호칭)`가 "고객님"→"OOO님", "우리 대표"→"OOO 대표"처럼
# 일반어를 이름으로 훼손하던 오탐을 막기 위한 제외 목록.
_NAME_STOPWORDS = frozenset({
    "고객", "손님", "선생", "사장", "회장", "회원", "여러분", "저희", "우리",
    "부모", "사모", "환자", "기사", "담당", "본인", "당사", "귀사", "관계자",
})


def _mask_name(m: "re.Match[str]") -> str:
    """이름 후보가 일반 호칭이면 원복, 실제 이름으로 보이면 OOO로 치환."""
    name = m.group(0)
    return name if name in _NAME_STOPWORDS else "OOO"


_ANON_PATTERNS = [
    # 주민등록번호(6자리-성별1~4+6자리)는 전화번호 패턴보다 먼저 매칭해야 함
    (re.compile(r'\b\d{6}[-\s]?[1-4]\d{6}\b'), '******-*******'),
    # 이름+호칭(씨/님/직책). 일반 호칭명사(고객/사장/…)는 _mask_name이 제외.
    (re.compile(r'[가-힣]{2,4}(?=\s*(?:씨|님|사장|대표|과장|부장|팀장|차장|이사))'), _mask_name),
    # (주)회사명 — 닫는 괄호를 필수로. 과거 `주\)?`가 "해주세요"/"일주일"/"주휴수당"의
    # '주'에도 매치되어 일반 문장을 "(주)OOO"로 훼손하던 오탐 수정.
    # 또한 단독 "회사"는 일반명사("회사 사정/지시")라 "주식회사"로 좁혀 오탐 방지.
    (re.compile(r'(?:\(?\s*주\s*\)\s*|㈜\s*|주식회사\s+)[가-힣A-Za-z]+'), '(주)OOO'),
    (re.compile(r'\d{2,3}[-.\s]?\d{3,4}[-.\s]?\d{4}'), '***-****-****'),
    (re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'), '***@***.***'),
]


def anonymize(text: str) -> str:
    """개인정보 비식별화 — 주민번호·이름+호칭·(주)회사명·전화·이메일 마스킹."""
    if not text:
        return text
    for pattern, replacement in _ANON_PATTERNS:
        text = pattern.sub(replacement, text)
    return text
