#!/usr/bin/env python3
"""노동법 해설서 marker 변환본을 Pinecone laborlaw-v2 네임스페이스에 업로드.

대상 서적은 BOOKS 레지스트리로 관리한다(현재 4권 — Win 노동법, 근로기준법 주해 Ⅲ,
개별 노동법실무, 이론판례 노동법). 각 서적의 마크다운을 헤더 단위로 분할 → 청킹 →
임베딩 → 업로드한다. 4권 체제의 저작권 영향은 없음 — G4-T 총량 상한 6은 서적 수와
무관하게 고정이고, 권당 상한의 실효 천장은 rerank_top_n에 막혀 4권에서 포화한다
(CLAUDE.md G4-T 절의 시나리오 표).
원본 스캔이 여러 파일로 쪼개진 서적은 Book.extra_parts로 조각을 이어붙인다.
crawl/metadata 단계 없이 upload 스크립트 하나로 처리하는 점은
pinecone_upload_counsel.py와 동일한 관례를 따름.

저작권 경계 — 본문은 비공개 검색 백엔드에만 적재되고 다음 가드가 함께 적용된다
(설계 §4):
  · G1~G3  답변의 축자 인용 금지·단독 근거 금지·서명 표기  (app/templates/prompts.py)
  · G4     동일 서적 청크 상한 3                            (app/core/rag.py::_cap_by_book)
  · G5     출처 라벨 "노동법 해설서"                         (rag.py + public/index.html)
가드 없이 이 스크립트만 실행하면 설계 전제가 깨진다.

사용법:
  python3 pinecone_upload_textbook.py --book juhae3 --dry-run   # 청킹만
  python3 pinecone_upload_textbook.py --book juhae3             # 1권 업로드
  python3 pinecone_upload_textbook.py --all                     # 전권 업로드
"""

from __future__ import annotations

import os
import re
import sys
import json
import time
import argparse
import unicodedata
from dataclasses import dataclass, field

from dotenv import load_dotenv
from openai import OpenAI
from pinecone import Pinecone

from vector_ledger import VectorLedger

load_dotenv()

# ── 설정 ──────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CORPUS_DIR = os.path.join(BASE_DIR, "output_노동법교재")

EMBED_MODEL = "text-embedding-3-small"
CHUNK_MAX = 700
CHUNK_OVERLAP = 80
EMBED_BATCH = 50
UPSERT_BATCH = 100
NAMESPACE = "laborlaw-v2"
SOURCE_TYPE = "textbook"

# 업로드한 벡터 ID 보존 경로. Pinecone Serverless는 메타데이터 필터 삭제를
# 지원하지 않으므로, 이 목록이 서적 단위 롤백의 유일한 수단이다(설계 §9).
UPLOADED_IDS_FILE = os.path.join(CORPUS_DIR, "_uploaded_ids.json")

# 헤딩 폐기율이 이 값을 넘으면 중단. 위생 규칙 오작동이나 새 서적의 마크다운
# 관례 차이로 섹션이 조용히 뭉개지는 것을 막는다(설계 §3.4).
MAX_HEADING_DROP_RATE = 0.10

_BOOK_ID_RE = re.compile(r"^[a-z0-9]+$")


@dataclass(frozen=True)
class BookPart:
    """스캔이 여러 파일로 쪼개진 서적의 후속 조각.

    조각마다 앞머리(속표지·중간 목차)의 위치가 다르므로 절단 마커를 따로 갖는다.
    """
    path: str
    body_start: str

    def __post_init__(self) -> None:
        # Book과 같은 이유로 생성 시점에 막는다 — 레지스트리 상수라 손으로 쓰고,
        # 틀려도 실행 중 예외가 아니라 조용한 오적재로 나타난다.
        if not self.path:
            raise ValueError("BookPart.path가 비어 있습니다")
        if not self.body_start:
            # str.find("")는 -1이 아니라 0을 반환한다 — load_body()의
            # `marker_pos == -1` 가드를 통과해 표지·목차가 절단 없이 본문에
            # 들어가고, 그 잡음은 헤딩이 아니라 표 텍스트라 폐기율 게이트에도
            # 걸리지 않는다.
            raise ValueError(f"BookPart.body_start가 비어 있습니다: {self.path}")


@dataclass(frozen=True)
class Book:
    """업로드 대상 서적.

    book_id는 chunk_id의 구성요소라 구분자('_')를 포함할 수 없다 — 포함하면
    ID 파싱이 모호해진다.
    """
    book_id: str
    title: str
    path: str
    body_start: str            # 표지·목차 절단 마커
    ocr_fixes: dict[str, str] = field(default_factory=dict)
    # 원본 스캔이 분할된 서적의 나머지 조각. 나열 순서가 곧 본문 순서다.
    # **뒤에만 추가할 것** — 중간에 끼우면 section_idx가 통째로 밀려 기존
    # chunk_id가 전부 바뀌고, 이전 벡터가 고아로 남는다(설계 §2.3의 ID 안정성).
    extra_parts: tuple[BookPart, ...] = ()
    # 서적별 헤딩 추출 특례(옵트인). 조문 특례(_ARTICLE_RE)처럼 길이·의미비율
    # 검사 **전에** 매치를 시도해, 매치되면 그 부분을 정규화해 헤딩으로 살린다.
    # **전역 규칙으로 승격하지 말 것** — 같은 패턴이 기존 서적의 폐기 헤딩에
    # 있으면 유지로 전환돼 section_idx가 밀린다(실측: 판례 패턴을 전역으로
    # 두면 win에서 6건 전환 → 1,408벡터 뒤쪽이 전부 고아).
    heading_extractors: tuple[re.Pattern, ...] = ()
    # 저신호 청크 제외율 상한의 서적별 override(옵트인). None이면 전역 상한
    # (MAX_CHUNK_DROP_RATE). **제외분 전량 육안 판정을 마친 서적에만** 올릴 것
    # — 상한은 "규칙 오작동 감지기"라, 육안 없이 올리면 감지기를 끄는 것과
    # 같다. 전역 상한을 올리지 않는 이유도 같다(다른 서적의 감지력 보존).
    low_signal_cap: float | None = None

    def __post_init__(self) -> None:
        # 레지스트리 상수라 사실상 타입 불변식이다 — main()에서만 검사하면
        # BOOKS를 직접 import하는 소비자들이 검증을 통과하지 않는다.
        if not _BOOK_ID_RE.match(self.book_id):
            raise ValueError(
                f"book_id는 소문자·숫자만 허용합니다(chunk_id 파싱): {self.book_id!r}")
        # 조각 경로 중복은 그 부분을 두 번 임베딩한다. section_idx가 계속
        # 증가하므로 chunk_id는 서로 달라 main()의 충돌 검사(서적 간 비교)에
        # 걸리지 않고, 폐기율도 정상으로 나온다 — 여기서만 잡을 수 있다.
        paths = [p.path for p in self.parts]
        dup = {p for p in paths if paths.count(p) > 1}
        if dup:
            raise ValueError(f"'{self.book_id}' 조각 경로가 중복됩니다: {sorted(dup)}")

    @property
    def parts(self) -> tuple[BookPart, ...]:
        """본문 순서대로의 전체 조각 — 단일 파일 서적은 길이 1."""
        return (BookPart(self.path, self.body_start),) + tuple(self.extra_parts)

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(p.path for p in self.parts)


