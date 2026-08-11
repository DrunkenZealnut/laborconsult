# textbook-corpus-embedding Design

> Plan: `docs/01-plan/features/textbook-corpus-embedding.plan.md`
> 작성일: 2026-08-10

## 1. 설계 개요

노동법 해설서 2권의 본문을 `laborlaw-v2`에 `source_type="textbook"`으로 임베딩하고
(Track A), 같은 서적이 인용하는 판례 중 코퍼스에 없는 166건을 법제처 공개 API로
수집한다(Track B). **두 트랙은 서로 독립적이며 어느 쪽이 실패해도 다른 쪽은 완결된다.**

Track A는 저작물 본문을 코퍼스에 넣는 첫 사례이므로, 인용 가드 5종(G1~G5)을
**업로드보다 먼저** 구현한다.

### 1.1 모듈 구성

```text
[Track A — 본문]
output_노동법교재/Win노동법_merged.md          (기존, gitignore)
output_노동법교재/근로기준법주해3_임금.md       (신규 반입, gitignore)
        │
        ▼
pinecone_upload_textbook.py                    [수정] 서적 레지스트리화
        │  ├─ load_body(book)      표지·목차 절단 + 명시 치환
        │  ├─ sanitize_heading()   [신규] OCR 손상 헤딩 폐기/복원
        │  ├─ parse_sections()     폐기 헤딩은 직전 섹션에 흡수
        │  └─ chunk_section()      textbook_{book_id}_{sec:04d}_{chunk}
        ▼
Pinecone laborlaw-v2  (source_type="textbook", book_id="win"|"juhae3")
        │
        ▼  검색 시
app/core/rag.py::format_pinecone_hits
        └─ _cap_by_book()  [신규 G4] 동일 서적 최대 3청크

[Track B — 인용 판례]
(위 두 .md)
        │
        ▼
extract_textbook_cases.py                      [신규] 사건번호 추출·대조
        │  ├─ 사건부호 화이트리스트
        │  ├─ 기존 코퍼스 1,319건 대조 (L2 재사용)
        │  └─ _미발견.csv 110건 차감
        ▼
output_노동법교재/누락_판례목록_교재통합.csv    (166행)
        │
        ▼
fetch_court_precedents.py --input <csv>        [수정] 입력 경로 주입
        ▼
output_판례_보강/*.md → pinecone_upload_court_precedents.py
        ▼
Pinecone laborlaw-v2  (source_type="precedent")

[공통 마무리]
build_bm25_corpus.py → data/bm25_corpus.json.gz  [커밋 필수]
```

### 1.2 확정 수치 (위생 처리 적용 후 실측)

| 서적 | book_id | 헤딩 | 유지 | 섹션 | **청크** |
|------|---------|------|------|------|----------|
| 근로기준법 주해 Ⅲ(임금) | `juhae3` | 158 | 150 (폐기 8, 5.1%) | 144 | **460** |
| Win 노동법 | `win` | 1,229 | 1,214 (폐기 15, 1.2%) | 920 | **1,407** |
| **합계** | | | | 1,064 | **1,867** |

> Plan의 1,877은 위생 처리 전 수치다. 폐기 헤딩의 본문이 직전 섹션에 흡수되면서
> 청크가 10개 줄었다. **1,867이 확정치**이며 완료 기준도 이 값을 쓴다.

---

## 2. 서적 레지스트리와 벡터 ID (Plan D1)

### 2.1 왜 서적 식별자가 필수인가 — 실측된 충돌

현행 `chunk_id`는 `textbook_{heading_idx:04d}_chunk_{idx}`로, **서적을 구분하지 않는다.**
현행 스크립트를 그대로 두 서적에 적용하면:

```
Win 1,414청크 / 주해Ⅲ 463청크
→ ID 충돌 177건 (주해Ⅲ 청크의 38%가 Win 벡터를 덮어쓴다)
```

Pinecone `upsert`는 같은 ID를 조용히 덮어쓴다. **오류도, 경고도 없다.** CLAUDE.md에
기록된 NFD post_id 충돌(판례 836개 → 고유 362개, 474개 유실)과 동일한 실패 모드다.

### 2.2 Book 레지스트리

