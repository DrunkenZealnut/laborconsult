#!/usr/bin/env python3
"""
사례집 파싱 → 개별 사례 마크다운 파일 생성

입력: documents/2022_Regional_Labor_Center_Case_Collection.md
출력: output_legal_cases/case_{NNN}_{title}.md
"""

import re
from pathlib import Path

INPUT_PATH = Path("documents/2022_Regional_Labor_Center_Case_Collection.md")
OUTPUT_DIR = Path("output_legal_cases")

# --- TOC에서 사례번호 → 제목 매핑 추출 ---
TOC_CASE_RE = re.compile(r"사례(\d{1,3})\s+(.+?)(?:\s+\d{1,3}\s*$|\s*\|)", re.MULTILINE)

# --- 챕터 정의 (사례번호 범위 기반) ---
CHAPTERS = [
    (1, 5, "Chapter 01", "일하기 전 알아두기", "채용 취소 / 근로계약 작성하기"),
    (6, 15, "Chapter 02", "일 시작하기", "근로자로 인정받기 / 근로계약"),
    (16, 40, "Chapter 03", "일하는 중", "근로시간 / 휴일 / 휴가 / 교대근무 / 모성보호"),
    (41, 45, "Chapter 03", "일하는 중", "모성보호 제도 및 일·가정 양립 지원"),
    (46, 74, "Chapter 03", "일하는 중", "임금 / 인사명령 / 4대보험"),
    (75, 81, "Chapter 04", "일하다 몸이 다쳤거나 아플 때", "산재 가입 / 보상 / 권리구제"),
    (82, 100, "Chapter 05", "일 그만두기", "실업급여 / 퇴사 / 해고 / 부당해고"),
    (101, 109, "Chapter 06", "직장 내 괴롭힘과 성희롱", "괴롭힘 / 성희롱"),
    (110, 114, "Chapter 07", "플랫폼 노동자 산재", "플랫폼 노동자 산재"),
]


def get_chapter_info(case_num: int) -> tuple[str, str]:
    for start, end, ch, desc, topic in CHAPTERS:
        if start <= case_num <= end:
            return f"{ch} {desc}", topic
    return "기타", "기타"


def parse_toc(lines: list[str]) -> dict[int, str]:
    """목차에서 사례번호 → 제목 매핑 추출"""
    toc_text = "\n".join(lines[:300])
    titles = {}
    for m in TOC_CASE_RE.finditer(toc_text):
        num = int(m.group(1))
        raw = m.group(2).strip()
        raw = raw.strip().lstrip("|").strip()
        raw = re.sub(r"\s*\|.*", "", raw)
        raw = re.sub(r"<[^>]+>", "", raw)
        titles[num] = raw.strip()
    return titles


# --- 다중 패턴 사례 탐지 ---

# 패턴별 우선순위:
# 1) ### N title, ## N title (가장 신뢰)
# 2) #### <sup>...</sup> N title
# 3) <sup>...</sup> N title (heading prefix 없음)
# 4) ### text N title (근로자로 인정받기 6 ...)
# 5) 단독 줄: N title (OCR artifact)
# 6) # text N title (# 관계간 휴일 23 ...)
# 7) text N title (28시간 연장... 20 연장근로...)

HEADER_PATTERNS = [
    # Pattern 1: clean heading + number
    re.compile(r"^#{1,4}\s+(\d{1,3})\s+(.{4,})$"),
    # Pattern 2: heading + <sup>topic</sup> + number
    re.compile(r"^#{1,4}\s+<sup>.*?</sup>\s+(\d{1,3})\s+(.{4,})$"),
    # Pattern 3: <sup>topic</sup> + number (no heading)
    re.compile(r"^<sup>.*?</sup>\s+(\d{1,3})\s+(.{4,})$"),
    # Pattern 4: heading + Korean prefix + number
    re.compile(r"^#{1,4}\s+(?:[\w·가-힣\s<>/]+?)\s+(\d{1,3})\s+(.{4,})$"),
    # Pattern 5: bare number at line start
    re.compile(r"^(\d{1,3})\s+([가-힣].{3,})$"),
    # Pattern 6: # + text + number
    re.compile(r"^#\s+.+?\s+(\d{1,3})\s+(.{4,})$"),
    # Pattern 7: any text + number + Korean title (for garbled OCR)
    re.compile(r"^[\w·가-힣\s]+?\s+(\d{1,3})\s+([가-힣].{4,})$"),
    # Pattern 8: heading with dots/bold markers + number (### ···· **91** title)
    re.compile(r"^#{1,4}\s+[·.\s]+\*\*(\d{1,3})\*\*\s+(.{4,})$"),
]

