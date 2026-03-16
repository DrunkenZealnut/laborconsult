#!/usr/bin/env python3
"""
대법원_2020~2026 폴더의 신규 판례를 Pinecone에 업로드하고 카테고리 폴더로 이동.

처리 흐름:
1. 기존 카테고리 폴더(.md)에서 사건번호 수집 → 중복 세트 구성
2. 대법원_20XX 폴더(.txt) 순회 → 사건번호로 중복 검사
3. 신규 파일: .txt → .md 변환 + 카테고리 자동 분류
4. Pinecone 업로드 (namespace=precedent)
5. .md 파일을 해당 카테고리 폴더로 이동

사용법:
  python3 upload_new_precedents.py              # 전체 실행
  python3 upload_new_precedents.py --dry-run    # 변환/분류만 (업로드·이동 안 함)
  python3 upload_new_precedents.py --year 2024  # 특정 연도만
"""

import os
import re
import sys
import time
import shutil
import argparse
from datetime import datetime

from dotenv import load_dotenv
from openai import OpenAI
from pinecone import Pinecone

load_dotenv()

# ── 설정 ──────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRECEDENT_DIR = os.path.join(BASE_DIR, "output_법원 노동판례")

EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536
CHUNK_MAX = 700
CHUNK_OVERLAP = 80
EMBED_BATCH = 50
UPSERT_BATCH = 100
NAMESPACE = "precedent"

CATEGORY_DIRS = ["근로기준", "노동조합", "산재보상", "비정규직", "기타"]
YEAR_DIRS = [f"대법원_{y}" for y in range(2020, 2027)]

# ── 사건번호 패턴 ────────────────────────────────────────────────────────────
CASE_NO_PATTERN = re.compile(r"(\d{4}[다두도가누][A-Za-z가-힣]*\d+)")

# 한글 → ASCII 매핑 (Pinecone ID용)
KR_TO_ASCII = {
    "다": "da", "두": "du", "도": "do", "가": "ga", "누": "nu",
    "나": "na", "마": "ma", "추": "chu", "재": "jae", "허": "heo",
}


def case_no_to_ascii(case_no: str) -> str:
    """사건번호의 한글을 ASCII로 변환 (Pinecone ID용)."""
    result = case_no
    for kr, en in KR_TO_ASCII.items():
        result = result.replace(kr, en)
    # 남은 비ASCII 문자 제거
    result = re.sub(r"[^\x00-\x7F]", "", result)
    return result

# ── 카테고리 분류 키워드 ─────────────────────────────────────────────────────
CATEGORY_KEYWORDS = {
    "노동조합": [
        "노동조합", "노조", "단체교섭", "쟁의", "파업", "교섭창구",
        "부당노동행위", "단체협약", "조합원", "쟁의행위", "교섭대표",
        "복수노조", "노동위원회", "공정대표의무",
    ],
    "산재보상": [
        "산재", "산업재해", "업무상 재해", "업무상재해", "요양급여",
        "장해급여", "유족급여", "진폐", "출퇴근 재해", "출퇴근재해",
        "산재보험", "업무상 질병", "업무상질병", "산업재해보상",
        "재해위로금", "장해등급", "요양", "업무상 사망",
    ],
    "비정규직": [
        "파견근로", "기간제", "비정규", "차별시정", "고용간주",
        "직접고용 간주", "직접고용간주", "고용의무", "고용승계",
        "파견법", "기간제법", "단시간", "용역근로", "사내하도급",
        "불법파견", "갱신기대권",
    ],
}


# ── 1단계: 기존 사건번호 수집 ─────────────────────────────────────────────────

def collect_existing_case_numbers() -> set[str]:
    """기존 카테고리 폴더의 .md 파일에서 모든 사건번호 추출."""
    existing = set()
    for cat in CATEGORY_DIRS:
        cat_dir = os.path.join(PRECEDENT_DIR, cat)
        if not os.path.isdir(cat_dir):
            continue
        for fname in os.listdir(cat_dir):
            if not fname.endswith(".md"):
                continue
            filepath = os.path.join(cat_dir, fname)
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            for m in CASE_NO_PATTERN.finditer(content):
                existing.add(m.group(1))
    return existing


# ── 2단계: 카테고리 분류 ─────────────────────────────────────────────────────