```python
@dataclass(frozen=True)
class Book:
    book_id: str          # ^[a-z0-9]+$ — chunk_id 구성요소라 구분자 금지
    title: str            # 메타데이터 title (출처 표기에 그대로 노출)
    path: str
    body_start: str       # 표지·목차 절단 마커
    ocr_fixes: dict[str, str]   # 헤딩 명시 치환 (§3.3)

BOOKS = {
    "win": Book(
        book_id="win",
        title="Win 노동법(2025, 공인노무사·5급공채·변호사시험 대비)",
        path="output_노동법교재/Win노동법_merged.md",
        body_start="<!-- page: 18 -->",
        ocr_fixes=WIN_OCR_FIXES,          # 기존 KNOWN_OCR_FIXES 이관
    ),
    "juhae3": Book(
        book_id="juhae3",
        title="근로기준법 주해 Ⅲ — 임금(제2판 수정증보판)",
        path="output_노동법교재/근로기준법주해3_임금.md",
        body_start="<!-- page: 6 -->",
        ocr_fixes=JUHAE3_OCR_FIXES,
    ),
}
```

`body_start` 근거 — 주해 Ⅲ는 1~5페이지가 표지·목차이고 `<!-- page: 6 -->` 직후에
`# 제 3장 임 금`이 나온다. 목차 페이지는 marker가 표 구조를 깨뜨려 글자 스프만 남는다
(Win의 `<!-- page: 18 -->`과 같은 이유).

### 2.3 chunk_id 규격

```
textbook_{book_id}_{section_idx:04d}_{chunk_idx}
예) textbook_juhae3_0000_0
    textbook_win_0919_2
```

- `book_id`에 `_`가 없으므로 파싱이 모호해지지 않는다 (`^[a-z0-9]+$` 강제)
- 결정적 ID이므로 재업로드는 upsert 덮어쓰기로 처리 — `--reset` 금지는 유지
  (`laborlaw-v2`는 판례·행정해석과 공유하는 네임스페이스라 `delete_all`이 전체를 날린다)
- `section_idx`는 **위생 처리 후 유지된 섹션의 순번**이다. 폐기 헤딩은 번호를 소비하지
  않는다 — 소비하면 `ocr_fixes` 한 줄만 바뀌어도 뒤쪽 ID가 전부 밀려 고아 벡터가 생긴다

### 2.4 마이그레이션 불요

`laborlaw-v2`의 `textbook` 벡터는 **실측 0건**(BM25 코퍼스 62,315건 대조)이다.
기존 ID를 재작성할 대상이 없으므로 신규 체계를 그대로 적용한다.

---

## 3. 헤딩 위생 처리 (Plan D5)

### 3.1 두 가지 실패 모드

헤딩은 `section` 메타데이터이자 `embed_text` 접두사(`섹션: {heading}`)로 두 번 쓰인다.
손상되면 검색 품질과 출처 표시가 함께 망가진다. 실패는 두 종류다.

| 종류 | 예 | 처리 |
|------|-----|------|
| **복원 불가** — 의미가 남지 않은 OCR 잔해 | `$I.99$`, `!!!!!!!!!…`, `(K M 3장 임 금 C K` | **폐기** — 섹션 경계로 쓰지 않고 본문을 직전 섹션에 흡수 |
| **복원 가능** — 유효 표제 + 잡음 꼬리 | `Ⅱ. 출국금지의 해제요청 800 2000 028 28 28 9 10 12` | **명시 치환** (§3.3) |

> **설계 원칙**: 폐기 판정만 범용 규칙으로 하고, 복원은 명시 치환으로 한다.
> 잘못 폐기해도 본문은 그대로 보존되고 섹션 경계 하나가 사라질 뿐이지만, 잘못 복원하면
> 코퍼스에 오정보가 들어간다. 선행 사이클의 "범용 보정 로직 대신 명시 치환" 관례는
> 이 비대칭을 지키기 위한 것이므로, 위험한 쪽(복원)에만 적용한다.

### 3.2 `sanitize_heading()` 규격 (실데이터 검증 완료)

