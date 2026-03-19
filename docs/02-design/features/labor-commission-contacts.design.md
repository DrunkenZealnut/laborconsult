# Design: 전국 노동위원회 연락처 정보 제공

> Plan 참조: `docs/01-plan/features/labor-commission-contacts.plan.md`

---

## 1. 변경 사항 요약

| # | 변경 | 파일 | 심각도 |
|---|------|------|--------|
| D-1 | 노동위원회 데이터 모듈 신규 생성 | `app/core/labor_offices.py` | Critical |
| D-2 | 시스템 프롬프트에 노동위원회 안내 규칙 추가 | `app/core/pipeline.py` | Critical |
| D-3 | 컨텍스트 구성 시 노동위원회 연락처 삽입 | `app/core/pipeline.py` | Major |
| D-4 | legal_hints 면책 문구에 노동위원회 참조 추가 | `wage_calculator/legal_hints.py` | Low |

---

## 2. 상세 설계

### D-1. `app/core/labor_offices.py` — 노동위원회 데이터 모듈 (신규)

#### 1a. 데이터 구조

```python
from dataclasses import dataclass

@dataclass
class LaborCommission:
    name: str
    phone: str
    fax: str
    address: str
    jurisdiction: list[str]   # 관할 지역 키워드
```

#### 1b. 데이터 상수 (14개 기관)

```python
COMMISSIONS: list[LaborCommission] = [
    LaborCommission(
        name="중앙노동위원회",
        phone="044-202-8226",
        fax="0503-8803-0729",
        address="세종시 한누리대로 422, 11동 3~4층",
        jurisdiction=["전국", "재심"],
    ),
    LaborCommission(
        name="서울지방노동위원회",
        phone="02-3218-6070",
        fax="02-2069-0630",
        address="서울 영등포구 문래로20길 56",
        jurisdiction=["서울"],
    ),
    # ... 나머지 12개 기관
]
```

#### 1c. 관할구역 매핑 dict

지역명 키워드 → `COMMISSIONS` 인덱스 매핑. 광역시·도·주요 시군구 포함:

```python
REGION_MAP: dict[str, int] = {
    # 서울 (index 1)
    "서울": 1, "강남": 1, "서초": 1, "마포": 1, "영등포": 1, "송파": 1,
    "강서": 1, "구로": 1, "용산": 1, "종로": 1, "중구": 1, "성동": 1,
    # 부산 (index 2)
    "부산": 2, "해운대": 2, "사상": 2, "금정": 2,
    # 경기 (index 3)
    "경기": 3, "수원": 3, "성남": 3, "용인": 3, "고양": 3, "안산": 3,
    "안양": 3, "파주": 3, "화성": 3, "시흥": 3, "평택": 3, "김포": 3,
    # 인천 (index 4)
    "인천": 4, "미추홀": 4, "부평": 4, "남동": 4,
    # 강원 (index 5)
    "강원": 5, "춘천": 5, "원주": 5, "강릉": 5,
    # 충북 (index 6)
    "충북": 6, "청주": 6, "충주": 6, "제천": 6,
    # 충남·대전·세종 (index 7)
    "충남": 7, "대전": 7, "세종": 7, "천안": 7, "아산": 7, "논산": 7,
    # 전북 (index 8)
    "전북": 8, "전주": 8, "익산": 8, "군산": 8,
    # 전남·광주 (index 9)
    "전남": 9, "광주": 9, "목포": 9, "순천": 9, "여수": 9,
    # 경북·대구 (index 10)
    "경북": 10, "대구": 10, "포항": 10, "구미": 10, "경산": 10,
    # 경남 (index 11)
    "경남": 11, "창원": 11, "김해": 11, "진주": 11, "양산": 11, "거제": 11,
    # 울산 (index 12)
    "울산": 12,
    # 제주 (index 13)
    "제주": 13,
}
```

#### 1d. 조회 함수

```python
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
```

---

### D-2. `app/core/pipeline.py` — 시스템 프롬프트 업데이트

#### 2a. SYSTEM_PROMPT에 규칙 추가 (기존 10번 뒤에)

```python
# 기존 10. 답변은 마크다운 형식으로 작성하세요. 뒤에 추가:

"""
11. **노동위원회 연락처가 포함된 경우**:
   - 부당해고 구제신청, 부당노동행위, 차별시정, 노동쟁의 조정 등 노동위원회 소관 사안이면
     제공된 노동위원회 연락처를 답변에 포함하세요.
   - 임금체불, 근로기준법 위반 등 고용노동부(근로감독관) 소관 사안은 기존대로 1350을 안내하세요.
   - 해고를 당한 근로자에게는 노동위원회 구제신청(30일 이내)을 반드시 안내하세요.
"""
```

