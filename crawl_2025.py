#!/usr/bin/env python3
"""
노동OK BEST Q&A 2025년 게시글 크롤러
- 2025년 게시글만 output_2025/ 폴더에 저장
- 리스트 페이지에서 날짜 추출 시도 → 불명확한 경우에만 개별 페이지 방문
- 한 페이지에서 2025년 이전 게시글만 발견되면 조기 종료
"""

import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md
import time
import os
import re

BASE_URL   = "https://www.nodong.kr"
LIST_URL   = "https://www.nodong.kr/bestqna"
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output_2025")
TARGET_YEAR = "2025"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
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


def parse_date_from_text(text: str) -> str:
    """텍스트에서 YYYY.MM.DD 또는 YYYY-MM-DD 형식 날짜 추출"""
    m = re.search(r'(\d{4})[.\-](\d{2})[.\-](\d{2})', text)
    if m:
        return f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
    return ""


def get_post_links_from_page(page: int) -> list[dict]:
    """
    목록 페이지에서 게시글 링크 + 가능하면 날짜도 수집.
    날짜 year 판별:
      - "2025" → include
      - 다른 연도  → exclude (리스트에서 확인 가능한 경우)
      - 날짜 미확인 → fetch_needed=True (개별 페이지 방문 필요)
    """
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

    # XpressEngine 게시판: 보통 <tr> 또는 <li> 단위로 게시글 구성
    # 각 행에서 링크 + 날짜 같이 파싱 시도
    rows = soup.select('tr, li.item, li.bd_item, .list_item')

    if rows:
        for row in rows:
            # 링크 찾기
            for a in row.find_all('a', href=True):
                href = a['href']
                m = re.search(r'/bestqna/(\d+)', href) or re.search(r'document_srl=(\d+)', href)
                if not m:
                    continue
                doc_id = m.group(1)
                if doc_id in seen:
                    continue
                seen.add(doc_id)

                title = a.get_text(strip=True)
                if not title or len(title) <= 2:
                    continue

                # 같은 행에서 날짜 찾기
                row_text = row.get_text('\n')
                date_in_row = parse_date_from_text(row_text)
                year = date_in_row[:4] if date_in_row else ""

                posts.append({
                    'id': doc_id,
                    'url': f"{BASE_URL}/bestqna/{doc_id}",
                    'title': title,
                    'list_date': date_in_row,
                    'list_year': year,
                })
    else:
        # fallback: 모든 a 태그 스캔 (날짜 불명)
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
                posts.append({
                    'id': doc_id,
                    'url': f"{BASE_URL}/bestqna/{doc_id}",
                    'title': title,
                    'list_date': '',
                    'list_year': '',
                })

    return posts


def should_stop_pagination(posts: list[dict]) -> bool:
    """
    페이지에서 가져온 게시글들이 모두 2025년 이전이면 True (조기 종료).
    날짜가 확인된 항목들 중 2024 이하만 있으면 종료.
    """
    dated = [p for p in posts if p['list_year']]
    if not dated:
        return False  # 날짜 불명 → 계속 진행
    all_before_2025 = all(p['list_year'] < TARGET_YEAR for p in dated)
    return all_before_2025


def extract_post(url: str) -> dict:
    """게시글 개별 페이지에서 제목·날짜·본문 추출"""
    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        return {'error': str(e)}

    soup = BeautifulSoup(resp.text, 'lxml')
    result = {'title': '', 'date': '', 'views': '', 'content': ''}

    # 제목
    rd = soup.select_one('.rd')
    if rd:
        title_tag = rd.find(['h1', 'h2']) or rd.find('a', class_='hx')
        if title_tag:
            result['title'] = title_tag.get_text(strip=True)
    if not result['title']:
        for sel in ['h1', 'h2', '.hx', 'title']:
            t = soup.select_one(sel)
            if t:
                result['title'] = t.get_text(strip=True)
                break

    # 날짜 / 조회수
    if rd:
        full_rd_text = rd.get_text('\n')
        date_match = re.search(r'(\d{4}[.\-]\d{2}[.\-]\d{2})', full_rd_text)
        if date_match:
            result['date'] = date_match.group(1)
        views_match = re.search(r'조회\s*수\s*(\d[\d,]*)', full_rd_text)
        if views_match:
            result['views'] = views_match.group(1).replace(',', '')

    # 본문
    content_div = soup.select_one('.xe_content') or soup.select_one('.rd_body')
    if content_div:
        for tag in content_div.select('.relate_tag, .share_btn, .ad_wrap, script, style'):
            tag.decompose()
        converted = md(
            str(content_div),
            heading_style='ATX',
            bullets='-',
            strip=['script', 'style'],
            newline_style='backslash',
            table_infer_header=True,
            escape_misc=False,
        )
        converted = re.sub(r'\n{3,}', '\n\n', converted).strip()
        result['content'] = converted

    return result


