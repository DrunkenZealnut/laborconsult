#!/usr/bin/env python3
"""
nodong.kr BEST Q&A 게시판 크롤러 v2
- lxml 파서: <hr> 등 void element 올바르게 처리
- markdownify: 표/인라인 포맷 완전 변환
"""

import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md
import time
import os
import re
from pathlib import Path

BASE_URL = "https://www.nodong.kr"
LIST_URL = "https://www.nodong.kr/bestqna"
OUTPUT_DIR = str(Path(__file__).parent / "output")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}

session = requests.Session()
session.headers.update(HEADERS)


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', '', name)
    name = name.replace('\n', ' ').replace('\r', '').strip()
    return name[:80]


def get_total_pages() -> int:
    try:
        resp = session.get(LIST_URL, timeout=10)
        soup = BeautifulSoup(resp.text, 'lxml')
        text = soup.get_text()
        m = re.search(r'/\s*(\d+)\s*GO', text)
        if m:
            return int(m.group(1))
        page_nums = [int(m.group(1)) for a in soup.find_all('a', href=True)
                     for m in [re.search(r'[?&]page=(\d+)', a['href'])] if m]
        return max(page_nums) if page_nums else 7
    except Exception as e:
        print(f"  [오류] 페이지 수 확인 실패: {e}")
        return 7


