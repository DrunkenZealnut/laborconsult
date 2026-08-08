# precedent-corpus-expansion Design

> Plan: `docs/01-plan/features/precedent-corpus-expansion.plan.md`
> 작성일: 2026-08-09

## 1. 설계 개요

교재에서 추출한 사건번호 601건을 법제처 Open API로 조회해 판례 원문을 수집하고,
3단계 중복 방지를 거쳐 마크다운으로 정규화한 뒤 `laborlaw-v2` 네임스페이스에
임베딩한다. **교재 본문은 사용하지 않는다 — 사건번호(사실 정보)만 입력으로 쓴다.**

### 1.1 모듈 구성

```
output_노동법교재/누락_판례목록.csv   (입력, 601행)
        │
        ▼
fetch_court_precedents.py            [신규] 수집 + 마크다운 생성
        │  ├─ 법제처 lawSearch.do  (target=prec | detc)
        │  ├─ 정확일치 게이트 (<사건번호> 검증)
        │  └─ 법제처 lawService.do (상세)
        ▼
output_판례_보강/*.md                (~568건, gitignore)
output_판례_보강/_progress.json      (재개용)
output_판례_보강/_미발견.csv         (실패 목록)
        │
        ▼
pinecone_upload_court_precedents.py  [신규] 청킹 + 임베딩 + 업로드
        │
        ▼
Pinecone laborlaw-v2 (source_type="precedent")
        │
        ▼
build_bm25_corpus.py → data/bm25_corpus.json.gz  [커밋 필수]
```

CLAUDE.md의 "새 코퍼스 소스 추가 시 `crawl_*` → `generate_metadata_*` →
`pinecone_upload_*` 3종을 함께 추가" 관례를 따르되, `generate_metadata_*`는
생략한다 — `nodong_counsel`·`output_법원 노동판례` 등 판례·상담 계열 소스가
모두 metadata.json 단계 없이 upload 스크립트가 `.md`를 직접 파싱하는 방식이다.

---

## 2. 왜 `pinecone_upload_legal.py` 확장이 아니라 신규 스크립트인가

Plan §2 Phase 4는 기존 스크립트 확장을 상정했으나, **설계 단계에서 치명적 결함을
확인해 신규 스크립트로 변경한다.**

### 2.1 확인된 결함 — macOS NFD 파일명과 사건번호 정규식 불일치

`pinecone_upload_legal.py::extract_post_id()` (L162)

```python
case_m = re.match(r"(\d{4}[다두도가누마재추허][A-Za-z가-힣]*\d+)", basename)
```

macOS는 파일명을 **NFD(자모 분해)** 로 저장한다. `2020다242423_...`의 "다"는
`U+B2E4`가 아니라 `U+1103 U+1161`(ᄃ+ᅡ) 두 코드포인트다. 문자 클래스는 완성형
글자만 담고 있어 **매치가 항상 실패**하고, 폴백 `re.match(r"(\d+)", basename)`이
연도 4자리만 잡는다.

실측(`output_법원 노동판례` 836개 파일):

| 조건 | 고유 post_id | 덮어쓰기 손실 |
|------|:---:|:---:|
| 현재 코드 그대로 | **362** | **474건 (57%)** |
| `unicodedata.normalize("NFC", ...)` 적용 시 | 836 | 0건 |

`chunk_id = f"{source_type}_{post_id}_chunk_{idx}"`이므로 2020년 판례 78건이
전부 `precedent_2020_chunk_N`으로 충돌해 서로를 덮어쓴다.

### 2.2 이번 데이터에서의 영향

추가로 정규식이 `\d{4}`(4자리 연도)를 요구해 **2자리 연도 사건번호 277건(46%)**
(`90누9421`, `86다카24445`, `98헌마141` …)이 아예 매치되지 않는다.
`_KR_TO_ASCII`에 `헌`·`바`·`카`가 없어 `2011헌바395` → `2011`로 뭉개진다.

601건에 그대로 적용 시 **22개 충돌 그룹, 259건(43%) 소실**로 계산된다
(`94` ← 36건, `91` ← 35건, `92` ← 34건 …).

### 2.3 결론