# marker OCR이 헤딩을 깨뜨린 건들. 유효 표제가 남아 있어 복원 가능한 것만
# 명시 치환한다 — 잔해만 남은 헤딩은 sanitize_heading()이 폐기한다.
# 범용 '보정' 로직을 두지 않는 이유: 오폐기는 섹션 경계 하나를 잃을 뿐이지만
# 오복원은 코퍼스에 오정보를 남긴다(설계 §3.1).
# 키는 '#' 접두사를 뗀 헤딩 텍스트다 — sanitize_heading()이 받는 형태와 같아야
# 한다. 한자는 _MEANING_RE에 포함되므로 이 잔해는 비율 판정을 통과한다(즉
# 명시 치환 없이는 그대로 살아남는다).
WIN_OCR_FIXES = {
    "기본원칙 高温 日本 日本 日本 日本 日本 日本 日本 日本 日本 日本 日本 日本 日本":
        "기본원칙",
}

JUHAE3_OCR_FIXES = {
    "**Ⅰ. 최저임금의 결정기준** 나는 다시 보도 모든 이 모든 바로 유료되었다.":
        "Ⅰ. 최저임금의 결정기준",
    "Ⅱ. 최저임금 결정절차 [○ 1901 19121212 - 1910 12 12 12 12 12 12 12 12 12 12 12 12 12":
        "Ⅱ. 최저임금 결정절차",
    "Ⅱ. 출국금지의 해제요청 800 2000 028 28 28 9 10 12":
        "Ⅱ. 출국금지의 해제요청",
    "$\\text{I\\hspace{-.1em}I}$ . 보조ㆍ지원 제한의 예외 $\\text{I\\hspace{-.1em}I}$ "
    "에서 대한 일정 INSES 주립(ASIA)에서 조용자 ① 고몽노동부장관은 제43조의2에 따른 제물사업주":
        "Ⅱ. 보조·지원 제한의 예외",
}

# '실무테마'→'실무데마' OCR 오독 4건은 치환하지 않는다. 모두 직후에 하위 헤딩이
# 와 본문이 비고, 그래서 섹션에서 탈락해 벡터에 나타나지 않는다(치환 유/무
# 산출물이 바이트 동일함을 확인). 그중 2건은 번호만 남아('실무데마 19.') 제목을
# 채우려면 목차에서 가져와야 하는데, 그것은 원문에 없는 말을 헤딩에 넣는 일이다 —
# 오폐기는 섹션 경계 하나를 잃을 뿐이지만 오복원은 코퍼스에 오정보를 남긴다.
# 효과 없는 치환을 위해 그 위험을 지지 않는다.
#
# 아래 2건(전부 Part6)은 <sup> 각주 마크업이 의미문자 비율의 분모에 들어가
# 0.35 미만으로 떨어져 오폐기되는 정상 표제다 — 유효 표제가 온전히 남아 있어
# 명시 치환 대상이다. 범용 '<sup> 제거' 규칙을 두지 않는 이유: 규칙 변경은
# 다른 조각·서적의 유지/폐기 상태를 바꿔 section_idx(→chunk_id)를 밀 수 있다.
# (기존 조각의 sup 헤딩 5건은 한글 비중이 높아 치환 없이도 유지된다.)
# 같은 유형인 '(2) 국세청<sup>1)</sup>'은 치환하지 않는다 — 직후에 하위 헤딩이
# 바로 와 본문이 비고, 그래서 섹션에서 탈락해 산출물이 치환 유/무 동일하다.
GAEBYEOL_OCR_FIXES = {
    "2. 징계권의 근거<sup>1)</sup>": "2. 징계권의 근거",
    "Tip 고용안정협약<sup>1)</sup>": "Tip 고용안정협약",
}

# 스캔이 7파일로 분할된 서적. 각 조각의 앞머리는 속표지(해당 PART의 테마 목록)라
# 본문에서 제외한다 — 목차는 페이지 번호만 담고 있어 검색에 노이즈다.
# 조각 이름은 디스크의 디렉토리명 그대로 써야 한다 — 5번째 조각부터 'Part5'처럼
# 대문자다(경로가 {name}/_markdown/{name}/{name}.md 3중으로 name을 쓴다).
_GAEBYEOL_DIR = "개별노동법실무1"


def _gaebyeol_md(name: str) -> str:
    """조각 경로. macOS는 파일명을 NFD로 저장하므로 정규화 형태를 모두 시도한다.

    소스 리터럴은 NFC라 디스크의 NFD 이름과 **바이트가 다르다**. macOS(APFS)는
    조회 시 정규화해 주지만 Linux/ext4·CI·네트워크 공유는 그러지 않아, 같은
    코드가 `ls`에 보이는 파일을 '없다'고 말한다. 이 저장소는 NFD로 벡터 474개를
    잃은 전력이 있다.
    """
    for form in ("NFC", "NFD"):
        p = os.path.join(CORPUS_DIR, unicodedata.normalize(form, _GAEBYEOL_DIR),
                         name, "_markdown", name, f"{name}.md")
        if os.path.exists(p):
            return p
    # 어느 형태로도 없으면 호출부(존재 검사)가 경로를 그대로 보고하게 둔다.
    return os.path.join(CORPUS_DIR, _GAEBYEOL_DIR, name, "_markdown", name, f"{name}.md")


_JUHAE3_DIR = "근로기준법주해-3"


def _juhae3_md(filename: str) -> str:
    """근로기준법주해-3/ 직속 파일 경로 — 한글 경로라 NFC/NFD 폴백(_gaebyeol_md와 동일 이유).

    디렉터리와 파일명의 정규화 형태를 **독립적으로** 순회한다 — 혼합 조합
    (NFC 디렉터리 + NFD 파일명)은 바이트 보존 FS에서 단일 form 순회로는
    못 찾는다(precedent-archive PR#61 doc_path에서 실증된 클래스).
    """
    for dir_form in ("NFC", "NFD"):
        for file_form in ("NFC", "NFD"):
            p = os.path.join(CORPUS_DIR, unicodedata.normalize(dir_form, _JUHAE3_DIR),
                             unicodedata.normalize(file_form, filename))
            if os.path.exists(p):
                return p
    return os.path.join(CORPUS_DIR, _JUHAE3_DIR, filename)


def _juhae3_scan(name: str) -> str:
    """근로기준법주해-3/ 하위 marker 스캔 조각({name}/{name}.md) 경로."""
    for dir_form in ("NFC", "NFD"):
        for file_form in ("NFC", "NFD"):
            n = unicodedata.normalize(file_form, name)
            p = os.path.join(CORPUS_DIR, unicodedata.normalize(dir_form, _JUHAE3_DIR),
                             n, f"{n}.md")
            if os.path.exists(p):
                return p
    return os.path.join(CORPUS_DIR, _JUHAE3_DIR, name, f"{name}.md")