```python
_MARK    = re.compile(r"</?mark>")
_TEX     = re.compile(r"\$[^$]*\$")
_ART     = re.compile(r"(제\d+조(?:의\d+)?\s*\([^)]{1,30}\))")
_MEANING = re.compile(r"[가-힣一-龥ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]")
_SIGNIF  = re.compile(r"[^\s.·…\-—,、]")      # 비율 분모: 공백·구두점 제외
MIN_LEN, MAX_LEN, MIN_RATIO = 3, 60, 0.35

def sanitize_heading(raw: str, ocr_fixes: dict) -> str | None:
    """정제된 헤딩, 또는 폐기 대상이면 None."""
    h = ocr_fixes.get(raw.strip(), raw)          # ① 명시 치환이 최우선
    s = _MARK.sub("", h).replace("**", "")
    m = _ART.search(s)                            # ② 조문 표기가 있으면 길이 무관하게 그것만
    if m:
        return re.sub(r"\s+", "", m.group(1))
    s = _TEX.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip(" .·…-—")
    if not (MIN_LEN <= len(s) <= MAX_LEN):        # ③ 과단/과장 폐기
        return None
    denom = len(_SIGNIF.findall(s))
    if denom == 0 or len(_MEANING.findall(s)) / denom < MIN_RATIO:
        return None                               # ④ 의미문자 비율 미달 폐기
    return s
```

설계상 주의점 셋 — 모두 프로토타이핑에서 실제로 걸린 것들이다.

1. **비율 분모에서 공백·구두점을 빼야 한다.** 원문 헤딩은 `2. 요 건`처럼 자간 공백이
   흔한데, 분모를 전체 길이로 잡으면 2/6 = 0.33 < 0.35로 **정상 표제가 오폐기된다.**
   `_SIGNIF` 분모(`2요건` → 2/3 = 0.67)로 바꿔 해소했다.
2. **조문 표기 추출은 길이 검사보다 먼저** 해야 한다. `지역 이 이 이 시 시 <mark>제43조의5(업무위탁 등)</mark> 기회에 …`은
   59자라 `MAX_LEN=60` 검사를 아슬아슬하게 통과해 잡음이 그대로 살아남았다.
3. **`ocr_fixes`는 원문 문자열 기준**으로 매칭한다. 정제 후에 매칭하면 정제 과정이
   바뀔 때마다 치환 키가 조용히 무효가 된다.

### 3.3 명시 치환 목록 (`JUHAE3_OCR_FIXES`)

| 원문 헤딩 | 치환 |
|-----------|------|
| `**Ⅰ. 최저임금의 결정기준** 나는 다시 보도 모든 이 모든 바로 유료되었다.` | `Ⅰ. 최저임금의 결정기준` |
| `Ⅱ. 최저임금 결정절차 [○ 1901 19121212 - 1910 12 12 …` | `Ⅱ. 최저임금 결정절차` |
| `Ⅱ. 출국금지의 해제요청 800 2000 028 28 28 9 10 12` | `Ⅱ. 출국금지의 해제요청` |
| `$\text{I\hspace{-.1em}I}$ . 보조ㆍ지원 제한의 예외 $…$ 에서 대한 일정 INSES …` | `Ⅱ. 보조·지원 제한의 예외` |

`WIN_OCR_FIXES`는 기존 `KNOWN_OCR_FIXES` 1건을 그대로 이관한다.

### 3.4 실측 결과와 안전장치

| 서적 | 헤딩 | 유지 | 폐기 | 폐기율 |
|------|------|------|------|--------|
| 주해 Ⅲ | 158 | 150 | 8 | 5.1% |
| Win 노동법 | 1,229 | 1,214 | 15 | 1.2% |

폐기 8건은 전량 실제 OCR 잔해임을 육안 확인했다(`$I.99$`, `$/대 모 키$`, `$I.7$ $A$`,
`$I.$ $\vec{A}$ $\vec{A}$`, `$I.7$ $A$`, `!!!!!!…`, `(K M 3장 임 금 C K`, `$1.9$ 의`).

**안전장치**: 폐기율이 **10%를 넘으면 업로드를 중단**한다(`sys.exit`). 규칙이 오작동하거나
새 서적의 마크다운 관례가 다를 때 조용히 섹션을 뭉개는 것을 막는다.

**분모는 반드시 '유지된 헤딩 수'다 (U-4)** — `parse_sections()`는 본문이 빈 섹션을 결과에서
제외하므로 `len(sections)`를 분모로 쓰면 폐기율이 부풀려져 **정상 서적이 게이트에 걸린다**
(실측: Win 1.2%가 1.6%로 오보). 그래서 `parse_sections()`는 `(sections, kept_headings,
dropped)` 3튜플을 반환하고 `check_drop_rate()`가 `kept + dropped`를 분모로 쓴다.

