# source-pack-refresh — Design

> Plan: `docs/archive/2026-11/source-pack-refresh/source-pack-refresh.plan.md` · 작성: 2026-11-12 · 기준: main `9838261`
> 근거 조사: 법제처 현행판(eflaw) XML을 대상 6법령 받아 대상 12조문의 태그·이미지·상자 표·본문 길이를 셌다(2026-11-12, 회선 118.33.130.107). 받은 XML은 세션 scratchpad `spr/`(저장소 밖, 일회용)에 두었다.

## 0. 설계 결정 요약

| ID | 결정 | 근거 |
|---|---|---|
| D1 | **대상은 8조문** — 이미지 보류 7 + 국민연금법 제126조. 임금채권보장법 신설 4와 민사집행규칙 15는 제외 | §1.2 — 임금채권보장법 4조문은 현행판에서도 제목·항이 없는 빈 조문(본문 = "제3조의2" 5~6자)이다. 실을 내용이 없다. 민사집행규칙(가상자산 집행)은 노동 상담 빈도가 낮다(Plan Q1 권고) |
| D2 | 이미지 조문은 **`<img>` 태그와 `</img>`만 걷고** 그 사이의 상자 표 텍스트(`┌│└`)를 본문으로 쓴다. 상자 표 문자가 없으면 지금처럼 보류 | §1.1 — 7조문 전부 이미지 1~2개와 상자 표 60~264자를 함께 가진다. 표 텍스트가 이미지와 같은 산식·표를 담는다(3건 육안 확인) |
| D3 | 상자 표 텍스트는 **다듬지 않는다**(정렬 공백·선 문자 유지) | 원문 대조가 공백 무시 부분일치이고, 다듬으면 저장본이 원문과 달라진다(fetch_official_rules 별표 규칙과 같다). 줄바꿈은 `clean()`의 행 단위 공백 축약만 거친다 |
| D4 | 7조문 전부 **사람 검토 후 적재** — 표 텍스트가 산식을 빠짐없이 담는지 법제처 화면과 대조해 Design §7에 판정 기록. 불완전한 조문은 보류 유지 | Plan R1. 공식 원문으로 틀린 산식이 실리는 것이 누락보다 나쁘다 |
| D5 | **새 배치 `qpack_20261112_`**, 메타데이터 스키마는 기존 배치와 같음(`official: True`, `source_batch: sourcepack_20261112`, `version_scope: current_body`, `retrieved_on: 2026-11-12`). ID = `qpack_20261112_{work_key16}_{sha(section)10}_{k}` — `work_key`는 기존 배치와 같은 `sha(work_id)[:16]`라 문서 단위 대응이 유지된다 | Plan Q4. 같은 접두사를 재사용하면 원장의 '어느 날 스냅숏인가'가 흐려진다 |
| D6 | 국민연금법 제126조는 **구 ID 삭제 + 새 배치에 현행판 추가**. 삭제는 원장 `qpack_20261009.json`에서 그 조문 ID만(섹션 해시로 특정) 골라 dry-run → apply, 구 원장에는 `revision.superseded_by_20261112`로 ID 목록 기록 | 고아 벡터 방지(CLAUDE.md 원장 규칙). 문서 전체 롤백(`--document`)은 다른 조문까지 지운다 |
| D7 | 준비·적재 스크립트를 **저장소에 둔다** — `source_pack_refresh.py`(단계: `fetch` → `prepare` → `upload` → `verify` → `ledger`). 기존 저장소 밖 스크립트의 `clean`·청킹(`pinecone_upload_official_rules.split_text`)·메타데이터 규칙을 그대로 옮긴다 | Plan Q5. 다음 스냅숏 갱신을 같은 절차로 반복하려면 저장소에 있어야 한다. 원본 팩(`~/Downloads/…`) 의존은 없앤다 — 법제처에서 직접 받는다 |
| D8 | BM25는 **전체 재빌드**(`build_bm25_corpus.py`) | 증분 병합은 저장소 밖 스크립트에만 있었다. 전체 재빌드가 관례이고 가드 3종(감소 20% 등)이 있다. 약 3.5시간 |
| D9 | 조문 키 대조를 저장소 스크립트 하위 명령으로 둔다(`source_pack_refresh.py audit`) — 원장의 섹션 키 ↔ 현행판 조문 키, 노동 관련 법령만 실패로 센다 | Plan 완료 조건 2. 다음 갱신의 입력을 자동으로 만든다 |
| D10 | 임베딩·업로드·BM25는 **사용자 확인 후** 실행(비용·프로덕션 반영). fetch·prepare·audit·테스트는 무확인 | laborlaw-v2는 프로덕션이 읽는 NS다 — 업로드 즉시 검색에 섞인다 |

## 1. 근거

### 1.1 이미지 보류 7조문 (현행판 2026-11-12)