BOOKS: dict[str, Book] = {
    "win": Book(
        book_id="win",
        title="Win 노동법(2025, 공인노무사·5급공채·변호사시험 대비)",
        path=os.path.join(CORPUS_DIR, "Win노동법_merged.md"),
        # 표지·목차(0~17)는 marker OCR이 표 구조를 깨뜨려 글자 스프뿐이라 전량 제외.
        body_start="<!-- page: 18 -->",
        ocr_fixes=WIN_OCR_FIXES,
    ),
    "juhae3": Book(
        book_id="juhae3",
        # 수록 범위를 title에 명시한다(부분 수록 규칙 — G3가 이 문자열을 인용
        # 서명으로 쓴다). 2026-09-02에 같은 권의 4개 장 스캔이 추가됐다:
        # 제3장 임금(1~185) → 제4장 근로시간과 휴식(186~) → 제5장 여성과
        # 소년 → 제6장의2 직장 내 괴롭힘(590~) → 제8장 재해보상(644~721).
        # 스캔 확보분만 수록(제6장·제7장 없음). 조각은 **뒤에만 추가할 것.**
        title="근로기준법 주해 Ⅲ — 임금·근로시간과 휴식·여성과 소년·"
              "직장 내 괴롭힘·재해보상(제2판 수정증보판)",
        path=_juhae3_md("근로기준법주해3_임금.md"),
        # 1~5페이지가 표지·목차. page 6 직후에 '# 제 3장 임 금'이 나온다.
        body_start="<!-- page: 6 -->",
        ocr_fixes=JUHAE3_OCR_FIXES,
        # 각 조각의 page 0은 속표지(장 제목뿐) — page 1부터 본문.
        extra_parts=(
            BookPart(path=_juhae3_scan("iPhone_15_-_근로기준법주해_근로시간과_휴식"),
                     body_start="<!-- page: 1 -->"),
            BookPart(path=_juhae3_scan("iPhone_15_-_근로기준법주해_여성과소년"),
                     body_start="<!-- page: 1 -->"),
            BookPart(path=_juhae3_scan("iPhone_15_-_근로기준법주해_직장내괴롭힘금지"),
                     body_start="<!-- page: 1 -->"),
            BookPart(path=_juhae3_scan("iPhone_15_-_근로기준법주해_재해보상"),
                     body_start="<!-- page: 1 -->"),
        ),
    ),
    "gaebyeol": Book(
        book_id="gaebyeol",
        # 수록 범위를 title에 명시한다. 원서의 실무테마 1~85 전량이 적재됐다
        # (2026-08-20, Part6·Part7 추가). 범위 표기를 유지하는 이유: G3
        # (prompts.py)가 "참고 자료에 있는 서명만" 쓰라고 지시해 이 문자열이
        # LLM 인용 서명의 유일한 출처이고, 범위가 곧 서지 정보이기 때문이다.
        # 조각을 추가하면 이 범위도 함께 갱신할 것(part1~3=1~35, part4=36~46,
        # Part5=47~60, Part6=61~81, Part7=82~85). title은 build_bm25_corpus.py가
        # BM25 코퍼스에도 담으므로 변경 시 재빌드가 필요하다.
        title="개별 노동법실무 1권 — 실무테마 1~85(최영우, 개정증보 12판)",
        # part1의 0~12페이지는 표지·차례·색인(용어→페이지 번호)이라 전량 제외.
        # page 13에서 '실무테마 1. 근로기준법의 적용범위'로 본문이 시작한다.
        path=_gaebyeol_md("part1"),
        body_start="<!-- page: 13 -->",
        ocr_fixes=GAEBYEOL_OCR_FIXES,
        # part2 이후는 page 0이 해당 PART의 속표지다.
        # **뒤에만 추가할 것** — 중간에 끼우면 section_idx가 밀려 기존 조각의
        # chunk_id가 전부 바뀌고 이전 벡터가 고아로 남는다.
        extra_parts=(
            BookPart(_gaebyeol_md("part2"), "<!-- page: 1 -->"),
            BookPart(_gaebyeol_md("part3"), "<!-- page: 1 -->"),
            BookPart(_gaebyeol_md("part4"), "<!-- page: 1 -->"),
            BookPart(_gaebyeol_md("Part5"), "<!-- page: 1 -->"),
            BookPart(_gaebyeol_md("Part6"), "<!-- page: 1 -->"),
            BookPart(_gaebyeol_md("Part7"), "<!-- page: 1 -->"),
        ),
    ),
    "ironpanrye": Book(
        book_id="ironpanrye",
        # 판례 헤딩 특례 — 이 책은 판례가 소제목 단위다("이론판례"). 사건번호
        # 헤딩은 숫자·마침표가 의미비율 분모를 채워 전량 오폐기됐다(실측:
        # 폐기 253건 중 ~200건). 사건번호는 이 책의 최우선 검색 키이므로
        # 특례로 살린다. 서적별 옵트인인 이유는 Book.heading_extractors 주석.
        heading_extractors=(
            # 어미(판결/결정)는 옵셔널 — '대법원 2002.7.9. 선고 2001다29452'
            # 처럼 어미가 누락된 헤딩도 사건번호까지는 유효하다. 병합 사건은
            # 두 번째 번호에 부호가 다시 붙을 수 있다('2015다221903,
            # 2015다221910'). '대결'·'결정'·'등 판결'도 실측 변형.
            re.compile(
                r"((?:대법원|대결)\s*\d{4}\s*[.,]\s*\d{1,2}\s*[.,]\s*\d{1,2}\s*[.,]?\s*"
                r"(?:선고\s*)?\d{2,4}[가-힣]{1,4}\d+"
                r"(?:\s*[·,]\s*(?:\d{2,4}[가-힣]{1,4})?\d+)*"
                r"(?:\s*등)?\s*(?:전원합의체\s*)?(?:판결|결정)?)"
            ),
        ),
        # 기출 이력 접미(◆노16, 변19 등)·마크업 잔재가 의미비율을 깎아
        # 오폐기되는 핵심 쟁점 표제들 — 유효 표제가 온전히 남아 있어 명시
        # 치환한다(관례: 오폐기 < 오복원, 복원은 명시 치환만).
        ocr_fixes={
            "09 시용 4 노16, 변19, 5급22": "09 시용",
            "01 전직 4 변13, 5급11·20·23": "01 전직",
            "05 전적 ∢노10, 5급14·23": "05 전적",
            "08 징계절차의 정당성 ◆변13·14·17·19·24, 5급14·22, 노10·23":
                "08 징계절차의 정당성",
            "06 해고의 서면통지 ◆노11·16·22, 변13·17·20·25": "06 해고의 서면통지",
            "**| 불이익변경의 절차 ⁴** 노13·15·21, 변12·22·23, 5급13·17·21":
                "불이익변경의 절차",
            "(4) 일<del>률</del>성": "(4) 일률성",
        },
        # 전권 수록(2026-08-22 part2·part3 적재) — 첫 조각이 PART 01 총론 +
        # PART 02 근로기준법(퇴직금까지), part2가 PART 03 노조법 전체, part3이
        # PART 04 기타 법령(비정규직·안전보건·산재보험·고용보험·노동위원회).
        # 조각을 더 추가하면 extra_parts **뒤에만** 붙이고 title·이 주석을
        # 함께 갱신할 것 + BM25 재빌드.
        title="이론판례 노동법(제15판, 김기범 편저, 2026)",
        # p0 표지, p1 법령 약어표, p2~17 목차, p18 PART 01 속표지(이미지).
        # page 19에서 'Chapter 01 노동법의 법원'으로 본문이 시작한다.
        path=os.path.join(CORPUS_DIR, "이론판례노동법", "이론판례노동법.md"),
        body_start="<!-- page: 19 -->",
        # part3의 저신호 제외율이 10.5%로 전역 상한(10%)을 스치는데, 제외
        # 68건 전량 육안 판정 결과 전부 정당한 잡음이었다 — 빈 표 구분선
        # 60건(파견대상업무 표·각 법률 '구성' 표의 깨진 OCR), 'LABOR LAW'
        # 워터마크 4, OCR 반복 3. 정상 본문 오탐 0. 이 책은 법률 구성 표가
        # 많은 편집이라 잡음 비율이 구조적으로 높다 — 여유폭만 소폭 부여.
        low_signal_cap=0.13,
        # part2·part3은 page 0이 해당 PART 속표지(이미지+장 목록)라 제외.
        extra_parts=(
            BookPart(os.path.join(CORPUS_DIR, "이론판례노동법", "part2", "part2.md"),
                     "<!-- page: 1 -->"),
            BookPart(os.path.join(CORPUS_DIR, "이론판례노동법", "part3", "part3.md"),
                     "<!-- page: 1 -->"),
        ),
    ),
}

