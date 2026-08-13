"""Supabase Q&A 저장 — 질문·답변·첨부파일 영구 보관"""

from __future__ import annotations

import base64
import logging
import os
import uuid
from dataclasses import dataclass

from supabase import Client as SupabaseClient

logger = logging.getLogger(__name__)


# ── Supabase 접속 ───────────────────────────────────────────────────────────
#
# ⚠️ **기본 스키마는 public 이 아니라 laborconsult 다.**
#    2026-08-13, 이 프로젝트는 다른 앱과 Supabase public 스키마를 공유하다가
#    board_posts 이름 충돌로 남의 테이블을 자기 것으로 오인했다(구 단위 권한
#    모델을 쓰는 별개 앱이었다). public 으로 떨어지면 같은 사고가 재발한다.
#
# ⚠️ **접속은 반드시 이 함수로만 만들 것.** create_client() 를 직접 부르면
#    스키마 옵션이 빠져 public 으로 새고, 그 실패가 조용하다 — 테이블이 없으면
#    PGRST205, 있으면 남의 것을 건드린다.
#
# 여기(app/core/storage.py)에 두는 이유는 PUBLIC_EXCLUDE_KEYS·BOARD_POST_COLUMNS
# 와 같다 — FastAPI·pipeline·API 키에 의존하지 않아 앱과 운영 스크립트가 모두
# import 할 수 있는 유일한 지점이다.
SUPABASE_SCHEMA_DEFAULT = "laborconsult"


def make_supabase_client(url: str | None = None, key: str | None = None):
    """laborconsult 스키마로 고정된 Supabase 클라이언트. 미설정 시 None."""
    url = url or os.getenv("SUPABASE_URL")
    key = key or os.getenv("SUPABASE_KEY")
    if not (url and key):
        return None

    schema = os.getenv("SUPABASE_SCHEMA") or SUPABASE_SCHEMA_DEFAULT
    if schema == "public":
        # 값으로 허용은 하되 조용히 넘어가지 않는다 — 실수로 넣었을 때 드러나야 한다.
        logger.warning(
            "SUPABASE_SCHEMA=public — 다른 앱과 테이블 이름이 충돌할 수 있습니다. "
            "의도한 설정이 아니면 제거하세요(기본값 %s).", SUPABASE_SCHEMA_DEFAULT,
        )

    from supabase import create_client
    from supabase.lib.client_options import SyncClientOptions

    client = create_client(url, key, options=SyncClientOptions(schema=schema))
    # 어느 스키마에 붙었는지 사후에 확인할 방법이 없으면 이번 사고처럼 진단이 길어진다.
    logger.info("Supabase 연결: schema=%s host=%s", schema, url.split("//")[-1].split(".")[0])
    return client

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
    (["소정근로시간", "근로시간 계산", "근로시간계산", "월 근로시간", "월근로시간"], ["working_hours"]),
    (["주 52시간", "주52시간", "52시간"], ["weekly_hours_check"]),
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


# ── board_posts 스키마 계약 ─────────────────────────────────────────────────
#
# 사용자 직접 작성 게시글 테이블의 컬럼 집합. 여기(app/core/storage.py)에 두는
# 이유는 PUBLIC_EXCLUDE_KEYS와 같다 — 이 모듈은 FastAPI·pipeline·API 키 어디에도
# 의존하지 않아 API(api/index.py)·점검 스크립트(check_schema.py)·테스트가 모두
# import할 수 있는 유일한 지점이다.
#
# ⚠️ DDL은 supabase_board_posts.sql이 단일 출처다. 여기를 고치면 그 파일도
#    함께 고칠 것 — test_offline_units.py::test_board_posts_schema_source가
#    두 소스를 대조해 고정한다.
#
# ⚠️ 이 대조는 **파일과 코드**만 본다. 실제 DB가 어긋났는지는 CI에서 알 수 없다
#    (자격증명 없음). 그건 check_schema.py의 몫이고, 2026-08-13에 발견된 드리프트
#    (8컬럼 중 5개 결손)가 정확히 그 유형이었다.
BOARD_POST_COLUMNS = (
    "id",
    "nickname",
    "password_hash",
    "category",
    "question_text",
    "status",
    "ip_hash",
    "created_at",
)

