#!/usr/bin/env python3
"""보유기간이 지난 첨부파일을 Supabase Storage에서 삭제한다.

왜 별도 스크립트인가
--------------------
Supabase는 `storage.objects`에 대한 직접 DELETE를 트리거로 차단한다.

    ERROR 42501: Direct deletion from storage tables is not allowed.
                 Use the Storage API instead. (PL/pgSQL function protect_delete())

그래서 `supabase_retention_purge.sql`의 `purge_expired_data()`는 파일을 지우지 않고
경로를 `storage_purge_queue`에 적재만 한다. 이 스크립트가 그 큐를 읽어 Storage API로
실제 삭제를 수행한다. **둘 다 돌아야** 개인정보처리방침 제5항(1년 경과 시 파기)이 이행된다.

사용법
------
    python3 purge_storage_orphans.py            # 큐를 비운다
    python3 purge_storage_orphans.py --dry-run  # 지울 목록만 출력
    python3 purge_storage_orphans.py --limit 50 # 한 번에 처리할 건수(기본 200)

필요 환경변수: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY (.env 또는 셸 환경)

왜 anon 키(SUPABASE_KEY)가 아니라 service_role 키인가
------------------------------------------------------
supabase_schema.sql이 storage.objects에 부여하는 정책은 INSERT("Allow anon
upload")와 SELECT("Allow anon read")뿐이고 DELETE 정책이 없다. RLS는 명시적으로
허용하지 않은 동작을 기본 차단하므로, anon 키로 storage.remove()를 호출하면
권한 오류로 실패한다. service_role 키는 RLS를 완전히 우회하므로 정책을 추가로
열어 줄 필요가 없다. 이 키는 관리자 권한과 동등하므로 절대 브라우저로 보내지
말고, 이 스크립트처럼 서버·로컬 배치 실행 전용으로만 사용할 것.

권장 주기: pg_cron이 매일 04:00 KST에 큐를 채우므로, 그 이후 하루 1회.
"""

from __future__ import annotations

import argparse
import os
import sys

BUCKET = "chat-attachments"
DEFAULT_LIMIT = 200


def _load_client():
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass  # .env 없이 셸 환경변수만 쓰는 경우

    url = os.getenv("SUPABASE_URL")
    # anon 키(SUPABASE_KEY)는 storage.objects DELETE 정책이 없어 삭제가 실패한다.
    # service_role 키가 RLS를 우회해야 실제로 파일이 지워진다 — 모듈 docstring 참조.
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        sys.exit(
            "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 가 설정되지 않았습니다.\n"
            "  service_role 키는 Supabase 대시보드 → Project Settings → API → service_role에서 확인하세요.\n"
            "  (anon 키는 storage.objects에 DELETE 정책이 없어 이 스크립트가 동작하지 않습니다.)"
        )

    try:
        from supabase import create_client
    except ImportError:
        sys.exit("supabase 패키지가 없습니다:  pip install -r requirements.txt")

    return create_client(url, key)


def main() -> int:
    ap = argparse.ArgumentParser(description="만료 첨부파일을 Storage에서 삭제")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"처리 건수 (기본 {DEFAULT_LIMIT})")
    ap.add_argument("--dry-run", action="store_true", help="삭제하지 않고 목록만 출력")
    args = ap.parse_args()

    sb = _load_client()

    try:
        rows = (sb.rpc("storage_purge_claim", {"p_limit": args.limit}).execute().data) or []
    except Exception as e:
        print(f"큐 조회 실패: {e}", file=sys.stderr)
        print("  → supabase_retention_purge.sql §0 을 먼저 적용했는지 확인하세요.", file=sys.stderr)
        return 1

    if not rows:
        print("삭제 대기 중인 첨부파일이 없습니다.")
        return 0

    print(f"삭제 대기: {len(rows)}건")
    if args.dry_run:
        for r in rows:
            print(f"  [dry-run] {r['bucket_id']}/{r['object_path']}")
        return 0

    ok = failed = 0
    for r in rows:
        path = r["object_path"]
        try:
            # 파일이 이미 없어도 Storage API 는 오류를 내지 않는다 → 멱등
            sb.storage.from_(r["bucket_id"]).remove([path])
            sb.rpc("storage_purge_mark", {"p_id": r["id"], "p_ok": True}).execute()
            ok += 1
        except Exception as e:
            failed += 1
            print(f"  ✗ {path}: {e}", file=sys.stderr)
            try:
                sb.rpc(
                    "storage_purge_mark",
                    {"p_id": r["id"], "p_ok": False, "p_error": str(e)[:300]},
                ).execute()
            except Exception as mark_err:
                # 마킹 자체가 실패해도 다음 실행에서 재시도되므로 치명적이진 않지만,
                # 로그가 없으면 큐가 계속 안 줄어드는 원인을 나중에 진단할 수 없다.
                print(f"  ⚠ 마킹 실패 (id={r['id']}): {mark_err}", file=sys.stderr)

    print(f"완료 — 삭제 {ok}건, 실패 {failed}건")
    if failed:
        print("실패 항목은 5회까지 재시도됩니다. 원인은 supabase_retention_purge.sql §5 로 확인하세요.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