- 신규 `pinecone_upload_court_precedents.py`를 만들어 **ID 생성을 직접 통제**한다.
- 기존 `pinecone_upload_legal.py`의 NFD 버그는 **이번 범위 밖**이지만 실재하는
  결함이므로 §8에 후속 과제로 기록한다. (`precedent` 네임스페이스는 현재
  프로덕션 검색 대상이 아니라 사용자 영향은 없다 — `rag.py::NS_GROUP_LAW`는
  `laborlaw-v2`만 조회한다.)

---

## 3. 수집 모듈 — `fetch_court_precedents.py`

### 3.1 API 스펙 (실측 확인)

**검색**: `GET http://www.law.go.kr/DRF/lawSearch.do`
`OC={LAW_API_KEY}&target={prec|detc}&type=XML&query={사건번호}&display=20`

**상세**: `GET http://www.law.go.kr/DRF/lawService.do`
`OC={LAW_API_KEY}&target={prec|detc}&ID={일련번호}&type=XML`

### 3.2 필드 매핑 — 두 target의 스키마가 다르다

| 논리 필드 | `prec` (법원) | `detc` (헌재) |
|-----------|---------------|---------------|
| 결과 XML 태그 | `<prec>` (소문자) | `<Detc>` (**대문자 D**) |
| 일련번호 | `판례일련번호` / 상세 `판례정보일련번호` | `헌재결정례일련번호` |
| 사건번호 | `사건번호` | `사건번호` |
| 사건명 | `사건명` | `사건명` |
| 날짜 | `선고일자` (YYYYMMDD) | `종국일자` (YYYYMMDD) |
| 법원 | `법원명` | *(없음)* → `"헌법재판소"` 고정 |
| 유형 | `판결유형` | *(없음)* → `사건종류명` 대체 |
| 분류 | `사건종류명` | `사건종류명` |
| 쟁점 | `판시사항` | `판시사항` |
| 요지 | **`판결요지`** | **`결정요지`** |
| 참조조문 | `참조조문` | `참조조문` |
| 참조판례 | `참조판례` | `참조판례` |
| 전문 | **`판례내용`** | **`전문`** |
| 개행 표현 | `<br/>` 태그 | 실제 `\n` |

→ 단일 `normalize_record(root, target, serial_id)`가 target 분기로 공통 dict에
정규화한다. (초안은 어댑터 2개였으나 필드 매핑 7종이 1:1 대응이라 분기가 더 단순.)

### 3.3 정확일치 게이트 (필수)

법제처 검색은 사건명 기준 fuzzy 매칭이라 **요청과 무관한 판례를 반환한다.**
실측: `90누9421` 검색 → `2023두57876` 등 6건 반환, 요청 사건은 없음.
응답 XML의 `<사건번호>`가 요청과 일치할 때만 채택하고, 불일치는 미발견으로
기록한다. **이 게이트가 없으면 엉뚱한 판례가 코퍼스를 오염시킨다.**

같은 fuzzy 매칭 때문에 **요청한 사건이 결과 뒤쪽으로 밀린다.** 1차 전량 수집
후 미발견 125건을 표본 진단한 결과:

| 원인 | 예시 | 조치 |
|------|------|------|
| `display=20`이 작아 정답이 잘림 (totalCnt 99·279) | `90도357`, `82다카90` | `display=100` + 최대 3페이지 순회 |
| 헌재 사건을 `prec`로 조회 — CSV 법원 컬럼이 틀림 | `2005헌바20`(대법원으로 분류됨) | **사건부호로 라우팅** (`헌` 포함 → `detc`) |
| 상세 응답이 병합 사건번호 | `2000다51919, 51926` | 콤마 분해 + 괄호 주기 제거 후 포함 판정 |
| 법제처 DB 미수록 (totalCnt=0) | `2001두3709` | 복구 불가 → `_미발견.csv` |

라우팅을 CSV 법원 컬럼에만 의존하면 안 된다 — 교재 인용 추출 과정에서 법원이
잘못 붙은 건이 있어 헌재 사건이 `prec`로 조회되면 영영 못 찾는다.

### 3.4 OCR 보정

교재 OCR이 "다"를 "대"로 오인식한 4건만 명시적 치환한다(범용 보정 로직 없음 —
사례가 한정적이라 과설계):

```python
OCR_FIXES = {
    "2000대8127": "2000다8127",
    "2006대381":  "2006다381",
    "2021대69":   "2021다69",
    "2020도다296321": "2020다296321",
}
```

### 3.5 수집 정책

