# colloquial-legal-mapping Gap 분석 (Check)

> 분석일: 2026-08-20 | 대상: Design(`docs/02-design/features/colloquial-legal-mapping.design.md`) ↔ 구현
> 방법: gap-detector(설계 대조) + code-analyzer(설계 무관 경로 리뷰) 병렬 — CLAUDE.md 관례
> ("Match Rate 90%+여도 변경이 닿는 경로를 설계와 무관하게 훑는 리뷰를 한 번 더")

## 1. 종합 판정

| 구분 | 값 |
|------|-----|
| **Match Rate (gap-detector)** | **91%** (채점 64항목: MATCH 52 · 의도적 이탈 4 · PARTIAL 4 · MISSING 4) |
| 코어 불변식 (C2 I-1~I-8, 킬스위치, 승격 순서, promoted 마커) | 18/18 충족 |
| **경로 리뷰 (code-analyzer)** | **P0 1건 · P1 3건 · P2 4건** — Match Rate가 원리적으로 못 잡는 결함 |
| 배포 판정 | **조건부 — P0-1·P1-2·P1-3 수정 전 머지 불가.** P1-4는 완화 조치, P2는 이번 사이클 내 처리 권장 |

Match Rate ≥ 90%이지만, 설계 자체의 서술 오류 2건(P1-2 "병기" 미구현, P1-3 "발동 조건 불변" 반증)이 경로 리뷰에서 드러났다 — textbook-corpus-embedding 사이클(100% Match Rate 후 High 2건)과 동일한 패턴의 재현이다.

## 2. 머지 차단 결함 (경로 리뷰)

### P0-1. `app/core/colloquial_map.py` git 미추적 — 배포 시 전 엔드포인트 500
`pipeline.py:19`가 모듈 최상단에서 import하므로 이 파일 없이 push하면 `api/index.py` import 체인이 죽는다. CLAUDE.md가 명시한 실패 모드 그대로("untracked files cause Vercel import errors"). `data/eval_colloquial_queries.json`·`eval_colloquial.py`도 미추적.
**조치**: 커밋 시 신규 4파일 + 문서를 반드시 함께 add. (코드 수정 아님 — 커밋 체크리스트 항목)

### P1-2. 사전 발동 시 사용자 원문이 검색 쿼리에서 소실
Design §2.2와 모듈 docstring은 "원문 병기"를 명시하지만, `_merge_search_queries`(pipeline.py:141-164)의 `fallback`은 **merged가 비었을 때만** 붙는다. 사전이 매칭되면 `prec_queries`가 차므로 원문(`query[:80]`)이 탈락 — 검색이 일반명사 나열("부당해고 해고 통보")만으로 돌아 상황 특정성을 잃는다. 사전 **미매칭일 때만** 원문이 검색되는, 의도와 정반대 구조.
**파급**: `eval_colloquial.py`의 폴백 측정(사전+원문)이 프로덕션(사전만)과 달라 — 보고된 폴백 도달 50%는 프로덕션이 재현하지 못하는 수치(P2-8).
**조치**: `_merge_search_queries`에 원문 병기 경로 추가(합성 경로 한정) + `test_merge_search_queries` 갱신.

### P1-3. 승격 연쇄가 유일한 법률근거를 축출하고 하위 순위로 되메움
Design §3.2 "앞 승격이 뒤 발동 조건을 바꾸지 않는다"는 **반증됨** — 대상 집합은 배타적이지만 **victim 집합이 배타적이 아니다**. `_pick_swap_victim`의 폴백(`candidates[-1]`)이 selected 내 유일한 precedent를 지우면, legal 승격의 발동 조건이 새로 생겨 더 낮은 순위의 판례로 되메운다. SIMPLE(top_n=3)에서 rerank 2위 판례 → 4~5위 판례 강등 + counsel 소실 + 3슬롯 중 2슬롯이 승격분. 총량이 불변이라 어떤 메트릭에도 안 잡힌다. T24-b의 fixture는 상위가 전부 qa(중복 출처)라 이 조합이 비어 있다.
**조치**: victim 보호 확장 — 보호 클래스(textbook·legal) 중 selected 내 **유일** 멤버는 폴백에서도 victim 금지(I-4의 확장). T24에 "전원 단일 출처 + 두 승격 동시" 케이스 추가.

