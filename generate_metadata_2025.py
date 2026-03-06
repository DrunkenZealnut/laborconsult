#!/usr/bin/env python3
"""
output_2025/ 폴더의 2025년 markdown 파일들을 분석하여 metadata_2025.json 생성

생성되는 metadata_2025.json은:
  1. pinecone_upload_2025.py의 업로드 소스
  2. 업로드 완료 후 chunk_count, upload_status 업데이트됨
"""

import os
import re
import json
from datetime import datetime

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR    = os.path.join(BASE_DIR, "output_2025")
METADATA_FILE = os.path.join(BASE_DIR, "metadata_2025.json")


def parse_md(filepath: str) -> dict:
    """markdown 파일 파싱 → 메타데이터 dict 반환"""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    filename = os.path.basename(filepath)

    # post_id: 파일명 앞 숫자
    id_match = re.match(r"^(\d+)_", filename)
    post_id  = id_match.group(1) if id_match else ""

    # 제목
    title_match = re.match(r"^# (.+)$", content, re.MULTILINE)
    title       = title_match.group(1).strip() if title_match else ""

    # 메타 테이블에서 작성일 / 조회수 / 원문 URL
    date_match  = re.search(r"\| 작성일 \| ([^|]+) \|", content)
    views_match = re.search(r"\| 조회수 \| ([^|]+) \|", content)
    url_match   = re.search(r"\| 원문 \| \[([^\]]+)\]", content)

    date      = date_match.group(1).strip()  if date_match  else ""
    views_str = views_match.group(1).strip() if views_match else "0"
    url       = url_match.group(1).strip()   if url_match   else ""

    try:
        views = int(views_str.replace(",", ""))
    except ValueError:
        views = 0

    # 날짜 → 정렬용 숫자 (2025.03.01 → 20250301)
    date_num = 0
    if date:
        try:
            date_num = int(re.sub(r"[.\-]", "", date))
        except ValueError:
            pass

    # 본문 추출
    body_match = re.search(r"^## 본문\s*\n\n(.*)", content, re.MULTILINE | re.DOTALL)
    body       = body_match.group(1).strip() if body_match else ""
    char_count = len(body)

    # 섹션 헤딩 목록
    sections = re.findall(r"^#{2,3} (.+)$", content, re.MULTILINE)

    return {
        "post_id":       post_id,
        "title":         title,
        "date":          date,
        "date_num":      date_num,
        "views":         views,
        "url":           url,
        "filename":      filename,
        "char_count":    char_count,
        "sections":      sections,
        "chunk_count":   0,
        "upload_status": "pending",
    }


def compute_stats(posts: list[dict]) -> dict:
    dates = [p["date_num"] for p in posts if p["date_num"] > 0]
    views = [p["views"]    for p in posts if p["views"]    > 0]
    chars = [p["char_count"] for p in posts if p["char_count"] > 0]

    def fmt_date(n: int) -> str:
        s = str(n)
        return f"{s[:4]}.{s[4:6]}.{s[6:]}" if len(s) == 8 else str(n)

    return {
        "total_posts": len(posts),
        "date_range": {
            "from": fmt_date(min(dates)) if dates else "",
            "to":   fmt_date(max(dates)) if dates else "",
        },
        "views": {
            "max": max(views) if views else 0,
            "avg": round(sum(views) / len(views)) if views else 0,
        },
        "content": {
            "total_chars": sum(chars),
            "avg_chars":   round(sum(chars) / len(chars)) if chars else 0,
            "max_chars":   max(chars) if chars else 0,
        },
    }


def main():
    print("=== metadata_2025.json 생성 ===\n")

    if not os.path.isdir(OUTPUT_DIR):
        print(f"[오류] output_2025/ 폴더가 없습니다. crawl_2025.py를 먼저 실행하세요.")
        return

    md_files = sorted(
        f for f in os.listdir(OUTPUT_DIR)
        if f.endswith(".md") and f != "index.md"
    )
    print(f"markdown 파일: {len(md_files)}개\n")

    posts  = []
    errors = []

    for i, filename in enumerate(md_files, 1):
        filepath = os.path.join(OUTPUT_DIR, filename)
        try:
            meta = parse_md(filepath)
            posts.append(meta)
        except Exception as e:
            print(f"  [오류] {filename}: {e}")
            errors.append(filename)

        if i % 50 == 0 or i == len(md_files):
            print(f"  처리: {i}/{len(md_files)}")

    # post_id 내림차순 정렬 (최신 먼저)
    posts.sort(key=lambda x: int(x["post_id"]) if x["post_id"].isdigit() else 0, reverse=True)

    stats = compute_stats(posts)

    metadata = {
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "source": {
            "site": "노동OK BEST Q&A",
            "url":  "https://www.nodong.kr/bestqna",
            "year": "2025",
        },
        "embedding": {
            "model":              "text-embedding-3-small",
            "dimensions":         1536,
            "chunk_max_chars":    700,
            "chunk_overlap_chars": 80,
        },
        "stats": stats,
        "posts": posts,
    }

    with open(METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    print(f"\n저장: {METADATA_FILE}")
    print(f"\n통계:")
    print(f"  총 게시글: {stats['total_posts']}개")
    print(f"  날짜 범위: {stats['date_range']['from']} ~ {stats['date_range']['to']}")
    print(f"  평균 조회수: {stats['views']['avg']:,}  최대: {stats['views']['max']:,}")
    print(f"  평균 본문: {stats['content']['avg_chars']:,}자  총: {stats['content']['total_chars']:,}자")
    if errors:
        print(f"\n오류 ({len(errors)}개): {errors}")


if __name__ == "__main__":
    main()