# 수동 보정: OCR 아티팩트로 자동 탐지 불가능한 사례들
# (줄번호, 사례번호) — 문서 수동 확인 기반
MANUAL_FALLBACKS = {
    9: 680,    # 무역회사 자문의 근로자성
    11: 753,   # 근로계약 미작성 시 대응 방안
    34: 1678,  # 회계연도 연차휴가 문의
    57: 2747,  # 퇴직금 감액처분
    60: 2873,  # 퇴직연금 지연이자 청구
    63: 2993,  # 연차유급휴가 수당 산정 시점
    64: 3023,  # 주중 입사 시 주휴수당 지급여부
    71: 3334,  # 대기발령 중 임금
    78: 3668,  # 산재 종결 후 재요양 절차
    85: 3929,  # 영업양도와 계속 근로기간 문의
    90: 4143,  # 강요에 의한 권고사직
    94: 4283,  # 경영상 이유에 의한 해고
}


def _toc_similarity(title: str, toc_title: str) -> float:
    """TOC 제목과의 간단한 유사도 (0.0~1.0)"""
    if not toc_title or not title:
        return 0.0
    t = title.replace(" ", "")
    tc = toc_title.replace(" ", "")
    if t[:2] == tc[:2]:
        return 0.8
    if tc[:4] in t or t[:4] in tc:
        return 0.6
    # 한글 키워드 겹침
    kw_t = set(re.findall(r"[가-힣]{2,}", t))
    kw_tc = set(re.findall(r"[가-힣]{2,}", tc))
    if kw_t and kw_tc:
        overlap = len(kw_t & kw_tc) / max(len(kw_t | kw_tc), 1)
        return overlap * 0.5
    return 0.0


def find_case_starts(lines: list[str], toc_titles: dict[int, str]) -> list[tuple[int, int, str]]:
    """본문에서 사례 시작 위치 탐지 (다중 패턴 + TOC 기반 번호 교정 + 수동 보정)"""
    cases = []
    seen = set()
    all_expected = set(range(1, 115))

    for i, line in enumerate(lines):
        if i < 300:  # TOC 건너뜀
            continue

        stripped = line.strip()
        if not stripped or len(stripped) < 4:
            continue

        for pat in HEADER_PATTERNS:
            m = pat.match(stripped)
            if not m:
                continue

            num = int(m.group(1))
            title = m.group(2).strip()

            # --- TOC 기반 번호 교정 ---
            # 외부 번호가 유효하더라도 내부 번호가 TOC와 더 잘 맞으면 교체
            # e.g., "### 88 회적금 54 퇴직금을..." → outer=88, inner=54
            inner = re.search(r"(\d{1,3})\s+([가-힣].{3,})", title)
            if inner:
                inner_num = int(inner.group(1))
                if inner_num in all_expected and inner_num not in seen:
                    outer_sim = _toc_similarity(title, toc_titles.get(num, ""))
                    inner_sim = _toc_similarity(inner.group(2), toc_titles.get(inner_num, ""))
                    if inner_sim > outer_sim:
                        num = inner_num
                        title = inner.group(2).strip()

            if num not in all_expected or num in seen:
                # 재시도: 내부 번호 시도
                if inner:
                    inner_num = int(inner.group(1))
                    if inner_num in all_expected and inner_num not in seen:
                        num = inner_num
                        title = inner.group(2).strip()
                    else:
                        continue
                else:
                    continue

            if num in seen:
                continue

            # 패턴 5, 7은 오탐 가능 → TOC 제목과 유사성 검증
            if pat in (HEADER_PATTERNS[4], HEADER_PATTERNS[6]):
                if num in toc_titles:
                    toc_t = toc_titles[num]
                    if _toc_similarity(title, toc_t) < 0.3:
                        continue

            seen.add(num)
            title = re.sub(r"<[^>]+>", "", title)
            title = re.sub(r"!\[.*?\]\(.*?\)", "", title).strip()
            cases.append((i, num, title))
            break  # 첫 번째 매칭 패턴 사용

    # --- 수동 보정 (MANUAL_FALLBACKS) 적용 ---
    for miss_num, fallback_line in MANUAL_FALLBACKS.items():
        if miss_num not in seen and fallback_line < len(lines):
            title = toc_titles.get(miss_num, f"사례 {miss_num}")
            cases.append((fallback_line, miss_num, title))
            seen.add(miss_num)

    cases.sort(key=lambda x: x[0])
    return cases


