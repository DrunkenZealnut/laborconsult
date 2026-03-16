"""세션 관리 — 대화 이력 + pending 분석 상태 + 계산 캐시 + 대화 요약"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from app.models.schemas import AnalysisResult


@dataclass
class Session:
    id: str
    history: list = field(default_factory=list)   # [{"role": ..., "content": ...}]
    _pending_analysis: AnalysisResult | None = field(default=None, repr=False)

    # ── 대화 맥락 유지 (conversation-memory) ──
    summary: str = ""                                    # 6턴 이전 대화의 구조화 요약
    calc_cache: dict = field(default_factory=dict)       # {calc_type: extracted_info}
    created_at: float = field(default_factory=time.time) # 세션 생성 시각

    def add_user(self, text: str):
        self.history.append({"role": "user", "content": text})

    def add_assistant(self, text: str):
        self.history.append({"role": "assistant", "content": text})

    def recent(self, max_turns: int = 6) -> list:
        """최근 N턴 대화 이력 반환"""
        return self.history[-(max_turns * 2):]

    # ── pending 분석 상태 (추가정보 수집용) ──

    def has_pending_info(self) -> bool:
        return self._pending_analysis is not None

    def save_pending(self, analysis: AnalysisResult):
        self._pending_analysis = analysis

    def merge_with_pending(self, new_analysis: AnalysisResult, user_reply: str) -> AnalysisResult:
        """기존 pending analysis + 새로 추출된 정보를 병합

        최저임금 키워드 감지: user_reply에 '최저시급' 등이 있으면
        LLM이 환각한 wage_amount를 제거하고 use_minimum_wage=true를 강제 설정.
        """
        merged = self._pending_analysis

        # 최저임금 키워드 감지 → LLM 환각 방지 (merge 레벨)
        _MW_KEYWORDS = ("최저시급", "최저임금으로", "최저임금 기준")
        if any(kw in user_reply for kw in _MW_KEYWORDS):
            new_analysis.extracted_info["use_minimum_wage"] = True
            new_analysis.extracted_info.pop("wage_amount", None)
            new_analysis.extracted_info.setdefault("wage_type", "시급")

        for key, val in new_analysis.extracted_info.items():
            if val is not None:
                merged.extracted_info[key] = val

        # missing_info 정리: 새로 추출된 키에 해당하는 설명 제거
        # extracted_info 키(영어) → missing_info 설명(한국어) 매핑
        _FIELD_TO_DESC = {
            "wage_amount": "임금", "monthly_wage": "임금", "annual_wage": "임금",
            "hourly_wage": "임금", "daily_wage": "임금", "use_minimum_wage": "임금",
            "daily_work_hours": "소정근로시간", "weekly_total_hours": "소정근로시간",
            "weekly_work_days": "근무일수",
            "business_size": "근로자 규모",
            "start_date": "입사일", "service_period_text": "근무기간",
        }
        resolved_descs = set()
        for key in new_analysis.extracted_info:
            desc = _FIELD_TO_DESC.get(key, "")
            if desc:
                resolved_descs.add(desc)

        merged.missing_info = [
            m for m in merged.missing_info
            if not any(desc in m for desc in resolved_descs)
        ]
        self._pending_analysis = None
        return merged

    def clear_pending(self):
        self._pending_analysis = None

    # ── 계산 결과 캐싱 ──

    def cache_calculation(self, calc_type: str, extracted_info: dict):
        """계산 결과의 입력 파라미터를 캐싱"""
        if calc_type not in self.calc_cache:
            self.calc_cache[calc_type] = {}
        self.calc_cache[calc_type].update(
            {k: v for k, v in extracted_info.items() if v is not None}
        )

    def get_cached_info(self) -> dict:
        """모든 캐시된 계산 파라미터를 병합하여 반환 (최신 값 우선)"""
        merged = {}
        for info in self.calc_cache.values():
            for k, v in info.items():
                merged[k] = v
        return merged

    # ── 대화 요약 (condensation) ──

    def condense_if_needed(self, max_turns: int = 6):
        """6턴 초과 시 오래된 대화를 summary로 압축"""
        if len(self.history) <= max_turns * 2:
            return

        old_messages = self.history[:-(max_turns * 2)]
        new_summary_parts = []

        for i in range(0, len(old_messages), 2):
            user_msg = old_messages[i].get("content", "")[:100]
            asst_msg = old_messages[i + 1].get("content", "")[:100] if i + 1 < len(old_messages) else ""
            new_summary_parts.append(f"Q: {user_msg} / A: {asst_msg}")

        condensed = "; ".join(new_summary_parts)

        if self.summary:
            self.summary = self.summary + " | " + condensed
        else:
            self.summary = condensed

        # 2KB 제한
        if len(self.summary) > 2000:
            self.summary = self.summary[-2000:]

        self.history = self.history[-(max_turns * 2):]

    # ── 직렬화 (Supabase 영속 저장용) ──

    def to_snapshot(self) -> dict:
        """Supabase 저장용 스냅샷"""
        return {
            "summary": self.summary,
            "calc_cache": self.calc_cache,
            "history_tail": self.history[-4:],  # 최근 2턴만
        }

    @classmethod
    def from_snapshot(cls, session_id: str, snapshot: dict) -> "Session":
        """스냅샷에서 Session 복원"""
        session = cls(id=session_id)
        session.summary = snapshot.get("summary", "")
        session.calc_cache = snapshot.get("calc_cache", {})
        session.history = snapshot.get("history_tail", [])
        return session


# 인메모리 세션 스토어 (프로덕션에서는 Redis 등으로 교체)
_sessions: dict[str, Session] = {}


def get_or_create_session(
    session_id: str | None = None,
    restore_fn: Callable[[str], dict | None] | None = None,
) -> tuple[Session, bool]:
    """세션 조회/생성. (session, is_restored) 반환."""
    if session_id and session_id in _sessions:
        return _sessions[session_id], False

    # Layer 3: Supabase 복원 시도
    if session_id and restore_fn:
        try:
            snapshot = restore_fn(session_id)
            if snapshot:
                session = Session.from_snapshot(session_id, snapshot)
                _sessions[session_id] = session
                return session, True
        except Exception:
            pass  # graceful fallback

    sid = session_id or uuid.uuid4().hex[:12]
    session = Session(id=sid)
    _sessions[sid] = session
    return session, False