### 3.5 `enrich_court_precedents.py` 호환

이 스크립트는 `pinecone_upload_textbook.py::load_body`에 의존한다(선행 사이클 설계 §245).
`load_body(book: Book)`로 시그니처가 바뀌므로 **호출부를 함께 수정**한다.

**단순 인자 교체로는 부족하다 (U-3)** — enrich는 청킹이 아니라 본문을 통째로 훑어 표제
경로를 뽑으므로 **위생 처리가 적용된 마크다운**이 필요하다. 위생 규칙을 enrich에 복제하면
단일 출처가 깨지므로, `load_body_normalized(book)` 헬퍼를 두어 헤딩 라인을 정제된 형태로
치환(폐기분은 줄 제거, 본문은 보존)한 마크다운을 반환한다.

부수 효과 — 판례 인용문이 표제로 오인식되던 15건이 실제 표제로 교정되고(예:
`기타 원칙 › 대법원 2024.6.27. 선고 2020도16541 판결 :` → `기타 원칙 › 근로조건의 명시`),
잡음 표제로만 태깅되던 2건이 라벨을 잃는다(770 → 768). enrich를 재실행하지 않으면 기존
태그는 그대로다.

---

## 4. 인용 가드 (Plan D4)

### 4.1 배치

| 가드 | 성격 | 위치 |
|------|------|------|
| G1 축자 인용 금지 | 소프트(프롬프트) | `app/templates/prompts.py::CONSULTATION_SYSTEM_PROMPT` |
| G2 단독 근거 금지 | 소프트(프롬프트) | 〃 |
| G3 출처 표기 강제 | 소프트(프롬프트) + 컨텍스트 헤더 | 〃 + `rag.py::format_pinecone_hits` |
| **G4 동일 서적 청크 상한** | **구조적** | `rag.py::_cap_by_book()` |
| G5 출처 라벨 | 표시 | `rag.py` + `public/index.html` |

원문 조각의 외부 노출 표면은 이미 닫혀 있다 — `_build_sources_payload()`는 주석에
명시된 대로 `chunk_text`를 제외하고 제목·출처 메타만 프론트로 보낸다. 따라서 SSE
`sources` 이벤트와 공개 게시판에는 본문 조각이 나가지 않는다. **가드는 LLM 컨텍스트
단계에만 필요하다.**

### 4.2 G4 — `_cap_by_book()` (구조적 상한)

```python
MAX_CHUNKS_PER_BOOK = 3
_TEXTBOOK_ID_RE = re.compile(r"^textbook_([a-z0-9]+)_")

def _book_id_of(hit: dict) -> str:
    """hit의 해설서 식별자. 해설서가 아니면 빈 문자열."""
    book = (hit.get("book_id") or "").strip()
    if book:
        return book
    m = _TEXTBOOK_ID_RE.match(hit.get("id") or "")
    if m:
        return m.group(1)
    # 서적을 특정하지 못해도 해설서면 상한은 걸어야 안전하다.
    return "_unknown" if hit.get("source_type") == "textbook" else ""

def _cap_by_book(hits: list[dict], limit: int = MAX_CHUNKS_PER_BOOK) -> list[dict]:
    """동일 서적 청크를 limit개로 제한. 순위 순서는 보존."""
    counts: dict[str, int] = {}
    out = []
    for h in hits:
        book = _book_id_of(h)
        if not book:                     # 해설서가 아닌 소스는 무제한
            out.append(h)
            continue
        counts[book] = counts.get(book, 0) + 1
        if counts[book] <= limit:
            out.append(h)
    return out
```

**`book_id`는 메타데이터만으로 부족하다 (U-1·U-2)** — BM25 코퍼스는
`{id, text, title, section, source_type}`만 담아 `book_id`가 없다. 메타데이터만 믿으면
**BM25로 올라온 해설서 청크가 G4를 그대로 빠져나간다.** 두 겹으로 막는다:

1. `build_bm25_corpus.py`가 코퍼스에 `book_id`를 보존하고 `bm25_search.py`가 결과 dict에
   실어 보낸다 — 정본 경로
2. `_book_id_of()`가 벡터 ID(`textbook_{book_id}_...`)에서 되뽑는다 — 구 코퍼스·신규 소스 대비

