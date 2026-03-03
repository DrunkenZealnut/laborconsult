#!/usr/bin/env python3
"""
nodong.kr Q&A 게시판 크롤러
- 최근 10,000개 질문 수집 (최대 500페이지 × 20개)
- lxml 파서: <hr> 등 void element 올바르게 처리
- markdownify: 표/인라인 포맷 완전 변환
- 재개 가능: 이미 저장된 파일 건너뜀
- 답변, 프로필 메타, 태그, 카테고리 포함 추출
"""

import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md
import time
import os
import re
import random

BASE_URL = "https://www.nodong.kr"
LIST_URL = "https://www.nodong.kr/qna"
OUTPUT_DIR = "/Users/zealnutkim/Documents/개발/nodongokboardcrawl/output_qna"
MAX_PAGES = 500

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


def get_saved_ids(output_dir: str) -> set:
    """이미 저장된 게시글 ID 목록"""
    saved = set()
    if not os.path.exists(output_dir):
        return saved
    for fname in os.listdir(output_dir):
        if fname.endswith('.md') and fname != 'index.md':
            m = re.match(r'^(\d+)_', fname)
            if m:
                saved.add(m.group(1))
    return saved


def get_post_links_from_page(page: int) -> list[dict]:
    url = f"{LIST_URL}?page={page}"
    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [오류] 목록 페이지 {page}: {e}")
        return []

    soup = BeautifulSoup(resp.text, 'lxml')
    posts = []
    seen = set()

    for a in soup.find_all('a', href=True):
        href = a['href']
        # /qna/숫자 패턴
        m = re.search(r'/qna/(\d+)', href)
        if not m:
            m = re.search(r'document_srl=(\d+)', href)
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
                'url': f"{BASE_URL}/qna/{doc_id}",
                'title': title,
            })

    return posts


def extract_category(soup: BeautifulSoup) -> str:
    """카테고리 추출"""
    for sel in ['.category', '.cate', '.board_category', '.qna_cate', 'span.cate', '.sc']:
        cat = soup.select_one(sel)
        if cat:
            text = cat.get_text(strip=True)
            if text and len(text) < 30:
                return text

    # rd 영역에서 카테고리 탐색
    rd = soup.select_one('.rd')
    if rd:
        text = rd.get_text('\n')
        m = re.search(r'카테고리\s*[:：]?\s*([^\n|,]{1,30})', text)
        if m:
            return m.group(1).strip()

    return ''


def extract_tags(soup: BeautifulSoup) -> list[str]:
    """태그 추출"""
    tags = []

    for sel in ['.tag_list', '.tags', '.keyword', '.hash_tag', '.tag', '.keyword_list']:
        tag_area = soup.select_one(sel)
        if tag_area:
            for a in tag_area.find_all('a'):
                t = a.get_text(strip=True).lstrip('#')
                if t and len(t) > 1:
                    tags.append(t)
            if tags:
                return tags

    # 본문에서 #keyword 패턴 탐색 (최대 10개)
    text = soup.get_text()
    found = re.findall(r'#([가-힣a-zA-Z0-9_]{2,15})', text)
    tags = list(dict.fromkeys(found))[:10]
    return tags


def extract_profile(soup: BeautifulSoup) -> dict:
    """작성자 프로필 정보 추출"""
    profile = {}

    # 프로필 전용 영역 탐색
    profile_area = (
        soup.select_one('.profile_info') or
        soup.select_one('.user_profile') or
        soup.select_one('.writer_info') or
        soup.select_one('.qna_profile') or
        soup.select_one('.member_info') or
        soup.select_one('.user_info')
    )

    text = profile_area.get_text('\n') if profile_area else soup.get_text('\n')

    patterns = {
        '성별':       r'성별\s*[:：]?\s*([남여][^\n\|,]{0,10})',
        '지역':       r'지역\s*[:：]?\s*([^\n\|,]{1,15})',
        '사업체_형태': r'사업체\s*형태\s*[:：]?\s*([^\n\|,]{1,20})',
        '사업체_규모': r'사업체\s*규모\s*[:：]?\s*([^\n\|,]{1,20})',
        '직위':       r'직위\s*[:：]?\s*([^\n\|,]{1,20})',
    }

    for key, pattern in patterns.items():
        m = re.search(pattern, text)
        if m:
            profile[key] = m.group(1).strip()

    return profile