# 공개 응답에 실어도 되는 컬럼. password_hash·ip_hash·status는 **의도적으로 제외**한다
# — 해시는 유출 대상이고, ip_hash는 개인정보, status는 내부 상태다. 편의로 여기에
# 추가하는 회귀는 test_offline_units.py가 막는다.
BOARD_POST_PUBLIC_COLUMNS = (
    "id",
    "nickname",
    "category",
    "question_text",
    "created_at",
)


def board_post_select(columns=BOARD_POST_PUBLIC_COLUMNS) -> str:
    """PostgREST select 문자열. 호출부가 컬럼을 각자 나열하면 다시 갈라진다."""
    return ", ".join(columns)


# ── 공개 게시판 노출 계약 ────────────────────────────────────────────────────
#
# 이 키가 metadata에 있으면 공개 게시판(api/index.py::board_*)에서 제외한다.
#   guard_flag — 가드 의심(monitor) 대화 (chatbot-security FR-09)
#   truncated  — 스트림 절단으로 완결되지 않은 답변 (llm-fallback-hardening FR-02)
#   textbook   — 저작권 있는 해설서를 근거로 쓴 답변 (textbook-corpus-embedding G6)
#   synthetic  — 벤치마크·CLI·테스트가 만든 대화 (board-duplicate-cleanup)
#
# 여기(app/core/storage.py)에 두는 이유: 노출 여부를 **읽는** 쪽은 api/index.py이고
# **쓰는** 쪽은 pipeline.py·이 파일인데, 운영 스크립트(dedupe_board.py)도 같은
# 규칙이 필요하다. 이 모듈은 FastAPI·pipeline·API 키에 의존하지 않아 셋 모두가
# import할 수 있는 유일한 지점이다.
#
# ⚠️ 이 키들은 **True일 때만 기록한다.** PostgREST 필터는 키 부재(`IS NULL`)로,
#    Python 후처리는 truthiness로 판정하므로 `{"truncated": False}`처럼 명시적
#    False를 쓰면 두 경로가 갈라진다.
PUBLIC_EXCLUDE_KEYS = ("guard_flag", "truncated", "textbook", "synthetic")


def is_public_excluded(meta) -> bool:
    """공개 게시판 제외 대상인지."""
    return isinstance(meta, dict) and any(meta.get(k) for k in PUBLIC_EXCLUDE_KEYS)


# 세션 ID를 직접 만드는 호출부(벤치마크·모델비교·검증 스크립트)를 위한 규약.
# 이 접두사로 시작하는 세션의 대화는 공개 게시판에 노출하지 않는다.
#
# ⚠️ 열거형이라 **열린 기본값**이다 — 등록되지 않은 접두사는 잡히지 않는다.
#    새 스크립트는 여기 등록하거나 metadata["synthetic"]을 직접 설정할 것.
#    (닫힌 기본값으로 뒤집으려면 abuse_guard의 세션 수용 정규식을 발급 형태
#    `^[0-9a-f]{12}$`와 일치시켜야 하는데, 그러면 구 클라이언트의 세션 이력이
#    끊긴다. 현재 이 가드가 단독으로 잡는 케이스가 0건이라 미뤄 둔 판단이다.)
SYNTHETIC_SESSION_PREFIXES = ("bench_", "test_", "cmp_", "verify_", "eval_")


def _is_synthetic_session(session_id: str | None) -> bool:
    """예약 접두사 세션인지 판정 (board-duplicate-cleanup G-C).

    정상 세션 ID는 uuid4().hex[:12] 형태라 이 접두사와 겹치지 않는다
    (16진수 문자만 나오므로 's'·'_'가 포함될 수 없다).
    """
    return (session_id or "").startswith(SYNTHETIC_SESSION_PREFIXES)


