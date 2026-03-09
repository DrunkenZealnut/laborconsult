"""전국 근로복지공단 연락처 — 63개소 (7 지역본부 + 56 지사) 데이터 + 관할구역 매칭"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ComwelOffice:
    name: str                           # 지사명
    phone: str                          # 직통전화
    address: str                        # 주소
    jurisdiction: list[str]             # 관할 구·군·시
    parent: str | None = None           # 상위 지역본부명


# ── 63개소 데이터 (comwel.or.kr 공식) ─────────────────────────────────────────

OFFICES: list[ComwelOffice] = [
    # === 서울 (0~8) ===
    # 0: 서울지역본부
    ComwelOffice(
        name="서울지역본부",
        phone="02-2230-9476",
        address="서울 중구 퇴계로 173, 남산스퀘어",
        jurisdiction=["중구", "종로구", "동대문구"],
    ),
    # 1
    ComwelOffice(
        name="서울강남지사",
        phone="02-3459-7153",
        address="서울 강남구 삼성2동 대종빌딩",
        jurisdiction=["강남구"],
        parent="서울지역본부",
    ),
    # 2
    ComwelOffice(
        name="서울동부지사",
        phone="02-3433-1308",
        address="서울 송파구",
        jurisdiction=["강동구", "광진구", "송파구"],
        parent="서울지역본부",
    ),
    # 3
    ComwelOffice(
        name="서울서부지사",
        phone="02-2077-0107",
        address="서울 마포구 백범로 23, 구프라자",
        jurisdiction=["마포구", "서대문구", "용산구", "은평구"],
        parent="서울지역본부",
    ),
    # 4
    ComwelOffice(
        name="서울남부지사",
        phone="02-2165-3111",
        address="서울 영등포구 버드나루로2길 8",
        jurisdiction=["영등포구", "강서구", "양천구"],
        parent="서울지역본부",
    ),
    # 5
    ComwelOffice(
        name="서울북부지사",
        phone="02-944-8132",
        address="서울 노원구",
        jurisdiction=["성북구", "도봉구", "강북구", "중랑구", "노원구"],
        parent="서울지역본부",
    ),
    # 6
    ComwelOffice(
        name="서울관악지사",
        phone="02-2109-2303",
        address="서울 관악구",
        jurisdiction=["관악구", "구로구", "금천구", "동작구"],
        parent="서울지역본부",
    ),
    # 7
    ComwelOffice(
        name="서울서초지사",
        phone="02-6250-7295",
        address="서울 서초구",
        jurisdiction=["서초구"],
        parent="서울지역본부",
    ),
    # 8
    ComwelOffice(
        name="서울성동지사",
        phone="02-460-3542",
        address="서울 성동구",
        jurisdiction=["성동구"],
        parent="서울지역본부",
    ),

    # === 인천·경기 (9~22) ===
    # 9: 경인지역본부
    ComwelOffice(
        name="경인지역본부",
        phone="032-451-9712",
        address="인천 남동구 미래로 16, 미추홀타워",
        jurisdiction=["남동구", "연수구", "미추홀구", "동구", "중구"],
    ),
    # 10
    ComwelOffice(
        name="인천북부지사",
        phone="032-540-4525",
        address="인천 계양구",
        jurisdiction=["계양구", "부평구", "서구"],
        parent="경인지역본부",
    ),
    # 11
    ComwelOffice(
        name="의정부지사",
        phone="031-828-3121",
        address="경기 의정부시",
        jurisdiction=["의정부시", "동두천시", "양주시", "포천시", "연천군"],
        parent="경인지역본부",
    ),
    # 12
    ComwelOffice(
        name="남양주지사",
        phone="031-524-7005",
        address="경기 남양주시",
        jurisdiction=["남양주시", "구리시"],
        parent="경인지역본부",
    ),
    # 13
    ComwelOffice(
        name="고양지사",
        phone="031-931-0909",
        address="경기 고양시",
        jurisdiction=["고양시"],
        parent="경인지역본부",
    ),
    # 14
    ComwelOffice(
        name="파주지사",
        phone="031-934-1213",
        address="경기 파주시",
        jurisdiction=["파주시"],
        parent="경인지역본부",
    ),
    # 15
    ComwelOffice(
        name="수원지사",
        phone="031-231-4204",
        address="경기 수원시",
        jurisdiction=["수원시"],
        parent="경인지역본부",
    ),
    # 16
    ComwelOffice(
        name="화성지사",
        phone="031-547-4706",
        address="경기 화성시",
        jurisdiction=["화성시"],
        parent="경인지역본부",
    ),
    # 17
    ComwelOffice(
        name="용인지사",
        phone="031-547-3706",
        address="경기 용인시",
        jurisdiction=["용인시"],
        parent="경인지역본부",
    ),
    # 18
    ComwelOffice(
        name="평택지사",
        phone="031-669-8661",
        address="경기 평택시",
        jurisdiction=["평택시"],
        parent="경인지역본부",
    ),
    # 19
    ComwelOffice(
        name="부천지사",
        phone="032-650-0362",
        address="경기 부천시",
        jurisdiction=["부천시"],
        parent="경인지역본부",
    ),
    # 20
    ComwelOffice(
        name="안양지사",
        phone="031-463-0573",
        address="경기 안양시",
        jurisdiction=["안양시", "과천시", "군포시", "의왕시"],
        parent="경인지역본부",
    ),
    # 21
    ComwelOffice(
        name="안산지사",
        phone="031-481-4112",
        address="경기 안산시",
        jurisdiction=["안산시", "시흥시"],
        parent="경인지역본부",
    ),
    # 22
    ComwelOffice(
        name="성남지사",
        phone="031-720-1685",
        address="경기 성남시",
        jurisdiction=["성남시", "하남시", "광주시"],
        parent="경인지역본부",
    ),

    # === 부산 (23~26) ===
    # 23: 부산지역본부
    ComwelOffice(
        name="부산지역본부",
        phone="051-661-0187",
        address="부산 동구 중앙대로 276, 아모레퍼시픽빌딩",
        jurisdiction=["동구", "중구", "영도구", "남구", "수영구"],
    ),
    # 24
    ComwelOffice(
        name="부산동부지사",
        phone="051-550-3263",
        address="부산 해운대구",
        jurisdiction=["해운대구", "금정구", "기장군", "연제구"],
        parent="부산지역본부",
    ),
    # 25
    ComwelOffice(
        name="부산북부지사",
        phone="051-320-8117",
        address="부산 북구",
        jurisdiction=["북구", "사상구", "강서구", "금정구"],
        parent="부산지역본부",
    ),
    # 26
    ComwelOffice(
        name="부산중부지사",
        phone="051-801-4163",
        address="부산 사하구",
        jurisdiction=["사하구", "서구", "동래구", "부산진구"],
        parent="부산지역본부",
    ),

    # === 대구·경북 (27~34) ===
    # 27: 대구지역본부
    ComwelOffice(
        name="대구지역본부",
        phone="053-601-7302",
        address="대구 중구 달구벌대로 2195",
        jurisdiction=["중구", "동구", "남구", "수성구", "달성군"],
    ),
    # 28
    ComwelOffice(
        name="대구북부지사",
        phone="053-607-4215",
        address="대구 북구",
        jurisdiction=["북구"],
        parent="대구지역본부",
    ),
    # 29
    ComwelOffice(
        name="대구서부지사",
        phone="053-609-5317",
        address="대구 서구",
        jurisdiction=["서구", "달서구"],
        parent="대구지역본부",
    ),
    # 30
    ComwelOffice(
        name="포항지사",
        phone="054-288-5207",
        address="경북 포항시",
        jurisdiction=["포항시", "영덕군", "울진군"],
        parent="대구지역본부",
    ),
    # 31
    ComwelOffice(
        name="구미지사",
        phone="054-479-9183",
        address="경북 구미시 백산로 112",
        jurisdiction=["구미시", "김천시", "칠곡군", "성주군", "고령군"],
        parent="대구지역본부",
    ),
    # 32
    ComwelOffice(
        name="경산지사",
        phone="053-819-2114",
        address="경북 경산시",
        jurisdiction=["경산시", "청도군", "영천시"],
        parent="대구지역본부",
    ),
    # 33
    ComwelOffice(
        name="영주지사",
        phone="054-639-0168",
        address="경북 영주시",
        jurisdiction=["영주시", "봉화군", "울진군", "영양군"],
        parent="대구지역본부",
    ),
    # 34
    ComwelOffice(
        name="안동지사",
        phone="054-850-5428",
        address="경북 안동시",
        jurisdiction=["안동시", "예천군", "의성군", "청송군"],
        parent="대구지역본부",
    ),

    # === 광주·전라 (35~42) ===
    # 35: 광주지역본부
    ComwelOffice(
        name="광주지역본부",
        phone="062-608-0385",
        address="광주 서구 천변좌로 268",
        jurisdiction=["서구", "남구", "동구", "북구"],
    ),
    # 36
    ComwelOffice(
        name="광산지사",
        phone="062-608-0475",
        address="광주 광산구",
        jurisdiction=["광산구", "화순군", "곡성군", "구례군", "담양군"],
        parent="광주지역본부",
    ),
    # 37
    ComwelOffice(
        name="전주지사",
        phone="063-240-8119",
        address="전북 전주시",
        jurisdiction=["전주시", "완주군", "진안군", "무주군", "장수군"],
        parent="광주지역본부",
    ),
    # 38
    ComwelOffice(
        name="익산지사",
        phone="063-839-0131",
        address="전북 익산시",
        jurisdiction=["익산시", "김제시"],
        parent="광주지역본부",
    ),
    # 39
    ComwelOffice(
        name="군산지사",
        phone="063-450-0141",
        address="전북 군산시",
        jurisdiction=["군산시", "부안군", "정읍시", "고창군"],
        parent="광주지역본부",
    ),
    # 40
    ComwelOffice(
        name="목포지사",
        phone="061-240-0123",
        address="전남 목포시",
        jurisdiction=["목포시", "무안군", "신안군", "영암군", "해남군", "진도군", "완도군", "강진군", "장흥군"],
        parent="광주지역본부",
    ),
    # 41
    ComwelOffice(
        name="여수지사",
        phone="061-680-0154",
        address="전남 여수시",
        jurisdiction=["여수시", "광양시"],
        parent="광주지역본부",
    ),
    # 42
    ComwelOffice(
        name="순천지사",
        phone="061-805-0204",
        address="전남 순천시",
        jurisdiction=["순천시", "보성군", "고흥군"],
        parent="광주지역본부",
    ),

    # === 대전·충청 (43~50) ===
    # 43: 대전지역본부
    ComwelOffice(
        name="대전지역본부",
        phone="042-870-9163",
        address="대전 서구 한밭대로 809, 사학연금회관",
        jurisdiction=["서구", "중구", "대덕구"],
    ),
    # 44
    ComwelOffice(
        name="대전동부지사",
        phone="042-722-4112",
        address="대전 동구",
        jurisdiction=["동구"],
        parent="대전지역본부",
    ),
    # 45
    ComwelOffice(
        name="대전서부지사",
        phone="042-820-5443",
        address="대전 유성구",
        jurisdiction=["유성구", "세종시"],
        parent="대전지역본부",
    ),
    # 46
    ComwelOffice(
        name="청주지사",
        phone="043-229-5044",
        address="충북 청주시",
        jurisdiction=["청주시", "증평군", "진천군", "괴산군", "보은군", "옥천군", "영동군"],
        parent="대전지역본부",
    ),
    # 47
    ComwelOffice(
        name="천안지사",
        phone="041-629-5103",
        address="충남 천안시",
        jurisdiction=["천안시", "아산시", "당진시", "예산군", "홍성군"],
        parent="대전지역본부",
    ),
    # 48
    ComwelOffice(
        name="충주지사",
        phone="043-840-0365",
        address="충북 충주시",
        jurisdiction=["충주시", "제천시", "단양군"],
        parent="대전지역본부",
    ),
    # 49
    ComwelOffice(
        name="보령지사",
        phone="041-939-2255",
        address="충남 보령시",
        jurisdiction=["보령시", "서천군", "부여군", "청양군", "논산시", "금산군", "계룡시"],
        parent="대전지역본부",
    ),
    # 50
    ComwelOffice(
        name="서산지사",
        phone="041-419-8176",
        address="충남 서산시",
        jurisdiction=["서산시", "태안군"],
        parent="대전지역본부",
    ),

    # === 울산·경남 (51~56) ===
    # 51
    ComwelOffice(
        name="울산지사",
        phone="052-226-4257",
        address="울산광역시",
        jurisdiction=["울산 전역"],
    ),
    # 52
    ComwelOffice(
        name="창원지사",
        phone="055-268-0102",
        address="경남 창원시",
        jurisdiction=["창원시", "함안군", "의령군"],
    ),
    # 53
    ComwelOffice(
        name="양산지사",
        phone="055-380-8466",
        address="경남 양산시",
        jurisdiction=["양산시", "밀양시"],
    ),
    # 54
    ComwelOffice(
        name="김해지사",
        phone="055-723-8011",
        address="경남 김해시",
        jurisdiction=["김해시", "거제시"],
    ),
    # 55
    ComwelOffice(
        name="진주지사",
        phone="055-760-0154",
        address="경남 진주시",
        jurisdiction=["진주시", "사천시", "하동군", "산청군", "합천군", "거창군", "함양군"],
    ),
    # 56
    ComwelOffice(
        name="통영지사",
        phone="055-640-7118",
        address="경남 통영시",
        jurisdiction=["통영시", "고성군", "남해군"],
    ),

    # === 강원 (57~61) ===
    # 57: 강원지역본부
    ComwelOffice(
        name="강원지역본부",
        phone="033-749-2378",
        address="강원 원주시",
        jurisdiction=["원주시", "횡성군"],
    ),
    # 58
    ComwelOffice(
        name="춘천지사",
        phone="033-240-6165",
        address="강원 춘천시",
        jurisdiction=["춘천시", "화천군", "양구군", "인제군", "홍천군"],
        parent="강원지역본부",
    ),
    # 59
    ComwelOffice(
        name="강릉지사",
        phone="033-640-9108",
        address="강원 강릉시",
        jurisdiction=["강릉시", "동해시", "삼척시", "속초시", "양양군", "고성군"],
        parent="강원지역본부",
    ),
    # 60
    ComwelOffice(
        name="태백지사",
        phone="033-550-0593",
        address="강원 태백시",
        jurisdiction=["태백시", "정선군"],
        parent="강원지역본부",
    ),
    # 61
    ComwelOffice(
        name="영월지사",
        phone="033-371-6120",
        address="강원 영월군",
        jurisdiction=["영월군", "평창군"],
        parent="강원지역본부",
    ),

    # === 제주 (62) ===
    # 62
    ComwelOffice(
        name="제주지사",
        phone="064-754-6703",
        address="제주특별자치도",
        jurisdiction=["제주 전역"],
    ),
]


# ── 관할구역 매핑 ─────────────────────────────────────────────────────────────

REGION_MAP: dict[str, int] = {
    # 서울 (광역 → 서울지역본부)
    "서울": 0,
    "종로구": 0, "종로": 0, "동대문구": 0, "동대문": 0,
    # 서울 구별 매핑
    "강남구": 1, "강남": 1,
    "강동구": 2, "강동": 2, "광진구": 2, "광진": 2, "송파구": 2, "송파": 2,
    "마포구": 3, "마포": 3, "서대문구": 3, "서대문": 3,
    "용산구": 3, "용산": 3, "은평구": 3, "은평": 3,
    "영등포구": 4, "영등포": 4, "강서구": 4, "양천구": 4, "양천": 4,
    "성북구": 5, "성북": 5, "도봉구": 5, "도봉": 5, "강북구": 5, "강북": 5,
    "중랑구": 5, "중랑": 5, "노원구": 5, "노원": 5,
    "관악구": 6, "관악": 6, "구로구": 6, "구로": 6,
    "금천구": 6, "금천": 6, "동작구": 6, "동작": 6,
    "서초구": 7, "서초": 7,
    "성동구": 8, "성동": 8,

    # 인천·경기
    "인천": 9,
    "계양구": 10, "계양": 10, "부평구": 10, "부평": 10,
    "의정부": 11, "동두천": 11, "양주": 11, "포천": 11, "연천": 11,
    "남양주": 12, "구리": 12,
    "고양": 13, "일산": 13,
    "파주": 14,
    "수원": 15,
    "화성": 16, "동탄": 16,
    "용인": 17, "기흥": 17, "수지": 17,
    "평택": 18,
    "부천": 19,
    "안양": 20, "과천": 20, "군포": 20, "의왕": 20,
    "안산": 21, "시흥": 21,
    "성남": 22, "분당": 22, "판교": 22, "하남": 22,
    "경기광주": 22,

    # 부산
    "부산": 23,
    "해운대": 24, "해운대구": 24, "기장": 24,
    "사상구": 25, "사상": 25,
    "사하구": 26, "사하": 26,

    # 대구·경북
    "대구": 27,
    "수성구": 27, "수성": 27, "달성군": 27, "달성": 27,
    "달서구": 29, "달서": 29,
    "포항": 30, "영덕": 30,
    "구미": 31, "김천": 31, "칠곡": 31,
    "경산": 32, "청도": 32, "영천": 32,
    "영주": 33, "봉화": 33,
    "안동": 34, "예천": 34, "의성": 34,

    # 광주·전라
    "광주": 35,
    "광산구": 36, "광산": 36, "화순": 36, "곡성": 36, "담양": 36,
    "전주": 37, "완주": 37,
    "익산": 38, "김제": 38,
    "군산": 39, "정읍": 39, "고창": 39, "부안": 39,
    "목포": 40, "무안": 40, "영암": 40, "해남": 40,
    "여수": 41, "광양": 41,
    "순천": 42, "보성": 42, "고흥": 42,

    # 대전·충청
    "대전": 43,
    "세종": 45, "유성구": 45, "유성": 45,
    "청주": 46, "증평": 46, "진천": 46,
    "천안": 47, "아산": 47, "당진": 47,
    "충주": 48, "제천": 48,
    "보령": 49, "서천": 49, "논산": 49, "금산": 49, "계룡": 49, "부여": 49,
    "서산": 50, "태안": 50,

    # 울산·경남
    "울산": 51,
    "창원": 52, "마산": 52, "진해": 52, "함안": 52,
    "양산": 53, "밀양": 53,
    "김해": 54, "거제": 54,
    "진주": 55, "사천": 55, "하동": 55, "산청": 55, "합천": 55, "거창": 55,
    "통영": 56, "고성": 56, "남해": 56,

    # 강원
    "강원": 57, "원주": 57,
    "춘천": 58, "화천": 58, "인제": 58, "홍천": 58,
    "강릉": 59, "동해": 59, "삼척": 59, "속초": 59,
    "태백": 60, "정선": 60,
    "영월": 61, "평창": 61,

    # 제주
    "제주": 62, "서귀포": 62,

    # 도 이름 → 대표 지사
    "경기": 9,
    "충북": 46,
    "충남": 47,
    "전북": 37,
    "전남": 40,
    "경북": 27,
    "경남": 52,
}


# ── 조회 함수 ─────────────────────────────────────────────────────────────────

_METRO_KEYWORDS = frozenset([
    "서울", "부산", "대구", "인천", "광주", "대전", "세종", "울산",
    "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
])


def find_office(query: str) -> ComwelOffice | None:
    """질문 텍스트에서 지역명을 추출하여 관할 근로복지공단 지사 반환.

    구·군·시 단위 키워드를 광역시·도 이름보다 우선 매칭합니다.
    """
    metro_match = None
    for keyword, idx in REGION_MAP.items():
        if keyword in query:
            if keyword not in _METRO_KEYWORDS:
                return OFFICES[idx]
            elif metro_match is None:
                metro_match = idx
    if metro_match is not None:
        return OFFICES[metro_match]
    return None


def format_office(office: ComwelOffice) -> str:
    """근로복지공단 지사 정보를 답변 삽입용 텍스트로 포맷."""
    lines = [
        f"📍 근로복지공단 {office.name}",
        f"   전화: {office.phone}",
        f"   대표전화: 1588-0075",
        f"   주소: {office.address}",
        f"   관할: {', '.join(office.jurisdiction)}",
    ]
    if office.parent:
        lines.append(f"   (상위: {office.parent})")
    return "\n".join(lines)


def format_office_guide() -> str:
    """근로복지공단 검색 안내 (지역 미명시 시 사용 — 63개 전체 나열 대신)."""
    return (
        "관할 근로복지공단 지사를 찾으시려면:\n"
        "- 근로복지공단 고객센터: 1588-0075 (평일 09:00~18:00)\n"
        "- 지사 찾기: https://www.comwel.or.kr/comwel/intr/srch/srch.jsp\n"
        "- 지역명을 알려주시면 관할 지사를 안내해 드립니다."
    )
