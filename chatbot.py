#!/usr/bin/env python3
"""
노동OK BEST Q&A 챗봇

사용법:
  python3 chatbot.py              # 기본 모드
  python3 chatbot.py --top 7     # 검색 결과 수 조정 (기본 5)
  python3 chatbot.py --threshold 0.5  # 유사도 임계값 조정 (기본 0.4)
  python3 chatbot.py --search-only    # Claude 답변 없이 검색 결과만 표시

종료: q / quit / 엔터 두 번
"""

import os
import sys
import argparse
import textwrap

from dotenv import load_dotenv
from openai import OpenAI
from pinecone import Pinecone
import anthropic

load_dotenv()

# ── 설정 ──────────────────────────────────────────────────────────────────────
EMBED_MODEL  = "text-embedding-3-small"
CLAUDE_MODEL = "claude-opus-4-6"
INDEX_NAME   = os.getenv("PINECONE_INDEX_NAME", "nodongok-bestqna")
WRAP_WIDTH   = 80


# ── 검색 ──────────────────────────────────────────────────────────────────────

def embed_query(query: str, client: OpenAI) -> list[float]:
    resp = client.embeddings.create(model=EMBED_MODEL, input=[query])
    return resp.data[0].embedding


def search(query: str, index, openai_client: OpenAI,
           top_k: int = 5, threshold: float = 0.4) -> list[dict]:
    """Pinecone 벡터 검색 → 임계값 이상의 결과만 반환"""
    qvec = embed_query(query, openai_client)
    results = index.query(vector=qvec, top_k=top_k, include_metadata=True)

    hits = []
    for match in results.matches:
        if match.score < threshold:
            continue
        hits.append({
            "score":       round(match.score, 4),
            "post_id":     match.metadata.get("post_id", ""),
            "title":       match.metadata.get("title", ""),
            "date":        match.metadata.get("date", ""),
            "views":       match.metadata.get("views", 0),
            "url":         match.metadata.get("url", ""),
            "section":     match.metadata.get("section", ""),
            "chunk_text":  match.metadata.get("chunk_text", ""),
        })

    return hits


# ── RAG 컨텍스트 구성 ──────────────────────────────────────────────────────────

def build_context(hits: list[dict]) -> str:
    """검색 결과를 Claude에게 전달할 컨텍스트로 포맷"""
    parts = []
    seen_posts = {}  # 같은 게시글이 여러 청크로 나올 때 중복 제목 방지

    for i, h in enumerate(hits, 1):
        pid = h["post_id"]
        header = f"[문서 {i}] {h['title']}"
        if pid in seen_posts:
            header += f" (계속)"
        seen_posts[pid] = True

        section_info = f" > {h['section']}" if h["section"] not in ("질문", "본문", h["title"]) else ""
        parts.append(
            f"{header}{section_info}\n"
            f"출처: {h['url']}  |  작성일: {h['date']}\n\n"
            f"{h['chunk_text']}"
        )

    return "\n\n---\n\n".join(parts)


# ── Claude 답변 생성 ───────────────────────────────────────────────────────────

SYSTEM_PROMPT = """당신은 한국 노동법 전문 상담사입니다.
아래 '참고 문서'는 노동OK(www.nodong.kr)의 BEST Q&A에서 가져온 실제 상담 사례입니다.

답변 원칙:
- 참고 문서에 있는 내용을 바탕으로 정확하게 답변하세요.
- 관련 법 조문이나 행정해석이 있으면 함께 언급하세요.
- 문서에 없는 내용은 "해당 내용은 참고 문서에서 확인되지 않습니다"라고 명시하세요.
- 답변 마지막에 참고 출처 URL을 표시하세요.
- 법적 조언이 아닌 정보 제공임을 명심하세요."""