_PAGE_COMMENT_RE = re.compile(r"<!--\s*page:\s*\d+\s*-->")
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)


# ── 텍스트 유틸 ───────────────────────────────────────────────────────────────
# `pinecone_upload_legal.py`의 clean_text와 **다르다** — 그쪽의 마크다운
# 이스케이프 해제 2줄(`\\\n`, `\\([*_...])`)이 여기엔 없다. 이전 주석이
# "동일 로직"이라고 잘못 주장했다(외부감사 2026-08-23 M6).
#
# **의도적으로 추가하지 않는다.** marker 변환 산출물에도 이스케이프가 있긴 하나
# 극소량이고(실측: 4권 본문 474만 자 중 133개 = 0.003%, 2~74ppm), 반면
# clean_text가 바뀌면 청크 분할 경계가 밀려 `chunk_id`가 달라지고 **기존
# 해설서 벡터 10,103개 중 일부가 고아로 남는다**(prune으로 정리되더라도 재업로드
# 비용이 든다). 백슬래시 133개를 지우려고 치를 대가가 아니다.

def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
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


# ── 헤딩 위생 처리 ────────────────────────────────────────────────────────────

_MARK_RE = re.compile(r"</?mark>")
_TEX_RE = re.compile(r"\$[^$]*\$")
_ARTICLE_RE = re.compile(r"(제\d+조(?:의\d+)?\s*\([^)]{1,30}\))")
_MEANING_RE = re.compile(r"[가-힣一-龥ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]")
# 비율 분모에서 공백·구두점을 뺀다 — 원문 헤딩은 '2. 요 건'처럼 자간 공백이
# 흔해서, 전체 길이를 분모로 쓰면 정상 표제가 오폐기된다(2/6=0.33 < 0.35).
_SIGNIF_RE = re.compile(r"[^\s.·…\-—,、]")

HEADING_MIN_LEN = 3
# 상한은 '잡음 걸러내기'용이지 '긴 제목 자르기'용이 아니다. 60은 조문 해설서
# 두 권에 맞춘 값이었는데, Q&A형 실무서가 들어오면서 정상 표제를 지우기
# 시작했다 — 실측 폐기 사유: gaebyeol은 32건 중 28건이 길이 초과이고 그중
# 27건이 멀쩡한 문장('(4) 공공기관 청년인턴제도에 따른 …', 95자)인 반면
# win의 2건은 진짜 OCR 잡음이었다. 폐기된 헤딩은 본문만 직전 섹션에 흡수되고
# 제목 문자열 자체는 코퍼스에서 사라지므로, 질문이 곧 검색 키인 Q&A 책에서는
# 그 키가 통째로 없어진다. 80은 메타데이터 저장 폭(section[:80])과 같은 값이라
# 잘림 없이 실릴 수 있는 한계이기도 하다. 상향 효과: gaebyeol 32→10, win 15→14.
HEADING_MAX_LEN = 80
HEADING_MIN_RATIO = 0.35


def sanitize_heading(raw: str, ocr_fixes: dict[str, str],
                     extractors: tuple[re.Pattern, ...] = ()) -> str | None:
    """정제된 헤딩 문자열, 또는 폐기 대상이면 None.

    헤딩은 section 메타데이터이자 embed_text 접두사로 두 번 쓰이므로,
    OCR 잔해가 들어가면 검색 품질과 출처 표시가 함께 망가진다.

    extractors: 서적별 옵트인 특례(Book.heading_extractors). 조문 특례처럼
    길이·의미비율 검사 전에 매치를 추출해 살린다 — 전역화 금지 사유는
    Book 필드 주석 참조.

    Returns:
        정제된 헤딩. None이면 섹션 경계로 쓰지 않고 본문을 이웃 섹션에 흡수한다.
    """
    # ocr_fixes는 원문 문자열 기준으로 매칭한다 — 정제 후에 매칭하면 정제
    # 과정이 바뀔 때마다 치환 키가 조용히 무효가 된다.
    heading = ocr_fixes.get(raw.strip(), raw)

    s = _MARK_RE.sub("", heading).replace("**", "")

    # 조문 표기 추출은 길이 검사보다 먼저 — 잡음이 섞여도 59자처럼 상한을
    # 아슬아슬하게 통과하면 그대로 살아남는다.
    m = _ARTICLE_RE.search(s)
    if m:
        return re.sub(r"\s+", "", m.group(1))

    # 서적별 특례 — 매치 부분만 추출(잔재 접두 'm'·'血' 등은 매치 밖이라
    # 자동 탈락). 공백은 collapse만 하고 보존한다(조문 특례의 전면 제거와
    # 달리 '대법원 2010.5.20. 선고 …'는 공백이 의미 단위다).
    for ex in extractors:
        em = ex.search(s)
        if em:
            return re.sub(r"\s+", " ", em.group(1)).strip()

    s = _TEX_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip(" .·…-—")

    if not (HEADING_MIN_LEN <= len(s) <= HEADING_MAX_LEN):
        return None

    denom = len(_SIGNIF_RE.findall(s))
    if denom == 0 or len(_MEANING_RE.findall(s)) / denom < HEADING_MIN_RATIO:
        return None
    return s


# ── 본문 파싱 ─────────────────────────────────────────────────────────────────

def load_part_body(part: BookPart) -> str:
    """조각 하나의 본문(앞머리 절단 후, page 주석 제거).

    없거나 마커를 못 찾으면 중단한다 — 조용히 건너뛰면 책의 중간이 빠진 채
    업로드되고, 그 사실을 알아챌 방법이 없다. 오류 메시지는 **그 조각의**
    마커를 보여준다(책 대표 마커를 보여주면 3조각 중 2번은 엉뚱한 곳을 가리킨다).
    """
    if not os.path.exists(part.path):
        sys.exit(f"[오류] 원본 파일이 없습니다: {part.path}")
    with open(part.path, "r", encoding="utf-8") as f:
        content = f.read()

    marker_pos = content.find(part.body_start)
    if marker_pos == -1:
        sys.exit(f"[오류] body_start 마커를 찾을 수 없습니다: "
                 f"{part.body_start!r} ({part.path})")
    return _PAGE_COMMENT_RE.sub("", content[marker_pos + len(part.body_start):])


def load_parts(book: Book) -> list[str]:
    """조각별 본문 리스트(본문 순서). 단일 파일 서적은 길이 1."""
    return [load_part_body(p) for p in book.parts]


def join_parts(segments: list[str]) -> str:
    """조각 본문을 하나로 잇는다.

    경계에 빈 줄을 둔다 — 앞 조각의 마지막 문단과 다음 조각의 첫 헤딩이 한 줄로
    붙으면 _HEADING_RE(^ 앵커)가 그 헤딩을 인식하지 못해 섹션이 통째로 사라진다.
    """
    return "\n\n".join(segments)


def load_body(book: Book) -> str:
    """표지·목차를 제외한 본문만 로드. 분할 서적은 조각을 순서대로 이어붙인다."""
    return join_parts(load_parts(book))