---

### D-3. `app/core/pipeline.py` — 컨텍스트에 노동위원회 정보 삽입

#### 3a. import 추가

```python
from app.core.labor_offices import find_commission, format_commission, format_all_commissions
```

#### 3b. 컨텍스트 구성 구간 (기존 "# 3. 컨텍스트 구성" 블록, line ~506~516)

`parts` 리스트에 노동위원회 정보를 조건부 삽입:

```python
# 기존 parts 구성 후, 질문 추가 전에:

# 노동위원회 연락처 (해고·차별·쟁의 관련 시)
_COMMISSION_KEYWORDS = ["해고", "부당해고", "구제신청", "부당노동행위", "차별시정",
                        "노동쟁의", "조정신청", "노동위원회", "교섭대표"]
if any(kw in query for kw in _COMMISSION_KEYWORDS):
    comm = find_commission(query)
    if comm:
        parts.append(f"관할 노동위원회 연락처:\n\n{format_commission(comm)}")
    else:
        parts.append(f"노동위원회 연락처:\n\n{format_all_commissions()}")

parts.append(f"질문: {query}")
```

**핵심 로직**: 질문에 해고/구제신청 등 키워드가 있으면 노동위원회 정보를 Claude 컨텍스트에 삽입. 지역명이 있으면 관할 1개소, 없으면 전체 목록.

---

### D-4. `wage_calculator/legal_hints.py` — 면책 문구 보완

#### 4a. 기존 면책 문구 (line 260~263)

```python
# Before
lines.append(
    "\n⚠️ 위 내용은 참고용이며 법적 판단이 아닙니다. "
    "정확한 판단은 고용노동부(1350) 또는 노무사에게 문의하세요."
)

# After
lines.append(
    "\n⚠️ 위 내용은 참고용이며 법적 판단이 아닙니다. "
    "정확한 판단은 고용노동부(1350) 또는 노무사에게 문의하세요. "
    "부당해고·차별시정 구제신청은 관할 지방노동위원회에 접수합니다."
)
```

변경 범위 최소화: 한 문장 추가만으로 노동위원회 존재를 인지시킴. 상세 연락처는 D-3에서 pipeline이 제공.

---

## 3. 구현 순서

```
Step 1: app/core/labor_offices.py — LaborCommission 데이터 + REGION_MAP + 조회 함수
Step 2: app/core/pipeline.py — import + SYSTEM_PROMPT 규칙 추가 + 컨텍스트 삽입
Step 3: wage_calculator/legal_hints.py — 면책 문구 한 문장 추가
Step 4: 통합 테스트 — 키워드·지역 조합별 동작 확인
```

---

## 4. 변경하지 않는 것

| 항목 | 이유 |
|------|------|
| `harassment_assessor/constants.py` | 괴롭힘은 고용노동부 소관(제76조의3) — 노동위원회 아님. 기존 "1350" 안내 유지 |
| `chatbot.py` (CLI) | API 파이프라인에만 통합, CLI는 개발용이므로 제외 |
| `_extract_params()` | 노동위원회는 계산기 파라미터가 아니므로 tool 추가 불필요 |
| `WageInput` / 계산기 모듈 | 연락처 기능은 계산과 무관 |

---

## 5. 검증 매트릭스

| 검증 항목 | 입력 조건 | 기대 결과 |
|----------|----------|----------|
| 지역 + 해고 키워드 | "서울에서 부당해고 구제신청하려면?" | 서울지방노동위원회 (02-3218-6070) 포함 |
| 지역 + 노동쟁의 | "부산에서 노동쟁의 조정신청" | 부산지방노동위원회 (051-559-3700) 포함 |
| 복합 관할 (대전) | "대전에서 차별시정 신청" | 충남지방노동위원회 (042-520-8070) 포함 |
| 지역 미명시 | "부당해고 구제신청 방법" | 전국 14개 노동위원회 요약 목록 |
| 비관련 질문 | "주휴수당 계산해주세요" | 노동위원회 정보 미삽입 (기존대로) |
| 임금체불 | "임금체불 신고하려면?" | 고용노동부(1350) 안내 유지 |
| 괴롭힘 | "직장 내 괴롭힘 신고" | 고용노동부(1350) 안내 유지 — 노동위원회 아님 |
| find_commission 정확도 | 모든 REGION_MAP 키워드 | 올바른 노동위원회 반환 |
