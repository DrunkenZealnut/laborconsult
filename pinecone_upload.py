#!/usr/bin/env python3
"""
노동OK BEST Q&A → Pinecone 벡터 업로드  ⛔ **실행 봉인됨 (2026-08-23)**

**이 스크립트를 되살리려면 아래 두 결함을 먼저 고쳐야 한다.** 봉인 해제 전에
실행하면 둘 다 조용히, 그리고 되돌릴 수 없게 남의 데이터를 건드린다.

1. **네임스페이스 무지정 upsert** — 이 스크립트는 `index.upsert(vectors=...)`를
   네임스페이스 없이 호출해 기본 네임스페이스에 쓴다. 그런데 이 Pinecone 인덱스는
   **다른 프로젝트와 공유**하고 있고(인덱스명 `semiconductor-lithography`가 그
   흔적), 기본 네임스페이스 12,169벡터는 전부 반도체 프로젝트 소유다
   (실측 2026-08-23: `domain=semiconductor`, `category=반도체개발/재료/제조`).
   즉 **남의 영역에 우리 데이터를 섞는다.** 게다가 프로덕션 검색
   (`app/core/rag.py::NS_GROUPS`)은 `laborlaw-v2`/`counsel`/`qa` 세 곳만 읽으므로
   여기 올린 벡터는 **검색되지 않는다** — 임베딩 비용만 쓰고 성공 메시지는 정상
   출력되는 조용한 실패다.
2. **`--reset`이 인덱스를 통째로 삭제했다** — 구현이 `pc.delete_index()`였다.
   네임스페이스가 아니라 **인덱스 전체**라, 실행 시 반도체 프로젝트를 포함한
   139,776벡터가 전멸하고 Pinecone Serverless에는 복구 수단이 없다. 이 경로는
   제거했다(아래 `--reset` 처리 참조). 되살리더라도
   `index.delete(delete_all=True, namespace=...)`로 자기 네임스페이스에 한정할 것.

**현황**: BEST Q&A 274건은 프로덕션 코퍼스에 **없다**(실측: `qa` 네임스페이스
조회 0/274, 일반 Q&A 9,809건과 교집합 0건 — 중복 수록도 아니다). 로컬 원본
`output/`도 비어 있어 재적재하려면 `crawl_bestqna.py` 재크롤이 선행돼야 한다.

**되살리는 방법**: 이 파일을 고치지 말고 `pinecone_upload_court_precedents.py`나
`pinecone_upload_textbook.py`를 본떠 새로 쓰는 편이 안전하다. 그쪽은 네임스페이스
명시·ID 충돌 검사·zip 길이 검증·원장 기반 prune을 갖췄다. 벡터 ID는 `qa`
네임스페이스의 현행 규약인 `ctx_qa_{post_id}_c{i}`를 따를 것.

파이프라인(참고):
  1. metadata.json 로드 (없으면 generate_metadata.py 자동 실행)
  2. 각 markdown 파일을 섹션 단위로 청킹
  3. OpenAI text-embedding-3-small 로 임베딩 생성
  4. Pinecone에 배치 upsert
  5. metadata.json의 chunk_count, upload_status 갱신
"""

import os
import re
import sys
import json
import time
import argparse
from datetime import datetime

from dotenv import load_dotenv
from openai import OpenAI
from pinecone import Pinecone, ServerlessSpec

from app.config import resolve_index_name
from vector_ledger import atomic_write_json

load_dotenv()

# ── 설정 ──────────────────────────────────────────────────────────────────────
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR    = os.path.join(BASE_DIR, "output")
METADATA_FILE = os.path.join(BASE_DIR, "metadata.json")

EMBED_MODEL   = "text-embedding-3-small"
EMBED_DIM     = 1536
CHUNK_MAX     = 700   # 청크 최대 글자 수
CHUNK_OVERLAP = 80    # 청크 오버랩 글자 수

