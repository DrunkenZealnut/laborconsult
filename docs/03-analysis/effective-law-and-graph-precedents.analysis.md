# effective-law-and-graph-precedents — Gap Analysis (Check)

> 2026-10-04 · gap-detector 대조(110항목) + 후속 조치 반영
> 대상: Design rev2 §0~§10 (§11 검증 반영 이력, §13 C1~C20 = 승인된 변경·실측)

## 1. 요약

| 항목 | 결과 |
|---|---|
| **Match Rate** | **98.2%** (부분 일치 0.5 계산) · 엄격 기준 96.4% |
| 대조 항목 | 110개 — D1~D14, §3~§7 세부, §8 E1~E17 + 기존 테스트 갱신 6건, §9 1~10단계 |
| 일치 / 동등(§13 미기록) / 부분 / 누락 | 104 / 2 / 4 / **0** |
| C1~C16 확인 | 코드 확인 13 · 부분 1(C13 → 후속에서 해소) · 실측 기록 2(C2·C16) |
| 정합성 위험 | Medium 4 · Low-Med 1 · Low 7 → 위험 6과 P1을 뺀 나머지 전부 조치(12는 PR 리뷰 후 조치) |

미할당 변수와 fail-open 경로 이탈은 **없었다**. 확인 범위는 pipeline의 신규 변수 5개 전부가 무조건 초기화되는지, `precedent_records` 예외 흡수, `fetch_relevant_articles`의 반환 경로 3곳 모두 통계 공개, `_article_expiry` 계산, L1 튜플 의미 변경의 잔존 독자 0이다.

## 2. 부분 일치·변경

| # | 위치 | 차이 | 처리 |
|---|---|---|---|
| P1 | `rule_facts` insured_status 앵커 | `ei_enf_145`의 두 앵커가 같은 항(②)인지를 보장하지 못한다 | **수용** — 구절 앵커의 원리적 한계. 구간 결속 앵커는 범위 밖 |
| P2 | E3 | `v3:` 키를 읽지 않는다는 직접 단언이 없었다 | **조치** — 단언 추가, 출력 문구 v4 |
| P3 | E17 | `fetch_nlrc_detail` 누락 | **조치** |
| P4 | Plan 완료 조건 4 | 2013다25194 결과 미기록 | **조치** — 3차 Live 0건(§13 C20) |
| X1 | `check_law_freshness` 시행 예정 목록 | `nw=2` 대신 efdes 목록 필터 | 동등 — §13 C17 기록 |
| X2 | G4 구간 | "다음 선고"가 아니라 "다음 사건번호"까지 | 동등 — §13 C18 기록(`supersedes` 속성 포함) |

## 3. 정합성 위험과 조치

| # | 심각도 | 내용 | 조치 |
|---|---|---|---|
| 1 | Medium | 4명 이하 판정 결과에 "적용되지 않습니다" 경고와 제109조 벌칙·제116조 과태료·노동청 진정이 **함께** 들어갔다. 이 사이클이 고치려던 오류와 같은 클래스다 | `SMALL_WORKPLACE_LEGAL`·`SMALL_WORKPLACE_STEPS`로 바꿨다. E18이 `format_assessment` 결과 전체를 검사한다 |
| 2 | Medium | "2026. 10. 8.부터 삭제된다"는 시제가 10-08 이후 거짓이 되고, 이 문장에는 앵커도 없었다 | 시제 중립 문장("…2026. 10. 8. 시행 시 삭제")으로 바꿨다 — 손볼 필요가 없다 |
| 3 | Medium | 법률상담 경로의 조회 통계가 `metadata.law_api`에 남지 않았다(설계 공백) | `process_consultation(law_api_stats=)` + pipeline 합산(E20) |
| 4 | Medium(배포) | `case_numbers.py`·`graph_precedents.json`이 untracked다 — 커밋에서 빠지면 판례 참조가 조용히 실패한다 | 커밋 시 untracked 0건 확인 항목 |
| 5 | Low-Med | `business_size` 정확일치 → "5인 미만" 우회 | `_is_small_workplace` 정규화(E18) |
| 6 | Low | 계산기 판례가 `secondhand`로 분류된다(enforce 전환 시 영향) | **수용** — CLAUDE.md가 enforce를 금지한다 |
| 7 | Low | `"3.3"` 부분문자열 과감지 | 원천징수 표현 정규식(E20) |
| 8 | Low | 지역변수 `results`가 바깥 변수를 가렸다 | `candidates`로 이름 변경 |
| 9 | Low | 앵커·별표 점검 예외 미처리, 루트가 None일 때 오경보 | try/except + "확인 불가" 구분 |
| 10 | Low | `조문가지번호="0"` 미정규화 | `lstrip("0")`(E20) |
| 11 | Low | 실행 위치 기준 상대경로, 미사용 import | `Path(__file__)` 기준 경로, import 정리 |
| 12 | Low | 변경 표기 안의 번호도 '렌더됨'으로 친다 | 처음에는 수용 → **CodeRabbit PR #98 지적으로 조치**: 자기 항목 줄 머리(`- 법원 사건번호`)가 있을 때만 렌더로 본다 |

## 4. 문서 갭 → 조치

CLAUDE.md에서 고친 곳:
- :135 조문 9+고시 4 → 23+5
- 부정어 창 → 같은 문장 120자 + 신규 부정어
- 판정기 서술 → 근거·절차까지 정정
- `law_api` 관측 범위 → 두 경로 합산

설계 문서에서 고친 곳:
- §3.2 업로드 대상 → 5건
- §13 → C17~C20, §13.1 후속 표

테스트에서 고친 곳:
- `test_effective_law.py` docstring → E1~E20
- `test_kin_accuracy` K6의 낡은 예외 조건 제거

수용한 것:
- 아카이브 inventory의 2022다291153 선고일(crawl 메타 2025.12.21)과 원문 기록(2025.08.14)의 불일치. 이 값은 crawl 원본에서 파생되며 §1.3에 기록돼 있다.

## 5. 검증

- 오프라인 전 스위트 통과: Python 14종 + `-m unittest legal_rule` 66 + eval offline 2종 + Node 45/45. `test_effective_law.py`는 30건이다.
- 판례 아카이브 `build → verify` 전체 통과(코드 줄 번호 갱신 반영).
- 그래프 재빌드 동등성(E16) 통과.

## 6. 판정

Match Rate 98.2%, 누락 0, Medium 위험은 모두 조치했다(4번은 커밋 체크리스트). → **Report 단계로 진행 가능.**

배포 전 확인할 것:
- untracked 파일 커밋
- `check_law_freshness.py --anchors` 실행(배포 전 + 2026-10-08 오전 — 근로기준법 시행 예정분)