def extract_answers(soup: BeautifulSoup) -> list[str]:
    """답변(댓글) 추출 - markdownify 변환"""
    answers = []

    # 댓글 목록 컨테이너 탐색
    comment_containers = (
        soup.select('.fdb_lst_wrp .fdb_lst_ul > li') or
        soup.select('.fdb_lst_wrp > ul > li') or
        soup.select('.comment_list > li') or
        soup.select('.comments > li') or
        soup.select('.fdb_itm')
    )

    for container in comment_containers:
        body = (
            container.select_one('.xe_content') or
            container.select_one('.comment_content') or
            container.select_one('.bd_tit_font') or
            container.select_one('.fdb_txt') or
            container.select_one('.rd_body')
        )
        if body:
            for tag in body.select('script, style, .ad_wrap, .share_btn'):
                tag.decompose()
            converted = md(
                str(body),
                heading_style='ATX',
                bullets='-',
                strip=['script', 'style'],
                newline_style='backslash',
                escape_misc=False,
            )
            converted = re.sub(r'\n{3,}', '\n\n', converted).strip()
            if converted and len(converted) > 5:
                answers.append(converted)

    # 컨테이너가 없으면 전체 답변 영역을 통째로 변환
    if not answers:
        answer_area = soup.select_one('.fdb_lst_wrp') or soup.select_one('.comments')
        if answer_area:
            for tag in answer_area.select('script, style, .ad_wrap, .share_btn'):
                tag.decompose()
            converted = md(
                str(answer_area),
                heading_style='ATX',
                bullets='-',
                strip=['script', 'style'],
                escape_misc=False,
            )
            converted = re.sub(r'\n{3,}', '\n\n', converted).strip()
            if converted:
                answers = [converted]

    return answers


def extract_post(url: str) -> dict:
    """게시글 전체 내용 추출"""
    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        return {'error': str(e)}

    soup = BeautifulSoup(resp.text, 'lxml')

    result = {
        'title': '', 'date': '', 'views': '', 'category': '',
        'tags': [], 'profile': {}, 'content': '', 'answers': [],
    }

    # ── 제목 ──────────────────────────────────────────────────
    rd = soup.select_one('.rd')
    if rd:
        title_tag = rd.find(['h1', 'h2'])
        if not title_tag:
            title_tag = rd.find('a', class_='hx')
        if title_tag:
            result['title'] = title_tag.get_text(strip=True)

    if not result['title']:
        for sel in ['h1', 'h2', '.hx', '.title']:
            t = soup.select_one(sel)
            if t:
                result['title'] = t.get_text(strip=True)
                break

    # ── 날짜 / 조회수 ──────────────────────────────────────────
    if rd:
        full_rd_text = rd.get_text('\n')
        date_match = re.search(r'(\d{4}[.\-]\d{2}[.\-]\d{2})', full_rd_text)
        if date_match:
            result['date'] = date_match.group(1)
        views_match = re.search(r'조회\s*수\s*(\d[\d,]*)', full_rd_text)
        if views_match:
            result['views'] = views_match.group(1).replace(',', '')

    # ── 카테고리 / 태그 / 프로필 ───────────────────────────────
    result['category'] = extract_category(soup)
    result['tags'] = extract_tags(soup)
    result['profile'] = extract_profile(soup)

    # ── 본문 ──────────────────────────────────────────────────
    content_div = (
        soup.select_one('.bd_viewer_font') or
        soup.select_one('.xe_content') or
        soup.select_one('.rd_body')
    )

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
        result['content'] = re.sub(r'\n{3,}', '\n\n', converted).strip()

    # ── 답변 ──────────────────────────────────────────────────
    result['answers'] = extract_answers(soup)

    return result