EMBED_BATCH   = 50    # OpenAI 한 번에 임베딩할 청크 수
UPSERT_BATCH  = 100   # Pinecone 한 번에 upsert할 벡터 수


# ── 텍스트 청킹 ───────────────────────────────────────────────────────────────

def clean_text(text: str) -> str:
    """markdown 특수문자 및 공백 정리"""
    text = text.replace("\xa0", " ")              # non-breaking space
    text = re.sub(r"\\\n", "\n", text)            # backslash line break → newline
    text = re.sub(r"\\([*_\[\]()#!])", r"\1", text)  # 이스케이프 제거
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_by_size(text: str, max_chars: int = CHUNK_MAX, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """단락 경계를 우선으로 max_chars 크기로 분할 (오버랩은 청크 간에만 적용)"""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))

        if end < len(text):
            # 마지막 청크가 아닐 때만 끊기 포인트 탐색
            # 단락 > 줄 > 문장 순 우선
            broke = False
            for delimiter in ["\n\n", "\n", ". ", ", "]:
                pos = text.rfind(delimiter, start + max(overlap, 50), end)
                if pos > start:
                    end = pos + len(delimiter)
                    broke = True
                    break
            # 적절한 위치를 못 찾으면 그냥 max_chars에서 자름

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= len(text):
            break  # 마지막 청크 처리 후 종료 (끝에서 슬라이딩 방지)

        start = end - overlap  # 다음 청크는 overlap만큼 뒤로 겹쳐서 시작

    return chunks


def extract_body(md_content: str) -> str:
    """markdown에서 본문만 추출 (메타 테이블 제외, ## 본문 이후)"""
    # "## 본문" 이후 전체
    match = re.search(r"^## 본문\s*\n\n(.*)", md_content, re.MULTILINE | re.DOTALL)
    if match:
        return clean_text(match.group(1))
    # 없으면 메타 테이블 이후의 전체 텍스트
    after_meta = re.sub(r"^.*?\n---\n\n", "", md_content, count=1, flags=re.DOTALL)
    return clean_text(after_meta)


def chunk_post(post_id: str, title: str, body: str) -> list[dict]:
    """
    본문을 섹션 단위로 청킹.
    반환 형식:
      - embed_text : 임베딩에 사용 (제목+섹션 컨텍스트 포함)
      - chunk_text : 실제 내용 (Pinecone metadata에 저장, 챗봇 답변에 사용)
      - section    : 섹션명
      - chunk_index: 게시글 내 순번
    """
    # ## / ### 헤더로 섹션 분리
    header_pat = re.compile(r"^(#{2,3})\s+(.+)$", re.MULTILINE)
    headers = list(header_pat.finditer(body))

    sections: list[tuple[str, str]] = []  # (section_name, content)

    # 첫 헤더 이전 내용 (질문 본문)
    if not headers or headers[0].start() > 0:
        pre = body[: headers[0].start() if headers else len(body)].strip()
        if pre:
            sections.append(("질문", pre))

    # 각 헤더 섹션
    for i, h in enumerate(headers):
        section_name = h.group(2).strip()
        content_start = h.end()
        content_end = headers[i + 1].start() if i + 1 < len(headers) else len(body)
        content = body[content_start:content_end].strip()
        if content:
            sections.append((section_name, content))

    # 청크 생성
    chunks = []
    idx = 0
    for section_name, content in sections:
        for sub_text in split_by_size(content):
            if not sub_text.strip():
                continue
            # 임베딩 텍스트: 제목 + 섹션명 prefix → 검색 품질 향상
            embed_text = f"제목: {title}\n섹션: {section_name}\n\n{sub_text}"
            chunks.append({
                "chunk_id":    f"{post_id}_chunk_{idx}",
                "chunk_index": idx,
                "section":     section_name,
                "embed_text":  embed_text,
                "chunk_text":  sub_text,   # Pinecone metadata 저장용
            })
            idx += 1

    # 섹션 없으면 전체를 하나의 청크로
    if not chunks:
        for sub_text in split_by_size(body):
            embed_text = f"제목: {title}\n\n{sub_text}"
            chunks.append({
                "chunk_id":    f"{post_id}_chunk_{idx}",
                "chunk_index": idx,
                "section":     "본문",
                "embed_text":  embed_text,
                "chunk_text":  sub_text,
            })
            idx += 1

    return chunks


