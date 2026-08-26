"""BM25 키워드 검색 + Dense 벡터 검색 RRF 결합 모듈

Pinecone Dense 검색에 BM25 키워드 매칭을 결합하여
정확한 법조문 번호/용어 검색 시 recall을 향상시킨다.

- Mecab 형태소 분석기 설치 시 정확한 토큰화 사용
- 미설치 시 정규식 기반 경량 토크나이저 폴백
- Vercel serverless: 글로벌 변수로 cold start 시 1회만 로드
"""

from __future__ import annotations

import gc
import json
import logging
import re
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# ── BM25 인덱스 (글로벌 캐시) ────────────────────────────────────────────

_bm25_index = None       # rank_bm25.BM25Okapi | None
_bm25_corpus = None      # list[dict] — _KEEP_FIELDS만 보관(book_id 포함)
_bm25_loaded = False
_loaded_src: str | None = None   # 어느 코퍼스 파일을 읽었는지(/api/health 관측용)

_BM25_DATA_DIR = Path(__file__).parent.parent.parent / "data"
# gz(배포용 커밋 대상) 우선, raw json(로컬 빌드 산출물) 폴백 (DB-1)
# JSONL(신) 우선, JSON 배열(구) 폴백. **양쪽을 계속 지원한다** — 코드와 데이터의
# 배포 시점이 어긋날 수 있어서다(코드가 먼저 나가면 구 gz를, 데이터가 먼저 나가면
# 신 gz를 읽어야 한다). 구 포맷 지원 제거는 전환이 끝난 뒤 별도 커밋으로 한다.
BM25_CORPUS_PATHS = [_BM25_DATA_DIR / "bm25_corpus.jsonl.gz",
                     _BM25_DATA_DIR / "bm25_corpus.jsonl",
                     _BM25_DATA_DIR / "bm25_corpus.json.gz",
                     _BM25_DATA_DIR / "bm25_corpus.json"]