def build_markdown(post_meta: dict, data: dict) -> str:
    title = data.get('title') or post_meta.get('title', '제목 없음')
    date = data.get('date', '')
    views = data.get('views', '')
    category = data.get('category', '')
    tags = data.get('tags', [])
    profile = data.get('profile', {})
    url = post_meta.get('url', '')
    body = data.get('content', '')
    answers = data.get('answers', [])

    lines = [f"# {title}", ""]

    lines += ["| 항목 | 내용 |", "| --- | --- |"]
    if category:
        lines.append(f"| 카테고리 | {category} |")
    if date:
        lines.append(f"| 작성일 | {date} |")
    if views:
        lines.append(f"| 조회수 | {views} |")
    if tags:
        lines.append(f"| 태그 | {' '.join('#' + t for t in tags)} |")
    lines.append(f"| 원문 | [{url}]({url}) |")
    lines.append("")

    # 작성자 프로필
    if profile:
        lines += ["### 작성자 정보", "", "| 항목 | 내용 |", "| --- | --- |"]
        field_map = {
            '성별': '성별', '지역': '지역',
            '사업체_형태': '사업체 형태', '사업체_규모': '사업체 규모', '직위': '직위',
        }
        for key, label in field_map.items():
            if key in profile:
                lines.append(f"| {label} | {profile[key]} |")
        lines.append("")

    lines += ["---", ""]

    if body:
        lines += ["## 질문", "", body, ""]

    if answers:
        lines += ["## 답변", ""]
        for i, ans in enumerate(answers, 1):
            if len(answers) > 1:
                lines += [f"### 답변 {i}", ""]
            lines += [ans, ""]

    return "\n".join(lines) + "\n"


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("=== 노동OK Q&A 크롤러 시작 ===\n")
    print(f"목표: 최대 {MAX_PAGES}페이지 × 20개 = 최대 10,000개\n")

    # 이미 저장된 파일 확인 (재개 기능)
    saved_ids = get_saved_ids(OUTPUT_DIR)
    if saved_ids:
        print(f"이미 저장된 게시글: {len(saved_ids)}개 (건너뜀)\n")

    # 게시글 링크 수집
    all_posts = []
    seen_ids = set()

    for page in range(1, MAX_PAGES + 1):
        print(f"[페이지 {page}/{MAX_PAGES}] 목록 수집...", end=' ', flush=True)
        posts = get_post_links_from_page(page)

        new_posts = []
        for p in posts:
            if p['id'] not in seen_ids:
                seen_ids.add(p['id'])
                new_posts.append(p)

        all_posts.extend(new_posts)
        print(f"{len(new_posts)}개 → 누적 {len(all_posts)}개")

        time.sleep(random.uniform(0.4, 0.7))

    print(f"\n총 {len(all_posts)}개 게시글 발견\n")
    print("=== 내용 수집 시작 ===\n")

    posts_info = []
    failed = []
    skip_count = 0

    for i, post in enumerate(all_posts, 1):
        # 이미 저장된 게시글 건너뜀
        if post['id'] in saved_ids:
            skip_count += 1
            continue

        print(f"[{i}/{len(all_posts)}] {post['title'][:50]}...")
        data = extract_post(post['url'])

        if 'error' in data:
            print(f"  [오류] {data['error']}")
            failed.append(post)
            posts_info.append({
                'id': post['id'], 'title': post['title'],
                'filename': '', 'date': '', 'views': '',
            })
            time.sleep(2)
            continue

        title_for_file = data.get('title') or post['title']
        safe_title = sanitize_filename(title_for_file)
        filename = f"{post['id']}_{safe_title}.md"

        md_content = build_markdown(post, data)
        with open(os.path.join(OUTPUT_DIR, filename), 'w', encoding='utf-8') as f:
            f.write(md_content)

        content_len = len(data.get('content', ''))
        ans_count = len(data.get('answers', []))
        print(f"  → {filename} (본문 {content_len}자, 답변 {ans_count}개)")

        posts_info.append({
            'id': post['id'],
            'title': title_for_file,
            'filename': filename,
            'date': data.get('date', ''),
            'views': data.get('views', ''),
        })

        time.sleep(random.uniform(0.4, 0.7))

    print(f"\n=== 완료 ===")
    collected = len(all_posts) - skip_count - len(failed)
    print(f"신규 수집: {collected}개")
    print(f"건너뜀(기존): {skip_count}개")
    print(f"실패: {len(failed)}개")
    if failed:
        print("실패 목록 (최대 20개):")
        for p in failed[:20]:
            print(f"  - {p['title']} ({p['url']})")
    print(f"저장 위치: {OUTPUT_DIR}")


if __name__ == '__main__':
    main()
