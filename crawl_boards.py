#!/usr/bin/env python3
"""
nodong.kr 게시판 통합 크롤러
- 자료실 (pds), 법원 노동판례 (case), 노동부 행정해석 (interpretation),
  훈령/예규/고시/지침 (instruction)
- 카테고리별 하위 폴더에 markdown 저장
- 재개 가능 (이미 저장된 파일은 건너뜀)
"""

import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md
import time
import os
import re
import json
import argparse

BASE_URL = "https://www.nodong.kr"
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}

# ── 게시판 정의 ────────────────────────────────────────────────────────────────
BOARDS = {
    "pds": {
        "name": "자료실",
        "url_path": "pds",
        "mid": "pds",
    },
    "case": {
        "name": "법원 노동판례",
        "url_path": "case",
        "mid": "case",
    },
    "interpretation": {
        "name": "노동부 행정해석",
        "url_path": "interpretation",
        "mid": "interpretation",
    },
    "instruction": {
        "name": "훈령예규고시지침",
        "url_path": "instruction",
        "mid": "instruction",
    },
}

session = requests.Session()
session.headers.update(HEADERS)


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', '', name)
    name = name.replace('\n', ' ').replace('\r', '').strip()
    return name[:80]


def sanitize_dirname(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', '', name)
    name = name.replace('\n', ' ').replace('\r', '').strip()
    return name[:50] if name else "미분류"


def get_total_pages(board_key: str) -> int:
    """게시판 총 페이지 수 파악"""
    board = BOARDS[board_key]
    url = f"{BASE_URL}/{board['url_path']}"
    try:
        resp = session.get(url, timeout=15)
        soup = BeautifulSoup(resp.text, 'lxml')
        text = soup.get_text()
        # "/ 12 GO" 패턴에서 총 페이지 수 추출
        m = re.search(r'/\s*(\d+)\s*GO', text)
        if m:
            return int(m.group(1))
        # fallback: page= 파라미터에서 최대값
        page_nums = []
        for a in soup.find_all('a', href=True):
            pm = re.search(r'[?&]page=(\d+)', a['href'])
            if pm:
                page_nums.append(int(pm.group(1)))
        return max(page_nums) if page_nums else 1
    except Exception as e:
        print(f"  [오류] 페이지 수 확인 실패: {e}")
        return 1


def get_posts_from_page(board_key: str, page: int) -> list[dict]:
    """목록 페이지에서 게시글 링크 + 카테고리 추출"""
    board = BOARDS[board_key]
    url_path = board['url_path']

    if page == 1:
        url = f"{BASE_URL}/{url_path}"
    else:
        url = f"{BASE_URL}/index.php?mid={board['mid']}&page={page}"

    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [오류] 목록 페이지 {page}: {e}")
        return []

    soup = BeautifulSoup(resp.text, 'lxml')
    posts = []
    seen = set()

    # 테이블 행에서 카테고리와 링크 추출
    for tr in soup.find_all('tr'):
        # 카테고리 추출
        cate_td = tr.find('td', class_='cate')
        category = ""
        if cate_td:
            span = cate_td.find('span')
            category = (span.get_text(strip=True) if span
                        else cate_td.get_text(strip=True))

        # 게시글 링크 추출
        title_td = tr.find('td', class_='title')
        if not title_td:
            # title 클래스 없으면 a 태그에서 직접 탐색
            for a in tr.find_all('a', href=True):
                href = a['href']
                m = re.search(rf'/{url_path}/(\d+)', href)
                if not m:
                    m = re.search(r'document_srl=(\d+)', href)
                if m:
                    doc_id = m.group(1)
                    if doc_id in seen:
                        continue
                    seen.add(doc_id)
                    title = a.get_text(strip=True)
                    if title and len(title) > 2:
                        posts.append({
                            'id': doc_id,
                            'url': f"{BASE_URL}/{url_path}/{doc_id}",
                            'title': title,
                            'category': category,
                        })
                    break
            continue

        # title TD에서 링크 추출
        a_tag = title_td.find('a', href=True)
        if not a_tag:
            continue
        href = a_tag['href']
        m = re.search(rf'/{url_path}/(\d+)', href)
        if not m:
            m = re.search(r'document_srl=(\d+)', href)
        if not m:
            continue
        doc_id = m.group(1)
        if doc_id in seen:
            continue
        seen.add(doc_id)
        title = a_tag.get_text(strip=True)
        if title and len(title) > 2:
            posts.append({
                'id': doc_id,
                'url': f"{BASE_URL}/{url_path}/{doc_id}",
                'title': title,
                'category': category,
            })

    # 테이블 구조에서 못 찾으면 a 태그 전체에서 fallback 탐색
    if not posts:
        for a in soup.find_all('a', href=True):
            href = a['href']
            m = re.search(rf'/{url_path}/(\d+)', href)
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
                    'url': f"{BASE_URL}/{url_path}/{doc_id}",
                    'title': title,
                    'category': "",
                })

    return posts


