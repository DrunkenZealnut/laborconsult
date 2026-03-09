"""세션 관리 — 대화 이력 + pending 분석 상태 유지"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.models.schemas import AnalysisResult


@dataclass
class Session:
    id: str
    history: list = field(default_factory=list)   # [{"role": ..., "content": ...}]
    _pending_analysis: AnalysisResult | None = field(default=None, repr=False)

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
            "daily_work_hours": "소정근로시간",
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


# 인메모리 세션 스토어 (프로덕션에서는 Redis 등으로 교체)
_sessions: dict[str, Session] = {}


def get_or_create_session(session_id: str | None = None) -> Session:
    if session_id and session_id in _sessions:
        return _sessions[session_id]
    sid = session_id or uuid.uuid4().hex[:12]
    session = Session(id=sid)
    _sessions[sid] = session
    return session