def load_body_normalized(book: Book) -> str:
    """본문 + 헤딩 위생 처리를 마크다운 형태 그대로 반환.

    청킹이 아니라 '본문을 통째로 훑는' 소비자(enrich_court_precedents.py의
    표제 경로 추출)를 위한 경로다. 손상 헤딩은 줄 자체를 제거하되 본문은
    남긴다 — 위생 규칙을 두 곳에 복제하지 않기 위한 단일 출처.

    위생 처리 범위는 `_HEADING_RE`와 같은 **h1~h3**이다. enrich의 HEADING_RE는
    `#{1,6}`이라 h4~h6(win 249개, juhae3 29개)은 정제 없이 통과한다 — 청킹
    경계를 h1~h3으로 고정한 결과이며, 넓히면 chunk_id가 밀려 고아 벡터가 생긴다.
    """
    body = load_body(book)

    def _rewrite(m: re.Match) -> str:
        heading = sanitize_heading(m.group(2).strip(), book.ocr_fixes, book.heading_extractors)
        return f"{m.group(1)} {heading}" if heading else ""

    return _HEADING_RE.sub(_rewrite, body)


def parse_sections(body: str, book: Book) -> tuple[list[dict], int, int]:
    """헤더(#/##/###) 단위로 섹션 분할. 손상 헤딩은 경계로 쓰지 않는다.

    폐기된 헤딩의 본문은 직전 섹션에 흡수한다(직전이 없으면 다음 섹션 앞에 붙인다).
    폐기 때문에 본문이 유실되는 경로는 없다.

    단, **책 전체의 첫 헤딩보다 앞선 텍스트는 어떤 섹션에도 들어가지 않는다**.
    body_start 직후에 헤딩이 오는 것을 전제한 동작이다.

    분할 서적에서는 이 규칙이 첫 조각에만 적용된다 — 이 함수는 이미 이어붙인
    한 덩어리를 받으므로, 2번째 이후 조각의 헤딩 앞 텍스트는 '두 헤딩 사이'가
    되어 **직전 조각의 마지막 섹션에 흡수된다**. 현재 gaebyeol에서는 이미지
    참조 한 줄(약 26자)뿐이라 실질 영향이 없지만, 조각의 body_start를 한 페이지
    앞으로 잘못 잡으면 그 조각의 속표지 목차가 통째로 직전 조각의 헤딩 아래
    실린다. 폐기율 게이트는 헤딩만 세므로 이 경로를 잡지 못한다.

    Returns:
        (sections, kept_headings, dropped_headings)
        sections: [{"heading": "...", "text": "..."}, ...]
        kept_headings는 len(sections)와 다르다 — 본문이 빈 섹션은 sections에서
        빠지기 때문이다. 폐기율 분모는 반드시 kept_headings를 써야 한다.
    """
    matches = list(_HEADING_RE.finditer(body))
    if not matches:
        return ([{"heading": "본문", "text": clean_text(body)}] if body.strip() else []), 0, 0

    sections: list[dict] = []
    dropped = 0
    pending = ""          # 직전 섹션이 없는 상태에서 폐기된 헤딩의 본문

    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        raw_text = body[start:end]

        heading = sanitize_heading(m.group(2).strip(), book.ocr_fixes, book.heading_extractors)
        if heading is None:
            dropped += 1
            if sections:
                sections[-1]["text"] += "\n" + raw_text
            else:
                pending += raw_text + "\n"
            continue

        sections.append({"heading": heading, "text": pending + raw_text})
        pending = ""

    cleaned = []
    for s in sections:
        text = clean_text(s["text"])
        if text:
            cleaned.append({"heading": s["heading"], "text": text})
    return cleaned, len(sections), dropped


def check_drop_rate(book: Book, kept: int, dropped: int,
                    scope: str | None = None, marker: str | None = None) -> None:
    """헤딩 폐기율 상한 검사 — 초과 시 중단.

    Args:
        scope: 검사 대상 표시(조각 파일명 등). None이면 책 전체.
        marker: 오류 메시지에 보여줄 body_start. None이면 책 대표 마커.
    """
    label = f"'{book.book_id}'" + (f" [{scope}]" if scope else "")
    # 마커는 여기서 딱 한 번 repr 한다 — 호출부가 미리 repr 해서 넘기면
    # f-string의 !r이 그 위에 다시 걸려 따옴표가 두 겹으로 나온다.
    shown = book.body_start if marker is None else marker
    total = kept + dropped
    if total == 0:
        # 게이트가 막으려던 실패(body_start 오배치)가 정확히 이 모습이다 —
        # 헤딩이 하나도 없으면 책 전체가 단일 섹션이 되므로 통과시키면 안 된다.
        sys.exit(f"[오류] {label} 본문에서 헤딩을 찾지 못했습니다 — "
                 f"body_start 마커({shown!r})가 잘못됐을 수 있습니다.")
    rate = dropped / total
    print(f"  {scope or '전체'}: 헤딩 {total}개 → 유지 {kept} / 폐기 {dropped} "
          f"({rate * 100:.1f}%)")
    if rate > MAX_HEADING_DROP_RATE:
        sys.exit(
            f"[오류] {label} 헤딩 폐기율 {rate * 100:.1f}%가 상한 "
            f"{MAX_HEADING_DROP_RATE * 100:.0f}%를 초과했습니다 — 위생 규칙 오작동 "
            f"또는 body_start 마커({shown!r}) 오류일 수 있습니다. 업로드를 중단합니다."
        )


def check_part_drop_rates(book: Book, segments: list[str]) -> None:
    """조각별 폐기율 검사 — 병합 합계는 한 조각의 손상을 희석한다.

    실측(gaebyeol): 조각별 2.05 / 2.06 / 5.30%가 합계 2.96%로 뭉쳐 10% 상한과
    대조된다. 3조각이면 한 조각이 30% 망가져도 합계는 통과한다.

    조각 길이도 함께 출력한다 — 마커가 '찾을 수 없음'이 아니라 **엉뚱한 위치에서
    맞는** 경우(페이지 번호 오프셋 착오)는 폐기율이 오히려 좋아져서 어떤 비율
    게이트로도 못 잡는다. 분량 급감은 사람이 보면 바로 안다.

    parse_sections를 조각마다 다시 돌리는 것은 중복이 아니다 — 병합본의 폐기
    카운트에서는 어느 헤딩이 어느 조각 것인지 되짚을 수 없다. 카운트 로직을
    따로 구현하면 위생 규칙이 두 벌이 되므로 같은 함수를 재사용한다.

    Args:
        segments: 조각별 본문(load_parts 결과). 호출부가 이미 읽은 것을 넘겨
            파일을 두 번 읽지 않는다.
    """
    if not book.extra_parts:
        return
    for part, seg in zip(book.parts, segments):
        sections, kept, dropped = parse_sections(seg, book)
        scope = f"{os.path.basename(part.path)} ({len(seg):,}자)"
        check_drop_rate(book, kept, dropped, scope=scope, marker=part.body_start)

        # 청크 제외율도 조각별로 본다. 책 단위로만 재면 헤딩 게이트에서 이미
        # 겪은 희석이 그대로 재현된다 — 실측(gaebyeol) 조각별 2.79/1.58/4.25%가
        # 합계 2.80%로 뭉치고, 상한 10%면 part3 하나가 32% 망가져도 통과한다.
        c_kept = c_dropped = 0
        for section_idx, section in enumerate(sections):
            part_chunks, part_dropped = chunk_section(section, book, section_idx)
            c_kept += len(part_chunks)
            c_dropped += part_dropped
        check_chunk_drop_rate(book, c_kept, c_dropped, scope=scope)