def fill_missing_cases(
    lines: list[str],
    found_cases: list[tuple[int, int, str]],
    toc_titles: dict[int, str],
) -> list[tuple[int, int, str]]:
    """누락된 사례를 인접 사례 사이에서 탐색하여 추가"""
    found_nums = {c[1] for c in found_cases}
    missing = sorted(set(range(1, 115)) - found_nums)
    if not missing:
        return found_cases

    # 사례번호 → 줄번호 매핑 (정렬된 순서)
    sorted_cases = sorted(found_cases, key=lambda x: x[0])
    num_to_line = {c[1]: c[0] for c in sorted_cases}

    additional = []

    for miss_num in missing:
        title = toc_titles.get(miss_num, f"사례 {miss_num}")

        # 바로 앞/뒤로 발견된 사례 찾기
        prev_line = 300
        next_line = len(lines)
        for cline, cnum, _ in sorted_cases:
            if cnum < miss_num:
                prev_line = max(prev_line, cline)
            elif cnum > miss_num:
                next_line = min(next_line, cline)
                break

        # 검색 범위: 이전 사례 ~ 다음 사례
        search_start = prev_line
        search_end = next_line

        best_line = None

        # 전략 1: TOC 제목의 키워드로 검색
        title_keywords = re.findall(r"[가-힣]{2,}", title)
        if title_keywords:
            kw = title_keywords[0]  # 첫 번째 한글 키워드
            for j in range(search_start, min(search_end, len(lines))):
                ln = lines[j]
                if kw in ln and len(ln.strip()) > 10:
                    # 이 줄 또는 근처에 질문 마커가 있는지 확인
                    nearby = "\n".join(lines[max(0, j - 3):min(len(lines), j + 5)])
                    if re.search(r"질문|[⊘@📀👩👧👲😧]", nearby):
                        best_line = j
                        break

        # 전략 2: 숫자 N이 줄에 단독으로 나오는 경우 (OCR 잔해)
        if best_line is None:
            num_str = str(miss_num)
            for j in range(search_start, min(search_end, len(lines))):
                ln = lines[j].strip()
                # 줄이 숫자로 시작하거나 숫자만 포함
                if ln == num_str or re.match(rf"^{num_str}\s*$", ln):
                    # 근처에 질문 마커가 있는지
                    nearby = "\n".join(lines[max(0, j - 2):min(len(lines), j + 5)])
                    if re.search(r"질문|[⊘@📀👩👧👲😧]", nearby):
                        best_line = j
                        break

        # 전략 3: 페이지 이미지 + 질문 마커 패턴
        if best_line is None:
            for j in range(search_start, min(search_end, len(lines))):
                ln = lines[j].strip()
                if re.match(r"[⊘@📀👩👧👲😧오알]\s*질문", ln) or ln == "질문":
                    # 이 위치가 아직 다른 사례에 할당되지 않았는지 확인
                    conflict = False
                    for cline, _, _ in sorted_cases:
                        if abs(cline - j) < 3:
                            conflict = True
                            break
                    for aline, _, _ in additional:
                        if abs(aline - j) < 3:
                            conflict = True
                            break
                    if not conflict:
                        best_line = j
                        break

        if best_line is not None:
            additional.append((best_line, miss_num, title))

    all_cases = found_cases + additional
    all_cases.sort(key=lambda x: x[0])
    return all_cases