| 항목 | 설계 |
|------|------|
| 요청 간격 | 0.3초 (601건 × 2요청 ≈ 6분) |
| 재시도 | 3회, 지수 백오프 (`2 ** attempt`) — 기존 `embed_texts` 관례와 동일 |
| 키 선검증 | 시작 시 알려진 사건 1건 프로브. 실패 시 즉시 중단 |
| 재개 | `_progress.json`에 처리 완료 사건번호 기록. 이미 파일이 있으면 건너뜀 |
| 라우팅 | CSV `법원` 컬럼이 `헌법재판소` → `detc`, 그 외 → `prec` |
| 하급심 | 시도는 하되 실패해도 정상 처리(조회율 25%, Plan 의사결정 #2) |
| 실패 기록 | `_미발견.csv` (사건번호, 사유) — 법원·날짜는 `누락_판례목록.csv`와 사건번호 조인으로 복구 |

### 3.6 함수 인터페이스

```python
def probe_api_key(api_key: str) -> bool: ...
def resolve_target(case_no: str, court: str) -> str: ...      # 사건부호 우선 라우팅
def search_case(case_no: str, target: str, api_key: str) -> dict | None: ...
def fetch_detail(serial_id: int, target: str, api_key: str) -> ET.Element | None: ...
def normalize_record(root: ET.Element, target: str, serial_id: int) -> dict: ...
def detail_matches(detail_case_no: str, wanted: str) -> bool: ...  # 병합 사건번호 판정
def to_markdown(rec: dict) -> str: ...
def safe_filename(case_no: str, case_name: str) -> str: ...
def main() -> None: ...   # --limit / --dry-run / --force (재개가 기본 동작, §3.5)
```

(초안의 `fetch_detail -> dict`·`--resume`은 구현에 맞춰 정정 — XML 파싱을
`normalize_record` 한 곳에 모았고, 재개는 플래그가 아니라 기본 동작이다.)

---

## 4. 마크다운 스키마

기존 판례 파일의 메타 테이블 관례를 따르고, `pinecone_upload_legal.py::
parse_md_metadata()`/`extract_legal_body()`와 호환되는 구조를 유지한다
(`\n---\n` 구분선 필수).

```markdown
# {사건명}

| 항목 | 내용 |
| --- | --- |
| 분류 | {사건종류명} |
| 작성일 | {YYYY.MM.DD} |
| 사건번호 | {사건번호} |
| 법원 | {법원명} |
| 판결유형 | {판결유형} |
| 원문 | [https://www.law.go.kr/...](https://www.law.go.kr/...) |

---

## 판시사항
{...}

## 판결요지
{...}

## 참조조문
{...}

## 참조판례
{...}

## 전문
{...}
```

- 파일명: `{사건번호}_{사건명 60자}.md` — 사건번호가 **맨 앞**이어야 파일명만으로도
  중복 검사가 동작한다. 파일명 생성 시 `unicodedata.normalize("NFC", ...)` 적용
  후 `/`, `:` 등 경로 위험 문자 제거.
- 헌재 문서도 헤더 라벨은 `판시사항`/`판결요지`로 통일하고(`결정요지`→`판결요지`),
  `전문` 섹션에 `전문` 필드를 넣는다 — 다운스트림 파서를 하나로 유지하기 위함.
- 빈 필드는 섹션 자체를 생략한다.
- `<br/>` → `\n` 변환, `html.unescape()` 적용.
- **`## 관련 쟁점`** (Do 단계 추가, `enrich_court_precedents.py`): 교재의 인용
  위치(표제 경로 `절 › 세부쟁점`)를 사실 정보로 추출해 메타 테이블 직후에 삽입.
  멱등(재실행 시 교체). 커버리지 실측 496/500(99.2%).
  - **저작권 경계**: 저자의 해설 문장은 요약·의역 형태로도 가져오지 않는다 —
    요약이 원문 표현과 실질적 유사성을 유지하면 2차적저작물 문제가 남는다.
    추출 대상은 "어느 표제 아래에서 어느 판례를 인용하는가"라는 사실 정보뿐이며,
    표제 자체는 노동법 문헌 공통의 표준 강학상 분류다. 판례 요지는 공공저작물인
    판시사항·판결요지가 담당한다.
  - 업로드 시 별도 청크가 아니라 **각 청크의 embed_text(`쟁점:` 줄) + 저장
    텍스트 프리픽스(`[관련 쟁점: …]`) + metadata `topics`** 로 얹는다. 저장
    텍스트에 넣는 이유는 BM25가 metadata `text` 필드를 색인하기 때문. 벡터
    ID는 쟁점 유무와 무관하게 동일 — 태깅 전 업로드분을 재실행이 덮어쓴다.
  - 교재 원문엔 `95다 53188`처럼 번호 내부에 공백 낀 표기가 있어 스캔은 공백
    허용 패턴을 쓴다(오탐은 대상 사건 집합 필터가 제거).
  - **의존**: 교재 본문 로딩(표지·목차 제외 + OCR 표제 보정)은
    `pinecone_upload_textbook.py::load_body`를 재사용한다 — enrich를 커밋할 때
    이 파일을 반드시 함께 커밋할 것(지연 import라 CI 테스트로는 안 잡힌다).

---

## 5. 중복 제거 3단계

| 단계 | 시점 | 기준 | 구현 |
|------|------|------|------|
| **L1** | 목록 생성 | 사건번호 set | 완료됨(추출 단계) — 601건 유니크 |
| **L2** | 수집 전 | 기존 파일 코퍼스 | 아래 §5.1 |
| **L3** | 업로드 | 결정적 벡터 ID | 아래 §5.2 |

### 5.1 L2 — 파일 코퍼스 대조

`output_법원 노동판례/` + `output_판례_보강/`의 각 `.md` 파일에서 **그 문서가
다루는 대표 사건번호 1개**를 뽑아 set을 만들고, 대상 사건번호가 이미 있으면
수집을 건너뛴다.

```python
CASE_NO_RE = re.compile(r"(\d{2,4}[가-힣]{1,4}\d+)")   # 확장된 패턴

def extract_representative_case_no(text, filename):
    # 우선순위: 메타 테이블 → 파일명 → 본문 앞 1500자
    ...
```

**파일 본문 전체를 긁으면 안 된다.** 판례 본문에는 참조판례 목록이 딸려 있어
"A판례가 B를 인용" 을 "B가 코퍼스에 있음" 으로 오판한다.

구현 중 실측한 오판 규모(836개 파일):

| 추출 방식 | 사건번호 수집량 | 601건 중 스킵 판정 |
|-----------|:---:|:---:|
| 본문 전체 긁기 | 2,450개 (오탐 1,631) | 135건 → **133건 부당 스킵** |
| 파일당 대표 1건 | 819개 | 2건 |

기존 `upload_new_precedents.py::collect_existing_case_numbers()`의
`[다두도가누]`는 **`다카`(27) · `헌바`(16) · `헌마`(9)를 놓친다.** 위 패턴으로
확장하고, **NFC 정규화를 반드시 선행**한다(§2.1과 같은 실패 모드).

> 선행 대조(교재 인용 분석)는 이미 대표 사건번호 방식이었으므로 601건 목록
> 자체는 정확하다. 수집 직전 재확인해 그 사이 추가된 파일만 반영한다.

### 5.2 L3 — 결정적 벡터 ID

```python
def make_vector_id(case_no: str, idx: int) -> str:
    ascii_no = _case_no_to_ascii(unicodedata.normalize("NFC", case_no))
    return f"precedent_{ascii_no}_chunk_{idx}"
```

`_case_no_to_ascii`는 **사건부호 전량**을 매핑한다(기존 `_KR_TO_ASCII` 10종은
부족 — `헌바`/`헌마`/`헌가`/`다카`/`도다` 누락):

```python
_CASE_CODE_MAP = {
    "다카": "daka", "헌바": "heonba", "헌마": "heonma", "헌가": "heonga",
    "다": "da", "두": "du", "누": "nu", "도": "do", "가": "ga",
    "나": "na", "마": "ma", "재두": "jaedu", "가합": "gahap", ...
}
```

**긴 부호 우선 치환**(`다카` → `daka`가 `다`→`da`보다 먼저)해야 `86다카24445`가
`86daka24445`가 된다. 매핑에 없는 부호를 만나면 **경고 로그 후 해당 건 스킵** —
조용히 비ASCII를 제거하면 §2.2의 ID 뭉개짐이 재발한다.

동일 ID로 재실행하면 upsert가 덮어쓰므로 **중복 벡터가 원천적으로 불가능**하다.

---

## 6. 업로드 모듈 — `pinecone_upload_court_precedents.py`

### 6.1 청킹 범위 (Plan 의사결정 #1 확정)

**임베딩 대상: 판시사항 + 판결요지 + 참조조문. 전문은 파일 보존만, 청킹 제외.**

실측 근거:

| 범위 | 평균 글자수 | 601건 예상 청크 |
|------|:---:|:---:|
| 판시사항+판결요지+참조조문 | ~2,450 | **~2,100** |
| \+ 전문 포함 | ~25,900 | ~22,000 (10배) |

전문 최대 52,867자(2016다255941 전합) → 단일 판례가 75청크. 게다가
`【원고, 상고인】`·`【주 문】` 같은 절차 보일러플레이트가 검색 노이즈가 된다.
판시사항·판결요지는 법원이 쟁점을 압축한 텍스트라 RAG 단위로 더 적합하다.

### 6.2 청킹 파라미터

기존 전 스크립트와 동일: `CHUNK_MAX=700`, `CHUNK_OVERLAP=80`,
섹션(`^##`) 우선 분할 후 초과 시 `\n\n → \n → ". " → ", "` 경계 탐색.
`end >= len(text): break` 가드 유지.

### 6.3 벡터 메타데이터

```python
{
    "source_type": "precedent",          # 기존 값 재사용 → UI 라벨 수정 불필요
    "title": 사건명[:200],
    "section": "판시사항" | "판결요지" | "참조조문",
    "case_no": 사건번호,                  # 신규 — 인용 검증·중복 확인용
    "court": 법원명,
    "date": "YYYY.MM.DD",
    "chunk_index": idx,
    "chunk_text": text[:900],
    "text": text[:900],
}
```

`source_type="precedent"`는 `app/core/rag.py:318`의 라벨 맵과
`public/index.html:1365`의 `labels` 객체에 **이미 "판례"로 존재**한다.
새 값을 만들면 두 곳을 모두 고쳐야 하므로 재사용한다.

### 6.4 네임스페이스

**`laborlaw-v2` 고정.** `app/core/rag.py:17`의 `NS_GROUP_LAW = ["laborlaw-v2"]`가
프로덕션이 실제 조회하는 유일한 법령 네임스페이스다. `pinecone_upload_legal.py`가
정의한 `precedent` 네임스페이스(6,540벡터)는 **검색 대상이 아니다** — 여기 올리면
임베딩 비용만 쓰고 아무도 못 찾는다.

`build_bm25_corpus.py:35`의 `namespaces` 목록에도 `laborlaw-v2`가 이미 있어
BM25 재빌드 시 자동 포함된다(수정 불필요).

### 6.5 CLI

```bash
python3 pinecone_upload_court_precedents.py            # 전체 업로드
python3 pinecone_upload_court_precedents.py --dry-run  # 청킹만
python3 pinecone_upload_court_precedents.py --limit 20 # 부분 검증
```

`--reset`은 **제공하지 않는다** — `laborlaw-v2`는 다른 소스와 공유하는
네임스페이스라 `delete_all`이 기존 9,088벡터를 통째로 날린다.

---

## 7. 테스트 계획

기존 판례/상담 업로드 스크립트에는 전용 테스트가 없으나, 이번 건은 **조용히
틀리는 실패 모드**(오매칭·ID 충돌·NFD)가 셋이라 오프라인 단위 테스트를 둔다.
API 키 불요 — CI(`.github/workflows/tests.yml`)에서도 돌아야 한다.

`test_precedent_ingest.py` (신규):

| # | 테스트 | 검증 내용 |
|---|--------|-----------|
| T1 | `test_exact_match_gate` | `90누9421` 검색 결과 픽스처(무관한 6건)를 넣으면 `None` 반환 |
| T2 | `test_exact_match_accepts` | 정확일치 픽스처는 채택 |
| T3 | `test_nfd_case_number` | NFD 파일명/텍스트에서도 사건번호 추출 성공 |
| T4 | `test_vector_id_uniqueness` | 601건 전체 사건번호 → 벡터 ID 601개 고유 (충돌 0) |
| T5 | `test_case_code_coverage` | CSV의 모든 사건부호가 `_CASE_CODE_MAP`에 존재 |
| T6 | `test_detc_field_mapping` | 헌재 픽스처의 `결정요지`/`전문`이 공통 dict로 정규화 |
| T7 | `test_br_tag_conversion` | `<br/>` → 개행, HTML 엔티티 언이스케이프 |
| T8 | `test_chunk_excludes_full_text` | 전문이 청킹 대상에서 빠지는지 |
| T9 | `test_markdown_roundtrip` | 생성한 마크다운을 업로드측 파서가 되읽는지 |
| T10 | `test_dedup_ignores_citations` | 참조판례 인용을 "코퍼스에 있음"으로 오판하지 않는지 |
| T11 | `test_target_routing` | 헌재 사건이 법원 컬럼 오류에도 `detc`로 가는지 |
| T12 | `test_merged_case_number` | 병합 사건번호(괄호 주기 포함)를 일치로 인정하는지 |
| T13 | `test_topic_enrichment` | 쟁점 태그 md 삽입 멱등성 + embed_text/BM25 텍스트/metadata 반영 + 별도 청크 미생성 + 공백 낀 표기 매칭 |

CSV(`누락_판례목록.csv`)는 gitignore 대상이라 CI에 없다. T4·T5는 사건부호
12종의 대표 표본을 테스트 파일에 내장해 **데이터 없이도 실행**되게 한다 —
CSV가 있으면 601건 전량으로 확장 검증한다.

### 통합 검증 (수동, API 필요)

1. `--limit 20`으로 부분 수집 → 마크다운 육안 확인
2. `--dry-run`으로 청크 수·샘플 확인
3. 업로드 전후 `describe_index_stats()`의 `laborlaw-v2` 벡터 증분 확인
4. `2016다255941`(전합, 교재 최다 인용급) 질의로 실제 검색 히트 확인
5. `build_bm25_corpus.py` 재실행 → gz 커밋

---

## 8. 구현 순서

1. `fetch_court_precedents.py` — API 어댑터 + 정확일치 게이트 + 마크다운 생성
2. `test_precedent_ingest.py` — T1~T7 (수집 로직 대상)
3. `--limit 20` 시범 수집 → 포맷 검증
4. 전량 수집 (~6분) → `_미발견.csv` 확인
5. `pinecone_upload_court_precedents.py` — 청킹 + 업로드
6. T4·T5·T8 추가 → `--dry-run` 검증
7. 실제 업로드 → 벡터 증분 확인
8. `build_bm25_corpus.py` 재실행 → `data/bm25_corpus.json.gz` 커밋
9. `CLAUDE.md` 갱신 (코퍼스 디렉토리·커맨드 목록·NFC 주의사항)

---

## 9. 후속 과제 (이번 범위 밖)

| # | 내용 | 근거 |
|---|------|------|
| F1 | `pinecone_upload_legal.py::extract_post_id()` NFD 버그 수정 | §2.1 — 기존 판례 836개 중 474개(57%)가 Pinecone에서 덮어써진 상태. `precedent` NS가 프로덕션 검색 대상이 아니라 사용자 영향은 없으나, 해당 NS를 살릴 계획이라면 선행 필수 |
| F2 | `upload_new_precedents.py`의 중복 정규식 확장 | §5.1 — `다카`/`헌바`/`헌마` 미커버 |
| F3 | 미발견 ~33건 보완 수집 | 법제처 미수록분. 종합법률정보 등 대체 경로 검토 |
| F4 | 교재 인용 하급심 4건 | 조회율 25%, 가치 대비 비용 낮음 |

---

## 10. 확정된 의사결정 (Plan §3 대응)

| # | 항목 | 확정 | 근거 |
|---|------|------|------|
| 1 | 청킹 본문 범위 | 판시사항+판결요지+참조조문 (전문 제외) | §6.1 — 청크 10배 차이, 절차 보일러플레이트 노이즈 |
| 2 | 하급심 4건 | 시도하되 실패 허용 | 조회율 25% |
| 3 | 저장 디렉토리 | 신규 `output_판례_보강/` | 출처·포맷이 달라 분리 |
| 4 | 미발견 처리 | `_미발견.csv` 보존 | 후속 F3 |
| 5 | 비용 | 임베딩 $0.05 미만 | ~2,100청크 × 700자 |
| 6 | **업로드 스크립트** | **신규 작성** (Plan은 기존 확장 상정) | §2 — NFD 버그로 43% 소실 |