# ── 청크 본문 신호 판정 ───────────────────────────────────────────────────────

# 괘선·구분선만으로 이루어진 청크(marker가 표 구조를 본문으로 흘린 잔해).
_STRUCT_ONLY_RE = re.compile(r"^[\s|\-:+_=.·…—]*$")
_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")
# 연속 중복 구절 축약. 12자 하한을 두어 조사·접속사 같은 짧은 반복은 건드리지
# 않는다. 축약은 원문 변형이지만 **정보를 더하지 않으므로** 오정보 위험이 없다
# — 위생 규칙이 경계하는 것은 없던 말을 채워 넣는 방향이다.
_DUP_RUN_RE = re.compile(r"(.{12,}?)\1+", re.S)

# 청크 의미비율의 분모. 헤딩용 _SIGNIF_RE와 달리 **표 구분자와 셀 여백을 뺀다**
# — 마크다운 표는 '|'가 내용만큼 많아서, 그것을 분모에 넣으면 정상 표가 통째로
# 잡음으로 판정된다(실측: 교대제 근무표 478자·287자가 오탐). 헤딩 판정은 표를
# 만날 일이 없으므로 상수를 공유하지 않고 따로 둔다.
_CHUNK_SIGNIF_RE = re.compile(r"[^\s.·…\-—,、|:]")
# 표 안에서만 숫자를 의미문자로 인정한다.
#
# 분자인 _MEANING_RE는 헤딩용이라 한글·한자·로마숫자만 센다. 헤딩은 그래야
# 맞지만 본문에 그대로 쓰면 **한글이 없는 정상 청크가 무조건 제외된다** —
# 최저임금·통상임금 수치표(`| 2024 | 9,860 | 2,060,740 |`)가 의미비 0.000이
# 되는데, 그런 표는 임금 해설서의 핵심 자료형이다. 현재 3권에서 오탐이 없는
# 것은 700자 청크에 보통 한글 표제가 섞이기 때문이고, split_by_size가 표
# 중간을 자르면 바로 재현된다.
#
# 그렇다고 숫자를 항상 인정하면 'Ex -- 1-1-1-0 | 5 -- …' 같은 숫자 OCR 잔해가
# 살아난다. 표일 때만 인정하는 이유다 — 표 형태의 OCR 잡음
# ('| The state of the state of …')은 숫자가 없어 여전히 걸린다.
_MEANING_IN_TABLE_RE = re.compile(r"[가-힣一-龥ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ0-9]")

# 길이 하한은 '잡음 거르기'가 아니라 '축약 후 껍데기만 남은 것' 판정이다.
# 15로 두면 '1. 의 의'(6자)·'(1) 귀책사유의 의미'(12자) 같은 정상 소제목 조각을
# 버린다(실측 오탐 3건). 짧은 잡음은 의미비율·구조 규칙이 이미 잡으므로
# 여기서는 사실상 빈 문자열만 막는다.
CHUNK_MIN_LEN = 4
CHUNK_MIN_UNIQ_RATIO = 0.25
CHUNK_MIN_MEANING_RATIO = 0.10
# 신호 게이트 오작동으로 본문이 대량 소실되는 것을 막는 상한.
# 헤딩 폐기율 상한을 **참조**한다 — 값만 같게 복사해 두면 한쪽을 조정할 때
# 규약이 조용히 갈라진다. "위생 규칙의 허용 손실은 10%"가 하나의 규약이다.
MAX_CHUNK_DROP_RATE = MAX_HEADING_DROP_RATE


def collapse_dup_runs(text: str) -> str:
    """연속 중복 구절을 1회로 접는다."""
    return _DUP_RUN_RE.sub(r"\1", text)


def _looks_like_table(text: str) -> bool:
    """마크다운 표 조각인가.

    '|를 포함한 줄이 과반'으로 판정하면 산문형 OCR 잔해가 표로 오인된다
    (실측: '1-1-1-0 0 Ex -- … | 5 -- 1-1-1-0 | 5' 한 줄이 표로 잡혔다).
    마크다운 표의 행은 **줄 첫 글자가 셀 구분자**이므로 그것을 요구한다 —
    청크 경계가 표 중간을 잘라 첫 줄이 셀 값부터 시작해도, 이어지는 행이
    조건을 만족한다.
    """
    return any(ln.lstrip().startswith("|")
               for ln in text.splitlines() if ln.strip())


def is_low_signal(text: str) -> bool:
    """검색 가치가 없는 잡음 청크인가.

    **단일 의미문자 비율로 판정하면 안 된다** — 잡음과 정보가 같은 비율 구간에
    공존한다(실측: 표 구분선 0.000·OCR 반복 0.266이 잡음인 반면, 영문 병기
    목록 0.250·판례 표 0.309는 유용). 비율은 판별식이 될 수 없으므로 잡음의
    구조를 본다.

    축약을 **먼저** 하는 것이 핵심이다. OCR이 한 구절을 반복 출력하면 그 청크의
    고유토큰비가 무너지는데, 반복을 걷어내고 보면 유효한 본문이 남아 있는
    경우가 있다(실측: textbook_win_0612_1은 원본 646자 중 축약 후 79자가
    판례 인용을 포함한 정상 문장이다). 축약 없이 자르면 그 본문까지 함께
    버린다 — 반복은 잡음이지만 반복된 *내용*은 아니다.

    규칙은 서로를 보완한다 — 'THE STATE OF' 반복은 축약 후 고유토큰비가 1.0이
    되지만 의미비 0.000으로 걸린다. 하나를 빼면 샌다.
    """
    t = collapse_dup_runs(text).strip()

    if len(t) < CHUNK_MIN_LEN:
        return True
    if _STRUCT_ONLY_RE.match(t):
        return True

    # 표는 값이 반복되는 것이 정상이다 — 교대제 근무표('근 | 휴 | 2근 | 2근 …')
    # 처럼 실무 정보를 담은 표가 고유토큰비 규칙에 잡힌다(실측 오탐 2건).
    # 표 안에 든 OCR 잡음은 아래 의미비율이 백스톱으로 잡으므로 안전하다.
    is_table = _looks_like_table(t)
    if not is_table:
        tokens = _TOKEN_RE.findall(t)
        if tokens and len(set(tokens)) / len(tokens) < CHUNK_MIN_UNIQ_RATIO:
            return True

    meaning_re = _MEANING_IN_TABLE_RE if is_table else _MEANING_RE
    denom = len(_CHUNK_SIGNIF_RE.findall(t))
    if denom == 0 or len(meaning_re.findall(t)) / denom < CHUNK_MIN_MEANING_RATIO:
        return True
    return False


def check_chunk_drop_rate(book: Book, kept: int, dropped: int,
                          scope: str | None = None) -> None:
    """청크 제외율 상한 검사 — 초과 시 중단.

    Args:
        scope: 검사 대상 표시(조각 파일명 등). None이면 책 전체.
    """
    label = f"'{book.book_id}'" + (f" [{scope}]" if scope else "")
    total = kept + dropped
    if total == 0:
        sys.exit(f"[오류] {label} 청크가 하나도 생성되지 않았습니다.")
    rate = dropped / total
    if dropped:
        print(f"  저신호 청크 제외{f' [{scope}]' if scope else ''}: "
              f"{dropped} / {total} ({rate * 100:.1f}%)")
    cap = book.low_signal_cap if book.low_signal_cap is not None else MAX_CHUNK_DROP_RATE
    if rate > cap:
        sys.exit(
            f"[오류] {label} 청크 제외율 {rate * 100:.1f}%가 상한 "
            f"{cap * 100:.0f}%를 초과했습니다 — 신호 판정 규칙 "
            f"오작동일 수 있습니다. 업로드를 중단합니다."
        )