def extract_sections(text: str) -> dict[str, str]:
    """사례 텍스트에서 질문/답변/판례/행정해석 섹션 추출"""
    # 이미지 태그 제거
    clean = re.sub(r"!\[.*?\]\(.*?\)", "", text)
    # HTML 태그 제거
    clean = re.sub(r"<[^>]+>", "", clean)
    # 과도한 빈줄 정리
    clean = re.sub(r"\n{4,}", "\n\n\n", clean)

    sections = {"질문": "", "답변": "", "판례": "", "행정해석": ""}

    # 질문 마커
    q_pattern = re.compile(
        r"(?:[⊘@📀👩👧👲😧오알]\s*질문"
        r"|\(\)\s*질문"
        r"|[#*]+\s*[\w]*\s*[#*]*\s*질문"
        r"|^\)\s*질문"
        r"|^질문$"
        r"|^질문\s*$)",
        re.MULTILINE,
    )

    # 답변 마커 — 이미지 뒤 본문 시작도 포함
    a_pattern = re.compile(
        r"(?:Q\)\s*답변|^-?\s*\)\s*답변|^답변\s*$)", re.MULTILINE
    )

    # 판례 마커
    p_pattern = re.compile(r"(?:^#{0,4}\s*판례\s*$|^판례\s*$)", re.MULTILINE)

    # 행정해석/회시 마커
    h_pattern = re.compile(
        r"(?:^#{0,4}\s*(?:회시|행정\s*해석)\s*$|^행정\s*해석\s+.+)", re.MULTILINE
    )

    # 질문 시작
    q_match = q_pattern.search(clean)
    if q_match:
        q_start = q_match.end()
    else:
        # 마커 없으면 첫 긴 텍스트 줄을 질문으로
        clines = clean.strip().split("\n")
        q_start = 0
        for j, ln in enumerate(clines):
            s = ln.strip()
            if s and not s.startswith("#") and len(s) > 20:
                q_start = sum(len(l) + 1 for l in clines[:j])
                break

    # 답변 시작 (질문 이후)
    a_match = a_pattern.search(clean, q_start)
    if a_match:
        a_start = a_match.end()
        q_end = a_match.start()
    else:
        # 답변 마커 없으면 질문 뒤 문단 구분으로 추정
        remaining = clean[q_start:]
        parts = re.split(r"\n\n\n+", remaining, maxsplit=1)
        if len(parts) >= 2:
            q_end = q_start + len(parts[0])
            a_start = q_end
        else:
            q_end = len(clean)
            a_start = q_end

    # 판례
    p_match = p_pattern.search(clean, a_start if a_start < len(clean) else 0)
    if p_match:
        p_start = p_match.end()
        a_end = p_match.start()
    else:
        p_start = None
        a_end = len(clean)

    # 행정해석/회시
    h_match = h_pattern.search(clean, a_start if a_start < len(clean) else 0)
    if h_match:
        h_start = h_match.end()
        if p_start and h_match.start() > p_start:
            p_end = h_match.start()
        elif not p_start:
            a_end = min(a_end, h_match.start())
            p_end = None
        else:
            p_end = h_match.start()
    else:
        h_start = None
        p_end = len(clean) if p_start else None

    sections["질문"] = _clean(clean[q_start:q_end])
    if a_start < len(clean):
        sections["답변"] = _clean(clean[a_start:a_end])
    if p_start:
        sections["판례"] = _clean(clean[p_start:p_end if p_end else len(clean)])
    if h_start:
        sections["행정해석"] = _clean(clean[h_start:])

    return sections


