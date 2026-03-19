# Design: 전국 고용센터 연락처와 홈페이지 정보 제공

> Plan 참조: `docs/01-plan/features/employment-center-contacts.plan.md`

---

## 1. 변경 사항 요약

| # | 변경 | 파일 | 심각도 |
|---|------|------|--------|
| D-1 | 고용센터 데이터 모듈 신규 생성 | `app/core/employment_centers.py` | Critical |
| D-2 | 시스템 프롬프트에 고용센터 안내 규칙 추가 | `app/core/pipeline.py` | Critical |
| D-3 | 컨텍스트 구성 시 고용센터 연락처 삽입 | `app/core/pipeline.py` | Major |
| D-4 | legal_hints 면책 문구에 고용센터 참조 추가 | `wage_calculator/legal_hints.py` | Low |

---

## 2. 상세 설계

### D-1. `app/core/employment_centers.py` — 고용센터 데이터 모듈 (신규)

#### 1a. 데이터 구조

```python
from __future__ import annotations
from dataclasses import dataclass, field

@dataclass
class EmploymentCenter:
    name: str                           # 센터명
    phone: str                          # 대표전화
    address: str                        # 주소
    jurisdiction: list[str]             # 관할 구·군·시
    parent: str | None = None           # 상위 센터명 (하부센터인 경우)
    homepage: str | None = None         # 개별 홈페이지 URL
```

#### 1b. 데이터 상수 (132개 센터)

센터를 지역별로 그룹화하여 `CENTERS` 리스트에 저장. 각 센터에 인덱스 부여.

```python
CENTERS: list[EmploymentCenter] = [
    # === 서울 (0~10) ===
    EmploymentCenter(
        name="서울고용센터",
        phone="02-2004-7301",
        address="서울 중구 삼일대로 363",
        jurisdiction=["중구", "종로구", "동대문구"],
        homepage="https://www.work.go.kr/seoul/",
    ),
    EmploymentCenter(
        name="서초고용센터",
        phone="02-580-4900",
        address="서울 서초구 반포대로",
        jurisdiction=["서초구"],
        homepage="https://www.work.go.kr/seocho/",
    ),
    # ... 나머지 130개 센터 (Plan 문서 §2 데이터 참조)

    # 하부센터 예시:
    EmploymentCenter(
        name="함안고용센터",
        phone="055-278-9210",
        address="경남 함안군 가야읍 남경길",
        jurisdiction=["함안군"],
        parent="창원고용센터",
    ),
]
```

**인덱스 할당 규칙**: 서울(0~10) → 부산(11~14) → 대구(15~19) → 인천(20~23) → 광주(24~25) → 대전·세종·충남(26~40) → 울산(41) → 경기(42~70) → 강원(71~79) → 충북(80~85) → 전북(86~93) → 전남(94~103) → 경북(104~117) → 경남(118~131) → 제주(132 또는 말미)

#### 1c. 관할구역 매핑 dict

`REGION_MAP`: 시·군·구 이름 → `CENTERS` 인덱스 매핑. 광역시·도 이름은 대표 센터로 매핑.

```python
REGION_MAP: dict[str, int] = {
    # 서울 (광역 → 서울고용센터)
    "서울": 0,
    # 서울 구별 매핑
    "중구": 0, "종로구": 0, "종로": 0, "동대문구": 0, "동대문": 0,
    "서초구": 1, "서초": 1,
    "강남구": 2, "강남": 2, "테헤란로": 2,
    "송파구": 3, "송파": 3, "강동구": 3, "강동": 3,
    "성동구": 4, "성동": 4, "광진구": 4, "광진": 4,
    "마포구": 5, "마포": 5, "서대문구": 5, "서대문": 5,
    "용산구": 5, "용산": 5, "은평구": 5, "은평": 5,
    "강서구": 6, "양천구": 7, "양천": 7,
    "영등포구": 7, "영등포": 7,
    "노원구": 8, "노원": 8, "도봉구": 8, "도봉": 8, "중랑구": 8, "중랑": 8,
    "강북구": 9, "강북": 9, "성북구": 9, "성북": 9,
    "관악구": 10, "관악": 10, "구로구": 10, "구로": 10,
    "금천구": 10, "금천": 10, "동작구": 10, "동작": 10,
    # 부산
    "부산": 11,
    "해운대구": 13, "해운대": 13, "금정구": 13,
    "사하구": 12, "사하": 12,
    "북구": 14, "사상구": 14, "사상": 14,
    # ... 나머지 지역 (Plan 문서 §2 관할구역 데이터 참조)
    # 경기 시 단위 매핑
    "수원": 42, "용인": 43, "화성": 44, "성남": 45,
    # ...
}
```