def build_markdown(post_meta: dict, data: dict) -> str:
    title  = data.get('title') or post_meta.get('title', '제목 없음')
    date   = data.get('date', '')
    views  = data.get('views', '')
    url    = post_meta.get('url', '')
    body   = data.get('content', '')

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
        "# 노동OK BEST Q&A 2025년 게시글 목록",
        "",
        f"> 총 {len(posts_info)}개 게시글 (2025년)",
        "",
        "---",
        "",
    ]
    for i, p in enumerate(posts_info, 1):
        filename = p.get('filename', '')
        title    = p.get('title', '제목 없음')
        date     = p.get('date', '')
        meta     = f" ({date})" if date else ""
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

    print(f"=== 노동OK BEST Q&A {TARGET_YEAR}년 크롤러 시작 ===\n")

    total_pages = get_total_pages()
    print(f"총 페이지 수: {total_pages}\n")

    # 1단계: 각 페이지에서 게시글 링크 수집 (날짜 포함 시도)
    candidates = []    # 2025년 확실하거나 날짜 미확인 게시글
    seen_ids   = set()

    for page in range(1, total_pages + 1):
        print(f"[페이지 {page}/{total_pages}] 목록 수집...")
        posts = get_post_links_from_page(page)
        print(f"  → {len(posts)}개 발견")

        new_added = 0
        for p in posts:
            if p['id'] in seen_ids:
                continue
            seen_ids.add(p['id'])

            year = p['list_year']
            if year == TARGET_YEAR:
                candidates.append(p)
                new_added += 1
            elif year == '':
                # 날짜 미확인 → 일단 후보로 넣고 개별 페이지에서 확인
                candidates.append(p)
                new_added += 1
            # else: 다른 연도 → 스킵

        print(f"  → 2025 후보 누적: {len(candidates)}개")

        # 조기 종료: 확인된 날짜가 있는 게시글이 모두 2025 이전이면 종료
        if should_stop_pagination(posts):
            print(f"  → 페이지 {page}에서 2025 이전 게시글만 발견 → 크롤링 종료\n")
            break

        time.sleep(0.4)

    print(f"\n2025년 후보: {len(candidates)}개\n")
    print("=== 개별 게시글 수집 시작 ===\n")

    # 2단계: 후보 게시글 방문 → 날짜 확인 후 2025년만 저장
    posts_info = []
    failed     = []

    for i, post in enumerate(candidates, 1):
        print(f"[{i}/{len(candidates)}] {post['title'][:50]}...")
        data = extract_post(post['url'])

        if 'error' in data:
            print(f"  [오류] {data['error']}")
            failed.append(post)
            time.sleep(1)
            continue

        # 날짜 확인
        date = data.get('date', '')
        if not date.startswith(TARGET_YEAR):
            if date:
                print(f"  → {date} 게시글 스킵")
            else:
                print(f"  → 날짜 미확인 스킵")
            continue

        # 2025년 게시글 저장
        title_for_file = data.get('title') or post['title']
        safe_title     = sanitize_filename(title_for_file)
        filename       = f"{post['id']}_{safe_title}.md"
        md_content     = build_markdown(post, data)

        with open(os.path.join(OUTPUT_DIR, filename), 'w', encoding='utf-8') as f:
            f.write(md_content)

        content_len = len(data.get('content', ''))
        print(f"  → {filename} ({content_len}자) [{date}]")

        posts_info.append({
            'id':       post['id'],
            'title':    title_for_file,
            'filename': filename,
            'date':     date,
            'views':    data.get('views', ''),
        })

        time.sleep(0.7)

    save_index(posts_info)

    print(f"\n=== 완료 ===")
    print(f"2025년 게시글 저장: {len(posts_info)}개")
    print(f"실패: {len(failed)}개")
    if failed:
        print("실패 목록:")
        for p in failed:
            print(f"  - {p['title']} ({p['url']})")
    print(f"저장 위치: {OUTPUT_DIR}")


if __name__ == '__main__':
    main()