**세 번째 단계인 `"_unknown"` 센티널이 fail-closed를 보장한다** — 1·2가 모두 실패해도
`source_type == "textbook"`인 hit은 한 버킷으로 묶여 상한이 걸린다(권당 3이 아니라 전체 3이라
오히려 더 엄격해진다). 즉 **가드 무결성은 센티널이 지키고, 1·2는 서적별 granularity(검색 품질)를
지킨다.** 세 단계 모두 역할이 달라 어느 하나도 "중복"이 아니다.

`build_bm25_corpus.py`는 **`book_id` 값이 있을 때만** 키를 넣는다 — 무조건 넣으면 6번째 키가
CPython dict를 8→16슬롯으로 리사이즈시켜 문서당 +88B, 코퍼스 전체 상주 메모리 +5.7MB가 된다
(코퍼스의 97%가 해설서가 아니다). 소비자 3곳이 모두 부재를 흡수하므로 안전하다.

**적용 지점은 `format_pinecone_hits()` 진입부** — 이 함수는 `pipeline.py:1640` 단
한 곳에서만 호출되는 초크포인트다(전수 확인). 여기 두면 호출부를 늘려도 가드가 새지
않고, `pipeline.py` 수정이 불필요하다. 컨텍스트에서 빠진 청크는 `meta_list`에서도
빠지므로 인용 화이트리스트와 자동으로 일치한다.

`_query_namespaces()`가 `book_id`를 hit dict에 실어야 한다 — 메타데이터에서
`meta.get("book_id", "")`를 읽어 추가한다(§6).

**트레이드오프**: rerank 상위 5건이 모두 같은 서적이면 컨텍스트가 3건으로 줄어든다.
상위 슬롯을 다른 소스로 백필하지는 않는다 — 그 시점엔 이미 상위 N건만 남아 있어
백필 후보가 없고, 후보를 다시 끌어오려면 검색을 한 번 더 돌려야 한다. 컨텍스트가
얇아지는 쪽을 수용한다(가드가 목적이므로).

드롭 발생 시 `logger.info`로 서적·드롭 수를 남긴다 — 가드가 실제로 작동하는지
관측할 수 있어야 한다.

### 4.3 G1~G3 — 프롬프트 규칙

`CONSULTATION_SYSTEM_PROMPT`의 `5-1. 판례·행정해석 인용 규칙` 바로 뒤에 `5-1-b`로
삽입한다(기존 인용 규칙과 같은 "절대 규칙" 블록에 두어야 모델이 동급으로 취급한다).

```text
5-1-b. **해설서 인용 규칙** (절대 규칙 — 반드시 준수):
   참고 자료에 [노동법 해설서]로 표시된 항목은 저작권이 있는 출판물입니다.
   ① 원문 문장을 그대로 옮기지 마세요. 반드시 자신의 표현으로 요약·재진술하세요.
   ② 해설서만을 근거로 결론을 내리지 마세요.
      법조문 또는 판례로 뒷받침되지 않으면 "해석상 논의가 있습니다"로 서술하세요.
   ③ 해설서를 근거로 쓸 때는 서명을 표기하세요. 예: "「근로기준법 주해 Ⅲ」의 설명에 따르면"
   ④ 해설서를 인용하면서 저자명·면수를 지어내지 마세요 — 자료에 있는 서명만 씁니다.
```

`COMPOSER_SYSTEM`에는 **추가하지 않는다.** 전수 확인 결과 `app/templates/prompts.py:325`에
정의만 있고 import하는 곳이 없다(`composer.py`는 `compose_follow_up()`만 남은 legacy).
죽은 프롬프트를 함께 고치면 "두 곳을 동기화해야 한다"는 잘못된 유지보수 의무가 생긴다.

### 4.4 컨텍스트 헤더 (G3 보조)

`format_pinecone_hits()`의 헤더는 현재 `[{source_label}] {title} — {section}`이다.
`title`이 서명(`근로기준법 주해 Ⅲ — 임금(제2판 수정증보판)`)이므로 라벨만 추가하면
G3③이 요구하는 서명이 자동으로 컨텍스트에 들어간다. 별도 포맷 변경은 불필요하다.

---

## 5. 출처 라벨 (Plan D2)

두 곳 모두 `textbook` 키가 없어 원문이 그대로 노출된다. 같은 문자열로 채운다.