def classify_category(title: str, content: str) -> str:
    """제목 가중(x3) + 본문 키워드로 카테고리 분류.
    제목에 키워드가 있으면 3배 가중치, 본문은 1배."""
    scores = {}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        title_score = sum(3 for kw in keywords if kw in title)
        body_score = sum(1 for kw in keywords if kw in content[:2000])
        total = title_score + body_score
        if total > 0:
            scores[cat] = total

    if not scores:
        return "근로기준"

    # 최고 점수 카테고리 결정, 단 근로기준 대비 다른 카테고리가
    # 확실히 높을 때만 (근로기준은 기본값이므로)
    best_cat = max(scores, key=scores.get)
    best_score = scores[best_cat]

    # 제목에 해당 카테고리 키워드가 없으면 본문만으로는
    # 임계치(3점) 이상이어야 비근로기준으로 분류
    title_has_keyword = any(kw in title for kw in CATEGORY_KEYWORDS.get(best_cat, []))
    if not title_has_keyword and best_score < 3:
        return "근로기준"

    return best_cat


# ── 3단계: txt → md 변환 ─────────────────────────────────────────────────────

def parse_txt_filename(filename: str) -> dict:
    """파일명에서 메타데이터 추출.
    예: 038_38_대법_20200604_2019다297496_부사장으로_호칭됐으나_..._.txt
    """
    parts = filename.replace(".txt", "").split("_")
    info = {"seq": "", "court": "", "date": "", "case_no": "", "title": ""}

    if len(parts) >= 5:
        info["seq"] = parts[1] if len(parts) > 1 else parts[0]
        info["court"] = parts[2] if len(parts) > 2 else ""

        # 날짜 찾기 (YYYYMMDD 형식)
        date_match = re.search(r"(20\d{6})", filename)
        if date_match:
            d = date_match.group(1)
            info["date"] = f"{d[:4]}.{d[4:6]}.{d[6:8]}"

        # 사건번호 찾기
        case_match = CASE_NO_PATTERN.search(filename)
        if case_match:
            info["case_no"] = case_match.group(1)

        # 제목: 사건번호 이후의 부분
        if case_match:
            title_start = filename.index(case_match.group(1)) + len(case_match.group(1)) + 1
            info["title"] = filename[title_start:].replace(".txt", "").replace("_", " ").strip()
        else:
            info["title"] = " ".join(parts[4:])

    return info


def convert_to_markdown(filepath: str, meta: dict, category: str) -> str:
    """txt 판례 파일을 md 형식으로 변환."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # 원본에서 첫 줄 제거 (보통 "한국실무노동법연구소")
    lines = content.strip().split("\n")
    if lines and "연구소" in lines[0]:
        lines = lines[1:]
    body = "\n".join(lines).strip()

    title = meta["title"] or meta["case_no"]
    date_str = meta["date"] or ""

    md = f"""# {title}

| 항목 | 내용 |
| --- | --- |
| 분류 | {category} |
| 작성일 | {date_str} |
| 사건번호 | {meta['case_no']} |

---

