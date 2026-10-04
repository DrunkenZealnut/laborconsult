# kin-answer-accuracy — Gap Analysis (Check)

> 2026-10-03 · gap-detector 대조 + 후속 조치 반영
> 대상: Design `docs/02-design/features/kin-answer-accuracy.design.md` §0~§10 (§11 C1~C18은 승인된 변경)

## 요약

| 항목 | 결과 |
|---|---|
| **Match Rate** | **94%** (약 75항목: MATCH 67 · PARTIAL 6 · MISSING 2) → 후속 조치 후 **98%** |
| 설계 결정 D1~D6 | 6/6 구현 |
| 구현 중 변경 C1~C14 | 14/14 실제 구현 확인 (C8은 원답변 대조로 별도 확인) |
| 테스트 K1~K12 | 전부 존재 + K13(목 포맷) 추가, CI 등록 |

## MISSING → 조치

| # | 설계 | 조치 |
|---|---|---|
| M1 | §6.3 기준선을 `consultation-eval-baseline.md` "지식iN" 절에 기록 | ✅ 작성 — 기준선·개선 1·2차 표 |
| M2 | §3.1 폐기일 확정 + 테스트 고정 | ✅ 시행일로 확정(C17), K7 `test_k7_change_dates_are_pinned` |

## PARTIAL → 조치

| # | 위치 | 차이 | 조치 |
|---|---|---|---|
| P1 | `stale_rules.py` `daily_10days` | '1개월' 고정 없이 넓어짐 | 설계 §11 C15로 승인 기록(실측 표현 다양) |
| P2 | `stale_rules._EXCLUDE_SOURCES` | `is_counsel_source` 대신 사본 | C16 + K7 동일성 테스트 |
| P3 | `pipeline.py` 규칙 블록 | try 하나로 전체 감쌈 → 한 블록 예외가 전부 제거 | ✅ `build_rule_facts()` 블록별 격리(C18) + K4 테스트 |
| P4 | `pipeline.py` 6-1b | 사유마다 예산 새로 잡음 | ✅ `_rel_deadline` 하나로 공유 |
| P5 | `rule_facts.dismissal_notice` | `topic AND "해고"`로 좁힘 | 유지 — 해고·징계 주제의 징계 상담에 해고예고 블록이 붙지 않게 한 의도적 축소 |
| P6 | K3·K12 | 합성 문장 검사, 프롬프트 문구 미검증 | 수용 — K3는 기존 60건 금지 문구 **전량**에 단정형·무관형 판정을 걸고, 실제 문맥 검증은 10-02 원답변 12/12 검출로 대신했다 |

## 정합성 위험 → 조치

| # | 위험 | 조치 |
|---|---|---|
| — | pipeline 변수 정의 경로 | 문제 없음(전부 함수 최상위 무조건 초기화, 이른 return은 사용 전 이탈) |
| R1 | monitor에서도 `done` 전 임베딩 동기 호출, ping 없음 | ✅ 호출 전 ping. 최대 10초·fail-open은 수용 |
| R2 | `[구 기준 주의]` 주석이 관련성 임베딩에 섞임 | ✅ `classify_paths`에서 주석 줄 제거 + K10 테스트 |
| R3 | 법령 API·NLRC 블록 번호가 `secondhand`로 기록 | docstring을 실제 동작에 맞춤(monitor라 기록만) |
| R4 | `eval_retrieval`·`eval_corpus_mix`가 필터를 거쳐 기준선 이동 | 수용 — 재현은 `STALE_FILTER=off`. Report에 명시 |
| R5 | `fixture_path` 절대경로 게시 | 기존 문제(이번 변경 아님) — 범위 밖 |
| R6 | "일용직" 키워드만으로 실업급여 블록 | 수용 — 상한 2블록 안의 잡음 |

## 설계가 못 잡은 것 (Match Rate 밖)

Do 단계 Live 비교에서 **설계에 없던 기존 결함 3건**이 드러났다. 셋 다 이번 사이클에서 고쳤다.
1. `legal_api` 조문 포맷이 목(目)을 버려 현행 제40조가 구기준으로 채워짐(C12)
2. `_citation_source_hits()`가 `case_no`를 버려 T31 메타 경로가 죽어 있었음(C9)
3. `fetch_official_rules.write_doc` KeyError로 조문 수집 불능(C10)

설계 대조는 "설계대로 만들었는가"만 답한다. 1번은 실제 답변을 돌려 보지 않았으면 발견되지 않았다.

## 판정

Match Rate ≥ 90% → **Report 단계로 진행 가능.** 단 Plan 목표(사람 재채점 평균 ≥ 88)는 아직 측정 전이다.
