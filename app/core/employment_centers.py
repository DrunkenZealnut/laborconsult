"""전국 고용센터 연락처 — 133개 센터(하부 센터 포함) 데이터 + 관할구역 매칭"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EmploymentCenter:
    name: str
    phone: str
    address: str
    jurisdiction: list[str]
    parent: str | None = None
    homepage: str | None = None


# ── 133개 센터 데이터 (work24.go.kr 공식, 2026-03 기준) ──────────────────────

CENTERS: list[EmploymentCenter] = [
    # === 서울 (0~10) ===
    # 0
    EmploymentCenter(
        name="서울고용센터",
        phone="02-2004-7301",
        address="서울 중구 삼일대로 363",
        jurisdiction=["중구", "종로구", "동대문구"],
    ),
    # 1
    EmploymentCenter(
        name="서초고용센터",
        phone="02-580-4900",
        address="서울 서초구 반포대로",
        jurisdiction=["서초구"],
    ),
    # 2
    EmploymentCenter(
        name="서울강남고용센터",
        phone="02-3468-4794",
        address="서울 강남구 테헤란로 410 금강타워",
        jurisdiction=["강남구"],
    ),
    # 3
    EmploymentCenter(
        name="서울동부고용센터",
        phone="02-2142-8924",
        address="서울 송파구 중대로 IT벤처타워",
        jurisdiction=["송파구", "강동구"],
    ),
    # 4
    EmploymentCenter(
        name="성동광진고용센터",
        phone="02-2047-9900",
        address="서울 성동구 연무장길 76",
        jurisdiction=["성동구", "광진구"],
    ),
    # 5
    EmploymentCenter(
        name="서울서부고용센터",
        phone="02-2077-6000",
        address="서울 마포구 마포대로",
        jurisdiction=["마포구", "서대문구", "용산구", "은평구"],
    ),
    # 6
    EmploymentCenter(
        name="서울강서고용센터",
        phone="02-2063-6700",
        address="서울 강서구 양천로57길",
        jurisdiction=["강서구"],
    ),
    # 7
    EmploymentCenter(
        name="서울남부고용센터",
        phone="02-2639-2300",
        address="서울 영등포구 선유로 120",
        jurisdiction=["영등포구", "양천구"],
    ),
    # 8
    EmploymentCenter(
        name="서울북부고용센터",
        phone="02-2171-1700",
        address="서울 노원구 노해로 450",
        jurisdiction=["노원구", "도봉구", "중랑구"],
    ),
    # 9
    EmploymentCenter(
        name="강북성북고용센터",
        phone="02-3406-0900",
        address="서울 강북구 도봉로",
        jurisdiction=["강북구", "성북구"],
    ),
    # 10
    EmploymentCenter(
        name="서울관악고용센터",
        phone="02-3282-9200",
        address="서울 구로구 디지털로34길",
        jurisdiction=["관악구", "구로구", "금천구", "동작구"],
    ),

    # === 부산 (11~14) ===
    # 11
    EmploymentCenter(
        name="부산고용센터",
        phone="051-860-1919",
        address="부산 부산진구 중앙대로 993",
        jurisdiction=["부산진구", "연제구", "영도구", "남구"],
    ),
    # 12
    EmploymentCenter(
        name="부산사하고용센터",
        phone="051-520-4900",
        address="부산 사하구 낙동남로 1400",
        jurisdiction=["사하구"],
    ),
    # 13
    EmploymentCenter(
        name="부산동부고용센터",
        phone="051-760-7100",
        address="부산 수영구 수영로 676",
        jurisdiction=["동래구", "금정구", "수영구", "해운대구", "기장군"],
    ),
    # 14
    EmploymentCenter(
        name="부산북부고용센터",
        phone="051-330-9900",
        address="부산 북구 화명대로 9",
        jurisdiction=["사상구"],
    ),

    # === 대구 (15~19) ===
    # 15
    EmploymentCenter(
        name="대구고용센터",
        phone="053-667-6000",
        address="대구 수성구 동대구로 392",
        jurisdiction=["수성구"],
    ),
    # 16
    EmploymentCenter(
        name="대구강북고용센터",
        phone="053-606-8000",
        address="대구 북구 칠곡중앙대로 318",
        jurisdiction=["군위군"],
    ),
    # 17
    EmploymentCenter(
        name="대구동부고용센터",
        phone="053-667-6900",
        address="대구 동구 아양로",
        jurisdiction=["동구"],
    ),
    # 18
    EmploymentCenter(
        name="대구서부고용센터",
        phone="053-605-6500",
        address="대구 서구 서대구로 9",
        jurisdiction=["달서구"],
    ),
    # 19
    EmploymentCenter(
        name="대구달성고용센터",
        phone="053-605-9510",
        address="대구 달성군 논공읍 논공중앙로34길 1",
        jurisdiction=["달성군", "고령군"],
    ),

    # === 인천 (20~23) ===
    # 20
    EmploymentCenter(
        name="인천고용센터",
        phone="032-460-4701",
        address="인천 남동구 문화로",
        jurisdiction=["연수구", "남동구", "옹진군"],
    ),
    # 21
    EmploymentCenter(
        name="인천북부고용센터",
        phone="032-540-5641",
        address="인천 계양구 장제로 804",
        jurisdiction=["부평구", "계양구"],
    ),
    # 22
    EmploymentCenter(
        name="인천서부고용센터",
        phone="032-540-2001",
        address="인천 서구 이음1로 389",
        jurisdiction=["서구"],
    ),
    # 23
    EmploymentCenter(
        name="강화고용센터",
        phone="032-540-7990",
        address="인천 강화군 강화읍 강화대로",
        jurisdiction=["강화군"],
        parent="인천고용센터",
    ),

    # === 광주 (24~25) ===
    # 24
    EmploymentCenter(
        name="광주고용센터",
        phone="062-609-8500",
        address="광주 북구 금남로",
        jurisdiction=["동구", "서구", "남구", "북구", "나주시", "담양군", "곡성군", "구례군", "장성군"],
    ),
    # 25
    EmploymentCenter(
        name="광주광산고용센터",
        phone="062-960-3200",
        address="광주 광산구 하남대로",
        jurisdiction=["광산구", "함평군"],
    ),

    # === 대전 (26) ===
    # 26
    EmploymentCenter(
        name="대전고용센터",
        phone="042-480-6000",
        address="대전 서구 문정로 56",
        jurisdiction=["대전광역시"],
    ),

    # === 세종 (27) ===
    # 27
    EmploymentCenter(
        name="세종고용센터",
        phone="044-865-3219",
        address="세종 조치원읍 터미널안길",
        jurisdiction=["세종시"],
    ),

    # === 울산 (28) ===
    # 28
    EmploymentCenter(
        name="울산고용센터",
        phone="052-228-1919",
        address="울산 남구 화합로 106",
        jurisdiction=["울산광역시"],
    ),

    # === 충남 (29~41) ===
    # 29
    EmploymentCenter(
        name="천안고용센터",
        phone="041-620-7400",
        address="충남 천안시 서북구 동서대로",
        jurisdiction=["천안시"],
    ),
    # 30
    EmploymentCenter(
        name="아산고용센터",
        phone="041-570-5500",
        address="충남 아산시 배방읍 배방로 5",
        jurisdiction=["아산시"],
    ),
    # 31
    EmploymentCenter(
        name="당진고용센터",
        phone="041-620-7456",
        address="충남 당진시 당진중앙1로 59",
        jurisdiction=["당진시"],
    ),
    # 32
    EmploymentCenter(
        name="예산고용센터",
        phone="041-620-9511",
        address="충남 예산군 예산읍 군청로1길",
        jurisdiction=["예산군"],
        parent="천안고용센터",
    ),
    # 33
    EmploymentCenter(
        name="서산고용센터",
        phone="041-661-5600",
        address="충남 서산시 호수공원1로",
        jurisdiction=["서산시"],
    ),
    # 34
    EmploymentCenter(
        name="태안고용센터",
        phone="041-661-5691",
        address="충남 태안군 태안읍 동백로",
        jurisdiction=["태안군"],
        parent="서산고용센터",
    ),
    # 35
    EmploymentCenter(
        name="논산고용센터",
        phone="041-731-8600",
        address="충남 논산시 시민로210번길 14-8",
        jurisdiction=["논산시", "계룡시"],
    ),
    # 36
    EmploymentCenter(
        name="공주고용센터",
        phone="041-851-8501",
        address="충남 공주시 번영1로 46",
        jurisdiction=["공주시"],
    ),
    # 37
    EmploymentCenter(
        name="금산고용센터",
        phone="041-731-8690",
        address="충남 금산군 금산읍 인삼로 70",
        jurisdiction=["금산군"],
        parent="대전고용센터",
    ),
    # 38
    EmploymentCenter(
        name="보령고용센터",
        phone="041-930-6200",
        address="충남 보령시 보령남로 28",
        jurisdiction=["보령시"],
    ),
    # 39
    EmploymentCenter(
        name="부여고용센터",
        phone="041-930-6236",
        address="충남 부여군 부여읍 신동엽길",
        jurisdiction=["부여군"],
        parent="보령고용센터",
    ),
    # 40
    EmploymentCenter(
        name="서천고용센터",
        phone="041-930-6244",
        address="충남 서천군 서천읍 충절로109번길",
        jurisdiction=["서천군"],
        parent="보령고용센터",
    ),
    # 41
    EmploymentCenter(
        name="홍성고용센터",
        phone="041-930-6200",
        address="충남 홍성군 홍성읍 법원로",
        jurisdiction=["홍성군", "청양군"],
    ),

    # === 경기 (42~70) ===
    # 42
    EmploymentCenter(
        name="수원고용센터",
        phone="031-231-7864",
        address="경기 수원시 팔달구 경수대로 584",
        jurisdiction=["수원시"],
    ),
    # 43
    EmploymentCenter(
        name="용인고용센터",
        phone="031-289-2210",
        address="경기 용인시 기흥구 강남로 3",
        jurisdiction=["용인시"],
    ),
    # 44
    EmploymentCenter(
        name="화성고용센터",
        phone="031-290-0800",
        address="경기 화성시 봉담읍 동화길",
        jurisdiction=["화성시"],
    ),
    # 45
    EmploymentCenter(
        name="성남고용센터",
        phone="031-739-3177",
        address="경기 성남시 분당구 성남대로 146",
        jurisdiction=["성남시"],
    ),
    # 46
    EmploymentCenter(
        name="하남고용센터",
        phone="031-730-7000",
        address="경기 하남시 미사강변대로 52",
        jurisdiction=["하남시"],
    ),
    # 47
    EmploymentCenter(
        name="경기광주고용센터",
        phone="031-799-2760",
        address="경기 광주시 광주대로",
        jurisdiction=["광주시"],
    ),
    # 48
    EmploymentCenter(
        name="양평고용센터",
        phone="031-740-6780",
        address="경기 양평군 양평읍 중앙로111번길",
        jurisdiction=["양평군"],
        parent="경기광주고용센터",
    ),
    # 49
    EmploymentCenter(
        name="여주고용센터",
        phone="031-740-6790",
        address="경기 여주시 여흥로109번길",
        jurisdiction=["여주시"],
    ),
    # 50
    EmploymentCenter(
        name="이천고용센터",
        phone="031-644-3820",
        address="경기 이천시 이섭대천로 1309",
        jurisdiction=["이천시"],
    ),
    # 51
    EmploymentCenter(
        name="안양고용센터",
        phone="031-463-0700",
        address="경기 안양시 만안구 안양로",
        jurisdiction=["안양시", "과천시"],
    ),
    # 52
    EmploymentCenter(
        name="의왕고용센터",
        phone="031-463-7460",
        address="경기 의왕시 안양판교로",
        jurisdiction=["의왕시"],
        parent="안양고용센터",
    ),
    # 53
    EmploymentCenter(
        name="군포고용센터",
        phone="031-463-7610",
        address="경기 군포시 군포로 522",
        jurisdiction=["군포시"],
        parent="안양고용센터",
    ),
    # 54
    EmploymentCenter(
        name="광명고용센터",
        phone="02-2680-1500",
        address="경기 광명시 시청로",
        jurisdiction=["광명시"],
    ),
    # 55
    EmploymentCenter(
        name="안산고용센터",
        phone="031-412-6600",
        address="경기 안산시 단원구 원고잔로 11",
        jurisdiction=["안산시"],
    ),
    # 56
    EmploymentCenter(
        name="시흥고용센터",
        phone="031-496-1900",
        address="경기 시흥시 마유로418번길",
        jurisdiction=["시흥시"],
    ),
    # 57
    EmploymentCenter(
        name="평택고용센터",
        phone="031-646-1205",
        address="경기 평택시 경기대로 1194",
        jurisdiction=["평택시"],
    ),
    # 58
    EmploymentCenter(
        name="안성고용센터",
        phone="031-686-1705",
        address="경기 안성시 안성맞춤대로 984",
        jurisdiction=["안성시"],
    ),
    # 59
    EmploymentCenter(
        name="오산고용센터",
        phone="031-8024-9805",
        address="경기 오산시 경기동로",
        jurisdiction=["오산시"],
    ),
    # 60
    EmploymentCenter(
        name="의정부고용센터",
        phone="031-828-0900",
        address="경기 의정부시 시민로 49",
        jurisdiction=["의정부시"],
    ),
    # 61
    EmploymentCenter(
        name="구리고용센터",
        phone="031-560-5800",
        address="경기 구리시 건원대로",
        jurisdiction=["구리시"],
    ),
    # 62
    EmploymentCenter(
        name="남양주고용센터",
        phone="031-560-1919",
        address="경기 남양주시 경춘로",
        jurisdiction=["남양주시"],
    ),
    # 63
    EmploymentCenter(
        name="고양고용센터",
        phone="031-920-3937",
        address="경기 고양시 일산동구 고봉로 32-16",
        jurisdiction=["고양시"],
    ),
    # 64
    EmploymentCenter(
        name="파주고용센터",
        phone="031-860-0401",
        address="경기 파주시 중앙로 328",
        jurisdiction=["파주시"],
    ),
    # 65
    EmploymentCenter(
        name="동두천고용센터",
        phone="031-860-1700",
        address="경기 동두천시 삼육사로 984",
        jurisdiction=["동두천시", "연천군"],
    ),
    # 66
    EmploymentCenter(
        name="양주고용센터",
        phone="031-849-2300",
        address="경기 양주시 부흥로 1533",
        jurisdiction=["양주시"],
    ),
    # 67
    EmploymentCenter(
        name="포천고용센터",
        phone="031-850-7690",
        address="경기 포천시 중앙로",
        jurisdiction=["포천시"],
    ),
    # 68
    EmploymentCenter(
        name="김포고용센터",
        phone="031-999-0900",
        address="경기 김포시 김포한강4로 125",
        jurisdiction=["김포시"],
    ),
    # 69
    EmploymentCenter(
        name="부천고용센터",
        phone="032-320-8900",
        address="경기 부천시 길주로 351",
        jurisdiction=["부천시"],
    ),
    # 70
    EmploymentCenter(
        name="가평고용센터",
        phone="031-580-0901",
        address="경기 가평군 가평읍 가화로",
        jurisdiction=["가평군"],
    ),

    # === 강원 (71~79) ===
    # 71
    EmploymentCenter(
        name="춘천고용센터",
        phone="033-250-1900",
        address="강원 춘천시 퇴계농공로 9",
        jurisdiction=["춘천시", "화천군", "양구군", "인제군"],
    ),
    # 72
    EmploymentCenter(
        name="강릉고용센터",
        phone="033-610-1919",
        address="강원 강릉시 강릉대로 176",
        jurisdiction=["강릉시"],
    ),
    # 73
    EmploymentCenter(
        name="속초고용센터",
        phone="033-630-1919",
        address="강원 속초시 동해대로 4174",
        jurisdiction=["속초시", "고성군", "양양군"],
    ),
    # 74
    EmploymentCenter(
        name="동해고용센터",
        phone="033-539-1901",
        address="강원 동해시 동해대로 4921",
        jurisdiction=["동해시"],
    ),
    # 75
    EmploymentCenter(
        name="원주고용센터",
        phone="033-769-0900",
        address="강원 원주시 서원대로 383",
        jurisdiction=["원주시", "횡성군"],
    ),
    # 76
    EmploymentCenter(
        name="영월고용센터",
        phone="033-371-6260",
        address="강원 영월군 영월읍 단종로 8",
        jurisdiction=["영월군", "정선군", "평창군"],
    ),
    # 77
    EmploymentCenter(
        name="태백고용센터",
        phone="033-552-8605",
        address="강원 태백시 황지로 119",
        jurisdiction=["태백시"],
    ),
    # 78
    EmploymentCenter(
        name="삼척고용센터",
        phone="033-570-1900",
        address="강원 삼척시 중앙로 214",
        jurisdiction=["삼척시"],
    ),
    # 79
    EmploymentCenter(
        name="홍천고용센터",
        phone="033-439-1902",
        address="강원 홍천군 홍천읍 홍천로 356",
        jurisdiction=["홍천군"],
    ),

    # === 충북 (80~85) ===
    # 80
    EmploymentCenter(
        name="청주고용센터",
        phone="043-230-6700",
        address="충북 청주시 서원구 1순환로 642",
        jurisdiction=["청주시", "괴산군", "보은군", "증평군", "영동군"],
    ),
    # 81
    EmploymentCenter(
        name="옥천고용센터",
        phone="043-730-4100",
        address="충북 옥천군 옥천읍 삼양로 91",
        jurisdiction=["옥천군"],
        parent="청주고용센터",
    ),
    # 82
    EmploymentCenter(
        name="진천고용센터",
        phone="043-229-0790",
        address="충북 진천군 덕산읍 자안로",
        jurisdiction=["진천군"],
        parent="청주고용센터",
    ),
    # 83
    EmploymentCenter(
        name="충주고용센터",
        phone="043-850-4000",
        address="충북 충주시 국원대로 13",
        jurisdiction=["충주시"],
    ),
    # 84
    EmploymentCenter(
        name="제천고용센터",
        phone="043-640-9310",
        address="충북 제천시 내토로",
        jurisdiction=["제천시", "단양군"],
    ),
    # 85
    EmploymentCenter(
        name="음성고용센터",
        phone="043-880-8600",
        address="충북 음성군 금왕읍 무극로",
        jurisdiction=["음성군"],
    ),

    # === 전북 (86~93) ===
    # 86
    EmploymentCenter(
        name="전주고용센터",
        phone="063-270-9100",
        address="전북 전주시 덕진구 태진로 114",
        jurisdiction=["전주시", "완주군", "무주군", "진안군", "장수군", "임실군"],
    ),
    # 87
    EmploymentCenter(
        name="정읍고용센터",
        phone="063-530-7500",
        address="전북 정읍시 수성택지3길 28",
        jurisdiction=["정읍시"],
    ),
    # 88
    EmploymentCenter(
        name="남원고용센터",
        phone="063-630-3900",
        address="전북 남원시 향단로 39",
        jurisdiction=["남원시", "순창군"],
    ),
    # 89
    EmploymentCenter(
        name="김제고용센터",
        phone="063-540-8400",
        address="전북 김제시 화동길 105",
        jurisdiction=["김제시"],
    ),
    # 90
    EmploymentCenter(
        name="익산고용센터",
        phone="063-840-6500",
        address="전북 익산시 익산대로52길 11",
        jurisdiction=["익산시"],
    ),
    # 91
    EmploymentCenter(
        name="군산고용센터",
        phone="063-450-0600",
        address="전북 군산시 조촌로 62",
        jurisdiction=["군산시"],
    ),
    # 92
    EmploymentCenter(
        name="부안고용센터",
        phone="063-580-0501",
        address="전북 부안군 부안읍 번영로 145",
        jurisdiction=["부안군"],
        parent="군산고용센터",
    ),
    # 93
    EmploymentCenter(
        name="고창고용센터",
        phone="063-580-0540",
        address="전북 고창군 고창읍 중앙로 330",
        jurisdiction=["고창군"],
        parent="군산고용센터",
    ),

    # === 전남 (94~103) ===
    # 94
    EmploymentCenter(
        name="목포고용센터",
        phone="061-280-0500",
        address="전남 목포시 평화로",
        jurisdiction=["목포시", "신안군"],
    ),
    # 95
    EmploymentCenter(
        name="무안고용센터",
        phone="061-280-0161",
        address="전남 무안군 무안읍 성안길",
        jurisdiction=["무안군"],
        parent="목포고용센터",
    ),
    # 96
    EmploymentCenter(
        name="영암고용센터",
        phone="061-280-0190",
        address="전남 영암군 영암읍 농암로",
        jurisdiction=["영암군"],
        parent="목포고용센터",
    ),
    # 97
    EmploymentCenter(
        name="해남고용센터",
        phone="061-530-2900",
        address="전남 해남군 해남읍 중앙1로 61",
        jurisdiction=["해남군", "강진군", "완도군", "장흥군"],
    ),
    # 98
    EmploymentCenter(
        name="순천고용센터",
        phone="061-720-9114",
        address="전남 순천시 충효로 147",
        jurisdiction=["순천시", "보성군", "고흥군"],
    ),
    # 99
    EmploymentCenter(
        name="광양고용센터",
        phone="061-798-1900",
        address="전남 광양시 중마로",
        jurisdiction=["광양시"],
    ),
    # 100
    EmploymentCenter(
        name="여수고용센터",
        phone="061-650-0155",
        address="전남 여수시 웅천북로",
        jurisdiction=["여수시"],
    ),
    # 101
    EmploymentCenter(
        name="나주고용센터",
        phone="061-280-0184",
        address="전남 나주시 이창1길",
        jurisdiction=["나주시"],
        parent="광주고용센터",
    ),
    # 102
    EmploymentCenter(
        name="영광고용센터",
        phone="061-280-0158",
        address="전남 영광군 영광읍 물무로2길",
        jurisdiction=["영광군"],
        parent="광주광산고용센터",
    ),
    # 103
    EmploymentCenter(
        name="화순고용센터",
        phone="061-280-0155",
        address="전남 화순군 화순읍 쌍충로 38",
        jurisdiction=["화순군"],
        parent="광주고용센터",
    ),

    # === 경북 (104~117) ===
    # 104
    EmploymentCenter(
        name="포항고용센터",
        phone="054-280-3000",
        address="경북 포항시 북구 중흥로",
        jurisdiction=["포항시", "영덕군", "울릉군"],
    ),
    # 105
    EmploymentCenter(
        name="울진출장센터",
        phone="054-783-0841",
        address="경북 울진군 울진읍 읍내7길 10",
        jurisdiction=["울진군"],
        parent="포항고용센터",
    ),
    # 106
    EmploymentCenter(
        name="경주고용센터",
        phone="054-778-2500",
        address="경북 경주시 원화로",
        jurisdiction=["경주시"],
    ),
    # 107
    EmploymentCenter(
        name="구미고용센터",
        phone="054-440-3300",
        address="경북 구미시 백산로",
        jurisdiction=["구미시"],
    ),
    # 108
    EmploymentCenter(
        name="칠곡고용센터",
        phone="054-970-1919",
        address="경북 칠곡군 왜관읍 중앙로 146",
        jurisdiction=["칠곡군", "성주군"],
    ),
    # 109
    EmploymentCenter(
        name="김천고용센터",
        phone="054-429-8900",
        address="경북 김천시 신양2길",
        jurisdiction=["김천시"],
    ),
    # 110
    EmploymentCenter(
        name="영주고용센터",
        phone="054-639-1122",
        address="경북 영주시 번영로 88",
        jurisdiction=["영주시", "봉화군"],
    ),
    # 111
    EmploymentCenter(
        name="문경고용센터",
        phone="054-559-8200",
        address="경북 문경시 매봉1길 67",
        jurisdiction=["문경시"],
    ),
    # 112
    EmploymentCenter(
        name="상주고용센터",
        phone="054-559-8280",
        address="경북 상주시 왕산로 155",
        jurisdiction=["상주시"],
        parent="문경고용센터",
    ),
    # 113
    EmploymentCenter(
        name="안동고용센터",
        phone="054-851-8061",
        address="경북 안동시 경동로 400",
        jurisdiction=["안동시", "청송군", "영양군"],
    ),
    # 114
    EmploymentCenter(
        name="의성고용센터",
        phone="054-851-8150",
        address="경북 의성군 의성읍 문소3길",
        jurisdiction=["의성군"],
        parent="안동고용센터",
    ),
    # 115
    EmploymentCenter(
        name="예천고용센터",
        phone="054-851-8180",
        address="경북 예천군 예천읍 봉덕로",
        jurisdiction=["예천군"],
        parent="안동고용센터",
    ),
    # 116
    EmploymentCenter(
        name="경산고용센터",
        phone="053-667-6800",
        address="경북 경산시 남매로 227",
        jurisdiction=["경산시", "청도군"],
    ),
    # 117
    EmploymentCenter(
        name="영천고용센터",
        phone="054-778-2591",
        address="경북 영천시 금완로",
        jurisdiction=["영천시"],
        parent="경산고용센터",
    ),

    # === 경남 (118~131) ===
    # 118
    EmploymentCenter(
        name="창원고용센터",
        phone="055-239-0900",
        address="경남 창원시 성산구 마디미서로 60",
        jurisdiction=["창원시", "의령군"],
    ),
    # 119
    EmploymentCenter(
        name="마산고용센터",
        phone="055-259-1500",
        address="경남 창원시 마산회원구 3·15대로",
        jurisdiction=["마산"],
        parent="창원고용센터",
    ),
    # 120
    EmploymentCenter(
        name="함안고용센터",
        phone="055-278-9210",
        address="경남 함안군 가야읍 남경길",
        jurisdiction=["함안군"],
        parent="창원고용센터",
    ),
    # 121
    EmploymentCenter(
        name="창녕고용센터",
        phone="055-278-9250",
        address="경남 창녕군 창녕읍 군청길",
        jurisdiction=["창녕군"],
        parent="창원고용센터",
    ),
    # 122
    EmploymentCenter(
        name="김해고용센터",
        phone="055-330-6400",
        address="경남 김해시 호계로 441",
        jurisdiction=["김해시"],
    ),
    # 123
    EmploymentCenter(
        name="밀양고용센터",
        phone="055-350-2800",
        address="경남 밀양시 백민로",
        jurisdiction=["밀양시"],
        parent="김해고용센터",
    ),
    # 124
    EmploymentCenter(
        name="양산고용센터",
        phone="055-379-2400",
        address="경남 양산시 중부로 10",
        jurisdiction=["양산시"],
    ),
    # 125
    EmploymentCenter(
        name="진주고용센터",
        phone="055-753-9090",
        address="경남 진주시 진양호로",
        jurisdiction=["진주시", "산청군", "남해군", "함양군", "합천군"],
    ),
    # 126
    EmploymentCenter(
        name="하동고용센터",
        phone="055-880-5510",
        address="경남 하동군 진교면 민다리안길",
        jurisdiction=["하동군"],
        parent="진주고용센터",
    ),
    # 127
    EmploymentCenter(
        name="거창고용센터",
        phone="055-949-6589",
        address="경남 거창군 거창읍 송정8길",
        jurisdiction=["거창군"],
        parent="진주고용센터",
    ),
    # 128
    EmploymentCenter(
        name="사천고용센터",
        phone="055-760-6590",
        address="경남 사천시 사천읍 옥산로",
        jurisdiction=["사천시"],
        parent="진주고용센터",
    ),
    # 129
    EmploymentCenter(
        name="통영고용센터",
        phone="055-650-1800",
        address="경남 통영시 광도면 죽림1로",
        jurisdiction=["통영시"],
    ),
    # 130
    EmploymentCenter(
        name="거제고용센터",
        phone="055-730-1919",
        address="경남 거제시 서문로5길 6",
        jurisdiction=["거제시"],
    ),
    # 131
    EmploymentCenter(
        name="고성고용센터",
        phone="055-650-1842",
        address="경남 고성군 고성읍 동외로 175",
        jurisdiction=["고성군"],
        parent="통영고용센터",
    ),

    # === 제주 (132) ===
    # 132
    EmploymentCenter(
        name="제주고용센터",
        phone="064-759-2450",
        address="제주시 청사로",
        jurisdiction=["제주시", "서귀포시"],
    ),
]

# ── 지역명 → CENTERS 인덱스 매핑 ─────────────────────────────────────────────

REGION_MAP: dict[str, int] = {
    # --- 서울 ---
    "서울": 0,
    "종로": 0, "동대문": 0,
    "서초": 1,
    "강남": 2, "테헤란로": 2,
    "송파": 3, "강동": 3,
    "성동": 4, "광진": 4,
    "마포": 5, "서대문": 5, "용산": 5, "은평": 5,
    "강서": 6,
    "영등포": 7, "양천": 7,
    "노원": 8, "도봉": 8, "중랑": 8,
    "강북": 9, "성북": 9,
    "관악": 10, "구로": 10, "금천": 10, "동작": 10,

    # --- 부산 ---
    "부산": 11,
    "사하": 12,
    "동래": 13, "해운대": 13, "수영": 13, "기장": 13,
    "사상": 14,

    # --- 대구 ---
    "대구": 15,
    "달서": 18, "달성": 19, "고령": 19,

    # --- 인천 ---
    "인천": 20,
    "부평": 21, "계양": 21,
    "강화": 23,

    # --- 광주 ---
    "광주": 24,
    "광산": 25, "함평": 25,

    # --- 대전·세종·울산 ---
    "대전": 26,
    "세종": 27,
    "울산": 28,

    # --- 충남 ---
    "충남": 29,
    "천안": 29,
    "아산": 30,
    "당진": 31,
    "예산": 32,
    "서산": 33,
    "태안": 34,
    "논산": 35, "계룡": 35,
    "공주": 36,
    "금산": 37,
    "보령": 38,
    "부여": 39,
    "서천": 40,
    "홍성": 41, "청양": 41,

    # --- 경기 ---
    "경기": 42,
    "수원": 42,
    "용인": 43,
    "화성": 44,
    "성남": 45, "분당": 45, "판교": 45,
    "하남": 46,
    "경기광주": 47,
    "양평": 48,
    "여주": 49,
    "이천": 50,
    "안양": 51, "과천": 51,
    "의왕": 52,
    "군포": 53,
    "광명": 54,
    "안산": 55,
    "시흥": 56,
    "평택": 57,
    "안성": 58,
    "오산": 59,
    "의정부": 60,
    "구리": 61,
    "남양주": 62,
    "고양": 63, "일산": 63,
    "파주": 64,
    "동두천": 65, "연천": 65,
    "양주": 66,
    "포천": 67,
    "김포": 68,
    "부천": 69,
    "가평": 70,

    # --- 강원 ---
    "강원": 71,
    "춘천": 71, "화천": 71, "양구": 71, "인제": 71,
    "강릉": 72,
    "속초": 73, "양양": 73,
    "동해": 74,
    "원주": 75, "횡성": 75,
    "영월": 76, "정선": 76, "평창": 76,
    "태백": 77,
    "삼척": 78,
    "홍천": 79,

    # --- 충북 ---
    "충북": 80,
    "청주": 80, "괴산": 80, "보은": 80, "증평": 80, "영동": 80,
    "옥천": 81,
    "진천": 82,
    "충주": 83,
    "제천": 84, "단양": 84,
    "음성": 85,

    # --- 전북 ---
    "전북": 86,
    "전주": 86, "완주": 86, "무주": 86, "진안": 86, "장수": 86, "임실": 86,
    "정읍": 87,
    "남원": 88, "순창": 88,
    "김제": 89,
    "익산": 90,
    "군산": 91,
    "부안": 92,
    "고창": 93,

    # --- 전남 ---
    "전남": 94,
    "목포": 94, "신안": 94,
    "무안": 95,
    "영암": 96,
    "해남": 97, "강진": 97, "완도": 97, "장흥": 97,
    "순천": 98, "보성": 98, "고흥": 98,
    "광양": 99,
    "여수": 100,
    "나주": 101,
    "영광": 102,
    "화순": 103,

    # --- 경북 ---
    "경북": 104,
    "포항": 104, "영덕": 104, "울릉": 104,
    "울진": 105,
    "경주": 106,
    "구미": 107,
    "칠곡": 108, "성주": 108,
    "김천": 109,
    "영주": 110, "봉화": 110,
    "문경": 111,
    "상주": 112,
    "안동": 113, "청송": 113, "영양": 113,
    "의성": 114,
    "예천": 115,
    "경산": 116, "청도": 116,
    "영천": 117,

    # --- 경남 ---
    "경남": 118,
    "창원": 118,
    "마산": 119,
    "함안": 120,
    "창녕": 121,
    "김해": 122,
    "밀양": 123,
    "양산": 124,
    "진주": 125, "산청": 125, "남해": 125, "함양": 125, "합천": 125,
    "하동": 126,
    "거창": 127,
    "사천": 128,
    "통영": 129,
    "거제": 130,
    "고성": 131,

    # --- 제주 ---
    "제주": 132,
    "서귀포": 132,
}


# ── 조회 함수 ─────────────────────────────────────────────────────────────────

_METRO_KEYWORDS = frozenset([
    "서울", "부산", "대구", "인천", "광주", "대전", "세종", "울산",
    "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
])


def find_center(query: str) -> EmploymentCenter | None:
    """질문 텍스트에서 지역명을 추출하여 관할 고용센터 반환.

    구·군·시 단위 키워드를 광역시·도 이름보다 우선 매칭합니다.
    예: '서울 강남에서 실업급여' → 강남 > 서울 (구 단위 우선)
    """
    metro_match = None
    for keyword, idx in REGION_MAP.items():
        if keyword in query:
            if keyword not in _METRO_KEYWORDS:
                # 구·군·시 단위 → 즉시 반환 (가장 구체적)
                return CENTERS[idx]
            elif metro_match is None:
                metro_match = idx
    if metro_match is not None:
        return CENTERS[metro_match]
    return None


def format_center(center: EmploymentCenter) -> str:
    """고용센터 정보를 답변 삽입용 텍스트로 포맷."""
    lines = [
        f"📍 {center.name}",
        f"   전화: {center.phone}",
        f"   주소: {center.address}",
        f"   관할: {', '.join(center.jurisdiction)}",
    ]
    if center.homepage:
        lines.append(f"   홈페이지: {center.homepage}")
    if center.parent:
        lines.append(f"   (상위 센터: {center.parent})")
    return "\n".join(lines)


def format_center_guide() -> str:
    """고용센터 검색 안내 (지역 미명시 시 사용 — 132개 전체 나열 대신)."""
    return (
        "관할 고용센터를 찾으시려면:\n"
        "- 고용노동부 고객상담센터: 1350 (평일 09:00~18:00)\n"
        "- 고용24 고용센터 검색: https://www.work24.go.kr\n"
        "- 지역명을 알려주시면 관할 고용센터를 안내해 드립니다."
    )