def save_conversation(sb: SupabaseClient, record: ConversationRecord) -> str | None:
    """대화를 qa_conversations 테이블에 저장. 생성된 conversation_id 반환."""
    conv_id = str(uuid.uuid4())

    # G-C: 예약 접두사 백스톱. save_conversation은 pipeline.py의 단일 호출부를
    # 갖는 초크포인트라 여기에 두면 향후 저장 경로가 늘어도 가드가 새지 않는다.
    #
    # ⚠️ 현재 이 가드가 **단독으로** 잡는 케이스는 0건이다 — 예약 접두사 세션은
    #    인프로세스 호출부에서만 생기고(웹은 abuse_guard의 세션 정규식이 '_'를
    #    받지 않아 신규 hex12를 발급한다) 그 집합은 정확히 `guard_ctx is None`,
    #    즉 pipeline.py의 G-A가 이미 덮는 범위다. 부하를 지는 것은 G-A이므로
    #    "G-C가 다 잡으니 G-A는 중복"이라 판단해 G-A를 지우지 말 것.
    #
    # record.metadata를 제자리 변경하면 호출부가 이후 참조하는 값이 오염되므로
    # 반드시 복사본을 쓴다.
    metadata = dict(record.metadata or {})
    try:
        if _is_synthetic_session(record.session_id):
            metadata["synthetic"] = True
    except Exception as e:  # 가드 실패가 저장을 막지 않는다 (fail-open)
        logger.warning("합성 세션 판정 실패 (저장은 계속): %s", e)

    try:
        ensure_session(sb, record.session_id)
        sb.table("qa_conversations").insert({
            "id": conv_id,
            "session_id": record.session_id,
            "category": record.category,
            "question_text": record.question_text,
            "answer_text": record.answer_text,
            "calculation_types": record.calculation_types or [],
            "metadata": metadata,
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


def _safe_storage_name(filename: str) -> str:
    """스토리지 키용 파일명 정제 — 경로 구분자·특수문자를 제거해 프리픽스
    이탈(../ 등)을 차단하고 S3 안전 문자만 남긴다. 표시용 원본 파일명은
    qa_attachments.filename에 따로 보존되므로 손실 없음."""
    import re
    base = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", base).strip("._") or "file"
    return safe[:100]  # 과도한 길이 방지


def upload_attachment(
    sb: SupabaseClient,
    conversation_id: str,
    session_id: str,
    filename: str,
    content_type: str,
    file_data: bytes,
) -> str | None:
    """파일을 Supabase Storage에 업로드하고 qa_attachments에 메타 저장. storage_path 반환.

    chat-attachments 버킷은 비공개다(supabase_attachments_private.sql). 따라서
    영구 공개 URL을 만들지도, 저장하지도 않는다 — 열람은 관리자 조회 시점에
    발급하는 1시간 만료 signed URL로만 이루어진다(api/index.py::admin_conversation_detail).
    public_url 컬럼은 admin.html 하위호환을 위해 남겨 두되 항상 NULL로 둔다.
    """
    # uuid 프리픽스로 키를 고유화 — 같은 대화에 동일 파일명 2개 첨부 시
    # 두 번째 업로드가 중복 키로 실패하던 문제 방지
    storage_path = (
        f"{session_id}/{conversation_id}/"
        f"{uuid.uuid4().hex[:8]}_{_safe_storage_name(filename)}"
    )
    try:
        sb.storage.from_("chat-attachments").upload(
            path=storage_path,
            file=file_data,
            file_options={"content-type": content_type},
        )

        sb.table("qa_attachments").insert({
            "conversation_id": conversation_id,
            "filename": filename,
            "content_type": content_type,
            "storage_path": storage_path,
            "public_url": None,
            "file_size": len(file_data),
        }).execute()
        logger.info("첨부파일 저장: %s (%d bytes)", filename, len(file_data))
        return storage_path
    except Exception as e:
        logger.warning("첨부파일 업로드 실패 (%s): %s", filename, e)
        return None