# ── 청킹 ─────────────────────────────────────────────────────────────────────

def chunk_section(section: dict, book: Book,
                  section_idx: int) -> tuple[list[dict], int]:
    """섹션 1개 → 청크 리스트.

    chunk_id에 book_id가 반드시 들어가야 한다 — 없으면 서적 간 heading_idx가
    겹쳐 Pinecone upsert가 조용히 덮어쓴다(실측: Win 1,414 / 주해Ⅲ 463청크에서
    177건 충돌).

    section_idx는 '유지된 섹션'의 순번이다. 폐기 헤딩이 번호를 소비하면
    ocr_fixes 한 줄만 바뀌어도 뒤쪽 ID가 전부 밀려 고아 벡터가 생긴다.

    같은 이유로 저신호 청크도 번호를 소비하지 않는다 — 소비하면 ID에 구멍이
    생기고, 롤백 원장의 검증 정규식(`_\\d+$`)은 구멍을 통과시켜 조용하다.

    **판정한 텍스트를 그대로 저장한다.** 축약본으로 판정하고 원본을 저장하면,
    게이트를 통과시킨 근거(반복을 걷어낸 79자)와 실제 적재분(646자)이 달라져
    임베딩이 내용 대신 OCR 반복을 인코딩하고 그 반복이 LLM 컨텍스트와 출처
    카드까지 간다. 게이트를 둔 목적 자체가 무효가 된다.

    Returns:
        (chunks, dropped) — dropped는 저신호로 제외된 청크 수.
    """
    chunks = []
    dropped = 0
    for raw_text in split_by_size(section["text"]):
        sub_text = collapse_dup_runs(raw_text).strip()
        if is_low_signal(raw_text):
            dropped += 1
            continue
        idx = len(chunks)
        embed_text = f"제목: {book.title}\n섹션: {section['heading']}\n\n{sub_text}"
        chunks.append({
            "chunk_id": f"textbook_{book.book_id}_{section_idx:04d}_{idx}",
            "chunk_index": idx,
            "embed_text": embed_text,
            "chunk_text": sub_text,
            "section": section["heading"],
        })

    # 섹션의 청크가 전부 제외되면 **헤딩 문자열이 코퍼스에서 통째로 사라진다.**
    # 헤딩 위생 처리는 폐기해도 본문을 이웃 섹션에 흡수시키지만 이 경로는
    # 둘 다 잃는다 — 실측으로 '재량근로시간제'·'근로시간의 범위' 같은 검색 키가
    # 사라졌다(게이트 도입 전에는 잡음 청크가 그 헤딩을 embed_text에 싣고 있었다).
    # 잡음 본문은 버리되 표제는 남긴다.
    if not chunks and dropped:
        heading = section["heading"]
        chunks.append({
            "chunk_id": f"textbook_{book.book_id}_{section_idx:04d}_0",
            "chunk_index": 0,
            "embed_text": f"제목: {book.title}\n섹션: {heading}",
            "chunk_text": heading,
            "section": heading,
        })
    return chunks, dropped


def build_chunks(book: Book) -> list[dict]:
    """서적 1권 → 전체 청크 (임베딩 전 단계까지)."""
    # 조각을 한 번만 읽어 병합본과 조각별 검사에 함께 쓴다.
    segments = load_parts(book)
    body = join_parts(segments)
    sections, kept, dropped = parse_sections(body, book)
    check_drop_rate(book, kept, dropped)
    check_part_drop_rates(book, segments)

    chunks = []
    low_signal = 0
    for section_idx, section in enumerate(sections):
        part, dropped_chunks = chunk_section(section, book, section_idx)
        chunks.extend(part)
        low_signal += dropped_chunks
    check_chunk_drop_rate(book, len(chunks), low_signal)
    print(f"  섹션 {len(sections)} → 청크 {len(chunks)}")
    return chunks


# ── 임베딩 ────────────────────────────────────────────────────────────────────

def embed_texts(texts: list[str], client: OpenAI) -> list[list[float]]:
    for attempt in range(3):
        try:
            resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
            return [d.embedding for d in sorted(resp.data, key=lambda x: x.index)]
        except Exception as e:
            if attempt == 2:
                raise
            print(f"  임베딩 재시도 ({attempt + 1}/3): {e}")
            time.sleep(2 ** attempt)
    return []


# 원장 구현은 vector_ledger.py가 단일 출처다 — court 스크립트도 같은 것을 쓴다.
# 사본을 두지 않는 이유: 같은 사이클(외부감사 2026-08-23)에서 M1이 "업로드
# 스크립트 간 유틸 복사"로 legal의 NFD 픽스가 contextual에 3.5개월간 전파되지
# 않은 것을 확인했다. 여기 원장은 Pinecone Serverless에서 고아 벡터를 지울 수
# 있는 유일한 수단이라 드리프트의 대가가 더 크다.
_LEDGER = VectorLedger(
    UPLOADED_IDS_FILE,
    group_re=_BOOK_ID_RE,
    id_re_for=lambda bid: re.compile(rf"^textbook_{re.escape(bid)}_\d{{4}}_\d+$"),
)


def _read_ledger() -> dict[str, list[str]]:
    """원장 로드(위임). 테스트가 UPLOADED_IDS_FILE을 갈아끼우므로 경로를 매번 맞춘다."""
    _LEDGER.path = UPLOADED_IDS_FILE
    return _LEDGER.read()


def _write_ledger(data: dict[str, list[str]]) -> None:
    """원장 원자적 기록(위임)."""
    _LEDGER.path = UPLOADED_IDS_FILE
    _LEDGER.write(data)


def record_uploaded_ids(book_id: str, ids: list[str]) -> set[str]:
    """업로드 예정 벡터 ID를 기록하고 이전 기록을 돌려준다(upsert보다 **먼저**)."""
    _LEDGER.path = UPLOADED_IDS_FILE
    previous = _LEDGER.record({book_id: ids})[book_id]
    merged = len(previous | set(ids))
    print(f"  벡터 ID {len(ids)}건 기록(누적 {merged}): {UPLOADED_IDS_FILE}")
    return previous


def finalize_uploaded_ids(book_id: str, current_ids: list[str]) -> None:
    """업로드·정리가 모두 성공한 뒤 원장을 현재 집합으로 확정한다."""
    _LEDGER.path = UPLOADED_IDS_FILE
    _LEDGER.finalize({book_id: current_ids})


def prune_stale_vectors(book: Book, current_ids: list[str], previous_ids: set[str],
                        index, allow_large: bool = False) -> None:
    """이번 업로드에 없는 이전 chunk_id 벡터를 삭제한다(위임)."""
    _LEDGER.path = UPLOADED_IDS_FILE
    _LEDGER.prune({book.book_id: current_ids}, {book.book_id: previous_ids},
                  index, NAMESPACE, batch_size=UPSERT_BATCH,
                  allow_large=allow_large, label=f"'{book.book_id}'")


