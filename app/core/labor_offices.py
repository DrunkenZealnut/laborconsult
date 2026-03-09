"""전국 노동위원회 연락처 — 14개 기관 데이터 + 관할구역 매칭"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LaborCommission:
    name: str
    phone: str
    fax: str
    address: str
    jurisdiction: list[str]


# ── 14개 기관 데이터 (nlrc.go.kr 공식) ────────────────────────────────────────

COMMISSIONS: list[LaborCommission] = [
    # 0: 중앙
    LaborCommission(
        name="중앙노동위원회",
        phone="044-202-8226",
        fax="0503-8803-0729",
        address="세종시 한누리대로 422, 11동 3~4층",
        jurisdiction=["전국", "재심"],
    ),
    # 1: 서울
    LaborCommission(
        name="서울지방노동위원회",
        phone="02-3218-6070",
        fax="02-2069-0630",
        address="서울 영등포구 문래로20길 56",
        jurisdiction=["서울"],
    ),
    # 2: 부산
    LaborCommission(
        name="부산지방노동위원회",
        phone="051-559-3700",
        fax="051-529-7868",
        address="부산 금정구 공단서로 12, 합동청사 4층",
        jurisdiction=["부산"],
    ),
    # 3: 경기
    LaborCommission(
        name="경기지방노동위원회",
        phone="031-259-5003",
        fax="0503-8803-1206",
        address="경기 수원시 영통구 청명로 141, 3층",
        jurisdiction=["경기"],
    ),
    # 4: 인천
    LaborCommission(
        name="인천지방노동위원회",
        phone="032-430-3100",
        fax="032-430-3118",
        address="인천 미추홀구 석정로 239, 6~7층",
        jurisdiction=["인천"],
    ),
    # 5: 강원
    LaborCommission(
        name="강원지방노동위원회",
        phone="033-269-3414",
        fax="033-256-0362",
        address="강원 춘천시 후석로440번길 64, 3층",
        jurisdiction=["강원"],
    ),
    # 6: 충북
    LaborCommission(
        name="충북지방노동위원회",
        phone="043-299-1260",
        fax="043-285-6995",
        address="충북 청주시 서원구 1순환로 1047, 5층",
        jurisdiction=["충북"],
    ),
    # 7: 충남·대전·세종
    LaborCommission(
        name="충남지방노동위원회",
        phone="042-520-8070",
        fax="042-483-3196",
        address="대전 서구 청사로 189, 정부대전청사 2동 12층",
        jurisdiction=["대전", "충남", "세종"],
    ),
    # 8: 전북
    LaborCommission(
        name="전북지방노동위원회",
        phone="063-240-1600",
        fax="063-240-1605",
        address="전북 전주시 덕진구 건산로 251",
        jurisdiction=["전북"],
    ),
    # 9: 전남·광주
    LaborCommission(
        name="전남지방노동위원회",
        phone="062-975-6100",
        fax="062-975-6160",
        address="광주 북구 첨단과기로208번길 43, 7층",
        jurisdiction=["광주", "전남"],
    ),
    # 10: 경북·대구
    LaborCommission(
        name="경북지방노동위원회",
        phone="053-667-6520",
        fax="053-767-6539",
        address="대구 수성구 동대구로 231, 4층",
        jurisdiction=["대구", "경북"],
    ),
    # 11: 경남
    LaborCommission(
        name="경남지방노동위원회",
        phone="055-239-8020",
        fax="055-266-4622",
        address="경남 창원시 의창구 창원대로363번길 22-47, 10층",
        jurisdiction=["경남"],
    ),
    # 12: 울산
    LaborCommission(
        name="울산지방노동위원회",
        phone="052-208-0001",
        fax="052-256-0081",
        address="울산 남구 두왕로 318, 4층",
        jurisdiction=["울산"],
    ),
    # 13: 제주
    LaborCommission(
        name="제주지방노동위원회",
        phone="064-710-7990",
        fax="064-710-7999",
        address="제주시 청사로 59, 5층",
        jurisdiction=["제주"],
    ),
]

# ── 지역명 → COMMISSIONS 인덱스 매핑 ────────────────────────────────────────

REGION_MAP: dict[str, int] = {
    # 서울 (1)
    "서울": 1, "강남": 1, "서초": 1, "마포": 1, "영등포": 1, "송파": 1,
    "강서": 1, "구로": 1, "용산": 1, "종로": 1, "성동": 1, "관악": 1,
    "동작": 1, "광진": 1, "노원": 1, "도봉": 1, "은평": 1,
    # 부산 (2)
    "부산": 2, "해운대": 2, "사상": 2, "금정": 2, "사하": 2,
    # 경기 (3)
    "경기": 3, "수원": 3, "성남": 3, "용인": 3, "고양": 3, "안산": 3,
    "안양": 3, "파주": 3, "화성": 3, "시흥": 3, "평택": 3, "김포": 3,
    "광명": 3, "하남": 3, "이천": 3, "오산": 3, "군포": 3, "의왕": 3,
    "양주": 3, "포천": 3, "여주": 3, "동두천": 3, "과천": 3, "구리": 3,
    "남양주": 3, "의정부": 3, "부천": 3,
    # 인천 (4)
    "인천": 4, "미추홀": 4, "부평": 4, "남동": 4, "연수": 4, "계양": 4,
    # 강원 (5)
    "강원": 5, "춘천": 5, "원주": 5, "강릉": 5, "속초": 5, "동해": 5,
    # 충북 (6)
    "충북": 6, "청주": 6, "충주": 6, "제천": 6,
    # 충남·대전·세종 (7)
    "충남": 7, "대전": 7, "세종": 7, "천안": 7, "아산": 7, "논산": 7,
    "서산": 7, "당진": 7, "홍성": 7, "공주": 7, "보령": 7,
    # 전북 (8)
    "전북": 8, "전주": 8, "익산": 8, "군산": 8, "정읍": 8, "남원": 8,
    # 전남·광주 (9)
    "전남": 9, "광주": 9, "목포": 9, "순천": 9, "여수": 9, "나주": 9,
    # 경북·대구 (10)
    "경북": 10, "대구": 10, "포항": 10, "구미": 10, "경산": 10, "안동": 10,
    "김천": 10, "영주": 10, "상주": 10, "경주": 10,
    # 경남 (11)
    "경남": 11, "창원": 11, "김해": 11, "진주": 11, "양산": 11, "거제": 11,
    "통영": 11, "사천": 11, "밀양": 11,
    # 울산 (12)
    "울산": 12,
    # 제주 (13)
    "제주": 13, "서귀포": 13,
}


# ── 조회 함수 ────────────────────────────────────────────────────────────────

def find_commission(query: str) -> LaborCommission | None:
    """질문 텍스트에서 지역명을 추출하여 관할 노동위원회 반환."""
    for keyword, idx in REGION_MAP.items():
        if keyword in query:
            return COMMISSIONS[idx]
    return None


def format_commission(comm: LaborCommission) -> str:
    """노동위원회 정보를 답변 삽입용 텍스트로 포맷."""
    return (
        f"📍 {comm.name}\n"
        f"   전화: {comm.phone}\n"
        f"   팩스: {comm.fax}\n"
        f"   주소: {comm.address}\n"
        f"   관할: {', '.join(comm.jurisdiction)}"
    )


def format_all_commissions() -> str:
    """전국 노동위원회 요약 목록 (지역 미명시 시 사용)."""
    lines = ["전국 노동위원회 연락처:"]
    for c in COMMISSIONS:
        lines.append(f"- {c.name}: {c.phone} ({', '.join(c.jurisdiction)})")
    return "\n".join(lines)
