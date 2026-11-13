# source-pack-held-articles — Design

> Plan: `docs/archive/2026-11/source-pack-held-articles/source-pack-held-articles.plan.md`(v0.2, P1 결과 부록 포함)
> 상위 사이클: source-pack-refresh(아카이브 `docs/archive/2026-11/source-pack-refresh/`)
> 작성일: 2026-11-13 · 상태: Draft

## 1. 확정된 사실 (P1)

| 항목 | 값 |
|---|---|
| 대상 | 고용보험법 시행령 제60조의2·제104조의8·제104조의15 (현행 시행 2026-09-18, 대통령령 제36588호, lsiSeq 288717) |
| 손실 | 법제처 eflaw 텍스트(XML·JSON 공통)의 상자 표 계산식에서 `≤`(U+2264) 하나가 `?`(0x3F)로 바뀜. 앞의 `－`(U+FF0D)는 빼기로 맞다 |
| 근거 ① | XML `<img>` 조문 이미지(flSeq 129419233·129419251·102803845) — 사람 판독 |
| 근거 ② | law.go.kr 화면 `LSW/lsInfoR.do?lsiSeq=288717&efYd=20260918`의 같은 이미지 `alt` = `@@LATEX@@1- … \leq … + …@@/LATEX@@` — 기계 판독 가능 |
| 손실 위치 | 조문마다 정확히 1곳(`÷ 180일 ? 예술인`·`÷ 9개월 ? 근로자`·`÷ 12개월 ? 근로자`) |

## 2. 결정

| ID | 결정 | 근거 |
|---|---|---|
| D1 | 새 대상 파일 `data/source_pack_refresh/targets_{batch}.json` — `ei-decree` 3조문만. `batch`는 Do 당일 날짜(YYYYMMDD). supersede 없음(구 배치에 없는 조문) | 20261112 배치·원장은 건드리지 않는다(원장 불변 규칙) |
| D2 | **처리 방식 B** — `?`를 `≤`로 치환하고 정정 기록을 대상 파일·원장·청크 머리글에 남긴다 | 근거가 법제처 자신이라 출처 대응이 유지된다. A(본문 그대로 + 주석)는 검색·LLM이 `?` 식을 그대로 읽고, C(PDF·관보)는 새 원문 조사가 필요하다 |
| D3 | 정정은 **문맥 문자열 정확 치환**(`find` → `replace`)이고 본문에서 **정확히 1회** 일치해야 한다. 0회·2회 이상이면 prepare 중단 | 원문이 바뀌면(개정·법제처 변환 수정) 조용히 엉뚱한 곳을 고치거나 무효가 되는 것을 막는다 |
| D4 | 정정 근거 **자동 대조**(fail-closed): fetch가 정정이 가리키는 이미지(flSeq)와 화면 HTML을 함께 받고, prepare가 ① 이미지 sha256 = 기록값 ② 화면 HTML에서 그 flSeq `<img>`의 `alt` LaTeX가 기록한 `latex_token`(`\leq`)을 포함 — 둘 다 맞아야 치환한다. 사람 판독(검토 표)은 그대로 필수 | 사람 판독만으로는 다음 갱신 때 이미지가 바뀐 것을 알 수 없다. LaTeX는 기호의 '존재'만 보증하고 위치는 D3 문맥이 보증한다 |
| D5 | **G1 `suspect_glyph`** — 상자 표 문자가 있는 줄의 `?`(0x3F)·`�` 개수를 정정 **후** 본문에서 센다. review 표에 `의심 문자` 열, upload는 남은 의심 문자가 있는 조문의 `적재` 판정을 거절(판정에 `의심 문자 확인:` 사유가 있으면 통과) | Plan R6. 정정이 없는 손실은 사람이 근거를 적지 않는 한 적재되지 않는다 |
| D6 | 메타데이터 키는 **늘리지 않는다**. 정정 사실은 청크 머리글 한 줄(`정정: 계산식의 '?'를 '≤'로 — 법제처 조문 이미지·화면 수식 대조`)과 원장 `documents[wid].corrections`에 둔다 | S5(기존 배치와 같은 19키) — 공식 증거 2차 조회·BM25 빌더가 같은 필드를 읽는다. 머리글은 LLM이 읽는 근거라 정정 사실이 본문과 함께 간다 |
| D7 | R8(기존 배치 G1 집계)은 새 명령 없이 Do에서 `suspect_glyphs()`를 자료팩 원본(`~/DEV/laborconsult_eval/source-integration-20261009/cleaned/*.json`)과 20261112 prepared 산출물(있으면)에 돌려 **건수만** 분석 문서에 적는다 | 범위 밖 정정을 이번 사이클에서 하지 않는다(Plan §2) |

