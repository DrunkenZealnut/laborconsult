# precedent-corpus-followup Gap Analysis

> Check 단계 (gap-detector, 2026-08-09)
> 기준: `docs/02-design/features/precedent-corpus-followup.design.md` (Do 중 갱신 반영본)
> 대상: `sync_overlap_precedents.py` · `fetch_court_precedents.py`(--cases) ·
> `pinecone_upload_legal.py` · `upload_new_precedents.py` · `test_precedent_ingest.py` · `CLAUDE.md`

## Match Rate: 95%

| 판정 | 개수 |
|------|---:|
| ✅ 일치 | 47 |
| ⚠️ 부분일치 | 5 |
| ❌ 미구현 | 0 |
| ➕ 설계 초과 | 10 (감점 없음) |

(47 + 5×0.5) / 52 = 95.2% → **95%**. 핵심인 §2.3 삭제 안전 규칙 5종과
Track A NFD 수정은 **한 항목도 누락 없이** 구현 확인. 실행 산출물
(`_겹침대상.csv` 286행, `_ctx_deleted.json` 128사건/950 ID)이 §6 구현 순서
수행을 뒷받침.

## 갭과 처리 (측정 후 Check 단계에서 즉시 정정)

| # | 심각도 | 내용 | 처리 |
|---|:---:|------|------|
| G1 | 중간 | CLAUDE.md가 봉인된 NFD 버그를 현존으로 서술 — 매 세션 로드 문서라 미래 세션이 재수정하거나 코드를 불신 | ✅ "봉인됨(2026-08-09, T14)" + laborlaw-v2 재수집 사실로 갱신 |
| G2 | 낮음~중간 | T15 L2 생략 검증이 소스 문자열 매칭 | ✅ `resolve_existing(cases_mode)` 순수 함수 추출 + 반환값 검증(T15-b/c) |
| G3 | 낮음 | T14-d가 다카만, NFC 정규화 후 전달이라 내부 처리 미검증 | ✅ NFD 파일명 그대로 넘기는 헌바 케이스(T14-e2) 추가 |
| G4 | 낮음 | V0/V1 자동 출력 부재(설계 §1 [무수정] 지정과 §2.4 자동 출력 요구의 내부 모순) | ✅ 업로드 스크립트 말미 V1 스냅샷 출력 추가 |
| G5 | 낮음 | Plan의 "836개 시뮬레이션" 대비 T14-c가 픽스처 19종 | ✅ `_target_case_numbers()` 재사용 — CSV 있으면 601건 전량(로컬), CI는 픽스처 |
| G6 | 관찰 | `upload_new_precedents.case_no_to_ascii`의 구형 10종 매핑 + 조용한 비ASCII 제거가 잔존 — §3.3 "재발 방지" 의도와 어긋남 | ✅ 45종 매핑 + hex 폴백으로 이식(T14-g/h) — 설계 명세 밖이나 사이클 취지 내라 즉시 처리 |

정정 후 오프라인 테스트 **78건 전부 통과** (T14 11 · T15 3 · T16 5 포함).

## 설계 초과 구현 (발췌)

- SDK `index.list()` 반환형 다형(str/ListItem/ListResponse) 흡수 — Do 중 실런타임에서 발견
- `valid_ctx_id`의 `re.fullmatch` + `re.escape` / T16-d·e(접미 변형·타 소스 거부)
- fetch `--cases` 헤더에 "[명시 대상 모드] / L2 생략" 표시 — 모드 오인 방지
- legal `extract_post_id` 최종 폴백도 hex + 경고 출력 — 조용한 폴백 전면 차단

## 데이터 실행 결과 (코드 외, Do 단계 실측)

| 항목 | 결과 |
|------|------|
| 겹침 재계산 | 286건 (Plan 추정 266 대비 +20 — 공백 허용 스캔) |
| 수집 | 274/286 (96%), 미발견 12건은 ctx 보존으로 현상 유지 |
| 벡터 4시점 | V0 10,989 → V1 **12,179**(정확) → 삭제 950 → V2 **11,229**(정확) |
| 유실군 복구 | 표본 3건(`2019두59349` 등) 벡터 생성 + Dense/BM25 검색 히트 확인 |
| BM25 | 62,315문서 (= 62,075 + 1,190 − 950 정확). 1차 qa 타임아웃은 기존 gz 보존 로직이 방어 → 재시도 성공 |
| Track C | ④ 수용 권고 판정, 설계 §7 부록 기입 |

## 결론

미구현 0건. 부분일치 5건은 전부 검증 강도·문서 정합성 사안으로 **Check 단계에서
전건 정정 완료**, 관찰 1건(G6)도 즉시 이식. Match Rate 95% ≥ 90% — Act 불필요.
남은 것은 커밋·PR·BM25 gz 배포(선행 사이클과 동일한 "미커밋 시 조용한 Dense-only
폴백" 규약)뿐이다.
