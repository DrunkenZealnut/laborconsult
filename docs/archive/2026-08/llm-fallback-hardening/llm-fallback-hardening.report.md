# Report: LLM 폴백 경화 (llm-fallback-hardening)

> **Feature**: LLM 폴백 경화 — 빈 응답·절단·전환 지연·교차벤더 실패 시나리오 차단
> **PDCA Cycle**: Plan(v0.2) → Design(v0.1) → Do → Check(91%→99%) → Report
> **Period**: 2026-08-06 ~ 2026-08-06 (PDCA 1일, 구현·검증 병렬)
> **Match Rate**: 99% (Act-1 반영, 배포 의존 항목 1건 제외)
> **Status**: 준비 완료, 배포 대기

---

## Executive Summary

### 1.1 4관점 가치 전달

| 관점 | 내용 |
|------|------|
| **Problem** | 벤더 1곳이 LLM 호출 8지점 중 6곳을 차지하고, 유일한 폴백 체인(답변 생성)도 빈 응답·중도 절단·지연을 성공으로 처리해 "조용한 실패"가 사용자에게 그럴듯한 저품질 답변으로 전달됨. Anthropic 장애 시 계산기·스코프 게이트·인용 교정 동시 실패 → 숫자 없는 일반론이 정상처럼 노출. 폴백이 죽어도 관측 불가능(계측 부재) → 같은 장애를 반복 |
| **Solution** | 5가지 경화: ① 빈 응답·절단을 실패로 승격·명시 고지 + metadata 기록 + 게시판 제외 ② 폴백 전환 시 하트비트로 프론트 idle 타이머 리셋(무이벤트 구간 ≤25초) ③ 답변·교정 경로 재시도 제거 + 벤더 전환으로 가속 ④ 의도분석 교차벤더 폴백(OpenAI gpt-4.1) → Anthropic 단일 장애점 해소 ⑤ 폴백 계측(provider/fallback/빈응답/절단) 자동 기록 + 오프라인 회귀 테스트(API 키 불요) |
| **Function/UX Effect** | 정상 경로 무회귀: TTFT ~20초 유지(지연 증가 없음). 장애 시 사용자는 빈 답변 대신 폴백 벤더 답변 or 명시적 안내 수신. Anthropic 장애 중에도 임금 계산 결과 유지(V1 검증: ANTHROPIC_API_KEY 무효화 → 퇴직금 10,922,155원 계산 정상). 절단 대화는 게시판 노출 제외로 사용자 신뢰 보호 |
| **Core Value** | 노동상담은 금액·기간 오류 시 실害 발생 도메인. 장애가 오류 아닌 "그럴듯한 저품질 답변"으로 새는 경로 차단 → 가용성이 아닌 **답변 신뢰성** 수호. Gemini 404 발견·복구로 문서·코드가 약속했던 3단 폴백을 실질적으로 회복(그전까지는 2단만 동작) |

---

## 1. Plan 요약

### 1.1 계획 문서

**문서**: `docs/01-plan/features/llm-fallback-hardening.plan.md` (v0.2)
**일시**: 2026-08-06
**기본 원칙**: "조용히 나빠지는 것"은 허용, "조용히 틀리는 것"은 차단

### 1.2 LLM 호출 8지점 실측

| ID | 호출부 | 모델 | 타임아웃 | 폴백 | 현행 결함 |
|---|--------|------|---------|------|---------|
| L1 | 답변 1순위 | Claude-5 | 30s×3 ≈ 91s | → L2 | 빈응답·절단 미처리 |
| L2 | 답변 2순위 | OpenAI o3 | SDK 600s | → L3 | 무이벤트 초과 |
| L3 | 답변 3순위 | Gemini-2.5-pro | **무제한** | 없음 | **404 사망** |
| L4 | 의도분석 | Claude-5 | 12s×3 | L5(동일 벤더) | **Anthropic 장애 = 계산기 미실행** |
| L5 | 레거시 추출 | Claude-5 | 10s×3 | 없음 | 의존 L4 |
| L6 | 쿼리분해 | Haiku | 3s×3 | 규칙 축소 | SDK 재시도 잔존 |
| L7 | 인용 교정 | Haiku→Gemini→o3 | 혼재 | 3단 | 타임아웃 부정합 |
| L8 | 미세 퇴고 | Haiku | 2s | 없음 | 교정 기초 약함 |