## 3. 데이터 형식

### 3.1 대상 파일 `corrections`

```json
{
 "batch": "{batch}", "as_of": "{YYYY-MM-DD}", "prior_ledger": "data/vector_ledgers/qpack_20261112.json",
 "laws": [{"work_id": "ei-decree", "law": "고용보험법 시행령", "articles": ["60의2", "104의8", "104의15"]}],
 "corrections": [
  {"work_id": "ei-decree", "article": "60의2",
   "find": "÷ 180일 ? 예술인", "replace": "÷ 180일 ≤ 예술인",
   "image_flseq": "129419233",
   "image_sha256": "432854070afb4fe94fc15c09cf2b534f866597c170eff2648814b3b3b41e4350",
   "screen_url": "https://www.law.go.kr/LSW/lsInfoR.do?lsiSeq=288717&efYd=20260918&chrClsCd=010202&ancYnChk=0",
   "latex_token": "\\leq", "reviewed_by": "사람 판독(이미지) 2026-11-13"},
  {"…": "104의8 — find '÷ 9개월 ? 근로자', flSeq 129419251, sha 5e329b07…"},
  {"…": "104의15 — find '÷ 12개월 ? 근로자', flSeq 102803845, sha 922bd3fd…"}
 ]
}
```

`find`·`replace`는 `clean()` 뒤 본문 기준(공백 1칸 축약 후)이다. `find`와 `replace`는 `?` ↔ 한 글자만 달라야 한다(prepare가 검사 — 정정이 다른 글자를 바꾸지 못하게).

### 3.2 작업 디렉터리 추가 산출물

| 파일 | 내용 |
|---|---|
| `{batch}/img_{flSeq}.gif` | fetch가 받은 조문 이미지(gitignore — 기존 XML과 같은 취급) |
| `{batch}/{work_id}.screen.html` | 화면 HTML(gitignore). 키 불요 경로라 `OC` 미포함 |
| `fetch_manifest.json` | 기존 + `"assets": {flSeq: sha256, "screen:{work_id}": sha256}` |
| `prepare_rows.json` | prepare 행(`suspect_glyph` 포함) — upload 관문이 읽는다 |

### 3.3 원장

`documents["ei-decree"].corrections = [{article, find, replace, image_flseq, image_sha256, screen_url, latex_token, reviewed_by}]`. `test_committed_vector_ledgers`·`source_pack_ledger.py verify`는 문서의 추가 키를 읽지 않으므로 형식 변경 없이 통과해야 한다(Do에서 확인).

## 4. 코드 변경 (`source_pack_refresh.py`)

| 함수 | 변경 |
|---|---|
| `suspect_glyphs(body) -> int` (신규) | `BOX_CHARS`가 있는 줄의 `?`·`�` 수. IMG 태그는 `article_body`가 이미 지워 URL의 `?`는 셀 일이 없다 |
| `apply_corrections(body, fixes) -> (body, notes)` (신규) | D3: 각 fix의 `find`가 정확히 1회, `find`/`replace` 길이 같고 다른 글자 1개(`?`→기호)인지 검사 후 치환. 위반 시 `SystemExit` |
| `verify_correction_sources(spec, out)` (신규) | D4: manifest `assets`의 이미지 sha256 = `image_sha256`, 화면 HTML에서 `<img[^>]*flSeq={flSeq}[^>]*>`의 `alt`에 `latex_token` 포함. 하나라도 어긋나면 중단 |
| `fetch` | `spec.get("corrections")`가 있으면 이미지(`https://www.law.go.kr/flDownload.do?flSeq=`)·화면 HTML(정정별 `screen_url`, 중복 제거)을 받아 저장·해시 기록. 화면은 키 없는 경로 — `requests`에 `OC`를 넘기지 않는다 |
| `prepare` | `article_body` 뒤 `verify_correction_sources`(1회) → `apply_corrections` → `suspect_glyphs`. 정정이 있으면 머리글에 `정정:` 줄 추가(D6). 행에 `suspect_glyph`, `corrected` 기록, `prepare_rows.json` 저장 |
| `write_review` | 표에 `의심 문자`·`정정` 열 |
| `approved_vectors` | `prepare_rows.json`에서 남은 `suspect_glyph > 0`이고 판정이 `적재`인데 `의심 문자 확인:`이 없으면 `SystemExit`(D5) |
| `build_ledger` | 정정이 있는 문서에 `corrections` 기록 |
| docstring | `corrections`·G1 규칙 한 단락 |