| 위치 | 변경 |
|------|------|
| `app/core/rag.py::format_pinecone_hits` 라벨 맵 | `"textbook": "노동법 해설서"` 추가 |
| `public/index.html::renderSources` 의 `labels` | `textbook: '노동법 해설서'` 추가 |

`public/sw.js`의 `VERSION`을 올린다 — `ASSET_PATTERN`이 js를 포함해 cache-first이므로
올리지 않으면 낡은 `index.html`이 남아 라벨이 반영되지 않는다(실패가 조용하다).

---

## 6. 벡터 메타데이터 스키마

```python
{
    "source_type": "textbook",
    "book_id":     book.book_id,          # [신규] G4 + 서적별 롤백 키
    "title":       book.title[:200],
    "section":     chunk["section"][:80],
    "chunk_index": chunk["chunk_index"],
    "chunk_text":  chunk["chunk_text"][:900],
    "text":        chunk["chunk_text"][:900],
}
```

- `CHUNK_MAX=700`이므로 `[:900]`에서 실제 절단은 일어나지 않는다(기존 동작 유지)
- `book_id`는 Pinecone 메타데이터 필터에도 쓸 수 있으나, **Serverless는 메타데이터
  필터 삭제를 지원하지 않는다.** 롤백은 §9의 ID 목록 파일로 명시 삭제한다

---

## 7. Track B — 인용 판례 수집

### 7.1 `extract_textbook_cases.py` (신규)

```
입력: BOOKS 레지스트리의 .md (본문만 — load_body 재사용)
출력: output_노동법교재/누락_판례목록_교재통합.csv  (사건번호,법원,인용횟수,출처서적)
```

처리 순서:
1. 본문 로드(표지·목차 제외) → `OCR_FIXES` 적용
2. 사건번호 추출 (§7.2)
3. `collect_existing_case_numbers(EXISTING_DIRS)` 재사용 → 기보유 1,319건 차감
4. `output_판례_보강/_미발견.csv` 110건 차감 — 법제처 DB 미수록분이라 재시도해도 회수 불가
5. 인용횟수 내림차순 정렬 후 CSV 기록

`법원` 컬럼은 사건부호로 추정한다(`헌*` → 헌법재판소, 그 외 → 대법원).
`fetch_court_precedents.py::resolve_target()`이 사건번호 부호로 최종 판정하므로
CSV 컬럼이 틀려도 라우팅은 안전하다(선행 설계 §140의 확립된 방어).

### 7.2 사건부호 화이트리스트 — 필수

기존 `CASE_NO_RE = (\d{2,4}[가-힣]{1,4}\d+)`를 그대로 쓰면 **조문 표기를 사건번호로
오인한다.** 실측:

```
화이트리스트 없음 → 주해Ⅲ에서 308건 추출, 그중 113건이 노이즈
   상위 오탐: '43조의2'(31회) '43조의4'(28) '43조의3'(19) '43조1'(15) '109조2'(7)
화이트리스트 적용 → 195건 (전량 유효)
```

주해 Ⅲ는 조문 해설서라 조문 표기 밀도가 판례 수험서보다 훨씬 높다 — 이 오탐은
Win 노동법에서는 눈에 띄지 않았을 수 있다.

```python
CASE_CODES = ("다카|재다|재두|재누|다|두|도|누|므|프|마|카|그|후|허|초|오|모|추|우|즈|드|"
              "나|노|라|가합|가단|가소|구합|구단|고합|고단|카합|카단|카기|비합|인|"
              "헌바|헌마|헌가|헌라|헌나|헌사|헌아")
CASE_RE = re.compile(rf"(?<![0-9])(\d{{2,4}})\s*({CASE_CODES})\s*(\d+)(?![0-9])")
```

- **긴 부호를 먼저** 나열해야 한다(`다카` 앞에 `다`가 오면 `87다카2803`이 `87다`로 잘린다)
- `\s*`는 교재 원문의 `95다 53188` 표기를 흡수한다(선행 설계 §243의 기지 사항)
- 앞뒤 `(?<![0-9])` / `(?![0-9])`로 긴 숫자열 중간 오매칭을 막는다

### 7.3 `fetch_court_precedents.py --input`

