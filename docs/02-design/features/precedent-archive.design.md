# precedent-archive Design

> Plan: `docs/01-plan/features/precedent-archive.plan.md` (2026-08-30)
> Plan §7이 Design에 위임한 5개 과제 — ① 스키마·인벤토리 컬럼 확정 ② 크롤분 게이트 판정 절차
> ③ `--verify` 검사 목록 ④ 회귀 케이스 목록 ⑤ records/ 스냅샷 갱신 규칙 — 을 여기서 확정한다.
> 설계 전 실측(2026-08-30)에서 Plan의 전제가 수정됐고(§2.4, §5.3, D-10), design-validator
> 검증(2026-09-01, 74/100 수정 후 승인)의 High 5·Medium 10·Low 10을 반영해 개정했다.

## 1. 설계 개요 — 결정 요약

| # | 결정 | 내용 | 근거 절 |
|---|------|------|--------|
| D-1 | 레코드 정본은 `body_md` = **파일 바이트 그대로** | 메타 필드는 body에서 뽑은 파생 사본. `--extract`는 body_md를 쓰기만 하면 무손실(S4)이 자명해진다 | §3 |
| D-2 | 번들 레코드 키는 `doc_id` = **NFC 상대 경로** | 크롤 구세대는 사건번호가 없어 case_key로 유일성이 성립하지 않는다. 경로는 파일시스템이 유일성을 보장 | §3 |
| D-3 | 장부는 **2파일** — `inventory.csv`(사건 단위) + `documents.csv`(문서 단위) | 1사건:N문서 관계가 실재(letec 정본 + 크롤 대체 출처, `_겹침대상.csv` 286쌍)하고, 대표 사건번호 없는 게시물형도 문서 행은 가져야 한다 | §5 |
| D-4 | 대표 사건번호는 **`fetch_court_precedents.extract_representative_case_no` import** (메타 → 파일명 → 본문 앞 1,500자) | 초판은 "본문 안 읽기"를 새로 정의했으나 검증 H2 지적대로 **후속 `fetch --cases`의 L2 중복검사와 판정이 갈라진다**. 같은 함수 import가 판정 단일 출처(사본 금지 관례). 참조판례 함정은 1,500자 상한이 이미 흡수(그 함수의 실측 근거: 전량 스캔 2,450 vs 대표 819) | §6 |
| D-5 | 크롤 게이트는 **파일 단위 3-버킷** 자동 분류 + 표본 육안 이중 | 계층 전체 일괄 판정보다 verbatim(판결문 원문)만 선별 승격하는 쪽이 내구성 이득이 크고, 오공개 비대칭 원칙(폐기만 범용)과도 부합 | §7 |
| D-6 | NLRC는 인벤토리 **비대상** (Plan 수정 ①) | 실측: `data/nlrc_cases.json` 필드 7종(구분·순번·위원회명·자료구분·작성일자·제목·조회수)에 사건번호도 본문도 없다. "인용처 nlrc"는 성립 불가 | §5.3 |
| D-7 | 직렬화는 **결정적** — 키 정렬·gzip `mtime=0`·정렬된 행 순서 | S6(멱등) 성립 조건. `gzip.open` 기본값은 헤더에 mtime을 넣어 재실행마다 바이트가 달라진다 | §4.3 |
| D-8 | records/ 스냅샷 파일명은 **ASCII 통일** | 한글 파일명은 macOS가 NFD로 커밋해 Linux checkout과 어긋난다 — NFD로 474벡터를 잃은 실패 클래스의 파일명 판 | §9 |
| D-9 | 회귀는 `test_precedent_ingest.py`에 **T27 계열** 추가 | 기존 최고 번호 T26. 같은 파일에 두는 이유: 픽스처 폴백·`check()` 헬퍼 공유 | §11 |
| D-10 | `case_key`는 **`pinecone_upload_court_precedents.case_no_to_ascii` import** — 원장을 만든 바로 그 함수. hex 폴백 없음 | 검증 H1: 초판이 지목한 `legal._case_no_to_ascii`는 원장 생산 함수가 아니고 계약도 다르다(None 반환·NFC 미수행). 실측: 원장 1,568키 전부 court 함수 산출물이고 **hex 키 0건** — 폴백 규약 자체가 불필요. `UnknownCaseCode` 예외 시 `case_key=null + note=미매핑부호` | §3 |
| D-11 | 사장 NS 존재 사실을 `vec_dead` 컬럼으로 기록 (Plan 이탈 ③ 해소) | Plan §3 비목표가 "인벤토리에 존재 사실만 기록"을 명시 — 초판 누락(검증 M5). `--pinecone` 열거 스냅샷 기반, ID 역매핑 가능분만 | §5.1 |

## 2. 소스 데이터 실측 계약 (2026-08-30 실측, 2026-09-01 검증 교차확인)

파서가 의존해도 되는 형식을 실측으로 고정한다. 여기 어긋나는 파일은 **버리지 않고 오류 목록으로 보고**한다(조용한 폐기 금지 — 해설서 위생 처리 교훈).

### 2.1 letec (`output_판례_보강/`) — 1,584파일 = 사건 md 1,578 + 부속 6

