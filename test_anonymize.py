#!/usr/bin/env python3
"""공개 게시판 비식별화(app/anonymize.py) 회귀 테스트.

board_recent 조사에서 드러난 `_anonymize` 오탐(일반 문장의 '주'·'회사'·호칭명사를
개인정보로 오인해 훼손)을 확정 케이스로 고정해 재발을 방지한다.

- 오탐(FP) 케이스: 개인정보가 없는 일반 문장 → 원문이 그대로 유지되어야 한다.
- 정탐(TP) 케이스: 실제 식별정보 → 반드시 마스킹되어야 한다.

실행: python3 test_anonymize.py   (전부 통과 시 exit 0, 하나라도 실패 시 exit 1)
"""
from __future__ import annotations

import sys

from app.anonymize import anonymize

_failures: list[str] = []


def _check(label: str, got: str, cond: bool, detail: str) -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {label}: {detail}")
    if not cond:
        _failures.append(f"{label}: {detail} (결과='{got}')")


# ── 오탐 방지: 개인정보 없는 일반 문장은 절대 변형되면 안 된다 ──────────────────
_NO_CHANGE = [
    "해주세요 근로계약서를 작성",       # '주' 오탐(과거 "해(주)OOO")
    "일주일에 40시간 근무합니다",       # '주' 오탐(과거 "일(주)OOO")
    "주휴수당 지급 문의드립니다",        # '주' 오탐(과거 "(주)OOO 문의")
    "연차를 미리 주세요",             # '주' 오탐
    "우리 회사 지시로 야근했습니다",      # 단독 '회사' 오탐
    "회사 사정으로 권고사직 당했어요",     # 단독 '회사' 오탐
    "고객님 응대 중 폭언을 들었습니다",    # 호칭명사 '고객' 오탐(과거 "OOO님")
    "선생님께 상담받고 싶어요",         # 호칭명사 '선생' 오탐
    "사장님이 임금을 체불했습니다",       # 호칭명사 '사장' 오탐
    "우리 대표가 부당해고를 통보",        # 대명사 '우리' 오탐
    "저희 회장님이 지시하셨어요",        # 호칭명사 '회장' 오탐
    "초과근무수당 주 52시간 초과분",      # '주' 오탐
]

for text in _NO_CHANGE:
    out = anonymize(text)
    _check("오탐방지", out, out == text, f"'{text}' → 원문 유지")


# ── 정탐: 실제 식별정보는 반드시 마스킹돼야 한다 (입력, 마스킹 후 포함되어야 할 조각) ──
_MUST_MASK = [
    ("(주)삼성전자에서 근무합니다", "(주)OOO"),
    ("㈜카카오 재직 중입니다", "(주)OOO"),
    ("주식회사 네이버 소속입니다", "(주)OOO"),
    ("주)현대자동차 다닙니다", "(주)OOO"),
    ("홍길동님께 연락 부탁드립니다", "OOO님"),
    ("김철수 과장이 지시했습니다", "OOO 과장"),
    ("박영희 씨가 담당자입니다", "OOO 씨"),
    ("제 번호는 010-1234-5678 입니다", "***-****-****"),
    ("주민번호 900101-1234567 입니다", "******-*******"),
    ("이메일 hong@example.com 로 보내주세요", "***@***.***"),
]

for text, expected_fragment in _MUST_MASK:
    out = anonymize(text)
    masked = expected_fragment in out
    # 원본의 식별 조각(회사명/이름/번호)이 남아있지 않은지도 확인
    _check("정탐", out, masked, f"'{text}' → '{expected_fragment}' 포함")


# ── 부수 회귀: 여는 괄호 중복 버그("(주)삼성"→"((주)OOO")가 없어야 한다 ──────────
_dup = anonymize("(주)삼성전자 재직")
_check("괄호중복", _dup, "((주)" not in _dup, f"'(주)삼성전자 재직' → '{_dup}' (중복괄호 없음)")


if _failures:
    print(f"\n❌ {len(_failures)}건 실패:")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)

print(f"\n✅ 전체 통과 ({len(_NO_CHANGE)} 오탐방지 + {len(_MUST_MASK)} 정탐 + 1 괄호중복)")
sys.exit(0)
