#!/usr/bin/env python3
"""법제처 조문 캐시 예열 — 등록 IP 머신이 프로덕션 L2(`law_article_cache`)를 채운다.

production-law-api-recovery D1·D2·D12. 프로덕션(Vercel)은 IP가 법제처에 등록돼 있지 않아 실호출이
전부 인증 실패한다(그래서 `LAW_API_LIVE=off`로 실호출을 끈다). 답변은 이 스크립트가 쓴 행만 읽는다.
launchd가 매일 KST 00:10·06:10과 로그인 시(RunAtLoad)에 돌린다 — 자정 실행이 실패해도 아침에 회복한다.

동작:
1. 대상 = `law_catalog.warm_law_names()` — 현행성 점검(check_law_freshness)과 같은 목록이다.
2. 법령마다 판본 목록에서 기준판(시행일 ≤ 오늘의 최댓값)을 구하고 **그 판본을 명시해** 받는다
   (`fetch_law_root(..., ef_yd=기준판)`). 머리글 시행일자가 기준판과 다르면 그 법령은 쓰지 않는다.
   법제처는 자정 직후 '현행' 포인터를 늦게 바꿀 수 있는데(legal_api 00~03시 1시간 규칙), 판본을
   고정하면 그 지연과 무관해진다. 그래서 예열 행만 자정을 넘겨 유효하다.
3. 행 = 조문 전체 + 항 단위. 키는 `legal_api.article_cache_key`, 텍스트는 프로덕션 조회와 같은
   `_extract_article`이다(바이트 동일). 만료 = min(다음 시행일 00:00 KST, 지금 + 3일).
   상한 3일은 판본 목록에 아직 없는 '공포 즉시 시행' 개정 대비이고, 맥이 꺼졌을 때의 최악 지연이다.
   판본 목록을 못 받으면 판본을 지정하지 않고 받되, 다음 KST 자정에 만료한다(경고).
4. 500행씩 upsert하고 **반영 행 수**(`len(res.data)`)로 성공을 판정한다 — Supabase 쓰기는 실패가 조용하다.
5. 상태 행 `meta:law_warm_status`(만료 2099-12-31)를 쓴다. 폴백 감시(check_llm_fallback ①)가 읽는다.

    python3 warm_law_cache.py --dry-run          # 조회·행 생성만(쓰기 없음)
    python3 warm_law_cache.py                    # 예열
    python3 warm_law_cache.py --law 근로기준법   # 일부 법령만(상태 행은 쓰지 않는다 — 행 수 감소 오탐 방지)

종료 코드: 0 정상 · 1 일부 실패(법령·쓰기·설정) · 2 인증 오류(등록 IP가 아님 — 행을 하나도 쓰지 않는다)

⚠️ **프로덕션 Supabase에 쓴다**(로컬 .env의 SUPABASE_URL). 등록 IP 맥에서만 돈다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

from app.core.law_catalog import warm_law_names
from app.core.legal_api import (
    LawApiAuthError, _extract_article, _law_key, _parse_hang_no, article_cache_key,
    canonical_law_name, fetch_law_root,
)
from app.core.storage import LAW_WARM_STATUS_KEY

KST = timezone(timedelta(hours=9))
EXPIRY_CAP = timedelta(days=3)
FETCH_TIMEOUT = 60            # 소득세법 본문이 크다 — 프로덕션 조회 타임아웃(8초)으로는 끊긴다
RETRIES = 2                   # 법령마다 최대 2회 재시도(총 3회). 인증 오류는 재시도하지 않는다
UPSERT_CHUNK = 500
STATUS_EXPIRES = "2099-12-31T00:00:00Z"
SOURCE_TYPE = "law_warm"


class WarmError(RuntimeError):
    """한 법령을 쓰지 않는 사유(판본 불일치·미매칭·조문 0개)."""


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _kst_label(iso: str) -> str:
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc).astimezone(KST).strftime("%m-%d %H:%M")


def midnight_kst(yyyymmdd: str) -> datetime:
    return datetime.strptime(yyyymmdd, "%Y%m%d").replace(tzinfo=KST)


def next_midnight_kst(now: datetime) -> datetime:
    k = now.astimezone(KST)
    return (k + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def expiry_for(versions: list[dict], today: str, now: datetime) -> tuple[datetime, str | None]:
    """(만료 시각, 다음 시행일). 만료 = min(다음 시행일 00:00 KST, now + 3일)(D2)."""
    nxt = min((v["date"] for v in versions if v.get("date") and v["date"] > today), default=None)
    cap = now + EXPIRY_CAP
    return (min(midnight_kst(nxt), cap) if nxt else cap), nxt


def header_date(root: ET.Element) -> str:
    return (root.findtext(".//기본정보/시행일자") or "").strip()


def _branch(jo: ET.Element) -> int | None:
    """조문가지번호 — 없거나 "0"·"00"이면 None(`_extract_article`·현행성 점검과 같은 판정, 검증 L8)."""
    text = (jo.findtext("조문가지번호") or "").strip()
    return (int(text) or None) if text.isdigit() else None


def build_rows(root: ET.Element, law_name: str, expires_at: str, fetched_at: str) -> list[dict]:
    """조문 전체 + 항 단위 행. 키·텍스트를 프로덕션 조회와 **같은 함수**로 만든다(R7).

    편·장·절 제목(조문여부=전문)은 뒤따르는 조문과 같은 조문번호를 갖는다 — 행으로 만들지 않는다.
    텍스트가 None인 키는 쓰지 않는다(프로덕션도 그 키에서 None을 낸다).
    """
    name = canonical_law_name(law_name)
    rows: dict[str, dict] = {}

    def add(key: str, no: int, text: str | None) -> None:
        if text and key not in rows:
            rows[key] = {"cache_key": key, "law_name": name, "article_no": no, "content": text,
                         "source_type": SOURCE_TYPE, "fetched_at": fetched_at, "expires_at": expires_at}

    for jo in root.iter("조문단위"):
        if (jo.findtext("조문여부") or "").strip() != "조문":
            continue
        m = re.search(r"(\d+)", jo.findtext("조문번호") or "")
        if not m:
            continue
        no, sub = int(m.group(1)), _branch(jo)
        add(article_cache_key(name, no, sub), no, _extract_article(root, no, None, sub))
        for hang in jo.iter("항"):
            p = _parse_hang_no(hang.findtext("항번호") or "")
            if p:
                add(article_cache_key(name, no, sub, p), no, _extract_article(root, no, p, sub))
    return list(rows.values())


def warm_one(name: str, key: str, today: str, now: datetime) -> dict:
    """한 법령 → {rows, ref, next, expires, warning}. 인증 오류(LawApiAuthError)는 그대로 올린다."""
    from check_law_freshness import law_versions, reference_version

    warning = None
    try:
        versions: list[dict] | None = law_versions(name, key)
    except LawApiAuthError:
        raise
    except Exception as e:   # 판본 목록만 실패 — 판본 없이 받되 다음 자정에 만료한다
        versions, warning = None, f"판본 목록 조회 실패({type(e).__name__})"
    ref = reference_version(versions, today) if versions else None
    if ref:
        root = fetch_law_root(name, key, ef_yd=ref, timeout=FETCH_TIMEOUT)
        if root is None:
            raise WarmError(f"기준판 {ref} 본문 미매칭")
        if header_date(root) != ref:
            raise WarmError(f"판본 불일치(머리글 {header_date(root) or '없음'} ≠ 기준판 {ref})")
        expires, nxt = expiry_for(versions, today, now)
    else:
        if warning is None:
            warning = "판본 목록에 법령명 일치 없음" if not versions else "기준일 이전 판본 없음"
        warning += " — 판본 미지정·다음 자정 만료"
        root = fetch_law_root(name, key, timeout=FETCH_TIMEOUT)
        if root is None:
            raise WarmError("본문 미매칭")
        expires, nxt = next_midnight_kst(now), None
    rows = build_rows(root, name, _iso(expires), _iso(now))
    if not rows:
        raise WarmError("조문 0개")
    return {"rows": rows, "ref": ref, "next": nxt, "expires": _iso(expires), "warning": warning}


def upsert_rows(db, rows: list[dict]) -> tuple[int, int]:
    """(반영 행 수, 실패 행 수). 예외가 아니라 반영 행 수로 판정한다(CLAUDE.md — 쓰기는 조용히 실패한다)."""
    written = failed = 0
    for i in range(0, len(rows), UPSERT_CHUNK):
        chunk = rows[i:i + UPSERT_CHUNK]
        try:
            res = db.table("law_article_cache").upsert(chunk, on_conflict="cache_key").execute()
            n = len(res.data or [])
        except Exception as e:  # noqa: BLE001 — 실패 행으로 세고 다음 묶음을 시도한다
            print(f"  ✗ 쓰기 실패({i}~{i + len(chunk) - 1}): {type(e).__name__}: {str(e)[:160]}")
            n = 0
        written += n
        failed += len(chunk) - n
    return written, failed


def read_status(db) -> dict | None:
    """직전 상태 행(만료 필터 없이 원시 조회). 없거나 해석 불가면 None."""
    res = db.table("law_article_cache").select("content").eq("cache_key", LAW_WARM_STATUS_KEY).execute()
    data = res.data or []
    if not data:
        return None
    try:
        return json.loads(data[0]["content"])
    except (TypeError, ValueError, KeyError):
        return None


def write_status(db, status: dict, now: datetime) -> bool:
    res = db.table("law_article_cache").upsert({
        "cache_key": LAW_WARM_STATUS_KEY, "law_name": "meta", "article_no": None,
        "content": json.dumps(status, ensure_ascii=False), "source_type": "meta",
        "fetched_at": _iso(now), "expires_at": STATUS_EXPIRES,
    }, on_conflict="cache_key").execute()
    return len(res.data or []) == 1


def _select(names: list[str], wanted: list[str] | None) -> tuple[list[str], list[str]]:
    if not wanted:
        return names, []
    keys = {_law_key(canonical_law_name(w)): w for w in wanted}
    picked = [n for n in names if _law_key(n) in keys]
    unknown = [w for k, w in keys.items() if k not in {_law_key(n) for n in picked}]
    return picked, unknown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="조회·행 생성만 하고 쓰지 않는다")
    parser.add_argument("--law", action="append", help="이 법령만(반복 가능). 상태 행은 쓰지 않는다")
    args = parser.parse_args(argv)

    from dotenv import load_dotenv  # import 시점이 아니라 실행 시에만(테스트 환경변수 보호)
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=True)
    key = os.getenv("LAW_API_KEY")
    if not key:
        print("LAW_API_KEY 미설정 — 법제처 조회 불가")
        return 1

    names, unknown = _select(warm_law_names(), args.law)
    if unknown:
        print(f"예열 대상이 아닌 법령: {', '.join(unknown)} (law_catalog.warm_law_names() 참조)")
        return 1
    now = datetime.now(timezone.utc)
    today = now.astimezone(KST).strftime("%Y%m%d")
    print(f"예열 {now.astimezone(KST):%Y-%m-%d %H:%M} KST · 기준일 {today} · 대상 {len(names)}종"
          f"{' (dry-run)' if args.dry_run else ''}")

    rows: list[dict] = []
    ok: dict[str, dict] = {}
    failed: dict[str, str] = {}
    warnings: list[str] = []
    t0 = time.time()
    for name in names:
        result, error = None, ""
        for attempt in range(RETRIES + 1):
            try:
                result = warm_one(name, key, today, now)
                break
            except LawApiAuthError as e:
                print(f"❌ 인증 오류 — 등록 IP가 아닌 곳에서 돌았거나 키 문제다: {e}")
                print("   행을 하나도 쓰지 않고 중단한다(exit 2).")
                return 2
            except Exception as e:  # noqa: BLE001 — 법령 단위 재시도 후 다음 법령으로
                error = f"{type(e).__name__}: {str(e)[:160]}"
                if attempt < RETRIES:
                    time.sleep(2 * (attempt + 1))
        if result is None:
            failed[name] = error
            print(f"  ✗ {name}: {error}")
            continue
        ok[name] = result
        rows += result["rows"]
        if result["warning"]:
            warnings.append(f"{name}: {result['warning']}")
        print(f"  ✓ {name}  기준판 {result['ref'] or '—'} · 다음 {result['next'] or '—'} · "
              f"행 {len(result['rows'])} · 만료 {_kst_label(result['expires'])}"
              + (f"  ⚠️ {result['warning']}" if result["warning"] else ""))

    chars = sum(len(r["content"]) for r in rows)
    print(f"조회 {len(ok)}/{len(names)}종 · 행 {len(rows):,} · 약 {chars:,}자 · {time.time() - t0:.0f}초")
    if args.dry_run:
        print("(dry-run) 쓰기 없음")
        return 1 if failed else 0

    from app.core.storage import make_supabase_client
    db = make_supabase_client(postgrest_timeout=60)
    if db is None:
        print("SUPABASE_URL / SUPABASE_KEY 미설정 — 쓰기 불가")
        return 1
    written, write_failed = upsert_rows(db, rows)
    print(f"쓰기 {written:,}/{len(rows):,}행" + (f" · 실패 {write_failed:,}행" if write_failed else ""))
    if write_failed:
        failed["(쓰기)"] = f"{write_failed}행 반영 실패"

    if args.law:
        print("(--law) 상태 행은 쓰지 않는다")
    else:
        try:
            prev = read_status(db)
        except Exception as e:  # noqa: BLE001 — 직전 행 수만 모르게 될 뿐이다
            prev = None
            warnings.append(f"직전 상태 조회 실패({type(e).__name__})")
        status = {
            "at": _iso(now), "rows": written, "prev_rows": (prev or {}).get("rows"),
            "laws_ok": list(ok), "laws_failed": failed, "warnings": warnings,
            "versions": {n: r["ref"] for n, r in ok.items()},
            "next": {n: r["next"] for n, r in ok.items() if r["next"]},
        }
        try:
            if not write_status(db, status, now):
                print("  ✗ 상태 행 반영 0건")
                return 1
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ 상태 행 쓰기 실패: {type(e).__name__}: {str(e)[:160]}")
            return 1
        print(f"상태 행 기록: {LAW_WARM_STATUS_KEY} (직전 {status['prev_rows'] or '—'}행 → {written:,}행)")
    for w in warnings:
        print(f"  ⚠️ {w}")
    if failed:
        print(f"❌ 실패 {len(failed)}건: {', '.join(failed)}")
        return 1
    print("✅ 예열 완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