- 파일명: `{사건번호}_{사건명}.md` (NFD — NFC 정규화 선행 필수). 선두 토큰이 곧 대표 사건번호. **파일당 1사건이 fetch의 저장 규약이므로 보장됨.**
- 본문: `# 제목` → 메타 테이블(`| 분류 | 작성일 | 사건번호 | 법원 | 판결유형 | 원문 |`) → `---` → (`## 관련 쟁점`)? → `## 판시사항` 등.
- **prec/detc의 XML 스키마 차이는 `fetch::parse_record()`가 흡수해 md는 동일 서식이다**(`to_markdown()`이 메타 6행·섹션명을 통일 — 실측: `2000헌마707_….md`도 `법원 | 헌법재판소`·`판결유형 | 헌마`로 같은 표). 그래도 파서는 섹션명을 열거하지 않고 메타 행을 dict로 읽는다(향후 서식 변화 대비). letec에서 `court`는 항상 채워진다.
- 부속 6: `_수집결과_정리.md`, `_progress.json`, `_미발견.csv`, `_겹침대상.csv`, `_ctx_deleted.json`, `_uploaded_ids.json` — 사건 md 판정은 "밑줄로 시작하지 않는 `.md`".

### 2.2 crawl (`output_법원 노동판례/`) — md 837 = 문서 836 + `_index.md`

- 카테고리 하위 폴더 **5종 실측**(근로기준·기타·노동조합·비정규직·산재보상). `_index.md`의 표는 미분류 포함 6분류를 말하나 미분류 폴더는 없다. `category`는 부모 폴더명.
- **2세대 혼재** (실측, 교집합 0):
  - 구세대 350: `{post_id}_{제목}.md`, 메타 테이블에 사건번호 **없음**(분류·작성일·조회수·원문 URL).
  - 신세대 486: `{사건번호}_{제목}.md`, 메타 테이블에 `사건번호` 행 **있음**, 원문 URL·post_id 없음.
- 세대 판별: 파일명 선두 `^\d+_`(순수 숫자+밑줄)이면 구세대, `CASE_RE` 매치면 신세대(사건번호는 숫자 뒤에 한글 부호 — 배타적).
- `_index.md`(353게시글 표기)는 낡았지만 **버리지 않는다** — 크롤 쪽 유일의 "있어야 할 것" 기록이므로, 링크 목록을 파싱해 실파일과 차집합을 내고 누락분을 `inventory.note=크롤색인누락`으로 기록 + build 요약에 보고(검증 M8).

### 2.3 부속 기록 (records/ 원천)

| 파일 | 실측 형식 |
|------|----------|
| `_uploaded_ids.json` | `{case_key(ascii): [벡터 ID...]}` — 1,568그룹/5,893 ID, **hex형 키 0건** |
| `_미발견.csv` | BOM(utf-8-sig), 헤더 `사건번호,사유` — **967행**(초판·Plan·CLAUDE.md의 156은 낡은 수치 — 검증 H5) |
| `_겹침대상.csv` | BOM, 헤더 `사건번호,법원,게시글ID` — **286행**, 사건번호↔크롤 post_id 대응표 |
| `_ctx_deleted.json` | `{사건번호(NFC): [ctx_precedent_{post_id}_c{i}...]}` — 128사건 |
| `output_노동법교재/누락_판례목록.csv` | BOM, 헤더 `사건번호,법원,날짜,인용횟수` — 교재 인용 **601건**(602는 헤더 포함 줄수) |

모든 CSV 읽기는 `encoding="utf-8-sig"`. `누락_판례목록_교재통합.csv`는 헤더뿐(데이터 0행) — 스냅샷 제외 확정(검증 확인).

### 2.4 코드 인용 (Plan 1.2 확장 — 검증 H4)