`corrections`가 없는 대상 파일(20261112)은 동작이 바뀌지 않아야 한다 — 단, 20261112 산출물을 다시 prepare하면 G1이 3조문을 표시한다(그 조문은 이미 `보류` 판정이라 upload 영향 없음).

## 5. 테스트 (`test_source_pack_refresh.py`, CI)

| ID | 검사 |
|---|---|
| H1 | `suspect_glyphs`: 상자 표 줄의 `?`·`�`만 센다(상자 밖 문장 `?`·이미 지운 URL 0) |
| H2 | `apply_corrections`: 1회 일치 치환 / 0회·2회 중단 / `find`·`replace`가 2글자 이상 다르면 중단 |
| H3 | `verify_correction_sources`: 이미지 sha 불일치 중단 · alt에 `\leq` 없음 중단 · flSeq `<img>` 없음 중단 · 정상 통과(합성 HTML·바이트 fixture) |
| H4 | 커밋된 새 대상 파일의 정정 3건이 커밋된 fixture(`data/source_pack_refresh/fixtures/` — 세 조문의 `clean()` 후 본문 텍스트, 이미지·화면 없음)에 각각 정확히 1회 일치하고, 치환 후 `suspect_glyphs == 0` |
| H5 | `approved_vectors`: 남은 의심 문자 + `적재` → 중단, `적재(의심 문자 확인: …)` → 통과, `보류` → 제외 |
| H6 | 머리글 `정정:` 줄은 정정이 있는 조문 청크에만 |
| H7 | `build_ledger`: 정정 문서에 `corrections` 3건, 메타데이터 키는 S5 19키 그대로 |
| — | 기존 S5·S8 테스트를 대상 파일 목록(`targets_*.json`)으로 일반화 — 지금은 20261112 경로를 하드코딩 |

H4 fixture는 법제처 원문 조문 텍스트(공공저작물 — 저장소 공개 가능)다.

## 6. 실행 순서 (Do)

1. 브랜치 `feat/source-pack-held-articles` — 코드·테스트(H1~H7)·대상 파일·fixture → 오프라인 테스트 통과
2. 등록 회선에서 `fetch` → `prepare` → review 표 사람 검토(이미지와 대조, 판정 `적재`) → `upload`(dry-run 후 **사용자 확인** → `--apply`) → `ledger` → `source_pack_ledger.py verify`
3. `build_bm25_corpus.py`(+12문서 예상: 60의2 1·104의8 6·104의15 5) → gz 커밋 → BM25 메모리 테스트(CI Linux)
4. R7: 다중 직종 수급요건 질의 1~2건으로 새 청크 검색 확인(로컬 `eval` 계열, 프로덕션 화면 금지)
5. R8 집계(D7) → CLAUDE.md 보류 3조문 문장 갱신 + `corrections`·G1 규칙 한 줄
6. PR(머지 전 사용자 확인)

## 7. 위험

| 위험 | 대응 |
|---|---|
| 화면 HTML 구조가 바뀌어 `alt` LaTeX를 못 찾음 | D4가 중단(fail-closed) — 그때 사람이 이미지 판독으로 `latex_token` 검사만 대체하는 옵션은 두지 않는다(다음 사이클에서 판단) |
| 법제처가 텍스트 변환을 고쳐 `?`가 사라짐 | D3이 0회 일치로 중단 → 정정 항목을 지우고 그대로 적재 |
| 임베딩·업로드 비용 | 약 12벡터 — 무시 가능. 결제·크레딧 구매 없음 |
| laborlaw-v2 프로덕션 즉시 반영 | 업로드는 사용자 확인 후, 롤백은 원장 `rollback` + BM25 재빌드 |

## Version History

| 버전 | 날짜 | 내용 |
|---|---|---|
| 0.1 | 2026-11-13 | 초안 — 방식 B·근거 자동 대조·G1 |
