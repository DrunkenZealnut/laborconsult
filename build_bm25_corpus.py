"""Pinecone 메타데이터에서 BM25 코퍼스 생성

사용법:
    python build_bm25_corpus.py

출력:
    data/bm25_corpus.jsonl.gz — BM25 검색용 코퍼스 (커밋 대상, raw json은 gitignore)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


# 한 페이지(100건) 조회의 실측 지연은 15~16초이고 첫 페이지는 70초까지 걸린다.
# SDK 클라이언트 기본 타임아웃은 30초라 **정상 동작 구간이 타임아웃 경계에 걸쳐**
# 있었다 — 2026-09-04 실행에서 laborlaw-v2·counsel이 "read operation timed out"으로
# 죽고 qa만 남아 저장이 건너뛰어졌다(가드는 정상 작동). 상한을 지연 실측의 몇 배로
# 둔다. 이 값은 '느려도 기다린다'는 뜻이지 무한 대기가 아니다 — 진짜 무응답은
# 재시도 소진 후 예외로 올라온다.
PAGE_TIMEOUT = 180.0
# **총 시도 횟수**(최초 호출 + 재시도)이지 재시도 횟수가 아니다 — 이전 이름
# PAGE_RETRIES는 루프가 실제로 하는 일(4회 호출 = 재시도 3회)과 어긋나 읽는
# 사람마다 다르게 셌다.
PAGE_ATTEMPTS = 4
PAGE_LIMIT = 100  # 상향해도 처리량이 늘지 않는다(실측 limit 100/500/1000 = 6.5/4.0/4.7건/s)


def _fetch_page(index, ns: str, pagination_token):
    """페이지 1개 조회 — 일시적 오류는 같은 커서로 재시도한다.

    **재시도가 없으면 왕복 800회짜리 수집이 단 한 번의 타임아웃으로 전량
    폐기된다**(네임스페이스 단위 except가 루프 바깥에 있다). 커서는 성공한
    뒤에만 전진하므로 같은 토큰 재요청은 중복·누락을 만들지 않는다.
    """
    import time

    # 마지막 시도는 루프 밖에 둔다 — 루프 안에서 `attempt == 마지막`으로 분기하면
    # PAGE_ATTEMPTS가 0 이하일 때 루프가 통째로 건너뛰어져 **None이 반환된다**.
    # 호출부의 `resp.vectors`가 AttributeError를 내고, 그것이 네임스페이스 단위
    # except에 삼켜져 설정 실수가 '조회 실패'로 둔갑한다.
    # max(…, 0)로 감싸지 않는다 — range()는 음수를 빈 시퀀스로 처리하므로 클램프는
    # 아무 것도 막지 않으면서 '여기가 방어 지점'이라고 잘못 읽힌다. 실제 방어는
    # 루프 뒤의 무조건 return이다.
    retries = PAGE_ATTEMPTS - 1
    for attempt in range(retries):
        try:
            return _fetch_once(index, ns, pagination_token)
        except Exception as e:
            wait = 2 ** attempt
            print(f"      재시도 {attempt + 1}/{retries} ({wait}s 후): {e}", flush=True)
            time.sleep(wait)
    return _fetch_once(index, ns, pagination_token)


def _fetch_once(index, ns: str, pagination_token):
    return index.fetch_by_metadata(
        filter={"chunk_index": {"$gte": 0}},
        namespace=ns,
        limit=PAGE_LIMIT,
        pagination_token=pagination_token,
        timeout=PAGE_TIMEOUT,
    )


def build_corpus() -> None:
    api_key = os.getenv("PINECONE_API_KEY")
    if not api_key:
        print("ERROR: PINECONE_API_KEY not set")
        sys.exit(1)

    from pinecone import Pinecone

    from app.config import resolve_index_name
    index_name = resolve_index_name()
    pc = Pinecone(api_key=api_key)
    index = pc.Index(index_name)

    namespaces = ["laborlaw-v2", "counsel", "qa"]
    corpus: list[dict] = []
    failed_namespaces: list[str] = []

    for ns in namespaces:
        print(f"  Fetching namespace: {ns}...", flush=True)
        try:
            count = 0
            pages = 0
            pagination_token = None
            while True:
                # index.list()+fetch(by id)는 이 계정에서 list()가 반환한 ID가
                # fetch()에서 일관되게 0건으로 돌아오는 문제가 있어(list()의
                # ID 인덱스가 실제 벡터 데이터와 어긋난 것으로 보임 —
                # query()/fetch_by_metadata는 정상 동작함을 확인) 메타데이터
                # 필터 기반 페이지네이션으로 우회한다. chunk_index는 모든
                # 청크에 항상 존재하는 정수 필드라 전체 매치용으로 사용.
                resp = _fetch_page(index, ns, pagination_token)
                pages += 1
                for vid, vec in resp.vectors.items():
                    meta = vec.metadata or {}
                    # laborlaw-v2(Contextual Retrieval)는 "text" 없이 "chunk_text"만 존재
                    text = meta.get("text") or meta.get("chunk_text", "")
                    if not text:
                        continue
                    entry = {
                        "id": vid,
                        "text": text,
                        "title": meta.get("title", ""),
                        "section": meta.get("section", ""),
                        "source_type": meta.get("source_type", ""),
                    }
                    # 해설서 인용 가드(G4)가 BM25 경로에서 우회되지 않도록
                    # book_id를 보존한다. rag.py는 벡터 ID 폴백도 갖고 있지만,
                    # 코퍼스가 정본을 담는 편이 확실하다.
                    #
                    # 값이 있을 때만 넣는다 — 6번째 키를 무조건 넣으면 CPython
                    # dict가 8슬롯→16슬롯으로 리사이즈돼 문서당 +88B가 붙는다.
                    # 코퍼스의 97%가 해설서가 아니므로 빈 문자열을 위해 상주
                    # 메모리 5.7MB를 내는 셈이다(bm25_search.py의 RSS 경고 참조).
                    # 소비자(bm25_search.py, rag.py)는 부재를 이미 흡수한다.
                    if meta.get("book_id"):
                        entry["book_id"] = meta["book_id"]
                    corpus.append(entry)
                    count += 1
                pagination_token = resp.pagination.next if resp.pagination else None
                # 왕복 800회 × 15초라 전체가 수 시간이다. 진행 표시가 없으면
                # '느린 것'과 '멈춘 것'을 밖에서 구분할 수 없다.
                #
                # **문서 수가 아니라 페이지 수로 센다.** 문서 카운터는 위의
                # `if not text: continue` 하나만 걸려도, 또는 API가 100건 미만
                # 페이지를 한 번만 돌려줘도 2,000의 배수를 영영 비껴가 진행
                # 표시가 그 뒤로 통째로 침묵한다 — 이 표시가 막으려던 상태와
                # 정확히 같은 모습이 된다. 페이지 카운터는 무조건 증가한다.
                if pages % 20 == 0:
                    print(f"      {ns}: {count:,}건 ({pages}페이지)...", flush=True)
                if not pagination_token:
                    break
            print(f"    {ns}: {count} documents", flush=True)
            # 0건은 **예외 없이** 나온다 — 메타데이터 필터가 스키마 변경과
            # 어긋나거나 SDK 페이지네이션 동작이 바뀌면 조용히 빈 결과가 온다
            # (외부감사 2026-08-23 M7). 그대로 저장하면 부분 코퍼스가 정상
            # 파일을 덮어쓰고, gz라 커밋 diff로도 내용을 볼 수 없어 크기 변화
            # 외에는 알아챌 단서가 없다. 검색 대상 NS는 비어 있을 수 없다.
            if count == 0:
                print(f"    {ns}: 0건 — 조회는 성공했으나 문서가 없습니다")
                failed_namespaces.append(f"{ns} (0건)")
        except Exception as e:
            print(f"    {ns}: ERROR — {e}")
            failed_namespaces.append(ns)

    # 일부 네임스페이스라도 실패하면 부분 코퍼스로 기존 정상 파일을 덮어쓰지 않는다
    # — 이전엔 실패 후에도 무조건 저장해 불완전한 코퍼스가 커밋될 위험이 있었다.
    if failed_namespaces:
        print(f"\nERROR: 다음 네임스페이스 조회 실패 — 저장 건너뜀 (기존 파일 보존): "
              f"{failed_namespaces}")
        sys.exit(1)

    # gzip 출력 — Vercel 배포용 커밋 대상 (raw json은 .gitignore) (DB-1)
    # 임시 파일에 먼저 쓰고 성공 시에만 교체 — 쓰기 도중 중단돼도 기존 파일이 손상되지 않음
    import gzip
    # **JSONL**(한 줄 = 문서 1건)로 쓴다 — 배열이면 로더가 `json.load()`로 전체를
    # 파싱해야 하고, 그때 코퍼스 dict 전체와 토큰 리스트가 **동시에** 살아 있어
    # RSS 피크가 692MB까지 올라간다(Vercel 한도 1024MB). 줄 단위면 한 문서씩
    # 처리하고 놓아줄 수 있어 415MB로 내려간다(bm25-memory-scaling 실측).
    # gzip 압축률은 배열과 같다(19.8MB).
    out_path = Path("data/bm25_corpus.jsonl.gz")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    legacy_path = Path("data/bm25_corpus.json.gz")   # 구 포맷(급감 검사 폴백용)

    # 급감 가드 — NS별 0건 검사(위)를 통과해도 페이지네이션이 조기 종료하면
    # 각 NS가 '일부'만 담긴 채 정상으로 보인다. 코퍼스는 단조 증가가 정상이고
    # (삭제는 prune 정도), 20% 넘는 감소는 수집 결함을 의심할 신호다.
    # gz 산출물이라 커밋 diff로 내용을 검토할 수 없어 이 자동 검사가 유일한 방어다.
    # 전환 첫 실행에는 신 포맷이 없다 — 구 포맷을 기준으로 비교해야 급감 검사가
    # 한 번 비는 일이 없다(그 한 번이 하필 결함 있는 빌드일 수 있다).
    prev_path = out_path if out_path.exists() else legacy_path
    if prev_path.exists():
        try:
            with gzip.open(prev_path, "rt", encoding="utf-8") as f:
                # 앞 64바이트에서 첫 실질 문자를 본다 — `read(1)`은 파일이
                # 공백·BOM으로 시작하면 빈 문자열이 되어 JSONL로 오판하고,
                # 한 줄짜리 배열을 1건으로 세어 **급감 가드를 조용히 무효화**한다
                # (0.8 × 1보다 작은 값은 없다). 이 가드가 유일한 방어다.
                head = f.read(64).lstrip("\ufeff \t\r\n")[:1]
                f.seek(0)
                prev_count = (len(json.load(f)) if head == "["
                              else sum(1 for ln in f if ln.strip()))
        except Exception as e:                      # 기존 파일 손상은 차단 사유가 아니다
            print(f"\n[경고] 기존 코퍼스를 읽지 못해 급감 검사를 건너뜁니다: {e}")
            prev_count = 0
        if prev_count and len(corpus) < prev_count * 0.8:
            print(f"\nERROR: 문서 수가 {prev_count:,} → {len(corpus):,}로 "
                  f"{(1 - len(corpus) / prev_count) * 100:.0f}% 감소했습니다 "
                  f"— 저장 건너뜀 (기존 파일 보존).\n"
                  f"       의도한 축소라면 기존 {out_path}를 옮긴 뒤 재실행하세요.")
            sys.exit(1)

    with gzip.open(tmp_path, "wt", encoding="utf-8") as f:
        for doc in corpus:
            f.write(json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n")
    tmp_path.replace(out_path)

    size_mb = out_path.stat().st_size / 1e6
    print(f"\nBM25 corpus saved: {len(corpus)} documents → {out_path} ({size_mb:.1f}MB gz)")
    if size_mb > 10:
        print("⚠️ 10MB 초과 — 리포 커밋 대신 외부 저장(design 부록 A) 검토 필요")


if __name__ == "__main__":
    build_corpus()