**벤더 집중도**: 8곳 중 6곳 Anthropic 전용(L1·L4·L5·L6·L7-1순위·L8)

### 1.3 기능 요구사항 13종

**P0 조용한 실패 제거(FR-01~04)** — 4건
- FR-01: 빈 응답(실질 0자) 실패 승격
- FR-02: 절단 처리(고지+metadata+게시판 제외)
- FR-03: 무이벤트 구간 제거(하트비트 + 재시도 축소)
- FR-04: 타임아웃 단일 출처화

**P1 벤더 단일 장애점 해소(FR-05~08)** — 4건
- FR-05: 의도분석 교차벤더 폴백(OpenAI)
- FR-06: 스코프 게이트 생존 검증
- FR-07: 교정 타임아웃 정합(동적+단계 예산)
- FR-08: 죽은 3순위 복구(Gemini-pro-latest로 교체) **[High 승격]**

**P2 관측·검증(FR-10~13)** — 4건 + FR-09(1건)
- FR-10: 폴백 계측 + 구조화 로그
- FR-11: 오프라인 회귀 테스트(API 키 불요)
- FR-12: 장애 주입 양성 검증 절차(V1~V4)
- FR-13: 운영 문서 정합

---

## 2. Design 요약

### 2.1 설계 문서

**문서**: `docs/02-design/features/llm-fallback-hardening.design.md` (v0.1)
**핵심 발견**: **설계 중 3순위 폴백(Gemini)이 404로 이미 죽어있음을 실측 확인** → FR-08 High 승격

### 2.2 10가지 설계 결정 (D1~D10)

| # | 결정 | 확정 값 | 근거 |
|---|------|--------|------|
| **D1** | 3순위 Gemini 존치 | `gemini-pro-latest` 교체 | 레거시 SDK 호환 유지, 2→3단 회복 |
| **D2** | SDK 마이그레이션 | 미시행(`google-generativeai` 유지) | 3순위 위해 의존성 교체는 과투자 |
| **D3** | 답변 경로 재시도 | `max_retries=0` | 벤더 전환이 동일 벤더 재시도보다 빠름 |
| **D4** | 전환 하트비트 | `(provider, "")` 2-튜플 | 기존 호출 규약 보존 |
| **D5** | 의도분석 폴백 모델 | `gpt-4.1`(비추론) | reasoning 토큰 한도 잠식 회피 |
| **D6** | 교정 타임아웃 | 입력 길이 비례 동적 + 단계 예산 | 고정값은 1k~8k 편차 커버 불가 |
| **D7** | 절단 면책 고지 | **유지**(제거하지 않음) | 법적 필요, 절단 고지는 별도 부착 |
| **D8** | 절단 인용 교정 | **수행** | 잘린 답변에도 환각 판례 남음 |
| **D9** | 계측 저장소 | `qa_conversations.metadata` 재사용 | 스키마 마이그레이션 0 |
| **D10** | 게시판 제외 방식 | `board_posts` 미적용 | metadata 컬럼 부재로 PostgREST 400 → 게시글 소실 위험 |

### 2.3 타임아웃·재시도 예산표

**최악 경로 누적** (전 벤더 실패 시나리오)

```
이해   L4(12s) + L4b(10s) + L5(10s)        =  32s
검색   RAG·법령 API·병렬 처리              ≈  30s
답변   L1(25s) + L2(25s) + L3(25s)         =  75s
교정   L7 단계 예산(60s) + L8(20s)          =  80s
저장   Supabase + 첨부(하트비트로 보호)     ≈  20s
───────────────────────────────────────────────────
합계                                        ≈ 237s  < 300s ✅
무이벤트 최대 구간 = 답변 벤더 1회 25s      < 60s  ✅
```

