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

법령 조회 감시(production-law-api-recovery D11) — 같은 실행·같은 종료 코드 규약으로 판정한다.
프로덕션 법제처 조회는 IP 미등록으로 6주 넘게 전부 실패했는데 아무에게도 보이지 않았다.
  ① 예열 상태(`law_article_cache`의 `meta:law_warm_status`): 마지막 실행 후 36시간 초과, `laws_failed`가
     비어 있지 않음, 행 수가 직전 대비 20% 넘게 감소, 상태 행 없음 → 알림. 조회 실패는 exit 2.
  ② 조문 성공률: 조문을 요청한 최근 실사용 10건에서 Σok / Σ(requested − skipped_unwarmed − deleted) < 0.8 → 알림.
     deleted(삭제된 조문 요청, law-article-coverage D5)는 존재하지 않는 조문 요청과 같은 취급이라 분모에서 뺀다.
     분모 합이 20 미만이면 보류한다. CLAUDE.md가 금지한 것은 **대화 단위** 비율(하루 0~5건이라 1건으로
     100%가 된다)이고, 이 조건은 요청 수 합(대화당 5~10건)으로 판정한다.
  ③ 인증 오류: `live=on`인 대화에서 auth_error > 0 → 알림(고정 IP 전환 뒤에 의미가 있다).
  `metadata.law_api` v2(`{"live", "articles", "precedents"}`)만 읽고 옛 평평한 구조는 건너뛴다.
  이 스크립트는 legal_api를 import하지 않는다 — Actions는 supabase만 설치한다(requests 없음).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

DEFAULT_WINDOW = 3
PAGE_SIZE = 50
MAX_PAGES = 20            # 최대 1,000행 — 벤치마크가 합성 행을 수십 건씩 쌓아도 실사용 window건을 찾는다
KST = timezone(timedelta(hours=9))

LAW_WINDOW = 10           # ② 조문을 요청한 최근 실사용 대화 수
LAW_MIN_DENOMINATOR = 20  # ② 분모(요청 − 예열 밖) 합이 이보다 작으면 판정 보류
LAW_MIN_OK_RATE = 0.8
WARM_MAX_AGE = timedelta(hours=36)
WARM_MAX_DROP = 0.2


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


def is_real(r: dict) -> bool:
    meta = r.get("metadata") or {}
    return not meta.get("synthetic") and bool(meta.get("llm"))


def judge(rows: list[dict], window: int = DEFAULT_WINDOW) -> Verdict:
    """rows: qa_conversations 행(정렬 무관). 합성·llm 메타 없는 행은 제외한다."""
    # offset 페이지 사이에 새 행이 저장되면 경계 행이 다음 페이지에 다시 온다 — 같은 행을 두 표본으로
    # 세면 오탐이다(CodeRabbit PR #89). 새 행은 offset을 뒤로 밀 뿐이라 누락은 없고 중복만 생긴다.
    seen, real = set(), []
    for r in rows:
        key = r.get("id") or (r.get("created_at"), id(r))
        if is_real(r) and key not in seen:
            seen.add(key)
            real.append(r)
    real.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    picked = [(r, degraded(r["metadata"]["llm"])) for r in real[:window]]
    if len(picked) < window:
        return Verdict("insufficient", picked)
    return Verdict("alert" if all(reasons for _, reasons in picked) else "ok", picked)


def fetch_recent(db, window: int = DEFAULT_WINDOW) -> list[dict]:
    """실사용 행을 window개 모을 때까지 페이지를 이어 조회한다.

    고정 limit으로 한 번만 읽으면 벤치마크가 쌓은 합성 행이 창을 가득 채워, 실사용 폴백이
    창 밖으로 밀려나 '판정 불가'로 통과한다(CodeRabbit PR #89 — 실측 8-24에 수 분간 합성 ~25건).
    기록을 다 읽었을 때만 표본 부족이다.
    """
    rows: list[dict] = []
    for page in range(MAX_PAGES):
        chunk = db.table("qa_conversations").select("id,created_at,metadata") \
            .order("created_at", desc=True).range(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE - 1) \
            .execute().data or []
        rows += chunk
        if sum(map(is_real, rows)) >= window or len(chunk) < PAGE_SIZE:
            break
    return rows