| 법령·조문 | 제목 | img | 상자 표 문자 | 본문 길이 | 표의 내용 |
|---|---|---|---|---|---|
| 고용보험법 시행령 제60조의2 | 피보험 단위기간 산정 | 1 | 90 | 660 | 근로자·예술인·노무제공자 합산식 |
| 고용보험법 시행령 제104조의2 | 육아기 근로시간 단축 급여 | 1 | 210 | 1,203 | 최초 10시간분(상한 250만·하한 50만)·나머지(80%, 상한 160만) 산식 |
| 고용보험법 시행령 제104조의8 | 예술인 구직급여 수급요건 등 | 1 | 98 | 3,196 | 소득감소 비교식 |
| 고용보험법 시행령 제104조의15 | 노무제공자 구직급여 수급요건 등 | 1 | 98 | 2,734 | 소득감소 비교식(30% 이상 감소) |
| 고용보험법 시행규칙 제105조 | 부정행위에 따른 추가징수 등 | 2 | 264 | 2,279 | 횟수별 비율 표(3회 미만 100분의 100 · 3~5회 150 · 5회 이상 200) |
| 국민건강보험법 제71조 | 소득월액 | 1 | 60 | 412 | (연간 보수 외 소득 − 대통령령 금액) × 1/12 |
| 퇴직급여법 시행령 제8조 | 급여 전액지급 예외 사유 | 1 | 121 | 644 | 퇴직급여 누계액 ÷ (적립금 + 부담금) 비율 |

제105조·제71조·제8조는 표 텍스트를 육안으로 확인했다 — 이미지와 같은 산식·표가 텍스트로 있다.

### 1.2 임금채권보장법 신설 4조문

제3조의2·제13조의2·제16조의2·제19조의2는 현행판(시행 2026-08-20)에서 `조문제목`이 비고 `항`·`호` 태그가 없으며 `조문내용`이 조문 번호뿐이다(5~6자). 실질 내용이 없는 자리 조문이라 적재하지 않는다. 다음 판본(2026-12-08 타법개정)에서 본문이 생기면 `audit`가 다시 잡는다.

### 1.3 국민연금법 제126조

현행판 시행 2026-10-20, 본문 1,854자(외국인 당연적용·반환일시금). 자료팩 본문과 유사도 0.72(calculator-statute-audit §4.4).

## 2. 모듈 구조 — `source_pack_refresh.py`

```
python3 source_pack_refresh.py fetch   --out data/source_pack_refresh/20261112/        # 법제처 eflaw XML 6종 저장(등록 IP)
python3 source_pack_refresh.py prepare --in  …/20261112/ --targets targets_20261112.json  # 대상 조문 → prepared_vectors.jsonl + review.md
python3 source_pack_refresh.py upload  --prepared … [--apply]                            # 임베딩·upsert(기본 dry-run, 선존재 0 확인)
python3 source_pack_refresh.py verify  --prepared …                                      # fetch로 text·chunk_sha256 대조
python3 source_pack_refresh.py ledger  --prepared … --out data/vector_ledgers/qpack_20261112.json
python3 source_pack_refresh.py supersede --old data/vector_ledgers/qpack_20261009.json --section-key <work_id>:<section> [--apply]
python3 source_pack_refresh.py audit   [--offline]                                       # 원장 섹션 키 ↔ 현행판 조문 키
```

- `fetch` 산출 XML은 **커밋하지 않는다**(`data/source_pack_refresh/`를 `.gitignore`에) — 크기가 크고 법제처에서 다시 받을 수 있다. sha256만 원장에 남긴다.
- `targets_*.json`(커밋): `[{work_id, law, article, reason}]` — 이번 8건. `work_id`는 기존 팩의 id(`ei-decree`·`ei-rule`·`ei-nhis-act-current`·`general_law_retirement_enf`·`general_law_nps`).
- `prepare`의 본문 규칙: 조문단위에서 `조문내용·항내용·호내용·목내용` 텍스트를 `clean()`(저장소 밖 스크립트 그대로)로 모으고, `<img …>`·`</img>` 태그만 제거(D2). 상자 표 문자가 없는데 이미지가 있으면 그 조문은 `held`로 내보낸다.
- 청크·헤더·메타데이터는 기존 `prepare()`와 같은 형식(`{title} — {section}\n공식기관: …\n수집 기준일: 2026-11-12 | 조문/규칙 시행일: …`), `pinecone_upload_official_rules.split_text`로 자른다. `rights_basis`는 기존 권리 검토의 `copyright_act_article7_primary`(법령 — 저작권법 제7조 비보호).
- 국민연금법은 기존 배치의 현재 적용 부칙 주석(`operative_supplement_contexts.json` — 부칙 제20903호 제4조 등)을 제126조에는 붙이지 않는다(그 부칙들의 `affected_articles`에 제126조가 없다 — prepare에서 확인해 기록).
- `review.md`(커밋): 조문별 표 텍스트 원문·청크 수·사람 판정 칸.

## 3. 데이터 흐름

1. fetch(등록 IP) → XML 6종 + sha256
2. prepare → 8조문 청크(예상 20~40개) + review.md → **사람 검토(D4)**
3. 확인 후 upload `--apply`(임베딩 text-embedding-3-small, 비용 수 센트)
4. verify → ledger(`qpack_20261112.json`, `state: verified`)
5. supersede 국민연금법 제126조 구 ID dry-run → apply, 구 원장 `revision` 갱신
6. `source_pack_ledger.py verify` 두 원장
7. BM25 재빌드(D8) → gz 커밋 → CI(BM25 메모리)
8. audit → 누락 0(노동 관련)·제126조 본문 일치