### P1-4. 합성 주입이 2벤더 동시 장애 상황에 무타임아웃 검색 스택을 연다
`analysis is None`은 정의상 Claude·OpenAI가 둘 다 실패한 상태인데, 신규 개방된 블록의 OpenAI 임베딩 호출(`rag.py`)에 타임아웃이 없다(SDK 기본 600s×2회). `status` 이벤트(1585) 이후 `sources`까지 중간 yield가 없어, OpenAI가 행(hang)으로 열화되면 프론트 idle 60초를 넘겨 abort — 기존 "빠른 열화 답변"이 "답변 0자"로 뒤집힐 수 있다.
**조치**: ① 임베딩 호출에 국소 타임아웃(`with_options(timeout=10)`, 답변 LLM 경로 무영향), ② 합성 경로는 complexity를 SIMPLE로 강제(decompose·Self-RAG·wider 차단 — 어차피 해당 벤더가 죽어 있어 실패 재시도 낭비).

## 3. P2 (이번 사이클 내 처리 권장)

| ID | 내용 | 조치 |
|----|------|------|
| P2-5 | 정규식 오탐 5종 — "기계에 손가락이 **잘렸**"(산재→해고 판례), "**출장 나가라**고"(전보→해고), "**실업급여 못 받**"(고용보험→임금체불), "임신 중 외근 **나가**라"(배치→해고), "연금이 **안 들**어왔다"(미입금→미가입) | 억제자(suppressor) 방식 도입 — abuse_guard `_BENIGN_ACTOR`와 동일 설계. 음성 케이스 5건 추가 |
| P2-6 | 합성 경로가 로그·metadata 어디에도 표식 없음 — "의도분석 전멸 대화"를 사후 식별 불가 | 합성 객체에 `intent_provider="synthetic"` 세팅(기존 `_llm_meta` 조건이 자동 수용) + 미매칭도 로그 |
| P2-7 | `map_colloquial_terms`에 NFC 정규화 부재 — 비웹 호출부(CLI·fixture)에서 NFD 입력 시 조용한 0매칭 (NFD로 474벡터 잃은 전력과 동일 클래스) | 진입부 `unicodedata.normalize("NFC", text)` 1줄 |
| P2-8 | eval의 폴백 쿼리 구성이 프로덕션과 불일치 | P1-2 수정으로 자동 해소 — 수정 후 기준선 재측정 |

## 4. gap-detector MISSING/PARTIAL (Med 4 · Low 4)

| ID | 심각도 | 내용 | 조치 |
|----|:---:|------|------|
| G-1·G-2 | Med | Design §4.1 프롬프트 예시 중 "갈구다"(괴롭힘)·"공상 처리"(산재) 2줄 미추가 — Plan V3이 지목한 바로 그 두 계열 | prompts.py rule 16에 2줄 추가 |
| G-3 | Med | "사전이 정상 경로에서 미발동" 회귀 테스트 부재 — 사전이 정상 경로로 옮겨져도 CI가 조용함 | 소스 토큰 검사 방식 회귀 추가 |
| G-4 | Med | Design §6 "uses_textbook 폴백 동일 적용을 T24c에서 확인" — T24-c는 건수만 단언 | T24-c에 단언 1줄 추가 |
| G-5 | Low | 사전 양성 케이스 4건 부재(구조조정·갑질·블랙리스트·연차) — 패턴 오타가 조용히 통과 가능 | 양성 4건 추가 |
| G-6 | Low | T24에 랭크 창 밖 무승격 미러 케이스 부재 | 1케이스 추가 |
| G-7·G-8 | Low | Design "~30건" 문구 vs 실제 22패턴 / 주석 2건 누락 | 문서·주석 정정 |

**의도적 이탈(수용, Design 반영 필요)**: 합성 `AnalysisResult` 주입(원안 "가드만 완화"보다 우월 — 무방비 참조를 구조적으로 해소), `_ensure_source_presence` 5인자(I-7/I-8 성립에 필요), fixture 18건(초과), eval 3층 구조. **부수효과 문서화**: 폴백에서 NLRC·GraphRAG도 활성화됨(Design §2.2 미기록).

## 5. 문서 정합 (Report 전 처리)

- Design §3.1 불변식 번호가 코드·선행 사이클과 충돌(Design I-5=최소크기 vs 코드 I-5=승격→가드 순서) — Design을 선행 번호 체계(I-1~I-6 + 신규 I-7·I-8)로 재정렬.
- **CLAUDE.md 미갱신** — 법률근거 승격(`LEGAL_PROMOTE`)·구어 사전이 RAG/가드 서술에 없음. Match Rate가 못 잡는 설계 공백(산출물 목록 자체에 누락).
- `eval_colloquial.py` 기준선 주석이 "구현 후 측정치로 갱신할 것" 상태 — P1-2 수정 후 재측정치로 갱신.

## 6. 경로 리뷰에서 "문제없음" 확인된 것 (재검증 불요)