def extract_post(url: str) -> dict:
    """게시글 상세 내용 추출"""
    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        return {'error': str(e)}

    soup = BeautifulSoup(resp.text, 'lxml')
    result = {'title': '', 'date': '', 'views': '', 'content': '', 'category': ''}

    # ── 카테고리 (상세 페이지에서 추출) ──
    cate_td = soup.select_one('td.cate')
    if cate_td:
        span = cate_td.find('span')
        result['category'] = (span.get_text(strip=True) if span
                              else cate_td.get_text(strip=True))

    # ── 제목 ──
    rd = soup.select_one('.rd')
    if rd:
        title_tag = rd.find(['h1', 'h2'])
        if not title_tag:
            title_tag = rd.find('a', class_='hx')
        if title_tag:
            result['title'] = title_tag.get_text(strip=True)

    if not result['title']:
        for sel in ['h1', 'h2', '.hx', 'title']:
            t = soup.select_one(sel)
            if t:
                result['title'] = t.get_text(strip=True)
                break

    # ── 날짜 / 조회수 ──
    if rd:
        full_rd_text = rd.get_text('\n')
        date_match = re.search(r'(\d{4}[.\-]\d{2}[.\-]\d{2})', full_rd_text)
        if date_match:
            result['date'] = date_match.group(1)
        views_match = re.search(r'조회\s*수\s*(\d[\d,]*)', full_rd_text)
        if views_match:
            result['views'] = views_match.group(1).replace(',', '')

    # ── 추가 메타데이터 (extra_form: 판례번호, 행정해석번호 등) ──
    extra_form = soup.select_one('.extra_form')
    extra_meta = {}
    if extra_form:
        for dl in extra_form.find_all('dl'):
            dt = dl.find('dt')
            dd = dl.find('dd')
            if dt and dd:
                key = dt.get_text(strip=True)
                val = dd.get_text(strip=True)
                if key and val:
                    extra_meta[key] = val

    result['extra_meta'] = extra_meta

    # ── 본문 ──
    content_div = soup.select_one('.xe_content')
    if not content_div:
        content_div = soup.select_one('.rd_body')

    if content_div:
        for tag in content_div.select('.relate_tag, .share_btn, .ad_wrap, script, style'):
            tag.decompose()

        content_html = str(content_div)
        converted = md(
            content_html,
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
    title = data.get('title') or post_meta.get('title', '제목 없음')
    date = data.get('date', '')
    views = data.get('views', '')
    category = data.get('category') or post_meta.get('category', '')
    url = post_meta.get('url', '')
    body = data.get('content', '')
    extra = data.get('extra_meta', {})

    lines = [f"# {title}", ""]
    lines.append("| 항목 | 내용 |")
    lines.append("| --- | --- |")
    if category:
        lines.append(f"| 분류 | {category} |")
    if date:
        lines.append(f"| 작성일 | {date} |")
    if views:
        lines.append(f"| 조회수 | {views} |")
    for k, v in extra.items():
        lines.append(f"| {k} | {v} |")
    lines.append(f"| 원문 | [{url}]({url}) |")
    lines.append("")
    lines.append("---")
    lines.append("")

    if body:
        lines.append(body)

    return "\n".join(lines) + "\n"


def load_progress(progress_path: str) -> set:
    """이미 처리된 게시글 ID 로드"""
    if os.path.exists(progress_path):
        with open(progress_path, 'r') as f:
            return set(json.load(f))
    return set()


def save_progress(progress_path: str, done_ids: set):
    with open(progress_path, 'w') as f:
        json.dump(sorted(done_ids), f)


def crawl_board(board_key: str, force: bool = False):
    board = BOARDS[board_key]
    board_name = board['name']
    output_dir = os.path.join(PROJECT_DIR, f"output_{board_name}")
    progress_path = os.path.join(output_dir, "_progress.json")

    os.makedirs(output_dir, exist_ok=True)

    done_ids = set() if force else load_progress(progress_path)

    print(f"\n{'='*60}")
    print(f"  {board_name} ({board_key}) 크롤링 시작")
    print(f"  이미 수집: {len(done_ids)}건")
    print(f"{'='*60}\n")

    # 1. 총 페이지 수 확인
    total_pages = get_total_pages(board_key)
    print(f"총 페이지 수: {total_pages}\n")

    # 2. 모든 게시글 링크 수집
    all_posts = []
    for page in range(1, total_pages + 1):
        print(f"[페이지 {page}/{total_pages}] 목록 수집...")
        posts = get_posts_from_page(board_key, page)
        print(f"  → {len(posts)}개 발견")
        for p in posts:
            if not any(x['id'] == p['id'] for x in all_posts):
                all_posts.append(p)
        time.sleep(0.5)

    print(f"\n총 {len(all_posts)}개 게시글 (신규: {len(all_posts) - len([p for p in all_posts if p['id'] in done_ids])}개)\n")

    # 3. 게시글 내용 수집 및 저장
    success = 0
    failed = 0
    skipped = 0

    for i, post in enumerate(all_posts, 1):
        if post['id'] in done_ids:
            skipped += 1
            continue

        print(f"[{i}/{len(all_posts)}] {post['title'][:50]}...")
        data = extract_post(post['url'])

        if 'error' in data:
            print(f"  [오류] {data['error']}")
            failed += 1
            time.sleep(1)
            continue

        # 카테고리 결정 (목록에서 가져온 것 우선, 없으면 상세페이지에서)
        category = post.get('category') or data.get('category') or '미분류'
        data['category'] = category

        # 카테고리 폴더 생성
        safe_category = sanitize_dirname(category)
        category_dir = os.path.join(output_dir, safe_category)
        os.makedirs(category_dir, exist_ok=True)

        # 파일 저장
        title_for_file = data.get('title') or post['title']
        safe_title = sanitize_filename(title_for_file)
        filename = f"{post['id']}_{safe_title}.md"

        md_content = build_markdown(post, data)
        filepath = os.path.join(category_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(md_content)

        content_len = len(data.get('content', ''))
        print(f"  → {safe_category}/{filename} ({content_len}자)")

        done_ids.add(post['id'])
        success += 1

        # 중간 저장 (50건마다)
        if success % 50 == 0:
            save_progress(progress_path, done_ids)

        time.sleep(0.7)

    # 최종 진행상황 저장
    save_progress(progress_path, done_ids)

    # 인덱스 파일 생성
    _save_board_index(output_dir, board_name, all_posts, done_ids)

    print(f"\n=== {board_name} 완료 ===")
    print(f"성공: {success} | 건너뜀: {skipped} | 실패: {failed}")
    print(f"저장 위치: {output_dir}\n")

    return success, skipped, failed


def _save_board_index(output_dir: str, board_name: str, all_posts: list, done_ids: set):
    """게시판 인덱스 + 카테고리별 통계 생성"""
    # 카테고리별 분류
    by_category = {}
    for p in all_posts:
        cat = sanitize_dirname(p.get('category') or '미분류')
        by_category.setdefault(cat, []).append(p)

    lines = [
        f"# {board_name} 목록",
        "",
        f"> 총 {len(all_posts)}개 게시글 (수집완료 {len(done_ids)}건)",
        "",
        "## 카테고리별 현황",
        "",
        "| 카테고리 | 건수 |",
        "| --- | --- |",
    ]
    for cat in sorted(by_category.keys()):
        lines.append(f"| {cat} | {len(by_category[cat])} |")

    lines.extend(["", "---", ""])

    for cat in sorted(by_category.keys()):
        lines.append(f"## {cat}")
        lines.append("")
        for p in by_category[cat]:
            status = "✅" if p['id'] in done_ids else "❌"
            lines.append(f"- {status} [{p['title']}](./{cat}/{p['id']}_{sanitize_filename(p['title'])}.md)")
        lines.append("")

    index_path = os.path.join(output_dir, "_index.md")
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines) + "\n")
    print(f"인덱스 저장: {index_path}")


def main():
    parser = argparse.ArgumentParser(description="nodong.kr 게시판 통합 크롤러")
    parser.add_argument(
        "--board",
        choices=list(BOARDS.keys()) + ["all"],
        default="all",
        help="크롤링할 게시판 (기본: all)",
    )
    parser.add_argument("--force", action="store_true", help="이미 수집된 게시글도 다시 수집")
    args = parser.parse_args()

    print("=== nodong.kr 게시판 통합 크롤러 ===\n")

    boards_to_crawl = list(BOARDS.keys()) if args.board == "all" else [args.board]

    total_stats = {"success": 0, "skipped": 0, "failed": 0}
    for bk in boards_to_crawl:
        s, sk, f = crawl_board(bk, force=args.force)
        total_stats["success"] += s
        total_stats["skipped"] += sk
        total_stats["failed"] += f

    print("=" * 60)
    print(f"전체 결과: 성공 {total_stats['success']} | 건너뜀 {total_stats['skipped']} | 실패 {total_stats['failed']}")
    print("=" * 60)


if __name__ == '__main__':
    main()