**매핑 규칙**:
- 광역시·도 이름 → 해당 지역 대표 센터 (예: "부산" → 부산고용센터)
- 구·군 이름 → 해당 관할 센터 (예: "해운대" → 부산동부고용센터)
- "~구" 접미사 있는 것과 없는 것 모두 등록 (예: "강남구", "강남")
- 시 이름 → 해당 센터 (예: "수원" → 수원고용센터)

#### 1d. 조회 함수

```python
def find_center(query: str) -> EmploymentCenter | None:
    """질문 텍스트에서 지역명을 추출하여 관할 고용센터 반환."""
    for keyword, idx in REGION_MAP.items():
        if keyword in query:
            return CENTERS[idx]
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
        lines.append(f"   (상위: {center.parent})")
    return "\n".join(lines)


def format_center_guide() -> str:
    """고용센터 검색 안내 (지역 미명시 시 사용 — 132개 전체 나열 대신)."""
    return (
        "관할 고용센터를 찾으시려면:\n"
        "- 고용노동부 고객상담센터: 1350 (평일 09:00~18:00)\n"
        "- 고용24 고용센터 검색: https://www.work24.go.kr\n"
        "- 지역명을 알려주시면 관할 고용센터를 안내해 드립니다."
    )
```

**설계 포인트**: 노동위원회(14개)와 달리 고용센터는 132개이므로, 지역 미명시 시 전체 목록 대신 `format_center_guide()`로 검색 안내.

---

### D-2. `app/core/pipeline.py` — 시스템 프롬프트 업데이트

#### 2a. SYSTEM_PROMPT에 규칙 추가 (기존 11번 뒤에)

```python
# 기존 11. 노동위원회 연락처... 뒤에 추가:

"""
12. **고용센터 연락처가 포함된 경우**:
   - 실업급여(구직급여) 신청, 구직활동 지원, 직업훈련(내일배움카드), 고용보험, 취업지원 등
     고용센터 소관 사안이면 제공된 고용센터 연락처를 답변에 포함하세요.
   - 고용센터 연락처에 홈페이지 URL이 있으면 함께 안내하세요.
   - 지역 정보가 없으면 1350 전화 + 고용24(work24.go.kr) 검색을 안내하세요."""
```

---

### D-3. `app/core/pipeline.py` — 컨텍스트에 고용센터 정보 삽입

#### 3a. import 추가

```python
from app.core.employment_centers import find_center, format_center, format_center_guide
```

#### 3b. 컨텍스트 구성 구간 (기존 노동위원회 블록 뒤, `parts.append(f"질문: {query}")` 전에)

```python
# 기존 노동위원회 블록 뒤에 추가:

# 고용센터 연락처 (실업급여·구직·직업훈련 관련 시)
_CENTER_KEYWORDS = ["실업급여", "구직급여", "구직활동", "구직등록", "실업",
                    "직업훈련", "내일배움카드", "국비훈련", "취업지원", "취업성공패키지",
                    "고용센터", "고용보험", "피보험자격", "고용유지지원금",
                    "출산전후휴가급여", "육아휴직급여", "고용복지"]
if any(kw in query for kw in _CENTER_KEYWORDS):
    center = find_center(query)
    if center:
        parts.append(f"관할 고용센터 연락처:\n\n{format_center(center)}")
    else:
        parts.append(f"고용센터 안내:\n\n{format_center_guide()}")

parts.append(f"질문: {query}")
```

**핵심 로직**: 질문에 실업급여/구직/직업훈련 등 키워드가 있으면 고용센터 정보를 Claude 컨텍스트에 삽입. 지역명이 있으면 관할 1개소, 없으면 검색 안내.

