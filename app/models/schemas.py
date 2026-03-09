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