## 4. 테스트 (`test_source_pack_refresh.py`, CI)

| ID | 단언 |
|---|---|
| S1 | 이미지 + 상자 표 fixture → 본문에 표 텍스트 포함, `<img`·`</img>` 없음 |
| S2 | 이미지만(상자 표 없음) fixture → held |
| S3 | 빈 조문(임금채권보장법형: 제목 없음·항 없음·본문 ≤ 10자) → skip(held 아님, 사유 `empty_article`) |
| S4 | ID 형식 `^qpack_20261112_[0-9a-f]{16}_[0-9a-f]{10}_\d+$`, work_key = sha(work_id)[:16]가 기존 원장의 같은 문서 키와 같음 |
| S5 | 메타데이터 키 집합이 기존 배치 샘플과 같음(`official` True·`source_batch`·`chunk_sha256`·`version_scope`) |
| S6 | supersede: 구 원장에서 섹션 키로 고른 ID가 그 조문 것만이고(다른 섹션 0), dry-run은 쓰기 0 |
| S7 | 커밋 원장 형식(`test_offline_units.py::test_committed_vector_ledgers`가 새 원장도 순회) |
| S8 | `targets_20261112.json`의 8건과 review.md 판정 칸이 모두 채워졌는지(적재 전 관문) |

fixture는 이번에 받은 XML에서 해당 `조문단위` 발췌만(`data/source_pack_refresh/fixtures/*.xml`, 커밋).

## 5. 위험 대응 (Plan §3 보강)

- R1 → D4 + S8. R2 → `upload`가 선존재 fetch 0을 확인(기존 관례). R3 → D6·S6. R4 → CI 메모리 테스트. R5 → 업로드 뒤 `python3 sync_legal_rules.py --topic minimum_wage`(읽기 전용) 1회. R6 → fetch 산출물을 먼저 저장하고 이후 단계는 오프라인.
- 추가 R7: 새 청크가 공공 쿼터·인용 화이트리스트에 들어간다(`regulation` = 공공) — 동작 변화가 기대된 효과다. 재결례처럼 별도 배선은 필요 없다(기존 `qpack_` 배치와 같은 source_type).

## 6. CLAUDE.md 갱신

- `laborlaw-v2` 벡터 수·구성 줄에 `qpack_20261112_` 추가분과 국민연금법 제126조 대체를 적는다.
- 명령 절에 `source_pack_refresh.py` 사용법, 원장 규칙 절에 "스냅숏 갱신은 새 배치 + supersede" 한 줄.

## 7. 사람 검토 기록 (Do, 2026-11-12)

판정 원문은 `data/source_pack_refresh/review_20261112.md`. prepare 결과 8조문 → 23청크, 그중 **적재 5조문 11청크**.

| 조문 | 판정 | 사유 |
|---|---|---|
| 시행령 제60조의2 | 보류 | 계산식의 연산 기호 1개가 **법제처 텍스트 자체에서 `?`(0x3F)로 빠져 있다** — 이미지에만 원 기호가 있다. 틀린 식이 실릴 수 있음 |
| 시행령 제104조의2 | 적재 | 두 열 표가 줄 단위로 섞이지만 최초 10시간분(상한 250만·하한 50만·×10÷단축 전 소정근로시간)·나머지(80%·상한 160만·하한 50만) 항목이 모두 있다 |
| 시행령 제104조의8 | 보류 | 제60조의2와 같은 계산식(`?`) |
| 시행령 제104조의15 | 보류 | 같은 계산식(`?`). ① 소득감소 30% 요건 본문은 온전하나 조문 단위로 보류(D4) |
| 시행규칙 제105조 | 적재 | 표 두 개(일반 100·150·200/100, 사업주 공모 300·400·500/100) 모두 텍스트 |
| 국민건강보험법 제71조 | 적재 | (연간 보수 외 소득 − 대통령령 금액) × 1/12 |
| 퇴직급여법 시행령 제8조 | 적재 | 퇴직급여 누계액 ÷ (적립금 + 부담금) |
| 국민연금법 제126조 | 적재 | 이미지 없음, 현행판 2026-10-20 |

**설계 밖 발견:** 이미지 조문의 표 텍스트가 원 기호를 잃은 경우가 있다(D2의 전제 일부 실패). 상자 표 문자 유무만으로는 판정할 수 없어 사람 검토(D4)가 실제로 걸러냈다. 보류 3조문은 법제처 화면 이미지로 원 기호를 확인한 뒤 텍스트에 주석을 다는 방식(본문 불변, 헤더에 "[원문 식의 연산 기호: ≤ — 이미지 확인]")을 후속으로 둔다.

## Version History

| 버전 | 일자 | 내용 |
|---|---|---|
| 1.0 | 2026-11-12 | 초판 — D1~D10(대상 8조문, 표 텍스트 채택, 새 배치 + supersede, 저장소 스크립트), 테스트 S1~S8 |
