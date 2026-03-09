"""
직장 내 괴롭힘 판정 입력 데이터 스키마
"""

from dataclasses import dataclass, field
from enum import Enum


class RelationType(Enum):
    """가해자-피해자 관계 유형"""
    SUPERIOR    = "상급자"
    EMPLOYER    = "사용자"
    REGULAR_IRR = "정규직_비정규직"
    MAJORITY    = "다수_소수"
    SENIOR      = "선임_후임"
    PEER        = "동료"
    SUBORDINATE = "하급자"
    CUSTOMER    = "고객"


class BehaviorType(Enum):
    """괴롭힘 행위 유형"""
    ASSAULT         = "폭행_협박"
    VERBAL_ABUSE    = "폭언_모욕"
    OSTRACISM       = "따돌림_무시"
    UNFAIR_WORK     = "부당업무"
    PERSONAL_ERRAND = "사적용무"
    SURVEILLANCE    = "감시_통제"
    UNFAIR_HR       = "부당인사"


class Likelihood(Enum):
    """판정 가능성 수준"""
    HIGH   = "높음"
    MEDIUM = "보통"
    LOW    = "낮음"
    NA     = "비해당"


class ElementStatus(Enum):
    """3요소 개별 판정 상태"""
    MET     = "해당"
    NOT_MET = "미해당"
    UNCLEAR = "불분명"


@dataclass
class HarassmentInput:
    """괴롭힘 판정 입력 데이터"""
    # 관계
    perpetrator_role: str = ""
    victim_role: str = ""
    relationship_type: str = ""

    # 행위
    behavior_description: str = ""
    behavior_types: list[str] = field(default_factory=list)

    # 빈도·기간
    frequency: str = ""
    duration: str = ""

    # 증거·상황
    witnesses: bool = False
    evidence: list[str] = field(default_factory=list)
    impact: str = ""

    # 회사 대응
    company_response: str = ""

    # 사업장
    business_size: str = ""