- **정규식 스캔 대상**: `app/ wage_calculator/ harassment_assessor/`의 `*.py` + `wage_calculator_cli.py`(계산 검증 케이스의 근거 판례).
- **구조 열거 대상**: `build_graph.py::MAJOR_PRECEDENTS` — GraphRAG 노드 판례 **8건 실측**(2010다111757·2012다89399·2013다25194·2017다261387·2018다200709·2019다293449·2020나2016258·2023다302838), 그중 **7건이 Plan 17건 밖**. 정규식이 아니라 dict 키 열거로 수집(프로덕션 지식그래프라 공백이 가장 치명적).
- **제외**: 파이프라인·수집 스크립트(`fetch_*`·`pinecone_upload_*`·`extract_textbook_cases` 등)와 `test_*`·`eval_*` — 이들의 사건번호는 OCR 정정 맵·픽스처라 법적 근거 인용이 아니다.
- 추출기: **`extract_textbook_cases.CASE_RE` import**(사건부호 화이트리스트 — T20 조문 오탐 방지). ⚠️ 4자리 연도 grep은 `96다24699`를 놓친다(실측). CASE_RE는 2~4자리 연도 커버.
- 발견 전량을 `records/code_citations.csv`(사건번호,파일,라인,컨텍스트종류)로 스냅샷(§9) — `컨텍스트종류 ∈ {data, docstring, comment, cli_case}`. 실측: `2021헌마1234`·`2023다302838`이 `legal_api.py`·`citation_validator.py` **docstring 예시**로 등장 — 예시 오염은 구조적이므로, 컨텍스트가 docstring/comment뿐인 사건은 `note=예시의심` 자동 초안 + Do에서 사람 확정(검증 M6). **확정 결과의 저장처는 코드 상수** `EXAMPLE_CONFIRMED`(예시확정 — 2021헌마1234·2017헌바127·2006다49372)·`EXAMPLE_OVERRIDE_REAL`(실인용 복권 — 2006다49653: comment지만 근로자성 체크리스트의 법적 근거) — 재빌드 멱등·diff 리뷰 가능(Do #3 확정, gap 판정 타당).
- **연도 유효성 게이트**: 3자리 연도·범위 밖(1946~2030) 4자리는 기각 — 실측 오탐 `299인2020`(사업장 규모 표기 "50~299인 2020")·`005두4403`. **2자리 오탐(`10인30`류)은 수용** — 2자리 연도는 1900/2000년대 판별이 불가능해 구조적 차단이 안 되고, `_미발견` 유래 소수 행이라 장부 오염이 미미하다.
- Plan의 "17건"은 이 확장 범위로 Do #2에서 재확정한다(모집단이 커지므로 17+α).

## 3. 아카이브 레코드 스키마 (확정)

jsonl 한 줄 = 문서 1건. **키 정렬 직렬화**(`json.dumps(..., ensure_ascii=False, sort_keys=True)`).

```json
{
  "doc_id": "output_판례_보강/2000다15869_부당이득금.md",
  "source": "letec",
  "case_no": "2000다15869",
  "case_key": "2000da15869",
  "doctype": "prec",
  "court": "대법원",
  "decided": "2000.06.09",
  "title": "부당이득금",
  "category": "민사",
  "category_src": "meta",
  "post_id": null,
  "origin_url": "https://www.law.go.kr/DRF/lawService.do?...",
  "issues": ["임금채권 우선변제"],
  "sha256": "…(body_md의 sha256)",
  "body_md": "…파일 내용 바이트 그대로…"
}
```

| 필드 | 규칙 |
|------|------|
| `doc_id` | 저장소 루트 기준 상대 경로, **NFC 정규화**. 번들 내 유일 키(T27-b) |
| `source` | `letec` \| `crawl` |
| `case_no` | 대표 사건번호(NFC, §6). 게시물형은 `null` |
| `case_key` | **`pinecone_upload_court_precedents.case_no_to_ascii` import**(D-10 — 원장 생산 함수와 같은 객체, 사본 3벌 문제의 4벌째를 만들지 않는다). `UnknownCaseCode` 예외 시 `null` + note=미매핑부호 — hex 폴백은 두지 않는다(원장 키 공간에 hex 0건 실측 — 대조 상대가 없는 규약은 죽은 코드다). `case_no`가 null이면 null |
| `doctype` | `prec` \| `detc`(사건부호 `헌*`) \| `post`(대표 사건번호 없는 크롤 게시물) |
| `court`/`decided`/`title`/`origin_url` | 메타 테이블·`# 제목`에서 추출한 파생 사본. 없으면 null |
| `category` | **공용**: letec은 메타 `분류`(민사/헌마 등), crawl은 폴더명. `category_src ∈ {meta, folder}` 병기(검증 L10) |
| `post_id` | crawl 구세대만. letec·신세대는 null |
| `issues` | letec의 `## 관련 쟁점` 리스트. **포함 확정** — `enrich_court_precedents.py` docstring이 이미 판정: 쟁점 표제는 "노동법 문헌 공통의 표준 강학상 분류"이고 추출물은 사실 정보뿐 |
| `sha256` | `body_md` UTF-8 바이트의 sha256 — 번들 자기 정합(V2) 기준 |
| `body_md` | **파일 내용 그대로**(정규화·트림 금지). 원문 출처는 로컬 파일뿐 — Pinecone `chunk_text` 복원 금지(Plan) |

**문자열 파생 필드는 전부 NFC** — `body_md`만 원본 바이트 유지(검증 L7. CSV에 NFD가 섞이면 Excel·grep에서 조용히 안 잡힌다).

## 4. 산출물 배치와 공개 계층

### 4.1 파일 배치

```
archive_precedents.py                     # 단일 스크립트 (서브커맨드 §10)
data/precedent_archive/
  letec_precedents.jsonl.gz               # 공개 계층 ① — letec 1,578 전량 (비보호 저작물)
  crawl_verbatim.jsonl.gz                 # 공개 계층 ② — 게이트 통과 시에만 생성 (⏸️)
  inventory.csv                           # 사건 단위 장부 (평문)
  documents.csv                           # 문서 단위 목록 (평문)
  MANIFEST.json                           # §4.2 스키마 — verify V0의 대조 기준
  records/                                # §9
```

- `.gitignore`는 `output_*/` 유지 + **추가 2줄**(검증 M9): `precedent_crawl_*.tar.gz`(게이트 미통과 보관본의 우발 커밋 차단 — PUBLIC 저장소라 회수 불가), `data/precedent_archive/*.tmp`(원자적 쓰기 중간물). 기존 `*.jsonl` 룰은 `*.jsonl.gz`를 잡지 않음을 실측 확인(bm25 선례).
- **게이트 미통과 크롤 잔여**는 커밋하지 않는다. 내구성은 `tar czf` + 저장소 밖 보관(Do 절차서에 명령만 기록, `--backup-dir` 관례 준용).

### 4.2 MANIFEST.json 스키마 (검증 M3)

```json
{
  "counts": {"letec": 1578, "crawl": 836, "inventory_rows": 0, "documents_rows": 0},
  "bundles": [{"path": "letec_precedents.jsonl.gz", "sha256": "…", "bytes": 0, "records": 0}],
  "snapshot_map": {"records/ledger_uploaded_ids.json": "output_판례_보강/_uploaded_ids.json", "…": "…"},
  "snapshot_origin_digests": {"records/ledger_uploaded_ids.json": {"sha256": "…", "groups": 1568}},
  "scope_notes": ["NLRC 제외(§5.3)", "사장 NS는 vec_dead로 존재만(§5.1 D-11)"],
  "gate_rule_version": 1
}
```

`snapshot_origin_digests`가 **스냅샷 낡음의 유일한 탐지 수단**이다(검증 M4): 로컬 verify(원본 존재 시)가 원본 sha256·그룹 수를 스냅샷 기록과 대조해 불일치 = "원본이 바뀐 뒤 build를 안 돌림" = 실패. **CI 단독으로는 낡음을 못 잡는다** — 스냅샷만 읽는 CI V4는 자기 정합만 보장한다. 시각 필드는 두지 않는다(결정성 D-7, 갱신 이력은 git).

### 4.3 공개 계층 불변식 (S5)

커밋되는 번들에 들어갈 수 있는 doc은 두 부류뿐: ① `source=letec` 전량(법제처 원문 — 저작권법 제7조 비보호) ② `source=crawl` 중 게이트 판정 `verbatim`(§7). `--verify` V7과 회귀 T27-d가 이중으로 고정.

### 4.4 결정적 직렬화 (S6)

- 레코드 순서: `doc_id` 오름차순. CSV 행 순서: 기본 키 오름차순.
- gzip: `gzip.GzipFile(fileobj=..., mode="wb", mtime=0)` — 기본 mtime 삽입 차단.
- 산출물 쓰기는 tmp→`os.replace`(`vector_ledger.atomic_write_json` 패턴).

## 5. 인벤토리 설계

### 5.1 `inventory.csv` — 사건 단위 (기본 키 `case_no`)

**행 모집단 = 알려진 모든 사건번호의 합집합**: letec 대표 1,578 ∪ crawl 대표(§6) ∪ 코드 인용(§2.4) ∪ 교재 인용 601 ∪ `_미발견` **967** ∪ 원장 키 역매핑 ∪ 겹침대상 286. 문서가 없는 사건도 행이 된다 — **doc·vec 계열이 전부 0인 행이 곧 공백 목록(G3)**. 예상 행 수 대략 **2,900~3,300**(중복 해소 후 — Do #2에서 실측 확정. 초판의 "미발견 156" 기준 추정보다 훨씬 크다는 점을 Do가 이상으로 오인하지 말 것).

**사건번호 정준형·별칭**(검증 M7): 같은 사건의 표기 변형이 별도 행이 되면 장부 목적이 훼손된다. `CASE_RE` 그룹 재조립(`year+code+num` — 내부 공백 흡수) 후, **1946~1999년 4자리 연도 표기는 2자리 정식 표기로 정규화한 별칭을 계산해 병합**(실측: `_미발견.csv`에 `1992다28556`류 존재, 정식은 `92다28556`). 병합 시 원표기를 `case_alias` 컬럼에 보존 + `note=표기병합`.

| 컬럼 | 값 | 채움 규칙 |
|------|-----|----------|
| `case_no` | NFC 정준형 | 정렬 키 |
| `case_alias` | 병합된 원표기(`;` 구분) | 없으면 빈 값 |
| `case_key` | ASCII | §3 D-10 함수. 미매핑은 빈 값 |
| `court` / `decided` / `title` | 문자열 | **letec 우선**(정본 규칙), 없으면 crawl 메타, 다음 교재 CSV의 법원·날짜, 최후는 빈 값 |
| `doc_letec` | 0..N | letec 문서 수 (1 초과 시 `note=letec중복` — 검증 L6, V5 합계 등식 유지) |
| `doc_crawl` | 0..N | 이 사건을 대표 번호로 갖는 크롤 문서 수 |
| `vec_chunks` | 0..N | 원장에서 case_key 그룹의 ID 수 (오프라인) |
| `vec_ctx` | 0..N / 빈 값 | `records/ctx_vector_ids.json` + §6 ③.5의 post_id 대응으로 산출. 스냅샷 부재 시 빈 값 = "미확인"(0과 구분) |
| `vec_dead` | 0/1 / 빈 값 | 사장 NS(`precedent`·`laborlaw`) 존재 — `records/dead_ns_ids.json`에서 case_key 역매핑 가능분만(D-11). 스냅샷 부재 시 빈 값 |
| `cited_code` | 0..N | `records/code_citations.csv` 파생(§2.4) |
| `cited_textbook` | 0..N | 교재 인용 횟수 |
| `not_found` | 0/1 | `_미발견.csv` 수록 — 법제처 미수록이라 재시도 무익 |
| `overlap` | 0/1 | `_겹침대상.csv` 수록 |
| `note` | 문자열 | `예시의심`·`예시확정`·`원장미수록`·`원장미수록(섹션없음)`·`표기병합`·`크롤색인누락`·`미매핑부호`·`letec중복` (구현 확정 어휘 — R4 실측: 미수록 10건 전부 하급심·헌재로 전문만 있고 EMBED_SECTIONS 부재 → 업로더 스킵) |

- 인코딩 `utf-8-sig`(기존 records CSV·한국어 Excel 관례).
- **상태 판정을 컬럼으로 두지 않는다** — "수록/미수록/공백"은 doc·vec 컬럼에서 파생 가능하고, 파생값 컬럼은 원천과 어긋나는 순간 장부를 거짓말쟁이로 만든다. S3의 공백 카운트는 `--verify`가 계산해 보고.

### 5.2 `documents.csv` — 문서 단위 (기본 키 `doc_id`)

| 컬럼 | 값 |
|------|-----|
| `doc_id` | NFC 상대 경로 |
| `source` | letec/crawl |
| `case_no` | 대표 사건번호(정준형) 또는 빈 값(게시물형) |
| `case_src` | 대표 채택 경로 — `meta`/`filename`/`body_head`/`overlap`(§6) |
| `doctype` | prec/detc/post |
| `category` / `category_src` | §3 규칙 |
| `post_id` | 구세대 크롤만 |
| `title` | 문서 제목 |
| `gate` | letec은 `exempt`(비보호), crawl은 §7 판정(`verbatim`/`editorial`/`post`/`pending`) |
| `bundled` | 0/1 — 커밋 번들 수록 여부 |

`gate ∉ {exempt, verbatim}`인데 `bundled=1`인 행 0건 — S5의 CSV 측 표현(V7).

### 5.3 NLRC 제외 (Plan 1.1·4.3 수정)

Plan은 "NLRC 인벤토리에 참조만"·인용처 `nlrc`를 상정했으나, 실측(D-6)상 번들에 사건번호·본문이 없어 **어떤 형태의 사건 대응도 만들 수 없다**. 인벤토리·documents에서 NLRC를 완전 제외하고 MANIFEST `scope_notes`에 기록. 중노위 판정례의 사건 체계(예: `중앙2024부해123`)는 법원 사건번호와 다른 키 공간이라, 포함하려면 별도 컬럼 설계가 필요하다(후속 사이클).

## 6. 대표 사건번호 판정 (파일당 최대 1개)

**판정 함수는 `fetch_court_precedents.extract_representative_case_no`를 import한다**(D-4) — 우선순위 메타 테이블 → 파일명(NFC) → 본문 앞 1,500자. 후속 수집(`fetch --cases`)의 L2 중복검사와 **같은 함수 = 같은 답**이 되는 것이 재구현 금지의 실익이다(검증 H2).

archive 측 추가 처리 3단:

1. **화이트리스트 게이트**: fetch의 `CASE_NO_RE`는 범용 패턴이라 비법원 번호(인권위 `09진차219` 등 — 구세대 게시물 실측)도 잡는다. 추출 결과가 `extract_textbook_cases.CASE_RE`(사건부호 화이트리스트)에 부합하지 않으면 기각 → `post`. **fetch 판정과의 차집합(기각 목록)은 build 요약에 보고** — L2와 인벤토리가 갈라지는 지점을 눈에 보이게 한다.
2. **겹침 대응 채택**(검증 H3): 1에서 대표를 얻지 못한 크롤 문서 중 `_겹침대상.csv`·`_ctx_deleted.json`의 post_id 대응이 있으면 그 사건번호를 대표로 채택(`case_src=overlap`). 본문 스캔이 아니라 편집자 큐레이션 산출물이라 참조판례 함정과 무관. 겹침 CSV 유래 표기에는 `OCR_FIXES` 정정을 적용한다(교재 OCR 유래 — §6 하단의 "미적용"은 파일명·메타에 한정). **Do 실측 정정**: fetch 함수의 본문 1,500자 폴백(`case_src=body_head`)이 구세대 대표의 주경로여서 overlap 채택 실적은 0건 — `vec_ctx`는 겹침 CSV → ctx_deleted → 크롤 문서 post_id의 3중 대응 맵으로 채워지며(구현 `build_inventory`), overlap 단계는 그 맵의 한 겹이자 백스톱이다.
3. **불일치 보고**(검증 M10): 신세대에서 파일명 선두와 메타 `사건번호` 행이 다르면 — 채택은 함수의 메타 우선을 따르되 — **오류 목록에 보고**(조용한 폐기 금지 원칙의 채택 판 — 조용한 선택 금지).

- 정준형·별칭 정규화(§5.1)는 판정 **후** 적용.
- OCR 정정(`OCR_FIXES`)은 적용하지 않는다 — 그 맵은 교재 OCR 오인식용이고 파일명·메타는 기계 생성이라 오인식이 없다.
- 전부 실패 → 대표 없음 = `doctype=post`. 위음성 수용: 그 사건이 인용 공백으로 잡히면 후속 letec 수집이 **정본**을 가져오므로, 크롤 문서를 억지로 연결하는 것보다 결과가 좋다(정본 규칙과 일관).

## 7. 크롤분 저작권 게이트

### 7.1 자동 3-버킷 (전수, 파일 단위)

판정 순서(검증 L8): **① 대표 사건번호 유무 → ② 구조 마커.** 대표 없으면 `post`(마커 유무 무관 — 실측상 공집합이나 규칙은 고정).

| 버킷 | 판정 | 처분 |
|------|------|------|
| `verbatim` | 판결문 구조 마커 충족 + 블록 밖 본문 잔량 적음 | 육안 게이트 통과 시 `crawl_verbatim.jsonl.gz`로 커밋 |
| `editorial` | 대표 사건번호는 있으나 마커 미충족 또는 블록 밖 텍스트 과다 | 비공개 |
| `post` | 대표 사건번호 없음 | 비공개 |

구조 마커(신세대 실측 서식 기준 — **Do 확정 규칙 v3**):
- **필수**: `【주 문】`·`【이 유】`(또는 detc형 `【결정요지】`) 존재 + 선고문 라인(`선고 {사건번호}` 병기) 존재.
- **정량**: 블록 경계 앵커 = 【 마커 줄 ∪ 서명 줄(재판장·대법관·판사) ∪ **판결문 종결 문구**("주문과 같이 판결한다"·"관여 대법관의 일치된 의견" — v2에서 추가: 크롤 판결문 473건이 서명 없이 종결 문구로 끝나는 서식이라, 종결 앵커 없이는 이유 본문 전체가 '블록 밖'으로 오계산돼 verbatim이 9건뿐이었다). 첫 앵커 **앞**과 마지막 앵커 **뒤** 각각 실질 텍스트 5줄 이하(`MAX_EDGE_LINES=5` — 실측 확정: verbatim 후보 분포가 (front 1, back 0) 중심).
- **혼입·오염 신호 즉시 editorial**(v3 — 1차 육안 표본 73건에서 발견): `※` 편집자 안내문("홈페이지 참조"·"이하 생략"·"준회원") + 크롤 JS 잔재(`document.on*`·`CheckKeyPress`·`<script`, 12건 실측). 블록 안팎 불문.
- **완화는 §7.2 육안 절차 재수행 없이 금지**(보수 방향 원칙). 규칙 변경 시 `GATE_RULE_VERSION` 증가 → 기존 승인 자동 무효화.

### 7.2 육안 게이트 (표본)

- 표본: verbatim 버킷에서 무작위 60 + 마커 점수 하위 경계 20 = **80건 육안**.
- 통계 근거: 오분류 0/60이면 rule of 3으로 자동 분류 오류율 상한 ≈5%. 경계 20건은 오분류가 몰리는 구간을 직접 때린다.
- 판정 규칙: **1건이라도** 해설·요약 혼입 발견 → 그 패턴을 마커에 추가(보수화) → 전량 재분류 → 표본 재추첨. 2회 내 수렴하지 않으면 **이번 사이클은 크롤 전체 비공개로 종료**(Plan #5 ⏸️ 경로). 오폐기는 내구성 손해뿐, 오공개는 회수 불가 — 방향 비대칭.
- 육안 판정 기준은 좁게: "판결문 블록 밖에 실질 텍스트가 있는가"만 본다. 애매하면 editorial(검증 R2 대응).
- 무작위 추첨은 `random.Random(고정 seed)` — 재현 가능해야 판정 이력이 의미를 갖는다.

### 7.3 판정의 저장

- `documents.csv::gate` + `records/crawl_gate.json`(버킷별 건수, 마커 규칙 버전=MANIFEST `gate_rule_version`, 표본 doc_id 목록, 육안 판정, 판정일 — 판정일은 `--as-of` 수동 인자: 결정성 유지).
- **`--approve`는 표본을 재추첨하지 않는다**(gap M1) — 승인은 "기록된 표본을 육안했다"는 진술이므로, 기록된 `sample`·`seed`를 그대로 승인하고 표본 기록 부재·버킷 불일치(추첨 후 파일 변경)면 거부한다. 추첨마다 `rounds[]`에 {rule_version, seed, buckets, sample_size, approved} 이력이 쌓인다(규칙 진화 감사 추적).
- 게이트 완료 전 기본값 `pending` — pending은 `bundled=0`과 함께만 존재 가능(V7).

## 8. `verify` 검사 목록

이번 사이클은 **커밋 전 수동 관문**이다(검증 L9 — CI 편입은 Do #8에서 번들 파싱 시간 실측 후 판단하며, 편입 시의 서브셋만 여기 규정). 로컬 원본이 있으면 전체, 없으면(CI 상정) V0·V1·V2·V5~V7.

| # | 검사 | 판정 |
|---|------|------|
| V0 | MANIFEST 대조: `counts`·`bundles[].sha256`·`records` 수가 실제 산출물과 일치(검증 M3) | FAIL |
| V1 | 번들 파싱: 전 레코드 json 파싱 + 필수 필드 존재 + doc_id 유일 | FAIL |
| V2 | 자기 정합: 각 레코드 `sha256 == sha256(body_md)` | FAIL |
| V3 | 원본 대조(로컬 전용): 번들 body_md == 대응 로컬 파일 바이트. **전 건** — S4의 "임의 표본"을 전수로 상향(로컬에선 초 단위 비용) | FAIL |
| V4 | 원장 포섭(S2): 원장 1,568 case_key 전부 inventory에 존재. **로컬(원본 존재 시)은 원본을 읽고, 추가로 원본 sha256·그룹 수를 MANIFEST `snapshot_origin_digests`와 대조해 스냅샷 낡음을 탐지**(검증 M4). CI는 스냅샷만 — 낡음 탐지 불가를 §4.2에 명시 | FAIL |
| V5 | 장부 정합: inventory `doc_letec`/`doc_crawl` 합계 == documents의 source별 사건-보유 문서 수; documents의 case_no 전부 inventory에 존재 | FAIL |
| V6 | 인용 완결(S3): `records/code_citations.csv`의 사건번호 전부 inventory에 존재 + `cited_code ≥ 1`. 공백 건수(doc·vec 전부 0) 집계 보고 | FAIL |
| V7 | 공개 불변식(S5): 번들 수록 doc 전부 `gate ∈ {exempt, verbatim}`; documents에서 `bundled=1 ∧ gate ∉ {exempt, verbatim}` 0건; `pending ∧ bundled=1` 0건 | FAIL |
| V8 | 멱등(S6, 로컬 전용): 빌드 재실행 임시 산출물과 커밋 대상이 바이트 동일 | FAIL |

모든 검사는 실패 항목을 **전부 나열**하고 마지막에 종료 코드 1 — 첫 실패에서 멈추지 않는다(한 번의 실행으로 전체 그림. 검증 L1의 "중단" 표기 모순 해소).

## 9. `records/` 스냅샷 규칙

| 스냅샷(ASCII) | 원본(로컬) | 비고 |
|---------------|-----------|------|
| `ledger_uploaded_ids.json` | `output_판례_보강/_uploaded_ids.json` | **읽기 전용 백업.** 실사용 원장은 여전히 원본 — 이중화지 이전이 아니다. 복구 = 스냅샷을 원위치로 복사 |
| `not_found.csv` | `_미발견.csv` (967행) | |
| `overlap_targets.csv` | `_겹침대상.csv` (286행) | |
| `ctx_deleted.json` | `_ctx_deleted.json` | |
| `textbook_citations.csv` | `output_노동법교재/누락_판례목록.csv` (601) | |
| `code_citations.csv` | (build가 생성 — §2.4) | 사건번호,파일,라인,컨텍스트종류 |
| `ctx_vector_ids.json` | (원본 없음) | `--pinecone` 시 laborlaw-v2 `ctx_precedent_*` 1,310 ID 열거. 이후 오프라인 입력 |
| `dead_ns_ids.json` | (원본 없음) | `--pinecone` 시 사장 NS(`precedent`·`laborlaw`) ID 열거(D-11). NFD 손상 이력이 있는 NS라 역매핑은 가능분만 |
| `crawl_gate.json` | (build/gate가 생성 — §7.3) | |

- 원본→스냅샷 매핑은 MANIFEST `snapshot_map`, 원본 digest는 `snapshot_origin_digests`(§4.2).
- `_progress.json`은 **제외** — 재수집 재개용 진행 상태라 유실 시 `--force` 재수집이면 되고, 백업하면 낡은 진행 상태를 "복구"하는 사고 경로만 생긴다. `누락_판례목록_교재통합.csv`도 제외(데이터 0행 실측).
- **갱신 시점은 수동**: 원본을 바꾸는 이벤트(신규 수집, 업로드, ctx 정리) 후 `build` 재실행. build는 항상 원본→스냅샷 단방향 복사(바이트 그대로, 재인코딩 금지) — 스냅샷을 손으로 고치지 않는다(원본이 진실). 갱신 누락은 로컬 verify V4가 탐지(§4.2).

## 10. CLI 설계 — `archive_precedents.py`

Plan 4.1의 `--extract`/`--verify` 플래그 표기는 **서브커맨드로 변경**한다(검증 L2 — 상호배타 동작이라 서브커맨드가 argparse 관례에 맞다).

```bash
python3 archive_precedents.py build              # 로컬 원본 → 번들+장부+스냅샷 (오프라인)
python3 archive_precedents.py build --pinecone   # + ctx·사장 NS 벡터 열거 스냅샷 (유일한 네트워크 경로, 조회 전용)
python3 archive_precedents.py gate               # 자동 3-버킷 + 표본 추첨 목록 출력 (§7)
python3 archive_precedents.py gate --approve --as-of 2026-09-02  # 육안 완료 후 verbatim 승격 확정
python3 archive_precedents.py extract 2000다15869  # 번들 → md 복원 (stdout 또는 --out)
python3 archive_precedents.py verify             # §8 (원본 유무로 범위 자동 축소)
```

- **Pinecone에 쓰는 경로가 없다** — `--pinecone`도 조회 전용. 원장은 읽기 전용(Plan 4.5). `NS-CONTRACT` 마커 불요(적재 자체가 없음 — `test_offline_units.py::test_upload_namespace_contract`는 `pinecone_upload*.py`만 순회하므로 파일명 규약상으로도 대상 아님).
- `extract`는 case_no로 조회하되 동일 사건 문서가 여럿이면(letec+crawl) 전부 나열하고 doc_id 선택을 받는다.
- import 재사용(사본 금지): `pinecone_upload_court_precedents.case_no_to_ascii`(D-10)·`fetch_court_precedents.extract_representative_case_no`(D-4)·`fetch_court_precedents.normalize_case_no`·`extract_textbook_cases.CASE_RE`. ⚠️ 초판이 지목한 `pinecone_upload_legal._case_no_to_ascii`는 **원장 생산 함수가 아니다** — 매핑표 사본이 legal·court·`upload_new_precedents.py` 3벌 존재하는 기존 문제는 이 사이클 범위 밖(공용 모듈 통합은 후속 — 지금 필요한 것은 "원장과 같은 답"이고 그것은 court import로 충족).

## 11. 회귀 설계 (T27, `test_precedent_ingest.py`)

전부 오프라인·픽스처 내장(gitignore 데이터 없이 CI 실행 — 기존 관례).

| ID | 검사 | 고정하는 실패 모드 |
|----|------|-------------------|
| T27-a | 픽스처 md(NFD 파일명 포함) → 레코드: 필수 필드 + case_no NFC + body_md 바이트 보존 | NFD 오추출·본문 변형 |
| T27-b | 아카이브의 case_key 함수가 `pinecone_upload_court_precedents.case_no_to_ascii`와 **같은 객체**(is 동일성) + `UnknownCaseCode` 픽스처 → case_key null·note 기록 | 원장 키 규약 이탈·유틸 사본 드리프트(M1 클래스) |
| T27-c | 대표 판정: 본문 1,500자 **밖**(참조판례 위치)에만 사건번호가 있는 픽스처 → 대표 없음(post); 1,500자 안 서두 선고문 픽스처 → 채택 | 참조판례 함정·fetch 판정과의 괴리 |
| T27-d | 게이트 불변식: editorial/post/pending 레코드를 공개 번들에 넣으면 V7 실패 | 오공개 |
| T27-e | extract round-trip: build→extract 결과 == 원본 픽스처 바이트 | 복원 손실(S4) |
| T27-f | 같은 픽스처로 build 2회 → 번들·CSV 바이트 동일 | gzip mtime·순서 비결정(S6) |
| T27-g | 원장 픽스처의 case_key가 inventory에 없으면 V4 실패 | 원장 포섭 구멍(S2) |
| T27-h | 구조 마커 분류기 3픽스처: verbatim(순수 판결문) / **서두 요약 6줄** / **말미 해설 6줄** — 뒤 둘은 editorial(검증 M1) | 게이트 휴리스틱 회귀(양끝) |
| T27-i | 크롤 세대·대표 채택 5픽스처(§6): 신세대-메타 / 구세대-파일명 / 구세대-겹침대응(case_src=overlap) / 게시물형 / **비법원 번호(진차) → 화이트리스트 기각** | 세대 혼재·비법원 번호 오채택 |
| T27-j | 정준형 병합: `1992다28556` 픽스처 → `92다28556` 행으로 병합 + case_alias 보존 | 표기 변형 이중 행(M7) |

## 12. 실행 순서 (Do 체크리스트)

1. `archive_precedents.py` 구현(§3~§10) + T27 회귀 — 픽스처 선행 가능 항목(T27-a~c·e·f·j)은 TDD로
2. `build` 실행 → 실측 보고: 사건 수(S1 — 예상 2,900~3,300 범위 확인), 오류·불일치·화이트리스트 기각 목록 검토, letec 1,578 vs 원장 1,568 차이 10건 건별 사유 → note(R4)
3. `records/code_citations.csv` 검토 → `2021헌마1234` 등 docstring 예시 판정 확정 → note
4. `gate` 실행 → 버킷 분포 실측 → 임계값 확정 → 표본 80건 육안 → `--approve` 또는 비공개 종료
5. `verify` 전체 통과 → `.gitignore` 2줄 추가 → `data/precedent_archive/` 커밋(crawl_verbatim은 게이트 결과에 따라)
6. 게이트 미통과 잔여 crawl은 `precedent_crawl_YYYYMMDD.tar.gz` + 저장소 밖 보관
7. CLAUDE.md 갱신: 아카이브 절차·공개 경계·"수집·업로드 후 build 재실행" 규칙 + **낡은 수치 정정**(`_미발견` 156→967 — 검증 H5)
8. CI: `test_precedent_ingest.py`는 이미 편입(T27 자동 포함). `verify`의 CI 편입은 번들 파싱 시간 실측 후 후속 판단

## 13. 리스크 (Plan §6 계승 + 설계 신규)

| ID | 리스크 | 대응 |
|----|--------|------|
| R1 | 제목·메타·겹침대응 어디에도 사건번호가 없는 실제 판결문 → post 오분류 | 수용(§6 위음성 논리). 공백 목록이 후속 수집을 데려온다 |
| R2 | 게이트 표본 육안의 판정 일관성 | §7.2 기준을 "블록 밖 실질 텍스트 유무"로 좁게 고정. 애매하면 editorial(보수) |
| R3 | gz 번들 크기(letec 5.2MB + crawl 1.8MB) | BM25 19MB 선례 이내. MANIFEST `bytes` 기록, 20MB 초과 시 분할 검토 후속 |
| R4 | letec md 1,578 vs 원장 1,568 차이 10건 | Do #2에서 건별 사유(임베딩 불가 1·폐기·미업로드) 확정 후 note — V4는 "원장→inventory" 방향만 강제하므로 차이 자체는 실패 아님 |
| R5 | fetch 함수 import로 인한 결합 — fetch의 판정 순서 변경이 아카이브 판정을 바꾼다 | 의도된 결합(같은 답이 목적). T27-c·i가 현재 계약을 고정하므로 fetch 변경 시 회귀가 울린다 |
| R6 | 신규 수집 후 build 재실행 누락 → 스냅샷 낡음 | 로컬 verify V4가 `snapshot_origin_digests` 대조로 탐지(§4.2). **CI 단독으로는 못 잡는다** — 커밋 전 로컬 verify가 유일한 탐지점임을 CLAUDE.md에 명시(Do #7) |
| R7 | `vec_dead` 역매핑 불완전(사장 NS는 NFD 손상 이력) | 가능분만 기록 + MANIFEST scope_notes에 한계 명시. 완전 복원은 비목표(Plan) |

## 변경 이력

- 2026-08-30: 초판. Plan 대비 수정 2건 — NLRC 인벤토리 제외(D-6), 장부 2파일 분리(D-3). 크롤 2세대 혼재(350/486) 실측 반영.
- 2026-09-01: **design-validator 검증(74/100) 반영 개정.** High 5 — case_key를 원장 생산 함수(court)로 교체·hex 폴백 제거(H1→D-10), 대표 판정을 fetch 함수 import로 수렴+화이트리스트 게이트(H2→D-4), 겹침대상 286쌍을 대표 채택 경로로 승격해 vec_ctx 채움(H3→§6), 코드 인용 범위 확장+MAJOR_PRECEDENTS 구조 열거(H4→§2.4), `_미발견` 156→967 정정(H5). Medium 10 — 게이트 블록 양끝 정의(M1), detc 서술 정정(M2), MANIFEST 스키마+V0(M3), 스냅샷 낡음 탐지(M4), vec_dead(M5→D-11), code_citations.csv(M6), 정준형·별칭(M7), _index 대조(M8), .gitignore 델타(M9), 파일명-메타 불일치 보고(M10). Low 10 반영(폴더 5종 실측 정정 포함 — 검증자의 6종도 색인 기준이라 부정확).
- 2026-09-01(Do 후): **gap 분석(96.9%) 반영 — 구현 확정 사항 역반영.** 게이트 규칙 v3 확정(§7.1 — v2 종결 문구 앵커: 서명 없는 크롤 서식 473건 오폐기 해소, v3 육안 발견 혼입 패턴: ※ 안내문·JS 잔재), `--approve` 재추첨 금지+rounds 이력(§7.3, gap M1), 연도 유효성 게이트·2자리 오탐 수용(§2.4), 예시 확정 저장처=코드 상수(§2.4, gap 판정 타당), note 어휘 확정+R4 사유 단일 확정(§5.1 — 10건 전부 "전문만, EMBED_SECTIONS 부재"), overlap 실적 0건 정정+vec_ctx 3중 대응 맵(§6), 색인 대조 선두 토큰 기준(§2.2 취지 유지 — 파일명 문자열 대조는 105건 오탐).
