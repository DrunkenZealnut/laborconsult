# adjudication-corpus — Design rev2

> Plan: `docs/01-plan/features/adjudication-corpus.plan.md`
>
> **결정**(2026-11-08, 사용자 "권고안대로 진행" — Plan §6 권고 7건 확정):
> - D1: 출처 유형은 **`ruling` 하나** + 메타 `agency`(`eiac`|`iaciac`)·`category`. 라벨 '재결례'.
> - D2: iaciac **전량 934**. BM25 관문(CI RSS 550MB) 미달 시 2016년 이후로 축소(§4.6).
> - D3: 청킹 대상은 **머리글 + 개요/쟁점 + 주문 + 이유**. 청구인·청구취지 제외.
> - D4: 인용 검증에 **재결 번호 패턴 + 화이트리스트**(판례와 같은 규약). 컨텍스트 밖 번호는 제거·교정.
> - D5: 출처 우선순위 메모에서 **판례 아래, 행정해석과 같은 층(3항)**.
> - D6: **원장(ID 목록)만 커밋**. 원문은 `output_재결례/`(gitignore).
> - D7: 측정 약 348답변(gpt-6-sol) — **실행 전 승인**(§8.4). 2026-11-08 사용자 "D7 승인".
>
> **기준 코드:** `main` 1f19366(PR #153·#154 머지 뒤). 파일·함수 이름은 그 코드 기준이다.
>
> **설계 단계 실측(2026-11-08):** 두 위원회 목록·상세 XML을 실제로 받아 필드명·루트 태그·본문 구조를 확정했다(§1). 설계에서 새로 드러난 것 셋 — ① iaciac의 `사건` 필드가 `2010재결 제2071호 요양불승인처분취소`처럼 **eiac형 번호를 접두사로 갖는다**(두 기관의 번호 표기가 겹친다, D8·D12) ② eiac `이유`·`청구취지`에 HTML 잔재(`<span style="display:none;">`·`<각주>`·`<img>`)가 있고 `<근로계약서 발췌>`처럼 **태그가 아닌 꺾쇠 캡션**도 있다(D9) ③ `이유`는 `1. 사건개요 … 7. 결론` 소제목 구조이고 iaciac은 관계법령 소절에 **당시 법령 전문**을 인용하며 그 안의 `가.·나.·다.`가 소절 표기와 겹친다(D9).
>
> **rev2(2026-11-08):** design-validator 72점(High 3·Medium 11·Low 13). 지적 전부를 코드·fixture·실답변으로 재현했고(§12), 다음이 바뀌었다.
> - **패턴 B는 기관 문맥이 있을 때만** 검증한다(H1). rev1의 `제` 배제만으로는 BM25 코퍼스 438건(전부 고시·공고 번호)과 실답변 "고시(2025-124호)"·"고시 2018-23호"가 환각 재결로 지워졌다.
> - **소절 경계는 짧은 제목·어휘 목록으로만** 인식한다(H2·M4). iaciac 12699의 관계법령 소절 안 `가.~라.` 조문 목(目)이 소절로 오인돼 구 출퇴근 기준 조문이 '판단' 라벨로 임베딩됐다.
> - **측정 계측을 하네스 spy로** 한다(H3). `sources`는 5건 절단이고 쿼터·승격 항목은 맨 뒤라 재결례가 빠지며, 답변은 교정 뒤 본문이다.
> - `_PREC_PATTERN`에 **재결 구간 마스킹**을 앞세운다(M6 — `2015-1987호 2015. 8. 27.`이 `1987호2015` 환각 판례가 됐다).
> - 교정 문구 라벨은 그대로 둔다(M5 — K12가 고정). `rag_sources` 관측 키를 저장한다(M8). `--prune-missing`은 원장에 그룹 삭제 메서드를 신설한다(M9). BM25 관문을 측정 **앞**으로 당긴다(M10). 재결례를 뺀 공공 지표(M11), `case_name`/`title` 분리(M12), 별칭 충돌·기관 불일치 판정(M13), PII 정규식·가림 목록(M14). Low 13건은 §12.

## 0. 설계 결정

Plan 확정분(D1~D7)에 설계에서 더한 결정이다. 번호는 Plan에 이어 붙인다.

| # | 결정 | 근거 |
|---|---|---|
| D8 | **제목·번호 정규화.** 메타 `case_name` = 사건명(iaciac `사건`에서 선행 `^\d{4}\s*재결\s*제\s*\d+\s*호\s*` 제거), 메타 `title` = `{기관명} {사건번호} — {case_name}`(≤200자). `case_no`는 각 기관의 `사건번호` 필드 그대로(eiac `2019재결 제117호`, iaciac `2010-2071호`). 의결일자는 `YYYY.MM.DD`로 0 채움(`2010.8.27` → `2010.08.27`) | 두 기관의 `YYYY재결 제N호` 표기가 겹쳐(§1.2) 한 컨텍스트에 두 형태가 섞이면 LLM이 기관을 바꿔 인용한다. iaciac은 `사건번호` 필드(`YYYY-N호`)가 기관을 구분하는 표기라 그것을 정식 번호로 쓴다. `title`에 기관명·번호가 들어가야 `format_pinecone_hits` 머리줄·`citation_relevance.classify_paths`(title\|case_no에서 primary 판정)·M2 추출이 번호를 본다 |
| D9 | **이유는 소제목 단위로 자른 뒤 700/80으로 나눈다.** 소제목 인식은 세 조건을 **모두** 만족할 때다 — (a) 줄머리 `^\s*(\d+)\.\s*(\S.{0,40})$`(상위) 또는 `^\s*([가-하])\.\s*(\S.{0,40})$`(소절) (b) **제목이 짧다**(표식 뒤 12자 이하, 공백 제거 기준)이거나 어휘 목록 `관계\s*법령\|관련\s*법령\|사실\s*관계\|인정\s*사실\|의학적\s*소견\|판\s*단\|결\s*론\|사건\s*개요\|주장\|의견\|처분\s*내용\|위법·?부당` 중 하나를 포함한다 (c) 상위 번호는 직전 상위 +1, 소절 글자는 직전 소절 +1(`가→나→다`). 제외 규칙: 제목(공백 제거)이 `^관계법령(의내용)?$\|^관련법령$\|^관계법규$`면 **그 절 또는 소절을 다음 인식 경계까지 통째로 제외**한다. 정제는 **알려진 HTML 태그만** 다룬다 — 블록 태그(`p`·`div`·`br`·`tr`·`li`·`table`·`tbody`)는 개행으로, 인라인 태그(`span`·`font`·`b`·`i`·`u`·`strong`·`em`·`a`·`td`·`th`)는 빈 문자열로 바꾸고, `<span style="display:none;">…</span>`은 내용까지 지우며, `<각주>n</각주>`는 `[각주 n]`으로(뒤에 `(\d+\|[가-하])\.\s`가 이어지면 개행 삽입), `<img … alt="X"></img>`는 `[이미지 생략: X]`로 바꾼다 | iaciac 12699 `이유`의 관계법령 소절(37행 `가. 관계법령`)은 **의결 당시 법령 전문**이고 그 안에 조문 목(目) `가.~라.`(44~47행 — 47행이 2018년 이전 출퇴근 기준)와 호 `1.~4.`가 반복된다. rev1의 "순차 번호" 규칙만으로는 44행 `가.`·45행 `나.`가 소절 경계가 되어 구 조문이 `이유 — 다. 사업주가 제공한 교통수단…`으로 임베딩되고 실제 소절(77행 `나. 사실관계`·88행 `다. 의학적 소견`·132행 `라. 판 단`)은 그 밑으로 흡수된다(검증 H2 재현). 조문 목은 제목이 길고 문장형이라 '짧은 제목' 조건이 거른다. 그대로 임베딩하면 2010년 조문이 '재결례' 라벨로 실려 R3(낡은 기준)의 직접 경로가 된다. eiac 3행은 `…하였다.<각주>1</각주>다. 이에`로 각주 뒤에 소항목이 같은 줄에 붙어 있어(검증 M4) 개행 삽입이 없으면 `다.` 소항목을 잃는다. 꺾쇠를 전부 벗기면 `<근로계약서 발췌>` 캡션이 사라지므로 화이트리스트 태그만 다룬다. 이미지(eiac 18·21행 — 근로계약서·근무표)는 본문에서 사라지므로 자리 표시를 남긴다(검증 L16) |
| D10 | 벡터 ID는 `ruling_{agency}_{serial}_chunk_{idx}`(Plan의 `{idx:03d}` 대신 `_chunk_{idx}`). 원장 그룹 키 `{agency}_{serial}`, `group_re = ^(eiac\|iaciac)_\d+$`. `chunk_index`는 **정수** 메타 | court·regulation 업로더와 같은 규약이고 `legal_updates._CHUNK_SUFFIX_RE`도 이 접미사를 안다(법률 기준 검색은 `_TYPES` 필터로 재결례를 보지 않으므로 그쪽 영향은 없다 — 검증 L21). `build_bm25_corpus._fetch_once`가 `{"chunk_index": {"$gte": 0}}` 필터로 페이지를 돈다(검증 L23) — 정수가 아니면 재결례가 **BM25에서 통째로 빠진다** |
| D11 | **모든 청크의 `text` 첫 줄에 머리글**을 넣는다: `[{기관명} {사건번호} · 의결 {YYYY.MM.DD} · {분류}]`. `embed_text`도 같은 문자열이다 | BM25는 `text`만 토큰화한다(`_load_streaming`) — `title`에 번호가 있어도 번호 키워드 검색에는 소용없다. 의결일자는 R3의 유일한 본문 신호다(머리글 연도로 낡은 결정을 알아본다). 화이트리스트 등록은 `title`(D8)로도 되지만 BM25 경로 hit의 `chunk_text`에도 번호가 있어야 `classify_paths`의 `mentioned`가 성립한다 |
| D12 | 인용 검증 패턴과 **마스킹·별칭·기관 판정**. <br>A `(?<!\d)((?:19\|20)\d{2})\s*재결\s*제?\s*(\d{1,5})\s*호` → 키 `{Y}재결제{N}호`. <br>B **기관 문맥 필수**: `(?:산업재해보상보험\s*재심사\s*위원회\|산재\s*재심사\s*위원회\|재심사\s*위원회)[^.\n]{0,25}?((?:19\|20)\d{2})\s*-\s*(\d{1,5})\s*호?` → 키 `{Y}-{N}호`. 문맥 없는 `YYYY-N호`는 검증 대상이 **아니다**. <br>화이트리스트: `source_type == "ruling"`인 hit의 `case_no` 메타는 **문맥 없는 코어 정규식**으로 파싱해 등록하고 `agency`를 함께 기록한다. title·chunk_text는 A·B로 파싱한다. B 키에는 A 형태 별칭을 **실키가 없을 때만** 등록한다(실키 우선). <br>검증: 답변에서 A·B로 뽑은 키가 화이트리스트에 있고, 번호 앞 30자 안에 기관명이 있으면 그 기관이 등록 기관과 **같아야** valid다. 다르면 hallucinated. <br>`_PREC_PATTERN`은 **재결 구간을 공백으로 가린 뒤** 돈다(추출·검증 양쪽) — 가림은 문맥 없는 코어 A·B로 한다(가림은 삭제 권한이 없어 넓어도 안전하다) | rev1의 B(`제` 배제·`호` 필수)는 BM25 코퍼스 95,762문서에서 **438건**에 맞았고 전부 고시·공고 번호였다(`고용노동부고시 2015-77호`·`공고 2021-244호`·`고시(2025-83호).pdf`…). 실답변에도 `고시(2025-124호)`·`고용노동부 고시 2018-23호`가 있어 PR-A 배포 즉시 그 문장이 "관련 판례가 있을 수 있으나…"로 교정됐을 것이다(검증 H1 재현). 기관 문맥 요구가 그것을 막고, D18이 그 형식을 지시한다. `_PREC_PATTERN`은 `산업재해보상보험재심사위원회 2015-1987호 2015. 8. 27.`에서 `1987호 2015`를 판례로 잡았다(검증 M6 재현 — 번호가 1950~2030 범위고 뒤에 날짜가 오면). iaciac 번호는 수천대라 흔하다. `case_no` 메타는 기관명이 없어 B로는 파싱되지 않으므로 코어 정규식 경로가 필요하다. 별칭은 iaciac 원문이 A 형태라 LLM이 그 형태로 쓸 수 있어서 두되, iaciac 목록에 `2010-348호`처럼 낮은 번호가 있어 eiac 실번호와 겹칠 수 있다(검증 M13) — 실키 우선 + 기관 판정으로 기관을 바꾼 인용을 막는다 |
| D13 | **배선 PR(PR-A)을 데이터 PR(PR-B)보다 먼저 머지·배포한다.** PR-A: 스크립트·배선·테스트·fixture(데이터 없음). PR-B: 커밋 원장·BM25 gz·CLAUDE.md 수치. 업로드는 PR-A 배포 **뒤**에 한다. PR-A는 재결 검증 패턴을 켜므로 **코퍼스·실답변 전량 스캔으로 재결 아닌 일치 0건**을 머지 조건으로 둔다(RU19·§7-2) | `laborlaw-v2`는 프로덕션이 읽는 NS라 업로드 즉시 Dense 검색에 재결례가 섞인다. 배선 없는 프로덕션은 라벨을 `ruling` 원문으로 보이고 재결 번호를 검증하지 않으며 공공 쿼터 집합 밖이라 `_diversity_class_of`가 보호하지 않는다. "재발 방지 가드를 정리보다 먼저 배포"와 같은 순서 원칙. rev1의 "PR-A는 프로덕션 동작 불변"은 틀린 서술이었다(검증 H1) — 패턴이 켜지므로 무해함을 **측정으로** 보인다 |
| D14 | 커밋 원장은 `data/vector_ledgers/rulings_202611.json`, **`source_pack_ledger.py` 형식**(`batch`·`id_prefix`·`id_pattern`·`index`·`namespace`·`uploaded_on`·`state`·`vector_count`·`document_count`·`composition`·`documents{key:{title,source_type,official_url,source_sha256,ids}}`). 업로더의 `--write-batch-ledger`가 로컬 원장 + md 메타에서 생성한다. 빈 그룹·md 없는 그룹은 **넣지 않는다**(있으면 중단). `--verify`를 함께 주면 `source_pack_ledger.verify`를 돌려 통과 시 `state="verified"`, 아니면 `"uploaded"` | `test_offline_units.test_committed_vector_ledgers`가 `data/vector_ledgers/*.json` 전부를 그 형식으로 검사한다. 같은 도구로 재결 1건 단위 롤백이 된다. 로컬 원장은 gitignore라 디스크를 잃으면 삭제 수단도 사라진다. `VectorLedger.finalize`는 비운 그룹 키를 `[]`로 남기므로(`vector_ledger.py:155`) 생성기가 그것을 걸러야 한다(검증 M9·L22) |
| D15 | 측정 K는 지식iN **고용보험 범주 14문항**(kin-03·04·06~13·16·17·18·20) + `data/eval_consultation_queries.json`의 **산재·괴롭힘·차별 범주 8문항**(risk-01~08). 비용 (18 + 6 + 52) × 4 + 22 × 2 = **348답변**(R 실측 52 — 실업급여 45·산재 7) | fixture `category == "지식iN·고용보험"`이 14건이다. iaciac 7,500청크가 산재 답변에 들어가는데 산재 비회귀 문항이 없었다(검증 M7) |
| D16 | 청구취지는 제외, eiac `각주목록`은 **`각주번호`·`각주내용` 자식을 짝지어** `[각주 n] 내용` 줄로 만들고 `각주` 섹션으로 포함한다 | 청구취지는 실측 둘 다 주문의 반복이고 eiac는 숨김 span 잡음이 든다. 각주는 `이유`가 `[각주 n]`으로 참조하는 사실(소정급여일수·수급기간)이다. `itertext`로 이으면 `1\n내용\n2\n…`가 된다(검증 L17 — 자식이 `각주번호`·`각주내용` 쌍이다) |
| D17 | `official_url`은 **판례와 같은 DRF 규약** `https://www.law.go.kr/DRF/lawService.do?OC=&target={agency}&ID={serial}&type=HTML`(OC 빈값) | 공개 페이지 후보를 확인했으나 본문이 열리는 URL이 없었다(§1.4). `fetch_court_precedents.normalize_record`의 `source_url`과 같은 형식 |
| D18 | **재결례 인용 규칙 `RULING_CITATION_RULES`**(소프트 가드)를 `prompts.py`에 두고 `pipeline`이 **두 답변 분기 공통**으로, 컨텍스트에 `ruling`이 실렸을 때만 접미한다(`uses_ruling(precedent_meta)`). 예시 번호는 **자리표시**(`YYYY재결 제N호`)로 쓴다 | 해설서·상담 가드와 같은 이유 — 답변 경로가 두 갈래다. 내용은 ① 머리글의 기관명+사건번호 그대로(기관명 필수 — D12 B의 문맥 조건과 짝) ② 개별 사안 판단이라 일반 규칙화 금지 ③ 오래된 의결은 현행 조문 우선. 실번호 예시는 그 번호가 답변에 복제될 위험이 있다(예시 시급 10,000원 사고와 같은 클래스, 검증 L20) |
| D19 | 평가 fixture의 `allowed_sources`에 `ruling`을 더한다 — `precedent`를 허용하는 모든 항목(kin 20·consultation 60·audit50 14·calc_card 19·wage_update 38). 일괄 편집 스크립트는 저장소 밖, 결과만 커밋 | `eval_consultation.score_result`는 sources의 `source_type`이 `allowed_sources`의 부분집합일 때만 `automatic_pass`다. 재결례가 실린 답변이 그 이유만으로 실패하면 K 비회귀가 가짜 회귀를 낸다 |
| D20 | **프로덕션 관측 키** `metadata.rag_sources = {source_type: count}`를 `precedent_meta`에서 세어 저장한다(`conv_metadata`, `rule_facts`·`stale_filtered`와 같은 관측 키. `PUBLIC_EXCLUDE_KEYS` 무관) | `sources` 이벤트는 저장되지 않는다(`conv_metadata` 키 목록에 없음 — 검증 M8). 이 키 없이는 "프로덕션에서 재결례가 실렸는가"와 §11의 분류별 분포를 볼 수 없다 |
| D21 | **측정 계측은 하네스 spy다.** `run_eval.py`가 `format_pinecone_hits`를 감싸(**`stale_out` 등 키워드 인자를 그대로 전달**) 반환 `meta_list`의 `source_type`·`case_no`·`title`을, `validate_response_citations`를 감싸 **교정 전** `valid`·`hallucinated`와 교정 전 답변을 기록한다. M1·M2는 그 기록으로 계산한다(§8.2) | `_build_sources_payload`는 법률 근거를 `other[:5]`로 자르고(`pipeline.py:320~322`), 쿼터·승격 항목은 목록 맨 뒤라(`rag.py` 551·601) 재결례가 컨텍스트에는 있는데 `sources`에서 빠진다. `observed["answer"]`는 replace 뒤 본문이라 교정이 지운 환각을 보지 못한다(검증 H3). `eval_corpus_mix.py:68`의 spy는 `stale_out`을 받지 못해 `--production`이 깨져 있다는 지적이 있다 — Do에서 확인하고 같은 실수를 반복하지 않는다 |

---

## 1. 실측 근거 (2026-11-08, 등록 회선)

### 1.1 API 응답 구조

목록 `lawSearch.do?target={eiac|iaciac}&type=XML&display=…&page=…`:

| 항목 | eiac | iaciac |
|---|---|---|
| 루트 | `Eiac` | `Iaciac` |
| 메타 자식 | `target`·`키워드`·`section`·`totalCnt`(118)·`page`·`기관명` | 같음(`totalCnt` 934) |
| 항목 태그 | `eiac` | `iaciac` |
| 항목 필드 | `결정문일련번호`·`사건명`·`사건번호`·`의결일자`·`결정문상세링크` | `결정문일련번호`·**`사건`**·`사건번호`·`의결일자`·`결정문상세링크` |
| `결정문상세링크` | `/DRF/lawService.do?OC=…&target=eiac&ID=…` — **OC 포함**, 저장 금지 | 같음 |

상세 `lawService.do?target={…}&ID={결정문일련번호}&type=XML`(실측 11327·12699):

| eiac `EiacService` | 길이 | iaciac `IaciacService` | 길이 |
|---|---|---|---|
| `결정문일련번호` | 5 | `결정문일련번호` | 5 |
| `사건의분류` "수급자격에 관한 사례" | 11 | `사건대분류`·`사건중분류`·`사건소분류` "업무상 재해 여부 관련"·"업무상 사고"·"작업시간 중 사고" | 12·6·9 |
| `의결서종류` "재결서" | 3 | `쟁점` | 241 |
| `개요` | 63 | `사건번호` "2010-2071호" | 10 |
| `사건번호` "2019재결 제117호" | 12 | `의결일자` "2010.8.27" | 9 |
| `사건명` | 23 | `사건` "2010재결 제2071호 요양불승인처분취소" | 23 |
| `청구인` "전 ○ ○" | 5 | `청구인` "성○○(남자, 60세, 생산직, (주)△△, 입사일 : 1979. 7. 13.)" | 45 |
| `피청구인` "○○지방고용노동청장" | 10 | `원처분기관` "근로복지공단 ○○지사장" | 14 |
| `주문` | 84 | `주문` | 17 |
| `청구취지`(숨김 span 포함) | 225 | `청구취지` | 57 |
| `이유` | 3,958 | `이유` | 7,777 |
| `의결일자` "2019.10.23" | 10 | `문서제공구분` "데이터 개방" | 6 |
| `기관명` "고용보험심사위원회" | 9 | — | |
| `각주목록`(`각주번호`·`각주내용` 쌍) | 443 | — | |

- 상세 본문은 CDATA다. `findtext`가 아니라 `itertext` 전량 수집(court 수집기와 같은 이유 — 자식 엘리먼트 뒤 tail이 잘린다). 단 `각주목록`은 자식을 쌍으로 읽는다(D16).
- 상세에 `기관명`이 없는 iaciac은 상수로 쓴다(목록 메타 `기관명` 참조).

### 1.2 본문 특성 (fixture 줄 번호는 `이유` 본문 기준)

- **`이유` 소제목** — eiac 11327: `1. 사건개요(1) / 2. 청구인 주장(4) / 3. 피청구인 주장(6) / 4. 관계법령(9) / 5. 인정사실(13) / 6. 이 사건 처분의 위법ㆍ부당 여부(23) → 가. 관계법령의 내용(24)·나. 판단(30) / 7. 결론(34)`. iaciac 12699: `1. 사건개요(1) / 2. 청구인 주장(6) / 3. 원처분기관 의견(23) / 4. 원처분기관 처분내용(28) / 5. 관계법령, 사실관계 및 판단(34) → 가. 관계법령(37)·나. 사실관계(77)·다. 의학적 소견(88)·라. 판 단(132) / 6. 결 론(135)`. 관계법령 소절 안에 조문 목 `가.~라.`(44~47 — 47행 "사업주가 제공한 교통수단 … 출퇴근 중 발생한 사고"가 2018년 이전 기준)·`가.~다.`(50~52)·호 `1.~4.`(58~61)·`1.~3.`(67~69)·`1.~2.`(71~72)가 반복된다. **번호도 글자도 1·가로 되돌아가고, 제목이 문장형으로 길다**(D9의 세 조건 근거).
- **HTML 잔재** — eiac `이유`에 `<각주>n</각주>`(3·5행 — 3행은 `…하였다.<각주>1</각주>다. 이에`로 소항목이 같은 줄에 붙음), `<img src="…flDownload.do?flSeq=…" alt="1번째 이미지"></img>`(18·21행), 캡션 `<근로계약서 발췌>`. `청구취지`에 `<span style="display:none;">○ 사건번호 및 사건명 …</span>`. iaciac 두 건은 태그 0. 특수문자는 `’“”`뿐.
- **번호 표기 겹침** — iaciac `사건`이 `2010재결 제2071호 …`로 시작한다. iaciac 목록에는 `2010-348호`처럼 낮은 번호도 있어 eiac 실번호(연 100건 안팎)와 겹칠 수 있다.
- **의결일자** — eiac `2019.10.23`, iaciac `2010.8.27`(0 채움 없음). Plan §1.4의 "오류 연도 2건"은 날짜 파싱 실패로 분류한다(§3.3).
- **청구인** — eiac는 성명 마스킹만, iaciac는 성(姓) 1자 + 성별·나이·직종·마스킹된 회사·입사일. 임베딩 제외 대상(D3·R6).
- **길이** — Plan 표본 50건의 중앙값 6,677·4,522자에 두 실측(3,958·7,777)이 들어맞는다. iaciac 12699의 관계법령 소절은 37~76행 약 2,500자다. 제외 효과는 Do의 `--dry-run`에서 집계한다.

### 1.3 코드 배선 지점 현황 (main 1f19366)

| 지점 | 현재 값 |
|---|---|
| `app/core/rag.py:107` | `POOL_PUBLIC_SOURCES = frozenset({"precedent", "interpretation", "regulation"})` — `_is_public_source`(152)·`_fetch_public_hits`의 `$in`(172)·`LEGAL_PROMOTE_SOURCES = POOL_PUBLIC_SOURCES`(455)·`_diversity_class_of`가 모두 이 객체를 본다 |
| `app/core/rag.py:958~965` | `format_pinecone_hits` 라벨 맵 6종. 미등록은 `source_type` 원문 노출 |
| `public/index.html:1461` | `renderSources` `labels` 9종. `sw.js`는 `navigate` 요청을 네트워크 우선으로 처리하므로 index.html 변경에 `VERSION` 상향이 필수는 아니다(검증 L21) — 배포 관례에 따라 올리되 테스트로 고정하지 않는다 |
| `app/core/conflict_resolver.py:74` | `"3. 행정해석·판정사례 — 참고 자료"`. 입력은 `precedent_text`(RAG 컨텍스트 전체)라 재결례가 자동 포함된다 |
| `app/core/citation_validator.py:61~77` | `_PREC_PATTERN`(연도 + 한글 1~2자 + 숫자, `년월일` 제외)·`_ADMIN_PATTERN`(`…과-N`). `extract_precedents_from_hits`는 title·chunk_text·meta case_no 세 경로. `_CORRECTION_TEXT["hallucinated"][1] == "확인되지 않은 판례 번호"`는 `test_kin_accuracy` K12가 고정한다 |
| `app/core/pipeline.py:325` | `_citation_source_hits`가 `precedent_meta`의 `case_no`·`source_type`을 hit으로 넘긴다 — 재결례 meta도 같은 경로(변경 불요) |
| `app/core/pipeline.py:4235` | 컨텍스트 머리글 `"관련 판례 (법제처 국가법령정보센터 검색):"` 아래에 RAG 컨텍스트가 실린다 |
| `app/core/pipeline.py:4532~4536` | `extract_precedents_from_hits`·`extract_admin_refs_from_hits` → `validate_response_citations(full_text, precs, admins)` |
| `app/core/pipeline.py:4438~4467` | `uses_textbook`·`uses_counsel` → 두 분기 공통 접미 |
| `app/core/pipeline.py:4633~4694` | `conv_metadata` 키: guard_flag·truncated·textbook·counsel·case_match·synthetic·rule_facts·official_evidence·stale_filtered·citation_relevance·law_api·assessor·llm — **sources 없음**(D20) |
| `app/core/stale_rules.py` | `_EXCLUDE_SOURCES = {"qa","counsel"}`. 규칙은 일용 '10일 미만'·주휴 '다음 주'·근로기준법 제35조 셋뿐 — **산재 기준 규칙이 없다**(§5.7) |
| `app/core/bm25_search.py:46` | `CORPUS_FIELDS = (id,text,title,section,source_type,book_id)` — `case_no` 없음(D11) |
| `build_bm25_corpus.py:65` | `fetch_by_metadata(filter={"chunk_index": {"$gte": 0}})` — 정수 `chunk_index` 필수(D10) |
| `vector_ledger.py:155·184~188` | `finalize`는 비운 그룹을 `[]`로 남긴다. `prune` 대량 삭제 가드의 분모는 **이번에 넘긴 그룹의 청크 합**이다(§4.6) |
| `pipeline._build_sources_payload:320~322` | `official + other[:max_items]`(5) — 측정 계측에 쓸 수 없다(D21) |
| `eval_colloquial.py:55` | `LEGAL_CORPUS_SOURCES` 리터럴 — `ruling` 추가 |
| `test_precedent_ingest.py:1685` | T24-a4 `LEGAL_PROMOTE_SOURCES == {"precedent","interpretation","regulation"}` — 갱신 대상 |
| CI | `test_bm25_memory` 상한 550MB, main 실측 459MB(2026-11-08). `eval_tokenizer.py --check --full`(M6 비율 상한 5.40%)도 재빌드 gz를 본다 |

### 1.4 공개 URL

키 없이 확인한 후보 — `LSW/eiacInfoP.do?eiacSeq=11327`·`LSW/iaciacInfoP.do?iaciacSeq=12699`(200이지만 5KB 셸, 본문 없음), `/eiac/11327`(404), `/재결례/(2019재결제117호)`(404), DRF HTML OC 빈값(200, 1.4KB 오류 페이지). 본문이 열리는 공개 URL은 없었다 → D17.

### 1.5 인용 패턴 사전 스캔 (2026-11-08)

| 패턴 | BM25 코퍼스 95,762문서 | 실답변(저장소 밖 하네스 wuf) |
|---|---|---|
| rev1 B(`제` 배제·`호` 필수, 문맥 없음) | **438건** — regulation 427·textbook 8·precedent 2·interpretation 1, 전부 고시·공고 번호(`고용노동부고시 2015-77호`·`공고 2021-244호`·`고시(2025-83호).pdf` …) | `고시(2025-124호)`·`고용노동부 고시 2018-23호` 각 1건 |
| A(`YYYY재결 제N호`) | 0건 | 0건 |
| `_PREC_PATTERN`에 `…재심사위원회 2015-1987호 2015. 8. 27.` | `1987호 2015` 매치(환각 판례 판정) | — |

→ D12(기관 문맥 필수·마스킹). rev2 B를 같은 코퍼스에 돌려 0건임을 RU19가 CI에서 고정한다.

---

## 2. 변경 파일

| 파일 | PR | 변경 |
|---|---|---|
| `fetch_rulings.py` | A | 신규. 목록 전량 → 상세 → `output_재결례/{agency}/…md`(§3) |
| `pinecone_upload_rulings.py` | A | 신규. 청킹·임베딩·`laborlaw-v2` 적재·원장·prune·그룹 삭제·배치 원장 생성(§4). 유틸은 court 업로더 import |
| `vector_ledger.py` | A | `VectorLedger.drop_groups(group_ids, index, namespace, *, allow_large, dry_run)` 신설(§4.6) |
| `app/core/rag.py` | A | `POOL_PUBLIC_SOURCES`에 `"ruling"`, 라벨 맵 `"ruling": "재결례"` |
| `public/index.html` | A | `labels`에 `ruling: '재결례'` |
| `public/sw.js` | A | `VERSION` 상향(배포 관례) |
| `app/core/conflict_resolver.py` | A | 3항 문구·docstring 원칙 줄 |
| `app/core/citation_validator.py` | A | `_RULING_EI_PATTERN`·`_RULING_IA_PATTERN`(문맥)·`_RULING_CORE_*`(마스킹·메타)·`_mask_ruling_spans`·`extract_rulings_from_hits`·`validate_response_citations(..., available_rulings=None)`·`build_available_citations_text` 재결례 블록·목록 머리글·`_CORRECTION_TEXT["hallucinated"][0]` 머리말만 |
| `app/core/pipeline.py` | A | `uses_ruling()`·`RULING_CITATION_RULES` 접미(두 분기)·`available_rulings` 전달·컨텍스트 머리글 "관련 판례·재결례"·`conv_metadata["rag_sources"]`(D20) |
| `app/templates/prompts.py` | A | `RULING_CITATION_RULES`(자리표시 예시) |
| `eval_colloquial.py` | A | `LEGAL_CORPUS_SOURCES`에 `"ruling"` |
| `data/eval_*_queries.json` 5종 | A | `allowed_sources`에 `ruling`(D19) |
| `data/ruling_fixtures/eiac_list_p1.xml`·`iaciac_list_p1.xml`·`eiac_detail_11327.xml`·`iaciac_detail_12699.xml` | A | 신규. 2026-11-08 실제 응답(OC 제거, 청구인은 합성 문자열로 치환) |
| `test_rulings_ingest.py` | A | 신규. RU1~RU19(§6) |
| `test_precedent_ingest.py` | A | T24-a4 집합에 `ruling` |
| `.github/workflows/tests.yml` | A | `python3 test_rulings_ingest.py` 단계(판례 수집·업로드 테스트 다음) |
| `CLAUDE.md` | A | 명령 2줄·새 출처 유형 배선 메모(공공 쿼터 집합·인용 패턴 문맥 조건·우선순위·`rag_sources`) |
| `data/vector_ledgers/rulings_202611.json` | B | 신규. 배치 원장(D14) |
| `data/bm25_corpus.jsonl.gz` | B | 재빌드 |
| `CLAUDE.md` | B | `laborlaw-v2` 벡터 구성(`ruling_` N)·BM25 문서 수·CI RSS 실측 |
| `output_재결례/`(gitignore) | — | `{eiac,iaciac}/*.md`·`_progress.json`·`_pii_report.json`·`_pii_redactions.json`·`_uploaded_ids.json`·`_excluded/` |

---

## 3. 수집 — `fetch_rulings.py`

### 3.1 CLI

```
python3 fetch_rulings.py                       # eiac + iaciac 전량(재개)
python3 fetch_rulings.py --agency iaciac --limit 50
python3 fetch_rulings.py --list-only           # 목록만 받아 건수·연도 분포 출력(저장 없음)
python3 fetch_rulings.py --serial 11327 --agency eiac   # 특정 건 재수집(가림 목록은 업로더가 적용 — §3.5)
python3 fetch_rulings.py --force               # 진행 기록 무시
```

### 3.2 흐름

1. `.env` 로드(`override=True`) → `LAW_API_KEY` 없으면 종료.
2. 기관별 목록: `display=100`, `page=1..ceil(totalCnt/100)`. 항목 `결정문일련번호`로 집합을 만든다(페이지 간 중복 제거). `totalCnt`와 수집 건수가 다르면 경고(종료는 아님 — 다음 실행이 채운다).
3. 상세: 진행 기록에 없는 일련번호만 `lawService.do`로 받는다. `REQUEST_DELAY = 0.3`, `MAX_RETRIES = 3`(지수 백오프), `TIMEOUT = 20`.
4. 정규화(§3.3) → 정제(§3.4) → PII 스캔(§3.5) → md 저장(§3.6) → 진행 기록 갱신(건마다, `atomic_write_json`).
5. 종료 요약: 기관별 저장·스킵·실패(사유별), PII 보고 건수, 연도 분포, 날짜 파싱 실패 건수.

**오류 규약** — `_raise_if_error_root`(`app.core.legal_api`)를 모든 응답에 건다. `LawApiAuthError`는 진행 기록을 저장한 뒤 **exit 2**로 멈추고 `failed`에 **기록하지 않는다**(RU18). HTTP·파싱 실패와 **필수 필드 부재**(`사건번호`·`의결일자`·`이유` 중 하나라도 빈 상세)는 `failed[serial] = {reason, at}`로 기록하고 다음 실행에 재시도한다(court의 `not_found`처럼 영구 저장하지 않는다). `reason`은 예외 **클래스명 + HTTP 상태** 또는 `"필수 필드 없음: 이유"`처럼 필드명만(메시지는 쿼리 URL에 OC를 담을 수 있다).

### 3.3 정규화 (필드 매핑)

| 공통 키 | eiac | iaciac |
|---|---|---|
| `agency` | `"eiac"` | `"iaciac"` |
| `agency_name` | `기관명`(없으면 "고용보험심사위원회") | "산업재해보상보험재심사위원회"(상수) |
| `serial` | `결정문일련번호` | 같음 |
| `case_no` | `사건번호` | `사건번호` |
| `case_name` | `사건명` | `사건`에서 `^\d{4}\s*재결\s*제\s*\d+\s*호\s*` 제거 |
| `title` | `{agency_name} {case_no} — {case_name}` | 같음 |
| `decided_at` | `의결일자` → `YYYY.MM.DD`; 파싱 실패면 **원문 그대로** + `decided_year = None` | 같음(0 채움) |
| `category` | `사건의분류` | `사건대분류 > 사건중분류 > 사건소분류`(빈 값 생략) |
| `doc_kind` | `의결서종류` | `문서제공구분` |
| `summary` | `개요` | `쟁점` |
| `respondent` | `피청구인` | `원처분기관` |
| `claimant` | `청구인` | `청구인` |
| `disposition` | `주문` | `주문` |
| `claim` | `청구취지` | `청구취지` |
| `reasoning` | `이유` | `이유` |
| `footnotes` | `각주목록` → `[각주 n] 내용` 줄 목록(D16) | "" |
| `official_url` | D17 | D17 |

`case_no`·`case_name`은 NFC 정규화. 날짜 파싱 실패 건은 요약에 세고(Plan §1.4의 "오류 연도 2"), `--exclude-before`(§4.6)는 `decided_year is None`을 **제외하지 않는다**(날짜를 모르는 결정을 낡았다고 단정하지 않는다).

### 3.4 정제 (`clean_ruling_text`)

순서: `<br/>` → 개행 → `<span style="display:none;">…</span>` 삭제(내용 포함) → `<img … alt="X"></img>`(`alt` 없으면 빈 캡션) → `[이미지 생략: X]` → `<각주>(\d+)</각주>` → `[각주 \1]`, 바로 뒤에 `\s*(\d+|[가-하])\.\s`가 오면 개행 삽입 → 블록 태그 → 개행, 인라인 태그 → 빈 문자열(D9 목록, 열고 닫는 태그·속성 포함) → `html.unescape` → 공백 정리(`court.clean_api_text`와 같은 규칙). **그 밖의 꺾쇠는 보존**한다(`<근로계약서 발췌>`). 정제 뒤 `</?[A-Za-z][^>]*>`가 남으면 그 문서를 `failed["잔존 태그"]`로 기록한다(dry-run 집계 대상, §4.4).

### 3.5 PII 스캔·가림

저장 전 전 필드(청구인 포함)에 ① 주민등록번호 `(?<!\d)\d{6}-[1-4]\d{6}(?!\d)` ② 휴대전화 `(?<!\d)01[016789]-?\d{3,4}-?\d{4}(?!\d)` ③ 이메일 `[\w.+-]+@[\w-]+\.[\w.]+`를 돈다(`\b`는 한글 뒤 숫자에서 경계가 아니다 — 검증 M14). 발견은 `output_재결례/_pii_report.json`에 `{agency, serial, field, pattern, snippet(앞뒤 20자), reviewed: false}`로 남기고 **저장은 그대로** 한다(원문 보존). 사람이 확인해 실제 개인정보면 `output_재결례/_pii_redactions.json`에 `{agency, serial, field, literal}`을 적고 `reviewed: true`로 바꾼다. **가림은 md를 고치는 것이 아니라 업로더가 청킹 시점에 적용한다**(§4.2) — md를 직접 고치면 `--serial`·`--force` 재수집이 원본으로 덮어쓴다. 청구인 필드는 어차피 임베딩에서 제외된다.

### 3.6 저장 형식 — `output_재결례/{agency}/{serial}_{case_no_ascii}.md`

court 업로더의 `parse_meta`·`parse_sections`가 그대로 읽는 형식:

```
# {case_name}

| 항목 | 내용 |
| --- | --- |
| 기관 | {agency_name} |
| agency | {agency} |
| 일련번호 | {serial} |
| 사건번호 | {case_no} |
| 의결일자 | {decided_at} |
| 분류 | {category} |
| 문서종류 | {doc_kind} |
| 피청구인 | {respondent} |
| 청구인 | {claimant} |
| 원문 | [{official_url}]({official_url}) |

---

## 개요        ← iaciac는 "## 쟁점"
## 주문
## 청구취지
## 이유
## 각주        ← eiac만, 있을 때 — 줄마다 "[각주 n] 내용"
```

`case_no_ascii`: `2019재결 제117호` → `2019jg117`, `2010-2071호` → `2010-2071`(파일명용. ID에는 쓰지 않는다 — ID는 일련번호).

### 3.7 진행 기록 — `output_재결례/_progress.json`

```json
{"eiac": {"fetched": {"11327": "11327_2019jg117.md"}, "failed": {}},
 "iaciac": {"fetched": {}, "failed": {"12345": {"reason": "HTTPError 500", "at": "2026-11-09T09:12:00+09:00"}}}}
```

---

## 4. 적재 — `pinecone_upload_rulings.py`

### 4.1 ID·그룹·원장

- `NAMESPACE = "laborlaw-v2"`, `SOURCE_TYPE = "ruling"`.
- `make_vector_id(agency, serial, idx) = f"ruling_{agency}_{serial}_chunk_{idx}"`(D10).
- `_LEDGER = VectorLedger("output_재결례/_uploaded_ids.json", group_re=^(eiac|iaciac)_\d+$, id_re_for=lambda g: ^ruling_{g}_chunk_\d+$)`.
- 그룹 키 `{agency}_{serial}` — iaciac 사건번호 중복 2건(R8)이 서로 다른 그룹이 된다. `record` → upsert → 전부 성공 뒤 `prune`(court와 같은 순서·가드).
- 소스 탐색은 `output_재결례/{eiac,iaciac}/*.md` **비재귀**(`_excluded/`는 보지 않는다).
- 유틸(`CHUNK_MAX`·`CHUNK_OVERLAP`·`UPSERT_BATCH`·`clean_text`·`split_by_size`·`embed_texts`·`parse_meta`·`parse_sections`)은 `pinecone_upload_court_precedents`에서 import한다(복사는 드리프트).

### 4.2 청킹 (D3·D9·D11·D16)

```
header = f"[{기관} {사건번호} · 의결 {의결일자} · {분류}]"       # ≤ 160자, 분류는 ≤ 80자로 절단
가림     _pii_redactions.json 의 literal 을 모든 섹션 본문에서 "***" 로 치환(청킹 전)
chunk 0  section="개요·주문" : header + "\n개요: " + 개요(또는 "쟁점: " + 쟁점) + "\n주문: " + 주문
         700자를 넘으면 split_by_size 로 나누고 각 조각에 header 를 붙인다
이유      소제목 분할(D9) → 관계법령 절·소절 제외 → 각 절 split_by_size(700, 80) → header + "\n" + 조각
         section = f"이유 — {상위 소제목}"[:80] (소절 단위로 잘렸으면 f"이유 — {상위} / {소절}"[:80])
각주      eiac → section="각주", 같은 방식
```

- `embed_text == text`(머리글 포함).
- 소제목 인식은 D9의 세 조건. 상위 소제목이 하나도 없으면 `이유` 전체를 `이유 — 본문`으로 자른다(폴백). 첫 상위 소제목 앞의 서두는 `이유 — 서두`.
- 제외 규칙은 D9. 제외한 글자 수·절 제목을 문서별로 기록해 dry-run 요약에 낸다.
- 청구인·청구취지는 어떤 청크에도 넣지 않는다(RU6).

### 4.3 메타데이터

```
source_type="ruling", title[:200], case_name[:120], section[:80], case_no, agency, serial(str),
date(YYYY.MM.DD 또는 원문), decided_year(int|None → None 이면 키 생략), category[:120],
disposition(주문[:120]), url(official_url), chunk_index(int), text[:1000], chunk_text[:1000]
```

`text`·`chunk_text` 둘 다 넣는다. `official` 표식은 넣지 않는다(Plan P0-2). `chunk_index`는 정수(D10).

### 4.4 CLI

```
python3 pinecone_upload_rulings.py --dry-run                  # §4.4 집계 — 중단 조건 포함
python3 pinecone_upload_rulings.py --agency eiac --limit 20   # 부분(그룹 = 일련번호라 안전)
python3 pinecone_upload_rulings.py                            # 전량 적재 + 고아 정리
python3 pinecone_upload_rulings.py --allow-large-prune        # ID 규격을 바꿨을 때만
python3 pinecone_upload_rulings.py --exclude-before 2016 --agency iaciac   # md 를 _excluded/ 로 이동만(§4.6)
python3 pinecone_upload_rulings.py --prune-missing [--allow-large-prune] [--dry-run]   # 소스 없는 그룹 삭제(§4.6)
python3 pinecone_upload_rulings.py --write-batch-ledger data/vector_ledgers/rulings_202611.json [--verify]
```

**dry-run 집계**: 문서 수·청크 수·평균 청크/문서, 관계법령 제외 글자 수와 비율, 문서별 상위 소제목 열, `결론`·`판단` 소제목이 없는 문서 수, 잔존 태그 문서 수, 날짜 파싱 실패 수, PII 보고 중 `reviewed: false` 수. **중단 조건**: `reviewed: false` > 0, 잔존 태그 > 0, `결론|판단` 없는 문서가 전체의 5%를 넘음(폴백 경로가 다수면 소제목 규칙이 틀렸다는 뜻). 실제 실행도 같은 조건으로 멈춘다.

### 4.5 커밋 원장 (D14)

`--write-batch-ledger`: 로컬 원장에서 **비어 있지 않고 소스 md가 있는** 그룹만 골라 `documents[f"{agency}_{serial}"] = {title, source_type: "ruling", official_url, source_sha256(md 파일), ids}`를 만든다(빈 그룹·md 없는 그룹이 있으면 중단 — 축소 뒤 `--prune-missing`을 빠뜨린 상태다). `vector_count`·`document_count`·`composition{"ruling": N}`·`id_prefix="ruling_"`·`id_pattern=^ruling_(eiac|iaciac)_\d+_chunk_\d+$`·`index=resolve_index_name()`·`namespace`·`uploaded_on`. `--verify`를 주면 `source_pack_ledger.verify`를 돌려 통과 시 `state="verified"`, 아니면 `"uploaded"`로 쓴다.

### 4.6 D2 축소 경로

CI `test_bm25_memory`가 550MB를 넘으면:

1. `--exclude-before 2016 --agency iaciac`: `decided_year < 2016`인 md를 `output_재결례/_excluded/iaciac/`로 **이동만** 한다(`decided_year is None`은 제외하지 않음). 이동 목록을 출력한다.
2. `--prune-missing --dry-run`: 원장에 있는데 소스 md가 없는 그룹과 그 벡터 수를 출력한다. 가드 분모는 **원장 전체 벡터 수**다(기존 `prune`은 이번에 넘긴 그룹의 합이 분모라 빠진 그룹만 넘기면 분모 0 → 항상 발동 — `vector_ledger.py:184~188`, 검증 M9). 2016년 이전은 약 55%라 `--allow-large-prune`이 필요하고, 이 플래그는 **`--prune-missing` 단독 실행에서만** 받는다(CLAUDE.md `--book` 교훈 — 전역으로 두면 다른 가드까지 조용히 풀린다).
3. `--prune-missing --allow-large-prune`: `VectorLedger.drop_groups`가 `index.delete(ids=…)` 뒤 **그룹 키를 제거**한다(`finalize`는 키를 `[]`로 남겨 `--write-batch-ledger`가 빈 문서를 만든다).
4. `--write-batch-ledger … --verify` 재생성 → BM25 재빌드 → PR-B 갱신 → CI 재판정. 상한 상향은 하지 않는다.

---

## 5. 배선

### 5.1 `rag.py`

```python
POOL_PUBLIC_SOURCES = frozenset({"precedent", "interpretation", "regulation", "ruling"})
...
"ruling": "재결례",      # format_pinecone_hits 라벨 맵
```

`_fetch_public_hits`의 `$in`·`_is_public_source`·`LEGAL_PROMOTE_SOURCES`·`_diversity_class_of`가 자동으로 따라온다(단일 객체). 재결례 전용 상한은 두지 않는다 — §8.2의 R4 관측(재결례를 뺀 공공 건수·판례 승격 발동 수)으로 판단한다. **롤백 수단**은 코드 스위치가 아니라 데이터다: `source_pack_ledger.py rollback data/vector_ledgers/rulings_202611.json --apply` → BM25 재빌드 → gz 커밋(§9 R4).

### 5.2 라벨 G5 양쪽

`public/index.html` `labels`에 `ruling: '재결례'`. `sw.js` `VERSION`은 배포 관례로 올리되 테스트는 두 라벨의 일치만 고정한다(RU11).

### 5.3 `conflict_resolver.annotate_source_priority`

- docstring 원칙: `현행 법령 > 대법원 판례 > 하급심 판례 > 행정해석 > 재결례·판정사례 > 상담사례`
- 메모 3항: `"3. 행정해석·판정사례·재결례 — 참고 자료(재결례는 개별 사안의 판단이라 일반화하지 않는다)"`

### 5.4 `citation_validator.py`

```python
# 문맥 패턴 — 답변·title·chunk_text 검증·추출용
_RULING_EI_PATTERN = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*재결\s*제?\s*(\d{1,5})\s*호")
_RULING_IA_PATTERN = re.compile(
    r"(?:산업재해보상보험\s*재심사\s*위원회|산재\s*재심사\s*위원회|재심사\s*위원회)"
    r"[^.\n]{0,25}?((?:19|20)\d{2})\s*-\s*(\d{1,5})\s*호?")
# 코어 패턴 — ruling hit 의 case_no 메타 파싱과 _PREC_PATTERN 마스킹 전용(검증에는 쓰지 않는다)
_RULING_CORE_EI = _RULING_EI_PATTERN
_RULING_CORE_IA = re.compile(r"(?<![\d\-])((?:19|20)\d{2})\s*-\s*(\d{1,5})\s*호")
_AGENCY_WORDS = {"eiac": ("고용보험심사위원회", "고용보험 심사위원회"),
                 "iaciac": ("산업재해보상보험재심사위원회", "산재재심사위원회", "재심사위원회")}

def _mask_ruling_spans(text) -> str      # 코어 A·B 일치 구간을 같은 길이의 공백으로
def extract_rulings_from_hits(hits) -> dict[str, dict]
    # key → {"agency": {"eiac"|"iaciac"|…}, "title", "hit_index", "source", "alias_of"?}
    # 1) ruling hit 의 case_no 메타: 코어로 파싱, agency 메타(없으면 title 의 기관명)로 기관 확정
    # 2) title·chunk_text: 문맥 패턴. B 는 "재심사위원회" 문맥이라 iaciac
    # 3) 2 차 패스에서 B 키마다 A 형태 별칭을 실키가 없을 때만 추가(alias_of)
def validate_response_citations(response_text, available_precedents, available_admin_refs=None,
                                available_rulings=None) -> dict
    # 1) 재결: 문맥 패턴으로 키 추출 → 화이트리스트 유무 → 번호 앞 30자의 기관명이 등록 기관과 다르면 hallucinated
    # 2) 판례: _mask_ruling_spans(response_text) 뒤 기존 _PREC_PATTERN
    # available_rulings 가 None 이면 재결 검증은 건너뛰되 마스킹은 항상 한다(기존 3 인자 호출 호환)
```

- `extract_precedents_from_hits`도 title·chunk_text·case_no에 `_mask_ruling_spans`를 먼저 적용한다(화이트리스트에 `1987호2015` 같은 가짜 판례 키가 들어가지 않게).
- `build_available_citations_text`: 머리글 `"[인용 가능한 판례·행정해석·재결례 목록]"`, `"\n재결례:"` 블록 — `"  - {기관명} {key} (출처: {title})"`. 별칭 항목은 **싣지 않는다**.
- `_CORRECTION_TEXT["hallucinated"]`: **머리말(0번)만** "판례·재결 번호가 잘못 인용되었습니다"로. 라벨(1번) "확인되지 않은 판례 번호"는 그대로(K12). 1번 규칙 문구도 그대로.
- 연도 범위 1950~2030, 번호 ≤ 99999.

### 5.5 `pipeline.py`

- `uses_ruling(precedent_meta)`: `any(m.get("source_type") == "ruling" …)` — `uses_textbook` 옆, 같은 형식.
- 두 답변 분기 공통 접미(4457~4467 블록): `if used_ruling: system_prompt += RULING_CITATION_RULES`.
- 6-1 검증: `available_rulings = extract_rulings_from_hits(whitelist_hits)` → `validate_response_citations(full_text, available_precs, available_admins, available_rulings)`.
- 컨텍스트 머리글(4235): `"관련 판례·재결례 (법제처 국가법령정보센터):"`.
- `conv_metadata["rag_sources"] = Counter(m["source_type"] for m in precedent_meta)`(D20) — `precedent_meta`가 비어 있으면 키를 쓰지 않는다. `PUBLIC_EXCLUDE_KEYS`에는 넣지 않는다.
- `_build_sources_payload`·`_citation_source_hits`·게시판 제외는 변경 없음.

### 5.6 `prompts.py` — `RULING_CITATION_RULES` (D18, ≤ 450자)

```
## 재결례 인용 규칙
참고 자료에 [재결례]로 표시된 항목은 고용보험심사위원회·산업재해보상보험재심사위원회가 개별 사건을 판단한 재결입니다.
- 인용은 머리글의 기관명과 사건번호를 그대로 쓰세요. 형식: "고용보험심사위원회 YYYY재결 제N호(YYYY. M. D. 의결)", "산업재해보상보험재심사위원회 YYYY-N호(YYYY. M. D. 의결)". 기관명을 생략하지 말고, [인용 가능한 목록]에 없는 번호는 쓰지 마세요.
- 개별 사안의 판단입니다. "재결례에 따르면 항상/모든 경우"처럼 일반 규칙으로 쓰지 말고, 사실관계가 비슷할 때 "유사한 사례에서 위원회는 …라고 판단했습니다"로 쓰세요.
- 의결일자가 오래된 재결(특히 2018년 이전 산재 재결)은 그 뒤 법령·인정기준이 바뀌었을 수 있으니 현행 조문을 우선하고, [구 기준 주의] 표시가 있으면 그 내용을 현행 기준으로 안내하지 마세요.
```

### 5.7 `stale_rules`

코드 변경 없음. 현재 규칙은 일용 '10일 미만'·주휴 '다음 주'·근로기준법 제35조 셋이라 **산재 구 기준(2018년 이전 출퇴근 재해·업무상 질병 인정기준)에는 주석이 붙지 않는다**(검증 M7). 그래서 R3 완화의 실효 수단은 D9(당시 조문 미적재)·D11(의결일자 머리글)·D18(③항)·K 산재 8문항이다. 적재 뒤 Do에서 `python3 -m app.core.stale_rules --scan`과 함께 `출퇴근` + `사업주.{0,20}(제공|지배관리)` + 머리글 연도 < 2018 조합의 재결 청크 수를 세어 기록하고, 규칙 추가 여부는 후속 과제로 넘긴다(패턴 추가는 상담글 제외 경로에도 걸려 전량 육안이 필요하다 — 이 사이클 범위 밖).

### 5.8 BM25·평가 스크립트·fixture

- `build_bm25_corpus.py` 변경 없음. 적재 뒤 재실행 → gz 커밋(PR-B). 재빌드 문서 수가 `95,762 + 재결 청크 수`와 같은지 대조한다(다른 코퍼스 변화가 섞이지 않았음).
- `eval_corpus_mix.py`는 `POOL_PUBLIC_SOURCES`를 import하므로 재결례가 자동으로 '공공'이다 — 그래서 "공공 상승"은 지표가 아니다(검증 M11). §8.2 M1b가 재결례를 뺀 공공을 본다.
- `eval_colloquial.LEGAL_CORPUS_SOURCES`에 `"ruling"` 추가. D19 fixture 갱신(PR-A).

---

## 6. 테스트 — `test_rulings_ingest.py` (오프라인, CI)

fixture는 `data/ruling_fixtures/`의 실제 응답 4건(2026-11-08). 상세 2건의 `청구인`은 합성 문자열(`○○○(남자, 40세, 사무직, (주)○○, 입사일 : 2000. 1. 1.)`)로 바꿨고, `결정문상세링크`의 OC는 제거했다. HTTP는 `fetch_rulings._session.get`을 가짜로 바꿔 **함수를 실제로 호출**한다(`test_legal_api_nlrc` 방식).

| # | 검사 |
|---|---|
| RU1 | 목록 파싱: 루트 `Eiac`/`Iaciac`, `totalCnt` 118/934, 항목 3건, 일련번호·사건번호·의결일자 추출, 페이지 간 중복 제거 |
| RU2 | eiac 상세 정규화: 매핑 전부, `decided_at == "2019.10.23"`, `category == "수급자격에 관한 사례"`, `footnotes`가 `[각주 1] 청구인의 소정급여 일수는 210일…`로 시작(쌍 결합), `title`에 기관명·번호 |
| RU3 | iaciac 상세 정규화: `case_name == "요양불승인처분취소"`(접두사 제거), `title == "산업재해보상보험재심사위원회 2010-2071호 — 요양불승인처분취소"`, `decided_at == "2010.08.27"`, `category == "업무상 재해 여부 관련 > 업무상 사고 > 작업시간 중 사고"`. 날짜 `"2010.8"`(파싱 불가) → 원문 유지·`decided_year None` |
| RU4 | 정제: 숨김 span 내용 삭제, `<각주>1</각주>다. 이에` → `[각주 1]` + 개행 + `다. 이에`, `<img … alt="1번째 이미지"></img>` → `[이미지 생략: 1번째 이미지]`, `<근로계약서 발췌>` **보존**, `&amp;` 복원, 정제 뒤 잔존 태그 0 |
| RU5 | PII 스캔: `번호880101-1234567`(한글 바로 뒤)·전화·이메일 합성 삽입 → 보고 3건, 원본 fixture → 0건. 가림 목록 적용 뒤 청크에 literal 없음 |
| RU6 | md 왕복: `to_markdown` → court `parse_meta`/`parse_sections`로 필드 복원. **청구인·청구취지 문자열이 어느 청크 `text`에도 없다** |
| RU7 | 청킹(12699): 상위 소제목 열이 `사건개요·청구인 주장·원처분기관 의견·원처분기관 처분내용·관계법령, 사실관계 및 판단·결 론`과 일치, 소절 `사실관계·의학적 소견·판 단`이 각각 청크로 존재, **`사업주가 제공한 교통수단`·`시행령 제27조`·`제34조`가 어느 청크에도 없음**, 관계법령 제외 글자 수 ≥ 2,000, 모든 청크 첫 줄이 머리글, chunk 0에 쟁점+주문. (11327): `4. 관계법령`·`6. … / 가. 관계법령의 내용` 제외, `나. 판단`·`7. 결론` 존재, 각주 섹션 존재, `[각주 1]` 뒤 `다. 이에` 소항목이 `사건개요` 청크에 있음 |
| RU8 | ID·원장: `ruling_eiac_11327_chunk_0`이 그룹 `eiac_11327`의 `id_re_for`에 맞음, `group_re`가 `eiac-11327`·`nlrc_1`을 거절, 메타 `chunk_index`가 `int` |
| RU9 | iaciac 사건번호 중복: 같은 `case_no`의 두 문서가 다른 그룹·ID 충돌 0 |
| RU10 | rag: `"ruling" in POOL_PUBLIC_SOURCES`, `LEGAL_PROMOTE_SOURCES is POOL_PUBLIC_SOURCES`, `_is_public_source`·`_is_legal_source` 참, `_diversity_class_of`가 `_is_legal_source`, 라벨 맵 `"재결례"` |
| RU11 | G5 양쪽: `public/index.html` `labels`의 `ruling` 값과 rag 라벨이 같은 문자열 |
| RU12 | 인용 검증 — 양성: eiac hit(`case_no="2019재결 제117호"`, `agency="eiac"`)에 "고용보험심사위원회 2019재결 제117호" valid; iaciac hit(`2010-2071호`)에 "산업재해보상보험재심사위원회 2010-2071호" valid, "재심사위원회 2010-2071" (호 없음) valid, 별칭 "2010재결 제2071호" valid. 기관 불일치 "고용보험심사위원회 2010재결 제2071호"(iaciac 전용 키) → hallucinated. 음성: "고시(2025-124호)"·"고용노동부 고시 2018-23호"·"고용노동부고시 제2026-67호"·"2024-01-15"·문맥 없는 "2010-2071호"는 `total_cited` 불변; "2019재결 제999호" → hallucinated. 마스킹: "산업재해보상보험재심사위원회 2015-1987호 2015. 8. 27. 의결"에서 `_PREC_PATTERN` 판례 0건(검증·추출 양쪽). `_ADMIN_PATTERN`은 두 형태에 0건. `build_available_citations_text` 머리글에 "재결례", 블록에 기관명 포함, 별칭 항목 없음. 별칭 충돌: eiac 실키 `2010재결제348호`와 iaciac `2010-348호`가 함께 있으면 A 키는 eiac 항목 |
| RU13 | BM25 경로: `case_no` 없는 hit이라도 `chunk_text` 머리글 `[산업재해보상보험재심사위원회 2010-2071호 · …]`로 화이트리스트에 오르고 기관이 iaciac으로 등록된다(D11·D12) |
| RU14 | pipeline: `uses_ruling` 참/거짓, 소스 검사로 `RULING_CITATION_RULES` 접미가 `TEXTBOOK_CITATION_RULES`와 같은 블록에 있고 `SYSTEM_PROMPT_TEMPLATE`·`CONSULTATION_SYSTEM_PROMPT` 본문에는 없음, `validate_response_citations` 호출이 4번째 인자를 넘김(AST), `conv_metadata["rag_sources"]` 기록 지점 존재, 컨텍스트 머리글에 "재결례" |
| RU15 | `annotate_source_priority` 메모에 "재결례" 포함, 기존 `test_conflict_resolver` 유지 |
| RU16 | `filter_stale_hits`: 폐기 기준에 걸리는 `ruling` hit은 주석되고 제외되지 않음 |
| RU17 | 커밋 원장(PR-B 뒤): 기존 `test_committed_vector_ledgers`가 `rulings_202611.json`을 자동으로 본다. 생성기 단위 테스트: 빈 그룹·md 없는 그룹이 있으면 예외 |
| RU18 | 인증 오류 경로: `<Response>` 루트 응답 → `LawApiAuthError` → `main`이 exit 2, `_progress.json`의 `failed`에 그 일련번호가 **없다**. HTTP 500 → `failed`에 `HTTPError 500` 기록 |
| RU19 | **패턴 사전 스캔**(CI): `data/bm25_corpus.jsonl.gz`에서 `source_type != "ruling"`인 문서 전량에 `_RULING_EI_PATTERN`·`_RULING_IA_PATTERN`을 돌려 일치 0건. (PR-A 시점엔 재결례가 없어 전 문서, PR-B 뒤엔 비재결 문서가 대상이다.) 실행 시간은 `test_bm25_memory`의 로드와 같은 급 |
| RU20 | `VectorLedger.drop_groups`: 분모가 원장 전체, 가드 발동 시 미삭제, `allow_large`로 삭제 뒤 그룹 키 제거, `dry_run`은 삭제 목록만 반환 |

기존 테스트 수정: `test_precedent_ingest.py` T24-a4 집합에 `"ruling"`. `test_offline_units.test_citation_validator`는 3인자 호출 유지. `test_kin_accuracy` K12는 **변경 없이 통과해야 한다**(라벨 유지).

---

## 7. 실행 순서

```
0. 사용자 승인 D7(측정 비용 356답변) — §8.4
1. worktree:  git worktree add ../laborconsult-rul -b feat/adjudication-corpus main
              .env 링크. output_재결례/는 worktree 안에 새로 만든다(gitignore)
2. PR-A 구현 → 오프라인 스위트(RU19 포함) → 저장소 밖 실답변 전량(laborconsult_eval/**/*.json)에 문맥 패턴 스캔 0건 확인
   → PR → CI·리뷰 → 머지 → 배포 확인. 데이터 없음. 재결 검증 패턴은 켜지지만 비재결 번호에 닿지 않음을 2 의 스캔이 보인다
3. 측정 before1·before2 — base = 배포된 main(PR-A 포함), **업로드 전**(공유 인덱스라 업로드 뒤에는 base 가 오염된다)
4. 수집:  fetch_official_rules.py --dry-run --doc ei_act_58 로 인증 확인 → fetch_rulings.py → _pii_report.json 육안
          → _pii_redactions.json 작성·reviewed 표시
5. 적재:  pinecone_upload_rulings.py --dry-run(집계·중단 조건) → 실행 → 벡터 수 스냅샷
          → --write-batch-ledger --verify
6. BM25:  build_bm25_corpus.py(약 3.5 시간) → 문서 수 = 95,762 + 청크 수 대조 → 로컬 test_bm25_memory(macOS 는 과대평가라
          550 미만이면 Linux 도 통과 — 참고치) → **PR-B 초안**(원장·gz) → CI test_bm25_memory·eval_tokenizer 판정
          → 넘으면 §4.6 축소 → 재빌드 → 재판정
7. 측정 after1·after2(gz 반영 worktree) → compare_rul.py → gates.json·report.md
8. PR-B 를 Ready 로(CLAUDE.md 수치 포함) → 머지 → 배포
9. 마무리: output_재결례/(원장·가림 목록 포함)를 main 작업 트리로 이동, worktree 제거, /pdca analyze
```

- 5단계 뒤 프로덕션은 PR-A 코드로 재결례를 **이미 검색**한다. D13으로 라벨·검증·쿼터가 갖춰진 상태라 허용한다. BM25 미반영 구간(5~8)은 Dense만 재결례를 본다.
- BM25 관문을 측정 **앞**에 둔다(6단계 — 검증 M10): 축소가 필요하면 after 측정을 다시 해야 하므로.
- 프로덕션 화면으로 확인 질문을 보내지 않는다. 라벨 표시는 로컬 `uvicorn`(같은 Pinecone, `LAW_API_LIVE=off`)에서 확인하고, 프로덕션은 첫 실사용 대화의 `metadata.rag_sources`(D20)로 본다.
- launchd 예열·`check_law_freshness --anchors`는 영향 없다.

---

## 8. 측정 (저장소 밖 `~/DEV/laborconsult_eval/rul/`)

### 8.1 문항

**S+ 합성 양성 18** (`synthetic.json`, `category: "합성 양성"`, 쟁점 태그는 `source_ref`에, `forbidden_claims`에 R2 금지 문구 `re:재결례?에?\s*따르면[^.]{0,20}(항상|모든\s*경우|무조건)`):

| id | 쟁점 | 질문 요지 |
|---|---|---|
| r-ins-spouse | 피보험자격 | 남편이 운영하는 회사에서 월급 받고 사무 일을 했는데 폐업 뒤 실업급여를 신청하니 대표 배우자라 피보험자격이 안 된다고 한다. 가족이면 무조건 안 되나 |
| r-ins-coop | 피보험자격 | 협동조합 조합원이면서 조합에서 급여를 받고 일했다. 피보험자격 취득이 되나 |
| r-ins-worker | 피보험자격·근로자성 | 프리랜서 계약서에 3.3% 공제였지만 출퇴근·업무 지시를 받았다. 확인청구하면 인정되나 |
| r-ins-retro | 피보험자격·소급 | 회사가 2년 넘게 고용보험 미신고. 퇴사 뒤 소급 확인이 되나, 어느 기간까지인가 |
| r-fraud-abroad | 부정수급 | 수급 중 2주 해외여행을 다녀왔는데 그 기간 실업인정도 받았다. 부정수급인가 |
| r-fraud-job | 부정수급 | 수급 중 지인 가게에서 며칠 일한 것을 신고하지 않았다. 전액 반환·추가징수까지 되나 |
| r-fraud-self | 부정수급·자진신고 | 부정수급을 뒤늦게 자진신고하면 추가징수가 면제되나 |
| r-elig-quit | 수급자격 | 권고사직이라고 들었는데 회사가 개인 사정 퇴사로 신고해 불인정됐다. 심사청구로 뒤집히나 |
| r-elig-shift | 구직급여 일액 | 3조 2교대로 주 5일을 못 채우는데 1일 소정근로시간을 어떻게 보나 |
| r-elig-recog | 실업인정 | 실업인정일에 출석을 못 했는데 그 기간 급여를 못 받나 |
| r-early-reject | 조기재취업 | 재취업 6개월 뒤 조기재취업수당을 신청했는데 거절됐다. 어떤 경우에 거절되나 |
| r-early-related | 조기재취업 | 재취업한 회사가 이전 회사와 관련된 회사라 안 된다고 한다. 맞나 |
| r-ia-eye | 요양 불승인 | 작업 중 약품이 눈에 튀어 다쳤는데 요양 불승인. 재심사에서 무엇을 보나 |
| r-ia-msk | 요양 불승인·근골격계 | 10년 넘게 중량물을 들어 허리디스크인데 업무상 질병 불승인. 재심사에서 인정된 사례가 있나 |
| r-ia-grade-finger | 장해등급 | 손가락 절단으로 12급을 받았는데 더 높아야 할 것 같다. 재심사로 등급이 바뀐 경우가 있나 |
| r-ia-grade-brain | 장해등급·뇌심혈관 | 뇌출혈 후유증 장해등급 판정에 불복. 재심사위원회는 무엇을 기준으로 판단하나 |
| r-ia-family | 유족·과로 | 남편이 야근 뒤 집에서 쓰러져 사망, 유족급여 불승인. 무엇을 입증해야 하나 |
| r-ia-commute | 출퇴근 | 퇴근길에 장을 보러 들렀다가 다쳤는데 출퇴근 재해가 되나 |

**S− 합성 음성 6**: 연차 발생·해고예고 수당·주휴수당·연장수당 가산·직장 내 괴롭힘 신고 절차·육아휴직 기간 — 재결례 주제와 **먼** 것만(최저임금·퇴직금·평균임금은 재결례와 겹친다 — 검증 L25). `ruling` 0건이어야 한다.

**R 실사용 52**: 실업급여 45·산재 7(2026-07-01 이후 388행 중, `build_real.py`가 Supabase에서 질문만 추출, 저장소 밖 — Plan의 산재 9는 집계 정규식 차이).

**K 비회귀 22**: 지식iN 고용보험 14 + consultation 산재·괴롭힘·차별 8(D15).

### 8.2 지표 정의 (`compare_rul.py`, 입력은 D21 spy 기록)

| 지표 | 계산 |
|---|---|
| M1 재결례 공급 | `precedent_meta`(spy)에 `source_type == "ruling"`이 1건 이상인 문항 비율. S+·R은 높을수록, S−는 0 |
| M1b 재결례 뺀 공공 | `precedent_meta`의 `precedent`·`interpretation`·`regulation` 건수 합 — S+·R 전후 비교(R4 관측) |
| M2a 교정 전 환각 재결 | spy가 기록한 교정 전 `hallucinated` 중 재결 키(A·B 형태) 수 — 전 문항 합계 |
| M2b 교정 후 잔여 | 최종 답변에서 문맥 패턴으로 뽑은 재결 번호 중 `precedent_meta`의 `case_no`·title에서 뽑은 키(별칭 포함)에 없는 것 — 0이어야 한다 |
| M2c 비재결 오판 | 교정 전 `hallucinated` 중 재결 형태인데 **기관 문맥이 고시·공고·훈령**인 것, 또는 `_PREC_PATTERN` 키가 재결 번호 조각(`\d{1,5}호\d{4}`)인 것 — 0이어야 한다(R7) |
| M3 쟁점 한정 유보 | 쟁점 어휘(`피보험자격\|부정수급\|수급자격\|조기재취업\|실업인정\|구직급여\|요양\|장해\|유족\|출퇴근\|업무상`)를 담은 문장에 `compare_t30.HEDGE_RES[0]`(제공된 자료 부재)와 신규 `(판례\|행정해석\|재결\|사례)[^.\n]{0,30}(확인되지\s*않\|찾을\s*수\s*없\|없습니다)`를 적용한 건수. `HEDGE_RES[1]`(조문 부재)은 재결례로 개선되지 않으므로 뺀다(검증 L26). S+ 평균 after ≤ 0.5 × before |
| M4 비회귀 | K: `forbidden_claims` 적중 수 after ≤ before(문항별), `allowed_source_only` 거짓 0. `eval_retrieval` 해설서 도달률 전후 동일 |
| M5 자원 | CI `test_bm25_memory` RSS, `eval_tokenizer` M6 비율, `laborlaw-v2` 벡터 수(전 44,676 → 후), 원장 `vector_count` = 적재 수, `source_pack_ledger verify` 누락 0 |

유보 정규식은 측정 전 **사전 검사**(정답 예문 0건·오답 예문 전건)를 통과해야 한다.

### 8.3 관문 (`gates.json`)

G1 M1(S+) ≥ 0.80 in after1·after2 각각 · G2 M1(S−) = 0 · G3 M2b = 0 **and** M2c = 0 · G4 M3 after ≤ 0.5 × before · G5 K 금지 문구 증가 0 · G6 CI RSS ≤ 550MB(7단계 전 판정) · G7 적재 수 = 목록 `totalCnt` 합 − 필수 필드 부재 − 축소 제외(각 수를 보고서에) · 원장 일치 · 고아 0. 미달이 있어도 정의를 바꾸지 않고 기록한다. M1b 30% 넘는 감소는 관문이 아니라 후속 과제 기록이다.

### 8.4 비용·절차

- 답변 수: (18 + 6 + 52) × 4 + 22 × 2 = **348**(gpt-6-sol, `--primary openai --law-mode cache`). 사용자 승인 2026-11-08(D7). before1·before2는 11-08 저녁 worktree(PR-A 코드, 업로드 전)에서 시작.
- 명령(예): `kin/run_eval.py --fixture rul/synthetic.json --cases all --primary openai --law-mode cache --repo <worktree> --out rul/runs/before1/synthetic.json`. spy 기록(D21)은 `run[...]`에 `rag_meta`·`citation_pre`·`answer_pre` 키로 담는다.
- before는 **업로드 전**에 끝낸다(§7-3). after는 BM25 gz까지 반영된 worktree에서 돈다.

---

## 9. 위험·완화

| # | 위험 | 완화 |
|---|---|---|
| R1 | BM25 RSS 550 초과 | §4.6 축소 경로. D9의 관계법령 제외가 청크를 줄인다. 관문을 측정 앞에 둔다(§7-6) |
| R2 | 개별 판단의 일반화 | D18 가드 + 우선순위 3항 + S+ `forbidden_claims` |
| R3 | 낡은 기준 전파 | D9(당시 조문 전문 미적재 — 12699 기준 2,500자), D11 의결일자 머리글, D18 ③항, K 산재 8문항. `stale_rules`에는 산재 규칙이 **없다**(§5.7) — 후속 |
| R4 | 판례·행정해석 밀어내기 | M1b 전후 비교. 재결례가 있으면 '법률근거 있음'이라 판례 승격이 발동하지 않는 것은 설계된 동작이다. 롤백은 원장 rollback + BM25 재빌드(§5.1) |
| R5 | 호출 제한·인증 | `_raise_if_error_root` exit 2(RU18), 0.3초 간격, 재개 기록 |
| R6 | 개인정보 | 청구인·청구취지 미임베딩(RU6), PII 스캔(한글 뒤 숫자 경계 포함) → 가림 목록 → 업로더 적용(재수집에도 유지) |
| R7 | 재결 번호 검증 오탐·미탐 | D12(기관 문맥·마스킹·별칭·기관 판정) + RU12 양성·음성 + RU19 코퍼스 스캔 + §7-2 실답변 스캔 + M2c. 문맥 없는 `YYYY-N호` 환각은 **잡지 않는다**(의도된 미탐 — 고시 번호 오삭제보다 낫다) |
| R8 | iaciac 사건번호 중복 | 그룹·ID는 일련번호(RU9) |
| R9 | 업로드~배포 사이 무배선 노출 | D13 PR 순서. 측정 before도 업로드 전에 |
| R10 | 두 기관 번호 표기 겹침으로 기관 오인용 | D8(한 형태만 보임) + D18 기관명 필수 + D12 기관 판정·실키 우선 |
| R11 | 소제목 오판 | D9 세 조건(짧은 제목·어휘·순차) + RU7 fixture 단언 + dry-run 중단 조건(`결론\|판단` 없는 문서 5%) |
| R12 | `citation_relevance`(monitor)가 별칭 키를 **결과에서 뺀다**(`classify_paths`는 title·case_no·chunk_text 어디에도 없는 키를 버린다) | 기록만 되는 모드다. enforce 전환 시 별칭을 실키로 되돌려 판정해야 한다 — 후속 메모 |
| R13 | fixture의 실제 응답에 남은 개인정보 | 청구인 합성 치환, OC 제거, 성명은 법제처 마스킹. 커밋 전 PII 정규식 + 육안 |
| R14 | 하네스 spy가 시그니처를 깨뜨린다 | spy는 `*args, **kwargs` 투과(D21). `eval_corpus_mix` spy 결함을 Do에서 확인 |

---

## 10. 완료 조건 (DoD)

1. 수집: 목록 `totalCnt` 합(1,052) − 필수 필드 부재 = 저장 수. `_progress.json` `failed`에 재시도 가능한 건 0, `_pii_report.json` 전건 `reviewed`, 가림 목록 적용 확인(RU5 방식의 실데이터 점검 — 가림 literal이 적재 청크에 없음).
2. `--dry-run` 집계 기록(청크 수·관계법령 제외 글자 수·소제목 폴백 문서 수·잔존 태그 0) → 적재 → 벡터 수 스냅샷 → 원장 `vector_count` 일치 → `source_pack_ledger verify` 누락 0 → 고아 0.
3. PR-A: RU1~RU16·RU18~RU20 + 기존 스위트 통과, 실답변 스캔 0건, CodeRabbit 반영, 머지·배포. PR-B: RU17·`test_bm25_memory`·`eval_tokenizer` 통과(수치 기록), 머지·배포.
4. 측정 G1~G7 판정 + M1b 관측 기록. 보고서에 before/after 수치와 `rag_sources` 분포(after 측정분).
5. CLAUDE.md: 명령·배선 메모(PR-A), `laborlaw-v2` 구성·BM25 문서 수·RSS(PR-B).
6. `output_재결례/`(원장·가림 목록 포함)가 main 작업 트리에 있고, worktree 제거.

---

## 11. 범위 밖·후속

- nlrc 44,430건·decc·expc(Plan §3).
- 재결례 전용 상한(M1b 관측 결과에 따라).
- `stale_rules` 산재 구 기준 규칙(2018년 이전 출퇴근·인정기준) — §5.7 집계 뒤 별도 사이클(상담글 제외 경로 전량 육안 필요).
- `citation_relevance` enforce 전환 시 별칭 처리(R12).
- 문맥 없는 `YYYY-N호` 환각 탐지(R7의 의도된 미탐) — 실측에서 발생하면 재검토.
- `eval_corpus_mix.py` spy의 `stale_out` 인자 결함(검증 지적) — Do에서 확인 뒤 별도 수정.
- 재결례 `category`별 공급 분포(`rag_sources`·spy 기록으로 Report의 관찰 항목).

---

## 12. 검증(design-validator rev1) 처리표

| # | 지적 | 재현 | 처리 |
|---|---|---|---|
| H1 | 패턴 B가 `제` 없는 고시 번호를 지운다 | ✅ BM25 438건·실답변 2건 | D12 기관 문맥 필수, RU19·§7-2 스캔, M2c, D13 서술 정정 |
| H2 | 관계법령 소절 분할이 12699에서 실패 | ✅ 44~47행 조문 목이 소절로 | D9 세 조건, RU7 단언(구 출퇴근 조문 부재·≥2,000자) |
| H3 | `sources` 5건 절단·교정 후 답변·검증 미기록 | ✅ `other[:5]`, `replace` 반영, `run_eval` 기록 키 | D21 spy, §8.2 M1·M2a/b/c 재정의 |
| M4 | 순차 번호 연쇄 실패·각주 뒤 소항목·태그 제거로 줄머리 상실 | ✅ eiac 3행 | D9 블록/인라인 구분·개행 삽입·짧은 제목 조건, dry-run 중단 조건 |
| M5 | K12가 교정 라벨을 고정 | ✅ `test_kin_accuracy.py:362` | 머리말만 변경 |
| M6 | `_PREC_PATTERN`이 `1987호 2015`를 판례로 | ✅ | `_mask_ruling_spans` 선행(추출·검증) |
| M7 | `stale_rules`에 산재 규칙 없음·K에 산재 없음 | ✅ 규칙 3종 | §5.7 정직 서술 + K 산재 8문항(D15) |
| M8 | `sources` 미저장 | ✅ `conv_metadata` 키 목록 | D20 `rag_sources` |
| M9 | `--prune-missing` 가드 분모·빈 그룹 키 | ✅ `vector_ledger.py:155·184~188` | `drop_groups` 신설(§4.6), 생성기 빈 그룹 거부, 플래그 단독 허용 |
| M10 | BM25 관문이 측정 뒤 | — 절차 | §7-6 PR-B 초안으로 선판정, tokenizer 포함 |
| M11 | 공공 상승 지표가 자동 참·롤백 수단 없음 | ✅ `eval_corpus_mix.py:43` | M1b, §5.1 롤백 절차 |
| M12 | `title` 정의 둘 | ✅ 설계 내부 | D8 `case_name`/`title` 분리 |
| M13 | 별칭 충돌·기관 미검증 | ✅ iaciac `2010-348호` | D12 실키 우선·기관 판정, RU12 |
| M14 | PII `\b`·재수집 덮어쓰기 | ✅ | §3.5 lookaround·가림 목록을 업로더가 적용 |
| L15 | `가. 관계법령의 내용` 잔존 | ✅ eiac 24행 | D9 제외 정규식에 `(의내용)?`, RU7 |
| L16 | 이미지 제거로 사실 소실 | ✅ 18·21행 | `[이미지 생략: alt]` |
| L17 | 각주 `itertext` 결합 | ✅ 자식 쌍 | D16 쌍 결합 |
| L18 | 이상 데이터 처리 없음 | — | §3.2 필수 필드 부재 → failed, §3.3 날짜 실패 처리, G7 정의 |
| L19 | 접두사 정규식 공백 | — | `^\d{4}\s*재결\s*제\s*\d+\s*호\s*` |
| L20 | 프롬프트 실번호 예시 | — | D18 자리표시 |
| L21 | R12·D10·D11·sw.js 근거 오류 | ✅ | 각 항 정정(R12 '결과에서 제외', D10 `_TYPES`, D11 BM25 토큰화, sw VERSION 비필수·RU11 단언 제거) |
| L22 | 원장 `state` 순서 | — | `--verify` 옵션으로 상태 결정. `metadata_flags`는 `verify`가 읽지 않으므로 넣지 않는다 |
| L23 | `chunk_index` 정수 필수 | ✅ `build_bm25_corpus.py:65` | D10, RU8 |
| L24 | 컨텍스트·목록 머리글 | ✅ `pipeline.py:4235` | §5.4·§5.5 문구 |
| L25 | S− 과엄격 | — | 먼 주제로 교체 |
| L26 | `HEDGE_RES[1]`은 조문 부재 | ✅ `compare_t30.py:21` | M3 정의 교체 |
| L27 | 인증 오류 테스트 없음 | — | RU18 |

---

## 13. Do 실측 기록 (2026-11-08, PR-A 구현 중)

수집·청킹을 실제 1,052건에 돌려 설계를 세 군데 고쳤다. 전부 dry-run 집계가 드러낸 것이다.

| 항목 | 실측 | 처리 |
|---|---|---|
| 수집 | eiac 118/118 · iaciac 934/934(약 9분, 실패 0). 13063은 `사건번호` 필드가 없고 `의결일자` 필드도 없다. 6427은 의결일자가 `202.0.0` | `사건` 접두사(`2012재결 제3198호`)에서 그 기관 표기 `2012-3198호`를 만든다. 의결일자는 **미상**으로 두고 머리글에 `미상(2012년 접수)`만 적는다 — 재결 번호의 연도는 접수 연도라 의결 연도가 아니다(1,050건 실측 **143건(13.6%)이 다음 해 의결**, CodeRabbit 리뷰가 잡았다). `--exclude-before`는 미상을 제외하지 않는다 |
| PII | 주민번호·전화·이메일 패턴 적중 0건(보고 파일 미생성) | 가림 목록 없음. Plan 표본의 "1건 확인 필요"는 패턴 정교화(lookaround) 뒤 재현되지 않았다 |
| 이유가 이미지뿐 | **152건**(iaciac 2015 1·2016 68·2017 8·2018 75 — 스캔 이미지로만 제공) | 쟁점·주문 청크(chunk 0)만 적재된다. 폴백 통계에서 분리(`image_only`). 본문 복원(OCR)은 범위 밖 |
| HTML 잔재 | eiac 2022~2023 18건에 여는 태그 없는 `</img>`가 홀로 남았다. 본문 `HORIZON<ALL>`(의료기기 규격)은 태그가 아니다 | `</img>` 단독 제거. 잔존 태그 판정을 **알려진 HTML 태그 이름**으로 한정 |
| 소제목 인식 | rev2 규칙으로 **446건(42%)이 폴백**. 원인: ① 어휘 목록에 "원처분기관 처분 및 심사기관 결정이유"(276건)·"재심사청구의 적법 여부"가 없어 그 뒤 번호가 전부 밀림 ② 위원회 원문의 번호 중복(`6. 의학적 소견` 뒤 `6. 판단`)·건너뜀(`5. 인정사실` 뒤 `7. 결론`) 20건 ③ 연쇄 실패 뒤 관계법령 안의 `2. 업무상 질병`이 상위 절로 오인(36건) | 어휘 목록을 실측 상위 제목으로 보강(길이 상한 28). 같은 번호·+2는 **어휘가 맞을 때만** 소제목. 제외 절(관계법령)에서 빠져나오는 소제목은 어휘 필수(`strict`). 결과: 폴백 **1건**(6747 — 판단 소제목 자체가 없음), 조문형 상위 절 **0건** |
| 청크 수 | 첫 집계 12,661(평균 12.0/문서, 28%가 본문 300자 미만 — "원처분기관 처분내용" 54자·"결 론" 56자가 머리글만 단 청크) | 연속 절을 700자 안에서 묶는 **패킹**(`pack_sections`, section은 ` · `로 이음) → **11,415**(평균 10.9) |
| 관계법령 제외 | **470,677자** 제외(제목 유형 상위: `관계법령` 305·`관계 법령` 134·`… / 관계법령` 57·55·`관계법령의 내용` 47) | 설계대로 |
| BM25 추정 | 95,762 + 11,415 = 약 107,200문서(+11.9%). Plan 추정 8,800청크보다 많다(이유 길이·절 수가 표본보다 컸다) | 선형 추정 459 × 1.12 ≈ **514MB**. 관문 550MB까지 약 36MB — PR-B 초안 CI가 판정한다(§7-6). 미달 시 §4.6 |

RU 테스트는 23개가 됐다(RU7c 이미지 전용·패킹, RU21 운영 플래그·재스캔 PII, RU7b에 어휘·번호 허용 사례). PR #155 리뷰(Codex 3·CodeRabbit 17)는 날짜형 번호 배제·번호 구간만 마스킹·가림을 메타데이터까지·기관 근접 판정·미확인 번호·별칭 해소·일련번호 대조·실패 재시도·이전 파일 제거·콜론 제목·dry-run 이동 금지·prune-missing 단독·청크 0 정리·문서 재스캔 PII로 반영했다. 원문 링크(DRF OC 빈값)는 설계 D17대로 유지했다. 변경 전 측정(before1·before2)은 11-08 20:08부터 worktree(PR-A 코드)에서 진행 중이다.