def upload_book(book: Book, chunks: list[dict], openai_client: OpenAI, index,
                allow_large_prune: bool = False) -> None:
    """청크 → 임베딩 → upsert."""
    # 롤백 기록이 먼저다 — 중간에 죽어도 적재분이 추적 대상에 남는다.
    chunk_ids = [c["chunk_id"] for c in chunks]
    previous_ids = record_uploaded_ids(book.book_id, chunk_ids)

    pending: list[dict] = []

    for i in range(0, len(chunks), EMBED_BATCH):
        batch = chunks[i:i + EMBED_BATCH]
        embeddings = embed_texts([c["embed_text"] for c in batch], openai_client)

        # zip은 길이가 다르면 남는 쪽을 조용히 버린다 — 부분 성공은 오류로 처리.
        if len(embeddings) != len(batch):
            sys.exit(f"[오류] 임베딩 수 불일치: {len(embeddings)} != {len(batch)} — 업로드 중단")

        for chunk, emb in zip(batch, embeddings):
            pending.append({
                "id": chunk["chunk_id"],
                "values": emb,
                "metadata": {
                    "source_type": SOURCE_TYPE,
                    "book_id": book.book_id,
                    "title": book.title[:200],
                    "section": chunk["section"][:80],
                    "chunk_index": chunk["chunk_index"],
                    "chunk_text": chunk["chunk_text"][:900],
                    "text": chunk["chunk_text"][:900],
                },
            })

        while len(pending) >= UPSERT_BATCH:
            index.upsert(vectors=pending[:UPSERT_BATCH], namespace=NAMESPACE)
            del pending[:UPSERT_BATCH]
            time.sleep(0.1)

        time.sleep(0.2)

    if pending:
        index.upsert(vectors=pending, namespace=NAMESPACE)

    # 전량 성공 후에만 정리 — upsert는 덮어쓸 뿐 지우지 않으므로, 청킹이 줄면
    # 이전 실행의 벡터가 남아 검색에 계속 섞인다.
    prune_stale_vectors(book, chunk_ids, previous_ids, index, allow_large_prune)


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="노동법 해설서 Pinecone 업로드")
    parser.add_argument("--book", choices=sorted(BOOKS), help="업로드할 서적 ID")
    parser.add_argument("--all", action="store_true", help="BOOKS 전권 업로드")
    parser.add_argument("--dry-run", action="store_true", help="청킹만 수행")
    parser.add_argument("--allow-large-prune", action="store_true",
                        help="고아 벡터가 현재 청크의 50%%를 넘어도 삭제 진행 "
                             "(chunk_id 규격을 의도적으로 바꿨을 때만). "
                             "--book 단일 실행에서만 사용할 수 있다")
    # --reset 없음: laborlaw-v2는 판례 등 다른 소스와 공유하는 네임스페이스라
    # delete_all이 전체를 날린다. Pinecone Serverless는 메타데이터 필터 삭제를
    # 지원하지 않으므로 source_type별 부분 삭제도 불가 — 재업로드는 결정적
    # chunk_id의 upsert 덮어쓰기로 해결한다.
    args = parser.parse_args()

    if not args.book and not args.all:
        parser.error("--book <id> 또는 --all 중 하나가 필요합니다.")

    # 대량 삭제 가드 해제는 한 권씩만 허용한다. 전역 플래그로 두면 한 권 때문에
    # 켰을 때 나머지 서적의 가드까지 조용히 풀리고, Pinecone Serverless에는
    # 복구 수단이 없다. 청킹 규격을 의도적으로 바꾸는 작업은 원래 한 권씩
    # 확인하며 진행하는 것이 정상 절차다.
    # 조건은 `not args.book`이 아니라 `args.all`이어야 한다 — 두 플래그는 서로
    # 배타적이지 않고 targets를 정하는 것은 --all 쪽이라, `--book win --all
    # --allow-large-prune`이 가드를 통과한 뒤 3권 전체를 대상으로 삼았다.
    if args.allow_large_prune and args.all:
        parser.error("--allow-large-prune 은 --book 단일 실행에서만 사용할 수 "
                     "있습니다 (--all 과 함께 쓰면 다른 서적의 가드까지 풀립니다).")

    targets = list(BOOKS.values()) if args.all else [BOOKS[args.book]]

    # 전량 사전 검사 — --all에서 1권을 업로드(임베딩 비용 + 벡터 적재)한 뒤
    # 2권 파일 부재로 죽는 것을 막는다.
    for book in targets:
        for path in book.paths:
            if not os.path.exists(path):
                sys.exit(f"[오류] 원본 파일이 없습니다: {path}")

    openai_key = os.getenv("OPENAI_API_KEY")
    pinecone_key = os.getenv("PINECONE_API_KEY")

    if not args.dry_run and not openai_key:
        sys.exit("[오류] OPENAI_API_KEY가 설정되지 않았습니다.")
    if not args.dry_run and not pinecone_key:
        sys.exit("[오류] PINECONE_API_KEY가 설정되지 않았습니다.")

    openai_client = OpenAI(api_key=openai_key) if not args.dry_run else None

    index = None
    if not args.dry_run:
        from app.config import resolve_index_name
        pc = Pinecone(api_key=pinecone_key)
        index = pc.Index(resolve_index_name())

    print(f"\n{'=' * 62}")
    print(f"노동법 해설서 업로드 {'(DRY RUN)' if args.dry_run else ''}")
    print(f"네임스페이스: {NAMESPACE}  |  source_type: {SOURCE_TYPE}")
    print(f"대상: {', '.join(b.book_id for b in targets)}")
    print(f"{'=' * 62}\n")

    # ── 1단계: 전량 청킹 ──
    # 파일 존재만 보는 사전 검사로는 부족하다. 마커 미발견·헤딩 폐기율·조각별
    # 폐기율·청크 제외율은 모두 build_chunks() 안에서 중단하는데, 예전에는 그
    # 함수가 업로드와 같은 루프에 있어 **앞 서적을 임베딩·업서트한 뒤** 죽었다.
    # 청킹은 파일 읽기와 정규식뿐이라 비용이 없으므로 전량을 먼저 끝낸다.
    all_ids: set[str] = set()
    built: list[tuple[Book, list[dict]]] = []

    for book in targets:
        print(f"── {book.book_id}: {book.title}")
        chunks = build_chunks(book)

        # 서적 간 ID 충돌은 조용한 데이터 유실이라 업로드 전에 확정적으로 막는다.
        ids = {c["chunk_id"] for c in chunks}
        collision = all_ids & ids
        if collision:
            sys.exit(f"[오류] chunk_id 충돌 {len(collision)}건 "
                     f"(예: {sorted(collision)[:3]}) — 업로드 중단")
        all_ids |= ids

        for c in chunks[:2]:
            preview = c["chunk_text"][:110].replace("\n", " ")
            print(f"    [{c['chunk_id']}] {c['section']}\n      {preview}...")
        built.append((book, chunks))
        print()

    # ── 2단계: 업로드 ──
    if not args.dry_run:
        for book, chunks in built:
            print(f"── 업로드: {book.book_id} ({len(chunks)}청크)")
            upload_book(book, chunks, openai_client, index, args.allow_large_prune)
            print()

    total_chunks = sum(len(c) for _, c in built)
    print(f"{'=' * 62}")
    print(f"총 청크 수: {total_chunks}  |  고유 벡터 ID: {len(all_ids)}")
    print(f"=== 완료 {'(DRY RUN)' if args.dry_run else ''} ===")
    print(f"{'=' * 62}\n")


if __name__ == "__main__":
    main()