{body}
"""
    return md


# ── 4단계: 청킹 (pinecone_upload_legal.py 로직 재활용) ───────────────────────

def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"\\\n", "\n", text)
    text = re.sub(r"\\([*_\[\]()#!])", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_by_size(text: str, max_chars: int = CHUNK_MAX, overlap: int = CHUNK_OVERLAP) -> list[str]:
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
            for delimiter in ["\n\n", "\n", ". ", ", "]:
                pos = text.rfind(delimiter, start + max(overlap, 50), end)
                if pos > start:
                    end = pos + len(delimiter)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = end - overlap
    return chunks


def chunk_document(case_no: str, title: str, category: str, body: str) -> list[dict]:
    """판례 본문을 청크로 분할."""
    body = clean_text(body)
    header_pat = re.compile(r"^(#{2,3})\s+(.+)$", re.MULTILINE)
    headers = list(header_pat.finditer(body))

    sections: list[tuple[str, str]] = []

    if not headers or headers[0].start() > 0:
        pre = body[: headers[0].start() if headers else len(body)].strip()
        if pre:
            sections.append(("본문", pre))

    for i, h in enumerate(headers):
        section_name = h.group(2).strip()
        content_start = h.end()
        content_end = headers[i + 1].start() if i + 1 < len(headers) else len(body)
        content = body[content_start:content_end].strip()
        if content:
            sections.append((section_name, content))

    chunks = []
    idx = 0
    for section_name, content in sections:
        for sub_text in split_by_size(content):
            if not sub_text.strip():
                continue
            embed_text = f"제목: {title}\n분류: {category}\n섹션: {section_name}\n\n{sub_text}"
            chunks.append(
                {
                    "chunk_id": f"precedent_{case_no_to_ascii(case_no)}_chunk_{idx}",
                    "chunk_index": idx,
                    "section": section_name,
                    "embed_text": embed_text,
                    "chunk_text": sub_text,
                }
            )
            idx += 1

    if not chunks:
        for sub_text in split_by_size(body):
            embed_text = f"제목: {title}\n분류: {category}\n\n{sub_text}"
            chunks.append(
                {
                    "chunk_id": f"precedent_{case_no_to_ascii(case_no)}_chunk_{idx}",
                    "chunk_index": idx,
                    "section": "본문",
                    "embed_text": embed_text,
                    "chunk_text": sub_text,
                }
            )
            idx += 1

    return chunks


# ── 5단계: 임베딩 + Pinecone 업로드 ─────────────────────────────────────────

def embed_texts(texts: list[str], client: OpenAI) -> list[list[float]]:
    for attempt in range(3):
        try:
            resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
            return [d.embedding for d in sorted(resp.data, key=lambda x: x.index)]
        except Exception as e:
            if attempt == 2:
                raise
            print(f"  임베딩 재시도 ({attempt + 1}/3): {e}")
            time.sleep(2**attempt)
    return []


def build_vector(chunk: dict, embedding: list[float], title: str, category: str, date: str, case_no: str) -> dict:
    return {
        "id": chunk["chunk_id"],
        "values": embedding,
        "metadata": {
            "source_type": "precedent",
            "title": title[:200],
            "category": category[:50],
            "date": date,
            "url": "",
            "section": chunk["section"][:100],
            "chunk_index": chunk["chunk_index"],
            "chunk_text": chunk["chunk_text"][:900],
        },
    }


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="신규 판례 업로드 (중복 검사 + 카테고리 이동)")
    parser.add_argument("--dry-run", action="store_true", help="변환/분류만 수행 (업로드·이동 안 함)")
    parser.add_argument("--year", type=int, help="특정 연도만 처리 (예: 2024)")
    args = parser.parse_args()

    openai_key = os.getenv("OPENAI_API_KEY")
    pinecone_key = os.getenv("PINECONE_API_KEY")
    index_name = os.getenv("PINECONE_INDEX_NAME", "nodongok-bestqna")

    if not openai_key:
        sys.exit("[오류] OPENAI_API_KEY가 설정되지 않았습니다.")
    if not args.dry_run and not pinecone_key:
        sys.exit("[오류] PINECONE_API_KEY가 설정되지 않았습니다.")

    openai_client = OpenAI(api_key=openai_key)
    index = None
    if not args.dry_run:
        pc = Pinecone(api_key=pinecone_key)
        index = pc.Index(index_name)

    # 1. 기존 사건번호 수집
    print("=" * 60)
    print("1단계: 기존 사건번호 수집")
    existing_cases = collect_existing_case_numbers()
    print(f"  기존 고유 사건번호: {len(existing_cases)}개")

    # 2. 신규 파일 수집 + 중복 검사
    print("\n2단계: 신규 파일 수집 + 중복 검사")

    years = [args.year] if args.year else list(range(2020, 2027))
    new_files = []  # (year, filepath, meta, case_no)
    skipped_dups = 0
    skipped_no_case = 0

    for year in years:
        yr_dir = os.path.join(PRECEDENT_DIR, f"대법원_{year}")
        if not os.path.isdir(yr_dir):
            continue
        for fname in sorted(os.listdir(yr_dir)):
            if not fname.endswith(".txt"):
                continue
            filepath = os.path.join(yr_dir, fname)
            meta = parse_txt_filename(fname)
            case_no = meta["case_no"]

            if not case_no:
                skipped_no_case += 1
                print(f"  [스킵] 사건번호 없음: {fname}")
                continue

            if case_no in existing_cases:
                skipped_dups += 1
                continue

            new_files.append((year, filepath, meta, case_no))

    print(f"  전체 스캔: {skipped_dups + skipped_no_case + len(new_files)}개")
    print(f"  중복 건너뜀: {skipped_dups}개")
    print(f"  사건번호 없음: {skipped_no_case}개")
    print(f"  업로드 대상: {len(new_files)}개")

    if not new_files:
        print("\n업로드할 파일이 없습니다.")
        return

    # 3. 변환 + 분류 + 업로드
    print(f"\n3단계: 변환 + 분류 + 업로드 {'(DRY RUN)' if args.dry_run else ''}")

    category_counts = {}
    total_chunks = 0
    errors = 0
    all_vectors = []
    moved_files = []  # (src, dst) for post-upload move

    for i, (year, filepath, meta, case_no) in enumerate(new_files, 1):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                raw_content = f.read()
        except Exception as e:
            print(f"  [{i}] 읽기 실패: {e}")
            errors += 1
            continue

        # 카테고리 분류
        title = meta["title"]
        category = classify_category(title, raw_content)
        category_counts[category] = category_counts.get(category, 0) + 1

        # md 변환
        md_content = convert_to_markdown(filepath, meta, category)

        # 본문 추출 (--- 이후)
        body_parts = md_content.split("\n---\n", 1)
        body = clean_text(body_parts[1]) if len(body_parts) > 1 else clean_text(raw_content)

        if len(body) < 20:
            continue

        # 청킹
        chunks = chunk_document(case_no, title, category, body)
        if not chunks:
            continue
        total_chunks += len(chunks)

        # md 파일 저장 경로
        safe_title = re.sub(r'[/\\:*?"<>|]', "", title)[:60]
        md_filename = f"{case_no}_{safe_title}.md"
        cat_dir = os.path.join(PRECEDENT_DIR, category)
        os.makedirs(cat_dir, exist_ok=True)
        md_dest = os.path.join(cat_dir, md_filename)

        if args.dry_run:
            if i <= 10 or i % 100 == 0:
                print(f"  [{i}/{len(new_files)}] {case_no} → {category} | {title[:40]}... ({len(chunks)} 청크)")
            moved_files.append((filepath, md_dest))
            continue

        # md 파일 저장 (이미 존재하면 덮어쓰기)
        with open(md_dest, "w", encoding="utf-8") as f:
            f.write(md_content)

        # 임베딩
        texts = [c["embed_text"] for c in chunks]
        embeddings = []
        for batch_start in range(0, len(texts), EMBED_BATCH):
            batch = texts[batch_start : batch_start + EMBED_BATCH]
            embeddings.extend(embed_texts(batch, openai_client))
            time.sleep(0.3)

        # 벡터 구성
        for chunk, emb in zip(chunks, embeddings):
            all_vectors.append(build_vector(chunk, emb, title, category, meta["date"], case_no))

        # 벡터 배치 upsert
        if len(all_vectors) >= UPSERT_BATCH:
            index.upsert(vectors=all_vectors, namespace=NAMESPACE)
            all_vectors = []
            time.sleep(0.1)

        moved_files.append((filepath, md_dest))

        if i % 50 == 0 or i == len(new_files):
            print(f"  진행: {i}/{len(new_files)} 파일, {total_chunks} 청크")

    # 남은 벡터 upsert
    if all_vectors and not args.dry_run:
        index.upsert(vectors=all_vectors, namespace=NAMESPACE)

    # 4. 원본 txt 파일 삭제 (md로 이동 완료 후)
    if not args.dry_run:
        print(f"\n4단계: 원본 .txt 파일 삭제")
        removed = 0
        for src, dst in moved_files:
            if os.path.exists(dst) and os.path.exists(src):
                os.remove(src)
                removed += 1
        print(f"  삭제 완료: {removed}개")

    # 최종 통계
    print(f"\n{'=' * 60}")
    print(f"=== 완료 {'(DRY RUN)' if args.dry_run else ''} ===")
    print(f"업로드: {len(moved_files)}개 파일, {total_chunks} 청크")
    print(f"중복 건너뜀: {skipped_dups}개")
    print(f"오류: {errors}개")
    print(f"\n카테고리별 분류:")
    for cat in sorted(category_counts.keys()):
        print(f"  {cat}: {category_counts[cat]}개")

    if not args.dry_run and index:
        time.sleep(2)
        stats = index.describe_index_stats()
        print(f"\nPinecone 인덱스 통계:")
        print(f"  총 벡터: {stats.total_vector_count:,}개")
        if hasattr(stats, "namespaces"):
            for ns_name, ns_info in stats.namespaces.items():
                print(f"  namespace='{ns_name}': {ns_info.vector_count:,}개")

    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