**키워드 충돌 방지**: `_COMMISSION_KEYWORDS`(노동위원회)와 `_CENTER_KEYWORDS`(고용센터)는 서로 겹치지 않음. 두 블록 모두 독립적으로 평가되므로, "해고 + 실업급여" 같은 복합 질문에서는 노동위원회 + 고용센터 모두 삽입 가능.

---

### D-4. `wage_calculator/legal_hints.py` — 면책 문구 보완

#### 4a. 기존 면책 문구 (line 260~264)

```python
# Before
lines.append(
    "\n⚠️ 위 내용은 참고용이며 법적 판단이 아닙니다. "
    "정확한 판단은 고용노동부(1350) 또는 노무사에게 문의하세요. "
    "부당해고·차별시정 구제신청은 관할 지방노동위원회에 접수합니다."
)

# After
lines.append(
    "\n⚠️ 위 내용은 참고용이며 법적 판단이 아닙니다. "
    "정확한 판단은 고용노동부(1350) 또는 노무사에게 문의하세요. "
    "부당해고·차별시정 구제신청은 관할 지방노동위원회에, "
    "실업급여·직업훈련은 관할 고용센터에 접수합니다."
)
```

변경 범위 최소화: 기존 노동위원회 문장을 확장하여 고용센터도 언급. 상세 연락처는 D-3에서 pipeline이 제공.

---

## 3. 구현 순서

```
Step 1: app/core/employment_centers.py — EmploymentCenter 데이터 + REGION_MAP + 조회 함수
Step 2: app/core/pipeline.py — import + SYSTEM_PROMPT 규칙 12 추가 + 컨텍스트 삽입
Step 3: wage_calculator/legal_hints.py — 면책 문구 확장
Step 4: 통합 테스트 — 키워드·지역 조합별 동작 확인
```

---

## 4. 변경하지 않는 것

| 항목 | 이유 |
|------|------|
| `app/core/labor_offices.py` | 노동위원회 전용 모듈 — 고용센터와는 별개 기관 |
| `harassment_assessor/` | 괴롭힘은 고용노동부 소관 — 고용센터 아님 |
| `chatbot.py` (CLI) | API 파이프라인에만 통합, CLI는 개발용 |
| `_extract_params()` | 고용센터는 계산기 파라미터가 아님 |
| `WageInput` / 계산기 모듈 | 연락처 기능은 계산과 무관 |

---

## 5. 검증 매트릭스

| 검증 항목 | 입력 조건 | 기대 결과 |
|----------|----------|----------|
| 지역 + 실업급여 | "서울 강남에서 실업급여 신청하려면?" | 서울강남고용센터 (02-3468-4794) + 홈페이지 |
| 지역 + 직업훈련 | "부산에서 내일배움카드 신청" | 부산고용센터 (051-860-1919) |
| 하부센터 관할 | "함안에서 구직등록" | 함안고용센터 (055-278-9210), parent=창원고용센터 |
| 복합 관할 (대전) | "대전에서 고용보험 가입" | 대전고용센터 (042-480-6000) |
| 지역 미명시 | "실업급여 신청 방법" | 1350 + work24.go.kr 검색 안내 (전체 목록 아님) |
| 비관련 질문 | "주휴수당 계산해주세요" | 고용센터 정보 미삽입 (기존대로) |
| 노동위원회 소관 | "부당해고 구제신청" | 노동위원회 안내 유지 — 고용센터 아님 |
| 임금체불 | "임금체불 신고하려면?" | 고용노동부(1350) 안내 유지 |
| 복합 질문 | "해고당해서 실업급여 받으려면?" | 노동위원회 + 고용센터 모두 삽입 |
| 홈페이지 포함 | 고용센터 안내 시 | homepage URL 포함 |
| find_center 정확도 | 모든 REGION_MAP 키워드 | 올바른 고용센터 반환 |
| 키워드 충돌 없음 | _COMMISSION_KEYWORDS ∩ _CENTER_KEYWORDS = ∅ | 두 세트 완전 분리 |