# ── 임베딩 ────────────────────────────────────────────────────────────────────

def embed_texts(texts: list[str], client: OpenAI) -> list[list[float]]:
    """OpenAI 임베딩 API 호출 (재시도 포함)"""
    for attempt in range(3):
        try:
            resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
            return [d.embedding for d in sorted(resp.data, key=lambda x: x.index)]
        except Exception as e:
            if attempt == 2:
                raise
            print(f"  임베딩 재시도 ({attempt+1}/3): {e}")
            time.sleep(2 ** attempt)
    return []


def embed_all(chunks: list[dict], client: OpenAI) -> list[list[float]]:
    """전체 청크 임베딩 (배치 처리)"""
    embeddings = []
    total = len(chunks)
    for i in range(0, total, EMBED_BATCH):
        batch = chunks[i : i + EMBED_BATCH]
        texts = [c["embed_text"] for c in batch]
        vecs = embed_texts(texts, client)
        embeddings.extend(vecs)
        print(f"  임베딩: {min(i + EMBED_BATCH, total)}/{total}", end="\r")
        time.sleep(0.3)  # rate limit 방지
    print()
    return embeddings


# ── Pinecone ──────────────────────────────────────────────────────────────────

def get_or_create_index(pc: Pinecone, index_name: str) -> any:
    """Pinecone 인덱스 준비 (없으면 Serverless로 생성)"""
    existing_names = [idx.name for idx in pc.list_indexes()]
    if index_name not in existing_names:
        print(f"인덱스 생성: {index_name} (dim={EMBED_DIM}, metric=cosine, AWS us-east-1)")
        pc.create_index(
            name=index_name,
            dimension=EMBED_DIM,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )
        # 준비 완료까지 대기
        for _ in range(30):
            if pc.describe_index(index_name).status["ready"]:
                break
            time.sleep(2)
        print("인덱스 생성 완료")
    else:
        print(f"기존 인덱스 사용: {index_name}")
    return pc.Index(index_name)


def build_pinecone_vector(chunk: dict, embedding: list[float], post_meta: dict) -> dict:
    """Pinecone upsert용 벡터 dict 생성"""
    # chunk_text는 최대 900자 (Pinecone metadata 제한 대응)
    chunk_text_stored = chunk["chunk_text"][:900]

    return {
        "id": chunk["chunk_id"],
        "values": embedding,
        "metadata": {
            # 검색 결과 표시용
            "post_id":     post_meta["post_id"],
            "title":       post_meta["title"],
            "date":        post_meta["date"],
            "date_num":    post_meta["date_num"],   # 날짜 range 필터용
            "views":       post_meta["views"],
            "url":         post_meta["url"],
            # 청크 정보
            "section":     chunk["section"],
            "chunk_index": chunk["chunk_index"],
            "chunk_text":  chunk_text_stored,       # RAG 컨텍스트 복원용
        },
    }


def upsert_vectors(index, vectors: list[dict]):
    """Pinecone에 배치 upsert"""
    total = len(vectors)
    for i in range(0, total, UPSERT_BATCH):
        batch = vectors[i : i + UPSERT_BATCH]
        index.upsert(vectors=batch)
        print(f"  upsert: {min(i + UPSERT_BATCH, total)}/{total}", end="\r")
        time.sleep(0.1)
    print()


# ── 메인 ──────────────────────────────────────────────────────────────────────