# 코퍼스에서 보관할 필드 — 원본 줄 dict를 그대로 담으면 스트리밍의 의미가 없다
# (같은 객체를 계속 들고 있게 된다). 검색 결과 반환에 쓰이는 것만 옮긴다.
# **build_bm25_corpus.py가 이 상수를 import한다** — 두 곳에서 손으로 선언하면
# 빌더가 필드를 추가해도 `_slim()`이 말없이 버려, Dense 히트에는 있고 BM25
# 히트에만 빈 값인 상태가 된다(경로 리뷰 M4). 회귀는 test_offline_units.py.
CORPUS_FIELDS = ("id", "text", "title", "section", "source_type", "book_id")
_KEEP_FIELDS = CORPUS_FIELDS
# 그중 반복이 큰 것만 인터닝한다(text는 문서마다 달라 공유될 일이 없다).
_INTERN_FIELDS = ("title", "section", "source_type", "book_id")
# 실측(60,174건 전체 로드 시 BM25Okapi 인덱스까지 프로세스 RSS 약 815MB, 2026-07-14).
# "여유"라 부를 수준은 아님 — Vercel 함수 메모리가 1GB라면 남는 건 ~185MB뿐이고,
# 여기 도달하기 전에 이 프로세스 다른 부분(FastAPI·다른 SDK 클라이언트·GraphRAG 등)도
# 메모리를 쓴다. 코퍼스가 커지면 이 상수와 실제 배포 메모리 한도를 함께 재검토할 것.
# 소프트 MemoryError는 app/core/rag.py::search_hybrid()의 broad except가 잡아
# Dense-only로 폴백하지만, OS 레벨 하드 OOM-kill은 코드로 방어 불가능하다.
#
# 후속 실측(2026-08-18, Vercel preview, 해설서 3권 체제 + 청크 신호 게이트 적용):
# 66,307건 로드 9.0초, OOM 없음. vercel.json은 legacy `builds` 블록이라 memory
# 키가 없어 기본 1024MB다. 로드 시간은 7.8초(2026-08-16, 게이트 이전 66,354건)에서
# 늘었고 콜드 스타트 첫 요청 지연에 그대로 얹힌다 — 건수가 줄었는데도 늘었다는 건
# 이 시간이 문서 수가 아니라 인스턴스 상태에 좌우된다는 뜻이므로, 회귀 판단의
# 기준선으로 쓰지 말 것.
#
# 후속 실측(2026-08-25, 로컬 macOS, 76,983건 — 훈령 1,763 적재 후):
#   인터닝 **이전**에는 gz 파싱 427MB → 인덱스 구축 **1,218MB**로 Vercel 기본
#   한도 1024MB의 **119%**였다. 문자열 인터닝을 넣어 **683MB(67%)** 로 내렸다
#   (load_bm25_corpus의 인터닝 주석 참조). 단계별 실측:
#
#     단계              인터닝 전 → 후
#     코퍼스 로드          437MB → 445MB
#     토큰화 피크          934MB → 536MB
#     BM25Okapi 구축     1,218MB → 683MB
#
#   로드 시간은 2.6초로 동일하고 검색 결과도 불변이다(같은 토큰 문자열을 공유할
#   뿐 값이 바뀌지 않는다).
#
#   ⚠️ 이 여유는 **코퍼스 증가로 다시 잠식된다** — 대략 문서 1만 건당 +90MB다.
#   소프트 MemoryError는 search_hybrid의 broad except가 Dense-only로 흡수하지만
#   그 경우 **하이브리드 검색이 조용히 반쪽이 되고**, OS 하드 OOM-kill은 방어 불가다.
#
# 최종 실측(2026-08-26, JSONL 스트리밍 전환 후): 로컬 macOS **약 410MB(40%)**, 로드 2.6초.
#
# ⚠️ **CI(Linux) 실측은 다르다** — 370MB(36%), 로드 **7.0초**, 그리고 구 배열 경로도
#   384MB뿐이다(로컬은 704MB). 즉 **플랫폼별 절대값·절감폭이 크게 다르다**:
#     macOS: 704 → 409MB (42% 절감)
#     Linux: 384 → 370MB (3.6% 절감)   ← 프로덕션이 Linux다
#   할당자·페이지 회수 정책 차이로 보인다. 판단 근거로는 **Linux 값을 쓸 것** —
#   "한도의 119%"라는 최초 진단도 macOS 측정이었고, Linux 기준으로는 그만큼
#   임박한 위험이 아니었을 수 있다. 다만 스트리밍이 더 낮다는 방향은 두 플랫폼에서
#   일치하고, 증가율을 낮추는 구조적 이점은 그대로다.
#   로드 시간 7.0초는 콜드 스타트 첫 요청에 그대로 얹힌다(개선 대상이 아니었다).
#   스트리밍이 배열 파싱의 이중 상주(코퍼스 dict + 토큰 리스트)를 없앤 결과다.
#   구 배열 폴백 경로는 여전히 약 700MB(69%)이므로 신 포맷 커밋이 전제다.
#   회귀는 test_bm25_memory.py(별도 프로세스, 상한 550MB, 초과 시 **실패**).
#   남은 완화 후보: text 미보관+fetch 보충 · 샤딩 · Vercel 메모리 상향
#   (대안별 실측은 docs/02-design/features/bm25-memory-scaling.design.md §1).
#
# BM25_MAX_DOCS의 의미가 **스트리밍 전환으로 바뀌었다**(2026-08-26).
#   · JSONL 경로: 루프 안에서 절단하므로 이 값이 **실제로 메모리를 제한한다.**
#   · 구 배열 경로(폴백): 여전히 json.load 이후 절단이라 피크를 줄이지 못한다.
# 즉 지금은 신 포맷에서만 유효한 상한이다.
BM25_MAX_DOCS = 100_000


# ── 한국어 토크나이저 ────────────────────────────────────────────────────

_mecab = None
_mecab_checked = False


def _get_mecab():
    """Mecab 인스턴스 lazy loading (1회만 시도)."""
    global _mecab, _mecab_checked
    if _mecab_checked:
        return _mecab
    _mecab_checked = True
    try:
        from konlpy.tag import Mecab
        _mecab = Mecab()
        logger.info("Mecab 형태소 분석기 로드 완료")
    except (ImportError, Exception) as e:
        logger.info("Mecab 미사용 (정규식 폴백): %s", e)
        _mecab = None
    return _mecab


