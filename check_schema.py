#!/usr/bin/env python3
"""Supabase 스키마 대조 — 코드가 기대하는 스키마·테이블·컬럼·RPC가 실제 DB에 있는지.

설계: docs/02-design/features/supabase-schema-migration.design.md §6

    python3 check_schema.py              # 대조 결과 요약
    python3 check_schema.py --verbose    # 실패 항목의 PostgREST 오류 원문

⚠️ **이 점검은 CI에서 돌지 않는다.** GitHub Actions에는 Supabase 자격증명이 없어
   DB에 접근할 수 없다. 배포 전·스키마 변경 후 **수동 실행** 항목이다.

   CI가 도는 것은 `test_offline_units.py` 의 D5~D9 이고, 그건 **DDL 파일 ↔ 코드
   상수**만 대조한다. 파일이 맞아도 그 DDL 을 DB 에 적용하지 않았으면 못 잡는다.
   2026-08-13 이전 프로젝트 전환에서 `qa_sessions.session_data`·`law_article_cache`
   가 빠진 채 프로덕션이 돌았던 것이 정확히 그 유형이다.

⚠️ **스키마 이름을 반드시 함께 확인한다.** 컬럼만 대조하면 잘못된 스키마에 우연히
   같은 이름의 테이블이 있을 때 "정상"을 보고한다 — 2026-08-13 board_posts 사고가
   그 형태였다(다른 앱 테이블의 id·category·created_at 3개가 맞아떨어졌다).
"""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

# 로컬 ~/.zshrc 의 낡은 키가 .env 를 덮는 것을 막는다.
load_dotenv(override=True)

from app.core.storage import (  # noqa: E402
    BOARD_POST_COLUMNS,
    SUPABASE_SCHEMA_DEFAULT,
    make_supabase_client,
)

# anon 이 SELECT 할 수 있어야 정상인 테이블
OPEN_TABLES: dict[str, tuple[str, ...]] = {
    "qa_sessions": ("id", "session_data", "created_at", "updated_at"),
    "qa_conversations": ("id", "session_id", "category", "question_text",
                         "answer_text", "calculation_types", "metadata", "created_at"),
    "qa_attachments": ("id", "conversation_id", "filename", "content_type",
                       "storage_path", "public_url", "file_size", "created_at"),
    "law_article_cache": ("cache_key", "law_name", "article_no", "content",
                          "source_type", "fetched_at", "expires_at"),
    "board_posts": BOARD_POST_COLUMNS,
}

# RLS ON + 정책 무부여 + GRANT 회수 → anon 직접 접근이 **막혀야** 정상인 테이블.
# 읽히면 이중 방어가 뚫린 것이다.
LOCKED_TABLES = ("chat_quota", "block_list", "abuse_events", "storage_purge_queue")

# 부작용 없이 호출할 수 있는 RPC 만 존재 확인한다.
# chat_guard_check·record_abuse_event 는 쓰기 부작용이 있어 여기서 부르지 않는다
# (같은 DDL 파일에서 생성되므로 아래 둘이 있으면 4개 모두 있다. 실동작은 종단 검증).
SAFE_RPCS: dict[str, dict] = {
    "abuse_unblock": {"p_subject_key": "probe:does-not-exist"},
    "abuse_summary": {"p_days": 1, "p_limit": 1},
}


def _classify(err: Exception) -> str:
    """PostgREST 오류를 원인별로 분류. 조치가 달라지므로 뭉뚱그리면 안 된다."""
    m = str(err)
    if "42703" in m:
        return "컬럼없음"
    if "42P01" in m or "PGRST205" in m:
        return "테이블없음"
    if "PGRST106" in m:
        return "스키마미노출"
    if "permission denied" in m or "42501" in m:
        return "권한없음"
    if "PGRST202" in m:
        return "함수없음"
    return "기타"