def load_metadata() -> dict:
    if not os.path.exists(METADATA_FILE):
        print("metadata.json이 없습니다. generate_metadata.py를 먼저 실행합니다...\n")
        import subprocess
        subprocess.run([sys.executable, os.path.join(BASE_DIR, "generate_metadata.py")], check=True)
    with open(METADATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_metadata(metadata: dict):
    """업로드 상태를 원자적으로 저장한다(외부감사 2026-08-23 M8).

    직접 쓰기는 중단 시 빈 파일을 남겨 274건의 `upload_status`를 통째로 잃는다.
    """
    metadata["last_upload"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    atomic_write_json(METADATA_FILE, metadata, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Pinecone 업로드 (봉인됨)")
    parser.add_argument("--reset",   action="store_true", help="[제거됨] 인덱스 전체를 삭제하던 옵션")
    parser.add_argument("--pending", action="store_true", help="pending 상태만 업로드")
    args = parser.parse_args()

    # ── 실행 봉인 ────────────────────────────────────────────────────────────
    # 사유는 모듈 docstring에 있다. 요약: 네임스페이스 무지정 upsert가 다른
    # 프로젝트의 기본 네임스페이스에 쓰고, 그 벡터는 프로덕션 검색 대상도 아니다.
    # 실패가 조용하므로(성공 메시지·정상 벡터 수가 그대로 찍힌다) 경고가 아니라
    # 차단으로 둔다.
    #
    # **해제 플래그를 두지 않는다**(CodeRabbit 리뷰 2026-08-23). 결함이 그대로인
    # 채 우회로만 있으면 그 문을 여는 순간 정확히 봉인이 막으려던 사고가 난다 —
    # 아래 upsert는 여전히 네임스페이스 무지정이다. 되살리는 방법은 이 파일을
    # 고치는 게 아니라 docstring의 안내대로 새로 작성하는 것이다.
    if True:
        sys.exit(
            "[봉인] 이 스크립트는 실행이 차단돼 있습니다 (2026-08-23).\n"
            "  · 네임스페이스 무지정 upsert → 반도체 프로젝트의 기본 네임스페이스에 기록됨\n"
            "  · 프로덕션 검색(rag.py::NS_GROUPS)은 laborlaw-v2/counsel/qa만 읽음 → 검색 불가\n"
            "  · BEST Q&A 274건은 현재 프로덕션에 없고 로컬 원본(output/)도 비어 있음\n"
            "  재적재가 필요하면 crawl_bestqna.py로 재크롤 후, "
            "pinecone_upload_court_precedents.py를 본떠\n"
            "  qa 네임스페이스에 ctx_qa_{post_id}_c{i} 규약으로 올리는 스크립트를 새로 작성하세요.\n"
            "  자세한 사유: 이 파일 상단 docstring"
        )

    # API 키 확인
    openai_key   = os.getenv("OPENAI_API_KEY")
    pinecone_key = os.getenv("PINECONE_API_KEY")
    index_name   = resolve_index_name()

    if not openai_key:
        sys.exit("[오류] OPENAI_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")
    if not pinecone_key:
        sys.exit("[오류] PINECONE_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")

    openai_client = OpenAI(api_key=openai_key)
    pc = Pinecone(api_key=pinecone_key)

    # 인덱스 준비
    # `--reset`의 pc.delete_index()는 제거됐다 — 네임스페이스가 아니라 **인덱스
    # 전체**를 지워 공유 인덱스의 타 프로젝트 데이터(139,776벡터)까지 파괴했고,
    # Pinecone Serverless에는 복구 수단이 없다. 삭제가 정말 필요하면
    # index.delete(delete_all=True, namespace=<자기 NS>)로 범위를 좁힐 것.
    if args.reset:
        sys.exit(
            "[차단] --reset은 제거됐습니다. 인덱스 전체 삭제라 공유 인덱스의 "
            "타 프로젝트 데이터까지 파괴합니다.\n"
            "  네임스페이스 한정 삭제가 필요하면 "
            "index.delete(delete_all=True, namespace=...)를 명시적으로 작성하세요."
        )
    index = get_or_create_index(pc, index_name)

    # 메타데이터 로드
    metadata = load_metadata()
    posts = metadata["posts"]

    # 업로드 대상 필터링
    if args.pending:
        targets = [p for p in posts if p.get("upload_status") != "uploaded"]
        print(f"\n업로드 대상: {len(targets)}개 (pending/failed)")
    elif args.reset:
        # reset이면 전체 재업로드 → status 초기화
        for p in posts:
            p["upload_status"] = "pending"
            p["chunk_count"] = 0
        targets = posts
        print(f"\n업로드 대상: {len(targets)}개 (전체 초기화)")
    else:
        targets = [p for p in posts if p.get("upload_status") != "uploaded"]
        if not targets:
            print("\n모든 게시글이 이미 업로드됨. --reset으로 재업로드하거나 --pending으로 실패분만 재시도.")
            return
        print(f"\n업로드 대상: {len(targets)}개")

    print(f"인덱스: {index_name}  |  임베딩 모델: {EMBED_MODEL}\n")
    print("=" * 60)

    total_chunks = 0
    failed = []

    for i, post_meta in enumerate(targets, 1):
        post_id  = post_meta["post_id"]
        title    = post_meta["title"]
        filename = post_meta["filename"]
        filepath = os.path.join(OUTPUT_DIR, filename)

        print(f"\n[{i}/{len(targets)}] {title[:45]}...")

        # markdown 파일 읽기
        if not os.path.exists(filepath):
            print(f"  [스킵] 파일 없음: {filename}")
            post_meta["upload_status"] = "failed"
            failed.append(post_id)
            continue

        with open(filepath, "r", encoding="utf-8") as f:
            md_content = f.read()

        body = extract_body(md_content)
        if not body:
            print(f"  [스킵] 본문 없음")
            post_meta["upload_status"] = "failed"
            failed.append(post_id)
            continue

        # 청킹
        chunks = chunk_post(post_id, title, body)
        if not chunks:
            print(f"  [스킵] 청크 생성 실패")
            post_meta["upload_status"] = "failed"
            failed.append(post_id)
            continue

        print(f"  청크: {len(chunks)}개  |  본문: {len(body):,}자")

        # 임베딩
        try:
            embeddings = embed_all(chunks, openai_client)
        except Exception as e:
            print(f"  [오류] 임베딩 실패: {e}")
            post_meta["upload_status"] = "failed"
            failed.append(post_id)
            continue

        # Pinecone 벡터 구성
        vectors = [
            build_pinecone_vector(chunk, emb, post_meta)
            for chunk, emb in zip(chunks, embeddings)
        ]

        # upsert
        try:
            upsert_vectors(index, vectors)
        except Exception as e:
            print(f"  [오류] upsert 실패: {e}")
            post_meta["upload_status"] = "failed"
            failed.append(post_id)
            continue

        # 상태 업데이트
        post_meta["chunk_count"] = len(chunks)
        post_meta["upload_status"] = "uploaded"
        total_chunks += len(chunks)

        print(f"  완료 ✓")

        # 50개마다 중간 저장
        if i % 50 == 0:
            save_metadata(metadata)
            print(f"\n  [중간 저장] metadata.json 갱신\n")

    # 최종 저장
    save_metadata(metadata)

    # 인덱스 통계
    stats = index.describe_index_stats()

    print("\n" + "=" * 60)
    print(f"=== 업로드 완료 ===")
    print(f"성공: {len(targets) - len(failed)}개 / 실패: {len(failed)}개")
    print(f"총 벡터 수: {total_chunks:,}개")
    print(f"Pinecone 총 벡터: {stats.total_vector_count:,}개")
    print(f"인덱스: {index_name}")
    if failed:
        print(f"\n실패 post_id: {failed}")


if __name__ == "__main__":
    main()