```python
parser.add_argument("--input", metavar="CSV",
                    help="입력 CSV 경로 (기본: output_노동법교재/누락_판례목록.csv). "
                         "L2 중복검사는 유지된다 — 신규 수집용")
input_csv = args.cases or args.input or INPUT_CSV
```

`--cases`(L2 생략, 겹침분 재수집용)와 **의미가 다르므로 별도 플래그**로 둔다.
`--cases`를 신규 수집에 쓰면 중복검사가 꺼져 이미 보유한 판례를 다시 받는다.
둘이 동시에 오면 `--cases`가 이긴다(기존 동작 보존).

### 7.4 예상 수확

| 서적 | 고유 | 기보유 | 누락 | 미발견 차감 | 실대상 |
|------|------|--------|------|-------------|--------|
| 주해 Ⅲ | 195 | 63 | 132 | −3 | 129 |
| Win | 928 | 788 | 140 | −98 | 42 |
| 합집합 | | | 264 | −98 | **166** |

선행 사이클 실수집률 83%를 적용하면 약 138건 예상이었으나, **실측은 120건(72.3%)이다**(U-6).
교재 인용 판례는 하급심·구판례 비중이 높아 법제처 DB 미수록률이 선행 사이클보다 높다 —
후속 사이클 예측 기준선은 **72%**를 쓸 것. 미달분은 `_미발견.csv`에 누적된다(110 → 156건).

---

## 8. 테스트 계획

`test_precedent_ingest.py`를 확장한다(오프라인·API 키 불요, CI 실행 대상).

| ID | 검증 | 근거 |
|----|------|------|
| T15-a | 두 서적 chunk_id 교집합 = 0 | R1 — 현행 체계에서 177건 충돌 실측 |
| T15-b | `book_id`에 `_` 포함 시 거부 | ID 파싱 모호성 차단 |
| T15-c | 폐기 헤딩이 `section_idx`를 소비하지 않음 | ocr_fixes 변경 시 ID 밀림 방지 |
| T16-a | `2. 요 건` 유지 (자간 공백 오폐기 회귀) | §3.2 주의점 1 |
| T16-b | `$I.99$`·`!!!!!!` 폐기 | 잔해 제거 |
| T16-c | 59자 + `<mark>제43조의5(업무위탁 등)</mark>` → `제43조의5(업무위탁등)` (§3.2의 `re.sub(r"\s+", "", …)`가 괄호 내부 공백까지 제거) | §3.2 주의점 2 |
| T16-d | `ocr_fixes`는 원문 키로 매칭 | §3.2 주의점 3 |
| T16-e | 폐기 헤딩의 본문이 직전 섹션에 흡수됨(유실 없음) | 본문 보존 |
| T17-a | 동일 `book_id` 4건 → 3건으로 컷 | G4 |
| T17-b | `book_id` 없는 hit는 무제한 | 판례·행정해석 회귀 |
| T17-c | 컷 후에도 rerank 순서 보존 | 순위 무결성 |
| T17-d | `meta_list`도 함께 컷 (인용 화이트리스트 일치) | 인용 검증 정합 |
| T18-a | `43조의2`·`109조2`가 사건번호로 잡히지 않음 | §7.2 실측 오탐 |
| T18-b | `87다카2803`이 `87다`로 잘리지 않음 | 부호 정렬 순서 |
| T18-c | `95다 53188` → `95다53188` | 공백 표기 |
| T18-d | `98헌마141` 추출 | 헌재 부호 |

수동 검증(API 필요):
- 업로드 후 `laborlaw-v2` `textbook` 벡터 1,867건
- 검색 양성 — "최저임금 산입범위", "임금 직접지급 원칙 예외", "휴업수당 산정" 3종
- 답변 표본 3건에서 G1(축자 인용 0건) · G3(서명 표기) 확인

---

## 9. 구현 순서

가드와 ID 체계가 **업로드보다 먼저**여야 한다. 순서를 바꾸면 R1(조용한 덮어쓰기)과
D4(무가드 노출)가 그대로 발생한다.

