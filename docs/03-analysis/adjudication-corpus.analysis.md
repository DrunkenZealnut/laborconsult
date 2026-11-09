# adjudication-corpus — Gap Analysis (Check)

> 2026-11-09 · gap-detector 대조 150항목(코드 줄 직접 대조, 저장소 밖 결과는 §13 기록으로 판정)
> 대상: Design rev2 D1~D21·§3~§10·§13 vs main 4fa6c26(PR #155 배선 f2fc2e8 + PR #156 데이터). 테스트는 에이전트가 실행하지 않았고 단언을 읽어 판정했다 — 실행 결과는 PR #155·#156 CI(전부 통과)가 증거다.

## 분석 개요

| 항목 | 내용 |
|---|---|
| 분석 대상 | `adjudication-corpus` (고용보험심사위원회 eiac 118 · 산재재심사위원회 iaciac 934 → `laborlaw-v2`, `source_type="ruling"`) |
| 설계 문서 | `docs/02-design/features/adjudication-corpus.design.md` (rev2 + §13 Do 실측 기록) |
| 참고 Plan | `docs/01-plan/features/adjudication-corpus.plan.md` |
| 기준 코드 | `main` 4fa6c26 (PR #155 배선 f2fc2e8 + PR #156 데이터) |
| 분석일 | 2026-11-09 |
| 방법 | 설계 항목마다 코드 줄을 직접 읽어 대조했다. 저장소 밖 결과(측정 하네스, Pinecone, CI RSS)는 §13 기록으로 판정하고 "문서 기록 확인"으로 표시했다. 에이전트에는 셸이 없어 **테스트는 실행하지 않았다**. 테스트 판정은 단언 내용을 읽은 결과다. |

## 종합 점수

| 구분 | 항목 수 | 일치 | 부분 | 불일치 | 확인 불가 | 일치율 |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| 결정 D1~D21 | 21 | 21 | 0 | 0 | 0 | 100% |
| §3 수집 | 27 | 25 | 2 | 0 | 0 | 92.6% |
| §4 적재 | 31 | 29 | 2 | 0 | 0 | 93.5% |
| §5 배선 | 29 | 29 | 0 | 0 | 0 | 100% |
| §6 테스트 | 23 | 22 | 1 | 0 | 0 | 95.7% |
| §7·§8·§10·CLAUDE.md | 19 | 14 | 1 | 0 | 4 | 93.3% |
| **합계** | **150** | **140** | **6** | **0** | **4** | **95.9%** |

```
Match Rate = 일치 ÷ (전체 − 확인 불가) = 140 ÷ 146 = 95.9%
코드·데이터로 직접 확인한 항목만(문서 기록 16건 제외) = 124 ÷ 130 = 95.4%
부분을 0.5로 셈할 때 = 143 ÷ 146 = 97.9%
```

불일치는 0건이다. 부분 6건은 모두 Low 또는 문서 수준이고, Medium은 CLAUDE.md 서술 1건이다.

---

## 1. 설계 항목 전수 대조표

### 1.1 결정 D1~D21

| ID | 설계 요구 | 구현 위치 | 판정 |
|---|---|---|---|
| D1 | 출처 유형 `ruling` 하나, 메타 `agency`·`category`, 라벨 '재결례' | `pinecone_upload_rulings.py:62`, `:582-590`, `app/core/rag.py:967` | 일치 |
| D2 | iaciac 전량 934건, 관문 미달 시 2016년 이후로 축소 | 축소 경로 `pinecone_upload_rulings.py:347-358`. 전량 적재는 §13과 `output_재결례/_progress.json`(fetched 1,052) | 일치 (문서 기록 확인) |
| D3 | 머리글 + 개요/쟁점 + 주문 + 이유. 청구인·청구취지 제외 | `pinecone_upload_rulings.py:278-298` | 일치 |
| D4 | 재결 번호 패턴 + 화이트리스트 | `app/core/citation_validator.py:400-414` | 일치 |
| D5 | 판례 아래, 행정해석과 같은 층(3항) | `app/core/conflict_resolver.py:7`, `:74` | 일치 |
| D6 | 원장만 커밋, 원문은 gitignore | `.gitignore:2`, `data/vector_ledgers/rulings_202611.json` | 일치 |
| D7 | 측정 비용 실행 전 승인 | 설계 머리말 "2026-11-08 사용자 'D7 승인'" | 일치 (문서 기록 확인) |
| D8 | `case_name` 접두사 제거, `title` 형식(≤200), `case_no` 원문, 의결일자 0 채움 | `fetch_rulings.py:77`, `:132-150`, `:286-315` | 일치 |
| D9 | 소제목 3조건, 관계법령 절·소절 제외, 알려진 태그만 정제 | `pinecone_upload_rulings.py:81-180`, `fetch_rulings.py:97-129` | 일치 (기록된 편차 포함, §3) |
| D10 | ID `ruling_{agency}_{serial}_chunk_{idx}`, 그룹 정규식, 정수 `chunk_index` | `pinecone_upload_rulings.py:69-77`, `:593` | 일치 |
| D11 | 모든 청크 첫 줄이 머리글, `embed_text == text` | `pinecone_upload_rulings.py:218-222`, `:271`, `:576` | 일치 |
| D12 | A·B(기관 문맥) 패턴, 코어로 메타 파싱, 별칭은 실키 우선, 기관 판정, `_PREC_PATTERN` 앞 마스킹 | `citation_validator.py:88-238`, `:373-417` | 일치 (기록된 편차 포함) |
| D13 | PR-A 머지·배포 뒤 업로드, 그다음 PR-B | git log f2fc2e8(PR #155) → 4fa6c26(PR #156), §13 업로드 기록 | 일치 (문서 기록 확인) |
| D14 | `source_pack_ledger` 형식 원장, 빈 그룹 거부, `--verify`로 상태 결정 | `pinecone_upload_rulings.py:392-434`. 원장은 `state=verified`, 1,052문서·11,415 ID | 일치 |
| D15 | 측정 K 22문항, 348답변 | §13 "각 98문항"(18+6+52+22) | 일치 (문서 기록 확인) |
| D16 | 청구취지 제외, 각주 `각주번호`·`각주내용` 쌍 결합 | `fetch_rulings.py:258-272` | 일치 |
| D17 | DRF 규약 `official_url`, OC 빈값 | `fetch_rulings.py:177-179` | 일치 |
| D18 | `RULING_CITATION_RULES`를 두 분기 공통으로, 재결례가 실릴 때만, 자리표시 예시 | `app/templates/prompts.py:619-631`, `pipeline.py:4451`, `:4480-4482` | 일치 |
| D19 | fixture 5종 `allowed_sources`에 `ruling` | `data/eval_*_queries.json` 151항목 중 151항목 | 일치 |
| D20 | `conv_metadata["rag_sources"]` 관측 키 | `pipeline.py:4702-4709` | 일치 |
| D21 | 하네스 spy 계측 | §13 "spy 기록 전건·누락 0"(저장소 밖) | 일치 (문서 기록 확인) |

### 1.2 §3 수집 (`fetch_rulings.py`)

| ID | 설계 요구 | 구현 위치 | 판정 |
|---|---|---|---|
| 3.1 | CLI 5종(`--agency`·`--limit`·`--list-only`·`--serial`·`--force`) | `:424-430` | 일치 |
| 3.2-a | `.env` override, 키 없으면 종료 | `:47`, `:432-435` | 일치 |
| 3.2-b | display 100 페이지 순회, 일련번호 중복 제거, totalCnt 불일치 경고 | `:221-251`, `:455-457` | 일치 |
| 3.2-c | 미수집분만, 0.3초 간격, 재시도 3회 지수 백오프, 20초 | `:55-57`, `:188-206`, `:466-467` | 일치 |
| 3.2-d | 진행 기록을 건마다 atomic 저장 | 실패는 건마다(`:478`, `:485`), 성공은 25건마다와 종료 시(`:505-509`) | **부분** |
| 3.2-e | 종료 요약(저장·스킵·실패·PII·연도 분포·날짜 실패) | `:451-462`, `:510`, `:517` | 일치 |
| 3.2-f | 인증 오류는 exit 2, failed에 기록하지 않음 | `:204`, `:511-515` | 일치 |
| 3.2-g | HTTP·파싱·필수 필드 부재는 failed `{reason, at}`, 다음 실행 재시도 | `:476-486`, `:466-467` | 일치 |
| 3.2-h | reason은 클래스명+상태 또는 필드명만 | `:209-212`, `:291-293` | 일치 |
| 3.2-i | 필수 필드 = 사건번호·의결일자·이유 | 사건번호는 `사건` 접두사 폴백(`:287-291`), 의결일자는 미상 폴백(`:298-305`) | 일치 (기록된 편차, §13) |
| 3.3-a | 필드 매핑표 | `:63-74`, `:307-327` | 일치 |
| 3.3-b | iaciac `사건` 선행 번호 제거 | `:77`, `:153-154`, `:295` | 일치 |
| 3.3-c | 날짜 파싱 실패 시 원문 유지, 연도 None | `:132-150`, 머리글은 `미상(YYYY년 접수)`(`:305`) | 일치 (기록된 편차, §13) |
| 3.3-d | `case_no`·`case_name` NFC | `:286`, `:295` | 일치 |
| 3.3-e | `--exclude-before`가 연도 None을 제외하지 않음 | `pinecone_upload_rulings.py:352` | 일치 |
| 3.4-a | 정제 순서, 블록 태그는 개행, 인라인 태그는 빈 문자열 | `:102-103`, `:111-129` | 일치 |
| 3.4-b | 숨김 span은 내용째 삭제 | `:97`, `:115` | 일치 |
| 3.4-c | img를 `[이미지 생략: alt]`로 | `:98-99`, `:116-117` | 일치 |
| 3.4-d | 각주를 `[각주 n]`으로, 뒤에 소항목이 오면 개행 | `:100-101`, `:121-122` | 일치 |
| 3.4-e | 그 밖의 꺾쇠 보존 | `:103`(인라인 목록 한정 치환) | 일치 |
| 3.4-f | 정제 뒤 잔존 태그는 `failed["잔존 태그"]` | 수집기는 기록하지 않음. 업로더 dry-run이 세고 중단(`pinecone_upload_rulings.py:307`, `:557-558`) | **부분** |
| 3.5-a | PII 3종, lookaround 경계 | `:80-84` | 일치 |
| 3.5-b | 보고 형식·`reviewed: false`·원문 저장 유지 | `:489-497`, `:403-414` | 일치 |
| 3.5-c | 가림은 업로더가 청킹 시점에 적용 | `pinecone_upload_rulings.py:227-258`, `:507` | 일치 |
| 3.6-a | md 형식(court 파서 호환) | `:348-376` | 일치 |
| 3.6-b | 파일명 `{serial}_{case_no_ascii}.md` | `:165-174`, `:379-380` | 일치 |
| 3.7 | 진행 기록 구조 | `:385-400` | 일치 |

### 1.3 §4 적재 (`pinecone_upload_rulings.py`)

| ID | 설계 요구 | 구현 위치 | 판정 |
|---|---|---|---|
| 4.1-a | `NAMESPACE`·`SOURCE_TYPE` | `:61-62` | 일치 |
| 4.1-b | `make_vector_id` | `:69-70` | 일치 |
| 4.1-c | 원장 `group_re`·`id_re_for` | `:73-77` | 일치 |
| 4.1-d | record → upsert → prune 순서 | `:571`, `:600-610` | 일치 |
| 4.1-e | 소스 비재귀, `_excluded/` 제외 | `:333-344` | 일치 |
| 4.1-f | 유틸은 court 업로더에서 import | `:50-53` | 일치 |
| 4.2-a | 머리글 ≤160자, 분류 ≤80자 | `:218-222` | 일치 |
| 4.2-b | 가림은 청킹 전 | `:253-263`(메타데이터까지 확장) | 일치 |
| 4.2-c | chunk 0 `section="개요·주문"`, 700자 초과 시 분할 | `:278-284`. iaciac는 `쟁점·주문` | **부분** |
| 4.2-d | 이유 소제목 분할 → 제외 → 700/80 → 머리글 | `:286-296`, `:268-276` | 일치 (패킹은 기록된 편차) |
| 4.2-e | section `이유 — {상위}`, 소절은 `/ {소절}`, 80자 | `:138-140`, `:274`, `:326-327` | 일치 |
| 4.2-f | 각주 섹션 | `:297-298` | 일치 |
| 4.2-g | `embed_text == text` | `:576` | 일치 |
| 4.2-h | 폴백 `본문`, 서두 `서두` | `:150`, `:177-179` | 일치 |
| 4.2-i | 제외 글자 수·제목 문서별 기록 | `:287-288`, `:303` | 일치 |
| 4.2-j | 청구인·청구취지 미포함 | `:278-298` | 일치 |
| 4.3-a | 메타 필드 목록·길이 상한 | `:581-598` | 일치 |
| 4.3-b | `official` 표식 없음 | `:581-596` | 일치 |
| 4.3-c | `chunk_index` 정수 | `:593` | 일치 |
| 4.4-a | CLI 7종 | `:440-449` | 일치 |
| 4.4-b | dry-run 집계 항목 | `:539-550`. 제외 비율과 문서별 상위 소제목 열을 출력하지 않음(`tops`는 `:289-292`에서 계산만) | **부분** |
| 4.4-c | 중단 조건 3종, 실제 실행도 같은 조건 | `:553-567` | 일치 |
| 4.5-a | 원장 필드 | `:415-427` | 일치 |
| 4.5-b | 빈 그룹·md 없는 그룹이면 중단 | `:404-409` | 일치 |
| 4.5-c | `--verify`로 verified/uploaded | `:428-432`. `source_pack_ledger.py:67-86` 반환 규약(0=정상)과 맞음 | 일치 |
| 4.6-a | `--exclude-before`는 이동만, 미상은 제외 안 함, 목록 출력 | `:347-358`, `:451-460` | 일치 |
| 4.6-b | `--prune-missing --dry-run`은 그룹·벡터 수 출력 | `:462-476`, `vector_ledger.py:222-224` | 일치 |
| 4.6-c | 가드 분모는 원장 전체 | `vector_ledger.py:225-230` | 일치 |
| 4.6-d | `--prune-missing`은 단독 실행 | `:463-466` | 일치 (설계 모호성은 §5 B-2) |
| 4.6-e | `drop_groups`가 그룹 키를 제거 | `vector_ledger.py:233-235` | 일치 |
| 4.6-f | 축소 불요 판정 | §13 CI 490MB ≤ 550 | 일치 (문서 기록 확인) |

### 1.4 §5 배선 7지점

| ID | 설계 요구 | 구현 위치 | 판정 |
|---|---|---|---|
| 5.1-a | `POOL_PUBLIC_SOURCES`에 `ruling` | `rag.py:109` | 일치 |
| 5.1-b | 라벨 맵 `"ruling": "재결례"` | `rag.py:967` | 일치 |
| 5.1-c | 단일 객체라 쿼터·승격·I-9가 자동으로 따라옴 | `rag.py:154-155`, `:172-175`, `:457`, `:464-474` | 일치 |
| 5.2-a | `index.html` labels | `public/index.html:1462` | 일치 |
| 5.2-b | `sw.js` VERSION 상향 | `public/sw.js:12`(`v13-2026-11-08`) | 일치 |
| 5.3-a | docstring 원칙 줄 | `conflict_resolver.py:7` | 일치 |
| 5.3-b | 메모 3항 문구 | `conflict_resolver.py:74` | 일치 |
| 5.4-a | 패턴 A | `citation_validator.py:88` | 일치 |
| 5.4-b | 패턴 B 기관 문맥 필수 | `:91-94` | 일치 (날짜형 배제는 기록된 편차) |
| 5.4-c | 코어 IA는 메타·마스킹 전용 | `:96`, `:150`, `:212` | 일치 |
| 5.4-d | 기관 어휘 | `:97-103` | 일치 |
| 5.4-e | `_mask_ruling_spans`가 같은 길이 공백으로 가림 | `:141-154` | 일치 (번호 구간만 가림은 기록된 편차) |
| 5.4-f | `extract_rulings_from_hits` 3경로, 별칭 실키 우선 | `:168-238` | 일치 |
| 5.4-g | `validate_response_citations` 4번째 인자, None이면 재결 생략·마스킹은 항상 | `:373-417` | 일치 |
| 5.4-h | 번호 앞 30자 기관 판정 | `:104`, `:119-131`, `:409-412` | 일치 |
| 5.4-i | `extract_precedents_from_hits`도 마스킹 선행 | `:267` | 일치 |
| 5.4-j | 인용 목록 머리글, 재결례 블록, 별칭 제외 | `:330`, `:363-368` | 일치 |
| 5.4-k | 교정 문구는 머리말만 변경, 라벨 유지 | `:461-462` | 일치 |
| 5.4-l | 연도 1950~2030, 번호 ≤99999 | `:115-116` | 일치 |
| 5.5-a | `uses_ruling` | `pipeline.py:221-224` | 일치 |
| 5.5-b | 두 분기 공통 접미 | `pipeline.py:4451`, `:4480-4482` | 일치 |
| 5.5-c | `available_rulings` 전달 | `:4550-4553` | 일치 |
| 5.5-d | 컨텍스트 머리글 "관련 판례·재결례" | `:4243` | 일치 |
| 5.5-e | `rag_sources`는 meta가 비면 미기록, 게시판 제외와 무관 | `:4704-4709` | 일치 |
| 5.5-f | `_build_sources_payload`·`_citation_source_hits` 무변경 | `:333-376` | 일치 |
| 5.6 | `RULING_CITATION_RULES` 문안·자리표시·≤450자 | `prompts.py:619-631`. 문안은 설계와 같고 개행 포함 약 460자로 추정, RU14 상한은 520 | 일치 |
| 5.7 | `stale_rules` 무변경, R3 집계 기록 | §13 69청크·22문서 | 일치 (문서 기록 확인) |
| 5.8-a | BM25 문서 수 = 95,762 + 청크 수 | §13 107,177 | 일치 (문서 기록 확인) |
| 5.8-b | `eval_colloquial.LEGAL_CORPUS_SOURCES`에 `ruling` | `eval_colloquial.py:55` | 일치 |

### 1.5 §6 테스트

| ID | 설계 검사 | 구현 위치 | 판정 |
|---|---|---|---|
| RU1 | 목록 파싱, totalCnt, 페이지 간 중복 제거 | `test_rulings_ingest.py:67-86` | 일치 |
| RU2 | eiac 정규화, 각주 쌍 결합 | `:88-105` | 일치 |
| RU3 | iaciac 정규화, 접두사 제거, 0 채움, 파싱 불가 날짜 | `:107-154` | 일치 |
| RU4 | 정제(숨김 span·각주 개행·img·꺾쇠 보존·`&amp;`·잔존 0) | `:156-175` | 일치 |
| RU5 | PII 합성 3건, 원본 0건, 가림 뒤 literal 부재 | `:177-197` | 일치 |
| RU6 | md 왕복, 청구인·청구취지가 청크에 없음 | `:203-225` | 일치 |
| RU7 | 12699 소제목 열·소절·구 조문 부재·≥2,000자, 11327 제외·각주·소항목 | `:227-275`. `시행령 제27조`·`제34조` 부재 대신 다른 조문 구절 3개를 단언(`:240-241`) | **부분** |
| RU8 | ID·원장 정규식, 정수 `chunk_index` | `:330-340` | 일치 |
| RU9 | 사건번호 중복이 다른 그룹 | `:342-360` | 일치 |
| RU10 | rag 집합·동일 객체·다양성 클래스·라벨 | `:366-375` | 일치 |
| RU11 | G5 라벨 양쪽 일치 | `:377-387` | 일치 |
| RU12 | 인용 양성·음성·마스킹·`_ADMIN_PATTERN`·목록·별칭 충돌 | `:401-492` | 일치 |
| RU13 | BM25 경로(`case_no` 없음) 등록 | `:494-503` | 일치 |
| RU14 | `uses_ruling`, 접미 위치, 프롬프트 본문 부재, 4인자 AST, `rag_sources`, 머리글 | `:505-542` | 일치 |
| RU15 | 우선순위 메모 | `:544-548` | 일치 |
| RU16 | `ruling`은 주석만 되고 제외되지 않음 | `:550-559` | 일치 |
| RU17 | 커밋 원장 자동 검사, 생성기 빈 그룹·고아 거부 | `:725-759`, `test_offline_units.py:1332-1353` | 일치 |
| RU18 | 인증 오류 exit 2·failed 없음, HTTP 500 기록 | `:565-638` | 일치 |
| RU19 | BM25 비재결 문서에 A·B 일치 0건 | `:640-656` | 일치 |
| RU20 | `drop_groups` 분모·가드·키 제거·dry_run | `:658-696` | 일치 |
| T24-a4 | 승격 집합에 `ruling` | `test_precedent_ingest.py:1684-1685` | 일치 |
| K12 | 교정 라벨 무변경 | `test_kin_accuracy.py:362` | 일치 |
| CI | `test_rulings_ingest.py` 단계 | `.github/workflows/tests.yml:105-106` | 일치 |

테스트 23개는 모두 `if __name__ == "__main__"`(`:762`) 앞에 있다.

### 1.6 §7 실행 순서·§8 측정·§10 완료 조건·CLAUDE.md

| ID | 설계 요구 | 근거 | 판정 |
|---|---|---|---|
| 7-a | PR-A 배포 → before → 업로드 → BM25 → PR-B | §13, git log | 일치 (문서 기록 확인) |
| 7-b | 머지 조건인 실답변 전량 문맥 패턴 스캔 0건 | §13에 결과 기록이 없음 | 확인 불가 → §6에서 해소 |
| G1 | S+ 재결례 공급 ≥0.80 | 0.94·0.89 | 일치 (문서 기록 확인) |
| G2 | S− 0 | 0 | 일치 (문서 기록 확인) |
| G3 | M2b = 0, M2c = 0 | 0, 0 | 일치 (문서 기록 확인) |
| G4 | M3 after ≤ 0.5 × before | 0.0·0.06 → 0.0·0.0 | 일치 (문서 기록 확인) |
| G5 | K 금지 문구 증가 0 | 0 → 0 | 일치 (문서 기록 확인) |
| G6 | CI RSS ≤550MB | 490MB | 일치 (문서 기록 확인) |
| G7 | 적재 수 = 1,052 − 필수 필드 부재 − 축소 | `_progress.json` fetched 1,052·failed 0, 로컬·커밋 원장 1,052그룹 | 일치 |
| M1b | 재결례를 뺀 공공 건수 관측 | §13 R4 관측 | 일치 (문서 기록 확인) |
| M4b | `eval_retrieval` 해설서 도달률 전후 동일 | 기록 없음 | 확인 불가 |
| M5 | 원장 `vector_count` = 적재 수, verify 누락 0 | 커밋 원장 11,415·verified, 로컬 원장 11,415 | 일치 |
| DoD1 | failed 0, PII 전건 reviewed | `_progress.json:123`, `:1062`. 보고 파일 없음(적중 0) + 업로더 재스캔 | 일치 |
| DoD4 | 보고서에 `rag_sources` 분포 | 저장소 밖 보고서 | 확인 불가 |
| DoD5-a | CLAUDE.md 명령 블록 | `CLAUDE.md:60-68`. 7개 플래그 모두 argparse와 맞음 | 일치 |
| DoD5-b | CLAUDE.md 배선 메모(공공 집합·인용 패턴·우선순위·`rag_sources`) | `CLAUDE.md:406-412`, `:1032`. 우선순위 3항·`rag_sources`·`RULING_CITATION_RULES` 미기재 | **부분** |
| DoD5-c | CLAUDE.md PR-B 수치 | `CLAUDE.md:449` | 일치 |
| DoD6-a | `output_재결례/`가 main 작업 트리에 있음 | `_progress.json`·`_uploaded_ids.json` 존재 확인 | 일치 |
| DoD6-b | worktree 제거 | 셸이 없어 확인하지 못함 | 확인 불가 → §6에서 해소 |

---

## 2. Gap 목록

### 2.1 부분 일치 6건

| # | 심각도 | 설계 참조 | 코드 위치 | 차이 | 권고 |
|---|---|---|---|---|---|
| G-1 | Medium | §10 DoD 5, §2 CLAUDE.md 행 | `CLAUDE.md:406-412` | 우선순위 3항, `metadata.rag_sources`, `RULING_CITATION_RULES` 두 분기 접미가 없다. 409행의 "짧은 제목(12자)·어휘·순차 번호 세 조건을 모두"는 rev2 서술이다. §13에서 어휘를 보강하고 길이 상한을 28로 올렸으며 같은 번호·+2를 허용하고 제외 절 이탈에 strict를 걸었는데, 그 내용이 반영되지 않았다. 해설서·상담 가드는 CLAUDE.md에 두 분기 규칙이 자세히 적혀 있어 대칭도 깨진다. | 재결례 절에 세 줄을 더하고 소제목 규칙을 §13 기준으로 고친다. "약 2,080자"와 설계의 "약 2,500자"도 맞춘다. |
| G-2 | Low | §3.2 4단계 "건마다" | `fetch_rulings.py:505-509` | 성공 건은 25건마다와 종료 시에만 저장한다. 중간에 죽으면 최대 24건의 진행 기록을 잃고 다음 실행에서 다시 받는다. md는 같은 내용으로 덮어써 데이터 손상은 없다. | 성공 건마다 저장하거나 설계를 "25건마다"로 고친다. |
| G-3 | Low | §3.4 잔존 태그 → failed | `fetch_rulings.py:105-107`, `pinecone_upload_rulings.py:97-99`, `:557-558` | 수집기는 잔존 태그를 기록하지 않고 업로더 dry-run이 막는다. 보호 효과는 같지만, 수집기 쪽 `RESIDUAL_TAG_RE`는 정의만 있고 쓰이지 않으며 두 파일에 같은 정규식이 복제돼 있다. | 설계를 "업로더가 중단"으로 고치고 정규식은 한 곳에서 import한다. |
| G-4 | Low | §4.2 chunk 0 `section="개요·주문"` | `pinecone_upload_rulings.py:284`, `test_rulings_ingest.py:248` | iaciac는 `쟁점·주문`이다. RU7이 이 값을 고정하는데 §13에는 기록이 없다. | 설계 문서만 고친다. |
| G-5 | Low | §4.4 dry-run 집계 | `pinecone_upload_rulings.py:539-550` | 관계법령 제외 비율과 문서별 상위 소제목 열을 출력하지 않는다. `tops`는 계산하지만 집계하지 않는다. | 출력하거나 설계에서 뺀다. |
| G-6 | Low | §6 RU7 | `test_rulings_ingest.py:240-241` | 설계는 `시행령 제27조`·`제34조` 부재를 단언하라고 했고, 테스트는 다른 조문 구절 3개의 부재를 단언한다. 판단 절이 시행령 조문 번호를 정당하게 언급할 수 있어 테스트 쪽이 더 안전하다. | 설계 문서를 테스트에 맞춘다. |

### 2.2 확인 불가 4건

| # | 항목 | 이유 | 권고 |
|---|---|---|---|
| U-1 | §7-2 실답변 전량 문맥 패턴 스캔 0건(D13 머지 조건) | §13에 결과가 없다. 측정 G3의 "비재결 오판 0"은 측정 답변 98문항 기준이라 대체 근거가 되지 않는다. | 하네스 스캔 결과를 보고서에 기록한다. → §6 |
| U-2 | §8.2 M4 `eval_retrieval` 해설서 도달률 전후 | §13 측정 행에 없다. | 측정했다면 수치를 기록하고, 아니면 미측정으로 적는다. |
| U-3 | DoD 4 `rag_sources` 분포 | 저장소 밖 `report.md`에만 있을 수 있다. | Report 단계에서 옮겨 적는다. |
| U-4 | DoD 6 worktree 제거 | 셸 없이 확인할 수 없다. | `git worktree list`로 확인한다. → §6 |

---

## 3. 기록된 편차 (gap 아님)

§13 또는 PR #155 리뷰 반영으로 설계 문서에 기록된 변경이다.

| # | 변경 | 설계 기록 | 코드 위치 |
|---|---|---|---|
| 1 | 소제목 어휘 보강, 길이 상한 28 | §13 소제목 인식 | `pinecone_upload_rulings.py:86-90`, `:106-117` |
| 2 | 같은 번호·+2는 어휘가 맞을 때만 소제목 | §13 | `:120-123` |
| 3 | 제외 절에서 빠져나오는 소제목은 어휘 필수(strict) | §13 | `:109-111`, `:159`, `:168` |
| 4 | 연속 절 패킹 | §13 청크 수 | `:312-328` |
| 5 | 이유가 이미지뿐인 152건을 폴백 통계에서 분리 | §13 | `:300-306` |
| 6 | 홀로 남은 `</img>` 제거, 잔존 태그는 알려진 태그 이름만 | §13 HTML 잔재 | `fetch_rulings.py:105-108`, `:118` |
| 7 | 사건번호가 없으면 `사건` 접두사에서 기관 표기로 생성 | §13 수집(13063) | `fetch_rulings.py:157-162`, `:287-289` |
| 8 | 의결일자 폴백 `미상(YYYY년 접수)` | §13 수집(6427·13063) | `fetch_rulings.py:298-305` |
| 9 | 패턴 B의 날짜형 번호 배제 | §13 리뷰 반영 | `citation_validator.py:89-94` |
| 10 | 마스킹은 번호 구간만 | §13 | `citation_validator.py:150-153` |
| 11 | 가림을 메타데이터까지 | §13 | `pinecone_upload_rulings.py:253-258` |
| 12 | 기관 판정은 번호에 가장 가까운 기관 | §13 | `citation_validator.py:119-131` |
| 13 | 기관 미확인 번호는 목록에서 빼고, 기관을 붙여 인용하면 환각 | §13 | `citation_validator.py:217-226`, `:363` |
| 14 | 별칭을 실키로 바꿔 `citation_relevance`에 전달(R12 일부 해소) | §13 | `citation_validator.py:157-165`, `pipeline.py:4595` |
| 15 | 응답 일련번호 대조(`SerialMismatch`) | §13 | `fetch_rulings.py:91-92`, `:282-284` |
| 16 | failed에 있으면 fetched여도 재시도 | §13 | `fetch_rulings.py:465-467` |
| 17 | 같은 일련번호의 이전 파일 제거 | §13 | `fetch_rulings.py:498-501` |
| 18 | 끝 콜론·마침표가 붙은 관계법령 제목도 제외 | §13 | `pinecone_upload_rulings.py:126-128` |
| 19 | `--exclude-before --dry-run`은 이동하지 않음 | §13 | `pinecone_upload_rulings.py:347-358` |
| 20 | `--prune-missing`은 `--agency`·`--limit` 거부 | §13 | `pinecone_upload_rulings.py:463-466` |
| 21 | 청크가 0이 된 문서의 이전 벡터 정리 | §13 | `pinecone_upload_rulings.py:513-517`, `:611-613` |
| 22 | 문서 재스캔 PII(`pii_problems`) | §13 | `pinecone_upload_rulings.py:361-377`, `:508-511` |
| 23 | 원문 링크는 D17(DRF, OC 빈값) 유지 | §13 | `fetch_rulings.py:177-179` |
| 24 | RU7b·RU7c·RU21 추가 | §13 | `test_rulings_ingest.py:277-328`, `:698-723` |

---

## 4. 설계 공백 (설계에 없거나 설계가 다루지 않은 위험)

### 4.1 확인 결과 문제없음

- **두 답변 분기 대칭.** `RULING_CITATION_RULES`는 두 분기 공통 블록에 붙는다(`pipeline.py:4480-4482`). 인용 가능 목록도 두 분기 모두에 실린다(`pipeline.py:4230-4239`). 한쪽에만 붙은 규칙은 없다.
- **공개 저장소 노출.** fixture 4건은 청구인이 합성 문자열로 바뀌었고 OC 문자열이 없다. 커밋 원장에는 제목·URL·sha256·ID만 있다. BM25 gz의 재결 청크는 공공저작물이고 청구인·청구취지를 담지 않는다.
- **답변 경로 격리.** `app/`·`api/`는 `fetch_rulings`를 import하지 않는다. 그 스크립트의 `load_dotenv(override=True)`가 답변 경로로 번지지 않는다.
- **`_pii_report.json` 부재 처리는 적절하다.** 보고 파일이 없으면 `pii_unreviewed()`는 0을 돌려주지만(`pinecone_upload_rulings.py:239-243`), 업로더가 가림 적용 사본을 문서마다 다시 스캔한다(`:361-370`, `:508-511`). 그래서 파일 부재가 실제 적중을 통과시키지 않는다. 보고서 키의 필드명이 수집기(`official_url`)와 업로더(`url`)에서 한 곳 다르지만, 불일치는 차단 쪽으로 작동해 안전하다.

### 4.2 공백 목록

| # | 심각도 | 내용 | 위치 | 권고 |
|---|---|---|---|---|
| B-1 | Medium | **재결례가 판례·행정해석·훈령 슬롯을 잠식하는데 코드 킬스위치가 없다.** §13 R4 관측에서 재결례를 뺀 공공 건수가 S+ 42·53 → 20·16(약 60% 감소), R 72 → 62·60으로 줄었다. 재결례가 법률근거 클래스에 들어가 I-9가 재결례 1건을 보호하고, "법률근거 있음"이라 판례 승격이 발동하지 않는다. 설계는 롤백 수단을 데이터 롤백(원장 rollback + BM25 재빌드)으로만 정했고, `LEGAL_POOL_QUOTA=off`는 쿼터 전체를 끈다. 관문은 아니었지만 답변의 법률 근거 구성이 바뀐 상태다. | `rag.py:109`, `:457`, `:464-474` | 후속 사이클에서 재결례 전용 상한이나 별도 다양성 클래스를 검토한다. 그때까지 쓸 env 킬스위치(재결례 필터)를 두면 재배포만으로 되돌릴 수 있다. |
| B-2 | Low | **`--allow-large-prune` 설계 내부 모순.** §4.4는 일반 업로드에서 쓰는 용법을 적었고, §4.6은 "`--prune-missing` 단독 실행에서만 받는다"고 적었다. 구현은 두 경로 모두 받고, 일반 업로드에서는 `--agency`·`--limit`과도 함께 쓸 수 있다. 그룹이 일련번호라 피해 범위는 그 실행분이다. | `pinecone_upload_rulings.py:444`, `:472-473`, `:609-610` | 설계 문서에서 용법을 하나로 정리한다. |
| B-3 | Low | **조용히 무시되는 플래그 조합.** `--write-batch-ledger`에 `--dry-run`을 붙여도 파일을 쓰고, `--verify`가 있으면 Pinecone도 조회한다. `--verify` 단독은 아무 일도 하지 않는다. `--exclude-before`와 `--prune-missing`을 함께 주면 prune 없이 exit 0이다. | `pinecone_upload_rulings.py:451-460`, `:478-482` | argparse 상호 배타 그룹으로 막는다. |
| B-4 | Low | **목록 첫 페이지가 실패하면 0건 요약 후 exit 0이다.** totalCnt가 0이 되어 "건수 불일치" 경고도 뜨지 않고 `[실패]` 한 줄만 찍힌다. 재개 실행이라 피해는 작지만 수집 완료로 오인할 수 있다. | `fetch_rulings.py:231-233`, `:455-457` | 목록이 0건이면 0이 아닌 코드로 끝낸다. |
| B-5 | Low | **기관 판정이 제목 문자열에만 기댄다.** rag가 `agency` 메타를 운반하지 않아(`rag.py:71-91`, `:988-998`, `pipeline.py:357-366`) `_agency_in(title)`이 유일한 경로다. 이 함수는 iaciac 어휘를 먼저 보고 맨 "재심사위원회"도 포함한다. eiac 제목에 그 낱말이 들어가면 iaciac로 등록되고, 정당한 "고용보험심사위원회 …" 인용이 환각으로 교정된다. 현재 실례는 확인하지 못했다. | `citation_validator.py:134-138`, `:207`, `:220` | `_query_namespaces`가 `agency`를 운반하거나, 제목 맨 앞 기관명으로 판정한다. → §6 검증 |
| B-6 | Low | **`eval_corpus_mix.py` spy가 여전히 `stale_out`을 받지 않는다.** 파이프라인이 `stale_out=`을 넘기므로 `--production` 경로는 TypeError로 죽는다. 설계 §11 후속 항목이 아직 열려 있다. 이 스크립트는 재결례를 '공공'으로 세어 공공 지표도 부풀린다(설계 M11이 인지함). | `eval_corpus_mix.py:68`, `pipeline.py:4066-4068` | spy를 `*args, **kwargs` 투과로 고치고, 공공 집계에서 `ruling`을 따로 센다. |
| B-7 | Low | **G4 관문이 개선을 측정하지 못했다.** S+ 기준선이 이미 0.0·0.06이라 "after ≤ 0.5 × before"가 자동으로 참이다. | 설계 §8.3 | Report에 "기준선 포화로 판별력 없음"을 적는다. |
| B-8 | Low | **이미지 전용 152건은 쟁점·주문 청크만으로 '재결례'로 실린다.** 이유를 보지 못한 채 결론("기각")만 인용될 수 있다. | `pinecone_upload_rulings.py:300-306` | 후속 OCR 사이클 전까지 Report의 관찰 항목으로 둔다. |
| B-9 | Low | **설계 문서 내부 불일치.** §7-0은 "356답변", D15·§8.4는 "348답변"이다. §2 표는 "RU1~RU19", §6은 RU20까지 있다. D9의 "12자 이하"는 §13에서 28자 상한으로 바뀌었다. 수집기의 `REQUIRED_FIELDS` 상수는 쓰이지 않는다(`fetch_rulings.py:60`). | 설계 문서, `fetch_rulings.py:60` | 문서 정리 때 함께 고친다. |

---

## 5. 다음 단계 권고 (gap-detector)

Match Rate는 **95.9%**로 90%를 넘는다. 불일치 0건, 부분 6건은 문서 수준이거나 Low다. `/pdca iterate` 대상이 아니고 `/pdca report adjudication-corpus`로 진행하면 된다.

1. **Report 전에 문서를 정리한다.** CLAUDE.md 재결례 절을 보강하고(G-1), §13에 없는 편차 3건(G-4·G-5·G-6)과 내부 불일치(B-9)를 설계 문서에 반영한다. 코드 변경은 필요하지 않다.
2. **Report에 기록할 것.** 확인 불가 4건(U-1~U-4)의 결과나 미측정 사실, R4 공공 잠식 수치(B-1), G4 판별력 부재(B-7), 이미지 전용 152건(B-8).
3. **후속 사이클 후보.** 재결례 전용 상한 또는 별도 다양성 클래스와 env 킬스위치(B-1), `stale_rules` 산재 구 기준 규칙(§11, §13 집계 69청크·22문서), `eval_corpus_mix.py` spy 수정(B-6).
4. **선택적 소규모 수정.** 플래그 상호 배타(B-3), 목록 0건 종료 코드(B-4), 진행 기록 저장 주기(G-2), 정규식 단일화(G-3), 기관 메타 운반(B-5).

테스트는 단언 내용을 읽어 판정했고 실행하지 않았다. 실행 근거는 PR #155·#156 CI 통과 기록이다.

관련 파일: `docs/02-design/features/adjudication-corpus.design.md` · `fetch_rulings.py` · `pinecone_upload_rulings.py` · `vector_ledger.py` · `app/core/citation_validator.py` · `app/core/pipeline.py` · `app/core/rag.py` · `app/templates/prompts.py` · `test_rulings_ingest.py` · `CLAUDE.md` · `eval_corpus_mix.py`

---

## 6. 검토자 보강 (Check 세션, 2026-11-09 — gap-detector 결과를 셸로 재확인)

| # | 항목 | 확인 | 결과 |
|---|---|---|---|
| U-1 | 실답변 전량 문맥 패턴 스캔(D13 머지 조건) | PR #155 머지 전(11-08) 저장소 밖 `laborconsult_eval/**/*.json` 26,496파일에 패턴 A·B(문맥 포함) 스캔 — Do 기록(`.bkit/state/memory.json` `doProgress.prA`) | **0건 — 해소(일치)**. §13에 적지 않았던 것이 누락이다(Report에 기록) |
| U-4 | worktree 제거 | `git worktree list` — `../laborconsult-rul` 없음, `output_재결례/`(md 1,052·`_uploaded_ids.json`·`_progress.json`)는 main 트리로 이동 | **해소(일치)** |
| U-2 | `eval_retrieval` 해설서 도달률 전후 | 이번 사이클에서 **측정하지 않았다** | 미측정으로 Report에 적는다(해설서 승격은 교체 방식이라 재결례 추가로 노출 상한이 바뀌지 않는다 — 구조 근거만 있다) |
| U-3 | `rag_sources` 분포 | 저장소 밖 `rul/report.md`·`runs/after*/` | Report 단계에서 옮겨 적는다 |
| B-3 | 플래그 조합 | `pinecone_upload_rulings.py` main: `--write-batch-ledger` 분기가 `args.dry_run`을 읽지 않고, `--exclude-before` 분기가 `return 0`으로 끝나 `--prune-missing`에 닿지 않는다 | **확인됨**(Low) |
| B-4 | 목록 첫 페이지 실패 | `fetch_list`: `root is None → break`, `total`은 0으로 남아 "건수 불일치" 조건 `total and …`이 거짓 | **확인됨**(Low) |
| B-5 | 기관 판정이 제목에 기댐 | `_RULING_AGENCY_WORDS`는 iaciac 어휘(맨 "재심사위원회" 포함)를 먼저 본다. 수집 원문 대조: eiac 118건의 **제목·본문 어디에도 "재심사위원회" 낱말이 없다**(0/118; "재심사 청구"는 있으나 기관명이 아니다). `extract_rulings_from_hits`는 `hit.get("agency")`를 먼저 보므로 rag가 `agency`를 운반하면 즉시 해소된다 | **잠재 위험만, 현재 실례 0**(Low 유지) |

재집계: U-1·U-4를 일치로 옮기면 일치 142 · 부분 6 · 확인 불가 2 → **142 ÷ 148 = 95.9%**(변동 없음).

### 6.1 Act 범위 제안

| 묶음 | 내용 | 변경 성격 |
|---|---|---|
| A(문서) | G-1 CLAUDE.md 재결례 절 보강(우선순위 3항·`rag_sources`·두 분기 접미·소제목 규칙 §13 기준·2,080자) · 설계 G-4(iaciac `쟁점·주문`)·G-5(dry-run 집계 항목 축소)·G-6(RU7 단언)·B-2(`--allow-large-prune` 용법 하나로)·B-9(356→348, RU20, D9 28자, `REQUIRED_FIELDS`) · §13에 U-1 스캔 결과 추가 | 문서만 |
| B(소규모 코드) | B-3 argparse 상호 배타(`--write-batch-ledger`+`--dry-run` 거부, `--verify` 단독 거부, `--exclude-before`+`--prune-missing` 거부) · B-4 목록 0건이면 exit 1 · G-3 `RESIDUAL_TAG_RE` 단일 출처(업로더가 수집기에서 import) · B-6 `eval_corpus_mix` spy `**kwargs` 투과 · `REQUIRED_FIELDS` 제거 | 스크립트·평가 도구만(답변 경로 무변경), RU 테스트 추가 |
| C(후속 사이클) | B-1 재결례 전용 상한/다양성 클래스 + env 킬스위치 · stale_rules 산재 구 기준 · B-5 `agency` 메타 운반 · B-8 이미지 전용 152건 OCR · G-2 저장 주기 | 설계 필요 |

---

## 7. Act-1 적용 결과 (2026-11-09, 사용자 "A+B 진행")

| 묶음 | 적용 | 파일 |
|---|---|---|
| A 문서 | G-1 CLAUDE.md 재결례 절에 배선 5지점(우선순위 3항·두 분기 접미·4번째 인자·`rag_sources`·라벨 양쪽)·운영 플래그 조합·R4 슬롯 잠식과 되돌림 수단을 적고 소제목 규칙을 §13 기준(28자·같은 번호/+2 어휘 필수·탈출 어휘 필수)으로 고쳤다 | `CLAUDE.md` |
| A 문서 | G-4 chunk 0 `쟁점·주문`(iaciac) · G-5 dry-run 집계에서 비율·문서별 열 생략 명시 · G-6 RU7 단언을 테스트에 맞춤 · B-2 `--allow-large-prune` 두 경로 수용·그룹 범위 · G-2 저장 주기(25건·종료 시) · B-9 356→348·RU1~RU21(27 테스트)·D9 28자·2,500→2,080자 · §13에 머지 전 스캔(U-1)과 Check 행 추가 | `docs/02-design/features/adjudication-corpus.design.md` |
| B 코드 | B-3 플래그 조합 거절(`--write-batch-ledger`+`--dry-run` / 단독 `--verify` / `--exclude-before`+`--prune-missing` → exit 1, 부작용 없음) · G-3 `RESIDUAL_TAG_RE`를 수집기에서 import(단일 출처) — **검사 책임은 업로더 dry-run 한 곳**으로 설계 §3.4를 고쳤다(수집기 `failed` 기록은 하지 않는다; 중단 메시지에 문서 이름을 싣는다) | `pinecone_upload_rulings.py` |
| B 코드 | B-4 목록 0건이면 `[실패]` 출력 + exit 1(건별 failed에는 적지 않음) · 미사용 `REQUIRED_FIELDS` 제거 | `fetch_rulings.py` |
| B 코드 | B-6 spy가 `**kwargs`(`stale_out=`)를 투과 | `eval_corpus_mix.py` |
| B 테스트 | RU22 플래그 조합 · RU23 목록 0건 exit 1 · RU24 정규식 동일 객체(`is`)·상수 부재 · RU25 spy `**kwargs`(AST) | `test_rulings_ingest.py` (23 → **27**) |

검증: `test_rulings_ingest.py` 27/27 · `test_offline_units.py` 전부 통과 · `test_law_api_recovery.py` 42 · `test_effective_law.py` 31 · `test_precedent_ingest.py` 전체 통과(venv Python 3.11). 답변 경로(`app/`·`api/`)는 바꾸지 않았다.

**자체 재집계**(gap-detector 재실행은 하지 않았다): 부분 6건 전부 해소(G-1·G-3 코드·문서, G-2·G-4·G-5·G-6 설계 정합), U-1·U-4 해소 → 일치 148 · 확인 불가 2(U-2 미측정·U-3 저장소 밖 보고서) → **148 ÷ 148 = 100%**(엄격 기준 동일). 설계 공백은 B-3·B-4·B-6·B-9 해소, B-2·G-2 문서 정합, **B-1(재결례 전용 상한·킬스위치)·B-5(`agency` 메타 운반)·B-7(G4 포화 기록)·B-8(이미지 152건)은 후속·Report 기록**으로 남는다.

다음: `/pdca report adjudication-corpus` → archive. 커밋·PR은 사용자 요청 시.

---

## 8. PR #157 리뷰 반영 (CodeRabbit 3건 · Codex 0건)

| # | 지적 | 검증 | 반영 |
|---|---|---|---|
| CR-1 | G-3을 정규식 공유만으로 해소로 셈했다 — 설계 §3.4는 여전히 수집기 `failed` 기록을 요구 | 타당. 설계 §3.4 문장이 rev2 그대로였다 | 설계 §3.4를 "수집기는 기록하지 않고 업로더 dry-run이 유일한 검사점"으로 고치고, 중단 메시지에 잔존 태그 문서 이름(최대 5)과 조치(`--serial` 재수집·정제 규칙 점검)를 싣는다. 재집계는 변동 없음(설계 정합으로 닫힘) |
| CR-2 | 목록 2페이지 이후 조회 실패가 부분 목록 + exit 0 | 타당. `fetch_list`가 `root is None → break`라 '건수 불일치' 경고만 남았다 | `ListFetchError` — 어느 페이지든 실패면 raise, main이 `[실패]`로 받아 exit 1(건별 `failed`에는 적지 않음). RU23b |
| CR-3 | `--write-batch-ledger`+`--exclude-before`/`--prune-missing`이 원장을 쓰지 않고 성공 | 타당. 이동·삭제 분기가 먼저 `return 0` | 거절 목록에 추가 + `--agency`·`--limit`도 거절(원장은 로컬 전체를 옮기므로 무시되던 플래그). RU22 보강 |

| CR-4 | 잔존 태그 중단 안내의 `--serial` 재수집은 `--agency` 없이는 수집기가 exit 1 | 타당(`fetch_rulings.main`: `--serial`은 `--agency` 필수) | `residual_docs`에 `기관/파일명`을 담고 안내를 `--agency <기관> --serial <일련번호>`로. RU24에 문구·동작 고정 |

테스트 **28/28**. CLAUDE.md 운영 플래그 문장도 같은 내용으로 갱신.