def _kst(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(KST).strftime("%m-%d %H:%M")
    except (ValueError, AttributeError):
        return str(ts)


# ── 법령 조회 감시 (production-law-api-recovery D11) ──────────────────────────

@dataclass
class LawVerdict:
    status: str                                    # "ok" | "alert"
    reasons: list = field(default_factory=list)    # 알림 사유
    notes: list = field(default_factory=list)      # 보류·참고(알림 아님)
    ok_rate: float | None = None
    denominator: int = 0
    sampled: int = 0


def law_record(row: dict) -> dict | None:
    """v2 metadata.law_api(조문·판례 분리)만. 옛 평평한 구조·요청 0건은 None."""
    rec = (row.get("metadata") or {}).get("law_api")
    if not isinstance(rec, dict) or not isinstance(rec.get("articles"), dict):
        return None
    return rec


def _article_requested(rec: dict) -> bool:
    return (rec.get("articles") or {}).get("requested", 0) > 0


def fetch_recent_law(db, window: int = LAW_WINDOW) -> list[dict]:
    """조문을 요청한 실사용 행을 window개 모을 때까지(또는 기록 끝·MAX_PAGES) 페이지를 이어 조회한다."""
    rows: list[dict] = []
    for page in range(MAX_PAGES):
        chunk = db.table("qa_conversations").select("id,created_at,metadata") \
            .order("created_at", desc=True).range(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE - 1) \
            .execute().data or []
        rows += chunk
        # 페이지 사이에 새 행이 저장되면 경계 행이 다음 페이지에 다시 온다 — judge_law처럼 id로 중복을
        # 빼고 세야 한다. 두 번 세면 실제 표본이 window보다 적은 채로 멈춰 분모가 모자라 판정이 보류된다
        # (CodeRabbit PR #102).
        seen: set = set()
        for r in rows:
            if is_real_law(r) and _article_requested(law_record(r)):
                seen.add(r.get("id") or (r.get("created_at"), id(r)))
        if len(seen) >= window or len(chunk) < PAGE_SIZE:
            break
    return rows


def is_real_law(r: dict) -> bool:
    meta = r.get("metadata") or {}
    return not meta.get("synthetic") and law_record(r) is not None


def fetch_warm_status(db) -> dict | None:
    """예열 상태 행 — 만료 필터 없이 원시 조회한다(D12). 행이 없으면 None, 조회 실패는 예외(exit 2)."""
    from app.core.storage import LAW_WARM_STATUS_KEY
    data = db.table("law_article_cache").select("content") \
        .eq("cache_key", LAW_WARM_STATUS_KEY).execute().data or []
    if not data:
        return None
    try:
        return json.loads(data[0]["content"])
    except (TypeError, ValueError, KeyError):
        return {"_unparsed": True}


def judge_warm(status: dict | None, now: datetime) -> list[str]:
    """① 예열 상태의 알림 사유."""
    if status is None:
        return ["예열 상태 행 없음(warm_law_cache.py가 한 번도 끝나지 않았거나 행이 지워졌다)"]
    if status.get("_unparsed"):
        return ["예열 상태 행을 해석할 수 없음"]
    reasons = []
    try:
        at = datetime.fromisoformat(str(status.get("at")).replace("Z", "+00:00"))
        if now - at > WARM_MAX_AGE:
            reasons.append(f"예열 마지막 실행 {_kst(status['at'])} — {WARM_MAX_AGE.total_seconds() / 3600:.0f}시간 초과"
                           "(맥이 꺼져 있거나 launchd 작업이 멈췄다)")
    except (TypeError, ValueError):
        reasons.append("예열 상태의 실행 시각을 해석할 수 없음")
    if status.get("laws_failed"):
        reasons.append(f"예열 실패 법령: {', '.join(status['laws_failed'])}")
    rows, prev = status.get("rows") or 0, status.get("prev_rows")
    if prev and rows < prev * (1 - WARM_MAX_DROP):
        reasons.append(f"예열 행 수 감소 {prev:,} → {rows:,}(-{(1 - rows / prev) * 100:.0f}%)")
    return reasons


def judge_law(rows: list[dict], warm_status: dict | None, now: datetime | None = None,
              window: int = LAW_WINDOW) -> LawVerdict:
    now = now or datetime.now(timezone.utc)
    reasons = judge_warm(warm_status, now)
    notes: list[str] = []

    seen, real = set(), []
    for r in rows:
        key = r.get("id") or (r.get("created_at"), id(r))
        if is_real_law(r) and key not in seen:
            seen.add(key)
            real.append(r)
    real.sort(key=lambda r: r.get("created_at") or "", reverse=True)

    # ② 조문 성공률 — 조문을 요청한 최근 window건
    picked = [law_record(r) for r in real if _article_requested(law_record(r))][:window]
    ok = sum((rec["articles"].get("ok") or 0) for rec in picked)
    denom = sum((rec["articles"].get("requested") or 0) - (rec["articles"].get("skipped_unwarmed") or 0)
                - (rec["articles"].get("deleted") or 0) for rec in picked)
    rate = ok / denom if denom > 0 else None
    if denom < LAW_MIN_DENOMINATOR:
        notes.append(f"조문 성공률 판정 보류(요청 {denom} < {LAW_MIN_DENOMINATOR}, 대화 {len(picked)}건)")
    elif rate < LAW_MIN_OK_RATE:
        reasons.append(f"조문 성공률 {rate:.0%} < {LAW_MIN_OK_RATE:.0%}(최근 {len(picked)}건, {ok}/{denom})")

    # ③ 실호출이 켜진 대화의 인증 오류 — 최근 v2 기록 window건
    auth = [rec for rec in map(law_record, real[:window]) if rec.get("live") == "on"
            and ((rec.get("articles") or {}).get("auth_error", 0) + (rec.get("precedents") or {}).get("auth_error", 0)) > 0]
    if auth:
        reasons.append(f"실호출(live=on) 인증 오류 {len(auth)}건 — 법제처 등록 IP·키를 확인할 것")
    return LawVerdict("alert" if reasons else "ok", reasons, notes, rate, denom, len(picked))


def render_law(v: LawVerdict, status: dict | None) -> str:
    title = "🚨 알림" if v.status == "alert" else "✅ 정상"
    lines = [f"## 법령 조회 감시: {title}", ""]
    if status and not status.get("_unparsed"):
        lines.append(f"- 예열: {_kst(str(status.get('at')))} · {status.get('rows') or 0:,}행 · "
                     f"성공 {len(status.get('laws_ok') or [])}종 · 실패 {len(status.get('laws_failed') or {})}종")
    rate = "—" if v.ok_rate is None else f"{v.ok_rate:.0%}"
    lines.append(f"- 조문 성공률: {rate} (최근 {v.sampled}건, 분모 {v.denominator})")
    lines += [f"- 🚨 {r}" for r in v.reasons] + [f"- {n}" for n in v.notes]
    return "\n".join(lines)


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
        rows = fetch_recent(db, args.window)
        law_rows = fetch_recent_law(db)
        warm_status = fetch_warm_status(db)
    except Exception as e:  # noqa: BLE001 — 감시 실패는 실패로 드러나야 한다
        print(f"::error::폴백 감시 조회 실패 — {type(e).__name__}: {str(e)[:200]}")
        return 2

    verdict = judge(rows, args.window)
    law_verdict = judge_law(law_rows, warm_status)
    report = render(verdict, args.window) + "\n\n" + render_law(law_verdict, warm_status)
    print(report)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(report + "\n")
    if verdict.status == "alert":
        print(f"::error::최근 실사용 답변 {args.window}건이 모두 1순위 제공자 실패 후 폴백으로 생성됐습니다")
    for reason in law_verdict.reasons:
        print(f"::error::법령 조회 감시 — {reason}")
    return 1 if (verdict.status == "alert" or law_verdict.status == "alert") else 0


if __name__ == "__main__":
    sys.exit(main())
