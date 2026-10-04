"""사건번호 정규화·대조 — 단일 출처 (effective-law-and-graph-precedents D5).

수집 스크립트(`fetch_court_precedents`)와 답변 경로(`legal_api`)가 **같은 함수**를 쓴다.
사본을 두면 한쪽만 고쳐지는 사각이 생긴다 — 이 저장소의 반복된 실패 클래스다(NFD
post_id 수정이 contextual 업로더에 3.5개월간 전파되지 않았던 일 등). 동일성은
`test_effective_law.py`가 `is`로 고정한다.

표준 라이브러리만 쓴다 — `fetch_court_precedents`는 import 시 `load_dotenv(override=True)`를
실행하므로 답변 경로가 그 모듈을 import하면 안 된다.
"""

from __future__ import annotations

import re
import unicodedata


def normalize_case_no(case_no: str) -> str:
    """비교용 정규화 — NFC 통일 + 공백 제거.

    macOS 파일명은 NFD로 저장되므로 NFC 정규화가 없으면 '다'(U+B2E4)와
    'ᄃ+ᅡ'(U+1103 U+1161)가 다른 문자로 취급돼 매칭이 조용히 실패한다.
    """
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", case_no or ""))


def detail_matches(detail_case_no: str, wanted: str) -> bool:
    """상세 응답의 사건번호가 요청 사건을 포함하는지.

    병합 사건은 사건번호가 '2000다51919, 51926'처럼 온다. 엄격 일치만 보면
    실제로 맞는 판례를 버리게 된다.
    """
    # 병합 사건은 '2015다221903(본소), 2015다221910(반소)'처럼 괄호 주기가 붙는다.
    detail = re.sub(r"\([^)]*\)", "", normalize_case_no(detail_case_no))
    want = re.sub(r"\([^)]*\)", "", normalize_case_no(wanted))
    if detail == want:
        return True
    # '2000다51919,51926' → 앞 조각의 연도·부호를 뒤 번호에 붙여 비교
    parts = [p for p in detail.split(",") if p]
    if not parts:
        return False
    if want in parts:
        return True
    prefix = re.match(r"^(\d{2,4}[가-힣]{1,4})", parts[0])
    if prefix:
        expanded = {parts[0]} | {
            p if re.match(r"^\d{2,4}[가-힣]", p) else prefix.group(1) + p
            for p in parts[1:]
        }
        return want in expanded
    return False