| # | 작업 | 산출 |
|---|------|------|
| 1 | 주해 Ⅲ 원본을 `output_노동법교재/근로기준법주해3_임금.md`로 반입 | (비커밋) |
| 2 | `sanitize_heading()` + `JUHAE3_OCR_FIXES` 구현, 폐기율 상한 | `pinecone_upload_textbook.py` |
| 3 | `Book` 레지스트리 + `book_id` 스코프 chunk_id + `--book/--all` | 〃 |
| 4 | `enrich_court_precedents.py`의 `load_body` 호출부 동기화 | `enrich_court_precedents.py` |
| 5 | T15~T17 작성 → **통과 확인** | `test_precedent_ingest.py` |
| 6 | G1~G3 프롬프트, G4 `_cap_by_book`, G5 라벨 2곳, `sw.js` VERSION | `prompts.py`·`rag.py`·`index.html`·`sw.js` |
| 7 | `--dry-run`으로 460 / 1,407 청크 + ID 교집합 0 확인 | 콘솔 |
| 8 | 업로드 (`--all`) + **chunk_id 목록을 파일로 보존** | `output_노동법교재/_uploaded_ids.json` |
| 9 | `extract_textbook_cases.py` + T18 | 신규 |
| 10 | `fetch_court_precedents.py --input` + 수집 실행 | 166건 → 약 138건 |
| 11 | `pinecone_upload_court_precedents.py --dry-run` → 업로드 | |
| 12 | `build_bm25_corpus.py` → `.gz` **커밋** | `data/bm25_corpus.json.gz` |
| 13 | 검색 양성 + 답변 표본 가드 확인 | |
| 14 | `CLAUDE.md` 갱신 | |

**롤백 경로** — 8단계에서 저장한 `_uploaded_ids.json`으로 `index.delete(ids=..., namespace="laborlaw-v2")`.
Pinecone Serverless는 메타데이터 필터 삭제를 지원하지 않으므로 ID 목록이 유일한 수단이다.
이 파일이 없으면 Track A를 되돌릴 방법이 사실상 없다.

---

## 10. 확정된 의사결정

| # | 사항 | 결정 | 근거 |
|---|------|------|------|
| 1 | 저작물 본문 업로드 | **한다** (인용 가드 5종 전제) | Plan §3 — 사용자 확정 |
| 2 | 대상 서적 | 주해 Ⅲ + Win 노동법 2권 | 사용자 확정 |
| 3 | 네임스페이스 | `laborlaw-v2` 공유 (별도 분리 안 함) | 그룹 A 병렬 검색 경로를 그대로 타야 검색에 반영된다 |
| 4 | `--reset` | 계속 금지 | 공유 네임스페이스 — `delete_all`이 판례까지 날린다 |
| 5 | 헤딩 복원 | 명시 치환만, 범용 보정 없음 | 오복원 = 오정보. 폐기만 범용화 |
| 6 | 서적당 청크 상한 | 3 | 구조적 가드. 컨텍스트 축소는 수용 |
| 7 | `COMPOSER_SYSTEM` 수정 | **안 함** | 사용처 0 — 죽은 동기화 의무 생성 방지 |
| 8 | 주해 Ⅲ 부분본(187p) | 그대로 진행 | 수록 범위가 최다 상담 주제와 일치. `book_id` 체계가 증분 업로드를 보장 |

### 비목표 (이번 범위 밖)

- `output_판례_보강/`의 하급심 미수집분 회수 — 법제처 DB 미수록분이라 경로가 없다
- 주해 Ⅲ 나머지 장(제7~11장) — 원본 PDF에 없다
- 주해 Ⅲ 목차 기반 쟁점 태깅 확장 — 본문에 실재하는 헤딩이 제한적이라 이득이 작다.
  필요해지면 후속 사이클로
- 교재 벡터의 서적별 부분 삭제 API — Serverless 제약. ID 목록 방식으로 대체

---

## 변경 이력

| 버전 | 일자 | 내용 | 작성 |
|------|------|------|------|
| 1.0 | 2026-08-10 | Design 최초 작성. chunk_id 충돌 177건 실측, 헤딩 위생 규칙 두 서적 검증(폐기율 5.1%/1.2%), 확정 청크 1,867 | DrunkenZealnut |
| 1.1 | 2026-08-10 | Check 결과 반영 — U-1·U-2 `_book_id_of` 벡터 ID 폴백 + BM25 `book_id` 전파 2중 구조(G4 우회 차단), U-3 `load_body_normalized` 단일 출처, U-4 폐기율 분모 교정, U-5 §8 T16-c 기대값 정정, U-6 수확률 83%→72% 실측 | DrunkenZealnut |
