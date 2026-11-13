# source-pack-held-articles — 완료 보고서

> 상위 사이클: source-pack-refresh(아카이브 `docs/archive/2026-11/source-pack-refresh/`)
> 문서: Plan `docs/archive/2026-11/source-pack-held-articles/source-pack-held-articles.plan.md` · Design `docs/archive/2026-11/source-pack-held-articles/source-pack-held-articles.design.md` · Analysis `docs/archive/2026-11/source-pack-held-articles/source-pack-held-articles.analysis.md`
> 기간: 2026-11-13(하루) · PR #170(`3c75e2e`)·#171(`5347ec7`)

## Executive Summary

### 1.1 개요

| 항목 | 값 |
|---|---|
| 기능 | 보류 3조문(고용보험법 시행령 제60조의2·제104조의8·제104조의15) 정정 적재 + G1 `suspect_glyph` |
| 시작·완료 | 2026-11-13 · 2026-11-13 |
| 단계 | Plan → P1 원문 조사 → Design → Do(PR #170) → Check 92.2% → Act-1(PR #171) 100% |

### 1.2 결과

| 지표 | 값 |
|---|---|
| Match Rate | 92.2% → **100%**(Act-1) |
| 적재 | `qpack_20261113_` **12벡터**(정정 3건) · laborlaw-v2 56,100 → **56,112** |
| BM25 | 107,186 → **107,198문서** · CI Linux 피크 RSS 490MB(상한 550) |
| 테스트 | `test_source_pack_refresh.py` 10 → **21건**(H1~H8 등) · 변이 검출 Do 6/6, Act 6/8(남은 2는 결과 무영향) |
| 변경 | `source_pack_refresh.py`·테스트·대상 파일·fixture 3·원장 1·문서 4 |
| 비용 | 임베딩 8,686토큰 |

### 1.3 Value Delivered

| 관점 | 내용 |
|---|---|
| **Problem** | 세 조문은 근로자·예술인·노무제공자 경력을 합산하는 실업급여 수급요건 계산식인데, 법제처 텍스트에서 `≤`가 `?`로 빠져 있어 지난 사이클에 적재하지 못했다. 같은 손실을 자동으로 찾는 장치도 없었다. |
| **Solution** | 법제처 조문 이미지 판독과 법제처 화면의 이미지 수식(LaTeX `\leq`)으로 기호를 확정하고, 근거 해시를 자동 대조하는 정정 경로(`corrections`)로 `?` → `≤` 한 글자만 바꿔 적재했다. 남은 의심 문자는 G1 관문이 막는다. |
| **Function UX Effect** | 다중 직종 수급요건 질의 2건에서 새 조문 청크가 Dense 검색 **1위**(0.587·0.593)로 올라와, 답변이 시행령 계산식을 정확한 부등호로 인용할 수 있다. |
| **Core Value** | 원문에 없는 문자를 추측하지 않았다. 치환은 법제처 자신의 두 근거가 일치할 때만, 한 글자만, 기록을 남기며 이뤄지고 근거가 바뀌면 중단한다(fail-closed). |

## 2. 진행 경과

| 단계 | 결과 |
|---|---|
| Plan | 원문 후보 경로 (a)~(e), 처리 방식 A/B/C, G1을 범위로 |
| P1 원문 조사 | (a) XML 조문 이미지 판독 + (b) law.go.kr 화면 이미지 `alt` LaTeX가 일치 → `?` = `≤`, `－`는 빼기로 맞다(Plan 가정 정정). JSON 응답도 같은 손실, HTML 응답은 껍데기. (c) PDF·(d) 관보는 불필요 |
| Design | D2 방식 B(치환 + 원장 기록) · D3 문맥 정확 1회 · D4 근거 자동 대조 · D5 G1 관문 · D6 메타데이터 키 불변 |
| Do | 코드·테스트 → fetch(현 회선 119.66.172.82에서 법제처 인증 통과) → prepare → 검토 판정 → 사용자 승인 후 upload → 원장 → BM25 재빌드 → PR #170 머지 |
| Check | gap-detector 45항목 ✅38 ⚠️7 ❌0 = 92.2%. High 1(G1 관문이 `prepare_rows.json` 부재 시 꺼짐) |
| Act-1 | 결함 7건 수정, PR #171 머지 |

## 3. 구현 요점

- **정정(`corrections`)**: 대상 파일에 `find`·`replace`·`image_flseq`·`image_sha256`·`screen_url`·`latex_token`·`reviewed_by`. prepare는 ① 이미지·화면 HTML 해시 재대조 ② 그 flSeq `<img>`의 `alt`에 `latex_token` ③ `find`가 본문에 정확히 1회 ④ 의심 문자 한 글자 → 허용 기호(`CORRECTION_GLYPHS`) ⑤ 미사용 정정 0을 모두 통과해야 치환한다.
- **G1**: 상자 표 줄의 `?`·U+FFFD를 **적재할 본문에서 직접** 센다. 남은 조문의 `적재` 판정은 `의심 문자 확인:` 사유가 없으면 upload가 거절한다.
- **기록**: 청크 머리글 `정정: 법제처 텍스트 계산식의 '?'를 '≤'로 바로잡음 — 법제처 조문 이미지·화면 수식 대조`, 원장 `documents["ei-decree"].corrections` 3건. 메타데이터는 기존 배치와 같은 19키.

## 4. 검증

| 항목 | 결과 |
|---|---|
| upload verify · `source_pack_ledger.py verify` · audit | 12/12 · 12/12 · 누락 0 |
| 원장 형식(`test_committed_vector_ledgers`) | 통과(원장 4개) |
| CI offline-tests | PR #170·#171 모두 통과 |
| Act-1 회귀 | 실제 20261113 산출물로 prepare 재실행 → 벡터 해시 동일·검토 파일 불변 |
| R7 검색 | 질의 2건 모두 새 청크 1위 |
| R8 집계 | 10-09 자료팩 의심 문자: 별표 3·서식/별지 55섹션(374자), **조문 0** |

## 5. 교훈

1. **가정한 손실 범위를 원문으로 먼저 좁힐 것.** Plan은 `－`도 부등호일 수 있다고 봤지만 원문 이미지로 보니 빠진 것은 `≤` 하나였다. 조사 전에 설계했다면 두 기호를 고치는 경로를 만들었을 것이다.
2. **법제처 화면 HTML에는 수식 이미지의 LaTeX 원문이 `alt`로 실려 있다.** 사람 판독을 기계 대조로 보강할 수 있는 공식 근거다.
3. **관문은 판정 대상 데이터에서 직접 계산할 것.** 부수 파일(`prepare_rows.json`)에 기대면 파일이 없을 때 조용히 열린다(Check High).
4. **HTML 해시는 바이트로.** `read_text`가 CRLF를 LF로 바꿔 fetch 때 해시와 어긋났다 — 합성 테스트(LF)로는 못 잡고 실데이터 재실행에서 드러났다.

## 6. 남은 것

| 항목 | 비고 |
|---|---|
| 별표 3건 의심 문자 정정 | 국민내일배움카드 운영규정 별표 1·6(원격훈련 요건 37자), 뇌심혈관 고시 별표 1 — 같은 `corrections` 경로로 가능 |
| 서식·별지 55섹션 | 체크박스 등 손실로 보임, 우선순위 낮음 |
| G4·G5(source-pack-refresh 후속) | 이번 범위 밖 |
| 아카이브 | `/pdca archive source-pack-held-articles` |