def get_post_links_from_page(page: int) -> list[dict]:
    url = f"{LIST_URL}?page={page}"
    try:
        resp = session.get(url, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [오류] 목록 페이지 {page}: {e}")
        return []

    soup = BeautifulSoup(resp.text, 'lxml')
    posts = []
    seen = set()

    for a in soup.find_all('a', href=True):
        href = a['href']
        m = re.search(r'/bestqna/(\d+)', href) or re.search(r'document_srl=(\d+)', href)
        if not m:
            continue
        doc_id = m.group(1)
        if doc_id in seen:
            continue
        seen.add(doc_id)
        title = a.get_text(strip=True)
        if title and len(title) > 2:
            posts.append({'id': doc_id, 'url': f"{BASE_URL}/bestqna/{doc_id}", 'title': title})

    return posts


def extract_post(url: str) -> dict:
    """게시글 전체 내용 추출"""
    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        return {'error': str(e)}

    # lxml 파서: <hr> 등 void element 올바르게 처리
    soup = BeautifulSoup(resp.text, 'lxml')

    result = {'title': '', 'date': '', 'views': '', 'content': ''}

    # ── 제목 ──────────────────────────────────────────────────
    # .rd 영역의 첫 번째 주요 텍스트 또는 h1/h2
    rd = soup.select_one('.rd')
    if rd:
        title_tag = rd.find(['h1', 'h2'])
        if not title_tag:
            # .rd 내 가장 앞의 a 태그
            title_tag = rd.find('a', class_='hx')
        if title_tag:
            result['title'] = title_tag.get_text(strip=True)

    if not result['title']:
        for sel in ['h1', 'h2', '.hx', 'title']:
            t = soup.select_one(sel)
            if t:
                result['title'] = t.get_text(strip=True)
                break

    # ── 날짜 / 조회수 ──────────────────────────────────────────
    # .rd 안의 span/li 중 날짜·조회수 패턴
    if rd:
        full_rd_text = rd.get_text('\n')
        # 날짜: YYYY.MM.DD 또는 YYYY-MM-DD (게시글 등록일)
        # 페이지 본문 외 영역에서 나오는 "오늘 날짜"를 피하기 위해
        # rd 영역에서만 탐색
        date_match = re.search(r'(\d{4}[.\-]\d{2}[.\-]\d{2})', full_rd_text)
        if date_match:
            result['date'] = date_match.group(1)

        views_match = re.search(r'조회\s*수\s*(\d[\d,]*)', full_rd_text)
        if views_match:
            result['views'] = views_match.group(1).replace(',', '')

    # ── 본문 ──────────────────────────────────────────────────
    content_div = soup.select_one('.xe_content')
    if not content_div:
        content_div = soup.select_one('.rd_body')

    if content_div:
        # 불필요 태그 제거 (광고, 연관검색어, 공유버튼 등)
        for tag in content_div.select('.relate_tag, .share_btn, .ad_wrap, script, style'):
            tag.decompose()

        content_html = str(content_div)
        # markdownify 변환 옵션
        converted = md(
            content_html,
            heading_style='ATX',        # ## 형식 헤딩
            bullets='-',                # 목록 기호
            strip=['script', 'style'],  # 제거 태그
            newline_style='backslash',  # <br> → \ 줄바꿈
            table_infer_header=True,    # 표 헤더 자동 인식
            escape_misc=False,          # * 등 불필요한 이스케이프 방지
        )

        # 정리: 연속 빈 줄 최대 2줄, 앞뒤 공백 제거
        converted = re.sub(r'\n{3,}', '\n\n', converted).strip()
        result['content'] = converted

    return result


def build_markdown(post_meta: dict, data: dict) -> str:
    title = data.get('title') or post_meta.get('title', '제목 없음')
    date = data.get('date', '')
    views = data.get('views', '')
    url = post_meta.get('url', '')
    body = data.get('content', '')

    lines = [f"# {title}", ""]
    lines.append("| 항목 | 내용 |")
    lines.append("| --- | --- |")
    if date:
        lines.append(f"| 작성일 | {date} |")
    if views:
        lines.append(f"| 조회수 | {views} |")
    lines.append(f"| 원문 | [{url}]({url}) |")
    lines.append("")
    lines.append("---")
    lines.append("")

    if body:
        lines.append("## 본문")
        lines.append("")
        lines.append(body)

    return "\n".join(lines) + "\n"


def save_index(posts_info: list[dict]):
    md_lines = [
        "# 노동OK BEST Q&A 게시글 목록",
        "",
        f"> 총 {len(posts_info)}개 게시글",
        "",
        "---",
        "",
    ]
    for i, p in enumerate(posts_info, 1):
        filename = p.get('filename', '')
        title = p.get('title', '제목 없음')
        date = p.get('date', '')
        views = p.get('views', '')
        meta = f" ({date})" if date else ""
        if filename:
            md_lines.append(f"{i}. [{title}](./{filename}){meta}")
        else:
            md_lines.append(f"{i}. {title} _(수집 실패)_")

    index_path = os.path.join(OUTPUT_DIR, "index.md")
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(md_lines) + "\n")
    print(f"\n인덱스 저장: {index_path}")


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 기존 파일 초기화
    for f in os.listdir(OUTPUT_DIR):
        if f.endswith('.md'):
            os.remove(os.path.join(OUTPUT_DIR, f))

    print("=== 노동OK BEST Q&A 크롤러 v2 시작 ===\n")

    total_pages = get_total_pages()
    print(f"총 페이지 수: {total_pages}\n")

    # 게시글 링크 수집
    all_posts = []
    for page in range(1, total_pages + 1):
        print(f"[페이지 {page}/{total_pages}] 목록 수집...")
        posts = get_post_links_from_page(page)
        print(f"  → {len(posts)}개 발견")
        for p in posts:
            if not any(x['id'] == p['id'] for x in all_posts):
                all_posts.append(p)
        time.sleep(0.4)

    print(f"\n총 {len(all_posts)}개 게시글\n")
    print("=== 내용 수집 시작 ===\n")

    posts_info = []
    failed = []

    for i, post in enumerate(all_posts, 1):
        print(f"[{i}/{len(all_posts)}] {post['title'][:50]}...")
        data = extract_post(post['url'])

        if 'error' in data:
            print(f"  [오류] {data['error']}")
            failed.append(post)
            posts_info.append({'id': post['id'], 'title': post['title'],
                               'filename': '', 'date': '', 'views': ''})
            time.sleep(1)
            continue

        title_for_file = data.get('title') or post['title']
        safe_title = sanitize_filename(title_for_file)
        filename = f"{post['id']}_{safe_title}.md"

        md_content = build_markdown(post, data)
        with open(os.path.join(OUTPUT_DIR, filename), 'w', encoding='utf-8') as f:
            f.write(md_content)

        content_len = len(data.get('content', ''))
        print(f"  → {filename} ({content_len}자)")
        posts_info.append({
            'id': post['id'],
            'title': title_for_file,
            'filename': filename,
            'date': data.get('date', ''),
            'views': data.get('views', ''),
        })

        time.sleep(0.7)

    save_index(posts_info)

    print(f"\n=== 완료 ===")
    print(f"성공: {len(posts_info) - len(failed)}개 / 실패: {len(failed)}개")
    if failed:
        print("실패 목록:")
        for p in failed:
            print(f"  - {p['title']} ({p['url']})")
    print(f"저장 위치: {OUTPUT_DIR}")


if __name__ == '__main__':
    main()
