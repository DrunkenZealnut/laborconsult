"""요청/응답 스키마"""

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class Attachment(BaseModel):
    """Base64 인코딩된 첨부파일"""
    filename: str
    content_type: str
    data: str   # base64 encoded


class ChatWithFilesRequest(BaseModel):
    """파일 첨부 가능한 채팅 요청"""
    message: str
    session_id: str | None = None
    attachments: list[Attachment] = []


class AnalysisResult(BaseModel):
    """의도 분석 결과 — analyze_intent()가 반환"""
    requires_calculation: bool = False
    calculation_types: list[str] = []
    extracted_info: dict = {}
    relevant_laws: list[str] = []
    missing_info: list[str] = []
    question_summary: str = ""
    # 법률상담 전용 필드 (계산 불필요 + 괴롭힘 아닌 경우)
    consultation_type: str | None = None
    consultation_topic: str | None = None
    # 판례 검색용 법적 쟁점 키워드 (맥락 기반 검색)
    precedent_keywords: list[str] = []
    # 특수 근로자 그룹 (청소년, 외국인, 장애인, 산재)
    worker_group: str | None = None
