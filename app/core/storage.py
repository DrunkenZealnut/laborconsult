"""Supabase Q&A 저장 — 질문·답변·첨부파일 영구 보관"""

from __future__ import annotations

import base64
import logging
import uuid
from dataclasses import dataclass

from supabase import Client as SupabaseClient

logger = logging.getLogger(__name__)

# ── 카테고리 매핑 ────────────────────────────────────────────────────────────

CATEGORY_MAP: dict[str, str] = {
    "overtime": "임금·수당",
    "comprehensive": "임금·수당",
    "ordinary_wage": "임금·수당",
    "minimum_wage": "임금·수당",
    "prorated": "임금·수당",
    "flexible_work": "임금·수당",
    "severance": "퇴직금",
    "dismissal": "해고",
    "shutdown_allowance": "해고",
    "unemployment": "실업급여",
    "annual_leave": "휴가·휴일",
    "weekly_holiday": "휴가·휴일",
    "public_holiday": "휴가·휴일",
    "compensatory_leave": "휴가·휴일",
    "insurance": "4대보험",
    "employer_insurance": "4대보험",
    "industrial_accident": "산업재해",
    "parental_leave": "육아·출산",
    "maternity_leave": "육아·출산",
    "wage_arrears": "임금체불",
    "harassment": "직장내 괴롭힘",
    "eitc": "근로장려금",
    "retirement_tax": "퇴직금",
    "retirement_pension": "퇴직금",
    "average_wage": "임금·수당",
}


# ── 키워드 기반 calculation_types 추론 ─────────────────────────────────────

_KW_CALC_TYPES: list[tuple[list[str], list[str]]] = [
    (["연장수당", "야간수당", "휴일수당", "초과근무", "52시간"], ["overtime"]),
    (["주휴수당", "주휴일", "주휴"], ["weekly_holiday"]),
    (["연차수당", "연차휴가", "연차"], ["annual_leave"]),
    (["퇴직금", "퇴직급여"], ["severance"]),
    (["해고예고수당", "해고예고", "부당해고", "해고"], ["dismissal"]),
    (["실업급여", "구직급여", "실업"], ["unemployment"]),
    (["최저임금", "최저시급"], ["minimum_wage"]),
    (["4대보험", "국민연금", "건강보험", "고용보험"], ["insurance"]),
    (["산재", "산업재해", "산재보험", "요양급여", "휴업급여", "장해급여"], ["industrial_accident"]),
    (["육아휴직", "육아휴직급여"], ["parental_leave"]),
    (["출산휴가", "출산전후휴가", "배우자출산"], ["maternity_leave"]),
    (["임금체불", "체불", "밀린 임금", "임금 미지급"], ["wage_arrears"]),
    (["괴롭힘", "갑질", "폭언", "따돌림", "직장 내 괴롭힘"], ["harassment"]),
    (["포괄임금", "포괄임금제"], ["comprehensive"]),
    (["탄력근무", "탄력적 근로", "유연근무"], ["flexible_work"]),
    (["보상휴가", "대체휴가"], ["compensatory_leave"]),
    (["근로장려금", "EITC"], ["eitc"]),
    (["통상임금", "통상시급"], ["ordinary_wage"]),
    (["평균임금"], ["average_wage"]),
    (["퇴직소득세", "퇴직세금"], ["retirement_tax"]),
    (["퇴직연금"], ["retirement_pension"]),
    (["임금계산", "급여계산", "실수령액"], ["insurance"]),
]


def infer_calc_types(query: str) -> list[str]:
    """질문 키워드에서 관련 calculation_types를 추론"""
    result = []
    for keywords, types in _KW_CALC_TYPES:
        if any(kw in query for kw in keywords):
            for t in types:
                if t not in result:
                    result.append(t)
    return result


def classify_category(
    calculation_types: list[str] | None,
    tool_type: str = "none",
    query: str = "",
) -> str:
    """계산 유형 목록 + 키워드 기반으로 대표 카테고리를 결정"""
    # 1. 괴롭힘 도구 사용 시
    if tool_type == "harassment":
        return "직장내 괴롭힘"

    # 2. 계산기 유형이 있으면 매핑
    if calculation_types:
        first = calculation_types[0]
        cat = CATEGORY_MAP.get(first)
        if cat:
            return cat

    # 3. 질문 키워드 기반 분류 (계산기 미작동 시 폴백)
    if query:
        _KW_CATEGORY: list[tuple[list[str], str]] = [
            (["해고", "부당해고", "구제신청", "해고예고", "정리해고", "권고사직"], "해고"),
            (["퇴직금", "퇴직급여"], "퇴직금"),
            (["임금체불", "체불", "밀린 임금", "임금 미지급", "급여 미지급"], "임금체불"),
            (["실업급여", "구직급여", "실업", "구직활동"], "실업급여"),
            (["산재", "산업재해", "산재보험", "요양급여", "휴업급여", "장해급여"], "산업재해"),
            (["괴롭힘", "갑질", "폭언", "따돌림", "부당대우", "직장 내 괴롭힘"], "직장내 괴롭힘"),
            (["육아휴직", "출산휴가", "출산전후", "배우자출산"], "육아·출산"),
            (["연차", "연차수당", "연차휴가"], "휴가·휴일"),
            (["주휴", "주휴수당", "주휴일"], "휴가·휴일"),
            (["4대보험", "국민연금", "건강보험", "고용보험", "산재보험료"], "4대보험"),
            (["근로장려금", "EITC", "장려금"], "근로장려금"),
            (["연장수당", "야간수당", "휴일수당", "초과근무", "overtime"], "임금·수당"),
            (["최저임금", "최저시급"], "임금·수당"),
            (["임금", "급여", "월급", "시급", "수당", "포괄임금"], "임금·수당"),
            (["근로계약", "근로시간", "근로기준법", "근로조건"], "근로조건"),
            (["비정규직", "계약직", "파견", "기간제"], "비정규직"),
            (["노동조합", "단체교섭", "노조"], "노동조합"),
        ]
        for keywords, cat in _KW_CATEGORY:
            if any(kw in query for kw in keywords):
                return cat

    return "일반상담"