합성 analysis 하류 12지점(법령 API·스코프 게이트·계산 라우팅·상담 분기·지식 모듈·missing_info·카테고리·저장 metadata·세션) 전부 기존 동작과 동일 / `_pick_swap_victim` int|None 호출부 1곳 처리 확인 / promoted 마커는 `format_pinecone_hits`가 고정 키 dict를 새로 만들어 하류(sources·citation·Supabase) 유출 없음 / 승격 엣지(빈 창·소형 pool·후보 배타성·원본 비변이) / 저작권 가드 무접촉(승격→G4/G4-T 순서 불변, legal 대상에 textbook 없음) / prompts 변경의 스키마·format 충돌 없음 / pydantic 합성 인스턴스 안전성.

## 7. 다음 단계

1. **iterate (Act)**: P1-2·P1-3·P1-4 코드 수정 + P2 4건 + G-1~G-6 → 테스트·eval 재실행(기준선 갱신)
2. 문서 정합(§5) 반영 → Report
3. 커밋 시 P0-1 체크리스트(신규 4파일 add 확인)

---

## 8. Act 결과 (2026-08-20, 같은 날 처리)

**전 항목 해소.** 재산정 Match Rate: **98%** (64항목 중 MISSING 4 → MATCH, PARTIAL 4 → MATCH, 의도적 이탈 4건은 Design에 역반영해 정합화. 잔여 감점: 사전 "~30건" 목표 대비 22패턴 — 고신뢰 원칙 우선의 의도적 미달로 Design 문구를 실측값으로 정정).

| 결함 | 조치 | 검증 |
|------|------|------|
| P1-2 원문 소실 | `_merge_search_queries(always_fallback=True)` — 합성 경로 전용, max_total 안쪽 보장 | `test_merge_search_queries` 3단언 추가, eval [3a]가 프로덕션과 동일 구성으로 50% 달성 |
| P1-3 승격 강등 순환 | **I-9 신설** — 다양성 클래스(해설서·법률근거) 마지막 1건은 victim 금지(`_diversity_class_of`, 두 승격 대상 집합과 동일 정의 공유) | T24-b7/b7b/b7c(유일 판례 보존·되메움 없음), T24-b8(자연 유입 해설서 역방향), T23 무회귀, `eval_retrieval` 75.0% 유지 |
| P1-4 무타임아웃 개방 | 임베딩 `with_options(timeout=10, max_retries=0)`(요청 단위 — 타 OpenAI 경로 무영향) + 합성 경로 SIMPLE 강제(죽은 벤더 재호출 차단) | import 스모크·전 스위트 통과 |
| P2-5 정규식 오탐 | 억제자 구조 도입(3-튜플): 신체 절단(`잘렸`≠해고)·이동 지시(`나가라`≠해고 통보)·미입금(`안 들`≠미가입) + '급여' 고정폭 lookbehind(실업·구직·휴직·요양 제외 — 복합 질의의 임금체불 매핑 보존) + 블랙리스트 죽은 분기 제거 | 음성 6건·억제 3건·복합 1건 회귀 추가 |
| P2-6 계측 부재 | 합성 객체 `intent_provider="synthetic"`(기존 `_llm_meta`가 자동 저장) + 미매칭 로그 | 코드 확인(543행 조건) |
| P2-7 NFC 부재 | `map_colloquial_terms` 진입부 정규화 | — |
| P2-8 eval 불일치 | P1-2 수정으로 자동 해소 — [3a]와 파이프라인 구성 일치 | 기준선 주석 갱신 |
| G-1~G-6 | 프롬프트 예시 2줄(갈구다·공상 처리 — LLM 키워드에 실반영 확인), 배선 회귀(`test_colloquial_fallback_only_wiring`), T24-c2 `uses_textbook`, 사전 양성 24건, T24-a9 창 밖 미러 | 전 스위트 통과 |
| §5 문서 정합 | Design(합성 주입·부수 활성화·I-9·번호 재정렬·§3.2 반증 정정·3층 eval)·CLAUDE.md(승격 2종·구어 3층 규범 신설)·eval 기준선 주석 | — |

**최종 측정** (Act 후): [1] LLM 변환 18/18 · [2] 사전 18/18 · [3] 폴백 50%(0%→) · 정상 72~83% 준결정 밴드(50%→) · `eval_retrieval` 75.0% 무회귀 · 오프라인 스위트 5종 전체 통과(T24 24케이스).

**잔여 (Report에 기록)**: 정상 경로 미도달 고정 2건(c15 4대보험·c16 근로자성)은 법률 코퍼스의 주제 커버리지 공백 — 검색 로직이 아니라 코퍼스 확장(행정해석·판례 수집) 사이클 후보. P0-1은 커밋 시 체크리스트로 이관.