def generate_answer(query: str, context: str, claude_client: anthropic.Anthropic) -> str:
    """Claude로 RAG 답변 생성 (스트리밍)"""
    user_message = f"참고 문서:\n\n{context}\n\n---\n\n질문: {query}"

    print("\n💬 답변:\n")

    full_text = ""
    with claude_client.messages.stream(
        model=CLAUDE_MODEL,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
            full_text += text

    print("\n")
    return full_text


# ── 출력 헬퍼 ─────────────────────────────────────────────────────────────────

def print_search_results(hits: list[dict]):
    """검색 결과 목록 출력"""
    if not hits:
        print("\n  관련 문서를 찾지 못했습니다.\n")
        return

    print(f"\n📚 관련 문서 ({len(hits)}개):\n")
    seen = {}
    rank = 1
    for h in hits:
        pid = h["post_id"]
        label = f"  {rank}. [{h['score']:.3f}] {h['title']}"
        sub   = f"      섹션: {h['section']}  |  {h['date']}  |  조회 {int(h['views']):,}"
        url   = f"      {h['url']}"

        if pid not in seen:
            print(label)
            print(sub)
            print(url)
            seen[pid] = rank
            rank += 1
        else:
            print(f"  {'':>2}  └ 추가 섹션: {h['section']} (유사도 {h['score']:.3f})")


def print_chunk_previews(hits: list[dict]):
    """각 청크의 내용 미리보기 출력"""
    print("\n📄 관련 내용 미리보기:\n")
    for i, h in enumerate(hits, 1):
        preview = h["chunk_text"][:200].replace("\n", " ")
        print(f"  [{i}] {h['title']} > {h['section']}")
        print(f"       {preview}{'...' if len(h['chunk_text']) > 200 else ''}")
        print()


def separator():
    print("─" * WRAP_WIDTH)


# ── 메인 챗봇 루프 ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="노동OK 챗봇")
    parser.add_argument("--top",         type=int,   default=5,   help="검색 결과 수 (기본 5)")
    parser.add_argument("--threshold",   type=float, default=0.4, help="유사도 임계값 (기본 0.4)")
    parser.add_argument("--search-only", action="store_true",     help="Claude 답변 없이 검색만")
    args = parser.parse_args()

    # API 키 확인
    openai_key   = os.getenv("OPENAI_API_KEY")
    pinecone_key = os.getenv("PINECONE_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")

    missing = []
    if not openai_key:   missing.append("OPENAI_API_KEY")
    if not pinecone_key: missing.append("PINECONE_API_KEY")
    if not args.search_only and not anthropic_key:
        missing.append("ANTHROPIC_API_KEY (--search-only 옵션으로 우회 가능)")
    if missing:
        sys.exit(f"[오류] .env에 설정 필요: {', '.join(missing)}")

    # 클라이언트 초기화
    openai_client = OpenAI(api_key=openai_key)
    pc = Pinecone(api_key=pinecone_key)
    claude_client = anthropic.Anthropic(api_key=anthropic_key) if not args.search_only else None

    # Pinecone 인덱스 연결
    try:
        index = pc.Index(INDEX_NAME)
        stats = index.describe_index_stats()
        total_vecs = stats.total_vector_count
    except Exception as e:
        sys.exit(f"[오류] Pinecone 인덱스 연결 실패: {e}\npinecone_upload.py를 먼저 실행하세요.")

    # 시작 메시지
    separator()
    print("  노동OK BEST Q&A 챗봇")
    print(f"  벡터 수: {total_vecs:,}  |  검색 결과: top {args.top}  |  임계값: {args.threshold}")
    if args.search_only:
        print("  모드: 검색 전용 (Claude 답변 없음)")
    separator()
    print("  노동 관련 질문을 입력하세요. 종료: q\n")

    empty_count = 0

    while True:
        try:
            query = input("질문 › ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n종료합니다.")
            break

        if not query:
            empty_count += 1
            if empty_count >= 2:
                print("종료합니다.")
                break
            continue
        empty_count = 0

        if query.lower() in ("q", "quit", "exit", "종료"):
            print("종료합니다.")
            break

        separator()

        # 검색
        print(f"🔍 '{query}' 검색 중...")
        try:
            hits = search(query, index, openai_client, args.top, args.threshold)
        except Exception as e:
            print(f"[오류] 검색 실패: {e}")
            continue

        if not hits:
            print(f"\n  유사도 {args.threshold} 이상의 관련 문서를 찾지 못했습니다.")
            print(f"  --threshold 값을 낮추거나 다른 키워드로 시도해보세요.\n")
            separator()
            continue

        # 검색 결과 출력
        print_search_results(hits)

        if args.search_only:
            print_chunk_previews(hits)
            separator()
            continue

        # RAG 답변 생성
        context = build_context(hits)
        try:
            generate_answer(query, context, claude_client)
        except Exception as e:
            print(f"\n[오류] 답변 생성 실패: {e}")

        separator()


if __name__ == "__main__":
    main()
