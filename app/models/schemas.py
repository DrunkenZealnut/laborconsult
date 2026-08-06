"""요청/응답 스키마"""

from pydantic import BaseModel, Field


# 파싱 폭탄 백스톱 — 실제 길이 제한(기본 2,000자)은 abuse_guard가 담당한다.
# 3경로 일관 응답을 위해 소프트 한도는 가드가, 하드캡만 여기서 처리(422 → 한국어 핸들러).
MAX_MESSAGE_HARD_CAP = 20_000


class ChatRequest(BaseModel):
    message: str = Field(max_length=MAX_MESSAGE_HARD_CAP)
    session_id: str | None = None


class Attachment(BaseModel):
    """Base64 인코딩된 첨부파일"""
    filename: str
    content_type: str
    data: str   # base64 encoded


class ChatWithFilesRequest(BaseModel):
    """파일 첨부 가능한 채팅 요청"""
    message: str = Field(max_length=MAX_MESSAGE_HARD_CAP)
    session_id: str | None = None
    attachments: list[Attachment] = []


class AnalysisResult(BaseModel):
    """의도 분석 결과 — analyze_intent()가 반환"""
    requires_calculation: bool = False
    calculation_types: list[str] = []
    extracted_info: dict = {}
    relevant_laws: list[str] = []
    missing_info: list[str] = []
    # 숫자 범위 검증이 제거한 파라미터 라벨 — 코드 판정 교체 후에도 보존 (CALC-13)
    validation_warnings: list[str] = []
    question_summary: str = ""
    # 법률상담 전용 필드 (계산 불필요 + 괴롭힘 아닌 경우)
    consultation_type: str | None = None
    consultation_topic: str | None = None
    # 판례 검색용 법적 쟁점 키워드 (맥락 기반 검색)
    precedent_keywords: list[str] = []
    # 특수 근로자 그룹 (청소년, 외국인, 장애인, 산재)
    worker_group: str | None = None
    # 노동법 스코프 판정 (chatbot-security FR-05)
    # 기본값 True = analyzer 실패·필드 누락 시 fail-open(상담 허용)
    is_labor_related: bool = True
    # 의도분석을 실제로 수행한 제공자 (llm-fallback-hardening FR-10 계측).
    # "OpenAI"면 Anthropic 장애로 교차벤더 폴백이 발동했다는 뜻이다.
    intent_provider: str | None = None