def _tokenize_ko(text: str) -> list[str]:
    """한국어 토크나이저 — Mecab 우선, 미설치 시 정규식 폴백.

    Mecab 사용 시: 명사(NNG,NNP) + 동사어간(VV) + 형용사어간(VA) 추출
    폴백 시: 조사 제거 + 공백 분리
    """
    mecab = _get_mecab()

    if mecab is not None:
        try:
            pos_tags = mecab.pos(text)
            tokens = [
                word for word, tag in pos_tags
                if tag.startswith(("NNG", "NNP", "VV", "VA")) and len(word) >= 2
            ]
            if tokens:
                return tokens
        except Exception:
            pass  # Mecab 실패 → 폴백

    # 정규식 기반 경량 토크나이저 (2글자 조사 우선 매칭)
    text = re.sub(r"(?:에서|부터|까지|에게)(?=\s|$)", "", text)
    text = re.sub(r"[은는이가을를의로도만와과](?=\s|$)", "", text)
    tokens = re.sub(r"[^\w\s]", " ", text).split()
    return [t for t in tokens if len(t) >= 2]


# ── BM25 코퍼스 로드 ─────────────────────────────────────────────────────

def _slim(doc: dict) -> dict:
    """원본 줄 dict → 보관용 dict.

    **원본을 그대로 담지 않는 것이 핵심**이다 — 그대로 append하면 파싱된 객체를
    계속 참조하게 되어 스트리밍의 이득이 사라진다. 검색 결과 반환에 쓰이는
    필드만 새 dict로 옮기고, 반복이 큰 것은 인터닝한다.
    """
    out = {}
    for key in _KEEP_FIELDS:
        val = doc.get(key)
        if val is None:
            continue
        if key in _INTERN_FIELDS and isinstance(val, str):
            val = sys.intern(val)
        out[key] = val
    return out


def _load_streaming(corpus_path) -> tuple[list[dict], list[list[str]]]:
    """코퍼스를 읽어 (보관용 문서 목록, 토큰 리스트)를 만든다.

    **JSONL이면 한 줄씩 처리해 원본 dict를 즉시 놓아준다.** 배열(구 포맷)은
    `json.load()`가 전체를 파싱할 수밖에 없어 피크가 높다 — 폴백 경로다.

    실측(76,983문서, 인터닝 포함):
      배열 일괄  692MB / 2.7초
      JSONL 스트리밍  415MB / 2.8초   ← Vercel 1024MB의 41%

    토큰 인터닝은 **여기서도 반드시 유지**한다. 토큰의 94.1%가 중복이라
    (549만 → 고유 32.6만) 인터닝이 없으면 스트리밍을 해도 한도를 넘는다.
    회귀 `test_offline_units.py::test_bm25_interning`이 고정한다.
    """
    import gzip

    opener = (gzip.open if str(corpus_path).endswith(".gz") else open)
    corpus: list[dict] = []
    tokenized: list[list[str]] = []
    is_jsonl = corpus_path.name.endswith((".jsonl", ".jsonl.gz"))

    with opener(corpus_path, "rt", encoding="utf-8") as f:
        if is_jsonl:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                if len(corpus) >= BM25_MAX_DOCS:
                    # 코퍼스는 네임스페이스 순차 수집이라 파일 **뒷부분이 qa**다
                    # (build_bm25_corpus.py의 NS 순서). 상한에 걸리면 무작위가
                    # 아니라 최대 코퍼스인 Q&A의 꼬리가 통째로 잘린다 — Dense가
                    # 받쳐주므로 증상이 "특정 주제만 BM25 미도달"로만 나타난다.
                    logger.warning("BM25_MAX_DOCS(%d) 도달 — 코퍼스 뒷부분이 "
                                   "잘렸습니다(주로 qa 네임스페이스)", BM25_MAX_DOCS)
                    break            # 스트리밍이라 이 상한이 실제 메모리를 제한한다
                try:
                    doc = json.loads(line)
                except json.JSONDecodeError as e:
                    # **전량 중단이 옳다** — 줄 단위 skip은 "부분 데이터가 정상으로
                    # 보이는" 실패를 만든다(빌더에 급감 가드가 있는 이유와 같다).
                    # 다만 어디서 깨졌는지는 남겨야 진단이 가능하다.
                    raise ValueError(
                        f"{corpus_path.name} {lineno}번째 줄 파싱 실패 "
                        f"(그때까지 {len(corpus)}건 읽음): {e}") from e
                tokenized.append([sys.intern(w)
                                  for w in _tokenize_ko(doc.get("text", ""))])
                corpus.append(_slim(doc))
        else:
            # 구 포맷 — 전체 파싱이 불가피하다. 파싱본을 빨리 놓아주려고
            # 순회하며 옮긴 뒤 원본을 해제한다(피크는 낮아지지 않는다).
            #
            # ⚠️ 빌더는 더 이상 이 포맷을 쓰지 않는다 — 여기 진입했다는 것은
            # 신 포맷이 배포본에 없다는 뜻이고, 그 파일은 **갱신이 멈춘 코퍼스**일
            # 수 있다(law-version-drift와 같은 실패 클래스: 낡은 데이터를 조용히
            # 계속 쓴다). 메모리도 약 300MB 높다.
            logger.warning("BM25: 구 배열 포맷(%s) 사용 — 갱신이 멈춘 코퍼스일 수 "
                           "있고 메모리 피크가 약 300MB 높습니다. "
                           "bm25_corpus.jsonl.gz 커밋을 확인하세요.", corpus_path.name)
            raw = json.load(f)
            for doc in raw[:BM25_MAX_DOCS]:
                tokenized.append([sys.intern(w)
                                  for w in _tokenize_ko(doc.get("text", ""))])
                corpus.append(_slim(doc))
            del raw
            gc.collect()
    return corpus, tokenized