def check_open(sb, verbose: bool) -> list[str]:
    print("\n[공개 테이블] anon SELECT 가능해야 정상")
    problems = []
    for table, columns in OPEN_TABLES.items():
        bad: dict[str, list[str]] = {}
        for col in columns:
            try:
                sb.table(table).select(col).limit(1).execute()
            except Exception as e:
                bad.setdefault(_classify(e), []).append(col)
                if verbose:
                    print(f"     {table}.{col}: {str(e)[:150]}")
        if not bad:
            print(f"  ✓ {table:<18} {len(columns)}컬럼")
            continue
        problems.append(table)
        for kind, cols in bad.items():
            if kind == "권한없음":
                # RLS 정책과 GRANT 는 다른 계층이다. 정책만 만들고 GRANT 를 빠뜨리면
                # 테이블·컬럼이 멀쩡해도 전부 막힌다 (커스텀 스키마에는 Supabase
                # 기본 권한이 자동 부여되지 않는다).
                print(f"  ✗ {table:<18} 권한없음 — GRANT 누락 "
                      f"(supabase_schema.sql §5-1 확인)")
            elif kind == "테이블없음":
                print(f"  ✗ {table:<18} 테이블 자체가 없음 — DDL 미적용")
            else:
                print(f"  ✗ {table:<18} {kind}: {', '.join(cols)}")
    return problems


def check_locked(sb, verbose: bool) -> list[str]:
    print("\n[잠긴 테이블] anon 직접 접근이 '막혀야' 정상")
    problems = []
    for table in LOCKED_TABLES:
        try:
            sb.table(table).select("*").limit(1).execute()
            problems.append(table)
            print(f"  ✗ {table:<20} 읽힘 — RLS/GRANT 회수 실패")
        except Exception as e:
            kind = _classify(e)
            if kind == "권한없음":
                print(f"  ✓ {table:<20} 차단됨")
            else:
                problems.append(table)
                print(f"  ✗ {table:<20} {kind} — 테이블이 없거나 다른 문제")
                if verbose:
                    print(f"     {str(e)[:150]}")
    return problems


def check_rpcs(sb, verbose: bool) -> list[str]:
    print("\n[RPC] 부작용 없는 호출로 존재 확인")
    problems = []
    for fn, params in SAFE_RPCS.items():
        try:
            sb.rpc(fn, params).execute()
            print(f"  ✓ {fn}")
        except Exception as e:
            problems.append(fn)
            print(f"  ✗ {fn} — {_classify(e)}")
            if verbose:
                print(f"     {str(e)[:150]}")
    print("    (chat_guard_check·record_abuse_event 는 쓰기 부작용이 있어 미호출 —")
    print("     같은 DDL 로 생성되며 실동작은 종단 검증 E4 가 확인한다)")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description="Supabase 스키마 대조 (수동 실행 전용)")
    ap.add_argument("--verbose", action="store_true", help="실패 항목의 오류 원문 출력")
    args = ap.parse_args()

    url = os.environ.get("SUPABASE_URL", "")
    schema = os.environ.get("SUPABASE_SCHEMA") or SUPABASE_SCHEMA_DEFAULT

    print("=== Supabase 스키마 대조 ===")
    print(f"  프로젝트 : {url.split('//')[-1].split('.')[0] if url else '(미설정)'}")
    print(f"  스키마   : {schema}")

    if schema != SUPABASE_SCHEMA_DEFAULT:
        print(f"  ⚠️ 기대 스키마({SUPABASE_SCHEMA_DEFAULT})와 다릅니다 — "
              "다른 앱의 동명 테이블을 보고 있을 수 있습니다")

    sb = make_supabase_client()
    if sb is None:
        print("\n✗ SUPABASE_URL / SUPABASE_KEY 가 설정되지 않았습니다 (.env 확인)")
        print("  ※ NEXT_PUBLIC_* 는 Next.js 관례라 이 프로젝트(FastAPI)가 읽지 않습니다.")
        return 1

    problems = (check_open(sb, args.verbose)
                + check_locked(sb, args.verbose)
                + check_rpcs(sb, args.verbose))

    print("\n" + "─" * 62)
    if not problems:
        print("✅ 스키마 일치")
        print("\n※ 이 점검은 컬럼 존재·권한·RPC 만 본다. RLS 정책 내용과 컬럼 단위")
        print("   권한은 anon 키로 확인할 수 없으므로 각 DDL 파일 말미의 검증 SQL을")
        print("   함께 볼 것.")
        return 0

    print(f"❌ 스키마 불일치 — {len(problems)}건: {', '.join(problems)}")
    print("\n조치: Supabase SQL Editor 에서 아래를 순서대로 실행 (멱등, 재실행 안전)")
    print("  1) supabase_schema.sql   2) supabase_abuse_guard.sql")
    print("  3) supabase_board_posts.sql   4) supabase_retention_purge.sql")
    return 1


if __name__ == "__main__":
    sys.exit(main())
