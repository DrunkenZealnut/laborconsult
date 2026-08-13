#!/usr/bin/env python3
"""질문게시판 중복 정리 — 같은 질문의 반복 게시글을 그룹당 최신 1건만 남기고 삭제.

설계: docs/archive/2026-08/board-duplicate-cleanup/board-duplicate-cleanup.design.md

    python3 dedupe_board.py                          # dry-run (기본) — 쓰기 0건
    python3 dedupe_board.py --apply                  # 백업 후 실제 삭제
    python3 dedupe_board.py --apply --purge-sessions # + 고아 세션 정리 (옵트인)
    python3 dedupe_board.py --backup-dir ./backups   # 백업 경로 지정

⚠️ 하드 삭제는 되돌릴 수 없다. --apply는 백업 JSON 생성에 성공해야만 삭제로 진입한다.

⚠️ qa_conversations.session_id는 ON DELETE CASCADE다. 세션 행을 지우면 그 세션의
   남은 대화까지 함께 사라진다 — 벤치마크 세션 하나가 대화 4건을 갖고 그중 1건이
   유지 대상인 상황이 실제로 있으므로, --purge-sessions는 삭제 직전 세션별 잔여
   대화 수를 재조회해 0인 것만 지운다.

복구 절차(스크립트 미구현 — 수동): 사이드카 파일
`backup_board_dedupe_*_sessions.json`의 세션을 **먼저** 삽입한 뒤
`backup_board_dedupe_*.json`의 `conversations`를 삽입한다.
qa_conversations.session_id가 qa_sessions를 FK로 참조하므로 순서를 뒤집으면
삽입이 실패한다. 사이드카가 없으면(= --purge-sessions 미사용) 세션이 그대로
살아 있으므로 대화만 넣으면 된다.

⚠️ **백업·생성 SQL은 상담 원문 평문 덤프다**(백업 JSON은 질문·답변 전문, .sql은
   대화 UUID). `.gitignore`가 커밋만 막을 뿐 로컬 디스크·백업 도구·운영자 사본은
   보호하지 않는다 — 이 파일들은 개인정보처리방침의 보유기간 대상 데이터와 같은
   내용이므로, **삭제 검증이 끝나면 파기하거나 저장소 밖 암호화 위치로 옮길 것.**
   보관한다면 `--backup-dir`로 저장소 바깥을 지정하는 편이 낫다. 되돌릴 필요가
   남아 있는 동안만 존재해야 하는 파일이다.

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
from collections import Counter, defaultdict
from datetime import datetime, timezone

# 공개 제외 계약의 단일 출처. app/core/storage.py는 FastAPI·pipeline·API 키에
# 의존하지 않아 운영 스크립트가 그대로 import할 수 있다.
from app.core.storage import PUBLIC_EXCLUDE_KEYS, is_public_excluded

DELETE_BATCH_SIZE = 50   # UUID 36자 × 50 ≈ 1.9KB — PostgREST 쿼리스트링 여유 확보
PAGE_SIZE = 1000         # Supabase range() 한계

_FULL_COLUMNS = ("id, session_id, category, question_text, answer_text, "
                 "calculation_types, metadata, created_at")


# ── 순수 함수 (오프라인 테스트 대상) ─────────────────────────────────────────

def _norm_question(t: str) -> str:
    """중복 판정용 질문 정규화.

    NFC 선행이 필수다 — 한글이 NFD(자모 분해)로 들어오면 완성형과 다른 키가 되어
    같은 질문이 갈라진다. pinecone_upload_legal.py가 이 누락으로 474벡터를
    덮어쓴 전례가 있다.
    """
    return re.sub(r"\W", "", unicodedata.normalize("NFC", t or "").lower())


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


def plan_dedupe(rows: list[dict]) -> list[tuple[dict, list[dict]]]:
    """정리 계획 — 그룹별 (유지 1건, 삭제 나머지) 쌍의 목록.

    유지 목록·삭제 목록·카테고리 불일치 그룹은 전부 이 반환값에서 파생된다.
    리포트가 대표 선정을 **다시 계산하면** 규칙을 바꾸는 순간 화면과 실제가
    갈라진다 — 삭제 직전 사람이 읽는 유일한 확인 화면이므로 단일 계산이어야 한다.
    """
    return [pick_representative(g) for g in group_by_question(rows).values()]


def keep_of(plan: list[tuple[dict, list[dict]]]) -> list[dict]:
    return [rep for rep, _ in plan]


def drop_of(plan: list[tuple[dict, list[dict]]]) -> list[dict]:
    return [row for _, rest in plan for row in rest]


# ── Supabase 입출력 ──────────────────────────────────────────────────────────

def _fetch_all(sb, columns: str = _FULL_COLUMNS) -> list[dict]:
    """qa_conversations 전량 페이징 조회.

    columns를 좁힐 수 있게 둔 이유: 검증 재조회는 metadata·question_text만 쓰는데
    답변 본문이 전체 전송량의 75%다(실측 245행 기준 1,272KB 중 1,012KB 낭비).
    백업 덤프는 원본 행이 필요하므로 기본값은 전체 컬럼이다.
    """
    rows: list[dict] = []
    offset = 0
    while True:
        res = (
            sb.table("qa_conversations")
            .select(columns)
            .order("created_at", desc=False)
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        page = res.data or []
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def _write_backup(path: str, drop: list[dict], keep_count: int) -> None:
    """삭제 대상 전량을 JSON으로 덤프. 실패는 예외로 전파한다 — 백업 없는 삭제 금지.

    이 파일은 **한 번만 쓰고 다시 열지 않는다.** 삭제 후 재기록하면 `open(w)`가
    기존 스냅샷을 먼저 잘라내므로, 그 시점에 실패하면 유일한 복구 수단이 파괴된다.
    세션 백업은 사이드카 파일로 분리한다(§_purge_orphan_sessions).
    """
    payload = {
        # 파일명에도 타임스탬프가 박히지만, 파일이 이름을 잃어도 실행 시점을
        # 추적할 수 있어야 한다.
        "created_at": datetime.now(timezone.utc).isoformat(),
        "reason": "board-duplicate-cleanup FR-02",
        "norm_rule": "NFC+lower+strip_non_word",
        "kept_count": keep_count,
        "deleted_count": len(drop),
        "conversations": drop,
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


def _emit_sql(path: str, ids: list[str], expected_keep: int) -> None:
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
    # 제외 조건도 단일 출처에서 생성한다 — 손으로 나열하면 키가 늘 때 생성 SQL이
    # 조용히 틀린 검증문을 담고, 그걸 잡는 테스트가 없다.
    cond = "\n--       AND ".join(f"metadata->>'{k}' IS NULL" for k in PUBLIC_EXCLUDE_KEYS)
    lines += [
        "",
        f"-- 확인: 아래가 {expected_keep}이어야 한다 (제외 키 {len(PUBLIC_EXCLUDE_KEYS)}종을 뺀 공개 건수)",
        "-- SELECT count(*) FROM qa_conversations",
        f"--  WHERE {cond};",
        "",
        "COMMIT;",
        "",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _purge_orphan_sessions(sb, session_ids: set[str], sidecar_path: str) -> int:
    """이번 삭제로 대화가 0건이 된 세션만 제거. 백업은 사이드카 파일에 선기록한다.

    ⚠️ CASCADE 방어: 삭제 직전에 세션별 잔여 대화 수를 재조회해 0인 것만 지운다.
       확인 없이 지우면 유지하기로 한 대화가 함께 증발한다. 세션 하나가 대화 4건을
       갖고 그중 1건만 유지 대상인 상황이 실제로 있다.

    ⚠️ 세션별 개별 조회(왕복 2~3회/세션)는 의도적이다. `in_()` 배치로 살아있는
       세션을 한 번에 추리는 편이 훨씬 빠르지만(178세션 기준 534→12왕복), 응답이
       페이지 한계에서 잘리면 살아있는 세션이 목록에서 빠져 **고아로 오판**되고
       유지 대상 대화가 CASCADE로 증발한다. 이 함수에서 틀리는 비용은 데이터
       파괴이고 이득은 수십 초라 교환이 성립하지 않는다.

    ⚠️ **쓰기가 멈춘 유지보수 창에서만 실행할 것.** 잔여 대화 조회와 세션 DELETE는
       별도 요청이라 그 사이에 해당 세션으로 새 대화가 저장되면 CASCADE가 그것까지
       지운다. 그 대화는 `drop` 목록에도 사이드카 백업에도 없으므로 **복구 불가**다.
       창을 닫으려면 `DELETE ... WHERE NOT EXISTS (...) RETURNING`을 단일
       SECURITY DEFINER RPC로 돌려야 하는데, 아래 이유로 어차피 RPC가 필요하다.

    ⚠️ **qa_sessions에도 anon DELETE 정책이 없다**(supabase_schema.sql:47-49 —
       INSERT/SELECT/UPDATE뿐). `_delete_batches()`와 똑같이 PostgREST가 에러 없이
       0행을 반환하므로 반영 행 수를 확인하지 않으면 "N건 정리 완료"를 출력하고도
       아무것도 지워지지 않는다. anon 키로는 이 경로가 항상 `RLSBlocked`로 끝나는
       것이 정상이며, 실제 정리는 SQL Editor나 service role이 필요하다.
    """
    purged: list[dict] = []
    orphans: list[str] = []

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
                purged.extend(row.data)
                orphans.append(sid)
        except Exception as e:
            print(f"  ⚠️ 세션 {sid} 조회 실패 (건너뜀): {e}")

    if not orphans:
        return 0

    # 백업 선기록 — 삭제 도중 중단돼도 복구 대상이 남는다. 실패는 전파해 삭제를 막는다.
    with open(sidecar_path, "w", encoding="utf-8") as f:
        json.dump({"created_at": datetime.now(timezone.utc).isoformat(),
                   "sessions": purged}, f, ensure_ascii=False, indent=2, default=str)

    done = 0
    for sid in orphans:
        try:
            res = sb.table("qa_sessions").delete().eq("id", sid).execute()
        except Exception as e:
            print(f"  ⚠️ 세션 {sid} 삭제 실패 (건너뜀): {e}")
            continue
        # 예외가 아니라 반영 행 수로 판정한다 — RLS 차단은 200 OK + 빈 배열이다.
        if not (res.data or []):
            raise RLSBlocked(
                f"세션 DELETE가 0행 반영됨 (id={sid}, 대상 {len(orphans)}건). "
                "qa_sessions에 anon DELETE 정책이 없어 조용히 차단된 상태입니다 — "
                f"세션 정리는 SQL Editor나 service role로 수행하세요. "
                f"백업은 {sidecar_path}에 있습니다."
            )
        done += len(res.data)
    return done


# ── 리포트 ───────────────────────────────────────────────────────────────────

def _print_summary(plan: list[tuple[dict, list[dict]]], public_count: int) -> None:
    """삭제 직전 확인 화면. 대표 선정을 재계산하지 않고 plan에서만 파생한다."""
    keep, drop = keep_of(plan), drop_of(plan)

    print(f"\n공개 대상   {public_count}건")
    print(f"유지        {len(keep)}건")
    print(f"삭제 대상   {len(drop)}건")

    cats = Counter(r.get("category") or "일반상담" for r in keep)
    print("\n유지분 카테고리 분포:")
    for cat, n in cats.most_common():
        print(f"    {cat:<14} {n:3d}")

    dups = [(rep, rest) for rep, rest in plan if rest]
    if dups:
        print(f"\n중복 그룹 {len(dups)}개 — 상위 10개:")
        for rep, rest in sorted(dups, key=lambda p: len(p[1]), reverse=True)[:10]:
            q = (rep.get("question_text") or "")[:50].replace("\n", " ")
            print(f"    {len(rest) + 1:2d}회 | {q}")

    conflicts = [(rep, rest) for rep, rest in plan
                 if {r.get("category") for r in rest} - {rep.get("category")}]
    if conflicts:
        print(f"\n⚠️ 그룹 내 카테고리가 갈리는 경우 {len(conflicts)}건"
              " — 최신 항목의 카테고리가 채택된다:")
        for rep, rest in conflicts:
            others = sorted({r.get("category") for r in rest} - {rep.get("category")})
            q = (rep.get("question_text") or "")[:40].replace("\n", " ")
            print(f"    채택 '{rep.get('category')}' ← 후보 {others} | {q}")


def _verify(sb, expected_keep: int) -> bool:
    """삭제 후 재조회 검증 — 고유 질문 수 일치 + 중복 그룹 0.

    공개 행 수가 아니라 **그룹 수**를 기대값과 비교한다. `group_by_question()`이
    질문이 기호뿐인 행(빈 키)을 폐기하므로 `plan_dedupe()`의 keep/drop 어디에도
    들어가지 않는데, 행 수로 비교하면 그런 행 N건이 그대로 불일치로 잡혀
    삭제가 정상인데도 경고가 뜬다.

    ⚠️ 기대값은 `--apply` 시작 시점의 스냅샷이라 삭제~재조회 사이에 저장된 신규
       대화를 모르고, 그만큼 그룹 수가 늘어 **불일치로 보고된다**(오탐 방향이라
       데이터는 안전하다). 프로덕션 트래픽 중 실행했다면 경고를 그대로 실패로
       읽지 말고 증가분이 신규 저장인지 확인할 것 — 쓰기가 멈춘 유지보수 창에서
       실행하면 이 모호함이 없다.
    """
    rows = [r for r in _fetch_all(sb, "question_text, metadata")
            if not is_public_excluded(r.get("metadata"))]
    groups = group_by_question(rows)
    dup = [g for g in groups.values() if len(g) > 1]
    skipped = len(rows) - sum(len(g) for g in groups.values())
    ok = len(groups) == expected_keep and not dup
    print(f"\n검증: 고유 질문 {len(groups)}개 (기대 {expected_keep}) / "
          f"중복 그룹 {len(dup)}개 / 공개 행 {len(rows)}건"
          + (f" (질문이 기호뿐인 행 {skipped}건 제외)" if skipped else ""))
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

    sb, has_service_key = _connect()
    if sb is None:
        return 1
    if args.apply and not has_service_key:
        print("\n⚠️ service_role 키가 없습니다 — RLS로 DELETE가 차단될 수 있습니다.")
        print("   차단 시 SQL 파일을 생성해 Supabase SQL Editor에서 실행하세요.")

    print("=" * 62)
    print("질문게시판 중복 정리" + ("  [APPLY]" if args.apply else "  [DRY-RUN]"))
    print("=" * 62)

    all_rows = _fetch_all(sb)
    public = [r for r in all_rows if not is_public_excluded(r.get("metadata"))]
    print(f"\n전체 {len(all_rows)}건 → 공개 제외 {len(all_rows) - len(public)}건")

    plan = plan_dedupe(public)
    _print_summary(plan, len(public))

    if not drop_of(plan):
        print("\n✅ 중복이 없습니다.")
        return 0

    if not args.apply:
        print("\n[DRY-RUN] 아무것도 삭제하지 않았습니다."
              " 실제 삭제는 --apply 를 붙이세요.")
        return 0

    return _apply(sb, args, plan)


def _connect() -> tuple[object | None, bool]:
    """Supabase 클라이언트 생성. 반환: (client|None, service_role 키 사용 여부)"""
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
        return None, False

    from supabase import create_client
    return create_client(url, key), bool(svc_key)


def _report_rls_blocked(err, sql_path: str, backup_path: str) -> None:
    print(f"\n✗ {err}")
    print("\n원인: qa_conversations의 anon RLS 정책이 INSERT/SELECT뿐이라")
    print("      DELETE가 에러 없이 0행 처리된다 (supabase_schema.sql:51-52).")
    print("\n해결 경로 둘 — 어느 쪽이든 데이터는 아직 그대로다:")
    print(f"  ① Supabase SQL Editor에서 실행: {sql_path}")
    print("  ② .env에 SUPABASE_SERVICE_ROLE_KEY 추가 후 재실행")
    print(f"\n백업(삭제 전 스냅샷): {backup_path}")


def _apply(sb, args, plan: list[tuple[dict, list[dict]]]) -> int:
    """백업 → 삭제 → (옵트인) 고아 세션 → 검증."""
    keep, drop = keep_of(plan), drop_of(plan)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(args.backup_dir, f"backup_board_dedupe_{stamp}.json")

    print(f"\n백업 기록 중 → {backup_path}")
    try:
        _write_backup(backup_path, drop, len(keep))
    except Exception as e:
        print(f"✗ 백업 실패 — 삭제를 진행하지 않습니다: {e}")
        return 1
    print(f"  ✓ {len(drop)}건 기록 완료")

    print(f"\n삭제 중 ({DELETE_BATCH_SIZE}건 배치)…")
    drop_ids = [r["id"] for r in drop]
    try:
        _delete_batches(sb, drop_ids)
    except RLSBlocked as e:
        sql_path = os.path.join(args.backup_dir, f"dedupe_board_{stamp}.sql")
        _emit_sql(sql_path, drop_ids, len(keep))
        _report_rls_blocked(e, sql_path, backup_path)
        return 1
    except Exception:
        print("✗ 삭제가 중단되었습니다. 백업 파일은 보존됩니다.")
        return 1

    if args.purge_sessions:
        print("\n고아 세션 정리 중 (잔여 대화 0건인 세션만)…")
        sidecar = backup_path[:-5] + "_sessions.json"
        affected = {r.get("session_id") for r in drop if r.get("session_id")}
        try:
            purged = _purge_orphan_sessions(sb, affected, sidecar)
            print(f"  ✓ 세션 {purged}건 정리 (백업: {sidecar})")
        except Exception as e:
            print(f"  ⚠️ 세션 백업 기록 실패 — 세션은 지우지 않았다: {e}")

    ok = _verify(sb, len(keep))
    print("\n" + ("✅ 정리 완료" if ok else "⚠️ 검증 불일치 — 백업으로 확인 필요"))
    print(f"백업: {backup_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