def load_bm25_corpus() -> bool:
    """BM25 코퍼스 로드 (서버 시작 시 1회).

    포맷: `data/bm25_corpus.jsonl.gz` (한 줄 = 문서 1건, 신)
          `data/bm25_corpus.json.gz`  (JSON 배열, 구 — 폴백. 피크가 약 300MB 높다)
    문서: {"id", "text", "title", "section", "source_type", "book_id"?}

    Returns:
        True if loaded successfully, False otherwise
    """
    global _bm25_index, _bm25_corpus, _bm25_loaded, _loaded_src

    if _bm25_loaded:
        return _bm25_index is not None

    _bm25_loaded = True

    corpus_path = next((p for p in BM25_CORPUS_PATHS if p.exists()), None)
    if corpus_path is None:
        # **warning 이상이어야 한다.** 코퍼스 미커밋은 프로덕션이 조용히
        # Dense-only로 떨어지는 가장 흔한 원인이고, 이 로그가 유일한 신호다.
        logger.warning("BM25 corpus not found: %s — 하이브리드 검색이 "
                       "Dense-only로 동작합니다(gz 커밋 누락 확인)",
                       BM25_CORPUS_PATHS[0])
        return False

    try:
        from rank_bm25 import BM25Okapi

        start = time.monotonic()
        _bm25_corpus, tokenized = _load_streaming(corpus_path)

        _bm25_index = BM25Okapi(tokenized)
        # BM25Okapi는 doc_freqs·idf·doc_len만 보관하고 원본 토큰 리스트를 참조하지
        # 않는다 — 명시 해제로 피크 이후 상주 메모리를 낮춘다.
        del tokenized
        gc.collect()

        elapsed = (time.monotonic() - start) * 1000
        # **어느 파일을 읽었는지 남긴다.** 신·구 포맷의 로그가 같으면 "고쳤다고
        # 믿는데 프로덕션은 구 경로(700MB)"가 아무 신호 없이 성립한다(경로 리뷰 H2).
        _loaded_src = corpus_path.name
        logger.info("BM25 loaded: %d docs, %.0fms, src=%s",
                    len(_bm25_corpus), elapsed, corpus_path.name)
        return True

    except ImportError:
        logger.warning("rank_bm25 not installed — BM25 disabled")
        return False
    except Exception as e:
        # **코퍼스를 반드시 놓아준다.** _bm25_corpus는 인덱스 구축 **전**에 채워지므로,
        # BM25Okapi가 MemoryError로 죽으면 쓸모없는 코퍼스 400MB가 프로세스 수명 내내
        # 남는다 — 메모리가 모자라 실패한 상황에서 메모리를 붙들어 이후 요청
        # (FastAPI·Pinecone·GraphRAG)의 OOM 위험을 키운다(경로 리뷰 M7).
        _bm25_corpus = None
        _bm25_index = None
        gc.collect()
        logger.warning("BM25 load failed: %s", e)
        return False


