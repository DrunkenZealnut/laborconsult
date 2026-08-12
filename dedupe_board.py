#!/usr/bin/env python3
"""질문게시판 중복 정리 — 같은 질문의 반복 게시글을 그룹당 최신 1건만 남기고 삭제.

설계: docs/02-design/features/board-duplicate-cleanup.design.md

    python3 dedupe_board.py                          # dry-run (기본) — 쓰기 0건
    python3 dedupe_board.py --apply                  # 백업 후 실제 삭제
    python3 dedupe_board.py --apply --purge-sessions # + 고아 세션 정리 (옵트인)
    python3 dedupe_board.py --backup-dir ./backups   # 백업 경로 지정

⚠️ 하드 삭제는 되돌릴 수 없다. --apply는 백업 JSON 생성에 성공해야만 삭제로 진입한다.

⚠️ qa_conversations.session_id는 ON DELETE CASCADE다. 세션 행을 지우면 그 세션의
   남은 대화까지 함께 사라진다 — 벤치마크 세션 하나가 대화 4건을 갖고 그중 1건이
   유지 대상인 상황이 실제로 있으므로, --purge-sessions는 삭제 직전 세션별 잔여
   대화 수를 재조회해 0인 것만 지운다.

이 모듈의 순수 함수(_norm_question·pick_representative·group_by_question)는
test_offline_units.py가 import한다 — Supabase 클라이언트 생성은 main() 안에서만
하므로 API 키 없이도 import된다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict

# api/index.py::_PUBLIC_EXCLUDE_KEYS 와 같은 계약. 여기서 재선언하는 이유는
# 이 스크립트가 FastAPI 앱을 import하지 않기 때문이다(운영 스크립트 관례).
PUBLIC_EXCLUDE_KEYS = ("guard_flag", "truncated", "textbook", "synthetic")

DELETE_BATCH_SIZE = 50   # UUID 36자 × 50 ≈ 1.9KB — PostgREST 쿼리스트링 여유 확보
PAGE_SIZE = 1000         # Supabase range() 한계


# ── 순수 함수 (오프라인 테스트 대상) ─────────────────────────────────────────

def _norm_question(t: str) -> str:
    """중복 판정용 질문 정규화.

    NFC 선행이 필수다 — 한글이 NFD(자모 분해)로 들어오면 완성형과 다른 키가 되어
    같은 질문이 갈라진다. pinecone_upload_legal.py가 이 누락으로 474벡터를
    덮어쓴 전례가 있다.

    `\\w`가 유니코드 모드에서 한글을 이미 포함하지만, 의도를 명시하는 방어적
    표기로 `가-힣`을 함께 둔다.
    """
    t = unicodedata.normalize("NFC", t or "").lower()
    return re.sub(r"[^\w가-힣]", "", t)


def is_public_excluded(meta) -> bool:
    """공개 게시판 제외 대상인지 — api/index.py::_is_public_excluded 와 동일 규칙."""
    return isinstance(meta, dict) and any(meta.get(k) for k in PUBLIC_EXCLUDE_KEYS)


def group_by_question(rows: list[dict]) -> dict[str, list[dict]]:
    """정규화된 질문을 키로 묶는다. 빈 키(질문 전체가 기호)는 버린다."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        key = _norm_question(row.get("question_text", ""))
        if key:
            groups[key].append(row)
    return dict(groups)


def pick_representative(group: list[dict]) -> tuple[dict, list[dict]]:
    """그룹에서 유지할 1건과 삭제할 나머지를 가른다.

    created_at 최댓값을 남긴다 — 파이프라인이 계속 개선돼 왔으므로 최신 답변이
    현재 품질을 가장 잘 대변한다. created_at이 동률이면 id 사전순 최댓값을
    택해 재실행 시 같은 결과를 보장한다(멱등).
    """
    ordered = sorted(group, key=lambda r: (r.get("created_at") or "", r.get("id") or ""))
    return ordered[-1], ordered[:-1]


