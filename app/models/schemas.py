"""Pydantic 요청/응답 스키마"""

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    message: str
    session_id: str
    calc_result: dict | None = None


class AnalysisResult(BaseModel):
    requires_calculation: bool = False
    calculation_types: list[str] = []
    extracted_info: dict = {}
    relevant_laws: list[str] = []
    missing_info: list[str] = []
    question_summary: str = ""