def _clean(text: str) -> str:
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_legal_refs(text: str) -> list[str]:
    refs = set()
    for m in re.finditer(r"[가-힣]+법\s+제\d+조(?:의\d+)?(?:제\d+항)?", text):
        refs.add(m.group())
    for m in re.finditer(r"(?:대법원?\s*)?\d{4}[다두가나]\d{3,6}", text):
        refs.add(m.group())
    for m in re.finditer(r"\d{4}구합\d{3,6}", text):
        refs.add(m.group())
    for m in re.finditer(r"근기\s*\d{5}-\d+", text):
        refs.add(m.group())
    for m in re.finditer(r"임금근로시간과[-·]?\d+", text):
        refs.add(m.group())
    return sorted(refs)


def sanitize_filename(title: str, max_len: int = 50) -> str:
    s = re.sub(r'[<>:"/\\|?*,·]', "", title)
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"_+", "_", s)
    s = s.strip("_")
    return s[:max_len].rstrip("_") if len(s) > max_len else s


def format_case(case_num: int, title: str, sections: dict, legal_refs: list) -> str:
    chapter, topic = get_chapter_info(case_num)

    md = f"# 사례{case_num} {title}\n\n"
    md += "| 항목 | 내용 |\n| --- | --- |\n"
    md += f"| 사례번호 | {case_num} |\n"
    md += f"| 챕터 | {chapter} |\n"
    md += f"| 주제 | {topic} |\n"
    md += "| 출처 | 2022년 서울시 노동상담사례집 |\n"
    if legal_refs:
        md += f"| 관련법령 | {', '.join(legal_refs[:5])} |\n"
    md += "\n"

    for name in ["질문", "답변", "판례", "행정해석"]:
        content = sections.get(name, "").strip()
        if content:
            md += f"## {name}\n\n{content}\n\n"

    return md


def main():
    if not INPUT_PATH.exists():
        print(f"ERROR: 입력 파일 없음: {INPUT_PATH}")
        return

    text = INPUT_PATH.read_text(encoding="utf-8")
    lines = text.split("\n")
    print(f"입력: {INPUT_PATH} ({len(lines)}줄, {len(text):,}자)")

    # 1) TOC 파싱
    toc_titles = parse_toc(lines)
    print(f"TOC 사례 수: {len(toc_titles)}")

    # 2) 다중 패턴 사례 탐지
    case_starts = find_case_starts(lines, toc_titles)
    found_pass1 = len(case_starts)
    found_nums1 = {c[1] for c in case_starts}
    print(f"1차 탐지: {found_pass1}건")

    # 3) 누락 사례 보완 탐색
    case_starts = fill_missing_cases(lines, case_starts, toc_titles)
    found_pass2 = len(case_starts) - found_pass1
    print(f"2차 보완: +{found_pass2}건")

    found_nums = {c[1] for c in case_starts}
    missing = sorted(set(range(1, 115)) - found_nums)
    print(f"최종 탐지: {len(case_starts)}건, 누락: {len(missing)}건")

    # 4) 파일 생성
    OUTPUT_DIR.mkdir(exist_ok=True)

    # 기존 파일 정리
    for f in OUTPUT_DIR.glob("case_*.md"):
        f.unlink()

    generated = 0
    sorted_cases = sorted(case_starts, key=lambda x: x[0])

    for idx, (line_idx, case_num, raw_title) in enumerate(sorted_cases):
        # 텍스트 범위
        if idx + 1 < len(sorted_cases):
            end_line = sorted_cases[idx + 1][0]
        else:
            end_line = len(lines)

        case_text = "\n".join(lines[line_idx:end_line])
        title = toc_titles.get(case_num, raw_title)
        title = re.sub(r"<[^>]+>", "", title).strip()

        sections = extract_sections(case_text)
        legal_refs = extract_legal_refs(case_text)
        md_content = format_case(case_num, title, sections, legal_refs)

        safe_title = sanitize_filename(title)
        filename = f"case_{case_num:03d}_{safe_title}.md"
        (OUTPUT_DIR / filename).write_text(md_content, encoding="utf-8")
        generated += 1

    print(f"\n출력: {OUTPUT_DIR}/ ({generated}개 파일)")

    if missing:
        print(f"\n미탐지 ({len(missing)}건): {missing}")
        print("  OCR 아티팩트로 헤더가 완전 손상된 사례입니다.")


if __name__ == "__main__":
    main()
