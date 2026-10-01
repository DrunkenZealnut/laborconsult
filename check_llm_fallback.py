"""LLM 폴백 감시 — 최근 실사용 답변 3건이 연속 저하면 실패(exit 1)해 알린다 (llm-fallback-alert).

GitHub Actions(.github/workflows/llm-fallback-alert.yml)가 6시간마다 돌린다. 실패하면 GitHub가
저장소 소유자에게 실패 메일을 보낸다 — 이 스크립트에는 발송 코드가 없다.

왜 필요한가: 폴백은 장애를 흡수해 답변을 정상으로 보이게 한다. 실측(2026-10-02) 8-21~9-28 38일간
프로덕션 실사용 답변 17/17이 폴백이었고(anthropic SDK 1.x 자동 설치), 같은 기간 로컬·벤치마크는
전부 Claude 성공이라 아무도 몰랐다. 이 판정이 있었다면 8-22에 잡혔다.

사용법:
    python3 check_llm_fallback.py              # 판정 (exit 0 정상·판정불가 / 1 알림 / 2 감시 실패)
    python3 check_llm_fallback.py --window 5

지킬 것 셋:
- **"Claude가 아님"으로 판정하지 말 것.** 관리자 화면에서 1순위를 OpenAI로 두면 attempts=['OpenAI']가
  정상이다. 저하는 "1순위가 실패해 다음으로 넘어갔다"(fallback)이다.
- **감시 자신은 fail-closed다.** 조회가 실패하면 exit 2로 실패한다 — 파이프라인처럼 조용히 넘어가면
  감시가 죽은 것도 조용해진다.
- **대화 본문은 읽지 않는다.** Actions 로그는 저장소 협업자에게 보인다. metadata만 조회한다.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

DEFAULT_WINDOW = 3
FETCH_LIMIT = 50          # 합성 행이 섞여도 실사용 window건을 확보할 여유
KST = timezone(timedelta(hours=9))


@dataclass
class Verdict:
    status: str                                   # "ok" | "alert" | "insufficient"
    considered: list = field(default_factory=list)  # [(row, reasons)] 최근 → 과거


def degraded(llm: dict) -> list[str]:
    """저하 사유 목록. 빈 목록이면 정상.

    truncated는 넣지 않는다 — 긴 답변의 정상 절단·네트워크 끊김이 섞여 있고, 별도 고지와
    게시판 제외가 이미 있다. 폴백 감시와는 다른 신호다.
    """
    reasons = []
    if llm.get("fallback") or len(llm.get("attempts") or []) > 1:
        reasons.append("fallback")
    if llm.get("empty"):
        reasons.append("empty")
    if llm.get("intent_provider"):
        reasons.append("intent_fallback")
    return reasons


def judge(rows: list[dict], window: int = DEFAULT_WINDOW) -> Verdict:
    """rows: qa_conversations 행(정렬 무관). 합성·llm 메타 없는 행은 제외한다."""
    real = [r for r in rows
            if not (r.get("metadata") or {}).get("synthetic") and (r.get("metadata") or {}).get("llm")]
    real.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    picked = [(r, degraded(r["metadata"]["llm"])) for r in real[:window]]
    if len(picked) < window:
        return Verdict("insufficient", picked)
    return Verdict("alert" if all(reasons for _, reasons in picked) else "ok", picked)


def fetch_recent(db, limit: int = FETCH_LIMIT) -> list[dict]:
    return db.table("qa_conversations").select("id,created_at,metadata") \
        .order("created_at", desc=True).limit(limit).execute().data or []


def _kst(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(KST).strftime("%m-%d %H:%M")
    except (ValueError, AttributeError):
        return str(ts)


def render(verdict: Verdict, window: int) -> str:
    title = {"ok": "✅ 정상", "alert": f"🚨 최근 실사용 {window}건 연속 폴백",
             "insufficient": f"– 판정 불가(실사용 {len(verdict.considered)}건 < {window})"}[verdict.status]
    lines = [f"## LLM 폴백 감시: {title}", "",
             "| 시각(KST) | provider | model | attempts | 저하 사유 |", "|---|---|---|---|---|"]
    for row, reasons in verdict.considered:
        llm = row["metadata"]["llm"]
        lines.append(f"| {_kst(row.get('created_at'))} | {llm.get('provider')} | {llm.get('model') or '—'} | "
                     f"{' → '.join(llm.get('attempts') or [])} | {', '.join(reasons) or '—'} |")
    if verdict.status == "alert":
        lines += ["", "Vercel 런타임 로그에서 `답변 생성 실패, 다음 제공자로 전환`·`의도분석 Claude 실패` 줄의 "
                      "오류 원문을 확인할 것(사용 한도·키·SDK 버전·모델 폐기가 지금까지의 원인이었다)."]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="LLM 폴백 감시")
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    try:
        from app.core.storage import make_supabase_client
        db = make_supabase_client(postgrest_timeout=15)
        if db is None:
            raise RuntimeError("SUPABASE_URL / SUPABASE_KEY 미설정")
        rows = fetch_recent(db)
    except Exception as e:  # noqa: BLE001 — 감시 실패는 실패로 드러나야 한다
        print(f"::error::폴백 감시 조회 실패 — {type(e).__name__}: {str(e)[:200]}")
        return 2

    verdict = judge(rows, args.window)
    report = render(verdict, args.window)
    print(report)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(report + "\n")
    if verdict.status == "alert":
        print(f"::error::최근 실사용 답변 {args.window}건이 모두 1순위 제공자 실패 후 폴백으로 생성됐습니다")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