def plan_dedupe(rows: list[dict]) -> tuple[list[dict], list[dict], list[list[dict]]]:
    """정리 계획 수립. 반환: (유지 목록, 삭제 목록, 카테고리 불일치 그룹 목록)"""
    keep: list[dict] = []
    drop: list[dict] = []
    category_conflicts: list[list[dict]] = []

    for _key, group in group_by_question(rows).items():
        rep, rest = pick_representative(group)
        keep.append(rep)
        drop.extend(rest)
        if len(group) > 1 and len({r.get("category") for r in group}) > 1:
            category_conflicts.append(group)

    return keep, drop, category_conflicts


# ── Supabase 입출력 ──────────────────────────────────────────────────────────

def _fetch_all(sb) -> list[dict]:
    """qa_conversations 전량 페이징 조회."""
    rows: list[dict] = []
    offset = 0
    while True:
        res = (
            sb.table("qa_conversations")
            .select("id, session_id, category, question_text, answer_text, "
                    "calculation_types, metadata, created_at")
            .order("created_at", desc=False)
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        page = res.data or []
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def _write_backup(path: str, drop: list[dict], keep_count: int,
                  sessions: list[dict]) -> None:
    """삭제 대상 전량을 JSON으로 덤프. 실패는 예외로 전파한다 — 백업 없는 삭제 금지."""
    payload = {
        "reason": "board-duplicate-cleanup FR-02",
        "norm_rule": "NFC+lower+strip_non_word",
        "kept_count": keep_count,
        "deleted_count": len(drop),
        "conversations": drop,
        "sessions": sessions,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)

    # 쓰기 성공을 실제로 확인한다 (디스크 가득참 등으로 조용히 잘리는 경우 방어)
    with open(path, encoding="utf-8") as f:
        written = json.load(f)
    if len(written.get("conversations", [])) != len(drop):
        raise RuntimeError(
            f"백업 검증 실패: 기록 {len(written.get('conversations', []))}건 "
            f"≠ 대상 {len(drop)}건"
        )


class RLSBlocked(RuntimeError):
    """RLS가 DELETE를 무성 차단했을 때."""


def _delete_batches(sb, ids: list[str]) -> int:
    """50건씩 나눠 삭제. 실패 시 진행분을 보고하고 예외를 올린다.

    ⚠️ **반영 행 수를 반드시 확인한다.** qa_conversations의 anon 정책은
    INSERT/SELECT뿐이라 DELETE 정책이 없으면 PostgREST가 **에러 없이 0행**을
    반환한다(supabase_schema.sql:51-52). 예외만 보고 성공으로 처리하면
    "225/225 삭제"를 출력하고도 아무것도 지워지지 않는다 — 실측된 실패다.
    """
    done = 0
    for i in range(0, len(ids), DELETE_BATCH_SIZE):
        batch = ids[i:i + DELETE_BATCH_SIZE]
        try:
            res = sb.table("qa_conversations").delete().in_("id", batch).execute()
        except Exception as e:
            print(f"  ✗ 배치 실패 ({done}/{len(ids)} 삭제 완료 상태): {e}")
            raise
        affected = len(res.data or [])
        if affected == 0:
            raise RLSBlocked(
                f"DELETE가 0행 반영됨 (배치 {len(batch)}건 요청). "
                "RLS DELETE 정책 부재로 조용히 차단된 상태입니다."
            )
        done += affected
        print(f"  … {done}/{len(ids)} 삭제 (배치 반영 {affected})")
    return done


def _emit_sql(path: str, ids: list[str]) -> None:
    """Supabase SQL Editor에 붙여 실행할 DELETE 문 생성.

    RLS는 SQL Editor 세션(postgres 역할)에 적용되지 않으므로, 영구적인 권한
    확대 없이 일회성 정리를 끝낼 수 있다.
    """
    lines = [
        "-- 질문게시판 중복 정리 (board-duplicate-cleanup FR-03)",
        f"-- 대상 {len(ids)}건 — 그룹당 최신 1건을 남기고 삭제",
        "-- 실행 전 SELECT로 건수를 먼저 확인할 것.",
        "",
        "BEGIN;",
        "",
    ]
    for i in range(0, len(ids), DELETE_BATCH_SIZE):
        chunk = ", ".join(f"'{x}'" for x in ids[i:i + DELETE_BATCH_SIZE])
        lines.append(f"DELETE FROM qa_conversations WHERE id IN ({chunk});")
    lines += [
        "",
        "-- 확인: 아래가 238이어야 한다 (metadata 제외 키 4종을 뺀 공개 건수)",
        "-- SELECT count(*) FROM qa_conversations",
        "--  WHERE metadata->>'guard_flag' IS NULL AND metadata->>'truncated' IS NULL",
        "--    AND metadata->>'textbook' IS NULL AND metadata->>'synthetic' IS NULL;",
        "",
        "COMMIT;",
        "",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _purge_orphan_sessions(sb, session_ids: set[str], backup: list[dict]) -> int:
    """이번 삭제로 대화가 0건이 된 세션만 제거.

    ⚠️ CASCADE 방어: 삭제 직전에 세션별 잔여 대화 수를 재조회해 0인 것만 지운다.
       확인 없이 지우면 유지하기로 한 대화가 함께 증발한다.
    """
    purged = 0
    for sid in sorted(session_ids):
        try:
            remain = (
                sb.table("qa_conversations")
                .select("id", count="exact")
                .eq("session_id", sid)
                .limit(1)
                .execute()
            )
            if (remain.count or 0) > 0:
                continue    # 대화가 남아 있다 — 절대 지우면 안 된다

            row = sb.table("qa_sessions").select("*").eq("id", sid).execute()
            if row.data:
                backup.extend(row.data)
            sb.table("qa_sessions").delete().eq("id", sid).execute()
            purged += 1
        except Exception as e:
            print(f"  ⚠️ 세션 {sid} 정리 실패 (건너뜀): {e}")
    return purged


# ── 리포트 ───────────────────────────────────────────────────────────────────

def _print_summary(public: list[dict], keep: list[dict], drop: list[dict],
                   conflicts: list[list[dict]]) -> None:
    from collections import Counter

    print(f"\n공개 대상   {len(public)}건")
    print(f"유지        {len(keep)}건")
    print(f"삭제 대상   {len(drop)}건")

    cats = Counter(r.get("category") or "일반상담" for r in keep)
    print("\n유지분 카테고리 분포:")
    for cat, n in cats.most_common():
        print(f"    {cat:<14} {n:3d}")

    dup_groups = [g for g in group_by_question(public).values() if len(g) > 1]
    if dup_groups:
        print(f"\n중복 그룹 {len(dup_groups)}개 — 상위 10개:")
        for g in sorted(dup_groups, key=len, reverse=True)[:10]:
            q = (g[0].get("question_text") or "")[:50].replace("\n", " ")
            print(f"    {len(g):2d}회 | {q}")

    if conflicts:
        print(f"\n⚠️ 그룹 내 카테고리가 갈리는 경우 {len(conflicts)}건"
              " — 최신 항목의 카테고리가 채택된다:")
        for g in conflicts:
            rep, _ = pick_representative(g)
            others = sorted({r.get("category") for r in g} - {rep.get("category")})
            q = (g[0].get("question_text") or "")[:40].replace("\n", " ")
            print(f"    채택 '{rep.get('category')}' ← 후보 {others} | {q}")


def _verify(sb, expected_keep: int) -> bool:
    """삭제 후 재조회 검증 — 공개 건수 일치 + 중복 그룹 0."""
    rows = [r for r in _fetch_all(sb) if not is_public_excluded(r.get("metadata"))]
    dup = [g for g in group_by_question(rows).values() if len(g) > 1]
    ok = len(rows) == expected_keep and not dup
    print(f"\n검증: 공개 {len(rows)}건 (기대 {expected_keep}) / 중복 그룹 {len(dup)}개")
    return ok


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="질문게시판 중복 정리")
    ap.add_argument("--apply", action="store_true",
                    help="실제 삭제 (미지정 시 dry-run — 쓰기 0건)")
    ap.add_argument("--purge-sessions", action="store_true",
                    help="삭제로 대화가 0건이 된 세션도 정리 (CASCADE 주의)")
    ap.add_argument("--backup-dir", default=".", help="백업 JSON 저장 경로")
    args = ap.parse_args()

    # ~/.zshrc의 낡은 키가 .env를 덮는 함정 회피
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
                override=True)

    url = os.environ.get("SUPABASE_URL")
    # service_role 키는 RLS를 우회한다. qa_conversations에는 anon DELETE 정책이
    # 없으므로(supabase_schema.sql:51-52) 일반 키로는 삭제가 0행 처리된다.
    svc_key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
               or os.environ.get("SUPABASE_SERVICE_KEY"))
    key = svc_key or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("✗ SUPABASE_URL / SUPABASE_KEY 가 필요합니다 (.env 확인)")
        return 1

    from supabase import create_client
    sb = create_client(url, key)
    if args.apply and not svc_key:
        print("\n⚠️ service_role 키가 없습니다 — RLS로 DELETE가 차단될 수 있습니다.")
        print("   차단 시 SQL 파일을 생성해 Supabase SQL Editor에서 실행하세요.")

    print("=" * 62)
    print("질문게시판 중복 정리" + ("  [APPLY]" if args.apply else "  [DRY-RUN]"))
    print("=" * 62)

    all_rows = _fetch_all(sb)
    public = [r for r in all_rows if not is_public_excluded(r.get("metadata"))]
    print(f"\n전체 {len(all_rows)}건 → 공개 제외 {len(all_rows) - len(public)}건")

    keep, drop, conflicts = plan_dedupe(public)
    _print_summary(public, keep, drop, conflicts)

    if not drop:
        print("\n✅ 중복이 없습니다.")
        return 0

    if not args.apply:
        print("\n[DRY-RUN] 아무것도 삭제하지 않았습니다."
              " 실제 삭제는 --apply 를 붙이세요.")
        return 0

    # ── 백업 ──
    from datetime import datetime, timezone
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(args.backup_dir, f"backup_board_dedupe_{stamp}.json")
    session_backup: list[dict] = []

    print(f"\n백업 기록 중 → {backup_path}")
    try:
        _write_backup(backup_path, drop, len(keep), session_backup)
    except Exception as e:
        print(f"✗ 백업 실패 — 삭제를 진행하지 않습니다: {e}")
        return 1
    print(f"  ✓ {len(drop)}건 기록 완료")

    # ── 삭제 ──
    print(f"\n삭제 중 ({DELETE_BATCH_SIZE}건 배치)…")
    affected_sessions = {r.get("session_id") for r in drop if r.get("session_id")}
    drop_ids = [r["id"] for r in drop]
    try:
        _delete_batches(sb, drop_ids)
    except RLSBlocked as e:
        sql_path = os.path.join(args.backup_dir, f"dedupe_board_{stamp}.sql")
        _emit_sql(sql_path, drop_ids)
        print(f"\n✗ {e}")
        print("\n원인: qa_conversations의 anon RLS 정책이 INSERT/SELECT뿐이라")
        print("      DELETE가 에러 없이 0행 처리된다 (supabase_schema.sql:51-52).")
        print("\n해결 경로 둘 — 어느 쪽이든 데이터는 아직 그대로다:")
        print(f"  ① Supabase SQL Editor에서 실행: {sql_path}")
        print("  ② .env에 SUPABASE_SERVICE_ROLE_KEY 추가 후 재실행")
        print(f"\n백업(삭제 전 스냅샷): {backup_path}")
        return 1
    except Exception:
        print("✗ 삭제가 중단되었습니다. 백업 파일은 보존됩니다.")
        return 1

    # ── 고아 세션 (옵트인) ──
    if args.purge_sessions:
        print("\n고아 세션 정리 중 (잔여 대화 0건인 세션만)…")
        purged = _purge_orphan_sessions(sb, affected_sessions, session_backup)
        print(f"  ✓ 세션 {purged}건 정리")
        try:
            _write_backup(backup_path, drop, len(keep), session_backup)
        except Exception as e:
            print(f"  ⚠️ 세션 백업 갱신 실패 (대화 백업은 유효): {e}")

    ok = _verify(sb, len(keep))
    print("\n" + ("✅ 정리 완료" if ok else "⚠️ 검증 불일치 — 백업으로 확인 필요"))
    print(f"백업: {backup_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