# ── BM25 검색 ────────────────────────────────────────────────────────────

def search_bm25(query: str, top_k: int = 10) -> list[dict]:
    """BM25 키워드 검색.

    Args:
        query: 검색 쿼리 텍스트
        top_k: 최대 반환 건수

    Returns:
        [{id, title, section, content, source_type, score, search_type}, ...]
    """
    if _bm25_index is None or _bm25_corpus is None:
        return []

    tokens = _tokenize_ko(query)
    if not tokens:
        return []

    scores = _bm25_index.get_scores(tokens)

    # 상위 top_k 인덱스 추출 (numpy 없이 순수 Python)
    indexed_scores = [(i, s) for i, s in enumerate(scores) if s > 0]
    indexed_scores.sort(key=lambda x: x[1], reverse=True)
    top_indices = indexed_scores[:top_k]

    results = []
    for idx, score in top_indices:
        doc = _bm25_corpus[idx]
        results.append({
            "id": doc["id"],
            "title": doc.get("title", ""),
            "section": doc.get("section", ""),
            "content": doc.get("text", ""),
            "source_type": doc.get("source_type", ""),
            "book_id": doc.get("book_id", ""),   # 해설서 인용 가드(G4) 키
            "score": round(float(score), 4),
            "search_type": "bm25",
        })

    logger.info("BM25 검색: query=%r, %d건", query[:40], len(results))
    return results


# ── Reciprocal Rank Fusion (RRF) ─────────────────────────────────────────

RRF_K = 60  # 표준 RRF 상수


def rrf_merge_ranked_lists(result_lists: list[list[dict]], top_k: int = 10) -> list[dict]:
    """여러 쿼리의 BM25 결과를 순위 기반으로 병합 (DB-8).

    멀티쿼리 분해 이점이 단일 문자열 결합 검색에서 상실되던 문제 해소 —
    쿼리별 검색 결과를 RRF로 결합한다.
    """
    scores: dict[str, float] = {}
    hit_map: dict[str, dict] = {}
    for hits in result_lists:
        for rank, hit in enumerate(hits):
            doc_id = hit["id"]
            scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (RRF_K + rank + 1)
            if doc_id not in hit_map:
                hit_map[doc_id] = hit
    ordered = sorted(scores, key=lambda x: scores[x], reverse=True)
    return [hit_map[doc_id] for doc_id in ordered[:top_k]]


def reciprocal_rank_fusion(
    dense_hits: list[dict],
    bm25_hits: list[dict],
    alpha: float = 0.5,
    top_k: int = 15,
) -> list[dict]:
    """Dense + BM25 결과를 RRF로 결합.

    Args:
        dense_hits: Pinecone Dense 검색 결과
        bm25_hits: BM25 키워드 검색 결과
        alpha: Dense 가중치 (0.0=BM25 only, 1.0=Dense only, 0.5=균등)
        top_k: 반환할 최대 건수

    Returns:
        RRF 점수 기준 정렬된 결합 결과
    """
    rrf_scores: dict[str, float] = {}
    hit_map: dict[str, dict] = {}

    # Dense 점수
    for rank, hit in enumerate(dense_hits):
        doc_id = hit["id"]
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0) + alpha / (RRF_K + rank + 1)
        if doc_id not in hit_map:
            hit_map[doc_id] = hit

    # BM25 점수
    for rank, hit in enumerate(bm25_hits):
        doc_id = hit["id"]
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0) + (1 - alpha) / (RRF_K + rank + 1)
        if doc_id not in hit_map:
            hit_map[doc_id] = hit

    # RRF 점수 내림차순 정렬
    sorted_ids = sorted(rrf_scores, key=lambda x: rrf_scores[x], reverse=True)

    results = []
    for doc_id in sorted_ids[:top_k]:
        hit = hit_map[doc_id].copy()
        hit["rrf_score"] = round(rrf_scores[doc_id], 6)
        results.append(hit)

    logger.info(
        "RRF fusion: Dense %d + BM25 %d → %d (alpha=%.1f)",
        len(dense_hits), len(bm25_hits), len(results), alpha,
    )
    return results