> 이 예산표는 **설계 시점** 값이다. 교정 단계 예산(60s)은 이후 CodeRabbit 리뷰(#9, §5.1)를 거쳐 **45초로 하향 클램프**됐다 — 교정 중에는 하트비트를 낼 수 없어 이 값이 곧 무이벤트 구간이 되므로, idle 60초와 같은 값은 마진이 없다고 판단했다. 최종 코드값은 §3.2 참고.

---

## 3. 구현 결과 (Do)

### 3.1 신설 파일

#### `app/core/llm_fallback.py` (99줄)

교차벤더 어댑터 — Anthropic tool_use 규약을 OpenAI function calling으로 번역

```python
# 핵심 3가지 내보내기:
- flatten_content(content) → str
  * 멀티모달 content 블록을 평문으로 변환
  * pipeline._flatten_content와 의도적 분기
    (이미지 탈락 안내 문구 없음 — 의도분석 텍스트 오염 방지)

- anthropic_tool_to_openai(tool) → dict
  * Anthropic tool → OpenAI function
  * JSON Schema(input_schema) 무수정 재사용(스키마 드리프트 방지)

- call_openai_tool(...) → dict
  * OpenAI tool_choice 강제 호출
  * max_retries=0 + 타임아웃 명시
  * tool_call 미반환 시 RuntimeError 전파(폴백으로 강등)
```

#### `test_llm_fallback.py` (20건)

API 키 불요 오프라인 회귀 테스트

| # | 테스트 | 목표 | 위치 |
|---|--------|------|------|
| T1 | 빈 응답 폴백 | 0청크 정상종료 → 다음 제공자 | l.65 |
| T2 | 공백 오염 방지 | 공백만 → 프론트 미전송 | l.78 |
| T3 | 전환 하트비트 | 첫 청크 전 실패 → `("OpenAI","")` | l.90 |
| T4 | 절단 정직성 | 실질 청크 후 실패 → truncated=True | l.103 |
| T5 | 전체 실패 | 모든 제공자 실패 → RuntimeError | l.116 |
| T6 | 전체 빈응답 | 모든 제공자 0청크 → RuntimeError | l.130 |
| T7 | 게시판 제외 | truncated 메타 → `_drop_flagged` 제외 | l.174 |
| T8 | 스키마 변환 | `anthropic_tool_to_openai` | l.260 |
| 추가 12건 | 제공자 순서·LLM 메타·절단 통합·교차벤더 폴백 3종·고지 정규화·교정 가드·타임아웃·예산 소진 등 | Do·Act-1·CodeRabbit 단계별 보강 | 각처 |

### 3.2 핵심 수정 파일

#### `app/config.py` (+35줄)

타임아웃·재시도 상수 단일 출처화

```python
# 답변 경로
CONNECT_TIMEOUT = 5.0
ANSWER_READ_TIMEOUT = 20.0          # 설계에서 확정(현행 vs 30초)
ANSWER_MAX_RETRIES = 0              # max 1로 클램프(재시도 > 벤더 전환)
ANSWER_MAX_TOKENS = 8192

# 의도분석
INTENT_TIMEOUT = 12.0
INTENT_FALLBACK_ENABLED = true      # 즉시 완화용
INTENT_FALLBACK_MODEL = "gpt-4.1"   # 비추론 모델
INTENT_FALLBACK_MAX_TOKENS = 4096

# 인용 교정
CITATION_STAGE_BUDGET = 45.0        # 단계 전체 예산 상한
                                     # (Act-1 시점 60초 → CodeRabbit #9로 45초 클램프.
                                     #  교정 중엔 하트비트를 못 내 이 값이 곧 무이벤트
                                     #  구간이라 idle 60초보다 확실히 낮아야 한다)

# ⚠️ 변경 시 design §3.4 예산표를 함께 갱신할 것
```

#### `app/core/pipeline.py` (+120줄)

`AnswerOutcome` + `_stream_answer` 상태 머신 재구성

```python
@dataclass
class AnswerOutcome:
    provider: str | None = None
    attempts: list[str] = field(default_factory=list)    # 시도 순서
    empty_providers: list[str] = field(default_factory=list)  # 빈응답
    truncated: bool = False                              # 절단 플래그
    error: str | None = None

def _stream_answer(messages, system, config, outcome=None):
    """Claude → OpenAI → Gemini 폴백 스트리밍
    
    변경점:
    1. started 불리언 폐기 → chars(실질 문자 수) 기반 판정
    2. pending 버퍼 — 공백 청크 폐기(오염 제거)
    3. yield (provider, "") — 전환 하트비트
    4. empty_providers 기록 — FR-01
    5. truncated 플래그 — FR-02
    """
```

호출부: 절단 고지 + 계측 + ping

```python
if outcome.truncated:
    yield {"type": "chunk", "text": "⚠️ 답변 생성이 중간에 중단되었습니다..."}
    conv_metadata["truncated"] = True           # 게시판 제외
    
conv_metadata["llm"] = _llm_meta(outcome)       # 계측
logger.info("llm_outcome provider=%s attempts=%s empty=%s truncated=%s", ...)
```

#### `app/core/analyzer.py` (+60줄)

벤더 중립 후처리 + OpenAI 폴백 분기

```python
def _build_analysis_result(inp: dict) -> AnalysisResult:
    """tool 입력 dict → AnalysisResult. 벤더 무관."""
    # 기존 155-197 로직 추출 (info_keys 필터 → 날짜보정 → 범위검증)

def analyze_intent(...) -> AnalysisResult:
    try:
        inp = _analyze_claude(messages, system_prompt, config)
    except Exception as e:
        if not INTENT_FALLBACK_ENABLED:
            raise
        logger.warning("Claude 실패 → OpenAI 폴백: %s", e)
        inp = _analyze_openai(messages, system_prompt, config)  # raise 전파
    return _build_analysis_result(inp) if inp else AnalysisResult(...)
```

#### `app/core/citation_validator.py` (+40줄)

동적 타임아웃 + 단계 예산 + `max_retries=0` 배선

```python
def _rewrite_timeout(text_len: int) -> float:
    """실측: 1,960자/7.7초 → 250자/초 × 1.5(안전계수) → [12,40]초 클램프"""
    return min(40.0, max(12.0, text_len / 165))

# 단계 예산 상한
deadline = deadline or (time.monotonic() + CITATION_STAGE_BUDGET)
remaining = deadline - time.monotonic()
if remaining < 5:
    logger.warning("예산 소진")
    break
result = vendor(prompt, timeout=min(per_call, remaining))

# GAP-1·2 수정: max_retries=0 배선
anthropic_client.with_options(timeout=timeout, max_retries=0).messages.create(...)
```

#### `api/index.py` (+25줄)

절단 대화 게시판 제외

```python
_PUBLIC_EXCLUDE_KEYS = ("guard_flag", "truncated")

def _apply_guard_filter(query, apply_filter=True):
    """⚠️ qa_conversations 전용 — board_posts는 metadata 컬럼 부재"""
    for key in _PUBLIC_EXCLUDE_KEYS:
        query = query.is_(f"metadata->>{key}", "null")
    return query

def _drop_flagged(rows):
    out = []
    for row in rows or []:
        meta = row.get("metadata", {})
        if isinstance(meta, dict) and any(meta.get(k) for k in _PUBLIC_EXCLUDE_KEYS):
            continue
        out.append(row)
    return out
```

#### `.env.example` + `CLAUDE.md`

- `.env.example:20-39` — 7개 변수 추가 + 롤백 시나리오
- `CLAUDE.md:297-304` — 폴백 규약 5항 기재

---

## 4. 검증 결과 (Check)

### 4.1 Gap Analysis — 91% → 99%

**Analysis 문서**: `docs/03-analysis/llm-fallback-hardening.analysis.md`

#### 1차 분석 (91%)

| 갭 | 심각도 | 원인 | 영향 |
|---|:------:|------|------|
| **GAP-1** | High | 인용 교정 재시도 미차단(`max_retries=0` 미배선) | 단계 예산 60s 보증 불가(실제 122초 가능) |
| **GAP-2** | Medium | L6(`query_decomposer`/`self_rag`) 재시도 미배선 | SDK 기본 재시도 잔존(3s → 최대 9s) |
| **GAP-3** | High | 폴백 분기 테스트 미구현(Claude 예외 주입 경로 미검증) | 검증 없는 폴백 = 없는 폴백과 같음 |
| **GAP-4** | Medium | V4 배포 후 계측 양성 확인 미실행 | 프로덕션 GEMINI_API_KEY 갱신 확인 불완전 |
| **GAP-5~8** | Low | 미세 조치(deadline 선정규화·주석·문서 드리프트) | — |

#### Act-1 수정 (2026-08-06)

| 갭 | 조치 | 결과 | 검증 |
|----|------|------|------|
| **GAP-1** | `citation_validator.py:277`·`:398`에 `with_options(max_retries=0)` 배선 | **0.33초**(재시도 무시) vs 1.4초(기본 재시도) | 실측 확인 |
| **GAP-2** | `query_decomposer`/`self_rag`에 `CRITICAL_MAX_RETRIES` import + 배선 | 예산표와 코드 일치 | 회귀 테스트 통과 |
| **GAP-3** | 폴백 분기 테스트 3종 추가(`test_llm_fallback.py:273~289`) | Claude 예외 → OpenAI 충전 + INTENT_FALLBACK_ENABLED=false 강등 + 양쪽 실패 → fail-open | **14→17건 전부 통과**(CodeRabbit 반영 후 최종 20건) |
| **GAP-5** | `micro_polish` deadline 선정규화 | — | 테스트 통과 |
| **GAP-6** | `flatten_content` 분기 근거 주석 추가 | — | — |
| **GAP-8** | Plan NFR "무이벤트 ≤25초" 각주 추가 | 문서 드리프트 해소 | — |
| **GAP-4** | V4 **배포 후** 실행(계측 양성 확인) | 프로덕션 환경 의존 | 후행 항목 |

**최종 Match Rate: 24.75 / 25 = 99.0%**
- 잔여 0.25는 배포 의존 항목(GAP-4 V4 프로덕션 계측)

### 4.2 회귀 테스트 — 전부 통과

```
test_wage_golden.py        ✅  (계산 엔진 32건)
test_pipeline_wiring.py    ✅  (배선 검증 3건)
test_offline_units.py      ✅  (검색·인용·세션 다건)
test_abuse_guard.py        ✅  (남용 가드 20개 그룹 + 신규 회귀 가드 1건)
test_llm_fallback.py       ✅  (폴백 경화 20건, 최종)
test_answer_renderer.js    ✅  (프론트 8/0)
실파이프라인 정상 경로      ✅  (TTFT ~20.4초, 계산 결과 동일)
```

### 4.3 장애 주입 양성 검증 (FR-12 V1~V3)

| # | 주입 | 기대 | 실제 결과 |
|---|------|------|----------|
| **V1** | `ANTHROPIC_API_KEY` 무효화 | 의도분석 OpenAI 폴백 + 계산 실행 | ✅ **퇴직금 10,922,155원 정상** + `llm.fallback=true` 기록 |
| **V2** | `ANSWER_PROVIDER=gemini` | 3순위 Gemini 직접 실행 | ✅ **79자 정상**(8.5초, 404 죽었다면 불가능) — FR-08 복구 증명 |
| **V3** | `ANSWER_READ_TIMEOUT=0.1` | 3벤더 타임아웃 + 하트비트 + 명시적 error | ✅ **ping 2회 발행 + RuntimeError** |
| **V4** | 프로덕션 계측 양성 확인(`select metadata->'llm'...`) | `metadata.llm.provider` 실제 기록 | ⏳ **배포 후 수행**(Plan 오픈 항목) |

---

## 5. CodeRabbit 리뷰 발견 사항 (PR #33·#34)

### 5.1 PR #33 — LLM 폴백 경화 구현 (555ae12)

**1차 리뷰 — 12건 지적 (Major 7)**

실제 결함으로 확인되어 수정한 것:

| # | 지적 | 영향 | 수정 |
|----|------|------|------|
| 1 | 교정 공백 반환 → 성공 처리 → `replace` 이벤트로 완성된 답변 통째로 지움 | **Critical** | `citation_validator.py`에서 공백 체크 추가 |
| 2 | 의도분석 `tool_use` 없이 빈 응답 → `None` 반환 → OpenAI 폴백 미발동 | **Critical** | 공백 체크 + raise 추가 |
| 3 | 절단 후 면책 고지 그대로 저장 → 오도 | **Major** | 절단 고지를 면책 고지 **앞에** 붙여 순서 고정 |
| 4 | 교정 재시도 미차단 → 단계 예산 무력화 | **Major** | `with_options(max_retries=0)` 배선 |
| 5 | L6 재시도 미배선 vs config.py 주석 불일치 | **Major** | 배선 + 주석 일치 |
| 나머지 | 주석·타입힌트·로깅 세부 | Minor | 대부분 반영(2건은 근거 설명 후 미반영) |

**2차 리뷰 — 신규 2건 지적**

| # | 지적 | 원인 | 수정 |
|----|------|------|------|
| 1 | 고지 복원 로직(면책만 남은 경우) 절단 고지를 뒤에 붙여 순서 역전 | 절단 고지 추가 시 위치 실수 | 순서 정정: 절단 → 면책 순서 고정 |
| 2 | pipeline.py에서 `outcome.provider` 참조 전 선바인딩 확인 필요 | — | 선바인딩 확인 + 주석 강화 |

**3차 리뷰 — 신규 지적 0건** ✅

### 5.2 PR #34 — 부수 문서 정리 (ff37b28)

| 항목 | 내용 |
|------|------|
| 외부 유입 문서 제거 | `chatbot-security.plan.md`(SafeFactory 프로젝트 문서, 참조 경로가 이 저장소에 없음) 삭제. 미추적 파일이라 스크래치패드에 백업 후 제거 |
| 대기 계획서 추적 | `answer-at-a-glance.plan.md`(laborconsult 소속, Draft 상태로 미추적이던 문서)를 git에 신규 편입 — 이번 사이클과 무관한 별개 기능 |
| CodeRabbit 지적 | Minor 2건 중 1건 반영(코드 블록 언어 식별자), 1건은 근거 설명 후 미반영(문서 작성자 의도 확인 필요) |

### 5.3 결함 발견·수정 통계

**구현 품질 지표**
- 1차 리뷰 지적: 12건 (구현 시 미처 찾지 못한 결함 7건 포함)
- 실제 결함(not nitpick): 7건
- 수정 완료율: 100% (미반영 2건은 근거 설명)
- 3차 리뷰 신규 지적: 0건 (안정화)

**이것이 정상적 PDCA 순환**. 1차 설계에서 100% 완벽하게 구현하는 것은 불가능하고, 리뷰를 통해 발견되는 갭을 즉시 정정하는 것이 중요하다. 특히 기능이 특정 조건에서 무력화되는 버그(의도분석 폴백 미발동)를 리뷰가 잡아낸 것은 이 사이클의 목표인 "폴백이 죽어도 아무도 모른다"는 함정을 재현하지 않았다는 증거다.

---

## 6. 설계 결정 D1~D10 준수

| # | 결정 | 구현 | 근거 |
|---|------|:----:|------|
| D1 | Gemini 존치 + 모델 교체 | ✅ | `config.py:25` `gemini-pro-latest` |
| D2 | google-generativeai 유지 | ✅ | `requirements.txt` 무변경 |
| D3 | `max_retries=0` + 벤더 전환 | ✅ | `config.py:42`, `pipeline.py:311,337` |
| D4 | **2-튜플 규약 보존** | ✅ | `test_abuse_guard.py:547` 스텁 무변경 통과 |
| D5 | 폴백 모델 `gpt-4.1` | ✅ | `config.py:55` |
| D6 | 교정 타임아웃 동적 + 예산 | ✅ | `citation_validator.py:21-30`·`:33-37` |
| D7 | **절단 면책 고지 유지** | ✅ | `pipeline.py:1924-1932` 절단 여부 무관 부착 |
| D8 | 절단 인용 교정 수행 | ✅ | 교정 블록이 절단 분기 외부 |
| D9 | **metadata 재사용(스키마 0)** | ✅ | `pipeline.py:2010-2017` |
| D10 | **board_posts 필터 미적용** | ✅ | `api/index.py:1011~1033,1085~1094` |

---

## 7. 구현 규모 및 커버리지

### 7.1 변경 통계

실측 `git diff --stat`(병합 커밋 26321d6..555ae12, 코드·설정 파일 한정) 기준.

| 범주 | 파일 | 수정 유형 | 규모(+/-) |
|------|------|----------|------|
| **신설** | `app/core/llm_fallback.py` | 교차벤더 어댑터 | +98 |
| | `test_llm_fallback.py` | 오프라인 회귀(Do 14건 → Act-1 17건 → 최종 **20건**) | +627 |
| **수정** | `app/core/pipeline.py` | AnswerOutcome·폴백·절단·계측 | +252/−등 |
| | `app/core/analyzer.py` | 벤더중립 후처리·OpenAI 폴백 | +181/− |
| | `app/core/citation_validator.py` | 동적 타임아웃·단계 예산·배선 | +127/− |
| | `app/config.py` | 타임아웃·재시도 상수화 | +45/− |
| | `api/index.py` | 절단 게시판 제외 | +31/− |
| | `.env.example` | 7개 변수 + 롤백 문서화 | +24 |
| | `test_abuse_guard.py` | `board_posts` 필터 회귀 가드 + 배선 검사 갱신 | +22/− |
| | `CLAUDE.md` | 폴백 규약·문서 정정 | +14/− |
| | `app/core/query_decomposer.py` | L6 재시도 배선(GAP-2) | +9/− |
| | `app/core/self_rag.py` | L6 재시도 배선(GAP-2) | +9/− |
| | `.github/workflows/tests.yml` | 신규 스위트 등록 | +5/− |
| | `app/models/schemas.py` | `intent_provider` 필드(계측) | +3 |

**합계**: **14개 신설/수정 파일, 1,309줄 추가 / 138줄 삭제**(PR #33 병합 기준) + 5개 기존 스위트 회귀 확인

### 7.2 기능 커버리지

| 요구사항 | 커버 | 근거 |
|---------|:----:|------|
| FR-01~04 | 100% | T1~T6 + V1~V3 검증 |
| FR-05~09 | 100% | T8 + V1 폴백 성공 |
| FR-10 | 100% | `_llm_meta` 계측 기록 + 구조화 로그 |
| FR-11 | 100% | `test_llm_fallback.py` 20건(최종) |
| FR-12 | 75% | V1~V3 완료, V4 배포 후 |
| FR-13 | 100% | 문서 정합 완료 |

---

## 8. 정상 경로 회귀 (무회귀 검증)

### 8.1 기존 오프라인 스위트

```
test_wage_golden.py      ✅ (32건 모두 통과)
test_pipeline_wiring.py  ✅ (CALC-1,2,3 3건)
test_offline_units.py    ✅ (검색·인용·세션)
test_abuse_guard.py      ✅ (20개 그룹 + 신규 guard_flag 회귀 1건)
```

### 8.2 실파이프라인 정상 경로 (설계 P1)

**조건**: Anthropic 정상, 모든 폴백 미발동

```
입력: "퇴직 급여 계산법을 알려줘"
의도: requires_calculation=True, calculation_types=['severance'], is_labor_related=True
처리:
  - 답변 제공자: Claude (1순위 성공)
  - 계산기 실행: severance calculator
  - 결과: 10,922,155원(기본 31개월 × 연 평균임금)
  - TTFT: ~20.4초(변경 전과 동일 수준)
  - metadata.llm: {"provider": "Claude", "attempts": ["Claude"]}

결론: ✅ 정상 경로 지연 증가 없음(무회귀)
```

---

## 9. PR & 커밋 이력

### 9.1 PR #33 — llm-fallback-hardening 본체

**링크**: `https://github.com/DrunkenZealnut/laborconsult/pull/33`
**병합 커밋**: `555ae12`
**작성 일시**: 2026-08-06
**리뷰**: CodeRabbit 3차(신규 지적 0건에서 병합)

**주요 변경**
- `app/core/llm_fallback.py` 신설
- `app/core/pipeline.py` AnswerOutcome 재구성
- `app/core/analyzer.py` OpenAI 폴백 분기
- `app/core/citation_validator.py` 타임아웃 정합
- `test_llm_fallback.py` 신설(14 → 17 → **최종 20건**)
- 기타 5개 파일 부수 수정

### 9.2 PR #34 — 부수 문서·정리

**링크**: `https://github.com/DrunkenZealnut/laborconsult/pull/34`
**병합 커밋**: `ff37b28`
**작성 일시**: 2026-08-06
**리뷰**: CodeRabbit 사소 1건 반영

**주요 변경**
- SafeFactory 외부 유입 문서(`chatbot-security.plan.md`) 제거
- `answer-at-a-glance.plan.md`(별개 기능, Draft) git 추적 편입
- CodeRabbit Minor 지적 1건 반영

---

## 10. 배포 전 체크리스트

- [x] **코드 변경**: Plan(v0.2)·Design(v0.1) 대비 99% 일치
- [x] **리뷰 통과**: CodeRabbit 3차 리뷰(신규 지적 0건)
- [x] **테스트 통과**: 신규 20건 + 기존 5스위트 회귀 무
- [x] **장애 주입 검증**: V1(의도분석 폴백), V2(Gemini), V3(타임아웃) 3건 완료
- [x] **문서 정합**: CLAUDE.md·.env.example 갱신
- [ ] **V4 프로덕션 계측**: 배포 후 수행 — 배포 차단 조건 아님

---

## 11. 후속 과제 (범위 밖)

| # | 과제 | 심각도 | 시기 |
|----|------|:------:|------|
| **GAP-4-V4** | 프로덕션 계측 양성 확인(`metadata.llm.provider` 기록 확인) | Medium | 배포 후 1일 내 |
| **GAP-7** | CLI(`chatbot.py::generate_answer`) 폴백 통합 — 단일 Claude만 사용 중 | Low | 별도 사이클 |
| **FR-08·V2** | Gemini API 키 갱신(로컬·Vercel) 확인 — 사용자 확인 완료 | Low | 운영 |
| **L6·L8 SDK 기본 재시도** | 모니터링(GAP-2 배선 후에도 남아있을 수 있는 다른 호출부) | Low | 모니터링 |
| **answer-at-a-glance** | 이번 PR #34로 git 추적에 편입됐으나 이 사이클과 무관한 별개 기능(Draft, design 이전 단계) | — | 별도 `/pdca design` |

---

## 12. 최종 결론

### 12.1 성과

1. **조용한 실패 근절** — 빈 응답·절단·전환 지연을 명시적으로 처리 + 게시판 격리
2. **벤더 단일 장애점 해소** — 의도분석 교차벤더 폴백 + 3순위 복구(404 사망 해결)
3. **신뢰성 기반 구축** — 폴백 계측 + 오프라인 회귀 테스트로 "죽은 폴백" 재발 방지
4. **설계 원칙 준수** — 정상 경로 무회귀(TTFT ~20초 유지) + fail-open 불변
5. **코드 품질** — CodeRabbit 3차 리뷰 안정화 + 기존 5스위트 회귀 무

### 12.2 수치

- **Match Rate**: 99.0% (배포 의존 항목 1건 제외)
- **구현 규모**: 14개 파일, 1,309줄 추가 / 138줄 삭제(PR #33 병합 기준, §7.1)
- **테스트 커버**: 신규 20건 + 기존 5스위트 회귀 무
- **장애 주입 검증**: 3건 완료, 1건 배포 후
- **정상 경로 TTFT**: 20.4초(기존 동일, 무회귀)

### 12.3 위험도

**매우 낮음**
- 핵심 변경(FR-01~03)은 실패 경로에만 분기
- 정상 경로는 테스트·수동 검증 모두 무회귀
- 폴백 코드는 자동 회귀 테스트(T1~T8) + 수동 장애 주입(V1~V3) 이중 검증
- 설계 원칙 P4(호출 규약 보존) + D10(`board_posts` 필터 미적용) 양쪽 회귀 확인

### 12.4 배포 권고

**준비 완료** — 즉시 배포 가능

- 1차 구현 후 CodeRabbit 리뷰로 7건 실제 결함 발견·수정 완료(2차 리뷰 2건 포함)
- Act-1 갭 수정 후 Match Rate 91% → 99%
- 기존 오프라인 스위트 5종 + 렌더러 테스트 전부 회귀 없음
- 배포 후 V4 계측 양성 확인만 남음

---

## Appendix

### 설계 문서

- **Plan**: `docs/01-plan/features/llm-fallback-hardening.plan.md` (v0.2)
- **Design**: `docs/02-design/features/llm-fallback-hardening.design.md` (v0.1)
- **Analysis**: `docs/03-analysis/llm-fallback-hardening.analysis.md` (91% → 99%)

### 구현 코드

- **신규**: `app/core/llm_fallback.py`·`test_llm_fallback.py`
- **수정**: `app/config.py`·`app/core/pipeline.py`·`app/core/analyzer.py`·`app/core/citation_validator.py`·`app/core/query_decomposer.py`·`app/core/self_rag.py`·`app/models/schemas.py`·`api/index.py`·`.env.example`·`CLAUDE.md`·`.github/workflows/tests.yml`·`test_abuse_guard.py`

### 참고 자료

- **타임아웃 예산표**: Design §3.4 (최악 237초 < 300초)
- **장애 시나리오**: Plan §3.1 (F1~F7)
- **FR 상세**: Plan §3.2 (13종)
- **테스트 매트릭스**: Design T1~T8(8종) + Do 단계 보강 6종 + GAP-3 대응 3종 + CodeRabbit 반영 3종 = 최종 20종

---

**작성 일시**: 2026-08-06
**작성자**: DrunkenZealnut
**상태**: 배포 대기 중