# ── 세션 관리 ────────────────────────────────────────────────────────────────

def ensure_session(sb: SupabaseClient, session_id: str) -> str:
    """세션이 없으면 생성, 있으면 updated_at 갱신"""
    try:
        existing = sb.table("qa_sessions").select("id").eq("id", session_id).execute()
        if existing.data:
            sb.table("qa_sessions").update({"updated_at": "now()"}).eq("id", session_id).execute()
        else:
            sb.table("qa_sessions").insert({"id": session_id}).execute()
    except Exception as e:
        logger.warning("세션 생성/갱신 실패 (session_id=%s): %s", session_id, e)
    return session_id


# ── 대화 저장 ────────────────────────────────────────────────────────────────

@dataclass
class ConversationRecord:
    session_id: str
    category: str
    question_text: str
    answer_text: str
    calculation_types: list[str] | None = None
    metadata: dict | None = None


def save_conversation(sb: SupabaseClient, record: ConversationRecord) -> str | None:
    """대화를 qa_conversations 테이블에 저장. 생성된 conversation_id 반환."""
    conv_id = str(uuid.uuid4())
    try:
        ensure_session(sb, record.session_id)
        sb.table("qa_conversations").insert({
            "id": conv_id,
            "session_id": record.session_id,
            "category": record.category,
            "question_text": record.question_text,
            "answer_text": record.answer_text,
            "calculation_types": record.calculation_types or [],
            "metadata": record.metadata or {},
        }).execute()
        logger.info("대화 저장 완료 (conv_id=%s, category=%s)", conv_id, record.category)
        return conv_id
    except Exception as e:
        logger.warning("대화 저장 실패: %s", e)
        return None


# ── 첨부파일 업로드 ──────────────────────────────────────────────────────────

# ── 세션 데이터 영속화 (conversation-memory) ─────────────────────────────────

def save_session_data(sb: SupabaseClient, session_id: str, snapshot: dict):
    """세션 스냅샷을 qa_sessions.session_data에 저장 (fire-and-forget)"""
    try:
        sb.table("qa_sessions").update({
            "session_data": snapshot,
            "updated_at": "now()",
        }).eq("id", session_id).execute()
    except Exception as e:
        logger.warning("세션 데이터 저장 실패: %s", e)


def restore_session_data(sb: SupabaseClient, session_id: str) -> dict | None:
    """qa_sessions에서 세션 데이터 복원. 24시간 TTL 초과 시 None 반환."""
    try:
        result = sb.table("qa_sessions").select(
            "session_data, updated_at"
        ).eq("id", session_id).execute()

        if not result.data:
            return None

        row = result.data[0]
        session_data = row.get("session_data")
        if not session_data:
            return None

        # TTL 검사: 24시간 초과 시 무시
        updated_at = row.get("updated_at")
        if updated_at:
            from datetime import datetime, timezone, timedelta
            updated = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - updated > timedelta(hours=24):
                return None

        return session_data
    except Exception as e:
        logger.warning("세션 복원 실패 (session_id=%s): %s", session_id, e)
        return None


def upload_attachment(
    sb: SupabaseClient,
    conversation_id: str,
    session_id: str,
    filename: str,
    content_type: str,
    file_data: bytes,
) -> str | None:
    """파일을 Supabase Storage에 업로드하고 qa_attachments에 메타 저장."""
    storage_path = f"{session_id}/{conversation_id}/{filename}"
    try:
        sb.storage.from_("chat-attachments").upload(
            path=storage_path,
            file=file_data,
            file_options={"content-type": content_type},
        )
        public_url = sb.storage.from_("chat-attachments").get_public_url(storage_path)

        sb.table("qa_attachments").insert({
            "conversation_id": conversation_id,
            "filename": filename,
            "content_type": content_type,
            "storage_path": storage_path,
            "public_url": public_url,
            "file_size": len(file_data),
        }).execute()
        logger.info("첨부파일 저장: %s (%d bytes)", filename, len(file_data))
        return public_url
    except Exception as e:
        logger.warning("첨부파일 업로드 실패 (%s): %s", filename, e)
        return None
